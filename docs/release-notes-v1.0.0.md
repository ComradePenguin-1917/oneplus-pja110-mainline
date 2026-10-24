# Ubuntu 24.04 交付镜像 v1.0.0

OnePlus Ace 2 Pro（**PJA110 / xigua**，SM8550）的 Ubuntu 24.04 + Phosh 可刷镜像，
内核 **mainline 6.14.0-oneplus-PJA110**。

> 这不是日常可用的发行版。音频、相机、指纹、NFC、蜂窝都不可用，
> 详见仓库的 [STATUS.md](../STATUS.md)。刷机前请先读
> [事故复盘](../docs/ab-flip-and-rename-incident-20261024.md)。

---

## 资产说明

| 文件 | 大小 | 刷到哪个分区 |
| --- | --- | --- |
| `boot_a.img` | 192 MiB | `fastboot flash boot_a` |
| `vendor_boot_a.img` | 192 MiB | `fastboot flash vendor_boot_a` |
| `dtbo_a.img` | 24 MiB | `fastboot flash dtbo_a` |
| `rootfs.img.gz` | 1.3 GiB | **不能直接 fastboot**，见下 |
| `SHA256SUMS` | — | 校验用 |
| `MANIFEST.txt` | — | 版本与校验信息 |

`rootfs.img.gz` 解压后是 8 GiB（稀疏），文件系统 UUID 与引导参数一致，
写入 `userdata`（`/dev/sda14`）后首次开机自动扩到整盘 450 GiB。

---

## 为什么 rootfs 不能直接 `fastboot flash userdata`

两个硬约束，都踩过：

1. **`max-download-size` 只有 768 MiB**，8 GiB 必须分块
2. fastboot 34.0.5 在 Windows 上转 sparse 分块时**报 `Error reading sparse file`**

正确做法有两种：

### 方案 A（推荐）：initramfs 安装器

镜像先放到设备的辅助卷 `/dev/sda6`（15 GiB，挂在 `/srv`），
再用一个只做 dd 的 initramfs 把它写进 `/dev/sda14`：

```sh
# 设备上：解压到 /srv
gunzip -c rootfs.img.gz > /srv/pja110-bundle/rootfs.img

# PC 上：刷安装器（构建方法见 docs/delivery-image-20261024.md）
fastboot flash vendor_boot_a install-rootfs-vendor_boot_a.img
fastboot reboot
```

安装器会依次：校验镜像大小与 ext4 魔数 → `dd` → 读回前 8 KiB 比对 →
在 `/srv` 留标记 → `switch_root` 正常启动。**任何一步失败就原地停住，不会重启循环**。

### 方案 B：解压后在 Linux 上直接写

```sh
gunzip -c rootfs.img.gz > rootfs.img
sudo dd if=rootfs.img of=/dev/sdXN bs=4M conv=fsync
```

---

## 刷完必做

```sh
fastboot getvar current-slot     # 必须是 a
```

bootloader 在反复启动失败后会自动切到 **B 槽**，而 B 槽没有系统 ——
症状是「只显示开机 logo、USB 上什么都没有」。恢复：
`fastboot --set-active=a`。

---

## 首次开机（全自动，无向导）

- 生成 SSH 主机密钥（`ssh.service` 的 drop-in）
- 根分区扩到 450 GiB（`pja110-growfs.service`，幂等）
- 设备名 / 密码都在**设置**里改（polkit 规则已放行）

默认账号：`ubuntu` / `123456` —— **请立刻改掉**。
USB 是 MTP 文件传输（暴露 `~/Shared`），**没有网络**；联网请走 Wi-Fi。

---

## 已确认可用

显示（60/120 Hz 可切）、触摸、Wi-Fi（WCN7850，含 6 GHz）、蓝牙、
MTP 文件传输、PD 快充（实测 12.5 W）、电池计量（`bq28z610`）、振动、
Phosh 0.38 + 打过补丁的虚拟键盘（占屏高 35%）。

## 已知不可用

音频（mainline 缺 DSP `SHARED_MEM_MAP_REGIONS`）、相机、指纹、NFC、蜂窝/通话。
USB OTG 未实测（手上没有 OTG 线）。
