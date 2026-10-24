#!/bin/bash
# PJA110 交付镜像 —— rootfs 镜像构建
#
# 在**设备上以 root 运行**，把当前运行的系统打成一个可 fastboot 刷入的
# ext4 镜像（默认 6 GiB），并对镜像做交付所需的清洗与改名。
#
#   sudo ./build-rootfs.sh [--size 6G] [--out /srv/pja110-image]
#
# 产出（在 --out 目录下）：
#   rootfs.img        可直接 fastboot flash userdata 的 ext4 镜像
#   rootfs.img.sha256
#   build-report.txt  构建记录（大小、UUID、校验结果）
#
# 设计要点：
#   * 镜像的**文件系统 UUID 与 live rootfs 保持一致**，所以 fstab 和
#     引导程序的 root=UUID= 都不用改
#   * 改名（penguin→ubuntu）在**镜像内离线执行**，不碰运行中的系统
#   * 首启 marker 复位 → 刷入后第一次开机会走首启流程

set -u

SIZE=8G
OUT=/srv/pja110-image
IMGNAME=rootfs.img

while [ $# -gt 0 ]; do
    case "$1" in
        --size) SIZE="$2"; shift 2 ;;
        --out)  OUT="$2";  shift 2 ;;
        *) echo "未知参数: $1"; exit 2 ;;
    esac
done

HERE="$(cd "$(dirname "$0")" && pwd)"
IMG="$OUT/$IMGNAME"
MNT=/run/pja110-imgroot
LIVE_UUID=8c04e46c-5d09-42c5-bccf-5e20d49a17ff
NEW_USER=ubuntu

STEPS=0
step() { STEPS=$((STEPS+1)); printf '\n=== [%d] %s ===\n' "$STEPS" "$*"; }
fail() { printf '\n✗ %s\n' "$*"; exit 1; }

[ "$(id -u)" -eq 0 ] || fail "必须以 root 运行"

# ---------------------------------------------------------------- 0. 预检
step "预检"
[ -d /etc ] && [ -b /dev/sda14 ] || fail "环境异常"
echo "  rootfs 设备: $(findmnt -no SOURCE /)"
echo "  已用空间:    $(df -h / | awk 'NR==2{print $3}')"
echo "  输出目录:    $OUT"
mkdir -p "$OUT" || fail "无法创建 $OUT"
avail=$(df -BG --output=avail "$OUT" | awk 'NR==2{gsub(/G/,"",$1);print $1}')
echo "  $OUT 可用:   ${avail}G"
[ "${avail:-0}" -ge 12 ] || fail "$OUT 空间不足（需要镜像两倍左右余量）"

# 确认 rsync 存在
command -v rsync >/dev/null 2>&1 || fail "缺少 rsync"

# 确认改名脚本存在
[ -f "$HERE/rename-user-offline.sh" ] || fail "缺少 $HERE/rename-user-offline.sh"

# ---------------------------------------------------------------- 1. locale
step "locale（en_US.UTF-8）"
if command -v locale-gen >/dev/null 2>&1; then
    grep -q '^en_US.UTF-8 UTF-8' /etc/locale.gen 2>/dev/null || \
        echo 'en_US.UTF-8 UTF-8' >> /etc/locale.gen
    locale-gen en_US.UTF-8 >/dev/null 2>&1 && echo "  已生成 en_US.UTF-8"
else
    echo "  ⚠️ 没有 locale-gen，跳过（镜像里 locale 可能不完整）"
fi

# ---------------------------------------------------------------- 2. mkfs
step "创建镜像文件 $IMG ($SIZE)"
umount "$MNT" 2>/dev/null || true
rm -f "$IMG"
truncate -s "$SIZE" "$IMG" || fail "truncate 失败"
# 关键：沿用 live rootfs 的 UUID，fstab 与 root= 都不用改
mkfs.ext4 -F -m 0 -L ut-root -U "$LIVE_UUID" "$IMG" >/dev/null 2>&1 \
    || fail "mkfs.ext4 失败"
echo "  完成，UUID=$(blkid -s UUID -o value "$IMG")"

mkdir -p "$MNT"
mount -o loop "$IMG" "$MNT" || fail "挂载镜像失败"

