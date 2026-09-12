# W1b 受控 Evidence Capture 与留存执行方案

> 状态：**W1b-0/1/2/3/4 已实现；W1b-5 S18 qualification 进行中；Release 继续 No-go**
> 日期：2026-09-06
> 上游：[`AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md`](./AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md)、[`team-session-2026-09-06.md`](./team-sessions/team-session-2026-09-06.md)、[`team-session-2026-09-06-2.md`](./team-sessions/team-session-2026-09-06-2.md)
> 已有基础：W1a `scripts/evidence_manifest.py`、W2 Linux 私有 wheelhouse snapshot，以及 W1b capture core、portable closure、Linux package sidecar 和 canonical sidecar 已完成；W1b-5 的设计文字不登记成实现证据。

## 1. 目标和非目标

W1b 把“测试执行”和“证据生成”收敛成同一个受控事务。唯一允许产生 W1b receipt 的 capture runner 必须亲自启动 `scripts/run_test_gate.sh`，采集真实进程结果，比较运行前后源码状态，封存该次运行实际产生的 artifact，并由 verifier 重算结论。调用方不得传入 exit code、测试统计或 qualification。

W1b 的完成目标是：

1. 每次运行使用新的、独占的 staging/run directory，不读取或复用旧绿色 artifact。
2. gate 成功、失败、异常退出或收到可处理信号时都进入 `finally`，尽最大努力生成结构完整的 diagnostic receipt；`SIGKILL`、主机掉电和文件系统彻底失效不在可保证范围内。
3. receipt 绑定运行前后 source snapshot、命令、环境、输入、artifact、原始 stdout/stderr 和真实 gate 退出状态。
4. portable、package、canonical 使用各自的 artifact closure；缺件、跨层、hash 漂移、后写入或可变镜像引用一律 fail closed。
5. 当前 checkout 可重算验证；历史 dirty evidence 只能做自包含完整性验证，不能事后升级为环境资格证明。
6. capture/finalizer 的错误不能掩盖原 gate 非零退出码。

W1b 明确不做：

- 不创建 CI workflow，不配置托管平台 required check。
- 不生成 `qualified-canonical` 或 `qualified-release`；schema v1 继续拒绝二者。
- 不自动删除历史 evidence；retention 期限、归档介质和 owner 仍由 `D-REL` 决定。
- 不解决 macOS Torch、资源预算、Demucs 权重许可、公开 runtime close、签名、SBOM、attestation 或 rollback。
- 不修改 `t2l/mtl/model.py`、`t2l/mtl/utils.py`，不更新 canonical oracle。

## 2. Teams 四角色复核

### 2.1 PM

第一反应：W1b 的用户价值是让本地绿色结果可复核，而不是扩大资格级别。首先锁定三层验收矩阵、目录布局、退出语义和故障注入目录。

主要关注：历史 dirty evidence 只能标为 diagnostic；独占目录、源码前后快照和失败 receipt 必须成为不可绕过的完成条件；文档不得把一次性临时路径写成长期受控制品。retention 期限、归档 owner 和批准人保留为显式决策项。

### 2.2 Architect

第一反应：capture runner 必须是唯一编排者，不能只是接受调用方提供数据后拼装 JSON。`RunContext`、分层 `ArtifactPolicy`、source snapshot 和 `ReceiptVerifier` 应先形成合同，再接入现有 shell runner。

主要关注：历史 dirty 状态需要区分“当前源码等价验证”和“归档字节完整性验证”；artifact 必须按层白名单闭合；receipt、source 输出和文档需要消除自引用。运行输出位于仓库外，receipt 不记录自身 hash，自身 hash 由外层索引计算。

### 2.3 Developer

第一反应：以标准库-only 的 `scripts/capture_test_gate.py` 做最小纵切，复用 W1a 的安全路径、稳定读取和 JUnit 重算能力，不复制 quality gate 业务规则。

主要关注：当前 `run_test_gate.sh` 使用 `set -e`，pytest 失败时后续 gate JSON 可能不存在，所以 finalizer 必须把缺件明确登记为 `missing`；package/canonical 还需各自 runner 输出机器可读 sidecar；信号、stdout/stderr、原 gate rc 和 finalizer rc 需要独立记录和稳定返回优先级。

### 2.4 QA

第一反应：只验证成功路径不够；失败仍可封存、但绝不晋级，才是 W1b 的核心反证。

主要关注：预置旧绿色文件、运行中修改 tracked/untracked/symlink、artifact 后写入、跨层拼接、可变镜像 tag、缺 sidecar、坏 XML、信号中断和 finalizer 自身失败都必须有确定性测试。每个坏输入至少有一个测试证明 gate 会红。

### 2.5 综合结论和张力

四个角色一致同意：

- capture 是唯一事实生产者；qualification 是 verifier 派生值，不是 producer 输入。
- source 前后不一致、artifact closure 不完整或 gate 非零时，只能生成 diagnostic。
- receipt 成功写入与测试成功是两个维度，不能互相覆盖。
- 文档更新会改变 dirty source；旧现场 manifest 必须明确标为历史 diagnostic，不能继续声称匹配当前 checkout。

尚未解决的张力是“长期可独立恢复”与“W1b 保持小而安全”。本方案选择先实现仓库外、不可复用、可重算的本地留存；Git bundle/LFS/完整源码恢复仍属于 W7。retention 期限和归档 owner 未决，不阻塞 W1b 本地实现，但阻止任何长期保存或 release 资格声明。

## 3. 架构边界

```text
caller
  |
  | layer/base-ref/retention-root only
  v
capture_test_gate.py
  |-- create exclusive staging directory
  |-- capture source.before
  |-- launch run_test_gate.sh itself
  |     |-- pytest / coverage / package / canonical runner
  |     `-- layer sidecars
  |-- capture source.after
  |-- snapshot and verify artifacts
  |-- derive diagnostic or implemented-unqualified
  |-- atomically seal receipt
  `-- return original gate rc, or capture rc when gate never failed

verify mode A: current-source     -> receipt + archived bytes + current checkout
verify mode B: archived-integrity -> receipt + archived bytes only; diagnostic scope
```

建议新增/调整的边界：

| 组件 | 责任 | 禁止承担 |
|---|---|---|
| `scripts/capture_test_gate.py` | 独占目录、前后 source snapshot、亲启 gate、捕获 rc/signal/log、finally 封存、原子发布 | 不重写 pytest selector，不接受外部统计/qualification |
| `scripts/evidence_manifest.py` | 安全文件读取、artifact record、JUnit/gate 交叉验证、W1a manifest verify、qualification 派生 | 不启动测试，不删除 evidence，不信任 producer 声明 |
| `scripts/run_test_gate.sh` | 执行现有 portable/package/canonical gate 并把 artifact 写入本次目录 | 不自行选择可复用目录，不生成最终 receipt |
| layer runner/verifier | 输出 package/canonical 专属 sidecar，包含实际观测值 | 不输出自报的 release qualification |
| `packaging/evidence-policy.json` | 版本化的分层 artifact closure、允许/必需字段和规则 hash | 不包含 secret、绝对用户路径、可变 tag |

`packaging/evidence-policy.json` 是建议文件名；实施时若继续使用 TOML，也必须保持标准库可读或由 capture 读取已受控 JSON 导出。policy 内容本身必须进入 receipt hash 闭包。

W1a 与 W1b 使用两个可独立演进的 schema：现有文件保持 `schema="ai-auto-lrc/evidence-manifest"`、`schema_version=1`；新增 receipt 使用 `schema="ai-auto-lrc/capture-receipt"`、`schema_version=1`，并引用或嵌入经验证的 W1a manifest record。不得在不升版本的情况下改变 W1a v1 的既有必需字段含义。未来允许 canonical/release 资格的升级必须另行版本化，不因 capture receipt v1 的数字同为 1 而自动获得资格。

## 4. CLI 与调用合同

目标 CLI：

```bash
uv run --frozen --no-sync python scripts/capture_test_gate.py run \
  --layer portable \
  --base-ref HEAD \
  --retention-root /absolute/outside-repository/evidence

uv run --frozen --no-sync python scripts/capture_test_gate.py verify \
  --receipt /absolute/evidence/<run-id>/receipt.json \
  --mode current-source \
  --repo-root /absolute/repository

uv run --frozen --no-sync python scripts/capture_test_gate.py verify \
  --receipt /absolute/evidence/<run-id>/receipt.json \
  --mode archived-integrity
```

约束：

- `run` 只接受 layer、base-ref、retention root 和已批准的 layer input 路径；不存在 `--exit-code`、`--passed`、`--skipped` 或 `--qualification`。
- retention root 必须是仓库外的真实目录；路径任一级为 symlink、root 位于 repo 内、与 repo 相同或不可创建独占子目录时，preflight 失败。
- capture 以最小环境变量把唯一 artifact directory 传给 `run_test_gate.sh`。调用方原有同名 artifact 目录变量必须被覆盖，不能注入旧目录。
- `run-id` 使用 UTC 时间前缀加至少 128 bit 随机值；目录以 `.incomplete-<run-id>` 建立，权限 `0700`，`exist_ok=False`。
- 不提供自动 `prune`。未来 retention 删除属于独立、可审计且需授权的操作。

## 5. 运行状态机与退出语义

```text
NEW
 -> PREFLIGHTED
 -> SOURCE_BEFORE_CAPTURED
 -> GATE_RUNNING
 -> GATE_FINISHED
 -> SOURCE_AFTER_CAPTURED
 -> FINALIZING
 -> SEALED_DIAGNOSTIC | SEALED_IMPLEMENTED_UNQUALIFIED

任一阶段异常 -> FINALIZING -> SEALED_DIAGNOSTIC
无法原子封存 -> UNSEALED_CAPTURE_FAILURE
```

状态机规则：

1. preflight/source-before 失败时不启动 gate，记录 `gate.started=false`。
2. gate 启动后，无论 rc、异常或信号如何都执行 source-after 和 finalizer。
3. `source.before != source.after` 时，运行结果即使为 0 也只能 diagnostic，并记录稳定原因 `SOURCE_CHANGED_DURING_RUN`。
4. finalizer 只读取本次 staging directory；文件的 ctime/mtime 必须落在本次 run window 或由明确的 input-copy 阶段生成。
5. finalizer 用同一 FD 安全读取后生成 artifact snapshot，再对 snapshot 做完整二次验证。
6. 先在 staging 写入、`fsync` 文件和目录，最后写入并同步 `SEALED` completion marker，再以单次原子 rename 发布为 `<run-id>`；发布目录不可覆盖。verifier 对没有 marker、marker 未绑定 receipt hash 或仍以 `.incomplete-` 命名的目录一律拒绝。

退出码优先级：

| 条件 | 进程返回 | receipt |
|---|---:|---|
| gate 返回非零，finalizer 成功或失败 | 原 gate rc | 成功时 diagnostic；失败时 staging 保留并写 best-effort failure marker |
| gate 被信号终止 | `128 + signal` | diagnostic，记录 raw returncode 与 signal |
| gate 返回 0，source 漂移或 closure/verify 失败 | `70` | diagnostic |
| gate 返回 0，finalizer 无法封存 | `70` | unsealed capture failure |
| preflight/source-before 失败、gate 未启动 | `70` | best-effort diagnostic，`gate.started=false` |
| CLI 参数错误 | `2` | 不创建伪运行 receipt |

若原 gate rc 大于 125，仍原样返回，并在 receipt 中分开记录 `raw_returncode`、`normalized_exit_code` 和 `signal`，避免仅凭数字猜测是否为信号。

## 6. Source snapshot 与历史验证

### 6.1 Source identity

`source.before.json` 和 `source.after.json` 至少包含：

- `head`：完整 40 位 commit。
- `tracked_patch`：`git diff --binary --full-index HEAD --` 的归档记录与 SHA-256，覆盖 staged、unstaged、删除和 mode 变化。
- `status`：稳定排序的 porcelain v1 `-z` bytes 的 hash，不用人类格式化文本替代。
- `untracked`：按原始 Git path bytes 排序的 ledger；每项记录 path、kind、mode、size 和 content/target SHA-256。
- `aggregate_sha256`：带类型、长度和域分隔的组合 hash，不能只拼接字符串。
- `captured_at_utc`，但时间不参与源码等价判断。

