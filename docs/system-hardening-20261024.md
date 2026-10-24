# 系统加固与两处误判更正（2026-10-24）

## 一、模块防覆盖：`pja110-kernel-mods` 包

### 1.1 问题

我们修改过的内核模块此前是**手工 `cp` 进 `/lib/modules/`** 的，不属于任何 Debian 包：

```
$ dpkg -S /lib/modules/6.14.0-oneplus-PJA110/kernel/drivers/power/supply/qcom_battmgr.ko
dpkg-query: no path found matching pattern ...
```

后果：任何后续安装内核模块包的操作都可以**静默覆盖**这些文件，快充、Wi-Fi、触摸会一起失效，且事后无从追溯文件来源。

### 1.2 解决

把 5 个修改过的模块和 2 个配置文件打成正式 Debian 包：

| 内容 | 作用 |
| --- | --- |
| `qcom_battmgr.ko` | 充电电流控制（快充）+ 抑制 ADSP 占位电池 |
| `ath12k.ko` | WCN7850 rfkill 引脚覆盖 |
| `snd-q6apm.ko` | 音频 DSP debugfs 辅助 |
| `qcom_hv_haptics_probe.ko` | PMIC 振动探测 |
| `synaptics-aston.ko` | S3910 触摸屏（树外模块） |
| `/etc/modules-load.d/pja110.conf` | 模块自动加载顺序 |
| `/etc/modprobe.d/pja110-battmgr.conf` | `ignore_battery=1` |

产物：`out/pkg/pja110-kernel-mods_6.14.0-oneplus-PJA110-1_arm64.deb`（1007 KB，sha256 `eb9edb91...`）

### 1.3 包定义要点

```
Package: pja110-kernel-mods
Version: 6.14.0-oneplus-PJA110-1     ← 版本号跟随内核 release
Architecture: arm64
Depends: kmod
```

`postinst` 执行 `depmod -a 6.14.0-oneplus-PJA110`，安装后模块依赖立刻可用。

两个 `/etc` 下的配置标记为 `conffiles`，升级时保留本地修改。

### 1.4 验证结果

```
$ dpkg -l pja110-kernel-mods
ii  pja110-kernel-mods  6.14.0-oneplus-PJA110-1  arm64

$ dpkg -S /lib/modules/6.14.0-oneplus-PJA110/kernel/drivers/power/supply/qcom_battmgr.ko
pja110-kernel-mods: /lib/modules/.../qcom_battmgr.ko

$ dpkg --verify pja110-kernel-mods
（无输出 = 文件与包记录一致）
```

功能回归：Wi-Fi 已连、ADSP running、单块电池、快充 active、触摸存在、`ignore_battery=Y`。

### 1.5 重新打包

改了任何一个模块后：

```sh
# 1. 把新模块放到暂存树
STAGE=/tmp/pkg-pja110
cp <new.ko> $STAGE/lib/modules/6.14.0-oneplus-PJA110/kernel/...

# 2. 提升版本号（改 DEBIAN/control 的 Version）
# 3. 重新构建
dpkg-deb --root-owner-group -b $STAGE out/pkg/pja110-kernel-mods_<ver>_arm64.deb

# 4. 安装
scp out/pkg/*.deb <device>:/tmp/ && ssh <device> 'sudo dpkg -i /tmp/*.deb'
```

---

## 二、误判更正 1：`wpa_supplicant.service` **不能**禁用

### 2.1 我之前的错误结论

审计时看到"三个网络组件都在运行"，判断为冲突，建议 disable `wpa_supplicant.service`。

**这是错的。** 如果真的执行，会直接断网。

### 2.2 实际情况

```
$ sudo ls /run/wpa_supplicant/
srwxrwx---  wlp1s0              ← 系统 wpa_supplicant 正在控制这块网卡
srwxrwx---  p2p-dev-wlp1s0

$ sudo busctl list | grep wpa
fi.w1.wpa_supplicant1   552  wpa_supplicant.service

$ ps -ef | grep [w]pa_supplicant
root  552  1  /usr/sbin/wpa_supplicant -u -s -O DIR=/run/wpa_supplicant GROUP=netdev
```

只有 **1 个** wpa_supplicant 进程，由 `wpa_supplicant.service` 管理（`Type=dbus`，`BusName=fi.w1.wpa_supplicant1`）。

