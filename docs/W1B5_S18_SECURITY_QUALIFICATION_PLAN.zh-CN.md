# W1b-5 S18 安全资格与证据收口执行方案

> 状态：**In progress / 当前字节的 macOS/Linux Security Gate 已通过；COV-015、P1、package/canonical/host/sealed evidence 尚未闭合，S18/W1b-5b/Release No-go**  
> 日期：2026-09-07  
> 适用代码：`scripts/capture_test_gate.py`、`scripts/manage_evidence_retention.py` 及其 qualification runner  
> 目的：把分散在交接文档、W1b-5 计划和 Teams 记录中的 S18 要求冻结成一份可执行、可验证、可恢复的本地规格。

## 1. 结论与当前入口

S18 不是“把总覆盖率数字刷绿”，而是建立两个安全脚本各自独立的 coverage policy、关键安全能力 manifest、验证器和分层 runner 证据。任一脚本不得借另一个脚本、`t2l` 生产包、package 或 canonical 测试补分；macOS、Linux、package、canonical 证据不得互相替代。

当前事实如下：

| 范围 | 当前事实 | Gate |
|---|---|---|
| capture 独立 coverage | 历史 baseline 145 passed、combined 75.7545%、branch 67.6768%，RED；当前 fresh run 273 passed、0 skip/fail，combined 88.8621%、statement 90.7280%、branch 84.4660% | 数值 Gate 通过；manifest 当前 9 个原子 critical symbol 的函数摘要均为 line/branch 100%，仍须由统一 runner 重新绑定 hash/nodeid 后签署 |
| capture + retention tests 覆盖 capture | 175 tests 加 1 个 Linux-only skip；combined coverage 75.8551%，statement line 79.3400%，branch 67.6768% | RED；跨 suite 补分无效 |
| retention 独立 coverage | 历史 baseline 为 175 passed、1 Linux-only skip，branch 74.25%，RED；当前 fresh run 为 244 passed、1 个 macOS 上声明的 Linux-device skip，combined 92.7439%、statement 93.9320%、branch 89.1089% | 数值 Gate 通过；架构复审后的 12 个原子/窄边界 symbol 当前函数摘要均为 line/branch 100%，仍须更新 manifest 并由统一 runner 重新绑定 |
| Linux x86_64 Python 3.11 | S16 + block/char device 为 9 passed；`/proc/self/fd` + source contract 为 9 passed | 功能证据有效；仍需 JUnit、provenance 和 manifest 绑定 |
| macOS package | 已从当前输入完整重建 wheelhouse；补齐 `PKG-024` 后最终 37 passed、1 deselected、0 skip/fail，Gate `passed=true`；旧 34/1/1 失败保留为历史 RED | macOS 当前 lane Go；Linux package 仍未刷新，不能升级为 S18 Go |
| canonical | 当前源码重建的 `linux/amd64` image 中 13 passed、0 skipped、7 warnings | 当前功能 Gate 通过；仍须纳入最终同源证据集 |
| W1b-5b | S18 coverage、package 和最新 evidence 尚未闭合 | No-go |
| W1b-5c/5d/5e | export、archive/restore、expiry/destruction 未授权 | 未实现，不进入本方案 |
| Release | 不具备双平台 package、签名、attestation、SBOM、rollback 等证明 | No-go |

当前唯一执行顺序：

```text
冻结 S18 policy / manifest / receipt schema
  -> 先写 verifier 合同并保留 RED
  -> 补 capture 真实缺失分支测试
  -> 验证 retention 独立 coverage 与关键分支
  -> 刷新 Linux required runner 证据
  -> 复核新 macOS wheelhouse/package 与 PKG-024 证据
  -> 建立独立 Linux package 证据
  -> 用同一最终源码重跑 canonical
  -> 宿主全量、静态检查、证据刷新
  -> W1b-5b Go/No-go 复审
```

文档里的计划、旧 coverage JSON 和旧 sealed receipt 都不是当前代码的资格证明。只有最后一次源码冻结后生成并由独立验证器重算通过的同源证据集，才可进入 W1b-5b 复审。

## 2. 范围与非目标

### 2.1 本轮范围

1. 为 `capture_test_gate.py` 和 `manage_evidence_retention.py` 分别建立 coverage policy。
2. 用 manifest 把每项关键安全能力映射到生产 symbol、required test nodeid、required platform 和预期结果。
3. 实现只读、fail-closed 的 coverage/qualification verifier。
4. 为 capture 补齐真实未覆盖分支，不用 `pragma: no cover`、删分支或降低门槛换取绿色。
5. 在 macOS、Linux、package、canonical runner 上生成各自独立的 JUnit、coverage、环境和 artifact hash。
6. 保留首轮失败、fixture 错误、flaky、skip、retry 及修复后结果。
7. 最终刷新 PASS 与 BLOCKED sealed evidence，再复审 W1b-5b。

### 2.2 明确非目标

- 不实现或执行 W1b-5c export、5d archive/restore、5e expiry/destruction。
- 不创建 CI，不上传、签名、发布、commit 或 push。
- 不自动清理 staging、orphan、旧证据或当前 dirty worktree。
- 不把顺序 source observation 改写成事务快照，不声称排除完整 ABA。
- 不把 Docker Desktop 的 Linux x86_64 功能结果写成原生硬件性能证明。
- 不修改生产代码去兼容与项目 Python 合同不一致的临时 runner。

## 3. 架构原则

### 3.1 单脚本独立性

每份 coverage JSON 只能有一个受测源文件：

- capture：`scripts/capture_test_gate.py`
- retention：`scripts/manage_evidence_retention.py`

验证器必须拒绝以下输入：

- `source` 指向整个 `scripts`、整个仓库或 `t2l`；
- 同一 JSON 中用其他文件覆盖率抬高 totals；
- 两个 `.coverage` 数据文件 combine 后再声称单脚本通过；
- 缺少 `meta.branch_coverage=true`；
- coverage JSON 的文件集合、source SHA-256 或命令 provenance 与 policy 不一致。

### 3.2 数字门槛和语义门槛并存

两个脚本都必须同时满足：

| 门槛 | 最低要求 | 说明 |
|---|---:|---|
| coverage.py combined percent | 80% | 保留现有 `fail_under=80`，不得降低 |
| statement line percent | 80% | 由 `covered_lines / num_statements` 独立重算 |
| branch percent | 80% | 由 `covered_branches / num_branches` 独立重算；与 line 使用同一最低标准，不允许用 combined percent 替代 |
| critical target line | 100% | policy 中列出的关键 symbol |
| critical target branch | 100% | 有分支的关键 symbol；无分支必须显式记录 0/0 |
| required category | 100% present | manifest 中每个安全类别至少一个有效 test mapping |
| required nodeid | 100% collected and passed | 不允许 skip、xfail、deselected 或 allowed failure |

全局数字通过但关键类别或 required nodeid 缺失，仍为 No-go。关键 symbol 100% 不是要求整个脚本 100%，而是防止高风险分支被大量低风险行稀释。

### 3.3 原始证据优先

Gate JSON 只能是对原始数据的派生结论。必须先保存：

- coverage JSON；
- JUnit XML；
- stdout/stderr 原始日志或其明确保留策略；
- 命令 argv；
- 退出码；
- OS、arch、Python implementation/version；
- coverage、pytest 版本；
- source、policy、manifest、JUnit、coverage artifact SHA-256；
- Git HEAD、base ref 和 dirty tree observation。

验证器不得信任 JUnit suite 自报 totals、coverage 顶层显示百分比或 runner 自报 `passed=true`；必须从 testcase 和 coverage 原始计数重算。

## 4. 组件与文件设计

### 4.1 新增 policy

计划新增 `packaging/security-coverage-policy.toml`，职责仅为冻结规则，不保存某次运行结果。建议 schema：

```toml
schema_version = 1

[thresholds]
coverage_combined_percent = 80
statement_line_percent = 80
branch_percent = 80
critical_line_percent = 100
critical_branch_percent = 100
zero_required_skip = true

[scripts.capture]
module = "scripts.capture_test_gate"
path = "scripts/capture_test_gate.py"

[scripts.retention]
module = "scripts.manage_evidence_retention"
path = "scripts/manage_evidence_retention.py"
```

policy parser 必须 exact-key、拒绝重复 TOML key、未知脚本、非法百分比、重复 target 和仓库外路径。policy 变化必须使旧 Gate 因 hash 不匹配失效。

### 4.2 新增安全能力 manifest

计划新增 `packaging/security-coverage-manifest.json`。manifest 不直接写易漂移的源码行号作为唯一身份，而使用：

- 稳定 capability ID；
- 脚本相对路径；
- Python symbol；
- 要求覆盖的成功/失败语义；
- required test nodeids；
- required runner；
- 预期稳定错误码或状态；
- 是否要求该 symbol 100% line/branch。

源码行号和 coverage arc 可以作为某次运行的派生诊断，但不能代替 symbol 与 test mapping。这样重排源码不会静默丢失安全意图，也不会迫使维护者手工追逐每次行号变化。

### 4.3 新增验证器

计划新增 `scripts/verify_security_coverage.py`，只读输入并输出 canonical JSON。它必须：

1. 严格解析 policy、manifest、coverage JSON 和 JUnit。
2. 校验受测源文件集合恰好等于目标脚本。
3. 重算 combined、statement line、branch、critical function 百分比。
4. 从 JUnit testcase 重建 collected/passed/skipped/failure/error 集合。
5. 校验 required nodeid 全部存在、通过且属于声明 runner。
6. 校验每个 capability 的成功和 fail-closed 语义均有映射。
7. 绑定 source、policy、manifest、coverage、JUnit SHA-256 和 run ID。
8. 输出 exact-key `security-coverage-gate.json`；任何输入异常返回非零且不修改原始证据。

验证器不得执行测试、修改 coverage 数据、清理目录、访问网络或根据最终百分比自动改 policy。

### 4.4 新增 runner

计划新增 `scripts/run_security_coverage.sh`，只负责编排两个互相隔离的进程：

```text
capture process
  -> fresh COVERAGE_FILE
  -> capture contract JUnit
  -> capture-only coverage JSON
  -> capture gate JSON

retention process
  -> different fresh COVERAGE_FILE
  -> retention contract JUnit
  -> retention-only coverage JSON
  -> retention gate JSON
```

runner 必须使用显式 artifact root，不覆盖已有目录，不执行 `coverage combine`，并把每条真实命令和退出码写入 run manifest。一个脚本失败时仍保留另一个脚本及失败脚本已经生成的原始证据。

### 4.5 新增 verifier 合同

计划新增 `tests/contract/test_security_coverage_gate.py`，至少覆盖：

- policy/manifest exact schema；
- 单脚本 source 限定；
- totals、显示百分比、JUnit totals 伪造；
- line、branch、combined 三个阈值分别不足；
- critical target 缺失或不是 100%；
- required nodeid 缺失、skip、xfail、fail、error、跨 runner；
- source/policy/manifest/JUnit/coverage hash 漂移；
- 重复 capability、重复 nodeid、未知 category；
- verifier 只读和失败时不写原始 evidence；
- CLI 单行脱敏错误与稳定非零退出码。

## 5. 关键安全能力逐条细化

下表是 S18 manifest 的最低能力集合。测试文件和最终 nodeid 可以在实现时扩展，但不得删除类别或用纯 mock 代替要求的真实系统证据。

| ID | 能力 | 生产 symbol | 必须证明的成功路径 | 必须证明的失败路径 | Required runner |
|---|---|---|---|---|---|
| S18-CAP-01 | sealed run fd 读取 | `_DirFdReceiptIO._open_parent/read/file_closure` | pinned run fd 下读取精确 closure | symlink、hardlink、FIFO/socket、非普通文件、owner/mode/nlink/identity 漂移 fail closed | macOS + Linux |
| S18-CAP-02 | 外部稳定文件读取 | `_read_stable_regular`、`_verify_record` | hash/size/identity 一致 | before/open/after swap、超限、类型不安全拒绝 | macOS |
| S18-CAP-03 | current-source 诊断观察 | `_source_material`、`_source_material_at`、`_verify_source_summary` | 两次有界 observation 相等 | checkout drift、unknown source key、observation limit 漂移；不得晋级 transactional | macOS + Linux `/proc/self/fd` |
| S18-CAP-04 | capture 预检与隔离 | `_preflight`、`_seal_run` | repo 外 retention、exclusive staging 到 sealed | retention 位于 repo 内、symlink parent、目标已存在 | macOS |
| S18-CAP-05 | gate 子进程与信号 | `_run_gate_process`、`_normalize_returncode` | 精确 return code、日志保留 | SIGTERM 转发、无 return code、异常 finalizer 不掩盖原结果 | macOS |
| S18-CAP-06 | portable 绑定 | `_portable_binding_reasons` | coverage/JUnit/policy/base ref/run ID 同源 | hash、run ID、scope、测试统计漂移诊断 | macOS |
| S18-CAP-07 | package closure | `_validate_package_sidecar`、`_package_binding_reasons` | wheelhouse/build/install/CLI sidecar 完整 | tag、manifest、JUnit、policy、run ID 或 artifact 漂移 | package runner |
| S18-CAP-08 | canonical closure | `_validate_canonical_sidecar`、`_canonical_binding_reasons` | container、安装、oracle、JUnit 完整绑定 | formal input、scope、network/rootfs、artifact 语义漂移 | canonical runner |
| S18-CAP-09 | receipt finalize 与 verify | `_finalize_run`、`_verify_receipt_from_io`、`verify_receipt_at` | sealed marker、closure、reason codes 重算 | 缺件、篡改、父路径 swap、非普通 sealed node 拒绝 | macOS + Linux |
| S18-CAP-10 | retention config 信任锚 | `_stable_bytes`、`load_secret_rules`、`load_retention_assessment` | checked-in bytes 与外部 expected digest 一致 | 弱规则、整体重绑、hardlink/FIFO/socket/wrong owner/过宽 mode 拒绝 | macOS + Linux device |
| S18-CAP-11 | 有界 closure 与扫描 | `_tree_snapshot`、`_scan_file`、`_scan_tree`、`_window_hits` | exact cap、跨 chunk 命中、全 closure record | entry/file/byte/metadata/hit cap、identity 变化、未知分类 fail closed | macOS |
| S18-CAP-12 | no-replace 事务发布 | `_rename_noreplace`、`_publish_event`、`_post_rename_identity` | 唯一 inspection/event 与 fsync 顺序 | rename 不支持、碰撞、event 可见后故障转 `CONTROL_COMMIT_UNCERTAIN` | macOS renameatx + Linux renameat2 |
| S18-CAP-13 | 锁与并发 | `_open_lock`、`inspect_run` | 独立进程中一个 committer | 真实 flock 竞争仅报 `CONTROL_LOCKED`；namespace/identity 错误不得伪装 | macOS + Linux S16 |
| S18-CAP-14 | crash 分类与 ledger | `_ledger_state`、`verify_inspection` | empty/staging/orphan/committed 连续两次稳定分类 | gap、duplicate、坏 transition、重哈希语义无效 event 拒绝；verify 零写入 | macOS + Linux S16 |
| S18-CAP-15 | CLI 脱敏 | `capture_test_gate.main`、`manage_evidence_retention.main`、`_output` | 成功输出 canonical JSON | secret、HOME、路径、控制字符、traceback 不进入 stdout/stderr | macOS |
| S18-CAP-16 | qualification provenance | 新 verifier 和 runner | 命令、环境、版本、hash、run ID 可重算 | 缺原始 JSON/JUnit、hash 不一致、required skip 立即 No-go | 全部 runner |
| S18-CAP-17 | capture closure 资源上限 | `_DirFdReceiptIO.file_closure`、`_verify_receipt_from_io` | 在冻结的 entry/metadata/bytes 上限内完成闭包验证 | cap+1 在继续物化全量集合前 fail closed；若当前 schema 无法表达，先冻结内部常量和稳定错误，不得宣称已有界 | macOS + Linux |

## 6. 可执行测试矩阵

### 6.1 Coverage Gate 合同

| Test ID | 输入/故障 | 预期 |
|---|---|---|
| S18-COV-001 | capture coverage JSON 只含 capture 脚本且全门槛达标 | capture gate pass |
| S18-COV-002 | retention coverage JSON 只含 retention 脚本且全门槛达标 | retention gate pass |
| S18-COV-003 | JSON 混入另一脚本或 `t2l` totals | `SOURCE_SET_INVALID` |
| S18-COV-004 | `branch_coverage=false` 或字段缺失 | `BRANCH_COVERAGE_REQUIRED` |
| S18-COV-005 | combined 79.99、line 80、branch 80 | `COMBINED_COVERAGE_BELOW_THRESHOLD` |
| S18-COV-006 | combined 80、line 79.99、branch 80 | `LINE_COVERAGE_BELOW_THRESHOLD` |
| S18-COV-007 | combined 80、line 80、branch 79.99 | `BRANCH_COVERAGE_BELOW_THRESHOLD` |
| S18-COV-008 | critical symbol 缺失或 line/branch 非 100 | `CRITICAL_TARGET_UNCOVERED` |
| S18-COV-009 | required nodeid 缺失或 deselected | `REQUIRED_TEST_MISSING` |
| S18-COV-010 | required nodeid skip/xfail/fail/error | 对应稳定错误且 gate fail |
| S18-COV-011 | JUnit suite totals 自报绿色但 testcase 含 failure | 从 testcase 重算并拒绝 |
| S18-COV-012 | coverage、JUnit、policy、manifest 或 source hash 被改 | `EVIDENCE_BINDING_INVALID` |
| S18-COV-013 | manifest 重复 ID/nodeid、未知 symbol/category/runner | schema fail closed |
| S18-COV-014 | verifier 失败 | 输入 bytes/mode/closure 完全不变 |

### 6.2 Capture 补测优先级

先按风险而非行号补测。每组必须先生成 RED，再做最小实现或确认现有实现：

1. `_DirFdReceiptIO`：parent component、leaf、hardlink、FIFO、socket、owner、mode、nlink、open 前后 identity。
2. `_read_stable_regular` / `_safe_run_file`：路径形状、超限、swap、非普通文件。
3. package/canonical sidecar parser：所有 exact-key、整数/哈希/tag、duplicate JSON key、artifact closure。
4. `_finalize_run`：gate 失败、artifact snapshot 失败、source after 失败、seal 失败、failure marker 失败的优先级。
5. `_verify_receipt_from_io`：reason code 重算、source exact shape、return code normalization、两种 verify mode。
6. CLI：capture/verify 的 argparse、稳定 exit、stdout/stderr XOR、敏感数据不回显。
7. capture 自身的 formal artifact 必须直接验证 uid、private mode、`nlink=1` 与 entry/metadata/bytes budget；retention 的后置扫描不能替代 capture 的输入边界。如果现有实现缺失，先写 hardlink、wrong-owner、overwide-mode、cap+1 RED，再决定最小生产修正。

禁止用直接调用微小 helper 但不验证可观察结果的“行覆盖测试”替代合同。优先从 public API 或 CLI 驱动；只有无法稳定触达的 syscall race 才 monkeypatch 私有 seam，并同时断言落盘状态。

### 6.3 Retention required 节点

retention 的数字已过初始门槛，但以下节点必须进入 manifest，不得只依赖全文件通过：

- S7 control/config special-file、owner、mode、identity swap；
- S8 external expected digest 和 rule-set ID；
- S9 hit/report bounds；
- S10 no-replace、orphan、ledger invalid；
- S11 concurrent publisher、CLI secret/actor；
- S12/S13 namespace swap、post-event uncertainty、teardown；
- S14 entry/file/byte/metadata budgets；
- S15 current-source diagnostic-only；
- S16 subprocess lock、双 publisher、六个 SIGKILL checkpoint；
- S17 rules/assessment hardlink/FIFO/socket/wrong-owner 和 Linux block/char device。

