# Wi-Fi 板级数据配置纠正（2026-10-24）

## 结论先行

**2026-10-23 的"Wi-Fi 不稳定修复"结论是错的。** 我当时的判断与实际相反：

| 项 | 我当时做的（错误） | 正确做法 |
| --- | --- | --- |
| `board.bin`（88728 B，ARM ELF）| 改名为 `board.bin.wrong-elf` | ✅ **必须保留** —— 这是本机 OEM 选中的板级数据 |
| `board-2.bin` | 从 `.zst` 解压后放入 | ❌ **必须不存在** |

正确配置（Oct 17 已验证，Oct 24 再次确认）：

```
/lib/firmware/ath12k/WCN7850/hw2.0/
├── board.bin          88728 B   ← 保留，API1 路径使用
└── board-2.bin.zst    33090 B   ← 保留压缩包，但不解压
    （board-2.bin 必须不存在）
```

验证结果：`failed to fetch board` 错误数 **0**，Wi-Fi 正常连接 5GHz。

## 一、为什么之前的判断错了

### 1.1 当时的推理链（错误）

```
观察：board.bin 是 ARM ELF 文件（\177ELF magic）
推理：ELF 不可能是射频参数 → 一定是坏文件
行动：改名 board.bin，从 board-2.bin.zst 解压出"正确"的板级数据
结果：Wi-Fi 当时确实恢复（错误归因）
```

### 1.2 实际情况

**`board.bin` 是一个 ELF 文件，但它是 OPPO 包装 BDF 数据的合法方式。**

关键证据来自 Oct 17 的 `out/wifi-bringup-20261017/install-stock-board.sh`：

```sh
# Leave board-2 selection disabled: use this phone's OEM-selected board ELF.
test ! -e "$dest/board-2.bin"          # ← board-2.bin 必须不存在
for f in board.bin regdb.bin; do install -D -m 644 "$f" "$dest/$f"; done
echo 'OEM board ELF and regdb installed'
```

**注释明确写：使用本机 OEM 选中的 board ELF，禁用 board-2 选择路径。**

### 1.3 为什么当时"看起来"修好了

`ath12k` 的 BDF 加载顺序（`core.c` `ath12k_core_fetch_bdf()`）：

```c
/* 1. 首选 board-2.bin（API2，有 magic 校验） */
ret = ath12k_core_fetch_board_data_api_n(...);
if (!ret) goto success;

/* 2. fallback board-2.bin */
ret = ath12k_core_fetch_board_data_api_n(ab, bd, fallback_boardname, ...);
if (!ret) goto success;

/* 3. 最后回退 board.bin（API1，★无 magic 校验★） */
ret = ath12k_core_fetch_board_data_api_1(ab, bd, ATH12K_DEFAULT_BOARD_FILE);
```

API1 路径**不做 magic 校验**，所以它接受任何文件——包括那个 ELF。

**当时的实际情况：**
- `board.bin` 被改名 → API1 失败
- `board-2.bin` 被加入 → 但**里面没有 `subsystem-device=1107` 条目** → API2 也失败

**所以那次"修复"后 Wi-Fi 能用，是因为其他原因（重启、模块重载时序），而不是我改的固件。** 属于错误归因。

## 二、决定性证据：本机的 subsystem ID

```sh
$ cat /sys/bus/pci/devices/0000:01:00.0/subsystem_device
0x1107
$ cat /sys/bus/pci/devices/0000:01:00.0/subsystem_vendor
0x17cb
```

内核据此构造查找名：

```
bus=pci,vendor=17cb,device=1107,subsystem-vendor=17cb,subsystem-device=1107,qmi-chip-id=2,qmi-board-id=255
```

而两份 `board-2.bin`（`.zst` 解压版 1897968 B / wifi-bringup 版 1986952 B）包含的 `subsystem-device` 值：

```
3378, 337c, 6021, 8000, 8002, 8003, 8d68, 8d99, 910a, 930a, 940a,
950a, 960a, 9618, 970a, 980a, 9f0a, 9f18, e0dc, e0e6, e0e9, e0ea,
e0eb, e0ed, e0ee, e0ef, e0f3, e0f7, e0fb, e107, e109, e10a, e10d,
e114, e115, e122, e125, e129, e12b
```

**都不含 `1107`。** 这类 `board-2.bin` 是给 M.2 网卡（NCM865 等）用的通用文件，不适用于本机这颗板载 WCN7850。

