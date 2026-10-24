# PM8550B HV Haptics 驱动逆向记录（2026-10-22）

## 一、硬件与软件定位

### 真实硬件

振动马达由 **PM8550B PMIC 内置的 HV haptics** 驱动，不是独立的 I2C 芯片，也不走 SoundWire。

| 项 | 值 |
| --- | --- |
| PMIC | PM8550B，SPMI 地址 **0x07** |
| 节点路径 | `/soc@0/spmi@c400000/pmic@7/hv-haptics@f000` |
| 寄存器块 | `reg = <0xf000 0xf100 0xf200>`（3 块） |
| 中断 | `<7 0xf0 1 1>`（fifo-empty） |
| 马达类型 | `qcom,vibrator-type = <0x270f>` = **9999**（LRA 线性马达） |
| 驱动电压 | `qcom,vmax-mv = <0x6b8>` = 1720 mV |
| LRA 周期 | `qcom,lra-period-us = <0x1e0c>` = 7692 us |
| 刹车 | `brake-mode = 0`，`brake-pattern = [ff 3f 1f]` |
| 信号形状 | `drv-sig-shape = 1`，`brake-sig-shape = 1` |
| 校准存储 | `nvmem = "hap_cfg_sdam"` |

### 重要纠正

调试音频时看到的 `swr_haptics@f0170220`（`sdw:2:0:0217:f002:00:0`，已 Attached）在 vendor DTB 里是 **`status = "disabled"`**，不是实际使用的振动通路。真正路径是 PMIC 的 SPMI 直连 HV haptics。

## 二、vendor 内核模块逆向（关键成果）

### 模块来源

vendor_dlkm 分区（**ext4**，不是 erofs —— 注意这点，初次挂载踩过坑）：

```
/root/dlkm/lib/modules/qcom-hv-haptics.ko    233112 B, aarch64, not stripped
/root/dlkm/lib/modules/haptic_feedback.ko
/root/dlkm/lib/modules/swr_haptics_dlkm.ko
```

反汇编需用工具链里的 `aarch64-none-linux-gnu-objdump`（系统自带 objdump 不支持 aarch64，会报 `can't disassemble for architecture UNKNOWN`）。

### 核心函数清单

```
haptics_hw_init                     硬件初始化
haptics_probe / remove / suspend / resume
haptics_enable_play                 启动播放 ★
haptics_play / haptics_playback     播放入口
haptics_set_fifo                    FIFO 配置 ★
haptics_fifo_hw_status              FIFO 状态查询
haptics_fifo_prgm_status            FIFO 编程状态
haptics_get_available_fifo_memory   FIFO 剩余空间
haptics_get_fifo_fill_status
haptics_set_vmax_mv                 电压设置 ★
haptics_toggle_module_enable        模块使能开关 ★
haptics_set_brake                   刹车控制 ★
haptics_set_direct_play             直接播放模式 ★
haptics_set_pattern                 波形模式
haptics_set_gain                    增益
haptics_set_fifo_empty_threshold    FIFO 空阈值
haptics_config_openloop_lra_period  开环 LRA 周期
haptics_get_closeloop_lra_period    闭环 LRA 周期
haptics_enable_hpwr_vreg            高压电源使能
haptics_enable_autores              自动谐振
haptics_wait_hboost_ready           等待升压就绪
haptics_freeze / haptics_erase      冻结/擦除
haptics_load_predefined_effect      加载预置效果
haptics_upload_effect               FF 效果上传
haptics_read / haptics_status
```

### 寄存器映射（全部相对 base = 0xf000）

通过反汇编各函数提取的 `regmap_*` 调用中 `add w8, w8, #0xNN` 指令得到：

| 偏移 | 操作 | 用途 | 来源函数 |
| --- | --- | --- | --- |
| `+0x0d` | bulk_read | 版本/ID | `hw_init` |
| `+0x24` | update_bits mask=0x0f | 配置 | `set_fifo` |
| `+0x26` | bulk_write 1B | direct play 模式 | `set_direct_play` |
| `+0x2d` | bulk_write | FIFO 参数 | `set_fifo` |
| **`+0x46`** | **bulk_write 2B** | **模块使能**（写 `0x64,0x65`） | `toggle_module_enable` |
| `+0x4c` | bulk_write 5B | 播放数据 | `enable_play` |
| `+0x50` | update_bits mask=0xcc | **刹车控制** | `set_brake` |
| `+0x5e` | bulk_write 2B | FIFO 配置 | `set_fifo` |
| **`+0x66`** | **bulk_write 1B = 0x07** | **播放使能** | `enable_play` |
| **`+0x67`** | **bulk_write 1B** | **Vmax 设置** | `set_vmax_mv` |
| `+0x68` | update_bits val=0x03 | 频率配置（比较 0x2710=10000） | `enable_play` |
| `+0x70` | bulk_read | 状态读取 | `hw_init` |
| **`+0x72`** | **update_bits mask=0x0c** | **FIFO/播放控制**（0x0c→0x04） | `enable_play`, `set_fifo` |

### 实测寄存器值（设备上读取）

| 寄存器 | 值 | 解读 |
| --- | --- | --- |
| `f00d` | `0x03` | 版本 |
| `f024` | `0x00` | 未配置 |
| `f026` | `0x00` | 非 direct play 模式 |
| `f02d` | `0x00` | — |
| **`f046`** | **`0x80`** | **模块已使能** |
| `f047` | `0xde` | 使能第二字节 |
| `f04c` | `0x01` | 播放数据 |
| `f050` | `0x41` | 刹车配置 |
| `f066` | **`0x00`** | **播放使能关闭（空闲态，符合预期）** |
| `f067` | `0x0a` | Vmax = 10 |
| `f068` | `0x54` | 频率 = 0x54 = 84 |
| `f072` | `0x04` | FIFO 控制 |

