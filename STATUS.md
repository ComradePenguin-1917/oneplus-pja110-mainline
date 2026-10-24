# 硬件支持状态（mainline Linux 6.14 + Ubuntu 24.04 / Phosh）

设备：OnePlus Ace 2 Pro，型号 **PJA110**，代号 **xigua**，SoC **SM8550**，16 GB RAM。

```
/sys/firmware/devicetree/base/model       → OnePlus PJA110
/sys/firmware/devicetree/base/compatible  → oneplus,pja110 qcom,sm8550
hostnamectl chassis                       → handset
uname -r                                  → 6.14.0-oneplus-PJA110
```

---

## ✅ 可用

| 功能 | 实现 / 备注 |
| --- | --- |
| 显示 | `panel-oneplus-aa536`（1240×2772，2K 曲面）。60/120 Hz 通过模块参数 `panel_oneplus_aa536.refresh` 切换；120 Hz 判定用 `adjusted_mode.clock > 350000` |
| GPU | Adreno 740（`msm`/`a6xx`），固件 `a740_sqe.fw` / `gmu_gen70200.bin` / `a740_zap.mbn` 放在 initramfs 里（内核无 userspace firmware fallback）|
| 触摸 | `synaptics_tcm_hbp`，I2C + SPMI |
| 按键 | 音量键、电源键 |
| Wi-Fi | WCN7850，`ath12k` PCIe `0000:01:00.0`，支持 6 GHz（5765–7125 MHz，需板级 `regdb`/`bdf` 修正，见 `docs/wifi-board-correction-20261024.md`）|
| 蓝牙 | WCN7850 over **UART14**（`hci_uart` + `btqca`）|
| USB 文件传输 | `dwc3` dual-role + configfs `ffs.mtp` + `umtp-responder`，暴露 `~/Shared`。**不含 NCM 网卡**（见 `docs/usb-mode-mtp-20261024.md`）|
| 充电 | Qualcomm `qcom_battmgr` + PMIC。PD 协商 RDO `0x1304B12C`；快充通过 `BAT_PROPERTY_SET(0x31)` / `BATT_CHG_CTRL_LIM(10)` 设为 `3000000` µA，实测 **12.5 W** |
| 电池计量 | `bq28z610`（真实电量）。ADSP 侧的假电池 `qcom-battmgr-bat` 用 `ignore_battery=1` 抑制 |
| 振动马达 | `qcom,hv-haptics`（SPMI 0x07，寄存器 `0xf000`/`0xf100`/`0xf200`，需要 `spmi_ext_register_readl/writel`）|
| 桌面 | Phosh 0.38 / Phoc 0.38 / greetd 0.9，phone 式自动登录（无 greeter）|
| 虚拟键盘 | `phosh-osk-stub`（stevia）0.38 打了两个补丁：按键高度按屏高比例、字号随按键缩放 |
| 设置 | `gnome-control-center` 打了 SoC 名称补丁（关于页显示 `Snapdragon SM8550`）|

---

## ❌ 不可用（含原因）

| 功能 | 原因 |
| --- | --- |
| **音频** | 本机**没有 WSA8845**，是 WCD938x（SoundWire）+ NXP TFA9874 ×2。mainline 侧缺少 ADSP 的 `SHARED_MEM_MAP_REGIONS`，DSP 拓扑跑不起来；没有可用的 ASoC machine driver。这是最硬的一块 |
| **相机** | 无 mainline 驱动，且 OEM 用的 CSID/CSI 组合没有公开文档 |
| **指纹** | 屏下光学，无 mainline 驱动 |
| **NFC** | 无 mainline 驱动 |
| **蜂窝 / 通话 / 短信** | 未开始（需要 QRTR + `qmi_wwan` + ModemManager 大量适配）|

## ⚠️ 未验证 / 未做

| 项 | 说明 |
| --- | --- |
| USB OTG / 外接显示 | `dwc3` 的 `DUAL_ROLE` 已编进内核，但 typec 相关驱动是模块（`CONFIG_TYPEC_TCPM=m`、`CONFIG_TYPEC_QCOM_PMIC=m`），initramfs 里没有；且手上没有 OTG 线实测 |
| 旁路充电 | 技术上就是 `BATT_CHG_CTRL_LIM = 0`，已验证寄存器可写，缺 UI 入口 |
| 屏幕常亮策略 / 自动亮度 | 光感在 `stk3338` 上，未接 |
| GPS | 未做 |

---

## 存储与引导布局

| 分区 | 设备节点 | 大小 | 用途 |
| --- | --- | --- | --- |
| `boot_a` | `sde13` | 192 MiB | 内核（6.14）|
| `dtbo_a` | `sde17` | 24 MiB | **DTBO 覆盖 `model`/`compatible`** —— 只改 `vendor_boot` 里的 DTB 无效 |
| `vendor_boot_a` | `sde24` | 192 MiB | initramfs（挂 rootfs、switch_root）+ 基准 DTB |
| `misc` | `sda3` | — | A/B 槽状态 + bootloader 命令。**注意：往里写 `boot-fastboot` 会让设备反复重启**（见事故复盘）|
| `userdata` | `sda14` | 456.9 GiB | ext4 rootfs，`LABEL=ut-root` |
| 辅助卷 | `sda6` | 15 GiB | ext4，挂在 `/srv`，`LABEL=pja110-spare` |

系统是 **usrmerge** 布局（`/lib` → `usr/lib`，`/bin` → `usr/bin` …）。
改用户、装包时别用 `tar -xJf … -C /`，会破坏符号链接（踩过）。

---

## 已知的本地 workaround（不适合上游）

| 项 | 位置 | 为什么不上游 |
| --- | --- | --- |
| `ignore_battery` 模块参数 | `qcom_battmgr.c` | 为了屏蔽 ADSP 假电池，属于调试开关 |
| 面板 `refresh` 模块参数 | `panel-oneplus-aa536.c` | 应该用 DRM connector 属性，模块参数只是快速验证 |
| OSK `height-ratio` / `label-scale` | `phosh-osk-stub` | 是 stevia 的本地补丁，应改为上游 gschema |
| `BATT_CHG_CTRL_LIM` 直接写 | `tools/enable-fastcharge.sh` | 应该走 power_supply 的 `charge_control_limit` |

---

## 数据来源

本文件的每一条都在设备上实测过，原始记录见 `docs/`：

- 显示 / 面板：[`docs/porting-status.md`](docs/porting-status.md)
- Wi-Fi：[`docs/wifi-fix-20261022.md`](docs/wifi-fix-20261022.md)、[`docs/wifi-board-correction-20261024.md`](docs/wifi-board-correction-20261024.md)
- 充电 / 快充：[`docs/fastcharge-fix-20261023.md`](docs/fastcharge-fix-20261023.md)
- 振动：[`docs/porting-status.md`](docs/porting-status.md)
- USB：[`docs/usb-mode-mtp-20261024.md`](docs/usb-mode-mtp-20261024.md)
- 分区与引导：[`docs/disk-layout-20261024.md`](docs/disk-layout-20261024.md)、[`docs/dtbo-model-fix-20261024.md`](docs/dtbo-model-fix-20261024.md)
