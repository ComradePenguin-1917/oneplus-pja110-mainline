# 首启初始化（first-boot）设计与实现（2026-10-24）

交付镜像的"刷完镜像之后"流程：**静默首启**（自动、无交互）+ **两页向导**（只需用户输入两件事）。

---

## 一、为什么需要首启流程

镜像不能把构建机的身份信息带出去。当前设备里已烘焙的内容：

| 项 | 位置 | 问题 |
| --- | --- | --- |
| machine-id | `/etc/machine-id` | 所有设备同一 ID |
| SSH 主机密钥 | `/etc/ssh/ssh_host_*` | 所有设备共用同一套密钥 |
| Wi-Fi PSK | `/etc/NetworkManager/system-connections/*.nmconnection` | 泄露个人热点密码 |
| 日志 | `/var/log/journal`（776 MB）| 含全部调试记录 |
| shell 历史 | `~/.bash_history` | 含操作历史 |
| sudo | `/etc/sudoers.d/90-penguin-nopasswd` | `NOPASSWD:ALL` |

其中前两项必须**每台设备不同**，否则 SSH 会报 "host key changed"，machine-id 也会导致
日志/状态在设备间串味。

---

## 二、两层设计

```
刷入镜像 → 首次开机
            │
            ├─ [静默] pja110-firstboot.service (root, oneshot)
            │     · machine-id    → 随机生成
            │     · SSH 主机密钥  → 重新生成
            │     · 时区          → Asia/Shanghai
            │     · /etc/hosts    → 与 hostname 对齐
            │     → 写 marker: /var/lib/pja110/firstboot-system-done
            │
            └─ [图形] 首次登录后自动弹出 两页向导 (penguin 身份)
                  · 页 1：设备名称（hostname）
                  · 页 2：锁屏密码（同时用于 SSH）
                  → 写 marker: /var/lib/pja110/firstboot-done
```

**为什么不用 gnome-initial-setup**：它可用（46.3），但依赖 `libgdm1`，是给 GDM 会话设计的。
本机是 greetd + `[initial_session]` 自动登录 + Phosh，没有 greeter 进程
（`gtkgreet`/`wlgreet`/`tuigreet`/`regreet` 一个都没装），接不上。硬接要换掉整个登录栈，
代价高于自写。

**为什么向导用 zenity 而不是写 GTK4 应用**：`zenity` 4.0.1 已在系统里（之前保留的），
两个对话框足够表达需求，零新增依赖。写 libadwaita 应用要多 200 行代码和一套
Python GI 绑定（`gir1.2-gtk-4.0` 在清理时已被移除）。

---

## 三、文件清单

| 文件 | 安装位置 | 身份 | 作用 |
| --- | --- | --- | --- |
| `pja110-firstboot` | `/usr/local/sbin/` | root | 静默首启脚本 |
| `pja110-firstboot-helper` | `/usr/local/sbin/` | root（sudo 调用）| 唯一提权入口，三个白名单子命令 |
| `pja110-firstboot-wizard` | `/usr/local/bin/` | penguin | 两页向导 |
| `pja110-firstboot.service` | `/etc/systemd/system/` | — | 静默首启 unit（`Before=ssh.service`）|
| `pja110-firstboot-wizard.desktop` | `/etc/xdg/autostart/` | — | 首登自启动 |
| `pja110-firstboot.sudoers` | `/etc/sudoers.d/` | — | 只放行 helper |
| `cleanup-for-image.sh` | 不安装（构建期用）| root | 打包前清洗 |

部署：`image/firstboot/install.sh`（从 WSL 运行，支持 `--status` / `--reset`）。

---

## 四、提权模型

不给 `NOPASSWD:ALL`，而是收窄到一个脚本：

```
# /etc/sudoers.d/pja110-firstboot
penguin ALL=(root) NOPASSWD: /usr/local/sbin/pja110-firstboot-helper
```

helper 只接受三个子命令，且做严格校验：

| 子命令 | 校验 |
| --- | --- |
| `set-hostname <name>` | 正则 `^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$` |
| `set-password` | 从 stdin 读 `user:password`；用户必须是 `penguin`；长度 ≥ 6 |
| `mark-done` / `status` | 无参数 |

**为什么不用 polkit**：`polkitd` 在跑，但系统里**没有任何 polkit 授权代理**
（Phosh 不自带）。polkit 拦截的调用会直接失败而不是弹授权框，所以走 sudo 助手更可靠。

---

## 五、实测记录

### 5.1 静默首启

```
清空 /etc/machine-id + 删除 /etc/ssh/ssh_host_*

$ sudo /usr/local/sbin/pja110-firstboot
  machine-id: 生成随机值
  ssh host keys: 重新生成
ssh-keygen: generating new host keys: RSA ECDSA ED25519
  timezone: 校正为 Asia/Shanghai

结果：
  machine-id: 6ee6b41d… → 2424d126aa744ea1bfee825facd801d3   （32 位十六进制 ✅）
  权限 444 ✅     /var/lib/dbus/machine-id → /etc/machine-id ✅
  SSH 密钥 3 个（RSA/ECDSA/ED25519）✅
  /etc/timezone: Etc/UTC → Asia/Shanghai ✅
  marker 创建 ✅；再跑一次直接退出（幂等）✅
```

