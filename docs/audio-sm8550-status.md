# SM8550 音频移植记录（PJA110）

更新：2026-10-21。状态：**DTS 层完成，声卡与 mixer 可用；喇叭仍未出声，卡在 SoundWire slave 无法进入 ATTACHED。**

## 0. 最重要的一句

**枚举成功（能读到芯片 ID），但 Device Number 分配失败，slave 永远停在 `UNATTACHED`。** 这是当前唯一卡点，其余环节均已验证正确。

```
/sys/bus/soundwire/devices/sdw:1:0:0217:0204:00:0/modalias = sdw:m0217p0204v02c00   ← ID 读到，枚举成功
/sys/bus/soundwire/devices/sdw:1:0:0217:0204:00:0/dev_num  ← 文件不存在，Device Number 从未分配
status = UNATTACHED
```

已用 `devmem` 直接读写硬件寄存器排除的因素：供电（已 enabled）、SD_N 引脚（已强制输出高）、引脚复用（function 正确）、SoundWire 帧参数（与上游逐项相同）、端口分配、驱动版本差异。

## 1. 各环节验证状态

| 环节 | 状态 | 证据 |
| --- | --- | --- |
| SoundWire 控制器 probe | ✅ | `Qualcomm Soundwire controller v2.0.0 Registered` |
| 设备 ID 枚举 | ✅ | `modalias = sdw:m0217p0204v02c00` |
| wsa884x 驱动绑定 | ✅ | `driver -> wsa884x-codec` |
| 供电 `vreg_l3g_1p2` | ✅ | `users=2 state=enabled`（修复前是 `users=0 disabled`） |
| 声卡创建 | ✅ | `card 0: Pro [OnePlus Ace 2 Pro]` |
| PCM 设备 | ✅ | MultiMedia1/2 Playback、MultiMedia3/4 Capture |
| mixer 控件 | ✅ | 86 个 |
| 引脚复用 | ✅ | gpio10/11=wsa_swr_clk/data；gpio17/18=function 1 (GPIO) |
| SD_N 电平 | ✅ | 强制后 `CFG=0xE01 VAL=0x3`（OE 使能、输出高） |
| **slave ATTACHED** | ❌ | `UNATTACHED`、无 `dev_num` |
| **实际播放** | ❌ | `aplay: pcm_write: write error: I/O error` |

## 2. 本轮修掉的两个真实 Bug

### 2.1 `vdd-io-supply` 引用了错误的 regulator（已修复）

| 项目 | 值 |
| --- | --- |
| 原写 | `vdd-io-supply = <0x1ac>` → 实际是 `vreg_l2g_1p2` ❌ |
| 正确 | `vdd-io-supply = <0x7b>` → `vreg_l3g_1p2` ✅ |

症状：`vreg_l3g_1p2` 的 `num_users=0`、`state=disabled`，codec 完全没有 IO 供电。修复后 `users=2 state=enabled`，deferred probe 也消失了。

### 2.2 speaker pinctrl 节点结构错误（已修复）

标签原本打在了嵌套的 `config` 子节点上，导致 `pinctrl-0` 指向错误节点，SoundWire 控制器卡在：

```
platform 6b10000.soundwire: deferred probe pending:
  wait for supplier /soc@0/pinctrl@6e80000/wsa-swr-active-state
```

改成上游 `sm8550-qrd.dts` 的写法（标签打在状态节点本身、属性直接挂在状态节点上）后恢复正常。


## 3. 五条 DTS 补丁（`source-patches.json`）

除原有的 bob1 电压修正、uart14 蓝牙外，新增三条：

### 3.1 swr0 启用 + 两个扬声器放大器

```dts
soundwire@6b10000 {                       /* swr0, WSA */
    status = "okay";

    spk_left: speaker@0,0 {
        compatible = "sdw20217020400";
        reg = <0x00 0x00>;
        pinctrl-names = "default";
        pinctrl-0 = <&spkr1_sd_n>;
        powerdown-gpios = <0x9d 0x11 0x01>;   /* lpass_tlmm gpio17, ACTIVE_LOW */
        #sound-dai-cells = <0x00>;
        sound-name-prefix = "SpkrLeft";
        vdd-1p8-supply = <0xc8>;              /* vreg_l15b_1p8 */
        vdd-io-supply = <0x1ac>;              /* vreg_l3g_1p2 */
    };

    spk_right: speaker@0,1 {
        compatible = "sdw20217020400";
        reg = <0x00 0x01>;
        pinctrl-names = "default";
        pinctrl-0 = <&spkr2_sd_n>;
        powerdown-gpios = <0x9d 0x12 0x01>;   /* lpass_tlmm gpio18 */
        #sound-dai-cells = <0x00>;
        sound-name-prefix = "SpkrRight";
        vdd-1p8-supply = <0xc8>;
        vdd-io-supply = <0x1ac>;
    };
};
```

**注意：`qcom,port-mapping` 故意省略。** 原厂 DTB 的 `qcom,swr-wsa-port-params` 编码与 mainline 的静态端口映射不同义；按 12×u16 → 6×u32 解码得到 `1,3,5,0,6,0` / `2,4,21,9,13,25`，其中 21、25 超出硬件端口范围 1–14，触发 `All ports busy` / `-EBUSY`。省略后驱动用 `find_first_zero_bit()` 自动分配，问题消失。

### 3.2 sound 卡节点

```dts
sound {
    compatible = "qcom,sm8550-sndcard", "qcom,sm8450-sndcard";
    model = "OnePlus Ace 2 Pro";
    audio-routing = "SpkrLeft IN", "WSA_SPK1 OUT",
                    "SpkrRight IN", "WSA_SPK2 OUT";

    wsa-dai-link {
        link-name = "WSA Playback";
        cpu      { sound-dai = <0x159 0x69>; }              /* q6apmbedai WSA_CODEC_DMA_RX_0 = 105 */
        codec    { sound-dai = <&spk_left>, <&spk_right>, <0x15d 0x00>, <0x99 0x00>; };
        platform { sound-dai = <0x157>; };                  /* q6apm */
    };

    va-dai-link {
        link-name = "VA Capture";
        cpu      { sound-dai = <0x159 0x78>; }              /* TX_CODEC_DMA_TX_3 = 120 */
        codec    { sound-dai = <0x94 0x00>; };              /* lpass_vamacro */
        platform { sound-dai = <0x157>; };
    };
};
```

phandle 对照：`q6apmbedai`=0x159、`q6apm`=0x157、`swr0`=0x15d、`lpass_wsamacro`=0x99、`lpass_vamacro`=0x94。

### 3.3 扬声器 SD_N 引脚复用

```dts
pinctrl@6e80000 {                          /* lpass_tlmm */
    spkr-1-sd-n-active-state {
        spkr1_sd_n: config {
            pins = "gpio17";
            function = "gpio";
            drive-strength = <16>;
            bias-disable;
            output-low;
        };
    };
    spkr-2-sd-n-active-state {
        spkr2_sd_n: config {
            pins = "gpio18";
            function = "gpio";
            drive-strength = <16>;
            bias-disable;
            output-low;
        };
    };
};
```

**这三条 pin 配置原本完全缺失**（`gpio17`/`gpio18` 在整份 DTB 里没有任何 pinctrl 状态），导致放大器 SD_N 使能脚从未被设为 GPIO。补上后 `pinmux-pins` 显示正确归属。

## 4. 关键的固件依赖：topology 文件

声卡首次创建失败，报：

```
qcom-apm: Direct firmware load for qcom/sm8550/OnePlus Ace 2 Pro-tplg.bin failed with error -2
qcom-apm: ASoC: error at snd_soc_component_probe: -2
snd-sc8280xp sound: probe with driver snd-sc8280xp failed with error -2
```

文件名由驱动拼装（`sound/soc/qcom/qdsp6/topology.c:1295`）：

```c
kasprintf(GFP_KERNEL, "qcom/%s/%s-tplg.bin", card->driver_name, card->name)
```

即 `qcom/sm8550/<声卡名>-tplg.bin`，声卡名来自 DT `model`。

**解决**：设备上已有 `SM8550-QRD-tplg.bin.zst`、`SM8550-HDK-tplg.bin.zst`（二者字节完全相同）。内核不支持压缩固件，必须解压后按声卡名复制：

```sh
cd /lib/firmware/qcom/sm8550
zstd -d -f SM8550-QRD-tplg.bin.zst -o SM8550-QRD-tplg.bin
cp SM8550-QRD-tplg.bin 'OnePlus Ace 2 Pro-tplg.bin'
```

之后声卡立即创建成功。**这是音频能走到 mixer 层的必要条件。**

## 5. 用户态依赖（离线安装）

系统里缺 `libasound2`（只有 `libasound2-data`）、`alsa-utils`、`alsa-ucm-conf`。WiFi 不稳，故离线装：

| 包 | 大小 |
| --- | --- |
| `libasound2t64_1.2.11-1ubuntu0.3_arm64.deb` | 386 KB |
| `libatopology2t64_1.2.11-1ubuntu0.3_arm64.deb` | 51 KB |
| `alsa-utils_1.2.9-1ubuntu5_arm64.deb` | 1.2 MB |
| `alsa-ucm-conf_1.2.10-1ubuntu5.15_all.deb` | 69 KB |
| `libfftw3-single3_3.3.10-1ubuntu3_arm64.deb` | 570 KB |
| `libsamplerate0_0.2.2-4build1_arm64.deb` | 1.3 MB |

