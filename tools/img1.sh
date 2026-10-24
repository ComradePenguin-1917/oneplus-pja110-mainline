#!/bin/bash
echo "=== 1. 当前系统信息 ==="
echo "  rootfs 设备: $(findmnt -n -o SOURCE / )"
echo "  文件系统:   $(findmnt -n -o FSTYPE / )"
echo "  总容量:     $(df -h / | tail -1 | awk '{print $2}')"
echo "  已用:       $(df -h / | tail -1 | awk '{print $3}')"
echo "  可用:       $(df -h / | tail -1 | awk '{print $4}')"
echo ""
echo "=== 2. 内核与启动 ==="
uname -r
cat /proc/cmdline
echo ""
echo "=== 3. 分区布局 ==="
lsblk -o NAME,SIZE,FSTYPE,LABEL,MOUNTPOINT 2>/dev/null | head -25
echo ""
echo "=== 4. 已安装的关键包 ==="
for p in phosh phoc gnome-control-center openssh-server network-manager; do
  v=$(dpkg-query -W -f='${Version}' $p 2>/dev/null)
  [ -n "$v" ] && printf "  %-24s %s\n" "$p" "$v"
done
echo ""
echo "=== 5. 我们改过的模块 ==="
ls -l /lib/modules/$(uname -r)/kernel/drivers/power/supply/qcom_battmgr.ko 2>/dev/null
ls -l /lib/modules/$(uname -r)/kernel/drivers/input/misc/qcom_hv_haptics_probe.ko 2>/dev/null
ls -l /lib/modules/$(uname -r)/kernel/sound/soc/qcom/qdsp6/snd-q6apm.ko 2>/dev/null
echo ""
echo "=== 6. 关键服务 ==="
for s in fastcharge ssh NetworkManager battery-guard.timer; do
  printf "  %-20s %s / %s\n" "$s" "$(systemctl is-active $s 2>&1)" "$(systemctl is-enabled $s 2>&1)"
done
echo SYS