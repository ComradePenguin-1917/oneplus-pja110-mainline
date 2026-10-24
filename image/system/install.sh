#!/bin/bash
# 安装 PJA110 系统级配置（在设备上以 root 运行）
#
#   sudo ./install.sh
#
# 安装三项：
#   1. SSH 主机密钥自动生成（ssh.service drop-in）
#   2. 根分区扩容（pja110-growfs.service，幂等）
#   3. polkit 放行改密码 / 改设备名
#
# 同时会**移除**旧的首启组件（如果存在）。

set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
log() { printf '[system] %s\n' "$*"; }
[ "$(id -u)" -eq 0 ] || { echo "必须以 root 运行"; exit 1; }

# ---------------------------------------------------------------- 1. SSH 密钥
log "1. SSH 主机密钥 drop-in"
install -d -m 0755 /etc/systemd/system/ssh.service.d
install -m 0644 -o root -g root "$HERE/ssh-host-keys.conf" \
        /etc/systemd/system/ssh.service.d/10-pja110-host-keys.conf
command -v /usr/bin/ssh-keygen >/dev/null || log "  ⚠️ /usr/bin/ssh-keygen 不存在，drop-in 会失败"

# ---------------------------------------------------------------- 2. 扩容
log "2. 根分区扩容 unit"
install -m 0644 -o root -g root "$HERE/pja110-growfs.service" \
        /etc/systemd/system/pja110-growfs.service

# ---------------------------------------------------------------- 3. polkit
log "3. polkit 规则"
install -d -m 0755 /etc/polkit-1/rules.d
install -m 0644 -o root -g root "$HERE/50-pja110-account.rules" \
        /etc/polkit-1/rules.d/50-pja110-account.rules

systemctl daemon-reload
systemctl enable pja110-growfs.service >/dev/null 2>&1
systemctl restart polkit 2>/dev/null || true
log "已安装并 reload"

# ---------------------------------------------------------------- 4. 清旧首启
log "4. 移除旧的首启组件"
systemctl disable --now pja110-firstboot.service >/dev/null 2>&1 || true
rm -f /etc/systemd/system/pja110-firstboot.service \
      /usr/local/sbin/pja110-firstboot \
      /usr/local/sbin/pja110-firstboot-helper \
      /usr/local/bin/pja110-firstboot-wizard \
      /etc/xdg/autostart/pja110-firstboot-wizard.desktop \
      /etc/sudoers.d/pja110-firstboot \
      /var/log/pja110-firstboot.log
rm -rf /var/lib/pja110
systemctl daemon-reload
left=$(ls /usr/local/sbin/pja110* /usr/local/bin/pja110* 2>/dev/null)
[ -z "$left" ] && log "  已清空" || log "  ⚠️ 仍有残留: $left"

# ---------------------------------------------------------------- 5. 立即扩容
log "5. 立即执行一次扩容"
systemctl start pja110-growfs.service 2>&1 | sed 's/^/  /'
df -h / | tail -1 | sed 's/^/  /'

log "完成"
