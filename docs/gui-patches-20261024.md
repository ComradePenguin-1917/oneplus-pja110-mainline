# GUI 组件补丁：虚拟键盘尺寸与处理器型号显示（2026-10-24）

本文记录两个必须改源码重新打包才能解决的 GUI 问题：

1. **虚拟键盘（stevia / `phosh-osk-stub`）**：按键区只有固定的 200 逻辑像素高，
   既不跟屏幕比例也不跟字号；改成按屏幕比例，并让字号/图标随之缩放。
2. **设置里的"处理器"（`gnome-control-center`）**：arm64 上显示成一串 CPU 核心名，
   改成显示 SoC 名称。

---

## 一、虚拟键盘 stevia（`phosh-osk-stub` 0.38.0）

### 1.1 上游状态

`phosh-osk-stub` 已改名 **stevia**，仓库 `https://gitlab.gnome.org/guidog/phosh-osk-stub`。
Ubuntu 24.04 只有 0.38.0，且**没有任何尺寸相关的 CLI 参数或 gsettings 键**。

### 1.2 根因

`src/pos-osk-widget.c`：

```c
#define KEY_HEIGHT 50
#define LAYOUT_ROWS 4

layer->key_height = KEY_HEIGHT;                        /* 固定 50 逻辑像素 */

*minimum_height = *natural_height = KEY_HEIGHT * LAYOUT_ROWS;   /* 固定 200 */
```

`src/pos-input-surface.c` 的 `pos_input_surface_check_resize()`：

```c
gtk_widget_get_preferred_size (GTK_WIDGET (self), &min, &nat);
if (gtk_widget_get_mapped (...) && min.height != self->height) {
    phosh_layer_surface_set_size (..., -1, min.height);        /* 用最小高度 */
    phosh_layer_surface_set_exclusive_zone (..., min.height);
}
```

所以键盘高度恒为 **200 逻辑像素**（在 1240×2772 / scale=2 下约占屏高 14.4%），
且 `self->height` 从未被赋值（恒为 0）→ 每次 `check_resize` 都调 `set_size`，
形成 resize 死循环。

### 1.3 三个补丁

#### 补丁 1：schema 新增两个键

`data/sm.puri.phosh.osk.gschema.xml`：

```xml
<key name="height-ratio" type='d'>
  <default>0.35</default>
  <range min="0.15" max="0.60"/>
  <summary>Fraction of the screen height occupied by the keyboard</summary>
</key>

<key name="label-scale" type='d'>
  <default>1.0</default>
  <range min="0.4" max="2.0"/>
  <summary>Scale factor for key labels and icons</summary>
</key>
```

#### 补丁 2：按屏幕比例定高

`src/pos-input-surface.c` 新增辅助函数与改写 `check_resize`：

```c
/* 取当前输出的逻辑高度 */
static int
pos_input_surface_get_monitor_height (PosInputSurface *self)
{
  GdkWindow *window = gtk_widget_get_window (GTK_WIDGET (self));
  if (!window) return 0;
  GdkMonitor *monitor = gdk_display_get_monitor_at_window (
                          gdk_window_get_display (window), window);
  if (!monitor) return 0;
  GdkRectangle geom;
  gdk_monitor_get_geometry (monitor, &geom);
  return geom.height;
}

/* check_resize 里：给 deck 设高度请求，让整条控件链自然算出目标高度 */
screen_h = pos_input_surface_get_monitor_height (self);
if (screen_h > 0 && self->height_ratio > 0.0) {
    GtkRequisition deck_min, deck_nat;
    int want = (int) (screen_h * self->height_ratio + 0.5);

    gtk_widget_get_preferred_size (GTK_WIDGET (self->deck), &deck_min, &deck_nat);
    int chrome = MAX (0, min.height - deck_nat.height);   /* 完成栏等占用的高度 */
    int deck_h = MAX (deck_min.height, want - chrome);

    gtk_widget_set_size_request (GTK_WIDGET (self->deck), -1, deck_h);
    gtk_widget_get_preferred_size (GTK_WIDGET (self), &min, &nat);
}
target = min.height;
```