存放在 `out/ut-test/debs/`。装好后 `aplay -l` 可见 4 个 PCM 设备。

**没有 SM8550 的 UCM 配置**（`/usr/share/alsa/ucm2/` 只有 `codecs/qcom-lpass`，没有板级配置），因此路由需手动用 amixer 设置。

## 6. 必需的手动 mixer 路由

```sh
amixer -c 0 cset numid=64 on,on   # WSA_CODEC_DMA_RX_0 Audio Mixer MultiMedia1
amixer -c 0 cset numid=3  on      # SpkrLeft  DAC Switch
amixer -c 0 cset numid=4  on      # SpkrLeft  COMP Switch
amixer -c 0 cset numid=5  on      # SpkrLeft  BOOST Switch
amixer -c 0 cset numid=11 on      # SpkrRight DAC Switch
amixer -c 0 cset numid=12 on      # SpkrRight COMP Switch
amixer -c 0 cset numid=13 on      # SpkrRight BOOST Switch
amixer -c 0 cset numid=1  12      # SpkrLeft  PA Volume (max 17)
amixer -c 0 cset numid=9  12      # SpkrRight PA Volume
```

不做路由时内核警告：`no backend DAIs enabled for MultiMedia1 Playback, possibly missing ALSA mixer-based routing or UCM profile`。

## 7. 卡点：SoundWire slave 停在 UNATTACHED

### 7.1 现象

播放时：

```
aplay: pcm_write:2146: write error: Input/output error
```

dmesg：

```
qcom-soundwire 6b10000.soundwire: qcom_swrm_irq_handler: SWR bus clsh detected
qcom-soundwire 6b10000.soundwire: qcom_swrm_irq_handler: SWR CMD error, fifo status 0x4e00c10x, flushing fifo
qcom-soundwire 6b10000.soundwire: qcom_swrm_irq_handler: SWR read FIFO underflow fifo status 0x4000000f
```

### 7.2 寄存器实证

通过 `/sys/kernel/debug/soundwire/master-1-0/qualcomm-sdw/qualcomm-registers`（5164 行寄存器转储）读取：

| 寄存器 | 地址 | 值 | 含义 |
| --- | --- | --- | --- |
| `INTERRUPT_STATUS` | 0x5000 | **0x08** | BIT(3) = `MASTER_CLASH_DET` 持续置位 |
| `CMD_FIFO_STATUS` | 0x5050 | 0x4000000f | 命令 FIFO 有残留/错误 |
| `MCP_SLV_STATUS` | 0x1090 | **0x00** | 无 slave 被报告为在线 |

而 sysfs 里两个 slave 设备仍然存在、驱动仍绑定 —— 即**枚举成功之后 slave 掉线了**。

读 slave 寄存器（`.../sdw:1:0:0217:0204:00:0/registers`）会**无限阻塞**，进一步证明总线已无响应。

### 7.3 引脚与时钟均已排除

`pinmux-pins` 显示归属正确，且已进一步在**寄存器级**逐个解码确认（注意 `LPI_GPIO_FUNCTION_MASK = GENMASK(5,2)`，不是 bit[3:0]）：

| 引脚 | CFG | bit[5:2] 功能 | bit9 OE | VALUE bit1 | 判定 |
| --- | --- | --- | --- | --- | --- |
| gpio10 (swr clk) | `0xC08` | `2` = wsa_swr_clk | — | — | ✅ |
| gpio11 (swr data) | `0xC0A` | `2` = wsa_swr_data | — | — | ✅ |
| gpio17 (SpkrLeft SD_N) | `0xE01` | `0` = gpio | `1` | `1`（高） | ✅ |
| gpio18 (SpkrRight SD_N) | `0xE01` | `0` = gpio | `1` | `1`（高） | ✅ |

`LPI_PINGROUP` 的 funcs 数组是 `{gpio, f1, f2, f3, f4}`，因此 gpio10/11 的 `wsa_swr_*` 索引是 **2**、gpio17/18 的 `gpio` 索引是 **0**，与实测完全吻合。

处理器件侧同样确认正常（仅在控制器 runtime **active** 时可读；`suspended` 时读回全 0，不能当作掉电证据）：

```
WSA SWR_CONTROL (0x6b00008) = 0x01   → BIT(0) CLK_EN=1，BIT(1) RST_EN=0（复位已释放）
SWRM_V2_0_CLK_CTRL (0x5060) = 0x01   → BIT(0) CLK_START 已置位
SWRM_V2_0_LINK_STATUS (0x5064) = 0x2081 → BIT(0) FRM_GEN_ENABLED=1（帧发生器运行中）
WSA_MACRO_MCLK_FREQ = 19200000（与驱动硬编码一致）
```

**结论：SoundWire 时钟在跑、帧发生器在跑、引脚功能正确、SD_N 已输出高电平（放大器上电）。** 因此"总线无时钟/引脚错/SD_N 未释放"这几类原因全部排除。帧参数（`qcom,ports-*`）也已与上游 `sm8550.dtsi` 逐项比对，完全一致。
### 7.4 本轮新增的被证伪假设（勿重复）

| 假设 | 做法 | 结果 |
| --- | --- | --- |
| WSA macro autosuspend 关闭 mclk 导致总线死掉 | 改 lpass-wsa-macro.c 去掉 autosuspend，替换模块 | 无效。实测播放时 wsa=active swr=active，电源管理本来就正常 |
| soundwire 控制器 autosuspend 竞态 | 去掉 pm_runtime_set_autosuspend_delay | 无效（clash 仍在） |
| soundwire: qcom: wait for the interrupt thread 上游补丁 | 在 swrm_runtime_suspend 前加 synchronize_irq(ctrl->irq) | 编译加载成功，无效 |
| WSA884x 缺少 clk_stop_mode1 | 仿 wsa881x.c 设 pdev->prop.clk_stop_mode1 = true | 无效（反而 SWR 错误增多），已回退 |
| SD_N 引脚死锁（放大器未上电→slave 不 attach→probe 不跑） | pinctrl 改 output-high，再用 devmem 强制 CFG=0xE01 VAL=0x3 | **证伪**：GPIO 确认输出高、放大器已上电，slave 仍 UNATTACHED |
| devmem 读 WSA macro 寄存器为 0 说明被掉电 | 读  x6b00000/ x6b00008 | **误判**：即使 WSA macro untime_status=active，该区域仍读回 0，说明 devmem 读不到 LPASS 内部寄存器，不能作为电源证据 |

**注意**：/tmp 下的驱动备份会随 WSL 重启丢失。恢复原始驱动应从 ~/.cache/linux-6.14.tar.xz 重新提取：

`sh
tar -xf ~/.cache/linux-6.14.tar.xz linux-6.14/drivers/soundwire/qcom.c \
    linux-6.14/sound/soc/codecs/lpass-wsa-macro.c linux-6.14/sound/soc/codecs/wsa884x.c
`

### 7.5 devmem 可用的寄存器地址（实测）

| 用途 | 地址 |
| --- | --- |
| SoundWire INTERRUPT_STATUS |  x6b15000 |
| SoundWire MCP_SLV_STATUS |  x6b11090 |
| SoundWire MCP_STATUS |  x6b1104c |
| LPASS TLMM gpioN CFG |  x6e80000 + 0x1000*N |
| LPASS TLMM gpioN VALUE |  x6e80000 + 0x1000*N + 4 |

CFG bit9 = 输出使能，VALUE bit1 = 输出电平。

**不要读 /sys/kernel/debug/soundwire/.../registers**：会阻塞内核线程，导致 TCP 23 shell 失去响应，只能长按电源键重启。
## 8. 已尝试且无效的方案（完整清单）

| # | 方案 | 结果 |
| --- | --- | --- |
| 1 | 用 QRD 的 `qcom,port-mapping` `<1 2 3 7 10 13>` / `<4 5 6 7 11 13>` | `SWR data-port collision` → `MASTER_CLASH_DET` |
| 2 | 用解码出的原厂映射 `<1 3 5 0 6 0>` / `<2 4 21 9 13 25>` | `All ports busy`、`-EBUSY`（21/25 超出 1–14） |
| 3 | 省略 `qcom,port-mapping`（驱动自动分配） | `All ports busy` 消失，但仍 `SWR CMD error`。**当前就处于这个状态** |
| 4 | 补 `gpio17/18` 引脚复用 | 引脚 function 正确，clash 仍在 |
| 5 | 换 HDK tplg | 与 QRD 文件逐字节相同（均 24296 B），无差别 |
| 6 | 禁 soundwire 控制器 runtime PM | SoundWire 错误减少，slave 仍 UNATTACHED |
| 7 | 重新 bind wsa884x slave | `Unbalanced pm_runtime_enable!`，clash 仍在 |
| 8 | unbind/bind soundwire 控制器 | IRQ 无法重映射：`irq: type mismatch, failed to map hwirq-202` |
| 9 | 上游补丁 `synchronize_irq(ctrl->irq)` | 编译加载成功，无效 |
| 10 | 禁 WSA macro autosuspend | 无效（实测播放时本就 `active`） |
| 11 | wsa884x 设 `clk_stop_mode1 = true` | 无效，SWR 错误反而增多，已回退 |
| 12 | pinctrl 改 `output-high` + devmem 强制 `CFG=0xE01 VAL=0x3` | **证伪 SD_N 假设**：GPIO 确认为输出高，slave 仍 UNATTACHED |

