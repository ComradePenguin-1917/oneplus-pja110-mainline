# DeepSeek 基线任务验收

日期：2026-10-17。结论：**正式打包与现有 A 根升级成果通过核验；可复用的镜像生成、完整回退和设备树可重建性尚未通过整体验收。** 本轮未修改真机、重启、安装或刷写；只读 SSH 已成功。

## 已确认的成果

- 真机运行 device-oneplus-xigua 1-r8、linux-oneplus-xigua 6.14-r2，电池约 71%，正在充电。
- battmgr、ADC 已位于标准模块目录；从真机文件读出的 SHA256 与新内核 APK 内对应文件完全一致。
- boot-success 脚本、迁移脚本与 unit 由 device 1-r8 拥有，qbootctl 来自发行版 0.2.2-r1；启动标记 unit 当前 active/exited、Result=success。
- 实时运行 `pja110-migrate-baseline check` 返回 PASS，无旧手工文件与临时 unit 残留。
- 独立重跑 APK 检查通过，包源本地 SHA512 全部匹配；Python 语法、新增 7 个 shell 脚本解析通过。12 项 DTB 属性检查通过。
- 原始 phase1 日志含 A 镜像读回哈希和 B 四分区未变记录；三次启动 ID 在验收记录中列明。本轮没有为重复测试再重启手机，也未重新执行特权原始分区哈希读取。
- 新 rootfs 仅静态检查、未整体刷入的状态仍明确为 false，未把旧根上的包升级冒充整镜像启动。

## 必须修正

### 1. 高优先级：文档默认命令会生成旧内核镜像并报告成功

位置：`tools/build_native_slot_image.py:55`、`:56`、`:280`，`docs/native-upgrade.md` 第 2 节。

生成器默认 kernel / initramfs 仍取 `out/postmarketos-integration-20261016/`，文档只给 mode、root UUID 和 out，因此实际走旧输入。已在电脑执行该命令复现；所得 kernel 和 initramfs 哈希均不同于实际部署的 baseline 产物，仍输出 PASS。旧目录自身的 artifacts 只能证明旧输入自洽，不能证明与当前目标包一致。

风险：未来照文档升级会把旧内核、旧 initramfs 与新模块包混用。内核 release 没变，`uname -r` 检查识别不了这种组合。

修正要求：显式要求目标构建 manifest / 输入，或从当前 profile 唯一解析本轮产物；校验目标包版本与 kernel、initramfs、rootfs 来源。同步所有示例。缺失输入时拒绝，不能静默回落到旧目录。

复现证据：`out/deepseek-review-20261017/default-input-reproduction/manifest.json`、`audit.json`。这些复现镜像仅供审查，不应刷入。

### 2. 高优先级：回退尚未形成完整、确定的事务

位置：`postmarketos/device/testing/device-oneplus-xigua/pja110-migrate-baseline.sh:215`，`tools/device/phase1-install.sh:95`、`:142`、`:154`，`docs/native-upgrade.md` 第 4 节。

- `restore` 从共同 STATE 目录按名字选最新备份。当前真机最新目录为 `20261017-213801-units/`，仅含临时 unit，真正模块与脚本在 `20261017-213413/`；默认 restore 不能恢复此前完整状态。
- phase1 未固定并备份旧内核 / 设备 APK，文档回退仍是 `/var/cache/apk/... 或保留的旧 APK`，不是确定可执行的恢复步骤。包安装覆盖同名 kernel release 的模块后，仅恢复 boot_a 不足以回到原基线。
- vendor_boot 写失败分支只恢复 vendor_boot，保留已写的新 boot 和已装的新包；普通 dd 非零退出也只进入打印日志的 EXIT trap，不能据此声称所有失败均自动完整回退。

修正要求：用明确 transaction ID 关联原始分区、旧 APK、配置 / unit 和启用状态；支持按 ID 恢复，不从无类型的最近目录猜测。失败状态必须明确哪些已变更，提供配套恢复路径。至少离线演练部分安装 / 写入失败及恢复选集，不在真机制造断电测试。

### 3. 中优先级：设备树仍是受控二进制，尚不能从源重建

位置：设备包 `source-manifest.json` 的 device_tree 段、`tools/compare_dtb_provenance.py`、总览中的设备树说明。

当前做了 DTB 属性与运行树核对，打包受控 blob 是进步，但生成仍依赖历史 vendor_boot 容器与 wifi-added.dtb。没有交付计划阶段 3 要求的 DTS/DTSI 或明确输入加 patch 的确定性生成流程。比较工具不能替代生成工具；总览也已承认“不从 DTS 重编”。

另外，比较工具对 running capture 主要计数，没有逐项执行其注释声称的完整 reviewed-contract 比较；部分属性检查由另一个 verifier 完成。不能把 838 节点存在等同所有运行属性一致。

修正要求：保留已验证 blob 作回退，以固定源 + 明确变换生成目标 DTB，语义比较覆盖本机关键连接与参数，并分别检查容器中的所有相关条目。可以分步完成，但应标为未完成。

### 4. 中优先级：验收自动 PASS 覆盖范围过窄

位置：`tools/capture_acceptance.py` 的 after 判定，以及现有验收报告第 4 节。

after 的 PASS 只要求电池、ADC、模块路径和旧文件消失，没有纳入已采集的模块 loaded、Wi-Fi connected、Phoc running，也不验证三次启动或 B 哈希。网络掉线、桌面未起时仍可能 PASS。报告已如实注明动态画面和双指尚待目视复验，应继续保留 pending，不能视为全项通过。

修正要求：输出逐项 passed / failed / pending 与证据来源；自动总结果不能掩盖已知失败。需要权限或目视的项目保持 pending，引用已有特权日志与用户确认后再关闭。

## 次要缺陷

- `--dtb` 声称支持同尺寸替换，但替换后又断言 ramdisk 之后所有字节等于原 vendor 模板（包含 DTB），非原样替换必然失败。应分别验证允许变化与必须保持的区间。
- 生成 manifest 的 `kernel_release` 实际为带引号的 CONFIG_LOCALVERSION（`"-oneplus-xigua"`），不是完整 release，容易误导下游。
- 新升级文档仍混用设备 1-r7 与 1-r8、多个备份时间及路径，不能当通用可复制操作手册。
- 报告中的“一次 GMU 性能投票超时”尚未复现，本轮当前启动未看到相同错误；保持已知问题，不推断原因也不扩大为 GPU 已坏。

## 本轮证据与边界

独立证据目录：`out/deepseek-review-20261017/`，包括 APK 检查、DTB 合同检查、实时包文件哈希和归属、默认输入复现及语法检查。实时完整状态另在 `out/maintenance-20261017/phone-state-20261017-214706.txt`。

未重新做耗时全量构建、userdata 重装、真机回退演练或用户目视验证。当前系统可继续使用；先修正上述升级与回退缺口，再将整个任务标记完成。
