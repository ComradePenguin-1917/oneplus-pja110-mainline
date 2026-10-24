# PJA110 Ubuntu 系统配置记录（2026-10-22）

本文记录 rootfs 层所有已验证的配置改动，供重装/迁移时复现。硬件层（DTB、内核）见 [移植总览](porting-status.md)。

一键复现：`sudo bash tools/setup-PJA110.sh`

> **执行注意事项**：脚本第 5 步会重启 `systemd-networkd` 和 `NetworkManager`，**会导致 Wi-Fi 短暂断开**。
> 因此执行脚本时**应通过 USB NCM 通道（172.16.42.1:23）**，不要在 Wi-Fi SSH 会话里执行，否则会自断连接。
> 若只想通过 Wi-Fi SSH 执行，加 `--skip-wifi` 参数跳过网络配置部分。

## 一、改动总览

| # | 项目 | 问题 | 解决方案 |
| --- | --- | --- | --- |
| 1 | 系统时间 | RTC 无电池，开机停在 **1970 年**，导致 apt 签名验证全部失败 | 装 `systemd-timesyncd` + 配国内 NTP |
| 2 | 账户权限 | `root` 密码 locked（任何密码都不对）、`penguin` 不在 sudo 组 | 设 root 密码、penguin 加入 sudo |
| 3 | SSH | 未安装 `openssh-server` | 安装并 enable |
| 4 | 屏幕缩放 | 1240×2772 按 1x 渲染，UI 元素巨大、内容显示不下 | phoc.ini 启用 `scale = 2` |
| 5 | Wi-Fi 无 IP | networkd/NM/wpa_supplicant 三方冲突 | NM 独占 wlp1s0 |
| 6 | GUI 设置 | 无图形化 Wi-Fi 连接入口 | 装 gnome-control-center + phosh-mobile-settings |

## 二、逐项说明

### 1. 系统时间（最隐蔽的坑）

**症状**：`date` 显示 1970-01-07，`apt-get update` 报：

```
E: Release file for .../noble-updates/InRelease is not valid yet
   (invalid for another 20742d 4h 35min 57s)
```

**根因**：设备无 RTC 电池，每次开机时间归零。apt 用 HTTPS/GPG 校验仓库签名，时间错乱则全部拒绝。

**修复**：

```sh
apt-get install -y systemd-timesyncd
cat > /etc/systemd/timesyncd.conf <<'EOF'
[Time]
NTP=ntp.aliyun.com time1.cloud.tencent.com
FallbackNTP=ntp.ubuntu.com
EOF
systemctl enable --now systemd-timesyncd
```

> 用国内 NTP 源，因为校园网常屏蔽境外 NTP。

**验证**：`timedatectl` 显示 `System clock synchronized: yes`。

**遗留**：`RTC time` 仍显示 1970（硬件无电池，无法修）。每次开机后需等 NTP 同步完成（约 2-5 秒）再执行 apt 操作。

### 2. 账户与权限

**症状**：GUI 弹窗要求输入密码，输 `123456` 无效。

**根因**：

```
passwd -S root     → root L   (L = locked，密码被锁定)
groups penguin     → penguin audio video plugdev input render
                            ↑ 没有 sudo 组！
```

**修复**：

```sh
echo 'root:123456' | chpasswd      # 解锁并设置 root 密码
echo 'penguin:123456' | chpasswd
usermod -aG sudo penguin           # 加入 sudo 组
```

**重要**：penguin 加入 sudo 组后需**重新登录**（或重启）才生效。

**当前凭据**：

| 账户 | 密码 | 组 |
| --- | --- | --- |
| `root` | `123456` | root |
| `penguin` | `123456` | penguin, sudo, audio, video, plugdev, input, render |

**免密 sudo**（为便于自动化，可选）：

```sh
echo 'penguin ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/90-penguin-nopasswd
chmod 440 /etc/sudoers.d/90-penguin-nopasswd
```