## 8.5 盘点中确认的关键事实（2026-10-21）

### slave 的 probe 确实跑过，但状态被反复刷回 UNATTACHED

- `hwmon50` 存在 → `wsa884x_probe()` 执行过（hwmon 是 probe 末尾注册的）
- `vreg_l3g_1p2` `users=2 enabled` → `regulator_bulk_enable` 执行过
- 但 `status = UNATTACHED`、`device_number = N/A`

注意 `device_number` 显示 `N/A` 只是 `status == SDW_SLAVE_UNATTACHED` 的**派生结果**，不是独立证据：

```c
/* drivers/soundwire/sysfs_slave.c */
if (slave->status == SDW_SLAVE_UNATTACHED)
        return sprintf(buf, "%s", "N/A");
```

### 中断处理里有一个"状态未变就跳过"的短路

```c
/* drivers/soundwire/qcom.c, NEW_SLAVE_ATTACHED 分支 */
if (ctrl->slave_status == slave_status) {
        dev_dbg(ctrl->dev, "Slave status not changed %x\n", slave_status);
} else {
        qcom_swrm_get_device_status(ctrl);
        qcom_swrm_enumerate(&ctrl->bus);
        sdw_handle_slave_status(&ctrl->bus, ctrl->status);
}
```

`ctrl->slave_status` 在 `qcom_swrm_init` 里被清零。若 `MCP_SLV_STATUS` 恒为 0，则 `ctrl->slave_status == slave_status == 0`，**每次中断都跳过枚举与状态更新**，slave 永远停在 UNATTACHED。

### 寄存器实测：总线上当前确实没有任何 slave

控制器 `runtime_status=active` 前提下读取（地址已核对为驱动里的宏值）：

| 寄存器 | 地址 | 实测 |
| --- | --- | --- |
| `SWRM_ENUMERATOR_CFG_ADDR` | `0x500` | `0x01` ✅ 自动枚举已使能 |
| `SWRM_ENUMERATOR_SLAVE_DEV_ID_1/2(m)` | `0x530/0x534 + 8*m` | m=1..4 全 `0` ❌ |
| `SWRM_MCP_SLV_STATUS` | `0x1090` | `0x00` ❌ |
| `SWRM_MCP_STATUS` | `0x104C` | `0x00` |
| `SWRM_V2_0_LINK_STATUS` | `0x5064` | `0x2081` → BIT(0) 帧发生器运行 ✅ |
| `SWRM_V2_0_CLK_CTRL` | `0x5060` | `0x01` → CLK_START ✅ |
| `SWRM_COMP_CFG_ADDR` | `0x004` | `0x03` → COMP + IRQ pulse ✅ |
| `SWRM_COMP_PARAMS` | `0x100` | `0x01684089` → DIN=4, DOUT=9 ✅ 与 DT 一致 |
| `SWRM_LINK_MANAGER_EE` | `0x018` | `0x01` = EE_CPU ✅ |
| `WSA SWR_CONTROL` | `0x6b00008` | `0x01` → CLK_EN=1, RST_EN=0 ✅ |

**即：master 侧初始化 100% 正确、时钟与帧发生器都在跑，但总线上没有任何 slave 回应该帧。**

### 原厂 DTB 用的是完全不同的架构

| 项目 | 原厂 DTB | mainline |
| --- | --- | --- |
| SoundWire 控制器 | `qcom,swr-mstr`（vendor） | `qcom,soundwire-v2.0.0` |
| 放大器 compatible | `qcom,wsa884x`（vendor） | `sdw20217020400`（MIPI） |
| 放大器节点 status | `disabled` | `okay` |
| MIPI Device ID | `0x2170220` / `0x2170221` | 枚举到 `0x2170204` |
| 供电 | 只有 `cdc-vdd-1p8` | `vdd-1p8` + `vdd-io` |

Device ID 不一致（`0204` vs `0220`）说明：mainline 枚举时芯片自报 `0204`（WSA8845 通用 ID），而原厂驱动用的是 `0220/0221` 变体 ID。这可能是原厂驱动对 ID 做了偏移处理，也可能两边识别的是不同寄存器视图。
## 8.6 决定性的架构发现（2026-10-21）

### 原厂 DTB 里整条 WSA 扬声器链路都是 disabled，LPASS macro 节点根本不存在

| 节点 | 原厂 DTB 状态 |
| --- | --- |
| `wsa_swr_clk_data_pinctrl` | `disabled` |
| `wsa2_swr_clk_data_pinctrl` | `disabled` |
| `wsa_spkr_en1_pinctrl` | `disabled` |
| `wsa_spkr_en2_pinctrl` | `disabled` |
| `wsa884x@02170220` / `@02170221`（两组，共 4 个） | 全部 `disabled` |
| `qcom,swr-mstr`（4 个） | 下属 slave 全 `disabled` |
| **`codec@6b00000`（lpass wsa macro）** | **节点根本不存在** |
| **`codec@6ac0000` / `codec@6ae0000` / `codec@6d44000`** | **节点根本不存在** |

整个 DTB 只有 9 个 `status = "okay"`，没有一个是音频相关。

对照：`rx_swr_clk_data_pinctrl`、`tx_swr_clk_data_pinctrl`（WCD938x 路径）**没有 disabled** —— 原厂走的是 WCD938x 音频路径。

### 平台标识

```dts
model = "Qualcomm Technologies, Inc. Kalama MTP,xigua";
qcom,model = "kalama-mtp-snd-card";
```

**这是 MTP 变体，不是 QRD。** 我此前照抄 `sm8550-qrd.dts` 的 WSA 扬声器配置，前提就不成立。

### Device ID 编码说明

mainline 匹配 `SDW_SLAVE_ENTRY(0x0217, 0x204, 0)`，实测 `modalias = sdw:m0217p0204v02c00` 完全吻合，driver 匹配正确。原厂的 `reg = <0x04 0x2170220>` 是 vendor 的 `<dev_num> <8位ID>` 编码（dev_num=4，ID=`0x217_0220`），与 mainline 的 mfg/part/class 三元组不是同一套表示法，不构成矛盾。binding `qcom,wsa8840.yaml` 明确写 `compatible: const: sdw20217020400`，覆盖 WSA8840/8845/8845H 整个家族。

## 8.7 结论

**主控侧（SoundWire master）已 100% 正确初始化并持续运行帧，但总线上没有任何 slave 回应 —— 因为原厂配置从未启用这条链路，PJA110 很可能没有装配/未引出 WSA8845 扬声器放大器。**

要继续验证这个判断，可行路径：

1. **查原厂 kernel 日志**（若能从 A12/A14 原厂系统取得 dmesg），确认是否存在 `wsa884x` 相关 probe 记录
2. **改走 WCD938x 路径**：原厂 `rx_swr`/`tx_swr` 是启用的，说明耳机/听筒路径存在。若目标是"能出声"，优先做 WCD938x 而非 WSA 扬声器
3. 物理确认：拆机或用原厂系统播放声音，确认外放喇叭是否工作
## 8.8 手动命令级验证：总线上没有 slave（2026-10-21）

绕过整个驱动栈，直接用 devmem 往 master 的 CMD FIFO 写读命令，逐个设备号探测：

```
for dev in 1..8:
    CMD_FIFO_WR (0x5020) <- read cmd for dev
    RD_FIFO_ADDR (0x5040) -> 0x00000C00   (所有 devnum 完全相同)
    INT_STATUS  (0x5000) -> 0x08         (只有 MASTER_CLASH_DET，无 NEW_SLAVE_ATTACHED / CMD_ERROR)
```

`RD_FIFO_ADDR` 在所有设备号上返回同一个值 `0x0C00`，且中断状态里从没出现过 `NEW_SLAVE_ATTACHED`(BIT1)。**说明没有任何地址上有 slave 应答** —— master 发出去的读命令在总线上无人响应。

这条验证独立于驱动、独立于 DTB 配置，直接证明**物理总线上没有 SoundWire 从设备**。

### 与 8.6 的呼应

原厂 DTB 里 WSA 链路全 disabled、LPASS macro 节点不存在、平台是 Kalama **MTP** 而非 QRD —— 与"总线上没有 slave"这一硬件事实完全一致。

**判断：PJA110 这条机器并未装配（或未引出）WSA8845 扬声器放大器，原厂走的是 WCD938x 音频路径。**

## 8.9 要"出声"应改走 WCD938x

原厂 DTB 中 `rx_swr_clk_data_pinctrl`、`tx_swr_clk_data_pinctrl` **没有 disabled**（而 wsa 的全被 disabled），说明 WCD938x 路径是原厂实际使用的。