untracked 普通文件使用 `O_NOFOLLOW` 与读前/打开后/读后/路径当前身份比较后复制到 `source/<phase>/untracked/` 私有 snapshot。untracked symlink 不跟随，记录 link target 原始 bytes 和 symlink 自身身份；FIFO、device、socket 或读取中突变使 source snapshot 不可资格化。这样 symlink 新增、删除或 target 改变都会改变 source hash，同时不会读取链接目标。

### 6.2 两种 verifier 模式

`current-source`：重新采集当前 repo source identity。S15 起必须连续执行两次完整顺序 observation；两次不同即 `CURRENT_SOURCE_OBSERVATION_UNSTABLE`，相同后才与 receipt 的 before/after 比较。有效 CLI 结论固定为 `diagnostic-current-source-observation`、`transactional=false`、`aba_excluded=false`；它不再产生或传播 `implemented-unqualified`。程序化 API 返回的原 receipt document 不是本次 effective qualification。

`archived-integrity`：只重算归档的 tracked patch、untracked snapshot、ledger、artifact 和 receipt 交叉引用。它证明“归档字节自洽且未被修改”，不证明当前 checkout、原 Git object database、原容器或外部 runner 仍可重建，因此最高返回 `diagnostic-historical-integrity`，不映射为 schema v1 qualification。

完整历史重建需要 Git bundle、LFS object、lock/assets 和隔离恢复，属于 W7，不由 W1b 偷渡实现。

### 6.3 消除自引用

- run/staging/retention root 强制位于 repo 外，因此 receipt 和 logs 不进入 source hash。
- receipt 不包含自身 hash；外部 `index.jsonl` 可以记录 sealed `receipt.json` 的 hash，但 index 不进入该 receipt 的 closure。
- source snapshot 不排除仓库内 `docs/`。运行后把 receipt hash 回写文档会真实改变 source；旧 receipt 的 `current-source` 验证应失败，这是正确行为。
- 文档只记录稳定 run ID、历史 hash和明确的 diagnostic 标签。不得声称旧现场 manifest 仍匹配当前工作树。

## 7. Run directory 与 receipt 结构

建议布局：

```text
<retention-root>/
  .incomplete-<run-id>/
  <run-id>/
    receipt.json
    SEALED
    logs/stdout.bin
    logs/stderr.bin
    source/before.json
    source/before.patch
    source/before-untracked.json
    source/after.json
    source/after.patch
    source/after-untracked.json
    artifacts/<layer>/...
    inputs/uv.lock
    inputs/evidence-policy.json
    inputs/profile-manifest.json
    inputs/oracles/...
```

receipt 顶层建议扩展为：

```json
{
  "schema": "ai-auto-lrc/capture-receipt",
  "schema_version": 1,
  "run_id": "20260905T000000Z-128bit-random",
  "claim": {"layer": "portable", "spec_ids": []},
  "source": {
    "before": {"path": "source/before.json", "sha256": "...", "size": 0},
    "after": {"path": "source/after.json", "sha256": "...", "size": 0},
    "stable_during_run": true
  },
  "environment": {},
  "inputs": {},
  "run": {
    "gate_started": true,
    "command_id": "run-test-gate-portable-v1",
    "selectors": ["tests/unit", "tests/contract", "tests/component"],
    "started_at_utc": "...",
    "finished_at_utc": "...",
    "duration_ns": 0,
    "raw_returncode": 0,
    "normalized_exit_code": 0,
    "signal": null
  },
  "artifacts": {},
  "missing_artifacts": [],
  "verification": {"passed": true, "reason_codes": []},
  "qualification": {"level": "implemented-unqualified"}
}
```

所有 path 都相对 sealed run root，使用 POSIX 规范形式；artifact record 固定包含 path、size、SHA-256 和 media/type。绝对用户目录只允许作为 CLI 输入，不写入 JSON。stdout/stderr 按原始 bytes 留存，展示时再做 replacement decode，避免日志解码失败破坏 finalizer。

dirty tracked patch、未跟踪文件 snapshot 与原始日志可能包含敏感内容。W1b 仅允许在本机 `0700` run directory 中保存，不自动上传、同步、附加到 issue 或写入 Git；receipt 只保存相对路径和 hash。日志展示/导出执行 policy 驱动的脱敏，但原始归档是否加密、保存多久和由谁销毁仍属于 `D-REL`。封存前必须扫描 receipt、JUnit、gate JSON 和 logs 中已定义的 HOME/credential pattern；命中时将 run 标记为 diagnostic 并禁止导出，不能只保证 receipt 本身干净。W1b 不声称能发现所有 secret。

## 8. 分层 Artifact Closure

通用必需项：receipt、before/after source、stdout/stderr、runner identity、policy、`uv.lock`、JUnit 和 JUnit gate。任何层都要求 gate JSON 的 `input_junit_sha256`、`policy_sha256`、layer、run ID 与实际 artifact 一致；JUnit 统计由 verifier 重算。

### 8.1 portable

必需：

- `portable.xml`
- `portable-gate.json`
- `coverage.json`
- `coverage-gate.json`
- quality policy snapshot
- base-ref 与 changed-line policy identity

coverage gate 必须绑定 `coverage.json` hash、policy hash、base-ref 和同一 run ID。overall line、changed executable line、关键函数 line/branch 都由 verifier 或受控 gate JSON 重算/交叉检查；不采信 stdout 百分比。

### 8.2 package

必需：

- `package.xml`、`package-gate.json`
- wheelhouse `manifest.json` 的私有副本与 hash
- Linux/macOS 平台 verifier sidecar；单平台运行只声明该平台 scope
- 实际容器 image ID 与不可变 repo digest；只有 tag 时失败
- release sdist、从 sdist 构建的 project wheel及其 hash
- wheel tag audit、`.pth` before/after、`pip check`、direct dependency imports、installed `t2l.__file__`
- CLI 命令/exit/stdout/stderr hash 和网络拒绝 receipt

当前 Linux v10 目录可作为输入做回归，但其临时路径和旧测试结果不能直接转换为 W1b 受控 receipt。macOS 未通过时，package 最高只能记录 Linux `implemented-unqualified`，不得关闭 `PKG-012/017`。

### 8.3 canonical

必需：

- `canonical.xml`、`canonical-gate.json`
- feature、numeric、public-e2e 三份 oracle 的 snapshot/hash
- canonical Dockerfile hash、base image 不可变 digest
- 实际 build image ID/digest；可变 tag 仅作显示字段
- runtime network/read-only/platform/Python receipt
- installed package provenance 与 import location

在这些 sidecar 未落地前，W1b schema v1 即使封存 canonical 运行也只生成 diagnostic。现有 functional canonical 的资格事实保持原口径，不由事后 W1b receipt 追认。

## 9. Qualification 派生规则

schema v1 只允许：

```text
diagnostic
implemented-unqualified
```

`implemented-unqualified` 必须同时满足：

1. gate 由 capture 亲自启动且真实 exit 0；
2. before/after source aggregate 完全一致；
3. 分层 required closure 完整且没有未知同名替代件；
4. JUnit 非空，failed/errors/skipped 全为 0；
5. gate JSON、coverage/sidecar、policy、run ID 和输入 hash 交叉一致；
6. artifact snapshot 全部安全读取、hash 重算通过且封存后不可再写；
7. layer 的环境声明不超出实际观测 scope。

任一条件失败都派生为 diagnostic，并给出稳定、可多值的 reason code，例如：

- `GATE_NOT_STARTED`
- `GATE_EXIT_NONZERO`
- `SOURCE_CHANGED_DURING_RUN`
- `SOURCE_SNAPSHOT_UNSAFE`
- `REQUIRED_ARTIFACT_MISSING`
- `ARTIFACT_CHANGED_DURING_CAPTURE`
- `ARTIFACT_LAYER_MISMATCH`
- `RUN_ID_MISMATCH`
- `POLICY_HASH_MISMATCH`
- `IMAGE_DIGEST_MISSING`
- `JUNIT_INVALID_OR_EMPTY`
- `REQUIRED_TEST_SKIPPED`
- `FINALIZATION_FAILED`

producer 输入中出现 `qualified-canonical` 或 `qualified-release` 必须直接拒绝，不能静默降级后让调用方误解为接受。

## 10. 实施拆分与回滚点

| 批次 | 允许修改 | 产物 | 退出条件 | 回滚边界 |
|---|---|---|---|---|
| W1b-0 合同 | 新 contract tests、policy fixture | CLI、state machine、closure、exit/reason code 合同 | 负例先红且不依赖真实 Docker | 仅测试/fixture |
| W1b-1 capture core | `capture_test_gate.py`、W1a 可复用函数 | 独占 staging、前后 snapshot、subprocess、logs、finally receipt | fake gate 成功/失败/信号/源码漂移全通过 | capture + tests |
| W1b-2 portable closure | quality gate JSON、portable runner/tests | coverage 与 JUnit 同 run/hash/policy 闭包 | 本地 portable capture 可重算，0 skip | portable 增量 |
| W1b-3 package sidecar | package runner/verifier/tests | wheelhouse/image/sdist/wheel/tag/`.pth`/CLI sidecar | 真实 Linux v10 或新候选生成 W1b receipt；仍单平台 | package 增量 |
| W1b-4 canonical sidecar | canonical runner/tests | oracle/Dockerfile/base/build image receipt | pinned canonical capture 闭包通过；schema v1 不晋级 canonical | canonical 增量 |
| W1b-5 retention/doc | verifier、文档、操作说明 | current/archived 两种验证模式、无自动删除 | 定向回归和全量静态门禁通过 | verifier/doc 增量 |

每批提交前都可单独回滚；不得把 W1b-3/4 的 Docker 高成本验证与 `.venv` 并发运行。若仅文档发生变化，不重复高成本 canonical；若 canonical Dockerfile/oracle/production provenance 变化，按现有 candidate 审查顺序重跑。

## 11. 可执行测试目录

以下为候选测试名，不自动成为 `tests/spec_inventory.json` 的稳定规格 ID；只有实现和证据通过后才登记。

