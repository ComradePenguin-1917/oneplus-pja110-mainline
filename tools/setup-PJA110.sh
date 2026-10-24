#!/bin/bash
#
# PJA110 Ubuntu 24.04 系统配置固化脚本
#
# 用途：把已经验证过的所有系统层改动固化为可重放脚本。
# 场景：重装 rootfs、恢复出厂、或迁移到 B 槽时，执行本脚本恢复全部配置。
#
# 用法： sudo bash setup-PJA110.sh [--skip-wifi]
#
# 前置条件：
#   - 已启动到 Ubuntu 24.04（kernel 6.14.0-oneplus-xigua）
#   - 有网络（Wi-Fi 或 USB NCM）
#
set -euo pipefail

RED='\033[0;31m'; GRN='\033[0;32m'; YEL='\033[1;33m'; NC='\033[0m'
info() { echo -e "${GRN}[INFO]${NC} $*"; }
warn() { echo -e "${YEL}[WARN]${NC} $*"; }
err()  { echo -e "${RED}[ERR ]${NC} $*" >&2; }

SKIP_WIFI=0
[[ "${1:-}" == "--skip-wifi" ]] && SKIP_WIFI=1

[[ $EUID -eq 0 ]] || { err "需要 root 权限：sudo bash $0"; exit 1; }

# =====================================================================
info "1/8  修正系统时间（RTC 无电池，必须靠 NTP）"
# =====================================================================
export DEBIAN_FRONTEND=noninteractive
apt-get install -y systemd-timesyncd >/dev/null 2>&1 || warn "timesyncd 安装失败"
# 校园网可能屏蔽境外 NTP，用国内源
cat > /etc/systemd/timesyncd.conf <<'EOF'
[Time]
NTP=ntp.aliyun.com time1.cloud.tencent.com
FallbackNTP=ntp.ubuntu.com
EOF
systemctl enable --now systemd-timesyncd >/dev/null 2>&1
systemctl restart systemd-timesyncd || true
sleep 2
info "   时间：$(date)"
timedatectl show -p NTPSynchronized --value | grep -q yes \
  && info "   NTP 已同步" || warn "   NTP 未同步（检查网络）"

# =====================================================================
info "2/8  账户与权限"
# =====================================================================
# penguin 加入 sudo 组（否则无法提权）
usermod -aG sudo penguin 2>/dev/null || true
# 免密 sudo（方便自动化；如不需要可删除此文件）
cat > /etc/sudoers.d/90-penguin-nopasswd <<'EOF'
penguin ALL=(ALL) NOPASSWD:ALL
EOF
chmod 440 /etc/sudoers.d/90-penguin-nopasswd
visudo -c -f /etc/sudoers.d/90-penguin-nopasswd >/dev/null && info "   sudoers 语法正确"
info "   penguin 组：$(groups penguin)"

# =====================================================================
info "3/8  SSH 服务（重要：USB OTG 实验的安全网）"
# =====================================================================
apt-get install -y openssh-server >/dev/null 2>&1
systemctl enable --now ssh >/dev/null 2>&1
info "   ssh: $(systemctl is-active ssh) / $(systemctl is-enabled ssh)"

# =====================================================================
info "4/8  屏幕缩放（1240x2772 必须 scale=2，否则 UI 显示不下）"
# =====================================================================
PHOC_INI=/usr/share/phosh/phoc.ini
if [[ -f "$PHOC_INI" ]]; then
  cp -n "$PHOC_INI" "$PHOC_INI.orig" 2>/dev/null || true
  python3 - "$PHOC_INI" <<'PY'
import sys, re
p = sys.argv[1]
s = open(p).read()
# 取消 DSI-1 段的注释并设为 scale=2
if '[output:DSI-1]' not in s or 'scale' not in s.split('[output:DSI-1]')[1].split('[')[0]:
    s = re.sub(r'#\[output:DSI-1\]\s*\n#scale\s*=\s*\d+',
               '[output:DSI-1]\nscale = 2', s)
open(p, 'w').write(s)
PY
  info "   phoc.ini DSI-1 段："
  sed -n '/\[output:DSI-1\]/,/^\[/p' "$PHOC_INI" | head -4 | sed 's/^/      /'
  warn "   需重启 phoc/phosh 或重启设备才生效"
else
  warn "   phoc.ini 不存在（phosh 未安装？）"
fi

# =====================================================================
info "5/8  Wi-Fi 固件修复（board-2.bin 缺失导致断流）"
# =====================================================================
# 症状：dmesg 刷 "HTC Rx: insufficient length" / "wmi tlv parse failure"，
#       wlp1s0 DOWN、扫描不到 AP。
# 根因：board-2.bin 只有 .zst 未解压 → 驱动回退到 board.bin，
#       而该文件是 ARM ELF 可执行文件（非射频数据）→ 射频参数错乱。
# 详见 docs/wifi-instability-fix-20261023.md
FW=/lib/firmware/ath12k/WCN7850/hw2.0
if [[ -d "$FW" ]]; then
  # 解压 board-2.bin（驱动首选，带 QCA-ATH12K-BOARD magic）
  if [[ -f "$FW/board-2.bin.zst" && ! -f "$FW/board-2.bin" ]]; then
    zstd -d "$FW/board-2.bin.zst" -o "$FW/board-2.bin" -f >/dev/null 2>&1 \
      && info "   board-2.bin 已解压（$(stat -c%s "$FW/board-2.bin") B）" \
      || warn "   board-2.bin 解压失败"
  fi

  # 检查 board.bin 是否是合法板级数据（magic = QCA-ATH12K-BOARD）
  if [[ -f "$FW/board.bin" ]]; then
    if head -c4 "$FW/board.bin" | grep -q "QCA-"; then
      info "   board.bin magic 正常"
    else
      mkdir -p /root/wifi-fw-backup
      mv "$FW/board.bin" "$FW/board.bin.wrong-elf" 2>/dev/null && \
        cp "$FW/board.bin.wrong-elf" /root/wifi-fw-backup/board.bin.elf 2>/dev/null
      warn "   board.bin 非法（非板级数据），已改名为 board.bin.wrong-elf"
    fi
  fi

  # 验证最终状态
  if [[ -f "$FW/board-2.bin" ]]; then
    info "   最终: board-2.bin 就绪（驱动将走 API2 路径）"
  else
    warn "   board-2.bin 仍缺失，Wi-Fi 可能不稳定！"
  fi
