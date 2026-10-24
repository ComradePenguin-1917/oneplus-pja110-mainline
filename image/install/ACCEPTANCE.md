# PJA110 交付镜像 —— 安装后验收清单

刷写完成、设备重启后按顺序确认。任一项不符请记录现象。

> **本版变化**：已删除全部首启脚本（设备名、密码都能在「设置」里改）。
> 首次开机只需自动完成两件事：**生成 SSH 主机密钥**、**把根分区扩到整盘**。

---

## 0. 刷写阶段（PC 上）

- [ ] `fastboot getvar current-slot` → **`a`**
- [ ] `sha256sum -c SHA256SUMS` 全部 `OK`
- [ ] 三个引导分区刷写均返回 `OKAY`（`boot_a` / `vendor_boot_a` / `dtbo_a`）
- [ ] 刷写后再次 `getvar current-slot` 仍为 **`a`**

> ⚠️ **`userdata` 不能直接用 `fastboot flash`** —— `max-download-size` 只有 768 MiB，
> 8 GiB 镜像会被切成 5 块，fastboot 34.0.5 在 Windows 上转 sparse 时会报
> `Error reading sparse file`。用 `docs/delivery-image-20261024.md` 里的
> **initramfs 安装器**方案（从 `/dev/sda6` 上的镜像 dd 到 `/dev/sda14`）。

---

## 1. 首次开机（全自动，无向导）

开机后等 1–2 分钟，然后：

```sh
ping 172.16.42.1        # 不适用（无 NCM）
# 用 Wi-Fi：设置 → Wi-Fi 连上后
ssh ubuntu@<IP>         # 密码 123456
```

- [ ] **没有任何向导弹窗**（不再问设备名 / 密码）
- [ ] 能进 Phosh 桌面

登录后确认：

```sh
df -h /                          # 期望 Size ≈ 450G（不是 8G）
ls /etc/ssh/ssh_host_*_key | wc -l   # 期望 3
cat /etc/hostname                # 期望 pja110
grep 127.0.1.1 /etc/hosts        # 期望 127.0.1.1  pja110
```

- [ ] 根分区已扩到 ~450 GB
- [ ] SSH 主机密钥 3 个（由 `ssh.service` 的 drop-in 生成）
- [ ] hostname 与 `/etc/hosts` 一致
- [ ] `systemctl is-active pja110-growfs` → `active`

---

## 2. 设置里的两个「原本要做首启」的操作

**必须能真正保存成功**（这依赖 polkit 规则，没有它就会报
`Interactive authentication required`）：

- [ ] **设置 → 关于 → 设备名**：改成别的名字 → 保存成功 → `hostname` 跟着变
- [ ] **设置 → 用户 → 密码**：改密码 → 保存成功 → 新密码能登录

命令行等价验证：

```sh
hostnamectl set-hostname pja110-test && hostname     # 应成功
hostnamectl set-hostname pja110
```

- [ ] 两条命令都无 `Interactive authentication required` 报错

---

## 3. 账号与权限

```sh
id
# 期望 uid=1000(ubuntu) gid=1000(ubuntu)
#      groups=1000(ubuntu),27(sudo),29(audio),44(video),46(plugdev),994(render),997(input)
getent passwd penguin        # 期望无输出
```

- [ ] 用户 `ubuntu`，6 个附加组齐全
- [ ] 无 `penguin` 残留
- [ ] 密码 `123456` 可登录

---

## 4. 硬件功能

```sh
nmcli -t -f DEVICE,STATE,CONNECTION device | grep wlp1s0   # connected
systemctl is-active bluetooth                              # active
grep -c Synaptics /proc/bus/input/devices                  # 1
systemctl is-active fastcharge                             # active
cat /sys/class/remoteproc/remoteproc*/state                # running
systemctl is-active udisks2                                # active
cat /sys/class/power_supply/bq28z610-0/capacity            # 电量数字
```

- [ ] Wi-Fi 可连接
- [ ] 蓝牙 active
- [ ] 触摸可用
- [ ] 快充 active
- [ ] ADSP running
- [ ] udisks2 active
- [ ] 电量可读

---

## 5. 显示与虚拟键盘

