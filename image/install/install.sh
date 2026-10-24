#!/bin/bash
# PJA110 交付镜像 —— 安装脚本（在 PC 上运行）
#
#   ./install.sh [--bundle DIR] [--yes]
#
# 做的事：
#   1. 校验 fastboot 设备与槽位（**槽位不是 a 就中止**）
#   2. 用 SHA256SUMS 校验交付包完整性
#   3. 依次刷入 boot_a / vendor_boot_a / dtbo_a / userdata
#   4. 复查槽位并给出后续步骤
#
# 安全设计：
#   * 只操作 A 槽，绝不碰 B 槽
#   * 刷 rootfs 前必须二次确认（会覆盖 userdata）
#   * 任一 sha256 不符即中止

set -u

BUNDLE="$(cd "$(dirname "$0")" && pwd)/bundle"
ASSUME_YES=0

while [ $# -gt 0 ]; do
    case "$1" in
        --bundle) BUNDLE="$2"; shift 2 ;;
        --yes|-y) ASSUME_YES=1; shift ;;
        -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
        *) echo "未知参数: $1"; exit 2 ;;
    esac
done

red()  { printf '\033[31m%s\033[0m\n' "$*"; }
grn()  { printf '\033[32m%s\033[0m\n' "$*"; }
ylw()  { printf '\033[33m%s\033[0m\n' "$*"; }
step() { printf '\n=== %s ===\n' "$*"; }
die()  { red "✗ $*"; exit 1; }

confirm() {
    [ "$ASSUME_YES" -eq 1 ] && return 0
    printf '%s [y/N] ' "$1"
    read -r a
    case "$a" in y|Y|yes|YES) return 0 ;; *) return 1 ;; esac
}

command -v fastboot >/dev/null 2>&1 || die "找不到 fastboot（请安装 android-tools / platform-tools）"

# ---------------------------------------------------------------- 1. 设备
step "1. 检查 fastboot 设备"
devs=$(fastboot devices 2>/dev/null | awk 'NF{print $1}')
[ -n "$devs" ] || die "没有检测到 fastboot 设备。请让手机进入 fastboot（关机后按住音量下 + 电源）"
echo "  设备: $devs"

# ---------------------------------------------------------------- 2. 槽位
step "2. 检查槽位（必须是 a）"
slot=$(fastboot getvar current-slot 2>&1 | awk -F': *' '/current-slot/{print $2}' | tr -d '\r')
echo "  current-slot: ${slot:-未知}"
if [ "$slot" != "a" ]; then
    red ""
    red "当前槽位是 '${slot:-未知}'，不是 'a'。"
    red "这通常意味着设备此前启动失败、bootloader 自动切到了 B 槽（B 槽没有系统）。"
    red ""
    red "请先执行：  fastboot --set-active=a"
    red "然后重新运行本脚本。"
    exit 1
fi
grn "  槽位正确"

# ---------------------------------------------------------------- 3. 校验
step "3. 校验交付包"
[ -f "$BUNDLE/SHA256SUMS" ] || die "找不到 $BUNDLE/SHA256SUMS"
for f in boot_a.img vendor_boot_a.img dtbo_a.img rootfs.img; do
    [ -f "$BUNDLE/$f" ] || die "缺少 $BUNDLE/$f"
done
( cd "$BUNDLE" && sha256sum -c SHA256SUMS ) || die "校验失败，交付包可能损坏"
grn "  校验通过"
echo ""
[ -f "$BUNDLE/MANIFEST.txt" ] && sed -n '1,8p' "$BUNDLE/MANIFEST.txt" | sed 's/^/  /'

# ---------------------------------------------------------------- 4. 确认
step "4. 刷写前确认"
cat <<EOF
即将刷入（只动 A 槽）：
  boot_a          ← $BUNDLE/boot_a.img          ($(ls -lh "$BUNDLE/boot_a.img" | awk '{print $5}'))
  vendor_boot_a   ← $BUNDLE/vendor_boot_a.img   ($(ls -lh "$BUNDLE/vendor_boot_a.img" | awk '{print $5}'))
  dtbo_a          ← $BUNDLE/dtbo_a.img          ($(ls -lh "$BUNDLE/dtbo_a.img" | awk '{print $5}'))
  userdata        ← $BUNDLE/rootfs.img          ($(ls -lh "$BUNDLE/rootfs.img" | awk '{print $5}'))

警告：刷 userdata 会**完全覆盖**手机上现有的根文件系统（包含所有数据）。
      sda6（/srv，15 GB 辅助卷）不在此次刷写范围内，但会保留旧内容。
EOF
confirm "确认继续？" || die "用户取消"

# ---------------------------------------------------------------- 5. 刷写
step "5. 刷写"
fastboot flash boot_a        "$BUNDLE/boot_a.img"        || die "boot_a 刷写失败"
fastboot flash vendor_boot_a "$BUNDLE/vendor_boot_a.img" || die "vendor_boot_a 刷写失败"
fastboot flash dtbo_a        "$BUNDLE/dtbo_a.img"        || die "dtbo_a 刷写失败"

ylw ""
ylw "  接下来刷 rootfs（约 8 GiB，视 USB 速率需要数分钟）…"
ylw ""
fastboot flash userdata      "$BUNDLE/rootfs.img"        || die "userdata 刷写失败"

# ---------------------------------------------------------------- 6. 复查
step "6. 刷写后复查槽位"
slot2=$(fastboot getvar current-slot 2>&1 | awk -F': *' '/current-slot/{print $2}' | tr -d '\r')
echo "  current-slot: ${slot2:-未知}"
[ "$slot2" = "a" ] && grn "  槽位仍是 a" || ylw "  ⚠️ 槽位变成 ${slot2}！请执行 fastboot --set-active=a"

# ---------------------------------------------------------------- 7. 重启
step "7. 重启"
fastboot reboot || die "重启命令失败"
cat <<EOF

$(grn "刷写完成，设备正在重启。")

首次启动会自动完成以下事项（无需人工干预）：
  · 重新生成 machine-id 与 SSH 主机密钥
  · 把根文件系统扩展到整个 userdata 分区（2.2 GiB → 450 GiB，约 1 分钟）
  · 校正时区与 hostname 一致性

随后会弹出一次「Device name」向导，让你给设备起名。

默认账号：
  user:      ubuntu
  password:  123456
（可在 设置 → 用户 里改密码；Wi-Fi 在 设置 → Wi-Fi 里配置）

验证清单见同目录 ACCEPTANCE.md。
EOF
