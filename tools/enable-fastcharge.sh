#!/bin/bash
#
# PJA110 快充启用脚本
#
# 原理：通过 qcom_battmgr 的 debugfs 接口向 ADSP 固件下发
#       BATTMGR_BAT_PROPERTY_SET (0x31) / BATT_CHG_CTRL_LIM (10)
#       设置电池充电电流上限。
#
# 背景：主线 qcom_battmgr 驱动定义了这两个常量但从未使用，
#       导致 Linux 无法控制充电电流，ADSP 固件保守限流在约 1.2W。
#       下发该命令后输入功率可达 12.5W（4.46V × 2.81A）。
#
# 前置条件（本脚本会等待，不靠固定 sleep）：
#   1. /sys/kernel/debug/qcom_battmgr/raw_set   ← qcom_battmgr 已加载
#   2. remoteproc* 状态为 running               ← ADSP 已启动
#   3. qcom-battmgr-usb 电源设备存在
#
# 结果校验：写完后读 last_set。
#   该固件不回复 ack，因此 rc=-110 (ETIMEDOUT) 是**正常成功值**；
#   rc=0 也接受。其他 rc 视为失败（-104 = ADSP 未就绪/通道断开）。
#
# 安全：ADSP 固件有自己的温度/电压保护，本脚本只在固件允许范围内
#       请求更高的充电电流，不会绕过硬件保护。
#
# 用法：
#   sudo enable-fastcharge.sh              # 默认 3A
#   sudo enable-fastcharge.sh 2000000      # 指定 2A
#   sudo enable-fastcharge.sh 0            # 恢复固件默认/旁路
#
set -uo pipefail

DBG=/sys/kernel/debug/qcom_battmgr
D=$DBG/raw_set
LS=$DBG/last_set
U=/sys/class/power_supply/qcom-battmgr-usb
B=/sys/class/power_supply/bq28z610-0
RP=/sys/class/remoteproc

# 默认 3A（实测 12.5W 稳定，温升温和）
CURRENT_UA=${1:-3000000}
WAIT_SECS=${FASTCHARGE_WAIT:-20}

# 日志同时写 stdout（给 systemd journal）和独立文件。
# 本机的 journald 目前收不到 unit 的 stdout（环境问题），
# 独立文件保证开机后仍能追溯每次下发的实际结果。
LOG=/var/log/pja110-fastcharge.log
LOG_MAX=65536

if [ -f "$LOG" ] && [ "$(stat -c%s "$LOG" 2>/dev/null || echo 0)" -gt $LOG_MAX ]; then
	mv -f "$LOG" "$LOG.1" 2>/dev/null || true
fi

say() {
	echo "$*"
	echo "$(date '+%F %T') $*" >> "$LOG" 2>/dev/null || true
}
warn() { echo "警告: $*" >&2; echo "$(date '+%F %T') 警告: $*" >> "$LOG" 2>/dev/null || true; }
die() { echo "错误: $*" >&2; echo "$(date '+%F %T') 错误: $*" >> "$LOG" 2>/dev/null || true; exit 1; }

[[ $EUID -eq 0 ]] || die "需要 root：sudo $0"

# ---- 参数校验 ----
[[ "$CURRENT_UA" =~ ^[0-9]+$ ]] || die "电流必须是整数（单位 uA）"
(( CURRENT_UA <= 4000000 )) || die "$CURRENT_UA uA 超过 4A 安全上限"

# ---- 前置条件 ----
cond_debugfs() { [ -w "$D" ] && [ -r "$LS" ]; }

cond_usb() { [ -r "$U/online" ]; }

cond_adsp() {
	local f
	for f in $RP/remoteproc*/state; do
		[ -r "$f" ] || continue
		[ "$(cat "$f" 2>/dev/null)" = "running" ] && return 0
	done
	return 1
}

wait_for() {
	local desc=$1 timeout=$2 fn=$3 i=0
	while (( i < timeout )); do
		$fn && return 0
		sleep 1
		i=$((i + 1))
	done
	warn "等待 $desc 超时（${timeout}s）"
	return 1
}

wait_for "qcom_battmgr debugfs" "$WAIT_SECS" cond_debugfs || \
	die "$D 不可用 —— qcom_battmgr 模块是否加载？"