| ID | 建议 nodeid/层级 | 故障注入 | 必须断言 |
|---|---|---|---|
| W1B-T01 | `test_capture_creates_exclusive_run_directory` / contract | 固定随机源碰撞、已存在目录 | 使用 `exist_ok=False` 失败，绝不复用旧目录 |
| W1B-T02 | `test_capture_overrides_stale_artifact_environment` / contract | 调用环境预置旧绿色目录 | 子进程只收到本次 staging path，旧文件未进入 receipt |
| W1B-T03 | `test_capture_launches_gate_and_records_real_exit` / contract | fake runner 返回 0/1/5/70 | receipt 和进程返回来自真实子进程，不存在外部 exit 输入 |
| W1B-T04 | `test_failed_gate_is_sealed_diagnostic` / contract | pytest 写 JUnit 后 exit 1 | receipt 存在、含 logs/JUnit、qualification=diagnostic、返回 1 |
| W1B-T05 | `test_failure_before_junit_records_missing_artifact` / contract | runner 在写 JUnit 前 exit 2 | 不拾取旧 JUnit，missing 字段明确，返回 2 |
| W1B-T06 | `test_finalizer_failure_does_not_mask_gate_failure` / contract | gate exit 5，finalizer fsync/rename 失败 | 进程仍返回 5，staging 含 best-effort marker |
| W1B-T07 | `test_finalizer_failure_after_green_gate_returns_capture_error` / contract | gate 0，原子 rename 失败 | 返回 70，不能输出绿色 qualification |
| W1B-T08 | `test_signal_is_recorded_and_normalized` / contract | SIGINT/SIGTERM 子进程 | signal/raw rc/normalized rc 明确，diagnostic，capture 不死锁 |
| W1B-T09 | `test_source_hash_binds_all_git_states` / contract | staged、unstaged、删除、mode、untracked binary | 每一项分别改变 aggregate；恢复后回到基线 |
| W1B-T10 | `test_untracked_symlink_is_hashed_without_following` / contract | 新建/改 target/删 symlink | hash 随 link 自身变化，不读取 target 内容 |
| W1B-T11 | `test_special_untracked_file_blocks_qualification` / contract | FIFO/socket/device fixture | 安全失败或 diagnostic，不阻塞等待读取 |
| W1B-T12 | `test_source_change_during_gate_forces_diagnostic` / contract | gate 中修改 tracked/untracked/symlink | gate 0 仍返回 capture error，reason 为 source changed |
| W1B-T13 | `test_source_change_then_restore_is_detected_when_observable` / contract | 运行中改写再恢复、保留时间/identity ledger | 若 before/after 无法证明中间变化，不声称连续不变；至少记录观测模型限制 |
| W1B-T14 | `test_retention_root_must_be_outside_repo_and_non_symlink` / contract | repo 内、同目录、symlink parent | preflight 拒绝，gate 不启动 |
| W1B-T15 | `test_artifact_snapshot_rejects_rename_and_in_place_mutation` / contract | 读取期间 rename/覆盖 | 无 receipt 晋级，不发布半成品 sealed dir |
| W1B-T16 | `test_artifact_written_after_gate_window_is_rejected` / contract | gate 结束后后台进程后写 | 身份/时间/hash不一致，diagnostic |
| W1B-T17 | `test_junit_gate_must_bind_same_run_layer_policy_and_hash` / contract | 混合不同 run/layer/policy/JUnit | 各字段逐项 fail closed，稳定字段路径 |
| W1B-T18 | `test_manifest_counts_are_recomputed_from_junit` / contract | 篡改 passed/failed/error/skipped | verifier 不信声明统计 |
| W1B-T19 | `test_portable_requires_complete_coverage_closure` / contract | 逐项删除/替换四件套 | JUnit、JUnit gate、coverage、coverage gate 缺一即 diagnostic |
| W1B-T20 | `test_package_requires_immutable_image_and_sidecars` / contract | tag-only、短 digest、错误 sdist/wheel hash、缺 `.pth`/CLI | 逐项拒绝；只接受实际 `sha256:<64hex>` |
| W1B-T21 | `test_canonical_requires_oracles_and_build_image_receipt` / contract | 缺任一 oracle、Dockerfile/base/build image | 逐项拒绝，tag 不可替代 digest |
| W1B-T22 | `test_cross_layer_artifact_substitution_fails` / contract | portable/package/canonical 互换 | classname、policy、run ID 和 closure 均阻止拼接 |
| W1B-T23 | `test_current_source_verification_detects_checkout_drift` / contract | sealed 后更新 docs/代码 | current-source 失败；原 receipt 不被重写 |
| W1B-T24 | `test_archived_integrity_verifies_bytes_but_never_qualifies` / contract | 无原 repo，仅保留 run dir | hash 自洽可报告历史完整性，qualification 仍 diagnostic |
| W1B-T25 | `test_receipt_and_index_have_no_hash_cycle` / contract | 写 receipt 后写 sibling index | receipt hash 稳定；index 不进入 receipt closure |
| W1B-T26 | `test_self_asserted_high_qualification_is_rejected` / contract | 输入 canonical/release 高资格字符串 | schema v1 直接失败，不接受也不静默降级 |
| W1B-T27 | `test_no_partial_sealed_directory_on_crash` / contract | 在每个 state transition 注入异常 | 只有 `.incomplete-*` 或完整 sealed dir，不出现半成品正式目录 |
| W1B-T28 | `test_logs_are_binary_safe_and_secret_redacted_by_policy` / contract | 非 UTF-8 与已定义 secret marker | 原始 bytes 可封存；展示/导出遵循脱敏策略，receipt 不含凭证 |

W1B-T13 必须在文档和实现里诚实限定：仅比较 before/after 不能证明运行期间从未瞬时改变后又恢复。若要强证明，需要只读源码 snapshot 中运行 gate，或文件系统监控/命名空间隔离。W1b 最小版应把 gate 输入切换到私有 source snapshot 作为后续增强；在此之前 qualification 文案只能说“运行前后身份一致”，不能说“运行期间绝无变化”。

## 12. 验证命令与完成定义

实现阶段的最小定向命令：

```bash
uv run --frozen --no-sync python -m pytest \
  tests/contract/test_evidence_manifest.py \
  tests/contract/test_evidence_capture.py \
  tests/contract/test_quality_gates.py \
  -q -p no:cacheprovider

uv run --frozen --no-sync ruff check scripts tests/contract
uv run --frozen --no-sync python -m compileall -q scripts tests
git diff --check
```

分层接入后再依次执行 portable、package、canonical；高成本容器门禁串行。没有显式 wheelhouse 时 package 的 skip 是预期 No-go，不得删测试或改为绿。

W1b 只有同时满足以下条件才完成：

1. capture runner 亲自启动现有 gate，API/CLI 无自报 exit/statistics/qualification 入口。
2. 独占目录、before/after source、finally receipt、原 gate rc 优先级均有自动化测试。
3. portable closure 在真实本地运行中零 skip 并能由新 verifier 重算。
4. package Linux sidecar 在真实断网 cold gate 中闭合；仍明确为单平台 implemented-unqualified。
5. canonical sidecar 绑定实际 build image 与三份 oracle；schema v1 仍不产生 qualified-canonical。
6. current-source 和 archived-integrity 两种模式边界清晰，旧 dirty evidence 不被追认。
7. 所有可处理失败路径都保留 diagnostic 或明确的 unsealed failure，不出现正式目录中的半成品；`SIGKILL`、掉电和介质失效只要求遗留目录没有有效 `SEALED` marker，不能承诺生成 receipt。
8. 文档、contract tests、inventory 状态与实际代码一致；静态/构建门禁通过。

完成 W1b 仍不能解除 Release No-go。之后依赖 `D-REL` 批准 retention/owner，依赖 `D-MAC` 完成双平台，依赖 W3-W6 和 W7 完成恢复、SBOM、attestation、签名与 rollback，才允许讨论 schema 升级和更高资格。

## 13. 当前现场证据勘误

`/tmp/ai-auto-lrc-w1-portable.Pd78d5/evidence-manifest.json` 曾在生成当时通过本地 W1a 重算，SHA-256 为 `8299bf756f5298adc0f911355f037a6b6b480046f21e58ff4361340cf560c582`。其后仓库文档继续更新，因此它现在用 `current-source` 语义校验会以 source mismatch 失败；这是预期的 fail-closed 行为。

这份文件只能作为历史 diagnostic 示例，不是当前工作树 evidence、W1b receipt、canonical/package 资格证据或 release artifact。后续 shell 检查退出码使用 `rc=$?`，不要使用 zsh 只读变量名 `status`。

## 14. 2026-09-05 第一纵切实施快照

本节是 W1b-0、W1b-1 和 W1b-2 当时的实施快照。W1b-3 的后续完成状态见第 16 节，W1b-4 见第 18 节；本节时点的 W1b-4 canonical sidecar，以及 W1b-5 的长期 retention owner、加密/销毁和 secret 导出策略均为 No-go。

### 14.1 已实现

- 新增 `scripts/capture_test_gate.py`：只接受 layer/base-ref/retention root/repo root，由它亲自启动 `scripts/run_test_gate.sh`，不存在外部 exit/statistics/qualification 参数。
- 每次运行创建仓库外、路径链无 symlink、随机且独占的 `0700` `.incomplete-<run-id>`；receipt 与 `SEALED` marker 完成后将内容和根目录设为只读，并在同一文件系统原子 rename。
- 运行前后保存 HEAD、binary/full-index tracked patch、NUL status、untracked regular bytes、symlink target 和 source aggregate。aggregate 不含 mtime/ctime；特殊文件使 run 只能 diagnostic。
- stdout/stderr 按原始 bytes 保存。receipt 只记录异常类型，不记录可能包含用户路径的异常消息。
- gate 运行在独立进程组；父进程捕获 SIGINT/SIGTERM 后转发给整组，等待子进程结束，再封存 signal/raw/normalized exit。`SIGKILL`、掉电和介质失效仍不承诺 receipt。
- finalizer 失败时，gate 已非零则返回原 gate rc；gate 原为 0 才返回 capture error 70。正式 sealed 目录必须通过一次 `archived-integrity` 自校验。
- verifier 强制检查 `SEALED` 对 receipt hash 的绑定、只读根目录、目录名/run ID、完整文件闭包、source snapshot、artifact hash、missing closure、退出码和派生 qualification 一致性。
- portable JUnit 与 coverage gate 同时绑定同一 run ID、输入 artifact SHA-256、quality policy SHA-256 和 base-ref；JUnit count/skip/failure 从 testcase 重算。
- 在 W1b-0/1/2 快照时，package/canonical 固定加入 `LAYER_CLOSURE_UNIMPLEMENTED`，即使存在占位 sidecar 也只能 diagnostic。第 16 节完成后 package 已改为语义闭包；canonical 仍保持该失败原因。

### 14.2 自动化反证

`tests/contract/test_evidence_capture.py` 现有 28 个实例，覆盖：三层独占目录、旧 artifact 环境覆盖、四类 gate 非零 rc、source 漂移、缺件、二进制日志、`SEALED`、高资格自报、staged/unstaged/delete/rename/mode/untracked binary/symlink、FIFO、并发 capture、额外 artifact、seal 失败、历史 untracked snapshot 篡改、current-source 漂移和 SIGTERM 转发。

capture、quality gate 与 W1a manifest 合同合并定向结果为 `48 passed`。完整宿主回归为 `349 passed, 18 skipped, 22 warnings in 48.18s`；18 个 skip 仍是 13 个 canonical-only golden 与 5 个未注入 wheelhouse 的 package gate，不是 Release 零 skip。

### 14.3 真实 portable capture

真实 capture 在仓库外生成并封存：

- run ID：`20260904T204120193767Z-1e4d03f61ed04d51b08dbc9525f93fb1`
- 运行时结果：`311 passed, 22 warnings, 0 skipped`
- receipt SHA-256：`1ebe778101a225c041999fc95fa5ec2944d3801ea9469b912849e2d0047f0988`
- JUnit：311 tests、0 skipped、0 failure/error；输入 SHA-256 `0b54f481b08e59a19e12d011f02bb39c9da4687c25ddfba7334e0f86f22fd65b`
- coverage 输入 SHA-256：`7f0fcd47bfe1a27ed9226d57c9fffe72f5b6fafc749e43e5443268ba96b56c55`
- policy SHA-256：`534103ffc0719277101e99300ff37f590f19206dbe30e4ac5f4094da9c120676`
- overall pure line：`1726 / 1975 = 87.392405%`
- changed executable line：`1696 / 1868 = 90.792291%`
- archived-integrity：valid，effective qualification 固定为 historical diagnostic
- current-source：在记录本节前验证为 valid、`implemented-unqualified`

将本节写入仓库后 source hash 必然变化，因此上述 receipt 随即转为历史 diagnostic；这是预期行为，不是证据损坏。最终当前工作树验证必须在所有文档更新之后重新 capture，并且不得把该 receipt hash 再回写仓库形成循环。

macOS 上 `/tmp` 是 symlink，preflight 已实际以 exit 70 拒绝 `/tmp/...` retention root且未启动 gate；成功运行使用真实路径 `/private/tmp/...`。操作文档后续必须使用真实路径或先解析并显式确认目标，不得静默放宽 symlink 规则。

### 14.4 package 预期失败回执

未注入 `AI_AUTO_LRC_WHEELHOUSE` 时，package capture 的 pytest 结果为 `29 passed, 5 skipped`，required verifier 返回 1；capture 原样返回 1 并封存 diagnostic。receipt SHA-256 为 `59d66abb93e932ed3fff034ae45cfdab927c6535af6f670668f9c726efb92bbf`，原因精确为：

