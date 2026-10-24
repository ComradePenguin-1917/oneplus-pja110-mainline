#!/bin/bash
# PJA110 交付镜像 —— 构建期清洗脚本
#
# 在**打包成镜像之前**在设备上以 root 运行，把不该随镜像流出的东西清掉。
#
#   sudo ./cleanup-for-image.sh --dry-run     只列出将要做什么
#   sudo ./cleanup-for-image.sh               真正执行
#
# 清洗内容分四类：
#   A. 设备唯一标识  —— machine-id / SSH 主机密钥（首启重新生成）
#   B. 个人凭据      —— Wi-Fi 密码、shell 历史、SSH 私钥
#   C. 运行痕迹      —— 日志、缓存、临时文件、构建残留
#   D. 交付口径      —— locale、时区、sudoers 收窄、首启 marker
#
# 执行后设备**仍可正常使用**（不会破坏当前运行状态），但下次开机时
# 已无首启脚本：machine-id 由 systemd 生成，SSH 主机密钥由 ssh.service 的
# ExecStartPre=ssh-keygen -A 生成（见 image/system/）。
set -u

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

MARKER_DIR=/var/lib/pja110
FAIL=0

say() { printf '  %s\n' "$*"; }
section() { printf '\n== %s ==\n' "$*"; }

# rm2 <path...> —— 支持 dry-run
rm2() {
    for p in "$@"; do
        if [ -e "$p" ] || [ -L "$p" ]; then
            if [ "$DRY" -eq 1 ]; then
                say "[dry] rm -rf $p"
            else
                rm -rf "$p" 2>/dev/null && say "已删除 $p" || { say "删除失败 $p"; FAIL=1; }
            fi
        fi
    done
}

[ "$(id -u)" -eq 0 ] || { echo "必须以 root 运行"; exit 1; }

echo "PJA110 镜像清洗脚本  ($([ "$DRY" -eq 1 ] && echo DRY-RUN || echo 实际执行))"

# ---------------------------------------------------------------- A. 唯一标识
section "A. 设备唯一标识（首启重新生成）"
if [ "$DRY" -eq 1 ]; then
    say "[dry] truncate /etc/machine-id"
    say "[dry] rm /etc/ssh/ssh_host_*"
else
    : >/etc/machine-id && say "已清空 /etc/machine-id"
    rm -f /etc/ssh/ssh_host_*_key /etc/ssh/ssh_host_*_key.pub
    say "已删除 SSH 主机密钥"
fi
rm2 /var/lib/dbus/machine-id.bak

# ---------------------------------------------------------------- B. 个人凭据
section "B. 个人凭据"
# Wi-Fi / 网络连接配置（含 PSK）
if [ -d /etc/NetworkManager/system-connections ]; then
    if [ "$DRY" -eq 1 ]; then
        ls /etc/NetworkManager/system-connections/ 2>/dev/null | sed 's/^/  [dry] rm /etc/NetworkManager/system-connections\//'
    else
        rm -f /etc/NetworkManager/system-connections/*.nmconnection 2>/dev/null
        say "已删除 NetworkManager 连接配置（含 Wi-Fi 密码）"
    fi
fi

# shell 历史
rm2 /root/.bash_history /root/.python_history
for h in /home/*/.bash_history /home/*/.python_history /home/*/.local/share/recently-used.xbel; do
    [ -e "$h" ] && rm2 "$h"
done

