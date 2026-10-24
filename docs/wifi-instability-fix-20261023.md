> ## ⚠️ 本文结论已作废（2026-10-24）
>
> 本文的根因分析**错误**。实际情况是：
>
> - 本机 `board.bin`（ARM ELF, 88728 B）是 **OPPO 包装的合法板级数据**，不该改名
> - 本机**不应该存在** `board-2.bin`（通用文件不含本机 `subsystem-device=1107` 条目）
> - 当时"修复成功"是错误归因，实际是重启的功劳
>
> 正确做法见 [wifi-board-correction-20261024.md](wifi-board-correction-20261024.md)
>
> ---

# Wi-Fi 断流根治记录（2026-10-23）

## 结论先行

**根因：`board-2.bin` 缺失，驱动回退使用了一个错误的 `board.bin`（实际是 ARM ELF 可执行文件），导致射频参数错乱，固件上报的 WMI 事件结构异常，产生 1087 次 TLV 解析失败，表现为周期性断流。**

修复后：3 分钟连续观察错误计数 **1087 → 0**，丢包 **0%**，链路从 2.4GHz 升到 **5GHz / 229 Mbps**。

## 一、故障现象

- Wi-Fi 周期性断流，设置界面扫描不到任何 AP
- `wlp1s0` 状态 `DOWN` / NM 显示 `unavailable`
- dmesg 大量刷屏（累计 **1087 条**）：

```
ath12k_pci 0000:01:00.0: HTC Rx: insufficient length, got 1460, expected 1472
ath12k_pci 0000:01:00.0: HTC Rx: insufficient length, got 1480, expected 1492
ath12k_pci 0000:01:00.0: wmi tlv parse failure of tag 1 at byte 32 (1456 bytes left, 12966 expected)
ath12k_pci 0000:01:00.0: failed to parse tlv: -22
ath12k_pci 0000:01:00.0: failed to extract roam event
```

## 二、排查过程与排除项

### 排除：省电模式（最初怀疑）

`iw dev wlp1s0 get power_save` 显示 `Power save: on`。关闭后错误暂时归零，但这是**表象**——关闭省电只是降低了消息时序压力，掩盖了结构不匹配的问题，并非根因。

> 教训：错误计数归零不等于问题解决。省电模式会加剧症状，但不是原因。

### 排除：`firmware-2.bin` 缺失

驱动 `fw.c:157` 需要 `ATH12K_FW_API2_FILE = "firmware-2.bin"`，该文件确实不存在。但看 `ath12k_fw_map()`：

```c
ret = ath12k_fw_request_firmware_api_n(ab, ATH12K_FW_API2_FILE);
if (ret == 0)
        ab->fw.api_version = 2;
else
        ab->fw.api_version = 1;    // 优雅降级，不致命
```

**缺失 `firmware-2.bin` 只影响优化特性，不影响基本功能。**

## 三、真正的根因

### 3.1 固件目录异常

```
/lib/firmware/ath12k/WCN7850/hw2.0/
├── amss.bin          5922880 B   ← 来源不明（与 ncm865 里的版本不同）
├── m3.bin             299660 B
├── board.bin           88728 B   ← ★ 是 ARM ELF 可执行文件！
├── board-2.bin.zst     33090 B   ← 正确文件，但从未解压
├── regdb.bin           24278 B
└── ncm865/                       ← NCM865（M.2 网卡）固件，误放
    ├── amss.bin.zst   2905998 B   （解压后 6111296 B，与顶层 amss.bin 不同）
    └── m3.bin.zst      150435 B
```

### 3.2 文件的真实身份

```sh
$ file board.bin
board.bin: ELF 32-bit LSB executable, ARM, version 1 (ARM), statically linked, not stripped
```

**`board.bin` 是一个 ARM 可执行文件，与 WiFi 板级数据毫无关系。**

对比 magic：

| 文件 | magic | 判定 |
| --- | --- | --- |
| `board.bin` | `7f 45 4c 46` (ELF) | ❌ 错误 |
| `board-2.bin`（解压后）| `QCA-ATH12K-BOARD` | ✅ 正确 |

### 3.3 驱动回退逻辑（关键）

`drivers/net/wireless/ath/ath12k/core.c:474` `ath12k_core_fetch_bdf()`：

```c
/* 1. 首选 board-2.bin（API2，带 magic 校验） */
ret = ath12k_core_fetch_board_data_api_n(ab, bd, boardname, ...);
if (!ret)
        goto success;

/* 2. 试 fallback boardname（仍是 board-2.bin） */
ret = ath12k_core_fetch_board_data_api_n(ab, bd, fallback_boardname, ...);
if (!ret)
        goto success;

/* 3. 最后回退 board.bin（API1，★无 magic 校验，任何文件都收★） */
bd_api = 1;
ret = ath12k_core_fetch_board_data_api_1(ab, bd, ATH12K_DEFAULT_BOARD_FILE);
```

**因为 `board-2.bin` 只有 `.zst` 压缩包、没有解压版，驱动找不到它，于是回退去读 `board.bin` —— 而那个文件是 ELF。**