- [ ] 屏幕点亮、无花屏
- [ ] 设置 → 显示器 可切 60/120 Hz
- [ ] 虚拟键盘占屏幕约 **35%** 高度，按键铺满
- [ ] 键盘字号与按键成比例

```sh
cat /sys/module/panel_oneplus_aa536/parameters/refresh    # 60 或 120
gsettings get sm.puri.phosh.osk height-ratio              # 期望 0.35
gsettings get sm.puri.phosh.osk label-scale               # 期望 1.0
```

---

## 6. 设置应用

- [ ] Settings 能打开
- [ ] **关于**：处理器显示 `Snapdragon SM8550`；Disk Capacity ≈ **507 GB**（不是 Unknown）
- [ ] Console（kgx）能打开

```sh
for b in /usr/bin/gnome-control-center /usr/bin/kgx /usr/bin/phoc /usr/bin/phosh; do
  printf '%-24s 缺失库 %s\n' "$(basename $b)" "$(ldd "$b" 2>/dev/null | grep -c 'not found')"
done
```

---

## 7. 设备树身份

```sh
tr -d '\0' < /sys/firmware/devicetree/base/model          # OnePlus PJA110
tr -d '\0' < /sys/firmware/devicetree/base/compatible     # oneplus,pja110 qcom,sm8550
hostnamectl chassis                                      # handset
```

- [ ] `model` = `OnePlus PJA110`
- [ ] `compatible` 首项 = `oneplus,pja110`
- [ ] `chassis` = `handset`

---

## 8. USB：MTP（不是网卡）

- [ ] 插到 PC 后，资源管理器出现 **便携式设备 `PJA110`**
- [ ] 能往里面拷文件（落到手机的 `~/Shared`）
- [ ] PC 上**不再出现**新的网络适配器（NCM 已移除）

```sh
ls /sys/kernel/config/usb_gadget/g1/functions      # 期望只有 ffs.mtp
cat /sys/kernel/config/usb_gadget/g1/UDC           # 期望 a600000.usb
pgrep -x umtprd                                    # 有 PID
for u in pja110-usb-gadget pja110-usb-bind umtp-responder; do systemctl is-active $u; done
systemctl is-enabled ut-usb-ncm ut-shell           # 都应是 disabled
```

- [ ] gadget 只有 `ffs.mtp`，UDC 已绑定
- [ ] `umtprd` 运行中
- [ ] `ut-usb-ncm`、`ut-shell` 都是 `disabled` / `inactive`

---

## 9. 辅助卷（/srv）

```sh
findmnt /srv && df -h /srv
```

- [ ] `/srv` 已挂载（15 GB）

> 交付镜像不刷 `sda6`，所以这里会保留上一台系统的旧内容。
> 交付前可以用 `sudo rm -rf /srv/*` 清空（注意别删 `/srv/pja110-*` 之外有用的东西）。

---

## 10. 回归：重启一次

- [ ] 重启后能进桌面
- [ ] **没有向导弹窗**
- [ ] Wi-Fi 自动重连
- [ ] `systemctl is-system-running` → `running`
- [ ] `systemctl --failed` → 空
- [ ] 根分区仍是 450G（`pja110-growfs` 无副作用）

---

## 失败时的处置

**永远先做这一件事**：

```sh
fastboot getvar current-slot     # 期望 a
```

| 现象 | 处置 |
| --- | --- |
| 反复显示开机 logo（循环重启）| 先查槽位；若 `misc` 里残留过启动命令，`fastboot flash misc` 写 32 字节零清零 |
| 能 ping 但没服务 | 已无 NCM，此症状不存在；改看 Wi-Fi 与端口 |
| SSH 连不上但桌面正常 | `ls /etc/ssh/ssh_host_*_key`；缺失就 `sudo ssh-keygen -A` |
| 根分区还是 8G | `systemctl status pja110-growfs`；手动 `sudo resize2fs /dev/sda14` |
| 设置里改设备名/密码报错 | 检查 `/etc/polkit-1/rules.d/50-pja110-account.rules` 是否存在、`systemctl status polkit` |
| PC 看不到 MTP 设备 | `ls /sys/kernel/config/usb_gadget/g1/functions`；`systemctl status umtp-responder pja110-usb-bind` |
