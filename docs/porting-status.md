# PJA110 主线 Linux 移植总览（Ubuntu + Phosh）

更新：2026-10-23。目标系统：**Ubuntu 24.04.3 LTS + Phosh 0.38（mainline 内核）**。

本文是项目现状的唯一总览。历史内容（postmarketOS/Nura 线、Ubuntu Touch + Lomiri 探索）已归档到 `docs/archive/`，不再代表当前状态。

## 1. 当前结论

- **设备已可作为一台可用的 Linux 手机运行**：能启动、有图形界面、支持触摸、Wi-Fi、电源键与音量键。
- **桌面栈选定 Phosh/Phoc**，放弃 Lomiri/Mir。原因：Mir 2.14 硬依赖已被 Mesa 25 移除的 `EGL_WL_bind_wayland_display`，导致回退软件缓冲（约 3 FPS）；Phoc 基于 wlroots，直接走 GBM/dmabuf，硬件加速正常。
- Ubuntu Touch 在 noble 上不具备可行性：UBports 官方仓库只有 `focal`，`repo.ubports.com/dists/noble/` 返回 404。
- 硬件层（内核、DTB、面板、触控、电池、Wi-Fi）完全复用 pmOS 线成果，本次未改内核。

## 2. 硬件与软件基线

| 项 | 值 |
| --- | --- |
| 手机 | PJA110（PJA110，xigua，OPPO project 22851） |
| SoC / 架构 | Snapdragon 8 Gen 2 / SM8550，aarch64；16 GB RAM |
| 内核 | 6.14.0-oneplus-xigua（本地补丁版，未修改） |
| 面板 | AA536_P_3_A0001，1240×2772，DSC 620×44，120 Hz 已启用 |
| 显示桥 | Pixelworks Iris7，旁路 |
| 触控 | Synaptics S3910（Aston TCM），`/dev/input/event3`，240 Hz |
| GPU | Adreno 740，msm + Mesa 25.2.8 freedreno FD740 |
| Wi-Fi | WCN7850 hw2.0，PCIe 17cb:1107，ath12k，接口 `wlp1s0` |
| 电量计 / ADC | bq28z610（0x55）；qcom_battmgr 单电池补丁；spmi-adc5-gen3 |
| 用户态 | Ubuntu 24.04.3 LTS，888 个包 |
| 桌面 | Phosh 0.38.0 / Phoc 0.38.0 / phosh-osk-stub 0.38.0 |
| 登录管理 | greetd 0.9.0（`initial_session` 自动登录） |

## 3. 存储与启动链

物理盘：SAMSUNG KLUFG8RHHD-B0G1，507.1 GB，UFS 分 **6 个 LUN**
（`/dev/sda`…`/dev/sdf`）。完整分区表见 [磁盘分区布局](disk-layout-20261024.md)。

```
/dev/sda14   456.9 GiB  ext4  LABEL=ut-root  UUID=8c04e46c-…   → /
/dev/sda6     15.0 GiB  ext4  LABEL=pja110-spare               → /srv（辅助卷）
sde13 boot_a          内核镜像 + cmdline
sde24 vendor_boot_a   迷你 initramfs（约 1.2 MB，含 GPU 固件）+ 基准 DTB
sde17 dtbo_a          24 MB DTBO 镜像（4 个 selector DTB）← 实际生效的 model/compatible
sde32 init_boot_a     空 cpio
```

启动顺序：`ABL → boot_a → vendor_boot_a(initramfs) → dtbo_a(overlay) → 挂载 /dev/sda14 → switch_root`

**注意**：`dtbo_a` 的 overlay 会覆盖基准 DTB 的 `model` 和 `compatible`。
只改 `vendor_boot_a` 里的 DTB 不生效，必须改 `dtbo_a`
（见 [设备树 model 修正](dtbo-model-fix-20261024.md)）。

启动命令行的关键部分：

```
root=UUID=8c04e46c-5d09-42c5-bccf-5e20d49a17ff rootwait rw console=tty0 loglevel=4
panel_oneplus_aa536.refresh=120
```

