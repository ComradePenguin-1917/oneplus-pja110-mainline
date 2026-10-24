# PJA110 交付镜像 —— 安装脚本（Windows / PowerShell 版）
#
#   .\install.ps1 [-Bundle <目录>] [-Yes]
#
# 与 install.sh 等价，但在 Windows 上执行 —— fastboot 只在 Windows 侧能看到设备
# （WSL 没有 USB 直通）。
#
# 做的事：
#   1. 校验 fastboot 设备与槽位（槽位不是 a 就中止）
#   2. 用 SHA256SUMS 校验交付包完整性
#   3. 依次刷入 boot_a / vendor_boot_a / dtbo_a / userdata
#   4. 复查槽位并给出后续步骤
#
# 安全设计：
#   * 只操作 A 槽，绝不碰 B 槽
#   * 刷 rootfs 前必须二次确认（会覆盖 userdata）
#   * 任一 sha256 不符即中止

[CmdletBinding()]
param(
    [string]$Bundle = (Join-Path $PSScriptRoot 'bundle'),
    [switch]$Yes
)

$ErrorActionPreference = 'Stop'

function Write-Step($msg) { Write-Host "`n=== $msg ===" -ForegroundColor Cyan }
function Write-Ok($msg)   { Write-Host "  $msg" -ForegroundColor Green }
function Write-Warn2($msg){ Write-Host "  $msg" -ForegroundColor Yellow }
function Fail($msg)       { Write-Host "`nX $msg" -ForegroundColor Red; exit 1 }

function Invoke-Fastboot {
    param([Parameter(ValueFromRemainingArguments = $true)][string[]]$Args)
    $out = & fastboot @Args 2>&1
    return ($out | Out-String).Trim()
}

# ---------------------------------------------------------------- 环境
Write-Step '0. 环境检查'
if (-not (Get-Command fastboot -ErrorAction SilentlyContinue)) {
    Fail '找不到 fastboot（请安装 Android platform-tools 并加入 PATH）'
}
if (-not (Test-Path $Bundle)) { Fail "交付包目录不存在: $Bundle" }
foreach ($f in 'boot_a.img','vendor_boot_a.img','dtbo_a.img','rootfs.img','SHA256SUMS') {
    if (-not (Test-Path (Join-Path $Bundle $f))) { Fail "缺少 $Bundle\$f" }
}
Write-Ok "交付包: $Bundle"

# ---------------------------------------------------------------- 设备
Write-Step '1. 检查 fastboot 设备'
$devs = & fastboot devices 2>&1 | Where-Object { $_ -match '\S' }
if (-not $devs) {
    Fail "没有检测到 fastboot 设备。请让手机进入 fastboot（关机后按住音量下 + 电源）"
}
Write-Ok ($devs -join '; ')

# ---------------------------------------------------------------- 槽位
Write-Step '2. 检查槽位（必须是 a）'
$slotOut = Invoke-Fastboot getvar current-slot
$slot = if ($slotOut -match 'current-slot:\s*(\S+)') { $Matches[1] } else { '' }
Write-Host "  current-slot: $(if($slot){$slot}else{'未知'})"
if ($slot -ne 'a') {
    Write-Host ''
    Write-Host "当前槽位是 '$slot'，不是 'a'。" -ForegroundColor Red
    Write-Host '这通常意味着设备此前启动失败、bootloader 自动切到了 B 槽（B 槽没有系统）。' -ForegroundColor Red
    Write-Host ''
    Write-Host '请先执行：  fastboot --set-active=a' -ForegroundColor Yellow
    Write-Host '然后重新运行本脚本。' -ForegroundColor Yellow
    exit 1
}
Write-Ok '槽位正确'

# ---------------------------------------------------------------- 校验
Write-Step '3. 校验交付包（SHA256）'
$sums = Get-Content (Join-Path $Bundle 'SHA256SUMS') | Where-Object { $_ -match '\S' }
foreach ($line in $sums) {
    $parts = $line -split '\s+', 2
    $expect = $parts[0].ToLower()
    $file   = $parts[1].Trim()
    $path   = Join-Path $Bundle $file
    Write-Host "  $file ... " -NoNewline
    $actual = (Get-FileHash -Algorithm SHA256 -Path $path).Hash.ToLower()
    if ($actual -ne $expect) {
        Write-Host 'FAIL' -ForegroundColor Red
        Fail "校验失败: $file`n  期望 $expect`n  实际 $actual"
    }
    Write-Host 'OK' -ForegroundColor Green
}