### 6.4 Linux required runner

Linux 功能 Gate 至少收集并通过：

1. `test_ret_s16_subprocess_lock_contention_is_fail_fast_and_write_free`
2. `test_ret_s16_two_subprocess_publishers_never_double_commit`
3. `test_ret_s16_sigkill_checkpoint_has_stable_restart_classification` 的全部六个参数 case
4. `test_ret_s17_linux_block_and_char_devices_fail_before_control_write`
5. `test_current_source_verification_uses_open_repository_anchor`
6. `test_current_source_verification_rejects_later_checkout_drift`
7. `source` exact-key 与 observation-limit 相关节点

runner 要求：Linux x86_64、CPython 3.11、repo 只读挂载；保存 image ID/digest、Docker host 架构与容器内 `uname`。`/proc/self/fd` 必须在容器内实际可读。block/char device fixture 必须位于隔离临时目录，测试后不扩大清理范围。

旧 canonical Python 3.10.21 环境 collection 的 `datetime.UTC` ImportError 是 runner 不匹配记录，不授权修改生产代码。S18 Linux qualification 使用项目支持且已成功验证的 Python 3.11 runner；canonical golden 继续使用其自身锁定环境和选择器。

### 6.5 Package required runner

旧 macOS wheelhouse 已失效，原因是 manifest 绑定的 `pyproject_sha256` 与当前文件不一致。禁止手工替换 hash。该失败已保留为历史 RED。当前已从现有输入完整重建新的 macOS arm64 CPython 3.11 wheelhouse；补齐 `PKG-024` 后，在第三个不可覆盖 evidence root 完成 37 passed、1 deselected、0 skip/fail 的 package Gate，新 Gate `passed=true`。这只关闭当前 macOS package lane，不关闭 Linux package 或 S18 总 Gate。

可重算的新证据：

- wheelhouse：`/private/tmp/ai-auto-lrc-wheelhouse-s18.KhFDMP/macos-arm64-py311/`
- wheelhouse manifest SHA-256：`93f253e999a9e1b97a065ecf2205cad489e23eff04b3eb38c6a8c6a89df900c2`
- package evidence：`/private/tmp/ai-auto-lrc-s18-package-macos-v3.WTKSTr/`
- `package.xml` SHA-256：`562351c86726be2139620fa90e089714b9c6cffa5d796e5584db2fec805457e9`
- `package-gate.json` SHA-256：`2743b7d6f756a94eff6f46b02f8fca67b49dc1bc2f36387e7082c3f66aa116c4`

重建与验证流程仍冻结为：

1. 用当前 `pyproject.toml`、`uv.lock`、policy 完整重建 macOS arm64 CPython 3.11 wheelhouse；
2. 保存下载/构建命令、网络阶段边界、manifest 和所有 wheel hash；
3. 在新隔离环境断网 cold install；
4. 运行 package required suite，JUnit 必须 collected > 0、0 skip、0 xfail、0 fail/error；
5. 独立重算 manifest closure、tag、安装来源、CLI 和 policy 绑定。

上述五步已经在新的 macOS evidence root 完成；`34 passed, 1 failed, 1 deselected` 继续作为旧 wheelhouse 的 No-go 历史证据保留，不得删除或用新结果覆盖。新增 `PKG-012` 与 `PKG-017` 合同验证 runtime wheel tag、从发布 sdist 断网构建 project wheel、全依赖 cold install、`pip check`、installed origin 与 CLI。`PKG-024` 也已成为独立合同并进入 inventory：安装 wheel 的真实短音频 API 在干净 CWD 与含伪造 `t2l`、三个 checkpoint、manifest 的恶意 CWD 中生成完全相同的 LRC、status、spans 与 timebase，并证明 import origin 位于隔离安装目录、资产只来自显式 asset root。

### 6.6 Canonical required runner

当前 canonical 已在当前源码重建 image 中得到 13 passed、0 skipped。最终 S18 收口时必须在 coverage/package 修改稳定后再次运行，避免用较早 image 替代最终源码：

- image 固定 `linux/amd64`，记录 image ID 和 base digest；
- 断网、只读 root filesystem、受限 tmpfs；
- installed distribution origin 位于 site-packages；
- 13 个 required golden 全部 collected/passed，0 skip；
- JUnit、canonical gate、oracle、source snapshot 和 image identity 交叉绑定。

## 7. 证据目录与 receipt schema

建议每次 qualification 使用仓库外 exclusive 目录：

```text
<evidence-root>/<run-id>/
  run-manifest.json
  source-observation.json
  capture/
    coverage.json
    junit.xml
    gate.json
    stdout.log
    stderr.log
  retention/
    coverage.json
    junit.xml
    gate.json
    stdout.log
    stderr.log
  linux/
    junit.xml
    environment.json
    gate.json
  package-macos/
    junit.xml
    wheelhouse-manifest.json
    environment.json
    gate.json
  canonical/
    canonical.xml
    canonical-gate.json
    environment.json
  summary.json
```

`summary.json` 只能引用各子 Gate 的 hash 和状态，不能复制一个子 Gate 的通过状态替代其他子 Gate。目录创建使用 exclusive semantics；不得覆盖旧 run。验证模式只读，不得修正 mode、补文件或清理失败产物。

## 8. 分阶段实施与 DoD

### S18-0 冻结 schema

产出：policy、manifest 和 Gate JSON schema 草案；Teams 签署能力类别和 runner ownership。

DoD：所有类别、阈值、错误码、required runner 和禁止边界明确；未决定的签署人以角色占位，不伪造个人批准。

### S18-1 Verifier RED

先实现 `test_security_coverage_gate.py` 的伪造证据、阈值、hash、required nodeid 和只读合同。

DoD：记录首次失败；验证器最小实现后测试全绿；不存在为当前 coverage 特判的 bypass。

### S18-2 Capture coverage

按缺口清单新增真实负向和状态测试，直到 capture 同时满足 combined >= 80、line >= 80、branch >= 80、critical targets 100%。

DoD：capture-only fresh process；coverage JSON source set 精确；required nodes 全过；连续三轮无 flaky。

### S18-3 Retention coverage

用独立 fresh process 重跑 retention，补齐 manifest 关键 target；不能复用 capture coverage data。

DoD：retention 数字与 critical targets 同时通过；macOS 上的 Linux device skip 记录为 platform-excluded，不进入 Linux required JUnit。

### S18-4 Linux qualification

使用 Linux x86_64 Python 3.11 runner 生成 JUnit 和环境 receipt。

DoD：required nodeids 全部 collected/passed，0 skip/fail；`renameat2`、`/proc/self/fd`、device、S16 均有直接证据。

### S18-5 Package qualification

完整重建 wheelhouse，再执行断网 cold package Gate。

DoD：manifest 与当前 inputs hash 一致；package JUnit 0 skip/fail；旧失败仍保留在历史记录。

当前检查点：macOS wheelhouse 重建、`PKG-012`/`PKG-017`/`PKG-024` 合同、Spec Inventory 和 37-test Gate 已完成；Linux package evidence 未刷新，因此本阶段仍为 partial。

### S18-6 Canonical refresh

在最终源码上重建 canonical image 并重跑 13 个 required golden。

DoD：13 passed、0 skipped；image/source/JUnit/gate hashes 可独立重算。

### S18-7 全量回归和 evidence refresh

执行 S16/S17 targeted、capture、retention、combined、host full、Ruff、compileall、`git diff --check` 和文档相对链接检查。随后用最新源码生成新的 PASS/BLOCKED sealed evidence。

DoD：所有首次失败和 retry 都有记录；最终 evidence 的 source observation 与最后代码一致；较早 run 明确标记 historical。

### S18-8 Gate 复审

Teams 按 capability manifest、原始 evidence 和未关闭边界复审 W1b-5b。

DoD：只能在全部 S18 required Gate 通过后讨论 W1b-5b；即使 W1b-5b 通过，也不自动授权 5c/5d/5e 或 Release。

## 9. 执行命令基线

命令在实现 runner 时固化；下面是人工复核基线，实际命令和版本必须进入 evidence：

```bash
# capture-only，fresh coverage data
COVERAGE_FILE=<exclusive-root>/.coverage-capture \
uv run --frozen --no-sync python -m pytest \
  tests/contract/test_evidence_capture.py \
  -q -p no:cacheprovider --junitxml=<exclusive-root>/capture/junit.xml \
  --cov=scripts.capture_test_gate --cov-branch \
  --cov-report=json:<exclusive-root>/capture/coverage.json \
  --cov-report=term-missing --cov-fail-under=80

# retention-only，different fresh coverage data
COVERAGE_FILE=<exclusive-root>/.coverage-retention \
uv run --frozen --no-sync python -m pytest \
  tests/contract/test_evidence_retention.py \
  -q -p no:cacheprovider --junitxml=<exclusive-root>/retention/junit.xml \
  --cov=scripts.manage_evidence_retention --cov-branch \
  --cov-report=json:<exclusive-root>/retention/coverage.json \
  --cov-report=term-missing --cov-fail-under=80

# verifier 合同
uv run --frozen --no-sync python -m pytest \
  tests/contract/test_security_coverage_gate.py -q

# 最终宿主回归
uv run --frozen --no-sync python -m pytest -q
uv run --frozen --no-sync ruff check .
uv run --frozen --no-sync python -m compileall -q t2l scripts tests
git diff --check
```

占位符必须由 runner 传入经过验证的绝对路径，不能直接复制执行。evidence root 必须位于仓库外且路径链无 symlink；macOS 使用 `/private/tmp/...` 的规范路径。

## 10. 角色职责与签署

| 角色 | 责任 | 不得代签的范围 |
|---|---|---|
| Architect | 冻结 policy、manifest、schema、边界和停止条件 | 不以架构评审代替实测 |
| Developer | 实现 verifier/runner 和最小生产修正，保留 RED | 不自行降低门槛或扩大允许错误集合 |
| QA | 维护 required nodeids、负向矩阵、flaky/skip 记录 | 不用 macOS skip 代替 Linux pass |
| Linux runner owner | 提供隔离 image、device 权限和环境 provenance | 不签 package/canonical |
| Package owner | 重建 wheelhouse、断网 cold install 和 package receipt | 不手工改 manifest hash |
| Canonical owner | 重建 image 并生成 canonical receipt | 不把旧 image 签成最终源码 |
| Evidence reviewer | 从原始 artifact 独立重算全部 Gate | 不运行自动修复或清理 |
| Release approver | 在上位 Release 条件全部满足后另行批准 | S18 通过不构成 Release 批准 |

具体人员尚未由用户指定时，只记录角色，不虚构 owner 或 signer。一个人可以兼任多个角色，但每次签署必须保留“producer”和“independent verifier”两个逻辑步骤及各自证据。

## 11. 首次失败和 retry 留痕规则

以下记录不可被最终绿色覆盖：

- S16 双 publisher 首轮 7 passed、1 failed 及 `ENOENT` 根因；
- S17 首轮 10 passed、6 failed；20 轮稳定性；联合首轮 1 failed、319 passed；
- 旧 S18 canonical Python 3.10 runner collection 的 `datetime.UTC` ImportError；
- capture coverage 75.7545% 和追加 retention 后 75.8551% 两次 RED；
- macOS package 34 passed、1 failed、1 deselected 及两个 `pyproject_sha256`；
- 任何新增 flaky、skip、fixture 错误、runner 错配和 retry。

每次记录至少包含时间、命令、环境、退出码、失败 nodeid、简短根因分类、修正内容和重跑结果。fixture 错误与 production RED 必须分开，不得合并成“测试失败”。

## 12. 停止条件

出现以下任一情况，S18 保持 No-go 并停止进入下游：

- 需要降低 80% combined/line/branch 门槛才能通过；
- 关键 symbol 只能靠排除、`pragma: no cover` 或删除逻辑变绿；
- coverage source set 不是单一目标脚本；
- required nodeid skip、xfail、deselected、fail 或未收集；
- Linux、package、canonical 任一 required runner 缺失或 provenance 不可重算；
- wheelhouse manifest 与当前 inputs hash 不一致；
- 最终源码晚于 coverage/package/canonical evidence；
- verifier 必须信任 producer 自报 totals/qualification；
- 实施需要 CI、upload、签名、发布、archive、restore、delete、commit 或 push，但没有新的明确授权。

## 13. 当前证据索引

当前临时证据根为 `/private/tmp/ai-auto-lrc-s18.sl1UY6/`。它用于保留本轮现场，不是长期发布制品：

| Artifact | SHA-256 / 状态 |
|---|---|
| `capture-coverage.json` | `bb0a0a1e4e4c2cd5e516da3a80e7f0c4c6734b821c638c2800faab46fdd08c6f`；RED |
| `capture-coverage-combined-tests.json` | `d1de8536b15db6013d4672f30b41d5ddc3130e4c453b79eb399626f0503d102c`；75.8551%，RED |
| capture S18 final `coverage.json` | `60dc07452648a71a76a688a36517aefaad3b2023f569887a98bdbae4253f518c`；source set 仅 capture，line 88.8736%、branch 81.0680%、combined 86.5477% |
| capture S18 final `junit.xml` | `147270dcbcef89273233ee48f950c4bdfbe7bc67694fcb9cf4602f0f603bfe72`；252 passed、0 skip/failure/error |
| `retention-coverage.json` | `c38ef9beb65c7968849ddbdeaa81f94591e7ae667ff9d45d6dc6bff1503bfd77`；branch 76.25%，RED |
| retention S18 baseline `coverage.json` | `58d255dd47458fbc1b7a3db81994682d53c1bebd0bd26bcd32139d098563ed57`；175 passed、1 platform skip，line 84.4463%、branch 74.25%、combined 81.9410%，RED |
| retention S18 baseline `retention.xml` | `110fa4cc62125c40f935455ca1e3fa85620e2ae9f4aa7125eed4a70ee401b836`；保存首次独立 coverage RED |
| retention S18 final `coverage.json` | `9c0f09de11f4123849b4b378ed4397abb6b9a8d91d239ce272666b2c93a9e29b`；source set 仅 retention，line 88.5922%、branch 82.4257%、combined 87.0732% |
| retention S18 final `retention.xml` | `ebf5309e1f228a2e421abe56e65c38c5d288e38046d2640f7619103a2cbe7f59`；207 passed、1 macOS 上明确的 Linux-only skip |
| `package-macos/package.xml` | `ea0c267722761f2e5747946df93d6ff109acd18cde4a456332f20ee7db7b9aef`；`PKG-018` hash mismatch，No-go |
| 新 wheelhouse `manifest.json` | `93f253e999a9e1b97a065ecf2205cad489e23eff04b3eb38c6a8c6a89df900c2`；由当前 `pyproject.toml`、`uv.lock`、policy 完整重建 |
| 新 `package-macos-v2/package.xml` | `cfc0f794bb826fd7c07059dfeb1e9125c7b7ac68dcc3c862d8c19c312ebdc491`；36 passed、0 skipped/failures/errors |
| 新 `package-macos-v2/package-gate.json` | `ddaf132bfa1efdaeb58ab2b39ca6db934bfc64e2f245c03eec005c1b5b77793f`；`passed=true`，仅关闭 macOS 当前 package lane |
| 最终 `package-macos-v3/package.xml` | `562351c86726be2139620fa90e089714b9c6cffa5d796e5584db2fec805457e9`；37 passed、1 Linux-only deselected、0 skip/fail |
| 最终 `package-macos-v3/package-gate.json` | `2743b7d6f756a94eff6f46b02f8fca67b49dc1bc2f36387e7082c3f66aa116c4`；`passed=true`，包含 `PKG-024` |
| `canonical/canonical.xml` | `63e5393d835134814f57a1b4dc0a8135c68a52527e75cfe9867b23a2544000a5`；13 passed、0 skipped |
| `canonical/canonical-gate.json` | `4579f84294956c30fe113f79b50fa046c6eb41cd8b39dd86b7f5d599e94df24c`；`passed=true`，只在该次 image/source 边界内有效 |

当前 canonical image 为 `sha256:d429650aacae3d9c8a50dfb1ff3e73e065e49eca3016bf3662e5ca2e7d7f5b19`，平台为 `linux/amd64`。最终代码变化后必须重建，不得复用该 digest 作为最终 qualification。

## 14. 完成判定

S18 完成必须同时满足：

1. policy、manifest、verifier、runner 和合同测试均存在且通过；
2. capture 与 retention 独立 coverage Gate 通过；
3. 两个脚本所有 critical target 100% line/branch；
4. Linux required nodeids 0 skip/fail；
5. 新 macOS wheelhouse 的 package Gate 0 skip/fail；
6. 最终源码 canonical 13 required tests 0 skip/fail；
7. 宿主全量、Ruff、compileall、diff、文档链接通过；
8. 最新 PASS/BLOCKED evidence 由独立 verifier 重算；
9. 所有历史 RED、skip 和边界仍可追溯；
10. Teams 明确签署 W1b-5b 的新 Go/No-go。

S18 完成后允许的最大结论是：两个本地安全脚本和 W1b-5b 在声明平台、runner、源码与 evidence 边界内完成资格收口。它仍不证明 power-loss、同 UID 完整 ABA、独立 checkpoint/source 恢复、双平台 release package、Demucs、SBOM、attestation、签名或 rollback，也不授权 W1b-5c/5d/5e 和 Release。

## 15. 关联文档

- [W1b-5 retention manager 执行计划](./W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md)
- [AI 重构 v2 主执行计划](./AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md)
- [AI 重构交接文档](./AI_REFACTOR_HANDOFF.zh-CN.md)
- [W1b controlled evidence capture 计划](./W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md)
- [S16 Teams 记录](./team-sessions/team-session-2026-09-06-4.md)
- [S17 Teams 记录](./team-sessions/team-session-2026-09-06-5.md)
- [S18 Teams 记录](./team-sessions/team-session-2026-09-06-6.md)

## 16. 2026-09-06 续接检查点

本节是防止会话压缩或跨任务交接丢失细节的恢复入口；它记录执行状态，不替代第 5 节 capability manifest、第 6 节测试矩阵或第 14 节完成判定。

### 16.1 已落盘且不得回退的决策

1. capture 与 retention 必须分别计算 combined、statement line、branch coverage；三项最低均为 80%，critical target line/branch 为 100%。
2. `packaging/quality-gates.toml` 不扩成混合事实源；S18 使用独立 policy、manifest、verifier 和 runner。
3. capture 必须自行验证 formal artifact 的 uid/mode/nlink 与 closure entry/metadata/bytes budget；retention 后置扫描不能代签。
4. macOS、Linux、package、canonical 证据不可互相替代；较早绿色结果不能证明最后源码。
5. 首次 RED、fixture 错误、flaky、skip、retry 必须保留；禁止通过删分支、降低门槛、扩大 omit 或 `pragma: no cover` 取绿。
6. W1b-5c export、5d archive/restore、5e destruction 仍未授权；不创建 CI，不上传、签名、发布、commit、push，也不自动清理当前 dirty worktree。

### 16.2 当前 Teams 实现线

| 工作线 | 独占修改范围 | 当前恢复点 |
|---|---|---|
| Security Gate | `packaging/security-coverage-policy.toml`、`packaging/security-coverage-manifest.json`、`scripts/verify_security_coverage.py`、security runner、`tests/contract/test_security_coverage_gate.py` | contract-first collection RED 已保留；verifier 合同 41 passed。最近一次统一 runner 仍因 critical target 为 `CRITICAL_TARGET_UNCOVERED`，正确 No-go；其后两条工作线 raw coverage 已补齐，但 manifest 裁决和同源 gate 尚未刷新 |
| Capture closure | `scripts/capture_test_gate.py`、`tests/contract/test_evidence_capture.py` | fresh raw coverage 273 passed、0 skip/fail，line 90.7280%、branch 84.4660%、combined 88.8621%；当前 9 个原子 critical exact function summary 均 100%，待统一 verifier 绑定 |
| Retention coverage | `scripts/manage_evidence_retention.py`、`tests/contract/test_evidence_retention.py` | fresh raw coverage 244 passed、1 个声明的 Linux-device platform skip，line 93.9320%、branch 89.1089%、combined 92.7439%；复审后的 12 个原子/窄边界 symbol 均 100%，待 manifest 更新和统一 verifier 绑定 |

