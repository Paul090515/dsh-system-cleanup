# =============================================================================
# DSH system-cleanup — 定时任务安装/卸载（Windows 任务计划程序 schtasks）
#
# 安装一个「每周（默认周日 03:00）自动清理」的保守任务：
#   默认运行 cleanup.ps1（dry-run）；只有显式 -Apply 才会无人值守清理。
#
# 用法：
#   powershell -ExecutionPolicy Bypass -File schedule.ps1 -Install
#   powershell -ExecutionPolicy Bypass -File schedule.ps1 -Install -Interval daily -MinAgeDays 14
#   powershell -ExecutionPolicy Bypass -File schedule.ps1 -Status
#   powershell -ExecutionPolicy Bypass -File schedule.ps1 -Uninstall
# =============================================================================
param(
  [switch]$Install,
  [switch]$Uninstall,
  [switch]$Status,
  [switch]$Apply,
  [ValidateSet('weekly','daily')]
  [string]$Interval = 'weekly',
  [ValidateRange(1, 36500)]
  [int]$MinAgeDays = 7
)

$ErrorActionPreference = 'Stop'
$taskName = 'DSH System Cleanup'
$skillDir = Split-Path -Parent $PSScriptRoot
$cleanup = Join-Path $PSScriptRoot 'cleanup.ps1'
$logDir = Join-Path $skillDir 'logs'
try { New-Item -ItemType Directory -Force -Path $logDir | Out-Null } catch {}

function Build-Command {
  $applyArg = if ($Apply) { ' -Apply' } else { '' }
  return "powershell -NoProfile -ExecutionPolicy Bypass -File `"$cleanup`"$applyArg -MinAgeDays $MinAgeDays"
}

function Invoke-Install {
  $cmd = Build-Command
  $schArgs = @(
    '/Create', '/TN', $taskName,
    '/TR', $cmd,
    '/F'
  )
  if ($Interval -eq 'daily') {
    $schArgs += @('/SC','DAILY','/ST','03:00')
  } else {
    $schArgs += @('/SC','WEEKLY','/D','SUN','/ST','03:00')
  }
  & schtasks @schArgs
  if ($LASTEXITCODE -eq 0) {
    Write-Host "已安装任务计划: $taskName（$Interval 03:00）"
    Write-Host "日志: $logDir\cleanup.log"
  } else {
    Write-Host "安装失败，exit=$LASTEXITCODE"
  }
}

function Invoke-Uninstall {
  & schtasks /Delete /TN $taskName /F 2>$null
  if ($LASTEXITCODE -eq 0) { Write-Host "已卸载任务计划: $taskName" }
  else { Write-Host "未找到任务计划（可能未安装）" }
}

function Invoke-Status {
  $r = & schtasks /Query /TN $taskName 2>$null
  if ($LASTEXITCODE -eq 0) {
    Write-Host "已安装："
    Write-Host ($r -join "`n")
  } else {
    Write-Host "未安装"
  }
}

if ($Install)      { Invoke-Install }
elseif ($Uninstall){ Invoke-Uninstall }
elseif ($Status)   { Invoke-Status }
else { Write-Host "需要 -Install / -Uninstall / -Status 之一" }