**NetworkManager 通过 D-Bus 使用这个系统实例**，而不是自己 fork 一个（`/run/NetworkManager/` 下没有任何 supplicant 配置）。

这是正确的集成方式，不是冲突。

### 2.3 三方组件的真实分工

| 组件 | 实际职责 | 处置 |
| --- | --- | --- |
| `NetworkManager` | 管理 `wlp1s0` 连接、DHCP、路由 | **保留** |
| `wpa_supplicant.service` | 提供 WPA 认证（被 NM 通过 D-Bus 调用） | **保留，不能禁用** |
| `systemd-networkd` | 什么都不管（所有接口 `unmanaged`，`/etc/systemd/network/` 为空） | 空转，无害；想精简可禁用 |

验证 `systemd-networkd` 确实空转：

```
$ networkctl list
1 lo     loopback carrier  unmanaged
2 wlp1s0 wlan     routable unmanaged
3 usb0   gadget   routable unmanaged
```

---

## 三、误判更正 2：关机后自动开机是 **USB 供电**导致

### 3.1 现象

用户报告：关机后设备会自动启动进系统，怀疑关机没生效。

### 3.2 实测结论

**拔掉 USB 数据线后关机，正常保持关闭。**

原因：Android 手机的 bootloader（ABL）有"检测到充电器插入就自动开机"的标准行为。原厂系统会进入"关机充电"界面（只显示电池图标），但这台机器的 A 槽是我们的 Linux，没有那个界面，ABL 直接引导系统。

### 3.3 这是软件层改不了的

行为在闭源的 ABL 里。USB 供电时无法真正保持关机。

实用建议：需要长时间关机就拔掉线；平时接着线反而是优点（不会把电池放空）。

### 3.4 辅助改进：journald 持久化

排查期间发现日志只在内存（`/run/log/journal`），重启后丢失，无法分析关机原因。已启用持久化：

```sh
sudo mkdir -p /var/log/journal
sudo systemd-tmpfiles --create --prefix /var/log/journal
sudo systemctl restart systemd-journald
```

现在 `/var/log/journal/<machine-id>/` 会保留历史启动记录，`journalctl --list-boots` 可以回看每次关机的最后日志。

判断关机是否正常的依据：

```sh
journalctl -b -1 | grep -iE "Powering off|reboot: Power down"
```

有记录 = 内核正常关机，之后是 bootloader 自己开机的；
无记录 = 内核那一步没走完（需要查 PSCI/PMIC poweroff）。

---

## 四、清理 Ubuntu Touch / Lomiri 残留

### 4.1 问题

系统里有 **3 个设置应用**，其中一个是 Ubuntu Touch 时代的残留：

| 应用名 | 实际包 | 状态 |
| --- | --- | --- |
| Settings | `gnome-control-center` | 保留 |
| Mobile Settings | `phosh-mobile-settings` | 保留 |
| **System Settings** | `lomiri-system-settings` | **删除** |

### 4.2 删除前的风险检查

先做删除模拟，确认不波及核心组件：

```
$ apt-get -s remove --purge <lomiri 包>
55 to remove
✅ 未波及 Phosh / phoc / gnome-control-center / NetworkManager / greetd
```

连带删除的非 lomiri 包：`ayatana-indicator-datetime`、`ayatana-indicator-power`、
`hfd-service`、`qtmir`、`libqtmirserver2`、`qml-module-qtmir`、`qml-module-hfd`、
`libmiroil3t64`、`libcontent-hub1`、`libdeviceinfo0`、`suru-icon-theme` 等。

### 4.3 关键预防：先保护被误标为 auto 的重要包

模拟时发现一批**必需包被标记为 `auto`**，一旦将来跑 `apt autoremove` 会被误删：

```
bluez  blueman  fonts-noto  fonts-noto-color-emoji
gstreamer1.0-plugins-good  gstreamer1.0-x  maliit-keyboard
libglib2.0-bin  dconf-cli  libnice10  libqt5*（若干）
```

删除前先固定为手动安装：

```sh
sudo apt-mark manual bluez blueman bluez-obexd \
  fonts-noto fonts-noto-color-emoji \
  gstreamer1.0-plugins-good gstreamer1.0-x \
  maliit-keyboard libglib2.0-bin dconf-cli libnice10 \
  libqt5core5t64 libqt5gui5t64 libqt5waylandclient5 libqt5dbus5t64 \
  libqt5network5t64 libqt5qml5 libqt5quick5
```

