# WCN7850 蓝牙移植记录（PJA110 / SM8550）

更新：2026-10-20。状态：**✅ 已完全打通**（上电、固件、HCI、扫描全部正常）。

本文记录从「完全不可用」到「可扫描周边设备」的完整过程，包括五个被证伪的假设。下次接手时读这一份即可。

## 1. 结论（一句话）

蓝牙能工作只靠**一处设备树改动**：在 `swctrl` / 供电之外，给 `bluetooth` 节点加 `local-bd-address`。**内核未做任何修改。**

## 2. 最终验证结果

```
hci0:  Type: Primary  Bus: UART
       BD Address: 02:00:00:00:5A:AD  ACL MTU: 1024:7  SCO MTU: 240:4
       UP RUNNING
       RX bytes:2204  events:129  errors:0
       TX bytes:289792 commands:1239  errors:0
       Features: 0xff 0xfe 0x0f 0xfe 0xd8 0x3f 0x5b 0x87

bluetoothctl show:
  Controller 02:00:00:00:5A:AD (public)
    Manufacturer: 0x001d (Qualcomm)
    Version: 0x0d (13)
    Name: PJA110
    Powered: yes / Pairable: yes
    UUID: A/V Remote Control, Audio Source ...

bluetoothctl scan on:
  [NEW] P20P-ED2C / JY0003 / ...  RSSI -72 ~ -105 dBm
```

## 3. 硬件与软件基线

| 项 | 值 |
| --- | --- |
| 蓝牙芯片 | WCN7850（与 Wi-Fi 同芯片，代号 kiwi） |
| 传输 | UART，`serial@898000`（uart14，别名 `hsuart0`） |
| 设备节点 | serdev `serial0-0` |
| 驱动链 | `hci_uart` + `btqca` + `pwrseq_qcom_wcn` |
| 固件 | `qca/hmtbtfw20.tlv` + `qca/hmtnv20.bin` |

**注意**：`/dev/ttyMSM0` 是 `serial@a9c000`（uart7，debug-uart），**不是蓝牙**。早期误绑此口造成「手动 btattach 成功」的假象。

## 4. 最终 DTB 配置（`source-patches.json` 第 2 条 replacement）

```dts
serial@898000 {
    compatible = "qcom,geni-uart";
    reg = <0x00 0x898000 0x00 0x4000>;
    clock-names = "se";
    clocks = <0x30 0x7b>;
    pinctrl-names = "default";
    pinctrl-0 = <0x47 0x48>;      /* TX/RX + CTS/RTS，两者都必须保留 */
    interrupts = <0x00 0x1cd 0x04>;
    interconnects = <0x32 0x02 0x00 0x32 0x05 0x00 0x33 0x02 0x00 0x34 0x1d 0x00>;
    interconnect-names = "qup-core\0qup-config";
    status = "okay";
    phandle = <0x12f>;

    bluetooth {
        compatible = "qcom,wcn7850-bt";
        local-bd-address = [ad 5a 00 00 00 02];   /* 小端，显示为 02:00:00:00:5A:AD */
        swctrl-gpios = <0x78 0x52 0x00>;          /* tlmm GPIO 82 */

        vddrfacmn-supply = <0x1f9>;
        vddaon-supply    = <0x1fa>;
        vddwlcx-supply   = <0x1fb>;
        vddwlmx-supply   = <0x1fc>;
        vddrfa0p8-supply = <0x1fe>;
        vddrfa1p2-supply = <0x1ff>;
        vddrfa1p8-supply = <0x200>;

        max-speed = <0x30d400>;                   /* 3200000 */
    };
};
```

引脚：`qup-uart14-default-state`（0x47）= gpio78/79，`qup-uart14-cts-rts-state`（0x48）= gpio76/77。

## 5. 根因：BD_ADDR 触发 `HCI_UNCONFIGURED`

### 5.1 现象

```
dmesg: QCA setup on UART is completed
       （之后无输出，没有 hci0 的 BD address）

hciconfig:  DOWN RAW
hciconfig hci0 up:  Can't init device hci0: Operation not supported (95)
btmgmt:     Index list with 0 items
```

### 5.2 代码级因果链