撤销：`rm /etc/sudoers.d/90-penguin-nopasswd`

### 3. SSH

原本**没有安装** `openssh-server`，`/etc/systemd/system/ssh.service` 不存在。

```sh
apt-get install -y openssh-server
systemctl enable --now ssh
```

验证：`ss -lnt | grep :22` 显示 `0.0.0.0:22 LISTEN`。

**战略意义**：这是 USB OTG 实验的安全网。切换 USB 到 host 模式会断开 NCM gadget（172.16.42.1），届时只能靠 Wi-Fi SSH 访问。

### 4. 屏幕缩放（显示不下的根因）

**症状**：UI 元素过大，设置页面内容超出屏幕，很多控件看不到。

**根因**：

```
物理分辨率: 1240×2772
/usr/share/phosh/phoc.ini:
    #[output:DSI-1]
    #scale = 2          ← 被注释掉，等于按 1x 渲染
```

**修复**：

```ini
# /usr/share/phosh/phoc.ini
[output:DSI-1]
scale = 2
```

**效果**：

| scale | 逻辑分辨率 | 说明 |
| --- | --- | --- |
| 1（原状） | 1240×2772 | UI 过大，显示不下 |
| **2（当前）** | **620×1386** | 手机常规比例 |
| 3 | 413×924 | 更小更精细，可能过小 |

**备份**：`/usr/share/phosh/phoc.ini.orig`

**生效条件**：需重启 phoc/phosh 或重启设备。**不能在运行中热切换**（重启 phoc 会中断图形会话）。

**如需微调**：改 `scale` 值后重启；或配合 `gsettings set org.gnome.desktop.interface text-scaling-factor 1.2` 单独放大字体。

### 5. Wi-Fi 管理（详细记录见 [wifi-fix-20261022.md](wifi-fix-20261022.md)）

**要点**：三套机制（`systemd-networkd` / `wpa_supplicant` / `NetworkManager`）同时管一块网卡导致冲突。

**修复**：NM 独占 wlp1s0，networkd 只管 usb0（实际 usb0 也是 unmanaged，由 gadget 自配 IP）。

```sh
# 移除 networkd 的无线配置
rm /etc/systemd/network/25-wlp1s0.network     # 备份到 /root/wifi-backup/

# NM 明确管理范围
cat > /etc/NetworkManager/conf.d/10-manage-wifi.conf <<'EOF'
[keyfile]
unmanaged-devices=interface-name:usb0
[device]
wifi.scan-rand-mac-address=no
EOF
```

**当前连接**：`HKUSTGZ`（802.1X 企业认证），IP `10.4.178.231/22`。

#### 多网络优先级（重要，踩过的坑）

设备上有多个已保存网络时会**自动挑优先级最高的连**。`K50G`（隐藏热点，priority=10）曾把校园网挤掉，导致 SSH 通道中断。

```sh
# 设定：校园网优先于手机热点
nmcli connection modify K50G    connection.autoconnect-priority 10
nmcli connection modify HKUSTGZ connection.autoconnect-priority 100
```

查看所有连接优先级：

```sh
for c in $(nmcli -t -f NAME connection show | grep -v '^lo$'); do
  printf "%-20s %s\n" "$c" "$(nmcli -t -f connection.autoconnect-priority connection show "$c" | cut -d: -f2)"
done
```

**排查要点**：如果 SSH 突然连不上但 USB NCM 还通，先查 `nmcli device` 看是不是自动切到别的 Wi-Fi 了，不一定是网络故障。

### 6. GUI 设置工具

Phosh 0.38 默认不带图形化 Wi-Fi 配置界面，只有 `nmtui`（终端 TUI）。

```sh
apt-get install -y --no-install-recommends phosh-mobile-settings gnome-control-center
```

