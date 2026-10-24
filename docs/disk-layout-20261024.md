# PJA110 磁盘分区布局与磁盘相关修正（2026-10-24）

本文记录当前机器的实际分区布局，以及这一轮针对磁盘的三处修正：
Disk Capacity 不显示、重复文件系统 UUID、chassis 被误判为 VM。

---

## 一、物理盘与 UFS LUN

```
SAMSUNG KLUFG8RHHD-B0G1    507 137 490 944 字节 = 507.1 GB
```

UFS 设备通过多个 **LUN（Logical Unit）** 暴露存储。这台机器分了 6 个，
所以 Linux 里看到 6 个独立的块设备：

| LUN | 设备 | 容量 | 用途 |
| --- | --- | --- | --- |
| 0 | `/dev/sda` | 472.3 GiB | **主数据区**（GPT，14 个分区）|
| 1 | `/dev/sdb` | 8 MiB | `xbl_a` —— A 槽引导程序 |
| 2 | `/dev/sdc` | 8 MiB | `xbl_b` —— B 槽引导程序 |
| 3 | `/dev/sdd` | 32 MiB | `cdt` / `ddr` / `engineering_cdt` —— 板级校准数据 |
| 4 | `/dev/sde` | 3.8 GiB | **A/B 固件区**（84 个分区）|
| 5 | `/dev/sdf` | 572 MiB | OPPO 保留区 |

---

## 二、LUN 0（`/dev/sda`）—— 主分区表

GPT，扇区 4096B。

| 分区 | 大小 | 文件系统 | PARTLABEL | 说明 |
| --- | --- | --- | --- | --- |
| sda1 | 8K | — | `ssd` | 保留 |
| sda2 | 32M | ext4 | `persist` | 传感器 / Wi-Fi MAC 校准数据 |
| sda3 | 1M | — | `misc` | **A/B 槽状态存在这里**（bootloader control block）|
| sda4 | 512K | — | `keystore` | 密钥 |
| sda5 | 512K | — | `frp` | 恢复出厂保护 |
| sda6 | 15G | ext4 | `super` | 原 Android 动态分区容器；**现为 `pja110-spare`，挂 `/srv`** |
| sda7 | 64K | — | `vbmeta_system_a` | AVB 校验元数据 |
| sda8 | 64K | — | `vbmeta_system_b` | 同上（B 槽）|
| sda9 | 64K | — | `vbmeta_vendor_a` | |
| sda10 | 64K | — | `vbmeta_vendor_b` | |
| sda11 | 64M | f2fs | `metadata` | |
| sda12 | 256M | — | `rawdump` | 崩溃转储 |
| sda13 | 32.6M | — | `splash_odm` | 开机 logo |
| **sda14** | **456.9G** | **ext4** | `userdata` | **← 根文件系统 `/`** |

根分区参数：

```
LABEL=ut-root
UUID=8c04e46c-5d09-42c5-bccf-5e20d49a17ff
```

---

## 三、LUN 4（`/dev/sde`）—— A/B 固件区

84 个分区，A 槽与 B 槽成对出现。**我们只动过 A 槽的三个**：

| 分区 | 大小 | PARTLABEL | 我们做了什么 |
| --- | --- | --- | --- |
| sde6 | 300M | `modem_a` | 未动 |
| sde10 | 1M | `abl_a` | 未动 |
| sde11 | 64M | `dsp_a` | 未动（音频固件在此）|
| **sde13** | 192M | `boot_a` | **刷入内核** |
| sde16 | 64K | `vbmeta_a` | 未动 |
| **sde17** | 24M | `dtbo_a` | **刷入修正后的设备树**（见 `dtbo-model-fix-20261024.md`）|
| sde21 | 537M | `vm-bootsys_a` | 未动 |
| **sde24** | 192M | `vendor_boot_a` | 刷入 initramfs |
| sde28 | 100M | `recovery_a` | 未动 |
| sde32 | 8M | `init_boot_a` | 未动 |
| sde38–sde63 | — | `*_b` | **完全未动**（B 槽全部组件）|

