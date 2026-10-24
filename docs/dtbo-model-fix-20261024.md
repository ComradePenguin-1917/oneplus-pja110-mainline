# PJA110 设备树 model 修正：改 dtbo_a 而非 vendor_boot（2026-10-24）

本文记录一个长期存在的困惑的最终答案：
**为什么改了 DTB 里的 `model`，`/proc/device-tree/model` 却不变？**

结论：**实际生效的 DTB 来自 `dtbo_a` 的 DTBO overlay，不是 `vendor_boot_a` 里的基准 DTB。**

---

## 一、现象

| 位置 | model | compatible |
| --- | --- | --- |
| 我们的源码 `oneplus-pja110.dts` | `OnePlus PJA110` | `oneplus,pja110` |
| 刷进 `vendor_boot_a` 的基准 DTB | `OnePlus PJA110` | `oneplus,pja110` |
| **运行中的 `/proc/device-tree/model`** | **`Qualcomm Technologies, Inc. Kalama MTP,xigua`** | **`oneplus,xigua`** |

`Kalama` 是高通 SM8550 的内部代号，`MTP` = Mobile Test Platform，
这是**厂商内部测试平台名**，不是产品名。

多次改 DTS 并刷 `vendor_boot_a` 都无效。

---

## 二、根因：dtbo_a 是 DTBO overlay 镜像

`/dev/sde17`（PARTLABEL 为 `dtbo_a`，24 MB）里不是裸 DTB，而是
**Android DTBO 镜像**（`dt_table_header`，magic `0xd7b7ab1e`）：

```
magic            = 0xd7b7ab1e
total_size       = 966454
header_size      = 32
dt_entry_size    = 32
dt_entry_count   = 4
dt_entries_offset= 32
page_size        = 4096
version          = 0
```

4 个条目，每个都是很小的 DTB（582–610 字节）：

| # | 大小 | 偏移 | 内容 |
| --- | --- | --- | --- |
| 0 | 594 | 160 | selector DTB |
| 1 | 610 | 148728 | selector DTB |
| 2 | 582 | 482092 | selector DTB |
| 3 | 598 | 631871 | selector DTB |

反编译后（4 个结构相同，只有匹配条件不同）：

```dts
/dts-v1/;

/ {
	model = "Qualcomm Technologies, Inc. Kalama MTP,xigua";
	compatible = "oneplus,xigua", "qcom,sm8550";
	qcom,msm-id = <0x258 0x20000 0x259 0x20000>;   /* SoC ID + revision */
	qcom,board-id = <0x10008 0x00>;
	oplus,project-id = <0x5943>;
	oplus,hw-id = <0x28 0x18 0x20 0x10>;           /* OPPO 硬件 ID */

	fragment@0 {
		target = <0xffffffff>;

		__overlay__ {
			xigua-avb-control {
				experiment = "avb-valid-overlay-v2";
			};
		};
	};

	__fixups__  { soc = "/fragment@0:target:0"; };
	__symbols__ { };
	__local_fixups__ { };
};
```

**ABL 按 `qcom,msm-id` / `qcom,board-id` / `oplus,hw-id` 选出其中一个，
叠加到基准 DTB 上，并把它根节点的 `model`、`compatible` 覆盖掉。**

这解释了此前所有"改了不生效"的尝试。

---

## 三、修复方案

只替换 4 个 selector DTB 里的 `model` 字符串，**其它一切保持原样**。

### 3.1 为什么不用"等长补零"

最初尝试的原地替换（写 `"OnePlus PJA110"` + NUL 补齐到原长度 44 字节）虽然
内核能正确读出（`of_property_read_string` 遇 NUL 停止），但 `dtc` 会把该属性
显示成字节数组，且 `/proc/device-tree/model` 文件里会带尾部 NUL，
对按字符串比较的工具不友好。因此改用下面的方式。

### 3.2 实际做法：dtc 往返重建 + 保持原偏移

