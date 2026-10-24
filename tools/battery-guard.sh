#!/bin/bash
#
# PJA110 电池保护守护（配合 battery-mode.sh balanced 使用）
#
# 每 5 分钟检查一次 SOC：
#   - 低于上限 5% 且不在充电 → 恢复快充
#   - 达到上限 → 转旁路（充电电流归零）
#
# 这样电池会长期维持在上限附近，既不充满也不深放，寿命最长。
#
set -uo pipefail

D=/sys/kernel/debug/qcom_battmgr/raw_set
B=/sys/class/power_supply/bq28z610-0
STATE=/run/battery-mode.state
CUR_FAST=3000000
CUR_OFF=0

[[ $EUID -eq 0 ]] || exit 1
[[ -f "$STATE" ]] || exit 0
[[ "$(cut -d: -f1 "$STATE")" == "balanced" ]] || exit 0

LIMIT=$(cut -d: -f2 "$STATE")
CAP=$(cat $B/capacity)
HYST=5

set_lim() { echo "31 10 $1" > "$D" 2>/dev/null; }

if [[ "$CAP" -ge "$LIMIT" ]]; then
    set_lim $CUR_OFF
    logger -t battery-guard "SOC $CAP% >= $LIMIT%, 转旁路"
elif [[ "$CAP" -lt $((LIMIT - HYST)) ]]; then
    set_lim $CUR_FAST
    logger -t battery-guard "SOC $CAP% < $((LIMIT - HYST))%, 恢复快充"
fi