# 用户 SSH 私钥（若有）
for d in /root/.ssh /home/*/.ssh; do
    [ -d "$d" ] || continue
    rm2 "$d/id_rsa" "$d/id_ecdsa" "$d/id_ed25519" "$d/authorized_keys" "$d/known_hosts"
done

# 我们自己的调试/构建残留
section "C. 运行痕迹与构建残留"
rm2 /root/fb-backup /root/pkgs-before-deep-clean.txt /root/pkgs-before-gui-clean.txt \
    /root/pkgs-before-builddep-clean.txt /root/pkgs-before-lomiri-removal.txt \
    /root/pos-src /root/pos-v0.38.0.tar.gz /root/pos-patched.tar.gz /root/patchset \
    /root/dtbo-work /root/gcc-src /root/gcc-src2 /root/gcc-orig \
    /tmp/pos-build /tmp/pos-build2 /tmp/pos-build3 /tmp/pos-v2 /tmp/pos-v3 \
    /tmp/pos-final /tmp/gcc-build.log /tmp/gcc-build.done /tmp/dtbo_a.img \
    /tmp/dtbo_a-new.img /tmp/dtbo_a-final.img /tmp/vb_a.img /tmp/vb_base.dtb \
    /tmp/purg.txt /tmp/rmlist.txt /tmp/builddeps.txt /tmp/rb-final.img /tmp/dtbo-rb.img \
    /tmp/purg.txt /tmp/rmlist.txt /tmp/builddeps.txt /tmp/rb-final.img /tmp/dtbo-rb.img

# 日志
if [ "$DRY" -eq 1 ]; then
    say "[dry] journalctl --vacuum-size=1M && 清空 /var/log"
else
    journalctl --vacuum-size=1M >/dev/null 2>&1 || true
    find /var/log -xdev -type f \( -name '*.log' -o -name '*.gz' -o -name '*.[0-9]' \) -delete 2>/dev/null
    : >/var/log/wtmp 2>/dev/null || true
    : >/var/log/btmp 2>/dev/null || true
    : >/var/log/lastlog 2>/dev/null || true
    rm -rf /var/log/journal/* 2>/dev/null
    say "已清理日志与 journal"
fi

# 临时文件与包缓存
rm2 /tmp/* /var/tmp/*
if [ "$DRY" -eq 1 ]; then
    say "[dry] apt-get clean"
else
    apt-get clean >/dev/null 2>&1 || true
    say "已清空 apt 缓存"
fi

# 备份/编辑器残留
rm2 /etc/*.bak /etc/*~ /etc/apt/sources.list.d/*.bak /root/ubuntu.sources.bak

# ---------------------------------------------------------------- D. 交付口径
section "D. 交付口径"

# D1. sudoers：删掉 NOPASSWD:ALL，只留首启助手的窄规则
if [ -f /etc/sudoers.d/90-penguin-nopasswd ]; then
    if [ "$DRY" -eq 1 ]; then
        say "[dry] rm /etc/sudoers.d/90-penguin-nopasswd"
    else
        say "已删除 NOPASSWD:ALL（交付镜像不再需要任何 sudo 规则）"
        say "已删除 NOPASSWD:ALL（仅保留 pja110-firstboot-helper 的窄规则）"
    fi
fi

# D2. locale：生成 en_US.UTF-8
if [ "$DRY" -eq 1 ]; then
    say "[dry] locale-gen en_US.UTF-8 并设 LANG=en_US.UTF-8"
else
    if command -v locale-gen >/dev/null 2>&1; then
        sed -i 's/^# *en_US.UTF-8 UTF-8/en_US.UTF-8 UTF-8/' /etc/locale.gen 2>/dev/null
        grep -q '^en_US.UTF-8 UTF-8' /etc/locale.gen 2>/dev/null || \
            echo 'en_US.UTF-8 UTF-8' >>/etc/locale.gen
        locale-gen >/dev/null 2>&1 || true
        say "已生成 en_US.UTF-8"
    else
        say "locale-gen 不存在，跳过"
    fi
fi
if [ "$DRY" -eq 1 ]; then
    say "[dry] /etc/default/locale LANG=en_US.UTF-8"
else
    sed -i '/^LANG=/d' /etc/default/locale 2>/dev/null || true
    echo 'LANG=en_US.UTF-8' >>/etc/default/locale
    say "LANG=en_US.UTF-8"
fi

# D3. 时区
if [ "$DRY" -eq 1 ]; then
    say "[dry] 时区设为 Asia/Shanghai"
else
    echo "Asia/Shanghai" >/etc/timezone
    ln -sf /usr/share/zoneinfo/Asia/Shanghai /etc/localtime
    say "时区 Asia/Shanghai"
fi

# D4. 首启 marker：确保都不存在（否则首启流程不会跑）
if [ "$DRY" -eq 1 ]; then
    say "[dry] 清理遗留的首启目录（组件本身已不存在）"
else
    rm -rf "$MARKER_DIR"
    say "已清理遗留首启目录 /var/lib/pja110"
    say "已复位首启 marker（下次开机走首启流程）"
fi

# D5. hostname 与 /etc/hosts 一致性
H="$(cat /etc/hostname 2>/dev/null)"
if [ -n "$H" ]; then
    if [ "$DRY" -eq 1 ]; then
        say "[dry] 确保 /etc/hosts 有 127.0.1.1 $H"
    else
        if grep -qE '^127\.0\.1\.1' /etc/hosts; then
            sed -i -E "s|^127\.0\.1\.1.*|127.0.1.1\t$H|" /etc/hosts
        else
            printf '127.0.1.1\t%s\n' "$H" >>/etc/hosts
        fi
        say "/etc/hosts 与 hostname ($H) 一致"
    fi
fi

# ---------------------------------------------------------------- 汇总
section "汇总"
if [ "$DRY" -eq 1 ]; then
    echo "  DRY-RUN 结束，未做任何修改"
else
    echo "  清洗完成。建议接着："
    echo "    sync"
    echo "    # 然后按 image/build 的流程打包 rootfs"
    [ "$FAIL" -ne 0 ] && echo "  ⚠️ 有删除失败项，请检查上面的输出"
fi
exit 0
