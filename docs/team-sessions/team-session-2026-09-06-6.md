# Dev Team 会话：W1b-5 S18 安全资格与证据收口

> Historical / superseded：本纪要保留当时讨论、RED与角色分歧，不再维护当前hash、pass计数或恢复步骤。当前唯一详细入口是 [`../W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md`](../W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md) 第 17.9 节。

> 2026-09-07 后续：第 17.9 节也已历史化；当前详细恢复入口为同一主方案第 17.10 节，新 Teams 纪要见 [`team-session-2026-09-07.md`](./team-session-2026-09-07.md)。

日期：2026-09-06  
模式：PM / Architect / Developer / QA；角色并行只读审阅，由主任务统一决策与回写  
主题：把 S18 从分散的“coverage + Linux + package + canonical”待办收敛为独立安全门禁、可执行测试矩阵和可重算 evidence bundle。

## 项目上下文

S16、S17 已完成各自声明范围。S18 开始前存在四个不同状态：Linux security functional 路径已局部通过；canonical 13 个 required golden 已通过；capture 独立 coverage 失败；macOS package 因旧 wheelhouse manifest 与当前 `pyproject.toml` hash 不一致失败。现有宿主全量与 PASS/BLOCKED sealed evidence 早于最新测试/代码，不能作为最终证据。

当前工作区包含大规模 modified/deleted/untracked v2 重构成果，必须保留。禁止 commit、push、CI、上传、签名、发布、自动清理/恢复/归档/销毁；W1b-5c/5d/5e 未授权。

## PM

1. **First reaction**：S18 的交付物不是一个绿色百分比，而是两个脚本、四类 runner 和最新 sealed evidence 的可追溯资格矩阵。
2. **Key concerns**：必须明确唯一事实源、owner、停止条件与失败留痕；Linux/canonical 局部通过不能掩盖 capture/package 阻断；旧宿主数字和旧 receipt 必须标记 historical。
3. **First action**：先冻结 policy、capability manifest、verifier schema 和 runner 责任，再实施测试，不在代码继续变化时刷新最终 evidence。
4. **Question for team**：Linux、package、canonical 与 independent evidence reviewer 的具体人员由谁指定？在用户指定前只记录角色，不虚构签署。

## Architect

1. **First reaction**：现有 `packaging/quality-gates.toml` 的事实域是 `t2l` portable coverage；把两个 security scripts 塞进去会混淆 source set 和资格边界，应建立独立 policy/manifest/verifier。
2. **Key concerns**：runner 只能生成原始 artifact，不能自报 qualification；verifier 必须从 coverage line/branch 与 JUnit testcase 重算；不同 attempt、平台或脚本不得拼接。
3. **First action**：冻结三件 checked-in 输入与职责：policy 定门槛，manifest 定能力到 symbol/nodeid/runner 映射，verifier 只读重算并在仓库外 exclusive 发布 Gate JSON。
4. **Question for team**：capture formal artifact 的 uid/mode/nlink 和 closure budget 是否属于本轮声明？结论是属于安全资格声明，现有实现证据不足，必须先写 RED。

## Developer

1. **First reaction**：coverage 缺口要通过真实错误路径和状态断言关闭，不能直接调用私有 helper、删分支、扩大 omit 或添加 `pragma: no cover`。
2. **Key concerns**：capture 的 `_DirFdReceiptIO`、`_read_stable_regular`、`_verify_record`、`_verify_source_summary`、`_verify_receipt_from_io`、`capture_gate`、`main` 有明显分支缺口；retention 的 `_private_child_directory_fd`、`_rename_noreplace`、`_open_lock`、`_stable_bytes`、`_resolve_cli_arguments` 是优先热点。
3. **First action**：先建立 `test_security_coverage_gate.py` 的 schema、伪造 totals、单 source、required nodeid、hash 和只读 RED；再补 hardlink/wrong-owner/overwide-mode、cap+1、identity race 和 CLI 负向用例。
4. **Question for team**：是否修改生产代码兼容旧 canonical Python 3.10 S18 collection？结论是否定的；S18 qualification 使用项目有效的 Python 3.11 runner，canonical golden 保持自身锁定环境。