主任务在合并三条线前不得覆盖上述文件。集成时先检查实际 diff，再依次运行各自 targeted tests、Spec Inventory 和独立 security coverage runner。

Retention 工作线较早的 final artifact 位于 `/private/tmp/ai-auto-lrc-s18-retention-final.YsW1sD/`；最新 raw artifact 和 hash 见 17.5。source SHA-256 仍为 `131d9964da80a29045d046941c314d207380e59b152995ec70def9a4689dc508`。新增 S18 case 与 20/20 稳定性轮次已通过。两处生产修复限定为 child `open()` 成功但后续 `fstat()` 失败时关闭 fd，并各自保留先 RED 后 GREEN 的证据。首次稳定性 shell 因 zsh 的 `status` 为只读变量而退出，也必须作为 runner 错误保留；修正变量名为 `result_code` 后的成功轮次不能抹去该记录。

Capture 工作线较早的同源 artifact 位于 `/private/tmp/ai-auto-lrc-s18-capture-final.9fxXOx/capture/`；最新 raw artifact 和 hash 见 17.4。source SHA-256 仍为 `12ab84391e12723f565ae9c549a95b872859e379eea15a7a1510acde8b0f303d`。该工作线在 production 冻结 formal dir/file mode、owner/nlink 与 entries/metadata/bytes 上限。首个系统 runner 因缺少 `PYTHONPATH` collection 失败；有效首轮为 9 failed、29 passed，其中 8 个 production RED 与 1 个 fixture 漏 import；其后还经历 combined 78.68%、branch 71.82% 和 branch 76.38% 两次独立 coverage RED。较早 252-test suite 连续三轮稳定；本轮又增加 21 个 targeted case并得到 273 passed。所有中间 RED 均不得被最终绿色覆盖。

统一 security runner 的同源 attempt 为 `/private/tmp/ai-auto-lrc-s18-gate-final.pDkaPN/attempt-002/`。两条 lane 的 source set、hash binding、required nodeids 和总体数值都通过，但 verifier 从 function coverage 重算后拒绝签署：capture critical 5/21，retention critical 1/16。capture gate SHA-256 为 `49849bc737019c8a23964b9f6c324947a5e7792ed3aac7a747fb075084429757`，retention gate SHA-256 为 `f885b64b18e257e234134d824d8d821b850492bd818371def492aeebecc6a3d4`。这不是 aggregate coverage 缺口；下一轮必须先区分原子 fail-closed enforcement seam 与大型 orchestration/diagnostic aggregator，再对前者补到 100%，后者保留 capability mapping、required 成功/失败 nodeid 与 global 80% 约束。该分层只能改变 `critical_*` 身份，不能删除 capability、降低 100% 门槛或移除反证。

### 16.3 Spec Inventory 与 package 未闭合项

Spec Inventory 首轮结果为 2 failed、2 passed：

1. 新 package 测试 docstring 曾使用缩写链 `PKG-012/017`，已改为 `PKG-012 and PKG-017`；
2. 当时 verifier 尚不存在，collection 触发 `ModuleNotFoundError: scripts.verify_security_coverage`。

当前 `PKG-024` exact nodeid 已映射到 `tests/spec_inventory.json`，与 Spec Inventory 一起重跑为 5 passed。`PKG-024` 自身首轮两次 RED 分别来自“第三方 warning 必须为空”和预期 span end 写成 8 而真实冻结值为 7，均归类为测试断言/fixture 错误；修正后真实产品行为未改动并通过。最终完整 macOS package Gate 为 37 passed、1 deselected。

### 16.4 下一执行顺序

```text
等待并审阅三条 Teams 工作线
  -> targeted tests + Spec Inventory
  -> 已完成的 PKG-024 与 inventory 证据复核
  -> capture/retention 独立 coverage runner 和 verifier
  -> Linux exact-node JUnit/provenance
  -> Linux package evidence
  -> 最终源码 canonical refresh
  -> host full + Ruff + compileall + diff/link checks
  -> 最新 PASS/BLOCKED sealed evidence
  -> Teams 复审 W1b-5b（Release 仍独立 No-go）
```

## 17. Teams 架构复审后的可执行重构方案

本节冻结 2026-09-06 Architect、Gate implementer、Capture reviewer、Retention reviewer 与 QA 视角的共同结论。它是后续续接的首要执行入口；任何实现若与本节冲突，必须先修改并复审本节，不能在测试代码中静默改变 critical 身份。

### 17.1 Critical 分级判据

`critical line/branch = 100%` 只授予原子 fail-closed enforcement seam，判据必须同时满足：

1. 函数是 leaf 或窄状态转换，不是多个 schema、平台和 artifact 的总编排器；
2. 某个分支未执行可能直接把不安全输入变成接受、发布或写入；
3. 该不变量没有被另一个已标 critical 的下层 seam 重复执行；
4. 成功与失败能通过稳定、可观察的结果验证，而不是只断言调用次数；
5. coverage.py 能以稳定 symbol 唯一识别整个 enforcement body。

不满足这些条件的函数仍必须保留 capability、symbol、success/fail-closed nodeid 和 runner 映射，并受全文件 combined/line/branch 80% 约束。`critical=false` 不等于不测试，也不允许删除反证。

当前 capture 原子集合冻结为：

- `_DirFdReceiptIO._open_parent`
- `_DirFdReceiptIO.read`
- `_DirFdReceiptIO.file_closure`
- `_read_stable_regular`
- `_verify_record`
- `_normalize_returncode`
- `_seal_run`
- `_source_material_at`
- `verify_receipt_at`

当前 manifest 已登记的 retention 原子集合为：

- `_stable_bytes`
- `_open_lock`
- `_rename_noreplace`
- `_post_rename_identity`
- `_scan_file`
- `_tree_snapshot`
- `_window_hits`
- `_ledger_state`

Teams 对另外 4 个函数有过明确分歧。Gate implementer 主张它们是对下层 seam 的编排/聚合，避免重复计量；Retention reviewer 指出它们分别是“事件已可见后的 commit-uncertain 分界”“run-wide 总预算”“外部配置 digest + strict schema 信任边界”，任一拒绝分支失效都可能直接接受不安全状态。Architect 最终裁决为：在 R0 manifest 变更中将以下 4 个函数提升为 critical；它们均不超过 39 statements，当前 fresh function summary 已经 line/branch 100%，不会靠降低门槛取绿：

- `_publish_event`：负责 rename 前可清理与 rename 后 `CONTROL_COMMIT_UNCERTAIN` 的不可逆边界；
- `_scan_tree`：负责单文件扫描之外的 run-wide entries/files/bytes/hits/metadata 总预算和 root identity；
- `load_secret_rules`：负责外部 expected digest、编码、strict schema、rule/matcher bounds 的信任入口；
- `load_retention_assessment`：负责 assessment digest、schema 与 rule-set/capability binding 的信任入口。

`_output`、`main`、`inspect_run` 和 `verify_inspection` 保持 noncritical。前两者是 CLI 薄适配，后两者分别为 112/65 statements 的多阶段事务编排。它们必须通过真实 CLI、secret/HOME/control-character/traceback、pre-commit failure、post-commit uncertain、tamper verify 和 current-source diagnostic required nodeids 加全文件 80% 约束；当前覆盖率高不构成提升 critical 的理由。

### 17.2 需要拆分的大型函数

以下函数不得为了当前 Gate 直接追求函数级 100%。重构目标是缩小职责和形成可测合同，不是移动未覆盖行：

| 现有函数 | 问题 | 目标组件 | 验收方式 |
|---|---|---|---|
| `_verify_receipt_from_io` | 读取、schema、artifact closure、source、sidecar、reason/qualification 重算集中在单函数 | `parse_receipt`、`verify_formal_closure`、`verify_source_binding`、`verify_layer_binding`、`derive_qualification`；全部返回 typed result/reason，不直接输出 | 原 receipt 成功/失败结果与 reason 顺序保持；每个新 enforcement leaf 独立 100%；总编排由成对 E2E nodeids 约束 |
| `_validate_package_sidecar` | package schema、wheel tag、安装 origin、JUnit、manifest 与 artifact hash 混合 | exact-schema parser、package identity validator、artifact closure validator、JUnit binding validator | 旧 sidecar 合同全绿；逐字段删改、重复 key、跨 run/layer/hash 反证保持稳定错误 |
| `_validate_canonical_sidecar` | container identity、formal input、oracle、scope、network/rootfs 与 artifact 闭包混合 | canonical schema parser、runtime isolation validator、oracle binding validator、artifact closure validator | 13 golden 成功路径不变；formal input/scope/network/rootfs/hash 各有独立 fail-closed case |
| `_portable_binding_reasons` / `_package_binding_reasons` / `_canonical_binding_reasons` | 诊断 reason 聚合与底层判断耦合，组合分支数量随 schema 增长 | 各层返回 immutable validation facts；单一 deterministic reason reducer 只排序/去重 | 相同输入得到字节稳定 reason 列表；底层验证器独立测真假，reducer 测顺序和重复 |
| `inspect_run` / `verify_inspection` | 事务阶段、环境时序、重复自检和多阶段绑定集中 | read-only observation、ledger classification、publish decision、post-commit verification 四层 | 六个 SIGKILL checkpoint、双 publisher、orphan/invalid/committed 真实进程测试结果不变 |

拆分顺序必须由内向外：先增加 characterisation tests，抽取纯解析/判断 helper，再让旧函数委托，最后才调整 manifest symbol。禁止同时改 schema、reason code 和控制流；每个 PR/本地变更批次只做一个可回滚切片。

### 17.3 嵌套 walker 的结构性缺口

当前 coverage JSON 将 `_DirFdReceiptIO.file_closure` 与 `_DirFdReceiptIO.file_closure.walk` 分开统计。外层已是 6/6 line、0/0 branch，但 nested `walk` 仅为 48/52 line、20/24 branch。Retention 的 `_tree_snapshot` 外层为 13/13 line、2/2 branch，但 `_tree_snapshot.walk` 仅为 32/41 line、17/20 branch。若 manifest 只匹配外层 symbol，会出现“critical 100% 但实际遍历 enforcement body 未完全测量”的假绿风险。

执行方案：

1. 先保持现有 public API 和稳定错误码不变，增加 closure/tree exact-cap、cap+1、unsupported node、identity drift、metadata/byte budget characterisation tests；
2. 将 nested walker 抽成模块级或类级、名称稳定的私有函数，例如 `_walk_receipt_closure` 与 `_walk_retention_tree`；
3. 显式传入 pinned dirfd、budget/state 和读取 callback，不重新解析可变路径；
4. 在 manifest 中新增新 helper symbol 为 critical，再运行 verifier；
5. 只有新 helper line/branch 100%、旧外层合同不变、真实 FIFO/socket/hardlink/identity case 全过后，才允许移除旧 nested symbol 诊断。

不能伪造操作系统不会从 `scandir()` 返回的 `.`、`..` 或含 `/` 名称来补覆盖。不可达防御分支要么通过设计证明后移到输入 parser，要么保留为非 critical 防御代码并记录理由；禁止用 pragma 隐藏。

### 17.4 Capture 本轮新增测试清单

本轮新增 21 个 contract case，按可观察风险分组如下：

| 组 | 新增反证/状态 | 预期 |
|---|---|---|
| parent fd | open 后不是目录、identity 漂移、parent open `OSError` | fail closed，已打开 fd 必须关闭，不读取可变路径 |
| sealed read | `os.read` 提前 EOF | size mismatch，不能接受短读 |
| stable read | 平台缺少 `O_NOFOLLOW`、stream short read | 保持 regular/identity/size 验证；短读拒绝 |
| return code | `None`、负 signal、正 exit | 稳定映射 raw/normalized/signal，finalizer 不掩盖原 gate |
| seal | 目标是 symlink、目标已存在 | 不发布、不替换、保留 staging/失败证据 |
| finalize | 同进程 gate 显式 signal | receipt 与进程返回保持真实 signal 语义 |
| CLI | `CaptureResult.run_directory=None` | 不伪造路径，输出保持单一脱敏通道 |
| source material | Git 报告 FIFO、symlink identity drift | special ledger 记录；漂移拒绝 |
| source summary | archived snapshot、symlink target mismatch、duplicate ledger path | 真实 snapshot 可验证；mismatch/duplicate 拒绝 |
| anchored source | closed fd、非目录 fd、descriptor identity drift、anchor path drift | 全部 fail closed，不退回 path-based trust |

定向结果为 `21 passed, 252 deselected`；fresh 全套 capture 结果为 `273 passed`、0 skip/failure/error。原始计数为 statement `1321/1456 = 90.7280%`、branch `522/618 = 84.4660%`、combined `88.8621%`。当前 9 个 capture 原子 critical symbol 在该 coverage JSON 的 exact function summary 中均为 line/branch 100%。

本次 raw artifact：

- root：`/private/tmp/ai-auto-lrc-s18-capture-doc-final.XBL1Yo/`
- source SHA-256：`12ab84391e12723f565ae9c549a95b872859e379eea15a7a1510acde8b0f303d`
- test SHA-256：`93f1a5d7ddea7e839937da1e7b270efef39c96b002876b3a2c402674b73cb4c0`
- `coverage.json` SHA-256：`e9ffe32bde0299346691602e4fefb8b045c9783f5041b953d302afb88a6bf917`
- `junit.xml` SHA-256：`b179c7bd10d44e11114c1e1391b2fdaf42c23320574e75b64d56c14d80ecdd23`

该目录是临时 raw evidence，不是已签署资格制品；统一 runner 尚未用新 JUnit/coverage/hash 重建 gate，因此当前结论只能写成“原子 critical raw coverage 已闭合，security Gate 待刷新”。

### 17.5 Retention 本轮测试与证据

Retention 最终 fresh 全套结果为 `244 passed`、1 个 macOS 上显式声明的 Linux-device skip、0 failure/error；coverage JSON 只包含 `scripts/manage_evidence_retention.py`。原始计数为 statement `1161/1236 = 93.9320%`、branch `360/404 = 89.1089%`、combined `92.7439%`。

当前 manifest 的 8 个 critical symbol 与架构复审建议新增的 `_publish_event`、`_scan_tree`、`load_secret_rules`、`load_retention_assessment` 均为 exact function summary line/branch 100%。`_output` 和 `main` 虽然也是 100%，仍按 CLI 编排器处理；`inspect_run` 为 line `98.214%`、branch `93.333%`，`verify_inspection` 为 line `89.231%`、branch `78.125%`，两者用事务 E2E required nodeids 和下层 critical seams 约束，不要求整函数 100%。

本轮补充了 ledger staging、writable tree root 和 CLI `RetentionError` 路径；既有两处最小生产修正继续保留：path/anchored dirfd 在 child `open()` 成功而后续 `fstat()` 失败时必须关闭 fd，且都有先 RED 后 GREEN 的证据。

本次 raw artifact：

- root：`/private/tmp/ai-auto-lrc-s18-retention-critical-final.CTShKx/`
- source SHA-256：`131d9964da80a29045d046941c314d207380e59b152995ec70def9a4689dc508`
- `coverage.json` SHA-256：`1ce6d324d87117a0668f10584a487e114c992d6bb50b33511e353600056677b7`
- `junit.xml` SHA-256：`af15c157d7f03969a2dbc1c9183a3165fc781c1abc48c6da39baafde314e93e9`

与 capture 相同，该目录是临时 raw evidence。新增 4 个 critical 身份会改变 manifest bytes，必须创建新 attempt 并由 verifier 重算，不能复用旧 gate hash。

### 17.6 重构与测试的执行波次

| 波次 | 允许修改 | 必须先有的 RED/characterisation | 完成条件 | 回滚边界 |
|---|---|---|---|---|
| R0 证据冻结 | docs、policy/manifest schema，不改业务控制流 | 当前 `CRITICAL_TARGET_UNCOVERED` gate 与所有历史 RED | critical 判据、symbol、nodeid、runner、hash schema 固定 | 仅回滚规格文件 |
| R1 walker 提取 | capture/retention 各自 walker 与对应 contract tests | nested function missing lines/arcs；exact-cap/cap+1 | 新 walker critical 100%，外层 API/reason/receipt bytes 不变 | 单脚本单测试文件 |
| R2 sidecar parser 提取 | package 或 canonical 单 lane | duplicate key、missing/unknown key、cross-run/hash | exact schema helper 100%，旧 E2E 与 artifact hash 语义不变 | 每次只做 package 或 canonical |
| R3 binding facts/reducer | 一种 layer binding | reason ordering/duplicate/multiple-failure characterisation | immutable facts + deterministic reducer；同输入 reason 列表一致 | 保留旧 wrapper 可立即切回 |
| R4 receipt pipeline | `_verify_receipt_from_io` facade 和新组件 | current/archived、tamper、source drift、formal closure 全套 | facade 只编排；新 leaf critical 100%；E2E required 全过 | 每个阶段独立 commit-ready diff，不实际 commit |
| R5 retention transaction | inspect/verify facade 和阶段组件 | S10/S13/S16 crash/concurrency 全套 | 六 checkpoint、双 publisher、uncertain/ledger 分类不变 | 不同时改 ABI/no-replace 实现 |
| R6 qualification refresh | runner/evidence only | 不适用 | capture/retention fresh gate、Linux、package、canonical、host/static 全部同源 | 失败保留新 attempt，不覆盖旧 evidence |

每个波次固定执行顺序：`targeted RED -> 最小实现 -> targeted GREEN -> 单脚本 fresh coverage -> verifier -> Ruff/compileall/diff-check -> 文档状态更新`。任何 source、test、policy 或 manifest 字节变化都会使较早 gate 失效，必须创建新 attempt，禁止覆盖。

### 17.7 最终可执行验收清单

- [ ] capture 与 retention 使用不同 fresh `COVERAGE_FILE`，coverage JSON source set 各自精确等于一个脚本，且从未 combine。
- [ ] 两个脚本的 combined、statement line、branch 都独立 `>= 80%`。
- [ ] manifest 中所有原子 critical symbol 的 line/branch 都为 100%；0/0 branch 显式记录。
- [ ] nested walker 已被独立命名和度量，或 Gate 明确 BLOCKED；不能以外层函数 100% 代替。
- [ ] 每项 capability 至少一个 success 和一个 fail-closed required nodeid；当前 runner 中全部 collected/passed。
- [ ] macOS 只允许 manifest 声明的 Linux-only device skip；Linux required runner 必须 0 skip/fail/error。
- [ ] policy、manifest、source、test、coverage、JUnit、environment、command 和 run manifest hash 均从当前 bytes 重算一致。
- [ ] runner 使用 exclusive attempt root，不覆盖旧目录；失败仍保留原始日志、退出码和 artifact。
- [ ] capture 与 retention 各连续三轮无 flaky；package/canonical/Linux 不能替代任一 coverage Gate。
- [ ] package macOS、package Linux、canonical 和 host full/static evidence 均晚于最后源码变化。
- [ ] 首次 RED、fixture/runner 错误、skip、retry 与修复后结果全部可追溯。
- [ ] Teams Evidence reviewer 从原始 artifact 独立重算并签署 W1b-5b；Release 继续单独 No-go。

### 17.8 2026-09-06 R1 落盘检查点

本节是当前代码字节对应的恢复检查点。第 17.1–17.7 节继续定义架构与验收合同；本节只记录已经发生的实现事实和下一条可执行命令链，后续结果不得覆盖或删除这里列出的 RED、skip、retry 与旧 artifact。

