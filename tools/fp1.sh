#!/bin/bash
echo "=== 1. vendor DTB 里的指纹节点 ==="
grep -inE "fingerprint|fpc|goodix|gf_|finger" /root/pja-work/v.dts 2>/dev/null | head -20
echo ""
echo "=== 2. vendor_dlkm 里的指纹驱动 ==="
B=/mnt/h/workspace/PJA110-Mainline/out/payload_extract
mountpoint -q /root/dlkm || mount -t ext4 -o ro,loop $B/vendor_dlkm.img /root/dlkm 2>/dev/null
ls /root/dlkm/lib/modules/ 2>/dev/null | grep -iE "finger|fpc|goodix|gf" | head -10
echo ""
echo "=== 3. vendor 分区里的指纹 HAL ==="
mountpoint -q /root/vnd || mount -t erofs -o ro $B/vendor.img /root/vnd 2>/dev/null
ls /root/vnd/lib64/hw/ 2>/dev/null | grep -iE "finger|biometric" | head
find /root/vnd -iname "*fingerprint*" -o -iname "*fpc*" 2>/dev/null | head -10
echo FP1