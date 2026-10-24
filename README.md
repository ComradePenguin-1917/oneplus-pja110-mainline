# OnePlus Ace 2 Pro (PJA110 / xigua) — mainline Linux + Ubuntu 移植记录

OnePlus Ace 2 Pro（型号 **PJA110**，代号 **xigua**，SoC **SM8550**）跑 **mainline Linux 6.14** +
**Ubuntu 24.04 (Phosh)** 的完整移植记录、可复现脚本与待上游补丁。

> 这不是一个"能日常用"的发行版，也不准备成为。这里记录的是：
> **哪些硬件在 mainline 上能跑通、怎么跑通的、哪些跑不通以及为什么。**
> 如果你手上有同款机器，可以照着复现；如果这些笔记能让别人少走几天弯路，目的就达到了。

---

## 当前状态一览

详细见 [STATUS.md](STATUS.md)。

| 类别 | 状态 |
| --- | --- |
| 显示（2K 曲面屏，60/120 Hz 可切）| ✅ |
| 触摸 / 按键 | ✅ |
| Wi-Fi（WCN7850 / ath12k）6 GHz | ✅ |
| 蓝牙（UART14）| ✅ |
| USB 文件传输（MTP，暴露 `~/Shared`）| ✅ |
| 充电（PD，实测 12.5 W 快充）| ✅ |
| 电池计量（`bq28z610`）| ✅ |
| 桌面（Phosh 0.38）+ 虚拟键盘（stevia 打过补丁）| ✅ |
| 音频 | ❌ 无 WSA8845；WCD938x + TFA9874 需要 DSP，mainline 缺 `SHARED_MEM_MAP_REGIONS` |
| 相机 | ❌ 无驱动 |
| 指纹 / NFC | ❌ 未做，短期不现实 |
| 蜂窝 / 通话 | ❌ 未做 |
| USB OTG | ⚠️ 未实测（手上没有 OTG 线）|
| 旁路充电 | ⚠️ 有能力实现（`BATT_CHG_CTRL_LIM = 0`），未做 |

---

## 仓库结构

```
docs/          移植全过程的记录（30 篇，按时间与主题分）
image/         交付镜像的构建 / 安装 / USB / 系统配置脚本
  build/       rootfs 镜像构建、离线改名、引导资产收集
  install/     安装器 initramfs、install.ps1/sh、验收清单
  usb/         MTP gadget（configfs + umtp-responder）
  system/      扩容、SSH 主机密钥、polkit 规则
dts/           设备树源（sm8550-oneplus-xigua*.dts / *.dtsi）
config/        内核配置片段
tools/         文档里实际用到的脚本（一次性调试脚本未收录）
archive/       历史文档（含早期 pmOS 路线）
```

镜像产物（8 GiB rootfs、三个引导分区）**不在仓库里**，见 Releases。

---

## 怎么用

### 只是想读结论

按顺序看这几篇：

1. [docs/porting-status.md](docs/porting-status.md) —— 总览，硬件逐项结论
2. [docs/disk-layout-20261024.md](docs/disk-layout-20261024.md) —— 分区布局、引导链、A/B 槽
3. [docs/delivery-image-20261024.md](docs/delivery-image-20261024.md) —— 镜像怎么构建、怎么装
4. [docs/ab-flip-and-rename-incident-20261024.md](docs/ab-flip-and-rename-incident-20261024.md) —— **踩过的坑**（强烈建议先看，能省几小时）

### 想复现

前提：设备已解锁 bootloader、`fastboot` 可用、A 槽为活动槽。

```sh
# 1. 构建 rootfs 镜像（在设备上跑，把当前系统打成镜像）
sudo ./image/build/build-rootfs.sh --size 8G --out /srv/pja110-image

# 2. 收集引导资产 + 组装交付包
sudo ./image/build/collect-boot-assets.sh \
     --rootfs /srv/pja110-image/rootfs.img \
     --out /srv/pja110-bundle

# 3. 安装（见 docs/delivery-image-20261024.md 的两阶段流程）
```

⚠️ **两个必须知道的约束**（都踩过）：

1. **`userdata` 不能用 `fastboot flash` 直接刷**。`max-download-size` 只有 768 MiB，
   8 GiB 镜像会被切成 5 块，fastboot 34.0.5 在 Windows 上转 sparse 时报
   `Error reading sparse file`。正确做法是 initramfs 安装器（设备内 dd）。
2. **每次刷机后必须 `fastboot getvar current-slot` 确认是 `a`**。
   bootloader 在反复启动失败后会自动切到 B 槽，而 B 槽没有系统 ——
   表现为「能开机 logo、USB 什么都没有」。

---

## 待上游的部分

`dts/` 里的设备树和 `config/` 里的配置目前是**独立维护的补丁**，还没走上游流程。
有意向上游时需要做的事：

- [ ] 按 `devicetree` 规范整理 dt-bindings
- [ ] `git format-patch` 成序列，发 `linux-arm-msm@vger.kernel.org` + `devicetree@vger.kernel.org`
- [ ] 面板（`panel-oneplus-aa536`）、充电（`qcom_battmgr` 改动）、振动（`qcom,hv-haptics`）各自单独成 patch
- [ ] 检查 xigua 与上游已有的 SM8550 机型（如 QRD8550）能否共用 dtsi

已知**不适合**上游的东西：`qcom_battmgr` 里的 `ignore_battery` 参数、
面板模块参数 `refresh`、OSK 的 `height-ratio` 补丁 —— 这些是本地 workaround，注释里都标了。

---

## 贡献

这个移植**不再由我继续往下做**了。设备会刷回精简 Android，工作留在这里。

如果你接手，最有价值的方向（按性价比排序）：

1. **音频**：搞清楚 ADSP 上 `SHARED_MEM_MAP_REGIONS` 缺失能否用 `qcom-q6apm` + 上游 ASoC 拓扑绕过
2. **USB OTG / 显示输出**：`dwc3` dual-role 已经编进内核，缺的是 typec 相关模块的加载顺序（见 `image/usb/`）
3. **DT 上游化**：把 `dts/` 整理成可 review 的 patch 序列
4. **旁路充电**：`BATT_CHG_CTRL_LIM = 0` 已确认可用，只差一个 UI 入口

提问前请先读 `docs/` 里对应的那篇 —— 绝大多数坑都写下来了，包括我踩坏设备的两次。

历史材料见 `archive/`（早期 pmOS 路线、已弃用的脚本），不需要继续维护多份状态报告。

---

## 许可证

- 代码与脚本：**MIT**（见 [LICENSE](LICENSE)）
- 文档：**CC BY-SA 4.0**（见 [LICENSE-docs](LICENSE-docs)）
- 内核补丁 / 设备树：**GPL-2.0**（与 Linux 内核一致）

## 免责声明

刷机有风险。本仓库记录的操作曾把设备刷成过启动循环（详见事故复盘），
所有命令请先读懂再执行，尤其是 `dd` 和 `fastboot flash`。
