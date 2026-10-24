# usrmerge 符号链接破坏事故与修复（2026-10-24）

## 事故摘要

**造成原因：** 一条模块安装命令破坏了 Ubuntu 的 usrmerge 符号链接布局，导致所有动态链接程序失效。

```bash
# 错误命令
sudo tar -xJf /tmp/pja110-mods.tar.xz -C /
```

**影响：** `/bin/bash` 不可用、PAM 认证失败（图形界面"密码不对"）、SSH 登录后 shell 无法启动。但已运行的进程（Phosh 界面）不受影响，因此症状极具迷惑性。

**恢复：** 通过定制 initramfs 自动修复符号链接，系统完全恢复，**无数据丢失**。

## 一、根因分析

### 1.1 Ubuntu 的 usrmerge 布局

Ubuntu 24.04 使用 merged `/usr`，顶层目录都是符号链接：

```
/bin   -> usr/bin
/sbin  -> usr/sbin
/lib   -> usr/lib
/lib64 -> usr/lib64
```

真正的文件都在 `/usr/` 下，例如：

```
/usr/bin/bash
/usr/lib/aarch64-linux-gnu/libc.so.6
/usr/lib/aarch64-linux-gnu/libpam.so.0
/usr/lib/ld-linux-aarch64.so.1
```

### 1.2 GNU tar 的默认行为

**当压缩包内含目录条目 `lib/`，而目标 `/lib` 是指向目录的符号链接时，GNU tar 默认会删除符号链接并创建真目录**——除非显式指定 `--keep-directory-symlink`。

本地复现验证：

```sh
# 准备
mkdir -p /tmp/tartest/usr/lib/foo /tmp/tartest/pkg/lib/modules/test
cd /tmp/tartest && ln -s usr/lib lib

# 打包（与出事的包结构相同）
tar -czf /tmp/t.tar.gz -C pkg lib

# 解压 —— 默认行为
tar -xzf /tmp/t.tar.gz -C /tmp/tartest
# 结果：lib 变成真目录！内容: modules      ← 符号链接被替换

# 加选项
tar -xzf /tmp/t.tar.gz -C /tmp/tartest --keep-directory-symlink
# 结果：lib -> usr/lib ✓
```

### 1.3 连锁后果

`/lib` 被替换成只含 `modules/` 的真目录后：

```
/lib/aarch64-linux-gnu/     → 不存在了
/lib/ld-linux-aarch64.so.1  → 不存在了
```

于是：

| 症状 | 原因 |
| --- | --- |
| `/bin/bash: No such file or directory` | execve 找不到 ELF 解释器（`ld-linux-aarch64.so.1`），返回 ENOENT |
| `bash: /usr/bin/grep: cannot execute: required file not found` | 同上，grep 的动态加载器缺失 |
| **图形界面"密码不对"** | PAM 模块（`libpam.so.0`）无法加载 → 认证必然失败 |
| Phosh 界面仍正常显示 | 已在内存中运行的进程不受影响 |
| SSH 登录显示欢迎信息但 shell 失败 | sshd 已运行，认证通过（PAM 在内存中），但新 fork 的 shell 起不来 |

**关键迷惑点：** 系统看起来"部分正常"，容易误判为密码问题或 rootfs 损坏。

## 二、诊断方法

### 2.1 从 USB shell 的错误定位

设备的 USB shell 服务（`/opt/utsel/shserver.py`）会暴露真实错误：

```
Traceback (most recent call last):
  File "/opt/utsel/shserver.py", line 5, in serve
    os.execv('/bin/bash', ['/bin/bash', '-i'])
FileNotFoundError: [Errno 2] No such file or directory
```

这直接证明 `/bin/bash` 不可执行。

### 2.2 判断"文件不存在"还是"解释器缺失"

```sh
ls -l /bin/bash              # 存在 → 不是文件丢失
ldd /bin/bash                # 报错 → 动态加载器缺失
ls -ld /lib /lib64 /bin /sbin  # 检查是否为符号链接
```

**若 `/lib` 是 `drwxr-xr-x` 真目录而非 `lrwxrwxrwx`，即可确认是本次事故。**

## 三、修复方案

### 3.1 为什么需要 initramfs

事故状态下：
- 无法通过 SSH 登录（shell 起不来）
- 无法使用设备终端（同样依赖动态链接）
- 无法 chroot（需要能运行程序）

**唯一可用的入口是 initramfs**（自带 busybox，静态链接，不依赖 rootfs）。

### 3.2 修复 init 脚本

见 [`rescue-init.sh`](../rescue-init.sh)。核心逻辑：

