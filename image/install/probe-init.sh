#!/bin/busybox sh
#
# PJA110 最小测试 initramfs —— 只诊断，不碰任何分区
#
# 目的：区分「引导链坏了」还是「sda14 的 rootfs 坏了」。
# 行为：挂必要文件系统 → 往 /dev/console 打日志（屏幕上能看到）→ 永远 sleep。
# 绝不 switch_root、绝不写任何块设备。

set -u
BB=/bin/busybox

# 尽量把输出送到屏幕
exec >/dev/console 2>&1

echo ""
echo "############################################"
echo "#  PJA110 MINIMAL TEST INITRAMFS           #"
echo "#  只诊断，不挂 rootfs、不写任何分区        #"
echo "############################################"
echo "kernel : $($BB uname -r)"
echo "date   : $($BB date)"
echo ""

$BB mount -t proc  proc /proc 2>/dev/null && echo "[ok] /proc"
$BB mount -t sysfs sys  /sys  2>/dev/null && echo "[ok] /sys"
$BB mkdir -p /dev
$BB mount -t devtmpfs dev /dev 2>/dev/null && echo "[ok] /dev"

echo ""
echo "--- 块设备 ---"
$BB ls /dev/sd* 2>/dev/null | $BB head -20
echo ""
echo "--- UDC ---"
$BB ls /sys/class/udc 2>/dev/null || echo "(无 UDC)"
echo ""
echo "--- configfs ---"
if $BB mount -t configfs none /sys/kernel/config 2>/dev/null; then
    echo "[ok] configfs 已挂载"
    $BB mkdir -p /sys/kernel/config/usb_gadget/probe 2>/dev/null \
        && echo "[ok] 能创建 gadget 目录" \
        || echo "[fail] 不能创建 gadget 目录"
else
    echo "[fail] configfs 挂载失败"
fi

echo ""
echo "--- sda14 前 1KB 摘要（只读检查）---"
$BB dd if=/dev/sda14 bs=1024 count=1 2>/dev/null | $BB od -An -tx1 | $BB head -4
echo ""
echo "--- ext4 魔数（偏移 1080，期望 53ef）---"
$BB dd if=/dev/sda14 bs=1 skip=1080 count=2 2>/dev/null | $BB od -An -tx1

echo ""
echo "=== 诊断结束，进入永久 sleep（不会重启）==="
echo ""

while true; do
    $BB sleep 60
done
