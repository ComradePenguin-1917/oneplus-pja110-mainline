# PJA110 系统级配置（替代原来的首启脚本）

原来的 `image/firstboot/` 全部删除。设备名、密码都可以在**设置**里改，
不需要自己的首启向导。但有三件事不能跟着一起删，否则系统会缺能力：

| 原本由首启脚本做的事 | 现在的替代 | 文件 |
| --- | --- | --- |
| 生成 SSH 主机密钥 | `ssh.service` 加一行 `ExecStartPre=ssh-keygen -A` | `ssh-host-keys.conf` |
| 根分区 8 GiB → 450 GiB | 幂等 oneshot `resize2fs`（满了立即返回） | `pja110-growfs.service` |
| 设置里改设备名 / 改密码 | polkit 放行三个 `auth_admin` 动作 | `50-pja110-account.rules` |

安装：`sudo ./install.sh`
