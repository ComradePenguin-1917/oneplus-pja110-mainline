# Ubuntu Touch 在 PJA110 上的移植状态

更新：2026-10-18 23:40。记录当前已跑通的启动链、可达的调试通道，以及显示栈的剩余问题。

## 1. 已达成

| 项 | 状态 | 证据 |
| --- | --- | --- |
| 内核直挂根分区启动 | ✅ | `root=/dev/sda14 rootwait rw`，无需 initramfs |
| Ubuntu 24.04 原生启动 | ✅ | `systemctl is-system-running` → `running`，`PRETTY_NAME="Ubuntu 24.04.3 LTS"` |
| systemd 作为 PID 1 | ✅ | 登录会话、logind、getty 全部正常 |
| USB 网络 | ✅ | 自建 NCM gadget，`usb0` = 172.16.42.1/24 |
| root shell（远程） | ✅ | python3 + pty 服务监听 23 端口 |
| 用户账户 | ✅ | `penguin` / 组 `video render input audio plugdev` |
| Lomiri 启动 | ⚠️ | Mir 初始化成功、QtMir 绑定 DSI-1、Greeter QML 加载，约 5 秒后 SIGILL |
| Wi-Fi | ❌ | ath12k `-110`，`/lib/firmware/ath12k` 缺失 |

## 2. 启动链（当前可用组合）

```
boot_a         devroot-boot_a.img        root=/dev/sda14 rootwait rw console=tty0 loglevel=7
                                          panel_oneplus_aa536.refresh=120，ramdisk 0
init_boot_a    boot-direct/init_boot_a.img   空 ramdisk（44 B）
vendor_boot_a  boot-direct/vendor_boot_a.img 空 cpio（无 /init）
```

关键结论：**这台设备不需要 initramfs**。内核 UFS/ext4/DRM/面板全部 built-in，`rootwait` 足够等到 `sda14` 出现。

踩过的坑（均已排除）：

- `root=UUID=...` 会 `unknown-block(0,0)`，改用设备路径 `/dev/sda14` 后正常；
- pmOS 的 initramfs 只能挂它自己的 loop 子分区，`pmos_root=` 可跳过但 `switch_root` 后被 systemd 判定为 chroot；
- 自建最小 initramfs 多次失败：动态 busybox 的 musl loader 路径、cpio 未对齐、`#!/bin/sh` 在 initramfs 中不存在、`set -e` 导致 PID 1 退出。

## 3. 设备上的自建组件

| 路径 | 作用 |
| --- | --- |
| `/opt/utsel/shserver.py` | python3 + pty 的 root shell，监听 0.0.0.0:23 |
| `/opt/utsel/usb-ncm.sh` | configfs 建 NCM gadget，`usb0` 配 172.16.42.1/24（带 UDC/网卡重试） |
| `/opt/utsel/busybox` | 从 pmOS initramfs 复制，未使用 |
| `/etc/systemd/system/ut-usb-ncm.service` | 开机建 gadget，`Before=ut-shell.service` |
| `/etc/systemd/system/ut-shell.service` | 开机起 shell 服务 |
| `/etc/NetworkManager/conf.d/99-usb0-unmanaged.conf` | 让 NM 不接管 usb0 |
| `/etc/systemd/system/getty@tty1.service.d/autologin.conf` | tty1 自动登录 penguin |
| `/home/penguin/.bash_profile` | tty1 上 `exec lomiri-session` |
| `/etc/environment` | `XDG_SESSION_TYPE=wayland`（让 logind 会话类型为 wayland） |

密码：`penguin` / `123456`。

## 4. 主机侧配置

- Windows 的 `UsbNcm Host Device` 网卡需静态地址 `172.16.42.2/24`；
- 设备无 DHCP 服务，每次重装系统后要手动配一次；
- 连接方式：`telnet 172.16.42.1 23`（本仓库脚本用原始 TCP 即可）。

## 5. 显示栈的剩余问题

**现象**：Lomiri 启动后 5 秒内退出，会话反复重建，屏幕在文字控制台与 UI 之间闪烁。

**已确认**：

- Mir 用 freedreno 初始化成功，EGL/GL 扩展正常；
- QtMir 绑定 `DSI-1 1240x2772`，输入设备（`gpio-keys`、`pmic_pwrkey`、`pmic_resin`）注册；
- Greeter/Shell 的 QML 已加载，然后在 Panel QML 之后 `Illegal instruction`（SIGILL，退出码 132）；
- 强制 `QT_QUICK_BACKEND=software` 时改为 SIGSEGV，说明崩点在 QML/场景图附近，不是纯 GPU 驱动路径；
- 无会话（root 直接跑）时 Mir 拿不到 DRM master，`miral-kiosk` 报 `gbm-kms does not claim to support this system`；
- 解绑 fbcon（`/sys/class/vtconsole/vtcon1/bind` = 0）不影响该循环；
- 会话已改为 `Type=wayland`（`pam_systemd` 读 `XDG_SESSION_TYPE`），循环仍在。

**未定位**：SIGILL 的具体指令与库。rootfs 里没有 `gdb`/`binutils`/`strace`，无法取回溯；core dump 可以产生（`kernel.core_pattern=core`），但缺解析工具。

## 6. 下一步（按优先级）

1. **拿到设备网络**，以便 `apt install gdb binutils firmware-atheros`：
   - 方式 A：Windows 对 `UsbNcm Host Device` 开 Internet 连接共享，设备补 `192.168.137.2/24` + 默认路由；
   - 方式 B：补 ath12k 固件（可从 `out/postmarketos-baseline-20261017/oneplus-xigua.img.gz` 里提取 `/lib/firmware/ath12k`），走 Wi-Fi。
2. **拿到 SIGILL 回溯**：`ulimit -c unlimited` + `gdb lomiri core`，或装 `binutils` 后用 `readelf -n` 读 NT_PRSTATUS/NT_FILE。
3. 依据回溯决定：换 Lomiri 版本、禁用 QML JIT、或修 Qt 包。

## 7. 回退资产（电脑上）

| 文件 | 用途 |
| --- | --- |
| `out/ut-backup/backup-20261018-153515/` | `boot_a` + 9 个基带/校准分区 |
| `out/ut-backup/backup-20261018-160329/` | `vendor_boot_a`（pmOS 原版） |
| `out/ut-backup/pmos-config-20261018-163413.tar.gz` | pmOS 配置、SSH 密钥、包清单 |
| `out/postmarketos-baseline-20261017/oneplus-xigua.img.gz` | pmOS 完整镜像 |