**关键点**：只把 `phosh_layer_surface_set_size()` 的目标值改大是无效的
（第一次尝试就失败在这里）——GTK 控件的**自然高度仍是 200**，多余空间变成空白，
按键留在原位。必须给容器（`deck`）设高度请求，让自然高度真的变大。

同时把**比较对象从 `self->height`（恒为 0）改成 `"height"` 属性值**，消除死循环。

#### 补丁 3：键高均分 + 字号/图标按比例

`src/pos-osk-widget.c`：

```c
/* 键高 = 分配高度 / 行数，而不是固定 KEY_HEIGHT */
if (self->height > 0 && self->layout.n_rows > 0)
    layer->key_height = (double) self->height / self->layout.n_rows;
else
    layer->key_height = KEY_HEIGHT;

/* draw_key 里：字号与图标跟随键高（以原设计 KEY_HEIGHT 为基准） */
font_scale = (box->height / (double) KEY_HEIGHT) * self->label_scale;
```

`render_label` / `render_hint` / `render_icon` 都改成接收 `font_scale`：

```c
pango_font_description_set_size (
  font, MAX (1, (int) (pango_font_description_get_size (font) * font_scale)));

icon_size = MIN ((int) (KEY_ICON_SIZE * font_scale), box->height / 2);
```

这样改 `height-ratio` 时字号自动跟随，不需要再单独调。

### 1.4 一个真实的健壮性 bug

首次构建在测试阶段失败：

```
GLib-GIO-FATAL-ERROR: Settings schema 'sm.puri.phosh.osk'
                     does not contain a key named 'label-scale'
```

因为直接 `g_settings_get_double (..., "label-scale")`，遇到旧版 schema 会硬崩。
改成防御式读取：

```c
static gboolean
osk_schema_has_key (const char *key)
{
  GSettingsSchemaSource *source = g_settings_schema_source_get_default ();
  if (!source) return FALSE;
  g_autoptr (GSettingsSchema) schema =
    g_settings_schema_source_lookup (source, "sm.puri.phosh.osk", TRUE);
  return schema && g_settings_schema_has_key (schema, key);
}

/* init 里 */
self->label_scale = 1.0;
if (osk_schema_has_key ("label-scale")) { ...读取并监听... }
```

改完 **43 个测试全过**（`Ok: 43, Fail: 0`）。

### 1.5 结果

| 指标 | 修改前 | 修改后 |
| --- | --- | --- |
| 键盘高度 | 固定 200 逻辑像素（约 14.4% 屏高）| **35% 屏高**（`height-ratio` 可调）|
| 按键高度 | 50 逻辑像素 | 121 逻辑像素（485/4）|
| 字号 | 继承 GTK 默认 11pt，不随键盘变化 | 按 `键高/50` 自动缩放（约 26pt）|
| 图标 | 固定 16px | 同步缩放 |
| resize 死循环 | 有（`self->height` 恒 0）| 无 |

### 1.6 可调参数

```sh
gsettings set sm.puri.phosh.osk height-ratio 0.30   # 键盘占屏高 30%
gsettings set sm.puri.phosh.osk label-scale  1.2    # 字号再放大 20%
```

均为即时生效（重启 OSK 或重新展开键盘）。

### 1.7 用户侧 GTK 覆盖

`~/.config/gtk-3.0/gtk.css`：

```css
pos-key {
  margin: 3px;
}
```

**不要在这里设 `font-size`** —— 会与代码里的自动缩放叠加。

---

## 二、设置里的"处理器"：`gnome-control-center` 46.7

### 2.1 现象

设置 → 关于 → 处理器 显示成核心组合：

```
Cortex-A715 × 2  Cortex-A710 × 2  Cortex-A510 × 3  …
```

### 2.2 根因

`panels/system/about/cc-system-details-window.c` 的 `get_cpu_info()`
依赖 **libgtop**：

```c
const char * const keys[] = { "model name", "cpu", "Processor", "Model Name" };
info = glibtop_get_sysinfo ();
...
for (j = 0; model == NULL && j != G_N_ELEMENTS (keys); ++j)
  model = g_hash_table_lookup (info->cpuinfo[i].values, keys[j]);
...
g_string_append_printf (cpu, "%s × %d", cleanedup, count);
```

