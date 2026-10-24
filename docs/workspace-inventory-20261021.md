# 工作区盘点（2026-10-21）

目的：在继续修音频前，把文档、脚本、设备状态全部核对一遍，消除不一致与残留。

## 1. 文档现状

| 文档 | 状态 | 说明 |
| --- | --- | --- |
| `porting-status.md` | ✅ 已同步 | 项目唯一总览；音频状态已统一为「slave 停在 UNATTACHED」 |
| `audio-sm8550-status.md` | ✅ 已重写 | 章节 0–10 完整；含 12 项被证伪方案、devmem 寄存器表 |
| `bluetooth-wcn7850-status.md` | ✅ 已同步 | 五个被证伪假设（原写四个，已修正） |
| `native-upgrade.md` / `fastcharge-status.md` / `deepseek-baseline-*.md` / `fast-charge-high-refresh-assessment.md` | ✅ 保持 | 带日期的阶段性记录，不涉及音频/蓝牙，不改动 |
| `archive/*` | ✅ 保持 | UT/Lomiri 路线历史，已声明不作现状依据 |

本次修正的不一致：

- `porting-status.md` 三处仍写 `MASTER_CLASH_DET`，已统一为 `UNATTACHED`
- 音频文档索引写「9 disproved」，实际 12 项，已改
- 蓝牙文档索引写「四个被证伪」，实际五个，已改
- 音频文档章节编号重复（两个 `## 2.`），已重排为 0–10

## 2. 代码与产物现状

### 2.1 内核源码树（`~/workspace/PJA110-Mainline/charger-native-a/linux-6.14`）

**三个曾改过的驱动已确认全部恢复为纯净上游版本**（与 `~/.cache/linux-6.14.tar.xz` 解压结果逐字节一致）：

| 文件 | 状态 |
| --- | --- |
| `drivers/soundwire/qcom.c` | PRISTINE |
| `sound/soc/codecs/lpass-wsa-macro.c` | PRISTINE |
| `sound/soc/codecs/wsa884x.c` | PRISTINE |

> 教训：驱动备份不要放 `/tmp`，WSL 重启会丢。原始文件从 `~/.cache/linux-6.14.tar.xz` 提取，或存到 `/root/pristine-6.14/`。

### 2.2 DTB 补丁（`source-patches.json`，共 5 条）

| # | 节点 | 内容 |
| --- | --- | --- |
| 0 | `regulators-0/bob1` | bob1 微伏修正（pmOS 基线原有） |
| 1 | `serial@898000` | uart14 启用 + bluetooth 子节点（含 `local-bd-address`） |
| 2 | `soundwire@6b10000` | swr0 启用 + 两个 WSA8845 speaker 节点 |
| 3 | `/`（根） | sound 卡节点（WSA Playback + VA Capture） |
| 4 | `pinctrl@6e80000` | spkr1/2 SD_N 引脚复用（`output-high`） |

### 2.3 清理结果

- 删除 174 个 `tools/_tmp_*.sh` 中的 172 个（保留 2 个盘点用）
- 删除 4 个已证伪方案的实验模块：
  `soundwire-qcom-noautosuspend.ko`、`soundwire-qcom-patched.ko`、
  `wsa-macro-noautosuspend.ko`、`wsa884x-clkstop.ko`
- 保留 `swr-clean.ko`、`wsa-macro-clean.ko`、`wsa884x-clean.ko` 作为纯净参考

## 3. 设备状态（2026-10-21 实测）

| 项 | 值 |
| --- | --- |
| 槽位 / 内核 | A 槽，`6.14.0-oneplus-xigua` |
| 蓝牙 | ✅ `hci0 UP RUNNING`，`BD Address 02:00:00:00:5A:AD` |
| 声卡 | ✅ `card 0: Pro [OnePlus Ace 2 Pro]`，4 个 PCM |
| codec 供电 | ✅ `vreg_l15b_1p8` users=4 enabled；`vreg_l3g_1p2` users=2 enabled |
| slave 状态 | ❌ `UNATTACHED`（两个都是），`dev_num` 文件不存在 |
| 驱动绑定 | ✅ 两个 slave 都绑定 `wsa884x-codec` |
| 设备模块 | ✅ 三个都是 clean 版（157624 / 205384 / 112856 B） |
| tplg 固件 | ✅ `/lib/firmware/qcom/sm8550/OnePlus Ace 2 Pro-tplg.bin`（24296 B） |
| 音频工具 | ✅ `alsa-utils`、`alsa-ucm-conf` 已装；`libasound2t64` 已装 |
| pipewire | `pipewire`/`pipewire-pulse`/`wireplumber` 服务 inactive，但 `wireplumber`(PID 737) 仍持有 `/dev/snd/controlC0` —— 测试时用 `hw:0,0` 直连不受影响，但值得留意 |

## 4. 新备份

| 资产 | 路径 | 校验 |
| --- | --- | --- |
| misc 分区（含槽位元数据） | `out/ut-backup/misc-20261021.bin` | 4096 B，sha256 `ad7a29f0516d95798578d0bbb7515f5bd7824ba7c0acc26b7ed0be8a4d27bc41`；offset 2048 = `0f 07 01 00 00 00 00 00` |

## 5. 继续修音频的起点

盘点暴露了一个**推理顺序错误**：我前面把 `qcom,port-mapping` 当成重点，但 **port-mapping 只在 `hw_params` 阶段生效，而 slave 连 ATTACH 都没完成** —— 端口映射根本不参与当前故障。

当前唯一有效的追问是：

> **枚举阶段能读到 Device ID（`0x02170204`），但 `MCP_SLV_STATUS` 读为 0，导致 `dev_num` 从未分配、slave 停在 UNATTACHED。为什么？**

对应代码路径（`drivers/soundwire/qcom.c`）：

```
qcom_swrm_enumerate()
  └─ reg_read(SWRM_ENUMERATOR_SLAVE_DEV_ID_1/2)   ← 这一步成功，拿到了 ID
  └─ sdw_extract_slave_id()
  └─ qcom_swrm_set_slave_dev_num(bus, slave, i)
       └─ reg_read(SWRM_MCP_SLV_STATUS, &status)
       └─ status >>= (devnum * 2); status &= MASK
       └─ if (status == SDW_SLAVE_ATTACHED) { slave->dev_num = devnum; ... }   ← 这里失败
```

下一步应聚焦 `SWRM_MCP_SLV_STATUS`（`0x1090`）的**位语义**与 `SDW_SLAVE_ATTACHED` 的取值，确认是 slave 真的没报告 attach，还是驱动读错了位/地址。
