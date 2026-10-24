#!/bin/bash
B=/mnt/h/workspace/PJA110-Mainline/out/payload_extract
mkdir -p /root/dlkm /root/hapdrv/ref
mountpoint -q /root/dlkm || mount -t ext4 -o ro,loop $B/vendor_dlkm.img /root/dlkm 2>/dev/null
K=/root/dlkm/lib/modules/uff_fp_driver.ko
ls -l "$K" || { echo "NOT FOUND"; ls /root/dlkm/lib/modules/ | grep -iE "fp|finger" ; exit 1; }
cp "$K" /root/hapdrv/ref/
K=/root/hapdrv/ref/uff_fp_driver.ko
echo ""
echo "=== 模块信息 ==="
strings -a $K | grep -E "^description=|^author=|^vermagic="
echo ""
echo "=== 芯片厂商 ==="
strings -a $K | grep -iE "goodix|fpc|egis|silead|chipone|jiiov|smoltek|qualcomm" | sort -u | head -15
echo ""
echo "=== 关键字符串 ==="
strings -a $K | grep -iE "spi_|GPIO|ldo|reset|irq|power" | head -20
echo FP6