引导程序传的是 `root=UUID=…`，但**我们的迷你 initramfs 硬编码 `/dev/sda14`**
（`ut-initramfs-init.sh` 里 `ROOT_DEV=/dev/sda14`），不依赖 UUID 解析。
`/etc/fstab` 用 UUID；此前 `sda6` 与 `sda14` UUID 相同曾导致 by-uuid 指向错误，
已于 2026-10-24 修复（`sda6` 换新 UUID）。

## 4. 已实现功能

| 功能 | 状态 | 关键实现 |
| --- | --- | --- |
| 启动到图形界面 | ✅ | greetd `initial_session` → `phosh-session` |
| 显示 120 Hz | ✅ | `panel_oneplus_aa536.refresh=120`；KMS `fb: XR24 1240x2772` |
| GPU 硬件加速 | ✅ | freedreno FD740，GLES 3.2；固件在 initramfs 内 |
| 触摸 240 Hz | ✅ | `synaptics-aston` + `report_rate_code=3` |
| 软键盘 | ✅ | `phosh-osk-stub` 自动启动 |
| Wi-Fi | ✅ | ath12k + **NetworkManager**（自动连接、DHCP、默认路由、重启保持） |
| 电源键（关屏/唤醒） | ✅ | greetd 建立 logind 会话 → `gsd-power` 生效 |
| 音量键 | ✅ | `pmic_resin`=VOLUMEUP、`gpio-keys`=VOLUMEDOWN |
| 蓝牙 | ✅ | qcom,wcn7850-bt + local-bd-address；luetoothctl scan 可发现周边设备 |
| 免密调试通道 | ✅ | USB NCM `172.16.42.1` + TCP 23 root shell |

## 5. 未实现功能

| 功能 | 状态 | 阻塞点 |
| --- | --- | --- |
| **音频** | ⚠️ | 硬件层全部打通（WCD938x 声卡/245 mixer 控件/slave 全 Attached）；卡在 DSP 音频框架不匹配（原厂 AMDB vs mainline APM），见 [音频记录](audio-sm8550-status.md) |
| **蓝牙** | ✅ | 固件、HCI、扫描全部正常；关键改动仅为 DT 加 local-bd-address（见 [蓝牙记录](bluetooth-wcn7850-status.md)） |
| 相机 / 指纹 / NFC / IMU | ❌ | 未开始 |
| 基带 / 通话 / 移动数据 / GNSS | ❌ | 未开始 |
| 渲染性能定量 | ⚠️ | 120 Hz 面板已确认；实际合成帧率未可靠测量 |
| Release 镜像 | ❌ | 见 §8 |

## 6. 音频可行性（已实施，未出声）

**结论：Linux 侧已全部打通 —— 声卡创建、245 个 mixer 控件、两个 WCD938x SoundWire slave 均 Attached。唯一阻塞在 DSP：OnePlus 固件的音频入口是 AMDB（GPR port 3），而 mainline 实现的是 APM（port 1），两套 DSP 音频框架不通用。详见 [音频移植记录](audio-sm8550-status.md) §8.14。**

已修正的两个早期误判：(1) 曾判断「音频需重编内核」，实际 SND_SOC_WSA884X/SND_SOC_WCD938X 早已编译并分发；(2) 曾判断「只缺 DTB 节点」，实际还需 topology 固件文件与手动 mixer 路由。

原本判断「只需 DTB」是基于 `snd-soc-sc8280xp.ko` 的 alias 含 `of:N*T*Cqcom,sm8550-sndcard`。但进一步核对发现：

- machine driver ✅ 在（`snd-soc-sc8280xp.ko` 支持 `qcom,sm8550-sndcard`）；
- LPASS 宏 ✅ 在（`snd-soc-lpass-{wsa,rx,tx,va}-macro.ko`）；
- DSP 后端 ✅ 在（`snd-q6apm.ko`、`q6apm-dai.ko`）；
- SoundWire 总线 ✅ 在（`soundwire-qcom.ko`、`soundwire-bus.ko`）；
- **扬声器放大器 ✅ 在**：`kernel/sound/soc/codecs/snd-soc-wsa884x.ko`；
- **codec ✅ 在**：`snd-soc-wcd938x.ko`、`snd-soc-wcd938x-sdw.ko`。

