---
name: system-cleanup
description: 保守地自动清理系统缓存与垃圾文件（macOS/Linux/Windows）。默认 dry-run 只报告不删除；真正清理时默认移入废纸篓/回收站（可恢复），按文件年龄过滤、跳过使用中文件，绝不触碰文档/下载/桌面/项目/主目录根。支持按需调用与安装定时任务。
whenToUse: 当用户要求清理电脑缓存、垃圾文件、释放磁盘空间、电脑变卡/卡顿，或提到「清理一下」「清缓存」「释放空间」「垃圾文件」「系统缓存」「C 盘满了」等时使用。
metadata:
  platforms: [darwin, linux, win32]
  safety: conservative
  default_mode: dry-run
---

# 系统缓存/垃圾清理（保守·安全）

目标：在不影响用户工作的前提下，自动清理「已知安全」的缓存与垃圾文件，释放磁盘空间。本 skill 永远优先「安全可恢复」，宁可少清、不可误删。

## 安全铁律（每次执行都必须遵守）

1. **白名单制**：只清理下面「清理范围」里列出的已知安全目录。绝不删除、绝不触碰：
   - 用户文档 / `Downloads` / `Desktop` / 桌面文件 / 图片 / 音乐 / 视频
   - 任何项目源码目录、`.git`、`.dsh` 会话目录、当前工作目录
   - 主目录根（`~`、`$HOME`）下的未知内容
2. **默认 dry-run**：先跑一遍「只报告 + 计算可释放空间」，把报告给用户看，**除非用户明确说「执行/清理/删掉/apply」否则不要真正删除**。
3. **可恢复删除**：真正清理时默认「移入废纸篓/回收站」，不永久删除（`rm -rf` 禁止）。
4. **年龄过滤**：默认只处理 `--min-age-days 7` 天以上未修改的条目，避开正在使用的文件。
5. **使用中检测**：默认用 `lsof`（macOS/Linux）跳过被进程打开的文件。

## 执行步骤

> 下方 `scripts/...`、`references/...` 均为相对路径，基于本 skill 的基目录解析（loader 会提供该基目录）。

### 1. 识别系统
- macOS / Linux → 运行 `scripts/cleanup.sh`
- Windows → 运行 `scripts/cleanup.ps1`（PowerShell）

### 2. 先 dry-run（默认，必做）
macOS / Linux：
```bash
bash "scripts/cleanup.sh"            # 默认 dry-run，输出将清理清单 + 可释放空间
bash "scripts/cleanup.sh" --category temp,usercache,logs,dev
```
Windows（PowerShell）：
```powershell
powershell -ExecutionPolicy Bypass -File "scripts/cleanup.ps1"    # 默认 -DryRun
```
把报告结果展示给用户，说明「将清理 X 项、约 Y 空间」，等待确认。

### 3. 用户确认后真正清理（移入废纸篓，可恢复）
macOS / Linux：
```bash
bash "scripts/cleanup.sh" --apply
bash "scripts/cleanup.sh" --apply --min-age-days 14          # 更保守：只清 14 天前的
bash "scripts/cleanup.sh" --apply --with deriveddata,trash   # 额外启用默认关闭的类别
```
Windows：
```powershell
powershell -ExecutionPolicy Bypass -File "scripts/cleanup.ps1" -Apply
```

### 4. 清理后报告
从脚本输出中汇总：清理了多少项、释放了多少空间、移入了废纸篓（可恢复）。提醒用户：废纸篓内的文件可随时还原。

## 清理范围（白名单）

| 类别 | 默认 | 内容 |
|---|---|---|
| `temp` | ✅ 开 | 系统临时目录（macOS: `/tmp`、`/var/tmp`；Linux: `/tmp`、`/var/tmp`）中超过年龄阈值的条目 |
| `usercache` | ✅ 开 | macOS `~/Library/Caches`；Linux `~/.cache` 下各应用缓存（按条目级、超过年龄阈值） |
| `logs` | ✅ 开 | macOS `~/Library/Logs`；Linux `~/.cache` 下日志；仅超过年龄阈值的 `.log` 文件/目录 |
| `dev` | ✅ 开 | 开发工具缓存：npm / pip / yarn / pnpm / Homebrew / cargo / go / gradle（优先用工具自带安全清理命令） |
| `deriveddata` | ⭕ 关 | Xcode DerivedData、iOS 模拟器缓存（清理后首次构建会变慢，需 `--with deriveddata` 显式开启） |
| `trash` | ⭕ 关 | 清空废纸篓/回收站（不可恢复，需 `--with trash` 显式开启） |

> 详细白名单与每个目录的安全说明见 `references/safety-and-scope.md`。

## 定时任务（可选，用户要求「定时自动清理」时）

安装每周自动清理（保守模式：`--apply` 移入废纸篓 + 年龄过滤）：
- macOS / Linux：`bash "scripts/schedule.sh" --install`
- Windows：`powershell -ExecutionPolicy Bypass -File "scripts/schedule.ps1" -Install`

查看/卸载：
- macOS / Linux：`bash "scripts/schedule.sh" --status` / `--uninstall`
- Windows：`... schedule.ps1 -Status` / `-Uninstall`

> 定时任务默认每周日 03:00 运行，日志写入 `logs/cleanup.log`。安装前先向用户说明它会在无人值守时按白名单+年龄过滤清理，并请用户确认。

## 参数速查（cleanup.sh / cleanup.ps1 通用语义）

| 参数 | 作用 |
|---|---|
| （默认） | dry-run：只报告，不删除 |
| `--apply` / `-Apply` | 真正清理（移入废纸篓/回收站） |
| `--min-age-days N` / `-MinAgeDays N` | 年龄阈值，默认 7 天 |
| `--category a,b,c` / `-Category a,b,c` | 只跑指定类别 |
| `--with a,b` / `-With a,b` | 额外启用默认关闭的类别 |
| `--no-trash` | 永久删除而非移入废纸篓（⚠️ 慎用，默认禁止） |

## 异常处理

- 脚本报权限不足 → 逐项说明哪些目录需要权限，绝不自动 `sudo`（除非用户明确要求并说明原因）。
- 清理工具（`trash`/`gio`/`trash-cli`）均不存在且无安全回退 → **跳过实际删除，只报告**，绝不降级为永久删除。
- 用户只说「电脑卡」没说要删东西 → 先跑 dry-run 报告，不要直接删。
