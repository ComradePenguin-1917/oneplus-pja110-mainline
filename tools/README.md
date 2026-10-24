# tools/ 说明

这里放移植过程中写的脚本。**不是所有脚本都还需要维护** —— 大量文件是一次性调试用的，
保留下来是为了「当时到底怎么验证的」可追溯。

---

## 当前仍在用的入口（文档里有引用）

| 脚本 | 用途 |
| --- | --- |
| `setup-PJA110.sh` | 设备侧一次性初始化（时区、hostname、`/etc/hosts`、常用包）|
| `enable-fastcharge.sh` | 快充：等 `last_set` 出现后写 `BATT_CHG_CTRL_LIM`，带 `rc` 校验与日志 |
| `capture_acceptance.py` | 采集验收数据（硬件状态、服务状态、电量、显示模式）|
| `capture_native_baseline.py` | 采集基线清单（包、模块、服务、分区）|
| `device_status.py` | 一眼看设备状态 |
| `build_mini_initramfs.py` | 构建最小 initramfs + vendor_boot（挂 rootfs、switch_root）|
| `build_native_slot_image.py` | 构建 A 槽镜像（AVB 偏移、对齐处理）|
| `build_rescue_revert.py` | 救援镜像：撤销一次性改动（用户名等）后正常启动 |
| `build_adc_gen3_wsl.py` | ADC5 Gen3 补丁后的内核模块构建 |
| `build_single_battery_wsl.py` | 单电池 battmgr 模块构建 |
| `prepare_adc_gen3_backport.py` | ADC5 Gen3 backport 准备 |
| `prepare_generated_panel.py` | 面板驱动代码生成准备 |
| `run_panel_generator.py` | 跑面板初始化序列生成器 |
| `adapt_generated_panel.py` | 把生成结果适配成驱动 |
| `compare_dtb_provenance.py` | 比对 DTB 来源（判断 model/compatible 被谁覆盖）|
| `deploy_native_rootfs_integrated.py` | 部署集成好的 rootfs |
| `plan_native_install.py` | 生成安装计划（分区、槽位检查）|
| `package_native_pmos.py` | 打 pmOS 包（早期路线，已弃用）|
| `prepare_pmos_integrated_build.py` | pmOS 集成构建准备（早期路线，已弃用）|
| `run_pmbootstrap_isolated.sh` | 隔离环境跑 pmbootstrap（早期路线，已弃用）|

另有 4 个 Windows 侧辅助脚本（`.ps1`），用于配置 USB NCM 网卡、静态 IP 等 —— 
**MTP 改造后 NCM 已移除，这些基本不用了**，留作参考。

---

## 其余文件

`tools/` 里还有约 150 个 `*.py` / `*.sh`，是各阶段的调试脚本，例如：

- `deploy_*.py` / `package_*.py` —— 把某个补丁部署到设备并取回证据
- `stage_*.py` / `test_*.py` —— 单项功能的验证（充电、Wi-Fi、USB、显示）
- `audit*.sh` —— 设备侧信息采集

它们**不保证还能直接运行**（路径、设备节点都变了），价值在于记录
「当时用什么方法验证了什么」。要复现请以 `docs/` 里的命令为准。

---

## 命名约定

- `format-patch` 系列产物不在 `tools/`，在内核树里
- `_` 开头的临时脚本不会进仓库（见 `.gitignore`）
- 设备侧脚本假定以 root 运行，主机侧脚本假定在 WSL/Ubuntu 里跑
