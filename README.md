# system-cleanup · DSH 系统清理 Skill

一个面向 [DeepSeek Harness (DSH)](https://github.com/deepseek-ai) 的可复用 **skill**，用于在 **macOS / Linux / Windows** 上保守地自动清理系统缓存与垃圾文件、释放磁盘空间，且**不影响用户工作**。

> 设计目标：宁可少清，不可误删。所有删除默认「可恢复」，绝不触碰文档 / 下载 / 桌面 / 项目 / 主目录根。

## ✨ 特性

| 特性 | 说明 |
|---|---|
| 🔍 Dry-run 默认 | 先报告「将清理什么 + 可释放空间」，确认后才真正清理 |
| ♻️ 可恢复删除 | 默认移入废纸篓/回收站（macOS `trash`、Windows 回收站、Linux `trash-cli`/`gio`/freedesktop），不 `rm -rf` |
| 🗂️ 白名单制 | 只清理已知安全的缓存/日志/临时目录，详见 `references/safety-and-scope.md` |
| ⏳ 年龄过滤 | 默认只处理 7 天前未修改的条目，避开正在使用的文件 |
| 🔒 使用中检测 | macOS/Linux 用 `lsof` 跳过被进程打开的文件 |
| 🖥️ 全平台 | 一套 skill，按系统自动分发：`cleanup.sh`（macOS/Linux）+ `cleanup.ps1`（Windows） |
| ⏰ 可选定时 | 附定时任务安装脚本（launchd / cron / schtasks），每周自动清理 |

## 📦 安装

本仓库同时支持「插件安装」与「skill 克隆安装」，任选其一即可。

**方式一（推荐）：`dsh plugin add` 一键安装**

```bash
# 从 GitHub 安装（会被 DSH 内置的 find_dsh_plugin 搜索发现）
dsh plugin --profile web add github:Paul090515/dsh-system-cleanup

# 或从 npm 安装（若已发布到 npm）
dsh plugin --profile web add dsh-system-cleanup
```

安装后重启 `dsh web`，对它说「清理一下」即可。

**方式二：git clone 到 skill 目录**

```bash
mkdir -p ~/.dsh/skills
git clone https://github.com/Paul090515/dsh-system-cleanup.git ~/.dsh/skills/system-cleanup
```

**方式三：手动复制**

```bash
mkdir -p ~/.dsh/skills/system-cleanup
cp -R SKILL.md scripts references ~/.dsh/skills/system-cleanup/
```

> 注意：方式二/三（克隆/复制安装）时，目标目录名必须与 skill 名一致，即 `system-cleanup`（frontmatter 中的 `name` 字段）。

## 🚀 使用

### 按需清理（推荐）

对 agent 说「清理一下 / 清缓存 / 电脑卡」，agent 会加载该 skill 并执行。核心命令：

```bash
# macOS / Linux
bash ~/.dsh/skills/system-cleanup/scripts/cleanup.sh            # dry-run：只报告
bash ~/.dsh/skills/system-cleanup/scripts/cleanup.sh --apply    # 真正清理（移入废纸篓）
bash ~/.dsh/skills/system-cleanup/scripts/cleanup.sh --apply --min-age-days 14   # 更保守
```

```powershell
# Windows
powershell -ExecutionPolicy Bypass -File ~/.dsh/skills/system-cleanup/scripts/cleanup.ps1          # dry-run
powershell -ExecutionPolicy Bypass -File ~/.dsh/skills/system-cleanup/scripts/cleanup.ps1 -Apply
```

### 定时自动清理（可选）

```bash
# macOS / Linux：安装每周日 03:00 自动清理
bash ~/.dsh/skills/system-cleanup/scripts/schedule.sh --install
bash ~/.dsh/skills/system-cleanup/scripts/schedule.sh --status
bash ~/.dsh/skills/system-cleanup/scripts/schedule.sh --uninstall
```

```powershell
# Windows：安装任务计划
powershell -ExecutionPolicy Bypass -File ~/.dsh/skills/system-cleanup/scripts/schedule.ps1 -Install
```

## 🛡️ 安全保证

1. **默认 dry-run**，不确认不删除。
2. **可恢复**：移入废纸篓/回收站，可随时还原。
3. **白名单**：只清 `references/safety-and-scope.md` 中列出的目录；文档/下载/桌面/项目/主目录根等永久不碰。
4. **无安全回退则不删**：系统上找不到「移入废纸篓」工具时，跳过实际删除、只报告，绝不降级为永久删除。
5. **不自动提权**：需要管理员权限的目录（如 `C:\Windows\Temp`）一律跳过。

## 📁 目录结构

```
dsh-system-cleanup/
├── SKILL.md                       # skill 定义（frontmatter + 执行说明）
├── scripts/
│   ├── cleanup.sh                 # macOS + Linux 清理脚本
│   ├── cleanup.ps1                # Windows 清理脚本
│   ├── schedule.sh                # 定时任务安装（launchd / cron）
│   └── schedule.ps1               # 定时任务安装（schtasks）
└── references/
    └── safety-and-scope.md        # 安全规则与完整白名单
```

## 📄 License

[MIT](LICENSE)