| 包 | 版本 | 作用 |
| --- | --- | --- |
| `phosh-mobile-settings` | 0.38.0-1 | Phosh 外壳设置（与 phosh 版本匹配）|
| `gnome-control-center` | 1:46.7 | 完整设置面板，含 Wi-Fi（支持 802.1X）|

**使用**：应用列表 → Settings → Wi-Fi → 选网络 → 输入账号密码。

## 三、当前系统状态

### 网络

```
usb0    UP   172.16.42.1/24        ← USB NCM 调试通道
wlp1s0  UP   10.4.178.231/22       ← 校园网 HKUSTGZ
              网关 10.4.179.254
              DNS 10.90.63.2 / 10.90.63.3
默认路由 via 10.4.179.254 dev wlp1s0
```

外网连通：`ping 223.5.5.5` → 2/2 收到，约 42ms。

### 两条独立访问通道

| 通道 | 地址 | 依赖 |
| --- | --- | --- |
| USB NCM | `172.16.42.1:23`（root shell）/ `:8080`（上传）| USB gadget 保持 device 模式 |
| **SSH** | `10.4.178.231:22`，用户 `penguin` / `123456` | Wi-Fi 在线 |

**两者互为备份**。做 USB OTG 之类会影响 gadget 的实验时，用 SSH 保底。

### 已安装软件版本

| 包 | 版本 |
| --- | --- |
| openssh-server | 1:9.6p1-3ubuntu13.20 |
| phosh-mobile-settings | 0.38.0-1 |
| gnome-control-center | 1:46.7-0ubuntu0.24.04.6 |
| alsa-utils | 1.2.9-1ubuntu5 |
| alsa-ucm-conf | 1.2.10-1ubuntu5.15 |
| iw | 6.7-1build1 |
| wpasupplicant | 2:2.10-21build4 |
| rfkill | 2.39.3-9ubuntu6.6 |

### 服务状态

```
ssh                active  / enabled
NetworkManager     active  / enabled
systemd-networkd   active  / enabled   (不再管 wlp1s0)
systemd-timesyncd  active  / enabled
```

### 内核模块替换（非 rootfs 层，但需记录）

| 模块 | 大小 | 说明 |
| --- | --- | --- |
| `sound/soc/qcom/qdsp6/snd-q6apm.ko` | 254808 | 带 debugfs APM 注入工具（音频调试用）|
| `drivers/input/misc/qcom_hv_haptics_probe.ko` | 66120 | HV haptics 探测驱动（振动调试用）|

两者均在 `out/ut-test/` 有对应副本。纯净原版 `snd-q6apm-pristine.ko` 也在该目录。

## 四、已知遗留问题

| 问题 | 说明 | 影响 |
| --- | --- | --- |
| RTC 时间 | 硬件无电池，`RTC time` 恒为 1970 | 每次开机需等 NTP 同步（约 2-5s），期间 apt 不可用 |
| 缩放需重启生效 | 改 phoc.ini 后必须重启 phoc/设备 | 首次配置时需重启一次 |
| sudo 组需重登 | `usermod -aG sudo` 后当前会话不生效 | 重启或重新登录 |
| USB 默认 device 模式 | DTB 中 `dr_mode = peripheral` | 想做 OTG 需改 DTB（有风险，详见 porting-status） |

## 五、恢复流程（重装后）

```sh
# 1. 确保有网络（USB NCM 或已连 Wi-Fi）
ping -c2 223.5.5.5

# 2. 拉取并执行配置脚本
sudo bash tools/setup-PJA110.sh

# 3. 配置 Wi-Fi（脚本会打印示例命令）
nmcli connection add type wifi con-name "HKUSTGZ" ifname wlp1s0 \
  ssid "HKUSTGZ" wifi-sec.key-mgmt wpa-eap 802-1x.eap peap \
  802-1x.phase2-auth mschapv2 802-1x.identity "用户名" \
  802-1x.password "密码" connection.autoconnect yes

# 4. 重启使缩放生效
sudo reboot
```
