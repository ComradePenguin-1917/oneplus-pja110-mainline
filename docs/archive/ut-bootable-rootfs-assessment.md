# 把 Ubuntu rootfs 做成可启动镜像：评估（2026-10-18）

结论先行：**可行，且不需要动现有 A/B 槽布局，但需要解决 5 个具体问题；其中 2 个是硬性的。**

## 1. 现有硬件/分区事实

| 项 | 值 | 影响 |
| --- | --- | --- |
| `boot_a` | 192 MiB | 放内核 + DTB（当前 Android v4 格式），够用 |
| `vendor_boot_a` | 192 MiB | 放 vendor ramdisk/DTB，UT 不需要改 |
| `userdata` | ~467 GiB (`/dev/loop0p2`) | 当前 pmOS 根；UT 需要一个独立根分区 |
| `super` | 15 GiB | Android 逻辑分区，未被使用 |
| 根文件系统载体 | `loop` 上的 ext4 | 这是当前性能与 I/O 的既有限制 |
| 内核 | 6.14.0-oneplus-xigua | 可复用，但 UT 的内核模块要进 rootfs |

## 2. 必须解决的 5 个问题

### 2.1 rootfs 里没有内核模块（硬性）

```
/opt/geekbench-rootfs/usr/lib/modules/   → 不存在
/opt/geekbench-rootfs/boot/              → 空
```

当前 Ubuntu rootfs 是 chroot 用的，**不含 `linux-modules`**。裸机启动必须：

- 安装与 `6.14.0-oneplus-xigua` 匹配的模块，或
- 把内核模块打包进 initramfs，或
- 用当前 pmOS 的 `/lib/modules/6.14.0-oneplus-xigua` 复制进去（版本必须完全一致）。

**这一条不解决，启动后没有 drm/panel/touch/网络驱动，等于黑屏。**

### 2.2 fstab 未配置（硬性）

```
# UNCONFIGURED FSTAB FOR BASE SYSTEM
```

必须写入根分区 UUID、可选 `/boot`，否则 systemd 无法正确挂载根。

### 2.3 需要一个根分区

`userdata` 已被 pmOS 占用（loop 镜像在其上）。三种选择：

| 方案 | 做法 | 代价 |
| --- | --- | --- |
| A | 在 `userdata` 里再放一个 loop 镜像，UT 根在其上 | 与现状一致，但仍是 loop I/O |
| B | 缩小 `userdata`，新建独立分区 | 需要 repartition，风险高，会动现有系统 |
| C | 用 `super` 的 15 GiB 做 UT 根 | `super` 是 Android 动态分区，Linux 侧可直接 `dd`，但会破坏 Android 逻辑分区表 |

**推荐 A**：不 repartition，失败可回退，符合当前“事务化、可回退”的原则。

### 2.4 内核命令行与 initramfs

- 当前 `boot_a` 的内核 cmdline 是 `root=UUID=... rootwait rw`，指向 pmOS 根；
- UT 需要指向自己的根分区，并且 initramfs 要能识别 loop/分区；
- 可以复用现有 `boot_a` 生成器（`tools/build_native_slot_image.py`），只改 `--root-uuid`。

### 2.5 systemd 与 display manager

- 容器验证已证明 systemd 会话可用（`is-system-running=running`）；
- 裸机启动后需要 `lomiri-session.service` 随 `graphical.target` 启动；
- 需要 `greetd` 或直接 `getty` 自动登录到 `lomiri-session`。

## 3. 工作量与风险

| 步骤 | 工作量 | 风险 |
| --- | --- | --- |
| 复制内核模块进 rootfs | 小 | 版本不匹配则黑屏 |
| 写 fstab、machine-id、hostname | 小 | 低 |
| 在 userdata 里建 UT loop 镜像 | 中 | 磁盘占用 ~4 GiB |
| 生成 UT 专用 `boot_a`（改 root UUID） | 小 | 已有工具链 |
| 首次启动调试（systemd、Lomiri、DRM） | 大 | 可能多次黑屏重启 |
| 回退方案 | 已具备 | 现有 `restore --tx` 可用 |

## 4. 建议的实施顺序

1. **准备 rootfs**：装内核模块、写 fstab、装 `lomiri-session.service`；
2. **建 UT 根镜像**：在 `userdata` 上创建 ext4 loop 文件（例如 6 GiB），写入 rootfs；
3. **生成 `boot_a`**：用现有生成器，`root=UUID=<UT 根>`，保留 120 Hz cmdline；
4. **首次启动**：从 UT 根启动，观察是否进 systemd → `lomiri-session`；
5. **失败回退**：用现成事务恢复原 `boot_a` 与 pmOS 根。

## 5. 与 Ubuntu Touch 正式移植的差距

即使裸机启动成功，仍缺：

- `deviceinfo` 挂载（已写好 `xigua.yaml`，需装进 `/etc/deviceinfo/devices/`）；
- repowerd / hfd-service / usb-moded；
- 音频 UCM、相机、通话、GNSS；
- AppArmor、click 包体系；
- OTA 更新机制。

**所以“能启动”不等于“可用作日常机”**，但它是必须跨过的一道门。

## 6. 结论

- 技术上可行，**不必须重新分区**；
- 第一步先把“内核模块 + fstab + UT 根镜像 + 专用 boot_a”做出来；
- 最大风险是首次启动的驱动/会话调试，而不是架构问题；
- 现有事务回退机制可以保证失败可恢复。