arm64 的 `/proc/cpuinfo` **没有 `model name` / `Processor` 字段**（架构特性）：

```
processor   : 0
BogoMIPS    : 38.40
CPU implementer : 0x41
CPU part    : 0xd46          ← 只有核心 ID
CPU revision    : 1
```

前几个键全部落空，于是用了 libgtop 合成的 `"cpu"` 键 ——
内容是**从 CPU part ID 翻译出来的核心名**（`lscpu` 显示同样的结果）。

**可用的正确数据源一直存在，只是没人用**：

```
/sys/devices/soc0/family   → Snapdragon
/sys/devices/soc0/machine  → SM8550
```

### 2.3 补丁

```c
/* arm64 has no "model name" in /proc/cpuinfo, so libgtop falls back to the
 * per-core names (e.g. "Cortex-A715"). Prefer the SoC identification the
 * kernel exposes so the About panel shows something meaningful. */
static char *
get_soc_name (void)
{
  g_autofree char *family = NULL;
  g_autofree char *machine = NULL;

  if (!g_file_get_contents ("/sys/devices/soc0/family", &family, NULL, NULL))
    return NULL;
  if (!g_file_get_contents ("/sys/devices/soc0/machine", &machine, NULL, NULL))
    return NULL;

  g_strstrip (family);
  g_strstrip (machine);

  if (*family == '\0' || *machine == '\0')
    return NULL;

  return g_strdup_printf ("%s %s", family, machine);
}

char *
get_cpu_info ()
{
  g_autofree char *soc_name = get_soc_name ();

  if (soc_name)                    /* 有 SoC 信息就优先用 */
    return g_steal_pointer (&soc_name);

  ... 原 libgtop 逻辑不变（x86 等平台完全不受影响）...
}
```

### 2.4 结果

设置 → 关于 → 处理器 显示：**`Snapdragon SM8550`**

---

## 三、构建与产物

两个包都是在设备上原生编译（arm64），先启用 `deb-src` 再 `apt-get build-dep`。

```sh
# 启用源码仓库
sudo sed -i 's/^Types: deb$/Types: deb deb-src/' /etc/apt/sources.list.d/ubuntu.sources
sudo apt-get update

# stevia
cd /path/to/stevia-src && dpkg-buildpackage -b -uc -us

# gnome-control-center
cd /path/to/gcc-src && dpkg-buildpackage -b -uc -us
```

### 产物

`out/stevia-0.38.0-pja1102/`：

| 文件 | 行数 | 说明 |
| --- | --- | --- |
| `0001-schema-height-ratio-label-scale.patch` | 31 | 两个新设置键 |
| `0002-input-surface-screen-ratio.patch` | 103 | 按屏幕比例定高 + 修死循环 |
| `0003-osk-widget-fill-and-scale-labels.patch` | 202 | 键高均分 + 字号/图标缩放 |
| `phosh-osk-stub_0.38.0-1pja1102_arm64.deb` | — | sha256 `3cc48be1…` |
| `stevia-0.38.0-pja1102-src.tar.gz` | — | 打完补丁的完整源码 |

`out/gcc-46.7-pja1101/`：

| 文件 | 行数 | 说明 |
| --- | --- | --- |
| `0001-about-show-soc-name.patch` | 42 | SoC 名称优先 |
| `gnome-control-center_46.7-…pja1101_arm64.deb` | — | sha256 `58d3a3dd…` |
| `gnome-control-center-data_46.7-…pja1101_all.deb` | — | sha256 `5cac7c7c…` |

> g-c-c 的 `-data` 包必须与主包**同版本**一起装，否则 `dpkg -i` 会报
> `dependency problems - leaving unconfigured`。

### 回滚

```sh
sudo apt-get install --reinstall phosh-osk-stub=0.38.0-1
sudo apt-get install --reinstall gnome-control-center=1:46.7-0ubuntu0.24.04.6 \
                              gnome-control-center-data=1:46.7-0ubuntu0.24.04.6
```

（需先把自建包降级，`apt-get install --reinstall` 指定版本即可，前提是
仓库里该版本仍可用。）

---

## 四、构建依赖：安装与清理

