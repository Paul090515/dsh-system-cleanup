# =============================================================================
# DSH system-cleanup — 保守的系统缓存/垃圾清理脚本（Windows / PowerShell）
#
# 安全设计（保守模式，与 cleanup.sh 对齐）：
#   1. 白名单制：只清理下方「已知安全」目录，绝不碰 文档/下载/桌面/用户主目录根。
#   2. Dry-run 默认：默认只报告，不删除；必须显式 -Apply。
#   3. 可恢复删除：默认送入回收站（可还原），不永久删除（-NoTrash 慎用）。
#   4. 年龄过滤：默认只处理 -MinAgeDays（默认 7）天前未修改的条目。
#   5. 不请求管理员权限：需要管理员权限的目录（C:\Windows\Temp、Windows Update 缓存等）一律跳过。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File cleanup.ps1                 # dry-run
#   powershell -ExecutionPolicy Bypass -File cleanup.ps1 -Apply
#   powershell -ExecutionPolicy Bypass -File cleanup.ps1 -Apply -MinAgeDays 14
#   powershell -ExecutionPolicy Bypass -File cleanup.ps1 -Category temp,usercache,dev
# =============================================================================
param(
  [switch]$Apply,
  [switch]$NoTrash,
  [int]$MinAgeDays = 7,
  [string]$Category = "",
  [string]$With = "",
  [switch]$Verbose
)

$ErrorActionPreference = 'Continue'
$skillDir = Split-Path -Parent $PSScriptRoot
$logDir = Join-Path $skillDir 'logs'
try { New-Item -ItemType Directory -Force -Path $logDir | Out-Null } catch {}
$logFile = Join-Path $logDir 'cleanup.log'

function Log([string]$msg) {
  $line = '{0} {1}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'), $msg
  try { Add-Content -Path $logFile -Value $line -ErrorAction SilentlyContinue } catch {}
}

function Format-Bytes([double]$n) {
  $u = 'B','KB','MB','GB','TB'; $i = 0; $v = $n
  while ($v -ge 1024 -and $i -lt 4) { $v /= 1024; $i++ }
  if ($i -eq 0) { return ('{0} B' -f $v) }
  return ('{0:F1} {1}' -f $v, $u[$i])
}

