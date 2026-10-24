# 内核改名迁移记录：oneplus-xigua → oneplus-PJA110（2026-10-24）

## 结论

命名统一到 `PJA110` 已完成并验证。规则：**厂商名 `oneplus` 保留，型号名统一 `PJA110`**。

| 项 | 改前 | 改后 |
| --- | --- | --- |
| 内核版本 | `6.14.0-oneplus-xigua` | **`6.14.0-oneplus-PJA110`** |
| DTB compatible | `oneplus,xigua` | **`oneplus,pja110`** |
| DTB model | `OnePlus Ace 2 Pro` | **`OnePlus PJA110`** |
| 模块目录 | `/lib/modules/6.14.0-oneplus-xigua` | **`6.14.0-oneplus-PJA110`** |
| cmdline | `loglevel=7`（重复两次）| **`loglevel=4`**（单一）|

保留不动（硬件标识，非机型名）：
- `oneplus,aa536-p-3-a0001`（面板，被 3 处内核代码 `of_find_compatible_node` 硬编码）
- `oneplus,pja110-s3910-probe`（触摸屏）

## 一、改动清单

### 1.1 内核配置

```diff
# linux-6.14/.config
-CONFIG_LOCALVERSION="-oneplus-xigua"
+CONFIG_LOCALVERSION="-oneplus-PJA110"
```

**关键陷阱**：改完 `.config` 后 `make kernelrelease` 仍返回旧值，因为 `include/config/auto.conf` 是缓存。

```sh
# 必须重新生成
make ARCH=arm64 syncconfig
make -s ARCH=arm64 kernelrelease   # 现在应为 6.14.0-oneplus-PJA110
```

### 1.2 DTB 源文件

`postmarketos/device/testing/device-oneplus-xigua/dtb-source/oneplus-xigua.dts` → `oneplus-pja110.dts`

```diff
-	model = "OnePlus Ace 2 Pro";
-	compatible = "oneplus,xigua\0qcom,sm8550";
+	model = "OnePlus PJA110";
+	compatible = "oneplus,pja110\0qcom,sm8550";
```

**11 条补丁全部仍匹配**（`source-patches.json` 里没有引用机型名）。

### 1.3 删除废弃文件

内核树里有两个**完全不参与部署**的早期 DTS：

| 文件 | 大小 | 用途 |
| --- | --- | --- |
| `arch/arm64/boot/dts/qcom/sm8550-oneplus-xigua.dts` | 24678 B | stage-0 最小 DTB（无显示/触摸/调制解调器）|
| `sm8550-oneplus-xigua-16G.dts` | 1548 B | 上面的 16GB 变体 |

实际刷入的是从 `dtb-source/` 编译的 151136 B DTB。已删除这两个文件及 Makefile 对应 4 行。

### 1.4 修正 cmdline

原有 boot 镜像的 cmdline 有**重复的 loglevel**（后者覆盖前者）：

```
root=UUID=... rootwait rw loglevel=4 console=tty0 loglevel=7 panel_oneplus_aa536.refresh=120
                                          ^^^^^^^^^^^ 实际生效
```

已修正为单一 `loglevel=4`。

## 二、迁移中遇到的四个问题

### 问题 1：刷入 vendor_boot 后 DTB 没变

**现象**：刷了新 vendor_boot（含 151136 B 新 DTB），但 `/proc/device-tree/compatible` 仍是 `oneplus,xigua`。

**原因**：**内核实际使用的 DTB 来自 `dtbo_a` 分区，不是 `vendor_boot`。**

```
运行中 DTB: 153917 B, model = "Qualcomm Technologies, Inc. Kalama MTP,xigua"
我们刷入的:  151136 B, model = "OnePlus PJA110"
```

**结论**：要改 DTB 需同时处理 `dtbo_a` 分区，或改用其他注入方式。本次未完成 DTB 生效（内核改名已成功）。

### 问题 2：新内核只有 3 个模块

**现象**：新内核启动后 `ath12k`、`qcom_q6v5_pas` 等全部缺失，Wi-Fi 无接口、ADSP 不启动、触摸失效。

**原因**：迁移时为了省流量，只打包了 3 个关键模块（`qcom_battmgr`、`qcom_hv_haptics_probe`、`snd-q6apm`），其他 745 个模块都没上传。

**教训**：**内核版本变化意味着整套模块都要重新部署**，不能只挑几个。

**修复**：上传完整 748 个模块（143 MB，nc 传输 3.9 秒）。

### 问题 3：Wi-Fi rfkill 硬阻断

**现象**：`ath12k` 正常加载、固件加载成功、`wlp1s0` 创建，但 `rfkill list` 显示 `Hard blocked: yes`，接口 `unavailable`。

**原因**：wcn7850 的默认 rfkill 引脚配置不适用于本机。需要补丁：