---

## 四、启动链

```
ABL (sdb/sdc 里的 xbl)
  → boot_a (sde13)            内核
    → vendor_boot_a (sde24)   initramfs + 基准 DTB
      → dtbo_a (sde17)        DTBO overlay（覆盖 model / compatible）
        → initramfs 挂载 /dev/sda14
          → switch_root → systemd
```

两点关键：

1. **`dtbo_a` 的 overlay 会覆盖 `vendor_boot` 里基准 DTB 的 `model` 和 `compatible`。**
   只改 `vendor_boot` 的 DTB 不生效，必须改 `dtbo_a`。
2. **当前 initramfs 硬编码 `/dev/sda14`**（`ut-initramfs-init.sh` 里 `ROOT_DEV=/dev/sda14`），
   不依赖 `root=UUID=` 解析 —— 这是之前重复 UUID 没导致启动失败的原因。

---

## 五、修正 1：Disk Capacity 不显示

### 现象

设置 → 关于 → Disk Capacity 显示 Unknown 或空白。

### 根因

`gnome-control-center` 的 `get_primary_disk_info()`
（`panels/system/about/cc-system-details-window.c`）完全依赖 udisks2：

```c
client = udisks_client_new_sync (NULL, &error);
if (client == NULL) {
  g_warning ("Unable to get UDisks client: %s. Disk information will not be available.",
             error->message);
  return NULL;              /* → 界面显示 Unknown */
}
```

而 `udisks2` 包在本轮激进清理中被当作"无依赖包"删除了
（`libudisks2-0` 是 g-c-c 的依赖所以还在，但守护进程包不在了）。

### 修复

```sh
sudo apt-get install -y udisks2
```

### 验证

```
$ udisksctl status
MODEL                     REVISION  SERIAL          DEVICE
SAMSUNG KLUFG8RHHD-B0G1   1501      751bcb10c54c    sda sdb sdc sdd sde sdf

Drive 对象：/org/freedesktop/UDisks2/drives/SAMSUNG_KLUFG8RHHD_B0G1_751bcb10c54c
  Size      = 507137490944       （507.1 GB）
  Removable = false
  Ejectable = false
```

udisks 把 6 个 LUN 归到**同一个 Drive 对象**，
`get_primary_disk_info()` 会把它计入总量，界面显示约 **507.1 GB**。

> 注：`get_primary_disk_info()` 累加所有非可移动、非可弹出 Drive 的容量。
> 这里只有一个 Drive，所以结果是物理总容量，不是可用空间。

---

## 六、修正 2：重复文件系统 UUID（重要）

### 现象

`sda6`（旧 `super` 分区）与 `sda14`（根分区）**UUID 完全相同**，
且 `/dev/disk/by-uuid/` 链接指向了错误的那一个：

```
修改前: /dev/disk/by-uuid/8c04e46c-…  ->  ../../sda6     ← 指向旧系统
```

### 为什么危险

- 内核命令行：`root=UUID=8c04e46c-…`
- `/etc/fstab`：`UUID=8c04e46c-… / ext4 …`

两处都按 UUID 定位根分区。当前能启动**只因为**自定义 initramfs 硬编码了
`/dev/sda14`，但 `systemd-remount-fs` 走的是 fstab 的 UUID，
解析到哪个设备取决于 udev 顺序 —— 属于随时可能出问题的状态。

### 根因

`sda6` 里残留了一份旧系统（2.0G/5.9G 已用），是从 `sda14` 克隆来的，
连 UUID 和 LABEL 一起复制了。

### 修复

```sh
sudo tune2fs -U random /dev/sda6
sudo e2label /dev/sda6 stale-super
```

### 验证

```
/dev/sda6 : UUID=e7e79191-…  LABEL=stale-super
/dev/sda14: UUID=8c04e46c-…  LABEL=ut-root

by-uuid 8c04e46c -> ../../sda14                              ✅
blkid | grep -c 8c04e46c  =  1                               ✅
findmnt --verify: UUID=8c04e46c… translated to /dev/sda14    ✅
```