else
  warn "   $FW 不存在（ath12k 固件未安装？）"
fi

# =====================================================================
info "6/8  Wi-Fi 管理（NetworkManager 独占，避免 networkd 冲突）"
# =====================================================================
if [[ $SKIP_WIFI -eq 0 ]]; then
  # 移除 networkd 对无线网卡的管理，让 NM 独占
  if [[ -f /etc/systemd/network/25-wlp1s0.network ]]; then
    mkdir -p /root/wifi-backup
    cp /etc/systemd/network/25-wlp1s0.network /root/wifi-backup/ 2>/dev/null || true
    cp /etc/wpa_supplicant/wpa_supplicant.conf /root/wifi-backup/ 2>/dev/null || true
    rm -f /etc/systemd/network/25-wlp1s0.network
    info "   已移除 networkd 的 wlp1s0 配置（备份在 /root/wifi-backup/）"
  fi

  # NM 配置：usb0 保持 unmanaged（调试通道不受干扰）
  cat > /etc/NetworkManager/conf.d/10-manage-wifi.conf <<'EOF'
[keyfile]
unmanaged-devices=interface-name:usb0
[device]
wifi.scan-rand-mac-address=no
EOF

  systemctl restart systemd-networkd 2>/dev/null || true
  systemctl reload-or-restart NetworkManager 2>/dev/null || true
  sleep 3
  info "   NM 设备状态："
  nmcli -t -f DEVICE,STATE,CONNECTION device 2>/dev/null | grep -E "wlp|usb0" | sed 's/^/      /' || true

  # 提示：Wi-Fi 连接需手动配置（SSID/密码/认证方式各不相同）
  cat <<'EOF'

   Wi-Fi 连接配置示例（需按实际情况替换）：

   # 普通 WPA2 家庭网络
   nmcli connection add type wifi con-name "MyWiFi" ifname wlp1s0 \
     ssid "MyWiFi" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "密码" \
     connection.autoconnect yes

   # 隐藏 SSID
   nmcli connection add type wifi con-name "Hidden" ifname wlp1s0 \
     ssid "Hidden" wifi-sec.key-mgmt wpa-psk wifi-sec.psk "密码" \
     802-11-wireless.hidden yes connection.autoconnect yes

   # 企业认证 802.1X（校园网，如 HKUSTGZ / eduroam）
   nmcli connection add type wifi con-name "HKUSTGZ" ifname wlp1s0 \
     ssid "HKUSTGZ" wifi-sec.key-mgmt wpa-eap 802-1x.eap peap \
     802-1x.phase2-auth mschapv2 802-1x.identity "用户名" \
     802-1x.password "密码" connection.autoconnect yes

   图形界面：应用列表 → Settings（gnome-control-center）→ Wi-Fi
EOF
else
  info "   跳过 Wi-Fi 配置（--skip-wifi）"
fi

# =====================================================================
info "7/8  音频与调试工具"
# =====================================================================
apt-get install -y alsa-utils alsa-ucm-conf iw wpasupplicant rfkill >/dev/null 2>&1 || true
info "   alsa-utils: $(dpkg-query -W -f='${Version}' alsa-utils 2>/dev/null || echo 未装)"
info "   iw:         $(dpkg-query -W -f='${Version}' iw 2>/dev/null || echo 未装)"

# =====================================================================
info "8/8  GUI 设置工具（连接 Wi-Fi 用）"
# =====================================================================
apt-get install -y --no-install-recommends \
  phosh-mobile-settings gnome-control-center >/dev/null 2>&1 || warn "GUI 设置安装失败"
for p in phosh-mobile-settings gnome-control-center; do
  w=$(command -v $p 2>/dev/null || true)
  info "   $p: ${w:-未安装}"
done

# =====================================================================
echo
info "======== 配置完成 ========"
echo
echo "验证清单："
echo "  时间:     $(date)"
echo "  NTP:      $(timedatectl show -p NTPSynchronized --value)"
echo "  SSH:      $(systemctl is-active ssh) (port 22)"
echo "  NM:       $(systemctl is-active NetworkManager)"
echo "  Wi-Fi:    $(nmcli -t -f STATE general 2>/dev/null || echo n/a)"
echo "  缩放:     $(grep -A1 'output:DSI-1' /usr/share/phosh/phoc.ini 2>/dev/null | tail -1 | tr -d ' ') (需重启生效)"
echo
echo "调试通道："
ip -br addr show 2>/dev/null | grep -vE "^lo" | sed 's/^/  /'
echo
warn "如需撤销免密 sudo：sudo rm /etc/sudoers.d/90-penguin-nopasswd"
warn "如需撤销缩放改动：sudo cp /usr/share/phosh/phoc.ini.orig /usr/share/phosh/phoc.ini"