#### Capture walker

- 已把 nested `_DirFdReceiptIO.file_closure.walk` 提取为模块级 `_walk_receipt_closure`；新 seam 显式接收 pinned dirfd、共享 state、entry/metadata budget、directory flags 和验证 callbacks，不重新解析可变路径。
- 提取前的 nested 证据为 line `48/52`、branch `20/24`；缺失分支对应目录打开后的 identity/traversal drift。新增 seam 合同首次 RED 为 symbol 尚不存在，随后用真实 nested tree 与四类 drift 关闭。
- targeted：`12 passed`；fresh full：`278 passed`、0 skip/fail/error。
- 新 walker：line `52/52 = 100%`，branch `24/24 = 100%`；全文件 line `1328/1459 = 91.0212%`，branch `526/618 = 85.1133%`，combined `89.2634%`。
- artifact root：`/private/tmp/ai-auto-lrc-s18-capture-walker-final.xsNvfq/`。
- source SHA-256：`69748719528956ecb15a84aabbe02e0089668872e048d9021cc6d6429a449428`；test SHA-256：`7324ef23f2aa467bf4257a6e24f4c9cb158feb71fa9d5098ece72d317530b2fe`；coverage SHA-256：`468482683d18ba6ac03c957cb3dfb5e3b7a4c796a1d7ef0c503dac86613e0f53`；JUnit SHA-256：`80eab3da6679c8639d0e591f318a07a78a3d3e2361ba91b31000c1abb6afcb42`。

#### Retention walker

- 已把 nested `_tree_snapshot.walk` 提取为模块级 `_walk_retention_tree`；新 seam 显式接收 pinned directory fd、相对 `PurePosixPath` prefix、共享 `_SnapshotBudget` 与 snapshot state，递归不接收或重新解析可变 `Path`。
- 提取前的 nested 证据为 line `32/41`、branch `17/20`；缺失非法 name、stat、special node、scandir、child open/fstat 和 identity mismatch 路径。新增 seam 合同首次 RED 为 symbol 尚不存在；最小实现还关闭了 child `open()` 成功而 `fstat()` 失败时的 fd 泄漏窗口。
- 新增 9 个 R1 case；fresh full：`253 passed`、1 个 macOS 上声明的 Linux-device skip、0 fail/error；walker targeted 连续 `20/20` 轮通过。
- 新 walker：line `45/45 = 100%`，branch `22/22 = 100%`；全文件 line `1174/1240 = 94.6774%`，branch `365/406 = 89.9015%`，combined `93.4994%`。
- artifact root：`/private/tmp/ai-auto-lrc-s18-retention-r1.pllOqf/`。
- source SHA-256：`7f33617cd6830f13753f1071a0ea1dc196f9782f1bce5d971affad19532dd2a2`；test SHA-256：`b7eee2840e689fbdef5f6c01ff99c220836b85bdc851c5c35f0e1eed80bbb2e8`；coverage SHA-256：`5c13efefb812340ce0bb02face9f67b374be999f2b5aebb6af44b5fb4c9cb89c`；JUnit SHA-256：`a0e4e4d9fb54f8bab0e369dada37455cb2c615c3721b24b9f206a816c25e14de`。

#### 尚未闭合的执行链

1. 更新 `packaging/security-coverage-manifest.json`：把 `_walk_receipt_closure` 归入 capture closure capability、把 `_walk_retention_tree` 归入 `S18-CAP-11`，两者均冻结 `critical_line=true`、`critical_branch=true`；同时把 `_publish_event`、`_scan_tree`、`load_secret_rules`、`load_retention_assessment` 提升为 retention critical。
2. 在 exclusive 新 attempt 中执行 `scripts/run_security_coverage.sh`；capture 与 retention 必须使用不同 fresh coverage data，两个 Gate 都要 `passed=true`，且旧 `CRITICAL_TARGET_UNCOVERED` attempts 原样保留。
3. 等待正在进行的 Linux wheelhouse 构建自然结束；不得重启相同构建或手改 manifest。成功后记录 target、input hashes、文件数、总大小与 manifest SHA-256。
4. 用新 Linux wheelhouse 在 `linux/amd64`、CPython 3.11.9、断网、repo/rootfs 只读、空 HOME/cache、fresh venv 环境执行 package required Gate，要求 0 skip/fail/error。
5. 以 exact nodeids 刷新 Linux S16/S17 security JUnit/provenance；必须实际覆盖 `renameat2`、`/proc/self/fd`、block/char device、flock、two publishers 与六个 SIGKILL checkpoint。
6. 最后一次 source/test/policy/manifest 稳定后，重建 canonical image 并重跑 13 required golden；随后执行 host full、Ruff、compileall、`git diff --check`、document links 与 Spec Inventory。
7. 生成新的 PASS/BLOCKED sealed evidence，并由独立 verifier 从原始 artifact 重算。只有第 17.7 节全部闭合后才能进入 W1b-5b 复审；W1b-5c/5d/5e 未授权，Release 保持 No-go。

恢复时先阅读本文件第 17 节，再查看 `docs/team-sessions/team-session-2026-09-06-6.md`。不要从聊天摘要反向覆盖本节；若代码或测试 hash 已变化，应创建新的事实检查点并保留本节为历史记录。

### 17.9 2026-09-06 当前可执行方案与测试规格

本节取代第 17.8 节作为当前恢复入口，但不删除或改写第 17.8 节。第 17.8 节、`/private/tmp/ai-auto-lrc-s18-gate-final-r1.wIzTuH/attempt-004` 以及所有更早 attempt 继续作为 historical evidence；它们不能证明本节列出的当前 source、test、manifest、runner 或 verifier 字节。

#### 17.9.1 当前字节和证据边界

下表只记录已经在本机重新核对的工作区字节或已经存在的 raw artifact。临时目录不是签署或长期发布制品；任何表内受约束文件变化后，相关绿色结果立即降级为 historical。

| 范围 | 当前事实 | Artifact / SHA-256 | 当前判定 |
|---|---|---|---|
| capture | fresh `282 passed`；line `1366/1499 = 91.1274%`，branch `537/634 = 84.7003%`，combined `89.2171%`；manifest 所列 capture critical 均为 100% | root `/private/tmp/ai-auto-lrc-s18-capture-fd-anchor-final.vzWWv7/`；source `ed911aec5113d6b78d88da3879aebf82df2a28af4b4b01a98b7ed1527d06118d`；test `e7eef7ff8a3d6f37cc5fa343e6fccd01cefac7b4695c564c3eff12bd439db583`；coverage `1882f2069927b2318571176881b28671feb06a926cbd44c4fe053cb764539663`；JUnit `7f2ea1bcf3c7b87c95a4d74768b84795689283a12cc83fa9b25660f82ab1e4cd` | raw coverage Go；当前macOS Gate 3/3见下；P0改动后须刷新 |
| retention | fresh `256 passed`、1 个 manifest 声明的 macOS Linux-device skip；line `1189/1251 = 95.0440%`，branch `367/410 = 89.5122%`，combined `93.6785%`；retention critical 均为 100% | root `/private/tmp/ai-auto-lrc-s18-retention-fd-coverage.RrzemZ/`；source `8504db0430cf40c23e2d794193aafcb0b0502c5cad08d5a4676adadf57338010`；test `55fc0003f320213ed886662b3c0dcb678c5b7e29fe308884749a2ea5aa195b09`；coverage `b5f6d6232f6597f32f8879378ec766534dacc4e975dd0808135dff8f66c77bb3`；JUnit `d82708f9d27f1664f5a38f83a9b130d360e1aadd8c00e4519a01fec50c5d5252` | raw coverage Go；当前macOS Gate 3/3见下；native测试后须刷新 |
| verifier 合同 | test SHA、跨 runner 同 nodeid、精确 platform exclusion 已实现；当前工作区定向实测 `47 passed` | verifier `afed11b4b39d907edac1058f1a9099f3ddb3b3ccf5d0962363bafbe76658fd6b`；runner `861fa2ada6f9fd79d19e77e3b17a76fc936210604a0d744e3e5b1dc1cf184255`；contract test `617ee25648d2cf2042bc6012c050dfddc8be64c93c95298484c1d8c0b2e61f56`；manifest `4285531e2ec9ce16d7fc65580447de6a0ab88f21758a552eaa90f555acc72b15` | schema 合同 Go；工具自身 hash 闭包和 per-runner semantic pair 待实现 |
| macOS security Gate | 当前相同 source/test/policy/manifest 字节连续三轮双 lane pass；capture每轮 `282 passed`、required `24/24`、critical `10/10`；retention每轮 `256 passed`、required `14/14`、critical `13/13`，唯一skip精确命中Linux-device exclusion | attempt roots：`/private/tmp/ai-auto-lrc-s18-security-stability-a1.g4q6yi/attempt-001`、`...-a2.QdOATC/attempt-002`、`...-a3.GhHcZY/attempt-003`；第三轮独立reverify与原Gate字节一致 | 当前字节3/3 Go；执行17.9.4任一P0改动后自动降级historical并重跑 |
| Linux wheelhouse | CPython 3.11.9、linux-x86_64；57 runtime wheels、2 build-system wheels、1 sdist，共 62 文件、343732866 bytes | root `/private/tmp/ai-auto-lrc-wheelhouse-linux-s18.MZWVHy/linux-x86_64-py311/`；manifest `362db2af2e6db6cdc98fc56c67e4ee8371ca9101a4c581122c5c8b139d3c9130` | 输入冻结完成；不得重建覆盖 |
| Linux package | 断网、只读 rootfs、fresh venv、installed origin、`pip check` 和 CLI 通过；`34 passed`、4 deselected、0 skip/fail，Gate `passed=true` | root `/private/tmp/ai-auto-lrc-s18-package-linux-final.glaKpX/`；JUnit `29a5fd7841f887241290daf9514b992d169f68310831f0954ca7f1145c7fc665`；Gate `e1b9da7a0c8ff4ffaa5764178b3559b9ab3b72645457aebaf4e1e255497cba7e` | Linux package lane Go；不能替代 security/canonical |
| Linux security runner | 首轮执行完测试后因 image 无 `git`，environment provenance 抛 `FileNotFoundError`；两个 lane 都未获得有效 Gate。v2 image 已加入 Git 并完成构建 | RED `/private/tmp/ai-auto-lrc-s18-linux-security-final.v9taqE/attempt-001/`；v2 image `sha256:8e6455f621dcd14edf292c7ce9276398dfadddabbc37a35cd74799e7304f2e30`；Dockerfile `430766091029691a91fb431ca2184d5e8a2ba33ce60ce89b8e0430c850e179ba`；image `linux/amd64` | attempt-001 永久保留；v2 attempt 尚未运行 |

当前 checked-in 受约束源文件的 SHA-256 是 capture `ed911a…`, capture test `e7eef7…`, retention `8504db…`, retention test `55fc00…`。生成新 Gate 前必须再次从完整字节重算，不能仅比较上述缩写或 Git 状态。

三轮 macOS Gate 的完整hash索引如下；不同attempt的JUnit、coverage、environment、command和run-manifest包含不同run ID，因此hash不同是预期行为，稳定性判断依据是同一输入字节、相同计数/覆盖率和各自可重算的Gate，而不是强求artifact字节相同。

| Attempt | Capture gate | Retention gate | Independent reverify |
|---|---|---|---|
| 001 | `264957a33a360669138bd7085ce2c0f395d98327ac71e551524d2fd3f680c29e` | `c93d44131b4adb8b0b521043f86077d662c5e2604e9cb0e1b0e9d774894ee7dc` | 未单独生成；原始bundle保留 |
| 002 | `62917cb423099ed8e4e893ee4ee9942366a1fde4bbac0b8a9f6cc02fa2f34347` | `a1aa35f8e2b3ddf88316cc6bd5e5c3ab937112b4b118f37c513cfcb01dd7f186` | 未单独生成；原始bundle保留 |
| 003 | `6a266c96aec64ca735efb4481fa77f4f8d564a9ef5b0cf8b6ee9d9d10fbd63e9` | `f89bb85395f7d1151832ec7cab2cf34db2f0cfd14630aa2ee636b2605f40eebd` | capture/retention输出分别与对应原Gate完全相同 |

#### 17.9.2 Teams 架构裁决

1. **Evidence closure 扩展为工具闭包。** `run_security_coverage.sh`、`verify_security_coverage.py` 和 pytest 配置的 SHA-256 必须进入 environment、run manifest 和 Gate 的 exact-key schema；任一工具或配置字节改变，旧 bundle 以 `EVIDENCE_TOOLCHAIN_BINDING_INVALID` 失效。该裁决为 P0，尚未实现，实施时先用 `S18-TOOL-001/002` 取得 RED。
2. **语义成对规则按 required runner 执行。** 一个 capability 若声明 macOS 和 Linux required，则每个 runner 必须各自至少有一个 `success` 和一个 `fail_closed` requirement。当前 verifier 只在 capability target 总体检查语义集合；升级前不能声称 per-runner 已满足。实施时先用 `S18-COV-018` 取得 `MANIFEST_RUNNER_SEMANTICS_INCOMPLETE` RED，再调整 parser；历史 schema-1 bundle 不回写。
3. **文档声明和 manifest runner 必须一致。** CAP-01、CAP-09、CAP-17 当前文档要求 macOS + Linux，但 manifest 主要只有 macOS required。选择补 Linux exact nodeids，不收窄安全声明；未补齐前这三项保持 Blocked。
4. **真实 no-replace ABI 必须同时证明成功和碰撞。** 新测试不能 monkeypatch `ctypes.CDLL`、`sys.platform` 或 rename seam；macOS 必须实际走 `renameatx_np`，Linux 必须实际走 `renameat2(RENAME_NOREPLACE)`。同一 exact nodeid 可以在两个 runner 分别登记，不能用一个平台结果代签另一个平台。
5. **运行期间 test drift 必须 fail closed。** runner 需在 pytest 前后分别 hash target test 文件；不同则保留 raw artifact 并返回 `EVIDENCE_BINDING_INVALID`。现有生产逻辑已计算 before/after hash，但缺直接 runner integration 合同。
6. **一次只推进一个可回滚切片。** Gate schema、capture、retention、package、canonical 和文档是不同 rollback unit。任何切片失败都创建新 attempt 并停在本波，不撤销其他已验证工作区成果。

#### 17.9.3 17 项能力的当前执行合同

`已有` 仅表示存在当前 raw 或合同证据，不等于 S18 已签署。`Blocked` 表示缺失下表列出的 required evidence；`Planned` 表示尚未运行，不能推断结果。

| ID | 不变量和可观察结果 | 当前已有证据 | 缺口与下一 exact test | Required runner / 完成判据 |
|---|---|---|---|---|
| CAP-01 sealed run fd 读取 | 从逐组件验证的绝对 anchor 打开 pinned run fd；所有 child `open -> fstat` 失败都关闭 fd；caller fd 保持有效；不回退到可变路径 | `_open_directory_anchor`、`_open_parent`、`_walk_receipt_closure` 已 harden，capture critical 100% | `S18-CAP-LNX-001`：Linux pinned-fd success + parent swap/special node fail closed；加入 Linux success/fail pair | macOS + Linux；两平台 exact nodeids 0 skip/fail，closure/hash/identity 稳定 |
| CAP-02 外部稳定文件读取 | 只接受 owner/mode/nlink/size/identity/digest 稳定的 regular file；短读、swap、超限拒绝 | `_read_stable_regular`、`_verify_record` critical 100%，macOS success/fail required 已有 | 当前无新增代码缺口；在最终 bytes 上重新绑定 source/test/JUnit/coverage hash | macOS；统一 Gate pass |
| CAP-03 current-source 观察 | 两次有界观察相等才接受，仍只声明 diagnostic；未知 key 或 checkout drift 拒绝 | manifest 已含 macOS pair 和 Linux `/proc/self/fd`、drift、exact-key/limit nodes | v2 Linux security attempt 执行全部 5 个 Linux required nodes并保存 provenance | macOS + Linux；Linux 5/5 collected/passed、0 skip |
| CAP-04 capture 隔离发布 | repo 外 retention、exclusive staging、目标不存在才 seal；symlink parent/已存在目标不覆盖 | `_seal_run` critical 100%，并发 capture 和 repo-inside 反证已有 | 最终三轮 macOS Gate 后确认无 flaky，保留目标碰撞 artifact | macOS；三轮同源 Gate pass |
| CAP-05 子进程和信号 | 保留 raw/normalized/signal；SIGTERM 转发；finalizer 不能掩盖原 gate 结果 | `_normalize_returncode` critical 100%，signal/exit required 已有 | 最终 runner 复核 command 与 JUnit test hash | macOS；success/fail pair 通过且 receipt return code 可重算 |
| CAP-06 portable binding | coverage/JUnit/policy/base ref/run ID 同源；deterministic reasons | required pair 已有，全文件门槛已过 | 后续 R3 才拆 immutable facts/reducer；本轮只重跑 Gate，不混入结构重构 | macOS；当前 facade 行为不变，Gate pass |
| CAP-07 package closure | wheelhouse、build/install、CLI sidecar、JUnit、policy、run ID 和 artifact closure 一致 | macOS package 37-pass 历史 lane；Linux package 34-pass 当前 lane | 最终 source/test 稳定后刷新 macOS package；若 capture parser 变化，两平台都重新绑定 | package macOS + Linux；各自 0 skip/fail，不能互相替代 |
| CAP-08 canonical closure | container、安装 origin、formal input、oracle、scope、network/rootfs、artifact closure 同源 | 早期 canonical 13/13 functional evidence | 当前 source 最终稳定后重建 image；不得复用旧 digest | canonical Linux；13/13、0 skip/fail，image/source/JUnit/Gate hash 可重算 |
| CAP-09 receipt finalize/verify | sealed marker、formal closure、reason/qualification、source/layer binding从原始 bytes 重算；父路径 swap仍绑住 opened fd | `verify_receipt_at` critical 100%，macOS pair 已有 | `S18-CAP-LNX-009`：Linux current/archived success + tamper/parent swap fail；登记 Linux pair | macOS + Linux；每平台 pair 和稳定 reason 均通过 |
| CAP-10 retention config trust | checked-in rules/assessment bytes绑定外部 expected digest；hardlink/FIFO/socket/device/wrong owner/宽 mode拒绝 | `_stable_bytes`、`load_secret_rules`、`load_retention_assessment` critical 100%；Linux device node已入 required | v2 Linux attempt执行 device节点；不得把 macOS exclusion算 pass | macOS + Linux device；macOS仅精确 exclusion，Linux 0 skip/fail |
| CAP-11 有界 closure/扫描 | exact cap 成功，cap+1在继续物化前拒绝；run-wide entries/files/bytes/hits/metadata预算与 root identity稳定 | `_tree_snapshot`、`_walk_retention_tree`、`_scan_file/_scan_tree/_window_hits` critical 100% | native no-replace测试加入后重新生成 retention full coverage，确认无意外下降 | macOS；critical 100%、文件三项指标均 >=80% |
| CAP-12 no-replace 发布 | 第一次 absent-target 原子提交；第二次碰撞绝不替换，source/target inode、bytes、hash保持；event可见后故障为 commit uncertain | unsupported、existing-target、publish/identity seams已有；Linux只有 fail-closed required | `test_ret_s18_native_rename_noreplace_commits_once_and_preserves_existing_target`：不 mock ABI；同一 nodeid分别登记 macOS/Linux success | macOS renameatx_np + Linux renameat2；每平台 success/fail pair、0 skip |
| CAP-13 锁与并发 | pinned namespace 上 flock；两个独立 publisher 最多一个 committer；loser只允许稳定状态且零替换写 | macOS S16 与 manifest Linux lock/two-publisher required 已有 | v2 Linux attempt执行 lock、namespace swap、两类 publisher exact nodes | macOS + Linux；所需节点全 collected/passed，最多一个 commit |
| CAP-14 crash 与 ledger | 六个 SIGKILL checkpoint分类稳定；verify只读；gap/duplicate/坏 transition/重哈希无效 event拒绝 | macOS全矩阵已完成；manifest已扩 Linux 六 checkpoint | v2 Linux attempt执行12个 retention required集合中的六 checkpoint及ledger反证 | macOS + Linux；两次 fresh classifier一致、verify零写入 |
| CAP-15 CLI 脱敏 | stdout/stderr 单一规范通道；secret、HOME、控制字符、traceback不泄漏 | macOS真实CLI nodes和 noncritical facade mapping已有 | host full 与最终 static后复核，不以函数100%替代E2E | macOS；success/fail required通过且日志无敏感值 |
| CAP-16 qualification provenance | producer只生成raw；verifier重算 source/test/policy/manifest/coverage/JUnit/environment/command/run ID；attempt独占 | test SHA 与精确 exclusion已实现，47 contract tests通过 | `S18-TOOL-001/002`、`S18-COV-015/016/017/018`；工具/pytest-config hash闭包与per-runner pair仍Blocked | 全部 runner；所有输入hash闭合、旧bundle对任一漂移fail closed |
| CAP-17 capture closure预算 | entries/metadata/bytes exact cap成功，cap+1在继续物化前稳定拒绝 | `_walk_receipt_closure` critical 100%，macOS预算合同已有 | `S18-CAP-LNX-017`：Linux exact-cap + cap+1；登记Linux pair | macOS + Linux；每平台pair通过，0 skip/fail |

