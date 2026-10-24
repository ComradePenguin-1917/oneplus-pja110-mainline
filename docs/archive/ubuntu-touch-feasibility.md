# PJA110 Ubuntu Touch 可行性验证（2026-10-18）

对象：OnePlus Ace 2 Pro / PJA110（xigua），当前 A 槽 Nura edge / 6.14.0-oneplus-xigua。
目的：判断这台机器能否运行 Ubuntu Touch 的图形栈，而不是判断“能不能装官方镜像”。

## 1. 结论

**Ubuntu Touch 的显示与合成栈在 PJA110 的 mainline 内核上可以运行。**

在 Ubuntu 24.04 arm64 chroot 中实测：

| 组件 | 结果 |
| --- | --- |
| DRM / DSI | `msm` 驱动，DSI-1 connected，`1240x2772@119.99` |
| Mir 显示后端 | `mir:gbm-kms` 选中并完成 modeset |
| Mir 渲染后端 | `mir:egl-generic`，EGL 1.5 上下文创建与 buffer swap 成功 |
| GPU | `freedreno` / `FD740`，OpenGL ES 3.2（Mesa 25.2.8） |
| QtMir | 创建 MirServer，绑定 `PlatformScreen` 到 DSI-1 |
| Lomiri Shell | `Shell.qml`、`Launcher`、`Panel`、`Drawer` 加载完成 |
| 合成帧率 | vsync 稳定 `8.30 ms`，约 `120.4 Hz` |
| 触控设备 | `PJA110 Synaptics S3910 (Aston TCM)` 在 `/dev/input/event3` 可见 |

即完整链路 `Lomiri → QtMir → Mir(gbm-kms) → DRM/msm → DSI` 已打通，且跑在 120 Hz。

## 2. 验证环境

- 底板：现有 Nura edge（Alpine + postmarketOS 设备包），内核 `6.14.0-oneplus-xigua`；
- 用户态：Ubuntu 24.04 (noble) arm64 rootfs，位于 `/opt/geekbench-rootfs`；
- 软件版本：Mir `2.14.1`、QtMir `0.8.0~git20240131`、Lomiri `0.2.1`、Mesa `25.2.8`；
- 运行方式：chroot + bind mount `/dev /proc /sys`，测试期间停 `greetd` 以释放 DRM master，结束后自动恢复。

## 3. 已验证的事实

1. **不需要 Halium / Android HWC**：Mir 的 `gbm-kms` 后端直接对 mainline DRM 工作。
2. **不需要 Wayland 合成器垫底**：`miral-app` 与 `lomiri` 都能在 gbm-kms 平台上直出。
3. **120 Hz 可用**：DRM 上报 `1240x2772@119.99`，Mir vsync 实测 `120.4 Hz`。
4. **输入设备可见**：Synaptics S3910 触控、PMIC pwrkey/resin、gpio-keys 均在 `/dev/input`。
5. **GPU 渲染正常**：freedreno FD740，GLES 3.2，合成无 llvmpipe 回退。

## 4. 已知限制

| 限制 | 影响 | 性质 |
| --- | --- | --- |
| chroot 内无 systemd/logind | `lomiri-app-launch` 无法枚举应用，锁屏信号缺失 | 环境限制，非平台限制 |
| AccountsService 未运行 | 用户配置、MMS 等属性读取失败 | 环境限制 |
| 缺 `Lomiri.SystemSettings.Update`、`MeeGo.QOfono` | 首次启动向导无法完成 | 缺包 |
| `EGL_WL_bind_wayland_display` 不可用 | Mir 回退到软件缓冲分配路径 | GBM 平台的结构性回退，现代 dmabuf 路径已启用 |
| `drmModeCrtcSetGamma` 未实现 | 无 gamma 调节 | msm 驱动限制，Phosh 下同样存在 |
| 无 EDID | Mir 报 “Unable to determine current display mode” | DSI 面板正常现象，使用驱动上报模式 |
| Adreno GMU HFI 偶发超时 | 日志出现 `HFI_H2F_MSG_GX_BW_PERF_VOTE timed out` | 与既有已知问题同类，未归因 |

## 5. 与 Ubuntu Touch 正式移植的差距

已解决：图形栈、DRM、输入设备、GPU、120 Hz。

尚未完成，属于移植工作量：

1. **启动方式**：当前是 chroot；UT 需要以 Ubuntu rootfs 作为根文件系统启动，并接入现有 A/B 槽与 `boot_a`。
2. **会话管理**：`lomiri-session` 需要 systemd user session、logind、AccountsService。
3. **设备信息**：需要 `deviceinfo` 的 `xigua.yaml`（方向、GridUnit、display cutout、Mir 参数）。
4. **电源**：`repowerd` 需要适配 mainline sysfs（背光、输入事件、休眠）。
5. **外设服务**：`hfd-service`（振动/LED）、`usb-moded`（USB 模式）、音频 UCM。
6. **应用层**：AppArmor 策略、click 包、`lomiri-app-launch` 的 systemd 集成。
7. **移动网络/通话/GNSS/相机**：当前 pmOS 线也未完成，UT 同样需要独立移植。

## 6. 判断

**可行性成立，工作量真实。** 这次验证排除的是“图形栈根本跑不起来”这个最大风险；剩下的都是可分解的移植工作，不是能力边界问题。

如果目标是“手机上有 Ubuntu Touch 体验”，应当按第 5 节的顺序推进，而不是继续在 chroot 里补服务——chroot 无法提供 UT 需要的 systemd/logind 语义。

## 7. 证据文件

- `out/ut-test/lomiri-probe8-20261018-144853.log`：外层运行记录；
- `out/ut-test/lomiri-session-20261018-144853.log`：Lomiri 完整会话日志（含 vsync 与 QML 加载）；
- `out/geekbench/aa536-vendor-timings.json`：面板 60/90/120 Hz 时序；
- `docs/fast-charge-high-refresh-assessment.md`：高刷移植背景。
