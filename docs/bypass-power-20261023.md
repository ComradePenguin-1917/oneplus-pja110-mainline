# 旁路供电与电池保护记录（2026-10-23）

## 结论先行

**这台机器天然支持旁路供电，不需要额外驱动。**

| 能力 | 状态 | 说明 |
| --- | --- | --- |
| Power Path（电源路径） | ✅ **硬件原生** | USB 直接供系统，电池独立充放电，充满后自动停止 |
| 充电电流抑制（软件旁路） | ✅ **已验证可用** | 设 `BATT_CHG_CTRL_LIM=0`，电池既不充也不放 |
| 真·物理断电池 bypass | ❌ 不支持 | 需要充电 IC 的 bypass 通路，本机 `sc8517` 的 bypass 模式只用于电荷泵直充，不是服务器用途 |

## 一、实测数据

### 1.1 默认行为（100% 满电，未干预）

```
USB 422mA | BAT +95mA | Full | 30.7℃
```

电池仍在微充（浮充）。长期如此会加速电池老化、有鼓包风险。

### 1.2 旁路模式（`BATT_CHG_CTRL_LIM = 0`）

3 分钟连续观察：

```
t= 20s  USB 4.96V 169mA | BAT +13mA 100% (Δ+0 uAh) 30.8C
t= 40s  USB 4.94V 150mA | BAT  -3mA 100% (Δ+0 uAh) 30.7C
t= 60s  USB 4.94V 206mA | BAT  -7mA 100% (Δ+0 uAh) 30.7C
t= 80s  USB 4.94V 181mA | BAT  -9mA 100% (Δ+0 uAh) 30.7C
t=100s  USB 4.95V 172mA | BAT  -9mA 100% (Δ+0 uAh) 30.7C
t=120s  USB 4.95V 178mA | BAT  -9mA 100% (Δ+0 uAh) 30.7C
t=140s  USB 4.95V 181mA | BAT  -9mA 100% (Δ+0 uAh) 30.7C
t=160s  USB 4.95V 194mA | BAT  -9mA 100% (Δ+0 uAh) 30.7C
t=180s  USB 4.94V 150mA | BAT  -9mA 100% (Δ+0 uAh) 30.7C
```

**关键指标：**
- `charge_now` 变化 **+0 uAh** —— 电池完全不参与
- 电池电流 **-9mA** 稳定 —— 接近零（测量噪声）
- USB 持续供 **150-206mA** —— 系统运行所需
- 温度 **30.7℃ 恒定** —— 无发热

**这就是真正的旁路：系统靠 USB 跑，电池躺着不动。**

### 1.3 电流抑制曲线（limit=0 生效过程）

```
基线:        BAT +95mA
limit=0 后:  +66 → +52 → +33 → +23 → +15 → +10 → +4 → 0 → -2 → -9mA
```

电流平滑下降到零并稳定在负值（电池自放电被 USB 侧的微小泄漏抵消）。

## 二、原理

### 2.1 Power Path 硬件

现代手机 PMIC 的充电通路是：

```
USB VBUS ──┬──→ 系统负载（SYS）
           └──→ 充电 IC ──→ 电池（BAT）
```

**系统负载和电池是并联在 VBUS 上的**，所以：
- 插入充电器后，**系统优先由 VBUS 供电**，多余电流才充电池
- 电池充满后，充电 IC 停止充电，系统继续由 VBUS 供电
- **这是硬件行为，不需要任何软件配置**

### 2.2 `BATT_CHG_CTRL_LIM` 的作用

主线 `qcom_battmgr` 定义的 `BATT_CHG_CTRL_LIM (10)` 控制的是**流入电池的电流上限**：

- 设为 3A → 快充（12.5W，见 [fastcharge-fix-20261023.md](fastcharge-fix-20261023.md)）
- 设为 0 → 完全禁止充电 → **软件实现的旁路**

**这不是"断开电池"，而是"禁止充电"**。电池仍在电路中，随时可以放电应对峰值负载。

### 2.3 为什么不是"真 bypass"

真正的 bypass 充电（charge bypass）是**用充电 IC 内部的开关把 VBUS 直接连到 SYS，同时断开电池 FET**。这样电池完全脱离电路，零损耗、零发热。

本机 `sc8517` 电荷泵有 `bypass` 模式：

```c
sc8547_cp_config_bypass_mode()
sc8571_master_cfg_bypass()
nu2205_master_cfg_bypass()
bq25980_master_cfg_bypass()
```