# ---------------------------------------------------------------- 3. rsync
step "复制根文件系统"
# 关键：排除易变/无用内容，否则会撑爆镜像
#   /var/log/*      journal + syslog + kern.log（实测 1.1 GB）
#   /var/cache/*    apt 包缓存与 pkgcache.bin（实测 180 MB）
#   /var/crash/*    核心转储（实测 3 × ~620 MB 稀疏文件，rsync 会变实心）
#   /var/lib/apt/lists/*  APT 索引（实测 ~100 MB）
EXCLUDES=(
    --exclude=/proc/* --exclude=/sys/* --exclude=/dev/* --exclude=/run/*
    --exclude=/tmp/* --exclude=/var/tmp/* --exclude=/mnt/* --exclude=/media/*
    --exclude=/srv/* --exclude=/lost+found --exclude=/swapfile
    --exclude=/var/log/*
    --exclude=/var/cache/*
    --exclude=/var/crash/*
    --exclude=/var/lib/apt/lists/*
    --exclude=/var/lib/docker
)
# --sparse 保证稀疏文件不被"实心化"
rsync -aHAX --sparse --numeric-ids "${EXCLUDES[@]}" / "$MNT/" \
    || fail "rsync 失败"
echo "  镜像已用: $(du -sh "$MNT" 2>/dev/null | cut -f1)"

# 被排除的目录要重建（否则系统缺 /var/log 等会报错）
for d in var/log var/log/journal var/cache var/cache/apt var/cache/apt/archives \
         var/crash var/lib/apt/lists; do
    mkdir -p "$MNT/$d"
done
chown root:root       "$MNT/var/log"           2>/dev/null; chmod 0755 "$MNT/var/log"
chown root:systemd-journal "$MNT/var/log/journal" 2>/dev/null; chmod 2755 "$MNT/var/log/journal"
for f in wtmp btmp lastlog; do
    : > "$MNT/var/log/$f"
done
chown root:utmp "$MNT/var/log/wtmp" 2>/dev/null; chmod 0664 "$MNT/var/log/wtmp"
chown root:utmp "$MNT/var/log/btmp" 2>/dev/null; chmod 0660 "$MNT/var/log/btmp"
chmod 0664 "$MNT/var/log/lastlog" 2>/dev/null
echo "  已重建 /var/log、/var/cache、/var/crash 等空目录"

# ---------------------------------------------------------------- 4. 改名
step "离线改名 penguin -> $NEW_USER（如需）"
if grep -q "^$NEW_USER:" "$MNT/etc/passwd"; then
    echo "  镜像里已经是 $NEW_USER，跳过"
elif grep -q '^penguin:' "$MNT/etc/passwd"; then
    bash "$HERE/rename-user-offline.sh" "$MNT" || fail "改名失败"
else
    fail "镜像里既没有 penguin 也没有 $NEW_USER，状态异常"
fi

# ---------------------------------------------------------------- 5. 清洗
step "交付清洗"
R="$MNT"
c() { printf '  %s\n' "$*"; }

# 5.1 设备唯一标识
[ -f "$R/etc/machine-id" ] && : > "$R/etc/machine-id" && c "machine-id 已清空"
rm -f "$R"/etc/ssh/ssh_host_*_key "$R"/etc/ssh/ssh_host_*_key.pub && c "SSH 主机密钥已删除"

# 5.2 网络凭据
if compgen -G "$R/etc/NetworkManager/system-connections/*" >/dev/null; then
    rm -f "$R"/etc/NetworkManager/system-connections/* && c "Wi-Fi/网络配置已删除"
fi

# 5.3 日志与缓存
rm -rf "$R"/var/log/journal/* 2>/dev/null && c "journal 已清空"
find "$R/var/log" -xdev -type f \( -name '*.log' -o -name '*.gz' -o -name '*.[0-9]' \) -delete 2>/dev/null
for f in wtmp btmp lastlog; do
    [ -f "$R/var/log/$f" ] && : > "$R/var/log/$f"
done
c "日志文件已清空"
rm -rf "$R"/var/cache/apt/archives/* 2>/dev/null && c "apt 缓存已清空"
rm -rf "$R"/tmp/* "$R"/var/tmp/* 2>/dev/null && c "临时目录已清空"

# 5.4 个人痕迹
rm -f "$R"/root/.bash_history "$R"/root/.python_history
for h in "$R"/home/*/.bash_history "$R"/home/*/.python_history; do
    [ -e "$h" ] && rm -f "$h"
done
rm -f "$R"/home/*/.ssh/id_* "$R"/home/*/.ssh/known_hosts "$R"/home/*/.ssh/authorized_keys 2>/dev/null
c "shell 历史与 SSH 用户密钥已清理"

# 5.5 构建机残留
rm -rf "$R"/root/fb-backup "$R"/root/pos-src "$R"/root/patchset "$R"/root/dtbo-work \
       "$R"/root/gcc-src "$R"/root/gcc-src2 "$R"/root/gcc-orig \
       "$R"/root/pos-v0.38.0.tar.gz "$R"/root/pos-patched.tar.gz \
       "$R"/root/pkgs-before-*.txt "$R"/root/ubuntu.sources.bak \
       "$R"/root/rename-revert.log "$R"/root/charger-logs 2>/dev/null
c "构建残留已清理"

# 5.6 交付口径：hostname / hosts / locale / 时区
HOSTNAME_DEF=pja110
echo "$HOSTNAME_DEF" > "$R/etc/hostname"
if grep -q '^127\.0\.1\.1' "$R/etc/hosts"; then
    sed -i -E "s|^127\.0\.1\.1.*|127.0.1.1\t$HOSTNAME_DEF|" "$R/etc/hosts"
else
    printf '127.0.1.1\t%s\n' "$HOSTNAME_DEF" >> "$R/etc/hosts"
fi
sed -i '/^LANG=/d' "$R/etc/default/locale" 2>/dev/null || true
echo 'LANG=en_US.UTF-8' >> "$R/etc/default/locale"
echo "Asia/Shanghai" > "$R/etc/timezone"
ln -sf /usr/share/zoneinfo/Asia/Shanghai "$R/etc/localtime"
c "hostname=$HOSTNAME_DEF, locale=en_US.UTF-8, tz=Asia/Shanghai"

# 5.7 fstab：root 用镜像自己的 UUID
IMG_UUID=$(blkid -s UUID -o value "$IMG")
sed -i -E "s|^UUID=[0-9a-f-]+([[:space:]]+/[[:space:]])|UUID=$IMG_UUID\1|" "$R/etc/fstab"
c "fstab root 行 = UUID=$IMG_UUID"
grep -vE '^\s*#|^\s*$' "$R/etc/fstab" | sed 's/^/      /'

# 5.8 已无首启脚本（设备名/密码都在"设置"里改，见 docs/firstboot-removal-20261024.md）。
#     只剩一个幂等的 pja110-growfs.service 在首次开机时把根分区扩到整盘。
[ -f "$R/etc/systemd/system/pja110-growfs.service" ] \
    && c "扩容单元在位（首次开机自动 resize2fs）" \
    || c "⚠️ 缺少 pja110-growfs.service，刷入后根分区只有 8G"

# ---------------------------------------------------------------- 6. 收尾
step "卸载与一致性检查"
sync
umount "$MNT" || fail "卸载失败"
e2fsck -f -y "$IMG" >/dev/null 2>&1
echo "  e2fsck 完成（退出码 $?）"

step "计算校验值与报告"
sha256sum "$IMG" | tee "$OUT/$IMGNAME.sha256" | sed 's/^/  /'
{
    echo "PJA110 rootfs image build report"
    echo "date:      $(date -Is)"
    echo "image:     $IMG"
    echo "size:      $(stat -c%s "$IMG") bytes ($(du -h "$IMG" | cut -f1))"
    echo "used:      $(df -h / | awk 'NR==2{print $3}') (live rootfs)"
    echo "fs uuid:   $IMG_UUID"
    echo "label:     ut-root"
    echo "user:      $NEW_USER (password 123456)"
    echo "hostname:  $HOSTNAME_DEF"
    echo "sha256:    $(cut -d' ' -f1 "$OUT/$IMGNAME.sha256")"
    echo ""
} > "$OUT/build-report.txt"
sed -n '1,12p' "$OUT/build-report.txt" | sed 's/^/  /'

echo ""
echo "PASS: 镜像构建完成 → $IMG"