备份包清单以便回滚：

```sh
sudo dpkg --get-selections > /root/pkgs-before-lomiri-removal.txt
```

### 4.4 执行

```sh
PKGS=$(dpkg -l | grep -i lomiri | awk '{print $2}' | tr '\n' ' ')
sudo apt-get remove --purge -y $PKGS
```

**不要加 `--auto-remove`**，避免连带删掉过多东西。

### 4.5 附带清理的废弃单元与文件

| 项 | 原因 |
| --- | --- |
| `/etc/systemd/system/ut-lomiri.service` | 指向已删除的 `lomiri` 二进制 |
| `/etc/systemd/system/ut-phosh.service` | greetd 之前的旧启动方式 |
| `/etc/systemd/system/ut-probe.service` | 只写一个标记文件，无用途 |
| `/etc/deviceinfo/` | Ubuntu Touch 设备描述，libdeviceinfo 已删除 |
| `/usr/bin/lomiri-session` | 无主文件（原包已删） |
| `/usr/lib/systemd/user/lomiri-session.service` | 无主文件 |

保留（当前调试通道，交付前需处理）：

| 项 | 说明 |
| --- | --- |
| `ut-usb-ncm.service` | USB NCM 网卡，SSH 调试依赖它 |
| `ut-shell.service` | **无认证的 root telnet shell（端口 23）—— 交付镜像必须禁用** |

### 4.6 结果

```
包数量:      1018 → 965   （删除 53 个）
lomiri 包:   43 → 0
磁盘占用:    5562 MB → 5409 MB
系统状态:    running，失败服务 0
Wi-Fi:       wlp1s0 connected
蓝牙:        active（控制器 02:00:00:00:5A:AD pja110）
快充:        active
模块包:      pja110-kernel-mods 6.14.0-oneplus-PJA110-1
外观变化:    菜单里的 "System Settings" 已消失
```

### 4.7 仍可进一步清理（未执行）

`sudo apt-get autoremove --purge` 还能再删 **121 个包**：

- `ayatana-indicator-*`（7 个，全部 inactive 且无 unit）
- Qt5 库、Mate 库、`click`/`libclick`、`liblightdm-*`、`libprotobuf` 等
- ⚠️ 会连带删除 `network-manager-openvpn`（想保留 VPN 支持需先 `apt-mark manual`）

已确认该操作**不会**动到受保护的关键包。

---

## 五、深度清理：`autoremove` 111 个包（2026-10-24）

### 5.1 保留清单（先固定为 manual）

`apt autoremove` 不会删被 manual 包依赖的东西，所以只需保护"脚本会用到但
没有依赖关系"的工具：

```sh
sudo apt-mark manual zstd zenity zenity-common sqlite3 gettext
```

| 包 | 为什么保留 |
| --- | --- |
| `zstd` | 固件解压（`board-2.bin.zst` 等）|
| `zenity` / `zenity-common` | 脚本/GUI 弹窗 |
| `sqlite3` | 通用工具 |
| `gettext` | 通用工具 |

**VPN 按需求一并删除**：`network-manager-openvpn` + `openvpn` 未保留。

### 5.2 删除前精确校验

逐个比对删除列表与关键包名单，确认全部安全：

```
✅ bluez / bluez-obexd / bluetooth     安全
✅ network-manager / phosh / phoc      安全
✅ gnome-control-center / greetd       安全
✅ maliit-keyboard / fonts-noto        安全
✅ gstreamer1.0-plugins-good           安全
✅ zstd / zenity / libglib2.0-bin      安全
```

### 5.3 执行

```sh
sudo dpkg --get-selections > /root/pkgs-before-deep-clean.txt
sudo apt-get autoremove --purge -y
sudo apt-get clean            # apt 缓存 1.1 GB → 76 KB
sudo rm -rf /var/lib/urfkill /var/lib/clickpkg
```

删除内容全部是 UT/Mate/Qt5 时代的无用组件：
`ayatana-indicator-*`、`mate-*`、`click`/`libclick`、`telepathy-*`、
`libqt5*`（Phosh 是 GTK，不依赖 Qt）、`libprotobuf`/`libabsl`、
`liblightdm-*`、`urfkill`、`zeitgeist`、`usermetricsservice` 等。

### 5.4 结果

| 指标 | 清理前 | 清理后 |
| --- | --- | --- |
| 包数量 | 965 | **854** |
| 磁盘占用 | 5409 MB | **4279 MB** |
| apt 缓存 | 1.1 GB | 76 KB |
| 损坏包 | 0 | 0 |

