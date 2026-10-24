#!/bin/bash
cd /root/pja-work
echo "=== node 0x668 (wsa884x_2) full context ==="
L=$(grep -n "phandle = <0x668>" v.dts | head -1 | cut -d: -f1)
sed -n "$((L-18)),$((L+4))p" v.dts | grep -vE "^\s*$"
echo ""
echo "=== wcd938x_codec node search ==="
grep -n "wcd938x_codec\|wcd938x-codec" v.dts | head -8
echo ""
echo "=== lpass-cdc version 7 = which SoC generation? ==="
sed -n "26985,27020p" v.dts | grep -vE "^\s*$" | head -20