内核配置 `/proc/config.gz` 亦确认 `CONFIG_SND_SOC_WSA884X=m`、`CONFIG_SND_SOC_WCD938X=m`、`CONFIG_SND_SOC_WCD938X_SDW=m`。

**因此音频不需要重编内核，只需补 DTB 节点**（此结论经历一次错误修正：早期用 `find -name "snd-soc-wsa884x.ko"` 搜索路径不完整而误判为缺失）。

DTB 侧参考上游 `sm8550-mtp.dts` / `sm8550-qrd.dts`；硬件参数（放大器 `qcom,wsa884x` SoundWire 地址 `0x2170220/0x2170221`、`wcd938x-codec` 供电）可从 `reference/live-PJA110-A14-16G.dtb` 提取。

**当前 DTB 中 `sound`、`swr0/1/2`、`wcd938x`、放大器节点全部缺失**，但 SoC 级的 `lpass_*macro`、`soundwire@*` 控制器节点已存在（`status=disabled`）。

## 7. 关键问题与根因（排查记录）

### 7.1 黑屏的三个层次

按发现顺序，同一个「黑屏」现象由三个独立原因造成：

| 层次 | 根因 | 解法 |
| --- | --- | --- |
| 1 | GPU 固件缺失：内核 0.8 s 请求 `a740_sqe.fw`，此时 rootfs 未挂载，且 `CONFIG_FW_LOADER_USER_HELPER` 未启用 | 把固件打进 initramfs |
| 2 | **背光只有 204/4095（5%）**：KMS 一直在正常送帧，屏幕暗到看不见 | `echo 3000 > /sys/class/backlight/ae94000.dsi.0/brightness` |
| 3 | 桌面栈选型：Mir 硬依赖已移除的 EGL 扩展 → 软件缓冲 | 改用 Phosh/Phoc |

### 7.2 电源键只关不醒

- 现象：按电源键屏幕熄灭，再按无反应。
- 根因：**系统没有任何 logind 会话**（`loginctl list-sessions` 为空）。早期用手写 systemd unit 直接启动 Phosh，绕过了 logind，导致 `gsd-power` 无法关联会话。
- 解法：改用 **greetd**，通过 `initial_session` 自动登录，建立真正的 `seat0/tty1/wayland` 会话。会话建立后 `gsd-power` 自动随 `gnome-session` 启动。

### 7.3 触摸不响应

- 现象：`/dev/input/` 只有 `event0-2`（全为按键），无触摸设备。
- 根因：驱动 `synaptics-aston.ko` 位于 `/lib/modules/.../extra/`（树外模块），**默认不加载**。
- 解法：`modprobe synaptics-aston`，并写入 `/etc/modules-load.d/touchscreen.conf`。

### 7.4 触摸采样率回落到默认

- 现象：触摸可用，但采样率不是 240 Hz。
- 根因：模块参数 `report_rate_code` 默认为 0（固件默认值）。pmOS 时代设置为 `3`。
- 解法：`/etc/modprobe.d/synaptics-aston.conf` 写入 `options synaptics_aston report_rate_code=3`；日志确认 `PJA_ASTON fixed report rate code=3 readback verified`；实测约 228 Hz。

### 7.5 软键盘不出现

- 现象：点击输入框无软键盘，日志 `sm.puri.OSK0 was not provided by any .service files`。
- 根因：`/usr/share/applications/sm.puri.OSK0.desktop` 不是 autostart 项；复制到 `/etc/xdg/autostart/` 后仍不生效，因为其中 `OnlyShowIn=Phosh`，而实际会话 `XDG_CURRENT_DESKTOP=GNOME`。
- 解法：复制到 `/etc/xdg/autostart/` 并**删除 `OnlyShowIn` 行**。

### 7.6 会话卡在 phosh-session 不启动 phoc

- 现象：`loginctl` 有会话，但只有 `/bin/sh /usr/bin/phosh-session`，phoc 始终不出现。
- 根因：`/home/penguin/.bash_profile` 残留早期调试内容：
  ```sh
  if [ "$(tty)" = "/dev/tty1" ]; then
      exec /usr/bin/lomiri-session >>/tmp/lomiri-tty1.log 2>&1
  fi
  ```
  `phosh-session` 用 `bash -lc` 启动 gnome-session，登录 shell 读取该文件后 `exec` 去了 Lomiri。
