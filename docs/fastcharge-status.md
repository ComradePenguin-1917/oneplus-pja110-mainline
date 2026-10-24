# PJA110 快充调试状态

更新时间：2026-10-17。当前只完成只读审计，未写 charger 寄存器、未启用实验性 `charger_init`、未刷写手机。

## 当前真实状态

最近一次手机审计保存在 `out/native-install-20261017/charger-policy-audit/usb-contract-20261017-221456.txt`：

- 电池 `bq28z610-0`：约 7.7V 电池包、75%、Charging、约 +150mA 净电流、约 30.8℃。
- USB 供电 `qcom-battmgr-usb`：在线、约 4.908V、`CURRENT_MAX=900mA`、`CURRENT_NOW=450mA`、`INPUT_CURRENT_LIMIT=1.5A`。
- USB gadget 当前为 high-speed，不能用 USB 调试链路推断充电器快充能力。
- Type-C 当前 `power_operation_mode=3.0A`、PD revision 3.0；partner PD revision 显示 0.0，说明此次连接没有完成可用的 PD 合同证据。
- UCSI source power-supply 报告能力字段 `PD / PD_PPS`，但这是控制器能力 / 描述，不等于本次已协商高压高功率。
- 当前 5V × 0.45A 约 2.2W 输入侧读数，属于普通低功率路径；还不能据此断言充电器或手机硬件不支持快充。

## 路径判断

普通 5V、USB-PD/PPS 和 VOOC/SUPERVOOC 共享 USB-C 物理接口，但协议和控制归属不同：

1. **普通 5V SDP/DCP/CDP**：当前已证明。PMIC-GLINK 暴露 USB power-supply，BQ 电量增长，普通充电工作。
2. **USB-PD/PPS**：Type-C/UCSI 和 PMIC-GLINK 路径出现能力字段，但 partner 合同、PDO、协商电压电流尚未被只读接口完整确认。应先查 contract / PDO / role-switch / TCPM 日志。
3. **VOOC/SUPERVOOC**：通常依赖厂商协议、充电 IC、ADSP/PMIC 服务和温控策略；目前没有可证明本机主线已经实现的协议驱动。不能把 `qcom-battmgr` 的普通 USB telemetry 当成 VOOC 实现。

## 已知安全边界

- 发行版内核明确去除了实验性的 `pja110_charger_init`、SET votes、charge-enable 和 AP gauge handshake；这是有意的，因为此前只在参数为 0 时验证过。
- 不要直接启用旧的 `prepare_charger_init_candidate.py` 产物，不要用 `insmod` 替换运行中的 `qcom_battmgr`，不要热卸载电源 / Wi-Fi 模块。
- 快充测试必须先记录电池温度、SOC、电压、输入电流、USB current limit、type-C 合同和 ADSP 日志，并设置超时 / 过温停止条件。

## 下一步实施顺序

### 阶段 A：只读协议枚举

扩展现有 `check_usb_power_contract.py`，读取：

- `/sys/class/typec/port0`、partner、PDO / alternate-mode / role 文件；
- `ucsi-source-psy-*` 和 `qcom-battmgr-usb` 的所有能力与实际值；
- 内核 `typec|ucsi|tcpm|pd|pdc|charger|battmgr|adsp` 日志；
- power-supply 的 `voltage_now/max`、`current_now/max`、`input_current_limit`；
- ADSP charger_pd / PDR 状态。

输出每次连接的完整快照，不进行 SET。使用普通 5V、PD 充电器、原装充电器分别采样，明确对照组。

### 阶段 B：确认可观测的合同

若能读到 PD source capabilities 和 negotiated contract，建立“请求值—协商值—实际输入—电池净电流”的表格。若 partner 仍显示 0.0 或只有能力字段，先停在协议观测，不进入写寄存器测试。

### 阶段 C：建立最小受控实验

只有在阶段 B 证明协议合同和驱动所有权后，才允许对一个已知安全的只读 / 有界 SET 做实验：

- 默认不超过 5V 路径已验证的输入限值；
- 每次只改变一项，最大持续时间短；
- 温度超过预设阈值、输入电流异常、通信超时或电池状态异常立即恢复；
- 记录写前 / 写后寄存器和 power-supply 状态；
- 实验完成后正常重启，确认基础 5V 充电仍工作。

### 阶段 D：再评估 VOOC/SUPERVOOC

如果 USB-PD/PPS 路径没有合同或驱动证据，VOOC 不应继续盲试。应先从原厂 firmware / ADSP 日志和 Aston 参考实现中确认协议服务、充电 IC、GPIO / I2C / PMIC 所有权，再决定是否移植现有驱动。没有完整终止、热保护、降级和拔线恢复策略，不把实验标成快充支持。

## 验收标准

- 普通 5V 充电在新改动前后均可用，SOC 持续增长。
- PD/PPS 只有在真实 partner contract、协商电压电流及稳定输入读数同时存在时才算“协议路径打通”。
- VOOC/SUPERVOOC 只有在协议握手、功率提升、温度限制、终止 / 再充电和重启恢复均通过后才算完成。
- 所有失败或未实现状态保留为 pending；不能仅凭 `PD_PPS` 能力字符串、`CURRENT_MAX` 或在线标志宣布快充。
