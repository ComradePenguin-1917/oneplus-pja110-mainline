#!/bin/bash
K=/root/dlkm/lib/modules/uff_fp_driver.ko
[ -f "$K" ] || cp /root/dlkm/lib/modules/uff_fp_driver.ko /root/hapdrv/ref/ 2>/dev/null
K=/root/hapdrv/ref/uff_fp_driver.ko
ls -l $K 2>/dev/null || { echo MISSING; exit 1; }
echo ""
echo "=== 1. 模块信息 ==="
strings -a $K 2>/dev/null | grep -E "^description=|^author=|^vermagic=" 
echo ""
echo "=== 2. 芯片厂商线索 ==="
strings -a $K 2>/dev/null | grep -iE "goodix|fpc|egis|silead|chipone|jiiov|qualcomm|synaptics|smoltek" | sort -u | head -15
echo ""
echo "=== 3. SPI 协议/命令 ==="
strings -a $K 2>/dev/null | grep -iE "spi|spi_sync|spi_write|transfer" | head -10
echo ""
echo "=== 4. 设备名 / 节点 ==="
strings -a $K 2>/dev/null | grep -iE "^/dev|fingerprint|fp_|uff" | head -15
echo FP5