- `GATE_EXIT_NONZERO`
- `REQUIRED_ARTIFACT_MISSING`：`package-platform.json`、`wheelhouse-manifest.json`
- `LAYER_CLOSURE_UNIMPLEMENTED`

该历史负例证明失败可留存且不能假绿，不证明 package 资格。第 16 节已使用 Linux v10 接入完整 sidecar 并重新 capture；macOS 仍受 `D-MAC` 阻塞。

### 14.5 静态和构建

以下命令均通过：Ruff 全仓、compileall、`uv lock --check`、`uv build --no-python-downloads`、`git diff --check`。本地构建 hash：

- wheel：`880b2a4c5ece1cbb0e5c793e96c3ba0f6f05a4bc1475b552a7ac6b6c787544ef`
- sdist：`ba54d172b173784b9dae05e3112db4a3a48e205d27e97f5b8e8cbd5e57ad6d7a`

本轮未修改 production audio/lyrics/inference、三份 oracle 或 canonical Dockerfile，因此没有重复执行高成本 canonical；最近有效的 functional canonical 仍保持原口径，不能被本节外推为 release provenance。

## 15. W1b-3 Linux package sidecar 可执行方案

本节是 W1b-3 的唯一字段级实施入口。它细化第 8.2、10、11 节，但不改变它们的资格边界：完成本节最多得到 Linux x86_64/CPython 3.11 scope 的 `implemented-unqualified`，不会关闭 macOS、`PKG-012/017` 或 Release No-go。

### 15.1 纵切边界与不变量

- capture 仍是唯一顶层编排者；package producer 不接受外部注入的 exit、统计或 qualification。
- producer 必须继承 `AI_AUTO_LRC_EVIDENCE_RUN_ID`，其 sidecar、`package-gate.json` 和 receipt 的 run ID 必须完全相同。
- 成功 package run 精确新增两个普通文件：`package-platform.json` 与 `wheelhouse-manifest.json`。后者必须是输入 `manifest.json` 的逐字节私有副本；不复制约 328 MiB wheelhouse。
- `package-platform.json` 只保存相对路径、稳定枚举、计数、size/hash 和命令 ID；不得保存宿主绝对路径、完整环境、token、可复用凭证或临时容器路径。
- image 必须同时有实际 image ID 和不可变 repo digest；`python:3.11.9-slim-bookworm` 之类 tag 只能作为显示字段，不能满足合同。
- 无 wheelhouse、package JUnit/gate 非零或 required skip 时不生成占位 sidecar；capture 保留原 gate exit，并以缺件原因封存 diagnostic。
- sidecar 写入使用同目录临时文件、flush/fsync 和原子 replace；capture 封存前仍执行稳定读取、完整闭包和 hash 复验。

### 15.2 组件责任与允许修改范围

| 组件 | 单一责任 | 本批允许修改 |
|---|---|---|
| `scripts/run_test_gate.sh` | package JUnit 通过后调用平台 producer；传递本次 artifact root 与 run ID | 只改 package 分支与错误传播 |
| `scripts/run_linux_package_gate.py` | 在宿主解析 immutable image、启动断网只读容器、收集 verifier JSON、原子写两个 sidecar | 新文件及其 contract tests |
| `scripts/verify_linux_offline_wheelhouse.py` | 在容器内完成私有 snapshot、离线 sdist build/install、`.pth`、imports、CLI 和 network probe，并输出无绝对路径的 observation | 扩展 observation；不得自行宣称 qualification |
| `scripts/capture_test_gate.py` | 对 package sidecar 做语义重算和跨件绑定；仅在该 verifier 完整后移除 package 的 `LAYER_CLOSURE_UNIMPLEMENTED` | package 分支；portable/canonical 语义不变 |
| `tests/contract/test_evidence_capture.py` | schema、篡改、缺件、跨 run/layer、原子失败的快速反证 | W1b-3 contract cases |
| `tests/package/test_offline_wheelhouse.py` | 真实 Linux positive 与平台内 verifier 行为 | 只增加可复用 producer/observation 断言 |

本批禁止修改 `t2l/` production 语义、三份 canonical oracle、canonical Dockerfile、`uv.lock`、依赖版本或 macOS 制品策略。若实现暴露这些变更需求，停止 W1b-3 并建立独立工作包；不得把它们夹带进 sidecar 提交。

### 15.3 `package-platform.json` schema v1

顶层键必须精确为以下集合，未知键、缺键或错误类型都 fail closed：

```json
{
  "schema": "ai-auto-lrc/package-platform",
  "schema_version": 1,
  "run_id": "<capture-run-id>",
  "layer": "package",
  "scope": {},
  "image": {},
  "network": {},
  "wheelhouse": {},
  "build": {},
  "installation": {},
  "cli": {}
}
```

字段合同：

| 对象 | 必填字段 | verifier 规则 |
|---|---|---|
| `scope` | `os=linux`、`arch=x86_64`、`python_implementation=CPython`、完整 `python_version`、`platform=linux-x86_64` | 与容器内 runtime observation 和 wheelhouse target 逐项一致；不得仅信 CLI 参数 |
| `image` | `image_id=sha256:<64hex>`、`repo_digest=<name>@sha256:<64hex>`；可选 `display_tag` | 宿主通过 inspect 得到；tag、短 digest、ID/digest 缺一均拒绝 |
| `network` | `policy=denied`、`probe=connect_ex`、`blocked=true`、`result_code` | 容器以 `--network none` 运行且 probe 不可连通；只写命令参数而无运行 probe 不成立 |
| `wheelhouse` | `manifest_path=wheelhouse-manifest.json`、`manifest_sha256`、`runtime_wheel_count`、`build_wheel_count`、`artifact_count`、`aggregate_sha256` | manifest 私有副本的 hash 必须一致；计数和 aggregate 从副本重算，不采信 producer 声明 |
| `build` | `source=sdist`、`sdist` record、`project_wheel` record、`runtime_wheel_tags`、`build_wheel_tags`、`project_wheel_tags` | record 含规范 basename、size、SHA-256；sdist 必须来自 manifest；project wheel 必须唯一且确由 sdist 构建；所有 tag 可解析且匹配 scope |
| `installation` | `pip_check_exit_code=0`、`pip_check_stdout_sha256`、`pip_check_stderr_sha256`、`pth_before`、`pth_after`、`direct_imports`、`installed_package` | `.pth` record 相对 venv root 且 before/after 完全相等；imports 与版本化 policy 的模块集合完全一致；installed package 只记录 `site-packages` 内相对路径和文件 hash |
| `cli` | `command_id=installed-public-e2e-v1`、`exit_code=0`、`stdout_sha256`、`stderr_sha256`、`expected_stdout_sha256` | 执行 installed console script；stdout hash 必须等于冻结期望，stderr 为空值也以 hash 表示；不得写真实 argv 绝对路径 |

所有 artifact record 使用 `{name, size, sha256}`；所有 hash 为小写 64 位十六进制。数组必须稳定排序且无重复。sidecar 自身不包含自身 hash；其 size/hash 由外层 capture receipt 记录。

### 15.4 producer 与 capture 数据流

```text
capture_test_gate.py (run ID / exclusive staging)
  -> run_test_gate.sh package
     -> pytest tests/package -> package.xml
     -> verify_quality_gates.py -> package-gate.json
     -> run_linux_package_gate.py
        -> stable-read wheelhouse manifest
        -> inspect immutable image ID/repo digest
        -> docker --network none --read-only
           -> verify_linux_offline_wheelhouse.py observation
        -> recompute/link observations
        -> atomic package-platform.json + wheelhouse-manifest.json
  -> capture semantic verifier
     -> JUnit/gate/run ID/manifest/image/sidecar cross-check
     -> source after snapshot
     -> diagnostic or implemented-unqualified receipt
```

runner 不得从 pytest stdout 抓取一段 JSON 后直接视为合格。宿主 producer 必须验证容器进程 exit、JSON schema、run ID、image identity 与 manifest link，然后才原子发布 sidecar。capture 再独立重算能够重算的字段，形成两层拒绝面。

### 15.5 实施 DAG 与回滚点

| 子批次 | 前置 | 实施与 RED/GREEN 产物 | 完成条件 | 回滚边界 |
|---|---|---|---|---|
| W1b-3a 合同冻结 | W1b-2 | schema fixture、parser、逐字段负例；先证明当前占位 sidecar被拒绝 | 新测试因语义 verifier 缺失而红，不依赖 Docker | 仅 fixtures/tests/docs |
| W1b-3b 容器 observation | 3a | 扩展 Linux verifier，输出 scope/network/build/install/CLI observation | 轻量 fake 与现有真实 verifier 测试通过；无绝对路径 | verifier/tests |
| W1b-3c 宿主 producer | 3b | 新 runner 解析 image identity、原子写 sidecar/manifest 副本 | tag-only、容器失败、半写、manifest race 全部失败关闭 | runner/tests |
| W1b-3d capture 集成 | 3c | `run_test_gate.sh` 接线；capture package 语义验证 | 只对 package 移除 `LAYER_CLOSURE_UNIMPLEMENTED`；portable/canonical 不变 | package 接线增量 |
| W1b-3e 真实复验 | 3d | 使用 Linux v10 或新候选进行一次 capture-bound run | package required 零 skip、sidecar 可重算、source before/after 相等 | 只保留 sealed evidence；不改源码 |

回滚只能撤回本批新增文件和明确的 package 增量；不得执行 `git reset --hard`、`git checkout --`、清理 untracked 文件或恢复用户现有 dirty worktree。

### 15.6 W1b-3 测试矩阵

以下是 W1b-3 的候选用例名；实现并产生证据前不进入稳定 inventory：

| ID | 层级/建议 nodeid | 注入 | 必须断言 |
|---|---|---|---|
| W1B-PKG-T01 | contract `test_package_sidecar_requires_exact_schema` | 缺键、未知键、错误类型、错误 layer | 逐项拒绝，稳定 reason path |
| W1B-PKG-T02 | contract `test_package_sidecar_binds_capture_run_id` | sidecar/gate/receipt 三个不同 run ID | 不得拼接历史绿色 sidecar |
| W1B-PKG-T03 | contract `test_package_sidecar_requires_immutable_image_identity` | tag-only、短 digest、缺 image ID/repo digest | `IMAGE_DIGEST_MISSING` 或更具体稳定原因；diagnostic |
| W1B-PKG-T04 | contract `test_package_manifest_copy_is_byte_exact_and_recomputed` | manifest 副本变更、计数/hash/aggregate 伪造 | 从副本重算并拒绝；不打开原 wheelhouse |
| W1B-PKG-T05 | contract `test_package_build_records_bind_sdist_and_project_wheel` | 错 sdist、两个 project wheel、hash/size/tag 不符 | 每种变体 fail closed |
| W1B-PKG-T06 | contract `test_package_pth_snapshots_must_be_equal_and_internal` | 新增/删除/改写 `.pth`、绝对外部路径 | 拒绝安装证据，不泄露真实路径 |
| W1B-PKG-T07 | contract `test_package_import_set_and_installed_origin_are_closed` | 少一个模块、重复模块、checkout origin、site-packages 外路径 | 与 policy 集合精确匹配，源码导入不能冒充安装验证 |
| W1B-PKG-T08 | contract `test_package_cli_receipt_is_exact` | 非零 exit、stdout/stderr hash 伪造、错误 command ID | 全部 diagnostic；不采信日志摘要 |
| W1B-PKG-T09 | contract `test_package_network_receipt_requires_observed_denial` | `blocked=false`、缺 probe、仅声明 `--network none` | 必须有实际 probe 结果且容器配置一致 |
| W1B-PKG-T10 | contract `test_package_sidecars_are_atomic_and_regular` | symlink、FIFO、写中失败、发布后替换 | 无半成品正式文件；capture 拒绝非普通文件和身份变化 |
| W1B-PKG-T11 | contract `test_package_without_wheelhouse_emits_no_placeholder_sidecar` | 不设置 wheelhouse | 保留 package gate 非零/required skip；缺两个 sidecar；无假绿 |
| W1B-PKG-T12 | package/system `test_linux_package_capture_closes_real_sidecar` | pinned digest + 真实 wheelhouse + 断网容器 | JUnit 零 skip、sidecar 全字段可重算、receipt 最高 Linux implemented-unqualified |
| W1B-PKG-T13 | contract `test_package_sidecar_cannot_upgrade_other_platforms` | Linux sidecar 自报 macOS/dual/release | 拒绝或仅保留 Linux scope；`PKG-012/017` 不变 |
| W1B-PKG-T14 | contract `test_package_artifacts_reject_secret_and_absolute_path_export` | HOME、token sentinel、容器临时绝对路径 | sealed 原始件可本地保留但禁止导出/晋级；展示输出脱敏 |