#### 17.9.4 P0 测试规格

以下测试先 RED 后最小实现；owner 尚未由用户指定，统一记录角色而不虚构个人签署。每个测试的 RED、fixture错误、GREEN和最终 Gate必须保存在不同或可追溯的 attempt 中。

| Test ID / exact nodeid | Runner | Fixture / fault seam | Oracle | Owner | 回滚单元 | 状态 |
|---|---|---|---|---|---|---|
| S18-RET-REN-001 `tests/contract/test_evidence_retention.py::test_ret_s18_native_rename_noreplace_commits_once_and_preserves_existing_target` | macOS + Linux | 同目录创建两个不同 source；第一次 target absent，第二次 target exists；不 mock `ctypes.CDLL`、`sys.platform` 或 rename seam | 第一次 source 消失且 target inode/content/hash等于第一 source；第二次抛 `FileExistsError`，target与第二 source inode/content/hash均不变 | Retention developer + Linux runner owner | retention test + CAP-12 manifest mapping | Planned / P0 |
| S18-COV-015 `test_s18_runner_rejects_target_test_drift_during_pytest` | host/macOS | 受控 fake pytest 在运行期间修改 target test bytes | runner保留raw并以 `EVIDENCE_BINDING_INVALID`失败；before/after hash不同可见 | Gate developer | runner + contract test | Planned / P0 |
| S18-COV-016 `test_s18_gate_rejects_second_test_path_in_command_scope` | host | command argv追加第二个 `tests/...` 路径并重算 command hash | verifier返回 `COMMAND_SCOPE_INVALID` | Gate developer | verifier + contract test | Planned / P0 |
| S18-COV-017 `test_s18_manifest_rejects_same_runner_duplicate_nodeid` | host | 同 runner复制 nodeid；对照相同nodeid用于不同runner | same-runner schema fail；cross-runner通过 | Gate developer | verifier parser + contract test | Partially Green；需显式合同 |
| S18-COV-018 `test_s18_manifest_requires_semantic_pair_per_required_runner` | host | 某capability的Linux requirement只有success或只有fail_closed | manifest parser fail closed；不能借macOS补齐Linux语义 | Architect + Gate developer | manifest schema/parser/test | Planned / P0 |
| S18-TOOL-001 `test_s18_bundle_binds_runner_and_verifier_bytes` | host | 生成bundle后分别改变runner或verifier bytes | 旧bundle `EVIDENCE_TOOLCHAIN_BINDING_INVALID`，不复用Gate | Architect + Gate developer | evidence schema v2 + runner/verifier/test | Decision accepted，implementation pending |
| S18-TOOL-002 `test_s18_gate_rejects_runner_or_config_hash_drift` | host | 生成bundle后改变runner或pytest配置，其他artifact和自报hash保持绿色 | `EVIDENCE_TOOLCHAIN_BINDING_INVALID`；原bundle只读保留 | Architect + Gate developer | evidence schema v2 + runner/config/verifier test | Planned / P0 |
| S18-CAP-LNX-001 | Linux | 真实 `/proc/self/fd` pinned run读取；parent swap/special node | exact closure成功；不安全节点稳定拒绝且fd无泄漏 | Capture developer + Linux runner owner | capture test + CAP-01 manifest | Planned / P0 |
| S18-CAP-LNX-009 | Linux | current/archived receipt成功；tamper与parent swap | qualification/reason重算稳定；不从可变path重开 | Capture developer + Linux runner owner | capture test + CAP-09 manifest | Planned / P0 |
| S18-CAP-LNX-017 | Linux | entries/metadata/bytes exact cap与cap+1 | cap内完成；cap+1在继续物化前fail closed | Capture developer + Linux runner owner | capture test + CAP-17 manifest | Planned / P0 |

测试实现统一遵循以下结构：Arrange 必须创建真实文件系统状态；Act 从 public API 或 CLI进入，只有不可稳定制造的 race 才替换私有 fault seam；Assert 同时检查错误码、落盘状态、inode/bytes/hash、fd ownership和敏感输出。仅断言函数被调用或只提高行覆盖率不构成 CAP 验收。

P1 hardening 在P0闭合后执行，不得阻塞保存当前P0 RED，也不得把尚未实现的强保证写入qualification声明：

| Test ID / exact nodeid | 风险与输入 | Oracle / 声明边界 | 状态 |
|---|---|---|---|
| S18-SRC-001 `test_s18_manifest_symbol_and_hash_use_same_frozen_source_bytes` | `_source_symbols()` 与后续bounded read看到不同source bytes | symbol解析和hash必须来自同一冻结bytes；否则 `EVIDENCE_BINDING_INVALID` | Planned / P1 |
| S18-JUNIT-001 `test_s18_gate_rejects_forged_junit_classname` | 伪造classname使拼接nodeid看似required | `JUNIT_NODEID_INVALID` | Planned / P1 |
| S18-JUNIT-002 `test_s18_gate_rejects_noncanonical_junit_name` | 参数化name含非canonical或歧义表示 | `JUNIT_NODEID_INVALID`，不做宽松归一化 | Planned / P1 |
| S18-XFAIL-001 `test_s18_runner_enforces_strict_xfail_semantics` | required测试意外XPASS/XFAIL或pytest strict配置漂移 | runner非零；分别为 `REQUIRED_TEST_XFAILED` 或 `RUNNER_CONFIGURATION_INVALID` | Planned / P1 |
| S18-ABA-001 `test_s18_runner_does_not_claim_aba_safe_without_immutable_snapshot` | pytest期间test bytes替换后恢复，before/after hash相同 | 当前方案不得宣称ABA-safe；若未来采用不可变snapshot，先取得 `EVIDENCE_EXECUTION_SNAPSHOT_UNPROVEN` RED | Boundary test / P1 |

#### 17.9.5 可执行波次和命令顺序

```text
R0.2 evidence schema hardening
  -> S18-TOOL-001/002 RED
  -> S18-COV-015/016/017/018 RED
  -> runner/verifier hash closure + per-required-runner semantic pair
  -> verifier contracts GREEN + Spec Inventory

R1.2 platform capability closure
  -> S18-RET-REN-001 RED/GREEN on native macOS
  -> CAP-01/09/17 Linux exact tests RED/GREEN
  -> manifest exact nodeids updated
  -> capture and retention fresh coverage regenerated

R6.1 qualification refresh
  -> macOS security Gate attempt-001/002/003 on identical bytes
  -> Linux security v2 new attempt, required capture 5/5 and retention 12/12, 0 skip/fail
  -> final macOS package refresh
  -> final canonical image and 13 required golden
  -> host full + Ruff + compileall + bash -n + diff/link/Spec Inventory
  -> new PASS/BLOCKED sealed evidence
  -> independent raw-artifact recomputation
  -> Teams W1b-5b review
```

Linux security v2 必须创建 `attempt-002` 或更高的新目录，不得覆盖 `attempt-001`。标准边界为 `--platform linux/amd64`、`--network none`、`--read-only`、独立 tmpfs HOME/cache、repo只读挂载和evidence只写挂载；保存 image ID、Dockerfile hash、base image digest、daemon arch、container `uname`、Python/pytest/coverage/Git版本、完整argv和退出码。

每个波次的最小命令集合是：targeted pytest → 单脚本 fresh branch coverage → verifier contracts → security runner → `ruff check` → `compileall` → `bash -n` → `git diff --check` → 文档链接与 Spec Inventory。`ruff format --check` 对 retention 大文件的历史失败位于 `/private/tmp/ai-auto-lrc-s18-retention-fd-format-check.Lmcc3L/`；本批不做整文件格式化，避免把上千行机械差异混入安全切片。

#### 17.9.6 证据、停止和回滚规则

- source、target test、policy、manifest、runner、verifier任一字节变化，所有更早统一 Gate降级为 historical；package/canonical是否需重跑按其实际闭包判断，但最终qualification必须晚于最后源码变化。
- pytest配置与runner/verifier同属toolchain bytes；未实现不可变执行snapshot前，test before/after hash只能证明端点一致，不能声称排除执行期替换后恢复的ABA。
- required nodeid未收集、deselected、skip、xfail、failure或error立即停止当前runner；macOS唯一允许的platform exclusion必须精确等于 `test_ret_s18_linux_block_and_char_devices_fail_before_control_write` 和 reason `requires Linux mknod device semantics`。
- 首次RED、fixture/runner错误、flaky、retry与旧attempt不得删除。当前明确保留：Linux package首次错误收集macOS-only cold-install测试的RED；Linux security `attempt-001`缺Git；旧security `attempt-004`无test-hash schema。
- 回滚只撤销当前切片引入的生产/测试/manifest改动，不使用 `reset`、`checkout`、`clean` 或广泛删除，不触碰仓库根来源不明空文件 `./=`，也不恢复用户已删除的v1文件。
- 任何需要commit、push、CI、上传、签名、发布、archive、restore、delete或destruction的步骤立即停止并请求新授权；W1b-5c/5d/5e和Release始终不由S18自动开放。

#### 17.9.7 本节完成判据

- [ ] `S18-TOOL-001/002` 与 `S18-COV-015..018` 先RED后GREEN，runner/verifier/pytest-config/test bytes全部进入evidence闭包。
- [ ] CAP-01、CAP-09、CAP-17的Linux success/fail pairs和CAP-12两平台native success/fail pairs进入manifest。
- [ ] 当前最终字节下capture/retention fresh coverage各自单source，三项指标 >=80%，所有critical line/branch 100%。
- [ ] 最终字节下macOS security连续三轮双lane pass、输入hash一致且每个attempt独立reverify与原Gate字节一致；Linux capture 5/5、retention 12/12，0 skip/fail/error。
- [ ] macOS/Linux package、canonical 13 golden、host full和全部static/doc/inventory检查晚于最后相关字节变化。
- [ ] 最新PASS/BLOCKED sealed evidence由Evidence reviewer从raw artifacts独立重算，producer与reviewer逻辑步骤分离。
- [ ] Teams只在上述全部闭合后复审W1b-5b；W1b-5c/5d/5e仍未授权，Release继续No-go。

恢复时直接从本节 17.9.5 的第一个未勾选步骤开始。不得从聊天记录推断新状态；新事实只能append为第 17.10 节或更高，并保留本节的hash、RED和未完成项。

### 17.10 2026-09-07 当前事实、Teams 裁决与剩余执行方案

本节取代 17.9 作为当前唯一详细恢复入口；17.9 及更早的字节、RED、fixture/runner error、flaky、retry、skip 和 attempt 继续作为 historical evidence，不删除、不覆盖。本节的结论来自 PM、Architect、Developer、QA 四视角复核：当前字节下的 macOS/Linux Security Gate 已形成可重算的 schema v2 checkpoint，但 `S18-COV-015` 真实 runner integration、P1 决策与实施、package/canonical/host 最终刷新和 sealed evidence 独立复核尚未闭合。因此 S18、W1b-5b 和 Release 仍为 **No-go**；W1b-5c/5d/5e 未授权。

Teams 讨论摘要保存在 [`team-sessions/team-session-2026-09-07.md`](./team-sessions/team-session-2026-09-07.md)；下述方案和状态表才是执行事实源。

#### 17.10.1 当前受约束字节锚点

| 输入 | 本地路径 | SHA-256 |
|---|---|---|
| capture source | `scripts/capture_test_gate.py` | `ed911aec5113d6b78d88da3879aebf82df2a28af4b4b01a98b7ed1527d06118d` |
| capture test | `tests/contract/test_evidence_capture.py` | `e7eef7ff8a3d6f37cc5fa343e6fccd01cefac7b4695c564c3eff12bd439db583` |
| retention source | `scripts/manage_evidence_retention.py` | `8504db0430cf40c23e2d794193aafcb0b0502c5cad08d5a4676adadf57338010` |
| retention test | `tests/contract/test_evidence_retention.py` | `150f7d6ce7408f0881a1fad29ad44d511cad24d710c6de7fea3532bcc322d375` |
| verifier | `scripts/verify_security_coverage.py` | `74b60290260525a7726538bd63c09bf0c991ff1579a57ac2b9792c9889fb978f` |
| runner | `scripts/run_security_coverage.sh` | `743a033a6c5828a0de469716a7a499c3cd68ae6f3364b4bf1739f8e09c55c218` |
| verifier contract test | `tests/contract/test_security_coverage_gate.py` | `0c67c053c6ef492f582d921d44a42b95e69956a37526542ba0d60dd65b245ab6` |
| manifest | `packaging/security-coverage-manifest.json` | `890a5267c17f7b5d38c61f936624364958883af557da369d355beda94a3085eb` |
| policy | `packaging/security-coverage-policy.toml` | `53fea4add3f2b498eb1f5f14705e16cab76055794e2d69751700d79d7ed3c5c0` |
| pytest config | `pyproject.toml` | `261e426e194d46308cdb1ca3117bb4015693691cd0704cfd071d1476240fed19` |

上述是 2026-09-07 从完整本地字节重算的值，与下述六个 macOS lane 及 Linux `attempt-003` 中的 environment before/after、run-manifest、Gate 和 independent reverify 一致。任一受约束字节变化后，必须按 17.10.7 的失效矩阵判定重跑范围，不得继续称旧 artifact 为 current。

#### 17.10.2 已完成并验证的能力切片

1. **R0.2 toolchain evidence schema 已实现。** environment、run-manifest、Gate 为 schema v2；command 和 runner-error 保持 schema v1。runner、verifier、pytest config 的 before/after SHA-256 已进入 environment、run-manifest 和 Gate；工具或配置漂移使用 `EVIDENCE_TOOLCHAIN_BINDING_INVALID`。旧 environment/run-manifest schema v1 fail closed。
2. **per-required-runner 语义成对已实现。** 每个 capability/target 中的每个 required runner 都必须独立具备 `success` 与 `fail_closed`；缺失时为 `MANIFEST_RUNNER_SEMANTICS_INCOMPLETE`。same-runner duplicate nodeid 拒绝，cross-runner 相同 nodeid 允许；command 出现第二 test path 以 `COMMAND_SCOPE_INVALID` 拒绝。
3. **R0.2 合同回归已通过。** RED 保存于 `/private/tmp/ai-auto-lrc-s18-r02-gate-red.tBl3Ix` 和 `/private/tmp/ai-auto-lrc-s18-r02-schema-v2-red.ST331U`；最终 `60 passed`，artifact 为 `/private/tmp/ai-auto-lrc-s18-r02-gate-v2-full.I6Bhn0`。该结果证明 verifier 合同实现，不单独冒充 target-input 最终 Gate。
4. **R1.2 platform capability closure 已实现。** CAP-01、CAP-09、CAP-17 已登记 Linux exact-node success/fail pairs；CAP-10 的 Linux success 与 device fail-closed 已成对；CAP-12 同一 native nodeid 在 macOS 真实调用 `renameatx_np`、在 Linux 真实调用 `renameat2(RENAME_NOREPLACE)`，并证明首次原子提交与第二次碰撞不覆盖。不支持的平台/ABI 仍硬失败，不新增宽泛 exclusion。
5. **当前字节 Security Gate 已在两平台通过。** macOS 三轮和 Linux `attempt-003` 都已由 verifier 从 raw artifact 重算；producer 输出与对应 independent reverify JSON 逐字节一致。这只证明 current security checkpoint，不等于 package、canonical、host full、W1b-5b 或 Release 完成。

#### 17.10.3 macOS 三轮稳定性证据

证据根为 `/private/tmp/ai-auto-lrc-s18-final-macos-stability.1ofdbv`。三轮 capture 均为 `282/282 passed`、required `24/24`、0 skip/fail/error，line `91.12741827885257%`、branch `84.70031545741325%`、combined `89.21706516643225%`；三轮 retention 均为 `257 passed + 1` 个精确声明的 macOS Linux-device exclusion、required `15/15`、0 fail/error，line `95.04396482813749%`、branch `89.51219512195122%`、combined `93.67850692354004%`。六个 lane 的 source/test/policy/manifest/runner/verifier/pytest-config 输入完全一致，各自 independent reverify 与原 Gate 逐字节相同。

| Attempt | Lane | Gate SHA-256 | JUnit SHA-256 | Coverage SHA-256 |
|---|---|---|---|---|
| 001 | capture | `332a02ebd7993f35132f752f7846f964cec834de6cff53c957e2809c3f7cbb2a` | `1028d764e3dbe11163903438de4ec2ef5dfcdf9ca8ee390844385d27cbcda79c` | `fbdc7e4683c46f64309a270e08078f6e9d71092ccc2dc79a9f4b5d741853ba0f` |
| 001 | retention | `55549266ac44e57b8637a94996ead923c6eb2ed412cbec427b6861645088f08c` | `7ec73c1b8dbbfa597163975f54430d942c746c01eb3430a1f8679c292a10cc81` | `7cda7f088504744ab681ce553cefd5e125cbe44b41f8619454260ce31b93fe7a` |
| 002 | capture | `d7fde989df06ca4a5fd6c2eea47a47b509f70cad4d29dcbc7b7207604fc04639` | `f752cbcb3987dd4c7c2bcf374042f34bcb3b6716be27a0ab1ef709e27e053abf` | `5691fae5f372729c721a45bee6a7b95aa31d02f7fc5fcac67d10424e1e457658` |
| 002 | retention | `104d776593bd04afa13d8683f3644892779bcdbf8f64a0b87dc99978fe8ee3c8` | `db39c5849667bac2aff6c1532135b1f1aa5167271e0c3888e73e365d74d08f14` | `3fe19289fc63927e87bed0c448ddce4778a9d1b311f8e1f3e4456b258856257c` |
| 003 | capture | `f9311481c70fb85e9d4b2ca7c42c62d8cbd01994c6aaaa9b7e0210b0af86258c` | `6516085db53c46ea5d7766fecb7badf6615a763b94ec3ec23a28ceedc0ad0b08` | `36a227eb1f839828e16ddbc5268606d89530900a2e19f2730c9d8f669d6d6a43` |
| 003 | retention | `5183b254b246b83c2b6e292d2a8a6b77effe864ab008c31c062130ffb8621c89` | `18e246ebbbf11f6e594f335c41ed00dbf175a82bf0486eebd76f2aa2ad8692b7` | `f4d6220fdd199716d8efef73e1c8486f3417affbb5e624706deecbe2ed8619c1` |

