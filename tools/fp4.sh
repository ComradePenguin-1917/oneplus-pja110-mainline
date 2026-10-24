#!/bin/bash
T=/root/workspace/PJA110-Mainline/charger-native-a/linux-6.14
echo "=== 1. 主线有没有 oplus,fp_spi 驱动 ==="
grep -rn "oplus,fp_spi\|fp_spi" $T/drivers/ 2>/dev/null | head -5
echo "(空=没有)"
echo ""
echo "=== 2. 主线有指纹类驱动吗（通用）==="
ls $T/drivers/ | grep -iE "fingerprint|biometric" 
find $T/drivers -iname "*fingerprint*" -o -iname "*fp_*" 2>/dev/null | head -5
echo ""
echo "=== 3. 上游 Linux 有 oplus fp 驱动吗 ==="
grep -rn "oplus" $T/drivers/ 2>/dev/null | grep -v "\.o:" | head -5
echo ""
echo "=== 4. vendor 里的指纹驱动模块 ==="
B=/mnt/h/workspace/PJA110-Mainline/out/payload_extract
mountpoint -q /root/dlkm || mount -t ext4 -o ro,loop $B/vendor_dlkm.img /root/dlkm 2>/dev/null
ls /root/dlkm/lib/modules/ | grep -iE "fp_|fingerprint|goodix_fp|oplus_bsp_fp" | head
echo ""
echo "=== 5. vendor 分区指纹 HAL ==="
find /root/vnd -iname "*fingerprint*" 2>/dev/null | head -8
echo FP4