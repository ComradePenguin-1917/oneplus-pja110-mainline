# DeepSeek 交接任务：固化可重建的 PJA110 原生系统基线

编制：2026-10-17。本文是实施任务书；项目全部硬件进度仍以 [移植总览](porting-status.md) 为准。请先阅读总览及本文，再改代码。

## 一、最优先的问题与目标

最优先解决 **运行中的系统与包源、整镜像之间尚未闭合** 的问题。当前已经可用的电池、温度与启动逻辑，仍部分依靠手机上的手工文件；重新安装现有包不能保证完整恢复这些功能。下一步开发前应把这些成果收回源码、正式打包，并形成适用于 A 槽的更新与回退流程。

目标：仅依赖项目权威源码、已列明固件与工具链，构建出包含当前已验证功能的 APK、rootfs 和 A 槽启动镜像；不靠手机中残存的临时文件才能工作。优先完成“现有根文件系统上的可回退包升级”，不要为了证明重装而先覆盖日常 userdata。

本任务不增加高刷、快充或新硬件功能，也不升级内核大版本。保留 6.14、生成版 AA536、GPIO90、Iris7 旁路、Aston 240Hz 触控、DPU 预算修复、DRM 关闭次序修复、Phoc 原子 KMS 修复和正式 Wi-Fi 成果。

## 二、本次检查确认的事实

真机只读证据：`out/maintenance-20261017/phone-state-20261017-202026.txt`。采集时：

- 原生 systemd，内核 `6.14.0-oneplus-xigua #1 SMP PREEMPT Sat Oct 17 08:23:58 UTC 2026`。
- BQ 电量 62%，Charging，电池净电流约 +161mA。并非仍是固定 0%；不能把快充当作当前唯一阻塞。
- 电池模块 `pja110-single-battery-1` 工作，但通过 `/usr/local/lib/pja110/qcom_battmgr.ko` 加载，参数 `pja110_charger_init=0`。
- `pja110-adc-test.service` 通过 insmod 加载 `/usr/local/lib/pja110/qcom-spmi-adc5-gen3.ko`。
- A 槽成功标记服务使用 `/usr/local/libexec/pja110-qbootctl` 与 `pja110-mark-a-success`。
- 还启用了 charger-capture、wifi-probe、wifi-clean-boot、wifi-aston-rfkill 等 bring-up 服务；其实际执行内容尚需逐项读出，不能仅凭名称删除。

离线检查：

- `postmarketos/integration-profile.json`：设备 1-r4、内核 6.14-r1、Phoc 0.57.0-r2；整 rootfs 静态检查通过，完整新 rootfs 原生启动仍为 false，正式包在旧根中启动验证为 true。
- 内核 APK 当前只显式增加 Wi-Fi patch，尚无正式的单电池 / ADC 回收步骤。
- 设备 APK 安装 verified-vendor.dtb 参考文件，不会自动更新 ABL 实际消费的 vendor_boot。
- `tools/package_native_pmos.py` 固定读取 20261016 的 DISTRO / BACKUP 和旧输出路径，不是通用原生更新工具。
- `tools/deploy_native_rootfs_integrated.py` 的 flash 会覆盖 userdata；不能拿来执行本任务的普通包升级。

以上是检查时状态，不是对未来运行状态的保证；执行前刷新只读清单。

## 三、工作位置与操作约束

| 内容 | 权威位置 |
| --- | --- |
| 项目文档、脚本、包源 | `H:\workspace\PJA110-Mainline`；WSL 入口 `/mnt/h/workspace/PJA110-Mainline` |
| 本地包 | `postmarketos/device/testing/`、`postmarketos/main/phoc/` |
| 构建目录 | `/home/comrade_penguin_desktop/workspace/PJA110-Mainline` |
| pmaports 本地包副本 | 由 `tools/prepare_pmos_integrated_build.py` 派生，不独立编辑 |
| 外置模块现有构建树 | WSL `charger-native-a/linux-6.14/` |

Windows 的 `linux/` 是固定上游提交的稀疏参考树；WSL 的 `linux/` 是较早 bring-up 工作树，均不能因名字相同就替换为当前模块构建树。

沿用 A 日常 / B 救援。保留 B 槽启动分区及 firmware、persist、校准等分区。保留现有账户、SSH 身份、Wi-Fi 配置。不得通过关闭 SSH 主机校验或自行设置免密 sudo 解决权限问题。

WSL 构建需要交互式 sudo；让用户在一次交互会话中授权，不反复启动注定会卡密码的后台构建。无需管理员权限的源码整理、离线构建准备和检查先完成。涉及手机特权安装 / 分区写入时，明确目标及回退步骤，再使用现有授权；不要把本任务书当作任意刷写的授权。

## 四、分阶段实施

### 阶段 1：冻结工作基线并列出差异