JUnit、coverage 和 Gate 包含 run ID、attempt 或时间信息，因此不同轮的 artifact SHA 不同是预期行为；稳定性判定依据是受约束输入相同、语义结果和覆盖率相同、每轮 Gate 均可从当轮 raw artifact 独立重算，而非强求不同轮产物字节一致。

#### 17.10.4 Linux Security Gate 与失败历史

最终 current 证据根为 `/private/tmp/ai-auto-lrc-s18-linux-security-final.v9taqE/attempt-003`，边界为 linux/amd64、CPython 3.11.9、`--network none`、只读 rootfs/repository、独立 tmpfs HOME/cache；image 为 `sha256:8e6455f621dcd14edf292c7ce9276398dfadddabbc37a35cd74799e7304f2e30`，Dockerfile SHA-256 为 `430766091029691a91fb431ca2184d5e8a2ba33ce60ce89b8e0430c850e179ba`。

| Lane | 结果 | Gate SHA-256 | JUnit SHA-256 | Coverage SHA-256 |
|---|---|---|---|---|
| capture | `282/282 passed`，required `16/16`，0 skip/fail/error，combined `88.60759493670886%`，line `90.393595730487%`，branch `84.38485804416403%` | `19c45d7920be0a01947986c278da5da7e95ceb65691574d70d3ad421d8ef8394` | `4f8fc0c661764b287da568659794e852205e6ace2a5e404a0e3ea36f13f675f8` | `8f8a8d4bc9cbd7958e74b2321237e59c74cce3847b57bdf19a1426321a6a67bc` |
| retention | `258/258 passed`，required `14/14`，0 skip/fail/error，combined `93.67850692354004%`，line `95.04396482813749%`，branch `89.51219512195122%` | `a4213216cbbd257e1f85c81bf6617d6c357f5c0e19a1b1e24e5d449dbfe67080` | `887b77522409b30cb0d7b8401a278b4ef4eb916c0167dcef39a255b523df04bf` | `dab37dfbbda225d3f82cf034970042574b4d0b17f6c2b686e262546c910108eb` |

- `attempt-001`：测试已运行，但 image 缺 Git，environment provenance 失败，两个 lane 都无有有效 Gate。
- `attempt-002`：capture 通过；retention 暴露 fake `NativeLibrary` 只提供 `renameatx_np` 的 Linux fixture 缺陷，保留 `COMMAND_FAILED` / `CRITICAL_TARGET_UNCOVERED` / `JUNIT_CONTAINS_FAILURE`。最小修正是为该测试 fake 增加 `renameat2 = renameatx_np`，未修改生产代码。
- `attempt-003`：双 lane 通过，两个 independent reverify 与对应 Gate 逐字节相同。

Linux exact-node 预检证据位于 `/private/tmp/ai-auto-lrc-r12-capture-linux-final.nmOSWF/junit.xml`，`11 passed`、0 skip/fail/error，JUnit SHA-256 `fd6c04ce7a1c9a5888855eb55faa14d0e4edd2986af1c465e4d9cf1492a12dea`。它用于能力映射复核，不替代统一 Linux Security Gate。

#### 17.10.5 17.9 历史化勘误与 P0 状态

- 17.9.1 retention 的 `256 passed`、test hash `55fc00…` 已被当前 `257 passed + 1 exclusion`、test hash `150f7d…` 取代。
- 17.9.1 verifier `47 passed`、旧 verifier/runner/contract/manifest hash、“toolchain closure/per-runner pair 待实现”和旧 macOS 三轮 Gate 表均已历史化。
- 17.9.1 “Linux v2 attempt 尚未运行”已历史化；current 为 `attempt-003`。
- 17.9.2 第 1–4 项裁决已实现；第 5 项只完成生产 before/after hash 和 verifier 直接拒绝合同，真实 runner drift integration 仍缺。
- 17.9.3 中 CAP-01/03/09/10/12/13/14/17 的平台 Gate 缺口已由 current macOS/Linux artifact 闭合；CAP-16 仍受 `S18-COV-015` 阻断。
- 17.9.5 的 Linux `capture 5/5、retention 12/12` 是旧 manifest 计数；current 为 `16/16` 和 `14/14`。
- 17.9.6 exclusion nodeid 中的 `test_ret_s18_linux_...` 是旧笔误；current 精确 nodeid 为 `tests/contract/test_evidence_retention.py::test_ret_s17_linux_block_and_char_devices_fail_before_control_write`，reason 仍为 `requires Linux mknod device semantics`。

| P0 Test | 当前状态 | 可声称边界 |
|---|---|---|
| `S18-TOOL-001/002` | Implemented + Verified | runner/verifier/pytest-config hash 闭包与漂移拒绝已有直接合同 |
| `S18-COV-016` | Implemented + Verified | 第二 test path 被 `COMMAND_SCOPE_INVALID` 拒绝 |
| `S18-COV-017` | Implemented + Verified | same-runner duplicate 拒绝，cross-runner 复用允许 |
| `S18-COV-018` | Implemented + Verified | 每 required runner 的 success/fail-closed pair 强制校验 |
| `S18-RET-REN-001` | Implemented + Verified | 两平台真实 native no-replace 成功/碰撞已进 Gate |
| `S18-CAP-LNX-001/009/017` | Implemented + Verified | 既有跨平台 exact nodes 已经真实 Linux 运行并进 manifest |
| `S18-COV-015` | **Partial / P0 Blocked** | runner 已采集 test before/after hash，verifier 直接合同已拒绝漂移；但尚无“真实 runner + 受控 fake pytest 运行期改变 target test bytes”integration，不得标已完成 |

`S18-COV-015` 必须在隔离的临时仓库副本内执行，不增加生产测试开关，不修改当前工作区 target test。受控 fake `uv`/pytest 在 runner 取得 `test_before` 后修改副本中的 target test，同时生成最小合法 JUnit/coverage或执行副本的真 pytest；断言：源 raw artifact 保留、`test_sha256_before != test_sha256_after`、runner 非零、Gate failures 精确包含 `EVIDENCE_BINDING_INVALID`。首次 RED、fixture error 和 GREEN 分别写入新 exclusive attempt。

#### 17.10.6 P1 设计与可执行测试

P1 原计划五项和一项 supporting claim-boundary 回归都不能静默遗漏。Teams 复审时必须二选一：在本轮完成；或逐项移入具名后续工作包，写明 owner、风险接受者、截止条件和声明上限。未得到明确 accepted defer 时，默认纳入 S18/W1b-5b DoD。

| Test ID | 实现切片 | 测试 fixture / Oracle | 宣称边界 |
|---|---|---|---|
| `S18-SRC-001` | 将 source 有界读取抽成一次 frozen bytes；AST/symbol 解析和 `source_sha256` 都仅消费该 bytes，禁止 `_source_symbols(path)` 与后续 hash 二次打开路径 | fault seam 让第二次 path read 返回不同内容；实现后只许一次读取，symbol 集和 hash 必须来自同一 bytes，无法冻结时 `EVIDENCE_BINDING_INVALID` | 只证明 verifier 内单次冻结，不自动证明 pytest 执行期 snapshot |
| `S18-JUNIT-001` | 在 `_nodeid` 前引入 canonical classname grammar，仅允许 target test path 可逆映射的模块形式 | 伪造 dot/slash/`.py`/`..` 混淆 classname；不做宽松归一化，稳定返回 `JUNIT_NODEID_INVALID` | 只接受 verifier 声明的 canonical grammar |
| `S18-JUNIT-002` | 为 testcase `name` 定义可逆、无换行/控制字符/路径分隔符/重复分隔符的 pytest 名称语法 | 参数化 name 含歧义括号、`::`、控制字符或非 canonical 表示；全部 `JUNIT_NODEID_INVALID` | 不通过“修复”不可信 JUnit 名称来接受证据 |
| `S18-XFAIL-001` | runner 显式启用 pytest strict xfail 语义，并将所有影响 strictness 的 pytest config 继续纳入 hash 闭包 | required node 分别生成 XFAIL、XPASS(strict=false)、XPASS(strict=true) 和 config drift；期待 runner 非零，Gate 分别为 `REQUIRED_TEST_XFAILED` 或 `RUNNER_CONFIGURATION_INVALID` | verifier 已会拒绝 required xfail，但本项闭合 runner 与 config 约束 |
| `S18-ABA-001` | 保持声明收缩：在未引入不可变 execution snapshot 前，不把 before/after 相等称为 ABA-safe | 受控 runner 中 target test 先替换后恢复，使端点 hash 相同；当前必须保持 `EVIDENCE_EXECUTION_SNAPSHOT_UNPROVEN` 边界，若未来引入 immutable snapshot 则先取 RED | COV-015 完成也不代表 ABA-safe |
| `S18-P1-CLAIM-001` | 增加声明边界回归，锁定 current-source 仅为 sequential diagnostic observation | 尝试将 Gate/receipt 声明提升为 transaction snapshot、power-loss durability、完整 same-UID ABA 或 cross-UID proof 时必须失败 | 防止局部测试绿色被扩张为未证实能力 |

P1 完成顺序为 SRC 单次冻结 → JUnit canonical grammar → strict xfail/config → ABA/声明上限。每项都使用独立 RED/GREEN attempt 和独立回滚单元；禁止把五项合成一个不可定位的 verifier 大改。

#### 17.10.7 剩余执行 DAG 与失效矩阵

```text
A0 当前 17.10 字节和 raw artifact 锚定
  -> A1 COV-015 isolated runner integration RED/GREEN
  -> A2 P1 decision gate
       -> implement: SRC -> JUnit -> XFAIL -> ABA/claim boundary
       -> accepted defer: 逐项记录 owner、风险、声明上限和截止条件
  -> A3 current-byte verifier contracts + Spec Inventory
  -> A4 按失效矩阵刷新 capture/retention coverage 和 Security Gate
  -> A5 macOS package fresh qualification
  -> A6 复核 Linux package closure；相关输入漂移则新建 attempt 重跑
  -> A7 canonical image 重建 + 13/13 required golden + independent verify
  -> A8 host full + Ruff + compileall + bash -n + diff/link/inventory
  -> A9 生成最新 PASS/BLOCKED sealed evidence
  -> A10 Evidence reviewer 从 raw artifacts 独立重算
  -> A11 Teams 复审 W1b-5b
```

| 变化类型 | 必须失效/重跑 | 不得做的替代 |
|---|---|---|
| capture/retention source、对应 target test、policy、manifest、runner、verifier、pytest config 变化 | 受影响的 fresh coverage；macOS 三轮；Linux 新 Security attempt；每轮 independent reverify | 不得用本节 current Gate 或单节点回归替代 |
| package source/test/policy/runner/verifier 变化 | 对应平台 package attempt | 不得用 Security Gate 替代 package |
| canonical source/formal input/oracle/container recipe/image/verifier 变化 | 重建 image、13/13 required golden 和独立重算 | 不得复用旧 digest、package 或 host functional |
| 仅文档或不进入上述闭包的合同测试变化 | doc/link/inventory 与相关合同回归 | 不得无根据扩大重跑，也不得借此保留已失效证据 |

若 A1/P1 只增加不在证据闭包内的合同测试且受约束字节完全未变，可保留 current Security checkpoint；若修改 runner、verifier、manifest、policy、pytest config 或 target tests，本节六个 macOS lane 和 Linux `attempt-003` 立即历史化，必须在 A4 新建 exclusive attempts。

#### 17.10.8 停止、回滚与证据保留

- required node missing/deselected/skip/xfail/failure/error、critical line/branch 非 100%、全文件任一指标低于 80%、toolchain/test drift 或 independent reverify 不一致时，立即停止当前波次并新建 attempt。
- macOS 只允许 manifest 中精确 nodeid `tests/contract/test_evidence_retention.py::test_ret_s17_linux_block_and_char_devices_fail_before_control_write` 且 reason 精确为 `requires Linux mknod device semantics` 的一个 exclusion；Linux 必须 0 skip。
- 首次 RED、fixture error、runner error、flaky、retry、skip、`attempt-001/002`、旧 schema bundle 和 `/private/tmp/ai-auto-lrc-s18-r02-runner-v2.zn0GDi/attempt-001` 的 runtime-count flaky 全部保留。该 flaky 的单节点重跑证据为 `/private/tmp/ai-auto-lrc-s18-r02-capture-runtime-count-rerun.fSof1Y`，不得修改历史 attempt 的失败结论。
- 回滚单元依次为 COV-015 test、SRC、JUnit grammar、XFAIL/config、ABA/claim、package、canonical、docs；不得跨切片回滚已验证成果。R2–R5 大型函数结构重构仍与 qualification refresh 分离。
- 禁止 `reset`、`checkout`、`clean`、广泛删除；保留所有 modified/deleted/untracked 成果和仓库根来源不明空文件 `./=`。
- 本阶段不声称 power-loss/ancestor durability、`F_FULLFSYNC`、完整 same-UID ABA、真实 cross-UID、独立 checkpoint/source 恢复、Demucs、SBOM/attestation/signing/rollback 或 Release。macOS、Linux、package、canonical 证据不可互相代签。
- commit、push、CI、上传/同步、签名、发布、archive、restore、delete 或 destruction 均需新授权；W1b-5c/5d/5e 不因任何局部绿色自动开放。

#### 17.10.9 最终 DoD 与最短恢复路径

- [ ] `S18-COV-015` 真实 runner integration 已在隔离副本先 RED 后 GREEN，无生产测试开关，raw artifact 完整保留。
- [ ] P1 原计划五项及 supporting claim-boundary 回归均已实现验证，或逐项形成明确 accepted defer、具名 owner/风险接受者、声明上限和后续截止条件。
- [ ] 最终受约束字节下 verifier contracts、Spec Inventory、fresh coverage 和必要的 macOS/Linux Security Gate 均为 current。
- [ ] macOS package fresh qualification、Linux package closure、canonical 13/13、host full 以及 Ruff/compileall/bash-n/diff/link/inventory 检查都晚于最后相关字节变化。
- [ ] 最新 PASS/BLOCKED sealed evidence 已生成，Evidence reviewer 从 raw artifacts 逻辑独立重算且与 producer 结果一致。
- [ ] Teams 完成 W1b-5b 复审；即使 W1b-5b 后续转 Go，W1b-5c/5d/5e 仍需独立授权，Release 也不自动开放。

下一位接手者不要从 17.9 的首个未勾选项重来。最短路径是：重算 17.10.1 字节→从 17.10.7 的 A1 开始→在 A2 显式锁定 P1 选择→仅按失效矩阵刷新证据→完成 package/canonical/host/sealed review→Teams 复审 W1b-5b。不得从聊天记录推断新状态；新事实只能 append 为 17.11 或更高。

### 17.11 2026-09-07 P1 加固与最终资格化执行方案

本节取代 17.10 中“从 A1 开始”的恢复指令，成为当前详细执行入口；17.10 及以前的状态、hash、RED、fixture error、flaky、retry、skip 和 attempt 全部保留为 historical evidence。`S18-COV-015` 的真实 runner integration 已在隔离仓库副本完成，不再是 P0 阻断；其首次 RED 位于 `/private/tmp/ai-auto-lrc-s18-cov015-first.frbhUe`，GREEN 位于 `/private/tmp/ai-auto-lrc-s18-cov015-green.C5QuBK`，当时完整 verifier contracts 为 `/private/tmp/ai-auto-lrc-s18-cov015-full.NA9B0P`、`61 passed`。该结果只证明当时字节下的 COV-015 合同；后续 contract、verifier、runner 或配置变化后必须重新执行相关合同，不得继续把 `61 passed` 写成 current 全量结果。

本轮 Teams 角色讨论与分歧记录在 [`team-sessions/team-session-2026-09-07-2.md`](./team-sessions/team-session-2026-09-07-2.md)；本节仍是字段、测试、DAG、失效矩阵与恢复动作的唯一执行事实源。

本轮 Teams 选择**实施并验证 P1，而不是静默 defer**。执行顺序固定为 source frozen bytes → JUnit canonical grammar → strict xfail/config/events → ABA claim boundary。每一项是独立回滚单元，必须先有能在前一状态稳定失败的 RED，再做最小生产改动并取得 GREEN。若任一项需要后移，必须追加 owner、风险接受者、截止条件和最大声明；仅写“后续处理”不构成 accepted defer。

SRC/JUnit 切片已经完成：仅修改 `scripts/verify_security_coverage.py` 与 `tests/contract/test_security_coverage_gate.py`，新增 `test_s18_manifest_symbol_and_hash_use_same_frozen_source_bytes`、`test_s18_gate_rejects_forged_junit_classname`、`test_s18_gate_rejects_noncanonical_junit_name`。SRC RED/GREEN 分别为 `/private/tmp/ai-auto-lrc-s18-src001-red.XYqcft/junit.xml`、`/private/tmp/ai-auto-lrc-s18-src001-green.JXwyvg/junit.xml`；JUNIT-001 RED/GREEN 为 `/private/tmp/ai-auto-lrc-s18-junit001-red.bB1K9B/junit.xml`、`/private/tmp/ai-auto-lrc-s18-junit001-green.0CS2Bz/junit.xml`；JUNIT-002 RED/GREEN 为 `/private/tmp/ai-auto-lrc-s18-junit002-red.OE8Ety/junit.xml`、`/private/tmp/ai-auto-lrc-s18-junit002-green.2mqCjG/junit.xml`。完整 verifier contracts 为 `64 passed in 5.41s`，JUnit 位于 `/private/tmp/ai-auto-lrc-s18-src-junit-full.bfAilf/junit.xml`、SHA-256 为 `65af977a2fbbb34883148c4485a5a1fe6e64b3b2a5ebb75f1a02b24f3c4f109d`；verifier SHA-256 为 `4e86bd4c1768eecaea71ddbd19a0ee8bf9c1a9de197cc4398790a2601385bf67`，contract test SHA-256 为 `ebfa1133da87db7e5185c39d2e59957b5dd57713bfd119a76d0ff477d01195cb`。Ruff、`py_compile` 和 diff check 均通过。由于 verifier bytes 已变化，17.10 的 macOS 六个 lane 和 Linux `attempt-003` 从此刻起全部降级为 historical，必须在 XFAIL/ABA 最终字节冻结后按 17.11.6 重跑。

#### 17.11.1 当前声明与架构裁决

| 主题 | 当前裁决 | 允许声明 | 禁止声明 |
|---|---|---|---|
| `S18-COV-015` | Implemented + Verified；真实 runner 在 pytest 期间观察到 target test endpoint drift 并 fail closed | before/after 端点字节不同时，Gate 以 `EVIDENCE_BINDING_INVALID` 拒绝，raw artifact 保留 | 不证明执行期间没有 swap-and-restore，也不证明 immutable snapshot |
| `S18-SRC-001` | Implemented + Verified；同一份有界 source bytes 同时供 AST/symbol 与 SHA-256 使用，禁止从 path 二次读取形成不同事实 | verifier 内单次 frozen read 的 symbol/hash 一致性 | 不证明 pytest、import graph 或整个仓库执行闭包不可变 |
| `S18-JUNIT-001/002` | Implemented + Verified；classname 和 testcase name 分别通过 canonical grammar，再可逆组成 nodeid，不对不可信输入做宽松“修复” | verifier 只接受与 target test path 和 pytest nodeid 语法一一对应的 JUnit | 不接受 dot/slash/`.py`/`..` 混淆、控制字符、路径分隔符或重复 `::` |
| `S18-XFAIL-001` | 配置语义、runner argv 和受约束 pytest events 三重闭合；required XFAIL 与任意 strictness 的 XPASS 都必须 fail closed | 当前 pytest 运行明确使用 strict override，plugin 记录 xfail intent/outcome，配置和 plugin bytes 都纳入 toolchain closure | 不把默认 pytest 行为、仅 hash 绑定配置或 JUnit 空 testcase 当作 strictness/XPASS 证明 |
| `S18-ABA-001` | 本轮锁定声明边界，不实现 immutable execution snapshot | sequential endpoint observation；端点不同时能发现 drift | `aba_safe`、`immutable_execution_snapshot`、`transactional_execution`、`power_loss_durable`、完整 same-UID 或 cross-UID proof |
| package | Linux capture-bound package 与 macOS functional/package lane 分层记录 | 各平台只按实际 runner 和 receipt 强度声明 | 在 macOS 尚无等强 capture-bound receipt 时，不称“双平台 package qualification 已闭合” |