当前 mainline 侧 WCD938x 的状态：

| 项 | 状态 |
| --- | --- |
| `snd-soc-wcd938x.ko` / `-sdw.ko` | ✅ 已编译、已安装 |
| `snd-soc-wcd-mbhc.ko` / `-classh.ko` | ✅ 已安装 |
| `swr1`(`6ad0000`) / `swr2`(`6d30000`) 平台设备 | ❌ **不存在**（DTB 里 disabled） |
| `wcd938x` 模块 | ❌ 未加载 |
| DTB `wcd938x` 节点 / sound 卡 WCD DAI link | ❌ 缺失 |

`input4 = "OnePlus Ace 2 Pro Headset Jack"` 只是 sound 卡注册的 jack 上报设备，不代表 codec 硬件已工作。

**所以下一步做外放/耳机声音，应当：补 `swr1`/`swr2` 启用、补 `wcd938x` codec 节点（含 reset-gpios、micbias、供电）、补 sound 卡的 WCD Playback/Capture DAI link，而不是继续在 WSA 上耗费。**
## 8.10 WCD938x 移植完成，最终卡在 DSP 侧（2026-10-21 深夜）

### 已完成：WCD938x 整条链路全部打通

| 环节 | 状态 | 证据 |
| --- | --- | --- |
| `swr1` (RX) / `swr2` (TX) 控制器 | ✅ | `sdw-master-2-0`、`sdw-master-3-0` 注册 |
| `wcd_rx` slave | ✅ | `sdw:2:0:0217:010d:00:4` **Attached** |
| `wcd_tx` slave | ✅ | `sdw:3:0:0217:010d:00:3` Attached（偶见 Alert） |
| `swr-haptics` slave | ✅ | `sdw:2:0:0217:f002:00:0` Attached |
| `wcd938x_codec` 绑定 | ✅ | `bound sdw:2:0:...:00:4` + `bound sdw:3:0:...:00:3` |
| 声卡创建 | ✅ | `card 0: Pro [OnePlus Ace 2 Pro]` |
| PCM | ✅ | MultiMedia1/2 Playback、MultiMedia3/4 Capture |
| mixer 控件 | ✅ | **245 个**，含完整 HPHL/HPHR 放大链 |
| 耳机检测 | ✅ | `Impedance detect ramp error`（未插耳机的正常表现） |

对比 WSA：那次 slave 从头到尾一个都 attach 不上，而 WCD938x 全部 Attached —— 硬件存在性差异得到确证。

### 本轮修掉的 4 个 DTS 错误

| # | 错误 | 修正 |
| --- | --- | --- |
| 1 | `pinctrl-0 = <0x682>` 指向不存在的 phandle | phandle 必须加在**状态节点**上，不是其 `config` 子节点 |
| 2 | sound-dai 里用逗号分隔多个 entry | DTS 语法要求同一对尖括号内空格分隔 |
| 3 | codec 列表放了 SDW slave（无 `#sound-dai-cells`） | 应放 **swr 控制器**（`&swr1`），与上游 QRD 一致 |
| 4 | DAI ID 用了 `PRIMARY_MI2S_RX/TX`(10/11) | 应为 `RX_CODEC_DMA_RX_0`=**113(0x71)**、`TX_CODEC_DMA_TX_3`=**120(0x78)** |

另：audio-routing 原本照抄 vendor 全表（含 WSA/DMIC/VA 路径），精简为 WCD 实际存在的 `HPHL/HPHR`、`AMIC1-5`、`ADC1-4 → TX SWR_INPUT0/1` 后，widget 绑定错误消失。

### 最终卡点：DSP 拒绝内存映射

播放/录音时：

```
q6apm-dai: Error (1) Processing 0x0100100c cmd
q6apm-dai: DSP returned error[100100c] 1
q6apm-dai: Memory_map_regions failed
q6apm-dai: Audio Start: Buffer Allocation failed rc = -22
ASoC: error at snd_soc_pcm_component_prepare: -12
```

`0x0100100C` = `APM_CMD_SHARED_MEM_MAP_REGIONS`，`result->status = 1` 表示 **DSP 拒绝**（`audioreach.c:585`）。

**这不是 SoundWire / WCD / 引脚 / 时钟问题** —— 那些都已验证正常。是 ADSP 侧的 AudioReach graph 未建立。

### 根因判断：tplg 与 ADSP 固件不匹配

| 项 | 值 |
| --- | --- |
| ADSP 固件 | `qcom/sm8550/xigua/adsp.mdt`（**OnePlus 原厂**） |
| tplg 固件 | `OnePlus Ace 2 Pro-tplg.bin` ← 复制自 **SM8550-QRD** 的 24296 B 文件 |

QRD tplg 里的 AudioReach graph 与模块 ID 是给高通参考 ADSP 固件编译的。PJA110 跑的是 OnePlus 的 ADSP 固件，两者 graph 定义不匹配，DSP 因此拒绝共享内存映射。

佐证：QRD 与 HDK 两份 tplg 字节完全相同（均 24296 B），说明 linux-firmware 里只有一份通用 SM8550 tplg，没有按 OEM 变体区分。

### 附带发现

`swr-haptics`（PM8550B，`sdw:2:0:0217:f002:00:0`）在 mainline **没有对应驱动**，是个裸 slave。它的 `simple_clk_stop_capable` 取默认 false，导致 `sdw_bus_prep_clk_stop()` 走非 simple 路径，出现：

```
soundwire sdw-master-2-0: clock stop deprepare wait failed:-110   (-ETIMEDOUT)
```

这只是 `dev_warn`，不阻断流程，但说明 haptics slave 未按预期响应时钟停止序列。
## 8.11 【重大更正】外放不是 WSA，是 NXP TFA9874（2026-10-21）

从线刷包提取 `odm` 与 `vendor` 分区后，推翻并修正了此前关于"外放硬件"的多个判断。

### 提取过程（方法学更正）

此前误判"odm 数据是压缩的、无法解析"，原因有二：

1. 判断依据是"2 MB 分块里没有 ext4 superblock" —— 这个推理不成立，分块本来就不会在开头带 superblock。
2. **OTA operation 类型映射写错**。Android `InstallOperation` 枚举是 `0=REPLACE 1=REPLACE_BZ 2=MOVE 3=BSDIFF 4=SOURCE_COPY 5=SOURCE_BSDIFF 6=ZERO 7=DISCARD 8=REPLACE_XZ`。我把 `8` 当成了 SOURCE_COPY，实际是 **REPLACE_XZ**，导致漏掉了 625 个 xz 压缩块。

正确做法：按 `dst_extents`（field 6，repeated）重组 + xz/bz2 解压。该 payload 是**完整 OTA**（无 MOVE/SOURCE_COPY/BSDIFF）。

重组结果：

| 分区 | 文件系统 | 大小 | op 统计 |
| --- | --- | --- | --- |
| `odm` | **erofs**（magic `e2 e1 f5 e0` @1024） | 1456 MB | XZ 625 + REPLACE 52 + BZ 50 + ZERO 2 |
| `vendor` | erofs | 770 MB | XZ 383 + BZ 2 |

产物：`out/payload_extract/odm.img`、`vendor.img`（可 `mount -t erofs -o ro`）。

### 关键发现：外放功放是 TFA9874

`odm/etc/mixer_paths.xml` 里真正生效的 `speaker` path：

```xml
<path name="speaker">
    <ctl name="TFA_CHIP_SELECTOR" value="3" />
    <ctl name="TFA Profile" value="speaker" />
    <ctl name="TFA_CHECK_FEEDBACK" value="On" />
</path>
```

且有多条 TFA path：

| path | TFA_CHIP_SELECTOR | TFA Profile |
| --- | --- | --- |
| `speaker` | 3 | speaker |
| `handset` | 1 | receiver |
| `mmi-speaker-left` | 1 | speaker |
| `mmi-speaker-right` | 2 | speaker |
| `mmi-mic-seal-receiver` | 1 | speaker |

佐证文件：

```
odm/firmware/tfa98xx.cnt                5909 B   (头部: PM3_01 / OPPO / 9874 / tfa9874 / caspeaker)
odm/lib64/libtfa98xx.so                           TFA98xx 驱动库
odm/lib/rfsa/adsp/libtfadsp_sb4_0_rx.so           TFA DSP 模块 (RX)
odm/lib/rfsa/adsp/libtfadsp_sb4_0_tx.so           TFA DSP 模块 (TX)
vendor/lib64/libtfavib.so                         TFA 振动
```

### 原厂 DTB 中的 TFA 节点（真实硬件参数）

```dts
tfa98xx@34 {                          tfa98xx@35 {
    tfa_channel = <0x00>;                 tfa_channel = <0x01>;
    tfa_max_range = <0x1f40>;   /*8000*/  tfa_max_range = <0x1f40>;
    tfa_min_range = <0x1388>;   /*5000*/  tfa_min_range = <0x1388>;
    tfa9874_vdd-supply = <0x2f7>;         tfa9874_vdd-supply = <0x2f7>;
    compatible = "nxp,tfa98xx";           compatible = "nxp,tfa98xx";
};

oplus,speaker-codec-name     = "tfa98xx.4-0034", "tfa98xx.4-0035";
oplus,speaker-codec-dai-name = "tfa98xx-aif-4-34", "tfa98xx-aif-4-35";
```

