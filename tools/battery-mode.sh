#!/bin/bash
#
# PJA110 服务器模式：电池保护配置
#
# 适用于长期插电运行的场景（如迷你服务器）。
# 目的：避免电池长期处于 100% 满电浮充状态，延长电池寿命。
#
# 原理：通过 qcom_battmgr debugfs 设置 BATT_CHG_CTRL_LIM 限制充电电流。
#       设为 0 时电池既不充也不放，系统完全由 USB 供电（旁路模式）。
#
# 三种模式：
#   bypass   完全旁路，电池不参与（最保护电池，但断电无缓冲）
#   balanced 充到设定上限后转旁路（推荐，兼顾保护与缓冲）
#   full     正常充满（默认，适合会带出门的场景）
#
# 用法：
#   sudo bash battery-mode.sh bypass
#   sudo bash battery-mode.sh balanced [上限百分比]
#   sudo bash battery-mode.sh full
#   sudo bash battery-mode.sh status
#
set -uo pipefail

D=/sys/kernel/debug/qcom_battmgr/raw_set
B=/sys/class/power_supply/bq28z610-0
U=/sys/class/power_supply/qcom-battmgr-usb
STATE=/run/battery-mode.state

# 充电电流档位（uA）
CUR_FAST=3000000     # 3A 快充
CUR_TRICKLE=300000   # 300mA 涓流维持
CUR_OFF=0            # 关闭充电

[[ $EUID -eq 0 ]] || { echo "需要 root：sudo bash $0" >&2; exit 1; }

set_limit() {
    if [[ ! -w "$D" ]]; then
        echo "错误：$D 不可用" >&2
        return 1
    fi
    # 0x31 = BATTMGR_BAT_PROPERTY_SET, 10 = BATT_CHG_CTRL_LIM
    echo "31 10 $1" > "$D" 2>/dev/null
    return 0
}

show() {
    local cap bi ui st t
    cap=$(cat $B/capacity); bi=$(cat $B/current_now)
    ui=$(cat $U/current_now); st=$(cat $B/status); t=$(cat $B/temp)
    awk -v c="$cap" -v b="$bi" -v u="$ui" -v s="$st" -v t="$t" 'BEGIN{
        printf "  SOC %s%% | BAT %+dmA %-12s | USB %dmA | %.1f℃\n",
               c, b/1000, s, u/1000, t/10
    }'
}

MODE=${1:-status}
CAP_LIMIT=${2:-80}

case "$MODE" in
  bypass)
    echo "=== 旁路模式：电池不参与充放电 ==="
    set_limit $CUR_OFF
    echo "bypass" > "$STATE"
    sleep 3
    show
    echo "  说明：系统完全由 USB 供电，电池零负担"
    echo "        缺点：突然断电时无缓冲，建议配 UPS"
    ;;

  balanced)
    echo "=== 均衡模式：充到 ${CAP_LIMIT}% 后转旁路 ==="
    cap=$(cat $B/capacity)
    if [[ "$cap" -lt "$CAP_LIMIT" ]]; then
        echo "  当前 $cap% < $CAP_LIMIT%，先快充"
        set_limit $CUR_FAST
        echo "balanced:$CAP_LIMIT" > "$STATE"
    else
        echo "  当前 $cap% >= $CAP_LIMIT%，转旁路"
        set_limit $CUR_OFF
        echo "balanced:$CAP_LIMIT" > "$STATE"
    fi
    sleep 3
    show
    echo "  说明：配合 battery-guard.timer 定期检查，达上限后自动转旁路"
    ;;

  full)
    echo "=== 满充模式：正常充电 ==="
    set_limit $CUR_FAST
    echo "full" > "$STATE"
    sleep 3
    show
    ;;

  status)
    echo "=== 当前状态 ==="
    show
    [[ -f "$STATE" ]] && echo "  模式: $(cat $STATE)" || echo "  模式: 未设置（默认满充）"
    echo "  input_current_limit: $(cat $U/input_current_limit 2>/dev/null || echo n/a)"
    ;;

  *)
    echo "用法: $0 {bypass|balanced [cap%]|full|status}" >&2
    exit 1
    ;;
esac