`EVIDENCE_EXECUTION_SNAPSHOT_UNPROVEN` 是未来尝试提升为 immutable/ABA-safe 声明时的稳定拒绝标识，不得无条件加入所有正常 Security Gate 的 failures；否则现有所有 endpoint-observation Gate 会永久失败。当前 schema 若没有显式 claim 字段，ABA 工作只增加边界合同和文档断言，不为制造错误码而扩展 schema。

#### 17.11.2 XFAIL 运行语义与最小生产切片

当前 `pyproject.toml` 只有 `addopts = "-ra --strict-config --strict-markers"`，没有 `xfail_strict = true`；runner 的 pytest argv 也没有 strict override。verifier 已把 JUnit `<skipped type="pytest.xfail">` 映射为 `xfail` 并对 required node 返回 `REQUIRED_TEST_XFAILED`。Teams 已用真实 pytest/JUnit 实测三种结果：XFAIL 生成 `<skipped type="pytest.xfail">`；XPASS(strict=true) 生成 failure；XPASS(strict=false) 生成没有 failure/skipped 子元素的空 testcase，与普通 PASS 无法区分。测试级 `@pytest.mark.xfail(strict=False)` 可以覆盖全局 strict 配置，因此“配置 true + command token + JUnit”仍不足以识别全部 XPASS。

可接受的最小闭合方案是显式 pytest events sidecar，而不是根据 JUnit 文案猜测 XPASS：

1. `pyproject.toml` 的 `[tool.pytest.ini_options]` 增加布尔值 `xfail_strict = true`。
2. 新增受约束的 pytest plugin，例如 `scripts/pytest_security_events.py`。collection 阶段记录每个 canonical nodeid 是否存在 `xfail` marker；call report 阶段记录 `wasxfail` 与真实 outcome。plugin 不改变业务测试结果，不从 message/longrepr 推断语义。
3. `scripts/run_security_coverage.sh` 的 pytest argv 增加 exact plugin token 和 `-o xfail_strict=true`，并让 plugin 原子写入 `pytest-events.json`。plugin path/hash、events path/hash 与 before/after identity 进入 environment、command、run-manifest 和 Gate；plugin bytes 漂移与其它 toolchain 漂移相同，返回 `EVIDENCE_TOOLCHAIN_BINDING_INVALID`。
4. `pytest-events.json` 使用 exact-key schema v1：顶层 `{schema_version, run_id, target, runner, attempt, test_file, cases}`；每个 case 只能是 `{nodeid, xfail_marked, wasxfail, call_outcome}`。cases 按 nodeid 排序、nodeid 唯一，并与 JUnit collected case 集合一一对应；大小、case 数、字符串长度继续受 policy 上限约束。缺失、额外字段、重复/非法 nodeid、binding 不一致或 JUnit/events 集合不一致统一以 `PYTEST_EVENTS_INVALID` 拒绝。
5. `scripts/verify_security_coverage.py` 从已经有界读取的 `pytest_config_content` 使用 TOML parser 解析，要求 `[tool.pytest.ini_options].xfail_strict is true`；同时要求 command 中 strict/plugin token 各恰好出现一次。字段缺失、值为 `false`、错误类型、TOML 不可解析、token 缺失或重复统一返回 `RUNNER_CONFIGURATION_INVALID`，不得回显路径、配置片段或 parser 异常。required case 只要 `xfail_marked` 或 `wasxfail` 为 true，无论 JUnit 显示 skipped、failure 还是空 testcase，都以 `REQUIRED_TEST_XFAILED` 表达其不满足 required-success。

这是 evidence schema 的实质扩展：environment、run-manifest 和 Gate 必须升级到下一个 schema 版本并拒绝旧版本冒充 current；command 若新增 events/plugin binding 字段也同步升级。不得把新 plugin 当作未记录的测试辅助文件。pytest config before/after SHA 不同仍由 `EVIDENCE_TOOLCHAIN_BINDING_INVALID` 表达；配置最终语义无效时可同时出现 `RUNNER_CONFIGURATION_INVALID`。failure 排序必须保持确定性，测试断言排序后的精确集合而不是自由文本。

#### 17.11.3 XFAIL 可执行集成测试

四个测试全部复用 COV-015 的隔离 runner harness：复制最小仓库闭包，使用受控 fake `uv`/pytest 生成 coverage、JUnit、pytest events 和原始 coverage data，真实调用 `scripts/run_security_coverage.sh`。至少一个小型 characterization fixture 必须调用真实 pytest，锁定三种 JUnit 输出与 events sidecar 的对应关系。不得给生产 runner 增加 test-only 开关，不得修改当前工作区的 target test 或配置。

| Test | Fixture | 当前 RED / GREEN Oracle | 稳定错误码 |
|---|---|---|---|
| `test_s18_runner_rejects_required_xfail_even_when_pytest_exits_zero` | required node 的 events 为 `xfail_marked=true`/`wasxfail=true`，JUnit 为 `pytest.xfail` skipped，pytest exit 0 | runner exit 1；coverage/JUnit/events/log/environment/command/run-manifest/Gate 全保留；required status 不得是 passed | `REQUIRED_TEST_XFAILED` |
| `test_s18_runner_rejects_non_strict_xpass_hidden_as_junit_pass` | required node 使用 `xfail(strict=False)` 并意外通过；JUnit 是与 PASS 不可区分的空 testcase，events 记录 marker/wasxfail，pytest exit 0 | 修改前 Gate 误通过，形成核心 RED；修改后 runner exit 1，证明裁决来自受约束 events 而非 JUnit 文案 | `REQUIRED_TEST_XFAILED` |
| `test_s18_runner_rejects_strict_xpass` | required node 使用 strict xfail 并意外通过；JUnit failure、events 记录 xfail intent，pytest exit 1 | runner exit 1；command 记录 strict/plugin token；required 语义统一为 xfail-not-success，而不是依赖 longrepr 猜 `XPASSED` | `COMMAND_FAILED`、`REQUIRED_TEST_XFAILED` |
| `test_s18_runner_rejects_pytest_config_or_plugin_drift_during_pytest` | 参数化 config 漂移与 plugin bytes 漂移；运行仍生成合法 coverage/JUnit/events | before/after 对应 SHA 不同；runner exit 1；所有 raw artifacts 保留 | `EVIDENCE_TOOLCHAIN_BINDING_INVALID`；config 最终为 false 时另有 `RUNNER_CONFIGURATION_INVALID` |

还需保留 verifier 直接合同：配置缺失、`false`、字符串 `"true"` 或整数 `1` 均拒绝；strict/plugin token 缺失或重复均拒绝；events 缺失、超限、字段增删、重复 nodeid、非法 nodeid、JUnit/events 集合不一致和 run/target/runner/attempt/test-file binding 不一致均拒绝。这些合同用于定位 parser/sidecar/command contract，不替代上述真实 runner integration。

#### 17.11.4 ABA 与不可变执行快照的边界测试

本轮实现两个不改生产执行模型的合同：

1. `test_s18_runner_endpoint_hash_equality_does_not_claim_aba_safe`：隔离副本中保存 target test 原 bytes，fake pytest 在执行期间替换成不同 bytes，并在返回前恢复。断言 before/after SHA 相同，endpoint Gate 可以按当前合同通过，但 Gate、run-manifest、receipt 和文档 current-claim 列表均不得包含 `aba_safe`、`immutable_execution_snapshot`、`transactional_execution` 或 `power_loss_durable`。
2. `test_s18_p1_claim_boundary_rejects_unproven_execution_guarantees`：若未来 schema 接收显式 claims，加入上述任一提升声明必须以 `EVIDENCE_EXECUTION_SNAPSHOT_UNPROVEN` 拒绝；在 schema 尚无 claims 时，该测试只锁定公开输出和文档不得出现这些肯定声明，不虚构新的常规 Gate failure。

真正的 immutable snapshot 必须另立工作包，不属于本轮最小 P1。该工作包至少要冻结并从快照执行：生产 source、target tests、fixtures/import graph、policy、manifest、pytest config、runner、verifier 和运行所需 assets；还要处理 dirty/untracked bytes、跨 macOS/Linux 的路径与权限语义、coverage source provenance、快照创建期间自身的一致性，以及快照到 artifact 的完整 hash 链。仅复制一个 test、仅依赖 `git archive`、或只比较 before/after hash 都不能满足该定义。

#### 17.11.5 剩余执行 DAG

```text
B0 COV-015 Implemented + Verified
  -> B1 SRC-001 frozen-source Implemented + Verified
  -> B2 JUNIT-001/002 grammar Implemented + Verified
  -> B3 先冻结 pytest events schema/plugin binding，再完成 XFAIL-001 四组 runner integration + 直接合同
  -> B4 完成 ABA-001/CLAIM-001 边界合同，不实现 snapshot
  -> B5 冻结 verifier/runner/config/contract/manifest/policy 字节
  -> B6 verifier contracts + Spec Inventory current-byte 回归
  -> B7 macOS 三轮 capture/retention Security Gate + 每轮 independent reverify
  -> B8 Linux 新 exclusive Security attempt + independent reverify
  -> B9 package 证据分层决策
       -> B9a macOS functional/package fresh lane
       -> B9b Linux capture-bound package fresh lane
       -> B9c 若要求双平台同强资格化，先实现 macOS sidecar/capture；否则记录 accepted scope limit
  -> B10 canonical image 重建 + 13/13 required golden + independent verify
  -> B11 host full + Ruff + compileall + bash-n + diff/link/inventory
  -> B12 最新 PASS/BLOCKED sealed evidence + 独立 reviewer 重算
  -> B13 Teams W1b-5b Go/No-go 复审
```

B3–B4 严格串行，因为 ABA fixture 和声明依赖 XFAIL events/toolchain schema 的最终输出；B7 与 B8 在 B5 字节冻结后可由不同平台顺序执行，但不得共享或覆盖 attempt root。高成本 package、canonical 和 sealed evidence 必须晚于最后相关字节变化。B9 的 macOS 与 Linux 结果分别签署，B9c 未决时最高声明是 platform-scoped，不得合并成双平台 Release 证明。

#### 17.11.6 证据失效矩阵

| 变化 | 立即历史化 | 必须刷新 | 可保留但不得扩大声明 |
|---|---|---|---|
| verifier、runner、pytest config、pytest events plugin、policy、manifest 或 target source/test | 17.10 的六个 macOS lane、Linux `attempt-003` 及其 independent reverify | verifier contracts、受影响 fresh coverage、macOS 三轮、Linux 新 attempt | COV-015 与 SRC/JUnit 的历史 RED/GREEN 过程记录 |
| 仅新增不进入闭包的 contract test | 旧 contract 总数 | 定向合同、完整 contracts、Spec Inventory | 受约束字节完全相同时的 Security artifact |
| `pyproject.toml` 变化 | 依赖该 hash 的 Security Gate；所有以旧 pyproject 构建的 wheelhouse/package artifact | Security 双平台；macOS/Linux package manifest、cold install、`pip check`、installed origin/CLI | 与 package 无关的历史功能证据 |
| canonical source/formal input/oracle/container recipe/image/verifier 变化 | 旧 canonical current 声明 | image 重建、13/13 required golden、独立重算 | 旧 digest 仅作 historical |
| 仅文档变化 | 旧文档 current pointer | relative links、inventory、`git diff --check`，并确认 claims 未扩大 | 不应无依据重跑 Security/package/canonical |

任何 hash 漂移都必须先判断其属于哪个 evidence domain；不得无条件全量重做，也不得用单节点、host full、package 或 canonical 中任一结果替代另一域的 Gate。

#### 17.11.7 测试执行与 attempt 记录规范

每个 P1 切片按相同模板记录：test name、fixture、预期 RED、实际 RED root、最小生产文件、GREEN 命令、实际结果、GREEN root、受约束 SHA-256、rollback unit、未验证声明。首次 RED、fixture bug、runner error 和 retry 分开建目录；不得修改旧 attempt 内容。

推荐的低成本执行顺序：先运行新增 exact node；再运行 `tests/contract/test_security_coverage_gate.py` 全文件；随后做 Spec Inventory。只有 B5 字节冻结后才执行高成本 Security runner。测试命令必须使用仓库锁定环境并记录完整 argv；不得通过放宽 allowed failure、移除 strictness、增加宽泛 skip/exclusion 或手改 artifact 让 Gate 变绿。

#### 17.11.8 停止、回滚和授权边界

- required missing/deselected/skip/xfail/failure/error、critical line/branch 非 100%、全文件指标低于 policy、配置/工具/测试 drift、runner 与 verifier 结果不一致，立即停止当前波次并保留 attempt。
- XFAIL 改动的回滚单元是 pytest events schema/plugin + `pyproject.toml` + runner strict/plugin tokens + verifier config/events parser + 对应 contracts；不得连带回滚已经验收的 SRC/JUnit 切片。
- ABA 边界合同若失败，先收缩 claim；不得为了让测试通过而把 endpoint observation 重新命名为 snapshot。
- package 若只有 macOS functional lane 与 Linux capture-bound lane，必须在 Gate 表中分列；未经 B9c 设计或明确 accepted scope limit，不得写“双平台资格化完成”。
- 继续保留全部 modified/deleted/untracked 文件、根目录来源不明文件 `./=`、所有 RED/flaky/retry/旧 attempt。禁止 `reset`、`checkout`、`clean` 和广泛删除。
- commit、push、CI、upload/sync、签名、发布、archive、restore、delete、destruction 均未获授权；W1b-5c/5d/5e、独立恢复包和 Release supply chain 不属于本轮执行权限。

#### 17.11.9 完成判定与恢复入口

- [x] `S18-COV-015` 真实 runner integration 已保留 RED/GREEN，确认 endpoint drift fail closed。
- [x] SRC-001、JUNIT-001/002 已分别完成 RED/GREEN、定向与完整 contracts，并记录 verifier/test 字节；相关 Security Gate 已历史化。
- [ ] XFAIL-001 的 required XFAIL、non-strict XPASS、strict XPASS、运行期 config/plugin drift 全部通过真实 runner integration；config/events/argv 直接合同同时通过。
- [ ] ABA-001/CLAIM-001 锁定最大声明，公开输出和 current docs 不声称 immutable/transactional/ABA-safe/power-loss。
- [ ] 最终字节下 verifier contracts、Spec Inventory、macOS 三轮、Linux 新 attempt 与 independent reverify 全部 current。
- [ ] package 证据按平台与 receipt 强度分层；若没有 macOS 等强 capture-bound 证明，已记录明确 scope limit，未声称双平台 qualification。
- [ ] canonical 13/13、host full、静态/编译/link/inventory、最新 PASS/BLOCKED sealed evidence 与独立 reviewer 复核均晚于最后相关字节变化。
- [ ] Teams 完成 W1b-5b 复审；即使 W1b-5b 转 Go，W1b-5c/5d/5e 和 Release 仍需独立授权。

恢复时先核对是否存在正在进行的 P1 原子切片和其 attempt，再从本节 B3 开始：先冻结 pytest events sidecar/plugin 合同，再做 XFAIL runner integration；不要重跑 COV-015、SRC 或 JUnit 探索过程，也不要从 17.10 的 A1 恢复。每完成一个切片只在本节之后 append 新事实，不覆盖本节的计划、历史 artifact 或未完成项。

### 17.12 2026-09-07 P1 独立执行方案入口

第 17.11 节保留 XFAIL events 初始方案及当时状态；后续真实 B3 安全审阅发现新的资格化阻断：pytest entry-point autoload、`PYTEST_PLUGINS`、`PYTEST_ADDOPTS`、`conftest.py` 和 namespace package shadowing 尚未封闭，且 events `call_outcome` 尚未与 JUnit 状态逐 node 交叉验证。因此 B3 当前只能标记为 **Implemented / qualification blocked**，既有 `95 passed` 不能作为 hermetic execution 或当前双平台资格化证明。

当前唯一可执行方案为 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)，版本 `S18-P1-PLAN-v1.0`，SHA-256 `027d0350f8d3d2074828a2f2cf6a3645808f7e1bf7fb59ac27081d6857fb8c61`。Teams 冻结记录为 [`team-sessions/team-session-2026-09-07-3.md`](./team-sessions/team-session-2026-09-07-3.md)，SHA-256 `03744e04c50859584e75ce80bf969e96de3adec17f695b4bc0e5f130a61ac7f3`。

恢复顺序更新为：hostile plugin/environment/conftest RED → hermetic pytest boot → 实际 plugin path/hash 绑定 → JUnit/events outcome consistency → ABA claim boundary → current-byte contracts/link/inventory → 最终字节冻结 → 双平台 Security/package/canonical/host/sealed evidence。S18、W1b-5b、Release 继续 No-go；W1b-5c/5d/5e 未授权。

### 17.13 S18 P1 当前冻结指针

第 17.12 的 v1.0 hash 保留为首次落盘 checkpoint。Teams 最终审阅又补入真实 XFAIL runner、events 生成端资源上限、pytest 运行时工具链绑定、autoload 双重关闭和 typed ABA surface；当前有效版本为 `S18-P1-PLAN-v1.2`。

权威文件仍为 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)，当前 SHA-256 `ebc7bd3dcee085ca590d22df4d7fe2bc097a76efc4c463b5ed21e8ba06128683`。Teams 记录 SHA-256 为 `1d361c256584ec1f2d6be356aa2c060006a9a02ba69b66c181eaad709b058afa`。若 hash 不同，先记录新的 append-only 版本指针，不能继续把本节 hash 当作 current。

### 17.14 S18 P1 最终架构冻结指针

第 17.13 的 v1.2 指针保留为中间审阅 checkpoint。当前有效版本为 `S18-P1-PLAN-v1.3`，新增 exact pytest config/argv、JUnit/events P0 优先级、P1 traceability 决策门和 common/per-platform freeze ledger。

权威文件 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) SHA-256 为 `1ee9a126586c4321714a84bd195db0fb36cf4c6925dba06940b5723dbb539429`；Teams 记录 SHA-256 为 `81b1cb2b563ec8bbf7f110326e0796f9f1cc7ffff3dff23ca5626235984d2e1e`。后续只从方案第 16.5 节 DAG 恢复。

### 17.15 S18 P1 v1.4 本地执行恢复指针

第 17.14 节保留 v1.3 的架构冻结 checkpoint。Teams 续接复审已把 B3b/B3d 当前实现账本、B3c absolute trusted bootstrap、独立 plugin identity schema、pytest-cov RECORD/lock 绑定，以及 B3e/B3f/B4 的 RED/GREEN、mutation、跨平台和 evidence layout 统一写入权威方案第 17 节。

当前有效版本为 `S18-P1-PLAN-v1.4`；文件 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) SHA-256 为 `9cb1a2c534cab265aa43ec0b5e3d651392ba3e9ae4cce81406a834772dd07c68`，Teams 记录 [`team-sessions/team-session-2026-09-07-3.md`](./team-sessions/team-session-2026-09-07-3.md) SHA-256 为 `0d51117b5bacbbf4468e21f6b37e922f7de641462b04c5b356bd40e3d17535c7`。恢复时从方案第 17.8 节的 B3c trusted plugin identity RED 开始；B3b/B3d 只构成 host implementation checkpoint，不构成跨平台资格化。

### 17.16 S18 P1 v1.5 当前资格化入口

