#!/bin/bash
echo "=== 1. sda6 到底是什么 ==="
blkid /dev/sda6 2>/dev/null || echo "  (无 blkid 信息)"
echo ""
echo "  头部 magic:"
dd if=/dev/sda6 bs=1 count=64 2>/dev/null | od -An -c | head -3
echo ""
echo "  super 分区 magic (应为 0x534C4F54 'SLOT'):"
dd if=/dev/sda6 bs=1 skip=4096 count=4 2>/dev/null | od -An -tx1
echo ""
echo "=== 2. sda14 头部 ==="
dd if=/dev/sda14 bs=1 skip=1080 count=2 2>/dev/null | od -An -tx1
echo "  (53ef = ext4)"
echo ""
echo "=== 3. sda6 里的 ext4 超级块 ==="
dd if=/dev/sda6 bs=1 skip=1024 count=64 2>/dev/null | od -An -tx1 | head -2
echo ""
echo "=== 4. sda6 挂载测试（只读，不实际挂载）==="
echo "  尝试 dumpe2fs 探测:"
dumpe2fs -h /dev/sda6 2>&1 | head -8
echo ""
echo "=== 5. 结论判断 ==="
echo "  如果 sda6 是 ext4 且 UUID 与 sda14 相同 → super 已被覆盖，Android 已不存在"
echo SLOT2