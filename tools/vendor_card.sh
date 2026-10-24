#!/bin/bash
cd /root/pja-work
echo "=== vendor snd-card FULL node (kalama-mtp-snd-card) ==="
L=$(grep -n "kalama-mtp-snd-card" v.dts | cut -d: -f1)
sed -n "$((L-30)),$((L+5))p" v.dts | grep -vE "^\s*$"