第 17.15 节保留 v1.4 checkpoint。当前权威方案为 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第 18 节，版本 `S18-P1-PLAN-v1.5`，SHA-256 `59d42eaed5f5323255d510e3f6f4e5bd784c8d84ea329ffb1f01f1098dc4f262`；Teams 裁决 [`team-sessions/team-session-2026-09-07-4.md`](./team-sessions/team-session-2026-09-07-4.md) SHA-256 `91af3b63a6e9ec313c8ad343a71d993aa6e6339bdc5604fe6dfc0b1df12481c1`。

唯一下一步为 B3e-S 稳定 scenario IDs、scenario manifest 和 P1 ID authority，然后解决 B3c RECORD/no-replace 语义并执行 B3f-L、B3f-R。B3c/B3e 当前最多为 host implementation/contract checkpoint；179 passed 不构成持久 raw closure、Linux 证明或双平台资格化。

只有最终 schema 下的 B3c–B3e 重放、B4 typed claim/ABA/traceability、B7、common/per-platform freeze ledger 与平台独立 replay 全部 current 后，才可开始或消费最终 Security qualification。S18、W1b-5b、Release 继续 No-go，5c/5d/5e 未授权。

### 17.17 S18 P1 v1.6 当前资格化入口

第 17.16 节保留 B3e-S 前的 v1.5 checkpoint。当前权威方案为 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第 19 节，版本 `S18-P1-PLAN-v1.6`，SHA-256 `c14dc85959176d8e018713fbecaf064ca28c204f16e24e6280635406508217c8`；Teams 记录 [`team-sessions/team-session-2026-09-07-5.md`](./team-sessions/team-session-2026-09-07-5.md) SHA-256 `dd139646c3fbbec6c89ee7e3305e496066fc54a637372beb731bc933249b3293`。

B3e-S 已冻结 7 个 implemented host-contract scenario、13 个 planned macOS/Linux hostile scenario、exact outer/victim nodeids、artifact allowlist 与 required XFAIL run-true 语义。P1 inventory schema v3/v1 已落地，首批 7 个 record 由独立完整字段 authority 约束；collection 清除 pytest hostile environment/plugin/addopts/conftest 注入并消费结构化 `session.items` sidecar。当前所有 record 仍为 `unverified/unqualified`。

当前 host 结果不能代签 Linux、持久 raw closure、evidence 语义、transition authority 或平台 qualification。唯一下一步为 B3c RECORD field semantics/no-replace contract correction，随后 B3f-L、B3f-R 和 final-schema replay；首次 P1 状态晋级前还必须实现逐 kind 独立 verifier 与单调 transition ledger。S18、W1b-5b、Release 继续 No-go，5c/5d/5e 未授权。

### 17.18 S18 P1 v1.7 当前资格化入口

第 17.17 节保留 B3c 收口前的 v1.6 checkpoint。当前权威方案为 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第 20 节，版本 `S18-P1-PLAN-v1.7`，SHA-256 `a1cf11e7e9700a6689959a88d0a6abee5395c582b48a1e881db96013dbd34afc`；Teams 记录 [`team-sessions/team-session-2026-09-07-6.md`](./team-sessions/team-session-2026-09-07-6.md) SHA-256 `ceac0ee80f76681cdbc59fe2e42f119154853fe9344dbd89dc68bb5371c52720`。

B3c schema v1 的 `record_sha256` 已冻结为 `pytest_cov/plugin.py` RECORD entry digest；identity hard-link no-replace、mode `0600`、已有 final/publication race 和 whole-RECORD 错误 mutation 已通过 host contract。它不证明完整 writer fault closure、whole RECORD/METADATA closure、wheel provenance、single runtime、Linux 或平台 qualification。

唯一下一步为方案第 20.4 至 20.7 节的 B3f-L producer limits 与 writer fault matrix，随后按第 20.9 节进入 B3f-R、final-schema replay、完整 hostile matrix 和 B4/B7/B8。首次 P1 状态晋级前仍须逐 kind 独立 verifier 与单调 transition ledger。S18、W1b-5b、Release 继续 No-go，5c/5d/5e 未授权。

### 17.19 S18 P1 v1.8 当前资格化入口

第17.18节保留B3f-L执行前的v1.7 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第21节，版本`S18-P1-PLAN-v1.8`，SHA-256 `e33a9a312dcf49096f1af89276074f71beb8f243b1a3a0eabbf7e2a45868ebe4`；Teams记录[`team-sessions/team-session-2026-09-07-7.md`](./team-sessions/team-session-2026-09-07-7.md) SHA-256 `a386eb6a4f38e60b536362ff2a1ab7e40b25500b6040da5d132c23e2e66e1e3d`。

B3f-L五文件unit/mutation tranche已通过当前host contract；`257 passed`不证明第20.7尚未存在的capture/retention real-runner nodes。整个B3f-L继续PARTIAL/No-go，唯一下一步是建立独立scenario authority并完成双lane真实limit/fault matrix。完成前不得进入B3f-R、final-schema replay或平台资格化；首次P1状态晋级前仍须逐kind verifier与transition ledger。S18、W1b-5b、Release继续No-go，5c/5d/5e未授权。

### 17.20 S18 P1 v1.9 当前资格化入口

第17.19节保留authority建立前的v1.8 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第22节，版本`S18-P1-PLAN-v1.9`，SHA-256 `9e688a4edc94b308257f4ef72072e7ca9f06cd0a421db99e213cfbfd21cb8bf9`；Teams记录[`team-sessions/team-session-2026-09-07-8.md`](./team-sessions/team-session-2026-09-07-8.md) SHA-256 `a05f078026ce77feba9e4eddbc6085db3b59088c722099c7c1f184e656086afd`。

B3f-L authority已冻结67条，其中10条代表性capture/retention real-runner records为implemented，57条仍planned。该checkpoint只证明当前host的部分mutation contract，不是B3f-L、B3f-R、macOS/Linux或双平台qualification。唯一入口是方案第22.7节Batch A至H以及最终67条同hash replay；完成前不得启动B3f-R、final-schema replay或最终平台evidence刷新。首次P1状态晋级仍需逐kind verifier和transition ledger。S18、W1b-5b、Release继续No-go，5c/5d/5e未授权。

### 17.21 S18 P1 v1.10 当前资格化入口

第17.20节保留Batch A前的v1.9 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第23节，版本`S18-P1-PLAN-v1.10`，SHA-256 `c46808ba2fd421a20225ab145cf9715bd974576d4e3b8a5b23b166f484c485bd`；Teams记录[`team-sessions/team-session-2026-09-07-9.md`](./team-sessions/team-session-2026-09-07-9.md) SHA-256 `84dfea124230a7027a200fd00a3919d6e2b47c36e9da153767989f4c04ac47b5`。

Batch A的18条configure argv records已完成host real-runner contract，authority当前28 implemented/39 planned。该结果不是B3f-L、runtime provenance或平台qualification；下一步只执行第23.5节Batch B六条nodeid records，最终仍须67条同hash replay。首次P1晋级仍需逐kind verifier与transition ledger。S18、W1b-5b、Release继续No-go，5c/5d/5e未授权。

### 17.22 S18 P1 v1.11 当前资格化入口

第17.21节保留Batch B前的v1.10 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第24节，版本`S18-P1-PLAN-v1.11`，SHA-256 `8cc36822ec315d2e905d057e64121ee94c31bb21245e34578efa53f65ff37d2a`；Teams记录[`team-sessions/team-session-2026-09-07-10.md`](./team-sessions/team-session-2026-09-07-10.md) SHA-256 `b72d2f78957377b5d99d447692c6ce9f2a04b2adc7738b3e4afbde27015fd5d0`。

Batch B六条nodeid records已完成host contract，authority为34 implemented/33 planned。该结果不构成B3f-L、runtime provenance或平台qualification；下一步只执行Batch C四条serialized byte边界，最终仍须67条同hash replay和逐kind transition门。S18、W1b-5b、Release继续No-go，5c/5d/5e未授权。

### 17.23 S18 P1 v1.12 当前资格化入口

第17.22节保留Batch C前的v1.11 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第25节，版本`S18-P1-PLAN-v1.12`，SHA-256 `3bd00bca522b46880f75ad06e940865bab8b61241cd97a96d716e42dd0da8200`；Teams记录[`team-sessions/team-session-2026-09-07-11.md`](./team-sessions/team-session-2026-09-07-11.md) SHA-256 `60ffbcbeec2a1dc21610e58982874c1c44b3cecfb21075d3070c02a6aa9bfca1`。

Batch C四条serialized sessionfinish hard-check records已完成host mutation contract，authority为38 implemented/29 planned。该结果不构成normal producer自然可达、B3f-L/R或平台qualification。下一步只执行Batch D十四条pre-publication I/O，最终仍须67条同hash replay。S18、W1b-5b、Release继续No-go。

### 17.24 S18 P1 v1.13 当前资格化入口

第17.23节保留Batch D前的v1.12 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第26节，版本`S18-P1-PLAN-v1.13`，SHA-256 `7c6beb0c6c5c2fe6e3071d7e4a053dbaf94a4f37e0fff64ee629d9479a17eeef`；Teams记录[`team-sessions/team-session-2026-09-07-12.md`](./team-sessions/team-session-2026-09-07-12.md) SHA-256 `9bd312ae5da31ef2db556cca6063d76cdeae68fa1f33fd57ee0d0dd1486b8dff`。

Batch D十四条pre-publication I/O records已独立QA GREEN，B3f-L authority为52/15/67，但仍不是完整B3f-L或任何平台qualification。S18、W1b-5b、Release继续No-go；只允许继续Batch E，不执行5c/5d/5e。

### 17.25 S18 P1 v1.14 当前资格化入口

第17.24节保留Batch E前的v1.13 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第27节，版本`S18-P1-PLAN-v1.14`，SHA-256 `c273c92020eb3f9bc47d6537d1fce10513221af5119f9d69f4e10e23a098eae5`；Teams记录[`team-sessions/team-session-2026-09-07-13.md`](./team-sessions/team-session-2026-09-07-13.md) SHA-256 `781823e419f0f4bd4841c8adc40286baea9928a02629a12f5358ce657a5b80b5`。

Batch E六条protected-object/publish-race records已独立QA GREEN，B3f-L authority为58/9/67，但仍不是完整B3f-L或任何平台qualification。S18、W1b-5b、Release继续No-go；只允许继续Batch F，不执行5c/5d/5e。

### 17.26 S18 P1 v1.15 当前资格化入口

第17.25节保留Batch F前的v1.14 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第28节，版本`S18-P1-PLAN-v1.15`，SHA-256 `47e48deb8260e7171e23cfd8bd8adc7e4e6bf578a2196595588ad739aba1ecfb`；Teams记录[`team-sessions/team-session-2026-09-07-14.md`](./team-sessions/team-session-2026-09-07-14.md) SHA-256 `065d19d9455c1429a82cb8509ede5f94e906050a51bc9d1dd0b2847b62771da1`。

Batch F六条post-publication records已独立QA GREEN，B3f-L authority为64/3/67，但仍不是完整B3f-L或任何平台qualification。S18、W1b-5b、Release继续No-go；只允许继续Batch G，不执行5c/5d/5e。

### 17.27 S18 P1 v1.16 当前资格化入口

第17.26节保留Batch G前的v1.15 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第29节，版本`S18-P1-PLAN-v1.16`，SHA-256 `30b9df622cf930cb36e7a250193dd7386a379db9f4197d8d2e667f51b12ea248`；Teams记录[`team-sessions/team-session-2026-09-07-15.md`](./team-sessions/team-session-2026-09-07-15.md) SHA-256 `f70cd4737f8705996936cafe2345b7d52bf4919a2a7fa301e5e4f414cd298178`。

Batch G两条syscall-order records已独立QA GREEN，B3f-L authority为66/1/67，但仍不是完整B3f-L或任何平台qualification。S18、W1b-5b、Release继续No-go；只允许继续Batch H，不执行5c/5d/5e。

### 17.28 S18 P1 v1.17 当前资格化入口

第17.27节保留Batch H前的v1.16 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第30节，版本`S18-P1-PLAN-v1.17`，SHA-256 `a12aff9eaa2e3bb86f21efb7833d079bb4b82bb51dcb7ec2bf83e98ac6298398`；Teams记录[`team-sessions/team-session-2026-09-07-16.md`](./team-sessions/team-session-2026-09-07-16.md) SHA-256 `b9943d2f5e5688765a092d52b9f95394631ef5f342cf5325f05530333698a76c`。

Batch H唯一runner-input record已独立QA GREEN，B3f-L authority为67/0/67，但最终同hash replay尚未完成，因此仍不是完整B3f-L或任何macOS/Linux/platform qualification。S18、W1b-5b、Release继续No-go；只允许执行最终67条fresh replay与独立审计，不执行5c/5d/5e。

### 17.29 S18 P1 v1.18 当前资格化入口

第17.28节保留final 67前的v1.17 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第31节，版本`S18-P1-PLAN-v1.18`，SHA-256 `a6250365667cee35caf2784c68a96932e3336b57328e607fcc6790e47e84f488`；Teams记录[`team-sessions/team-session-2026-09-07-17.md`](./team-sessions/team-session-2026-09-07-17.md) SHA-256 `51041766bb0723257b62adf00803fd4926faeabf47ca65c14169df5e7b349021`。

B3f-L final 67 host contract已完成，但B3f-R runtime/lock/offline binding、final-schema replay和macOS/Linux hostile matrix均未完成，所以S18、W1b-5b、Release继续No-go。下一步只执行B3f-R0低成本合同RED，不执行5c/5d/5e或平台资格化。

### 17.30 S18 P1 v1.20 当前资格化入口

第17.29节保留R0前的v1.18 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第33节，版本`S18-P1-PLAN-v1.20`，SHA-256 `5b14134df98e68b5ed092262d5b43cf521b8156cee791dfb5c14719da52267f2`；Teams记录[`team-sessions/team-session-2026-09-07-19.md`](./team-sessions/team-session-2026-09-07-19.md) SHA-256 `271caf7e77870a024bf7d4b6a4d35aec5142bf872d3cf422d3c9ceba494e109a`。

B3f-R1a仅完成当前host的bootstrap primitive合同，不是runtime identity publication、真实runner evidence或平台qualification。唯一下一步为第33.7节R1b exact15；完成后仍须R2/R3/R4、final-schema replay、完整hostile matrix及macOS/Linux各自证据。S18、W1b-5b、Release继续No-go，不执行5c/5d/5e。

### 17.31 S18 P1 v1.21 R1b QA P1 资格化入口

前一入口保留为历史 checkpoint。当前权威方案为 [S18 P1 执行方案](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第34节（尤其34.6至34.10），版本 `S18-P1-PLAN-v1.21`，整份 SHA-256 `cc3705d97e7b9d6c75b0e91059f0ba9d88d5f1fe91de836290553d0677f457e7`；[Teams 20](./team-sessions/team-session-2026-09-07-20.md) SHA-256 `f5a1822407d8523093ada70700520cc9c964379be6c3f6db92d4cf1c3055e63a`。

R1b 定向回归通过，但独立 QA 发现 lock pathname 同内容换 inode 未拒绝、文件身份字段接受根路径两个 P1，当前 **未验收**。下一次执行从第34.8节局部 test-first 修复与新 hash 独立 QA 开始，不能跳到 R2。本次仅持久化方案，不修改代码或消费资格；产品/P1计数不晋级。S18、W1b-5b、Release 继续 No-go，不执行 W1b-5c/5d/5e。后续完整 DAG、测试用例、原始证据失效处理均以权威方案为准。

### 17.32 S18 P1 v1.22 R1b 验收与 R2 资格化边界

前一入口保留旧 QA P1 checkpoint。当前权威方案为 [S18 P1 执行方案](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第35节，版本 `S18-P1-PLAN-v1.22`，整份 SHA-256 `6b6c29dedb130396f1ab5ec6c7e4bda9637fecf65ce3892e373d8bac1ab48fc8`；[Teams 21](./team-sessions/team-session-2026-09-07-21.md) SHA-256 `069f7663cded80d73a3f37b52807fd121a610c9dc3b99e8a16a2ab9ced2dc67a`。

两个 R1b P1 已在新 hash 下经 RED/GREEN、架构与独立 QA 关闭；exact15、R1a10 unique、legacy10 均通过，policy-v3 仍是唯一预期 RED。R1b producer foundation 完成，不代表真实 runner、identity-v2 publication、Linux/双平台或 Release qualification。下一步先解决第35.11节草案冲突，冻结 R2 exact 契约后执行第35.5节原子 cutover；第35.9至35.10节字段/十二节点仍为 proposed/planned，不计为实现。S18、W1b-5b、Release 继续 No-go，inventory不晋级，W1b-5c/5d/5e不执行。

### 17.33 S18 P1 v1.23 R2 进行中资格化边界

当前工作入口转至 [S18 P1 执行方案](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第36节和 [Teams 22](./team-sessions/team-session-2026-09-07-22.md)。第35节R1b最终hash仅为历史已验收基线；R2正在原子迁移，代码与文档尚未最终封板，因此本入口不提供冒充完成的固定hash。

先核对第36节最后checkpoint与真实worktree/进程状态后续接。不得复用旧R1b绿色、初始15-node scaffold RED或部分schema更改代签R2。真实双lane、final67和平台qualification仍待后续，inventory不晋级；S18、W1b-5b、Release继续No-go，5c/5d/5e不执行。

### 17.34 R2 方案本地保存与待独立 QA 入口

最新恢复点为 [S18 P1 执行方案](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第36.33–36.34节；实现已停写停测并交锁，九文件候选快照已核对。精确测试选择、证据索引与hash已保存到docs，原始测试产物仍在临时目录；本次不是完整证据归档。

R2尚未独立验收；下一步为同快照独立QA，不是R3。四项入口继续WIP，S18、W1b-5b、Release继续No-go；详情与验收门仅以权威方案最新checkpoint为准，不从旧绿色或聊天摘要推断完成。

### 17.35 R2 递归修复后的当前状态

最新恢复点为 [S18 P1执行方案](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第36.40节，新九文件清单位于第36.39节。深层JSON候选解析的P1已最小修复，主代理fresh47+35回归通过（去重79节点）；最终独立QA任务被执行环境中止，没有验收结论。独立验收门仍保留，不能据主代理复验启动R3；S18、W1b-5b、Release继续No-go。R3仅完成失败profile与隔离前置设计，不是执行或平台资格证据。

### 17.36 R2 独立验收完成与 R3 正常对照

2026-09-09 最新入口为 [S18 P1 执行方案](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第36.41–36.42节。R2冻结九文件已通过独立源码审阅与79个唯一节点fresh回归；主代理重算57份原始证据并通过42项文档治理。旧“最终独立QA缺失”状态保留为历史，当前R2合同已验收。R3正常macOS对照已实现：最终system层2项通过，真实capture282项和retention257项通过，两Gate PASS；retention有1个声明的平台不适用skip。完整异常矩阵、R4、平台与发布资格仍待完成。产品inventory不晋级，S18/W1b-5b/Release继续No-go。


## 17.37 2026-09-12 用户交付决定：文档与开发分支推送

用户明确要求异常场景暂不全覆盖，优先完善技术文档、系统说明、使用指南与 README 顶部 AI 使用提示词，并推送远端。本次提交/推送已有用户授权，早期“等待提交批准”记录保留为历史，不阻止本次开发快照交付。

当前权威入口为[文档导航](README.md)及[项目状态](PROJECT_STATUS.zh-CN.md)。保留 R2 冻结验收与 R3 macOS 正常对照证据；不扩大其结论、不补跑完整异常矩阵、不更改原始阈值。未完成事项标记暂缓/未验证，S18 / W1b-5b / Release No-go 不变。本轮只向 `improve-inference-reliability` 开发分支提交及推送，不覆盖远端 main，不发布发行版。
