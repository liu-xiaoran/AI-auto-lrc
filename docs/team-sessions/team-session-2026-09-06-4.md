# Dev Team 会话：W1b-5 S16 首建竞态修复与进程崩溃门禁

日期：2026-09-06  
模式：PM / Architect / Developer / QA；角色评审只读，由主任务统一实施和回写  
主题：修复 retention control tree 首次初始化时两个独立 publisher 竞争 `LOCK` 的真实竞态，并用 `SIGKILL` 与 fresh-process classifier 关闭 S16 process-crash hardening。

## 项目上下文

AI-auto-lrc 是 Python/macOS/Linux 音频对齐项目，当前共享 dirty worktree 包含大规模 v2 重构成果。W1b-5 的 S12a–S15 已闭合局部合同；S16–S18 是 retention hardening。完成标准是精确错误语义、真实独立进程系统测试、联合/宿主全量回归和可恢复的本地文档。禁止 commit、push、CI、上传、签名、发布、自动清理/恢复，以及未授权的 5c/5d/5e。

## PM

1. **First reaction**：这是 S16 范围内的真实首建竞态，修复方向合理，但必须证明创建者与跟随者绑定同一 pinned `run_fd`。
2. **Key concerns**：DoD 必须同时覆盖双 publisher、六个 `SIGKILL` 点、fresh-process 分类、锁释放与唯一提交；仅 `EEXIST` 可进入无 `O_CREAT` 的重开分支；证据只代表 process crash，不能晋级为掉电、恢复或 Release 证明。
3. **First action**：先保留并发首建 RED 和精确错误码，再做最小锁打开修正并执行 S16、retention、联合与宿主全量。
4. **Question for team**：S16 Gate 是否明确限定为 process-crash hardening Go，并保持 Release No-go？

## Architect

1. **First reaction**：`O_CREAT|O_EXCL` 创建、`FileExistsError` 后无创建重开可以收敛首次初始化竞态，但所有操作必须发生在 pinned run directory descriptor 上。
2. **Key concerns**：`FileExistsError -> open` 之间若得到 `ENOENT` 必须 fail closed；`fstat` 与目录项需要核对同一 inode；`CONTROL_LOCKED` 只表示真实 flock 竞争，创建、身份或 namespace 异常不得伪装成锁竞争。
3. **First action**：冻结双进程/SIGKILL 矩阵，验证单锁域、最多一个提交和 fresh-process 稳定分类。
4. **Question for team**：S16 威胁模型是否明确排除同 UID 主动替换 `LOCK` 的完整 ABA？若不排除，Release 必须继续 No-go。

## Developer

1. **First reaction**：测试发现的是生产竞态，不能放宽 loser 的允许集合掩盖；最小改动应只修复锁文件首建/open 协议和身份绑定。
2. **Key concerns**：生产代码不能出现 crash CLI/env switch；测试 checkpoint 必须在真实 syscall 返回后才通知父进程；任何诊断 traceback 模式必须在最终合同中移除。
3. **First action**：在 pinned `run_fd` 上先 `O_CREAT|O_EXCL`，仅捕获 `FileExistsError` 后用 `O_RDWR|O_NOFOLLOW|O_CLOEXEC` 重开；flock 前后核对打开 fd 与 `LOCK` 名称的 `(dev, ino)`，保留 type/owner/mode/nlink 检查。
4. **Question for team**：S17 是否严格在 S16 全量回归和文档 checkpoint 后开始？

## QA

1. **First reaction**：`ENOENT` 暴露首次 control 初始化竞态；修复必须由独立进程合同证明，不能由 thread test 或允许 `CONTROL_PUBLICATION_FAILED` 代替。
2. **Key concerns**：双 publisher 只允许“一成功 + `CONTROL_LOCKED`/`INSPECTION_ALREADY_COMMITTED`”；六个 crash 状态要精确；连续重跑、classifier/verify/retry 零写入和 sealed tree 不变必须共同成立。
3. **First action**：用 pipe/pass-fds 建 barrier，不使用 `sleep()`；完整 S16 连续三轮，再跑 retention、capture+retention 和宿主全量。
4. **Question for team**：重复轮数、macOS/Linux required gate 与 flaky 零容忍最终由谁签署？