1. 运行 `python tools/device_status.py --host <实际地址>`，保存独立的新证据目录。最近 Wi-Fi 为 `10.4.183.195`，USB 为 `172.16.42.1`，不能假定地址不变。
2. 只读采集所有 `pja110-*` unit、drop-in、启用状态、脚本、modules-load / modprobe 规则、实际模块路径和参数；记录文件 SHA256、包归属（apk info --who-owns）及加载顺序。
3. 核对运行 DT 与 `verified-vendor.dtb` 的语义差异，特别是根 compatible、项目身份、WCN7850 电源 / RFkill、ADC、BQ、显示 GPIO 和面板参数。
4. 核对当前 A 槽启动镜像、实际根 UUID、qbootctl 槽状态，以及 B 的 boot / init_boot / vendor_boot / dtbo 哈希。复用现有分区识别和读回工具，不硬编码 sdX。
5. 输出差异表：每项注明“已正式打包 / 运行时手工安装 / 实验或诊断 / 不确定待查”。不要直接执行已归档的一次性安装脚本。

交付：机器可读 baseline manifest 和差异表。无法读取特权文件时准确列出缺项，不凭历史猜测内容。

### 阶段 2：回收已验证的内核与模块改动

单电池参考：

- `tools/build_single_battery_wsl.py`。
- `out/battery-upower-20261017/candidate/{single-battery.patch,qcom_battmgr.c,manifest.json,result.json}`。
- 原始 bring-up 源 `drivers/power/supply/`。候选不是这个基础源的逐字副本，不要直接复制基础源后声称包含修复。

ADC 参考：

- `tools/prepare_adc_gen3_backport.py`、`tools/build_adc_gen3_wsl.py`。
- `out/native-install-20261017/adc-gen3/{source.json,linux-6.14-compat.patch,upstream/}`。
- 上游参考提交 `3857c2fe5449541e24afc5efdb0f81a8a8f9a3a0`。

实施要求：

1. 将单电池修复整理为正式包源 patch：仅 PJA110 且启用 BQ28 时不注册占位 GLINK 电池，保留 USB 供电设备，保留通知空指针防护。
2. 保持 `pja110_charger_init=0` 及实验性 SET / AP gauge 路径关闭。不得在“打包”任务中顺手启用未经验证的充电控制。
3. ADC 按现有上游驱动加最小 6.14 兼容补丁接入内核构建，模块与当前目标内核一起编译。核查 qcom-vadc-common 依赖与符号版本，避免两份同名驱动竞争。
4. 安装到标准 `/usr/lib/modules/<release>/` 路径并 depmod，正常 modprobe；迁移后不再依靠 `/usr/local` 的旧 ko 抢先加载。先检查设备现有 blacklist、软依赖和自动探测，避免模块加载竞态。
5. 显式增加 pkgrel、更新 source manifest 与校验和，并同步 integration-profile；不要复用同版本号覆盖旧 APK。

交付：可构建的内核包、可审查 patch 和来源记录；构建不得依赖已编译的候选 ko。若选择独立模块子包，必须声明精确内核兼容关系，并解释优于同树构建的理由。

### 阶段 3：回收设备树与启动服务

1. 以当前 verified-vendor.dtb 与实际运行 DT 为验收基线，将尚未回收到源的 ADC / Wi-Fi 等差异整理为 DTS / DTSI 或有明确输入与 patch 的确定性生成步骤。不要直接刷早期 DTS 编译产物。
2. 首轮允许保留工作 DTB 作回退参考，但构建必须能给出其来源、变换步骤和属性对比。区分 DTB 本体与 Qualcomm vendor_boot 容器、DTBO 项目匹配；不要丢失其他条目和选择信息。
3. 将 boot-success 服务及脚本纳入设备包，遵循发行版包路径惯例，避免把包文件放进 `/usr/local`。复用既有 qbootctl，不另写 UFS 槽控制协议；追溯 qbootctl 来源和构建方式，不能只有一个无来源 ELF。
4. 保留既有 A 槽、原生 systemd、可写根、BSG 和就绪状态检查；只标 A 成功，不改 B。审查 `After=multi-user.target` 与安装目标之间的依赖顺序，避免引入循环；用 systemd-analyze verify 检查。
5. ADC / battmgr 改为标准模块加载后，移除对应临时 insmod 服务的必要性。迁移安装需先备份旧文件，成功验证后再停用旧服务。
6. 根据阶段 1 的真实内容，停用已经失去作用的 Wi-Fi probe / clean-boot、充电诊断服务；仍有必要的逻辑正式打包并说明原因。诊断日志采集默认不再常驻启动链。

交付：设备包更新，服务启用机制及升级迁移 / 回退逻辑；无需手工登录修复即可到达桌面和网络。

### 阶段 4：建立离线原生镜像生成入口

复用 `package_native_pmos.py` 的 Android v4 容器处理、bootimg / FDT 库及已有验证逻辑，抽出参数化入口，不重写一套格式解析器。