即 **I2C bus 4，地址 0x34 与 0x35，两颗 TFA9874**，供电为 `0x2f7` = `pm_humu_l15` = `vreg_l15b_1p8`。

### 为什么之前所有 WSA 观察都"自洽但结论错"

| 观察 | 真实解释 |
| --- | --- |
| vendor DTB 所有 wsa 节点 `disabled`，`qcom,wsa-max-devs = <0>` | **正确** —— 确实没有 WSA 硬件 |
| WSA SoundWire slave 永远 attach 不上 | **正确** —— 硬件不存在 |
| odm `mixer_paths.xml` 有大量 `WSA_*` / `SpkrLeft` 控件 | 这些只在文件开头的**默认初始化块**里出现，全部 `value="0"`，**不在任何 `<path>` 中** |
| ACDB 里有大量 `DeviceRX_Speaker` 条目 | ACDB 是通用校准库，`DeviceRX_Speaker` 与具体功放型号无关 |

### 修正后的 PJA110 音频架构

```
播放:
  APM/DSP ──► WCD938x (HPHL/HPHR) ──► 耳机        [SoundWire, 已打通]
  APM/DSP ──► LPASS 模拟输出 ──► TFA9874 ×2 ──► 外放 [I2C 控制, 需驱动]

录音:
  WCD938x TX (AMIC/DMIC) ──► swr2 ──► DSP          [SoundWire, 已打通]
```

外放**完全不经过 SoundWire**，这是 swr0 上永远没有 slave 的根本原因。

### mainline TFA9874 支持现状

| 项 | 状态 |
| --- | --- |
| `sound/soc/codecs/tfa9879.c` | 存在，但那是 **I2S** 版本，不是 tfa98xx 系列 |
| `sound/soc/codecs/tfa989x.c` | 存在，支持 tfa9890/9891/9895/9896 —— **不含 9874** |
| `nxp,tfa98xx` binding | **不存在**（vendor 私有 compatible） |
| `CONFIG_SND_SOC_TFA98*` | **均未启用** |

**结论：外放 TFA9874 需要新写/移植 codec 驱动，工作量明显大于 WSA/WCD。**
## 8.12 方向 A 可行性评估：AGM/GSL 与 APM 是否兼容（2026-10-21）

结论先行：**协议同源，可行，但不是"改个 opcode"那么简单。**

### 证据一：两者共用同一套 GPR 传输与 opcode 数值

`libar-gsl.so`（OnePlus 的 GSL 实现）的 rodata 里直接包含 mainline APM 的 opcode 常量：

| 偏移 | 值 | 名称 | mainline 是否有 |
| --- | --- | --- | --- |
| `0xacb0` | `0x0100100d` | UNMAP_REGIONS | ✅ 有 |
| `0xacd8` | `0x0100100a` | REGISTER_SHARED_CFG | ✅ 有 |
| `0xacec` | `0x01001006` | SET_CFG | ✅ 有 |
| `0xad04` | `0x01001021` | GET_SPF_STATE | ✅ 有 |
| `0xad44` | `0x0100100c` | MAP_REGIONS | ✅ 有 |
| `0xad3c` | `0x08001005` | SUB_GRAPH_LIST | ✅ 有（APM_PARAM_ID_SUB_GRAPH_LIST） |
| `0xacd0` | `0x01001008` | ? | ❌ 无 |
| `0xad10` | `0x0100100b` | ? | ❌ 无 |
| `0xad18` | `0x01001009` | ? | ❌ 无 |
| `0xacb8` | `0x01001026` | ? | ❌ 无 |
| `0xad20` | `0x01001027` | ? | ❌ 无 |

即：**AGM 与 AudioReach 不是两套协议，而是同一 SPF 框架的两代封装**，opcode 空间完全重叠，固件版本比 mainline 新（多出若干命令）。

### 证据二：GSL API 与 mainline APM 一一对应

| GSL | mainline APM |
| --- | --- |
| `gsl_graph_open` | `audioreach_graph_init` |
| `gsl_graph_prepare` / `start` / `stop` / `flush` | `audioreach_graph_start` / `stop` / `flush` |
| `gsl_graph_set_cal` | `apm_set_cal` |
| `gsl_graph_read` / `write` | `audioreach_shared_memory_*` |
| `gsl_graph_add_new` / `remove_old` / `change` | 动态图管理（mainline 靠 tplg 静态描述） |
| `gsl_spf_ss_state_set` | **mainline 无对应实现** |

### 证据三：真正的卡点是 audio PD 没起来，不是协议不兼容

开机日志：

```
[3.79] PDR: Indication received from msm/adsp/audio_pd, state: 0x1fffffff, trans-id: 1
[3.79] qcom,apr: Adding APR/GPR dev: gprsvc:service:2:1
[9.18] qcom-apm gprsvc:service:2:1: CMD timeout for [1001021] opcode      ← GET_SPF_STATE 超时
[164]  q6apm-dai ...: DSP returned error[100100c] 1                        ← MAP_REGIONS 被拒
```

`state: 0x1fffffff` = **PD_DOWN**。即 `msm/adsp/audio_pd` 保护域在 mainline 下从未被拉起到 ACTIVE。

我们的 DT 写的是：

```dts
qcom,protection-domain = "avs/audio", "msm/adsp/audio_pd";
```

`avs/audio` 是 AudioReach 期望的 PD 名，写在前面；但日志里只出现 `msm/adsp/audio_pd` 的 PDR 通知，说明 `avs/audio` 这个 PD 不存在于该固件。

**GSL 靠 `gsl_spf_ss_state_set` 显式请求子系统 UP；mainline 只做 `GET_SPF_STATE` 查询、从不 SET，因此 APM 服务始终处于未激活状态，`GET_SPF_STATE` 超时、`MAP_REGIONS` 被拒。**

### 可行性判断

| 方案 | 工作量 | 风险 |
| --- | --- | --- |
| 让 mainline 补 `SET_SPF_STATE`（`0x01001008` / `0x0100100b` 之一） | 中等：改 `q6apm.c`，加一次握手 | 中 —— 需要试出正确 opcode 与 payload |
| 实现完整 GSL 客户端 | 很大：gsl_graph_* 全家族、GKV/CKV 机制、动态模块加载 | 高 |
| 反推 AGM 的 graph 描述格式（相当于自己写 tplg） | 很大 | 高 |

**优先尝试第一条**：`GET_SPF_STATE` 超时是最前置的失败点，若补上 `SET_SPF_STATE` 能让 APM 应答，后续 MAP_REGIONS 可能自然通过。

需要试的 opcode 候选（GSL 里有、mainline 里没有）：`0x01001008`、`0x01001009`、`0x0100100b`、`0x01001026`、`0x01001027`。
## 8.13 方向 A 实测结论：SET_SPF_STATE 探测全部失败（2026-10-22）

### 实验设计

在 `apm_probe()` 里，于 `q6apm_get_apm_state()` 之前插入探测：依次发送 GSL 有、mainline 没有的 5 个候选 opcode，每次之后立刻重测 `GET_SPF_STATE`，看 APM 端口是否开始应答。

改的是 `sound/soc/qcom/qdsp6/q6apm.c`，只替换 `snd-q6apm.ko`（240272 → 242552 B），不刷机。

### 结果：全部超时

```
[ 8.16] PROBE: SET_SPF_STATE cand 0x01001008 -> ret -110
[13.28] PROBE: GET_SPF_STATE after 0x01001008 -> ret -110 state 0x0
[18.40] PROBE: SET_SPF_STATE cand 0x01001009 -> ret -110
[23.52] PROBE: GET_SPF_STATE after 0x01001009 -> ret -110 state 0x0
[28.64] PROBE: SET_SPF_STATE cand 0x0100100b -> ret -110
[33.76] PROBE: GET_SPF_STATE after 0x0100100b -> ret -110 state 0x0
[38.88] PROBE: SET_SPF_STATE cand 0x01001026 -> ret -110
[44.00] PROBE: GET_SPF_STATE after 0x01001026 -> ret -110 state 0x0
[49.12] PROBE: SET_SPF_STATE cand 0x01001027 -> ret -110
[54.24] PROBE: GET_SPF_STATE after 0x01001027 -> ret -110 state 0x0
[54.24] PROBE: no SPF probe opcode worked
```

`-110` = `-ETIMEDOUT`。**不仅 5 个候选无响应，连 `GET_SPF_STATE` 本身也从未成功过** —— APM 端口对 mainline 完全沉默。

副作用：启动被拖后约 46 秒（8 s → 54 s），但系统仍能正常起来。已恢复原版模块（`snd-q6apm-pristine.ko`，sha256 `c6b7655f…`）。

### 同时纠正一个此前的错误推断

我在 8.12 里写「`state: 0x1fffffff` = PD_DOWN，audio 保护域从未拉起」—— **这是错的**。

`include/linux/soc/qcom/pdr.h`：

