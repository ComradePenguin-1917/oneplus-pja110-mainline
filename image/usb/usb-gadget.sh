#!/bin/sh
# PJA110 USB gadget —— 只提供 MTP（暴露 ~/Shared）
#
# 设计要点：
#   * 不再提供 NCM 网卡：插上 PC 是一个 MTP 设备，不是网络
#   * 手工搭 configfs gadget，不用 umtprd-ffs（那是 Debian 的示例脚本，
#     自己建 gadget 后 `umtprd &` 就退出，systemd 会以为服务挂了）
#   * FunctionFS 顺序：建 ffs.mtp → 挂 functionfs → umtprd 打开 ep0 写描述符
#     → 等 ep1 出现 → 最后才把 UDC 绑上去
#     （先绑 UDC 再写描述符会导致主机枚举不到配置）
#
# 用法：
#   usb-gadget.sh prep    建 gadget + 挂 functionfs（不绑 UDC）
#   usb-gadget.sh bind    等 umtprd 就绪后绑 UDC
#   usb-gadget.sh stop    解绑、卸 functionfs、拆 gadget
#   usb-gadget.sh status  打印当前状态

set -u

G=/sys/kernel/config/usb_gadget/g1
FFS=/dev/ffs-mtp
CFGFS=/sys/kernel/config

say() { echo "[usb-gadget] $*" >&2; }

udc_name() { ls /sys/class/udc 2>/dev/null | head -1; }

teardown() {
    [ -d "$G" ] || return 0
    # 1) 先解绑 UDC
    if [ -s "$G/UDC" ] 2>/dev/null; then
        echo "" > "$G/UDC" 2>/dev/null || true
    fi
    # 2) 摘掉 config 下的函数链接
    for l in "$G"/configs/*/*; do
        [ -L "$l" ] && rm -f "$l"
    done
    # 3) 卸 functionfs（必须在删 function 目录之前）
    umount "$FFS" 2>/dev/null || true
    # 4) 逐层删
    for d in "$G"/configs/c.1/strings/0x409 "$G"/configs/c.1 \
             "$G"/functions/ffs.mtp "$G"/functions/* \
             "$G"/strings/0x409; do
        [ -d "$d" ] && rmdir "$d" 2>/dev/null || true
    done
    rmdir "$G" 2>/dev/null || true
}

cmd_prep() {
    mount -t configfs none "$CFGFS" 2>/dev/null || true
    teardown

    UDC=$(udc_name)
    [ -n "$UDC" ] || { say "没有可用 UDC"; return 1; }

    mkdir -p "$FFS"
    mkdir -p "$G" || { say "创建 gadget 目录失败"; return 1; }

    # 设备级标识：MTP 设备惯例是 PTP 类（0x0100）
    echo 0x1d6b > "$G/idVendor"
    echo 0x0100 > "$G/idProduct"
    echo 0x0100 > "$G/bcdDevice"
    echo 0x0200 > "$G/bcdUSB"

    mkdir -p "$G/strings/0x409"
    echo "PJA110" > "$G/strings/0x409/serialnumber"
    echo "OnePlus" > "$G/strings/0x409/manufacturer"
    echo "PJA110" > "$G/strings/0x409/product"

    mkdir -p "$G/configs/c.1/strings/0x409"
    echo "MTP" > "$G/configs/c.1/strings/0x409/configuration"
    echo 500 > "$G/configs/c.1/MaxPower"

    mkdir -p "$G/functions/ffs.mtp"
    ln -sf "$G/functions/ffs.mtp" "$G/configs/c.1/"

    # 挂 functionfs，ep0 出现后 umtprd 才能打开
    mount -t functionfs mtp "$FFS" || { say "挂载 functionfs 失败"; return 1; }
    say "prep 完成：gadget=g1, udc=$UDC, ffs=$FFS（尚未绑定）"
    return 0
}

cmd_bind() {
    UDC=$(udc_name)
    [ -n "$UDC" ] || { say "没有可用 UDC"; return 1; }
    [ -d "$G" ]      || { say "gadget 不存在，先做 prep"; return 1; }
    [ -e "$FFS/ep0" ] || { say "$FFS/ep0 不存在，functionfs 没挂好"; return 1; }

    # 等 umtprd 把描述符写好（它会创建 ep1/ep2/ep3）
    i=0
    while [ $i -lt 100 ]; do
        [ -e "$FFS/ep1" ] && break
        i=$((i+1))
        sleep 0.2
    done
    if [ ! -e "$FFS/ep1" ]; then
        say "umtprd 未就绪（ep1 未出现），放弃绑定"
        return 1
    fi

    # 开机时特地在绑定前多等几秒：
    # 设备 5 秒就起完，如果 UDC 绑得太快，主机会来不及处理"上一次的断开"，
    # 从而保留一个已经死掉的设备实例、不再重新枚举（Windows 上实测如此，
    # 表现为系统一切正常但 PC 里看不到 PJA110）。给主机留出沉降时间即可。
    SETTLE=${PJA110_USB_SETTLE:-5}
    if [ "$SETTLE" -gt 0 ] 2>/dev/null; then
        say "等待 ${SETTLE}s 让主机处理断开"
        sleep "$SETTLE"
    fi

    echo "$UDC" > "$G/UDC" || { say "绑定 UDC 失败"; return 1; }
    say "已绑定 UDC=$UDC"
    return 0
}

cmd_stop() {
    teardown
    say "已拆除 gadget"
}

cmd_status() {
    echo "UDC available : $(udc_name)"
    echo "gadget dir    : $([ -d $G ] && echo 存在 || echo 不存在)"
    echo "UDC bound     : $(cat $G/UDC 2>/dev/null || echo 未绑定)"
    echo "functions     : $(ls $G/functions 2>/dev/null | tr '\n' ' ')"
    echo "config links  : $(ls $G/configs/c.1 2>/dev/null | tr '\n' ' ')"
    echo "ffs mounted   : $(mountpoint -q $FFS && echo 是 || echo 否)"
    echo "ffs ep        : $(ls $FFS 2>/dev/null | tr '\n' ' ')"
    echo "umtprd        : $(pgrep -x umtprd >/dev/null && echo 运行中 || echo 未运行)"
}

case "${1:-}" in
    prep)   cmd_prep ;;
    bind)   cmd_bind ;;
    stop)   cmd_stop ;;
    status) cmd_status ;;
    *) echo "用法: $0 {prep|bind|stop|status}"; exit 2 ;;
esac
