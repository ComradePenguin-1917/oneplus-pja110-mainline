#!/bin/bash
# PJA110 交付镜像 —— 离线改名：把默认用户从 penguin 改成 ubuntu
#
# 在**挂载好的 rootfs 镜像**上运行（不是运行中的系统），因此没有"用户有
# 运行中进程导致 usermod 失败"的问题，也不会有"改了 sudoers 之后自己没权限"
# 的自锁问题。
#
#   sudo ./rename-user-offline.sh <rootfs-mountpoint> [--dry-run]
#
# 例：
#   sudo ./rename-user-offline.sh /mnt/img
#
# 顺序很重要：先做所有需要"内容正确"的改动，最后再动 sudoers，
# 并且**文件名与文件内容都要改**（上次事故就是漏了这一条）。

set -u

ROOT="${1:-}"
DRY=0
[ "${2:-}" = "--dry-run" ] && DRY=1

OLD_USER=penguin
NEW_USER=ubuntu

[ -n "$ROOT" ] || { echo "用法: $0 <rootfs-mountpoint> [--dry-run]"; exit 2; }
[ -d "$ROOT/etc" ] || { echo "错误: $ROOT 看起来不是 rootfs（缺 /etc）"; exit 2; }

say()  { printf '  %s\n' "$*"; }
head_() { printf '\n== %s ==\n' "$*"; }

run() {
    if [ "$DRY" -eq 1 ]; then
        say "[dry] $*"
    else
        "$@"
    fi
}

# 在 $ROOT 下的文件里做替换（含 dry-run 预览）
subst() {
    local file="$ROOT/$1"; shift
    local expr="$1"
    [ -f "$file" ] || return 0
    grep -q "$OLD_USER" "$file" 2>/dev/null || return 0
    if [ "$DRY" -eq 1 ]; then
        say "[dry] sed '$expr' <- ${file#$ROOT}"
        grep -n "$OLD_USER" "$file" | head -3 | sed 's/^/        /'
    else
        sed -i "$expr" "$file" && say "已改 ${file#$ROOT}"
    fi
}

# ---- 前置检查 ---------------------------------------------------------
head_ "前置检查"
if [ "$DRY" -eq 0 ]; then
    if ! grep -q "^$OLD_USER:" "$ROOT/etc/passwd"; then
        echo "错误: $ROOT/etc/passwd 里没有 $OLD_USER —— 可能已经改过了"
        grep -q "^$NEW_USER:" "$ROOT/etc/passwd" && echo "       （$NEW_USER 已存在，视为已完成）"
        exit 1
    fi
    if grep -q "^$NEW_USER:" "$ROOT/etc/passwd"; then
        echo "错误: $NEW_USER 已经存在，拒绝继续"
        exit 1
    fi
    say "✓ $OLD_USER 存在，$NEW_USER 未被占用"
else
    say "[dry] 将校验 $OLD_USER 存在且 $NEW_USER 不存在"
fi

# ---- 1. 账户文件（uid 不变）------------------------------------------
head_ "1. 账户文件"
subst etc/passwd  "s/^$OLD_USER:/$NEW_USER:/"
subst etc/shadow  "s/^$OLD_USER:/$NEW_USER:/"
subst etc/passwd- "s/^$OLD_USER:/$NEW_USER:/"
subst etc/shadow- "s/^$OLD_USER:/$NEW_USER:/"

# 家目录字段
if [ "$DRY" -eq 1 ]; then
    say "[dry] /etc/passwd 家目录 :/home/$OLD_USER: -> :/home/$NEW_USER:"
else
    sed -i "s|:/home/$OLD_USER:|:/home/$NEW_USER:|" "$ROOT/etc/passwd"
    [ -f "$ROOT/etc/passwd-" ] && sed -i "s|:/home/$OLD_USER:|:/home/$NEW_USER:|" "$ROOT/etc/passwd-"
    say "已改 /etc/passwd 家目录字段"
fi

