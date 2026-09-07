# 安全规则与清理白名单

本文档是 `system-cleanup` skill 的权威安全说明。执行清理前必须对照本文档确认目标目录在「已知安全」白名单内。

## 核心安全原则

1. **白名单制**：只清理本文档列出的目录。任何未列出的路径一律不碰。
2. **默认 dry-run**：先报告「将清理什么 + 可释放空间」，用户确认后才真正清理。
3. **可恢复删除**：默认移入废纸篓/回收站（macOS `trash`、Windows 回收站、Linux `trash-cli`/`gio`/freedesktop Trash），绝不默认 `rm -rf`。
4. **年龄过滤**：默认只处理 7 天前（`--min-age-days 7`）未修改的条目，避开正在使用的文件。
5. **使用中检测**：macOS/Linux 用 `lsof` 跳过被进程打开的文件。
6. **无安全回退则不删**：当系统上没有可用的「移入废纸篓」工具且无法安全回退时，**跳过实际删除、只报告**，绝不降级为永久删除。

## 永久不触碰（绝对黑名单）

- 主目录根 `$HOME` 本身及主目录一级条目（含所有 `.` 开头目录，如 `.dsh`、`.ssh`、`.gitconfig`）
- `Documents`、`Downloads`、`Desktop`、`OneDrive`（Windows）及其全部子内容
- 任何项目源码目录、`.git`、当前工作目录
- 系统关键目录：`/System`、`/Library`（macOS 根级）、`/usr`、`/bin`、`/etc`、`C:\Windows`、`C:\Program Files`
- 用户自建的任意非白名单目录

## 清理白名单（按平台）

### macOS（Darwin）

| 类别 | 路径 | 说明 |
|---|---|---|
| temp | `/tmp`、`/var/tmp` | 系统临时目录；条目级、超龄 |
| usercache | `~/Library/Caches` | 各应用缓存（含浏览器缓存，如 `~/Library/Caches/Google`、`com.apple.Safari`）；条目级、超龄；书签/密码等不在此目录 |
| logs | `~/Library/Logs` | 应用日志；超龄 `.log` 文件/目录 |
| dev | `~/Library/Caches/Homebrew`、npm/pip/yarn/pnpm/brew/cargo/go/gradle 缓存 | 优先用工具自带安全清理命令（`npm cache clean` 等） |
| deriveddata（默认关） | `~/Library/Developer/Xcode/DerivedData`、`~/Library/Developer/CoreSimulator/Caches` | 清理后首次构建变慢；需 `--with deriveddata` |
| trash（默认关） | `~/.Trash` | 清空废纸篓，不可恢复；需 `--with trash` |

### Linux

| 类别 | 路径 | 说明 |
|---|---|---|
| temp | `/tmp`、`/var/tmp` | 条目级、超龄 |
| usercache | `~/.cache`（或 `$XDG_CACHE_HOME`） | 各应用缓存；条目级、超龄 |
| logs | `~/.cache` 下的 `.log*` 文件 | 超龄日志文件 |
| dev | npm/pip/yarn/pnpm/cargo/go/gradle 缓存 | 优先用工具自带安全清理命令 |
| trash（默认关） | `~/.local/share/Trash/files`（或 `$XDG_DATA_HOME`） | 清空回收站；需 `--with trash` |

### Windows（win32）

| 类别 | 路径 | 说明 |
|---|---|---|
| temp | `%TEMP%`、`%LOCALAPPDATA%\Temp` | 条目级、超龄 |
| usercache | `%LOCALAPPDATA%\Cache`、`INetCache`、Chrome/Edge 缓存、npm/pip/yarn 缓存 | 条目级、超龄 |
| logs | `%LOCALAPPDATA%\Logs`、`%APPDATA%\Logs` | 超龄 `.log` 文件 |
| dev | npm-cache、pip Cache、Yarn Cache、gradle/cargo 缓存 | 条目级、超龄 |
| trash（默认关） | 回收站（`Clear-RecycleBin`） | 需 `-With trash` |

> Windows 下需要管理员权限的目录（`C:\Windows\Temp`、Windows Update 缓存、`C:\Windows\SoftwareDistribution` 等）**一律跳过**，不请求提权。

## 年龄过滤的取值

- `--min-age-days 7`（默认）：只处理 7 天前修改的条目，最保守常用。
- `--min-age-days 14`：更保守，适合担心清理影响近期工作区的场景。
- 值越大越安全、释放空间越小；值越小释放越多、但碰到「还在用的文件」概率越高（仍有废纸篓兜底）。

## 失败与异常处理

- 脚本报权限不足 → 逐项说明，绝不自动 `sudo`（除非用户明确要求并说明原因）。
- 移入废纸篓失败（如文件被锁定）→ 跳过该项并计入「跳过-失败」，不阻断其余清理。
- dry-run 与 apply 的候选清单完全一致：dry-run 报告里出现的条目，apply 才会处理。

## 恢复方式

- macOS：废纸篓（Dock 的 Trash）→ 右键「放回原处」。
- Linux：`trash-cli` 的 `trash-restore`，或从 `~/.local/share/Trash/files` 手动移回。
- Windows：回收站 → 右键「还原」。