输入至少显式包含：kernel、initramfs、已验证 vendor 容器 / DTB、原槽镜像模板、目标 A、根 UUID、输出目录及来源 manifest。生成与刷写分离；生成命令不得接触手机。

区分两种模式：

- **现有根升级**：保留当前实际 root UUID，更新 APK 与必要 A 槽启动镜像；不能拿新镜像 UUID 替换。
- **全新 rootfs 安装**：使用生成镜像中的 UUID，单独记录会覆盖 userdata；本轮只生成和离线验证，不默默重装。

保留容器大小、偏移、分区容量和 AVB 尾部边界检查。解锁启动不等于重新签名；不得声称修改镜像具备原厂有效签名。不改 B，不用旧的固定日期输入冒充本轮构建结果。

交付：一条生成命令、一份输入输出 manifest、镜像解包验证结果。更新文档说明“APK 升级”和“实际 boot_a 更新”各自负责什么；本轮不必强行实现自动刷写的 apk hook。

### 阶段 5：离线构建与最小验证

常规入口：

```sh
bash /mnt/h/workspace/PJA110-Mainline/tools/run_pmbootstrap_isolated.sh integrated
```

优先复用现有缓存，不无故清空所有 buildroot 或重下载。先检查源码与 checksum，再做耗时构建。发生失败先读 log.txt 中真实错误，不让用户重复运行同一条失败命令。

验证新 APK / rootfs 中：

- 新模块、来源、依赖和配置齐全；包拥有必要文件，modules.dep 可解析。
- 无依赖 `/home/penguin/*test*`、临时 out 路径或 `/usr/local` 才能启动的必要功能。
- boot-success 服务与 qbootctl 均来自可追溯包源，服务启用符合 systemd-edge 做法。
- 显示、触控、Wi-Fi、Phoc 原子 KMS 配置保留。
- rootfs /boot 与独立启动镜像中 kernel / initramfs 的来源一致；UUID 与所选模式对应。

QEMU 只验证用户态、initramfs 或通用启动步骤，不将它当作手机 ADC、充电、DSI 或 UFS 槽管理验证。检查强度以这些实际风险为准，不新增无关的全目录严格门禁。

### 阶段 6：真机可回退升级与验收

先交付可审查的安装计划、备份位置、恢复命令。第一轮在现有 A 根中安装新 APK；只更新确有必要的 A 槽启动分区。无需覆盖 userdata。

迁移时明确旧 /usr/local 模块、blacklist、服务的处理顺序；不要热卸载正在工作的电源或 Wi-Fi 驱动来验证。采用正常重启，升级前备份实际受影响的文件与 A 分区，核对 B 仍可用。

验收标准：

1. 三次普通重启均进入 A，A 正确标记 successful；B 四个启动分区哈希不变。
2. Wi-Fi 自动连接、无线 SSH 可用；USB Developer mode 下 NCM SSH 仍可用。不要为自动通过网络检查改坏现有 NetworkManager 配置。
3. 登录桌面，动态显示经过原故障区域正常；触控位置、双指正常；Phoc 原子模式工作。
4. sysfs / UPower / 设置仅一个真实 BQ Battery，GLINK USB 电源保留；重新开机后不会出现占位 50% Main。
5. ADC 温度可读，模块来自正式包路径；启动无新增的重复注册、加载冲突或相关失败服务。
6. 记录供电状态、电池净电流和 SOC 趋势，不以一次瞬时负电流判定失败，也不以在线标志宣称快充完成。
7. 停用临时服务、移开旧文件后仍通过上述测试，证明没有隐形依赖；可从备份恢复到原工作基线。

## 五、最终交付与完成条件

- 可审查的源码 / 包修改与 LF 一致的校验和；清晰列出 Windows 权威源修改，不独立维护 WSL 副本。
- baseline manifest、手工文件迁移表、生成产物 manifest、真机测试记录和回退说明。
- 一条包 / rootfs 构建命令，一条离线 A 槽镜像生成命令，分开的安装步骤。
- 更新总览与 integration-profile 的真实验证状态：只验证“旧根上的新包”时，不得把“完整新 rootfs 已启动”改成 true。

第一阶段成功标志是消除当前工作系统的未打包必需依赖、可从同一份源重建并通过现有根升级验证。完整新 rootfs 重装验证属于后续独立步骤，不用牺牲日常系统来凑本轮验收。

## 六、给 DeepSeek 的直接指令

请按本文阶段顺序实施，先做阶段 1 的只读核对及差异表，再把已验证的单电池、ADC、A 槽启动标记和必要设备树修改收回正式包。优先复用现有驱动、脚本库和 pmbootstrap；不新增硬件功能，不大版本升级内核，不改 B 槽，不覆盖 userdata。遇到缺失管理员权限时明确所需的最小操作，其余独立工作继续推进。以生成可审查产物和真实测试证据为准，不以重复运行或修改状态 JSON 代替完成。
