#!/bin/bash
echo "=== 1. 当前槽位 ==="
echo -n "  misc 里的槽位信息: "
dd if=/dev/sda3 bs=1 skip=2048 count=8 2>/dev/null | od -An -tx1
echo ""
echo "=== 2. super 分区里的槽位相关（vendor_boot_a/b 等）==="
fastboot getvar all 2>/dev/null | head -5 || echo "  (fastboot 需 bootloader 模式)"
echo ""
echo "=== 3. super 分区布局 ==="
lsblk -o NAME,SIZE,PARTLABEL /dev/sda | grep -E "super|vbmeta"
echo "  super = $(lsblk -b -n -o SIZE /dev/sda6) bytes"
echo ""
echo "=== 4. 是否有 Android 分区残留（判断能否共存）==="
echo "  sda6 (super) 是 Android 动态分区容器"
echo "  vendor_boot / boot / dtbo 都在 super 里"
echo ""
echo "=== 5. 当前根分区 ==="
findmnt -n -o SOURCE /
echo ""
echo "=== 6. pmOS 在 B 槽的证据 ==="
lsblk -o NAME,LABEL,UUID /dev/sda | grep -iE "ut-root|pmos"
echo SLOT