QA 放行顺序固定为：schema 负例 -> producer 单元/合同 -> package 定向 -> capture 定向 -> 真实 Linux positive -> 宿主全量与静态门禁。真实 positive 不能替代任一负例，历史 Linux v10 输出也不能事后拼装成新 receipt。

### 15.7 验证命令和 W1b-3 完成定义

实现时先运行快速门禁：

```bash
uv run --frozen --no-sync python -m pytest \
  tests/contract/test_evidence_capture.py \
  tests/contract/test_package_platform_gate.py \
  tests/contract/test_evidence_manifest.py \
  tests/contract/test_quality_gates.py \
  tests/package/test_offline_wheelhouse.py \
  -q -p no:cacheprovider

uv run --frozen --no-sync ruff check scripts tests
uv run --frozen --no-sync python -m compileall -q scripts tests
uv lock --check
git diff --check
```

真实 capture 必须使用仓库外、路径链无 symlink 的 retention root；macOS 上使用 `/private/tmp/...` 而不是 `/tmp/...`。高成本 package capture 与 canonical、其他 `.venv` 操作串行。具体 Linux image 必须以批准的 digest 形式传入，不在文档中固定可能漂移的 tag。

W1b-3 只有同时满足以下条件才为 Go：

1. 14 个候选风险点中所有已实现合同均有唯一 nodeid，至少包含 T01–T13；T14 若 secret 导出仍未实现，明确留在 W1b-5 且 package qualification 继续受限。
2. package producer 由真实 gate 调用，sidecar 与 manifest 副本原子发布并绑定同一次 run ID；无外部自报结果入口。
3. capture 对 schema、image、manifest、build、`.pth`、imports、CLI、network 和 scope 做语义验证，不再只检查文件存在。
4. 无 wheelhouse 负例仍按真实 gate rc 失败并保存 diagnostic；不得通过生成空 sidecar 或删除 skip 变绿。
5. 真实 Linux x86_64/CPython 3.11 capture 中 package required 零 skip，source before/after 相等，sealed receipt可在 current-source 与 archived-integrity 各自边界内验证。
6. qualification 最高为 Linux scope `implemented-unqualified`；macOS、双平台和 release 表项保持 No-go。
7. 文档、测试 inventory、静态/构建检查同步；未创建 CI workflow、commit、push、签名、上传、自动 prune 或发布。

W1b-3 完成后按第 10 节进入 W1b-4；W1b-5 的 owner、期限、加密、销毁和 secret export 仍由 `D-REL` 决定，不能由实现者自行默认。

## 16. W1b-3 实际落地与恢复状态

本节是 2026-09-05 的实施回写，覆盖第 15 节中的 W1b-3a–3e。第 15 节继续作为字段和失败合同；本节记录已发生的代码、测试和真实证据。W1b-3 现为 **Go（仅 Linux x86_64/CPython 3.11、implemented-unqualified）**，不表示 W1b 整体完成。

### 16.1 已实现的数据路径

- `scripts/verify_linux_offline_wheelhouse.py` 在 `linux/amd64` 容器内输出 schema v1 observation，记录真实断网 probe、manifest closure、sdist build、runtime/build/project wheel tags、`.pth` 前后快照、`pip check`、固定 direct imports、site-packages 相对安装来源和 installed CLI stdout/stderr hash；不输出绝对路径，也不自报 qualification。
- `scripts/run_linux_package_gate.py` 只接受完整 `repo@sha256:<64hex>`，经 `docker image inspect` 绑定 repo digest 与实际 image ID，并按 image ID 启动 `--network none --read-only` 容器。它不挂载完整 checkout，只构造仓库外的最小只读 evidence bundle；manifest 运行前后稳定读取，两个 sidecar 同目录原子发布，第二件发布失败时回滚第一件。
- `scripts/run_test_gate.sh` 以 `AI_AUTO_LRC_PACKAGE_SCOPE=linux-x86_64` 选择 common + Linux package cases；capture-bound 运行还必须提供 `AI_AUTO_LRC_WHEELHOUSE`、`AI_AUTO_LRC_PACKAGE_IMAGE` 和由 capture 注入的 `AI_AUTO_LRC_EVIDENCE_RUN_ID`。未设置 scope 时保留默认 package 行为和五个无 wheelhouse skip 反证。
- `scripts/capture_test_gate.py` 独立重算 JUnit、quality gate、policy、run ID、manifest hash/count/aggregate 以及 sidecar 的 scope/image/network/build/install/CLI 语义。完整 package closure 移除 package 的 `LAYER_CLOSURE_UNIMPLEMENTED`；缺件使用 `REQUIRED_ARTIFACT_MISSING`，语义或跨件绑定错误使用 `RUN_ARTIFACT_BINDING_INVALID`。本节 W1b-3 快照时 canonical 仍固定 `LAYER_CLOSURE_UNIMPLEMENTED`；该状态已由第 18 节取代。
- `verify_receipt()` 对封存文件重新执行 package 语义验证；sidecar 无权自行提升 macOS、双平台、canonical 或 release 资格。

### 16.2 测试映射与失败合同

第 15.6 节的 T01–T13 已落到以下可执行测试面；参数化 case ID 是具体反证身份，T12 以真实 capture run ID 作为系统证据身份，避免在 package pytest 内递归启动自身：

| 风险组 | 当前可执行入口 |
|---|---|
| T01/T02/T04–T09/T13 | `tests/contract/test_evidence_capture.py::test_package_sidecar_semantic_mutations_are_diagnostic`、`::test_package_gate_must_bind_same_run_junit_and_policy`、`::test_package_junit_must_be_nonempty_green_and_package_scoped` |
| T03/T04/T10 | `tests/contract/test_package_platform_gate.py::test_producer_rejects_nonimmutable_image_reference_before_docker`、`::test_producer_requires_inspected_image_id_and_exact_repo_digest`、`::test_producer_rejects_manifest_identity_race`、`::test_atomic_publish_failure_leaves_no_formal_sidecar` |
| T06/T07/T08 | `tests/package/test_offline_wheelhouse.py::test_linux_container_observation_is_complete_stable_and_path_free` 及 `.pth`/direct-import 负例；producer 的 non-empty stderr 正例；capture 的 CLI hash 负例 |
| T10 | producer 的 absolute-path/secret、原子发布失败测试，加上 capture 的额外/非普通 artifact closure 测试 |
| T11 | `tests/contract/test_evidence_capture.py::test_missing_package_sidecars_preserve_nonzero_gate_exit` 和真实无 wheelhouse capture |
| T12 | `capture_test_gate.py run --layer package` 的真实 Linux capture，四件套和两种 verify mode 均验证 |
| T14 | 只完成 producer 侧“不写入绝对路径/secret material”；长期扫描、导出、加密、销毁与资格语义仍归 W1b-5，未宣称完成 |

真实门禁还暴露并关闭了一个仅靠 fake fixture 未发现的问题：`verify_quality_gates.py` 的标准 package gate 合法包含 `required_markers`、`outside_layer` 和 `failures`，consumer 曾用整对象相等错误拒绝它。修复后 consumer 逐项绑定核心字段，并要求 `required_markers=["package"]`、`outside_layer=[]`、`failures=[]`；对应正例和三组篡改负例已进入合同测试。

### 16.3 真实 Linux capture 证据

实施完成后的文档写入前 capture：

- 运行目录：`/private/tmp/ai-auto-lrc-w1b3-positive-final3.vEkfd3/20260904T215919887040Z-60c862bb3b484a14963a963822fe10dc`
- package gate：`33 passed, 3 deselected, 0 skipped`，raw/normalized/capture exit 均为 `0`。
- image repo digest：`python@sha256:8fb099199b9f2d70342674bd9dbccd3ed03a258f26bbd1d556822c6dfc60c317`；实际 image ID：`sha256:65a6ce634d975b67ee77c8d0f59248cbcb9d8b8f229d584c3cf5d624038bf963`。
- wheelhouse manifest SHA-256：`f5d0157395ba10b0a29ea595fb5c33ac276e54a5c2a2cbda2f7e756f9127cd7a`；四件套为 `package.xml`、`package-gate.json`、`package-platform.json`、`wheelhouse-manifest.json`。
- source before/after aggregate 均为 `b58f5b815d60eba1a7008d108733f40720184e4888da5f24106b4eab0bfe7017`，`stable_during_run=true`。
- `current-source` 当时验证为 valid、effective `implemented-unqualified`；`archived-integrity` 验证为 valid、effective `diagnostic-historical-integrity`。本节写入后该 run 按设计只再作为历史完整性证据；最终 current-source receipt 必须在全部文档更新后另行生成，且其 hash 不再回写仓库。

真实无 wheelhouse 负例保留 gate exit `1`，没有生成占位 sidecar，receipt 为 diagnostic；缺件精确为 `package-platform.json`、`wheelhouse-manifest.json`，原因是 `GATE_EXIT_NONZERO` 与 `REQUIRED_ARTIFACT_MISSING`。package 已不再使用 `LAYER_CLOSURE_UNIMPLEMENTED`。

### 16.4 当前验证与剩余 No-go

- W1b-3 联合快速层：`155 passed, 5 skipped`；五个 skip 都是未为默认 package run 注入 wheelhouse 的预期反证。
- 宿主全量：`421 passed, 18 skipped, 22 warnings`；18 个 skip 为 13 个 canonical-only golden 和 5 个默认 package wheelhouse case，不是 release 零 skip。
- Ruff 全仓、compileall、`bash -n scripts/run_test_gate.sh`、`uv lock --check`、`uv build --no-python-downloads` 与 `git diff --check` 均通过。
- 本节 W1b-3 快照时，W1b-4 canonical sidecar、W1b-5 retention/secret export、macOS cold install、`PKG-012/017` 双平台、资源预算、Demucs 真实离线权重/许可、`AlignmentRuntime.close()`、恢复、SBOM、attestation、签名和 rollback 均为 No-go；当前 W1b-4 已由第 18 节关闭，其余项与 Release 继续 **No-go**。

## 17. W1b-4 canonical sidecar 可执行方案

本节是 W1b-4 的唯一字段级实施入口；四角色原始结论见 [`team-session-2026-09-06.md`](./team-sessions/team-session-2026-09-06.md)。目标是把已有 Linux x86_64/CPython 3.10 functional canonical verify 纳入同一次 capture，而不是重新生成 oracle或扩大资格。实施完成后最高仍为 schema v1 `implemented-unqualified`。

### 17.1 边界与正式 artifact closure

capture-bound canonical 成功运行必须精确生成以下普通文件：

```text
canonical.xml
canonical-gate.json
canonical-runtime.json
canonical-Dockerfile
canonical-feature-oracle.json
canonical-numeric-oracle.json
canonical-public-e2e-oracle.json
canonical-profile-manifest.json
canonical-fixture-metadata.json
canonical-producer.py
canonical-observer.py
canonical-runner.sh
```

`uv.lock` 已由 capture 复制到 `inputs/uv.lock`，不在 canonical artifact 重复保存。三份 checkpoint 总计约 128 MiB，本批在 producer 运行前后稳定重算角色、相对路径、size/hash，但不复制进每个 receipt；因此 archived-integrity 只证明封存 bytes与记录自洽，不是独立 checkpoint 恢复证明。内容寻址 checkpoint retention 属于 W1b-5/恢复工作包。

