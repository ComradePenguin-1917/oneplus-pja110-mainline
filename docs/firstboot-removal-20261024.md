# 删除首启脚本（2026-10-24 晚）

用户提出：**设备名和密码都能在「设置」里改，首启脚本是多余的，全部去掉。**

结论：确实多余，但不能裸删 —— 有两件事原本挂在首启脚本上，删掉会让系统缺能力。
本文记录「删了什么、用什么替代、怎么验证」。

---

## 一、删掉的东西

| 文件 | 原用途 |
| --- | --- |
| `/usr/local/sbin/pja110-firstboot` | 静默首启：machine-id、SSH 主机密钥、时区、`/etc/hosts` 对齐、resize2fs |
| `/usr/local/sbin/pja110-firstboot-helper` | 提权入口（set-hostname / set-password / mark-done）|
| `/usr/local/bin/pja110-firstboot-wizard` | zenity 单页向导（设备名）|
| `/etc/systemd/system/pja110-firstboot.service` | 静默首启的 unit |
| `/etc/xdg/autostart/pja110-firstboot-wizard.desktop` | 向导的桌面自启项 |
| `/etc/sudoers.d/pja110-firstboot` | helper 的窄 sudo 规则 |
| `/var/lib/pja110/` | 两个 marker（`firstboot-done` / `firstboot-system-done`）|

工作区里对应的 `image/firstboot/` 整个目录也已删除。

---

## 二、为什么不能裸删：三件事必须换地方

### 1. SSH 主机密钥（否则 sshd 起不来）

`ssh.service` 在本系统上**只有** `ExecStartPre=/usr/sbin/sshd -t`，**不会**自动生成主机密钥
（Debian/Ubuntu 是在包安装时生成的）。镜像里删掉了密钥，如果不补，`sshd` 会因缺密钥失败。

替代：一个 drop-in

```ini
# /etc/systemd/system/ssh.service.d/10-pja110-host-keys.conf
[Service]
ExecStartPre=/usr/bin/ssh-keygen -A
```

> 坑：路径必须是 **`/usr/bin/ssh-keygen`**。写成 `/usr/sbin/ssh-keygen` 会
> `No such file or directory` —— usrmerge 之后 `/usr/sbin` 里只有 `sshd`。

`ssh-keygen -A` 只补缺失的密钥，已有的不动，所以幂等。

**演练记录**（在设备上真实做过）：

```
删除后密钥数: 0
ssh-keygen: generating new host keys: RSA ECDSA ED25519
重新生成后密钥数: 3
幂等再跑一次: （无输出）
sshd 配置校验: OK
```

### 2. 根分区扩容（否则只有 8 GiB）

交付镜像是 8 GiB，userdata 分区是 450 GiB。不扩容的话用户只剩 5.6 GiB 可用。

替代：一个幂等的 oneshot unit（**不需要 marker**，`resize2fs` 在已占满时立即成功返回）

```ini
# /etc/systemd/system/pja110-growfs.service
[Unit]
Description=Grow root filesystem to fill its partition
After=local-fs.target
ConditionPathIsMountPoint=/
ConditionPathExists=/dev/sda14

[Service]
Type=oneshot
RemainAfterExit=yes
ExecStart=/usr/sbin/resize2fs /dev/sda14

[Install]
WantedBy=multi-user.target
```

实测：安装后立即执行一次 → `/dev/sda14 450G 2.3G 448G 1% /`。

### 3. 设置里改设备名 / 改密码（否则报错）

实测两个动作的 polkit 默认要求：

```
org.freedesktop.hostname1.set-static-hostname   auth_admin_keep
org.freedesktop.hostname1.set-hostname          auth_admin_keep
org.freedesktop.accounts.change-own-password    auth_admin
```

而 Phosh 环境**没有任何 polkit 授权代理**，所以：

```
$ hostnamectl set-hostname pja110-probe
Could not set pretty hostname: Interactive authentication required.
```