## 三、故障现象对照

### 3.1 加入 board-2.bin 后的症状

```
ath12k_pci: failed to fetch board data for bus=pci,...,subsystem-device=1107,...
ath12k_pci: failed to fetch board.bin from WCN7850/hw2.0
ath12k_pci: qmi failed to load bdf:
ath12k_pci: qmi failed to load board data file:-2

→ 没有 wlp1s0 接口
```

### 3.2 恢复正确配置后

```
wlp1s0  UP  10.4.153.234/22
nmcli:  wlp1s0:connected:HKUSTGZ
dmesg:  failed to fetch board = 0 次
```

## 四、正确操作步骤

### 4.1 安装（已验证）

```sh
sudo rm -f /lib/firmware/ath12k/WCN7850/hw2.0/board-2.bin
sudo cp board.bin /lib/firmware/ath12k/WCN7850/hw2.0/board.bin
sudo cp regdb.bin /lib/firmware/ath12k/WCN7850/hw2.0/regdb.bin
sudo chmod 644 /lib/firmware/ath12k/WCN7850/hw2.0/board.bin
sudo reboot
```

### 4.2 为什么必须重启而不是重载模块

尝试过 `PCI unbind/bind` 触发 ath12k 重新加载，会导致内核 oops：

```
BUG: kernel NULL pointer dereference
pc : ath12k_mac_remove_link_interface.isra.0+0x3c/0x2e0 [ath12k]
lr : ath12k_mac_remove_link_interface.isra.0+0x34/0x2e0 [ath12k]
 ath12k_scan_vdev_clean_work+0x58/0x120 [ath12k]
```

这是 `ath12k` 在扫描工作项还挂着时强制拆除接口的缺陷。**修改 board 文件后必须重启。**

### 4.3 验证清单

```sh
# 1. 文件配置正确
ls /lib/firmware/ath12k/WCN7850/hw2.0/board*
# 应只有: board.bin  board-2.bin.zst
# 不应有: board-2.bin

# 2. 无 board 加载错误
dmesg | grep -c 'failed to fetch board'     # 应为 0

# 3. 接口存在且 up
cat /sys/class/net/wlp1s0/operstate          # up
ip -br addr show wlp1s0                      # 有 IP

# 4. NM 已连接
nmcli -t -f DEVICE,STATE,CONNECTION device | grep wlp
# wlp1s0:connected:HKUSTGZ
```

## 五、对历史文档的更正

`docs/wifi-instability-fix-20261023.md` 的以下结论**作废**：

| 原文结论 | 更正 |
| --- | --- |
| "根因：`board-2.bin` 缺失" | ❌ 错误。本机根本不该有 `board-2.bin` |
| "驱动回退使用错误的 `board.bin`（ARM ELF）" | ❌ 错误。那个 ELF 就是正确的板级数据 |
| "修复后 1087 → 0 错误" | ⚠️ 错误归因，实际是重启的功劳 |
| "`board.bin` → `board.bin.wrong-elf`" | ❌ 这个操作是有害的 |

**如果当时只在 Oct 17 的正确配置上保持不动，就不会有后续所有问题。**

## 六、教训

1. **不要仅凭 magic 判断文件有效性。** ELF 可以是合法的固件容器。Oct 17 的 `install-stock-board.sh` 里已经写明了正确做法，我应该先读它。

2. **驱动的 fallback 链意味着"能用"不等于"用对了文件"。** API1 不做校验，任何文件都能喂进去。

3. **验证修复要看设备实际需求。** 本机 `subsystem-device=1107`，而通用 `board-2.bin` 不含该条目——这个检查早该在放入文件前做。

4. **改固件后必须重启。** `unbind/bind` 会触发 ath12k 的 oops。

## 七、相关文件

| 文件 | 说明 |
| --- | --- |
| `out/wifi-bringup-20261017/install-stock-board.sh` | **权威参考**：Oct 17 已验证的安装脚本 |
| `out/wifi-bringup-20261017/firmware/ath12k/WCN7850/hw2.0/board-2.bin` | 通用版，**本机不适用** |
| 设备 `/lib/firmware/ath12k/WCN7850/hw2.0/board.bin` | ✅ 正确文件（88728 B ELF）|
| `board-2.bin.broken` / `board.bin.wrong-elf` 备份 | 可删除，属误操作产物 |