- 解法：删除 `/home/penguin/.bash_profile`。

### 7.7 greetd `initial_session` 只执行一次

- 现象：重启 greetd 后不再自动登录，直接进入 agreety。
- 根因：greetd 用 runfile 保证 initial session 每次开机只跑一次。
- 解法：删除 `/run/greetd/runfile` 后再重启 greetd。配置中已把 `runfile` 指向 `/run/greetd/runfile`（重启自动清空）。

### 7.8 基础系统缺常用工具

- 现象：没有 `ping`、`curl`、`sudo`、`less`。
- 根因：该系统源自 Geekbench 用的 debootstrap 环境，既无 `ubuntu-minimal` 也无 `ubuntu-standard`（元包计数均为 0）。
- 解法：安装两个元包，包数 744 → 888。注意 `ping` 属于 `ubuntu-minimal` 而非 `ubuntu-standard`。

## 8. 配置清单（复现依据）

### 8.1 服务

| 单元 | 状态 | 作用 |
| --- | --- | --- |
| `greetd.service` | enabled / active | 登录管理，拉起 Phosh 会话 |
| `NetworkManager` | enabled / active | Wi-Fi 管理（**已接管 wlp1s0**，替代 networkd） |
| `systemd-networkd.service` | enabled / active | DHCP 与路由 |
| `ut-phosh.service` | disabled | 早期方案，已被 greetd 取代，保留备查 |

### 8.2 文件

```
/etc/greetd/config.toml                     greetd 配置（initial_session → phosh-session）
/etc/modules-load.d/touchscreen.conf        synaptics-aston
/etc/modprobe.d/synaptics-aston.conf        report_rate_code=3
/etc/xdg/autostart/sm.puri.OSK0.desktop     软键盘自启（已删除 OnlyShowIn）
/etc/NetworkManager/system-connections/K50G.nmconnection   Wi-Fi 连接（隐藏 SSID，autoconnect，mode 600）
/root/wifi-backup/                                     旧 networkd/wpa_supplicant 配置备份
/etc/resolv.conf                            静态 DNS（systemd-resolved 未启用）
/lib/firmware/qcom/                         GPU 固件（同时打进 initramfs）
```

### 8.3 已知的手工状态（重启后可能丢失）

| 项 | 说明 |
| --- | --- |
| 系统时间 | 无 RTC，开机为 1970；需 `date -u -s` 或等待 NTP，否则 apt 报 Release 未生效 |
| ~~Wi-Fi 连接~~ | ✅ **已修复（2026-10-22）**，见 [Wi-Fi 修复记录](wifi-fix-20261022.md) |
| DNS | `/etc/resolv.conf` 为静态文件，`systemd-resolved` 未安装 |
| 背光 | 默认值 204（约 5%），开机后偏暗 |

## 9. 已知限制

- **渲染帧率未可靠测量**：`/sys/kernel/debug/dri/0/crtc-*/status` 的 `vblank count` 读数不稳定（出现负增量），无法据此计算 fps；面板 120 Hz 已由 cmdline 与 KMS 模式确认。
- **`drmModeCrtcSetGamma` 未实现**：msm 驱动限制，Phosh 下同样存在。
- **无 EDID**：DSI 面板正常现象。
- **`EGL_WL_bind_wayland_display` 缺失**：Mesa 25 已移除；Phoc 不依赖该扩展，Mir 依赖，这是放弃 Mir 的直接原因。
- **不要 unbind GPU**：`msm_dpu` 解绑后 `failed to bind 3d00000.gpu (-28)`，`/dev/dri` 消失，属破坏性操作。
- **音频声卡已能创建但尚不能出声**：WCD938x 整条链路已打通（声卡、4 个 PCM、245 个 mixer 控件、HPHL/HPHR 放大链、两个 SoundWire slave Attached、耳机阻抗检测在跑）。**阻塞点已定位到 DSP 音频框架差异**：原厂用 AMDB/MDF（AGM 架构，GPR port 3），mainline 用 APM（AudioReach 架构，port 1），端口与服务均不同，已实测 5 个 SET_SPF_STATE 候选 opcode 全部超时。此外已查明外放功放为 **NXP TFA9874 ×2**（I2C 4-0034/4-0035），mainline 无对应驱动。详见 [音频移植记录](audio-sm8550-status.md) §8.11–8.14。
- **相机、通话、GNSS 未实现**，pmOS 时代同样未实现。
- **不要在运行时读 SoundWire slave 的 debugfs `registers`**：会阻塞内核线程，导致 TCP 23 shell 失去响应，只能长按电源键重启。

