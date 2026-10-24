#!/bin/bash
#
# PJA110 面板刷新率切换（60 / 120 Hz）
#
# 原理：
#   面板驱动 panel-oneplus-aa536 有两个 DRM 模式（60Hz / 120Hz 时序完全不同，
#   像素时钟 248MHz vs 455MHz），并通过模块参数 refresh 指定面板初始化序列。
#   切换时需两步：
#     1. 写 /sys/module/panel_oneplus_aa536/parameters/refresh 选好初始化序列
#     2. 用 wlr-randr 触发 DRM modeset，让面板按新序列重新初始化
#   两步顺序不能颠倒，否则面板时序与 DRM 时序不匹配。
#
# 用法：
#   sudo PJA110-refresh.sh 60        切到 60Hz（省电）
#   sudo PJA110-refresh.sh 120       切到 120Hz（顺滑）
#   sudo PJA110-refresh.sh status    查看当前状态
#
set -uo pipefail

PARAM=/sys/module/panel_oneplus_aa536/parameters/refresh
CONNECTOR=DSI-1
MODE_BASE=1240x2772

die() { echo "错误: $*" >&2; exit 1; }

usage() {
	cat <<EOF
用法: $0 {60|120|status}

  60      切到 60Hz（省电）
  120     切到 120Hz（高刷）
  status  查看当前状态

注意：运行时切换不持久，重启后回到内核命令行指定的值
      （当前为 panel_oneplus_aa536.refresh=120）。
EOF
	exit 1
}

show_status() {
	local param actual
	param=$(cat "$PARAM" 2>/dev/null || echo "?")
	printf "  驱动参数:   %s Hz\n" "$param"

	actual=$(dmesg 2>/dev/null | grep -o "AA536 [0-9]* Hz initialization complete" | tail -1)
	[ -n "$actual" ] && printf "  面板初始化: %s\n" "$actual" || echo "  面板初始化: (无记录)"

	if command -v wlr-randr >/dev/null 2>&1; then
		local session
		session=$(_find_session)
		if [ -n "$session" ]; then
			printf "  当前模式:   %s\n" \
				$(echo "$session" | sed -n 's/.*\(1240x2772 px, [0-9.]* Hz\).*/\1/p' | head -1)
		fi
	fi
}

# 输出 phoc 会话的 "user|runtime_dir|wayland_display"
_find_session() {
	local wuser wuid sock
	wuser=$(ps -o user= -C phoc 2>/dev/null | head -1 | tr -d ' ')
	[ -z "$wuser" ] && return 1

	wuid=$(id -u "$wuser" 2>/dev/null) || return 1
	sock=$(ls /run/user/"$wuid"/wayland-* 2>/dev/null | grep -v '\.lock$' | head -1)
	[ -z "$sock" ] && return 1

	echo "$wuser|/run/user/$wuid|$(basename "$sock")"
}

[ $# -eq 1 ] || usage

case "$1" in
status)
	echo "=== PJA110 刷新率状态 ==="
	show_status
	exit 0
	;;
60|120) ;;
*) usage ;;
esac

RATE=$1

[ -e "$PARAM" ] || die "$PARAM 不存在（面板驱动未加载？）"
[ "$(id -u)" -eq 0 ] || die "需要 root：sudo $0 $RATE"
command -v wlr-randr >/dev/null 2>&1 || die "缺少 wlr-randr：apt install wlr-randr"

SESSION=$(_find_session) || die "未找到 phoc Wayland 会话（需要在图形界面运行时切换）"
WUSER=${SESSION%%|*}
REST=${SESSION#*|}
RUNTIME=${REST%%|*}
WDISPLAY=${REST##*|}

echo "=== 切换到 ${RATE}Hz ==="

# 第 1 步：选初始化序列
echo "$RATE" > "$PARAM" || die "写入 $PARAM 失败"
echo "  驱动参数已设为 $RATE"

# 第 2 步：触发 modeset
if ! runuser -u "$WUSER" -- env XDG_RUNTIME_DIR="$RUNTIME" WAYLAND_DISPLAY="$WDISPLAY" \
	wlr-randr --output "$CONNECTOR" --on --mode "${MODE_BASE}@${RATE}" >/dev/null; then
	die "wlr-randr 切换失败"
fi

sleep 1

ACTUAL=$(dmesg 2>/dev/null | grep -o "AA536 [0-9]* Hz initialization complete" | tail -1)
echo "  面板回报: ${ACTUAL:-（无）}"

case "$ACTUAL" in
*"$RATE Hz"*) echo "✅ 已切换到 ${RATE}Hz" ;;
*) echo "⚠️  面板初始化频率与目标不符，请检查 dmesg" >&2; exit 2 ;;
esac