> 坑：一开始用 `systemd-machine-id-setup --commit`，但在**已运行的系统**上它会复用
> 当前 transient ID，导致"重新生成"其实没变（实测前后都是 `6ee6b41d…`）。
> 改为直接写 `/proc/sys/kernel/random/uuid` 的 32 位十六进制值，行为确定。

### 5.2 helper 校验

```
主机名 "bad name"   → 拒绝      "-bad" → 拒绝      "bad_name" → 拒绝
密码 "123"          → 拒绝（长度不足 6）
用户 root           → 拒绝（只允许 penguin）
子命令 rm-rf-xxx    → 拒绝（未知动作）
合法操作            → 成功
```

### 5.3 向导

`zenity` 两页都能正常弹出、`sudo -n` 调 helper 成功。

---

## 六、踩到的两个坑

### 6.1 向导写不了 root 的日志

向导以 `penguin` 运行，`echo >> /var/log/pja110-firstboot.log` 报
`Permission denied`。注意这个错误**不会被 `2>/dev/null` 拦掉** —— 它发生在打开文件
重定向的阶段，早于命令自身的 stderr 重定向。

改为 `logger -t pja110-firstboot-wizard`，查日志用：

```sh
journalctl -t pja110-firstboot-wizard
```

### 6.2 改 machine-id 会让 journal 查不到（重要）

测试重新生成 machine-id 之后，`journalctl` 突然全部报 `No journal files were found`。
原因：journald 按 machine-id 分目录

```
/var/log/journal/6ee6b41d0bec448290f6586f8f276d2c/   ← journald 仍在写这里
/var/log/journal/2424d126aa744ea1bfee825facd801d3/   ← journalctl 去这里找，空的
```

**旧日志没丢**，用 `-D` 指定目录仍可读：

```sh
journalctl -D /var/log/journal/6ee6b41d0bec448290f6586f8f276d2c
```

让 journald 按新 ID 建目录：

```sh
sudo systemctl restart systemd-journald
```

验证：

```
/var/log/journal/ 下出现 2424d126… 目录     ✅
journalctl 能读到当前日志                    ✅
logger -t pja110-firstboot-wizard 可查        ✅（长 tag 不会被截断）
```

> 这个副作用在交付镜像里**不存在**：首启时 journal 是空的，journald 会直接用新的
> machine-id 建目录。但调试期若手动改 machine-id 就会踩到。

### 6.3 `pkill -f` 自杀

用 `ssh host 'pkill -f pja110-firstboot-wizard'` 时，**自己的命令行里含同样的字符串**，
`pkill -f` 会把自己的 SSH 会话杀掉（表现为连接被重置、命令无输出）。

正确做法二选一：

```sh
pkill -x zenity                    # 按进程名精确匹配
# 或把脚本写到设备上的文件再执行，使命令行不含目标字符串
ssh host 'cat > /tmp/x.sh && bash /tmp/x.sh' < local.sh
```

同类陷阱之前也踩过：`pgrep -a "apt|dpkg"` 会匹配到 `[irq/213-synaptics_tcm_hbp]`
（"apt" 是 "synaptics" 的子串）。

---

## 七、附带修好的中文字体问题

向导最初是中文，屏幕上全是方块。查因：

```
$ fc-list :lang=zh | wc -l
0                       ← 一个中文字体都没有
$ fc-match sans:lang=zh
NotoSans-Regular.ttf    ← 只有拉丁字符的 Noto Sans
```

清理包时把 CJK 字体连带清掉了（`fonts-noto` 只含拉丁，中文要单独的 `fonts-noto-cjk`）。

修复：

```sh
apt-get install -y fonts-noto-cjk        # 91 MB，30 个 zh 字体
```

装完 `fc-match sans:lang=zh` **仍然**返回 `Noto Sans`（fontconfig 优先家族名），
所以再加 `/etc/fonts/local.conf`，**仅对 zh/ja/ko 语言模式前置 CJK 字体**：

```xml
<match target="pattern">
  <test name="lang" compare="contains"><string>zh</string></test>
  <edit name="family" mode="prepend" binding="strong">
    <string>Noto Sans CJK SC</string>
  </edit>
</match>
```

验证：

```
fc-match sans:lang=zh  → NotoSansCJK-Regular.ttc: "Noto Sans CJK SC"   ✅
fc-match sans:lang=ja  → NotoSansCJK-Regular.ttc: "Noto Sans CJK JP"   ✅
fc-match sans          → NotoSans-Regular.ttf: "Noto Sans"             ← 拉丁不受影响 ✅
```