### 5.5 重启后回归验证

```
启动:     5.046s（kernel 1.662s + userspace 3.384s），桌面 3.356s
系统:     running，失败服务 0
图形:     phoc 1 / phosh 2
Wi-Fi:    wlp1s0 connected (HKUSTGZ)
蓝牙:     active，Controller 02:00:00:00:5A:AD pja110
快充:     active，开机写入 op=0x31 prop=10 val=3000000 rc=-110
ADSP:     remoteproc0 running
触摸:     Synaptics S3910 在位
电池:     bq28z610-0 60%
刷新率:   120 Hz
依赖:     apt check 通过，损坏包 0
动态库:   g-c-c / phosh-mobile-settings / phoc / phosh 均无缺失库
```

---

## 六、GUI 应用清点与精简（2026-10-24）

### 6.1 清点结果：真正可用的 GUI 应用只有 4 个

| 应用 | 可执行文件 | 所属包 |
| --- | --- | --- |
| Settings | `gnome-control-center` | gnome-control-center |
| Mobile Settings | `phosh-mobile-settings` | phosh-mobile-settings |
| Bluetooth Manager | `blueman-manager` | blueman |
| Bluetooth Adapters | `blueman-adapters` | blueman |
| Language Support | `gnome-language-selector` | language-selector-gnome |

**缺失**：没有任何图形终端。

### 6.2 发现的三个问题

| 问题 | 体积 | 状态 |
| --- | --- | --- |
| 无终端模拟器 | — | 功能性缺口 |
| `maliit-keyboard` + Qt5 全套 | **约 160 MB** | 未使用（Phosh 实际用 `phosh-osk-stub`）|
| Mir 残留（`mir-demos` + 6 个 platform 包）| 2.4 MB | UT 时代残留，未运行 |

关于 `maliit-keyboard`：它是 **Qt** 虚拟键盘，把整个 Qt5 运行时（49.3 MB）
和 8 个 `qml-module-qtquick*` 一起拖了进来。实际提供输入法的是：

```
$ pgrep -a -f osk
1131 /usr/bin/phosh-osk-stub --allow-replacement
```

### 6.3 处理

**1. 安装终端**：

```sh
sudo apt-get install -y kgx
```

`kgx` 是 GNOME Console（VTE 0.76），GTK4/libadwaita，在应用列表里显示为 **Console**。

**2. 删除 Mir 残留**：

```sh
sudo apt-get remove --purge -y mir-demos mir-platform-*
```

**3. 删除 maliit + Qt5**（需先取消此前的 manual 保护）：

```sh
sudo apt-mark auto maliit-keyboard maliit-framework libmaliit-plugins2 \
  libqt5core5t64 libqt5gui5t64 libqt5waylandclient5 libqt5dbus5t64 \
  libqt5network5t64 libqt5qml5 libqt5quick5
sudo apt-get remove  --purge -y maliit-keyboard maliit-framework libmaliit-plugins2
sudo apt-get autoremove --purge -y
```

连带清掉的还有 Mir 的库（`libmiral5t64`、`libmirserver58t64` 等）、
`libpinyin`、`libchewing`、`libboost-*`、`qttranslations5-l10n` 等。

### 6.4 结果

| 指标 | 清理前 | 清理后 |
| --- | --- | --- |
| 包数量 | 854 | **794** |
| 磁盘占用 | 4279 MB | **4026 MB** |
| Qt5 包 | 17 | **0** |
| qml-qt 包 | 7 | **0** |
| maliit 包 | 3 | **0** |

### 6.5 重启后回归

```
启动:     4.807s（kernel 1.266 + userspace 3.540），桌面 3.132s
系统:     running，失败服务 0
图形:     phoc 1 / phosh 2
Wi-Fi:    wlp1s0 connected
蓝牙:     active
快充:     active
ADSP:     running
触摸:     Synaptics S3910
终端:     kgx 46.0 (VTE 0.76)
依赖:     损坏包 0，关键程序无缺失库
```

### 6.6 应用列表最终状态