## 10. 下一步

内核源码树与交叉编译环境**已搭建完成**（Linux 6.14 + overlay，SHA512 校验通过，`kernelrelease` = `6.14.0-oneplus-xigua`，与运行内核一致；`CONFIG_MODVERSIONS`/`MODULE_SIG` 均未启用，可自由替换模块）。

1. **音频**：DSP 音频框架不匹配（AMDB vs APM）—— 需逆向 AMDB/MDF 协议或考虑其他路径；外放 TFA9874 需移植驱动（见 [音频移植记录](audio-sm8550-status.md) §8.14）；
2. **落盘当前状态**：写一份从干净 rootfs 到当前状态的完整脚本，用于生成 Release 镜像；
3. **渲染帧率测量**：改用 DRM tracepoint 或 `atomic` 统计，替代不可靠的 debugfs 计数；
4. **Release 镜像**：把已验证的 rootfs 打成可刷写镜像；
5. 剩余硬件：相机、指纹、基带。

## 11. 回滚资产

| 资产 | 路径 |
| --- | --- |
| boot_a 与 9 个 modem/校准分区 | `out/ut-backup/backup-20261018-153515/`（哈希已校验） |
| vendor_boot_a | `out/ut-backup/backup-20261018-160329/vendor_boot_a.img` |
| pmOS 配置归档 | `out/ut-backup/pmos-config-20261018-163413.tar.gz` |
| pmOS 完整镜像 | `out/postmarketos-baseline-20261017/oneplus-xigua.img.gz` |
| 原厂 DTB（硬件参数来源） | `reference/live-PJA110-A14-16G.dtb` |
| misc 分区（含槽位元数据） | `out/ut-backup/misc-20261021.bin`（4096 B，sha256 `ad7a29f0…bc41`，A 槽 metadata = `0f 07 01 00`） |

## 12. 调试验证通道

| 通道 | 地址 | 说明 |
| --- | --- | --- |
| USB NCM + TCP | `172.16.42.1:23` | 设备侧 python/pty root shell，无需认证 |
| **SSH（Wi-Fi）** | `10.4.178.231:22` | **penguin / 123456**，需 Wi-Fi 在线；USB 改动时的安全网 |
| Windows 侧地址 | `172.16.42.2/24` | 需管理员权限静态配置 |
| 串口 | COM15 | 仅在 pmOS initramfs 模式下出现 |

## 13. 证据文件

当前有效文档：