```c
enum servreg_service_state {
	SERVREG_LOCATOR_ERR              = 0x1,
	SERVREG_SERVICE_STATE_DOWN       = 0x0FFFFFFF,
	SERVREG_SERVICE_STATE_UP         = 0x1FFFFFFF,   /* ← 0x1fffffff 是 UP */
	SERVREG_SERVICE_STATE_EARLY_DOWN = 0x2FFFFFFF,
	SERVREG_SERVICE_STATE_UNINIT     = 0x7FFFFFFF,
};
```

所以开机日志那行

```
PDR: Indication received from msm/adsp/audio_pd, state: 0x1fffffff
```

意思是 **audio PD 已经正常 UP**。

另外 `qcom_pd_mapper.c` 表明 `avs/audio` 是 `msm/adsp/audio_pd` 域提供的**服务**，不是并列的两个 PD：

```c
static const struct qcom_pdm_domain_data adsp_audio_pd = {
	.domain = "msm/adsp/audio_pd",
	.instance_id = 74,
	.services = { "avs/audio", NULL },
};
```

即我们的 DT `qcom,protection-domain = "avs/audio", "msm/adsp/audio_pd"` 写法正确。

同理，`qcom,intents = <0x200 0x14>` = `<512 20>`，与上游 `sm8550.dtsi` 完全一致（曾因 `od -tu4` 对 DTB 大端数据误读成 `131072 335544320`，实为误判）。

### 方向 A 的结论

| 假设 | 结果 |
| --- | --- |
| 协议不同（AGM vs APM 两套） | ❌ 证伪 —— opcode 常量完全相同 |
| 只差一个 `SET_SPF_STATE` 握手 | ❌ 证伪 —— 5 个候选全部超时，且 `GET_SPF_STATE` 从未成功 |
| audio PD 未起来 | ❌ 证伪 —— `0x1fffffff` 是 UP |
| GPR intents 配置错 | ❌ 证伪 —— 与上游一致 |

**剩下的可能**：OnePlus 的 ADSP 固件虽然内含 AudioReach 的 CAP 组件，但其 GPR `service@1`（APM 端口）并未注册 APM 命令服务；AGM 走的是另一条通道（可能经 `libar-gsl` 的 `gsl_mdf_utils` / MDF 框架，而非标准 APM 端口）。

**判断：方向 A 的"低成本补丁"路径已走不通。** 继续需完整逆向 AGM 的 MDF/GSL 通道协议，工作量远超改 DTB，属于长期研究项目。
## 8.14 根因确认：原厂走 AMDB (port 3)，mainline 走 APM (port 1)（2026-10-22）

### 决定性证据：原厂 GPR 节点的子节点与 mainline 完全不同

原厂 DTB 的 `qcom,gpr` 节点（`v.dts` 10199-10222）：

```dts
qcom,gpr {
    phandle = <0x4d1>;
    reg = <0x02>;                          /* GPR_DOMAIN_ID_ADSP */
    qcom,intents = <0x200 0x14>;           /* 512 20 —— 与 mainline 一致 */
    qcom,glink-channels = "adsp_apps";
    compatible = "qcom,gpr";

    spf_core  { reg = <0x03>; compatible = "qcom,spf_core"; };   /* ← 端口 3 */
    audio-pkt { reg = <0x17>; compatible = "qcom,audio-pkt";
                qcom,audiopkt-ch-name = "apr_audio_svc"; };      /* ← 端口 23 */
    q6prm     { reg = <0x07>; compatible = "qcom,audio_prm"; };  /* ← 端口 7 */
}
```

**原厂的 GPR 下没有 `q6apm`。** 它用的是 `qcom,spf_core`（端口 3）。

mainline 的端口号定义（`include/dt-bindings/soc/qcom,gpr.h`）：

```c
#define GPR_DOMAIN_ID_ADSP    2
#define GPR_APM_MODULE_IID    1    /* mainline q6apm 用端口 1 */
#define GPR_PRM_MODULE_IID    2
#define GPR_AMDB_MODULE_IID   3    /* ← 原厂 spf_core 的端口 3 */
#define GPR_VCPM_MODULE_IID   4
```

即：**原厂的 `spf_core`(port 3) 就是 AMDB，mainline 的 `q6apm`(port 1) 是 APM。两者是同一 GPR domain 上的不同端口，服务不同。**

### mainline 没有对应驱动

```
sound/soc/qcom/qdsp6/ 下无 amdb*.c，无 spf_core 驱动
grep "qcom,amdb|AMDB_MODULE|qcom,spf_core" → 无结果
```

### 为什么探测 5 个 opcode 全部超时

APM opcode 必须发给 **port 1**（`GPR_APM_MODULE_IID`）。而 OnePlus 固件在 **port 1 上没有注册 APM 命令处理器** —— 它的音频入口在 port 3（AMDB/spf_core）。

所以：

| 现象 | 原因 |
| --- | --- |
| `GET_SPF_STATE` 超时 | port 1 无人处理 |
| `SET_SPF_STATE` 5 个候选全超时 | 同上，换 opcode 无用 |
| `MAP_REGIONS` 返回 status=1（而非超时） | 这条走的是 **DAI 端口**（`service@1:dais`），该端口存在，故能应答错误码 |
| 声卡、mixer、SoundWire 全部正常 | 这些都不依赖 APM 命令 |

### 方向 A 最终判定

| 方案 | 可行性 |
| --- | --- |
| 补 `SET_SPF_STATE` | ❌ 已实测失败 |
| 换 opcode | ❌ 端口错，换什么都没用 |
| 把 `q6apm` 的 dest_port 改成 3（冒充 spf_core） | ⚠️ 可试，但 AMDB 协议与 APM 不同（`gsl_mdf_utils_*`、`gsl_dynamic_module_mgr_*` 是 MDF 框架，与 APM 的 graph/container/module 模型不是一套） |
| 完整逆向 AMDB/MDF 协议 | 工作量极大，属长期研究 |

**结论：音频 DSP 通路在 mainline 上的阻塞，本质是 OnePlus 固件用 AMDB/MDF（AGM 架构），而 mainline 实现的是 APM（AudioReach 架构）。这不是配置问题，是两套 DSP 音频框架的差异。**

### 已完成的成果（不受此阻塞影响）

| 项 | 状态 |
| --- | --- |
| WCD938x DT 移植（9 条补丁） | ✅ 完整 |
| swr1/swr2 控制器 + wcd_rx/wcd_tx slave | ✅ Attached |
| `wcd938x_codec` 绑定 | ✅ 双端口 bound |
| 声卡 `card 0` | ✅ 创建成功 |
| mixer 控件 | ✅ 245 个 |
| 耳机检测 | ✅ 阻抗检测在跑 |
| 外放硬件型号 | ✅ 已查明 NXP TFA9874 ×2 (I2C 4-0034/4-0035) |
| tplg | ✅ 确认无需（原厂 AGM 动态建图） |

**唯一阻塞：DSP 音频框架不匹配，与上述硬件层工作正交。**
## 8.15 port 3 (AMDB) 探测：实验失败，但暴露了关键依赖关系（2026-10-22）

### 实验设计

在 `apm_probe()` 里对 GPR 端口 **1 / 3 / 7 / 23** 各发 11 个候选 opcode（fire-and-forget，用 `gpr_send_pkt` 不等待响应，避免每包 5 秒超时拖垮启动），观察是否有任何端口应答。

### 结果：探测本身把音频子系统整个搞挂了

`/proc/asound/cards` 变成 `--- no soundcards ---`，`no gpr bus`，dmesg 大量 deferred probe：

```
platform 6d44000.codec: deferred probe pending: va_macro: unable to get macro clock
platform 6e80000.pinctrl: deferred probe pending: Failed to get clk 'core'
platform 6ac0000.codec / 6ae0000.codec / 6b00000.codec:
    deferred probe pending: supplier 6d44000.codec not ready
platform 6ad0000 / 6b10000 / 6d30000.soundwire:
    deferred probe pending: wait for supplier pinctrl rx/wsa/tx-swr-active-state
platform sound: deferred probe pending: snd-sc8280xp: WCD Playback: error getting cpu dai name
```

**没有出现任何 `P3PROBE` 日志** —— 说明 `apm_probe()` 根本没被调用到那一步，或是 probe 失败得比我插桩的位置还早。

### 这次失败暴露的重要事实

从 deferred 链可以清楚看出音频子系统的**依赖顺序**：

```
q6prm (GPR port 2)
   └─► q6prm_clocks  (提供 LPASS clocks: core / va_macro / rx_macro / tx_macro)
          └─► 6d44000.va_macro        (拿 macro clock)
          └─► 6e80000.lpass_lpi_pinctrl (拿 clk 'core')
                 └─► 6ad0000/6b10000/6d30000.soundwire (等 pinctrl 状态)
          └─► 6ac0000 / 6ae0000 / 6b00000.codec
                 └─► sound card (等 cpu dai name)
```

即 **q6prm 是整条音频链的根**。它挂掉，后面全部 deferred。

之前能正常工作，是因为原版 `apm_probe` 里 `q6apm_get_apm_state()` 虽然超时（端口 1 无响应），但**不阻断** probe —— 返回值被丢弃，probe 照常继续，`of_platform_populate()` 才得以注册子设备（dais / bedais），q6prm 也随之起来。