## QA

1. **First reaction**：capture 和 retention 必须各有 fresh coverage data、独立 JUnit 和 exact required nodeids；Mac 上的 Linux-only skip 只能进入平台 allowlist，不能记为通过。
2. **Key concerns**：coverage.py branch-aware combined percent 会混合 line/branch，不足以表达安全 Gate；required test 缺失、skip、xfail、deselected、failure/error 均必须 fail closed；首次 RED、fixture 错误、flaky 和 retry 不得覆盖。
3. **First action**：建立 capture、retention、Linux security、macOS package、Linux package、canonical、host regression、evidence refresh 八个 lane，并为每个 attempt 保存 environment、command、nodeids、JUnit、coverage、Gate、logs 与 hash manifest。
4. **Question for team**：branch 门槛采用 75% 还是 80%？QA 建议和 line 一致采用 80%，避免根据 retention 当前 76.25% 反推较低标准。

## 讨论与决议

### 1. Branch 门槛

架构初稿曾提出 branch >= 75%，理由是同时再对 critical function 要求 100%。测试架构反对把 75% 作为首次冻结标准：当前 retention branch 恰为 76.25%，存在“按现状定门槛”的审计风险，也与“不降低现有 80%”的意图不够一致。

最终决议：两个脚本分别要求 coverage.py combined >= 80%、statement line >= 80%、branch >= 80%；critical target line/branch 100%。combined 只保留为现有 runner 兼容门槛，qualification 必须分别重算 line 与 branch。由此 capture 和 retention 当前都为 RED。

### 2. Policy 与 manifest 的边界

- `security-coverage-policy.toml`：exact schema、门槛、source allowlist、zero unexpected skip、artifact size bounds；不保存某次结果。
- `security-coverage-manifest.json`：capability ID、source target、symbol、required nodeid、runner scope、minimum cases、预期错误/状态；不保存运行百分比。
- `verify_security_coverage.py`：只读、bounded stable read、重算 line/branch/JUnit/capability closure，绑定 source/policy/manifest/JUnit/coverage/environment/command hash。
- runner：两个 fresh `COVERAGE_FILE`，禁止 `coverage combine`，每次使用不可覆盖 attempt 目录。

现有 `quality-gates.toml` 继续只管理 `t2l` portable/package/canonical 既有语义，不因 S18 被扩写成混合事实源。

### 3. Critical capabilities

最低类别冻结为：anchored path、special file、owner/mode/nlink、stable identity、source observation、entry/file/byte/metadata budget、no-replace、event visibility、teardown、flock/process crash、ledger/recovery、archived/current verify modes、CLI redaction、package/canonical binding、qualification provenance。

新增两个实现前 RED：

1. capture formal artifact 的 hardlink、foreign-owner、overwide-mode 必须由 capture 自身 fail closed；retention 后置扫描不能替代。
2. capture closure 必须有 entry/metadata/bytes exact-cap 与 cap+1 行为；若当前 schema 无法表达，先冻结内部常量和稳定错误，不能继续声称 capture closure 有界。

### 4. Runner 边界

- macOS capture/retention：关闭独立 coverage 与 CLI/fs/path 合同。
- Linux security：实际执行 `renameat2`、`/proc/self/fd`、block/char device、S16 flock/SIGKILL；Docker Desktop x86_64 容器是功能证据，不是原生性能证据。
- package：必须由当前源码完整重建 wheelhouse；canonical 不能替代 package。
- canonical：固定 image、断网、只读 root、13 required golden；只证明 functional canonical。
- evidence refresh：只能在最终源码、测试、policy 和文档稳定后进行。

## 首次失败与实测记录

### Linux runner

