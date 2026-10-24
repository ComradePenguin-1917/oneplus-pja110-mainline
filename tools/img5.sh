#!/bin/bash
echo "=== 找到 vendor_boot 分区 ==="
for p in /dev/sda*; do
  name=$(cat /sys/class/block/$(basename $p)/uevent 2>/dev/null | grep PARTNAME | cut -d= -f2)
  size=$(lsblk -b -n -o SIZE $p 2>/dev/null)
  [ -n "$name" ] && printf "  %-10s %-16s %s\n" "$(basename $p)" "$name" "$size"
done
echo ""
echo "=== fastboot 分区表 ==="
cat /proc/cmdline | tr ' ' '\n' | grep -iE "slot|partition" | head -5
echo ""
echo "=== 从 super 分区看（Android 动态分区）==="
lsblk -o NAME,SIZE,PARTLABEL /dev/sda | head -20
echo IMG5