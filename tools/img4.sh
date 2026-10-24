#!/bin/bash
echo "=== 1. vendor_boot_a 分区实际大小 ==="
lsblk -b -o NAME,SIZE /dev/sda 2>/dev/null | grep -E "sda12|sda13"
echo "  sda12 = vendor_boot_a?"
echo ""
echo "=== 2. 各分区用途（从 GPT 分区名）==="
for p in 6 11 12 13 14; do
  echo -n "  sda$p: "
  lsblk -o PARTLABEL /dev/sda$p 2>/dev/null | tail -1
done
echo ""
echo "=== 3. 当前 vendor_boot 里的 initramfs 大小 ==="
ls -l /mnt/h/workspace/PJA110-Mainline/out/ut-test/mini-vendor_boot_a.img 2>/dev/null
echo ""
echo "=== 4. rootfs 实际需要（清理 apt 缓存后）==="
echo "  当前已用: $(df -h / | tail -1 | awk '{print $3}')"
echo "  apt 缓存: $(du -sh /var/cache/apt/archives 2>/dev/null | cut -f1)"
echo "  清理后约: $(awk -v a=$(df -k / | tail -1 | awk '{print $3}') -v b=$(du -sk /var/cache/apt/archives 2>/dev/null | cut -f1) 'BEGIN{printf "%.1fG", (a-b)/1024/1024}')"
echo ""
echo "=== 5. 压缩工具 ==="
for t in zstd xz gzip; do which $t >/dev/null 2>&1 && echo "  $t: $(which $t)"; done
echo ""
echo "=== 6. 是否有 loop/mount 权限（制作镜像需要）==="
losetup -f 2>&1 | head -1
echo IMG4