首次使用旧 canonical Python 3.10.21 环境时，collection 因 `from datetime import UTC` 失败。该失败归类为 qualification runner 错配，不修改生产代码迁就。

成功环境为 `python:3.11.9-slim-bookworm`、容器 `linux/amd64`、Docker Desktop daemon `linux/arm64` 29.7.2、repo 只读挂载：

```text
S16 + block/char device:  9 passed, 167 deselected in 13.44s
/proc/self/fd + source:   9 passed, 136 deselected in 5.37s
```

这两批当前只有终端功能证据；最终必须用 exact nodeids 重跑并保存 JUnit、environment、command 与 source hash。

### Coverage

```text
capture-only:
  145 passed
  statement line 1104/1394 = 79.1966%
  branch         402/594  = 67.6768%
  combined                  75.7545%
  SHA-256 bb0a0a1e4e4c2cd5e516da3a80e7f0c4c6734b821c638c2800faab46fdd08c6f

capture with retention tests appended:
  statement line 1106/1394 = 79.3400%
  branch         402/594  = 67.6768%
  combined                  75.8551%
  SHA-256 d1de8536b15db6013d4672f30b41d5ddc3130e4c453b79eb399626f0503d102c

retention-only:
  175 passed, 1 Linux-only skip
  statement line 1060/1228 = 86.3192%
  branch         305/400  = 76.25%
  combined                  83.8452%
  SHA-256 c38ef9beb65c7968849ddbdeaa81f94591e7ae667ff9d45d6dc6bff1503bfd77
```

追加 retention tests 未改变 capture branch 命中，证明跨 suite 补分不能解决独立安全分支缺口。

### Package

旧 macOS wheelhouse 结果为 `34 passed, 1 failed, 1 deselected in 27.32s`。唯一失败 `test_pkg_018_wheelhouse_policy_and_manifest_are_complete`：

```text
manifest pyproject_sha256: 53a80382c01518ebd94b747268dc4c54ed396e2f9e3dd0c1536f24dfc589792a
current  pyproject_sha256: 261e426e194d46308cdb1ca3117bb4015693691cd0704cfd071d1476240fed19
```

这是确定性的 stale-artifact failure，不是 flaky。必须完整重建 wheelhouse，禁止手工改 manifest hash。JUnit SHA-256 为 `ea0c267722761f2e5747946df93d6ff109acd18cde4a456332f20ee7db7b9aef`。

### Canonical

当前源码重建 image `sha256:d429650aacae3d9c8a50dfb1ff3e73e065e49eca3016bf3662e5ca2e7d7f5b19`，`linux/amd64`、断网、只读 rootfs：

```text
13 passed, 0 skipped, 7 warnings in 143.57s
JUnit SHA-256 63e5393d835134814f57a1b4dc0a8135c68a52527e75cfe9867b23a2544000a5
Gate  SHA-256 4579f84294956c30fe113f79b50fa046c6eb41cd8b39dd86b7f5d599e94df24c
```

最大结论是 current dirty-source functional canonical Go / implemented-unqualified。任何进入 canonical closure 的后续变化都要求最终重建重跑。

## 可执行测试清单

新增 coverage verifier 合同至少包括：

```text
test_s18_policy_is_exact_and_locks_two_script_targets
test_s18_gate_rejects_composite_green_when_line_or_branch_is_below_threshold
test_s18_gate_requires_branch_coverage_and_exact_single_source
test_s18_gate_rejects_missing_failed_skipped_or_deselected_required_nodeid
test_s18_gate_requires_every_critical_category_and_arc
test_s18_gate_binds_policy_source_junit_coverage_environment_and_command_hashes
test_s18_gate_rejects_cross_platform_or_cross_attempt_evidence
test_s18_manifest_preserves_first_failure_skip_retry_and_flaky_state
```

