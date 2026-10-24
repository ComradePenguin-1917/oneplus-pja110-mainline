#!/bin/bash
B=/mnt/h/workspace/PJA110-Mainline/out/payload_extract
mountpoint -q /root/odm || mount -t erofs -o ro $B/odm.img /root/odm 2>/dev/null
echo "=== 1. fingerprint.json ==="
cat /root/odm/etc/fingerprint.json 2>/dev/null | head -40
echo ""
echo "=== 2. libIfp.so 里的芯片标识 ==="
for f in /root/odm/firmware/tp/22851/libIfp.so /root/odm/firmware/tp/23801/libIfp.so; do
  echo "--- $f ($(stat -c%s $f 2>/dev/null) B) ---"
  strings -a "$f" 2>/dev/null | grep -iE "27c6|goodix|fpc|egis|silead|jiiov|chip|sensor|vendor" | head -8
done
echo ""
echo "=== 3. 指纹服务里的芯片线索 ==="
strings -a /root/odm/bin/hw/vendor.oplus.hardware.biometrics.fingerprint@2.1-service_uff 2>/dev/null | grep -iE "27c6|goodix|fpc|egis|jiiov|silead|chip" | head -10
echo FP9