本批禁止修改 `tests/golden/Dockerfile.canonical`、三份 oracle、`t2l/` production 语义、依赖和 checkpoint。若必须修改，停止 W1b-4，走既有 candidate -> 三次一致 -> 人工 diff -> patch -> full verify 流程，不夹带重基线。

### 17.2 三段信任边界

| 组件 | 单一责任 | 不得宣称 |
|---|---|---|
| host producer | stable-read 输入；解析 Dockerfile `FROM`；inspect base；build `--iidfile`；inspect labels；按 build image ID create/run；校验 observation；原子发布 sidecar和输入副本 | 不接受外部 exit、统计、passed或qualification |
| container observer | 在真实容器内观测 scope、network/rootfs/tmpfs、CPU/thread、installed distribution；执行三份 pytest并输出原始 observation/JUnit | 不决定 capture qualification，不信任 tag |
| capture consumer | 重算 JUnit/gate/policy/run ID、正式输入副本、oracle链、Dockerfile/base、runtime schema和跨件绑定；派生 reason/qualification | 不调用 producer内部函数，不追认 inventory canonical资格 |

Docker daemon、本机内核与 capture/consumer 仍是本地信任根；W1b-4 不是签名 attestation。

### 17.3 `canonical-runtime.json` schema v1

顶层键精确为：

```json
{
  "schema": "ai-auto-lrc/canonical-runtime",
  "schema_version": 1,
  "run_id": "<capture-run-id>",
  "layer": "canonical",
  "scope": {},
  "image": {},
  "inputs": {},
  "runtime": {},
  "installation": {},
  "execution": {},
  "provenance": {}
}
```

所有嵌套对象也使用 exact-key；未知的 `qualification`、`qualified-canonical`、`qualified-release`、原始 argv、宿主绝对路径、环境全量或credential字段直接拒绝。所有 hash 为小写 64hex；所有路径是规范相对路径；角色数组排序、唯一且集合精确。

| 对象 | 必填内容 | consumer 规则 |
|---|---|---|
| `scope` | `os=linux`、`arch=x86_64`、`platform=linux-x86_64`、`python_implementation=CPython`、完整 3.10.x、`device=cpu` | 与 observer、oracle environment和image platform一致；Python 3.11/macOS/CUDA不接受 |
| `image.base` | Dockerfile中的完整 `repo_digest` 与 inspect得到的 `image_id` | tag-only/短 digest/inspect不匹配失败 |
| `image.build` | iidfile与inspect一致的 `image_id`；可选 `display_tag`；run/source/input labels | build image可无RepoDigest；create/run必须按ID，labels绑定本次run和输入 |
| `inputs.dockerfile` | 正式 `canonical-Dockerfile` record | 从私有副本重算hash并解析唯一 `FROM repo@sha256:<64hex>` |
| `inputs.oracles` | feature/numeric/public-e2e三角色、正式文件名、size/hash、oracle_id/status/scope | 从三份私有副本重算；角色不可缺失/重复/互换 |
| `inputs.profile_manifest` / `fixture_metadata` | 正式副本record | hash必须与oracle provenance引用一致 |
| `inputs.checkpoints` | Baseline/MTL/BDR的相对路径、size/hash | capture时从当前输入稳定重算，并与profile/oracle route引用一致 |
| `inputs.uv_lock_sha256` / aggregates | capture input lock hash、oracle/input aggregate | consumer用正式副本与receipt input重算 |
| `runtime.network` | `policy=denied`、`probe=connect_ex`、`blocked=true`、非零result | observer实际执行；同时宿主inspect要求NetworkMode=none |
| `runtime.root_filesystem` | `policy=read-only`、create probe、`blocked=true`、`errno=30` | 同时宿主inspect要求ReadonlyRootfs=true |
| `runtime.tmpfs` | `/tmp`、`writable=true`、固定options | 不把tmpfs可写误判成rootfs可写 |
| `runtime`其余 | CUDA unavailable、torch CUDA null、intraop=1、OMP/MKL/PYTHONHASHSEED固定 | 与canonical环境精确一致 |
| `installation` | distribution name/version、console entry point、site-packages relative `t2l/__init__.py` record | 隔离子进程移除workspace/PYTHONPATH影响；workspace origin直接拒绝 |
| `execution` | 固定command_id、三selectors、pytest exit=0、JUnit hash与统计 | consumer从XML重算；0 skip/fail/error，classname仅`tests.golden.*` |
| `provenance` | functional-not-release scope、producer/observer/runner/policy/source/input hashes | producer/observer/runner hash分别从三个正式源码副本重算；不得出现clean/signed/release/attested声明 |

主 pytest harness来自build image中的 `/workspace` source snapshot；installed probe来自同一image的site-packages。sidecar必须同时如实记录两者，不能将后者外推成整个pytest的import来源，也不能把workspace harness冒充installed验证。

### 17.4 无环数据流

```text
capture before source aggregate + run ID
  -> run_test_gate.sh canonical
     -> host producer stable-read Dockerfile/oracles/profile/fixture/checkpoints/lock
     -> docker build --iidfile --label run/source/input
     -> inspect base digest + build image ID/labels
     -> docker create by image ID --platform linux/amd64 --network none --read-only --tmpfs /tmp
     -> container observer probes + installed isolated import + pytest -> canonical.xml
     -> inspect container Image/NetworkMode/ReadonlyRootfs
     -> producer validates observation, stable-rereads inputs, atomically publishes snapshots + runtime
     -> verify_quality_gates.py -> canonical-gate.json
  -> capture consumer recomputes all formal bytes and cross-bindings
  -> source after aggregate -> receipt -> SEALED
```

sidecar不包含自身hash或后生成gate的hash；receipt同时记录sidecar、gate和所有输入副本hash，consumer再以共同run/JUnit/policy/source/input identity交叉验证，避免hash环。

### 17.5 实施DAG与文件边界

| 子批次 | 前置 | 允许修改 | 完成条件 |
|---|---|---|---|
| W1b-4a schema/closure | W1b-3 | `capture_test_gate.py`合同fixture、W1b文档 | 完整fake closure先红；canonical仍不能假绿 |
| W1b-4b observer | 4a | 新container observer及contract tests | scope/probe/import/JUnit observation无绝对宿主路径 |
| W1b-4c producer | 4b | 新host producer及其tests | iidfile/inspect/run-by-ID、TOCTOU和atomic失败全部关闭 |
| W1b-4d runner/consumer | 4c | canonical shell、`run_test_gate.sh`、capture consumer/tests | 完整fake closure移除固定reason；package/portable不变 |
| W1b-4e real capture | 4d | 仓库外sealed evidence | 13 tests零skip、两verify mode符合边界、source前后相等 |
| W1b-4f 文档收口 | 4e | 本节、主计划、Teams/交接 | 写完文档后再做最终current-source capture；hash不回写 |

回滚只撤回上述明确增量，不修改或清理用户现有dirty worktree。Docker高成本gate与package wheelhouse、canonical candidate和其他`.venv`操作串行。

### 17.6 快速反证矩阵

| ID | 风险/注入 | 必须断言 |
|---|---|---|
| CAN-T01 | 顶层/嵌套缺键、未知键、bool-as-int、非法hash/路径、qualification字段 | strict schema fail closed |
| CAN-T02 | 完整fake closure | 移除`LAYER_CLOSURE_UNIMPLEMENTED`，最高implemented-unqualified，spec_ids空 |
| CAN-T03 | runtime/gate/receipt不同run ID | 禁止拼接历史结果 |
| CAN-T04 | gate的JUnit/policy/run/count/passed篡改 | 从JUnit重算并拒绝 |
| CAN-T05 | markers缺失/错层、outside_layer或failures非空 | 精确要求`["golden"]`、`[]`、`[]` |
| CAN-T06 | JUnit空、malformed、skip、failure/error、package classname | 对应稳定reason；required零skip |
| CAN-T07 | 逐个删除三oracle/Dockerfile/profile/fixture副本 | REQUIRED_ARTIFACT_MISSING，不回读checkout代替 |
| CAN-T08 | 修改私有副本但保留旧sidecar hash | consumer与archived verify重算拒绝 |
| CAN-T09 | oracle_id/status/scope/role互换 | 三角色身份精确 |
| CAN-T10 | numeric中的feature oracle hash篡改 | 必须绑定feature私有副本hash |
| CAN-T11 | 三oracle base/Python/machine/profile不一致 | 不接受跨环境拼装 |
| CAN-T12 | Dockerfile变化、FROM tag-only/短digest、sidecar base不同 | 副本hash与immutable FROM同时匹配 |
| CAN-T13 | build只有tag、短ID或base digest冒充build ID | 必须有实际content-addressed ID |
| CAN-T14 | build后tag重绑 | create/run仍使用iidfile ID |
| CAN-T15 | Darwin/arm64/PyPy/3.11/CUDA/thread/env错 | canonical scope精确 |
| CAN-T16 | 仅argv、blocked=false、result=0或缺network probe | 必须有实际拒绝观察 |
| CAN-T17 | 仅`--read-only`、root写成功或缺probe | 必须EROFS且宿主inspect一致 |
| CAN-T18 | import origin为workspace/checkout、distribution/version/entrypoint错 | installed probe必须site-packages |
| CAN-T19 | lock/profile/checkpoint/fixture size/hash篡改 | provenance逐项重算/交叉验证 |
| CAN-T20 | provenance声称clean/release/signed/attested | 直接拒绝，不静默降级 |
| CAN-T21 | candidate模式或运行中写oracle | capture只接受verify且不发布候选 |
| CAN-T22 | 旧runtime、package sidecar、旧JUnit/image observation | exclusive root/layer/run/classname共同拒绝 |
| CAN-T23 | build/run期间source变化 | gate 0仍capture error/diagnostic |
| CAN-T24 | hash后替换/原地改oracle/Dockerfile/checkpoint | stable reread/identity拒绝，不正式发布 |
| CAN-T25 | 任一replace/fsync阶段失败 | 无半套正式closure；残留不能晋级 |
| CAN-T26 | build/pytest/gate exit 1/2/5/70 | receipt保留原gate rc，不被capture 70覆盖 |
| CAN-T27 | 封存后同时篡改sidecar与receipt record | archived verifier从formal copies重算拒绝 |
| CAN-T28 | 完整closure伪造unimplemented reason | verify拒绝reason/qualification不一致 |
| CAN-T29 | HOME/token/socket/宿主临时绝对路径进入sidecar | 拒绝或仅原始本地日志保留，不晋级 |
| CAN-T30 | sidecar自报已有canonical spec IDs | schema v1仍保持claim.spec_ids空 |

建议落点：producer/observer测试放 `tests/contract/test_canonical_runtime_gate.py`；consumer和receipt负例继续放 `tests/contract/test_evidence_capture.py`。参数化case ID必须指出具体字段，避免一个大case掩盖失败来源。

### 17.7 真实Docker矩阵与Go定义

真实验收至少覆盖：

1. `capture_test_gate.py run --layer canonical`：13 tests、0 skip/fail/error，四类exit均0，完整十二件closure。
2. build后重绑display tag仍按原image ID运行；container inspect的`.Image`一致。
3. 容器内network非零拒绝、rootfs `EROFS`、`/tmp`可写、Linux x86_64/CPython 3.10/CPU单线程。
4. 隔离installed probe得到site-packages相对路径；harness workspace来源另行明示。
5. 成功封存后`current-source` valid/implemented-unqualified；`archived-integrity` valid但effective historical diagnostic；改变checkout后前者失败而后者不升级。

W1b-4只有在4a–4f、CAN-T01–T30中已实施风险、真实Docker验收、宿主全量/静态/构建和文档同步全部通过时为Go。任何tag-only/run-by-tag、自报probe/资格、oracle无私有bytes、workspace冒充installed、非零skip、跨run、为变绿更新oracle或Dockerfile，都维持No-go。