也就是说**设置里能看到输入框、但点保存会失败**。必须放行：

```js
// /etc/polkit-1/rules.d/50-pja110-account.rules
polkit.addRule(function (action, subject) {
    if (!subject.active) { return; }
    if (action.id == "org.freedesktop.accounts.change-own-password")      { return polkit.Result.YES; }
    if (action.id == "org.freedesktop.hostname1.set-static-hostname")     { return polkit.Result.YES; }
    if (action.id == "org.freedesktop.hostname1.set-hostname")            { return polkit.Result.YES; }
});
```

加规则后实测通过：

```
$ hostnamectl set-hostname pja110-probe && hostname
pja110-probe            ← 成功，无报错
```

---

## 三、还需要注意的两点

### 删掉首启脚本后，machine-id 由谁生成

systemd 自己会在启动早期生成。原来静默脚本里的 "machine-id: 已存在，跳过"
就是因为它跑在 systemd 之后 —— 这段本来就是冗余的。

### `/etc/hosts` 的 `127.0.1.1`

原来由静默脚本兜底校正。现在改设备名时，`hostnamed` 会同步 `/etc/hosts`
（它自己维护那一行）。若出现不一致（`sudo: unable to resolve host xxx`），手工修：

```sh
sudo sed -i -E 's|^127\.0\.1\.1.*|127.0.1.1\t'"$(hostname)"'|' /etc/hosts
```

本次就是这么修的（设备名曾被向导改成 `test`，`/etc/hosts` 还写着 `pja110`）。

---

## 四、MTP 重启后 PC 端看不到（顺带修掉）

重启后出现过：系统正常、`ffs.mtp` 已绑 UDC、`umtprd` 在跑，但 Windows 里
**看不到 `PJA110`**。

- 设备侧完全正常（`/dev/ffs-mtp/ep0..ep3` 都在、`UDC=a600000.usb`）
- 手动 `echo "" > UDC; sleep 2; echo a600000.usb > UDC` → Windows 立刻认到

原因：设备 5 秒就起完，UDC 绑得太快，主机会来不及处理「上一次的断开」，
于是保留一个已死的设备实例、不再重新枚举。

修法：`usb-gadget.sh bind` 在绑 UDC 前先等 5 秒（可用 `PJA110_USB_SETTLE=0` 关闭）。

复现与恢复命令：

```sh
# 恢复（无需重启）
sudo sh -c 'echo "" > /sys/kernel/config/usb_gadget/g1/UDC; sleep 2; echo a600000.usb > /sys/kernel/config/usb_gadget/g1/UDC'
```

---

## 五、验证结果（设备上实测）

```
hostname                    pja110
systemctl is-system-running running
失败单元                    0
启动耗时                    1.455s (kernel) + 4.010s (userspace) = 5.466s
根分区                      450G  2.3G  1%
首启组件残留                无
SSH 主机密钥                3 个，ssh.service 的 drop-in 在位
pja110-growfs               enabled / active (exited, status=0/SUCCESS)
普通用户改设备名             成功（无 Interactive authentication required）
MTP（重绑 UDC 后）          Windows 侧 Status=OK, WPD, PJA110
```

---

## 六、交付镜像要跟着做的

`image/system/` 下有三个文件 + 安装脚本：

```
image/system/
  ssh-host-keys.conf          → /etc/systemd/system/ssh.service.d/10-pja110-host-keys.conf
  pja110-growfs.service       → /etc/systemd/system/pja110-growfs.service
  50-pja110-account.rules     → /etc/polkit-1/rules.d/50-pja110-account.rules
  install.sh                  → 以上三项 + 顺手清掉旧首启组件
```

`image/build/build-rootfs.sh` 里原先「复位首启 marker」那一步已改为
「检查 `pja110-growfs.service` 在位」，不再依赖任何 marker 文件。