```python
# 1) 从 dtbo 镜像按 header 解析出 4 个 DTB
# 2) 每个 DTB: dtc -I dtb -O dts → 替换 model 行 → dtc -I dts -O dtb
# 3) 新 DTB 都比原 DTB 小（字符串短了 31 字节），可以原偏移写入
# 4) 写入后把该条目剩余字节清零，并把 header 里的 dtb_size 改成新大小
```

结果：

| # | 原大小 | 新大小 | 偏移（不变）|
| --- | --- | --- | --- |
| 0 | 594 | 550 | 160 |
| 1 | 610 | 566 | 148728 |
| 2 | 582 | 538 | 482092 |
| 3 | 598 | 554 | 631871 |

### 3.3 自检

```
header:  magic=0xd7b7ab1e total=966454 count=4 page=4096           ✅
entry0:  size=550 offset=160    FDT=True totalsize=550            ✅
entry1:  size=566 offset=148728 FDT=True totalsize=566            ✅
entry2:  size=538 offset=482092 FDT=True totalsize=538            ✅
entry3:  size=554 offset=631871 FDT=True totalsize=554            ✅

反编译 4 个条目：
  p0/p1/p2/p3: model = "OnePlus PJA110";                          ✅
```

与原始镜像的**差异范围**（只集中在 4 个 DTB 区域，其它字节完全一致）：

```
0x000023 .. 0x0002e4    (entry0)
0x0244ff .. 0x02474c    (entry1)
0x075b33 .. 0x075d64    (entry2)
0x09a446 .. 0x09a687    (entry3)
```

---

## 四、写入方式：直接从 Linux 写分区

没有走 fastboot，理由：

- 避免设备进入 fastboot 再回来（此前出现过 bootloader 自己切到 B 槽导致卡死，
  见下文风险说明）
- 分区 24 MB，一次 `dd` + `fsync` 约 1 秒

安全措施（脚本里逐步校验，任一步不符即中止）：

1. 校验 `PARTLABEL == dtbo_a`
2. 校验文件大小 == 分区大小（25165824）
3. 校验分区未被挂载
4. 写入前先 sha256 确认当前内容 == 已知原始镜像
5. `dd conv=fsync` + `sync`
6. **回读整个分区再算 sha256，必须与写入文件一致**

实际执行记录：

```
$DEV PARTLABEL = 'dtbo_a'                                    ✅
分区大小 25165824 / 文件大小 25165824                          ✅
写入前分区 sha256: c52c02d0…（== 原始镜像）                    ✅
写入完成
回读: fd51e89b5819cdfd2afb3f1e9bdb8288ca2287f666f0e097baea9393fb704c2b
期望: fd51e89b5819cdfd2afb3f1e9bdb8288ca2287f666f0e097baea9393fb704c2b   ✅
回读镜像解析: magic=0xd7b7ab1e count=4                        ✅
```

---

## 五、重启后验证

```
$ cat /sys/firmware/devicetree/base/model
OnePlus PJA110                                  ← 修好了

$ cat /sys/firmware/devicetree/base/compatible
oneplus,pja110 qcom,sm8550                      ← 已同步修正

$ cat /sys/firmware/devicetree/base/chassis-type
handset
```

功能回归（全部正常）：

```
启动:   5.137s（kernel 1.375 + userspace 3.761）
系统:   running，失败服务 0，损坏包 0
Wi-Fi:  wlp1s0 connected (HKUSTGZ)
蓝牙:   active
触摸:   Synaptics S3910 在位
快充:   active
ADSP:   running
OSK:    1 个实例
刷新率: 120 Hz
```

---

## 六、`compatible` 的命名规范

### 6.1 为什么是 `oneplus,pja110` 而不是 `pja110`

Devicetree Specification 规定 `compatible` 是字符串列表，每项格式为
**`"manufacturer,model"`**。裸 `pja110` 没有厂商命名空间，会与其他厂商同名设备冲突，
`make dtbs_check` 会判为非法。

