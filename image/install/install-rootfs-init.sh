#!/bin/busybox sh
# PJA110 交付镜像安装器（基于已验证的 ut-initramfs-init.sh）
#
# 与正常 initramfs 的唯一差别：在挂载 rootfs 之前，如果 sda6 上的标记不存在，
# 就先把 sda6 里的交付镜像写进 /dev/sda14，校验通过后再切换根。
#
# 设计原则（来自这次事故）：
#   * 所有失败路径都是「原地 sleep」，绝不 exec shell（无 tty 时 shell 退出会让
#     PID1 消失 → kernel panic → 重启循环，屏幕上就只剩反复的开机 logo）
#   * dd 之后必须读回校验，不一致就不切换根
#   * 用 sda6 上的标记文件保证幂等（不看分区的当前内容，因为 resize2fs 会改变它）
#
# 不使用 set -u（沿用原脚本的教训：缺个变量就整段失效）

BB=/bin/busybox
ROOT_DEV=/dev/sda14
NEWROOT=/newroot
SRC_DEV=/dev/sda6
SRC_MNT=/src
SRC_IMG=/pja110-bundle/rootfs.img
FLAG=/src/pja110-rootfs-written-v2
IMG_SIZE=8589934592

$BB mount -t proc  proc /proc
$BB mount -t sysfs sys  /sys
$BB mkdir -p /dev
$BB mount -t devtmpfs dev /dev
$BB mkdir -p "$SRC_MNT" "$NEWROOT"

say() {
    echo "[install-rootfs] $1"
    if [ -c /dev/tty0 ]; then
        echo "[install-rootfs] $1" > /dev/tty0
    fi
    if [ -c /dev/console ]; then
        echo "[install-rootfs] $1" > /dev/console
    fi
}

# 失败时原地等待，避免 panic 重启
hold() {
    say "HOLD: $1"
    say "设备停在 initramfs，等待人工重刷（不会重启）"
    while true; do
        $BB sleep 30
    done
}

say "starting"

# ---------------------------------------------------------------- 等根设备
say "waiting for $ROOT_DEV"
i=0
while [ $i -lt 60 ]; do
    [ -b "$ROOT_DEV" ] && break
    i=$((i + 1))
    $BB sleep 1
done
[ -b "$ROOT_DEV" ] || hold "$ROOT_DEV 不存在"
say "root device ready"

# ---------------------------------------------------------------- 写镜像
if [ ! -b "$SRC_DEV" ]; then
    say "WARNING: $SRC_DEV 不存在，跳过安装步骤"
else
    $BB mkdir -p "$SRC_MNT"
    if ! $BB mount -o rw,noatime "$SRC_DEV" "$SRC_MNT"; then
        say "WARNING: 挂载 $SRC_DEV 失败，跳过安装步骤"
    else
        # 上一次安装器可能已经留下 /pja110-rootfs-written，但它那次写入很可能是坏的，
        # 所以清掉旧标记（本次用 -v2 标记强制再写一遍）
        $BB rm -f /src/pja110-rootfs-written
        if [ -f "$FLAG" ]; then
            say "标记 $FLAG 存在 → 已安装过，跳过写入"
        else
            say "首次安装：准备写入交付镜像"
            if [ ! -f "$SRC_MNT$SRC_IMG" ]; then
                hold "找不到 $SRC_MNT$SRC_IMG"
            fi

            SIZE=$($BB stat -c %s "$SRC_MNT$SRC_IMG")
            say "源镜像大小: $SIZE（期望 $IMG_SIZE）"
            [ "$SIZE" = "$IMG_SIZE" ] || hold "源镜像大小不对"

            MAGIC=$($BB dd if="$SRC_MNT$SRC_IMG" bs=1 skip=1080 count=2 2>/dev/null | $BB od -An -tx1 | $BB tr -d ' \n')
            say "源 ext4 魔数: $MAGIC（期望 53ef）"
            [ "$MAGIC" = "53ef" ] || hold "源不是 ext4 镜像"

            say "开始 dd 到 $ROOT_DEV（约 8 GiB，1-2 分钟）"
            if ! $BB dd if="$SRC_MNT$SRC_IMG" of="$ROOT_DEV" bs=4M; then
                hold "dd 失败"
            fi
            $BB sync
            $BB sleep 2

            # ---- 读回校验 ----
            SUM_SRC=$($BB dd if="$SRC_MNT$SRC_IMG" bs=8192 count=1 2>/dev/null | $BB md5sum | $BB cut -d' ' -f1)
            SUM_DST=$($BB dd if="$ROOT_DEV" bs=8192 count=1 2>/dev/null | $BB md5sum | $BB cut -d' ' -f1)
            say "读回校验: src=$SUM_SRC dst=$SUM_DST"
            if [ "$SUM_SRC" != "$SUM_DST" ]; then
                hold "读回校验不一致"
            fi

            MAGIC2=$($BB dd if="$ROOT_DEV" bs=1 skip=1080 count=2 2>/dev/null | $BB od -An -tx1 | $BB tr -d ' \n')
            say "目标 ext4 魔数: $MAGIC2"
            [ "$MAGIC2" = "53ef" ] || hold "目标没有 ext4 超级块"

            if $BB touch "$FLAG"; then
                say "写入完成，已留标记"
            else
                say "WARNING: 标记写入失败（下次开机会重复安装）"
            fi
            $BB sync
        fi
        $BB umount "$SRC_MNT" 2>/dev/null
    fi
fi

# ---------------------------------------------------------------- 切根
say "mounting $ROOT_DEV"
if ! $BB mount -o rw,noatime "$ROOT_DEV" "$NEWROOT"; then
    hold "挂载 $ROOT_DEV 失败"
fi

if [ ! -x "$NEWROOT/sbin/init" ]; then
    hold "$NEWROOT/sbin/init 不存在"
fi

$BB mkdir -p "$NEWROOT/proc" "$NEWROOT/sys" "$NEWROOT/dev" "$NEWROOT/run"
$BB mount --move /proc "$NEWROOT/proc"
$BB mount --move /sys  "$NEWROOT/sys"
$BB mount --move /dev  "$NEWROOT/dev"

say "switching root"
exec $BB switch_root "$NEWROOT" /sbin/init
