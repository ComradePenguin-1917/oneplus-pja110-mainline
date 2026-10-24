# USB 模式改造：NCM 网卡 → MTP 文件传输（2026-10-24）

把 USB 从「一条网络链路」改成「一个文件传输设备」，并关掉随之而来的两个不安全入口。

---

## 一、改造前后

| 项 | 改造前 | 改造后 |
| --- | --- | --- |
| USB gadget 功能 | `ncm.usb0`（网卡）| `ffs.mtp`（MTP）|
| PC 上看到 | 一个网卡，`172.16.42.1` | 便携式设备 `PJA110` |
| 文件传输 | 只能 `scp` | 资源管理器里直接拖文件 |
| 设备侧接口 | `usb0`（NCM）| 无网络接口 |
| 暴露目录 | — | `~/Shared`（交付镜像里是 `/home/ubuntu/Shared`）|
| 远程访问 | USB `172.16.42.1` + Wi-Fi | **只能 Wi-Fi** |
| 23 端口 root shell | 开启（`ut-shell.service`）| **已关闭** |

---

## 二、内核支持

`/proc/config.gz` 里确认：

```
CONFIG_USB_CONFIGFS=y
CONFIG_USB_LIBCOMPOSITE=y
CONFIG_USB_F_FS=y                 ← FunctionFS，MTP 走 userspace 需要它
CONFIG_USB_CONFIGFS_F_FS=y
CONFIG_USB_F_MASS_STORAGE=y       ← UMS 本来也能做，本次未启用
CONFIG_USB_CONFIGFS_MASS_STORAGE=y
```

`CONFIG_USB_F_MTP`（内核自带 MTP 函数）没有，但那不是问题 ——
现代方案是 **FunctionFS + userspace 响应器**（`umtp-responder`），只需要 `F_FS`。

---

## 三、组件

| 文件 | 作用 |
| --- | --- |
| `/opt/pja110/usb-gadget.sh` | 手工搭 configfs gadget（`prep` / `bind` / `stop` / `status`）|
| `pja110-usb-gadget.service` | oneshot，建 gadget + 挂 functionfs |
| `umtp-responder.service` | `umtprd` 前台运行（覆写 Debian 单元）|
| `pja110-usb-bind.service` | oneshot，等 `umtprd` 就绪后绑 UDC |
| `/etc/umtprd/umtprd.conf` | `storage "<家目录>/Shared" "Shared" "rw"` |

### 启动顺序（关键）

```
1. pja110-usb-gadget.service   → 建 g1 + ffs.mtp，挂 functionfs 到 /dev/ffs-mtp
                                  （此时 ep0 出现，但 UDC 未绑）
2. umtp-responder.service      → umtprd 打开 ep0、写描述符、创建 ep1/ep2/ep3
3. pja110-usb-bind.service     → 轮询等 /dev/ffs-mtp/ep1 出现，再 echo <udc> > UDC
```

**为什么必须最后绑 UDC**：FunctionFS 模式下描述符由 userspace 提供。
如果先绑 UDC，主机会枚举到一个没有配置描述符的设备，枚举失败。

---

## 四、踩到的三个坑

### 坑 1：Debian 的 `umtprd-ffs` 不能直接用

包里的 `ExecStart=/usr/sbin/umtprd-ffs` 是个**示例脚本**：

```sh
mkdir cfg; mount none cfg -t configfs
mkdir cfg/usb_gadget/g1; cd cfg/usb_gadget/g1
mkdir functions/ffs.mtp
...
umtprd &        # 后台起，然后脚本就结束了
sleep 1
ls /sys/class/udc/ > cfg/usb_gadget/g1/UDC
```

脚本自己建 gadget、`umtprd &` 后退出 → systemd 认为服务结束（`Type=simple`），
而且 `umtprd` 变成孤儿进程。所以自己写 gadget 脚本 + 覆写单元。

### 坑 2：`PrivateDevices=yes` 让 `/dev/ffs-mtp/ep0` 不存在

第一次绑定失败，日志：

```
[uMTPrd - Error] init_usb_mtp_gadget : Unable to open /dev/ffs-mtp/ep0 (No such file or directory)
```

