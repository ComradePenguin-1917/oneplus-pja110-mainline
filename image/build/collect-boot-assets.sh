#!/bin/bash
# PJA110 交付镜像 —— 收集引导资产并组装交付包
#
# 在**设备上以 root 运行**。从当前正常工作的分区直接 dump 三个引导分量，
# 与已构建的 rootfs.img 一起组成可交付的 bundle。
#
#   sudo ./collect-boot-assets.sh [--rootfs /srv/pja110-image/rootfs.img] [--out /srv/pja110-bundle]
#
# 产出（--out 目录）：
#   boot_a.img          sde13（192 MiB，内核）
#   vendor_boot_a.img   sde24（192 MiB，initramfs + 基准 DTB）
#   dtbo_a.img          sde17（24 MiB，DTBO，model/compatible 已改为 PJA110）
#   rootfs.img          根文件系统（8 GiB 稀疏）
#   SHA256SUMS
#   MANIFEST.txt        版本与校验信息
#
# 为什么从分区 dump 而不是复用工作区文件：
#   保证交付的三个分量与"当前验证通过的系统"完全一致，
#   不会因为工作区里有多份候选镜像而拿错。

set -u

ROOTFS=/srv/pja110-image/rootfs.img
OUT=/srv/pja110-bundle
VENDOR_BOOT=""

while [ $# -gt 0 ]; do
    case "$1" in
        --rootfs) ROOTFS="$2"; shift 2 ;;
        --out)    OUT="$2";    shift 2 ;;
        # 交付时的 vendor_boot_a 必须放"正常 initramfs"。
        # 如果设备上现在刷的是安装器，sde24 的 dump 就是错的，用这个参数覆盖。
        --vendor-boot) VENDOR_BOOT="$2"; shift 2 ;;
        *) echo "未知参数: $1"; exit 2 ;;
    esac
done

[ "$(id -u)" -eq 0 ] || { echo "必须以 root 运行"; exit 1; }
[ -f "$ROOTFS" ] || { echo "找不到 rootfs 镜像: $ROOTFS"; exit 1; }

# 分区表：sde13=boot_a, sde17=dtbo_a, sde24=vendor_boot_a
declare -A PART=(
    [boot_a]=/dev/sde13
    [dtbo_a]=/dev/sde17
    [vendor_boot_a]=/dev/sde24
)

echo "=== 1. 前置检查：确认分区标签 ==="
for name in "${!PART[@]}"; do
    dev="${PART[$name]}"
    label=$(lsblk -no PARTLABEL "$dev" 2>/dev/null)
    if [ "$label" != "$name" ]; then
        echo "  ✗ $dev 的 PARTLABEL 是 '$label'，期望 '$name' —— 中止"
        exit 1
    fi
    printf '  ✓ %-16s %s (%s 字节)\n' "$name" "$dev" "$(blockdev --getsize64 "$dev")"
done

echo ""
echo "=== 2. 运行环境 ==="
echo "  当前运行内核: $(uname -r)"
echo "  rootfs 设备:  $(findmnt -no SOURCE /)"

echo ""
echo "=== 3. 创建输出目录 ==="
mkdir -p "$OUT"
avail=$(df -BG --output=avail "$OUT" | awk 'NR==2{gsub(/G/,"",$1);print $1}')
need=12
echo "  $OUT 可用 ${avail}G（需要约 ${need}G）"
[ "${avail:-0}" -ge "$need" ] || { echo "  ✗ 空间不足"; exit 1; }

echo ""
echo "=== 4. dump 引导分区 ==="
for name in boot_a vendor_boot_a dtbo_a; do
    dev="${PART[$name]}"
    if [ "$name" = "vendor_boot_a" ] && [ -n "$VENDOR_BOOT" ]; then
        [ -f "$VENDOR_BOOT" ] || { echo "  ✗ 找不到 $VENDOR_BOOT"; exit 1; }
        cp "$VENDOR_BOOT" "$OUT/$name.img" || { echo "  ✗ 复制失败"; exit 1; }
        printf '  %-16s %s（来自 --vendor-boot 覆盖）\n' "$name.img" "$(ls -lh "$OUT/$name.img" | awk '{print $5}')"
        continue
    fi
    dd if="$dev" of="$OUT/$name.img" bs=1M conv=sparse status=none || { echo "  ✗ $name dump 失败"; exit 1; }
    printf '  %-16s %s\n' "$name.img" "$(ls -lh "$OUT/$name.img" | awk '{print $5}')"
done

echo ""
echo "=== 5. 复制 rootfs 镜像 ==="
cp --sparse=always "$ROOTFS" "$OUT/rootfs.img" || { echo "  ✗ 复制失败"; exit 1; }
printf '  %-16s %s（实占 %s）\n' "rootfs.img" "$(ls -lh "$OUT/rootfs.img" | awk '{print $5}')" "$(du -h "$OUT/rootfs.img" | cut -f1)"

echo ""
echo "=== 6. 校验和与清单 ==="
( cd "$OUT" && sha256sum boot_a.img vendor_boot_a.img dtbo_a.img rootfs.img > SHA256SUMS )
cat "$OUT/SHA256SUMS" | sed 's/^/  /'

{
    echo "PJA110 delivery bundle"
    echo "built:        $(date -Is)"
    echo "kernel:       $(uname -r)"
    echo "hostname:     pja110"
    echo "default user: ubuntu / 123456"
    echo ""
    echo "files:"
    for f in boot_a.img vendor_boot_a.img dtbo_a.img rootfs.img; do
        printf '  %-20s %12s bytes  %s\n' "$f" "$(stat -c%s "$OUT/$f")" \
               "$(sha256sum "$OUT/$f" | cut -d' ' -f1)"
    done
    echo ""
    echo "flash target:"
    echo "  boot_a.img        -> fastboot flash boot_a"
    echo "  vendor_boot_a.img -> fastboot flash vendor_boot_a"
    echo "  dtbo_a.img        -> fastboot flash dtbo_a"
    echo "  rootfs.img        -> 见 docs/delivery-image-20261024.md（8 GiB 无法直接 fastboot）"
    echo ""
    echo "features:"
    echo "  kernel 6.14.0-oneplus-PJA110 (mainline)"
    echo "  panel mode-aware 60/120Hz, OSK height-ratio 35%, SoC name in Settings"
    echo "  DT model/compatible = OnePlus PJA110 / oneplus,pja110"
    echo "  USB: MTP only (exposes ~/Shared), no NCM network"
    echo "  no firstboot scripts: device name / password via Settings (polkit rules allow it)"
    echo "  pja110-growfs.service: resizes root to the full partition on first boot"
    echo "  ssh-host-keys drop-in: generates host keys at boot (idempotent)"
} > "$OUT/MANIFEST.txt"

echo ""
echo "=== 7. 汇总 ==="
du -sh "$OUT" | sed 's/^/  总大小: /'
ls -lh "$OUT" | sed 's/^/  /'
echo ""
echo "PASS: 交付包已就绪 → $OUT"