Linux required set至少包括：S16 lock contention、two publishers、六个 SIGKILL 参数、S17 block/char device、真实 renameat2 existing-target/no-fallback、capture open repository anchor、later checkout drift、`/proc/self/fd` inode binding/unavailable fail-closed。required runner 应直接传 exact nodeids，避免用 `-k` 产生大量无意义 deselected。

Package 当前收集 36 cases：macOS 目标 35 selected/1 expected deselected，Linux 目标 33 selected/3 expected deselected，两者都要求 0 skip/fail。`tests/spec_inventory.json` 中 `PKG-012/017/024` 的聚合或精确 nodeid 映射仍须补齐，否则 required-set closure 不成立。

## 当前 Gate 与恢复入口

| 范围 | Gate |
|---|---|
| Linux security functional | 局部 Go；待 JUnit/provenance 刷新 |
| Canonical functional | 局部 Go / implemented-unqualified；最终源码后重跑 |
| Capture security coverage | No-go |
| Retention security coverage | No-go；branch 76.25% < 80% |
| macOS package | 新 wheelhouse/package lane Go；补齐 `PKG-024` 后 37 passed、0 skip/fail；Linux package 仍未刷新 |
| S18 / W1b-5b | No-go |
| W1b-5c/5d/5e | 未授权、未实现 |
| Release | No-go |

完整方案已落到 [`../W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md`](../W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md)。下一步按 policy/manifest/verifier RED → capture/retention 分支闭合 → Linux exact-node bundle → package 重建 → canonical/host/evidence refresh → W1b-5b 复审执行。禁止事项和 dirty worktree 保留要求不变。

## 执行勘误：macOS package v2 与续接状态

Teams 讨论后已从当前输入完整重建 macOS arm64 CPython 3.11 wheelhouse，未覆盖旧 wheelhouse。manifest SHA-256 为 `93f253e999a9e1b97a065ecf2205cad489e23eff04b3eb38c6a8c6a89df900c2`。新增 `PKG-012` 与 `PKG-017` 合同后，完整 macOS package Gate 为 36 passed、1 deselected、0 skip/fail，Gate `passed=true`：

- `package.xml` SHA-256：`cfc0f794bb826fd7c07059dfeb1e9125c7b7ac68dcc3c862d8c19c312ebdc491`
- `package-gate.json` SHA-256：`ddaf132bfa1efdaeb58ab2b39ca6db934bfc64e2f245c03eec005c1b5b77793f`

这关闭的是当前 macOS package lane，不是 S18 或 Release。`PKG-024` 的恶意 CWD 等价性合同、Linux package、capture/retention 独立 coverage、最终 canonical 和 sealed evidence 仍未闭合。三条 Teams 实现线及精确恢复顺序已固化在主方案第 16 节；旧 34 passed、1 failed、1 deselected 继续作为 stale-wheelhouse 首次 RED 保留。

### Retention 工作线回报

Retention-only baseline 为 175 passed、1 Linux-only skip，line 84.4463%、branch 74.25%、combined 81.9410%，确认 branch Gate 为 RED。新增 32 个真实分支 case 和两处 fd 泄漏最小修复后，fresh run 为 207 passed、1 Linux-only skip，line 88.5922%、branch 82.4257%、combined 87.0732%，source set 精确只有 `scripts/manage_evidence_retention.py`。数值 Gate 已闭合，但仍须由统一 security verifier 复核 critical target、required nodeid、hash 与 runner binding 后才能签署该 capability lane。

Final coverage SHA-256 为 `9c0f09de11f4123849b4b378ed4397abb6b9a8d91d239ce272666b2c93a9e29b`，JUnit SHA-256 为 `ebf5309e1f228a2e421abe56e65c38c5d288e38046d2640f7619103a2cbe7f59`，source SHA-256 为 `131d9964da80a29045d046941c314d207380e59b152995ec70def9a4689dc508`。20/20 稳定性轮次通过；首次 shell runner 因 zsh `status` 只读变量退出的错误按规则保留。

### Capture 工作线回报

