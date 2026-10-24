#!/bin/bash
echo "=== build_native_slot_image.py 功能概览 ==="
head -60 /mnt/h/workspace/PJA110-Mainline/tools/build_native_slot_image.py
echo ""
echo "=== 支持的命令行参数 ==="
grep -nE "add_argument|argparse" /mnt/h/workspace/PJA110-Mainline/tools/build_native_slot_image.py | head -20
echo IMG2