我加的发包代码在 `g_apm = apm;` 之后、`q6apm_get_apm_state()` 之前执行，`gpr_send_pkt()` 在 GPR 总线尚未就绪时可能阻塞或返回错误，导致 `apm_probe()` 提前失败 → 连锁 deferred。

### 已恢复

原版 `snd-q6apm.ko`（240272 B，sha256 `c6b7655f…`）已重新装回并验证：

```
card 0: Pro [OnePlus Ace 2 Pro]        ✅
snd_q6apm       4 users                ✅
q6prm_clocks   17 users                ✅
sdw:2:0:0217:010d:00:4  Attached        ✅
sdw:2:0:0217:f002:00:0  Attached        ✅
sdw:3:0:0217:010d:00:3  Alert           （已知，不影响）
```

### 关于 port 3 的结论

**没能测到。** 探测代码没跑到发包那一步就失败了，因此：

- port 3 上是否有 AMDB 服务在监听 —— **仍未验证**
- 存在"探测手段本身破坏依赖链"的风险，说明这条路要么在更安全的时机发出（例如用户态 ioctl，而不是 probe 阶段），要么需要改 `gpr` 层而非 `apm_probe`

**若要继续验证 port 3，正确做法**：不要在 `apm_probe` 里发包，而应：

1. 先让系统完整启动（音频栈全部就绪）
2. 通过一个独立的 debugfs / ioctl 接口，从用户态触发发包
3. 这样即使 GPR 报错也不影响 probe 链路

这需要写一个带 debugfs 节点的小模块，工作量比之前几次尝试都大。
## 8.16 debugfs 注入工具建成，并推翻两个错误结论（2026-10-22）

### 工具：`/sys/kernel/debug/q6apm/{send,last}`

在 `q6apm.c` 里新增 debugfs 接口（`CONFIG_DEBUG_FS=y` 已开启）：

```sh
echo "<dest_port> <opcode> [payload_words...]" > /sys/kernel/debug/q6apm/send
cat /sys/kernel/debug/q6apm/last
```

- 构造完整 `gpr_hdr` + 16 字节 `apm_cmd_header`，发到指定 DSP 端口
- 等待 2 s，报告 `RESP rsp=0x… status=…` 或 `SENT(n) NO RESPONSE`
- **只在系统完全启动后由用户态触发，不参与 probe**，因此不会破坏音频依赖链
- 模块：`out/ut-test/snd-q6apm-dbgfs2.ko`（254504 B）

### 推翻结论一：port 1 的 APM 服务其实是活的

```
port=1 op=0x01001021  →  RESP rsp=0x02001007 status=0     ✅ GET_SPF_STATE 成功
port=2 op=0x01001000  →  RESP rsp=0x01001000 status=2     (PRM)
port=3 op=0x01001021  →  SENT(40) NO RESPONSE 2s          (AMDB 端口无此命令)
```

`0x02001007` 正是 `APM_CMD_RSP_GET_SPF_STATE`，`status=0` 即成功。

**所以 8.14 的「APM 端口对 mainline 完全沉默」是错的。** 真相是：

- probe 阶段调用 `q6apm_get_apm_state()` 时，GPR 的 rpmsg endpoint 尚未就绪，`rpmsg_trysend()` 直接返回 `-ENOMSG(40)`，代码里返回值又被丢弃，于是只看到 `CMD timeout`
- 系统起来后，同一条命令完全正常

同理，8.12/8.13 的 5 个 `SET_SPF_STATE` 候选全部「超时」，也是因为它们在 probe 阶段发出、根本没发出去。

### 推翻结论二：tplg 加载成功

```
numid=168  'stream0.vol_ctrl0 MultiMedia1 Playback Volu'
numid=169  'stream1.vol_ctrl1 MultiMedia2 Playback Volu'
```

这些正是 `OnePlus Ace 2 Pro-tplg.bin` 里定义的控件名（`stream0.vol_ctrl0` / `MultiMedia1 Playback Volume`）。**tplg 已被 `audioreach_tplg_init()` 正确解析并加载**，graph 定义完整。

### 真正的卡点：`MAP_REGIONS` 被 DSP 拒绝

播放时（`speaker-test` / `aplay`）唯一的硬件错误：

```
q6apm-dai ...: Error (1) Processing 0x0100100c cmd
q6apm-dai ...: DSP returned error[100100c] 1
q6apm-dai ...: Memory_map_regions failed
q6apm-dai ...: Audio Start: Buffer Allocation failed rc = -22
ASoC: error at snd_soc_pcm_component_prepare: -12
```

`0x0100100C` = `APM_CMD_SHARED_MEM_MAP_REGIONS`，DSP 回 `status = 1`（拒绝，非超时）。

用 debugfs 复现：

| opcode | 结果 |
| --- | --- |
| `0x01001021` GET_SPF_STATE | status=0 ✅ |
| `0x01001000` GRAPH_OPEN（空 payload） | status=3（缺参数，预期） |
| `0x0100100c` MAP_REGIONS（4 种 mem_pool_id: 1/2/3/4） | 全部 `SENT(80) NO RESPONSE` |

debugfs 侧无响应是因为 `src_port` 用了固定值 1，而真实驱动用 `gpr_alloc_port()` 分配的**动态源端口**走 `gpr_send_port_pkt()`，响应回到 `graph->port` 的回调而非 `apm->wait`。所以 debugfs 的「NO RESPONSE」不能作为否定证据 —— 真实驱动确实收到了 `status=1`。

### 剩余差异点

mainline 与 vendor(GSL) 的内存映射模型不同：

| | mainline | vendor GSL |
| --- | --- | --- |
| 映射命令 | `APM_CMD_SHARED_MEM_MAP_REGIONS` → APM | `gsl_shmem_alloc` / `gsl_shmem_map_extern_mem` |
| mem_pool_id | `APM_MEMORY_MAP_SHMEM8_4K_POOL` = 3 | 未公开（在 .so 内） |

DSP 拒绝 `status=1` 最可能的原因：该固件根本不支持通过 APM 命令做 shmem 映射（它期望 GSL 用另一套 `hyp_assign` / `map_extern_mem` 流程），或对 `mem_pool_id`/地址属性有不同要求。

### 下一步可试（低成本）

用 debugfs 逐项试探 `MAP_REGIONS` 的 `mem_pool_id`（0..7）与 `property_flag`，并给 `src_port` 也用动态端口，看哪种组合能拿到 `status=0`。这不需要改驱动，只要在 debugfs 里补一个「用动态端口发送」的路径。
## 8.17 决定性定位：DSP 支持 APM graph 命令，唯独不支持 SHARED_MEM_MAP_REGIONS（2026-10-22）

### debugfs 工具已完善（`out/ut-test/snd-q6apm-dbg9.ko`，254808 B）

关键修正：`apm_callback()` 开头加了「记录所有响应 opcode/status 并唤醒」：

```c
result = data->payload;
apm->dbg_rsp_opcode = hdr->opcode;
apm->dbg_rsp_status = result ? result->status : 0;
wake_up(&apm->wait);
```

加上 `apm_cmd_header.payload_size` 正确填写后，任意命令的真实返回都能看到。

### DSP 对各 APM 命令的实际响应（空 payload 探测）

| opcode | 命令 | 返回 status | 判定 |
| --- | --- | --- | --- |
| `0x01001000` | GRAPH_OPEN | 1 | 拒绝（缺参数，预期） |
| `0x01001001` | GRAPH_PREPARE | **0** | ✅ 接受 |
| `0x01001002` | GRAPH_START | **0** | ✅ 接受 |
| `0x01001003` | GRAPH_STOP | 1 | 无 graph 可停 |
| `0x01001004` | GRAPH_CLOSE | 1 | 无 graph 可关 |
| `0x01001005` | GRAPH_FLUSH | 1 | 无 graph 可刷 |
| `0x01001006` | SET_CFG | 3 | 缺参数 |
| `0x01001007` | GET_CFG | 2 | 不支持 |
| `0x0100100a` | REGISTER_SHARED_CFG | 3 | 缺参数 |
| **`0x0100100c`** | **SHARED_MEM_MAP_REGIONS** | **2** | ❌ **不支持** |
| **`0x0100100d`** | **SHARED_MEM_UNMAP_REGIONS** | **2** | ❌ **不支持** |
| `0x01001013` | CLOSE_ALL | **0** | ✅ 接受 |
| `0x01001021` | GET_SPF_STATE | **0**（`0x02001007` 专属响应） | ✅ 正常 |
| `0x01001026` | （mainline 未定义；GSL 有） | **0** | ✅ 接受 |
| `0x01001027` | （mainline 未定义；GSL 有） | 1 | 拒绝 |

### 参数遍历确认不是配置问题

对 `MAP_REGIONS` 遍历 `mem_pool_id` 0..7，其余参数固定，**全部返回 `status=2`**：

```
pool=0..7, nreg=1, flag=0, addr=0x1000, sz=0x1000  →  全部 rsp=0x02001005 status=2
```

