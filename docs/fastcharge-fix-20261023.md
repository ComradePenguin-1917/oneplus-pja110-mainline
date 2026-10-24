# 快充修复记录（2026-10-23）

## 结论先行

**问题：充电功率长期只有 1.2W，12 小时才能充满。**

**根因：主线 `qcom_battmgr` 驱动定义了控制充电电流的常量和 opcode，但从未使用，导致 Linux 永远无法告诉 ADSP 固件"可以充快点"。**

**修复：通过 debugfs 下发 `BATTMGR_BAT_PROPERTY_SET (0x31)` + `BATT_CHG_CTRL_LIM (10)` 设置电池充电电流。**

**效果：**

| 指标 | 修复前 | 修复后 | 提升 |
| --- | --- | --- | --- |
| USB 输入功率 | 2.34 W | **12.5 W** | **5.3×** |
| 电池净电流 | 165 mA | **1384 mA** | **8.4×** |
| 预计充满 | 12-15 小时 | **约 1.5-2 小时** | ~8× |
| 温度 | 28.3℃ | 31.4℃ | 温和 |

实测 2 分钟稳定维持 12.5W，无过热、无异常。

## 一、排查过程（走过的弯路）

### 1.1 最初的错误判断

看到 `usb_type = SDP` 和电流 460mA，判断为"ADSP 把端口分类成 SDP 所以限流 500mA"。

**这是错的。** `usb_type` 显示 SDP 是因为驱动读错了属性（见下文 bug 1），不是真实分类。

### 1.2 验证过但无效的方向

| 方向 | 做法 | 结果 |
| --- | --- | --- |
| 换 PD 充电器 | 原装 150W + 第三方 PD | ❌ RDO 都是 `0x1304B12C`（请求 5V/3A），电流不变 |
| 省电模式 | 关闭 WiFi power_save | ❌ 与本问题无关 |
| USB 输入限流 | 写 `input_current_limit` | ❌ ADSP 接受命令但不采纳（PD 充电器上）|
| 喂看门狗 | 发 vendor 的 `0x00010006` | ❌ 超时 |
| 移植 `oplus_chg.ko` | 评估后放弃（见 §4） | ❌ 不可行 |

### 1.3 关键的社区线索

搜索 LKML 找到两组直接相关的补丁：