```sh
# 1. 挂载 rootfs
mount -o rw,noatime /dev/sda14 /newroot

# 2. 对每个 usrmerge 目录
for pair in "/lib:usr/lib" "/lib64:usr/lib64" "/bin:usr/bin" "/sbin:usr/sbin"; do
    d="${pair%%:*}"; tgt="${pair##*:}"
    cur="/newroot$d"; dst="/newroot/$tgt"

    # 已是符号链接则跳过
    [ -L "$cur" ] && continue

    # 真目录：内容迁到目标，再删掉
    if [ -d "$cur" ]; then
        mkdir -p "$dst"
        cp -a "$cur/." "$dst/"
        rm -rf "$cur"
    fi

    # 建相对符号链接（与 Ubuntu 默认一致）
    ln -sfn "$tgt" "$cur"
done

# 3. 校验 → 写日志 → 无条件 switch_root
```

### 3.3 init 脚本的两个致命坑（我踩过）

**坑 1：`exec $BB sh` 导致内核 panic**

```sh
# 错误
exec $BB sh
```

initramfs 里 PID 1 退出 → 内核 panic → 黑屏卡死。**无终端时 shell 立即退出。**

**坑 2：`exec </dev/tty0` 重定向失败**

```sh
# 错误：initramfs 早期 /dev/tty0 可能还不存在
exec </dev/tty0 >/dev/tty0 2>&1
```

重定向失败 → 脚本中止 → PID 1 退出 → panic。

**正确做法：**

```sh
# 1. 绝不依赖 tty
# 2. 绝不 exec 交互 shell
# 3. 失败路径用永久 sleep 而非退出
while true; do $BB sleep 60; done

# 4. 无论如何都要 switch_root，让系统按原样启动
exec $BB switch_root "$NEWROOT" "$INITPATH"
```

## 四、修复结果

修复日志（`/root/pja110-rescue.log`）：

```
--- BEFORE ---
DIR  /lib  items=1 content=modules          ← 仅剩 modules
MISS /lib/ld-linux-aarch64.so.1
MISS /lib/aarch64-linux-gnu/libc.so.6

--- FIX ---
MOVE /lib content -> /usr/lib
  removed real dir /lib
  /lib -> usr/lib
  /lib64 -> usr/lib64
SKIP /bin (already link -> usr/bin)
SKIP /sbin (already link -> usr/sbin)

--- AFTER ---
LINK /lib -> usr/lib
LINK /lib64 -> usr/lib64
LINK /bin -> usr/bin
LINK /sbin -> usr/sbin

--- KEY FILES AFTER ---
OK   /bin/bash
OK   /lib/ld-linux-aarch64.so.1
OK   /lib/aarch64-linux-gnu/libc.so.6
OK   /lib/aarch64-linux-gnu/libpam.so.0
OK   /sbin/init
RESULT: ALL_GOOD
```

系统状态：

```
内核:      6.14.0-oneplus-xigua  running
失败服务:  0
USB:       172.16.42.1/24 正常
```

**无数据丢失。**

## 五、正确做法（避免再犯）

### 5.1 安装内核模块的正确方式

```sh
# ❌ 错误：会替换 usrmerge 符号链接
tar -xJf mods.tar.xz -C /

# ✅ 正确 1：加 --keep-directory-symlink
tar -xJf mods.tar.xz -C / --keep-directory-symlink

# ✅ 正确 2：直接解压到目标子目录
tar -xJf mods.tar.xz -C /lib/modules

# ✅ 正确 3：用 cp（不触碰目录本身）
cp -r mods/* /lib/modules/

# ✅ 正确 4：用 dpkg 安装（最规范）
dpkg -i pja110-kernel-mods.deb
```

### 5.2 打包时避免该问题

```sh
# ❌ 压缩包含顶层 lib/ 目录条目
cd /tmp/staging && tar -cJf mods.tar.xz lib

# ✅ 只打包具体内容，不含顶层目录
cd /tmp/staging/lib/modules && tar -cJf mods.tar.xz 6.14.0-oneplus-PJA110
```

### 5.3 检查清单

安装任何会写入系统目录的压缩包前：

- [ ] `tar -tJf pkg.tar.xz | head` 确认顶层是否是 `lib/` `/usr/` `/etc/` 这类会被 usrmerge 影响的目录
- [ ] 目标机上 `ls -ld /lib /bin /sbin /lib64` 确认是符号链接
- [ ] 使用 `--keep-directory-symlink` 或解压到子目录

## 六、相关文件

| 文件 | 说明 |
| --- | --- |
| `rescue-init.sh` | 自动修复 initramfs 脚本 |
| `tools/build_mini_initramfs.py` | 构建工具（`INIT` 变量指向 rescue-init.sh）|
| `out/ut-test/mini-vendor_boot_a.img` | 修复用 vendor_boot |

### 恢复正常 vendor_boot

修复完成后，设备仍运行救援镜像。恢复正常镜像：

```bash
# 恢复 build 脚本指向
sed -i "s|INIT = ROOT / 'rescue-init.sh'|INIT = ROOT / 'ut-initramfs-init.sh'|" tools/build_mini_initramfs.py
python3 tools/build_mini_initramfs.py
fastboot flash vendor_boot_a out/ut-test/mini-vendor_boot_a.img
```