但**这些是电荷泵直充模式**（用于 150W SUPERVOOC 时把高压直接灌入电池），不是服务器场景的"电池脱机"。而且需要 vendor 的 `oplus_chg` 栈才能驱动。

**结论：软件层面的"充电电流归零"已经足够服务器场景使用**，且更安全（电池始终在线，能应对突发负载）。

## 三、服务器模式推荐配置

### 3.1 三种模式

| 模式 | 行为 | 适用 |
| --- | --- | --- |
| `bypass` | 电池完全不动 | 有 UPS、追求电池最长寿命 |
| `balanced N` | 充到 N% 后转旁路 | **推荐**，兼顾寿命与断电缓冲 |
| `full` | 正常充满 | 会带出门用 |

### 3.2 使用

```sh
# 查看状态
sudo battery-mode.sh status

# 均衡模式（充到 80% 后转旁路）
sudo battery-mode.sh balanced 80

# 完全旁路
sudo battery-mode.sh bypass

# 恢复正常充电
sudo battery-mode.sh full
```

### 3.3 自动守护（推荐）

`battery-guard.sh` 配合定时器，每 5 分钟检查 SOC：

- SOC ≥ 上限 → 转旁路
- SOC < 上限-5% → 恢复快充

安装定时器：

```sh
sudo tee /etc/systemd/system/battery-guard.service > /dev/null <<'EOF'
[Unit]
Description=PJA110 battery guard

[Service]
Type=oneshot
ExecStart=/usr/local/bin/battery-guard.sh
EOF

sudo tee /etc/systemd/system/battery-guard.timer > /dev/null <<'EOF'
[Unit]
Description=PJA110 battery guard timer

[Timer]
OnBootSec=5min
OnUnitActiveSec=5min

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable --now battery-guard.timer
```

### 3.4 为什么推荐 80%

| 长期存放 SOC | 容量保持率（1 年后）|
| --- | --- |
| 100% | ~70-80% |
| 80% | ~90-95% |
| 50% | ~95-98% |

锂电池在 **40-60% 区间**寿命最长。80% 是寿命与实用性的折中——既留了 20% 的断电缓冲，又避免了满电应力。

## 四、安全说明

- **`BATT_CHG_CTRL_LIM=0` 不绕过任何保护**。ADSP 固件仍监控温度、电压、电流；如果系统负载突增导致电池需要放电，硬件会正常工作
- **不会导致无法开机**。设置只影响充电，重启后固件恢复默认（除非 `fastcharge.service` 又设了值）
- **断电时电池仍在**。因为是"禁止充电"而非"断开电池"，拔掉适配器后手机会立即切到电池供电，不会关机
- **温度实测 30.7℃ 恒定**，无异常发热

## 五、相关命令速查

```sh
# 当前电池状态
cat /sys/class/power_supply/bq28z610-0/{capacity,current_now,voltage_now,temp,status}

# 当前充电限制（uA）
cat /sys/class/power_supply/qcom-battmgr-usb/input_current_limit

# 手动下发充电电流（uA）
echo "31 10 3000000" | sudo tee /sys/kernel/debug/qcom_battmgr/raw_set  # 3A 快充
echo "31 10 0"       | sudo tee /sys/kernel/debug/qcom_battmgr/raw_set  # 旁路

# 模式状态
cat /run/battery-mode.state
```

## 六、遗留问题

| 项 | 说明 |
| --- | --- |
| 拔插充电器后需重设 | ADSP 可能重置限制，`battery-guard.timer` 会自动恢复 |
| 未实现充放电阈值控制 | 主线协议只有 `BATT_CHG_CTRL_LIM`，没有 `CHARGE_CONTROL_START/END_THRESHOLD`（那是 x1e80100 的 `QCOM_BATTMGR_X1E80100` variant 特有）|
| 真 bypass 未实现 | 需 vendor `oplus_chg` + `sc8517` 驱动，工作量极大且无必要 |

> 注：上游正在为 x1e80100 添加 `charge_control_start_threshold` / `charge_control_end_threshold` 属性（[PATCH v4 7/8](https://lore.kernel.org/linux-devicetree/20250915-qcom_battmgr_update-v4-0-6f6464a41afe@oss.qualcomm.com/)），但那是 X1E80100 平台的固件特性。SM8550 是否支持需要实测——可以试发对应 opcode 探测。
