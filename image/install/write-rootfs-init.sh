#!/bin/busybox sh
#
# PJA110 交付镜像安装器（initramfs）
#
# 为什么需要它：Windows 上的 fastboot 34.0.5 在把 8 GiB 镜像切成 sparse 分块时
# 会报 "Error reading sparse file"（max-download-size 只有 768 MiB，必须分块）。
# 与其和 fastboot 较劲，不如让设备自己写自己：
# 镜像本来就在 /dev/sda6（/srv，15 GiB）上，直接在设备内部 dd 到 /dev/sda14。
#
# 流程：
#   1. 挂 /dev/sda6
#   2. 校验 /pja110-bundle/rootfs.img（大小 + ext4 超级块魔数）
#   3. dd 到 /dev/sda14，fsync
#   4. 在 sda6 上留标记，之后的开机跳过写入
#   5. 挂 /dev/sda14 并 switch_root 正常启动
#
# 幂等：标记存在 → 跳过写入，直接启动。

set -u

BB=/bin/busybox
SRC_DEV=/dev/sda6
SRC_MNT=/src
SRC_IMG=/pja110-bundle/rootfs.img
DST_DEV=/dev/sda14
NEWROOT=/newroot
FLAG="$SRC_MNT/pja110-rootfs-written"
LOG=/tmp/write.log

$BB mount -t proc  proc /proc 2>/dev/null
$BB mount -t sysfs sys  /sys  2>/dev/null
$BB mkdir -p /dev
$BB mount -t devtmpfs dev /dev 2>/dev/null
$BB mkdir -p "$SRC_MNT" "$NEWROOT"

say() { echo "[write-rootfs] $*" | $BB tee -a "$LOG"; }

say "start, date=$($BB date)"

wait_dev() {
    local dev="$1" i=0
    while [ $i -lt 60 ]; do
        [ -b "$dev" ] && return 0
        i=$((i+1)); $BB sleep 1
    done
    return 1
}

# ---------------------------------------------------------------- 1. 源
wait_dev "$SRC_DEV" || { say "FATAL: $SRC_DEV 不存在"; while true; do $BB sleep 60; done; }
# 必须 rw：写完要在 sda6 上留标记
if ! $BB mount -o rw,noatime "$SRC_DEV" "$SRC_MNT"; then
    say "FATAL: 挂载 $SRC_DEV 失败"
    while true; do $BB sleep 60; done
fi
say "已挂载 $SRC_DEV"

if [ -f "$FLAG" ]; then
    say "标记存在（$FLAG），跳过写入，直接启动"
else
    # ------------------------------------------------------------ 2. 校验
    if [ ! -f "$SRC_MNT$SRC_IMG" ]; then
        say "FATAL: 找不到 $SRC_MNT$SRC_IMG"
        while true; do $BB sleep 60; done
    fi
    SIZE=$($BB stat -c %s "$SRC_MNT$SRC_IMG" 2>/dev/null || echo 0)
    say "源镜像大小: $SIZE 字节（期望 8589934592）"
    if [ "$SIZE" != "8589934592" ]; then
        say "FATAL: 镜像大小不对"
        while true; do $BB sleep 60; done
    fi
    # ext4 超级块在偏移 1024，魔数 0xEF53 位于 +56
    MAGIC=$($BB dd if="$SRC_MNT$SRC_IMG" bs=1 skip=1080 count=2 2>/dev/null | $BB od -An -tx1 | $BB tr -d ' \n')
    say "ext4 超级块魔数: $MAGIC（期望 53ef）"
    if [ "$MAGIC" != "53ef" ]; then
        say "FATAL: 不是 ext4 镜像"
        while true; do $BB sleep 60; done
    fi

    # ------------------------------------------------------------ 3. 写入
    wait_dev "$DST_DEV" || { say "FATAL: $DST_DEV 不存在"; while true; do $BB sleep 60; done; }
    say "开始写入 $SRC_MNT$SRC_IMG -> $DST_DEV"
    if $BB dd if="$SRC_MNT$SRC_IMG" of="$DST_DEV" bs=4M 2>>"$LOG"; then
        $BB sync
        say "写入完成"
        $BB touch "$FLAG" && say "已留标记 $FLAG"
    else
        say "FATAL: 写入失败"
        # 不留标记，下次开机重试
        while true; do $BB sleep 60; done
    fi
fi

$BB umount "$SRC_MNT" 2>/dev/null || $BB umount -l "$SRC_MNT" 2>/dev/null

# ---------------------------------------------------------------- 5. 启动
say "挂载 $DST_DEV 并 switch_root"
if ! $BB mount -o rw,noatime "$DST_DEV" "$NEWROOT"; then
    say "FATAL: 挂载 $DST_DEV 失败"
    while true; do $BB sleep 60; done
fi
$BB cp "$LOG" "$NEWROOT/root/write-rootfs.log" 2>/dev/null

$BB mount --move /proc "$NEWROOT/proc" 2>/dev/null
$BB mount --move /sys  "$NEWROOT/sys"  2>/dev/null
$BB mount --move /dev  "$NEWROOT/dev"  2>/dev/null

exec $BB switch_root "$NEWROOT" /sbin/init