# ---- 2. 组：主组名 + **附加组成员**（最容易漏）-------------------------
head_ "2. 组与附加成员"
# 用整词替换同时覆盖两种情况：
#   - 主组行   penguin:x:1000:
#   - 成员列表 sudo:x:27:penguin,other
subst etc/group    "s/\b$OLD_USER\b/$NEW_USER/g"
subst etc/group-   "s/\b$OLD_USER\b/$NEW_USER/g"
subst etc/gshadow  "s/\b$OLD_USER\b/$NEW_USER/g"
subst etc/gshadow- "s/\b$OLD_USER\b/$NEW_USER/g"

# ---- 3. 家目录 -------------------------------------------------------
head_ "3. 家目录"
if [ -d "$ROOT/home/$OLD_USER" ] && [ ! -e "$ROOT/home/$NEW_USER" ]; then
    run mv "$ROOT/home/$OLD_USER" "$ROOT/home/$NEW_USER"
    [ "$DRY" -eq 0 ] && say "已移动 /home/$OLD_USER -> /home/$NEW_USER"
elif [ -d "$ROOT/home/$NEW_USER" ]; then
    say "/home/$NEW_USER 已存在，跳过"
else
    say "⚠️ /home/$OLD_USER 不存在"
fi

# ---- 4. 登录与提权配置 ------------------------------------------------
head_ "4. 登录与提权"
subst etc/greetd/config.toml                                        "s/$OLD_USER/$NEW_USER/g"
subst etc/systemd/system/getty@tty1.service.d/autologin.conf        "s/$OLD_USER/$NEW_USER/g"
subst etc/subuid                                                     "s/^$OLD_USER:/$NEW_USER:/"
subst etc/subgid                                                     "s/^$OLD_USER:/$NEW_USER:/"
# MTP 暴露的目录在配置里写的是绝对路径，必须跟着改
subst etc/umtprd/umtprd.conf                                         "s|/home/$OLD_USER|/home/$NEW_USER|g"

# sudoers：文件名和内容都要改（上次事故就是只改了文件名）
head_ "4b. sudoers（文件名 + 内容）"
SUDO_OLD="etc/sudoers.d/90-$OLD_USER-nopasswd"
SUDO_NEW="etc/sudoers.d/90-$NEW_USER-nopasswd"
if [ -f "$ROOT/$SUDO_OLD" ]; then
    subst "$SUDO_OLD" "s/^$OLD_USER /$NEW_USER /"
    if [ "$DRY" -eq 0 ]; then
        mv "$ROOT/$SUDO_OLD" "$ROOT/$SUDO_NEW"
        say "已改名 90-$OLD_USER-nopasswd -> 90-$NEW_USER-nopasswd"
    else
        say "[dry] mv $SUDO_OLD -> $SUDO_NEW"
    fi
else
    say "⚠️ 未找到 $SUDO_OLD（交付镜像里应当存在）"
fi

# ---- 5. accounts-daemon 缓存 -----------------------------------------
head_ "5. accounts-daemon 缓存"
if [ -f "$ROOT/var/lib/AccountsService/users/$OLD_USER" ] && \
   [ ! -e "$ROOT/var/lib/AccountsService/users/$NEW_USER" ]; then
    run mv "$ROOT/var/lib/AccountsService/users/$OLD_USER" \
           "$ROOT/var/lib/AccountsService/users/$NEW_USER"
    [ "$DRY" -eq 0 ] && sed -i "s|/home/$OLD_USER|/home/$NEW_USER|g" \
        "$ROOT/var/lib/AccountsService/users/$NEW_USER" && say "已迁移 accounts 缓存"
else
    say "无需迁移"
fi

# ---- 6. 校验 ---------------------------------------------------------
head_ "6. 校验"
if [ "$DRY" -eq 1 ]; then
    echo "  [dry] 结束"
    exit 0
fi

