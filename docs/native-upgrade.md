# 原生升级与回退：包升级、A 槽启动镜像、真机验收

更新：2026-10-17。本文说明 **APK 升级** 与 **实际 `boot_a` / `vendor_boot_a` 更新** 各自负责什么，
并给出可回退的安装顺序。总览见 [移植总览](porting-status.md)，基线任务书见
[可重建原生基线实施方案](deepseek-baseline-plan.md)。

## 1. 两条互不替代的更新路径

| 路径 | 改变什么 | **不**改变什么 |
| --- | --- | --- |
| `apk upgrade` / 安装新 APK | 根文件系统内的 `/usr/lib/modules/...`、unit、脚本、固件 | ABL 实际读取的 `boot_a`、`vendor_boot_a`、`dtbo_a`：它们不会自动更新 |
| 离线生成 + 写 A 槽镜像 | `boot_a`（内核 + cmdline）、必要时 `vendor_boot_a`（initramfs/DTB） | 根文件系统内容、账户、Wi-Fi 配置、userdata |

设备包仍保持 `flash_method=none`、`generate_bootimg=false`、`flash_kernel_on_update=false`：
这是刻意的，避免一次 `apk upgrade` 在无人值守时改写启动分区。两者必须分别执行、分别核对。

## 2. 先决条件与证据

- 保持 A 日常 / B 救援；不改 B 槽，不覆盖 userdata。
- 记录升级前状态：

```sh
python tools/device_status.py --host <实际地址>            # 只读
python tools/capture_native_baseline.py --host <实际地址>   # 只读清单
python tools/capture_acceptance.py --phase before --host <实际地址>
```

- 生成 A 槽镜像。**内核与 initramfs 没有默认值**，必须来自已验证的目标构建目录；
  生成器会把目标包版本与 `postmarketos/integration-profile.json` 对比，版本不符直接拒绝：

```sh
python tools/build_native_slot_image.py --mode existing-root \
  --target out/postmarketos-baseline-20261017 \
  --root-uuid <当前根 UUID> \
  --out out/native-slot-20261017/existing-root
```

`--mode fresh-rootfs` 只用于**全新根文件系统安装**：它采用生成镜像中的 UUID，写盘会覆盖 userdata；
本轮只生成和离线验证，不默认执行。显式给 `--kernel/--initramfs` 时还必须同时给
`--artifacts` 与 `--image-verification`，否则拒绝运行（不会回落到旧目录）。

## 3. 安装步骤（需要一次交互式 sudo 会话）

先让工具生成哈希固定的安装计划（只读）：

```sh
python tools/plan_native_install.py --host <实际地址>
# 产出 out/baseline-20261017/install-plan.json
```

以下命令在手机上的 root shell 中执行。若当前没有 root，先用用户自己的方式获得一次交互式
`sudo -i`；本项目不设置免密 sudo，也不关闭 SSH 主机校验。

### 3.0 分阶段脚本（推荐，已审查）

脚本随离线产物放在手机 `/home/penguin/pja110-install/`，源码在本仓库 `tools/device/`；
每个脚本都自带事务备份、写后回读、B 槽哈希复核和失败即停：

```sh
sudo -i
sh /home/penguin/pja110-install/phase1-install.sh   # 事务备份、装 APK、写 boot_a + vendor_boot_a
reboot                                              # 正常重启，等桌面出现

sudo -i
sh /home/penguin/pja110-install/phase2-after-first-boot.sh
sh /home/penguin/pja110-install/phase2b-cleanup-legacy-units.sh
reboot

sudo -i
sh /home/penguin/pja110-install/phase4-finalize.sh   # 安装当前设备包、清理 apk 残留
sh /home/penguin/pja110-install/phase5-adopt-legacy-backups.sh  # 把旧式备份登记为事务
reboot                                               # 第三次普通重启

sudo -i
sh /home/penguin/pja110-install/phase3-final-check.sh        # 只读验收事实
```

任一阶段失败都会打印事务 id 与 `full log:` 路径；phase 1 在回读不一致时会用同一事务
自动回滚。脚本不触碰 userdata，也不写 B 槽。

### 3.1 手工等价步骤（供审查）

脚本内部做的就是下面这些步骤；手工执行时必须保持同样的结构，否则回退无法按事务恢复。

```sh
tx=/var/lib/pja110-baseline/transactions/install-$(date +%Y%m%d-%H%M%S)
mkdir -p "$tx/partitions" "$tx/files"
printf 'id=%s\nkind=install\ncreated=%s\npartitions=boot_a,vendor_boot_a,init_boot_a\nfiles=files.tar\nunits=units\nstatus=in-progress\n' \
  "${tx##*/}" "$(date -Is)" > "$tx/meta"

for p in boot_a vendor_boot_a init_boot_a; do
  dd if=/dev/disk/by-partlabel/$p of="$tx/partitions/$p.img" bs=1M
done
sha256sum "$tx"/partitions/*.img > "$tx/SHA256SUMS"

tar -C / -cf "$tx/files.tar" boot "lib/modules/$(uname -r)" \
  usr/share/kernel/oneplus-xigua usr/libexec usr/lib/systemd/system \
  usr/lib/systemd/system-preset etc/systemd/system

apk info -v | sort > "$tx/apk_before.txt"
for p in boot_b init_boot_b vendor_boot_b dtbo_b; do
  sha256sum /dev/disk/by-partlabel/$p
done > "$tx/slot-b-before.txt"
```