即不是 pool id、不是地址、不是大小的问题 —— **DSP 根本不实现这两个命令**。

### 结论：这就是最终卡点

- DSP 的 APM 服务**是真的在跑**（`GET_SPF_STATE`、`GRAPH_PREPARE`、`GRAPH_START`、`CLOSE_ALL` 全部返回成功）
- 但 **`SHARED_MEM_MAP_REGIONS` / `UNMAP_REGIONS` 返回 `status=2`（不支持）**
- 而 mainline 的 `audioreach_map_memory_regions()` **必须**靠这两个命令把 PCM 缓冲区物理地址交给 DSP
- 没有内存映射，DSP 就拿不到音频数据缓冲区，`Audio Start: Buffer Allocation failed`，播放失败

### 与 vendor 架构的对应

vendor 的 GSL 用 `gsl_shmem_alloc` / `gsl_shmem_map_extern_mem` / `ar_shmem_hyp_assign_phys` —— 这是一套**独立于 APM 命令**的共享内存管理机制（可能在 GPR/Glink 层或 hypervisor 层完成地址分配），不经过 `APM_CMD_SHARED_MEM_MAP_REGIONS`。

**这解释了为什么 vendor 能出声而 mainline 不能：同一个 DSP 固件，两条不同的内存映射路径。**

### 可行的突破方向（重新排序）

1. **找 DSP 支持的替代映射命令**：`0x01001026` 返回 0（接受），GSL 里有而 mainline 没有；需确认它是否是 shmem 相关的替代接口。可以进一步试 `0x01001026` 带参数。
2. **`SET_CFG` 路径**：`0x01001006` 返回 3（缺参数），说明该命令存在，可能通过 module param 传递缓冲区信息。
3. **在 kernel 侧绕过**：不用 APM 映射，改用 `q6asm` 老路径（`q6asm-dai.c` 仍在树内），它用另一套 buffer 约定。
4. **逆向 GSL 的 `gsl_shmem_*` 实现**：从 `libar-gsl.so` 反推它实际发什么 GPR 包。

其中 **方向 1 成本最低**：`0x01001026` 已经是 status=0，值得带参数再探。
## 8.18 最终结论：APM 音频通路在 PJA110 固件上不可用（2026-10-22）

### `0x01001026` 探测结果：空操作，无价值

`0x01001026`（GSL 有、mainline 无，且紧邻 `UNMAP_REGIONS`，曾怀疑是 shmem 替代接口）对**任意参数**都返回 `status=0`：

| 参数 | payload | status |
| --- | --- | --- |
| 无 | 0 B | 0 |
| `0` / `1` / `4096` | 4 B | 0 |
| `0 0` / `1 0` | 8 B | 0 |
| `0 0 0 4096` | 16 B | 0 |
| `3 1 0 0 0 4096 4096 0`（完整 MAP_REGIONS 结构） | 32 B | 0 |

对照会校验参数的命令：`0x01001008` → 1、`0x01001009` → 1、`0x0100100b` → 3。

**一个对任何输入都返回成功、且前后 `GET_SPF_STATE` 毫无变化的命令，是不做校验的空操作（no-op），不是内存映射接口。** 这条路排除。

### 真实播放路径的最终错误

```
q6apm-dai ...: Error (1) Processing 0x0100100c cmd
q6apm-dai ...: DSP returned error[100100c] 1
q6apm-dai ...: Memory_map_regions failed
q6apm-dai ...: Audio Start: Buffer Allocation failed rc = -22
ASoC: error at snd_soc_pcm_component_prepare: -12
```

注意：真实驱动走 graph 端口，返回 `status=1`；debugfs 走 APM gdev 端口，返回 `status=2`。两者都表示拒绝，只是端口/token 不同导致的错误码差异。

### 全部尝试汇总

| 尝试 | 结果 |
| --- | --- |
| 换 `SET_SPF_STATE` opcode（8.13） | ❌ probe 阶段发包无效（GPR 未就绪） |
| port 3 (AMDB) 探测（8.15） | ❌ 方法破坏 probe 依赖链，未测到 |
| debugfs 注入工具（8.16） | ✅ **成功建成，可发任意 APM 命令** |
| `MAP_REGIONS` 遍历 mem_pool_id 0-7（8.17） | ❌ 全部 status=2 |
| `0x01001026` 候选接口（8.18） | ❌ 空操作 |
| `GET_SPF_STATE` | ✅ status=0，APM 服务在跑 |
| `GRAPH_PREPARE` / `GRAPH_START` / `CLOSE_ALL` | ✅ status=0，graph 管理正常 |

### 判定

**DSP 固件的 APM 实现只覆盖 graph 生命周期管理，不含共享内存映射命令。**

mainline 的 AudioReach 音频通路必须依赖 `APM_CMD_SHARED_MEM_MAP_REGIONS` 把 PCM 缓冲区交给 DSP，该命令缺失即无法播放任何音频。**这不是配置问题，也不是能靠 DTB 或 opcode 调整解决的。**

要突破只剩两条重工程路线：

1. **逆向 `libar-gsl.so` 的 `gsl_shmem_*` 实现**，搞清 vendor 如何把缓冲区地址交给 DSP（可能经 GPR 非 APM 通道、或 hypervisor `hyp_assign`），然后在 mainline 复刻。
2. **改用 `q6asm` 老路径**（`q6asm-dai.c` 仍在树内），它使用另一套 buffer 约定，但它依赖 `q6asm` APR 服务，需先确认该固件是否提供。

### 本次工作的实际产出（仍然有价值）

| 产出 | 说明 |
| --- | --- |
| **WCD938x 完整移植** | 9 条 DT 补丁，硬件层全通（声卡、245 控件、slave Attached、耳机检测） |
| **外放硬件查明** | NXP **TFA9874 ×2**（I2C 4-0034/4-0035），含 vendor DTB 参数与固件 `tfa98xx.cnt` |
| **debugfs APM 注入工具** | `/sys/kernel/debug/q6apm/{send,last}`，可发任意 GPR/APM 命令并读回响应——**后续调其他音频问题（含 TFA9874）都能复用** |
| **完整架构认知** | vendor 用 AMDB/MDF(GSL) 而 mainline 用 APM；两者的 opcode 空间重叠但 DSP 实现只覆盖部分 |
| **分块上传方案** | 带 sha256 逐块校验，解决大文件传输丢字节问题 |
## 9. 后续方向

### 9.1 最优先：恢复 `qcom,port-mapping` 并重新审视

当前 speaker 节点**没有** `qcom,port-mapping`，而上游 `sm8550-qrd.dts` **有**。这是与上游唯一的实质差异，也是下一步最该先排除的变量。

之前删掉它的理由是「解码出的 21/25 超出 1–14 端口范围」。但注意 `qcom.c` 里 maxport 来自 `qcom,dout-ports = <9>`，而 QRD 的映射值 10/13 同样超过 9 却能用——说明 `port-mapping` 的语义不是简单的端口索引，我的解码方式很可能错了。

原厂 `qcom,swr-wsa-port-params`（48 个 u16，4 组重复）的编码需要重新解读：更可能是「每个端口一组 (num, ch_mask)」，而不是 6 个 u32。

### 9.2 Device Number 分配失败的定位

枚举能读到 ID（`modalias = sdw:m0217p0204v02c00`），但 `dev_num` 文件从未出现。这个阶段由 `qcom_swrm_enumerate()` → `sdw_slave_add()` → `sdw_handle_slave_status()` 完成，需要对照 MIPI SoundWire 规范确认：

- master 通过 DP0 写 slave 的 SCP_DeviceNumber 寄存器
- 该写操作依赖 `SWRM_MCP_SLV_STATUS` 报告 slave 已 attach
- 若 slave 未报告 attach，master 不会分配编号（互为前提）

### 9.3 解译 `0x4e00c001`

这是唯一还没解读的硬证据。播放时报 `SWR CMD error, fifo status 0x4e00c001`（每次相同），需要对照 SoundWire master 的 CMD_FIFO_STATUS 位定义。低半字节 `0x001` 很可能就是具体的错误码。

### 9.4 已证伪、勿再尝试的方向

- **ADSP 固件争用 SoundWire**：之前的主要怀疑，但见 §7.4——clash 在控制器注册（8.835s）之前的 8.734s 就出现，且与 ADSP 的 `GET_SPF_STATE` 超时无直接因果。更关键的是供电 bug 和 pinctrl bug 修复后现象发生变化，说明问题在 Linux 侧配置。
- **WSA macro / soundwire 的 autosuspend 竞态**：实测播放时两者都正确 `active`。
- **SD_N 引脚死锁**：devmem 强制输出高后 slave 仍不 attach。
## 10. 重要提醒

- **不要在运行时读 slave 寄存器 debugfs**：会阻塞内核线程，导致 shell 服务（TCP 23）失去响应，只能长按电源键重启。
- 音频模块重载（`modprobe -r snd_soc_sc8280xp`）后组件仍绑定旧 card，会报 `already bound to card`，需要重启才能干净测试。
- `soundwire_qcom` 是模块（`CONFIG_SOUNDWIRE_QCOM=m`），改驱动后可只替换 `.ko` 而无需刷机。
