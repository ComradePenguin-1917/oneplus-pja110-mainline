# 交付级系统镜像：构建、安装与验收（2026-10-24）

把当前验证通过的系统打成可交付的镜像包。整条流水线三个脚本，
产物 8.4 GB（其中 rootfs 实占 2.3 GB）。

---

## 一、交付包内容

`image/install/bundle/`：

| 文件 | 大小 | sha256 | 来源 |
| --- | --- | --- | --- |
| `boot_a.img` | 192 MiB | `42fc8cd2…` | 从 `sde13` 分区 dump（当前运行内核）|
| `vendor_boot_a.img` | 192 MiB | `a60656b8…` | 从 `sde24` dump（正常 initramfs + 基准 DTB）|
| `dtbo_a.img` | 24 MiB | `46ddab6d…` | 从 `sde17` dump（model/compatible 已修正）|
| `rootfs.img` | 8 GiB（稀疏，实占 2.3 GiB）| `549cd5c4…` | 构建脚本产出 |
| `SHA256SUMS` | — | — | 上述四项校验和 |
| `MANIFEST.txt` | — | — | 版本、账号、刷写目标、特性清单 |

**为什么引导分量是"从分区 dump"而不是复用工作区文件**：
工作区里同一用途有十几个候选镜像（`mini-*` / `revert-*` / `-PJA110` / `-rescue` …），
极易拿错。直接从正常工作的分区 dump，能保证交付内容 == 当前验证通过的系统。

---

## 二、构建流水线

```
image/build/
  build-rootfs.sh            ① 在设备上跑：产出 rootfs.img
  rename-user-offline.sh     ② 被 ① 调用：离线改名 penguin → ubuntu
  collect-boot-assets.sh     ③ 在设备上跑：dump 三个引导分区，组装 bundle
  cleanup-for-image.sh       ④ 单独使用：交互式清洗（① 已内含等价逻辑）

image/install/
  install.sh                 安装脚本（PC 上运行）
  ACCEPTANCE.md              安装后验收清单
```

### 2.1 `build-rootfs.sh` 做什么

```sh
sudo ./build-rootfs.sh --size 8G --out /srv/pja110-image
```

| 步骤 | 内容 |
| --- | --- |
| 1 | 预检：rootfs 设备、可用空间（需镜像两倍余量）、`rsync` 存在 |
| 2 | 生成 `en_US.UTF-8` locale |
| 3 | `truncate` + `mkfs.ext4 -U <live UUID>`，**沿用 live rootfs 的 UUID** |
| 4 | `rsync -aHAX --sparse --numeric-ids` 复制根文件系统 |
| 5 | 调用 `rename-user-offline.sh` 改名 |
| 6 | 交付清洗（见 2.3）|
| 7 | 卸载 + `e2fsck -f` |
| 8 | 输出 `SHA256SUMS` 与 `build-report.txt` |

**沿用 live UUID 的关键好处**：`/etc/fstab` 和引导程序的 `root=UUID=…`
都不用改，减少一处出错面。（脚本里仍会把 fstab 的 root 行重写成镜像自己的 UUID 以防万一。）

### 2.2 rsync 必须排除的内容（第一次构建就栽在这里）

第一次用 6 GiB 镜像构建，`rsync` 报 `No space left on device`。原因：

| 目录 | 实测大小 | 问题 |
| --- | --- | --- |
| `/var/crash` | 3 个 QSGRenderThread 核心转储，每个 617–625 MB | **稀疏文件**，rsync 默认会写成实心 → 多占约 1.8 GB |
| `/var/log` | 1.1 GB | journal 828 MB + `syslog` 131 MB + `kern.log` 127 MB |
| `/var/cache` | 180 MB | apt 包缓存 + `pkgcache.bin` |
| `/var/lib/apt/lists` | ~100 MB | APT 索引 |

最终排除列表：

```sh
--exclude=/var/log/*
--exclude=/var/cache/*
--exclude=/var/crash/*
--exclude=/var/lib/apt/lists/*
```

并加上 **`--sparse`** 让稀疏文件保持稀疏。

被排除的目录在 rsync 之后**必须重建**，否则系统缺 `/var/log` 会出问题：

```sh
mkdir -p var/log var/log/journal var/cache/apt/archives var/crash var/lib/apt/lists
chown root:root var/log; chmod 0755 var/log
chown root:systemd-journal var/log/journal; chmod 2755 var/log/journal
: > var/log/wtmp;  chown root:utmp var/log/wtmp;  chmod 0664 var/log/wtmp
: > var/log/btmp;  chown root:utmp var/log/btmp;  chmod 0660 var/log/btmp
```

### 2.3 交付清洗清单

| 项 | 动作 |
| --- | --- |
| machine-id | 清空（首启生成）|
| SSH 主机密钥 | 删除（首启 `ssh-keygen -A`）|
| Wi-Fi / 网络凭据 | 删除 |
| journal 与日志文件 | 清空（上一步已排除，这里再兜一层）|
| apt 缓存、`/tmp`、`/var/tmp` | 清空 |
| shell 历史、SSH 用户密钥 | 删除 |
| 构建残留（`/root/pos-src` 等）| 删除 |
| hostname | 固定 `pja110`，并同步 `/etc/hosts` 的 `127.0.1.1` |
| locale / 时区 | `en_US.UTF-8` / `Asia/Shanghai` |
| 首启 marker | 复位（刷入后走首启流程）|

