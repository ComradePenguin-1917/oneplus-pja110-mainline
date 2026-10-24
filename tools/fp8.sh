#!/bin/bash
B=/mnt/h/workspace/PJA110-Mainline/out/payload_extract
mountpoint -q /root/vnd || mount -t erofs -o ro $B/vendor.img /root/vnd 2>/dev/null
echo "=== 1. vendor 指纹 HAL 库 ==="
find /root/vnd -iname "*fingerprint*" -o -iname "*goodix*" -o -iname "*fpc*" 2>/dev/null | head -10
echo ""
echo "=== 2. 指纹 HAL 里的芯片标识 ==="
F=$(find /root/vnd -name "vendor.qti.hardware.fingerprint@1.0.so" 2>/dev/null | head -1)
echo "  $F"
[ -n "$F" ] && strings -a "$F" 2>/dev/null | grep -iE "goodix|fpc|27c6|uff|chip|vendor_id|product" | head -12
echo ""
echo "=== 3. odm 分区的指纹固件/配置 ==="
mountpoint -q /root/odm || mount -t erofs -o ro $B/odm.img /root/odm 2>/dev/null
find /root/odm -iname "*fp*" -o -iname "*finger*" -o -iname "*goodix*" 2>/dev/null | head -12
echo ""
echo "=== 4. 搜指纹固件文件 ==="
find /root/vnd /root/odm -iname "*.bin" 2>/dev/null | grep -iE "fp|finger|goodix|uff" | head -10
echo FP8