#!/bin/bash
#
# PJA110 快充协议只读观测工具（阶段 A）
#
# 纯只读，不写任何寄存器、不改任何 sysfs。用于采集一次连接前后的完整快照，
# 建立"请求值 - 协商值 - 实际输入 - 电池净电流"的对照表。
#
# 用法：
#   sudo bash observe-charger.sh            # 打印当前快照
#   sudo bash observe-charger.sh --watch    # 每 3 秒刷新，插拔线时观察变化
#   sudo bash observe-charger.sh --save     # 保存快照到 /root/charger-logs/
#
# 参考：docs/fastcharge-status.md、docs/fast-charge-high-refresh-assessment.md
#
set -uo pipefail

WATCH=0
SAVE=0
for a in "$@"; do
  case "$a" in
    --watch) WATCH=1 ;;
    --save)  SAVE=1 ;;
  esac
done

[[ $EUID -eq 0 ]] || { echo "需要 root：sudo bash $0" >&2; exit 1; }

rd() { cat "$1" 2>/dev/null || echo "n/a"; }

snapshot() {
  local ts; ts=$(date '+%Y-%m-%d %H:%M:%S')

  echo "==================== $ts ===================="

  # ---------- 电池（真实状态）----------
  local B=/sys/class/power_supply/bq28z610-0
  local v i t c st
  v=$(rd $B/voltage_now); i=$(rd $B/current_now)
  t=$(rd $B/temp);        c=$(rd $B/capacity); st=$(rd $B/status)

  # 统一单位：V / mA / ℃
  awk -v v="$v" -v i="$i" -v t="$t" -v c="$c" -v st="$st" 'BEGIN{
    printf "BATTERY   %s  %.2fV  %+dmA  %.1f℃  %s%%\n",
           st, v/1e6, (i>=0? i/1000 : i/1000), t/10, c
  }'

  # ---------- 充电功率（电池侧实测，最可信）----------
  awk -v v="$v" -v i="$i" 'BEGIN{
    printf "PWR-BAT   %.2fW  (%.2fV x %+dmA)\n", (v/1e6)*(i/1000)/1000, v/1e6, i/1000
  }'

  # ---------- USB 输入侧 ----------
  local U=/sys/class/power_supply/qcom-battmgr-usb
  local uv ui umax utype ulim umaxv
  uv=$(rd $U/voltage_now); ui=$(rd $U/current_now)
  umax=$(rd $U/current_max); utype=$(rd $U/usb_type)
  ulim=$(rd $U/input_current_limit); umaxv=$(rd $U/voltage_max)
  awk -v v="$uv" -v i="$ui" -v m="$umax" -v t="$utype" -v l="$ulim" -v mv="$umaxv" 'BEGIN{
    printf "USB-IN    %.2fV  %dmA  (max %dmA, vmax %.1fV)\n", v/1e6, i/1000, m/1000, mv/1e6
    printf "USB-TYPE  %s\n", t
    printf "IN-LIMIT  %.2fA\n", l/1e6
  }'

  # ---------- UCSI source（PD 能力/合同）----------
  local S; S=$(ls -d /sys/class/power_supply/ucsi-source-psy-* 2>/dev/null | head -1)
  if [[ -n "$S" ]]; then
    echo "UCSI      type=$(rd $S/usb_type)  v=$(rd $S/voltage_now)  i_max=$(rd $S/current_max)  v_max=$(rd $S/voltage_max)"
    # PDO 列表（如果内核暴露）
    for pdo in $S/*pdo* $S/*Pdo*; do
      [[ -f "$pdo" ]] && echo "  $(basename $pdo) = $(cat $pdo 2>/dev/null)"
    done
  fi

  # ---------- Type-C ----------
  local T=/sys/class/typec/port0
  echo "TYPEC     data_role=[$(rd $T/data_role)]  power_role=[$(rd $T/power_role)]"
  echo "          opmode=$(rd $T/power_operation_mode)  pd_rev=$(rd $T/usb_power_delivery_revision)"

  # partner 是否存在（PD 合同的关键证据）
  if [[ -d /sys/class/typec/port0-partner ]]; then
    echo "PARTNER   pd_rev=$(rd /sys/class/typec/port0-partner/usb_power_delivery_revision)"
    for f in /sys/class/typec/port0-partner/*id* /sys/class/typec/port0-partner/*pd*; do
      [[ -f "$f" ]] && echo "          $(basename $f) = $(cat "$f" 2>/dev/null)"
    done
  else
    echo "PARTNER   (无 partner，未识别到对端)"
  fi

  # ---------- 充电驱动/服务状态 ----------
  echo "MODULES   battmgr=$(lsmod 2>/dev/null | grep -c qcom_battmgr)  charger=$(lsmod 2>/dev/null | grep -c charger)"

  # ---------- 内核异常（每次快照记录增量）----------
  local errs; errs=$(dmesg 2>/dev/null | grep -icE "charger|battmgr|typec|ucsi|pd[^a-z]")
  echo "DMESG     charger相关行数=$errs"

  echo ""
}

if [[ $WATCH -eq 1 ]]; then
  echo "每 3 秒刷新，Ctrl-C 退出。现在可以插拔充电器观察变化。"
  echo ""
  while true; do
    clear 2>/dev/null || true
    snapshot
    sleep 3
  done
else
  out=$(snapshot)
  echo "$out"
  if [[ $SAVE -eq 1 ]]; then
    mkdir -p /root/charger-logs
    f=/root/charger-logs/snapshot-$(date +%Y%m%d-%H%M%S).txt
    echo "$out" > "$f"
    echo "已保存: $f"
  fi
fi
