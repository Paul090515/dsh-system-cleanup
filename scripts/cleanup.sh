#!/usr/bin/env bash
# =============================================================================
# DSH system-cleanup — 保守的系统缓存/垃圾清理脚本（macOS + Linux）
#
# 安全设计（保守模式）：
#   1. 白名单制：只清理下方「已知安全」目录，绝不碰文档/下载/桌面/项目/主目录根。
#   2. Dry-run 默认：默认只「报告将清理什么 + 可释放空间」，不删除；必须显式 --apply。
#   3. 可恢复删除：默认移入废纸篓/回收站，不永久删除（rm -rf 仅在 --no-trash 时允许）。
#   4. 年龄过滤：默认只处理 --min-age-days（默认 7）天前未修改的条目。
#   5. 使用中检测：默认用 lsof（如有）跳过被进程打开的文件。
#
# 用法：
#   cleanup.sh                             # dry-run：报告将清理内容与空间
#   cleanup.sh --apply                     # 真正清理（移入废纸篓）
#   cleanup.sh --apply --min-age-days 14
#   cleanup.sh --category temp,usercache,logs,dev
#   cleanup.sh --apply --with deriveddata,trash
# =============================================================================
set -u

# --------------------------- 参数解析 ---------------------------
APPLY=0
NO_TRASH=0
MIN_AGE_DAYS=7
CATEGORIES=""      # 显式指定类别（空=默认开）
WITH=""            # 额外启用的默认关闭类别
VERBOSE=0

usage() {
  echo "用法: $0 [--apply] [--min-age-days N] [--category a,b,c] [--with a,b] [--no-trash] [--verbose]"
}

while [ $# -gt 0 ]; do
  case "$1" in
    --apply)        APPLY=1 ;;
    --no-trash)     NO_TRASH=1 ;;
    --min-age-days) MIN_AGE_DAYS="$2"; shift ;;
    --category)     CATEGORIES="$2"; shift ;;
    --with)         WITH="$2"; shift ;;
    --verbose|-v)   VERBOSE=1 ;;
    --help|-h)      usage; exit 0 ;;
    *) echo "未知参数: $1" >&2; usage >&2; exit 2 ;;
  esac
  shift
done

# 年龄阈值必须为正整数
case "$MIN_AGE_DAYS" in
  ''|*[!0-9]*) echo "错误: --min-age-days 必须为正整数" >&2; exit 2 ;;
esac

# --------------------------- 基础工具 ---------------------------
detect_os() {
  case "$(uname -s)" in
    Darwin) echo darwin ;;
    Linux)  echo linux ;;
    *)      echo unknown ;;
  esac
}
OS="$(detect_os)"
if [ "$OS" = "unknown" ]; then
  echo "不支持的系统: $(uname -s)" >&2
  exit 2
fi

SKILL_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)"
LOG_DIR="$SKILL_DIR/logs"
mkdir -p "$LOG_DIR" 2>/dev/null || true
LOG_FILE="$LOG_DIR/cleanup.log"

log() { printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LOG_FILE" 2>/dev/null; }

bytes_human() {
  awk -v n="$1" 'BEGIN{
    u[0]="B"; u[1]="KB"; u[2]="MB"; u[3]="GB"; u[4]="TB"; i=0; v=n;
    while (v>=1024 && i<4) { v/=1024; i++ }
    if (i==0) printf "%d B", v; else printf "%.1f %s", v, u[i]
  }'
}

has() { command -v "$1" >/dev/null 2>&1; }

# 文件是否被进程打开（best-effort）
is_open() {
  [ -n "${1:-}" ] || return 1
  if has lsof; then
    lsof "$1" >/dev/null 2>&1 && return 0
  fi
  return 1
}

dir_size() { du -sk "$1" 2>/dev/null | awk '{print $1*1024}'; }

