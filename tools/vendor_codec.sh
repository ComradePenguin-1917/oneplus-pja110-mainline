#!/bin/bash
cd /root/pja-work
echo "=== resolve asoc-codec phandles ==="
for ph in 4be 4c6 668 677; do
  L=$(grep -n "phandle = <0x$ph>" v.dts | head -1 | cut -d: -f1)
  if [ -n "$L" ]; then
    echo "--- 0x$ph (line $L)"
    sed -n "$((L-14)),${L}p" v.dts | grep -E "compatible|reg =|status" | head -3
  fi
done
echo ""
echo "=== lpass-cdc node (lpass_cdc / va_macro / rx_macro / tx_macro) ==="
grep -n "qcom,lpass-cdc\|lpass_cdc" v.dts | head -5