编译这两个包安装了约 **350 个构建依赖**（`-dev` 包、`meson`、`gtk-doc`、交叉编译器、`debhelper` 等）：

| 阶段 | 包数 |
| --- | --- |
| GUI 精简后 | 794 |
| 装完 stevia 构建依赖（2026-10-24 15:51，213 个）| 1009 |
| 装完 g-c-c 构建依赖（2026-10-24 16:48，139 个）| 1148 |
| 装 udisks2（16 个，**保留**）| 1164 |
| **清理后** | **810** |

### 4.1 为什么 `apt autoremove` 只删了 1 个包

`apt-get build-dep` 会把依赖标记为 **manual**（而非 auto），所以 `autoremove`
认为它们"用户显式安装"，一个都不删。

### 4.2 正确的清理方法：从 apt 历史精确还原

`/var/log/apt/history.log` 记录了每次事务的完整安装列表，按
`Commandline: apt-get build-dep` 筛出那两个事务，得到 352 个包名，
再 `apt-mark auto` 它们，最后 `apt-get autoremove --purge`：

```python
# 解析 history.log 中 build-dep 事务的 Install: 行
# → /tmp/rmlist.txt
sudo apt-mark auto $(cat /tmp/rmlist.txt)
sudo apt-get autoremove --purge -y     # 删 292 个（60 个仍被依赖，自动保留）
```

### 4.3 必须显式保留的包

清理前先把这些改回 `manual`，否则会被当孤儿删除：

```sh
sudo apt-mark manual udisks2 libudisks2-0 kgx gnome-console \
  fonts-cantarell pja110-kernel-mods phosh-osk-stub \
  gnome-control-center gnome-control-center-data
```

| 包 | 原因 |
| --- | --- |
| `udisks2` | **上一轮清理就栽在这里** —— 删掉后 Disk Capacity 变 Unknown |
| `kgx` / `gnome-console` | 图形终端 |
| `fonts-cantarell` | 虚拟键盘字体 |
| `pja110-kernel-mods` | 自建内核模块包 |
| `phosh-osk-stub` / `gnome-control-center(-data)` | 自建补丁包 |

### 4.4 第二轮：编译器本体

第一轮之后 `gcc` / `g++` / `make` / `dpkg-dev` / `binutils` 仍在 ——
它们是 352 个包里的成员（标记 auto），但仍被 `debhelper`、`libtool` 等互相依赖，
所以 `autoremove` 保留了它们。显式删除：

```sh
sudo apt-get remove --purge -y \
  gcc g++ make dpkg-dev binutils cpp build-essential libc6-dev
# → 连带删除 17 个：gcc-13, g++-13, cpp-13, debhelper, libtool,
#   dh-autoreconf, x11-xserver-utils, g++-aarch64-linux-gnu, libstdc++-13-dev …
sudo apt-get autoremove --purge -y    # 再删 44 个孤儿
#   autoconf, automake, m4, patch, dwz, debugedit,
#   libasan8/libtsan2/libubsan1/liblsan0/libitm1/libhwasan0,
#   linux-libc-dev, po-debconf, intltool-debian …
```

### 4.5 结果

| 指标 | 清理前 | 清理后 |
| --- | --- | --- |
| 包数量 | 1164 | **810** |
| 磁盘占用 | 5070 MB | **4081 MB** |
| apt 缓存 | — | 76 KB |
| 残留 `-dev` / `-doc` 包 | 154 | **0** |
| 损坏包 | 0 | 0 |

与"GUI 精简后"的 794 相比，多出的 16 个正是本轮新增的功能性包
（udisks2 及其依赖、kgx/gnome-console、fonts-cantarell）。

**同时恢复了 apt 源配置**（关闭 `deb-src`）与清空了 `/var/cache/apt`。

### 4.6 注意：设备上已无编译能力

删除后 `gcc`/`g++`/`make`/`dpkg-buildpackage`/`objdump`/`strings` 均不可用。
若之后需要在设备上重编内核模块或打补丁包，先装回：

```sh
sudo apt-get install -y build-essential dpkg-dev
# 并在 /etc/apt/sources.list.d/ubuntu.sources 里把 Types 加回 deb-src
```