# 安全守卫：绝不触碰这些路径
function Test-Protected([string]$p) {
  $home = $HOME.TrimEnd('\')
  if ($p.TrimEnd('\') -eq $home) { return $true }
  # 主目录直接子项整体保护
  $parent = Split-Path -Parent $p
  if ($parent.TrimEnd('\') -eq $home) { return $true }
  foreach ($guard in @(
    (Join-Path $home 'Documents'), (Join-Path $home 'Downloads'),
    (Join-Path $home 'Desktop'), (Join-Path $home 'OneDrive'),
    (Join-Path $home '.dsh'), (Join-Path $home '.ssh'), (Join-Path $home '.gitconfig')
  )) {
    if ($p -eq $guard -or $p.StartsWith($guard + '\', [System.StringComparison]::OrdinalIgnoreCase)) { return $true }
  }
  return $false
}

# 送入回收站（可恢复）
function Move-ToRecycleBin([string]$p) {
  if (-not (Test-Path -LiteralPath $p)) { return $false }
  # 方式 1：VisualBasic（Windows PowerShell 5.1 可靠）
  try {
    Add-Type -AssemblyName Microsoft.VisualBasic -ErrorAction Stop
    if (Test-Path -LiteralPath $p -PathType Container) {
      [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteDirectory($p, 'OnlyErrorDialogs', 'SendToRecycleBin')
    } else {
      [Microsoft.VisualBasic.FileIO.FileSystem]::DeleteFile($p, 'OnlyErrorDialogs', 'SendToRecycleBin')
    }
    return $true
  } catch {}
  # 方式 2：Shell.Application COM（PowerShell 7 / 无 VisualBasic 时兜底）
  try {
    $sh = New-Object -ComObject Shell.Application
    $dir = Split-Path -Parent $p
    $leaf = Split-Path -Leaf $p
    $item = $sh.Namespace($dir).ParseName($leaf)
    if ($null -ne $item) { $item.InvokeVerb('delete'); return $true }
  } catch {}
  return $false
}

function Get-Size([string]$p) {
  if (Test-Path -LiteralPath $p -PathType Container) {
    $s = (Get-ChildItem -LiteralPath $p -Recurse -Force -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
    if ($null -eq $s) { return 0 }
    return $s
  } else {
    $f = Get-Item -LiteralPath $p -Force -ErrorAction SilentlyContinue
    if ($null -eq $f) { return 0 }
    return $f.Length
  }
}

# 处理一批候选：dry-run 报告 / apply 送入回收站
function Process-Entries([string]$label, [array]$items) {
  $total = 0L; $count = 0; $skipped = 0
  foreach ($it in $items) {
    if ($null -eq $it) { continue }
    $p = $it.FullName
    if (Test-Protected $p) { if ($Verbose) { Write-Host "  [跳过-保护路径] $p" }; $skipped++; continue }
    $size = Get-Size $p
    $total += $size
    if ($Apply) {
      if ($NoTrash) {
        $ok = $false
        try { Remove-Item -LiteralPath $p -Recurse -Force -ErrorAction Stop; $ok = $true } catch { $ok = $false }
      } else {
        $ok = Move-ToRecycleBin $p
      }
      if ($ok) { $count++; Write-Host "  [已清理] $p ($(Format-Bytes $size))" }
      else { $skipped++; Write-Host "  [跳过-失败] $p" }
    } else {
      $count++
      Write-Host ("  [将清理] {0}  ({1})" -f $p, (Format-Bytes $size))
    }
  }
  Log "[$label] $count 项 / $(Format-Bytes $total) / 跳过 $skipped"
  Write-Host ("== {0}：{1} 项，{2}，跳过 {3} 项 ==" -f $label, $count, (Format-Bytes $total), $skipped)
  Write-Host ''
}

# 枚举目录下 mtime 超过阈值的条目
function Get-OldEntries([string]$dir) {
  if (-not (Test-Path -LiteralPath $dir)) { return @() }
  $cut = (Get-Date).AddDays(-$MinAgeDays)
  @(Get-ChildItem -LiteralPath $dir -Force -ErrorAction SilentlyContinue | Where-Object { $_.LastWriteTime -lt $cut })
}

# --------------------------- 各类别 ---------------------------
function Run-Temp {
  foreach ($d in @($env:TEMP, (Join-Path $env:LOCALAPPDATA 'Temp'))) {
    if ([string]::IsNullOrWhiteSpace($d)) { continue }
    Process-Entries "temp: $d" (Get-OldEntries $d)
  }
}
function Run-Usercache {
  $roots = @()
  $roots += Join-Path $env:LOCALAPPDATA 'Cache'
  $roots += Join-Path $env:LOCALAPPDATA 'Microsoft\Windows\INetCache'
  $roots += Join-Path $env:LOCALAPPDATA 'Google\Chrome\User Data\Default\Cache'
  $roots += Join-Path $env:LOCALAPPDATA 'Microsoft\Edge\User Data\Default\Cache'
  $roots += Join-Path $env:APPDATA 'npm-cache'
  $roots += Join-Path $env:LOCALAPPDATA 'pip\Cache'
  $roots += Join-Path $env:LOCALAPPDATA 'Yarn\Cache'
  foreach ($d in $roots) {
    if ([string]::IsNullOrWhiteSpace($d)) { continue }
    if (Test-Path -LiteralPath $d) { Process-Entries "usercache: $d" (Get-OldEntries $d) }
  }
}
function Run-Logs {
  foreach ($d in @((Join-Path $env:LOCALAPPDATA 'Logs'), (Join-Path $env:APPDATA 'Logs'))) {
    if (Test-Path -LiteralPath $d) {
      $cut = (Get-Date).AddDays(-$MinAgeDays)
      $items = @(Get-ChildItem -LiteralPath $d -Recurse -File -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Extension -match '\.log' -and $_.LastWriteTime -lt $cut })
      Process-Entries "logs: $d" $items
    }
  }
}
function Run-Dev {
  $d = Join-Path $env:LOCALAPPDATA 'npm-cache'
  if (Test-Path -LiteralPath $d) { Process-Entries "dev: npm-cache" (Get-OldEntries $d) }
  $d = Join-Path $env:LOCALAPPDATA 'pip\Cache'
  if (Test-Path -LiteralPath $d) { Process-Entries "dev: pip cache" (Get-OldEntries $d) }
  $d = Join-Path $env:LOCALAPPDATA 'Yarn\Cache'
  if (Test-Path -LiteralPath $d) { Process-Entries "dev: yarn cache" (Get-OldEntries $d) }
  $d = Join-Path $env:USERPROFILE '.gradle\caches'
  if (Test-Path -LiteralPath $d) { Process-Entries "dev: gradle cache" (Get-OldEntries $d) }
  $d = Join-Path $env:USERPROFILE '.cargo\registry\cache'
  if (Test-Path -LiteralPath $d) { Process-Entries "dev: cargo cache" (Get-OldEntries $d) }
}
function Run-Trash {
  # 清空回收站（不可恢复，默认关闭）
  if ($Apply) {
    Clear-RecycleBin -Force -ErrorAction SilentlyContinue
    Write-Host '  [已清理] 回收站（Clear-RecycleBin，不可恢复）'
    Log 'trash: Clear-RecycleBin'
  } else {
    Write-Host '  [将清理] 回收站（Clear-RecycleBin，不可恢复）'
  }
}

# --------------------------- 调度 ---------------------------
$defaultOn = 'temp,usercache,logs,dev'
if ([string]::IsNullOrWhiteSpace($Category)) { $sel = $defaultOn } else { $sel = $Category }
if (-not [string]::IsNullOrWhiteSpace($With)) { $sel += ',' + $With }

if ($Apply -and -not $NoTrash) { $mode = '真正清理（送入回收站，可恢复）' }
elseif ($Apply) { $mode = '真正清理（永久删除 -NoTrash，慎用）' }
else { $mode = 'DRY-RUN（只报告，不删除）' }

Log "================ 运行开始 (apply=$Apply noTrash=$NoTrash minAge=$MinAgeDays categories=$sel) ================"
Write-Host "运行模式：$mode"
Write-Host ''

foreach ($c in ($sel -split ',')) {
  switch ($c.Trim()) {
    'temp'        { Run-Temp }
    'usercache'   { Run-Usercache }
    'logs'        { Run-Logs }
    'dev'         { Run-Dev }
    'trash'       { Run-Trash }
    'deriveddata' { Write-Host '[提示] deriveddata 仅适用于 macOS，Windows 跳过' }
    default       { Write-Host "未知类别: $c" }
  }
}

Log "================ 运行结束 ================"
if (-not $Apply) {
  Write-Host '以上为 DRY-RUN 报告（未删除任何内容）。确认后加 -Apply 真正清理。'
}
