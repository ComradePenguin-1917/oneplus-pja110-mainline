# 快充与高刷移植评估（2026-10-18）

对象：OnePlus Ace 2 Pro / PJA110，当前 A 槽 1-r10 / 6.14-r2，mainline 6.14。
结论先行：

- **高刷（120 Hz）可行，建议先做**。vendor DTBO 里有完整的 60/90/120 Hz 时序和初始化命令，mainline 面板驱动目前只生成了 60 Hz；工作量中等，风险可控（黑屏可 SSH/重启恢复）。
- **快充要分阶段**。PD/PPS 有可能在现有 `qcom-battmgr` 上工作；但 150W SUPERVOOC 依赖 OPlus 私有栈（`oplus_chg` + ADSP VOOC PHY + SC8517/UFCS），mainline 没有对应驱动，完整移植属于逆向工程级别，风险高，不建议一上来就做。

## 1. 高刷现状与证据

### 1.1 当前状态

- DRM 只报一个模式：`1240x2772`，面板节点 `oneplus,aa536-p-3-a0001`，backlight `ae94000.dsi.0`。
- mainline 驱动：`charger-native-a/linux-6.14/drivers/gpu/drm/panel/panel-oneplus-aa536.c`，只有一个 60 Hz `aa536_mode`：
  `clock = (1240+100+8+120) * (2772+20+2+30) * 60 / 1000`，DSC `620x44`、2 slice、10bpc/8bpp。
- 驱动头注明来源：`OnePlus SM8550 live DT, AA536_P_3_A0001 60Hz`。

### 1.2 vendor DTBO 里有什么

从原厂 `dtbo_a.img` 的第 1/3 个 entry 中解出面板节点
`qcom,mdss_dsi_panel_AA536_P_3_A0001_dsc_cmd`，包含 4 组 timing：

| timing | fps | HFP/HBP/HSA | VFP/VBP/VPW | DSI clock | on-command |
| --- | --- | --- | --- | --- | --- |
| `timing@sa_fhd_60` | 60 | 100/120/8 | 20/30/2 | 1.0944 GHz | 1163 B |
| `timing@sa_fhd_90` | 90 | 64/80/8 | 10/16/2 | 1.0944 GHz | 1163 B |
| `timing@sa_fhd_120` | 120 | 64/50/8 | 2/8/2 | 1.0944 GHz | 1163 B |
| `timing@oa_fhd_120` | 120 | 64/50/8 | 2/8/2 | 1.0944 GHz | 1172 B |

公共参数：`1240x2772`、DSC slice 620x44、2 encoder、10bpc/8bpp、`dsi_cmd_mode`、burst mode。
另有 337 B 的 `qcom,mdss-dsi-timing-switch-command`，用于运行中切换时序。

已导出为机器可读文件：`out/geekbench/aa536-vendor-timings.json`；完整节点子树：`out/geekbench/stock-dtbo-panel-charger.json`。

### 1.3 移植路径

1. 从 DTBO 抽出 120 Hz 的 panel 节点（`timing@sa_fhd_120`），转成 DTS；
2. 复用仓库已有生成器（`tools/run_panel_generator.py`、`tools/prepare_generated_panel.py`、`tools/adapt_generated_panel.py`）生成 120 Hz 驱动；
3. 合并进 `panel-oneplus-aa536.c`：`get_modes()` 返回 60/120 两个模式，`prepare/enable` 按模式发送对应 init；若要运行中切换，再发送 337 B 的 timing-switch 命令；
4. DSC 参数不变（620x44、2 slice），但像素时钟要按新时序重算（120 Hz 约 455 MHz，60 Hz 约 232 MHz），确认 DSI PHY/lane 带宽；
5. 用 `modetest`/Phoc 验证，观察 underrun、闪烁、功耗，保留 60 Hz 回退。

风险：

- init 序列写错可能黑屏；可通过 SSH 重启恢复（显示不是启动必需）。
- Iris7（`pxlw,iris` / `pixelworks,iris`）在 mainline 没有驱动；高刷本身不依赖 MEMC，但 vendor 的 120 Hz init 可能隐含 Iris 配置，需要逐条比对。
- 动态切换涉及 MDP/DSI 重配，建议先做“启动时选 120 Hz”，再做运行时切换。

## 2. 快充现状与证据

### 2.1 硬件与 vendor 栈

原厂 DTBO 中的充电相关节点：