但宿主上 `ls /dev/ffs-mtp/` 明明有 `ep0`。原因是 Debian 单元自带
`PrivateDevices=yes` —— 服务跑在私有的 `/dev` 命名空间里，看不到 functionfs 的挂载点。

修复（drop-in `/etc/systemd/system/umtp-responder.service.d/pja110.conf`）：

```ini
[Service]
ExecStart=
ExecStart=/usr/bin/umtprd
PrivateDevices=no      # ← 关键
PrivateUsers=no
ProtectHome=no
ProtectSystem=no
NoNewPrivileges=no
Restart=always
```

`PrivateUsers=yes` 和 `ProtectHome=yes` 也要去掉，否则 `/home/ubuntu/Shared`
里的文件在服务命名空间里会变成 `nobody`，MTP 读写异常。

### 坑 3：配置里的家目录是硬编码

`umtprd.conf` 的 `storage` 是绝对路径。交付镜像要把用户从 `penguin` 改成 `ubuntu`，
所以 `rename-user-offline.sh` 里必须加一条：

```sh
subst etc/umtprd/umtprd.conf "s|/home/$OLD_USER|/home/$NEW_USER|g"
```

漏了这条，镜像里 MTP 会指向一个不存在的目录（`umtprd` 会静默给一个空存储）。

---

## 五、验证结果

### 设备侧

```
UDC available : a600000.usb
gadget dir    : 存在
UDC bound     : a600000.usb          ← 已绑定
functions     : ffs.mtp              ← 只有 MTP，没有 ncm
ffs mounted   : 是
ffs ep        : ep0 ep1 ep2 ep3
umtprd        : 运行中
```

### PC 侧（Windows）

```
Get-PnpDevice -Class WPD
  Status  FriendlyName   InstanceId
  OK      PJA110         USB\VID_1D6B&PID_0100\PJA110

资源管理器 → 便携式设备 → PJA110
```

### 单元状态

```
pja110-usb-gadget   enabled   active
pja110-usb-bind     enabled   active
umtp-responder      enabled   active
ut-usb-ncm          disabled  inactive
ut-shell            disabled  inactive
失败单元: 0
```

---

## 六、代价与注意事项

### 1. 远程访问只剩 Wi-Fi

关掉 NCM 后，`172.16.42.1` 不再存在。**交付镜像的 Wi-Fi 凭据是清空的**，
所以刷完机首次启动时：**没有任何远程访问通道**，必须用触摸屏配置 Wi-Fi。

排查时的顺序变成：
1. 看屏幕（Phosh 桌面 / 首启向导）
2. 触摸屏 → Console → 本地敲命令
3. 配好 Wi-Fi 后才能 SSH

### 2. `ut-usb-ncm.service` 仍保留，只是 disabled

需要临时恢复网卡模式时（在设备本地终端执行）：

```sh
sudo systemctl disable --now pja110-usb-gadget.service pja110-usb-bind.service
sudo systemctl enable  --now ut-usb-ncm.service
# 恢复后 PC 侧 172.16.42.1 又可访问
```

这条应急路径写进了验收文档。

### 3. `ut-shell.service`（23 端口 root shell）已关闭

它监听 `0.0.0.0:23`，任何能连上的人都是 root。原来的用途是 NCM 断了之后的救援通道，
现在 USB 不再是网络，留着只是风险。

需要应急 root shell 时：`sudo systemctl start ut-shell.service`（用完记得停）。

### 4. MTP 的可见范围是 `~/Shared`

不是整个家目录，也不是根文件系统。想传别的文件，先放到 `~/Shared` 里。
需要扩大范围时改 `umtprd.conf` 的 `storage` 行（可写多行，最多 16 个存储点）。

---

## 七、后续可选改进

| 项 | 说明 |
| --- | --- |
| 固定 USB MAC / serial | gadget 目前 serial 固定为 `PJA110`，但若要加 UMS 需注意 MAC |
| 加 UMS | 内核已支持，`mass_storage.0` 指向 `/dev/sda6` 即可；需 `/srv` 不自动挂载 |
| 加 ADB | 需要 `adbd`（Android 组件），mainline 上不常用 |
| MTP 加多个存储点 | 如 `~/Shared` + `/srv`，`storage` 可写多行 |