安装与写入（版本号从 profile 取，不要手写死）：

```sh
ver() {
  python3 -c 'import json,sys;print(json.load(open(sys.argv[1]))["packages"][sys.argv[2]])' \
    /mnt/h/workspace/PJA110-Mainline/postmarketos/integration-profile.json "$1"
}

apk add --no-cache qbootctl
apk add --allow-untrusted --force-overwrite "/tmp/pja110-pkgs/linux-oneplus-xigua-$(ver linux-oneplus-xigua).apk"
apk add --allow-untrusted --force-overwrite "/tmp/pja110-pkgs/device-oneplus-xigua-$(ver device-oneplus-xigua).apk"

dd if=/tmp/pja110-images/boot_a.img of=/dev/disk/by-partlabel/boot_a bs=1M && sync
sha256sum /dev/disk/by-partlabel/boot_a      # 必须等于 manifest 中 boot_a.img 的 SHA256
dd if=/tmp/pja110-images/vendor_boot_a.img of=/dev/disk/by-partlabel/vendor_boot_a bs=1M && sync
sha256sum /dev/disk/by-partlabel/vendor_boot_a
sed -i 's/^status=.*/status=complete/' "$tx/meta"
```

`init_boot_a` 与 `dtbo_a` 不写；写前写后各读一次四个 B 分区哈希并比较。

### 3.2 正常重启并迁移

```sh
reboot
```

重启后确认已在 A 槽、运行新内核、桌面与网络正常，再执行：

```sh
pja110-migrate-baseline check            # 只读
pja110-migrate-baseline apply            # 新建 migration-<id> 事务
pja110-migrate-baseline restore --list    # 记录两个事务 id
reboot
pja110-migrate-baseline check             # 应输出 PASS
```

## 4. 回退（按事务 id，不猜最新目录）

每个事务都带 `meta`，记录 `kind`、`status`、包含的分区和文件形态。先看清单：

```sh
pja110-migrate-baseline restore --list
# install-adopted-20261017-213025    kind=install   status=adopted partitions=boot_a,... apks=linux-oneplus-xigua-6.14-r1.apk,...
# migration-adopted-20261017-213413  kind=migration status=adopted partitions=-
# units-adopted-20261017-213801      kind=units     status=adopted partitions=-
```

早期用旧脚本做的升级，备份目录可用
`tools/device/phase5-adopt-legacy-backups.sh` 登记成 `install-adopted-*` 事务；
它会把原分区、旧 `/usr/local`、`/var/cache/apk` 中保留的旧 APK 和旧启用状态关联到同一 id。

演练（只校验并打印，不写设备）：

```sh
pja110-migrate-baseline restore --tx install-20261017-213025 --dry-run
```

真正回退指定事务（分区逐字节回读核对，文件树/`files.tar` 一并恢复，旧 unit 重新启用）：

```sh
pja110-migrate-baseline restore --tx install-20261017-213025
reboot
```

`restore` 会先校验事务内所有文件存在，缺一个就拒绝执行，不会部分写入。

旧包本身不保存在事务里；`apk_before.txt` 记录版本，文件系统内容由 `files.tar`
恢复（旧内核、模块、unit、`/boot`）。如需退回旧 APK，使用保留的旧 APK 或
`/var/cache/apk` 中的副本，并先确认版本与 `apk_before.txt` 一致。

phase 1 在第一次改动之后只要失败（安装、dd、回读任一步），会立即用同一事务回滚已写入的
分区和文件，并打印 `ROLLBACK_OK`；失败时打印 `ROLLBACK_FAILED` 和手工命令。由于 APK
数据库不回滚，回滚后 `apk info -v` 可能仍显示新版本，但启动链与 `/lib/modules` 已回到
`files.tar` 的内容；这一点会写进日志。

B 槽的救援镜像不受这些步骤影响；仍可用既有方式回到 B。

## 5. 真机验收清单（阶段 6）

1. 三次普通重启均进入 A，A 标记 successful；B 的 `boot_b`/`init_boot_b`/`vendor_boot_b`/`dtbo_b`
   哈希与安装事务记录一致。
2. Wi-Fi 自动连接、无线 SSH 可用；USB Developer mode 下 NCM SSH 可用。
3. 登录桌面，动态显示经过原故障区域正常；触控位置与双指正常；Phoc 原子模式工作。
4. sysfs / UPower / 设置只有真实 BQ 电池；`qcom-battmgr-usb` 存在；重启后不再出现 50% 占位 Main。
5. ADC 温度可读，`modinfo -F filename qcom_spmi_adc5_gen3` 指向 `/lib/modules/...`；
   无新增重复注册、加载冲突或失败服务。
6. 记录供电状态、电池净电流与 SOC 趋势；不以一次瞬时负电流判定失败，不以在线标志宣称快充完成。
7. 停用临时服务、移走旧文件后仍通过以上测试，证明没有隐形依赖；可从事务备份恢复。

`tools/capture_acceptance.py --phase after` 会逐项输出 `passed` / `failed` / `pending`
及证据来源；需要 root 的分区哈希与目视项目保持 pending，直到引用 phase 3 日志或用户确认。
未完成的验收必须如实记录在 `postmarketos/integration-profile.json` 与
[移植总览](porting-status.md)，不能把“已构建 / 已静态检查”写成“已在真机启动”。
