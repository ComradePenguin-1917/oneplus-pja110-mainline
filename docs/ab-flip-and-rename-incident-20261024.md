# 事故复盘：A/B 槽自动切到 B + 用户名改名的半成品状态（2026-10-24）

一次连环故障的完整记录：**用户改名只做了一半**、**设备自己切到了 B 槽**、
以及**救援 initramfs 里的一个 bug**。最终全部恢复。

---

## 一、最终结论（先看这个）

| 问题 | 根因 | 状态 |
| --- | --- | --- |
| 启动卡住、能 ping 但 22/23 端口无监听 | **`current-slot` 被切成 `b`**（bootloader 自动切槽）| 已 `--set-active=a` 恢复 |
| 改名后系统处于半成品状态 | `usermod -l` 因用户有运行中进程而失败，但后续步骤已执行 | 已用救援 initramfs 完整回退 |
| 恢复后 `penguin` 没有免密 sudo | 救援脚本改了 sudoers **文件名**却没改**文件内容** | 已修 |
| 改密码在设置里用不了 | polkit `change-own-password` 要求 `auth_admin`，而 Phosh 没有授权代理 | 已加 polkit 规则放行 |

**最重要的一条教训**：这台设备的 bootloader 会在启动失败若干次后**自动把槽切到 B**，
而 B 槽没有系统。任何"起不来"的排查，第一件事都必须是：

```sh
fastboot getvar current-slot     # 期望 a
```

---

## 二、时间线

| 时间 | 事件 |
| --- | --- |
| 19:01 | 用户在首启向导里设定主机名 `test` 与新密码，向导完整跑通（`journalctl -t pja110-firstboot-wizard` 有三条记录）|
| 19:0x | 重置密码为 `123456`、主机名改回 `pja110` |
| 19:1x | 执行 `penguin → ubuntu` 改名，**部分失败** |
| 19:18 | `systemctl reboot` |
| 19:20–19:40 | 设备 ping 通、22/23 均拒绝连接；屏幕停在启动文字 |
| 19:40 | 用户进 fastboot → `current-slot: b` |
| 19:44 | `--set-active=a` + 刷救援 initramfs（回退改名）→ 启动成功 |
| 19:48 | 刷回正常 initramfs → 验证全绿 |

---

## 三、故障 1：槽位被切到 B

### 现象

```
$ ping 172.16.42.1          → 通，2ms，TTL=64
$ ss 探测 22/23/53/80/...   → 全部 Connection refused
$ journalctl --list-boots   → 卡住的那次启动没有任何条目
```

### 判定过程

1. **网络在跑但没有任何服务** → 说明不是完全死机
2. **那次启动没有 journal 条目** → journald 都没起来，卡在更早的阶段
3. `flashboot getvar current-slot` → **`b`**

三点合起来：bootloader 把 A 槽标记为不可用并切到了 B 槽，而 B 槽没有可用系统。

### 为什么"能 ping 通"

我们的 initramfs 与 rootfs 都会拉起 USB NCM，所以网络层能通；
但用户态服务一个都没起来，表现就是"能通但什么都连不上"。

> 排查提示：**"能 ping 通"不等于"系统起来了"**。
> 判断依据应该是端口监听状态和 journal 是否有本次启动记录。

### 恢复

```sh
fastboot getvar current-slot
fastboot --set-active=a
fastboot reboot
```

### 交付要求

- 每次刷机后**必须**确认 `current-slot: a`
- 交付文档必须写明 `fastboot --set-active=a` 这条救援命令
- 槽位状态存在 `/dev/sda3`（`misc`），不要随意擦写

---

## 四、故障 2：用户名改名只做了一半

### 错误做法

```sh
usermod -l ubuntu -d /home/ubuntu -m penguin     # ← 这里失败了
groupmod -n ubuntu penguin                       # ← 但这个成功了
sed -i 's/penguin/ubuntu/' /etc/greetd/config.toml   # ← 这个也成功了
sed -i 's/^penguin /ubuntu /' /etc/sudoers.d/90-penguin-nopasswd  # ← 还有这个
```

`usermod` 报：

```
usermod: user penguin is currently used by process 793
```

（用户还有运行中的 Phosh 会话进程）

于是留下：**组叫 `ubuntu`、用户叫 `penguin`、greetd 指向 `ubuntu`**。

### 雪上加霜：sudoers 一改，后续 sudo 全部失效

`sed 's/^penguin /ubuntu /' /etc/sudoers.d/90-penguin-nopasswd` 一旦执行，
规则里的用户就变成 `ubuntu`，`penguin` **立刻失去免密 sudo**。
脚本里后续所有 `sudo mv ...` 全部报：

```
sudo: a terminal is required to read the password
```

结果 `/etc/sudoers.d/90-ubuntu-nopasswd` 改名、`/home` 移动、accounts 缓存迁移
全部没做 —— 状态进一步割裂。

### 正确的做法

**不要在活系统上改用户名。** 应该在镜像构建阶段离线改（没有运行中的进程）。
如果非要在活系统上做，必须：

1. 一次性用 **root** 执行（比如 23 端口 root shell），不要依赖会被改掉的 sudoers
2. 或者直接改文件而不调 `usermod`（uid 不变，运行中进程不受影响）：