# ---------------------------------------------------------------- 确认
Write-Step '4. 刷写前确认'
$sizes = @{}
foreach ($f in 'boot_a.img','vendor_boot_a.img','dtbo_a.img','rootfs.img') {
    $sizes[$f] = [math]::Round((Get-Item (Join-Path $Bundle $f)).Length / 1MB, 1)
}
Write-Host @"
即将刷入（只动 A 槽）：
  boot_a          <- boot_a.img          ($($sizes['boot_a.img']) MiB)
  vendor_boot_a   <- vendor_boot_a.img   ($($sizes['vendor_boot_a.img']) MiB)
  dtbo_a          <- dtbo_a.img          ($($sizes['dtbo_a.img']) MiB)
  userdata        <- rootfs.img          ($($sizes['rootfs.img']) MiB)

警告：刷 userdata 会完全覆盖手机上现有的根文件系统（包含所有数据）。
      sda6（/srv，15 GB 辅助卷）不在刷写范围内，但会保留旧内容。
"@

if (-not $Yes) {
    $a = Read-Host '确认继续？[y/N]'
    if ($a -notmatch '^(y|yes)$') { Fail '用户取消' }
}

# ---------------------------------------------------------------- 刷写
Write-Step '5. 刷写'
foreach ($pair in @(
    @('boot_a',        'boot_a.img'),
    @('vendor_boot_a', 'vendor_boot_a.img'),
    @('dtbo_a',        'dtbo_a.img')
)) {
    $part = $pair[0]; $img = Join-Path $Bundle $pair[1]
    Write-Host "  flash $part ..." -NoNewline
    $o = Invoke-Fastboot flash $part $img
    if ($o -notmatch 'OKAY|Finished') { Write-Host ' FAIL' -ForegroundColor Red; Fail $o }
    Write-Host ' OK' -ForegroundColor Green
}

Write-Host ''
Write-Warn2 '接下来刷 rootfs（约 8 GiB，视 USB 速率需要数分钟）…'
Write-Host ''
Write-Host '  flash userdata ...' -NoNewline
$o = Invoke-Fastboot flash userdata (Join-Path $Bundle 'rootfs.img')
if ($o -notmatch 'OKAY|Finished') { Write-Host ' FAIL' -ForegroundColor Red; Fail $o }
Write-Host ' OK' -ForegroundColor Green

# ---------------------------------------------------------------- 复查
Write-Step '6. 刷写后复查槽位'
$slotOut2 = Invoke-Fastboot getvar current-slot
$slot2 = if ($slotOut2 -match 'current-slot:\s*(\S+)') { $Matches[1] } else { '' }
Write-Host "  current-slot: $(if($slot2){$slot2}else{'未知'})"
if ($slot2 -eq 'a') { Write-Ok '槽位仍是 a' }
else { Write-Warn2 "槽位变成 $slot2！请执行 fastboot --set-active=a" }

# ---------------------------------------------------------------- 重启
Write-Step '7. 重启'
$o = Invoke-Fastboot reboot
Write-Host "  $o"

Write-Host ''
Write-Host '刷写完成，设备正在重启。' -ForegroundColor Green
Write-Host @'

首次启动会自动完成以下事项（无需人工干预）：
  · 重新生成 machine-id 与 SSH 主机密钥
  · 把根文件系统扩展到整个 userdata 分区（2.2 GiB -> 450 GiB，约 1 分钟）
  · 校正时区与 hostname 一致性

随后会弹出一次「Device name」向导，让你给设备起名。

默认账号：
  user:      ubuntu
  password:  123456
（设置 -> 用户 可改密码；设置 -> Wi-Fi 可配网络）

验证清单见同目录 ACCEPTANCE.md。
'@