```
1. btqca.c:742  qca_check_bdaddr():
       若 public_addr == BDADDR_ANY 且芯片上报地址 == config->bdaddr
       则 set_bit(HCI_QUIRK_USE_BDADDR_PROPERTY)

2. hci_sync.c:4873  hci_dev_setup_sync():
       invalid_bdaddr = HCI_QUIRK_INVALID_BDADDR || HCI_QUIRK_USE_BDADDR_PROPERTY

3. hci_sync.c:4881
       if (USE_BDADDR_PROPERTY && public_addr == ANY)
           hci_dev_get_bd_addr_from_property(hdev);   /* 从 DT 读 local-bd-address */

4. hci_sync.c:4886
       if (invalid_bdaddr && public_addr != ANY && set_bdaddr)
           set_bdaddr(...);  invalid_bdaddr = false;  /* DT 提供地址后清除 */

5. hci_sync.c:4899
       if (HCI_QUIRK_EXTERNAL_CONFIG || invalid_bdaddr)
           hci_dev_set_flag(hdev, HCI_UNCONFIGURED);

6. hci_sync.c:5322
       if (HCI_UNCONFIGURED) set_bit(HCI_RAW, ...);   /* 就是 hciconfig 看到的 RAW */

7. hci_core.c:438
       if (HCI_UNCONFIGURED && !HCI_USER_CHANNEL) return -EOPNOTSUPP;  /* 就是 95 */
```

**DT 提供 `local-bd-address` 后，第 3 步读到地址 → 第 4 步写入芯片并清除 `invalid_bdaddr` → 第 5 步不置 `HCI_UNCONFIGURED` → 一切正常。**

### 5.3 字节序

binding 文档（`bluetooth-controller.yaml`）明确：

> Formatted with least significant byte first (little-endian), e.g. in order to
> assign the address 00:11:22:33:44:55 this property must have the value
> `[55 44 33 22 11 00]`.

要显示 `02:00:00:00:5A:AD`，DT 写 `[ad 5a 00 00 00 02]`。

## 6. 被证伪的五个假设（勿重复尝试）

| # | 假设 | 做法 | 结果 |
| --- | --- | --- | --- |
| 1 | 缺 `vdddig` 导致 `-EPROBE_DEFER` | 加 `enable-gpios` + 补齐 6 路 regulator | 报 `Failed to init regulators:-517`。因为 `enable-gpios` 会强制走手动 regulator 路径，而 `vreg_pmu_*` 系列 LDO **从未注册成 regulator 设备**（46 个 regulator 里一个都没有）。**结论：不要加 `enable-gpios`，必须走 pwrseq 路径。** |
| 2 | 缺 `swctrl` GPIO 导致 IBS 失效 | 加 `swctrl-gpios = <&tlmm 82>` | 无变化。但**保留**了，与上游一致。 |
| 3 | CTS/RTS 流控阻塞发送 | 从 `pinctrl-0` 移除 `<0x48>` | 更糟：`hciconfig up` 仍报 95，且证明流控**必需**（`qca_open` 要求 `hci_uart_has_flow_control()`）。 |
| 4 | `max-speed` 3200000 非标准值 | 考虑改 3000000 | 未执行。termios 确实无 `B3200000` 常量（标准高值到 `B3500000`），但 `qcom_geni_serial` 接受任意整数波特率，且上游 QRD 同样用 3200000。不是根因。 |
| 5 | `qcom_geni_serial` 不支持 serdev 流控 | 准备改内核 | **完全错误**。6.14 的 `hci_uart_has_flow_control()` 对 serdev 直接 `return true`。读源码后推翻。 |

**另一个假象**：早期「手动 `btattach /dev/ttyMSM0 -S 3000000 -P qca` 成功、出现 `UP RUNNING`」是误判——`ttyMSM0` 是 debug-uart，没连到蓝牙芯片，那次只是创建了空 HCI 设备，`BD Address` 与 `ACL MTU 1024:8` 都是默认值。

## 7. 固件处理

`/lib/firmware/qca/hmtbtfw20.tlv`（270120 B）、`/lib/firmware/qca/hmtnv20.bin`（9508 B）。

**必须手动解压**：Ubuntu 的 `linux-firmware` 只提供 `.zst` 压缩版，而本内核 `CONFIG_FW_LOADER_COMPRESS_*` 全部未启用、`CONFIG_FW_LOADER_USER_HELPER` 也没有，内核读不了 `.zst`。