即使W1b-4达到Go，W1b-5 retention/secret export、macOS/双平台package、恢复、SBOM、attestation、签名、rollback与Release仍未关闭。

## 18. W1b-4 实际落地与恢复状态

本节是 2026-09-06 的实施回写，覆盖第 17 节 W1b-4a–4f。第 17 节继续作为字段、失败和测试合同；本节只记录已经发生的实现与证据。W1b-4 现为 **Go（canonical functional、implemented-unqualified）**，不代表 checkpoint 可独立恢复、W1b 整体完成或 Release 可放行。

### 18.1 已实现的数据路径

- 新增 `scripts/run_canonical_gate.py`。producer 对 Dockerfile、三份 oracle、profile、fixture、三个 checkpoint、`uv.lock`、quality policy 和 producer/observer/runner 源码执行 stable-read；解析唯一 immutable `FROM`，inspect base repo digest/image ID，使用 `docker build --iidfile` 和 run/source/input labels 取得实际 build image ID，并只按该 ID create/run/inspect。
- 新增 `tests/golden/canonical_capture_observer.py`。observer 在容器内实际执行 `connect_ex` 断网探针、`/workspace` 的 `EROFS` 根文件系统探针、`/tmp` 可写探针、隔离 `python -I` site-packages import、distribution/version/entry point/package hash 校验，以及三份 canonical pytest/JUnit。
- `scripts/run_canonical_legacy_v1_golden.sh` 与 `scripts/run_test_gate.sh` 只在 capture-bound `verify` 中调用 producer；缺 evidence run/source identity 时 fail closed，producer 非零时原样返回且不生成 gate。三个 candidate 模式和非 capture verify 保持既有路径。
- `scripts/capture_test_gate.py` 独立重算十二件 closure、JUnit/gate/run/policy、Dockerfile/base、build image/labels、oracle/profile/fixture/checkpoint/lock aggregates、runtime probes、installed origin、execution统计和三份源码快照 provenance。缺件仅使用 `REQUIRED_ARTIFACT_MISSING`；完整但语义无效仅使用 `RUN_ARTIFACT_BINDING_INVALID`；canonical receipt 中出现旧 `LAYER_CLOSURE_UNIMPLEMENTED` 会被 verifier 拒绝。
- 多文件 sidecar 发布以 `canonical-runtime.json` 为最后正式文件；任何 observation、JUnit、stable-reread、replace 或 fsync 失败都不得留下可晋级的半套 closure。

### 18.2 可执行测试与验证结果

- 新增/扩展 `tests/contract/test_canonical_runtime_gate.py`、`tests/contract/test_canonical_runner_wiring.py` 和 `tests/contract/test_evidence_capture.py`，覆盖第 17.6 节 CAN-T01–T30 的 schema、image identity、TOCTOU、atomic publish、runner wiring、artifact mutation、cross-run 和 forged reason 反证。
- W1b-4 联合快速层：`215 passed, 5 skipped`；五个 skip 仅来自默认 package run 未注入 wheelhouse。
- 2026-09-06 文档回写前宿主全量：`481 passed, 18 skipped, 22 warnings in 67.90s`。18 个 skip 精确为 13 个只允许经 canonical runner 执行的 golden 用例和 5 个未注入 wheelhouse 的 cold package 用例，不是 release 零 skip。
- Ruff、compileall、两个 shell runner 的 `bash -n`、`uv lock --check`、`uv build --no-python-downloads` 与 `git diff --check` 均通过。

### 18.3 真实 Docker capture

文档回写前的真实 positive run 位于 `/private/tmp/ai-auto-lrc-w1b4-positive.xU4sxR/20260906T082001031272Z-16044c5cc13e4202964b5c0f16c321a3`；该临时路径只作执行记录，不是长期 retention 承诺：

- canonical：`13 passed, 7 warnings, 0 skipped in 143.43s`，raw/normalized/capture exit 均为 `0`；十二件 artifact closure 完整。
- source before/after aggregate 均为 `aefe0e3d0a029e1964c5eb3807bf3bb1cdf376d3bd5f32e2b801d785b91c9d24`，`stable_during_run=true`。
- base 为 `python@sha256:8c97ebedc32fd60935cdf5992e935753e2a0f98231830028050e1e04bd3c13c2`，inspect image ID 为 `sha256:db825c749364f7f06c8fb165b360d9de94ba5c14727e2e446c1b4202a30224e7`；build iid 为 `sha256:a434bed0c04e82424c9956c4aea835d6087e480c3e43a73cfa5be7160aebfe63`。
- network probe result 为 `101`，rootfs probe errno 为 `30`，installed package 为 site-packages 内 `t2l/__init__.py`；pytest harness 明示为 `workspace-source-snapshot`。
- `archived-integrity` 为 valid、effective `diagnostic-historical-integrity`；当时的 `current-source` 为 valid、effective `implemented-unqualified`。本节写入后该 run 只再是历史完整性证据；最终 current-source capture 在全部文档落盘后生成，路径只在交付信息中报告，不把 receipt hash 回写仓库以免形成 source identity 循环。

### 18.4 当前 Gate

W1b-4 已关闭“canonical 固定 unimplemented reason”的缺口，但 qualification 仍由 schema v1 限制为 `implemented-unqualified`，`claim.spec_ids=[]`。W1b-5、macOS cold install、`PKG-012/017` 双平台、完整资源预算、Demucs 真实离线权重/许可、`AlignmentRuntime.close()`、独立恢复、SBOM、attestation、签名、rollback 和 Release 均继续 **No-go**。

## 19. W1b-5 retention、secret scan 与受控导出可执行方案

本节是 W1b-5 的唯一字段级设计入口；四角色原始意见和分歧见 [`team-session-2026-09-06-2.md`](./team-sessions/team-session-2026-09-06-2.md)。目标是让已经 `SEALED` 的本地 receipt 可被盘点、扫描、按策略准备导出、归档和恢复验证，同时保持默认无上传、无删除、无资格晋级。owner、期限、密钥、RPO/RTO 和销毁审批没有人类决议前，只允许实现 5a/5b 和 disabled-by-default 的本地 5c；不得启用 5d/5e。

> W1b-5a/5b 的首个最小实现已进一步收窄并固化在 [`W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md`](./W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md)：初始 manager 只允许 `inspect` 与 `verify-inspection`，在 D-REL 决议前不实现本节远期示例中的 `prepare-export`/`verify-export`。该执行计划同时给出 exact-key schema、公共 API、事务提交点、错误码和 QA RED 顺序；后续不得从聊天记录补全。

### 19.1 范围与非目标

W1b-5 管理 evidence 生命周期，不修改 capture 事实。它不得改写 run directory、`receipt.json` 或 `SEALED`，不得把扫描通过解释成“没有 secret”，不得把归档解释成可重建源码/checkpoint，也不得把本地 export bundle 自动上传到网络、issue、CI artifact、对象存储或 Git。

明确分层：

1. **事实层**：现有只读 `<retention-root>/<run-id>`，由 `verify --mode archived-integrity` 重新验证。
2. **控制层**：`<retention-root>/.control/<run-id>/` 保存独立 lifecycle manifest、扫描报告和 hash-chained 事件；它只能引用 run hash，不进入或修改原 receipt。
3. **导出层**：用户显式指定、仓库外且非 symlink 的 `<export-root>/.incomplete-<export-id>`；从 allowlist 重建 bundle，成功后原子 rename。工具不包含网络客户端。
4. **归档层**：是否加密、使用何种介质/KMS、key ID/rotation/escrow 和恢复环境由 `D-REL` 决定；未决时不得产生 `ARCHIVED` 事件。
5. **销毁层**：永不由 capture 或定时器自动触发。只有已批准 policy、到期事实、双人授权、dry-run 清单和隔离恢复/销毁演练全部成立后，才允许另行实现。

### 19.2 组件与 CLI 边界

建议新增独立 `scripts/manage_evidence_retention.py`，避免把破坏性生命周期职责混入 `capture_test_gate.py`：

```text
python scripts/manage_evidence_retention.py inspect \
  --receipt ABS/receipt.json \
  --policy ABS/retention-policy.json

python scripts/manage_evidence_retention.py prepare-export \
  --receipt ABS/receipt.json \
  --policy ABS/retention-policy.json \
  --approval ABS/export-approval.json \
  --export-root ABS

python scripts/manage_evidence_retention.py verify-export \
  --manifest ABS/export-manifest.json
```

- `inspect` 只读验证 archived integrity，枚举 closure，流式扫描全部普通文件，并原子写入控制层；不得改变 run mode 或内容。
- `prepare-export` 默认拒绝。只有 policy 与 approval 同时允许的 classification 可复制；源 patch、untracked bytes、raw stdout/stderr、checkpoint、credential-like 文件和未知 artifact 默认 deny。它只创建本地 bundle，不发送数据。
- `verify-export` 不读取 checkout；从 bundle 私有字节重算 path/size/hash、policy/approval/scanner identity 和 source receipt binding。
- 不提供 `upload`、`sync`、`prune` 或 `destroy` 子命令。后两者必须在 `D-REL` 和独立 destructive-action 评审后另立工作包。

### 19.3 policy、approval 与 manifest schema

所有 schema 均 exact-key、版本化、UTF-8 JSON；hash 为小写 64hex，时间为 UTC RFC 3339，路径为 canonical relative path。未知键、重复角色、绝对路径、`..`、symlink/hardlink/FIFO/socket/device、bool-as-int、超限文件或 parser failure 均 fail closed。

`retention-policy.json` 最少包含：

| 对象 | 必填字段 | 规则 |
|---|---|---|
| identity | `schema`、`schema_version`、`policy_id`、`effective_at` | policy bytes 自身进入 scan/export manifest hash闭包 |
| owners | `evidence_owner`、`security_owner`、`release_owner` | 不能为空或占位；无人类锁定时 policy 不可 operational |
| classes | 每类 `retention_days`、`exportable`、`encryption_required` | `source-raw`、`log-raw`、`checkpoint` 默认不可导出 |
| scanner | `rule_set_id`、`rule_set_sha256`、`max_file_bytes`、`on_error=block` | scanner 不能静默跳过文件或截断后报绿 |
| export | `default=deny`、允许分类、最大总量、approval TTL | allowlist 精确匹配；没有 glob 扩张 |
| archive | `enabled`、`provider`、`key_id`、`key_version` | 未决必须 `enabled=false`；不得把明文包记为 archived |
| recovery | `rpo_hours`、`rto_hours`、`checkpoint_strategy` | 未填时不能声称独立恢复 |
| destruction | `enabled`、`min_approvals`、`tombstone_days` | W1b-5 初始必须 `enabled=false` |

`export-approval.json` 绑定 `approval_id`、`run_id`、receipt SHA-256、policy SHA-256、允许分类、目的类别、approver identities、issued/expires。普通 JSON approval 只提供审计关联，不证明签名身份；签名审批属于后续 release control。

`secret-scan.json` 记录 scanner/rules/policy hash、receipt binding、逐文件 size/hash/classification、命中 rule ID/byte range 的脱敏定位、errors、`export_allowed`。不得写入命中的原始 secret。扫描至少覆盖已定义 HOME/user path、Bearer/Basic authorization、常见 token/key assignment、PEM/private-key header、云厂商 access-key 形态和项目 sentinel；二进制按 bytes 流式匹配。该结果只能证明“已定义规则未命中”。

`export-manifest.json` 精确记录 export ID、run/layer、source receipt/SEALED hash、policy/approval/scan hash、每个导出文件 path/size/hash/classification、aggregate、created_at 和 `transport=local-only`。manifest 不包含自身 hash；完成 marker 绑定 manifest hash，避免 hash 环。

### 19.4 生命周期与原子性

capture 状态和 retention 状态分离。合法 retention 事件为：