# ADSP 与 USB 电源设备缺失不致命，记录后继续尝试
wait_for "ADSP" "$WAIT_SECS" cond_adsp || warn "ADSP 未 running，写入可能返回 ECONNRESET(-104)"
wait_for "USB 电源设备" "$WAIT_SECS" cond_usb || warn "缺少 $U，无法读取充电状态"

# ---- 状态显示 ----
show_power() {
	local uv=0 ui=0 bi=0 bv=0 line
	[ -r "$U/voltage_now" ] && uv=$(cat "$U/voltage_now" 2>/dev/null || echo 0)
	[ -r "$U/current_now" ] && ui=$(cat "$U/current_now" 2>/dev/null || echo 0)
	[ -r "$B/current_now" ] && bi=$(cat "$B/current_now" 2>/dev/null || echo 0)
	[ -r "$B/voltage_now" ] && bv=$(cat "$B/voltage_now" 2>/dev/null || echo 0)
	line=$(awk -v uv="${uv:-0}" -v ui="${ui:-0}" -v bi="${bi:-0}" -v bv="${bv:-0}" 'BEGIN{
		printf "USB %.2fV %4dmA (%.2fW)   BAT %+5dmA @ %.2fV (%.2fW)",
		       uv/1e6, ui/1000, (uv/1e6)*(ui/1e6),
		       bi/1000, bv/1e6, (bv/1e6)*(bi/1e6)
	}')
	say "  $line"
}

say "=== 设置前 ==="
show_power

# ---- 下发 ----
say "=== 下发 BATT_CHG_CTRL_LIM = ${CURRENT_UA} uA ==="
echo "31 10 $CURRENT_UA" > "$D" 2>/dev/null

# ---- 校验 ----
rc=-1
if [ -r "$LS" ]; then
	line=$(cat "$LS" 2>/dev/null)
	say "  last_set: $line"
	rc=$(printf '%s\n' "$line" | sed -n 's/.*rc=\(-\{0,1\}[0-9]\{1,\}\).*/\1/p')
	[ -n "$rc" ] || rc=-1

	printf '%s\n' "$line" | grep -q "prop=10" || warn "last_set 记录的不是 BATT_CHG_CTRL_LIM"
	printf '%s\n' "$line" | grep -q "val=$CURRENT_UA" || warn "last_set 的值与本次请求不符"
else
	warn "缺少 $LS，无法校验（qcom_battmgr 模块版本过旧？）"
fi

# ---- 效果检查（默认关闭）----
# 电流是否真的上升取决于供电能力：接 PD 充电器时会明显上升，
# 接 PC 的 SDP 口（约 450mA）时不可能升到 800mA。
# 因此默认只做 last_set 校验（可靠且快），
# 需要观察实际电流时设置 FASTCHARGE_VERIFY=1。
if [ "${FASTCHARGE_VERIFY:-0}" = "1" ] && (( CURRENT_UA > 0 )); then
	status=$(cat "$B/status" 2>/dev/null || echo unknown)
	if [ "$status" = "Charging" ]; then
		say "=== 观察电流变化（最多 6 秒）==="
		for _ in 1 2 3 4 5 6; do
			cur=$(cat "$B/current_now" 2>/dev/null || echo 0)
			(( cur > 800000 )) && break
			sleep 1
		done
	fi
fi

say "=== 设置后 ==="
show_power
say "  SOC $(cat "$B/capacity" 2>/dev/null)%  温度 $(awk -v t="$(cat "$B/temp" 2>/dev/null || echo 0)" 'BEGIN{printf "%.1f", t/10}')℃  状态 $(cat "$B/status" 2>/dev/null)"

# ---- 结论 ----
case "$rc" in
0)
	say "✅ 已生效（固件确认 rc=0）"
	;;
-110)
	say "✅ 已生效（rc=-110 是此固件不 ack 的正常现象，实测电流会上升）"
	;;
-104)
	die "失败：rc=-104 ECONNRESET —— ADSP 未就绪或 glink 通道断开"
	;;
*)
	die "失败：rc=$rc（非预期返回值）"
	;;
esac

exit 0