---

## 三、离线改名（`rename-user-offline.sh`）

```sh
sudo ./rename-user-offline.sh /mnt/img [--dry-run]
```

在**挂载好的镜像**上操作，因此没有"用户有运行中进程导致 `usermod` 失败"的问题，
也不会出现"改了 sudoers 后自己失去权限"的自锁。

顺序（来自事故复盘，见 [ab-flip-and-rename-incident-20261024.md](ab-flip-and-rename-incident-20261024.md)）：

1. `/etc/passwd`、`/etc/shadow`（用户名 + 家目录字段）
2. `/etc/group`、`/etc/gshadow`（**主组名 + 附加组成员**，整词替换）
3. `mv /home/penguin /home/ubuntu`
4. greetd / getty autologin / helper 的 `ALLOWED_USER` / `subuid` / `subgid`
5. **sudoers：文件名和文件内容都要改**
6. `/var/lib/AccountsService/users/` 缓存迁移

脚本末尾输出 16 项校验，其中包括上次事故踩到的两个点：

```
✓ sudo 组含 ubuntu        ✓ audio 组含 ubuntu
✓ video 组含 ubuntu       ✓ plugdev 组含 ubuntu
✓ input 组含 ubuntu       ✓ render 组含 ubuntu
✓ ubuntu 有 NOPASSWD 规则  ✓ 无旧 sudoers 文件
✓ /etc 下无 penguin 残留
```

---

## 四、镜像验证结果（42 项全过）

在设备上挂载镜像只读检查：

| 分组 | 项数 | 结果 |
| --- | --- | --- |
| 账户（passwd/shadow/home）| 5 | ✅ |
| 组与提权（6 个组 + sudoers）| 10 | ✅ |
| 首启组件（脚本/unit/autostart/polkit）| 9 | ✅ |
| 登录与显示（greetd/getty/OSK 补丁/中文字体）| 5 | ✅ |
| 清洗结果（machine-id/密钥/Wi-Fi/日志/marker）| 7 | ✅ |
| 系统配置（hostname/locale/tz/fstab）| 6 | ✅ |
| **合计** | **42** | **全部通过** |

规模：**811 包，镜像内已用 2.2 GiB，镜像文件 8 GiB（实占 2.3 GiB）**。

---

## 五、安装流程

```sh
cd image/install
./install.sh                 # 会自动找 ./bundle
```

脚本做的事：

1. 检查 `fastboot devices`
2. **检查 `current-slot` 必须是 `a`**，否则中止并提示 `fastboot --set-active=a`
3. `sha256sum -c SHA256SUMS` 校验四个镜像
4. 打印刷写清单并要求确认（`--yes` 可跳过）
5. 依次 `fastboot flash boot_a / vendor_boot_a / dtbo_a / userdata`
6. 刷完复查槽位
7. `fastboot reboot`

**只操作 A 槽，不碰 B 槽。**

---

## 六、首启会自动完成的事

第一次开机（无需人工干预）：

1. 重新生成 `machine-id`
2. 重新生成 SSH 主机密钥（RSA/ECDSA/ED25519）
3. 校正时区与 `/etc/hosts`
4. **把根文件系统从 2.2 GiB 扩展到整个 userdata 分区（450 GiB）**
5. 之后弹出一次「Device name」向导

默认账号：`ubuntu` / `123456`
（设置 → 用户 可改密码；设置 → Wi-Fi 可配网络）

> 扩容用 `resize2fs /dev/sda14`（在线扩容）。首启日志在
> `/var/log/pja110-firstboot.log`，期望看到
> `rootfs: 扩展 2262 MiB -> 430000 MiB` 之类的记录。

---

## 七、已知限制

| 项 | 说明 |
| --- | --- |
| `sda6`（`/srv`，15 GiB）不刷 | 会保留上一台系统的旧内容；需要清空时手工 `mkfs` 并更新 fstab 的 UUID |
| 引导分量是"设备 dump" | 不是从源码重建，换设备/换内核时需重新 dump |
| 镜像未压缩 | 8.4 GB 传输；如需缩小可 `gzip -1` 后让安装脚本解压（未实现）|
| 未做 AVB 签名 | 设备是 `verifiedbootstate=orange`（已解锁），无需签名 |
| 传输速度 | NCM 实测约 43 MB/s，8 GiB 约 3 分钟 |

---

## 八、回滚

交付包本身就是回滚工具：重新跑一遍 `install.sh` 即可回到镜像状态。

若只是要回到**刷机前**的系统：需要事先自己做一份镜像
（把 `build-rootfs.sh` 里的改名/清洗关掉跑一次）。当前这份 bundle 是
"改名后的交付状态"，不是"刷机前的备份"。

---

## 九、产物位置

```
设备上（master）：
  /srv/pja110-image/rootfs.img + .sha256 + build-report.txt
  /srv/pja110-bundle/（四个镜像 + SHA256SUMS + MANIFEST.txt）

PC 上（可交付）：
  image/install/bundle/（同上，已校验）
  image/build/*.sh（构建脚本）
  image/install/install.sh, ACCEPTANCE.md
```