```sh
sed -i 's/^penguin:/ubuntu:/' /etc/passwd /etc/shadow
sed -i 's|:/home/penguin:|:/home/ubuntu:|' /etc/passwd
sed -i 's/\bpenguin\b/ubuntu/g' /etc/group /etc/gshadow     # ← 附加组成员！最容易漏
mv /home/penguin /home/ubuntu
# 然后才是 greetd / getty / sudoers / helper / subuid / accounts
```

3. **顺序**：先把所有需要 sudo 的动作做完，**最后**再改 sudoers
4. 改完立刻重启验证

### 两个容易漏的点

**（1）附加组成员在 `/etc/group` 里**

`usermod -l` 会自动处理，但手工改文件时很容易只改 `/etc/passwd`。漏掉会导致：

```
id ubuntu → groups=1000(ubuntu)          ← 只剩主组
```

于是失去 `sudo` / `audio` / `video` / `plugdev` / `input` / `render`，
音频、输入设备、GPU 访问全部受影响。

**（2）`accounts-daemon` 的缓存目录**

`/var/lib/AccountsService/users/penguin` 里存着图标路径 `/home/penguin/.face`，
要跟着改名，否则设置里的用户图标会丢。

---

## 五、故障 3：救援脚本自己的 bug

回退脚本把 `90-ubuntu-nopasswd` 改名回 `90-penguin-nopasswd`，但
**只改了文件名、没有改文件内容**：

```
$ grep -h '^[a-z]' /etc/sudoers.d/90-penguin-nopasswd
ubuntu ALL=(ALL) NOPASSWD:ALL        ← 文件名 penguin，内容 ubuntu
```

结果恢复后 `penguin` 依然没有免密 sudo，所有 `sudo` 操作要密码。

修正：

```sh
sed -i 's/^ubuntu /penguin /' /etc/sudoers.d/90-penguin-nopasswd
```

**教训**：改名类脚本里，"文件改名"和"文件内容改名"必须成对出现，
并且要在脚本末尾**打印校验结果**（本次就是靠 `grep -h '^[a-z]'` 才发现的）。

---

## 六、救援流程（可复用）

### 6.1 构建救援 initramfs

```sh
# 1) 写回退脚本 rescue-revert-init.sh（幂等，失败也继续 switch_root）
# 2) 用它构建镜像
python3 tools/build_rescue_revert.py
#    → out/ut-test/revert-vendor_boot_a.img
```

### 6.2 刷入

```sh
fastboot getvar current-slot
fastboot --set-active=a
fastboot flash vendor_boot_a out\ut-test\revert-vendor_boot_a.img    # 只刷 initramfs，不动内核
fastboot reboot
```

### 6.3 重要：用完必须刷回正常 initramfs

回退版 initramfs 每次开机都会执行 `ubuntu → penguin`。如果之后系统里真的是
`ubuntu`，它会在开机时又改回去 —— **这是个地雷**。

```sh
python3 tools/build_mini_initramfs.py       # 用 ut-initramfs-init.sh 重建
fastboot flash vendor_boot_a out\ut-test\mini-vendor_boot_a.img
```

校验方式（比对比 manifest 里的 `init_sha256` 与脚本 sha256）：

```
ut-initramfs-init.sh    sha256: de358cdd…
manifest init_sha256:          de358cdd…      ✅ 正常版
rescue-revert-init.sh   sha256: 351d378b…      ← 不该出现在正式镜像里
```

---

## 七、附带修好：设置里改密码

`org.freedesktop.accounts.change-own-password` 默认要求 `auth_admin`，
需要 polkit 授权代理弹框；但 Phosh 环境没有任何代理
（`polkit-gnome` / `lxpolkit` 都没装，Phosh 自带也不带），所以直接失败。

加一条规则放行（单用户手机，用户已通过解锁证明身份）：

```js
// /etc/polkit-1/rules.d/50-pja110-account.rules
polkit.addRule(function (action, subject) {
    if (action.id == "org.freedesktop.accounts.change-own-password" &&
        subject.active) {
        return polkit.Result.YES;
    }
});
```

> 坑：最初写成 `subject.local && subject.active`，结果**通过 SSH 测试永远失败** ——
> SSH 会话 `subject.local == false`（远程）。设备本地的 Phosh 会话才是 `local`。
> 去掉 `local` 限制后两种场景都可用。

验证：

```
$ busctl --system call org.freedesktop.Accounts /org/freedesktop/Accounts/User1000 \
    org.freedesktop.Accounts.User SetPassword ss "testpass999" ""
（无输出 = 成功，无需认证）

shadow 字段: $y$j9T$qmGi92e3…（yescrypt，74 字节）  ← accounts-daemon 正确哈希
crypt('123456', stored) == stored                ✅
crypt('testpass999', stored) == stored           ✅ 否（已改回）
```

---

## 八、交付镜像的硬性要求（由本次事故得出）

1. **不改运行中的用户名** —— 改名放镜像构建阶段离线做
2. **每次刷机后确认 `current-slot: a`** —— 写进安装脚本和验收清单
3. **救援镜像用完即弃** —— 正式镜像里不得含任何"自动改名"逻辑
4. **改名脚本必须打印校验结果** —— 文件名与文件内容都要核
5. **`sudoers` 永远最后改** —— 或者干脆用 root 直接操作
6. **判断系统是否起来看端口和 journal**，不要只看 ping