- `sc8517-charger@69`（`sc,sc8517-master`）：150W 电荷泵；
- `oplus,adsp-voocphy`：VOOC PHY 在 ADSP 固件侧；
- `oplus,sc2201-ufcs`、`oplus,ufcs-protocol`：UFCS 协议；
- `bq27541-battery@55`：原厂 gauge（mainline 用 `bq28z610`）；
- `bob-tps6128xd@75`：显示/系统 BOB。

vendor ramdisk（`vendor_boot_a.img` 的 vendor fragment，LZ4）里确认存在：

- `lib/modules/oplus_chg.ko`
- `lib/modules/oplus_chg_v2.ko`
- `lib/modules/oplus_chg_symbol.ko`
- `lib/modules/ufcs_class.ko`
- `lib/modules/charger-ulog-glink.ko`
- `lib/modules/msm_drm.ko`

### 2.2 mainline 现状

- `qcom-battmgr` + UCSI 已经能上报 USB/PD：
  `qcom-battmgr-usb` 的 `usb_type` 支持 `SDP DCP CDP ACA C PD PD_DRP PD_PPS BrickID`；
  `ucsi-source-psy` 支持 `PD PD_PPS`；
  `input_current_limit = 1.5 A`，只读（`-r--r--r--`），用户态改不了。
- 没有 `oplus_chg`、没有 SC8517 驱动；上游只有 `bq25980_charger.c`（TI 电荷泵），与本机 DT 里的 SC8517 不是一回事。
- 因此当前只能走 PMIC 的基础充电路径，150W 电荷泵和 UFCS/VOOC 协议都没有被 Linux 接管。

### 2.3 分阶段方案

**阶段 A：把 PD/PPS 的能力测清楚（低风险）**

1. 用原装 150W 充电器，电量放到 20–30%；
2. 插线后读：
   - `qcom-battmgr-usb` 的 `voltage_now`、`current_now`、`usb_type`；
   - `ucsi-source-psy` 的 `voltage_now`、`current_max`、`usb_type`；
   - 电池 `current_now`、`voltage_now`、`temp`。
3. 判断是否拿到 9V/2A 或 PPS；如果只有 5V/1.5A（约 7.5W），说明 PD 协商没生效，需要先修 UCSI/TCPM 路径。

**阶段 B：在不碰电荷泵的前提下提高功率**

- 若 UCSI 能协商到 9V/2A，约 18W，已经比现在快很多；
- 检查 `qcom_battmgr` 是否接受更高的 `input_current_limit`（当前只读，可能需要驱动改动或固件接口）；
- 全程监控电池温度与 `current_now`，不追求数字。

**阶段 C：电荷泵（SC8517）与 SUPERVOOC（高风险）**

- 需要 SC8517 寄存器级驱动 + OPlus 充电状态机（`oplus_chg` 的角色）+ ADSP VOOC PHY 协议；
- vendor 只给了二进制模块，没有源码；可行的路径是从 `oplus_chg.ko`/DTBO 反推寄存器序列，但工作量和风险都很大；
- 在阶段 A/B 没跑通之前，不建议投入 C；也不要把“150W”作为近期目标。

### 2.4 安全边界

- 只用原装充电器和原装电池；不改充电截止电压、不绕过温度保护；
- 任何电荷泵实验先在低功率、低电量、可监控的条件下做；
- 出现异常温升、电池鼓包迹象、反复掉电，立即停止并回退到基础充电。

## 3. 建议顺序

1. **高刷 120 Hz**：先把 vendor timing 变成 mainline 的第二个 mode，做启动时选择，再考虑运行时切换。
2. **快充阶段 A**：电量降下来后用原装充电器实测 PD/PPS 协商结果。
3. 根据 A 的结果决定是否进入 B；C 单独立项评估。

## 4. 证据文件

- `out/geekbench/aa536-vendor-timings.json`：4 组 timing 与命令长度；
- `out/geekbench/stock-dtbo-panel-charger.json`：面板/充电节点的完整子树；
- `out/geekbench/vendor_ramdisk.lz4`：原厂 vendor ramdisk（LZ4），可复现模块清单；
- `charger-native-a/linux-6.14/drivers/gpu/drm/panel/panel-oneplus-aa536.c`：当前 60 Hz 驱动；
- `charger-native-a/linux-6.14/drivers/power/supply/bq25980_charger.c`：上游 TI 电荷泵驱动（非本机 SC8517）。
