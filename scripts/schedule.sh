#!/usr/bin/env bash
# =============================================================================
# DSH system-cleanup — 定时任务安装/卸载（macOS launchd + Linux cron）
#
# 安装一个「每周（默认周日 03:00）自动清理」的保守任务：
#   运行 cleanup.sh --apply（移入废纸篓 + 年龄过滤），日志写入 logs/cleanup.log。
#
# 用法：
#   schedule.sh --install                    # 安装（每周日 03:00）
#   schedule.sh --install --interval daily   # 每天 03:00
#   schedule.sh --install --min-age-days 14
#   schedule.sh --status                     # 查看当前状态
#   schedule.sh --uninstall                  # 卸载
# =============================================================================
set -u

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)"
CLEANUP="$SKILL_DIR/scripts/cleanup.sh"
LOG_DIR="$SKILL_DIR/logs"
LOG_FILE="$LOG_DIR/cleanup.log"
ERR_FILE="$LOG_DIR/cleanup.err.log"
mkdir -p "$LOG_DIR" 2>/dev/null || true

ACTION=""
INTERVAL="weekly"   # weekly | daily
MIN_AGE_DAYS=7

while [ $# -gt 0 ]; do
  case "$1" in
    --install)   ACTION=install ;;
    --uninstall) ACTION=uninstall ;;
    --status)    ACTION=status ;;
    --interval)  INTERVAL="$2"; shift ;;
    --min-age-days) MIN_AGE_DAYS="$2"; shift ;;
    --help|-h)   sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "未知参数: $1" >&2; exit 2 ;;
  esac
  shift
done

[ -n "$ACTION" ] || { echo "需要 --install / --uninstall / --status 之一" >&2; exit 2; }

detect_os() {
  case "$(uname -s)" in
    Darwin) echo darwin ;;
    Linux)  echo linux ;;
    *)      echo unknown ;;
  esac
}
OS="$(detect_os)"

# ---------- macOS：launchd ----------
LABEL="com.dsh.system-cleanup"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"

plist_content() {
  local cal_key cal_val
  if [ "$INTERVAL" = "daily" ]; then
    cal_key=""; cal_val=""
  else
    cal_key="<key>Weekday</key><integer>0</integer>"
    cal_val=""
  fi
  cat <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>$CLEANUP</string>
    <string>--apply</string>
    <string>--min-age-days</string>
    <string>$MIN_AGE_DAYS</string>
  </array>
  <key>StartCalendarInterval</key>
  <dict>
    $cal_key
    <key>Hour</key><integer>3</integer>
    <key>Minute</key><integer>0</integer>
  </dict>
  <key>StandardOutPath</key><string>$LOG_FILE</string>
  <key>StandardErrorPath</key><string>$ERR_FILE</string>
  <key>ProcessType</key><string>Background</string>
</dict>
</plist>
EOF
}

mac_install() {
  mkdir -p "$HOME/Library/LaunchAgents"
  plist_content > "$PLIST"
  launchctl unload "$PLIST" 2>/dev/null
  launchctl load "$PLIST" 2>/dev/null && echo "已安装并加载 launchd 任务: $PLIST（$INTERVAL 03:00）"
  echo "日志: $LOG_FILE"
}
mac_uninstall() {
  launchctl unload "$PLIST" 2>/dev/null
  rm -f "$PLIST"
  echo "已卸载 launchd 任务（如已安装）"
}
mac_status() {
  if [ -f "$PLIST" ]; then
    echo "已安装: $PLIST"
    launchctl list "$LABEL" 2>/dev/null || echo "（未加载到当前用户会话）"
  else
    echo "未安装"
  fi
}

# ---------- Linux：cron ----------
CRON_MARK="# dsh-system-cleanup"

linux_cron_line() {
  local schedule
  if [ "$INTERVAL" = "daily" ]; then schedule="0 3 * * *"; else schedule="0 3 * * 0"; fi
  printf '%s %s /bin/bash %s --apply --min-age-days %s >> %s 2>&1\n' \
    "$schedule" "$CRON_MARK" "$CLEANUP" "$MIN_AGE_DAYS" "$LOG_FILE"
}

linux_install() {
  local existing newline line
  newline="$(linux_cron_line)"
  existing="$(crontab -l 2>/dev/null)"
  # 去掉旧的同名条目
  existing="$(printf '%s\n' "$existing" | grep -v "$CRON_MARK")"
  { printf '%s\n' "$existing"; printf '%s\n' "$newline"; } | crontab -
  echo "已安装 cron 任务（$INTERVAL 03:00）"
  echo "日志: $LOG_FILE"
}
linux_uninstall() {
  local existing
  existing="$(crontab -l 2>/dev/null | grep -v "$CRON_MARK")"
  printf '%s\n' "$existing" | crontab -
  echo "已卸载 cron 任务（如已安装）"
}
linux_status() {
  crontab -l 2>/dev/null | grep "$CRON_MARK" || echo "未安装"
}

# ---------- 分发 ----------
case "$OS" in
  darwin)
    case "$ACTION" in
      install)   mac_install ;;
      uninstall) mac_uninstall ;;
      status)    mac_status ;;
    esac
    ;;
  linux)
    case "$ACTION" in
      install)   linux_install ;;
      uninstall) linux_uninstall ;;
      status)    linux_status ;;
    esac
    ;;
  *)
    echo "不支持的系统: $(uname -s)" >&2
    exit 2
    ;;
esac