Capture-only baseline 为 145 passed、combined 75.7545%、line 79.1966%、branch 67.6768%，确认三项 Gate 为 RED。新增 107 个 S18 case并冻结 formal directory/file mode、owner/nlink、entry/metadata/bytes 三类 closure budget 后，fresh run 为 252 passed、0 skip/fail，combined 86.5477%、line 88.8736%、branch 81.0680%，source set 精确只有 `scripts/capture_test_gate.py`。

Ruff 后最终同源 coverage SHA-256 为 `60dc07452648a71a76a688a36517aefaad3b2023f569887a98bdbae4253f518c`，JUnit SHA-256 为 `147270dcbcef89273233ee48f950c4bdfbe7bc67694fcb9cf4602f0f603bfe72`，source SHA-256 为 `12ab84391e12723f565ae9c549a95b872859e379eea15a7a1510acde8b0f303d`。首个 runner 的 `PYTHONPATH` collection 错误、有效首轮 9 failed/29 passed、combined 78.68% 与 branch 76.38% 的后续 RED 都已保留。数值 Gate 已闭合，但仍须统一 security verifier 对 critical target、required nodeid 与 evidence binding 做最终复核。

### PKG-024 与 macOS package 最终刷新

新增 `PKG-024` installed-wheel 合同：同一个安装 wheel 和显式 asset root，在干净 CWD 与包含伪造 `t2l`、三个 checkpoint、manifest 的恶意 CWD 中分别执行真实短 MP3 Python API。两次 origin、LRC、status、spans、timebase 与 diagnostics 完全一致，网络和 `nltk.download` 被主动熔断。首轮测试因错误要求第三方 warning 为空失败，第二轮因预期 span end 写成 8 而真实冻结值为 7 失败；两者均作为测试 fixture/断言 RED 保留，未修改生产逻辑。

`PKG-024` 与 exact nodeid 加入 inventory 后，target + Spec Inventory 为 5 passed。最终 macOS package evidence 为 `/private/tmp/ai-auto-lrc-s18-package-macos-v3.WTKSTr/`：37 passed、1 Linux-only deselected、0 skip/fail，Gate `passed=true`。`package.xml` SHA-256 为 `562351c86726be2139620fa90e089714b9c6cffa5d796e5584db2fec805457e9`，`package-gate.json` SHA-256 为 `2743b7d6f756a94eff6f46b02f8fca67b49dc1bc2f36387e7082c3f66aa116c4`。该结果不替代 Linux package、security coverage 或最终 canonical。

## R1 walker 提取复审结论

Architect、Capture reviewer、Retention reviewer 与 Gate implementer 共同确认：外层函数 100% 不能代替 nested traversal enforcement body 100%，因此 R1 必须形成 coverage.py 可稳定定位的命名 seam，而不是扩大 omit、伪造 `scandir()` 不可能返回的名称或降低 critical 门槛。

- Capture 已提取 `_walk_receipt_closure`，保留 pinned dirfd、预算、状态和 callback 边界；targeted 12 passed，fresh full 278 passed，新 seam line/branch 均 100%。
- Retention 已提取 `_walk_retention_tree`，递归只传 descriptor、相对 prefix、共享预算与 snapshot state；fresh full 253 passed、1 个平台声明 skip，新 seam line/branch 均 100%，targeted 稳定性 20/20。
- 两条线均保留提取前 nested 缺口与新 symbol 不存在的首次 RED；均未 commit、push、清理或改动未授权 W1b-5c/5d/5e。
- Gate 线接续动作是把两个新 symbol 和四个 retention enforcement seams 写入 manifest，在新的 exclusive attempt 中重跑双 lane verifier。任何早于该 manifest/source/test 字节的绿色 coverage 都只能作为 raw evidence，不能声明 S18 通过。

完整数值、hash、artifact root 与剩余执行顺序统一记录在主方案第 17.8 节；本纪要不重复维护易漂移的详细状态。