1. **[qcom_battmgr: report the USB type from USB_ADAP_TYPE](https://patchew.org/linux/20261007123932.1664-1-26rote@gmail.com/)** — Joonhoe Kim
   > "On SM8350 and SM8550 class firmware the USB power supply reads its usb_type from the USB_TYPE property. On a Kaanapali (SM8850) tablet that property is 1 (SDP) whatever is plugged in, while USB_ADAP_TYPE reports the adapter."

2. **[qcom_battmgr: Allow setting the USB input current limit](https://patchew.org/linux/20261007123939.1679-1-26rote@gmail.com/)** — Joonhoe Kim
   > "The SM8350 class USB power supply reports input_current_limit, but does not allow writing it, although the firmware accepts BATTMGR_USB_PROPERTY_SET for USB_INPUT_CURR_LIMIT"
   >
   > "With a **USB PD charger the firmware keeps its own limit and the written value is not reflected**"

**第 2 条的最后一句是决定性的**——作者也发现 PD 充电器上写 USB 限流无效。这提示我：**限流不在 USB 侧**。

3. **[power: supply: qcom_smbx: add SMB5 support](https://lore.kernel.org/linux-devicetree/20260813-submit-qcom-smbx-send-v1-v3-0-27be0091d7c7@snyders.xyz/)** — Robin Snyders
   - SM8550 的充电 IC 是 SMB5 系列（PM8150B/PM7250B），主线驱动正在开发中但**尚未合入**

## 二、修复的三个驱动 bug

这些 bug 都有上游补丁佐证，不是我编造的：

### Bug 1：`usb_type` 读错属性

```c
// 修复前（drivers/power/supply/qcom_battmgr.c）
static const u8 sm8350_usb_prop_map[] = {
        ...
        [POWER_SUPPLY_PROP_USB_TYPE] = USB_TYPE,        // ❌ 永远是 1 (SDP)
};

// 修复后
        [POWER_SUPPLY_PROP_USB_TYPE] = USB_ADAP_TYPE,   // ✅ 真实适配器类型
```

**效果**：`usb_type` 从 `[SDP]` 变成 `[PD_PPS]`，与 `ucsi-source-psy` 一致。

### Bug 2：callback 缺 SET 分支

```c
static void qcom_battmgr_sm8350_callback(...)
{
        switch (opcode) {
        case BATTMGR_REQUEST_NOTIFICATION:
        case BATTMGR_BAT_PROPERTY_SET:      // ← 新增
        case BATTMGR_USB_PROPERTY_SET:      // ← 新增
                battmgr->error = 0;
                break;
```

**效果**：`unknown message 0x33` / `0x31` 消失。ADSP 的响应被正确识别（虽然等待仍会超时，因为 `complete()` 只在特定分支调用）。

### Bug 3：没有 `set_property`

```c
// 新增
static int qcom_battmgr_usb_set_property(struct power_supply *psy, ...)
{
        ...
        ret = qcom_battmgr_request_property(battmgr, BATTMGR_USB_PROPERTY_SET,
                                            USB_INPUT_CURR_LIMIT, pval->intval);
        ...
}

static const struct power_supply_desc sm8350_usb_psy_desc = {
        ...
        .set_property = qcom_battmgr_usb_set_property,
        .property_is_writeable = qcom_battmgr_usb_is_writeable,
```

**效果**：`/sys/class/power_supply/qcom-battmgr-usb/input_current_limit` 从 `-r--r--r--` 变为可写。

## 三、真正的解决办法

### 3.1 关键发现

主线驱动里有这些**从未被使用**的定义：

```c
#define BATTMGR_BAT_PROPERTY_SET        0x31   // 定义了，但代码里从不用
#define BATT_CHG_CTRL_LIM               10     // 电池充电电流限制
#define BATT_CHG_CTRL_LIM_MAX           11     // 最大可设值
```

**`BATT_CHG_CTRL_LIM` 才是控制充电电流的正确属性**，不是 USB 侧的 `USB_INPUT_CURR_LIMIT`。

### 3.2 下发命令

```sh
# opcode=0x31 (BAT_PROPERTY_SET), prop=10 (BATT_CHG_CTRL_LIM), value=3000000 uA
echo "31 10 3000000" > /sys/kernel/debug/qcom_battmgr/raw_set
```

**立即生效**：USB 电流从 460mA 跳到 2809mA。

### 3.3 为什么命令"超时"但实际生效

`raw_set` 返回 `-110 (ETIMEDOUT)`，因为 callback 的 `complete()` 没有被调用。但 **ADSP 已经执行了命令**。

这是主线的另一个设计缺陷：`BATTMGR_BAT_PROPERTY_SET` 的响应没有被 `out_complete` 路径处理。命令能生效，只是因为超时不阻止固件执行。

## 四、为什么不能移植 vendor 的 oplus_chg.ko

| 障碍 | 数据 |
| --- | --- |
| vermagic 不匹配 | vendor = `5.15.123`，我们 = `6.14.0` |
| modversions 不匹配 | vendor 启用，我们 `CONFIG_MODVERSIONS is not set` |
| 依赖缺失 | 12 个依赖中 7 个不在 vendor_dlkm（`oplusboot`/`boot_mode`/`oplus_project`/`smem`/`device_info`/`test-kit`/vendor 版 `pmic_glink`）|
| 无源码 | 6.7MB 二进制，API 跨代（`class_create` 签名变化、`platform_driver.remove` 改 void 等）|

**结论：二进制模块无法重编译，这条路不可行。**

但我们**不需要它**——主线协议里已经有 `BATT_CHG_CTRL_LIM`，只是没实现。

## 五、部署方式

### 5.1 手动

```sh
sudo bash /usr/local/bin/enable-fastcharge.sh          # 3A（默认）
sudo bash /usr/local/bin/enable-fastcharge.sh 2000000  # 2A
sudo bash /usr/local/bin/enable-fastcharge.sh 0        # 恢复默认
```

### 5.2 开机自动

已创建 `fastcharge.service`：

```ini
[Unit]
Description=PJA110 fast charge enable (set battery charge current limit)
After=multi-user.target

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/enable-fastcharge.sh 3000000

[Install]
WantedBy=multi-user.target
```

```sh
systemctl enable --now fastcharge.service
```

### 5.3 前置条件

需要带 debugfs 支持的 `qcom_battmgr` 模块：

```
out/ut-test/qcom-battmgr-v5.ko   ← 已安装到设备
```

该模块包含三项修复 + debugfs 接口（`raw_get` / `raw_set` / `last_get` / `kick_wdt` / `set_input_current_limit`）。

## 六、安全性

- **ADSP 固件保留完全控制权**：我们只是请求更高的充电电流，固件仍会在温度过高、电池异常时自行降级
- **温度实测**：2 分钟内从 28.3℃ 升到 31.4℃，升温速率温和
- **脚本内置上限**：拒绝超过 4A 的请求
- **可随时恢复**：`enable-fastcharge.sh 0`
- **已验证 2 分钟稳定**，无过热、无 OVC、无异常断电

## 七、待完善

| 项 | 说明 |
| --- | --- |
| 服务启动时机 | 目前 `After=multi-user.target`，若 `qcom_battmgr` 未加载会失败。可加 `ExecStartPre` 等待 |
| 拔插充电器 | 重新插拔后需要重新下发（ADSP 可能重置）。可考虑 udev 规则 |
| 上限探测 | 未测试 `BATT_CHG_CTRL_LIM_MAX (11)` 的实际值，理论可更高 |
| 电池温度联动 | 未实现高温自动降级（依赖固件自身保护）|

## 八、证据与产物

| 文件 | 说明 |
| --- | --- |
| `out/ut-test/qcom-battmgr-v5.ko` | 修复后的模块（含 debugfs） |
| `tools/enable-fastcharge.sh` | 启用脚本 |
| `docs/fastcharge-status.md` | 原始调研（已被本文取代的核心结论部分） |
| `docs/fast-charge-high-refresh-assessment.md` | 早期评估（§2 快充部分已被本文更新） |

### 实测数据（2 分钟稳定监控）

```
t= 10s  USB 4.46V 2809mA (12.5W)  BAT +1032mA 7.80V 29.2C 28%
t= 40s  USB 4.45V 2806mA (12.5W)  BAT +1350mA 7.81V 29.8C 29%
t= 80s  USB 4.46V 2809mA (12.5W)  BAT +1392mA 7.81V 30.3C 30%
t=120s  USB 4.46V 2809mA (12.5W)  BAT +1394mA 7.81V 30.7C 30%
```

## 九、遗留：为什么 USB 侧写入无效

写 `USB_INPUT_CURR_LIMIT (prop 5)` 后 ADSP 接受命令但功率不变，写 `BATT_CHG_CTRL_LIM (prop 10)` 立即生效。

推测：ADSP 的充电状态机以电池侧限制为准，USB 侧限制只作为输入参考，实际由电池路径决定。这与上游补丁作者的实测一致（PD 充电器上 USB 限流写入不被反映）。

**这也解释了为什么 150W SUPERVOOC 的路径是电荷泵直充电池**——USB 侧限流对快充意义有限，控制点在电池侧。

## 十、开机时序修复与结果校验（2026-10-24）

### 10.1 原方案的两个缺陷

```ini
# 旧 unit
[Unit]
After=multi-user.target
Wants=multi-user.target
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/enable-fastcharge.sh 3000000
```

旧脚本内部 `sleep 3` 后直接打印状态，**从不校验写入结果**。

| 缺陷 | 后果 |
| --- | --- |
| `sleep 3` 硬等待 | `systemd-analyze blame` 显示 **4.105s**，全是白等 |
| 把超时当成功 | `raw_set` 返回 -110 被 `if` 吞掉，**真失败也显示成功** |
| 无前置条件检查 | ADSP 未就绪时写入返回 -104，脚本照样报"已下发" |
| 无插拔处理 | ADSP 可能在重插时复位限制，快充静默失效 |

### 10.2 驱动增强：`last_set`

`sleep` 换成校验需要能读回结果，但 debugfs 原来只有 `last_get`（USB 属性专用），无法回读 `BATT_CHG_CTRL_LIM`。

在 `qcom_battmgr` 里加一个 `last_set` 记录最近一次写入：

```
$ cat /sys/kernel/debug/qcom_battmgr/last_set
op=0x31 prop=10 val=3000000 rc=-110
```

**关键认知**：这颗固件不回复 ack，所以 `rc=-110`（ETIMEDOUT）是**正常成功值**。
`rc=-104`（ECONNRESET）才是 ADSP 未就绪/通道断开。

### 10.3 新脚本：等待而非睡眠

```bash
# 前置条件，逐项等待（默认 20s 上限）
cond_debugfs() { [ -w "$D" ] && [ -r "$LS" ]; }
cond_adsp()    { for f in /sys/class/remoteproc/remoteproc*/state; do
                     [ "$(cat "$f")" = running ] && return 0; done; return 1; }

wait_for "qcom_battmgr debugfs" 20 cond_debugfs || die ...
wait_for "ADSP"                 20 cond_adsp    || warn ...
```

写入后读 `last_set` 校验 `prop=10`、`val=<请求值>`、`rc ∈ {0, -110}`。

正常情况 1.2 秒完成；只有加了 `FASTCHARGE_VERIFY=1` 才额外观察电流上升
（接 PC 的 SDP 口只有 450mA，永远涨不到阈值，所以默认不做这项等待）。

### 10.4 新 unit：不再排到启动末尾

```ini
[Unit]
After=systemd-modules-load.service
Wants=systemd-modules-load.service
[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/local/bin/enable-fastcharge.sh 3000000
TimeoutStartSec=60
[Install]
WantedBy=multi-user.target
```

去掉 `After=multi-user.target`（那会把它排到启动流程末尾）。
ADSP 就绪由脚本内部等待，不依赖 unit 排序。

### 10.5 插拔处理

`/etc/udev/rules.d/90-pja110-fastcharge.rules`：

```
ACTION=="change", SUBSYSTEM=="power_supply", KERNEL=="qcom-battmgr-usb", \
  ENV{POWER_SUPPLY_ONLINE}=="1", \
  RUN+="/usr/bin/systemctl --no-block try-restart fastcharge.service"
```

`try-restart` 保证服务未启用时不会被动拉起。

### 10.6 独立日志

本机 journald 收不到 unit 的 stdout（环境问题：用一个只 `echo` 的临时 unit
验证过同样收不到）。因此脚本同时写独立日志：

```
/var/log/pja110-fastcharge.log
  （超过 64 KB 轮转一次为 .log.1）
```

开机后的实际记录示例：

```
2026-10-24 14:37:15 === 设置前 ===
2026-10-24 14:37:15   USB 4.91V  450mA (2.21W)   BAT  -256mA @ 7.88V (-2.02W)
2026-10-24 14:37:15 === 下发 BATT_CHG_CTRL_LIM = 3000000 uA ===
2026-10-24 14:37:16   last_set: op=0x31 prop=10 val=3000000 rc=-110
2026-10-24 14:37:16 === 设置后 ===
2026-10-24 14:37:16   SOC 57%  温度 33.8℃  状态 Discharging
2026-10-24 14:37:16 ✅ 已生效（rc=-110 是此固件不 ack 的正常现象）
```

### 10.7 结果

| 指标 | 修复前 | 修复后 |
| --- | --- | --- |
| `fastcharge.service` 耗时 | 4.105 s | **1.178 s** |
| 总启动时间 | — | 4.770 s（kernel 1.199 + userspace 3.570）|
| 桌面就绪 | — | 3.049 s |
| 写入结果可验证 | ❌ | ✅ `last_set` |
| 失败可识别 | ❌ | ✅ rc 判定 |
| 插拔后自动重下发 | ❌ | ✅ udev |
| 开机日志可追溯 | ❌ | ✅ 独立日志文件 |

开机验证：`Result=success`、`ExecMainStatus=0`、
`last_set` 中有开机时刻的写入记录、日志文件时间戳对得上。

### 10.8 产物

| 文件 | 说明 |
| --- | --- |
| `tools/enable-fastcharge.sh` | 新脚本（等待 + 校验 + 日志） |
| `tools/fastcharge.service` | 新 unit |
| `tools/90-pja110-fastcharge.rules` | 插拔触发 |
| `out/pkg/pja110-kernel-mods_6.14.0-oneplus-PJA110-2_arm64.deb` | 含 `last_set` 的模块包 |