`oneplus` 前缀已在内核注册
（`Documentation/devicetree/bindings/vendor-prefixes.yaml`）：

```yaml
  "^oneplus,.*":
    description: OnePlus Technology (Shenzhen) Co., Ltd.
```

主线现有 OnePlus 机型全部是 `oneplus,<代号>`：

```dts
/* arch/arm64/boot/dts/qcom/ */
compatible = "oneplus,billie2",    "qcom,sm4250";
compatible = "oneplus,fajita",     "qcom,sdm845";
compatible = "oneplus,enchilada",  "qcom,sdm845";
compatible = "oneplus,oneplus3t",  "qcom,msm8996";
```

我们自己的 DTS 根节点本来也是这么写的：

```dts
model = "OnePlus PJA110";
compatible = "oneplus,pja110\0qcom,sm8550";
```

### 6.2 已同步修改（2026-10-24）

第一次只改了 `model`。随后确认 **内核侧没有任何模块匹配 `oneplus,xigua`**：

```
$ grep -rl "oneplus,xigua" /lib/modules/$(uname -r)/kernel/
匹配文件数: 0
```

且 `compatible` 列表第二项 `qcom,sm8550` 才是所有驱动真正匹配的目标
（面板、触摸、Wi-Fi、UART 等），第一项仅作机型标识 —— 改它对驱动绑定零影响。
因此从**原始镜像**重新做了一版，一次性改到位：

| 属性 | 原始 | 现在 |
| --- | --- | --- |
| `model` | `Qualcomm Technologies, Inc. Kalama MTP,xigua` | `OnePlus PJA110` |
| `compatible` | `"oneplus,xigua", "qcom,sm8550"` | **`"oneplus,pja110", "qcom,sm8550"`** |

### 6.3 顺序要求

`compatible` 列表必须**从最具体到最通用**排列：

```
"oneplus,pja110", "qcom,sm8550"
     ↑ 最具体        ↑ 最通用
```

不要反过来写。


---

## 七、产物与回滚

### 产物（`out/dtbo-a-fix/`）

| 文件 | 说明 | sha256 |
| --- | --- | --- |
| `dtbo_a.orig.img` | **原始镜像（回滚用）** 24 MB | `c52c02d0…` |
| `dtbo_a.pja110.img` | **最终镜像**（model + compatible 都已修正）| `46ddab6d…` |
| `dtbo_a.modelonly.img` | 中间版本（只改 model，留档）| `fd51e89b…` |
| `selector0-OnePlusPJA110.dtb` … `selector3-…` | 4 个重建后的 selector DTB | — |

### 回滚（设备无法启动时）

设备进 fastboot，然后：

```sh
fastboot flash dtbo_a out/dtbo-a-fix/dtbo_a.orig.img
fastboot reboot
```

### 从 Linux 回滚（设备能启动、想还原时）

```sh
sudo dd if=out/dtbo-a-fix/dtbo_a.orig.img of=/dev/sde17 bs=1M conv=fsync
sync
# 回读校验
sudo dd if=/dev/sde17 bs=1M count=24 status=none | sha256sum
# 应为 c52c02d091353bbd44cbadc2e9f84360ed4f2d2daefeb7a8bdf79ea2ba59ba11
```

---

## 八、风险提示：A/B 槽会自己切换

这一轮操作前后各重启一次，其中一次设备起不来（能 ping 通但 22 端口不监听），
进 fastboot 后发现：

```
$ fastboot getvar current-slot
current-slot: b            ← 被切到了 B 槽
```

B 槽没有系统，所以内核能启动、USB 网卡能通，但没有用户态服务。
用 `fastboot --set-active=a` 恢复。

**结论：这台设备的 bootloader 会在启动失败若干次后自动切槽。**
对交付镜像的要求：

- 安装流程结束必须 `fastboot getvar current-slot` 确认是 `a`
- 交付文档必须写明 `fastboot --set-active=a` 这一救援步骤
- 槽位状态存在 `/dev/sda3`（`misc`），不要随意擦写