| 条目 | 可执行文件 | 说明 |
| --- | --- | --- |
| Settings | `gnome-control-center` | |
| Mobile Settings | `phosh-mobile-settings` | |
| Bluetooth Manager | `blueman-manager` | |
| Bluetooth Adapters | `blueman-adapters` | |
| Language Support | `gnome-language-selector` | |
| **Console** | `kgx` | ← 本次新增 |
| Vim | `vim` | CLI 工具，桌面条目为附带 |
| TeXInfo | `info` | CLI 工具，桌面条目为附带 |

Vim / TeXInfo 是 `vim-common` 和 `info` 包自带的桌面条目，
点开只会得到提示页。想从应用列表隐藏可在
`/usr/local/share/applications/` 放同名 `NoDisplay=true` 覆盖文件（未执行）。

---

## 七、空闲挂起：服务器用途必须关闭（2026-10-24）

### 7.1 现象

SSH 会不定时连不上：ping 通、TCP 能连上，但 SSH 卡在 banner 交换阶段。
其中一次经端口 23 的 root shell 确认 **sshd 与用户态完全正常**，
那次真正原因是负载尖峰；但排查过程中发现了更根本的隐患。

### 7.2 根因

`gsd-power`（GNOME 电源管理守护进程）默认让系统在空闲 15 分钟后挂起：

```
$ gsettings get org.gnome.settings-daemon.plugins.power sleep-inactive-ac-timeout
900
$ gsettings get org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type
'suspend'
$ gsettings get org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type
'suspend'
```

内核支持挂起：

```
$ cat /sys/power/state
freeze mem
$ cat /sys/power/mem_sleep
s2idle [deep]
```

对一台要当**迷你服务器**的设备，自动挂起意味着随时掉线。

### 7.3 修改

接电（AC）状态下永不挂起：

```sh
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-ac-type 'nothing'
```

电池状态**保留 suspend**（拔电时省电是合理的）。如果希望拔电也不挂起：

```sh
gsettings set org.gnome.settings-daemon.plugins.power sleep-inactive-battery-type 'nothing'
```

### 7.4 验证

```
sleep-inactive-ac-timeout        900
sleep-inactive-ac-type           'nothing'    ← 接电不挂起
sleep-inactive-battery-timeout   900
sleep-inactive-battery-type      'suspend'    ← 电池仍省电
USB online                       1            ← 当前在接电状态
```

### 7.5 另一个已排除的疑点

排查时 `uptime` 显示 `load average: 4.67`，但 `ps` 里没有任何进程吃 CPU。
原因是连续执行了多条重负载命令（`apt-mark auto` 接 352 个参数、
多次 `apt-get -s autoremove` 模拟、多个并行 SSH 会话）造成的瞬时尖峰。
后续操作不要并发即可。

> `pgrep` 陷阱：`pgrep -a "apt|dpkg"` 会匹配到
> `[irq/213-syn**apt**ics_tcm_hbp]`（触摸屏中断线程），因为 "apt" 是
> "synaptics" 的子串。判断是否有 apt 在跑要用 `pgrep -x apt` / `pgrep -x dpkg`。

---

## 八、当前系统状态

```
内核:       6.14.0-oneplus-PJA110
模块包:     pja110-kernel-mods 6.14.0-oneplus-PJA110-2 (已安装)
包数量:     810（已清理 UT/Lomiri/Mate/Qt5/Mir 遗留 + 构建依赖）
磁盘:       4081 MB 已用 / 432 GB 可用
启动:       4.7s（桌面 3.4s）
设备树:     model = "OnePlus PJA110"，compatible = oneplus,pja110 / qcom,sm8550
chassis:    handset
Wi-Fi:      wlp1s0 connected (HKUSTGZ)
蓝牙:       active
刷新率:     60/120 可在 Settings 切换（内核 mode-aware）
电池:       单块 bq28z610-0（ADSP 占位电池已抑制）
快充:       fastcharge.service active，1.19s，带 last_set 校验
ADSP:       remoteproc0 running
触摸:       PJA110 Synaptics S3910
终端:       Console (kgx 46.0)
设置应用:   Settings（已补 SoC 名称）+ Mobile Settings
虚拟键盘:   stevia 0.38.0-1pja1102，占屏高 35%（可调）
udisks2:    active（Disk Capacity 显示 507.1 GB）
/srv:       /dev/sda6 15G（sda6 回收而来）
挂起:       接电时不挂起（sleep-inactive-ac-type = nothing）
编译能力:   已无（gcc/g++/make/dpkg-dev 已移除）
关机:       拔 USB 后正常（USB 供电时会被 bootloader 自动开机）
```