- `docs/porting-status.md`：本文，项目唯一总览；
- `docs/audio-sm8550-status.md`: audio porting record (9 DTS patches, WCD938x bring-up, TFA9874 discovery, AMDB-vs-APM root cause);
- `docs/wifi-fix-20261022.md`：**Wi-Fi 无 IP 修复记录**（networkd/NM 冲突、隐藏 SSID、持久化踩坑、换网操作速查）；
- `docs/system-config-20261022.md`：**系统配置记录**（时间同步、账户权限、SSH、屏幕缩放、GUI 设置，含一键复现脚本）；
- `docs/system-hardening-20261024.md`：**系统加固与两处误判更正**（pja110-kernel-mods 模块包、wpa_supplicant 不能禁用、关机自启是 USB 供电）；
- `docs/kernel-rename-migration-20261024.md`：**内核改名迁移**（oneplus-xigua → oneplus-PJA110，748 模块重部署，rfkill 补丁，4 个迁移陷阱）；
- `docs/wifi-board-correction-20261024.md`：**Wi-Fi 板级数据纠正**（`board.bin` 必须保留、`board-2.bin` 必须删除；推翻 10-23 的错误结论）；
- `docs/usrmerge-incident-20261024.md`：**usrmerge 符号链接事故与修复**（tar -C / 破坏 /lib 符号链接，导致 PAM 失效）；
- `docs/disk-layout-20261024.md`：**磁盘分区布局与磁盘修正**（6 个 UFS LUN 全表、A/B 固件区、Disk Capacity 缺失=udisks2 未装、重复 UUID 修复、sda6 回收为 /srv、chassis 误判 VM）；
- `docs/dtbo-model-fix-20261024.md`：**设备树 model 修正**（生效的 DTB 来自 `dtbo_a` 的 DTBO overlay 而非 `vendor_boot`，4 个 selector DTB 重建，含回滚镜像）；
- `docs/gui-patches-20261024.md`：**GUI 组件补丁**（stevia 虚拟键盘按屏幕比例 + 字号/图标缩放、g-c-c 显示 SoC 名称，含完整补丁与回滚）；
- `docs/firstboot-design-20261024.md`：**首启初始化设计**（静默首启 + 单页向导、账号默认 ubuntu/123456、提权收窄到单一 helper、polkit 放行改密码、中文字体修复、machine-id 与 journal 目录陷阱）；
- `docs/ab-flip-and-rename-incident-20261024.md`：**A/B 槽自动切槽与用户名改名事故复盘**（槽位切到 B 导致能 ping 但无服务、改名只做一半、sudoers 自锁、救援 initramfs 流程、可复用的排查顺序）；
- `docs/delivery-image-20261024.md`：**交付级镜像构建与安装**（bundle 组成、rsync 排除项与稀疏文件陷阱、离线改名、42 项镜像验证、install.sh 流程、首启扩容、已知限制）；
- `docs/usb-mode-mtp-20261024.md`：**USB 模式改造 NCM → MTP**（gadget 结构、FunctionFS 绑定顺序、PrivateDevices 陷阱、暴露 ~/Shared、关闭 NCM 与 23 端口 shell）；
- `docs/firstboot-removal-20261024.md`：**删除首启脚本**（设备名/密码改到设置里；SSH 密钥 drop-in、resize2fs 幂等 unit、polkit 放行三项动作；含 MTP 重启不枚举的修复）；
- `docs/wifi-instability-fix-20261023.md`：**Wi-Fi 断流根治记录**（board-2.bin 缺失→错误 board.bin 回退→1087 次 TLV 错误，修复后 0 错误 / 5GHz / 229Mbps）；
- `docs/fastcharge-fix-20261023.md`：**快充修复记录**（主线从未使用 BATT_CHG_CTRL_LIM → 1.2W；下发 0x31/prop10 后 12.5W，5.3 倍提升）；
- `docs/bypass-power-20261023.md`：**旁路供电与电池保护记录**（Power Path 原生支持、软件旁路实测零电流、服务器模式推荐配置）；
- `docs/haptics-reverse-engineering.md`：**振动马达逆向记录**（PM8550B HV haptics 寄存器映射、vendor 模块逆向）；
- `docs/bluetooth-wcn7850-status.md`：**蓝牙完整诊断记录**（五个被证伪的假设、代码级根因、修复方案）；
- `docs/native-upgrade.md`：native 升级线记录；
- `docs/fastcharge-status.md`：快充状态；
- `docs/fast-charge-high-refresh-assessment.md`：高刷与快充评估；
- `docs/deepseek-baseline-plan.md` / `deepseek-baseline-review.md`：pmOS 基线改造计划与复核。

已归档（`docs/archive/`，Ubuntu Touch / Lomiri 路线，**已被本文取代，勿作为现状依据**）：

- `archive/ubuntu-touch-feasibility.md`：UT 可行性结论（含放弃原因）；
- `archive/ut-bootable-rootfs-assessment.md`：可启动镜像评估；
- `archive/ut-bringup-status.md`：早期 bring-up 记录（Lomiri 阶段）。

其他证据：

- `out/geekbench/aa536-vendor-timings.json`：面板 60/90/120 Hz 时序；
- `out/baseline-20261017/`：pmOS 基线清单与 diff 表。

## 14. 源码与工作树

- Windows 工作树：`H:\workspace\PJA110-Mainline`
- 内核源码树：`charger-native-a/linux-6.14`（本地补丁版）
- 设备 DT：`dts/sm8550-oneplus-xigua.dts`（精简 bring-up 版，注释明示 "No display, no touch, no modem"；显示为后续补丁加入）