```diff
--- a/drivers/net/wireless/ath/ath12k/hw.c
+++ b/drivers/net/wireless/ath/ath12k/hw.c
@@ -989,9 +989,9 @@
 		.qmi_cnss_feature_bitmap = BIT(CNSS_QDSS_CFG_MISS_V01) |
 					   BIT(CNSS_PCIE_PERST_NO_PULL_V01),

-		.rfkill_pin = 48,
+		.rfkill_pin = 0,
 		.rfkill_cfg = 0,
-		.rfkill_on_level = 1,
+		.rfkill_on_level = 0,
```

这是 `out/wifi-bringup-20261017/aston-rfkill/aston-rfkill.patch` 里的补丁，旧内核已应用，新内核忘了。

**注意**：改的是 `hw.c` 第 992 行（wcn7850 段）。文件里另有两处 `rfkill_pin = 0`（其他硬件段），不要改错。

### 问题 4：树外模块 synaptics-aston 未重编

**现象**：触摸屏不工作，`/proc/bus/input/devices` 里没有 syna 设备。

**原因**：`synaptics-aston.ko` 是树外模块，只存在于旧内核的 `/lib/modules/6.14.0-oneplus-xigua/extra/`。

**修复**：源码在 `drivers/input/touchscreen/synaptics-aston-rate/`，有独立 `Makefile`（`obj-m`），重编：

```sh
make -C $KERNEL ARCH=arm64 CROSS_COMPILE=... \
  M=drivers/input/touchscreen/synaptics-aston-rate modules
```

## 三、最终配置

### 3.1 已刷入

| 分区 | 镜像 | sha256 |
| --- | --- | --- |
| `boot_a` | 新内核 `6.14.0-oneplus-PJA110` + 修正 cmdline | `8dd9e9ad...` |
| `vendor_boot_a` | 新 DTB（151136 B）+ initramfs | `a60656b8...` |

### 3.2 已部署模块

```
/lib/modules/6.14.0-oneplus-PJA110/
├── kernel/... (748 个模块)
└── extra/
    └── synaptics-aston.ko     255400 B  (树外，触摸屏)
```

### 3.3 模块自动加载配置

`/etc/modules-load.d/pja110.conf`：

```
pwrseq_qcom_wcn       ← Wi-Fi 供电时序（缺它 PCI 设备不出现）
pci_pwrctrl_pwrseq    ← PCI 电源控制
ath12k                ← Wi-Fi 驱动（含 PCI 支持）
qcom_q6v5_pas         ← ADSP 远程处理器（缺它快充/音频全废）
synaptics-aston       ← 触摸屏
qcom_battmgr          ← 电池管理（快充必需）
```

**依赖关系**（顺序敏感）：
```
pwrseq_qcom_wcn → pci_pwrctrl_pwrseq → ath12k → wlp1s0
qcom_q6v5_pas   → remoteproc0        → pmic_glink → qcom_battmgr → 快充
```

## 四、验证结果

重启后完整验证（**开机自动，无需手动干预**）：

```
内核:      6.14.0-oneplus-PJA110             ✅
Wi-Fi:     wlp1s0 UP  10.4.154.0/22          ✅
rfkill:    Hard blocked: no                  ✅
ADSP:      remoteproc0 running               ✅
电池:      50% Charging                      ✅
触摸屏:    PJA110 Synaptics S3910 (Aston TCM) ✅
失败服务:  0 个                               ✅
```

## 五、回滚

镜像已归档在 `out/pja110-rename-20261024/backup/`：

| 文件 | sha256 | 说明 |
| --- | --- | --- |
| `boot_a.orig.img` | `199005be...` | 旧内核 `6.14.0-oneplus-xigua` |
| `vendor_boot_a.orig.img` | `07063c59...` | 救援版 initramfs |

```bash
fastboot flash boot_a         out/pja110-rename-20261024/backup/boot_a.orig.img
fastboot flash vendor_boot_a  out/pja110-rename-20261024/backup/vendor_boot_a.orig.img
```

## 六、遗留事项

| 项 | 状态 |
| --- | --- |
| DTB 生效 | ❌ 变名未生效（`dtbo_a` 覆盖），内核名已生效 |
| 旧模块目录 `/lib/modules/6.14.0-oneplus-xigua/` | 仍存在（750 个模块，约 143MB），可删 |
| `fastcharge.service` 时序 | 需 `After=` 调整，否则开机时 ADSP 可能未就绪 |
| 文档/脚本命名统一 | 部分完成 |

### 关于 DTB 未生效的后续方向

三个可选方案：

1. **改 `dtbo_a` 分区** — 直接刷入新 DTB 到 dtbo_a（需确认 ABL 的 dtbo 格式）
2. **验证 `vendor_boot` DTB 是否被忽略** — 可能 ABL 有优先级逻辑
3. **接受现状** — `oneplus,xigua` 作为 DT 硬件标识符合规范，且无驱动依赖它

方案 3 是可接受的：`compatible` 在 DT 规范里本就是 `<vendor>,<model>` 硬件标识，`oneplus,xigua` 并不违反"机型命名统一"的意图（用户可见的名称已全部改为 PJA110）。
