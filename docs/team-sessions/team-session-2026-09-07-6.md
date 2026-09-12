# S18 P1 B3c 收口与 B3f L 执行设计 Teams 记录

日期：2026-09-07

模式：Teams 架构复核 实现设计 QA 对抗审阅

详细执行事实源：[`../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第 20 节 `S18-P1-PLAN-v1.7`

## 1. 讨论目标

在不覆盖 v1.6 历史 checkpoint 的前提下，确认 B3c 当前实现是否足以收口，冻结 schema v1 的 RECORD 字段语义与 no-replace 声明边界，并把 B3f-L 的 producer limits、writer 状态机、故障分类、真实 runner 用例和后续 DAG 写成本地可执行方案。

代理只做架构、实现和 QA 复核；仓库文档由主任务统一追加。所有角色都遵守 dirty worktree、历史 attempt、根目录 `./=` 和禁止操作边界。

## 2. 角色与独立意见

### 架构角色

架构角色建议新增 v1.7 current section，以 `implemented -> host-verified -> evidence-closed -> platform-qualified` 分离状态，并将 B3f-L、B3f-R、final-schema replay、B4、common freeze、双平台与下游资格化串成显式 DAG。任何 schema 升级必须同时覆盖 producer、runner、verifier、policy、manifest/Gate、direct test、real-runner test 和文档。

架构角色还要求区分 common input digest 与 per-platform runtime digest；B9/B10 只能在 common ledger 冻结后并行，macOS、Linux、package、canonical、host 和 sealed-review 不得互相代签。

### 实现角色

实现角色确认 B3f-L 应是五文件原子迁移，仅修改 events producer、runner、verifier、policy 与 security contract test。当前 events plugin 仍使用 schema v2、pretty JSON 和 `os.replace()`，没有三个 producer limit；当前 write loop 对 `os.write()==0` 不前进，write/file-fsync 异常会残留本次 temp。

实现角色建议把 `os.link(temp, final)` 作为唯一发布线性化点，以 ownership flag 管理本次 temp；link 前错误确定未发布，link 后错误保留 final 并标记 commit uncertain。B3f-L 不修改 bootstrap identity writer，也不引入 B3f-R runtime/lock/provenance。

### QA 角色

QA 角色实际复现 identity bootstrap 的 write exception、file-fsync exception 残留 temp，以及 zero-write 挂起。QA 指出“configure 前已有 final”只命中预检查，不能证明最终 publication primitive；必须另测 final 起初不存在、在 file-fsync 后和 link 前插入 competitor 的真正 publish race。

QA 要求 post-publication 故障按磁盘状态分类：temp unlink 永久失败时 final/temp 同 inode、`nlink == 2`，Gate 为 `COMMAND_FAILED, PYTEST_EVENTS_INVALID`；directory open/fsync 失败时 final 可合法读取且 `nlink == 1`，Gate 只为 `COMMAND_FAILED`，producer 另写 `PYTEST_EVENTS_COMMIT_UNCERTAIN`。

## 3. 分歧与裁决

### RECORD 字段名称

保留 identity `schema_version=1` 和外部字段名 `record_sha256`，避免在 B3c 做兼容性升级。其唯一语义冻结为 `pytest_cov/plugin.py` RECORD entry 中解码出的 SHA-256 digest，不是整份 RECORD 文件 hash。

主任务采纳 QA 建议，新增 whole-RECORD 精确 mutation：重绑定外层 identity artifact hash 后仍必须只得到 `PLUGIN_IDENTITY_INVALID`。whole RECORD、METADATA、entries mapping、lock package digest 与 runtime descriptor 继续整体留给 B3f-R schema v2。

### Publication marker 名称

Teams 讨论过 `PYTEST_EVENTS_PUBLICATION_UNCERTAIN` 与 `PYTEST_EVENTS_COMMIT_UNCERTAIN`。裁决采用后者，因为线性化点已经成功，问题是 temp 清理或目录持久化完成状态不确定，不应暗示“可能尚未发布”。

最终四类 marker：

```text
PYTEST_EVENTS_CONFIGURATION_INVALID
PYTEST_EVENTS_LIMIT_EXCEEDED
PYTEST_EVENTS_PUBLICATION_FAILED
PYTEST_EVENTS_COMMIT_UNCERTAIN
```

### B3c 与 B3f-L 边界

B3c 的 RECORD/no-replace/mode 合同标记为 host contract 已收口；B3c bootstrap 的 write-zero、异常清理和精确 fsync 顺序仍是已复现缺口，禁止扩展声明。B3f-L 先对 events writer 建立完整状态机和 fault matrix；bootstrap writer 在 final-schema replay 前另建小切片复用同类合同，不能由 B3f-L 绿色代签。

## 4. 本轮验证事实

最终 B3c 定向合同为 `12 passed, 195 deselected`，证据根 `/private/tmp/ai-auto-lrc-s18-b3c-whole-record-green.Znp2kc`，JUnit SHA-256 `83e2da35745502e79f28c7091a4d5dae271ef8ca16b424d1e6b332366dd636da`。

最终完整 security contract 为 `207 passed in 186.20s`，证据根 `/private/tmp/ai-auto-lrc-s18-b3c-v17-full.4vWi0c`，JUnit SHA-256 `97a30990c21b0b6016fbab17c94e9359f2c77f060fcb2335ffde4cad1caa9370`。

本轮最终代码 hash：

| 文件 | SHA-256 |
|---|---|
| `scripts/security_pytest_bootstrap.py` | `fe0cb701f6730c4dcd51f534ba25712bed85c9a7915c44db3c0f6449b0d49992` |
| `scripts/verify_security_coverage.py` | `e13d49eedbd523d98fd5fca4974d3ee965a6748daaf406219daa92a56065cc1c` |
| `tests/contract/test_security_coverage_gate.py` | `651052d09ac00c0dc605b2a785b6dfe586b501552adabaa01b3e66a1f217e80b` |

## 5. B3f L 测试共识

B3f-L 沿用第 18.5 节 `B3F-L-001` 至 `B3F-L-012`，新增：

- `B3F-L-013-preexisting-temp`：冻结旧 temp inode/bytes/mode/nlink，证明 `O_EXCL` 和 ownership cleanup；
- `B3F-L-014-syscall-order`：证明 `open/fchmod/write+/file-fsync/close/link/unlink/open-dir/dir-fsync/close`；
- `B3F-L-015-publish-race`：publication seam 插入 competitor，证明 no-replace winner 不变。

writer fault matrix 必须覆盖 temp open、fchmod、partial write 后异常、write-zero、file fsync、link、temp unlink、directory open/fsync/close，并同时断言 final/temp、inode、nlink、mode、producer marker、inner/outer exit、Gate failure 和 exact artifact set。

每个 fault 在 capture/retention 各跑真实 runner；一次只注入一个 target，另一 lane 保持 PASS。首次 characterization 冻结真实 pytest exit，不接受宽集合。zero-write GREEN 必须进程主动在 deadline 前失败，不能把 timeout 强杀当通过。

QA 初审后又冻结五项消歧：永久 temp-unlink 失败与 cleanup retry 成功是两个独立参数，前者 `nlink == 2` 且 events invalid，后者 `nlink == 1` 且 Gate 仅 command failed；writer matrix增加 directory-close 参数；scenario authority保存在现有 contract test 常量中，不新增第六个文件；plugin只校验 limit格式和 hard ceiling，policy等值由 runner+verifier闭合；动态 PID temp由外层记录的子进程 PID 推导 exact basename，禁止 glob allowlist。

## 6. 执行与权限结论

唯一下一步：B3f-L characterization RED，随后按 policy/events schema RED、producer/writer unit RED、writer GREEN、producer GREEN、policy/runner/verifier 原子 GREEN、capture/retention real-runner GREEN、完整回归执行。B3f-L 完成后才进入 B3f-R；完整 DAG 见权威方案第 20.9 节。

本轮没有 commit、push、CI、upload、sync、签名、发布、archive、restore、delete 或 destruction。W1b-5c/5d/5e 未执行。S18、W1b-5b、Release 继续 No-go。
