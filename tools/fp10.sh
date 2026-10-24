#!/bin/bash
F=/root/odm/firmware/tp/22851/libIfp.so
echo "=== 1. 导出函数（libIfp 接口）==="
NM=/opt/aarch64-linux-gnu-toolchain-13.3/bin/aarch64-none-linux-gnu-nm
$NM -D --defined-only $F 2>/dev/null | head -20
echo ""
echo "=== 2. 所有字符串（看协议）==="
strings -a $F 2>/dev/null | head -40
echo ""
echo "=== 3. 指纹服务 chip_type 相关 ==="
S=/root/odm/bin/hw/vendor.oplus.hardware.biometrics.fingerprint@2.1-service_uff
strings -a $S 2>/dev/null | grep -iE "chip_type|chip.*=|sensor.*=|vendor.*=|27c6|goodix|fpc" | head -20
echo ""
echo "=== 4. 指纹 HAL so 文件大小对比（判断是通用还是专用）==="
ls -l /root/odm/bin/hw/*fingerprint* 2>/dev/null
echo FP10