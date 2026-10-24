#!/bin/bash
echo "=== fingerprint_dev 节点完整内容 ==="
sed -n '8230,8280p' /root/pja-work/v.dts
echo ""
echo "=== 全 DTB 搜指纹专用 compatible ==="
grep -oE '"[a-z0-9]+,[a-z0-9-]*(finger|fpc|gf|goodix|silead|chipone)[a-z0-9-]*"' /root/pja-work/v.dts 2>/dev/null | sort -u | head -15
echo ""
echo "=== 搜 fpc / fingerprint 相关节点名 ==="
grep -inE "^\s+(fpc|fingerprint|gf|goodix_fp|fp_)" /root/pja-work/v.dts 2>/dev/null | head -15
echo FP2