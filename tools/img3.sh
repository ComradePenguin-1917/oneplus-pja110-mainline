#!/bin/bash
echo "=== 1. sda14 是否 LVM / 加密 / 特殊布局 ==="
findmnt -n -o SOURCE,FSTYPE,OPTIONS /
echo ""
echo "=== 2. /etc/fstab ==="
cat /etc/fstab 2>/dev/null
echo ""
echo "=== 3. rootfs UUID ==="
blkid /dev/sda14 2>/dev/null
echo ""
echo "=== 4. 已安装包数量 ==="
dpkg-query -f '.\n' -W 2>/dev/null | wc -l
echo ""
echo "=== 5. 大目录占用（找出可裁剪项）==="
du -sh /usr /var /opt /home /root /tmp 2>/dev/null | sort -rh
echo ""
echo "=== 6. /var/cache/apt 大小（可清理）==="
du -sh /var/cache/apt/archives 2>/dev/null
echo ""
echo "=== 7. 我们新增的文件（需要保留）==="
ls -la /usr/local/bin/ 2>/dev/null | head -10
ls /etc/systemd/system/fastcharge.service 2>/dev/null
echo IMG3