### 驱动中的关键提示字符串

```
"set Vmax failed, toggle HAPTICS_EN to restore HW status"     ← HAPTICS_EN 使能信号
"FIFO HW status: filled = %u, available = %u, full = %d, empty = %d"
"FIFO program status: writing %u bytes, written %u bytes, total %u bytes"
"play enable: %d"
"Detect LRA frequency failed, rc=%d"
"store cl_t_lra_us:%d"
"allowed tuples: [amplitude(<= 0x1ff) period(<=6(T_LRA_X_8)) f_lra_x2(0,1)]"
"HBoost is enabled in open loop condition"
"hboost is not ready for haptics play"
```

这些说明：
- 幅度上限 **0x1ff**
- 周期上限 **6**（单位 T_LRA_X_8）
- 需要等待 **HBoost**（升压）就绪

## 三、访问路径的技术要点（踩坑记录）

### 1. 子节点是 platform_device，不是 spmi_device

PMIC 子节点由 `qcom-spmi-pmic`（MFD 驱动）通过 `devm_of_platform_populate()` 创建：

```c
// drivers/mfd/qcom-spmi-pmic.c:284
return devm_of_platform_populate(&sdev->dev);
```

因此驱动必须写成 **`platform_driver`** 而非 `spmi_driver`。SPMI 句柄需从父设备向上查找：

```c
parent = pdev->dev.parent;
while (parent && strcmp(parent->bus->name, "spmi"))
        parent = parent->parent;
sdev = to_spmi_device(parent);
```

实际设备路径：
```
/sys/devices/platform/soc@0/c400000.spmi/spmi-0/0-07/c400000.spmi:pmic@7:hv-haptics@f000
```

### 2. 0xf000 需要 16 位地址访问

`spmi_register_read()` 只接受 **u8 地址**，读 `0xf000` 会返回 `-19 (ENODEV)` / `-22 (EINVAL)`。

必须用扩展访问器：

```c
spmi_ext_register_readl(sdev, 0xf000 + off, &val, 1);
spmi_ext_register_writel(sdev, 0xf000 + off, &val, 1);
```

### 3. reg 数组长度

```c
// 错误：reg 只有 3 个值，传 min=max=6 会返回 -75 (EOVERFLOW)
of_property_read_variable_u32_array(np, "reg", regs, 6, 6);
// 正确：
of_property_read_variable_u32_array(np, "reg", regs, 1, 8);
```

### 4. 大文件上传会丢字节

256 KB 的 .ko 直接走单次 base64 传输会丢 3 字节导致 sha256 不匹配、模块加载失败（表现为无声卡/无 dmesg）。
必须**分块上传 + 每块校验**（32 KB 一块，最后整体 sha256 比对）。

### 5. dump 范围要覆盖到 0x80

关键寄存器 `f046`/`f066`/`f067`/`f072` 都在 0x40 以上，初次只 dump 0x00-0x3f 会漏掉全部关键信息。

## 四、当前进展与下一步

### 已完成

| 项 | 状态 |
| --- | --- |
| DTB 节点（第 10 条补丁） | ✅ 已加入并刷入生效 |
| 驱动绑定 | ✅ `bound! pmic=0-07 base=0xf000 regs=3` |
| SPMI 读写通路 | ✅ 全部 `rc=0`，读到真实值 |
| debugfs 工具 | ✅ `/sys/kernel/debug/hv_haptics/{dump,wr}` |
| vendor 模块逆向 | ✅ 函数清单 + 寄存器映射表 |
| 寄存器实测 | ✅ 14 个关键寄存器值已记录 |

### 待验证

单独写 `f066 = 0x07` **不生效**（写入返回 0，但读回 0 —— 该寄存器为只写型）。

`haptics_enable_play()` 的完整序列还需要：

1. `+0x46` 写 2 字节模块使能
2. `+0x68` update_bits val=3（频率）
3. `+0x72` update_bits mask=0xc val=0xc 再 val=0x4（FIFO 控制）
4. `+0x4c` 写 5 字节播放数据
5. 最后 `+0x66` 写 0x07 启动

**且需要先通过 `haptics_set_fifo()` 把波形数据灌入 FIFO，并确保 HBoost 升压就绪。**

### 建议的下一步

按逆向出的完整序列实现播放函数，而不是单点写使能。具体：

1. 用 `haptics_set_fifo` 的路径：`+0x24`(mask 0xf) → `+0x5e`(2B) → `+0x72`(mask 0xc, val 8) 配置 FIFO
2. 通过 `+0x4c` 或 FIFO 口写入正弦波形数据
3. `+0x66` = 0x07 启动
4. 播放后 `+0x50` 刹车

由于寄存器语义仍靠推断，**必须先小步验证每一环**，且写错可能导致 PMIC 异常（需要重启恢复）。

## 五、相关文件

| 文件 | 说明 |
| --- | --- |
| `out/ut-test/qcom_hv_haptics_probe.ko` | 探测驱动（platform driver + debugfs） |
| `out/ut-test/oneplus-xigua-hap.dtb` | 含 haptics 节点的 DTB |
| `/root/hapdrv/ref/qcom-hv-haptics.ko` | vendor 原始模块（逆向用） |
| `/root/hapdrv/ref/syms.txt` | 符号表导出 |
| `source-patches.json` 第 10 条 | haptics 节点 DTS 补丁 |
| `docs/audio-sm8550-status.md` §8.11 | 外放 TFA9874 的发现（顺带查出 haptics 型号） |
