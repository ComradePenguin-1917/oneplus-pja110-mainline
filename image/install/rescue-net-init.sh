#!/bin/busybox sh
#
# PJA110 救援 initramfs（带网络 shell，**不 switch_root**）
#
# 目的：设备现在启动即 panic 重启，控制台看不到东西。这个 initramfs
# 不交接给 rootfs，而是：
#   1. 建 USB NCM gadget（172.16.42.1 + 169.254.42.1）
#   2. 起 telnetd（23 端口 root shell）
#   3. 挂 /dev/sda6 以便读写工具与镜像
#   4. 原地等待（**永不退出**，所以不会 panic 循环）
#
# 然后从 PC 侧 `telnet 169.254.42.1 23` 进去诊断、修、手动 switch_root。

set -u
BB=/bin/busybox

$BB mount -t proc  proc /proc 2>/dev/null
$BB mount -t sysfs sys  /sys  2>/dev/null
$BB mkdir -p /dev
$BB mount -t devtmpfs dev /dev 2>/dev/null
$BB mkdir -p /dev/pts /tmp /src /newroot
$BB mount -t devpts devpts /dev/pts 2>/dev/null
$BB mount -t tmpfs tmpfs /tmp 2>/dev/null
$BB mount -t configfs none /sys/kernel/config 2>/dev/null

echo "=== PJA110 rescue initramfs ==="
echo "内核: $($BB uname -r)"

# ---------------------------------------------------------------- NCM gadget
G=/sys/kernel/config/usb_gadget/g1
if [ -d "$G" ]; then
    [ -s "$G/UDC" ] && echo "" > "$G/UDC" 2>/dev/null
    for l in "$G"/configs/*/*; do [ -L "$l" ] && $BB rm -f "$l"; done
    $BB rmdir "$G"/configs/c.1/strings/0x409 "$G"/configs/c.1 2>/dev/null
    $BB rmdir "$G"/functions/* "$G"/strings/0x409 "$G" 2>/dev/null
fi

if $BB mkdir -p "$G" 2>/dev/null; then
    echo 0x1d6b   > "$G/idVendor"
    echo 0x0104   > "$G/idProduct"
    echo 0x0100   > "$G/bcdDevice"
    echo 0x0200   > "$G/bcdUSB"
    $BB mkdir -p "$G/strings/0x409"
    echo pja110-rescue > "$G/strings/0x409/serialnumber"
    echo OnePlus        > "$G/strings/0x409/manufacturer"
    echo "PJA110 rescue" > "$G/strings/0x409/product"
    $BB mkdir -p "$G/configs/c.1/strings/0x409"
    echo ncm > "$G/configs/c.1/strings/0x409/configuration"
    echo 500 > "$G/configs/c.1/MaxPower"
    if $BB mkdir -p "$G/functions/ncm.usb0" 2>/dev/null; then
        $BB ln -sf "$G/functions/ncm.usb0" "$G/configs/c.1/" 2>/dev/null
        UDC=$($BB ls /sys/class/udc 2>/dev/null | $BB head -1)
        if [ -n "$UDC" ]; then
            echo "$UDC" > "$G/UDC" && echo "NCM: 已绑定 UDC=$UDC"
        else
            echo "NCM: 没有 UDC"
        fi
    else
        echo "NCM: 无法创建 ncm.usb0"
    fi
else
    echo "NCM: 无法创建 gadget（configfs 不可用？）"
fi

# ---------------------------------------------------------------- 网络地址
IF=""
i=0
while [ $i -lt 40 ]; do
    for n in /sys/class/net/usb*; do
        [ -e "$n" ] && { IF=$($BB basename "$n"); break; }
    done
    [ -n "$IF" ] && break
    i=$((i+1)); $BB sleep 0.5
done
[ -z "$IF" ] && IF=usb0
$BB ip link set "$IF" up 2>/dev/null
$BB ip addr add 172.16.42.1/24 dev "$IF" 2>/dev/null
$BB ip addr add 169.254.42.1/16 dev "$IF" 2>/dev/null
echo "网络: $IF -> $($BB ip -4 -o addr show "$IF" 2>/dev/null | $BB awk '{print $4}' | $BB tr '\n' ' ')"

# ---------------------------------------------------------------- telnetd
$BB mkdir -p /var/run /var/log
echo "启动 telnetd :23（root shell，仅救援期）"
$BB telnetd -p 23 -l /bin/sh 2>/dev/null && echo "Telnetd: OK" || echo "Telnetd: 启动失败"

# ---------------------------------------------------------------- 工具盘
if $BB mount -o rw,noatime /dev/sda6 /src 2>/dev/null; then
    echo "已挂载 /dev/sda6 -> /src"
    $BB ls /src 2>/dev/null | $BB head -10
else
    echo "挂载 /dev/sda6 失败"
fi

echo ""
echo "救援模式就绪。从 PC: telnet 169.254.42.1 23"
echo ""

# 永不退出，避免 PID1 消失导致 panic
while true; do
    $BB sleep 30
done