> 注意：**向导本身已改为英文**（与 `en_US.UTF-8` 一致），不依赖 CJK 字体；
> 但字体仍然必要 —— 浏览中文网页、中文文件名、用户自己的中文内容都要用。

---

## 八、账号模型调整（2026-10-24 定稿）

### 8.1 决策

| 项 | 值 | 说明 |
| --- | --- | --- |
| 默认用户名 | `ubuntu` | 镜像里就是这个名字，**不做运行时改名** |
| 默认密码 | `123456` | 同上 |
| 首启向导 | **只问设备名** | 原来的密码页已移除 |
| 之后改密码 | `设置 → 用户`（或 SSH 里 `passwd`）| 见 8.3 |
| 之后改登录名 | 需要命令行 | GNOME 设置不提供改登录名 |

理由：手机不需要桌面式的账号初始化；只问设备名就够，凭据用默认值，
用户在设置里随时能改。

### 8.2 用户名必须在镜像构建阶段就定好

**不要在运行中的系统上改用户名。** 实测 `usermod -l` 会因为用户有运行中的
Phosh 会话而失败（`usermod: user penguin is currently running by process N`），
但脚本后续步骤继续执行，会留下「组叫新名、用户叫旧名、greetd 指向新名」的半成品，
直接把开机流程搞坏。

正确做法是在**挂载的 rootfs 上离线改**（没有运行中进程），顺序：

```sh
# 1) 账户文件（uid 不变）
sed -i 's/^penguin:/ubuntu:/' /etc/passwd /etc/shadow
sed -i 's|:/home/penguin:|:/home/ubuntu:|' /etc/passwd
# 2) 附加组成员（最容易漏！）
sed -i 's/\bpenguin\b/ubuntu/g' /etc/group /etc/gshadow
# 3) 家目录
mv /home/penguin /home/ubuntu
# 4) 登录与提权配置
sed -i 's/ubuntu/penguin/g' -> 反向，见事故文档  # greetd / getty / helper / subuid
mv /etc/sudoers.d/90-penguin-nopasswd /etc/sudoers.d/90-ubuntu-nopasswd
sed -i 's/^penguin /ubuntu /' /etc/sudoers.d/90-ubuntu-nopasswd    # ← 内容也要改！
# 5) accounts-daemon 缓存
mv /var/lib/AccountsService/users/penguin /var/lib/AccountsService/users/ubuntu
sed -i 's|/home/penguin|/home/ubuntu|g' /var/lib/AccountsService/users/ubuntu
```

完整踩坑记录见 [A/B 槽与改名事故复盘](ab-flip-and-rename-incident-20261024.md)。

### 8.3 让「设置 → 用户」能改密码

polkit 对 `org.freedesktop.accounts.change-own-password` 默认要求 `auth_admin`，
而 Phosh 环境**没有 polkit 授权代理**，弹不出授权框 → 改密码直接失败。

放行规则（随包安装）：

```js
// /etc/polkit-1/rules.d/50-pja110-account.rules
polkit.addRule(function (action, subject) {
    if (action.id == "org.freedesktop.accounts.change-own-password" &&
        subject.active) {
        return polkit.Result.YES;
    }
});
```

**注意 `subject.local` 陷阱**：SSH 会话的 `local == false`（远程），
带这个条件时通过 SSH 调用永远失败，只有本地 Phosh 会话能用。去掉后两种都行。

实测通过（无需认证）：

```
busctl --system call org.freedesktop.Accounts /org/freedesktop/Accounts/User1000 \
  org.freedesktop.Accounts.User SetPassword ss "testpass999" ""
→ 无输出（成功）

shadow: $y$j9T$qmGi92e3…（yescrypt，74 字节，accounts-daemon 正确哈希）
```

### 8.4 首启向导最终形态

只有一页（`zenity --entry`）＋ 一个完成提示：

| 步骤 | 内容 |
| --- | --- |
| 页 1 | `Device name`：预填当前 hostname，校验 `^[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?$` |
| 完成 | 提示默认账号 `ubuntu / 123456`，以及在哪里改密码、配 Wi-Fi |

`grep -c "zenity --password"` 应为 **0**（确认没有密码页）。

---

## 九、交付镜像里的相关约束

1. `cleanup-for-image.sh` 必须跑，它负责清 machine-id / SSH 密钥 / Wi-Fi / 日志 /
   `NOPASSWD:ALL`，并把两个首启 marker 复位
2. 首启 marker 不存在 → 首启流程才会跑；存在则跳过（可重复刷机后验证）
3. `/etc/hostname` 与 `/etc/hosts` 的 `127.0.1.1` 必须一致（首启脚本会兜底）
4. locale 生成为 `en_US.UTF-8`，时区 `Asia/Shanghai`
5. 用户名 `ubuntu` / 密码 `123456` 在**镜像构建阶段**就定好，运行时不再改名
6. 刷机后必须确认 `fastboot getvar current-slot` 为 `a`
