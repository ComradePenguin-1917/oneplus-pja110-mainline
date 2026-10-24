#!/bin/busybox sh
#
# PJA110 救援 initramfs：回退「penguin → ubuntu」改名
#
# 起因：改用户名的操作只做了一半（组改了、配置改了，用户记录在改名时因进程占用失败），
#       导致 boot 后 systemd 卡在 multi-user 之前，sshd / 23 端口都没起来，
#       但更早启动的 USB 网卡仍在，表现成「能 ping 通但没有服务」。
#
# 本脚本：挂载 rootfs → 把所有 ubuntu 引用改回 penguin → switch_root 正常启动。
# 全部操作幂等；日志写到 rootfs 的 /root/rename-revert.log，开机后可读。
#
# 设计约束（沿用前几版经验）：
#   * 不依赖 /dev/tty0，不 exec 交互 shell（无终端会让 PID1 退出 → kernel panic）
#   * 任何失败都继续 switch_root，避免越修越坏

BB=/bin/busybox
ROOT_DEV=/dev/sda14
NEWROOT=/newroot
MSG=/tmp/revert.log

$BB mount -t proc  proc /proc 2>/dev/null
$BB mount -t sysfs sys /sys   2>/dev/null
$BB mkdir -p /dev
$BB mount -t devtmpfs dev /dev 2>/dev/null

: > "$MSG"
say() { echo "$1" >> "$MSG"; }

say "PJA110 rescue: revert user rename ubuntu -> penguin"
say "date: $($BB date 2>/dev/null)"

# ---- 等根设备 ---------------------------------------------------------
i=0
while [ $i -lt 60 ]; do
    [ -b "$ROOT_DEV" ] && break
    i=$((i+1)); $BB sleep 1
done
if [ ! -b "$ROOT_DEV" ]; then
    say "FATAL: $ROOT_DEV 不存在"
    i=0
    while [ $i -lt 600 ]; do i=$((i+1)); $BB sleep 1; done
    # 超时后仍尝试 switch_root 是不可能的（没有 root），保持睡眠等 fastboot
    while true; do $BB sleep 60; done
fi

$BB mkdir -p "$NEWROOT"
say ""
say "mount $ROOT_DEV -> $NEWROOT"
if ! $BB mount -o rw,noatime "$ROOT_DEV" "$NEWROOT"; then
    say "FATAL: 挂载失败（可能文件系统需要 fsck）"
    say "尝试只读挂载以记录日志…"
    if $BB mount -o ro "$ROOT_DEV" "$NEWROOT" 2>/dev/null; then
        say "  只读挂载成功；文件系统本身可挂载，rw 失败原因需另查"
        $BB umount "$NEWROOT"
    fi
    while true; do $BB sleep 60; done
fi
say "mount ok"

R="$NEWROOT"

# ---- 回退：账户文件 ---------------------------------------------------
say ""
say "--- 回退账户文件 ---"
for f in etc/passwd etc/shadow etc/group etc/gshadow \
         etc/passwd- etc/shadow- etc/group- etc/gshadow-; do
    [ -f "$R/$f" ] || continue
    if $BB grep -q ubuntu "$R/$f" 2>/dev/null; then
        $BB sed -i 's/ubuntu/penguin/g' "$R/$f" && say "  已回退 $f"
    fi
done

# ---- 回退：家目录 -----------------------------------------------------
say ""
say "--- 家目录 ---"
if [ -d "$R/home/ubuntu" ] && [ ! -e "$R/home/penguin" ]; then
    if $BB mv "$R/home/ubuntu" "$R/home/penguin" 2>/dev/null; then
        say "  /home/ubuntu -> /home/penguin"
    else
        say "  ⚠️ 移动失败（可能有未关闭的文件），保留 /home/ubuntu"
    fi
elif [ -d "$R/home/ubuntu" ]; then
    say "  ⚠️ /home/penguin 已存在，未移动 /home/ubuntu（请开机后手工合并）"
else
    say "  /home/ubuntu 不存在，跳过"
fi

# ---- 回退：登录与提权配置 --------------------------------------------
say ""
say "--- 登录与提权 ---"
for f in etc/greetd/config.toml \
         etc/systemd/system/getty@tty1.service.d/autologin.conf \
         etc/sudoers.d/pja110-firstboot \
         usr/local/sbin/pja110-firstboot-helper \
         etc/subuid etc/subgid; do
    [ -f "$R/$f" ] || continue
    if $BB grep -q ubuntu "$R/$f" 2>/dev/null; then
        $BB sed -i 's/ubuntu/penguin/g' "$R/$f" && say "  已回退 $f"
    fi
done

# sudoers 文件改名
if [ -f "$R/etc/sudoers.d/90-ubuntu-nopasswd" ] && [ ! -e "$R/etc/sudoers.d/90-penguin-nopasswd" ]; then
    $BB mv "$R/etc/sudoers.d/90-ubuntu-nopasswd" "$R/etc/sudoers.d/90-penguin-nopasswd" \
        && say "  90-ubuntu-nopasswd -> 90-penguin-nopasswd"
fi

# accounts-daemon 缓存
if [ -d "$R/var/lib/AccountsService/users" ]; then
    if [ -f "$R/var/lib/AccountsService/users/ubuntu" ] && \
       [ ! -e "$R/var/lib/AccountsService/users/penguin" ]; then
        $BB mv "$R/var/lib/AccountsService/users/ubuntu" \
               "$R/var/lib/AccountsService/users/penguin" && say "  accounts 缓存已回退"
    fi
fi

# ---- 记录回退后的关键状态 --------------------------------------------
say ""
say "--- 回退结果 ---"
say "  passwd 里 penguin: $($BB grep -c '^penguin:' "$R/etc/passwd" 2>/dev/null)"
say "  passwd 里 ubuntu : $($BB grep -c '^ubuntu:'  "$R/etc/passwd" 2>/dev/null)"
say "  group 里 penguin : $($BB grep -c 'penguin'  "$R/etc/group"  2>/dev/null)"
say "  greetd: $($BB grep '^user = \"' "$R/etc/greetd/config.toml" 2>/dev/null | $BB tail -1)"
say "  getty : $($BB grep -o 'autologin [a-z]*' "$R/etc/systemd/system/getty@tty1.service.d/autologin.conf" 2>/dev/null)"

# ---- 把日志落到 rootfs -----------------------------------------------
$BB cp "$MSG" "$R/root/rename-revert.log" 2>/dev/null && say "日志已写入 /root/rename-revert.log"

# ---- 正常启动 ---------------------------------------------------------
$BB mount --move /proc "$NEWROOT/proc" 2>/dev/null
$BB mount --move /sys  "$NEWROOT/sys"  2>/dev/null
$BB mount --move /dev  "$NEWROOT/dev"  2>/dev/null

exec $BB switch_root "$NEWROOT" /sbin/init