# 安全守卫：这些路径/前缀一律不碰
is_protected() {
  local p="$1" rest
  [ "$p" = "$HOME" ] && return 0
  case "$p" in
    "$HOME"/*) : ;;
    *) return 1 ;;   # 不在主目录下，不保护（/tmp 等）
  esac
  # 主目录直接子项（含所有 dot 目录）整体受保护；更深层交给白名单目录单独判断
  rest="${p#"$HOME"/}"
  case "$rest" in
    */*) : ;;        # 有斜杠 => 深度 >= 2，继续细分判断
    *) return 0 ;;   # 无斜杠 => 主目录一级条目，保护
  esac
  case "$p" in
    "$HOME/Documents"|"$HOME/Documents"/*|"$HOME/Downloads"|"$HOME/Downloads"/*|"$HOME/Desktop"|"$HOME/Desktop"/*) return 0 ;;
    "$HOME/.dsh"|"$HOME/.dsh"/*|"$HOME/.ssh"|"$HOME/.ssh"/*|"$HOME/.gitconfig"|"$HOME/.gitconfig"/*) return 0 ;;
  esac
  return 1
}

# --------------------------- 移入废纸篓 ---------------------------
# 返回 0 成功、1 跳过（不存在）、2 失败
trash_path() {
  local p="$1"
  [ -e "$p" ] || [ -L "$p" ] || return 1
  if [ "$NO_TRASH" = "1" ]; then
    rm -rf "$p" && return 0 || return 2
  fi
  case "$OS" in
    darwin)
      if has trash; then
        trash -s "$p" >/dev/null 2>&1 && return 0
      fi
      if has osascript; then
        osascript -e "tell application \"Finder\" to delete POSIX file \"$p\"" >/dev/null 2>&1 && return 0
      fi
      mv "$p" "$HOME/.Trash/$(basename "$p").$$" >/dev/null 2>&1 && return 0 || return 2
      ;;
    linux)
      if has trash-put; then
        trash-put "$p" >/dev/null 2>&1 && return 0
      elif has trash; then
        trash "$p" >/dev/null 2>&1 && return 0
      elif has gio; then
        gio trash "$p" >/dev/null 2>&1 && return 0
      else
        freedesktop_trash "$p" && return 0 || return 2
      fi
      ;;
  esac
  return 2
}

freedesktop_trash() {
  local p="$1" base dest i=1
  local data="${XDG_DATA_HOME:-$HOME/.local/share}/Trash/files"
  local info="${XDG_DATA_HOME:-$HOME/.local/share}/Trash/info"
  mkdir -p "$data" "$info" 2>/dev/null || return 1
  base="$(basename "$p")"
  dest="$data/$base"
  while [ -e "$dest" ]; do
    i=$((i+1)); base="$(basename "$p").$i"; dest="$data/$base"
  done
  mv "$p" "$dest" 2>/dev/null || return 1
  printf '[Trash Info]\nPath=%s\nDeletionDate=%s\n' \
    "$(printf '%s' "$p" | sed 's/%/%%/g')" "$(date '+%Y-%m-%dT%H:%M:%S')" \
    > "$info/$base.trashinfo" 2>/dev/null || true
  return 0
}

# --------------------------- 候选枚举 ---------------------------
older_entries() {  # 目录下 maxdepth 1、mtime 超过阈值的条目
  local dir="$1"
  [ -d "$dir" ] || return 0
  find "$dir" -mindepth 1 -maxdepth 1 -mtime +"$MIN_AGE_DAYS" 2>/dev/null
}
older_logs() {     # 递归找超龄日志文件
  local dir="$1"
  [ -d "$dir" ] || return 0
  find "$dir" -type f \( -name '*.log' -o -name '*.log.*' -o -name '*.log.gz' \) -mtime +"$MIN_AGE_DAYS" 2>/dev/null
}

# --------------------------- 清理执行 ---------------------------
process_entries() {
  local label="$1" item size total=0 count=0 skipped=0
  while IFS= read -r item; do
    [ -n "$item" ] || continue
    if is_protected "$item"; then
      [ "$VERBOSE" = "1" ] && echo "  [跳过-保护路径] $item"
      skipped=$((skipped+1)); continue
    fi
    if [ -f "$item" ] && is_open "$item"; then
      [ "$VERBOSE" = "1" ] && echo "  [跳过-使用中] $item"
      skipped=$((skipped+1)); continue
    fi
    size="$(dir_size "$item")"; total=$((total + size))
    if [ "$APPLY" = "1" ]; then
      if trash_path "$item"; then
        count=$((count+1)); echo "  [已清理] $item ($(bytes_human "$size"))"
      else
        skipped=$((skipped+1)); echo "  [跳过-失败] $item"
      fi
    else
      count=$((count+1)); printf '  [将清理] %s  (%s)\n' "$item" "$(bytes_human "$size")"
    fi
  done
  log "[$label] $count 项 / $(bytes_human "$total") / 跳过 $skipped"
  printf '== %s：%d 项，%s，跳过 %d 项 ==\n' "$label" "$count" "$(bytes_human "$total")" "$skipped"
}

# --------------------------- 各类别 ---------------------------
run_temp() {
  for d in /tmp /var/tmp; do
    [ -d "$d" ] || continue
    older_entries "$d" | process_entries "temp: $d"
  done
}
run_usercache() {
  local d
  if [ "$OS" = "darwin" ]; then d="$HOME/Library/Caches"; else d="${XDG_CACHE_HOME:-$HOME/.cache}"; fi
  older_entries "$d" | process_entries "usercache: $d"
}
run_logs() {
  if [ "$OS" = "darwin" ]; then
    older_entries "$HOME/Library/Logs" | process_entries "logs: ~/Library/Logs"
  else
    older_logs "${XDG_CACHE_HOME:-$HOME/.cache}" | process_entries "logs: ~/.cache"
  fi
}
run_dev() {
  local d
  if [ "$OS" = "darwin" ]; then
    d="$HOME/Library/Caches/Homebrew"
    [ -d "$d" ] && older_entries "$d" | process_entries "dev: Homebrew cache"
  fi
  if has npm;    then [ "$APPLY" = "1" ] && npm cache clean --force >/dev/null 2>&1;      log "dev: npm cache clean"; fi
  if has pip3;   then [ "$APPLY" = "1" ] && pip3 cache purge >/dev/null 2>&1;            log "dev: pip3 cache purge"; fi
  if has pip;    then [ "$APPLY" = "1" ] && pip cache purge >/dev/null 2>&1;             log "dev: pip cache purge"; fi
  if has yarn;   then [ "$APPLY" = "1" ] && yarn cache clean >/dev/null 2>&1;            log "dev: yarn cache clean"; fi
  if has pnpm;   then [ "$APPLY" = "1" ] && pnpm store prune >/dev/null 2>&1;            log "dev: pnpm store prune"; fi
  if has brew;   then [ "$APPLY" = "1" ] && brew cleanup --prune=all >/dev/null 2>&1;    log "dev: brew cleanup"; fi
  d="${CARGO_HOME:-$HOME/.cargo}/registry/cache"
  [ -d "$d" ] && older_entries "$d" | process_entries "dev: cargo cache"
  if has go; then
    d="$(go env GOCACHE 2>/dev/null)"
    [ -n "$d" ] && [ -d "$d" ] && older_entries "$d" | process_entries "dev: go cache"
  fi
  d="$HOME/.gradle/caches"
  [ -d "$d" ] && older_entries "$d" | process_entries "dev: gradle cache"
}
run_deriveddata() {
  local d
  if [ "$OS" = "darwin" ]; then
    d="$HOME/Library/Developer/Xcode/DerivedData"
    [ -d "$d" ] && older_entries "$d" | process_entries "deriveddata: DerivedData"
    d="$HOME/Library/Developer/CoreSimulator/Caches"
    [ -d "$d" ] && older_entries "$d" | process_entries "deriveddata: CoreSimulator Caches"
  fi
}
run_trash() {
  local d
  if [ "$OS" = "darwin" ]; then d="$HOME/.Trash"; else d="${XDG_DATA_HOME:-$HOME/.local/share}/Trash/files"; fi
  [ -d "$d" ] && older_entries "$d" | process_entries "trash"
}

# --------------------------- 类别调度 ---------------------------
DEFAULT_ON="temp,usercache,logs,dev"
if [ -n "$CATEGORIES" ]; then SEL="$CATEGORIES"; else SEL="$DEFAULT_ON"; fi
[ -n "$WITH" ] && SEL="$SEL,$WITH"

log "================ 运行开始 (os=$OS apply=$APPLY no-trash=$NO_TRASH min-age=$MIN_AGE_DAYS categories=$SEL) ================"
if   [ "$APPLY" = "1" ] && [ "$NO_TRASH" = "0" ]; then mode="真正清理（移入废纸篓，可恢复）";
elif [ "$APPLY" = "1" ]; then mode="真正清理（永久删除 --no-trash，慎用）";
else mode="DRY-RUN（只报告，不删除）"; fi
echo "运行模式：$mode"
echo ""

for c in $(printf '%s' "$SEL" | tr ',' ' '); do
  case "$c" in
    temp)        run_temp ;;
    usercache)   run_usercache ;;
    logs)        run_logs ;;
    dev)         run_dev ;;
    deriveddata) run_deriveddata ;;
    trash)       run_trash ;;
    *) echo "未知类别: $c" >&2 ;;
  esac
done

log "================ 运行结束 ================"
if [ "$APPLY" = "0" ]; then
  echo "以上为 DRY-RUN 报告（未删除任何内容）。确认后运行: $0 --apply"
fi