```text
LOCAL_SEALED -> SCANNED_PASS | SCANNED_BLOCKED
SCANNED_PASS -> EXPORT_PREPARED
LOCAL_SEALED -> ARCHIVED          # 仅 D-REL 批准并完成加密与 restore drill 后
ARCHIVED -> EXPIRED               # 只记录到期，不删除
EXPIRED -> DESTROYED              # 本阶段不实现；需双授权和独立命令
```

事件 append-only，包含 `sequence`、`previous_event_sha256`、event type、run/receipt/policy hash、actor、timestamp 和 details；状态不得回退、覆盖或跳序。控制层与 export 都使用 exclusive staging、stable-read、`fsync`、completion marker 和同文件系统原子 rename；目标存在时拒绝覆盖。失败只清理本次未发布 staging 或保留明确 `.incomplete-*` 供人工检查，绝不删除原 run。

### 19.5 实施 DAG 与决策闸门

| 子批次 | 前置 | 允许修改 | 完成条件 |
|---|---|---|---|
| W1b-5a schema/threat model | W1b-4 | 新 schema fixture、合同测试、本节 | exact-key schema、分类、状态机和 reason code 先红；无文件复制/删除 |
| W1b-5b inspect/scan | 5a | 新 manager、scanner、contract tests | archived verify先行；binary-safe全闭包扫描；报告不含secret；源文件竞态失败 |
| W1b-5c local export | 5b + operational policy/approval | manager export/verify、tests | default deny、allowlist、原子 bundle、离线 local-only、独立复验 |
| W1b-5d encrypted archive | 5c + D-REL 锁定 provider/key/RPO/RTO | 独立 archive adapter/tests/runbook | 密文、key separation、rotation和隔离 restore drill通过后才记ARCHIVED |
| W1b-5e expiry/destruction | 5d + 双授权/法务策略 | 独立 destructive CLI/tests | dry-run、精确目标、quarantine、不可回退event和销毁证明；初始不实现 |
| W1b-5f 文档/恢复演练 | 5b–5e按批准范围 | 主计划、handoff、runbook | 已实现与待决分开；不得用未执行批次关闭 No-go |

必须由人类先锁定 `D-REL`：三类 owner、每类保留期限、归档介质、加密 provider/key custody/rotation、允许导出的分类与目的、审批人数/TTL、RPO/RTO、checkpoint 内容寻址策略、销毁与 tombstone期限。在这些字段锁定前，5d/5e 明确 blocked-by-decision，不以默认值代替。

### 19.6 快速反证矩阵

| ID | 风险/注入 | 必须断言 |
|---|---|---|
| RET-T01 | policy/approval/scan/manifest 缺键、未知键、非法类型 | strict schema fail closed |
| RET-T02 | receipt无有效SEALED、archived verify失败 | inspect/export不启动 |
| RET-T03 | run ID、receipt hash、policy hash、approval绑定不一致 | 禁止跨run拼接 |
| RET-T04 | symlink、hardlink、FIFO、socket、device、路径穿越 | 不扫描/复制并稳定失败 |
| RET-T05 | closure多件、少件或文件在扫描中变化 | exact closure + stable-read拒绝 |
| RET-T06 | UTF-8日志中的token/HOME/private key | SCANNED_BLOCKED，报告不回显secret |
| RET-T07 | 非UTF-8二进制中的secret sentinel | byte scanner命中并阻止导出 |
| RET-T08 | scanner rule/parser error、文件超限或被截断 | `on_error=block`，不得报pass |
| RET-T09 | 只扫描receipt而漏logs/source/artifacts | 全部普通文件必须有scan record |
| RET-T10 | source-raw/log-raw/checkpoint/未知分类请求导出 | default deny；approval不能越过policy |
| RET-T11 | approval缺失、过期、run/purpose/class不匹配 | prepare-export拒绝 |
| RET-T12 | 无owner或placeholder policy | 只可schema验证，不可operational |
| RET-T13 | export root在repo/retention内或路径链有symlink | preflight拒绝且不建staging |
| RET-T14 | export ID碰撞或正式目标已存在 | exclusive create；不覆盖 |
| RET-T15 | copy/hash/fsync/rename故障注入 | 无有效半包；原run不变 |
| RET-T16 | manifest后篡改导出文件或completion marker | verify-export重算拒绝 |
| RET-T17 | 导出集合与allowlist不等、aggregate顺序变化 | 精确集合与规范排序重算 |
| RET-T18 | 文件权限过宽 | staging/root为0700、文件0600，否则失败 |
| RET-T19 | 代码路径尝试网络、upload或外部传输 | manager无传输子命令；local-only合同 |
| RET-T20 | archive要求加密但provider/key未锁定 | 不生成ARCHIVED事件 |
| RET-T21 | 明文包、错key/version、密文损坏 | archive/restore验证失败 |
| RET-T22 | lifecycle sequence重复、跳号、hash链断裂或状态回退 | ledger verifier拒绝 |
| RET-T23 | 达到retention_days | 只记EXPIRED，不自动删除 |
| RET-T24 | destroy无双授权、无dry-run或目标不精确 | 拒绝；本阶段无destroy命令 |
| RET-T25 | 销毁目标替换/父目录symlink/越界 | descriptor/identity复验，禁止递归宽目标 |
| RET-T26 | checkpoint只有hash但内容存储缺失 | restore drill失败，不得声称独立恢复 |
| RET-T27 | 恢复只验证解密未验证closure | 必须再跑archived verifier与checkpoint hash |
| RET-T28 | scan/export自报qualification/spec IDs | schema拒绝；claim不晋级 |
| RET-T29 | 旧scan或旧approval用于新receipt | freshness和identity绑定拒绝 |
| RET-T30 | W1b-5局部绿测被描述为release | Gate表仍保持Release No-go |

建议新测试文件为 `tests/contract/test_evidence_retention.py`；参数化 case ID 使用上表稳定 ID。涉及真实 archive/key/restore 的 T20–T27 在 5d/5e 未获批准前保持 planned/No-go，不能 skip 后宣称 W1b-5 完成。

### 19.7 Go/No-go 与恢复入口

W1b-5 的“实现 Go”必须按子批次报告，不能整体涂绿：

- 5a/5b Go：所有 receipt 在本地可只读盘点，扫描闭包和错误可重算，未产生网络、归档或删除能力。
- 5c Go：仅表示批准的本地 export bundle 可原子生成和独立验证；不表示已传输或可公开。
- 5d Go：必须有 D-REL、密文介质、独立 key custody 和隔离 restore drill。
- 5e Go：必须有双授权、到期/法律策略、dry-run、精确目标和销毁证明；未实现时不得出现 destroy API。

即使 5a–5f 全部完成，仍只关闭 W1b evidence 生命周期自身；它不替代 macOS/双平台、完整 checkpoint/source恢复、SBOM、attestation、签名、rollback 或 release 审批。后续接手先读本节和 Teams `-2` 文件，再检查代码与测试是否真实存在；不得把本设计文字当作实现证据。

## 20. S15 current-source 语义勘误与当前执行入口

第 6.2 节已经按 S15 更新。本文中第 13、16–18 节记录的 “current-source 当时为 valid/implemented-unqualified” 仅是相应历史 run 在旧 verifier 下的现场事实，不再是当前合同。当前合同为：

- current-source 是两次完整顺序 observation 的诊断结果，不是事务快照；
- CLI 只可返回 `diagnostic-current-source-observation`、`transactional=false`、`aba_excluded=false`；
- 两次 observation 不一致返回 `CURRENT_SOURCE_OBSERVATION_UNSTABLE`；
- retention schema-v1 不得发布 current-source inspection，必须在任何 control I/O 前返回 `CURRENT_SOURCE_DIAGNOSTIC_ONLY`；
- archived-integrity 仍只证明历史封存字节与绑定关系；
- 程序化 verifier 返回的 sealed receipt document 不是本次验证的 effective qualification。

第 19 节是上位生命周期设计，不代表 5c/5d/5e 已获授权或已实现。当前可执行实现、S16–S18 测试矩阵和禁止边界以 [`W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md`](./W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md) 第 19 节为准；跨工作包 DAG 以 [`AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md`](./AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md) 第 29 节为准。Release 继续 No-go。

## 21. S16 完成后的生命周期边界补充

retention S16 已完成当前 macOS 宿主上的独立进程竞争与 process SIGKILL 分类：一个稳定 control namespace 中最多一个有效 inspection/event；staging、orphan、committed 的重启分类稳定且只读；重试不自动删除或覆盖。精确实现、RED 和验证数字见 [`W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md`](./W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md) 第 20 节。

这不改变本文件的上位生命周期授权：S16 不是真实 power-loss durability、archive/restore 或独立恢复证明，也不授权 5c export、5d archive、5e destruction。当前执行入口已推进为 S17 → S18 → evidence refresh → W1b-5b 复审；Release 继续 No-go。Teams 记录见 [`team-sessions/team-session-2026-09-06-4.md`](./team-sessions/team-session-2026-09-06-4.md)。

## 22. S17 `source` 声明形状冻结

capture receipt schema v1 的 `source` 顶层现在只允许：`before`、`after`、`before_aggregate_sha256`、`after_aggregate_sha256`、`stable_during_run`、`observation_limit`。额外的 `transactional`、`aba_excluded`、`qualification` 或其他未知声明必须由 archived/current-source verifier 拒绝，不能借 sealed receipt 注入超出 S15 诊断模型的保证。

兼容错误顺序被冻结：非对象返回 `source must be an object`；`observation_limit` 缺失或值漂移返回 `source.observation_limit is invalid`；额外/其他形状差异返回 `source has an invalid shape`。相关 5 个旧+新节点以及 S17 完整数据见 [`W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md`](./W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md) 第 21 节。

这仍不表示 source 是 transaction snapshot，也不排除单次观察内部完成并恢复的 ABA。S17 Linux device required 未执行；下一入口为 S18 qualification。Release、5c/5d/5e 与恢复授权均保持 No-go/未授权。

## 23. S18 独立安全 coverage 与跨 runner 证据边界

本节取代第 22 节中“Linux device 未执行”的时态。Linux/amd64 Python 3.11.9 受控 runner 已通过 S16+block/char device 和 `/proc/self/fd`+source 两批功能测试；但当前缺最终 JUnit、环境与 source hash bundle，因此只能关闭 Linux functional 子门禁，不能晋级 receipt qualification、package 或 Release。

S18 将 security coverage Gate 保持在 capture receipt schema v1 之外：`capture_test_gate.py` 是被测生产者，不能读取 policy 后给自己签发资格。若未来要把 security coverage 纳入正式 receipt closure，必须另行冻结 artifact 名称、schema、hash 绑定和 layer semantics，不得无版本地把新 sidecar 塞进现有 closure。

当前 capture line/branch 为 `79.1966%/67.6768%`，retention 为 `86.3192%/76.25%`；S18 对两个脚本分别要求 line/branch 均 `>=80%`，并要求关键能力到 required nodeids 的 manifest。package 因 stale wheelhouse manifest 继续 No-go；canonical 13/13 通过只能代表其独立 functional lane。完整架构、测试矩阵与停止条件见 [`W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md`](./W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md)，当前事实见 W1b-5 执行计划第 22 节。

该变化不授权 export、archive、restore、expiry、destruction、自动恢复、CI、上传、签名或发布。5c/5d/5e 与 Release 继续 No-go。

### 23.1 S18 当前执行勘误

本节上方百分比和 stale package 状态保留为首轮 RED。当前 capture raw coverage 为 line 90.7280%、branch 84.4660%，retention 为 line 93.9320%、branch 89.1089%；macOS package 为 37 passed、0 skip/fail。Security verifier 合同已通过 41 个用例，但两个 nested walker 的真实 enforcement body 尚未从外层函数摘要中独立出来，最终同源 Gate 仍应 No-go。

S18 的唯一详细方案是 [`W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md`](./W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md) 第 17 节。本文件继续只定义 capture 生命周期边界：security coverage sidecar 不得无版本并入现有 receipt closure，capture producer 不得为自身签发资格；所有新 evidence 仍须由独立 verifier 重算。
