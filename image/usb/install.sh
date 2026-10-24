#!/bin/bash
# PJA110 USB 模式切换：NCM 网卡 → MTP 文件传输
#
# 在设备上以 root 运行。因为会拆掉当前 SSH 所依赖的 NCM gadget，
# 必须以 **独立会话** 执行（setsid + 日志），否则命令会在中途被切断。
#
#   ./install.sh [--keep-telnet]
#
#   --keep-telnet   暂时保留 23 端口的 root shell（排查期有用）
#
# 做的事：
#   1. 建 ~/Shared（MTP 暴露的目录）
#   2. 安装 umtprd 配置与单元、gadget 脚本
#   3. enable MTP 三个单元，disable ut-usb-ncm / ut-shell
#   4. 拆除 NCM gadget，建立 MTP gadget 并绑定
#   5. 打印状态

set -u

KEEP_TELNET=0
[ "${1:-}" = "--keep-telnet" ] && KEEP_TELNET=1

HERE="$(cd "$(dirname "$0")" && pwd)"

# MTP 暴露哪个目录：跟随 uid 1000 的实际用户
# （交付镜像里是 ubuntu；测试机上可能还是 penguin）
OWNER="$(id -nu 1000 2>/dev/null)"
[ -n "$OWNER" ] || { echo "找不到 uid 1000 的用户"; exit 1; }
SHARED="$(getent passwd "$OWNER" | cut -d: -f6)/Shared"

log() { printf '[usb-mode] %s\n' "$*"; }
die() { printf '[usb-mode] ✗ %s\n' "$*"; exit 1; }

[ "$(id -u)" -eq 0 ] || die "必须以 root 运行"

# ---------------------------------------------------------------- 1. Shared
log "1. 准备 $SHARED（属主 $OWNER）"
install -d -m 0755 -o "$OWNER" -g "$OWNER" "$SHARED" || die "创建 $SHARED 失败"
ls -ld "$SHARED" | sed 's/^/    /'

# ---------------------------------------------------------------- 2. 部署文件
log "2. 部署文件"
install -d -m 0755 /opt/pja110
install -m 0755 -o root -g root "$HERE/usb-gadget.sh" /opt/pja110/usb-gadget.sh
install -m 0644 -o root -g root "$HERE/pja110-usb-gadget.service" /etc/systemd/system/pja110-usb-gadget.service
install -m 0644 -o root -g root "$HERE/pja110-usb-bind.service"   /etc/systemd/system/pja110-usb-bind.service
install -d -m 0755 /etc/systemd/system/umtp-responder.service.d
install -m 0644 -o root -g root "$HERE/umtp-responder.service.d-pja110.conf" \
        /etc/systemd/system/umtp-responder.service.d/pja110.conf

# umtprd 配置：把 storage 路径替换成实际用户的家目录
sed "s|^storage .*|storage \"$SHARED\" \"Shared\" \"rw\"|" "$HERE/umtprd.conf" \
    > /etc/umtprd/umtprd.conf
chmod 0644 /etc/umtprd/umtprd.conf
log "    /opt/pja110/usb-gadget.sh"
log "    /etc/systemd/system/pja110-usb-gadget.service"
log "    /etc/systemd/system/pja110-usb-bind.service"
log "    /etc/umtprd/umtprd.conf  ->  storage \"$SHARED\""
log "    /etc/systemd/system/umtp-responder.service.d/pja110.conf"

systemctl daemon-reload

# ---------------------------------------------------------------- 3. 单元开关
log "3. 调整单元启用状态"
systemctl enable  pja110-usb-gadget.service pja110-usb-bind.service umtp-responder.service >/dev/null 2>&1
systemctl disable ut-usb-ncm.service >/dev/null 2>&1 && log "    已 disable ut-usb-ncm.service（NCM 网卡不再随开机启动）"
if [ "$KEEP_TELNET" -eq 1 ]; then
    log "    保留 ut-shell.service（--keep-telnet）"
else
    systemctl disable --now ut-shell.service >/dev/null 2>&1 && log "    已 disable + stop ut-shell.service（23 端口 root shell）"
fi

# ---------------------------------------------------------------- 4. 停机顺序
log "4. 拆 NCM，建 MTP"
if [ "$KEEP_TELNET" -eq 0 ]; then
    systemctl stop ut-shell.service 2>/dev/null || true
fi
# 让 ut-usb-ncm 认为已停（它 RemainAfterExit=yes，stop 只清状态）
systemctl stop ut-usb-ncm.service 2>/dev/null || true

# prep 会 teardown 现有 g1（含 ncm.usb0）→ 此刻网络断开
systemctl start pja110-usb-gadget.service || die "gadget prep 失败"
systemctl start umtp-responder.service      || die "umtprd 启动失败"
# 等 umtprd 就绪后绑 UDC
systemctl start pja110-usb-bind.service     || die "UDC 绑定失败"

# ---------------------------------------------------------------- 5. 状态
log "5. 状态"
/opt/pja110/usb-gadget.sh status | sed 's/^/    /'
echo
log "    ut-usb-ncm: $(systemctl is-enabled ut-usb-ncm.service 2>&1) / $(systemctl is-active ut-usb-ncm.service 2>&1)"
log "    ut-shell:   $(systemctl is-enabled ut-shell.service 2>&1) / $(systemctl is-active ut-shell.service 2>&1)"
log "    umtp-responder: $(systemctl is-active umtp-responder.service 2>&1)"
echo
echo "PASS: USB 现在是 MTP 设备（暴露 $SHARED），网络访问只能走 Wi-Fi"
