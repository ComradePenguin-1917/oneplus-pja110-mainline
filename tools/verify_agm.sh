#!/bin/bash
B=/mnt/h/workspace/PJA110-Mainline/out/payload_extract
mkdir -p /root/odm /root/vnd
mount -t erofs -o ro $B/odm.img /root/odm 2>/dev/null
mount -t erofs -o ro $B/vendor.img /root/vnd 2>/dev/null
echo "=== 全盘搜 tplg（odm+vendor）==="
find /root/odm /root/vnd -iname "*tplg*" 2>/dev/null | head
echo "(none above = 确实没有)"
echo ""
echo "=== AGM 库确认（AGM = 旧架构，动态建图，不用 tplg）==="
ls /root/vnd/lib64/ 2>/dev/null | grep -iE "^libagm|^libar" | head
echo ""
echo "=== GKV (graph key vector) 文件？==="
find /root/odm /root/vnd -iname "*.gkv" 2>/dev/null | head
echo ""
echo "=== AGM 库里的 tag/键值定义 ==="
strings -n 6 /root/vnd/lib64/libagm.so 2>/dev/null | grep -iE "^MDF|^GKV|tag_id|graph_key" | head -10