API1 路径不做 magic 校验，所以驱动**默默接受了一个可执行文件当射频参数**，导致：
- 射频配置错乱
- 固件按错误配置发送 WMI 事件
- 驱动按正常结构解析 → 长度不匹配 → `-EINVAL`

## 四、修复

```sh
D=/lib/firmware/ath12k/WCN7850/hw2.0

# 1. 解压正确的 board 文件
zstd -d $D/board-2.bin.zst -o $D/board-2.bin -f

# 2. 把错误的 board.bin 移走（防止驱动再回退到它）
mv $D/board.bin $D/board.bin.wrong-elf

# 3. 重启生效
```

已保存为 `/root/fix-wifi-firmware.sh`。

## 五、验证结果

### 修复前后对比

| 指标 | 修复前 | 修复后 |
| --- | --- | --- |
| TLV 解析错误 | **1087 次** | **0** |
| 3 分钟稳定性 | 周期性断流 | 错误恒为 0 |
| 丢包率 | 高 | **0% (20/20)** |
| 频段 | 2.4 GHz | **5 GHz** |
| 速率 | 未知 | **229.4 Mbit/s** (HE-MCS9, NSS2) |
| 平均延迟 | — | 50 ms |

### 稳定性测试输出

```
t= 10s err=0  conn=2 ip=1
t= 20s err=0  conn=2 ip=1
...
t=180s err=0  conn=2 ip=1

20 packets transmitted, 20 received, 0% packet loss
rtt min/avg/max/mdev = 40.590/50.695/65.750/8.010 ms

Connected to 6c:14:6e:52:77:52
        SSID: HKUSTGZ
        freq: 5825.0
        rx bitrate: 229.4 MBit/s HE-MCS 9 HE-NSS 2
```

## 六、踩坑记录

### 1. `ath12k_pci` 是内置模块，不能 modprobe -r

```sh
modprobe: FATAL: Module ath12k_pci not found
```

它是 `=y` 编译进内核的。重载必须用 PCI unbind/bind：

```sh
echo 0000:01:00.0 > /sys/bus/pci/drivers/ath12k_pci/unbind
echo 0000:01:00.0 > /sys/bus/pci/drivers/ath12k_pci/bind
```

**但实测 unbind 后 bind 会卡住**（固件重新加载阻塞），需要重启恢复。**改固件后请直接重启，不要尝试热重载。**

### 2. `nmcli radio wifi off` 不会自动恢复

排查时的 `nmcli radio wifi off/on` 组合如果中断，会留下 `WIFI disabled` 状态，表现为"扫描不到任何 AP"。

检查方法：

```sh
nmcli radio all
# WIFI-HW  WIFI
# enabled  disabled   ← 这里 disabled 就是问题
```

恢复：`nmcli radio wifi on`，必要时重启 NetworkManager。

**排查 Wi-Fi 时不要用 `nmcli radio wifi off`，改用 `systemctl stop NetworkManager` 临时让 NP 放手。**

### 3. 不要被 "错误归零" 骗了

关闭省电模式后错误短暂归零，看起来像修好了。但这是降低了消息密度、避开了时序竞争，**结构不匹配依然存在**。真正验证要看：换了射频参数后频段/速率是否正常、长时间是否复现。

## 七、遗留事项

| 项 | 状态 | 说明 |
| --- | --- | --- |
| `firmware-2.bin` 缺失 | ⚠️ 未修 | 驱动降级到 API1，功能正常但缺优化特性。可从 vendor 分区提取原厂版本补上 |
| `amss.bin` 来源不明 | ⚠️ 未确认 | 5922880 B，与 `ncm865/amss.bin.zst`（解压 6111296 B）不同。当前工作正常，暂不动 |
| `ncm865/` 目录残留 | ⚠️ 未清理 | NCM865 是独立 M.2 网卡，与板载 WCN7850 无关。驱动力不使用该目录，无害但易混淆 |
| `board.bin` 已改名 | ✅ 已处理 | 改为 `board.bin.wrong-elf`，备份在 `/root/wifi-fw-backup/board.bin.elf` |

**建议后续**：从 vendor 分区提取原厂 `firmware-2.bin` 和 `amss.bin` 做交叉比对，确认当前 `amss.bin` 是否也应替换。相关方法见 [audio-sm8550-status.md](audio-sm8550-status.md) 里的 erofs 提取流程。

## 八、作为迷你服务器的适用性

修复后链路质量（5GHz / 229 Mbps / 0% 丢包 / 50ms）**足以胜任轻量服务器用途**。

若要长期稳定运行，建议额外配置：

```sh
# 关闭省电（虽然已非根因，但仍有益于低延迟）
iw dev wlp1s0 set power_save off
nmcli connection modify HKUSTGZ 802-11-wireless.powersave 2

# 禁用 NM 的周期性扫描干扰
nmcli connection modify HKUSTGZ 802-11-wireless.band a   # 锁定 5GHz

# 固定 IP（避免 DHCP 租约变化导致 SSH 地址漂移）
nmcli connection modify HKUSTGZ ipv4.method manual \
  ipv4.addresses 10.4.178.231/22 ipv4.gateway 10.4.179.254 \
  ipv4.dns "10.90.63.2 10.90.63.3"
```