fail=0
chk() { # chk <描述> <命令...>
    local desc="$1"; shift
    if "$@" >/dev/null 2>&1; then
        printf '  ✓ %s\n' "$desc"
    else
        printf '  ✗ %s\n' "$desc"; fail=1
    fi
}

grep -q "^$NEW_USER:" "$ROOT/etc/passwd"            && echo "  ✓ passwd 有 $NEW_USER" || { echo "  ✗ passwd 缺 $NEW_USER"; fail=1; }
grep -q "^$OLD_USER:" "$ROOT/etc/passwd"            && { echo "  ✗ passwd 仍有 $OLD_USER"; fail=1; } || echo "  ✓ passwd 无 $OLD_USER"
grep -q "^$NEW_USER:" "$ROOT/etc/group"             && echo "  ✓ group 有 $NEW_USER" || { echo "  ✗ group 缺 $NEW_USER"; fail=1; }

# 家目录字段
pw_home=$(grep "^$NEW_USER:" "$ROOT/etc/passwd" | cut -d: -f6)
[ "$pw_home" = "/home/$NEW_USER" ] && echo "  ✓ passwd 家目录 = $pw_home" || { echo "  ✗ passwd 家目录 = $pw_home"; fail=1; }
[ -d "$ROOT/home/$NEW_USER" ] && echo "  ✓ /home/$NEW_USER 存在" || { echo "  ✗ /home/$NEW_USER 缺失"; fail=1; }

# 附加组成员
for g in sudo audio video plugdev input render; do
    line=$(grep "^$g:" "$ROOT/etc/group" 2>/dev/null)
    [ -n "$line" ] || continue
    if printf '%s' "$line" | grep -q "[:,\b]$NEW_USER\b\|:$NEW_USER$"; then
        echo "  ✓ $g 组含 $NEW_USER"
    else
        echo "  ✗ $g 组不含 $NEW_USER（$line）"; fail=1
    fi
done

# sudoers：文件名与内容都要对
SUDO_FILE="$ROOT/etc/sudoers.d/90-$NEW_USER-nopasswd"
if [ -f "$SUDO_FILE" ]; then
    if grep -q "^$NEW_USER " "$SUDO_FILE"; then
        echo "  ✓ $NEW_USER 有 NOPASSWD 规则"
    else
        echo "  ✗ sudoers 文件名对了但内容是 $(grep -h '^[a-z]' "$SUDO_FILE" | head -1)"; fail=1
    fi
else
    echo "  ✗ 缺 $SUDO_FILE"; fail=1
fi
[ -f "$ROOT/etc/sudoers.d/90-$OLD_USER-nopasswd" ] && { echo "  ✗ 旧 sudoers 文件仍在"; fail=1; } || echo "  ✓ 无旧 sudoers 文件"

# greetd / getty
grep -q "user = \"$NEW_USER\"" "$ROOT/etc/greetd/config.toml" 2>/dev/null && echo "  ✓ greetd 指向 $NEW_USER" || { echo "  ✗ greetd 未指向 $NEW_USER"; fail=1; }
grep -q "autologin $NEW_USER" "$ROOT/etc/systemd/system/getty@tty1.service.d/autologin.conf" 2>/dev/null && echo "  ✓ getty autologin = $NEW_USER" || { echo "  ✗ getty autologin 未改"; fail=1; }

# 残留
left=$(grep -rl "$OLD_USER" "$ROOT/etc" 2>/dev/null | grep -v 'pre-rename' | grep -v '\.dpkg-' | head -5)
if [ -n "$left" ]; then
    echo "  ⚠️ /etc 下仍有 $OLD_USER 引用:"
    printf '%s\n' "$left" | sed "s|^$ROOT||; s/^/      /"
    fail=1
else
    echo "  ✓ /etc 下无 $OLD_USER 残留"
fi

echo ""
if [ "$fail" -eq 0 ]; then
    echo "PASS: 改名完成且校验通过"
    exit 0
else
    echo "FAIL: 有校验项未通过，请看上面的 ✗"
    exit 1
fi
