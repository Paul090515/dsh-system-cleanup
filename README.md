# system-cleanup · Mac 安全清理 Skill

将经过实际使用的“旧诊断日志逐文件移入废纸篓 + 只读增量查重”封装成可复用 Skill，保留 DSH 插件入口，也可用于 Codex。当前版本 **2.0.0，仅 macOS / Python 3.9+**。

## 边界

- 只在当前用户 `~/Library/Caches`、`~/Library/Logs` 中处理已知用途、至少 14 天未修改且未被占用的普通单链接文件。目前只识别少数明确的应用/更新器诊断日志，其余缓存保留。
- 默认只检查。实际移动需要用户授权及一份准确 manifest；已有相同范围的周期授权可复用，无需逐项重问。安装 Skill 不授予删除权限。
- 无整目录清理、无宽泛 `--apply`；lsof 不可用、结果不完整、权限不足、云端占位或用途不明时跳过。
- 每个文件移到唯一且不覆盖的同卷废纸篓路径，记录原路径、目标、时间、大小、理由并核验。**移入废纸篓不等于释放空间，同卷实际释放为 0。**
- 路径操作仍可能遇到其他程序并发替换：核验不符时仅安全回滚本次移动，否则停止并保留恢复路径，不把不确定结果计为成功。
- 重复检查只报告相同大小 + 完整 SHA-256 的文件，不删除个人资料，不下载云文件。排除仓库、依赖、应用包、系统管理库和符号链接。
- 每小时执行由宿主已有自动化/心跳负责；Skill 不安装或修改系统定时任务，无新增结果时不通知。

## 安装

克隆到尚不存在的 Skill 目录；已有安装请先保留本地改动再更新，不覆盖同名项目：

```bash
git clone https://github.com/Paul090515/dsh-system-cleanup.git ~/.codex/skills/system-cleanup
```

DSH 可使用 `~/.dsh/skills/system-cleanup`，也保留 `lib/index.js` 和 `cordis.patch.yml` 插件接口。本次更新只发布到 GitHub，不代表 npm 已发布新版本。

## 使用

先在**仓库外的用户工作区**运行，以便把本机记录保存在该工作区的 `work/daily-cleanup`：

```bash
python3 "/path/to/system-cleanup/scripts/safe_cleanup.py" inspect
python3 "/path/to/system-cleanup/scripts/duplicates_scan.py"
```

明确授权且审核候选后，只移动指定清单：

```bash
python3 "/path/to/system-cleanup/scripts/safe_cleanup.py" trash --manifest "/absolute/workspace/work/daily-cleanup/plan-TRANSACTION.json" --authorized
```

从仓库目录运行时，给脚本增加前置全局参数 `--state-dir "/absolute/non-repo/work/daily-cleanup"`。脚本拒绝把运行记录写进 Git 仓库。不要提交 `plan-*.json`、`receipt-*.jsonl`、重复检查状态或任何本机文件内容。

查重默认每批最多 10,000 条目 / 256 MiB 哈希读取 / 45 秒，最小文件 1 MiB；超过单批哈希上限的文件不会得到完整哈希，不报告为已确认重复。报告实际枚举的根、数量与截断原因，不代表全盘扫描。

### 恢复

manifest 和 receipt 包含精确原路径与废纸篓路径。先确认原路径没有新文件占用，再逐文件从废纸篓移回；不覆盖新日志。不提供自动清空或永久删除功能；直接移动的文件通常需要按记录手动还原，不能保证 Finder 的“放回原处”可用。

### 从 1.x 升级

这是有意收紧的破坏性升级：保留 Skill 名 `system-cleanup`，不再提供 Linux/Windows 清理、7 天门槛、系统临时目录、开发缓存或调度安装。旧的 `cleanup.sh --apply` 被拒绝；`schedule.sh` / PowerShell 入口只报说明，不改变既有系统任务。旧任务不会自动迁移或卸载，需用户明确授权后单独处理。旧版本仍保留在 Git 历史和原标签中。

## 验证

```bash
bash scripts/check.sh
```

测试只使用临时夹具，不清理真实用户数据。详细安全说明见 [references/safety-and-scope.md](references/safety-and-scope.md)。[MIT](LICENSE)。
