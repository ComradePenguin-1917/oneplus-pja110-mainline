#!/bin/busybox sh
#
# PJA110 自动修复 initramfs（无 tty 依赖版）
#
# 起因：`tar -xJf pja110-mods.tar.xz -C /` 中的 lib/ 目录条目替换了
#       usrmerge 下的 /lib 符号链接，使 /lib/aarch64-linux-gnu/*.so 与
#       动态加载器不可访问，导致所有动态链接程序（含 PAM）失效。
#
# 设计约束（前两版卡死的原因）：
#   * 绝不能依赖 /dev/tty0 —— initramfs 早期该节点可能不存在，
#     重定向失败会让 PID1 退出并触发内核 panic。
#   * 绝不能 exec interactive shell —— 无终端时 shell 立即退出。
#   * 修复失败也必须继续 switch_root，让系统按原样启动，
#     避免"越修越坏"。
#
# 日志：rootfs 的 /root/pja110-rescue.log（开机后可读）
#
BB=/bin/busybox
ROOT_DEV=/dev/sda14
NEWROOT=/newroot
LOG_INROOT=/root/pja110-rescue.log
MSG=/tmp/rescue.log

$BB mount -t proc  proc /proc 2>/dev/null
$BB mount -t sysfs sys  /sys  2>/dev/null
$BB mkdir -p /dev
$BB mount -t devtmpfs dev /dev 2>/dev/null

: > $MSG
say() { echo "$1" >> $MSG; }

say "PJA110 auto-fix: usrmerge symlinks"
say "date: $($BB date 2>/dev/null)"

# 等根设备（最多 60s）
i=0
while [ $i -lt 60 ]; do
    [ -b "$ROOT_DEV" ] && break
    i=$((i+1)); $BB sleep 1
done

if [ ! -b "$ROOT_DEV" ]; then
    say "FATAL: $ROOT_DEV 不存在，无法修复"
    # 仍尝试 switch_root 到某处？不，无 root 设备无法继续，只能挂起等待
    # 但为了不 panic，这里进入永久睡眠（比 panic 好，可通过 fastboot 重刷）
    say "进入睡眠，等待重新刷写"
    while true; do $BB sleep 60; done
fi

$BB mkdir -p "$NEWROOT"
say ""
say "mount $ROOT_DEV ..."
if ! $BB mount -o rw,noatime "$ROOT_DEV" "$NEWROOT"; then
    say "FATAL: 挂载失败"
    say "进入睡眠，等待重新刷写"
    while true; do $BB sleep 60; done
fi
say "mount ok"

# ---------- 修复前记录 ----------
say ""
say "--- BEFORE ---"
for d in /lib /lib64 /bin /sbin; do
    p="$NEWROOT$d"
    if [ -L "$p" ]; then
        say "LINK $d -> $($BB readlink "$p")"
    elif [ -d "$p" ]; then
        say "DIR  $d  items=$($BB ls "$p" 2>/dev/null | $BB wc -l) content=$($BB ls "$p" 2>/dev/null | $BB tr '\n' ' ')"
    else
        say "MISS $d"
    fi
done

say ""
say "--- KEY FILES BEFORE ---"
for f in /bin/bash /lib/ld-linux-aarch64.so.1 /lib/aarch64-linux-gnu/libc.so.6; do
    [ -e "$NEWROOT$f" ] && say "OK   $f" || say "MISS $f"
done

# ---------- 执行修复 ----------
say ""
say "--- FIX ---"
for pair in "/lib:usr/lib" "/lib64:usr/lib64" "/bin:usr/bin" "/sbin:usr/sbin"; do
    d="${pair%%:*}"
    tgt="${pair##*:}"
    cur="$NEWROOT$d"
    dst="$NEWROOT/$tgt"

    if [ -L "$cur" ]; then
        say "SKIP $d (already link -> $($BB readlink "$cur"))"
        continue
    fi

    if [ -d "$cur" ]; then
        say "MOVE $d content -> /$tgt"
        $BB mkdir -p "$dst" 2>/dev/null
        # -a 保留属性；失败也继续（可能只是部分文件已存在）
        $BB cp -a "$cur/." "$dst/" 2>/dev/null
        $BB rm -rf "$cur" 2>/dev/null
        say "  removed real dir $d"
    fi

    # 创建相对符号链接（与 Ubuntu 默认一致）
    $BB ln -sfn "$tgt" "$cur" 2>/dev/null
    say "  $d -> $($BB readlink "$cur")"
done

# ---------- 修复后校验 ----------
say ""
say "--- AFTER ---"
for d in /lib /lib64 /bin /sbin; do
    p="$NEWROOT$d"
    if [ -L "$p" ]; then
        say "LINK $d -> $($BB readlink "$p")"
    elif [ -d "$p" ]; then
        say "DIR  $d (STILL REAL DIR)"
    else
        say "MISS $d"
    fi
done

say ""
say "--- KEY FILES AFTER ---"
OK=1
for f in /bin/bash /lib/ld-linux-aarch64.so.1 /lib/aarch64-linux-gnu/libc.so.6 \
         /lib/aarch64-linux-gnu/libpam.so.0 /sbin/init /usr/sbin/init; do
    if [ -e "$NEWROOT$f" ]; then
        say "OK   $f"
    else
        say "MISS $f"
        OK=0
    fi
done
say "RESULT: $([ $OK -eq 1 ] && echo ALL_GOOD || echo INCOMPLETE)"

# ---------- 恢复被处理的模块目录 ----------
# 之前 tar 把模块放到 /lib/modules（现在是 usr/lib/modules 的一部分）
# 若 /usr/lib/modules/6.14.0-oneplus-PJA110 不存在而 /lib/modules 曾有内容，
# 上面的 cp -a 已一并迁移，无需额外处理。

# ---------- 写日志 ----------
$BB mkdir -p "$NEWROOT/root" 2>/dev/null
$BB cp $MSG "$NEWROOT$LOG_INROOT" 2>/dev/null

# ---------- 无条件 switch_root ----------
# 即使修复不完整也继续启动。系统若起不来，仍可用 fastboot 重刷。
$BB sync 2>/dev/null
$BB mkdir -p "$NEWROOT/proc" "$NEWROOT/sys" "$NEWROOT/dev" "$NEWROOT/run" 2>/dev/null
$BB umount /proc 2>/dev/null
$BB umount /sys  2>/dev/null
$BB umount /dev  2>/dev/null
$BB mount --move /proc "$NEWROOT/proc" 2>/dev/null
$BB mount --move /sys  "$NEWROOT/sys"  2>/dev/null
$BB mount --move /dev  "$NEWROOT/dev"  2>/dev/null

# 判断 init 存在与否，给出最可能可行的路径
if [ -x "$NEWROOT/sbin/init" ]; then
    INITPATH=/sbin/init
elif [ -x "$NEWROOT/usr/sbin/init" ]; then
    INITPATH=/usr/sbin/init
elif [ -x "$NEWROOT/lib/systemd/systemd" ]; then
    INITPATH=/lib/systemd/systemd
else
    INITPATH=/sbin/init
fi

exec $BB switch_root "$NEWROOT" "$INITPATH"
