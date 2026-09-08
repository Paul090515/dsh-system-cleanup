# Changelog

本文件记录 `system-cleanup` DSH skill 的版本历史。

## [1.0.0] - 2026-09-05

首个稳定版。

### 功能

- 保守地自动清理系统缓存与垃圾文件，支持 **macOS / Linux / Windows** 三平台
- 默认 **dry-run**（只报告、不删除），用户确认后才真正清理
- **可恢复删除**：默认移入废纸篓/回收站（macOS `trash`、Windows 回收站、Linux `trash-cli`/`gio`/freedesktop），绝不默认 `rm -rf`
- **白名单制**：只清理已知安全目录（临时目录、用户缓存、日志、开发工具缓存）
- **年龄过滤**：默认只处理 7 天前未修改的条目，避开正在使用的文件
- **使用中检测**：macOS/Linux 用 `lsof` 跳过被进程打开的文件
- 附**定时任务**安装脚本：launchd（macOS）/ cron（Linux）/ schtasks（Windows），每周自动清理

### 安全保证

- 绝不触碰：文档 / 下载 / 桌面 / 项目 / 主目录根 / `.git` / `.dsh` 等
- 无安全回退时不删：系统缺少「移入废纸篓」工具时，跳过实际删除、只报告
- 不自动提权：需要管理员权限的目录（如 `C:\Windows\Temp`）一律跳过

### 清理范围（白名单）

| 类别 | 默认 | 内容 |
|---|---|---|
| `temp` | ✅ | 系统临时目录中超过年龄阈值的条目 |
| `usercache` | ✅ | 各应用缓存（macOS `~/Library/Caches`；Linux `~/.cache`） |
| `logs` | ✅ | 应用日志（超龄 `.log` 文件/目录） |
| `dev` | ✅ | 开发工具缓存（npm / pip / yarn / pnpm / brew / cargo / go / gradle） |
| `deriveddata` | ⭕ | Xcode DerivedData、模拟器缓存（`--with deriveddata` 显式开启） |
| `trash` | ⭕ | 清空废纸篓/回收站（`--with trash` 显式开启） |
