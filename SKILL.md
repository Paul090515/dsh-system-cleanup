---
name: system-cleanup
description: 在 macOS 上逐文件安全清理已知用途的旧诊断缓存和日志，并对文档、下载、桌面做只读增量查重。用于清缓存、检查重复文件或按已有授权执行周期清理；不用于删除个人资料或清空废纸篓。
metadata:
  platforms: [darwin]
  safety: exact-manifest-trash-only
---

# Mac 安全清理与增量查重

只处理当前用户的 `~/Library/Caches` 和 `~/Library/Logs`。文件必须用途明确、为当前用户的普通单链接文件、至少 14 天未修改、未被占用。仅移动逐文件清单中的条目；不按父目录年龄移动目录。

详细范围、恢复方式与输出语义见 [references/safety-and-scope.md](references/safety-and-scope.md)。脚本路径相对本 Skill 目录；运行时工作目录是用户当前工作区，记录放在工作区的 `work/daily-cleanup`，不能放进 Git 仓库或随 Skill 上传。

## 执行

1. 明确授权：新环境默认只检查。只有用户明确同意清理，或已存在对象、范围、成本未变化的周期授权，才执行移动；已有授权无需逐项重复确认。Skill 的安装和 CLI 的 `--authorized` 标志本身不构成授权。
2. 检查已知诊断日志，产生唯一的逐文件 manifest，绝不移动：

   ```bash
   python3 "/path/to/system-cleanup/scripts/safe_cleanup.py" inspect
   ```

   目前助手只识别已知应用诊断日志和少数更新器 stdout/stderr，普通缓存不能仅凭目录或扩展名判为安全。检查失败或用途不明时保留；不要扩大白名单。
3. 审核 JSON 中每个 source、文件身份、用途和检查结果。授权覆盖时，仅执行这份准确清单：

   ```bash
   python3 "/path/to/system-cleanup/scripts/safe_cleanup.py" trash --manifest "/absolute/workspace/work/daily-cleanup/plan-TRANSACTION.json" --authorized
   ```

   移动前重查元数据、14 天年龄、用途、MIME、lsof、父目录及废纸篓。只同卷逐文件移动，目标唯一且不覆盖；事前记录并 fsync，事后逐项核验源身份消失、废纸篓身份/大小/mtime 一致。并发替换时仅安全回滚本次移动，否则保留恢复路径；rolled_back/uncertain 均停止后续项并通知，不能报作成功。无安全可恢复方式、权限不足或检查不完整就跳过，不提权。
4. 只读增量查重：

   ```bash
   python3 "/path/to/system-cleanup/scripts/duplicates_scan.py"
   ```

   仅文件大小与完整 SHA-256 都相同才报告。个人资料副本绝不自动移动。跳过仓库、依赖、应用包、系统管理库、符号链接、云端占位文件，不为扫描下载云文件。默认最小 1 MiB、每批最多 10,000 条目、读取哈希最多 256 MiB / 45 秒；超限留待后续批次，不声称扫完整台电脑。
5. 阅读 manifest、receipt 与重复检查报告；以 verified 结果汇总。区分“移入废纸篓的逻辑大小”与“实际释放的空间”；同卷移入废纸篓实际释放为 0，不清空废纸篓。不把重复组的逻辑冗余量称为可释放磁盘空间。

从 Git 仓库目录调用时，必须给两个 Python 脚本传入仓库外的 `--state-dir "/absolute/workspace/work/daily-cleanup"`，避免修改项目或把本机记录提交出去。

## 周期执行与通知

用户要求每小时运行时，使用宿主提供的心跳/自动化机制；先查已有任务，避免重复。保存对象、范围和静默通知约定；不要在本机另装 launchd、cron 或任务计划。发布/升级 Skill 不改变已有调度或活跃自动化源代码。

每次读取增量记录和已通知结果，避免完整重扫与重复提醒。无可处理内容、无新增重要重复组且无新故障时保持安静；只通知实际清理、新的重要重复、故障或用户需处理事项，持续未变的阻碍不重复提醒。用户询问状态时如实给出记录与覆盖范围。

## 禁止事项

- 无整脚本 `--apply`，无目录级批量清理；不降低 14 天门槛。
- 不移动个人文档、下载、桌面、照片、视频、项目、Git 仓库、应用或配置。
- 不处理数据库、登录状态、离线内容、下载中的文件、使用中文件、符号链接及其目标。
- 不永久删除、不清空废纸篓、不用 `rm -rf`、包管理器 purge/clean 或权限绕过。
- 不上传本机内容、路径清单、哈希记录或恢复记录；只发布 Skill 源码。
- 本版本仅支持 macOS；Linux/Windows 和旧调度入口明确拒绝执行，不自行迁移系统任务。

## 验证

`bash scripts/check.sh` 仅跑临时目录安全测试与插件入口测试，不执行真实用户清理。单次真实运行仍须报告检查限制；测试通过不代表任意缓存都可清理。