---

## 七、修正 3：回收 sda6 的 15G

### 约束（必须先说清）

`sda6` 在分区表里位于 `sda5` 与 `sda7` 之间：

```
 5   35.2MB   →  35.7MB    （frp）
 6   35.7MB   →  16142MB   （super）
 7   16142MB  →  16142MB   （vbmeta_system_a）
13   16478MB  →  16512MB   （splash_odm）
14   16512MB  →  507137MB  （userdata）
```

**不与根分区 `sda14` 相邻**，所以这 15G **无法并入 `/`**
（要合并就必须移动 sda7–sda14，风险极高，不做）。

实际可行的"回收"是：清掉旧系统残留，把 `sda6` 变成一个可用独立卷。

### 操作

```sh
sudo wipefs -a /dev/sda6
sudo mkfs.ext4 -L pja110-spare -m 0 -q /dev/sda6
```

`/etc/fstab` 增加：

```
UUID=3e02b238-f168-44f1-9102-7a5d3456bfdb  /srv  ext4  defaults,noatime,nofail  0  2
```

`nofail` 保证挂载失败也不影响启动。

### 结果

```
$ findmnt /srv
/srv  /dev/sda6  ext4  rw,noatime,stripe=128

$ df -h / /srv
/dev/sda14   450G  5.0G  422G   2%  /
/dev/sda6     15G   24K   15G   1%  /srv
```

> mkfs 提示 `alignment is offset by 491520 bytes`：该分区起始未按 1MB 对齐
> （GPT 是 512K 对齐 + 4K 扇区）。对 15G 的辅助卷影响可忽略，未处理。

---

## 八、修正 4：chassis 被误判为 VM

### 现象

```
$ hostnamectl
Icon name: computer-vm
    Chassis: vm 🖴
Virtualization: vm-other
```

### 根因

高通 SM8550 的设备树里有 Gunyah 虚拟机监控器节点，systemd 一看到
`/hypervisor` 就判定为虚拟机：

```
$ cat /proc/device-tree/hypervisor/compatible
qcom,gunyah-hypervisor-1.0 qcom,gunyah-hypervisor simple-bus
```

### 修复

```sh
sudo hostnamectl set-chassis handset
```

`phone` 不是合法值（systemd 255 的合法 chassis：
`vm container desktop laptop convertible server tablet handset watch embedded`）。

### 结果

```
Icon name: computer-handset
    Chassis: handset 🕻
Virtualization: vm-other        ← 保留，这个描述是准确的
```

> `Virtualization: vm-other` 不改：Linux 确实跑在 Gunyah 之上，
> systemd 的判断本身没错，错的只是把 chassis 也连带设成 vm。

---

## 九、现状汇总

```
物理盘:   SAMSUNG KLUFG8RHHD-B0G1  507.1 GB
根分区:   /dev/sda14  ext4  LABEL=ut-root  450G（已用 5.0G，2%）
辅助卷:   /dev/sda6   ext4  LABEL=pja110-spare  15G → /srv
固件区:   /dev/sde    3.8G（A/B 共 84 分区）
保留区:   /dev/sdf    572M（OPPO）
udisks2:  已安装并 enabled，Drive Size = 507.1 GB
chassis:  handset
```

## 十、回滚

| 项目 | 回滚方式 |
| --- | --- |
| sda6 重格式化 | 内容为旧系统残留，无需回滚；如需还原 UUID：`tune2fs -U 8c04e46c-5d09-42c5-bccf-5e20d49a17ff /dev/sda6`（**不要这么做**，会重新造成 UUID 冲突）|
| /srv 挂载 | 删除 `/etc/fstab` 中对应行即可 |
| udisks2 | `apt-get remove udisks2`（会重新失去 Disk Capacity）|
| chassis | 删除 `/etc/machine-info` |