**文件名规则**（`btqca.c`）：

```c
case QCA_WCN7850:
    snprintf(name, "qca/hmtbtfw%02x.tlv", rom_ver);   /* rom_ver=0x200 → hmtbtfw20.tlv */
    snprintf(name, "qca/hmtnv%02x.bin", ...);          /* → hmtnv20.bin */
```

注意是 **`hmt`** 前缀，不是 `hp`（`hpbtfw21.tlv` 属于其他芯片）。

固件来源：`https://github.com/endlessm/linux-firmware/raw/master/qca/hmtbtfw20.tlv`（kernel.org 有 Anubis 反爬拦截）。

## 8. 供电：与上游 QRD 一致，无安全风险

`wcn7850-pmu` 的输入供电：

| 属性 | regulator | 电压 |
| --- | --- | --- |
| `vdd-supply` | `vreg_s5g_0p8` | 0.5–1.0 V |
| `vddio-supply` | `vreg_l15b_1p8` | 1.8 V 固定 |
| `vddaon-supply` | `vreg_s2g_0p8` | ≤1.0 V |
| `vdddig-supply` | `vreg_s4e_0p9` | 0.904–0.984 V |
| `vddrfa1p2-supply` | `vreg_s4g_1p3` | 1.2–1.352 V |
| `vddrfa1p8-supply` | `vreg_s6g_1p8` | 1.8–2.0 V |

蓝牙节点引用的 7 路是 **PMU 内部固定输出 LDO**（`vreg_pmu_*`，电压由 WCN7850 硬件决定，DT 不写电压范围），**独占给蓝牙/Wi-Fi**，不与其它外设共享。

驱动只做 `regulator_bulk_enable/disable` + `set_load`，**从不设置电压**，因此不存在「设错电压烧硬件」的风险。

## 9. 副作用：A/B 槽自动切换问题（已修复）

**现象**：刷机后重启偶发卡住（ping 通但 TCP 23 关闭），串口显示进入了 B 槽（pmOS RAM-root 调试环境，内核 `6.14.0-sm8550-xigua-r1`）。

**根因**：`misc` 分区（`/dev/sda3`）的 slot metadata 全 0：

```
offset 2048: 00 00 00 00 00 00 00 00
```

即 A 槽 `successful_boot=0`、`tries_remaining=0`，bootloader 判定启动失败后切换到 B 槽。Ubuntu rootfs 里没有 `qbootctl` 之类的标记机制，所以每次启动都不会更新。

**修复**（已执行，备份在设备 `/tmp/misc.bak`）：

```sh
# struct slot_metadata { u8 priority; u8 tries_remaining; u8 successful_boot; u8 verity_mode; }
printf '\017\007\001\000\000\000\000\000' | dd of=/dev/sda3 bs=1 seek=2048 conv=notrunc
sync
```

写入后：

```
0f 07 01 00   →  A: priority=15, tries=7, successful_boot=1
00 00 00 00   →  B: 全 0（不可引导）
```

**验证**：此后多次重启都稳定回到 A 槽。

**应急恢复**：若仍切到 B 槽，`fastboot --set-active=a` 即可。

## 10. 相关文件

| 用途 | 路径 |
| --- | --- |
| DT 补丁 | `postmarketos/device/testing/device-oneplus-xigua/dtb-source/source-patches.json`（第 2 条） |
| 编译后 DTB | `out/ut-test/oneplus-xigua-bt.dtb` |
| vendor_boot 构建 | `python3 tools/build_mini_initramfs.py`（读 `DTB` 变量） |
| 设备侧固件 | `/lib/firmware/qca/hmt{btfw20.tlv,nv20.bin}` |
| 关键诊断命令 | `hciconfig -a`；`cat /sys/kernel/debug/devices_deferred`；`bluetoothctl scan on` |

## 11. 刷机注意

- 只刷 `vendor_boot_a`，A 槽。
- 刷前 `fastboot getvar current-slot` 确认是 `a`。
- **禁止 `rmmod bluetooth`**：会导致系统异常。（此条已因 slot metadata 修复而风险降低，但仍不建议。）
- 重启 greetd 后 `initial_session` 只执行一次，重跑需 `rm -f /run/greetd/runfile`。