## 综合结论与张力

- 四个角色一致认定首轮失败是生产竞态，不是测试误报；禁止把 `SYMLINK_FORBIDDEN`、`CONTROL_PUBLICATION_FAILED` 或任意宽泛错误加入 loser 允许集合。
- 最小修复是两阶段锁创建/open：创建者使用 `O_CREAT|O_EXCL`，跟随者仅在 `FileExistsError` 后无创建重开；所有其他打开错误 fail closed 为 `CONTROL_PUBLICATION_FAILED`。
- 锁 fd 在 flock 前后与 pinned directory 中的 `LOCK` 目录项核对 `(dev, ino)`；regular、owner、`0600`、`nlink=1` 继续是 required invariant。
- 架构张力没有被隐藏：上述顺序检查不能证明同 UID 主动攻击下不存在完整 ABA；standalone verifier 也不是该威胁模型下的恢复 authority。
- S16 可关闭的范围仅是当前 macOS 宿主上的独立进程竞争和 process-crash 可见状态；祖先目录 fsync、macOS `F_FULLFSYNC`、真实 power-loss、Linux required runner、自动恢复和 Release 均未关闭。

## RED、实现与真实验证

首轮 S16 为 `7 passed, 1 failed, 154 deselected`，稳定失败节点是 `test_ret_s16_two_subprocess_publishers_never_double_commit`。早期 loser 曾返回 `SYMLINK_FORBIDDEN`，随后返回 `CONTROL_PUBLICATION_FAILED`；临时 traceback 把直接原因定位为 `_open_lock()` 中 `os.open("LOCK", O_CREAT|...)` 在两个进程同时首次初始化 control tree 时抛出 `FileNotFoundError(ENOENT)`。另一进程成功且磁盘上仅留下一个 inspection/event。

实施后移除了 worker 的临时 `--trace-errors` 与 traceback 路径，恢复生产 CLI 的精确脱敏输出合同。2026-09-06，Darwin 25.6.0 arm64、Python 3.11.4 实测：

```text
双 publisher 原失败节点：       1 passed, 161 deselected
S16 round 1：                   8 passed, 154 deselected in 4.60s
S16 round 2：                   8 passed, 154 deselected in 4.61s
S16 round 3：                   8 passed, 154 deselected in 4.77s
retention contract：           162 passed in 52.15s
capture + retention：          304 passed in 82.53s
host full suite：              654 passed, 18 skipped, 22 warnings in 131.61s
ruff / compileall / diff：      PASS
document relative links：       1 passed
```

18 个 skip 仍是 13 个 canonical-only golden 和 5 个缺 cold wheelhouse 的 package case，不能吸收到通过声明。S15 阶段记录的联合首次 `1 failed, 295 passed` 顺序疑似 flaky 在本轮 `304 passed` 中未复现，但历史记录继续保留，不能据此声称已根治。

## 当前 Gate 与恢复入口

| 范围 | 判定 |
|---|---|
| S16 macOS process concurrency/crash | Go；只限本轮定义的独立进程、SIGKILL、稳定分类与零写入重试 |
| power-loss durability / 同 UID 主动 ABA | No-go / 未证明 |
| W1b-5a | Conditional Go；trusted local assessment-only |
| W1b-5b | No-go；继续等待 S17–S18 与新 evidence |
| W1b-5c/5d/5e | 未授权、未实现 |
| Release | No-go |

下一步只进入 S17：真实 CLI 脱敏、rules/assessment hardlink/FIFO/socket/wrong-owner、Linux device fixture 和 source unknown-key fail-closed。S18 及跨工作包顺序仍以 [`../W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md`](../W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md) 和 [`../AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md`](../AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md) 的最新当前入口为准。
