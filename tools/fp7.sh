#!/bin/bash
echo "=== 1. 设备上是否有指纹相关节点 ==="
ls /dev/ | grep -iE "fp|finger|uff" || echo "(无)"
ls /sys/class/ | grep -iE "fp|finger" || echo "(无类)"
echo ""
echo "=== 2. 当前内核加载的指纹模块 ==="
lsmod | grep -iE "fp|finger|uff" || echo "(无)"
echo ""
echo "=== 3. DTB 指纹节点是否存在于运行内核 ==="
find /proc/device-tree -iname "*fingerprint*" 2>/dev/null | head
echo ""
echo "=== 4. SPI 总线上有什么 ==="
ls /sys/bus/spi/devices/ 2>/dev/null | head
echo ""
echo "=== 5. 指纹相关 GPIO 状态 ==="
echo "  gpio40 (IRQ), gpio42 (reset)"
cat /sys/kernel/debug/gpio 2>/dev/null | grep -iE "gpio-40|gpio-42|fp" | head -5
echo ""
echo "=== 6. libfprint 是否已装 ==="
dpkg -l 2>/dev/null | grep -iE "libfprint|fprintd" | head -3 || echo "(未安装)"
echo FP7