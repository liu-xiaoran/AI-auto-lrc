# S18 P1 可执行重构与资格化方案

> **当前执行入口：第 36.40 节；深层 JSON P1 与修复见第 36.37–36.38 节。** 修复后新九文件已核对；主代理fresh复验通过，但独立QA任务被执行环境中止，R2尚未验收。第36.39节保存新冻结清单，第36.28节用于合同导航；其他旧入口均为历史。R3仅有设计裁决，尚未执行。

> **2026-09-07 续接入口更正：先读第 36.28 节，再按其索引读取第 36 节合同与待办。当前 R2 修复中，独立 QA 仍为 NOT ACCEPTED。** 下方“第 21 节当前入口”是历史导航，不能作为本次恢复点；本更正不改写旧证据或升级验收状态。

> **当前入口：第 21 节 `S18-P1-PLAN-v1.8`。** 下方 v1.0 元数据和第 1–20 节均为 append-only 历史 checkpoint；不得据此从 B1、B3c、B3f-L unit/mutation 或已完成的 B3e-S 重新开始。

> 方案版本：`S18-P1-PLAN-v1.0`
> 冻结日期：2026-09-07
> 状态：**Approved for execution / implementation incomplete / S18、W1b-5b、Release No-go**
> 适用仓库：`AI-auto-lrc` 当前 dirty worktree
> Teams 记录：[`team-sessions/team-session-2026-09-07-3.md`](./team-sessions/team-session-2026-09-07-3.md)

## 1. 结论和使用规则

本文件是 2026-09-07 之后 S18 P1 加固、测试、双平台资格化和最终证据刷新的唯一可执行方案。`W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md` 第 17.11 节及更早章节继续保留为历史事实和设计来源；发生冲突时，先执行本文件中版本更高且带 hash 的入口，再回查历史证据，不从聊天记录推断状态。

当前决定不是立即扩大安全声明，而是先封闭 pytest 运行环境、绑定实际加载的证据插件、交叉校验 JUnit 与 pytest events，再锁定 ABA 声明上限。完成这些代码与合同测试后，必须冻结最终字节并刷新 macOS、Linux、package、canonical、host 和 sealed evidence。任何旧 Gate 只能称 historical，不得代签当前结果。

本方案只授权仓库内代码、测试和 Markdown 文档的实现与验证。以下动作不在授权范围：commit、push、创建 CI、upload/sync、签名、发布、W1b-5c export、W1b-5d archive/restore、W1b-5e delete/destruction。不得执行 `reset`、`checkout`、`clean` 或广泛删除；必须保留全部 modified/deleted/untracked 文件、根目录来源不明空文件 `./=`、所有 RED、fixture/runner error、flaky、retry、skip 和旧 attempt。

## 2. 当前事实基线

### 2.1 已完成且不得重做的切片

| 能力 | 当前结论 | 证据边界 |
|---|---|---|
| `S18-COV-015` target test endpoint drift | 已在隔离仓库通过真实 runner RED/GREEN | 只证明 before/after 字节不同时 fail closed，不证明 swap-and-restore 不可能 |
| `S18-SRC-001` frozen source bytes | verifier 以同一次有界读取供 AST/symbol 和 SHA-256 使用 | 只约束 verifier 单次读取，不冻结 pytest 的完整执行闭包 |
| `S18-JUNIT-001/002` canonical nodeid | classname 精确匹配 target module，name 采用可逆 canonical grammar | 不接受宽松路径归一化、控制字符、重复 `::` 或不平衡参数 ID |
| `S18-XFAIL-001` events 基础链路 | schema v3、events plugin、strict config、runner integration 与直接合同已实现 | 仍未封闭外部 pytest plugin/conftest 注入，结果一致性检查也不完整 |

### 2.2 当前可复核 checkpoint

当前合同 checkpoint 为 `95 passed in 17.04s`，JUnit 为 `/private/tmp/ai-auto-lrc-root-b3-review.xml`。它证明现有合同在当时输入下通过，不证明 pytest 启动环境已 hermetic，也不具备双平台资格化效力。

| 文件 | 当前 SHA-256 |
|---|---|
| `scripts/pytest_security_events.py` | `978e539bfa870c7e529a246f7837a0ecf442d254b197da0167731f6421c1fb81` |
| `scripts/run_security_coverage.sh` | `49c6f90a0301e5d19ba9aebaa202e9da486863c3c9a259d691bc4815b6e2c673` |
| `scripts/verify_security_coverage.py` | `b2ab72c7d7612e31e36451850a7d9af461533af91e1029ef9f43595e58bbba4a` |
| `packaging/security-coverage-policy.toml` | `d2eba68274188a9eaf13f62f208005c1690a9dbe625a090d23077e2acabb5453` |
| `packaging/security-coverage-manifest.json` | `890a5267c17f7b5d38c61f936624364958883af557da369d355beda94a3085eb` |
| `pyproject.toml` | `360d2c4ce8577af20d79518e8b02a17421595e7a348e7a39c8c6d817c3f153c5` |
| `tests/contract/test_security_coverage_gate.py` | `56ae653b60d7ada8432f51f4896af2f0ff6ae7204322f1344326976313838d55` |

开始执行前必须重算这些 hash。任一值不一致时，以工作区实际字节为事实，新建 preflight 记录，不修改本节历史 checkpoint。

### 2.3 新发现的阻断

Teams 独立安全审阅确认：

1. runner 没有使用 `--disable-plugin-autoload`，本机实际自动加载了未纳入证据闭包的 `typeguard._pytest_plugin`。
2. 即使增加 `--disable-plugin-autoload`，pytest 仍会处理 `PYTEST_PLUGINS`；外部插件可以在 collection 阶段移除 `xfail` marker，使 non-strict XPASS 被 events 记录为普通 PASS。
3. `PYTEST_ADDOPTS` 可以注入或覆盖 pytest 参数；祖先/仓库 `conftest.py` 也可改变 hook、marker、收集和测试结果。
4. 当前 verifier 只检查 `call_outcome` 的枚举值，没有要求它与 JUnit 状态一致。把 required PASS 的 events 改成 `not-run`、`failed` 或 `skipped` 并重绑定 hash，Gate 仍可能通过。
5. `scripts/` 当前是 namespace package。继承的 `PYTHONPATH` 或已安装的 regular `scripts` 包可能让 `-p scripts.pytest_security_events` 加载非本地模块，而 verifier 仍只 hash 仓库内同名文件。

因此，B3 只能标记为 **Implemented / qualification blocked**。不得用现有 95 passed 或旧 macOS/Linux Gate 跳过下列 P0/P1 修复。

## 3. 架构边界和信任模型

### 3.1 受信输入

Security coverage Gate 的受信闭包必须显式包含：

- target production source 和 exact target test；
- policy、manifest、runner、verifier、pytest config；
- pytest events plugin 的实际加载 bytes 和可验证身份；
- coverage JSON、raw coverage data、JUnit、pytest events、stdout/stderr；
- environment、command、run-manifest、Gate；
- run ID、runner、attempt、target、test file、时间和 artifact hashes。

操作系统环境、父进程环境变量、用户级 pytest entry points、任意 `conftest.py`、继承的 `PYTHONPATH` 和当前工作目录之外的同名 Python package 均视为不可信输入；runner 必须消除其影响或把其规范化值与真实解析结果纳入证据闭包。当前方案选择“消除影响”，避免证明无限环境状态。

### 3.2 数据流

```text
policy + manifest + checked-in bytes
  -> runner preflight identity/hash snapshot
  -> hermetic pytest argv + sanitized environment
  -> explicit pytest_cov + bound security-events plugin
  -> raw coverage/JUnit/events/logs
  -> runner endpoint hash snapshot
  -> run-manifest artifact closure
  -> read-only verifier independent recomputation
  -> deterministic Gate JSON
  -> independent reviewer outside producer directory
```

每条边都必须有可重算的输入、输出和稳定错误码。只有结果文件存在但缺少产生它的 command/environment/identity，不构成证据闭环。

### 3.3 最大声明

本轮完成后最多允许声明：runner 在一个经过环境清理、禁止自动插件和 conftest 加载、显式加载已绑定插件的 pytest 进程中执行；verifier 能检测受约束端点字节漂移，并能拒绝 required XFAIL/XPASS 以及 JUnit/events 结果不一致。

本轮仍禁止声明：`aba_safe`、`immutable_execution_snapshot`、`transactional_execution`、`power_loss_durable`、完整 same-UID 防护、真实 cross-UID 防护或整个 import graph/asset graph 不可变。真正 immutable execution snapshot 必须另立工作包。

## 4. 能力逐条设计

### 能力 C0 运行期端点漂移检测

- **目标**：target source/test、policy、manifest、runner、verifier、pytest config 和 events plugin 的 before/after hash 不同时 fail closed。
- **实现**：保留当前 schema v3 hash 闭包；任何 pending 切片不得移除 raw artifact 或把 after bytes 覆盖为 before bytes。
- **失败语义**：checked-in 输入漂移为 `EVIDENCE_BINDING_INVALID` 或 `EVIDENCE_TOOLCHAIN_BINDING_INVALID`，按现有字段职责保持稳定。
- **验收**：已有 COV/SRC/JUnit/XFAIL drift 合同继续通过；pending 改动后执行完整 Gate contracts。
- **边界**：before/after 相等不代表执行期间未发生 ABA。

### 能力 C1 Source 单次冻结与 canonical JUnit

- **目标**：verifier 不从同一路径取得两份可能不同的 source 事实；JUnit nodeid 只能由可逆、精确 grammar 生成。
- **实现**：保留 `_bounded_bytes` 一次读取后同时做 hash 和 AST/symbol；classname 必须精确等于 target test module；test name 只允许严格 `test_` 基名和可选平衡最外层参数 ID。
- **失败语义**：source identity 不一致 fail closed；非 canonical JUnit 使用 `JUNIT_NODEID_INVALID`。
- **验收**：现有 SRC/JUNIT RED/GREEN 与全部 grammar 参数合同通过。
- **边界**：不得恢复 dot/slash 宽松归一化以兼容伪造输入。

### 能力 C2 XFAIL 意图与结果 sidecar

- **目标**：识别 JUnit 无法区分的 non-strict XPASS，并让 required node 的任何 xfail intent/outcome 都不计为 success。
- **实现**：保留 `xfail_strict = true`；events plugin 在 collection/call 阶段记录 canonical nodeid、`xfail_marked`、`wasxfail`、`call_outcome`；使用 exclusive temp、`fsync`、atomic replace 和 mode `0600`。
- **失败语义**：required xfail/xpass 为 `REQUIRED_TEST_XFAILED`；events schema/scope/set 问题为 `PYTEST_EVENTS_INVALID`；配置问题为 `RUNNER_CONFIGURATION_INVALID`。
- **验收**：真实 pytest characterization 覆盖 XFAIL、strict XPASS、non-strict XPASS；真实 runner integration 保留 raw artifacts。
- **边界**：不能从 longrepr 或 JUnit 文案猜测 XPASS。

### 能力 C3 Hermetic pytest 启动

- **优先级**：P0，先于 ABA 和任何双平台重跑。
- **目标**：用户级 entry-point plugin、`PYTEST_PLUGINS`、`PYTEST_ADDOPTS`、祖先/仓库 conftest 不得改变 Security Gate 的 collection、marker、hook 或 outcome。
- **runner 改动**：
  1. recorded argv 精确包含一次 `--disable-plugin-autoload`；
  2. recorded argv 精确包含一次 `--noconftest`；
  3. 显式加载且只加载 `-p pytest_cov` 与 `-p scripts.pytest_security_events`；
  4. pytest 子进程环境删除 `PYTEST_PLUGINS`、`PYTEST_ADDOPTS`，并将 `PYTHONPATH` 设置为经裁决的最小值；
  5. coverage data 环境继续只对 pytest 子进程设置，不污染 verifier；
  6. command/environment 记录采用规范化后的环境语义，不记录 secret value。
- **verifier 改动**：
  1. 四个必需 token/pair 精确一次；
  2. 拒绝任意其它 `-p`、`-pNAME`、冲突 autoload/conftest token；
  3. 拒绝缺失、重复或变体拼写；
  4. 验证 recorded sanitized-environment contract，而不是信任自由文本声明。
- **稳定错误码**：所有 argv/environment isolation 违约统一为 `RUNNER_CONFIGURATION_INVALID`。
- **验收测试**：见 6.2；必须包含真实恶意 plugin 和真实祖先 conftest characterization，不能只改 command JSON。
- **回滚单元**：runner env/argv + verifier argv/env parser + 直接合同 + runner integration 一起回滚；不得牵连 SRC/JUnit。

### 能力 C4 pytest plugin 装载身份绑定

- **优先级**：P0，与 C3 同一波次但单独做 RED/GREEN。
- **目标**：pytest 实际 import 的 plugin 必须就是 runner preflight 和 verifier hash 的仓库文件。
- **候选方案**：
  - **方案 A，推荐**：将受控 plugin 放入一个 regular package，提供 `__init__.py`，runner 固定 repository root 的最小 `PYTHONPATH`，plugin 启动时把 `Path(__file__).resolve()` 和自身 SHA-256 写入 events 顶层 identity；verifier 要求 realpath 和 hash 精确匹配受约束文件。
  - **方案 B**：通过 pytest bootstrap plugin 从绝对路径显式加载模块，并记录加载路径/hash。只有能在真实 pytest 8.4.2、macOS、Linux 上稳定验证时才可采用。
- **禁止方案**：只新增 `scripts/__init__.py` 却不记录实际 `__file__`；只看命令中的 `-p` 名称；继承任意 `PYTHONPATH`。
- **schema 影响**：events 顶层和 environment/run-manifest/Gate 若新增 identity 字段，必须升级 schema，旧 schema 不能冒充 current。
- **稳定错误码**：加载 path/hash 与受约束文件不一致为 `EVIDENCE_TOOLCHAIN_BINDING_INVALID`；schema 缺失或非法为 `PYTEST_EVENTS_INVALID`。
- **验收测试**：同名外部 regular package 置于继承路径时仍加载仓库受控 plugin，或 runner 明确拒绝；伪造 events identity 在重绑定 artifact hash 后仍被拒绝。
- **决策 Gate**：实现前由 Developer 和 Security reviewer 在 A/B 中锁定一个；未锁定不得进入高成本资格化。

### 能力 C5 JUnit 与 events 结果一致性

- **优先级**：P1，C3/C4 后立即完成。
- **目标**：events 的 `call_outcome` 不再是“格式合法但语义未使用”的字段。
- **一致性矩阵**：

| JUnit 状态 | events 必须满足 | 允许的 required 结论 |
|---|---|---|
| passed | `call_outcome=passed` 且无 xfail intent/outcome | passed |
| failure | `call_outcome=failed`，或 strict XPASS 对应的受约束 xfail 语义 | failure / xfail-not-success |
| skipped | `call_outcome=skipped` 或 collection 阶段未运行的受约束表示 | skipped，不计 required success |
| xfail | `xfail_marked=true` 或 `wasxfail=true`，且 outcome 与 plugin characterization 一致 | xfail，不计 required success |
| JUnit case 存在但 events 为 `not-run` | 禁止 | `PYTEST_EVENTS_INVALID` |

- **实现**：先从 JUnit parser 返回 canonical `nodeid -> status`；events parser 返回 `nodeid -> semantic record`；在 Gate 汇合处做 exact case-set 和逐 node 一致性验证。
- **稳定错误码**：集合或状态不一致为 `PYTEST_EVENTS_INVALID`；required xfail 语义可同时产生 `REQUIRED_TEST_XFAILED`，failure 排序必须确定。
- **验收测试**：对 required JUnit PASS 参数化篡改 events 为 `not-run`、`failed`、`skipped`，重绑定 events/run-manifest hash 后均失败；再覆盖 failure/skipped/xfail 合法与非法组合。
- **边界**：不得把所有非 passed 一律映射成同一状态，必须保留 Gate 现有 required/non-required 失败语义。

### 能力 C6 ABA 声明边界

- **优先级**：P1，必须在 C3–C5 最终 schema 后执行。
- **目标**：用可执行合同阻止 endpoint equality 被包装成 immutable/transactional 证明。
- **实现**：不改生产执行模型；增加 swap-and-restore 隔离 runner fixture，确认 before/after SHA 相等时 endpoint Gate 可能通过，但 Gate/run-manifest/receipt/current docs 不得出现提升声明。
- **测试**：
  - `test_s18_runner_endpoint_hash_equality_does_not_claim_aba_safe`
  - `test_s18_p1_claim_boundary_rejects_unproven_execution_guarantees`
- **稳定边界**：当前 schema 没有 claims 字段时，只锁定公开输出和文档；不无条件把 `EVIDENCE_EXECUTION_SNAPSHOT_UNPROVEN` 加入正常 Gate failures。
- **未来工作包**：immutable snapshot 必须冻结 source、tests、fixtures/import graph、policy、manifest、config、runner、verifier、assets 及 dirty/untracked bytes，并从该快照实际执行。

### 能力 C7 规格清单与文档治理

- **目标**：实现事实、资格化事实和计划 ID 分离；所有本地 Markdown 链接有效；恢复入口唯一。
- **实现**：本文件不成为 `tests/spec_inventory.json` 的 `source_plan`；正式稳定 ID 仍只由既有 source plan 与 inventory 管理。主文档仅追加版本、路径、SHA-256 和状态指针。
- **验收**：`test_document_links.py`、`test_spec_inventory.py` 与 security contracts 联合通过。
- **失败处理**：不得为消除 extra ID 无依据扩大 `ignored_non_spec_tokens`；先修正文档中误入 source plan 的裸 token。

### 能力 C8 macOS Security qualification

- **前置**：C3–C7 完成，受约束字节冻结。
- **目标**：capture 与 retention 各连续三轮，exact required nodes、独立 raw artifact、独立 Gate 和 independent reverify。
- **执行**：每轮使用唯一 run ID 和不存在的 absolute artifact root；失败后新建 attempt，不覆盖。
- **平台边界**：仅允许 manifest 中精确声明的 Linux-device exclusion，nodeid 和 reason 必须完全匹配；不得增加宽泛 skip。
- **完成**：六个 lane 全部 current，critical line/branch 100%，文件阈值满足 policy，required collected/passed/skipped/deselected 精确，reviewer 结果一致。

### 能力 C9 Linux Security qualification

- **前置**：与 C8 相同；必须使用新的 exclusive attempt，旧 `attempt-003` 继续 historical。
- **目标**：验证 Linux exact nodes，包括 `renameat2(RENAME_NOREPLACE)`、`/proc/self/fd`、block/char device 和 per-required-runner 语义；Linux 为 0 skip。
- **环境**：沿用已锁定 image recipe 时先重算 Dockerfile/image digest；任一输入漂移则构建新 attempt，不复用旧 digest 结论。
- **完成**：双 lane Gate 和 independent reverify current；不得用 macOS 或 canonical 结果代签。

### 能力 C10 package 分平台资格化

- **目标**：准确表达不同平台证据强度。
- **macOS**：当前只要求 fresh functional/package lane；若没有 capture receipt，只能标 `functional-package-qualified`。
- **Linux**：执行 fresh capture-bound package lane，receipt、run ID、command/environment、wheelhouse manifest 和 Gate 完整绑定。
- **决策**：若 W1b-5b 要求双平台等强，先实现 macOS capture-bound runner；否则记录具名 accepted scope limit。不能把一强一弱合并成“双平台 package qualification”。
- **失效**：`pyproject.toml` 已变化，旧 package artifact 全部 historical。

### 能力 C11 canonical 与 host/static

- **canonical**：用 `capture_test_gate.py run --layer canonical` 重建 current image，执行 13/13 required golden，随后 archived-integrity 与 quality Gate 独立重算。
- **host**：执行 full pytest + JUnit、Ruff、compileall、所有 shell runner `bash -n`、`git diff --check`、文档链接和 Spec Inventory。
- **untracked 检查**：普通 `git diff --check` 不覆盖 untracked 文本；对本任务新增/修改的 untracked 文本使用 no-index 或等价 whitespace 检查，不扫描或改写未知二进制。
- **边界**：canonical 不能代签 host/package/Security，host green 也不能代签 canonical。

### 能力 C12 sealed evidence 与独立复核

- **目标**：在最终字节和所有平台结果之后生成最新 PASS/BLOCKED sealed evidence，并由 producer 目录外的 reviewer 只读重算。
- **producer**：只生成 raw 和 manifest，不自行修改历史 attempt。
- **reviewer**：从 raw artifacts 重算，不读取 producer 的裁决作为输入；PASS 期望 exit 0，BLOCKED 期望稳定非零并保留三个预期 blocker。
- **完成**：producer/reviewer 结论一致、hash 可复核、路径与 attempt 唯一；随后才进入 Teams W1b-5b Go/No-go 复审。

## 5. 待修改文件与责任边界

| 文件 | 允许的 pending 改动 | 不允许的顺手重构 |
|---|---|---|
| `scripts/run_security_coverage.sh` | hermetic argv、sanitized env、explicit plugins、identity capture | 不拆分其它 runner、不更改 coverage thresholds |
| `scripts/verify_security_coverage.py` | exact argv/env contract、plugin identity、JUnit/events consistency | 不做 R2–R5 大型函数重构 |
| `scripts/pytest_security_events.py` | 记录实际 plugin path/hash；仅在 schema 决策需要时改 | 不改变业务测试结果、不解析 longrepr 猜语义 |
| `scripts/__init__.py` 或专用 regular package | 只在选择 C4 方案 A 时新增 | 不把整个 scripts 目录改造成公开 API |
| `packaging/security-coverage-policy.toml` | 仅加入有界 identity/env limit 或 schema 必需字段 | 不放宽 required nodes、阈值或 exclusions |
| `packaging/security-coverage-manifest.json` | 仅在 plugin identity/新 exact contract 需要时升级 | 不删除既有 capability 或 runner pairing |
| `pyproject.toml` | 保留 `xfail_strict=true`；只做必需 pytest contract 调整 | 不更新依赖、不改 package 元数据 |
| `tests/contract/test_security_coverage_gate.py` | C3–C6 RED/GREEN、直接合同和真实 runner integration | 不用 test-only production switch |
| `tests/spec_inventory.json` | 原则上不改；只有 source plan 正式新增 stable IDs 才按治理流程改 | 不扩大 ignored list 掩盖误写 |
| `docs/*.md` | 完成后 append 新事实、hash、evidence 和入口 | 不覆盖历史章节、不把计划写成已完成 |

每个原子切片由 Developer 实现、QA 运行定向与完整合同、Security reviewer 做对抗篡改、Architect 判定声明边界。一个角色的自验不能替代独立 reviewer。

## 6. 测试用例设计

### 6.1 已有回归集

必须保留并复跑：

- `test_s18_runner_rejects_target_test_drift_during_pytest`
- `test_s18_manifest_symbol_and_hash_use_same_frozen_source_bytes`
- `test_s18_gate_rejects_forged_junit_classname`
- `test_s18_gate_rejects_noncanonical_junit_name`
- `test_s18_pytest_events_plugin_records_xfail_and_both_xpass_modes`
- `test_s18_runner_enforces_xfail_events_and_toolchain_drift`
- config、token、events schema、binding、case-set、artifact hash 的现有直接合同

### 6.2 C3 Hermetic runner 新增测试

| 建议 test name | Fixture | RED oracle | GREEN oracle |
|---|---|---|---|
| `test_s18_runner_disables_unbound_pytest_entrypoint_plugins` | 在环境中暴露可观察的 entry-point plugin | 修改前 plugin hook 被调用或改变结果 | runner command 含 exact disable token，plugin 未加载，raw evidence 完整 |
| `test_s18_runner_clears_pytest_plugins_environment_injection` | `PYTEST_PLUGINS=evil_plugin`，evil plugin 移除 xfail marker | 修改前 non-strict XPASS 被伪装为普通 PASS | evil plugin 未加载，required XPASS 仍 `REQUIRED_TEST_XFAILED` |
| `test_s18_runner_clears_pytest_addopts_injection` | `PYTEST_ADDOPTS` 注入额外 `-p`、deselect 或 config | 修改前 scope/结果可被改变 | 继承值无效且不回显；recorded argv 保持 canonical |
| `test_s18_runner_ignores_ancestor_and_repository_conftest` | 临时仓库父层与仓库内放置改变 marker/outcome 的 `conftest.py` | 修改前 hook 可生效 | `--noconftest` 下不加载，exact nodes 不变 |
| `test_s18_gate_requires_exact_hermetic_pytest_tokens` | 参数化删除、重复、变体、额外 `-p` | 旧 verifier 误接收至少一个 mutation | 全部 `RUNNER_CONFIGURATION_INVALID`，合法 command PASS |
| `test_s18_gate_requires_sanitized_pytest_environment_contract` | 篡改 environment 中的 normalized env state 并重绑 hash | 旧 verifier 误接收 | `RUNNER_CONFIGURATION_INVALID` |

真实 integration 必须调用真实 pytest，至少保留恶意 `PYTEST_PLUGINS` fixture 的首次 RED。direct JSON mutation 只能定位 verifier contract，不能替代 runner integration。

### 6.3 C4 Plugin identity 新增测试

| 建议 test name | Fixture | GREEN oracle |
|---|---|---|
| `test_s18_runner_loads_the_hash_bound_local_events_plugin` | 外部路径提供同名 `scripts.pytest_security_events` | events 中 resolved path/hash 等于隔离仓库受控文件；否则 runner/Gate fail closed |
| `test_s18_gate_rejects_pytest_plugin_loaded_identity_mismatch` | 修改 events identity 并重绑定 artifact hash | `EVIDENCE_TOOLCHAIN_BINDING_INVALID` 或 schema 约定的精确失败集合 |
| `test_s18_gate_rejects_missing_or_extra_plugin_identity_fields` | exact-key schema mutations | `PYTEST_EVENTS_INVALID` |

若选择方案 B，测试名可保留，但 fixture 必须验证绝对路径加载，而不是 module name 推断。

### 6.4 C5 JUnit/events 一致性测试

| 建议 test name | 参数 | 期望 |
|---|---|---|
| `test_s18_gate_rejects_junit_pass_with_nonpassing_pytest_event` | `not-run`、`failed`、`skipped` | 重绑所有 hash 后仍含 `PYTEST_EVENTS_INVALID` |
| `test_s18_gate_rejects_junit_failure_with_passing_unmarked_event` | normal failure + events passed/unmarked | `PYTEST_EVENTS_INVALID` |
| `test_s18_gate_rejects_junit_xfail_without_bound_xfail_event` | JUnit xfail + events unmarked/no wasxfail | `PYTEST_EVENTS_INVALID` |
| `test_s18_gate_accepts_characterized_junit_event_pairs` | normal pass/failure/skip、XFAIL、两种 XPASS | 只接受真实 plugin characterization 产生的组合；required 非成功仍 fail closed |

测试必须断言排序后的精确 failure 集合，避免自由文本和实现顺序漂移。

### 6.5 C6 ABA 与声明测试

| test name | Fixture | 期望 |
|---|---|---|
| `test_s18_runner_endpoint_hash_equality_does_not_claim_aba_safe` | pytest 期间替换 target test 后恢复原 bytes | before/after hash 相等；endpoint Gate 可按现合同通过；所有公开 artifact 无提升声明 |
| `test_s18_p1_claim_boundary_rejects_unproven_execution_guarantees` | 扫描 Gate/run-manifest/receipt/current docs 的 claim surface | 禁止四个提升声明；若未来 schema 接收 claims，则使用稳定 snapshot-unproven 拒绝语义 |

### 6.6 联合回归命令

定向切片完成后按以下顺序执行；所有输出写入新的 `/private/tmp` attempt，不能覆盖已有证据。

```bash
uv run --frozen --no-sync python -m pytest \
  tests/contract/test_security_coverage_gate.py \
  -q -p no:cacheprovider

uv run --frozen --no-sync python -m pytest \
  tests/contract/test_document_links.py \
  tests/contract/test_spec_inventory.py \
  tests/contract/test_security_coverage_gate.py \
  -q -p no:cacheprovider
```

在 B5 字节冻结前不得启动最终 macOS/Linux/package/canonical 高成本运行。

## 7. 执行 DAG 与并行策略

```text
B0 读取本文件，重算 current hashes，确认无活跃 attempt 写入
  -> B1 C3 hostile plugin/env/conftest RED
  -> B2 C3 hermetic runner GREEN + direct verifier contracts
  -> B3 C4 plugin identity 方案裁决
  -> B4 C4 identity RED/GREEN + schema migration
  -> B5 C5 JUnit/events consistency RED/GREEN
  -> B6 C6 ABA/claim boundary RED/GREEN
  -> B7 完整 contracts + docs links + Spec Inventory
  -> B8 冻结 runner/verifier/plugin/config/policy/manifest/target bytes
       -> B9 macOS Security 三轮双 lane + independent reverify
       -> B10 Linux 新 exclusive Security attempt + independent reverify
  -> B11 package 分平台 fresh qualification + scope-limit decision
  -> B12 canonical rebuild + 13/13 + archived-integrity/quality verify
  -> B13 host full/static/doc/inventory/untracked-whitespace
  -> B14 PASS/BLOCKED sealed evidence + producer 外独立重算
  -> B15 append current facts/hashes/evidence，Teams W1b-5b 复审
```

B1–B8 严格串行，避免 schema、runner 和 verifier 的相互漂移。B9 与 B10 可由不同平台并行，但必须使用不同 artifact root，且只有 B8 hash 完全一致时才可合并进入复审。B11、B12 可在 B9/B10 后并行准备，但 sealed evidence 必须等待所有声明范围内结果完成。

## 8. 原子切片和 RED GREEN 纪律

每个 pending 切片遵循同一模板：

1. 在隔离副本创建唯一 RED attempt，记录输入 hash、完整 argv、environment contract、stdout/stderr、JUnit/events/coverage 和预期失败。
2. 只修改该切片列出的生产文件和合同测试。
3. 先运行 exact new node，取得 GREEN；再运行 `test_security_coverage_gate.py` 全文件。
4. 若出现 fixture/runner error，保留该 attempt，新建下一个 attempt 修复；不得重写首次 RED。
5. 由非实现者执行对抗 mutation，确认不是通过放宽 policy、skip、required nodes 或 failure list 获得 GREEN。
6. 记录最终文件 SHA-256 和变更造成的证据失效范围。

切片回滚顺序固定为 C3 hermetic boot → C4 plugin identity → C5 outcome consistency → C6 ABA claims → qualification docs。不得跨切片回滚已经验证的 COV/SRC/JUnit 成果。

## 9. Evidence 目录和 attempt 规则

推荐最终根目录：

```text
/private/tmp/ai-auto-lrc-s18-final-qualification.<random>/
  B1-hermetic-red/attempt-001/
  B2-hermetic-green/attempt-001/
  B4-plugin-identity/attempt-001/
  B5-event-consistency/attempt-001/
  B6-aba-claims/attempt-001/
  B9-security-macos/attempt-001/
  B10-security-linux/attempt-001/
  B11-package-macos/attempt-001/
  B11-package-linux/attempt-001/
  B12-canonical/attempt-001/
  B13-host-static/attempt-001/
  B14-sealed/attempt-001/
  B14-independent-review/attempt-001/
```

目录必须由 runner 以 exclusive create 建立；存在即拒绝。失败、重试或 flaky 使用新的 `attempt-NNN`，不能删除或覆盖。跨平台 artifact 不复制成另一个 runner 的结果；独立 reviewer 从 producer 目录外读取只读副本或稳定 raw path。

## 10. 证据失效矩阵

| 最后变化 | 立即历史化 | 必须重跑 |
|---|---|---|
| runner/verifier/plugin/pytest config/policy/manifest/target source or test | 所有旧 macOS/Linux Security Gate 与 reverify | contracts、受影响 coverage、macOS 三轮、Linux 新 attempt |
| plugin identity/events schema | 所有旧 schema v3 bundle | direct contracts、runner integration、Security 双平台 |
| package source/test/config/runner/verifier | 对应平台 package receipt | 对应平台 fresh package lane |
| canonical source/formal input/oracle/recipe/image/verifier | 旧 canonical image/digest/13-node result | rebuild、13/13、independent verify |
| 仅 Markdown 或闭包外 contract test | 旧文档/合同计数 | links、Spec Inventory、相关 contracts；不得无依据重跑平台 Gate |
| sealed-evidence producer/reviewer | 旧 sealed bundle | sealed producer 和独立 reviewer；不得反向污染平台 raw artifacts |

## 11. 停止条件

出现以下任一情况立即停止当前波次并保留 attempt：

- required node missing、deselected、skip、xfail、failure 或 error；
- critical line/branch 非 100%，或全文件指标低于 policy；
- pytest 实际加载了未绑定 plugin/conftest，或实际 plugin identity 不可证明；
- JUnit/events case-set 或逐 node outcome 不一致；
- source/test/toolchain/config before/after drift；
- runner 与独立 verifier 结论不同；
- 同一 artifact root 已存在、attempt 被覆盖、run ID/runner/target binding 不一致；
- macOS/Linux/package/canonical/host 结果被尝试互相代签；
- 为取得 GREEN 而放宽 threshold、required node、failure code、skip/exclusion 或 sanitized environment contract。

停止后只允许定位原因、增加新 attempt 和做当前原子切片内的最小修复。涉及扩大声明、引入 immutable snapshot、增加外部服务或执行未授权 W1b-5c/5d/5e 时必须另行决策。

## 12. Definition of Done

- [ ] C3 恶意 entry-point、`PYTEST_PLUGINS`、`PYTEST_ADDOPTS`、ancestor/repository conftest 均有真实 RED/GREEN，runner 使用 canonical hermetic argv/env。
- [ ] C4 实际 plugin path/hash 与受约束文件闭合，namespace shadowing 不再可行或能稳定 fail closed。
- [ ] C5 JUnit/events case-set 和 outcome 逐 node 一致，篡改 `not-run`/`failed`/`skipped` 在重绑 hash 后仍被拒绝。
- [ ] C6 ABA/claim 合同通过，current 输出不含 immutable/transactional/ABA-safe/power-loss 提升声明。
- [ ] 当前字节下 security contracts、document links 和 Spec Inventory 全绿，未扩大 ignored list 掩盖问题。
- [ ] 最终受约束字节已冻结并记录 SHA-256；冻结后没有相关代码/config/test 漂移。
- [ ] macOS 三轮双 lane与 Linux 新 attempt 均 current，且各自 independent reverify 一致。
- [ ] package 按平台和 receipt 强度分层；双平台等强未证明时有明确 scope limit。
- [ ] canonical 13/13、host full、Ruff、compileall、bash-n、diff/whitespace、links/inventory 全部晚于最终变化。
- [ ] 最新 PASS/BLOCKED sealed evidence 已由 producer 目录外 reviewer 重算。
- [ ] S18 主方案、handoff、V2 执行计划和 Retention 入口已 append 最新事实、版本和方案 hash。
- [ ] Teams 完成 W1b-5b 复审；即使转 Go，W1b-5c/5d/5e 与 Release 仍保持独立授权边界。

## 13. 最短恢复路径

下一位执行者只做以下动作：

1. 读取本文件和四个入口文档的最新追加段，确认版本与 SHA-256 一致。
2. 查看是否有 active agent 或未完成 attempt，避免并发写入同一文件/目录。
3. 重算 2.2 的文件 hash；若已变化，追加 preflight 差异，不回退工作区。
4. 从 DAG 第一个未勾选步骤继续。当前默认起点是 B1：先固定 hostile environment/plugin/conftest RED，再实现 C3。
5. 在 B8 前只运行定向/合同/文档测试；最终平台证据只能在字节冻结后刷新。

不得从旧 17.10 的 A1 或 17.11 的 B3 重做已经完成的 COV/SRC/JUnit 探索；不得把当前 95 passed 写成 S18 已闭合。

## 14. v1.1 Teams 最终安全审阅增补

> 增补版本：`S18-P1-PLAN-v1.1`
> 规则：本节修正 v1.0 中对 XFAIL runner integration 强度的描述，并新增生成端资源上限和运行时工具链绑定；执行时以本节为准。

### 14.1 XFAIL 当前状态勘误

现有实现包含两类测试：真实 pytest 的 events plugin characterization，以及由 fake `uv` 复制预制 JUnit/events 的 runner wiring 测试。它能证明组件语义和接线，但**不能证明真实 runner** 在 required XFAIL、XPASS(strict=false)、XPASS(strict=true)、环境注入或 plugin 写出失败下取得预期 Gate。

因此 2.1 表中的 `S18-XFAIL-001` 当前准确状态为：**plugin characterization + fake runner wiring implemented；real-runner qualification blocked**。执行者必须补充隔离仓库真实 runner 测试，至少覆盖：

1. required XFAIL；
2. required XPASS strict false；
3. required XPASS strict true；
4. `PYTEST_PLUGINS`、`PYTEST_ADDOPTS`、entry-point plugin 和 `conftest.py` 注入；
5. events plugin 加载失败或 sessionfinish 写出失败。

这些真实 runner 测试应插入 DAG 的 B2–B4，并在 B7 完整 contracts 前完成。fake wiring 测试继续保留，不得删除，因为它提供确定性的 artifact/runner contract 定位。

### 14.2 JUnit 与 events 阶段语义补充

只记录单一 `call_outcome` 难以区分 setup/call/teardown failure 和 collection/skip。C5 实现前必须先用真实 pytest characterization 决定以下二选一：

- **推荐**：events schema 记录 setup、call、teardown 三阶段 outcome；verifier 根据 JUnit 状态检查允许组合。
- **最小方案**：保留 `call_outcome`，但对无法被 call-only 事实唯一证明的 setup/teardown 状态 fail closed，不做宽松猜测。

无论选择哪种，required JUnit PASS 必须有受约束的 call PASS 且无 xfail intent；`not-run` 绝不能算 success。schema 改动必须新版本化并历史化全部旧 schema v3 bundles。

### 14.3 能力 C13 Events 生成端资源界限

- **优先级**：P2，但必须在最终资格化前完成或形成具名 accepted defer；默认实施。
- **风险**：当前 4096 cases 和 8 MiB 上限只在 verifier 读取时生效；plugin 会先在内存收集全部 cases 和任意长度 nodeid，再序列化和写盘，可能在 verifier 前造成内存/磁盘放大。
- **实现**：policy 提供 max cases、max nodeid bytes 和 max serialized bytes；runner 以精确、唯一参数传给 plugin；plugin 在 collection 插入、字符串接收和写临时文件前分别检查并 fail closed。
- **错误语义**：plugin 受控拒绝应让 pytest 非零并保留 stderr；sidecar 缺失/不完整由 verifier 记录 `PYTEST_EVENTS_INVALID`，不得写半截 JSON 冒充成功。
- **测试**：exact-boundary pass、cases +1、nodeid bytes +1、serialized bytes +1、Unicode byte/character 差异、拒绝后无残留 temp、既有 attempt 不覆盖。
- **证据**：资源上限属于 policy/plugin/runner/verifier 闭包，任一变化历史化旧 Security Gate。

### 14.4 能力 C14 pytest 运行时工具链绑定

- **优先级**：P2，必须在 B8 最终字节冻结前裁决。
- **风险**：仅记录版本字符串不能证明实际安装的 pytest、pluggy、pytest-cov、coverage 代码与 lock 一致；`uv run --frozen --no-sync` 不会自动修复已漂移的现有环境。
- **最小闭合**：
  1. environment exact tools 增加 `pytest_cov`，并保留 pytest/coverage/Python/uv；
  2. `uv.lock` before/after SHA-256 进入 environment、run-manifest 和 verifier toolchain closure；
  3. preflight 独立读取 lock，验证 pytest、pytest-cov、coverage、pluggy 的安装版本与锁定解析一致；
  4. 版本查询失败或不一致时在 pytest 启动前 fail closed，不自动同步或联网修复环境。
- **更强方案**：若要声明实现字节级供应链绑定，另行设计已安装 distribution RECORD/hash 闭包；本轮最小闭合不得表述为 wheel/signature/SBOM provenance。
- **测试**：缺失 `pytest_cov` version、伪造版本、`uv.lock` before/after drift、lock 与 installed mismatch、command 未显式 `-p pytest_cov`，均稳定拒绝且不回显环境路径或配置内容。

### 14.5 最终审阅运行事实

- 合同复跑为 `95 passed in 29.93s`，Ruff、`py_compile`、`bash -n` 和 diff check 通过；这仍只是当前字节 checkpoint。
- 真实 macOS 双 lane 在未修复 hermeticity 的 runner 下 exit 0：capture `282/282`、retention `258/258`，artifact 位于 `/private/tmp/ai-auto-lrc-b3-review.3lwpwY/attempt-001`。由于 P0 注入路径存在，只能保留为诊断证据，不能作为最终资格化。
- Linux 临时容器中 capture `282/282`、required `16/16` 且 Gate 通过；retention 因非 root 容器缺少 `mknod` 权限出现 `PermissionError`。artifact 位于 `/private/tmp/ai-auto-lrc-b3-linux.hxjeFV/attempt-001`。该结果只证明 plugin/events 路径可运行，不能判定 Linux retention 失败或通过。
- plugin 注入反证位于 `/private/tmp/b3-plugin-review/`，必须作为 C3 首次 hostile RED 保留。

### 14.6 v1.1 DoD 增量

- [ ] 五类真实 runner XFAIL/hermetic 场景全部 RED/GREEN，不再以 fake wiring 替代。
- [ ] setup/call/teardown 与 JUnit 的一致性规则已通过真实 pytest characterization 固化，无法证明的组合 fail closed。
- [ ] events 生成端 case/nodeid/serialized-byte 上限在 verifier 前生效，并有边界测试。
- [ ] `pytest_cov`、`uv.lock` 和 installed-vs-lock preflight 纳入当前 toolchain closure，或形成具名 accepted defer 和最大声明。
- [ ] `/private/tmp/ai-auto-lrc-b3-review.3lwpwY/attempt-001` 与 `/private/tmp/ai-auto-lrc-b3-linux.hxjeFV/attempt-001` 只标 historical/diagnostic，没有被复制为最终资格化。

## 15. v1.2 架构可执行性勘误

> 当前有效版本：`S18-P1-PLAN-v1.2`
> 本节修正 ABA 的可机验 surface，并固化 Spec Inventory 和 pytest autoload 环境合同。

### 15.1 pytest autoload 双重关闭

C3 的 canonical 子进程环境除清理 `PYTEST_PLUGINS`、`PYTEST_ADDOPTS` 和固定最小 `PYTHONPATH` 外，还必须显式设置 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`；recorded argv 仍必须包含一次 `--disable-plugin-autoload`。环境变量和 argv 双重约束都由 verifier 检查，缺失、错误值或重复/冲突 token 统一为 `RUNNER_CONFIGURATION_INVALID`。

显式 coverage plugin 的最终 module name 必须由真实 pytest 8.4.2 表征锁定。当前已验证 `-p pytest_cov` 可在 macOS 生成 coverage/events；如果实现者选择 `pytest_cov.plugin`，必须先证明两平台行为、实际 `__file__` 和版本绑定一致，并同步 exact-token contracts，不能同时允许两个别名。

### 15.2 ABA 可机验 surface

Security coverage runner 只产生 `gate.json` 和 `run-manifest.json`，不产生 receipt；C6 不得断言不存在的 security receipt。可执行合同拆为两层：

1. **Security endpoint layer**：swap-and-restore fixture 只断言 source/test before/after hash 相等、当前 exact-key Gate/run-manifest schema 不新增提升 claim、endpoint Gate 仍按现有观察模型裁决。不得通过全文搜索否定词判断，因为当前文档会合法地解释这些术语。
2. **Capture receipt layer**：复用 `capture_test_gate.py verify --mode current-source` 的 typed 输出，必须精确为 `transactional=false`、`aba_excluded=false`、`observation_model=sequential-double-observation`；receipt `source.observation_limit` 必须保持 `before-and-after identity; transient restored changes may be unobserved`。把 `transactional`、`aba_excluded` 或 `qualification` 提升字段注入 `source` 后，现有 exact-shape verifier 必须拒绝。

对应既有可复用合同：

- `test_s15_verify_cli_reports_effective_observation_semantics`
- `test_s15_verify_receipt_at_rejects_invalid_source_observation_limit`
- `test_s17_verify_receipt_at_rejects_unknown_source_claims`

新增的 `test_s18_runner_endpoint_hash_equality_does_not_claim_aba_safe` 只覆盖第一层。建议的 `test_s18_p1_claim_boundary_rejects_unproven_execution_guarantees` 应验证上述 typed 字段、exact schema 和入口文档指向本方案；不得用“仓库全文不含 aba/transactional 等单词”作为 oracle。

### 15.3 Spec Inventory 当前结果与规则

联合回归首次 RED 为 `1 failed, 3 passed`：inventory 的 `source_plan` 是 `docs/AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md`，其中导航文字 `S18-COV-015` 被稳定 ID 正则截取为未登记的 `COV-015`。已用语义等价的非 ID 导航文字消歧，没有修改 `ignored_non_spec_tokens`。

修复后实际联合回归为：

```text
tests/contract/test_document_links.py
tests/contract/test_spec_inventory.py
tests/contract/test_security_coverage_gate.py
100 passed in 23.45s
```

该结果证明当前文档链接、inventory 和 security contracts 同时通过；后续任何代码或文档变化后仍需重跑。S18 主方案中的本地能力标签不是 V2 source plan 的产品规格 ID，不应为了收录它们扩大 inventory 范围。

### 15.4 当前恢复点

v1.0 的 B1 仍是默认起点，但执行时必须同时应用 v1.1 和 v1.2：真实 hostile runner RED → 双重关闭 autoload/环境注入 → plugin identity → 真实 XFAIL runner 三态 → JUnit/events 阶段一致性 → 生成端 limits 与工具链绑定 → typed ABA boundary → B7 联合回归 → B8 冻结。

## 16. v1.3 最终架构冻结增补

> 当前有效版本：`S18-P1-PLAN-v1.3`

### 16.1 Exact effective command

C3 的 runner 除 `--disable-plugin-autoload`、`--noconftest` 和两个显式 plugin 外，还必须用唯一 `-c pyproject.toml` 固定配置入口。verifier 不再只检查 required-token 子集，而是从 policy、target、runner、attempt 和 artifact paths 构造完整 expected argv，按顺序精确比较；只允许明确声明为顺序无关的字段规范化。

额外或重复的 `-p`、`-o`、`-c`、selection、deselect、marker、import mode、rootdir、confcutdir 和 test path 均为 `RUNNER_CONFIGURATION_INVALID`。command schema 必须记录 exact sanitized environment policy，包括 unset keys、fixed keys 和允许继承的非敏感最小集合；不得记录秘密环境变量值。

跨平台实现前必须锁定唯一 coverage plugin token。当前方案默认 `-p pytest_cov`，因为它已有真实 macOS 表征；任何切换到 `pytest_cov.plugin` 都需新 RED/GREEN、两平台真实 pytest 验证和 exact contract 更新。

### 16.2 JUnit events 一致性提升为 P0

C5 从 P1 提升为 P0。它能在 artifact hash 全部重绑定后造成 `passed=true` 假阳性，因此必须与 C3/C4 一起在任何 ABA、freeze 或平台资格化前完成。执行顺序固定为：先真实 characterize setup/call/teardown/skip/xfail，再冻结 schema 和合法矩阵，最后实现 verifier；不得边猜矩阵边写宽松兼容分支。

### 16.3 P1 工作包 traceability 决策门

当前 `100 passed` 中的 Spec Inventory 只证明 V2 产品规格 inventory；它不自动证明 P1 复合能力与 nodeid 可追踪。B7 前增加独立决策门：

- **推荐实施**：在现有 `tests/spec_inventory.json` 的下一 schema 增加 `work_package_specs.S18_P1`，保留产品 `source_plan`、274 个 ID 计数和 qualification 语义不变；P1 表项单独记录 full work-package ID、状态（planned/implemented/verified/qualified 分离）、runner scope 和 `nodeids[]`。
- 首批至少纳管 target-test drift、frozen source、JUnit classname/name、XFAIL、ABA 和 typed claim boundary；CAP-01 至 CAP-17 继续只由 security manifest 管理，不复制到第二权威源。
- 合同使用 full work-package ID grammar，不得用旧产品 ID regex 截尾；一个 ID 可映射多个显式参数化 nodeid，参数化测试必须提供稳定 `ids=`。
- **允许 defer 的条件**：具名 owner、风险接受者、截止条件和“P1 traceability 未机验”的最大声明全部写入 decision artifact。仅以产品 inventory green 代替不构成 defer。

这项工作不要求把 P1 ID 混入 V2 产品 `plan_id_ranges`，也不得把 `COV-015` 加入 ignored list。

### 16.4 Freeze ledger

B8 必须生成机器可读 freeze ledger，至少包含：

- **common closure**：capture/retention source、两个 target tests、policy、manifest、runner、verifier、pytest config、events plugin、security Gate contracts、产品/P1 inventory 与其 contracts、`uv.lock`、Git HEAD、dirty/untracked aggregate、explicit plugin allowlist、sanitized environment policy；
- **per-platform runtime**：实际 Python executable identity/version、pytest、pytest-cov、coverage、pluggy、uv version、system、machine 和平台 runner identity；
- **derived digest**：确定性 `common_closure_sha256` 和 `platform_runtime_sha256`。

macOS 与 Linux 的 `common_closure_sha256` 必须相同才可进入同一跨平台声明；runtime digest 应各自保留，不要求相同。任一 ledger 输入在 B9/B10 后变化，对应平台 attempt 立即历史化。

### 16.5 最终 DAG 替换段

```text
B0-B2 historical complete
  -> B3a retain XFAIL events core and fake wiring
  -> B3b hermetic env/autoload/config/exact argv
  -> B3c plugin loaded-identity binding
  -> B3d real pytest phase characterization + JUnit/events P0 consistency
  -> B3e real runner XFAIL/XPASS/injection/write-failure scenarios
  -> B3f producer-side events limits + runtime/lock binding
  -> B4a security swap/restore endpoint contract
  -> B4b capture typed claim boundary mapping
  -> B4c P1 traceability implement or accepted-defer artifact
  -> B7 contracts + product inventory + P1 traceability + doc links
  -> B8 common/per-platform freeze ledger
       -> B9 macOS three exclusive dual-lane roots + replay/recompute
       -> B10 Linux new exclusive attempt + replay/recompute
  -> B11 platform-scoped package decision and fresh lanes
  -> B12 canonical rebuild 13/13 + replay
  -> B13 host full/static/bash/diff
  -> B14 sealed PASS/BLOCKED + producer-external reviewer recompute
  -> B15 Teams W1b-5b decision + append current facts
  -> B16 post-doc links/P1 inventory/typed-claim/diff checks
```

B16 只验证文档和工作包治理，不因纯 docs 变化重跑 Security；若 B16 发现任何 current claim、P1 mapping 或 hash 指针错误，则 S18 仍不得完成。

## 17. v1.4 当前实现账本与后续执行冻结

> 当前有效版本：`S18-P1-PLAN-v1.4`
>
> 本节是当前唯一恢复段。第 1–16 节保留历史设计、RED 和中间裁决；若其 token、schema、状态或起点与本节冲突，以本节为准。文档继续 append-only，不回写旧 checkpoint。

### 17.1 Teams 复审结论与当前 Gate

2026-09-07 的 Architect、Security、Developer、QA 与 Skeptic 复审确认：v1.3 已建立总体 DAG，但 B3c 仍是候选设计，B3b/B3d 的实现事实没有进入 current ledger，B3e/B3f/B4 也缺少统一的可执行验收矩阵。因此本节锁定以下裁决：

1. B3c 采用 **absolute trusted bootstrap**；regular `scripts` package + plugin 自报 identity 不作为信任根。
2. 当前唯一 coverage plugin token 是 `pytest_cov.plugin`；第 4 节和第 16.1 节中的 `pytest_cov` 默认值历史化。`pytest_cov` alias、重复 token 或同时允许两个名字均为 `RUNNER_CONFIGURATION_INVALID`。
3. B3b 标记为 `implemented / host contracts green / cross-platform and complete evidence closure pending`。
4. B3d 标记为 `implemented / host characterization and contracts green / B3c schema changes will invalidate qualification evidence`。
5. B3c、B3e、B3f、B4a、B4b、B4c 仍为 `planned / not qualified`。
6. S18、W1b-5b、Release 继续 **No-go**；W1b-5c/5d/5e 仍未授权。不得启动最终 macOS/Linux/package/canonical/sealed qualification。

### 17.2 B3b Hermetic pytest 当前实现账本

当前 runner 已实现并由 verifier 精确约束：

- 子进程删除 `PYTEST_ADDOPTS`、`PYTEST_PLUGINS`；
- 固定 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 和独立 `COVERAGE_FILE`；
- pytest argv 精确包含一次 `-c pyproject.toml`、`--noconftest`、`-p no:cacheprovider`、`-p pytest_cov.plugin`、`-p scripts.pytest_security_events`、`-o xfail_strict=true`；
- command schema v2 记录 exact sanitized environment；
- verifier 构造完整 expected argv，不接受额外或重复 plugin、config、selection、deselect、marker 或 import-path token；
- pytest config 只允许 `addopts`、`markers`、`testpaths`、`xfail_strict` 四个 exact key。

当前实现字节与证据：

| 项目 | 当前事实 |
|---|---|
| runner SHA-256 | `49ba2e60062a19767340de92d23ab302f2c4a57212a465e3a9edc982901032b6` |
| hostile RED | `/private/tmp/ai-auto-lrc-s18-b3b-hostile-red.xNBKYf` |
| 首次 GREEN fixture error | `/private/tmp/ai-auto-lrc-s18-b3b-hostile-green.mgH0a0`，fake git 抢占目标测试内部 `git init`，必须保留 |
| hostile GREEN | `/private/tmp/ai-auto-lrc-s18-b3b-hostile-green2.KKIUQH`，`1 passed` |
| direct GREEN | `/private/tmp/ai-auto-lrc-s18-b3b-direct-green.yBxpsm`，`31 passed` |
| integration GREEN | `/private/tmp/ai-auto-lrc-s18-b3b-integration-green.8QhpDM`，`7 passed` |
| full GREEN | `/private/tmp/ai-auto-lrc-s18-b3b-full-green.mj2hGz`，`113 passed` |
| static fixture error | `/private/tmp/ai-auto-lrc-s18-b3b-static.UOJBd9`，误将 shell 输入 Ruff |
| static GREEN | `/private/tmp/ai-auto-lrc-s18-b3b-static2.i6MULc`，Python Ruff/compile、shell `bash -n`、`git diff --check` 通过 |

这些结果证明当前 host 上 `PYTEST_PLUGINS`、`PYTEST_ADDOPTS`、repository `conftest.py` 与 exact argv/env 的合同闭合；它们尚未证明真实 entry-point plugin、ancestor `conftest.py`、`sitecustomize`/`sys.modules`、coverage plugin shadow 或 Linux 行为。以上 `/private/tmp` 目录也不是最终 qualification bundle，不得标为 current platform evidence。

### 17.3 B3d 三阶段 events 与 JUnit 一致性账本

B3d 已选择并实现 pytest-events schema v2。它取代第 4 节 C2/C5 与第 14.2 节的 `call_outcome`/二选一设计：

```text
case = {
  nodeid: string,
  xfail_marked: boolean,
  phases: {
    setup: null | {outcome, wasxfail},
    call: null | {outcome, wasxfail},
    teardown: null | {outcome, wasxfail}
  }
}
```

`outcome` 只允许 pytest 实际报告的受约束枚举；未知阶段、重复阶段、非法 outcome、非法生命周期、case-set 漂移或 JUnit 映射矛盾统一包含 `PYTEST_EVENTS_INVALID`。required PASS 只在 setup/call/teardown 全部 `passed`、`xfail_marked=false` 且每阶段 `wasxfail=false` 时成立。XFAIL、non-strict XPASS 与 strict XPASS 继续使用 `REQUIRED_TEST_XFAILED`，不得因 JUnit suite totals 或单一 testcase 状态被提升为 success。

| 项目 | 当前事实 |
|---|---|
| events plugin SHA-256 | `3bf1dfeab0d099848e8eaa4145d77b1323b382457f89536c89dec81e6e74b05c` |
| verifier SHA-256 | `b7c30b596a8008b8f467918099475dee219d6bfe4c40b96471fc10378c9074f4` |
| security contract test SHA-256 | `f879f8b17fdc5860ba6bf15122680ba9f9d6b8f4e90a6439322d08688f9bd15b` |
| characterization root | `/private/tmp/ai-auto-lrc-b3d-char.E8FbWj/` |
| RED JUnit | `/private/tmp/ai-auto-lrc-b3d-red.nWAktq/junit.xml` |
| RED JUnit SHA-256 | `6062ee5c79c390bfdeac09c99934bb6283e3d6af6a409f0e42fcc7cad091077f` |
| 定向 GREEN | `27 passed, 103 deselected`；主任务独立复验为 `27 passed, 103 deselected in 1.32s` |
| 完整 GREEN | `130 passed in 263.68s` |
| GREEN JUnit | `/private/tmp/ai-auto-lrc-b3d-green.lj84KD/junit.xml` |
| GREEN JUnit SHA-256 | `9e87c50f5f3f16e304ca03214557134c192b76fe6155c1a73ddc3d540e9cd2e7` |

RED 已证明旧实现对 JUnit PASS + events `failed`/`skipped`/`not-run` 的三种假阳性返回 `failures=[]`。当前 GREEN 覆盖 normal pass/failure、setup failure/skip、call skip、teardown failure、XFAIL 与两类 XPASS。现有目录没有形成包含全部 sidecar、重绑定 manifest/Gate、stdout/stderr 和输入 hash 的完整 attempt closure；B3c 还会改变 runner/schema/toolchain closure，因此 B3d 只能称 host implementation green，不能称 platform qualified。

### 17.4 B3c Trusted plugin identity 最终架构

#### 17.4.1 Exact process contract

新增 `scripts/security_pytest_bootstrap.py`，runner 只允许以下启动骨架；所有路径均在运行前解析为 canonical absolute path：

```text
uv run --frozen --no-sync python -I -B
<ABS_REPO>/scripts/security_pytest_bootstrap.py
--plugin-identity=<ABS_TARGET>/plugin-identity.json
--
<canonical pytest argv>
```

`canonical pytest argv` 继续精确包含 `-c pyproject.toml`、`--noconftest`、`-p no:cacheprovider`、`-p pytest_cov.plugin`、`-p scripts.pytest_security_events`、`-o xfail_strict=true` 以及当前 target/coverage/JUnit/events 参数。verifier 按完整顺序构造 expected argv；去掉、重复、改序或替换 `-I`、`-B`、bootstrap path、identity arg、delimiter 或任一 pytest token 均为 `RUNNER_CONFIGURATION_INVALID`。

pytest 子进程环境必须删除 `PYTHONPATH`、`PYTHONHOME`、`PYTHONUSERBASE`、`UV_PROJECT_ENVIRONMENT`、`UV_PYTHON`、`PYTEST_PLUGINS`、`PYTEST_ADDOPTS`，并固定 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`。秘密值不得写入 command/environment。`-I` 是隔离主控制；`-B` 防止 Linux 只读 source root 上的 `.pyc` 写入。

#### 17.4.2 Bootstrap 装载顺序

bootstrap 必须按以下顺序 fail closed：

1. 在 repository root 尚未加入 `sys.path` 时解析同一运行时的 `pytest-cov` distribution metadata，从 RECORD 定位 `pytest_cov/plugin.py`，执行 no-follow stable read，并校验文件 identity、source SHA-256、distribution name/version、RECORD hash 和 `uv.lock` resolution。
2. 对仓库内 `scripts/pytest_security_events.py` 执行 no-follow stable read；hash 和 `compile`/`exec` 必须使用同一份 bytes，不得先 hash 路径再由普通 import 读取另一份 bytes。
3. 为 local plugin 构造 synthetic `scripts` parent 和 canonical module object；从受信 bytes 预装载两个 plugin。
4. 通过 `pytest.main(..., plugins=[...])` 注册预装载对象，同时保留 canonical `-p` token 作为可审计 command contract。
5. trusted guard 在 `pytest_configure` 逐项断言 `pluginmanager.get_plugin(canonical_name) is preloaded_module`；同名不同对象、重复注册或缺失对象立即中止。
6. 身份验证成功后才原子写 `plugin-identity.json`，随后把 canonical repository root 加入 `sys.path`，供目标测试导入 `scripts.capture_test_gate` 等仓库模块。

现场已确认单纯给现有命令增加 `python -I` 会使仓库 `scripts` 导入失败。因此不得先恢复 repository root 再装载插件，也不得以新增 `scripts/__init__.py` 代替 trusted bootstrap。

#### 17.4.3 Independent identity sidecar

`plugin-identity.json` 使用 exact-key schema v1：

```json
{
  "schema_version": 1,
  "run_id": "<exact run id>",
  "target": "capture|retention",
  "runner": "macos|linux",
  "attempt": 1,
  "python_isolated": true,
  "plugins": {
    "pytest_cov.plugin": {
      "file": "<canonical absolute path>",
      "sha256": "<64 lowercase hex>",
      "distribution_name": "pytest-cov",
      "distribution_version": "<uv.lock-bound version>",
      "record_sha256": "<64 lowercase hex>"
    },
    "scripts.pytest_security_events": {
      "file": "<canonical absolute repository path>",
      "sha256": "<64 lowercase hex>",
      "distribution_name": null,
      "distribution_version": null,
      "record_sha256": null
    }
  }
}
```

plugins map 只允许以上两个 key，且每个 key 精确一次。所有路径以 Python `Path.resolve(strict=True)` 结果记录；不得硬编码完整 site-packages 前缀。identity 独立于 events，禁止由被验证 plugin 自报后作为自身信任根。

identity 采用 mode `0600`、exclusive temp、`fsync`、atomic replace。bootstrap/guard/identity 写出失败时 pytest 必须非零；runner 仍保留 command、environment、stdout、stderr 和 runner-error，不得写半截 JSON、覆盖已有 attempt 或把 sidecar 缺失包装成 PASS。

#### 17.4.4 Verifier 与 evidence closure

`scripts/verify_security_coverage.py` 新增必需 `--plugin-identity`，对 sidecar 做独立 bounded read、duplicate-key 拒绝、exact schema/scope/path/hash/version/RECORD/registration binding 校验。local plugin 的 resolved path/hash 必须等于 checked-in bound bytes；pytest-cov 必须由同一 runtime 的 distribution metadata/RECORD 定位，source hash 与 RECORD、installed version 与 `uv.lock` 同时一致。

以下项目进入同一闭包：bootstrap bytes、events plugin bytes、pytest-cov source/RECORD/version、`plugin-identity.json`、`uv.lock`、sanitized environment 与 exact command。environment 记录 bootstrap/uv.lock before/after hash；run-manifest 升版并记录 `bootstrap_sha256`、`plugin_identity_sha256`、`uv_lock_sha256`；policy 增加 `plugin_identity_bytes` 上限；Gate 只输出已验证的 identity 摘要/hash，不复制不受约束路径文本。

稳定失败语义：

| 违约 | 稳定失败码 |
|---|---|
| identity missing/extra key、scope、path、hash、version、RECORD、registration object 不一致 | `PLUGIN_IDENTITY_INVALID` |
| `-I`/`-B`/bootstrap/identity arg/pytest argv 或 sanitized env 漂移 | `RUNNER_CONFIGURATION_INVALID` |
| bootstrap/pytest 非零 | `COMMAND_FAILED`，并保留底层受控错误 |
| bootstrap、identity artifact 或 `uv.lock` manifest/before-after 绑定漂移 | `EVIDENCE_TOOLCHAIN_BINDING_INVALID` |

B3c 的最小 toolchain closure 必须包含 pytest-cov version/RECORD 与 `uv.lock`；否则只能称 `origin-observed`，不能称 trusted identity。B3f 继续绑定更广的 pytest/pluggy/coverage/uv runtime，并实现 events producer limits。

#### 17.4.5 Rejected alternative 与 package 边界

新增 `scripts/__init__.py` 会把 checkout 中的 PEP 420 namespace 变成 regular package，改变 loader、`__file__`、namespace merge 和 shadowing 语义，却仍不能阻止 `sitecustomize`、预填 `sys.modules` 或 import hook。它最多是 defense-in-depth，本轮不采用，也不是 B3c 完成条件。

当前 setuptools `include = ["t2l*"]` 意图排除 private tooling，但 B3c 后的 package 回归必须分别证明 source-tree wheel、sdist、sdist-built-wheel 都不包含 `scripts/`、bootstrap 或 security private tooling；cold install 后 `importlib.util.find_spec("scripts") is None`。这些测试只证明 public package surface，不代签 loaded identity。

### 17.5 B3c 可执行测试矩阵

| 类别 | Fixture / mutation | RED oracle | GREEN oracle |
|---|---|---|---|
| local plugin shadow | `PYTHONPATH` 放置 external regular `scripts` package 和 sentinel | 旧 runner 加载或触发 sentinel | 新 bootstrap 下 sentinel 不存在；resolved path/hash 为仓库受控文件 |
| coverage plugin shadow | external fake `pytest_cov/plugin.py` 和 sentinel | 旧 import 路径可被劫持或身份无法证明 | 实际对象、RECORD、version、source hash 与同一 runtime/lock 一致 |
| startup injection | `sitecustomize.py` 预填 `sys.modules` | 旧 runner 使用预填对象或无法区分 | `-I` 阻止启动注入；guard 只接受预装载对象 |
| registration substitution | pluginmanager 注册同名不同对象 | identity 仍可自报 | guard 中止且不写 identity |
| identity schema | 缺/多 plugin、unknown/duplicate key、legacy schema | 旧 verifier 无独立 contract | `PLUGIN_IDENTITY_INVALID` |
| identity scope | swap run_id/target/runner/attempt 或跨 lane 复用 | artifact hash 重绑后误收 | `PLUGIN_IDENTITY_INVALID` |
| identity origin | path 互换、symlink/noncanonical/case 漂移、hash/RECORD/version 漂移 | 只看 module name 时误收 | `PLUGIN_IDENTITY_INVALID` |
| command | 去掉、重复、改序 `-I`、`-B`、bootstrap、identity arg、delimiter | 子集检查误收 | `RUNNER_CONFIGURATION_INVALID` |
| manifest binding | identity hash 不绑或重绑错误 sidecar；bootstrap/uv.lock before-after 漂移 | closure 不完整 | `EVIDENCE_TOOLCHAIN_BINDING_INVALID` |
| write failure | temp create、fsync、replace 或 final file 冲突 | sidecar 缺失原因丢失或被覆盖 | pytest/runner 非零，raw diagnostics 保留，旧 attempt 不变 |

真实 shadow RED/GREEN 必须同时跑 capture 与 retention；fake `uv` 复制预制 sidecar不能替代。host 定向实现通过后，macOS 与 Linux 各执行一个真实 pytest shadow GREEN：macOS 以 `Path.resolve()` 处理 `/tmp -> /private/tmp`，拒绝 `Scripts/scripts` 大小写歧义，不依赖 BSD 缺失的 `readlink -f`；Linux 使用 `-B` 支持只读 source root，只向 artifact directory 写入，按 RECORD membership 而非硬编码 site-packages 路径验证。

B3c 原子回滚单元为：bootstrap + runner argv/env + identity schema/writer + verifier parser/binding + policy/manifest schema + direct/real-runner tests。不得留下新 command 配旧 schema，或新 schema 配旧 verifier。

### 17.6 B3e B3f B4 验收矩阵

| 切片 | 必须取得的 RED / mutation | GREEN 完成条件 | 平台与证据边界 |
|---|---|---|---|
| B3e real runner | required XFAIL、XPASS strict false、XPASS strict true、entry-point plugin、`PYTEST_PLUGINS` marker removal、`PYTEST_ADDOPTS` plugin/selection、ancestor/repository conftest、plugin import failure、sessionfinish/atomic-write failure | 每场景有真实 pytest exit code、Gate exact failures、完整 raw；非成功不得被 JUnit/events 提升 | macOS/Linux 分栏；sidecar 缺失仍保留 command/environment/stdout/stderr/run-manifest 或 failure ledger |
| B3f producer limits | exact boundary、cases +1、nodeid bytes +1、serialized bytes +1、Unicode bytes/chars、零/负/重复 limit、temp residue、existing attempt | plugin 在收集、接收字符串和 serialize/write 前 fail closed；合法边界通过；无半截 sidecar | policy/plugin/runner/verifier 同一闭包；两平台各绑定 runtime digest |
| B3f runtime/lock | pytest、pytest-cov、coverage、pluggy、uv 缺失/伪造、lock duplicate/mismatch、version query failure、`uv.lock` before-after drift | installed versions/origins 与唯一 lock resolution 一致；失败不联网、不 auto-sync、不泄露秘密 | B3c 已先闭合 pytest-cov/RECORD；本切片补广义 runtime closure |
| B4a endpoint | pytest 期间 swap target source/test 后恢复；向 Gate/run-manifest 注入 forbidden positive claims | before/after 可相等但 exact schema 不出现提升 claim；endpoint observation 不被命名为 snapshot | macOS/Linux runner 各一次；这是 characterization，不是 ABA-safe 证明 |
| B4b typed claims | 逐字段翻转 `transactional`、`aba_excluded`、`observation_model`、`source.observation_limit`，注入 unknown qualification/claim key | 必须精确保持 `false`、`false`、`sequential-double-observation` 和现有 observation-limit；extra key 被 exact schema 拒绝 | platform-independent contract；不产生 security receipt |
| B4c traceability | full work-package ID grammar、状态混淆、runner scope、missing nodeid、unstable param id、duplicate/unknown ID、CAP 重复进入 inventory；defer artifact 缺 owner/risk acceptor/deadline/max claim | 实现 `work_package_specs.S18_P1` 或生成具名 accepted defer；产品 inventory 计数和 qualification 语义不变 | runner-scope 映射逐项验证；产品 inventory green 不代签 P1 traceability |

### 17.7 Exact acceptance commands 与 evidence layout

每个切片必须先运行新增 exact node，再跑 security contract 全文件，最后跑 links/product inventory/P1 traceability 联合回归。当前 B3b/B3d 可复验 node 为：

```bash
uv run --frozen --no-sync python -m pytest \
  tests/contract/test_security_coverage_gate.py::test_s18_gate_requires_exact_pytest_plugin_and_strict_tokens \
  tests/contract/test_security_coverage_gate.py::test_s18_gate_rejects_second_pytest_test_path \
  tests/contract/test_security_coverage_gate.py::test_s18_runner_ignores_hostile_pytest_environment_and_conftest \
  -q -p no:cacheprovider

uv run --frozen --no-sync python -m pytest \
  tests/contract/test_security_coverage_gate.py::test_s18_pytest_events_plugin_records_setup_call_and_teardown_reports \
  tests/contract/test_security_coverage_gate.py::test_s18_pytest_events_plugin_rejects_invalid_phase_reports \
  tests/contract/test_security_coverage_gate.py::test_s18_gate_accepts_characterized_nonpassing_phase_combinations \
  tests/contract/test_security_coverage_gate.py::test_s18_gate_rejects_junit_and_phase_status_disagreement \
  -q -p no:cacheprovider
```

正式 RED/GREEN 运行不能只复制以上交互命令。每条命令必须把 JUnit、stdout、stderr、exit code、exact argv、sanitized environment、input hash manifest 和 expected failure 写入唯一 attempt；RED、fixture error、retry、GREEN 分开，不覆盖。

```text
/private/tmp/ai-auto-lrc-s18-p1-v1.4.<random>/
  B3b-hermetic/{red,green}/attempt-NNN/
  B3c-plugin-identity/{red,green}/{macos,linux}/attempt-NNN/
  B3d-phase-consistency/{red,green}/{macos,linux}/attempt-NNN/
  B3e-real-runner/<scenario>/{macos,linux}/attempt-NNN/
  B3f-limits-runtime/{limits,runtime}/{macos,linux}/attempt-NNN/
  B4a-endpoint/{macos,linux}/attempt-NNN/
  B4b-typed-claims/attempt-NNN/
  B4c-traceability/attempt-NNN/
  B7-contracts-docs-inventory/attempt-NNN/
```

实现 B3c 之后至少执行：新增 B3c exact nodes；`tests/contract/test_security_coverage_gate.py` 全文件；Ruff/`py_compile`/`bash -n`/`git diff --check`；再执行：

```bash
uv run --frozen --no-sync python -m pytest \
  tests/contract/test_document_links.py \
  tests/contract/test_spec_inventory.py \
  tests/contract/test_security_coverage_gate.py \
  -q -p no:cacheprovider
```

文档命令仅用于确认导航与 inventory，不使旧 Security artifact 恢复资格。高成本平台资格化仍必须等待 B3c–B4、P1 traceability 和 freeze ledger 全部完成。

### 17.8 当前恢复顺序

下一位执行者从 **B3c trusted plugin identity RED** 开始，不再从第 13 节的 B1 或第 15.4 节的 hostile RED 恢复：

```text
B3b implemented host checkpoint
  -> B3c trusted bootstrap + identity RED/GREEN
  -> B3d rebase/reverify under final identity schema
  -> B3e real-runner scenario matrix
  -> B3f producer limits + broad runtime/lock binding
  -> B4a endpoint swap/restore
  -> B4b typed claim boundary
  -> B4c P1 traceability or named accepted defer
  -> B7 contracts/docs/product inventory/P1 traceability
  -> B8 common/per-platform freeze ledger
  -> B9+ final qualification sequence from section 16.5
```

common freeze ledger 必须显式包含 bootstrap bytes/hash、local plugin bytes、identity schema/allowlist、pytest-cov source/RECORD/version、identity artifact hash 和 `uv.lock`。per-platform runtime ledger 必须包含实际 Python executable、pytest/pytest-cov/coverage/pluggy/uv、pytest-cov resolved path/source hash/RECORD hash。只有两个 plugin 的 registration object、canonical path/hash、pytest-cov RECORD/lock 与 identity/run-manifest closure 全部通过，文档和 Gate 才可使用“trusted loaded identity”表述。

## 18. v1.5 当前字节账本 未决门和恢复胶囊

> 当前有效版本：`S18-P1-PLAN-v1.5`
>
> 本节是唯一恢复段。第 1–17 节保留历史设计、失败记录和当时 checkpoint；若状态、schema、字段含义、测试数、恢复起点或 DAG 冲突，以本节为准。
>
> Teams 裁决：[`team-sessions/team-session-2026-09-07-4.md`](./team-sessions/team-session-2026-09-07-4.md)，SHA-256 `91af3b63a6e9ec313c8ad343a71d993aa6e6339bdc5604fe6dfc0b1df12481c1`。

### 18.1 状态词汇与当前 DAG 账本

本方案从 v1.5 起强制区分四层状态：

| 状态 | 精确定义 |
|---|---|
| `implemented` | 代码或 schema 已存在，当前字节下直接合同通过 |
| `host-verified` | 当前宿主执行了完整目标合同，并保留 command、JUnit、日志和输入 hash；不等于真实 runner raw closure |
| `evidence-closed` | 真实 runner 场景的内部 raw attempt 在测试生命周期外仍可由独立 verifier 重算 |
| `platform-qualified` | 最终冻结字节下，指定平台、target、lane、重复次数、package scope 与 producer 外 reviewer 均满足资格化条件 |

普通 pytest 的外层 JUnit 只能支持 `host-verified`。它不能把实现提升为 `evidence-closed` 或 `platform-qualified`。

| 步骤 | 当前状态 | 继续条件 |
|---|---|---|
| B0–B2 | `historical complete` | 不重做探索；仅在最终 schema 下回归 |
| B3a | `implemented / host checkpoint` | 保留 events 核心和历史 fake wiring，不把 fake wiring 当真实资格化 |
| B3b | `implemented / host-verified` | 最终 schema 后回归；平台证据未闭合 |
| B3c | `implemented / host-verified` | 先修正 RECORD 字段语义和 identity 发布规范；Linux 与持久 raw closure 未完成 |
| B3d | `rebased / host-verified` | 已在 B3c schema 下通过当前合同；最终 B3f schema 后再次回归 |
| B3e | `core scenarios implemented / host-verified` | 先加稳定 scenario ID，再补完整 hostile 矩阵和双平台持久 raw evidence |
| B3e-S | `next / not implemented` | 冻结稳定参数 ID、scenario manifest 和 P1 ID authority |
| B3f-L | `planned / not implemented` | producer limits RED/GREEN |
| B3f-R | `planned / not implemented` | single-runtime、no-site、offline 与 named core runtime/lock RED/GREEN |
| B4a | `planned / not implemented` | B4b typed surface 冻结后做 swap-and-restore characterization |
| B4b | `planned / foundation exists` | 把现有 capture typed negative claims 纳入 S18 P1 exact contract |
| B4c | `planned / not implemented` | `work_package_specs.S18_P1`，或真正获得具名人类风险接受的 defer |
| B5–B6 | `retired as independent steps` | 当前职责已并入 B7；不得从旧 DAG 恢复 |
| B7 | `blocked` | B3f、B4a、B4b、B4c 全部完成后跑 contracts/docs/product/P1 inventory |
| B8 | `blocked` | B7 通过后生成 common freeze ledger |
| B9–B10 | `blocked` | B8 后分别做 macOS/Linux runtime ledger 和最终 Security qualification |
| B11–B16 | `blocked` | 按 package → canonical → host → sealed → Teams → post-doc 顺序执行 |

当前唯一实现起点是 **B3e-S**，不是第 17.8 节的 B3c RED。高成本平台资格化继续晚于 B3f、B4、B7 和 B8。

### 18.2 当前字节和独立复验事实

当前分支为 `improve-inference-reliability`，HEAD 为 `db8e714eceb73e88496f0f705a56cd8c571e0278`。工作区是 dirty worktree；下列值只锚定当时路径字节，不是 Git blob、commit 或可移植发布锚点。

| 文件 | SHA-256 |
|---|---|
| `scripts/security_pytest_bootstrap.py` | `b31849ebfff8d6928b69075543c3f7514df7a19155fb38d53081d8767fe7ade5` |
| `scripts/run_security_coverage.sh` | `904548293f7b25dcd33ccbb13db9e21419665e8eecf31654c12e6b2bf414d983` |
| `scripts/verify_security_coverage.py` | `10ffbc2218749f67eeefb11770ec88e1b5480be3c7fdb21e22b6d0eb3702ed59` |
| `scripts/pytest_security_events.py` | `3bf1dfeab0d099848e8eaa4145d77b1323b382457f89536c89dec81e6e74b05c` |
| `packaging/security-coverage-policy.toml` | `4e65814a391a8032e534a6cfc63e2a48e4d0ea0b60b3c128cd1f8b5f0f31e81d` |
| `packaging/security-coverage-manifest.json` | `890a5267c17f7b5d38c61f936624364958883af557da369d355beda94a3085eb` |
| `tests/contract/test_security_coverage_gate.py` | `9fdb69babacc38f6031652c01f4fec9ea36fa309aa7453523ddf771f8b2c89cc` |
| `pyproject.toml` | `360d2c4ce8577af20d79518e8b02a17421595e7a348e7a39c8c6d817c3f153c5` |
| `uv.lock` | `3f20a0afdd3bfa055c7a98c413b305e84aa0a3ad1af2c254b094bb8440cd31eb` |

主任务在以上当前字节下独立执行：

```text
179 passed in 188.03s
JUnit: /private/tmp/ai-auto-lrc-s18-b3e-independent.qoUBLg/junit.xml
JUnit SHA-256: 301877aa83187b409e0490088f65bd393a042077b9ac0dd939cc90acee6644e3
```

该目录只有外层 pytest JUnit；B3e 测试内部真实 runner attempt 来自 pytest `tmp_path`，测试结束后不能作为持久 raw bundle 独立复算。因此它是 `host-verified` checkpoint，不是正式 Security attempt。

必须保留以下演进记录，不以最终 GREEN 覆盖：

| 路径 | 语义 | 完整 closure |
|---|---|---|
| `/private/tmp/ai-auto-lrc-b3c-register-proto.nhGzdN` | bootstrap 原型 shell quoting/SyntaxError | 否，fixture error |
| `/private/tmp/ai-auto-lrc-b3c-register-proto-retry.2XaPgD` | 未关闭 autoload 时 pytest-cov 重复注册 characterization | 否，characterization |
| `/private/tmp/ai-auto-lrc-b3c-register-proto-retry2.Jq8IVg` | trusted object 注册成功原型 | 否，prototype |
| `/private/tmp/ai-auto-lrc-b3c-shadow-red-artifacts.v1` | 旧 runner 被外部 regular `scripts` 劫持的 RED | 否，RED |
| `/private/tmp/ai-auto-lrc-b3c-shadow-red-artifacts.v2` | 共享工作区并发读取中间态导致的 runner error | 否，concurrency fixture error |
| `/private/tmp/ai-auto-lrc-s18-b3c-shadow-red.ijFOzY` | 实现阶段可信 shadow RED | 否，implementation RED |
| `/private/tmp/ai-auto-lrc-b3c-hostile-realuv-artifacts.v1` | B3c 当前宿主真实 uv 双 lane GREEN | 是，host diagnostic；非最终平台资格化 |
| `/private/tmp/ai-auto-lrc-b3c-hostile-realuv-review.v1` | producer 外 verifier replay | 是，host diagnostic |
| `/private/tmp/ai-auto-lrc-s18-b3e-red.97hryN` | B3e shell fixture error | 否 |
| `/private/tmp/ai-auto-lrc-s18-b3e-first-run.bXf64O` | identity-write 首次实际 exit `3` 的 RED | 否，characterization |
| `/private/tmp/ai-auto-lrc-s18-b3e-retry.INZE9E` | B3e 修正后的 retry | 否 |
| `/private/tmp/ai-auto-lrc-s18-b3e-green.ivIWZR` | B3e 核心 7 场景 GREEN | 否，测试生命周期证据 |
| `/private/tmp/ai-auto-lrc-s18-b3c-b3e-directed.lq6MMv` | B3c+B3e 定向 `73 passed` | 否，host contract |
| `/private/tmp/ai-auto-lrc-s18-b3e-independent.qoUBLg` | 当前全文件 `179 passed` 外层 JUnit | 否，host contract |

所有 `/private/tmp` 路径都易失。路径缺失只能记为 `historical evidence unavailable`；不能推导该执行从未发生，不能据此覆盖旧记录、擅自重跑高成本资格化或提升声明。

### 18.3 B3c 当前实现修正与最大声明

B3c 已实现全局清理 `PYTHONPATH`、`PYTHONHOME`、`PYTHONUSERBASE`、`UV_PROJECT_ENVIRONMENT`、`UV_PYTHON`、`PYTEST_PLUGINS`、`PYTEST_ADDOPTS`，并以 `python -I -B`、stable-read 同一 bytes、synthetic `scripts` parent、预装载 plugin object 和 `pytest_configure` object identity guard 运行。B3c 的主机实现和合同已通过，但第 17.4 节有两项历史表述必须纠正：

1. 当前 identity writer 是 `exclusive same-directory temp + mode 0600 + file fsync + os.link no-replace publication + temp unlink + directory fsync`，不是 atomic replace。已有 final 必须保持 bytes/mode 不变并失败。
2. schema v1 的 `record_sha256` 实际语义是 `pytest_cov/plugin.py` 的 RECORD entry digest，不是整份 `.dist-info/RECORD` 文件 SHA-256。它不能证明 installed tree 来自 `uv.lock` 中的特定 wheel。

B3f-R 必须把歧义字段拆为 `entries[path].sha256` 和 `record_file_sha256`，并增加 `metadata_sha256`、lock package digest 与 runtime descriptor。若不捕获 bounded RECORD/METADATA bytes，独立 replay 仍依赖验证时 live site-packages 未变化，不能称 self-contained 或 portable evidence。

B3f-R 完成前，最大允许声明为：

```text
the two registered pytest plugin objects were bound to the observed plugin bytes
```

中文表述仅允许“当前宿主上的两个已注册 pytest plugin object 与观察到的入口字节完成绑定”。禁止称 supply-chain trusted、wheel verified、complete import graph frozen、single-runtime qualified 或 dual-platform qualified。

### 18.4 B3e 稳定场景合同和剩余矩阵

当前已实现的 7 个核心真实 pytest 场景为：

| 稳定 scenario ID | mutation | pytest exit | Gate / raw oracle |
|---|---|---:|---|
| `B3E-XFAIL-REQUIRED` | required node `xfail(run=False)` | 0 | capture Gate `REQUIRED_TEST_XFAILED`；retention PASS |
| `B3E-XPASS-NONSTRICT` | required node non-strict XPASS | 0 | capture Gate `REQUIRED_TEST_XFAILED`；retention PASS |
| `B3E-XPASS-STRICT` | required node strict XPASS | 1 | capture Gate `COMMAND_FAILED, REQUIRED_TEST_XFAILED`；retention PASS |
| `B3E-PLUGIN-IMPORT` | capture local events plugin import failure | 2 | EARLY raw + runner-error；无 Gate；retention PASS |
| `B3E-IDENTITY-CONFLICT` | capture identity final 已存在 | 3 | 原 marker bytes 与 mode `0600` 不变；无 Gate；retention PASS |
| `B3E-SESSIONFINISH-FAILURE` | capture sessionfinish 受控失败 | 2 | Gate `COMMAND_FAILED, PYTEST_EVENTS_INVALID`；retention PASS |
| `B3E-EVENTS-PUBLISH-FAILURE` | `_atomic_write` 调用前受控失败 | 2 | Gate `COMMAND_FAILED, PYTEST_EVENTS_INVALID`；retention PASS |

现有参数化测试必须在 B3e-S 增加显式 `ids=`；禁止继续使用 `[xfail-0-expected_failures0]` 一类由位置生成的 nodeid。建议新增 `tests/fixtures/security_coverage_scenarios.json`，每条 exact schema 包含：

```text
scenario_id
mutation
target
runner
expected_pytest_exit
expected_outer_exit
expected_gate_failures
required_artifacts
forbidden_artifacts
expected_sentinel_state
```

artifact profile 固定为：

- `FULL`：coverage raw/JSON、JUnit、events、plugin identity、environment、command、run-manifest、Gate、stdout/stderr、verifier stderr。
- `NO_EVENTS`：`FULL` 去掉 events；Gate 必须存在。
- `EARLY`：environment、command、stdout/stderr、`runner-error.json`；无 Gate。runner-error 记录 stage、reason code、子进程 exit、present/missing artifact 和 present hashes。

正式 B3e 仍须拆分并补齐：

- 临时离线环境中真实安装的 `pytest11` hostile distribution，不污染共享 `.venv`；
- `PYTEST_PLUGINS` plugin 实际移除 required xfail marker；
- `PYTEST_ADDOPTS` 的 plugin 注入与 `-k`、`-m`、`--deselect`、第二 test path selection 注入；
- ancestor `conftest.py` 与 repository `conftest.py` 独立场景；
- local plugin import、identity conflict、sessionfinish 和 events publication 的 capture/retention 对称注入；
- macOS 与 Linux 各自持久 inner raw attempt 和独立 replay。

`B3E-EVENTS-PUBLISH-FAILURE` 只证明调用前失败传播，不证明 temp/open/write-zero/fsync/link/unlink/directory-fsync；这些属于 B3f-L writer fault matrix。

### 18.5 B3f-L Producer limits 原子设计

B3f-L 只约束 events plugin 自身保存的 case/nodeid 状态与 sidecar 序列化/写出。它不约束 pytest 在 hook 前已经完成的 collection、pytest 总内存、CPU、其他 plugin 或测试进程资源，不得写成“pytest 全进程资源有界”。

policy 升为 schema v2，并以同一字段同时驱动 producer 与 verifier：

```toml
schema_version = 2

[limits]
testcases = 4096
pytest_events_nodeid_bytes = 4096
pytest_events_bytes = 8388608
```

runner 从已绑定 policy 读取，并在每个 pytest argv 中各精确传一次：

```text
--security-max-cases=4096
--security-max-nodeid-bytes=4096
--security-max-events-bytes=8388608
```

缺失、重复、改序、非十进制、零、负数、超过 plugin hard ceiling 或与 policy 不同，统一为 `RUNNER_CONFIGURATION_INVALID`。events sidecar 升 schema v3，增加 exact `limits` 对象；不写 `serialized_bytes` 自引用字段，verifier 直接观察原始 artifact byte length。

producer 算法按以下顺序 fail closed：

1. configure 解析唯一正十进制参数，并与 policy 和内建 hard ceiling 比较。
2. 每个 item 插入前先做字符数快速上界，再以 `nodeid.encode("utf-8", "strict")` 按原始 UTF-8 bytes 检查；不做 Unicode normalization。
3. 在第 `max_cases + 1` 个 item 插入前拒绝。
4. 对实际 nodeid 构造三阶段最坏 case 模板，使用 compact canonical JSON、`ensure_ascii=False` 计算累计预算，避免 O(n²) 全量重序列化。
5. report 只更新已收集 case；未知 case、未知或重复 phase、非法 outcome 立即失败，不保存 longrepr、exception 或任意 pytest object。
6. sessionfinish 使用 `sort_keys=True`、`separators=(",", ":")`、`ensure_ascii=False` 和单尾换行；写前再次检查实际 bytes。
7. writer 使用 same-directory exclusive temp、mode `0600`、完整写循环、`os.write()==0` 立即失败、file fsync、`os.link(temp, final)` no-replace、temp unlink、directory fsync；未发布异常路径清理本次 temp，绝不删除旧 temp、旧 final 或旧 attempt。

producer 固定 stderr 标识为 `PYTEST_EVENTS_CONFIGURATION_INVALID` 或 `PYTEST_EVENTS_LIMIT_EXCEEDED`。进入 sessionfinish 后的无 events 失败，Gate 精确为 `COMMAND_FAILED, PYTEST_EVENTS_INVALID`；collection/config 期真实 pytest exit 先做一次 characterization，冻结后所有 runner、scenario manifest 和合同使用同一数字，不为迎合预设数字改写 pytest 行为。

B3f-L 的 RED/GREEN 节点统一采用 `test_s18_b3f_events_limits_real_runner[<stable-id>-capture|retention]`，最少包含：

| ID | fixture | GREEN oracle |
|---|---|---|
| `B3F-L-001-cases-boundary` | exact 4096 cases | FULL；Gate PASS |
| `B3F-L-002-cases-plus-one` | 4097 cases | 插入前失败；无 events/temp；raw error 保留 |
| `B3F-L-003-nodeid-boundary` | UTF-8 bytes exact 4096 | FULL；Gate PASS |
| `B3F-L-004-nodeid-plus-one` | ASCII 与多字节 Unicode 分别 4097 bytes | 进入 case map 前失败；证明 bytes 而非 chars |
| `B3F-L-005-serialized-boundary` | 完整 compact JSON 加尾换行 exact 8 MiB | sidecar 实际大小等于 limit；Gate PASS |
| `B3F-L-006-serialized-plus-one` | 最终 bytes 为 8 MiB + 1 | 写盘前失败；NO_EVENTS；无 temp |
| `B3F-L-007-invalid-limit` | zero、negative、non-decimal、overflow | configure fail closed；EARLY |
| `B3F-L-008-duplicate-limit` | 三个 option 各重复一次 | `RUNNER_CONFIGURATION_INVALID`；EARLY |
| `B3F-L-009-write-zero` | `os.write()` 返回 0 | 非零退出、不挂死、无本次 temp/final |
| `B3F-L-010-existing-final` | 预置 final bytes/mode | 原 final 不变；no-replace failure |
| `B3F-L-011-writer-fault-matrix` | temp open、write exception/zero、file fsync、link、temp unlink、directory open/fsync | 每例校验 final、temp、raw、exit、Gate/code；旧 artifact 不删 |
| `B3F-L-012-existing-attempt` | 预置 attempt marker | runner input invalid；目录逐字节不变 |

exact boundary 单元测试和真实 runner 故障测试必须同时存在；不能只 mock verifier，也不能为每个 4096-case边界重复运行完整双 lane 导致测试不可控。

### 18.6 B3f-R Single runtime 与 lock binding

B3f-R 采用 named core runtime closure：`pytest`、`pytest-cov`、`coverage`、`pluggy`、`uv` 和当前 Python。Python stdlib、OS 动态库、证书库、内核、完整依赖图与 wheel provenance不在本切片声明内。

runner 只解析一次 canonical absolute uv executable，后续所有 Python helper、bootstrap、pytest 和 verifier 使用同一骨架：

```text
<ABS_UV> run --offline --frozen --no-sync python -I -S -B
```

禁止使用 PATH 中裸 `python3` 或后续重新解析 `uv`。`-I -S -B` 必须各精确一次。`-S` 会使 Python 3.11 的 `sys.prefix` 回到 base prefix；bootstrap 必须从未 resolve 的 absolute `sys.executable` 和 stable-read 的 `pyvenv.cfg` 推导唯一 venv site-packages，手工 `sys.path.append()`，禁止 `site.addsitedir()` 和执行 `.pth`。

uv binary 的 before/after SHA 可由该 resolved uv 启动的隔离 Python自测；这是 endpoint consistency evidence，不把 uv 自测变成供应链信任根。runner 同时绑定 `uv --version`、`uv.lock` before/after 和 exact `--offline --frozen --no-sync`；网络、sync 或 lock/cache 写入均为失败。

`plugin-identity.json` 升 schema v2，不新增第二个重叠 runtime sidecar。它至少包含：

```text
runtime.executable
runtime.executable_realpath
runtime.venv_root
runtime.base_prefix
runtime.implementation
runtime.version
runtime.cache_tag
runtime.system
runtime.machine
runtime.isolated = true
runtime.no_site = true
runtime.dont_write_bytecode = true
uv.path / uv.version / uv.sha256
uv_lock_sha256
distributions.pytest
distributions.pytest-cov
distributions.coverage
distributions.pluggy
```

每个 distribution 必须做 PEP 503 name 规范化，并要求当前 site-packages 和 `uv.lock` 中各恰好一个对象；多 resolution 暂不宽松猜测，出现歧义即失败，直到另立 exact marker resolver contract。每个对象绑定 installed version、canonical dist-info、whole METADATA hash、whole RECORD hash、required entry hash/size 和 canonical lock package object digest。

最小 required entries：

```text
pytest/__init__.py
pluggy/__init__.py
coverage/__init__.py
pytest_cov/__init__.py
pytest_cov/plugin.py
```

RECORD 拒绝绝对路径、`..`、重复路径、非 SHA-256 或缺 size；stable-read 的同一 entry bytes 用于 hash/size 和 compile/exec。pytest-cov 额外验证 lock dependency 包含 pytest、coverage、pluggy；pytest 依赖包含 pluggy。identity、environment、command、run-manifest 与 Gate 的 exact schema 同步升级；Gate provenance 只能是 `installed-record-consistent`。

稳定失败码：runtime schema、scope、origin、version、distribution 或 lock resolution 错误为 `RUNTIME_IDENTITY_INVALID`；artifact hash、uv/lock before-after 漂移为 `EVIDENCE_TOOLCHAIN_BINDING_INVALID`；exact argv/env 漂移为 `RUNNER_CONFIGURATION_INVALID`。

B3f-R 的合同最少包含：

| ID | mutation | GREEN oracle |
|---|---|---|
| `B3F-R-001-exact-runtime` | 当前真实 `.venv` | identity v2 exact schema；同平台双 lane runtime digest 相同 |
| `B3F-R-002-no-site` | trusted site `.pth` 与 `sitecustomize` sentinel | sentinel 不存在；只加入已验证 site root |
| `B3F-R-003-missing-duplicate-dist` | 四个 distribution 分别 missing/normalized duplicate | pytest 未启动；`RUNTIME_IDENTITY_INVALID` |
| `B3F-R-004-lock-resolution` | missing、duplicate、version mismatch | 不 auto-sync、不联网；runtime invalid |
| `B3F-R-005-origin-entry` | fake module、symlink/noncanonical origin、entry hash/size drift | runtime invalid |
| `B3F-R-006-metadata-record` | whole METADATA/RECORD drift，入口行不变 | runtime invalid；证明整文件已绑定 |
| `B3F-R-007-dependency-edge` | 删除 pytest-cov/pytest required dependency edge | runtime invalid |
| `B3F-R-008-uv-endpoint` | PATH fake uv、version query failure、binary before/after drift | 固定 ABS_UV；失败不泄露 secret |
| `B3F-R-009-lock-drift` | pytest 期间改变 `uv.lock` | `EVIDENCE_TOOLCHAIN_BINDING_INVALID` |
| `B3F-R-010-command-flags` | 去掉/重复/改序 `-I -S -B --offline --frozen --no-sync` | `RUNNER_CONFIGURATION_INVALID` |
| `B3F-R-011-runtime-rebind` | 跨 lane/attempt 复用 identity，或改内容并重绑 manifest | scope/runtime invalid；不能仅靠 hash 绕过 |
| `B3F-R-012-no-wheel-claim` | 注入 `wheel-verified` provenance | exact schema拒绝；Gate只允许 installed-record-consistent |

B3f-R 完成后仍禁止声称 wheel/signature/SBOM provenance、完整 import graph、same-UID 防篡改、power-loss durability 或跨 UID 安全。

### 18.7 B4 typed claims ABA 和 P1 traceability

B4b 先于 B4a 冻结 claim authority：

- Security Gate/run-manifest 不增加 `claims`、`qualification`、`transactional`、`aba_excluded` 或 snapshot 字段；extra key 由 exact schema拒绝。
- Capture current-source CLI 是 typed negative claim 的公开面，精确保持 `effective_qualification=diagnostic-current-source-observation`、`transactional=false`、`aba_excluded=false`、`observation_model=sequential-double-observation`。
- receipt 的 `source.observation_limit` 保持“before-and-after identity; transient restored changes may be unobserved”的精确语义。
- receipt `source` 的 unknown key、`transactional`、`aba_excluded` 和 `qualification` 继续由 exact-shape verifier拒绝。
- 独立 Gate consumer/sealed reviewer 再验证 top-level exact keys；producer 不得仅验证自己生成的 claim。

B4a swap-and-restore 必须使用独立 handshake，证明 target bytes 在 pytest 期间确实替换并恢复。预期 characterization 是 before/after hash 相等且 endpoint Gate 可能通过；GREEN 只表示盲区被观察且声明边界正确，不表示 ABA 防护、snapshot 或 transaction 已实现。

B4c 将 `tests/spec_inventory.json` 升级为独立 `work_package_specs.S18_P1` 区域，同时保持 V2 产品 source plan、274 项计数和 qualification 语义不变。推荐字段：

```text
full_id
implementation_status
verification_status
qualification_status
runner_scope
target_scope
nodeids[]
evidence_refs[]
```

full ID grammar 固定为 `^S18-[A-Z][A-Z0-9]*-[0-9]{3}$`；CAP-01 至 CAP-17 继续只在 security manifest，不能复制进 P1 inventory 或 ignored list。一个 ID 可映射多个显式稳定参数 nodeid。

defer 只有在获得具名人类决定后才成立，必须含 owner、risk acceptor、decision date、deadline 或解除条件、approval reference、最大允许声明和是否继续阻断 W1b-5b。执行代理不得自行填写“已接受”并继续；未获授权时状态保持 blocker。

### 18.8 Freeze ledger 和最终执行顺序

B8 拆为生命周期明确的三个动作：

1. B8a 在最终 common bytes 后生成一次 common ledger。ledger producer/verifier 自身也进入闭包；payload canonical digest 不含自身 digest 字段。
2. B9/B10 在 macOS/Linux 各自 runner 内生成 per-platform runtime ledger，并把 common/runtime digest 绑定进每个 run-manifest。
3. 两平台完成后执行 cross-platform comparator，只要求 common digest 相同；runtime digest 分平台保留，不要求相同。

dirty/untracked 不得只记录不透明 aggregate；common ledger 包含排序后的 path/type/mode/size/hash manifest，并明确表示 symlink、deleted path、特殊文件和根 `./=`。ledger 只证明列举输入一致，不是 immutable snapshot、transaction 或可重建 Git checkout。

最终恢复 DAG：

```text
current B3c/B3d/B3e host checkpoint
  -> B3e-S stable scenario IDs + P1 ID authority
  -> B3c RECORD field semantics + no-replace contract correction
  -> B3f-L producer-limit RED/GREEN
  -> B3f-R single-runtime/runtime-lock/offline RED/GREEN
  -> replay B3c/B3d under final schemas
  -> complete B3e hostile matrix on macOS/Linux with persistent raw + replay
  -> B4b typed claim authority
  -> B4a swap/restore characterization + independent claim validation
  -> B4c machine traceability or genuinely authorized defer
  -> B7 full contracts/docs/product/P1 inventory
  -> B8a common freeze ledger
  -> B9 macOS three exclusive dual-lane roots + runtime ledger + replay
  -> B10 Linux new exclusive attempt + runtime ledger + replay
  -> cross-platform common digest comparison
  -> B11 package scoped fresh qualification
  -> B12 canonical rebuild 13/13 + replay
  -> B13 host full/static/bash/diff
  -> B14 sealed PASS/BLOCKED + producer-external reviewer recompute
  -> B15 Teams W1b-5b decision + append facts
  -> B16 post-doc links/P1 inventory/typed-claim/diff checks
```

### 18.9 可复制恢复命令 停止条件和授权边界

恢复者先确认没有其他 agent 或 shell 正在写上述文件或 attempt，然后执行只读 preflight：

```bash
pwd
git branch --show-current
git rev-parse HEAD
git status --short
shasum -a 256 \
  docs/S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md \
  docs/team-sessions/team-session-2026-09-07-4.md \
  scripts/security_pytest_bootstrap.py \
  scripts/run_security_coverage.sh \
  scripts/verify_security_coverage.py \
  scripts/pytest_security_events.py \
  packaging/security-coverage-policy.toml \
  packaging/security-coverage-manifest.json \
  tests/contract/test_security_coverage_gate.py \
  pyproject.toml uv.lock
```

任何 hash、branch、HEAD、active writer 或文件类型不一致，只追加 preflight 差异；不 reset、checkout、clean、删除、恢复旧 v1 文件或覆盖 attempt。当前低成本复验命令为：

```bash
bash -n scripts/run_security_coverage.sh
uv run --offline --frozen --no-sync python -m py_compile \
  scripts/security_pytest_bootstrap.py \
  scripts/verify_security_coverage.py \
  tests/contract/test_security_coverage_gate.py
uv run --offline --frozen --no-sync ruff check \
  scripts/security_pytest_bootstrap.py \
  scripts/verify_security_coverage.py \
  tests/contract/test_security_coverage_gate.py
uv run --offline --frozen --no-sync python -m pytest \
  tests/contract/test_security_coverage_gate.py \
  -q -p no:cacheprovider --junitxml=<new-exclusive-path>/junit.xml
uv run --offline --frozen --no-sync python -m pytest \
  tests/contract/test_document_links.py \
  tests/contract/test_spec_inventory.py \
  -q -p no:cacheprovider
git diff --check
```

占位符 `<new-exclusive-path>` 必须替换为 `mktemp -d` 创建的唯一目录；不得复用本节历史路径。上述命令只能复验 host contracts 和文档，不创建 platform qualification。

B7 关闭前新增 `test_s18_current_resume_pointers_agree`：对 Handoff、V2 主计划、Retention、S18 主资格方案和本文件首屏 current pointer 逐一校验最新版本、权威相对路径、SHA-256、section、唯一下一步与 Gate 完全一致。旧 checkpoint 允许保留，但 latest pointer 缺失、互相冲突或仍指向已完成步骤必须失败；现有 link test 不能替代该语义合同。

出现下列任一情况立即停止当前波次并保留 raw：required missing/deselected/skip/xfail/failure/error；critical line/branch 非 100%；producer limit 或 runtime identity 失败；command/environment/toolchain/config/source/test before-after drift；runner 与 verifier不一致；attempt 已存在；跨平台/common digest 不一致；为取得 GREEN 而放宽阈值、失败码、required node、stable ID、schema、skip 或环境清理合同。

当前最终声明上限为：macOS 当前宿主的 179 个 security contracts 在本节列出的工作区字节下通过；B3c 和 B3e 核心已有 host 实现与合同证据。它不证明 Linux、正式平台 evidence closure、完整 runtime provenance、无网络执行、pytest 总资源有界、ABA-safe、immutable snapshot、transactional execution、power-loss durability、same-UID/cross-UID 防护或发布资格。

S18、W1b-5b、Release 继续 **No-go**。commit、push、创建 CI、upload/sync、签名、发布、archive、restore、delete、destruction、W1b-5c/5d/5e 和 supply-chain 扩权均未获授权。

## 19. v1.6 B3e-S 稳定场景和 P1 ID 权威

> 当前有效版本：`S18-P1-PLAN-v1.6`
>
> 本节实施第 18.1 节的 B3e-S。第 18 节继续定义 B3f 及后续架构；若恢复起点或 B3e-S 状态冲突，以本节为准。

### 19.1 Required XFAIL 行为裁决

B3e required XFAIL fixture 保留当前真实执行语义：`pytest.mark.xfail(strict=False)` 后仍执行 required test 的业务 exercise，并以受控 `pytest.fail()` 形成 XFAIL。第 18.4 节的 `xfail(run=False)` 描述历史化。

选择 `run=True + controlled failure` 的原因是：B3e 要同时观察实际测试执行、coverage/JUnit/events 和 Gate，不应通过 `run=False` 绕过 required test body 或引入与 XFAIL 意图无关的 coverage 缺口。non-strict XPASS 与 strict XPASS 继续执行同一业务 exercise，仅改变 mark strictness 和受控结果。

### 19.2 首批 S18 P1 exact ID authority

机器权威固定在 `tests/contract/test_spec_inventory.py` 的 `S18_P1_ID_AUTHORITY`，不能从 `tests/spec_inventory.json` 自身、scenario manifest、全仓 `S18-*` 扫描结果或 security capability manifest 推导。inventory 只能声明并精确等于该集合。

| Full ID | 当前 implementation | 当前 verification | 当前 qualification | Exact nodeids |
|---|---|---|---|---|
| `S18-ABA-001` | planned | unverified | unqualified | 空；B4a 前不得伪造 future node |
| `S18-CLAIM-001` | planned | unverified | unqualified | 空；B4b 前不得伪造 future node |
| `S18-COV-015` | implemented | unverified | unqualified | `tests/contract/test_security_coverage_gate.py::test_s18_runner_rejects_target_test_drift_during_pytest` |
| `S18-JUNIT-001` | implemented | unverified | unqualified | `tests/contract/test_security_coverage_gate.py::test_s18_gate_rejects_forged_junit_classname` |
| `S18-JUNIT-002` | implemented | unverified | unqualified | `tests/contract/test_security_coverage_gate.py::test_s18_gate_rejects_noncanonical_junit_name` |
| `S18-SRC-001` | implemented | unverified | unqualified | `tests/contract/test_security_coverage_gate.py::test_s18_manifest_symbol_and_hash_use_same_frozen_source_bytes` |
| `S18-XFAIL-001` | implemented core | unverified | unqualified | 三个 `B3E-XFAIL-REQUIRED`、`B3E-XPASS-NONSTRICT`、`B3E-XPASS-STRICT` exact parameter node |

旧 `S18-P1-CLAIM-001` 不符合 `^S18-[A-Z][A-Z0-9]*-[0-9]{3}$`，只保留为历史 token；其 canonical replacement 为 `S18-CLAIM-001`。CAP-01 至 CAP-17 继续只由 `packaging/security-coverage-manifest.json` 管理，禁止进入 P1 inventory 或 `ignored_non_spec_tokens`。首批 authority 也不自动吸收其他语法合法的 COV/TOOL ID。

### 19.3 Inventory schema 和状态单调性

`tests/spec_inventory.json` 顶层升为 schema v3，产品 source plan、274 项计数、ranges、qualification levels、overrides、implemented 映射和 `ignored_non_spec_tokens` 保持原义。新增 `work_package_specs.S18_P1` schema v1，package exact keys 为：

```text
schema_version
source_plan
source_section
specs
```

每个 spec exact keys 为：

```text
full_id
implementation_status
verification_status
qualification_status
runner_scope
target_scope
nodeids
evidence_refs
```

状态枚举和单调约束：

- `implementation_status = planned | implemented`；planned 必须 `nodeids=[]`、unverified、unqualified。
- `verification_status = unverified | host-verified | evidence-closed`；implemented 必须映射至少一个 exact collected nodeid。
- `host-verified` 至少绑定 `host-bundle` evidence；`evidence-closed` 至少绑定 `raw-run-manifest` 与 `independent-review`。
- `qualification_status = unqualified | platform-qualified`；platform-qualified 必须先 evidence-closed 并绑定 `qualification-ledger`。
- 同一 nodeid 禁止无声明地代签多个 P1 ID；参数化 nodeid 必须包含显式稳定 `ids=`。
- 当前首次迁移全部保持 unverified/unqualified，因为第 18.2 节的外层 JUnit 不满足 inventory 的 typed evidence reference 要求；不得因“179 passed”自动晋级。

`evidence_refs` 每项 exact keys 为 `kind/path/sha256`，kind 只允许 `host-bundle`、`raw-run-manifest`、`independent-review`、`qualification-ledger`。历史外部路径消失不反推执行从未发生，但任何状态晋级必须由相应 verifier 或 ledger 校验实际 bytes。

### 19.4 B3e-S 与首批 P1 authority 实施事实

本轮已完成 B3e-S 的稳定场景身份和首批 P1 current-state machine authority；它们是 host contract checkpoint，不是 verification/qualification evidence closure。

#### B3e-S

- `tests/fixtures/security_coverage_scenarios.json` 使用 exact 13-key schema，冻结 7 个 `implemented / host-contract` 场景与 13 个 `planned / macos-linux` 场景。
- 7 个 implemented scenario 的 ID、mutation、outcome、outer nodeid、victim nodeid、artifact exact allowlist 和 sentinel 均由测试代码中的独立 authority 约束；planned 场景不伪造 future node、exit 或 artifact。
- actual artifact 必须与 allowlist 精确相等；额外 `runner-error.json` 或任意未知 artifact 会失败。
- required XFAIL 按第 19.1 节执行真实业务 exercise，再以受控 `pytest.fail()` 形成 XFAIL；不使用会跳过 test body 的 `run=False`。
- 最终定向复验：`24 passed, 172 deselected in 15.48s`，JUnit `/private/tmp/ai-auto-lrc-s18-b3e-s-directed.ebcVJd/junit.xml`，SHA-256 `795bc22476a3b86ec439bd94e9fcc353a7be3dc55afb9e99b549e573848d9bb3`。
- 独立全 security contract：`196 passed in 192.41s`，JUnit `/private/tmp/ai-auto-lrc-s18-b3e-s-p1-independent.8XMYGa/junit.xml`，SHA-256 `f46becb8dd4828156cc134ea2d37b68673d72aa5d0a5c2935389716a0fa94338`。

#### P1 current-state authority

- `tests/spec_inventory.json` 顶层为 schema v3，新增 `work_package_specs.S18_P1` schema v1；V2 产品 source plan、274 项计数、ranges、qualification levels/overrides、implemented mapping 与 `ignored_non_spec_tokens=["SHA-256"]` 未改变语义。
- `tests/contract/test_spec_inventory.py` 的 `S18_P1_AUTHORITY` 独立冻结每个 ID 的 implementation、verification、qualification、runner scope、target scope、exact nodeids 和 exact evidence refs。仅修改 inventory 的 cross-ID node swap、arbitrary collected node 替换、scope 漂移、status downgrade 或 evidence-ref 晋级均会失败。
- collection authority 在隔离 Python 中运行，清除 `PYTHONHOME`、`PYTHONPATH`、`PYTHONUSERBASE`、`PYTEST_ADDOPTS`、`PYTEST_PLUGINS`，设置 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1`，固定 `--disable-plugin-autoload --noconftest -c <repository pyproject.toml> -p no:cacheprovider`，并从内联受信 collector 的结构化 sidecar 读取真实 `session.items`；pytest stdout 不再是 node authority。
- 未经 authority 接受的 evidence record 在读取任意 path 前即拒绝。对 authority 当前接受的非空 evidence ref，reader 要求原始 canonical spelling、存在、非 symlink、regular file、最多 8 MiB，以 `O_NOFOLLOW/O_NONBLOCK` descriptor 有界读取，同 fd 前后 identity/size/mtime 不漂移，并对冻结 bytes 重算 SHA-256。
- 当前 7 项全部保持 `unverified/unqualified`，`evidence_refs=[]`；本轮 JUnit 和 `/private/tmp` attempt 只作为实施过程记录，不写入 current inventory，也不触发状态晋级。
- 最终 inventory contract：`41 passed in 8.56s`，JUnit `/private/tmp/ai-auto-lrc-s18-p1-spec-final2.jYn8nZ/junit.xml`，SHA-256 `d57ca2957455535d3612590b17fae8aa8ed585487aa13a6e999a636f79df87c4`。

最终受约束文件 SHA-256：

| 文件 | SHA-256 |
|---|---|
| `tests/contract/test_security_coverage_gate.py` | `ded1d46792c3a0d7385c62dec8fb652cef7deb0d263fd0107c3258d2a5643833` |
| `tests/fixtures/security_coverage_scenarios.json` | `3ac8a7147854c128c7be2e7b79718f446a9b07a3aae5521dec56a59512549704` |
| `tests/contract/test_spec_inventory.py` | `2bfa4d75235947e2726c8ffe1ba8f90f1c1233a6496965c5cb109d37706e019a` |
| `tests/spec_inventory.json` | `d98286d076c4357af10080c58568e044ba54b3f6f2eaa3118967a6b6c6b6ba68` |

### 19.5 RED、retry 与 runner-error 保留账本

| 阶段 | 结果 | 保留位置 |
|---|---|---|
| B3e-S 初始 RED | 2 failed | `/private/tmp/ai-auto-lrc-s18-b3e-s-red.WQ95pw` |
| B3e-S fixture retry | 10 passed, 1 failed | `/private/tmp/ai-auto-lrc-s18-b3e-s-retry.Cze7QK` |
| B3e-S Ruff retry | `RUF043` | `/private/tmp/ai-auto-lrc-s18-b3e-s-retry-ruff.hdnuDx` |
| B3e-S authority RED | 3 failed | `/private/tmp/ai-auto-lrc-s18-b3e-s-authority-red.LdocuF` |
| B3e-S exact-artifact RED | 1 failed | `/private/tmp/ai-auto-lrc-s18-b3e-s-artifact-red.mkKAhr` |
| P1 fixture error | pytest collection exit 4，缺少 `pytest` import | `/private/tmp/ai-auto-lrc-s18-p1-inventory-red.Y7HFY8` |
| P1 schema RED | schema v2 不等于 v3 | `/private/tmp/ai-auto-lrc-s18-p1-inventory-red-retry.gKdGlW` |
| P1 documented-ID RED | `S18-ABA-001` 未写入方案 | `/private/tmp/ai-auto-lrc-s18-p1-inventory-doc-red.pPP1Ie` |
| P1 anti-self-signing RED | 5 failed；四类 record drift 与 synthetic evidence 未被拒绝 | `/private/tmp/ai-auto-lrc-s18-p1-anti-self-red.u0FSoE` |
| P1 首次 anti-self retry | 8 passed, 2 failed；missing/noncanonical 抛出未规范化异常 | `/private/tmp/ai-auto-lrc-s18-p1-anti-self-green.rUln6Z` |
| P1 anti-self GREEN | 10 passed | `/private/tmp/ai-auto-lrc-s18-p1-anti-self-green2.53dQGQ` |
| P1 hostile collection/helper GREEN | 15 passed | `/private/tmp/ai-auto-lrc-s18-p1-collection-green.y1V2ix` |
| P1 canonical-case/size/I/O-order GREEN | 12 passed | `/private/tmp/ai-auto-lrc-s18-p1-path-final.AnbJ0f` |

anti-self RED 命令结束后另出现 zsh `status` 只读变量 runner error；该 attempt 没有覆盖或重用，随后命令改用 `run_exit` 并创建新目录。collection 首次隔离尝试因 `-I` 同时移除仓库根、导致 `scripts` namespace package 无法导入而失败；修正为先从受信 site 导入 pytest，再显式加入已解析的仓库根，保留 `-I` 和全部 hostile environment 清理。

首次逐个 untracked whitespace loop 使用 zsh 特殊变量 `path`，意外覆盖 `PATH`，第二次调用 `git` 产生 `command not found`；retry 改用 `target_file`。retry 发现 `W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md` 首屏三行历史 Markdown hard-break 带 trailing spaces；这些行早于本轮且不在追加区，未为取得 GREEN 改写历史。本轮新增区、代码、manifest 与 Teams 文件另行检查无新增 whitespace error。

### 19.6 未闭合边界与唯一下一步

本轮允许的最大声明是：

> B3e-S stable scenario IDs、scenario manifest、exact artifact allowlist，以及当前 S18 P1 inventory record 的独立字段 authority 已实现并通过 host contract；已复现的 inventory-only semantic mapping/status/scope/nodeid/evidence-ref 自签绕过和 hostile pytest collection 注入已被拒绝。

以下仍是 blocker，不得由本节代签：

1. evidence reader 目前只验证 current authority 接受的 path、文件类型、bounded stable bytes 和 hash；它尚未按 kind 调用 `host-bundle`、`raw-run-manifest`、`independent-review`、`qualification-ledger` 的独立语义 verifier。首次状态晋级前必须逐 kind 绑定 full ID、exact nodeids、runner/target/platform scope、source/toolchain bytes 和 producer-external reviewer 结论。
2. authority 的未来状态迁移尚无独立 transition artifact。必须冻结 `planned/unverified -> implemented/unverified -> host-verified -> evidence-closed -> platform-qualified` 的允许边，并绑定 previous/next authority digest、changed fields、supporting evidence、verifier/toolchain digest、review/approval reference；禁止 scope 缩减、倒退或覆盖历史。
3. 当前 reader 不声明跨进程路径不可替换、hardlink 唯一性、same-UID/cross-UID 防篡改或 power-loss durability。若未来 evidence trust boundary 需要这些性质，必须补 ancestor symlink、FIFO/socket/device、hardlink/nlink、oversize、swap-after-open 和 content drift mutation。
4. B3e-S 仍只有 7 个 host-contract implemented 场景；13 个 macOS/Linux hostile 场景、持久 raw attempt、Linux replay 和平台资格化尚未完成。

唯一执行恢复点更新为：

```text
B3c RECORD field semantics + no-replace contract correction
  -> B3f-L producer limits
  -> B3f-R single runtime/runtime lock/offline provenance
  -> final-schema replay B3c-B3e
  -> complete B3e hostile macOS/Linux persistent evidence
  -> B4b typed claim authority
  -> B4a swap/restore characterization
  -> B4c semantic evidence verifiers + transition ledger + P1 traceability
  -> B7/B8 and final qualification sequence from section 18.8
```

S18、W1b-5b、Release 继续 **No-go**。W1b-5c/5d/5e 继续未授权。禁止 commit、push、CI、upload/sync、签名、发布、archive、restore、delete、destruction；保留 dirty worktree、根 `./=`、全部 RED/fixture error/runner error/retry/skip 和旧 attempt。

## 20. v1.7 B3c 收口与 B3f 可执行重构门

> 当前有效版本：`S18-P1-PLAN-v1.7`
>
> 本节取代第 19.6 节的恢复指令。第 18 节的 B3f-R、B4、freeze ledger 和最终资格化设计继续有效；发生冲突时，以本节记录的当前状态、原子边界、测试 oracle 和执行顺序为准。Teams 架构、实现与 QA 讨论记录见 [`team-sessions/team-session-2026-09-07-6.md`](./team-sessions/team-session-2026-09-07-6.md)。

### 20.1 当前结论和唯一恢复点

B3c 已完成 schema v1 RECORD entry 语义、identity hard-link no-replace publication、mode `0600` 和外部 verifier final invariant 的 host contract 收口。B3e-S 与 P1 current-state authority 继续保持第 19 节状态，不重做、不自动晋级。B3f-L、B3f-R、final-schema replay、完整 B3e hostile matrix、B4 typed claims/transition、common freeze 和双平台资格化仍未完成。

当前唯一实现起点改为 **B3f-L producer limits**。恢复者必须先核对第 20.2 节的 B3c 文件 hash 与第 20.10 节 preflight；一致时不得重跑 B3c RED 或改写 schema v1，直接从 B3f-L characterization RED 开始。不一致时只追加差异和新 attempt，不覆盖本节。

状态词汇严格分层：

```text
implemented
  -> host-verified
  -> evidence-closed
  -> platform-qualified
```

本节的 `207 passed` 只支持 B3c `implemented / host-verified`。它不把 P1 inventory record 晋级为 `host-verified`，也不构成持久 raw、独立 review、Linux 或平台 qualification。

### 20.2 B3c 最终合同与证据

schema v1 外部字段名继续为 `record_sha256`，精确语义冻结为：

```text
decoded SHA-256 digest from the pytest_cov/plugin.py RECORD entry
```

它不是 `sha256(.dist-info/RECORD file bytes)`。生产端从 `importlib.metadata.PackagePath.hash` 解码 entry digest；验证端从唯一 `pytest_cov/plugin.py` RECORD row 解码同一 digest，并交叉验证 live plugin bytes hash、entry size、distribution name/version 和已注册 plugin object。whole RECORD、METADATA、lock package、wheel 和 runtime 字段禁止零散加入 schema v1，统一留给 B3f-R schema v2。

identity writer 的发布合同冻结为：

```text
same-directory O_EXCL temp
-> fchmod(0600)
-> complete write
-> file fsync
-> os.link(temp, final) no-replace
-> temp unlink
-> directory fsync
```

`os.link` 是唯一发布线性化点，不允许以 `os.replace`、rename 或“atomic replace”描述。已有 final 和受控 publication race 的竞争 winner 都不得被覆盖。验证器从已打开 descriptor 的 `fstat` 要求 identity 是 regular、owned、single-link 且 mode 精确为 `0600`；`0640`、`0644` 必须只得到 `PLUGIN_IDENTITY_INVALID`。

本轮新增精确 whole-RECORD mutation：将 `record_sha256` 替换为整份 RECORD 文件 SHA-256，并重绑定外层 `plugin_identity_sha256` 后，Gate 仍只返回 `PLUGIN_IDENTITY_INVALID`。这证明拒绝来自字段语义，不是 artifact 外层 hash 抢先失败。

最终受约束文件 SHA-256：

| 文件 | SHA-256 |
|---|---|
| `scripts/security_pytest_bootstrap.py` | `fe0cb701f6730c4dcd51f534ba25712bed85c9a7915c44db3c0f6449b0d49992` |
| `scripts/verify_security_coverage.py` | `e13d49eedbd523d98fd5fca4974d3ee965a6748daaf406219daa92a56065cc1c` |
| `tests/contract/test_security_coverage_gate.py` | `651052d09ac00c0dc605b2a785b6dfe586b501552adabaa01b3e66a1f217e80b` |

证据账本：

| 阶段 | 结果 | 位置与 JUnit SHA-256 |
|---|---|---|
| RECORD/no-replace RED | 预期失败 | `/private/tmp/ai-auto-lrc-s18-b3c-record-noreplace-red.9FAdVr`；`9d70369d89e8281f91b6479aaaf6af0ec7f798a99ba6e8c771bf57fa27fc48a6` |
| restrictive umask/mode RED | 3 个预期失败 | `/private/tmp/ai-auto-lrc-s18-b3c-umask-mode-red.SAvP9o`；`a3e772e1bb0aa5c2e792634e1242f436607d396372b9a0a70bbc46d06d9cacf2` |
| 实现代理 B3c GREEN | `11 passed` | `/private/tmp/ai-auto-lrc-s18-b3c-green-retry.tx0qVr`；`59abf2d5287865ca3e4a9be21ee3c3ebf71805e3c13a679955cb59d5207d7af4` |
| 主任务独立 B3c 复验 | `11 passed, 195 deselected` | `/private/tmp/ai-auto-lrc-s18-b3c-root-directed.xeVv7x`；`966071c56279527f48393f25d2fc72ee5cf49268f9c834fd03aeb6466d5059af` |
| whole-RECORD 精确 mutation | `12 passed, 195 deselected` | `/private/tmp/ai-auto-lrc-s18-b3c-whole-record-green.Znp2kc`；`83e2da35745502e79f28c7091a4d5dae271ef8ca16b424d1e6b332366dd636da` |
| 最终完整 security contract | `207 passed in 186.20s` | `/private/tmp/ai-auto-lrc-s18-b3c-v17-full.4vWi0c`；`97a30990c21b0b6016fbab17c94e9359f2c77f060fcb2335ffde4cad1caa9370` |

历史实现代理的 `206 passed` 与主任务补测试前的 `206 passed` 均继续保留为演进 checkpoint，不覆盖、不删除，也不作为 v1.7 最终计数。

### 20.3 B3c 明确未覆盖的 writer 故障

QA 已对最新 identity bootstrap 实际复现：

```text
write exception      -> final absent; current temp remains
file fsync exception -> final absent; current temp remains
os.write() == 0      -> no progress/hang; alarm interrupted; temp remains
```

这些缺口不否定第 20.2 节的 RECORD/no-replace/mode 合同，但禁止宣称完整 writer fault closure、crash safety 或 power-loss durability。相同的状态机和 fault oracle 必须在 B3f-L events writer 上首先实现；bootstrap identity writer 的 write-zero、异常清理和精确 fsync 顺序在 final-schema replay 前另建小切片重放，不能由 events writer 的绿色代签。

B3c 当前最大声明只允许：

> Schema v1 的 `record_sha256` 已冻结为 `pytest_cov/plugin.py` 的 RECORD entry digest；当前宿主的 identity writer 使用 hard-link no-replace，已有 final 与受控 publication race 不会被覆盖，并强制写出和验证 mode `0600`。

禁止扩大为 whole RECORD/METADATA、installed tree、lock wheel、完整 writer fault matrix、single runtime、offline、双平台或 supply-chain closure。

### 20.4 B3f-L 原子边界和五文件迁移

B3f-L 只约束 `scripts/pytest_security_events.py` 自身保存的 cases、nodeid、序列化 bytes 和 sidecar writer。它不约束 pytest 在 hook 前的 collection、pytest 总进程内存、CPU、其他 plugin 或测试代码资源。

最小实现必须作为一个五文件原子迁移：

1. `scripts/pytest_security_events.py`：producer limits、events schema v3、canonical compact JSON、writer 状态机；
2. `scripts/run_security_coverage.sh`：从受信 policy 读取并唯一传递三个 limit；
3. `scripts/verify_security_coverage.py`：policy/argv/events exact validation、raw byte 和 mode 检查；
4. `packaging/security-coverage-policy.toml`：schema v2 与三个 limit；
5. `tests/contract/test_security_coverage_gate.py`：unit、mutation、real-runner 和回归合同。

本切片禁止修改 `scripts/security_pytest_bootstrap.py`、B3e scenario manifest、security capability manifest、Spec Inventory 或 B3f-R runtime 字段。producer、runner、verifier、policy 不能以半新半旧 schema 进入下一阶段。

policy v2 冻结：

```toml
schema_version = 2

[limits]
testcases = 4096
pytest_events_nodeid_bytes = 4096
pytest_events_bytes = 8388608
```

runner 在 capture/retention 每个 pytest argv 中各精确一次、按冻结顺序传入：

```text
--security-max-cases=4096
--security-max-nodeid-bytes=4096
--security-max-events-bytes=8388608
```

缺失、重复、改序、非 ASCII 正十进制、零、负数、超过 hard ceiling 或与 policy 不同，统一按 `RUNNER_CONFIGURATION_INVALID` 处理。events plugin 不读取 policy 文件：plugin 只校验 option 的格式、唯一性和 hard ceiling；runner 从已绑定 policy 传值，verifier 独立校验 command argv、events `limits` 与 policy 三者相等。events schema v3 增加 exact `limits` 对象，不增加 producer 自报的 `serialized_bytes`；verifier 直接观察原始 artifact byte length并重建 canonical bytes。

### 20.5 B3f-L producer 与 writer 状态机

producer 顺序冻结为：

1. configure 解析三个唯一正整数并与内建 hard ceiling 比较；policy 等值由 runner 和 verifier 在 plugin 外闭合；
2. item 插入前先做字符数快速上界，再用 `nodeid.encode("utf-8", "strict")` 检查原始 bytes，不做 Unicode normalization；
3. 第 `max_cases + 1` 个 item 插入前失败；
4. 用实际 nodeid 构造三阶段最坏 case 模板并累计 compact JSON 预算，禁止每次全量重序列化形成 O(n²)；
5. report 只更新已收集 case，未知 case、未知/重复 phase、非法 outcome 立即失败，不保存 longrepr、exception 或 pytest object；
6. sessionfinish 使用 `sort_keys=True`、`separators=(",", ":")`、`ensure_ascii=False` 和单尾换行，写前再次检查实际 bytes；
7. verifier 重建相同 canonical bytes，逐项复核 cases、nodeid UTF-8 bytes、limits、raw bytes 和 final mode `0600`。

events writer 以 `os.link(temp, final)` 成功返回为唯一发布线性化点：

| 状态 | 本次 temp | final 可见 | 失败语义 |
|---|---:|---:|---|
| `INITIAL` | 未拥有 | 否 | temp open 失败；不得执行 unlink |
| `TEMP_OPEN` | 已拥有 | 否 | fchmod/write/write-zero/file-fsync 失败；关闭 fd，仅清理本次 temp |
| `FILE_SYNCED` | 已拥有 | 否 | link 失败；清理本次 temp，竞争 final 原样保留 |
| `PUBLISHED` | 与 final 同 inode | 是 | temp unlink 失败；不得删除 final，状态 commit uncertain |
| `TEMP_UNLINKED` | 否 | 是 | directory open/fsync/close 失败；final 保留，状态 commit uncertain |
| `DURABLE` | 否 | 是 | directory fsync 和 close 完成，唯一成功终态 |

`temp_owned` 只能在 `O_CREAT|O_EXCL` open 成功后置真，在成功 unlink 后立即置假。cleanup 不能用 `Path.exists()`、glob 或固定 PID 名推断 ownership；不得删除旧 temp、旧 final、竞争 winner 或旧 attempt。cleanup 异常不能覆盖原始异常。link 成功后绝不删除 final 作为回滚。

稳定 producer marker 冻结为：

```text
PYTEST_EVENTS_CONFIGURATION_INVALID
PYTEST_EVENTS_LIMIT_EXCEEDED
PYTEST_EVENTS_PUBLICATION_FAILED
PYTEST_EVENTS_COMMIT_UNCERTAIN
```

`PYTEST_EVENTS_PUBLICATION_FAILED` 仅用于 link 成功前、可以确定本次未提交的错误；`PYTEST_EVENTS_COMMIT_UNCERTAIN` 用于 link 成功后的 temp unlink、directory open/fsync/close 错误。后者禁止安全重试同一 attempt。

### 20.6 B3f-L 精确测试用例

第 18.5 节 `B3F-L-001` 至 `B3F-L-012` 继续有效，并追加三类不可由现有节点代签的合同：`B3F-L-013-preexisting-temp`、`B3F-L-014-syscall-order`、`B3F-L-015-publish-race`。所有参数使用显式稳定 `id=`；禁止 pytest 位置生成 ID。

| ID | fixture | 精确 GREEN oracle |
|---|---|---|
| `B3F-L-001-cases-boundary` | exact 4096 cases | FULL；Gate PASS；case count 精确 |
| `B3F-L-002-cases-plus-one` | 4097th insert | 插入前 `LIMIT_EXCEEDED`；无 events/temp |
| `B3F-L-003-nodeid-boundary` | UTF-8 bytes exact 4096 | FULL；Gate PASS |
| `B3F-L-004-nodeid-plus-one` | ASCII 与多字节 Unicode 4097 bytes | 进入 case map 前失败；证明 bytes 而非 chars |
| `B3F-L-005-serialized-boundary` | compact JSON 加尾换行 exact 8 MiB | final 实际大小等于 limit；Gate PASS |
| `B3F-L-006-serialized-plus-one` | final bytes 8 MiB + 1 | 写盘前失败；NO_EVENTS；无 temp |
| `B3F-L-007-invalid-limit` | zero/negative/non-decimal/overflow | configure fail closed；EARLY |
| `B3F-L-008-duplicate-limit` | 三个 option 各重复 | runner configuration invalid；EARLY |
| `B3F-L-009-write-zero` | 首次 `os.write()` 返回 0 | 外层 deadline 前主动失败；不再次 write/fsync/link；无本次 temp/final |
| `B3F-L-010-existing-final` | configure 前预置 final | 旧 final inode/bytes/mode 不变；只证明预检，不代签 publication race |
| `B3F-L-011-writer-fault-matrix` | open/fchmod/write/file-fsync/link/unlink/directory open/fsync/close | 每例精确 final/temp/inode/nlink/mode/code/Gate；包含独立 directory-close 参数 |
| `B3F-L-012-existing-attempt` | 预置 attempt marker | runner input invalid；目录逐字节不变 |
| `B3F-L-013-preexisting-temp` | 预置当前命名规则的 temp | old temp `(dev,ino,mode,nlink,size,hash)` 不变；final 不存在；证明 `O_EXCL`/ownership |
| `B3F-L-014-syscall-order` | 记录型 wrapper + 真实 filesystem calls | `open/fchmod/write+/file-fsync/close/link/unlink/open-dir/dir-fsync/close` 精确顺序；禁用 replace/rename |
| `B3F-L-015-publish-race` | file fsync 后、link 前插入 competitor | `PUBLICATION_FAILED`；winner inode/bytes/mode/hash 不变；本次 temp 清理；不做 dir fsync |

预发布 fault 参数至少包含：

```text
B3F-L-009-write-zero
B3F-L-011-write-exception
B3F-L-011-file-fsync
B3F-L-011-link-failure
```

共同 oracle：final 不存在或竞争者原样保留，本次 temp 清理，公共 marker 为 `PYTEST_EVENTS_PUBLICATION_FAILED`。zero-write 必须在隔离子进程和硬 deadline 内测试；错误实现由 timeout 回收只是 RED，不得算 GREEN。

发布后 fault 参数至少包含：

| 参数 | 磁盘状态 | producer marker | Gate failures |
|---|---|---|---|
| `B3F-L-011-temp-unlink` | final/temp 同 inode，`nlink == 2` | `PYTEST_EVENTS_COMMIT_UNCERTAIN` | `COMMAND_FAILED, PYTEST_EVENTS_INVALID` |
| `B3F-L-011-temp-unlink-retry-success` | 首次 unlink 失败，cleanup retry 成功；final `nlink == 1`、temp absent | `PYTEST_EVENTS_COMMIT_UNCERTAIN` | 仅 `COMMAND_FAILED` |
| `B3F-L-011-directory-open` | final `0600`、`nlink == 1`、temp absent | `PYTEST_EVENTS_COMMIT_UNCERTAIN` | 仅 `COMMAND_FAILED` |
| `B3F-L-011-directory-fsync` | final `0600`、`nlink == 1`、temp absent | `PYTEST_EVENTS_COMMIT_UNCERTAIN` | 仅 `COMMAND_FAILED` |
| `B3F-L-011-directory-close` | directory fsync 已返回，close 失败；final `0600`、`nlink == 1` | `PYTEST_EVENTS_COMMIT_UNCERTAIN` | 仅 `COMMAND_FAILED` |

`temp-unlink` 表示所有清理尝试永久失败；`temp-unlink-retry-success` 表示后续 cleanup 成功。两者都不能吞掉 commit-uncertain 主错误，但磁盘与 Gate oracle 不同。directory open/fsync/close 场景中的 events 内容可以完全合法；失败来自 command exit 和 durability 不确定，不能伪造 `PYTEST_EVENTS_INVALID`。

### 20.7 Real runner 场景与证据合同

低层 writer/unit 合同通过后，每类 limit/fault 至少对 capture 和 retention 各运行一次真实 runner；一次只注入一个 target，另一 lane 必须 PASS 作为控制组。推荐统一 node：

```text
test_s18_b3f_events_limits_real_runner[<stable-id>-capture]
test_s18_b3f_events_limits_real_runner[<stable-id>-retention]
test_s18_b3f_events_writer_real_runner[<stable-id>-capture]
test_s18_b3f_events_writer_real_runner[<stable-id>-retention]
```

首次 RED 必须观察并冻结 configure/collection/sessionfinish 的真实 inner pytest exit；不得接受 `{1,2,3,4}` 宽集合。outer runner 固定非零且两 lane 都运行。pre-publication 无 events 时 Gate 精确为 `COMMAND_FAILED, PYTEST_EVENTS_INVALID`；post-publication合法单链接 final 时 Gate 精确为 `COMMAND_FAILED`；残留同 inode双链接 temp 时 Gate 精确为 `COMMAND_FAILED, PYTEST_EVENTS_INVALID`。

每个 scenario record 至少冻结：

```text
scenario_id
target
fault
publication_phase
expected_producer_code
expected_pytest_exit
expected_outer_exit
expected_gate_failures
required_artifacts
forbidden_artifacts
expected_final_state
expected_temp_state
outer_nodeid
status
```

scenario authority 直接写在现有 `tests/contract/test_security_coverage_gate.py` 的独立常量中，并由测试与实际 collection 双向约束；本切片不新增第六个 fixture 文件。每个 attempt 保存 command、sanitized environment、JUnit、stdout/stderr、artifact exact-name set、hash manifest、mutation recipe ID、基础与 mutated plugin SHA-256，以及 final/temp/sentinel 的 before/after `(dev,ino,mode,nlink,size,sha256)`。zero-write 另保存 elapsed/deadline。

动态 PID temp 不得通过 glob 放宽 artifact allowlist。外层 harness 在 mutation evidence 中记录受控子进程 PID，并按 writer 命名规则推导唯一 temp basename；永久残留场景的 exact artifact set 只能比标准 allowlist 多这一个名称，其他 dotfile 仍失败。该 PID 只属于外层测试证据，不新增产品 command/run-manifest schema 字段。所有这些结果只标为 host contract/mutation evidence，不写入 P1 current inventory，不晋级 platform qualification。

### 20.8 B3f-R 与 final-schema replay

B3f-L 完成并冻结 schema 后才进入 B3f-R。B3f-R 必须把 identity、environment、command、run-manifest、Gate 和 verifier 作为同一迁移单元升级；禁止把 whole RECORD、METADATA 或 runtime 字段补回 schema v1。

B3f-R 输出继续采用第 18.6 节设计：named core runtime 只绑定当前 Python、uv、pytest、pytest-cov、coverage、pluggy；捕获 bounded whole RECORD/METADATA bytes、required entry hash/size、canonical lock package object digest，并固定 `<ABS_UV> run --offline --frozen --no-sync python -I -S -B`。provenance 最大值仍为 `installed-record-consistent`，不允许 `wheel-verified`、signature 或 SBOM 字段。

B3f-R GREEN 后必须在最终 schema 下按顺序：

1. replay B3c RECORD/no-replace/mode 与 whole-RECORD mutation；
2. 补并 replay bootstrap identity writer 的 write-zero、异常清理、preexisting temp、精确 syscall 顺序和 post-publication failure 分类；
3. replay B3d JUnit/events consistency；
4. replay B3e 七个 implemented scenario；
5. 实现 13 个 planned macOS/Linux hostile scenario，生成持久 inner raw 并由 producer 外 verifier 重算。

任一步导致 source、test、policy、manifest、runner、verifier、bootstrap、events plugin、`pyproject.toml`、`uv.lock` 或 schema 字节变化，都使依赖旧字节的后续 evidence historical；不得局部复用旧平台证明。

### 20.9 后续 DAG 输入输出与依赖

最终执行顺序冻结为：

```text
B3f-L producer limits + writer fault matrix
  -> B3f-R named core runtime / lock / offline binding
  -> final-schema replay B3c / B3d / B3e core
  -> complete B3e hostile macOS + Linux persistent raw/replay
  -> B4b typed claim authority
  -> B4a swap/restore characterization
  -> B4c evidence semantic verifier + monotonic transition ledger
  -> B7 contracts/docs/product/P1 inventory/current-pointer agreement
  -> B8 common freeze ledger
  -> B9 macOS Security qualification -+
                                     +-> cross-platform common digest comparator
  -> B10 Linux Security qualification-+
  -> B11 package scoped evidence
  -> B12 canonical rebuild 13/13 + replay
  -> B13 host full/static/bash/diff
  -> B14 sealed PASS/BLOCKED + producer-external review
  -> B15 Teams W1b-5b decision
  -> B16 post-doc links/inventory/claims/pointer/diff
```

B9/B10 只有在 B8 common digest相同后才可并行，artifact root 必须分离。comparator 只允许声明 `common-input-equivalent` 与 `platform-runtime-distinct`；macOS、Linux、package、canonical、host 和 sealed-review 不能互相代签。B4 的顺序保持 `B4b -> B4a -> B4c`；P1 状态晋级必须先实现逐 kind evidence semantic verifier 和 previous/next authority digest 绑定的单调 transition ledger。

### 20.10 Attempt 生命周期 逻辑回滚和命令

建议证据根：

```text
<v1.7-root>/
  B3f-L/<scenario>/{red,green}/attempt-NNN/
  B3f-R/<scenario>/{red,green}/attempt-NNN/
  replay/{b3c,b3d,b3e}/attempt-NNN/
  B3e-hostile/<scenario>/{macos,linux}/attempt-NNN/
  B4/{claims,aba,transition}/attempt-NNN/
  B7-common-regression/attempt-NNN/
  B8-common-ledger/attempt-NNN/
  B9-security-macos/round-NNN/
  B10-security-linux/round-NNN/
  comparator/attempt-NNN/
  B11-package/{macos,linux}/attempt-NNN/
  B12-canonical/attempt-NNN/
  B13-host/attempt-NNN/
  B14-sealed/attempt-NNN/
```

“回滚”只表示停止当前切片、保留失败字节差异和 raw、不让失败 schema 进入下一阶段、修复后创建新 attempt。不得执行 `reset`、`checkout`、`clean`、广泛删除或恢复历史文件；不得覆盖 RED、fixture/runner error、retry、flaky、skip 和旧 attempt。

恢复 preflight：

```bash
pwd
git branch --show-current
git rev-parse HEAD
git status --short
shasum -a 256 \
  docs/S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md \
  docs/team-sessions/team-session-2026-09-07-6.md \
  scripts/security_pytest_bootstrap.py \
  scripts/pytest_security_events.py \
  scripts/run_security_coverage.sh \
  scripts/verify_security_coverage.py \
  packaging/security-coverage-policy.toml \
  tests/contract/test_security_coverage_gate.py \
  tests/fixtures/security_coverage_scenarios.json \
  tests/contract/test_spec_inventory.py \
  tests/spec_inventory.json pyproject.toml uv.lock
```

B3f-L 完成前的最低验证顺序：

```bash
bash -n scripts/run_security_coverage.sh
uv run --offline --frozen --no-sync python -m py_compile \
  scripts/pytest_security_events.py \
  scripts/verify_security_coverage.py \
  tests/contract/test_security_coverage_gate.py
uv run --offline --frozen --no-sync ruff check \
  scripts/pytest_security_events.py \
  scripts/verify_security_coverage.py \
  tests/contract/test_security_coverage_gate.py
uv run --offline --frozen --no-sync python -m pytest \
  tests/contract/test_security_coverage_gate.py \
  -q -p no:cacheprovider --junitxml=<new-exclusive-path>/junit.xml
uv run --offline --frozen --no-sync python -m pytest \
  tests/contract/test_document_links.py \
  tests/contract/test_spec_inventory.py \
  -q -p no:cacheprovider
git diff --check
```

`<new-exclusive-path>` 必须由 `mktemp -d` 新建；不得复用本节任何路径。Ruff format 若因既有未跟踪文件的全文件格式漂移失败，只记录差异，不为取得 GREEN 做无关批量格式化。

### 20.11 停止条件和最大声明

出现任一情况立即停止当前波次并保留 raw：producer/consumer schema不一致；required node missing/deselected/skip/xfail/failure/error；failure code集合或排序漂移；write-zero挂死；writer覆盖 final/competitor 或删除 preexisting temp；post-link 错误被降级为安全未提交；runtime/lock resolution歧义；发生网络/sync/cache/lock写入；source/test/policy/manifest/toolchain before-after漂移；raw与独立 replay不一致；B8 后 common digest变化；两平台 common digest不同；attempt 已存在；为 GREEN 放宽 threshold、schema、node、skip、claim 或 artifact allowlist。

v1.7 当前允许的最大声明为：

> B3e-S stable scenario authority 与 P1 current-state authority 已完成 host contract；B3c schema v1 的 RECORD entry 语义、identity hard-link no-replace publication、mode `0600` 和 whole-RECORD 错误 mutation 已收口。唯一下一步是 B3f-L events producer limits 与 writer fault matrix。

只有 B3f-L 全部 unit/real-runner合同完成后，才能增加“pytest events producer在声明的 case/nodeid/artifact byte边界内 fail closed”；仍不得写“pytest全进程资源有界”。只有 B3f-R 完成后，才能增加“当前 named core runtime 在 `installed-record-consistent` 边界内完成 host binding”。只有 B9、B10 和 comparator 完成后，才能按各自平台与 common digest 范围声明 Security qualification。

始终禁止声称完整依赖图、wheel/signature/SBOM provenance、immutable snapshot、ABA-safe、transactional execution、power-loss durability、same-UID/cross-UID 防护、portable runtime、Release 批准，或用 package/canonical/host/sealed 任一 lane 代签另一 lane。

S18、W1b-5b、Release 继续 **No-go**。commit、push、创建 CI、upload/sync、签名、发布、archive、restore、delete、destruction 和 W1b-5c/5d/5e 均未获授权。

## 21. v1.8 B3f L unit mutation checkpoint

> 当前有效版本：`S18-P1-PLAN-v1.8`
>
> 本节追加第 20.4 至 20.6 节的实际执行结果；第 20.7 至 20.11 节继续定义未完成的 real-runner、B3f-R 和后续 DAG。Teams 实现、架构与 QA 复核见 [`team-sessions/team-session-2026-09-07-7.md`](./team-sessions/team-session-2026-09-07-7.md)。

### 21.1 当前状态和唯一下一步

B3f-L 五文件 schema/runner/verifier/unit-mutation 原子 tranche 已实现并通过当前 host contract。整个 B3f-L 仍为 **PARTIAL / No-go**，因为第 20.7 节独立 scenario authority 和 capture/retention 双 lane real-runner matrix 尚未实现。

当前唯一恢复点是 **B3f-L 第 20.7 节**，不是重做 policy v2、events v3、writer unit RED，也不是提前进入 B3f-R。`257 passed` 只能证明目前存在的合同通过，不能代签尚不存在的 real-runner nodes。

### 21.2 已落地的五文件原子迁移

| 文件 | 当前能力 | SHA-256 |
|---|---|---|
| `scripts/pytest_security_events.py` | events v3、limits、canonical bytes、fatal suppression、no-replace writer 状态机 | `aa44ed1307b221c3cdd538e31942a0005abf399f3ff76a1b3a0e042454c91ef6` |
| `scripts/run_security_coverage.sh` | policy v2、冻结 limit、双 lane exact argv | `b79298af7ad80392f10c1f04c505ca5724d4dc80fff1afc163c18f77f368c15c` |
| `scripts/verify_security_coverage.py` | policy/events/argv 等值、canonical/raw byte、mode `0600` 独立复验 | `9a324d972ded9c50f4b8009b2e90479b0c089758ba29a647d22a89b1031a4300` |
| `packaging/security-coverage-policy.toml` | schema v2 与 `4096/4096/8388608` producer limits | `c7e02af2303a1ada48590493abfc605737c3185327aeec1eceb19eb5355a39cd` |
| `tests/contract/test_security_coverage_gate.py` | boundary、mutation、writer fault、runner/verifier合同 | `4f118218ed8e9e08b3e813f42b5509dc35c92f82305f488abf437bc55f2484fc` |

实现边界：

- limit 只接受唯一、ASCII 正十进制且不超过 hard ceiling；plugin 在有界证明后才调用 `int()`。
- cases 和 nodeid 在插入前拒绝 `+1`；nodeid 按原始 UTF-8 bytes 计数，不 normalize。
- collection 累计预算使用 producer 可接受三阶段 shape 的精确最大模板；sessionfinish 再对最终 canonical bytes 做硬检查。
- producer fatal 后禁止写出 partial sidecar；compact JSON 使用 `sort_keys=True`、`separators=(",", ":")`、`ensure_ascii=False` 和单尾换行。
- writer 处理 partial write 与 zero write，强制 `0600`，file fsync 后以 hard-link no-replace 发布，按 ownership清理本次 temp，再做 directory fsync。
- link 前失败归一为 `PYTEST_EVENTS_PUBLICATION_FAILED`；link 后失败归一为 `PYTEST_EVENTS_COMMIT_UNCERTAIN`，不得删除 final或安全重试同一 attempt。
- runner 从冻结 policy向每个 lane各传一次三个参数；verifier独立要求 policy、command argv与events `limits`精确相等，并验证 final regular/owned/single-link/mode与 raw/canonical bytes。

### 21.3 RED GREEN 和并发污染账本

| 阶段 | 结果 | 保留位置 |
|---|---|---|
| B3f 初始 RED | `28 failed, 207 deselected` | `/private/tmp/ai-auto-lrc-s18-b3fl-red.JFuyot` |
| policy/close 补充 RED | `4 failed, 2 passed` | `/private/tmp/ai-auto-lrc-s18-b3fl-small-red-retry.87ariM` |
| 最小 GREEN | `6 passed` | `/private/tmp/ai-auto-lrc-s18-b3fl-small-green.AOwwDJ` |
| B3f unit GREEN | `31 passed` | `/private/tmp/ai-auto-lrc-s18-b3fl-unit-retry.FihBFr` |
| mutation/characterization GREEN | `63 passed` | `/private/tmp/ai-auto-lrc-s18-b3fl-mutations.6DixWO` |
| docs/Spec Inventory 回归 | `42 passed` | `/private/tmp/ai-auto-lrc-s18-b3fl-doc-spec.OYcGb4` |
| QA real collection limit | exit `4`、`PYTEST_EVENTS_LIMIT_EXCEEDED`、无 events/temp | `/tmp/s18-b3f-qa.uHGqI6` |
| 架构终审 P1 RED | `2 failed` | `/private/tmp/ai-auto-lrc-s18-b3fl-arch-red.7vEPNP` |
| 架构终审 P1 GREEN | `2 passed` | `/private/tmp/ai-auto-lrc-s18-b3fl-arch-green.WcdaBh` |
| 最终 B3f 精确集 | `34 passed, 223 deselected` | `/private/tmp/ai-auto-lrc-s18-b3fl-final-targeted2.ySgG92` |
| 主任务独立 B3f 相关集 | `44 passed, 213 deselected` | `/private/tmp/ai-auto-lrc-s18-b3fl-root-targeted.NzQhgB`；JUnit SHA-256 `d413cfb3b8bcfc5fbb82a5b122dd0c4581581f24a65e9587aa5a067791d233cb` |
| 主任务独立完整合同 | `257 passed in 189.45s` | `/private/tmp/ai-auto-lrc-s18-b3fl-root-full.UAlfK6`；JUnit SHA-256 `de08a1d9f9825be83377c62dd78573d3a051dc56ccaf7f65d9e8ac069fd494e2` |

QA 在 P1 修复前同一冻结 hash曾得到终端 `254 passed in 208.54s`，但没有持久 JUnit/log目录，只保留为终端 checkpoint。实现代理与另一条 hostile real-runner 并发时得到 `253 passed, 1 failed`，路径 `/private/tmp/ai-auto-lrc-s18-b3fl-contract-green.845NcG`；失败为 capture Gate `COMMAND_FAILED, JUNIT_CONTAINS_FAILURE`，retention PASS。该 attempt 作为并发污染保留，不能与串行 GREEN 合并或删除。

### 21.4 架构终审发现并关闭的 P1

第一项 P1：collection 最坏 case模板原使用 `wasxfail=true`，而 canonical JSON 的 `false` 多 1 byte，三个 phase 合计低估 3 bytes。修复后测试对两个 `xfail_marked` 值各遍历 `7^3=343` 种合法 phase组合，逐项要求 estimate 不小于 actual，并精确等于该组最大值。

第二项 P1：5000 位十进制 limit曾在长度防护前进入 `int()`，触发 Python digit limit的 `ValueError` 和 pytest INTERNALERROR。修复后先用 ASCII regex、字符串长度和同长度字典序与 ceiling比较，证明有界后才转换。真实 configure合同冻结 exit `4`、stderr `ERROR: PYTEST_EVENTS_CONFIGURATION_INVALID`，且无 final/temp。

架构与 QA 在最终 hash下独立复核这两项通过；当前未发现新的 unit/mutation P1。

### 21.5 第 20.7 节未完成的 P0

以下仍全部缺失，任何一项不能由 unit mock、直接 plugin pytest或 `257 passed`代签：

1. 独立 B3f scenario authority，冻结第 20.7 节的 15 个字段、outer nodeid、status和 exact artifact profile；
2. `test_s18_b3f_events_limits_real_runner[...]` capture/retention 双 lane nodes；
3. `test_s18_b3f_events_writer_real_runner[...]` capture/retention 双 lane nodes；
4. 真实 4096/4097 cases、producer-valid 8 MiB/8 MiB+1 artifact边界；
5. temp open/fchmod/partial-write/write-zero/file-fsync/link/temp-unlink/directory-open/fsync/close在两个 lane的精确 inner/outer exit；
6. 单 target fault时另一 lane PASS、Gate failure排序、artifact exact allowlist、base/mutated hash、sentinel identity和动态 PID temp receipt；
7. 每个 inner raw在外层 pytest结束后仍能由 producer外 verifier独立复算。

实现这些 nodes时必须使用不会碰撞产品 Spec ID grammar的 collected parameter ID，例如小写 `b3fl001-cases-boundary-capture`；`B3F-L-001` 至 `B3F-L-015`只作为 scenario record中的描述性 ID，不得形成 `L-001-suffix` 之类 decorated stable ID。

### 21.6 可执行续接顺序

```text
freeze current five-file hashes
  -> add independent B3f real-runner scenario authority in existing contract test
  -> RED limits real-runner capture + retention
  -> RED writer fault real-runner capture + retention
  -> implement only required fault seams/harness, not new product claims
  -> GREEN each scenario with exact artifact/final/temp/Gate oracle
  -> producer-external replay after outer pytest lifetime
  -> B3f-L full contract + docs/spec inventory/static checks
  -> append next current checkpoint
  -> only then enter B3f-R
```

第 20.7 P0 关闭前，唯一允许新增的结论是：

> B3f-L 的五文件 schema/runner/verifier/unit-mutation tranche 已在当前宿主通过；它证明 events producer与独立 verifier在低层合同中对冻结的 case、nodeid和artifact byte限制 fail closed。

仍禁止写成 capture/retention real-runner完整闭合、pytest全进程资源有界、B3f-L完成、B3f-R完成、platform-qualified、crash/power-loss durable或Release批准。

S18、W1b-5b、Release 继续 **No-go**。W1b-5c/5d/5e、commit、push、CI、upload/sync、签名、发布、archive、restore、delete和destruction仍未授权。

## 22. v1.9 B3f L real runner authority 与完整执行方案

> 当前有效版本：`S18-P1-PLAN-v1.9`
>
> 本节把第 20.7 节从概念方案升级为已落地 authority、代表性真实 runner checkpoint 和剩余 57 条的逐批执行规范。第 21 节保留为 unit/mutation tranche 的历史 checkpoint；本轮 Teams 实现、架构裁决与 QA 终审见 [`team-sessions/team-session-2026-09-07-8.md`](./team-sessions/team-session-2026-09-07-8.md)。

### 22.1 当前结论和恢复点

B3f-L 的独立 real-runner authority 已冻结为 67 条不可缩减记录，当前精确状态为 `10 implemented / 57 planned`。已实现的 10 条来自 5 个 concrete variant 的 capture/retention 双 lane：

| concrete variant | capture | retention | 当前证据等级 |
|---|---:|---:|---|
| `B3F-L-001-cases-boundary` | implemented | implemented | host real-runner mutation contract |
| `B3F-L-002-cases-plus-one` | implemented | implemented | host real-runner EARLY contract |
| `B3F-L-011-link-failure` | implemented | implemented | host real-runner pre-publication contract |
| `B3F-L-011-temp-unlink` | implemented | implemented | host real-runner post-publication contract |
| `B3F-L-011-directory-open` | implemented | implemented | host real-runner post-publication contract |

其余 57 条必须继续保留 `planned`，不得用这 10 条代表性记录、unit mock、直接 plugin pytest、`19 passed` 或第 21 节的 `257 passed` 代签。当前唯一恢复点是按本节第 22.7 节逐批关闭 57 条，不进入 B3f-R。

当前五文件与 authority 字节冻结为：

| 文件或对象 | SHA-256 |
|---|---|
| `packaging/security-coverage-policy.toml` | `c7e02af2303a1ada48590493abfc605737c3185327aeec1eceb19eb5355a39cd` |
| `scripts/pytest_security_events.py` | `aa44ed1307b221c3cdd538e31942a0005abf399f3ff76a1b3a0e042454c91ef6` |
| `scripts/run_security_coverage.sh` | `ba633df67a85b2854a82e41fdb607bed6dd652bd0dbfd3c8788eb45a01972bb8` |
| `scripts/verify_security_coverage.py` | `354db6f314a75b3468ebb76ceface16a5f8a990a3fc24a3533a8e08fbecaf074` |
| `tests/contract/test_security_coverage_gate.py` | `690169df567d1db212157235e8f6cd6063093a0025efa3ef422f3149c3cb197e` |
| 67-record authority canonical bytes | `de990f4e997eb4f6872306d8c65058ca7a15136886ac5e8137985f8aaa6628b5` |

这些 hash 只冻结当前 10/67 checkpoint。后续任何批次修改上述文件后，本表自动历史化；必须在新 checkpoint 重算，不得把旧 real-runner evidence 标成 current。

### 22.2 Authority exact schema 与状态单调性

每条 authority record 精确包含以下 15 个字段，不允许增加、删除或重命名：

```text
scenario_id
target
fault
publication_phase
expected_producer_code
expected_pytest_exit
expected_outer_exit
expected_gate_failures
required_artifacts
forbidden_artifacts
expected_final_state
expected_temp_state
expected_sentinel_state
outer_nodeid
status
```

`mutation_recipe_id` 不属于 authority；它只存在于真实运行产生的外层 mutation receipt，并必须等于该次实际 recipe 与 target 的绑定值。

`planned` 记录必须保持未观察事实为空：producer code、两个 exit、outer nodeid为 `null`；artifact集合为空；final/temp/sentinel为 `not-applicable`；`expected_gate_failures=[]` 只在 planned 占位语义下使用。禁止先猜测结果再把记录写成 implemented。

真实节点存在并稳定 GREEN 后，才能在同一原子 patch 内填写实测结果、outer nodeid并把 status单调晋级为 `implemented`。不得把 implemented降回planned来掩盖回归，也不得删除失败 variant 来缩小总数。总数始终为67：

```text
limit and boundary concrete variants: 16 x capture/retention = 32
writer and publication concrete variants: 17 x capture/retention = 34
existing attempt global runner variant: 1
total: 67
```

`B3F-L-012-existing-attempt:runner` 是唯一 `target=runner` 的全局场景；它发生在 pytest 启动前，没有 capture/retention 双 lane、pytest exit、Gate或 producer-external replay。

### 22.3 生命周期阶段与证据形态术语

`publication_phase` 表示 pytest 或 writer 生命周期阶段，规范集合为：

```text
pre-run
configure
collection
sessionfinish
pre-publication
publication
post-publication
```

`EARLY` 表示 raw completeness 和 runner 输出形态，不是新的 publication phase。当前4097 cases合同的规范组合是：

```text
publication_phase = collection
expected_gate_failures = null
artifact profile = EARLY
runner-error.stage = raw-completeness
```

其语义是“collection阶段失败，coverage raw不完整，runner保留EARLY evidence，不生成run-manifest或Gate”。文档可用“collection EARLY”描述该组合，但不得把authority值改成 `collection-early`，也不得增加第16个 `evidence_phase` 字段。

Gate字段必须区分：

- `null`：Gate不存在、未执行；
- `[]`：Gate实际执行并PASS；
- 非空有序列表：Gate实际执行并按该顺序失败。

第20.7节“pre-publication无events时一律生成Gate”的宽泛规则被本节收窄：configure/collection阶段如果coverage尚未完成，只能生成EARLY runner-error、不得伪造Gate；sessionfinish或writer阶段在coverage/JUnit/identity完整时，才允许由verifier生成有序Gate failures。

### 22.4 Artifact profiles 与 runner error v2

Real-runner合同使用 exact-name equality，不接受“至少包含”或glob放宽：

| profile | 精确语义 | 关键产物 |
|---|---|---|
| `FULL` | producer与verifier完成 | coverage raw/JSON、JUnit、events、identity、environment、command、run-manifest、Gate、stdout/stderr、verifier stderr |
| `NO_EVENTS` | raw足以执行verifier，但events缺失 | `FULL`减events；Gate存在且精确失败 |
| `FULL_PLUS_PID_TEMP` | post-link永久temp残留 | `FULL`加由受控子进程PID精确推导的唯一temp名称 |
| `EARLY` | coverage未完成，不能构造manifest/Gate | command、environment、JUnit、plugin identity、runner-error、stdout、stderr，共7件 |

动态PID temp只由外层harness记录的受控子进程PID推导；禁止使用glob、目录搜索或模糊basename放宽allowlist。

`runner-error.json` 当前为 schema v2，exact字段为：

```text
schema_version
run_id
target
runner
attempt
stage
reason_code
pytest_exit_code
environment_exit_code
command_exit_code
qualification
present_artifacts
missing_artifacts
present_hashes
```

4097 cases实测冻结：inner pytest exit `4`、outer exit `1`、`stage=raw-completeness`、`reason_code=REQUIRED_RAW_ARTIFACT_MISSING`、exit tuple `4/0/0`、qualification `INCOMPLETE_RAW_EVIDENCE`。外部verifier必须精确返回 exit `2`、stderr `SECURITY_COVERAGE_INPUT_INVALID\n`，且不生成输出Gate。这不是replay失败，而是证明不完整raw不能被升级为Gate。

### 22.5 当前代表 tranche 的精确事实

| variant | phase/profile | producer / exits | Gate | final/temp/sentinel |
|---|---|---|---|---|
| cases boundary | collection/FULL | no marker；pytest `0`；outer `0` | `[]` | final single-link `0600`；temp absent；sentinel unchanged |
| cases plus one | collection/EARLY | `PYTEST_EVENTS_LIMIT_EXCEEDED`；pytest `4`；outer `1` | `null` | final/temp absent；sentinel unchanged |
| link failure | pre-publication/NO_EVENTS | `PYTEST_EVENTS_PUBLICATION_FAILED`；pytest `1`；outer `1` | `COMMAND_FAILED, PYTEST_EVENTS_INVALID` | final/temp absent；sentinel unchanged |
| permanent temp unlink | post-publication/FULL_PLUS_PID_TEMP | `PYTEST_EVENTS_COMMIT_UNCERTAIN`；pytest `1`；outer `1` | `COMMAND_FAILED, PYTEST_EVENTS_INVALID` | final/temp同inode、`nlink=2`、`0600`；sentinel unchanged |
| directory open | post-publication/FULL | `PYTEST_EVENTS_COMMIT_UNCERTAIN`；pytest `1`；outer `1` | `COMMAND_FAILED` | final single-link `0600`；temp absent；sentinel unchanged |

实现使用真实复制的产品runner、真实uv和pytest/plugin；mutation只作用于目标lane，另一lane必须完整PASS。未向产品runner增加测试专用argv或环境变量seam。receipt绑定所有mutated files的base/mutated hash、exact artifact sets、sentinel和final/temp before/after身份。

已保留证据：

| checkpoint | 结果 | 路径 |
|---|---|---|
| 代表 tranche最终checkpoint | `19 passed in 60.06s` | `/private/tmp/ai-auto-lrc-s18-b3f-final-checkpoint.pw2ENR/run.log` |
| real-runner harness首次RED | `b3fl011-link-failure-capture`因real harness缺失失败 | `/private/tmp/ai-auto-lrc-s18-b3f-red.svFLVH/red.log` |
| link failure双lane GREEN | `2 passed in 9.62s` | `/private/tmp/ai-auto-lrc-s18-b3f-link-pair.LxLsmX/run.log` |
| temp unlink verifier修复后GREEN | `2 passed in 9.51s` | `/private/tmp/ai-auto-lrc-s18-b3f-temp-verifier-fix.9ZVtiC/run.log` |
| cases plus one EARLY GREEN | `2 passed in 9.70s` | `/private/tmp/ai-auto-lrc-s18-b3f-cases-plus-one-green.Beq4ca/run.log` |
| runner-error v2 B3e兼容 | `2 passed` | `/private/tmp/ai-auto-lrc-s18-runner-error-v2.E3PEXK` |

永久temp-unlink首次Gate曾出现派生的 `EVIDENCE_BINDING_INVALID`：verifier在events bounded read失败后又以替代空bytes参与hash比较，形成无独立意义的双报。修复后它只报告 `COMMAND_FAILED, PYTEST_EVENTS_INVALID`；禁止把旧三项Gate固化为新oracle，也禁止为消除双报而放宽events的single-link读取规则。

### 22.6 剩余 57 条 exact inventory 与测试 oracle

下表中的“×2”表示capture与retention各一条独立record、独立outer node和独立fresh evidence root；唯一例外existing-attempt只有runner一条。planned记录中的exit、marker、artifact set和Gate不得在首次真实characterization前预填。

| variant | 数量 | phase | 必须生成的fixture或mutation | 稳定GREEN oracle |
|---|---:|---|---|---|
| nodeid boundary | 2 | collection | 原始UTF-8恰好4096 bytes | pytest/outer 0；FULL；Gate PASS；证明bytes而非chars |
| nodeid plus one ASCII | 2 | collection | ASCII nodeid 4097 bytes | 进入case map前fail closed；无partial events/temp；真实exit后冻结 |
| nodeid plus one multibyte | 2 | collection | 多字节Unicode nodeid 4097 bytes且不normalize | 与ASCII独立证据；不能由字符数触发 |
| serialized boundary | 2 | sessionfinish | producer-valid compact JSON加单尾换行恰好8388608 bytes | `st_size=8388608`；single-link `0600`；FULL；Gate PASS |
| serialized plus one | 2 | sessionfinish | 不超case/nodeid限制的合法document 8388609 bytes | 写盘前fail closed；final/temp absent；真实sessionfinish exit和Gate后冻结 |
| invalid limit zero | 2 | configure | 单一target argv值为0 | configure EARLY；稳定marker；无traceback/INTERNALERROR |
| invalid limit negative | 2 | configure | 单一target argv为负数 | configure EARLY；不得进入producer运行 |
| invalid limit nondecimal | 2 | configure | ASCII非十进制字符串 | configure EARLY；精确拒绝原因 |
| invalid limit nonascii | 2 | configure | 非ASCII十进制字形 | configure EARLY；不得被Unicode数字解析接受 |
| invalid limit excessive digits | 2 | configure | 5000位十进制字符串 | 在`int()`前拒绝；无`ValueError`、traceback或INTERNALERROR |
| invalid limit over ceiling | 2 | configure | 比hard ceiling大1 | 用有界字符串比较拒绝；不溢出、不截断 |
| duplicate max cases | 2 | configure | `--security-events-max-cases`重复一次 | 只改变目标lane argv；configure EARLY；控制lane PASS |
| duplicate max nodeid bytes | 2 | configure | `--security-events-max-nodeid-bytes`重复一次 | 同上；保留argv顺序和双值receipt |
| duplicate max events bytes | 2 | configure | `--security-events-max-bytes`重复一次 | 同上；不得静默采用first/last wins |
| write zero | 2 | pre-publication | 第一次`os.write()`返回0 | hard deadline前主动失败；不再write/fsync/link；无本次final/temp |
| existing final | 2 | configure | runner前预置final并记录身份 | 旧final `(dev,ino,mode,nlink,size,hash)`逐字段不变；不能代签publish race |
| temp open | 2 | pre-publication | 精确在`O_CREAT|O_EXCL` open失败 | 不获得ownership；不得清理旧文件；final absent |
| fchmod | 2 | pre-publication | temp open成功后fchmod失败 | 只清理本次owned temp；不进入write/fsync/link |
| partial write success | 2 | pre-publication | 多次short write后完成 | write调用大于1；最终bytes精确；pytest/outer 0；FULL Gate PASS |
| write exception after partial | 2 | pre-publication | 至少一次short write后异常 | producer publication failed；owned temp清理；final absent |
| file fsync | 2 | pre-publication | 完整write后file fsync失败 | 不执行link；owned temp清理；NO_EVENTS Gate精确失败 |
| file close | 2 | pre-publication | file fsync后close失败 | 与directory close区分；不发布final；主异常不被cleanup覆盖 |
| temp unlink retry | 2 | post-publication | link后首次unlink失败、cleanup retry成功 | commit uncertain；final `nlink=1`、temp absent；Gate仅`COMMAND_FAILED` |
| directory fsync | 2 | post-publication | open directory后fsync失败 | final保留single-link `0600`；Gate仅`COMMAND_FAILED` |
| directory close | 2 | post-publication | directory fsync成功后close失败 | final保留；commit uncertain；不得误报events invalid |
| preexisting temp | 2 | pre-publication | 预置当前PID命名规则temp | 旧temp身份逐字段不变；`O_EXCL`拒绝；final absent |
| syscall order | 2 | publication | 记录型wrapper加真实filesystem calls | 精确`open/fchmod/write+/file-fsync/close/link/unlink/open-dir/dir-fsync/close`；禁replace/rename |
| publish race | 2 | pre-publication | file fsync后、link前插入competitor | winner身份不变；本次temp清理；不做directory fsync |
| existing attempt | 1 | pre-run | 预置attempt root与marker | outer exit 2；stderr `SECURITY_COVERAGE_RUNNER_INPUT_INVALID\n`；stdout空；目录逐字节不变；不启动pytest |

合计：nodeid 6、serialized 4、invalid/duplicate limits 18、writer/preexisting/race 26、post-publication 6、syscall order 2、existing attempt 1，共57。

### 22.7 可执行批次和每批完成数

为降低一次性变更和证据失效范围，剩余工作按以下顺序执行；同一时刻只允许一个实现角色写入，架构和QA只读审查，文档由主任务在批次冻结后统一追加：

| 批次 | 新增implemented | 累计implemented | 范围 |
|---|---:|---:|---|
| A | 18 | 28/67 | configure invalid/duplicate argv |
| B | 6 | 34/67 | nodeid boundary/+1 |
| C | 4 | 38/67 | serialized exact 8 MiB/+1 |
| D | 14 | 52/67 | write-zero、temp-open、fchmod、partial/write/fsync/close |
| E | 6 | 58/67 | existing final、preexisting temp、publish race |
| F | 6 | 64/67 | temp-unlink retry、directory fsync/close |
| G | 2 | 66/67 | exact syscall order |
| H | 1 | 67/67 | existing attempt global runner input |

每批输入：上一批冻结hash、exact 67-record authority、独占 `mktemp -d` evidence root、复制的最小仓库、真实uv/pytest和产品runner、仅目标lane生效的mutation recipe。启动高成本real-runner前必须确认没有其他pytest/runner进程。

每批 RED：authority继续保持planned；用非authority characterization node触发尚不支持的recipe；保存首次真实inner/outer exit、stdout/stderr、artifact exact set、final/temp/sentinel before/after和所有mutated files hashes。zsh glob、fixture导入、缺runner等错误单独标成runner/fixture error，不算合同RED。

每批 GREEN：mutation helper只支持该exact recipe；capture和retention对称记录分别通过，目标fault时控制lane完整PASS；实际结果填入15字段；status、outer nodeid和pytest参数在同一原子patch中晋级；EARLY外部verifier精确INPUT_INVALID/no output，其余producer-external replay与runner Gate完全相等。

每批最小测试矩阵：

| 维度 | 目标lane | 控制lane |
|---|---|---|
| command argv | exact mutation或canonical argv | canonical argv |
| pytest exit | authority实测精确值 | 0 |
| outer exit | authority实测精确值 | 同一outer run整体结果 |
| marker | 精确一次或明确null | 无错误marker |
| Gate | null、空列表或精确有序失败 | `passed=true, failures=[]` |
| artifact set | required/forbidden exact equality | FULL exact profile |
| final/temp | authority精确状态 | final single-link `0600`、temp absent |
| hashes | 全部mutated files base/mutated加artifact manifest | artifact manifest |
| replay | Gate相等或EARLY INPUT_INVALID | Gate相等 |
| sentinel | before/after身份相等 | 不受影响 |

每批完成后立即运行轻量authority门：15 keys、总数67、implemented/planned计数、scenario ID唯一、implemented outer nodeid与实际collection双向相等、planned无nodeid和未观察结果、小写 `b3fl...` 参数ID、无decorated Spec ID、B3e scenario manifest和P1 inventory未自动晋级。

### 22.8 各批次特有执行约束

Batch A 的argv mutation只改目标lane一个参数位置；duplicate保留两次出现的顺序和值。所有configure EARLY场景必须使用runner-error v2，且5000位数字不得到达Python `int()`异常路径。

Batch B 先由独立生成器证明字符数与UTF-8 bytes数；4097场景不得被case count或serialized budget提前触发。ASCII与multibyte必须是两条独立authority、node和evidence。

Batch C 的8 MiB构造必须保持case count `<4096`、每个nodeid `<=4096`，并用独立长度计算器证明compact JSON加单尾换行的最终bytes。禁止降低冻结limit加速，禁止用synthetic unit直接调用serializer代签真实runner。允许共享fixture生成算法和immutable source template，不允许复用attempt evidence。

Batch D 的每个recipe只能命中一个syscall阶段。write-zero必须在隔离子进程和hard deadline内主动失败；partial-write-success必须真实多次write后成功；file close与directory close不可共用含糊recipe。cleanup异常不得覆盖主异常。

Batch E 必须记录preexisting或competitor的 `(dev,ino,mode,nlink,size,sha256)` before/after。禁止用glob推断ownership；existing-final预检不能代签link时竞争；publish-race不得覆盖或chmod winner。

Batch F 以link成功为publication线性化点。所有错误保留final并报告 `PYTEST_EVENTS_COMMIT_UNCERTAIN`；不得删除final回滚，不得吞掉commit-uncertain。single-link合法final只允许Gate `COMMAND_FAILED`。

Batch G 必须调用真实filesystem并同时记录trace；仅mock调用序列不算GREEN。trace文件放在产品target allowlist外，并由外层receipt绑定；任何缺失、重复、改序或replace/rename调用都失败。

Batch H 在runner输入层完成，不套用双lane模型。不能创建capture/retention目录，不能修改旧attempt，不能伪造pytest exit或Gate。

### 22.9 停止条件和逻辑回滚

任一条件出现立即停止当前批次、保留全部raw并维持未完成record为planned：

- control lane非PASS，或mutation泄漏到非目标lane；
- inner/outer exit、marker、Gate顺序在稳定重跑间漂移；
- artifact set出现未知文件，或通过glob放宽；
- receipt未绑定所有mutated files、artifacts或sentinel/final/temp身份；
- source/test/policy/manifest/toolchain before/after意外漂移；
- write-zero超deadline；
- preexisting final/temp/sentinel/attempt被覆盖、chmod或删除；
- post-link错误被降级为安全未提交，或final被删除回滚；
- external replay与runner Gate不一致；
- 为GREEN放宽schema、failure list、node、threshold、skip或artifact allowlist；
- 发生网络、sync、cache或lock写入；
- attempt目录已经存在。

“回滚”只表示停止当前切片、保留RED/fixture error/runner error/retry字节、修复后创建新attempt。禁止 `git reset`、`git checkout`、`git clean`、广泛删除、恢复历史v1文件或覆盖旧attempt。全部modified/deleted/untracked文件及根目录 `./=` 继续保留。

### 22.10 最终 67 条同 hash replay 门

逐批GREEN只是开发checkpoint，不能拼接成最终closure；原因是后续批次会修改contract test，而run-manifest绑定测试字节。Batch H完成后必须在最终冻结hash下从fresh roots执行：

1. authority精确 `67 implemented / 0 planned`；
2. collect-only得到exact 67 outer nodeids并与authority双向相等；
3. replay全部67 records，不能只重跑每批新增节点；
4. 每个target fault都有另一lane完整PASS；
5. 所有FULL/NO_EVENTS场景的producer-external replay与原Gate相等；
6. 所有EARLY场景精确verifier exit2、INPUT_INVALID、no output；
7. B3e 7个implemented scenarios回归，13个planned macOS/Linux场景仍不缩水；
8. P1 inventory仍保持既有product-plan ID总量和S18_P1状态，不因B3f authority自动晋级；
9. 完整security contract、docs links、Spec Inventory、Ruff、py_compile、bash-n、JSON解析和`git diff --check`在同一hash下通过；
10. 保存新的exclusive evidence root、JUnit、raw、hash manifest和最终五文件/authority hashes；
11. 此后任何source/test/policy/runner/verifier/plugin变化都使最终67 replay历史化，并要求重新执行本门。

B3f-L完整闭合后仍先执行B3f-R named core runtime/lock/offline binding和final-schema replay；不能直接跳到macOS/Linux Security qualification。

### 22.11 最大声明和未授权边界

当前10/67 checkpoint最多允许声明：

> B3f-L 的15字段scenario authority已冻结67个不可缩减场景，其中10个capture/retention real-runner records已完成host mutation contract，包括case count boundary/+1及代表性的pre/post-publication writer failures；其余57个仍为planned。

只有最终67/67、同hash replay和本节完整回归门全部通过后，才允许增加：

> pytest events producer在声明的case数量、单nodeid UTF-8字节数和最终events artifact字节边界内fail closed；capture/retention real runner、policy、command argv、producer、verifier、artifact hash closure和writer publication状态机在该host contract范围内闭合。

即使上述完成，仍不得声明pytest全进程资源有界、B3f-R runtime/lock provenance完成、Linux或双平台qualification、ABA-safe、immutable snapshot、transactional、crash/power-loss durable、wheel/signature/SBOM provenance或Release批准。

S18、W1b-5b、Release继续 **No-go**。W1b-5c/5d/5e、commit、push、创建CI、upload/sync、签名、发布、archive、restore、delete和destruction仍未授权。

## 23. v1.10 B3f L Batch A configure argv checkpoint

> 当前有效版本：`S18-P1-PLAN-v1.10`
>
> 本节追加第22.7节Batch A的真实RED、characterization、GREEN与Teams终审。第22节继续作为剩余Batch B至H的完整执行规范；Teams记录见[`team-sessions/team-session-2026-09-07-9.md`](./team-sessions/team-session-2026-09-07-9.md)。

### 23.1 当前状态和唯一下一步

Batch A的9个configure argv variant已在capture/retention双lane全部真实实现，共18条。Authority当前精确为：

```text
total = 67
implemented = 28
planned = 39
```

整个B3f-L仍为 **PARTIAL / No-go**。唯一下一步是第22.7节Batch B的6条nodeid boundary/+1记录；不得重做Batch A、不得把28/67写成B3f-L闭合，也不得进入B3f-R。

当前冻结字节：

| 文件或对象 | SHA-256 |
|---|---|
| `packaging/security-coverage-policy.toml` | `c7e02af2303a1ada48590493abfc605737c3185327aeec1eceb19eb5355a39cd` |
| `scripts/pytest_security_events.py` | `aa44ed1307b221c3cdd538e31942a0005abf399f3ff76a1b3a0e042454c91ef6` |
| `scripts/run_security_coverage.sh` | `ba633df67a85b2854a82e41fdb607bed6dd652bd0dbfd3c8788eb45a01972bb8` |
| `scripts/verify_security_coverage.py` | `354db6f314a75b3468ebb76ceface16a5f8a990a3fc24a3533a8e08fbecaf074` |
| `tests/contract/test_security_coverage_gate.py` | `dca43ce13777fcd5971e8e630f8ff59bdaf37ba854334b8d56b34165e97b935e` |
| 67-record authority canonical bytes | `b663323b82622aafe97e38301cc53245b20fca6d9724d0f591391c131c8cf331` |

Batch A只修改合同测试与复制件mutation harness；产品policy、events plugin、runner和verifier字节不变。由于contract test字节变化，第22.5节的10条代表性证据已是历史checkpoint；最终仍按第22.10节在67/67同一hash下全量fresh replay。

### 23.2 旧 runner configuration 术语勘误

第20.4和20.6节把invalid/duplicate limit宽泛写成 `RUNNER_CONFIGURATION_INVALID`，该说法在Batch A真实注入边界下不成立，保留为历史方案。当前精确分层为：

| 输入边界 | 拒绝者 | 精确结果 |
|---|---|---|
| checked-in policy schema或冻结值异常 | 产品runner preflight | `SECURITY_COVERAGE_RUNNER_CONFIGURATION_INVALID`，pytest不启动 |
| 完整evidence中的command argv与policy不一致 | verifier | Gate `RUNNER_CONFIGURATION_INVALID` |
| copied runner在command array构造后仅对目标lane注入malformed/duplicate argv | events plugin `pytest_configure` | `PYTEST_EVENTS_CONFIGURATION_INVALID`，pytest exit4，EARLY/no Gate |

Batch A证明的是plugin configure defense-in-depth，不新增产品runner的pytest前command self-validator。若未来要把第三行提升为runner input错误，必须作为独立schema/runner迁移重新设计，不能通过改authority文本伪造。

### 23.3 Batch A exact oracle

已实现variant为：zero、negative、ASCII nondecimal、non-ASCII decimal、5000-digit excessive、over hard ceiling，以及三个limit option各自的exact duplicate。每个variant均有capture与retention独立record。

18条共同实测合同：

```text
publication_phase = configure
expected_producer_code = PYTEST_EVENTS_CONFIGURATION_INVALID
expected_pytest_exit = 4
expected_outer_exit = 1
expected_gate_failures = null
artifact_profile = early-configure
expected_final_state = absent
expected_temp_state = absent
expected_sentinel_state = unchanged-mode-0600
status = implemented
```

`early-configure`与collection EARLY不同，精确只有六件：

```text
command.json
environment.json
plugin-identity.json
runner-error.json
stdout.log
stderr.log
```

没有JUnit、coverage raw/JSON、events、run-manifest、Gate或verifier stderr。`runner-error.json`保持exact schema v2、stage `raw-completeness`、reason `REQUIRED_RAW_ARTIFACT_MISSING`、pytest/environment/command exits `4/0/0`、qualification `INCOMPLETE_RAW_EVIDENCE`以及present/missing/hashes闭包。

复制件mutation只改 `scripts/run_security_coverage.sh`，在canonical command array完成后、执行subshell前按目标lane注入；非目标lane argv逐元素保持canonical。invalid只替换一个值；duplicate紧邻插入完全相同token并断言count精确为2，拒绝first-wins和last-wins假绿。5000位值真实进入command与receipt，stderr marker精确一次且不含Traceback、INTERNALERROR、`Exceeds the limit`或整数转换异常。

目标lane external verifier精确exit2、stderr `SECURITY_COVERAGE_INPUT_INVALID\n`、stdout空、无output Gate；控制lane精确12件FULL profile、command exit0、Gate PASS并由外部verifier重放相等。Receipt的唯一mutated file为复制runner，base/mutated hash不同；events plugin和目标test hash不变，sentinel不变，`uses_fake_uv=false`。

### 23.4 RED GREEN 和独立 QA 证据

| 阶段 | 结果 | 证据 |
|---|---|---|
| 首次TDD RED | mutation harness尚不支持Batch A recipe | `/private/tmp/ai-auto-lrc-s18-b3f-batch-a-red.WPzjfa/run.log` |
| 首个真实characterization | zero capture确认exit4/outer1、六件early-configure、no Gate | `/private/tmp/ai-auto-lrc-s18-b3f-ewqg0ncp` |
| 实现方18节点GREEN | `18 passed in 38.26s` | `/private/tmp/ai-auto-lrc-s18-b3f-batch-a-final.Nhl1ru/run.log` |
| QA authority/parameter/collection | `4 passed in 0.13s` | `/private/tmp/ai-auto-lrc-s18-b3f-batch-a-qa.amGKK3`；JUnit SHA-256 `a795975d94375c674b09dbcdf7a17cd25e1e81188a103241c7ab6030c5ae8952` |
| QA fresh 18节点 | `18 passed in 38.22s` | 同上；JUnit SHA-256 `08f9975eb9a3fa5b9d1c1e269576354b6991dfe6cf71e9b56006ce59838cdfaa` |
| QA 468核心文件复核 | 全部hash闭合 | checksum list SHA-256 `5822799ff8cc94f8cf808b762e17dcd955c1540b3ed81cee21a452ee572fa516`；QA manifest SHA-256 `3fec6debb54ba536ca514a0225e493a25d1b53607a347600631f1086b1202eeb` |

实现方Bash syntax、Python compile、Ruff和4个轻量authority节点通过。QA未运行full contract；本批checkpoint不代签最终完整security contract或第22.10节67条同hash replay。

### 23.5 Batch B 恢复胶囊

Batch B只实现以下6条：

```text
B3F-L-003-nodeid-boundary:capture|retention
B3F-L-004-nodeid-plus-one-ascii:capture|retention
B3F-L-004-nodeid-plus-one-multibyte:capture|retention
```

开始前确认无pytest/runner进程、重算第23.1节hash并保持其他33条planned。先以非authority characterization node生成真实fixture，独立证明每个nodeid的Python字符数与原始UTF-8 bytes；boundary恰好4096 bytes，ASCII与multibyte分别恰好4097 bytes且不normalize。4097错误必须在case-map插入前由nodeid byte limit触发，不能由case count、canonical grammar或serialized budget抢先失败。

首次真实结果稳定前不预填exit、artifact profile或Gate。预计boundary为FULL/PASS，+1为collection EARLY/no Gate，但只能按实测晋级。完成后authority应为 `34 implemented / 33 planned / 67 total`，并执行6个exact real-runner nodes、4个authority/collection节点和fresh evidence checksum；任何控制lane失败、ASCII/Unicode语义合并、字符数代替bytes、unknown artifact或external replay漂移都立即停止并保留raw。

S18、W1b-5b、Release继续 **No-go**。W1b-5c/5d/5e、commit、push、CI、upload/sync、签名、发布、archive、restore、delete和destruction仍未授权。

## 24. v1.11 B3f L Batch B nodeid bytes checkpoint

> 当前有效版本：`S18-P1-PLAN-v1.11`
>
> 本节追加第23.5节Batch B的真实fixture裁决、GREEN与QA复验。第22节继续定义剩余Batch C至H和最终67条同hash replay；Teams记录见[`team-sessions/team-session-2026-09-07-10.md`](./team-sessions/team-session-2026-09-07-10.md)。

### 24.1 当前状态和唯一下一步

Batch B的nodeid boundary、ASCII +1、multibyte +1在capture/retention双lane全部实现。Authority为：

```text
total = 67
implemented = 34
planned = 33
```

当前唯一下一步是第22.7/22.8节Batch C的serialized exact 8 MiB与8 MiB+1共4条。B3f-L仍为PARTIAL/No-go，不进入B3f-R。

当前冻结字节：

```text
policy     c7e02af2303a1ada48590493abfc605737c3185327aeec1eceb19eb5355a39cd
events     aa44ed1307b221c3cdd538e31942a0005abf399f3ff76a1b3a0e042454c91ef6
runner     ba633df67a85b2854a82e41fdb607bed6dd652bd0dbfd3c8788eb45a01972bb8
verifier   354db6f314a75b3468ebb76ceface16a5f8a990a3fc24a3533a8e08fbecaf074
tests      be3ccca37715c1f027232d71a58f85c7ca9fa8ea11a93b1ea089dac7c8d2c2c9
authority  59d8c9cae97108482c34a7b50b6e577bfdf57f566a1533e3c1c0dd935d0eb31f
```

### 24.2 Raw Unicode fixture 裁决

Pytest默认会转义非ASCII parameter ID，直接使用 `pytest.param(id=<unicode>)`不能证明plugin接收到原始multibyte nodeid。Batch B没有修改产品pyproject或runner argv，而是在复制的目标测试模块中注册：

```text
globals()["test_b3f_nodeid_fixture[<raw-payload>]"] = callable
```

`[`前的函数名保持ASCII canonical grammar，Unicode只在平衡bracket suffix中。Pytest按模块字典key收集该项，不经过parameter-ID escaping。原callable别名不以 `test_`开头并在注册后删除；payload禁止bracket和控制字符；真实collect必须只新增一个item，且完整nodeid与预构造bytes逐字相等。唯一mutated file是目标test，control lane不含该测试，plugin/runner/pyproject保持不变。

首次probe因collect-only生成pycache使复制仓库dirty，被保留为fixture error；fresh retry使用Python `-B`与`PYTHONDONTWRITEBYTECODE=1`，没有删除或覆盖旧attempt。

### 24.3 三类 exact oracle

| variant | 完整nodeid实测 | lifecycle | 结果 |
|---|---|---|---|
| boundary | ASCII chars=bytes=`4096` | collection/FULL | pytest/outer 0；Gate PASS；events与JUnit同一raw nodeid |
| ASCII +1 | chars=bytes=`4097` | collection/EARLY | `PYTEST_EVENTS_LIMIT_EXCEEDED`；pytest4/outer1；no Gate |
| multibyte +1 | decomposed `e + U+0301`；chars=`2754`、bytes=`4097`；NFC不同 | collection/EARLY | byte guard拒绝，不由char guard触发；pytest4/outer1；no Gate |

每个复制件只新增一个case，实测总case数capture `25`、retention `16`，远低于4096。独立serialized upper bound为capture `11573/11574`、retention `9104/9105` bytes，远低于8 MiB，因此+1不是被case count或serialized estimate抢先拒绝。

+1场景精确保留collection EARLY七件，runner-error v2闭合，external verifier exit2/`SECURITY_COVERAGE_INPUT_INVALID\n`/no output；控制lane FULL PASS。Boundary final single-link `0600`、temp absent，producer-external replay与Gate相等。

### 24.4 证据

| 证据 | 结果 | 路径或hash |
|---|---|---|
| 实现方fresh 6节点 | `6 passed in 12.91s` | `/private/tmp/ai-auto-lrc-s18-b3f-batch-b-final-retry.KzDN8P`；JUnit `4bfd6df8ce3c4cc7faf004058caeb440c378d7137d61ad83f5be5f40246d59a8` |
| 实现方静态与authority | Bash/Ruff/compile通过；`4 passed` | `/private/tmp/ai-auto-lrc-s18-b3f-batch-b-checks.V3L7yp` |
| QA fresh 6节点 | `6 passed in 13.28s` | `/private/tmp/ai-auto-lrc-s18-b3f-batch-b-qa.t5HJQy`；JUnit `78e58581fb6e86668bbdcae0c25479636e80b79f7f2c92ab12de5058074b6a14` |
| QA authority/collection | `4 passed in 0.15s` | 同一QA root |
| QA 180核心文件checksum | 全部闭合 | `562fcf7c1088e95e141e9ea2d0de3d574c6b570754c86213aefd0cf8964fca6a`；manifest `9a17a4c8760dd693a2ec90d8b883dbc9bfd5e363c29348aa71c5de0712c26ef5` |

本批没有运行full suite；后续test字节变化会使本节real-runner evidence历史化，最终仍必须执行第22.10节67条同hash replay。

### 24.5 Batch C 恢复胶囊

只实现 `B3F-L-005-serialized-boundary` 与 `B3F-L-006-serialized-plus-one` 的capture/retention四条。Fixture必须保持case count `<4096`、每个nodeid `<=4096`，使用合法三阶段shape，并由独立计算器证明compact JSON `ensure_ascii=False`加单尾换行精确为8388608或8388609 bytes。禁止降低limit、超长非法nodeid、超过case limit或直接调用serializer的synthetic unit代签。

真实characterization前保持4条planned，不预填sessionfinish exit、artifact profile或Gate。Boundary必须以磁盘 `st_size=8388608`、single-link `0600`、FULL/Gate PASS证明；+1必须在写盘前fail closed、final/temp absent。若coverage/JUnit/identity完整，预计Gate为 `COMMAND_FAILED, PYTEST_EVENTS_INVALID`，但必须按首次真实结果冻结。完成目标为 `38 implemented / 29 planned / 67 total`。

S18、W1b-5b、Release继续 **No-go**。W1b-5c/5d/5e及全部禁止事项不变。

## 25. v1.12 B3f L Batch C serialized hard check checkpoint

> 当前有效版本：`S18-P1-PLAN-v1.12`
>
> 本节追加Batch C的可达性勘误、exact-ceiling RED/GREEN与独立QA。第24.5节保留原始方案但其“正常producer自然到达8 MiB”含义被本节取代。Teams记录见[`team-sessions/team-session-2026-09-07-11.md`](./team-sessions/team-session-2026-09-07-11.md)。

### 25.1 当前状态和唯一下一步

Batch C四条serialized boundary/+1 records已GREEN，authority为 `38 implemented / 29 planned / 67 total`。当前唯一下一步是第22.7节Batch D的14条pre-publication I/O/partial-write records；B3f-L仍为PARTIAL/No-go。

```text
policy     c7e02af2303a1ada48590493abfc605737c3185327aeec1eceb19eb5355a39cd
events     aa44ed1307b221c3cdd538e31942a0005abf399f3ff76a1b3a0e042454c91ef6
runner     ba633df67a85b2854a82e41fdb607bed6dd652bd0dbfd3c8788eb45a01972bb8
verifier   354db6f314a75b3468ebb76ceface16a5f8a990a3fc24a3533a8e08fbecaf074
tests      111d6ecdbd9918f9afa86c6d23a5d51837f1757d5aa725f7aa277e3709f98236
authority  b961e5e2bedc33ea5dd07e35342d78eeb65a7a4f0e09b63eee0217b370815f44
```

### 25.2 自然路径不可达与声明修正

正常producer的collection estimator对每个case使用三阶段最坏shape；verifier-valid实际lifecycle严格小于该估算。因此任何合法final精确达到或超过8388608 bytes时，natural serialized upper bound已经大于limit，会先在collection拒绝。第20.6、22.6和24.5节中的“producer-valid 8 MiB/+1”不能解释为未修改producer自然到达sessionfinish。

Batch C精确证明的是：target-only copied-plugin collection-budget fault injection允许预先计算的exact corpus通过collection，而sessionfinish serializer、hard limit、writer和verifier保持产品原实现。005验证第二道hard check、writer和verifier接受exact limit；006验证estimator受控失效时sessionfinish仍拒绝limit+1。不得扩大为normal producer可自然生成8 MiB artifact。

### 25.3 Exact ceiling mutation 与 QA RED

首次实现把目标lane的collection serialized比较完全跳过。QA在启动新runner前静态拒绝：这不等于“使用独立natural upper bound作为精确ceiling”。该版本和其4-node结果保留为RED，不能计入本checkpoint。

修复后目标与控制均保留同一比较表达式；目标ceiling为独立计算并receipt绑定的literal，控制else分支仍使用policy `8388608`。四个literal分别为：

```text
boundary capture    8394554
boundary retention  8394527
plus-one capture    8394555
plus-one retention  8394528
```

Mutation只改变复制plugin的collection比较hunk和目标test；不修改state limits、events limits、runner argv、policy、sessionfinish、serializer、writer或verifier。Receipt断言scenario/target/policy limit/natural upper bound和copied plugin exact fragment，控制lane不进入target ceiling。

### 25.4 Exact byte oracle 与实测结果

独立oracle不用产品 `_canonical_events_bytes()` 或 `_worst_case_bytes()`，直接重建events v3 document并使用标准JSON compact参数加单尾换行。动态global tests真实调用 `_exercise()`；case count低于4096、所有nodeid不超过4096 bytes。

| scenario | target | expected size/hash | cases | 真实结果 |
|---|---|---|---:|---|
| 005 boundary | capture | 8388608 / `e88c9818529d7a8b50020cde450de5aa1dfc49f4f36655ec9c6e2735f6fdd171` | 1982 | raw逐字相等；FULL；Gate PASS；0600 single-link |
| 005 boundary | retention | 8388608 / `50860b9eb171772b279290525e1d2be2ade826b4414bd83335346f7d6cb2a31c` | 1973 | raw逐字相等；FULL；Gate PASS；0600 single-link |
| 006 plus-one | capture | 8388609 / `06146f8cb651275afb05d58c5b147f8777c2dcb82cc5e94133d4464cce52d0ed` | 1982 | pytest4/outer1；NO_EVENTS 11件；final/temp absent |
| 006 plus-one | retention | 8388609 / `17e4df8ec0af8aa142fd06471d1a2d64ef3e226351289d1c8491c2b1fd9ef716` | 1973 | pytest4/outer1；NO_EVENTS 11件；final/temp absent |

006 marker精确 `PYTEST_EVENTS_LIMIT_EXCEEDED`，无Traceback/INTERNALERROR/config-invalid；Gate有序为 `COMMAND_FAILED, PYTEST_EVENTS_INVALID`，外部replay exit1且Gate逐字相等。Control lane全部FULL PASS。

### 25.5 最终证据与透明性

| 验证 | 结果 | 证据 |
|---|---|---|
| 实现方fixed exact4 | GREEN | 4 roots与134项checksum `/private/tmp/ai-auto-lrc-s18-b3f-batch-c-fixed-checks.2XAN4J` |
| QA authority/collection | `4 passed in 0.13s` | `/private/tmp/ai-auto-lrc-s18-b3f-batch-c-qa-authority.4gG073`；JUnit `47642fc8e496323b8f71b41d691756d814ae1d9d5dbaccc54ab78a0ee3d92b2a` |
| QA fresh exact4 | `4 passed in 34.58s` | `/private/tmp/ai-auto-lrc-s18-b3f-batch-c-qa-exact.weAVU0`；JUnit `3e64f7b99607570e403d7ec39699ae59f08ce262d346a4e44237d37cc05058d8` |
| QA 134项evidence checksum | 闭合 | `24229ffce09da08bb78437a11ee8ab56310e91810a8647bf35bd8638eb7faab6` |

QA首次authority命令误用 `uv run pytest`，在collection前失败；两个离线validator草稿还有缩进/语法与过宽假设错误。这些均保留为QA runner/validator error，不算合同RED，也未修改repo或evidence。修正后的独立validator通过。

### 25.6 Batch D 恢复胶囊

Batch D只实现write-zero、temp-open、fchmod、partial-write-success、write-exception-after-partial、file-fsync、file-close七个variant的capture/retention，共14条，完成目标 `52 implemented / 15 planned / 67`。每个recipe只能命中一个精确syscall阶段，复制plugin target-only mutation，receipt绑定所有modified files和call trace。

Partial-write-success必须真实多次write后完整发布、FULL/Gate PASS。其余预发布失败预计marker `PYTEST_EVENTS_PUBLICATION_FAILED`、final/temp absent、NO_EVENTS Gate `COMMAND_FAILED, PYTEST_EVENTS_INVALID`，但真实exit和profile须characterize后冻结。Write-zero必须hard deadline前主动失败且不再次write/fsync/link；cleanup异常不得覆盖主异常；file-close与directory-close不可混淆。

S18、W1b-5b、Release继续 **No-go**；未授权边界不变。

## 26. v1.13 B3f L Batch D pre-publication I/O checkpoint

> 当前有效版本：`S18-P1-PLAN-v1.13`
>
> 本节追加Batch D十四条pre-publication I/O records的架构裁决、RED/GREEN、marker语义勘误和独立QA。第25.6节保留执行前恢复胶囊；Teams记录见[`team-sessions/team-session-2026-09-07-12.md`](./team-sessions/team-session-2026-09-07-12.md)。

### 26.1 当前状态和唯一下一步

Batch D的write-zero、temp-open、fchmod、partial-write-success、write-exception-after-partial、file-fsync、file-close已在capture/retention双lane各实现一条，共十四条。Authority现在为 `52 implemented / 15 planned / 67 total`；B3f-L仍为PARTIAL/No-go。

```text
policy     c7e02af2303a1ada48590493abfc605737c3185327aeec1eceb19eb5355a39cd
events     aa44ed1307b221c3cdd538e31942a0005abf399f3ff76a1b3a0e042454c91ef6
runner     ba633df67a85b2854a82e41fdb607bed6dd652bd0dbfd3c8788eb45a01972bb8
verifier   354db6f314a75b3468ebb76ceface16a5f8a990a3fc24a3533a8e08fbecaf074
tests      56efc37cae5ca7aab28636660343c788b14a480aa66d702264fb1f06d4961d34
authority  9921474a3f3a83efc29f7ee6f91f7280db423b96dfa23989d486d8572060ee57
```

当前唯一下一步是第22.7节Batch E的existing-final、preexisting-temp、publish-race三种variant的capture/retention六条，完成目标为 `58 implemented / 9 planned / 67 total`。不得开始Batch F-H、B3f-R或平台资格化。

### 26.2 Fault injection架构边界

Batch D不修改产品writer；每个场景复制产品plugin后，在`_atomic_write()`的精确call site插入wrapper。Wrapper用预计算的目标`pytest-events.json`完整绝对路径识别目标lane，不能只看父目录名，也不能monkeypatch共享`os`模块。非目标lane直接调用真实`os`且不得写入trace，避免污染pytest、coverage、runner和证据写入。

Trace位于attempt目录外的fresh execution root，trace写入必须no-throw。Mutation receipt绑定scenario/target、目标output/temp/PID、fault injection position、deadline/elapsed、raw trace的size/SHA-256/parsed sequence，以及plugin、target test、runner、pytest config的base/mutated SHA-256。每例`mutated_files`精确只有`scripts/pytest_security_events.py`；control lane必须FULL/Gate PASS且trace中不存在control output。

不得用`TextIOWrapper`模拟partial write，不得以全局`os.fsync`调用次数区分file/directory fsync，不得让file-close recipe命中directory fd。File-close必须先对temp fd执行真实close再抛受控错误，以证明descriptor已关闭且不发生link；cleanup异常不得覆盖更早的主异常。

### 26.3 精确call trace与结果

| variant | 目标trace | 真实结果 |
|---|---|---|
| temp-open | `TEMP_OPEN(error)` | pytest/outer `1/1`；NO_EVENTS；final/temp absent |
| fchmod | `TEMP_OPEN ok, FCHMOD error, FILE_CLOSE cleanup ok, CLEANUP_UNLINK ok` | 同上；不进入write/fsync/link |
| write-zero | `TEMP_OPEN, FCHMOD, WRITE#1 zero, FILE_CLOSE cleanup, CLEANUP_UNLINK` | 单次zero write后主动失败；无第二次write、fsync、link或directory call |
| partial-write-success | `TEMP_OPEN, FCHMOD, WRITE+ positive, FILE_FSYNC, FILE_CLOSE, LINK, PUBLISH_UNLINK, DIR_OPEN, DIR_FSYNC, DIR_CLOSE` | pytest/outer `0/0`；FULL/Gate PASS；final `0600`、`nlink=1`；temp absent |
| write-exception-after-partial | `TEMP_OPEN, FCHMOD, WRITE#1=1, WRITE#2 error, FILE_CLOSE cleanup, CLEANUP_UNLINK` | pytest/outer `1/1`；NO_EVENTS；final/temp absent |
| file-fsync | `TEMP_OPEN, FCHMOD, WRITE+ sum=content, FILE_FSYNC error, FILE_CLOSE cleanup, CLEANUP_UNLINK` | pytest/outer `1/1`；不执行link |
| file-close | `TEMP_OPEN, FCHMOD, WRITE+ sum=content, FILE_FSYNC ok, FILE_CLOSE(after-real,error), CLEANUP_UNLINK` | pytest/outer `1/1`；无link和任何directory call |

十二条失败场景的producer code均为`PYTEST_EVENTS_PUBLICATION_FAILED`，artifact profile精确为NO_EVENTS十一件，Gate有序为`COMMAND_FAILED, PYTEST_EVENTS_INVALID`，producer-external replay与runner Gate逐字相等，final/temp absent，sentinel不变。两个partial-write-success场景的producer code为null；两次正数write分别为`1 + remainder`，累计精确等于capture 7216 bytes、retention 4774 bytes，最终FULL/Gate PASS。

Write-zero的60秒hard deadline与elapsed写入receipt；独立QA观测约1.8至2.3秒内主动失败。该结论只证明隔离runner中的writer no-progress保护，不外推为pytest全进程资源有界。

### 26.4 Producer marker语义勘误

第22.7节矩阵中的“marker精确一次”指producer产生并传播一个语义错误事件。对于未捕获的writer异常，稳定oracle是stderr中恰好一条按行锚定的终结异常记录：

```text
scripts.pytest_security_events.EventsPublicationError: PYTEST_EVENTS_PUBLICATION_FAILED
```

Python traceback还会回显包含同一字符串字面量的源码行，因此raw substring计数为2；这是展示观察值，不是第二个producer事件，也不得作为稳定通过条件。禁止为了把raw substring改成1而移动marker字面量、使用`raise ... from None`、改写为`pytest.UsageError`、过滤stderr或改变`pytest_sessionfinish()`传播链。Batch A-C的UsageError路径继续使用其既有exact-once/no-traceback oracle。

QA首次静态审查发现实现曾把raw substring `count == 2`固化为合同，立即在启动QA pytest前hard stop。最小修复改为按行锚定终结异常并要求精确一条；随后又删除了“异常必须是stderr最后一行”的冗余展示位置断言。旧十四个roots仍是有效characterization/superseded GREEN，全部保留，但不能代签最终测试hash下的Batch D GREEN。

### 26.5 RED、GREEN与独立QA证据

非authority RED在authority仍为`38/29/67`时建立，精确失败为copied-plugin不支持temp-open recipe：

```text
/private/tmp/ai-auto-lrc-s18-b3f-batch-d-red.pFUmI3
```

实现方在最终marker修复后的fresh exact-14为`14 passed`：

```text
/private/tmp/ai-auto-lrc-s18-b3f-batch-d-final2.RBiZk4
/private/tmp/ai-auto-lrc-s18-b3f-batch-d-final2-checks.BE7ueO
```

独立QA从fresh roots得到：

| 验证 | 结果 | 证据/hash |
|---|---|---|
| py_compile / Ruff | PASS | `/private/tmp/ai-auto-lrc-s18-b3f-batch-d-qa.fhlORH` |
| authority / collection | `4 passed in 0.33s` | JUnit `ba4135e1a2b549b003869041a89bb627b3cd0e6eba28cafa92f576432593f451` |
| exact 14 | `14 passed in 29.12s` | log `cf16d2d131516298b917351f82a8a7a7e9b7f096c973e72a0eaf6b2ecab361fd`；JUnit `9bc9988a2734feaec580c85b3ccd2396b6253ee6be3ae50bdd0dcb4b26fe53a7` |
| 14 fresh roots | 闭合 | `evidence-roots.tsv` `08bd49bafc1aa61d6ad9b6b9c314e8cfcb98986f285f861265b9f677c642a996` |
| 464项evidence checksum | 闭合 | `140fa52d4903cede72c15396b45f2e4077a19148bb36e4a43764bd615aff4e9f` |
| QA artifact manifest | 闭合 | `5d28fa724fdc9b6e43ece082fc837c90ba808b6e62d757ae684321fb5b52aee6` |
| ordered mutation receipts | 闭合 | `9dfcb5283cea562efc0f68a672da5f15a8ff01ff3597e336a1b0b0bddaf181f2` |

QA另行串行重放全部28个target/control verifier lanes；返回码符合Gate，输出JSON逐字相同，stdout/stderr为空。Authority独立确认为exact 15 fields、67 unique IDs、52 implemented/15 planned；planned observations保持null/empty；canonical compact加单尾换行为51036 bytes。

透明记录：实现汇总时有一次不存在workdir导致的未执行命令；QA有一次只读源码摘录命令同样因workdir误写而在进程创建前失败。二者均无状态变化，作为tool/QA command error保留，不算合同RED。QA在旧marker断言上先hard stop，修复并冻结新测试hash后才重新运行。

### 26.6 Batch E恢复胶囊

Batch E只实现existing-final、preexisting-temp、publish-race的capture/retention六条。每例必须在runner前记录受保护对象的`(dev, ino, mode, nlink, size, sha256)`并在运行后逐字段比较；不得用glob推断ownership。

- Existing-final发生在configure预检：原final逐字段不变，不能代签link时竞争。
- Preexisting-temp按目标child PID的真实命名规则预置，`O_EXCL`必须拒绝；旧temp逐字段不变，final absent，cleanup不得删除或chmod旧temp。
- Publish-race在file fsync成功后、link前插入competitor；winner身份/bytes/mode/hash不变，本次owned temp清理，不进入directory fsync。Existing-final与publish-race必须是两个独立oracle。

真实characterization前六条继续planned，不预填exit、artifact profile、marker或Gate。启动每个真实runner前先确认无其他pytest/runner；完成后只允许晋级到`58/9/67`。S18、W1b-5b、Release继续 **No-go**；W1b-5c/5d/5e及全部禁止事项不变。

## 27. v1.14 B3f L Batch E protected-object and publish-race checkpoint

> 当前有效版本：`S18-P1-PLAN-v1.14`
>
> 本节追加Batch E六条protected-object/publish-race records的时序勘误、真实EEXIST证明、RED/GREEN与独立QA。第26.6节保留执行前恢复胶囊，但其中“runner前预置”的字面含义由本节取代。Teams记录见[`team-sessions/team-session-2026-09-07-13.md`](./team-sessions/team-session-2026-09-07-13.md)。

### 27.1 当前状态和唯一下一步

Existing-final、preexisting-temp、publish-race已在capture/retention双lane各实现一条，共六条。Authority现在为 `58 implemented / 9 planned / 67 total`；B3f-L仍为PARTIAL/No-go。

```text
policy     c7e02af2303a1ada48590493abfc605737c3185327aeec1eceb19eb5355a39cd
events     aa44ed1307b221c3cdd538e31942a0005abf399f3ff76a1b3a0e042454c91ef6
runner     ba633df67a85b2854a82e41fdb607bed6dd652bd0dbfd3c8788eb45a01972bb8
verifier   354db6f314a75b3468ebb76ceface16a5f8a990a3fc24a3533a8e08fbecaf074
tests      bc713de0b96630470a91978dd5705d96d80e3eb90e5c66d23bff521a93dc0188
authority  08d8fb9c7ac9be77aac5ea4f7c25884c28d87b5f1cd945cc7995cde4846cc38e
```

当前唯一下一步是第22.7节Batch F的temp-unlink-retry、directory-fsync、directory-close三种post-publication variant的capture/retention六条，目标仅为 `64 implemented / 3 planned / 67 total`。不得开始Batch G-H、B3f-R或平台资格化。

### 27.2 预置时序勘误与target guard

Runner启动时拒绝任何已存在的artifact root，随后才创建capture/retention目录。因此第22.6和26.6节所称“runner前预置”不能解释为shell runner进程启动前写入attempt；否则只会触发runner input invalid，无法测试producer。

Batch E实际且权威的时点是：copied plugin import阶段，runner已经创建lane目录、真实Python child PID已知，但`pytest_configure()`尚未执行。在相关producer检查或syscall之前创建并记录protected object。Mutation必须同时验证canonical argv中的`--security-events=<完整绝对路径>`、`--security-target=<target>`以及预计算target output，不能只看父目录名；禁止环境变量seam、glob、预测PID和共享`os` monkeypatch。

所有protected identity使用`lstat()`并要求regular file；记录`(dev, ino, mode, nlink, size, sha256)`。六条场景的`mutated_files`精确只有copied `scripts/pytest_security_events.py`，产品plugin/runner/verifier/policy/manifest均未改动。

### 27.3 三类真实oracle

| variant | fixture/syscall trace | 真实profile与Gate | 身份oracle |
|---|---|---|---|
| existing-final | import时`O_EXCL`创建0640非events final；`FIXTURE_FINAL_CREATE -> CONFIGURE_OUTPUT_EXISTS(true)` | pytest/outer `4/1`；`PYTEST_EVENTS_CONFIGURATION_INVALID`精确一次；7项EARLY_CONFIGURE+protected final；无Gate；external replay exit2/INPUT_INVALID | final before/after六字段相等、regular、nlink1、0640；无temp；writer未进入 |
| preexisting-temp | 以真实child PID计算精确temp；`FIXTURE_TEMP_CREATE -> TEMP_OPEN(error,EEXIST,injected=false)` | `1/1`；terminal `PYTEST_EVENTS_PUBLICATION_FAILED`精确一条；12项NO_EVENTS+PID temp；Gate `COMMAND_FAILED, PYTEST_EVENTS_INVALID` | protected temp before/after六字段相等、0640、writer未获ownership；final absent；无fchmod/write/close/link/cleanup/dir调用 |
| publish-race | 真实TEMP_OPEN/FCHMOD/WRITE+/FILE_FSYNC/FILE_CLOSE后创建0640 winner；真实LINK返回EEXIST；随后只CLEANUP_UNLINK owned temp | `1/1`；terminal publication marker精确一条；FULL 12项，其中events为competitor；Gate `COMMAND_FAILED, PYTEST_EVENTS_INVALID` | winner before/after六字段相等、nlink1、0640；winner与owned temp inode不同；owned temp最终absent；无PUBLISH_UNLINK/DIR_* |

Publish-race必须调用真实`os.link()`并观测真实`errno=EEXIST`，不能复用旧link-failure的synthetic exception。Competitor final会被run-manifest绑定，但其非events内容必须被verifier拒绝；不能因artifact集合为FULL就声明evidence有效。所有十二个target/control external verifier replay均与runner Gate逐字一致，existing-final则精确为exit2、stdout空、`SECURITY_COVERAGE_INPUT_INVALID\n`且无输出Gate。

### 27.4 RED、实现GREEN与独立QA

非authority RED在authority仍为`52/15/67`时建立，精确失败为existing-final recipe unsupported，且没有启动runner：

```text
/private/tmp/ai-auto-lrc-s18-b3f-batch-e-red.TGZwzp
```

实现侧最终fresh exact-6与离线审计：

```text
/private/tmp/ai-auto-lrc-s18-b3f-batch-e-final.BByAxr
```

实现过程中曾遗漏configure phase的existing-final，使其未进入writer参数集合；在正式冻结前修正。首次轻量命令误用直接`pytest`入口导致collection import失败，改用项目规范的离线冻结`python -m pytest`后通过；另有一次错误workdir导致命令未创建进程。均保留为fixture/command error，不算合同RED。

独立QA从fresh roots得到：

| 验证 | 结果 | 证据/hash |
|---|---|---|
| py_compile / Ruff | PASS | `/private/tmp/ai-auto-lrc-batch-e-qa.nnN2Qw` |
| authority / collection | `4 passed in 0.34s` | JUnit `9542ae561aed4bc0ea20ab510f154ac5dbee472331b2d55537677babd8d1ba92` |
| exact 6 | `6 passed in 12.73s` | log `460be167c416c53c5cab739ac8042294c2249d19cfa73c9664881e843e5a8d16`；JUnit `e49d77c095ef2170c55993492ac30925b1879b66a479ac4ac09ba75d02929946` |
| 6 fresh roots | 闭合 | `fresh-evidence-roots.txt` `255ea5dfcbd6a4fdc1a702423a2fa370b7c3f2cd6c14cec78c64cf35c10846f3` |
| 18项关键checksum | 闭合 | `548a2ad6c6e7628f30f45e1f21b09f2d36622c36c76fad5a91fd224caf01f75e` |
| 独立审计 | `INDEPENDENT_AUDIT_PASS roots=6 lanes=12` | `e5422d223e620d1c92fcb34ba68c8957a653c19011a80ed9d6b6c7ed749ab260` |

QA脱离测试断言重算trace sequence/PID/absolute path/argv guard、protected六字段、artifact exact set/hash manifest、target/control exits与Gate顺序，并独立运行12次external verifier replay。QA自身首次roots行首grep只提取1条，改绝对路径后确认6条；一次组合hash/pgrep命令自观察，分离复查为空；一次错误workdir使进程未启动，正确路径复查后通过。这些全部透明保留，不算合同RED。

### 27.5 Batch F恢复胶囊

Batch F只实现temp-unlink-retry、directory-fsync、directory-close的capture/retention六条。Link成功是publication线性化点；其后任何错误都必须保留final并报告`PYTEST_EVENTS_COMMIT_UNCERTAIN`，不得删除final回滚或降级为安全未提交。

- Temp-unlink-retry：首次publish unlink失败，outer cleanup对同一owned temp重试成功；final必须0600、single-link、temp absent。Gate预计只含`COMMAND_FAILED`，但首次真实结果前不得预填。
- Directory-fsync：publish unlink成功、directory open成功，真实directory fsync失败；final保持0600、single-link、temp absent，不能误报events invalid。
- Directory-close：directory fsync成功后，对精确directory fd先真实close再注入错误；final保持，不能与Batch D file-close混淆或泄漏descriptor。

每个recipe使用精确call-site wrapper和完整absolute output guard，trace必须证明publication已发生、错误阶段唯一、cleanup没有覆盖主异常。真实characterization前六条继续planned，不预填exit/profile/marker/Gate；启动每个runner前先确认无其他pytest/runner。S18、W1b-5b、Release继续 **No-go**；W1b-5c/5d/5e及全部禁止事项不变。

## 28. v1.15 B3f L Batch F post-publication checkpoint

> 当前有效版本：`S18-P1-PLAN-v1.15`
>
> 本节追加Batch F六条post-publication records的精确call-site裁决、RED/重试/最终GREEN与独立QA。第27.5节保留执行前恢复胶囊。Teams记录见[`team-sessions/team-session-2026-09-07-14.md`](./team-sessions/team-session-2026-09-07-14.md)。

### 28.1 当前状态和唯一下一步

Temp-unlink-retry、directory-fsync、directory-close已在capture/retention双lane各实现一条，共六条。Authority现在为 `64 implemented / 3 planned / 67 total`；B3f-L仍为PARTIAL/No-go。

```text
policy     c7e02af2303a1ada48590493abfc605737c3185327aeec1eceb19eb5355a39cd
events     aa44ed1307b221c3cdd538e31942a0005abf399f3ff76a1b3a0e042454c91ef6
runner     ba633df67a85b2854a82e41fdb607bed6dd652bd0dbfd3c8788eb45a01972bb8
verifier   354db6f314a75b3468ebb76ceface16a5f8a990a3fc24a3533a8e08fbecaf074
tests      7b680054b918e9ed64a68708bf6f7d02cf75b755d95d3aec1e8d9b081ec47f9a
authority  70fa1e697a86e8119867200e9876e8354c753a68c77d36c9bc64c8c8b9e00938
```

当前唯一下一步是第22.7节Batch G的syscall-order capture/retention两条，目标仅为 `66 implemented / 1 planned / 67 total`。Batch H existing-attempt仍保持planned；不得提前做最终67条同hash replay、B3f-R或平台资格化。

### 28.2 Publication身份与descriptor角色

所有场景均以真实成功`LINK`作为publication线性化点。LINK trace即时绑定final/temp六字段：两者regular、同`(dev, ino)`、`nlink=2`、mode `0600`、size/hash一致。其后错误只能传播为`EventsCommitUncertain`，不得删除final回滚或改写为`EventsPublicationError`。

Batch D/F共享wrapper按精确源码call site区分`TEMP_OPEN/FILE_FSYNC/FILE_CLOSE`与`DIR_OPEN/DIR_FSYNC/DIR_CLOSE`，并记录输入/输出descriptor。同角色descriptor必须相等，但不要求temp fd数值与directory fd不同，因为内核可在temp fd关闭后复用整数。Control lane调用真实syscall且不写trace；`mutated_files`仍精确只有copied plugin。

最终结构审查发现首轮实现把主路径directory close和outer-finally close都包装为同名`DIR_CLOSE`。虽然首轮exact-6和离线审计通过，但该结构不能证明fault只命中主close。最终实现将它们拆为`DIR_CLOSE`与`CLEANUP_DIR_CLOSE`两个精确call site；旧roots全部保留为superseded GREEN，最终声明只绑定拆分后的新测试hash与fresh roots。

### 28.3 三类精确trace与真实结果

| variant | fault与后续trace | 真实结果 |
|---|---|---|
| temp-unlink-retry | 正常到`LINK(ok)`；主`PUBLISH_UNLINK(error,injected,before-real)`；outer `CLEANUP_UNLINK(ok,injected=false,real_call=true)`；无`DIR_*` | pytest/outer `1/1`；terminal `COMMIT_UNCERTAIN`精确一条；FULL 12；Gate仅`COMMAND_FAILED`；final 0600/nlink1；temp absent |
| directory-fsync | 正常到`PUBLISH_UNLINK, DIR_OPEN`；精确directory fd的`DIR_FSYNC(error,injected,before-real)`；同fd `DIR_CLOSE(ok,real_call=true)` | 同一exit/marker/profile/Gate/final/temp oracle；无events-invalid |
| directory-close | 正常到真实`DIR_FSYNC(ok)`；主`DIR_CLOSE`先真实close再注错，`real_close_completed=true, after-real`；`CLEANUP_DIR_CLOSE`不执行 | 同一exit/marker/profile/Gate/final/temp oracle；单次close、无double-close或fd泄漏 |

六条target场景的terminal记录均精确为一条`EventsCommitUncertain: PYTEST_EVENTS_COMMIT_UNCERTAIN`；raw substring计数不作稳定合同。明确不存在`PYTEST_EVENTS_PUBLICATION_FAILED`和`PYTEST_EVENTS_CONFIGURATION_INVALID`。所有final都是合法events，故Gate出现`PYTEST_EVENTS_INVALID`是hard stop；实际六条均只含`COMMAND_FAILED`。十二个target/control external replay均与runner Gate逐字一致，control全部canonical FULL/Gate PASS、single-link 0600、无temp/trace。

### 28.4 RED、失败root、GREEN与独立QA

非authority RED在authority仍为`58/9/67`时建立，精确失败为unsupported temp-unlink-retry recipe：

```text
/private/tmp/ai-auto-lrc-s18-b3f-fcjigjxx
/private/tmp/ai-auto-lrc-s18-b3f-batch-f-red.qFQ5hQ
```

首轮实现还在`/private/tmp/ai-auto-lrc-s18-b3f-yzsj9oij`暴露trace detail的`path`字段冲突；修复后才完成characterization。拆分`DIR_CLOSE/CLEANUP_DIR_CLOSE`前的首轮exact-6为superseded GREEN；最终实现证据为：

```text
/private/tmp/ai-auto-lrc-s18-b3f-batch-f-final2.djeTwM
```

独立QA从fresh roots得到：

| 验证 | 结果 | 证据/hash |
|---|---|---|
| py_compile / Ruff | PASS | `/private/tmp/ai-auto-lrc-batch-f-qa.qW6ETK` |
| authority / collection | `4 passed in 0.38s` | JUnit `f4791e67980a24a3541a1f8df0a71bad39100cea2511e1f0c47a8534ae227b23` |
| exact 6 | `6 passed in 12.72s` | log `d068a99966f0819947653ca097c36d043eb5aa5daa08e2de7d8b873e5c86e296`；JUnit `0767b2bc6f59051b059fda3ba87de08d4dbda737dda3137e1120c1ad966449be` |
| 6 fresh roots | 闭合 | `d04218fc826e38f287da3909d4e8cbe2f5eb984c79ff57298ffbcf0afe8464da` |
| 18项关键checksum | 闭合 | `8400f104070c4bf2da27816657ce26f6c44cc62a649ed48f2a27f3114ca61284` |
| 独立审计 | `INDEPENDENT_AUDIT_PASS roots=6 lanes=12 exact_call_sites=6 no_double_close=2` | `2e10e41356420168122f968d19f91c049bce3abdb5e19f9465eefdd37fd1fd91` |

QA脱离测试断言重算全部六个roots和十二个lanes：两个directory-close均只有一次主`DIR_CLOSE`且`real_call=true, real_close_completed=true, after-real`，全部roots的`CLEANUP_DIR_CLOSE`计数为0。QA正式exact命令两次因手工JUnit路径输入错误而在shell解析/展开阶段退出，未启动pytest/runner；每次重做空进程门后第三次正确运行。这些作为QA command error保留，不算合同RED。

### 28.5 Batch G恢复胶囊

Batch G只实现`B3F-L-014-syscall-order`的capture/retention两条。必须使用记录型exact call-site wrapper，同时调用真实filesystem；纯mock调用序列不能代签。

成功trace必须精确为：

```text
TEMP_OPEN
FCHMOD
WRITE+
FILE_FSYNC
FILE_CLOSE
LINK
PUBLISH_UNLINK
DIR_OPEN
DIR_FSYNC
DIR_CLOSE
```

每个WRITE必须为真实正数且累计等于content bytes；descriptor角色、LINK后的双链接身份和最终single-link 0600身份均须绑定。Trace不得出现`CLEANUP_UNLINK`、`CLEANUP_DIR_CLOSE`、`replace`或`rename`。Trace放在产品target allowlist外、由outer receipt绑定，control lane不得写trace。真实characterization前两条保持planned，不预填exit/profile/marker/Gate；预计FULL/Gate PASS但必须以首次真实结果冻结。完成后只允许晋级到`66/1/67`，随后才执行Batch H。S18、W1b-5b、Release继续 **No-go**；W1b-5c/5d/5e及全部禁止事项不变。

## 29. v1.16 B3f L Batch G exact syscall-order checkpoint

> 当前有效版本：`S18-P1-PLAN-v1.16`
>
> 本节追加Batch G两条record-only real-filesystem syscall-order records的静态+动态证明、RED/GREEN与独立QA。第28.5节保留执行前恢复胶囊。Teams记录见[`team-sessions/team-session-2026-09-07-15.md`](./team-sessions/team-session-2026-09-07-15.md)。

### 29.1 当前状态和唯一下一步

`B3F-L-014-syscall-order`已在capture/retention各实现一条。Authority现在为 `66 implemented / 1 planned / 67 total`，唯一planned为`B3F-L-012-existing-attempt:runner`；B3f-L仍为PARTIAL/No-go。

```text
policy     c7e02af2303a1ada48590493abfc605737c3185327aeec1eceb19eb5355a39cd
events     aa44ed1307b221c3cdd538e31942a0005abf399f3ff76a1b3a0e042454c91ef6
runner     ba633df67a85b2854a82e41fdb607bed6dd652bd0dbfd3c8788eb45a01972bb8
verifier   354db6f314a75b3468ebb76ceface16a5f8a990a3fc24a3533a8e08fbecaf074
tests      6bdd9c09ef308d55afa55a1c2730f9ba64a509057d2244adbdf8fb2d65ef7a52
authority  fc8e4d457d6e773f0091094669d694fed5667e1b2acc42d45769a208e94a9e16
```

当前唯一下一步是第22.7节Batch H的一条global runner-input existing-attempt record，目标只允许晋级到`67/0/67`。即使Batch H单条GREEN，也不能拼接旧批次宣称B3f-L闭合；随后仍必须在最终同一测试hash下fresh replay全部67条。

### 29.2 Record-only真实路径

Syscall-order recipe使用Batch D/F exact call-site recorder但`injection_position=null`，不改变write参数、memoryview或返回值，不伪造任何syscall。Target由完整absolute output与canonical `--security-events/--security-target` argv双guard绑定；control直接执行真实syscall且不写trace。所有记录均`status=ok, injected=false, real_call=true`。

两条target trace精确为：

```text
TEMP_OPEN
FCHMOD
WRITE+
FILE_FSYNC
FILE_CLOSE
LINK
PUBLISH_UNLINK
DIR_OPEN
DIR_FSYNC
DIR_CLOSE
```

`CLEANUP_UNLINK/CLEANUP_DIR_CLOSE`均未执行。每次WRITE为真实正数、不超过requested、序号连续且累计等于content bytes；不冻结WRITE次数。Temp open精确为O_WRONLY、O_CREAT、O_EXCL、O_CLOEXEC、无O_TRUNC、mode0600；directory open以`O_ACCMODE == O_RDONLY`判断，并带O_DIRECTORY/O_CLOEXEC。File/directory descriptor链按call-site role闭合，不用fd数值差异代替角色证明。

真实LINK绑定source/temp、destination/final和`follow_symlinks=false`；link后final/temp为同inode、nlink2、0600、size/hash相同，publish unlink后final为regular single-link 0600且temp absent。Target/control均pytest/outer 0/0、producer marker null、FULL/Gate PASS，四次external replay与runner Gate逐字一致。

### 29.3 No replace/rename证明边界

“无replace/rename”由静态与动态证据组合证明，范围严格限定为冻结events writer，不外推整个pytest进程：

1. Base product plugin SHA-256精确为`aa44ed...`；`_atomic_write()`的独立AST/call inventory不含`os.replace`、`os.rename`、`Path.replace`、`Path.rename`或`renameat2`。
2. Mutated copied plugin由exact base加批准recorder helper及11组call-site replacement生成；12个operation、unified diff/hash/bytes、helper hash和`_atomic_write()`前后unchanged regions全部receipt绑定。
3. 独立前向构造与逆向重建均逐字还原base；动态trace证明十阶段真实filesystem路径确实执行。

仅凭trace中没有rename不够，禁止通过全局monkeypatch `os.replace/os.rename`扩大到pytest、coverage或trace I/O。

### 29.4 RED、GREEN与独立QA

非authority RED在authority仍为`64/3/67`时建立，精确失败为unsupported syscall-order recipe：

```text
/private/tmp/ai-auto-lrc-batch-g-red.W40MB9
/private/tmp/ai-auto-lrc-s18-b3f-i5gmjk6w
```

实现侧最终证据：

```text
/private/tmp/ai-auto-lrc-batch-g-final.H0aNOM
capture  /private/tmp/ai-auto-lrc-s18-b3f-9n92375q
retention /private/tmp/ai-auto-lrc-s18-b3f-7k56ljes
```

独立QA从fresh roots得到：

| 验证 | 结果 | 证据/hash |
|---|---|---|
| py_compile / Ruff | PASS | `/private/tmp/ai-auto-lrc-batch-g-qa.sdSJSr` |
| authority / collection | `4 passed in 0.41s` | JUnit `6ba1915af10a23a6b9d960c3b2c2dcf92c8774fde00cbc8e62dda323b6e6ecea` |
| exact 2 | `2 passed in 5.10s` | log `d29346840e3f69aac05f833a631e275ee645ed051708ff4d740d9df9cbd946c0`；JUnit `1d729dceefe01cb7aa86b4c2042a1c701213f2531222e7833aabcbd6df7cd88f` |
| 2 fresh roots | 闭合 | `480835fd77bb2462f4dec4ff473320cbfeb9c1a2412a0bc246b1cee1cd50b6b6` |
| 6项关键checksum | 闭合 | `abe22e366b9b2cd74703f3bc67536505aed23b5593978383d9031c69d9ba31ea` |
| 独立AST/diff/trace审计 | PASS | `0538c7c0231ff87467ab80a14f8b1a47309eea4408ccb7b9f69977f2fbfbcca9` |

QA独立重建AST inventory、12 operations/11 replacement groups、前向/逆向base、unified diff与unchanged regions，并审计两个roots、四个lanes和四次external replay。Ruff首次因错误workdir未启动，正确路径重跑通过；作为QA command error保留，不算合同RED。

### 29.5 Batch H与最终67条恢复胶囊

Batch H只实现`B3F-L-012-existing-attempt:runner`一条全局runner-input场景。它没有capture/retention双lane、pytest exit、Gate或producer replay；不得套用writer helper。

在调用runner前预置exact attempt root和marker，并记录整个目录的递归path/type/mode/size/hash清单。真实runner必须在启动pytest前拒绝：outer exit2、stdout精确为空、stderr精确`SECURITY_COVERAGE_RUNNER_INPUT_INVALID\n`；不得创建capture/retention、不得修改任何旧字节、mode、inode或新增文件。运行后目录清单和逐文件身份必须完全相等。

真实characterization前该record继续planned，不预填outer nodeid或观察值。完成Batch H只允许晋级为`67 implemented / 0 planned / 67 total`；然后冻结最终tests/authority hash，从fresh roots collect exact 67 outer nodeids并逐条replay全部67，不能复用或拼接Batch A-H旧roots。最终replay前仍须确认无其他pytest/runner，并保持B3e/P1 inventory边界不变。S18、W1b-5b、Release继续 **No-go**；W1b-5c/5d/5e及全部禁止事项不变。

## 30. v1.17 B3f L Batch H existing attempt checkpoint

> 当前有效版本：`S18-P1-PLAN-v1.17`
>
> 本节追加唯一global runner-input record的实现、递归身份合同、RED/GREEN、独立QA和最终67条执行门。第29.5节保留执行前恢复胶囊。Teams记录见[`team-sessions/team-session-2026-09-07-16.md`](./team-sessions/team-session-2026-09-07-16.md)，SHA-256 `b9943d2f5e5688765a092d52b9f95394631ef5f342cf5325f05530333698a76c`。

### 30.1 当前状态与边界

`B3F-L-012-existing-attempt:runner`已从planned原子晋级为implemented，authority现在为`67 implemented / 0 planned / 67 total`。它是唯一target=runner的记录；其余66条仍是capture/retention real-runner记录。

```text
policy     c7e02af2303a1ada48590493abfc605737c3185327aeec1eceb19eb5355a39cd
events     aa44ed1307b221c3cdd538e31942a0005abf399f3ff76a1b3a0e042454c91ef6
runner     ba633df67a85b2854a82e41fdb607bed6dd652bd0dbfd3c8788eb45a01972bb8
verifier   354db6f314a75b3468ebb76ceface16a5f8a990a3fc24a3533a8e08fbecaf074
tests      915fbaaed6ca151c3b2b00a6983f081c1ea65cc4fc029b66b997cde82270ad07
authority  68871f33db9c20c0aa5e676e31a82f894c0133d13ff03eb7105366169dd43a44
authority  56,657 bytes
```

Batch H没有修改产品runner、plugin、verifier或policy。Authority对implemented runner采用唯一整对象特判：producer code、pytest exit和Gate failures均为`None`，required artifacts为空，forbidden artifacts只列capture/retention，outer exit为2，sentinel语义为`unchanged-recursive-tree`。其余implemented记录继续强制target为capture/retention、pytest/outer exit为整数且required artifacts非空，不能借runner特例放宽。

完成67/0/67只表示authority中没有planned记录；在最终同一测试hash下fresh replay全部67条之前，B3f-L仍为PARTIAL/No-go。

### 30.2 可执行合同与测试用例

Batch H直接调用当前工作树真实`scripts/run_security_coverage.sh`，不复制仓库、不修改runner/plugin/verifier、不使用writer mutation helper。Fresh external execution root中先建立已存在的absolute`attempt-001`：

```text
attempt-001/
├── preserve.txt             0640
├── empty.bin                0440 zero bytes
├── hardlink-source.bin      0600 nlink=2
├── hardlink-peer.bin        0600 same dev/ino
├── nested/                  0750
│   └── binary.bin           0600 NUL/non-text bytes
└── nested-link -> nested/binary.bin
```

before/after从root的`.`开始，用`lstat()`、不跟随symlink并按POSIX relative path bytes排序。每项记录`relative_path/entry_type/mode/dev/ino/nlink/size/content_sha256/symlink_target/symlink_target_sha256`；regular file由`O_NOFOLLOW`打开后再以`fstat`绑定dev/ino并流式hash。整个manifest以sorted-key compact JSON加单尾换行计算SHA-256，receipt和raw stdout/stderr均放在attempt之外。

正式节点为：

```text
tests/contract/test_security_coverage_gate.py::test_s18_b3f_existing_attempt_real_runner[b3fl012-existing-attempt-runner]
```

真实调用必须满足：argv精确4项、absolute attempt、受控run ID、attempt参数1、cwd为真实repository root、deadline 10秒，且`0 < elapsed < deadline`。精确结果为：

```text
outer exit = 2
stdout = b""
stderr = b"SECURITY_COVERAGE_RUNNER_INPUT_INVALID\n"
```

动态侧只在PATH前置attempt外的`uv` tripwire；若被执行则写外部marker并返回97。静态侧绑定runner hash并验证root-exists guard、invalid stderr/exit、platform case、repository cd、run_one、uv和capture/retention invocation的严格顺序。只有“冻结runner + 静态控制流 + 本次tripwire未触发 + recursive manifest无差异”组合起来，才支持“本次调用在pytest链前拒绝”的声明。

### 30.3 RED GREEN与QA

非authority TDD RED在authority仍为66/1/67时建立，且没有启动runner：

```text
/private/tmp/ai-auto-lrc-batch-h-red.j7oLuZ
unsupported B3f runner recipe: existing-attempt; recursive receipt unavailable
```

首次GREEN候选`/private/tmp/ai-auto-lrc-s18-b3f-existing-attempt-pql1ihg9`误把symlink mode跨平台冻结为0777；macOS实际为0755。修正只移除该常量假设，仍记录真实mode并要求before/after逐字段相等。一次可选审计还错误读取Batch G copied root中不存在的contract文件而`FileNotFoundError`；正确审计改用当前冻结hash与diff check，没有伪造历史diff。

实现侧最终证据：

```text
/private/tmp/ai-auto-lrc-s18-b3f-existing-attempt-l2y9oi53
/private/tmp/ai-auto-lrc-batch-h-final.MgnpVI
```

独立QA从fresh root复跑：

| 验证 | 结果 | 证据/hash |
|---|---|---|
| authority / collection | `4 passed in 0.43s` | JUnit `5dd18dbd3a9c18bc231b1b5fc77b83609bb48487270629bff8f70d5f322abacd` |
| exact 1 | `1 passed in 0.05s` | JUnit `ed15fa0eab1c334b42c02c800597b567fdefe38002c73c4d9900f4aa45d36b75`；log `3047bfb011884c22cbef095e577e5838c337dbd031de34d11b2f060f83b0ec11` |
| independent audit | `INDEPENDENT_AUDIT_PASS` | `abf194b862f823291c6f24ad6e2a4aba613092e110860d8b6b3fe30e1ef09731` |
| fresh evidence root | 8 entries | `/private/tmp/ai-auto-lrc-s18-b3f-existing-attempt-ykhuwhvt`；manifest `3481fda2323c34bef41fc67e5acefffa7cec724712ea6d6edbe9105e2ad50f8f` |
| QA root | 保留 | `/private/tmp/ai-auto-lrc-batch-h-qa.PsvXoo` |

QA独立重算runner顺序、结果bytes、manifest canonical bytes、root身份、hardlink、symlink、tripwire与authority。一次checksum-only命令末参数误写为`/privatelk?`，部分成功后报错；正确只读重试取得全部hash，该错误保留且不算合同失败。最终py_compile、Ruff、`git diff --check`和进程门均通过。

### 30.4 声明限制

- before/after递归manifest证明端点状态不变，不证明过程中不存在写入后恢复的ABA；不得把它表述为全程无写入监控。
- `pytest_started=false`不能脱离冻结runner hash、静态顺序和tripwire单独消费；它不是任意进程的全局instrumentation。
- receipt中的有限`generated_artifacts`名称枚举不是主要排除证据；完整manifest的新增/缺失集合均为空才排除所有残留路径。
- 本记录绑定当前host及本次继承环境，不证明恶意`BASH_ENV`、exported shell function等任意父环境下的普遍安全性。
- Batch H不是capture/retention双lane结果，没有pytest exit、Gate PASS、producer marker或external verifier replay；这些字段不得用0、空数组或伪artifact补齐。

### 30.5 最终67条同hash replay执行方案

执行门分四步：

1. 冻结上表policy/events/runner/verifier/tests/authority六项；authority是67条sorted-key compact JSON加单尾换行。另记录manifest、bootstrap、pyproject、uv.lock、capture/retention source与test的当前hash。
2. 在无其他pytest或security runner时，以真实collect-only得到exact 67 outer nodeids，并与authority的67个implemented `outer_nodeid`做双向集合相等和唯一性检查。唯一runner节点不得进入capture/retention参数集合。
3. 在同一测试hash和同一authority hash下，从全新exclusive roots一次性运行67个正式节点；不得复用Batch A-H旧roots或把各批GREEN拼接。每个limit/writer记录保留target/control、FULL/NO_EVENTS/EARLY、runner Gate/external replay一致性；唯一runner记录保留既存目录输入合同。
4. 独立QA重算67 roots、authority、hash、artifact allowlist、marker、Gate/replay、writer trace和runner-only receipt；再回归B3e七个implemented/十三个platform planned、P1 inventory、docs links、Ruff、py_compile、bash-n、JSON与diff check。运行后任何冻结对象漂移都使结果历史化并要求完整重跑。

最终67条replay完成前，B3f-L、S18、W1b-5b和Release继续 **No-go**。即使replay通过，后续仍有B3f-R、final-schema replay、hostile matrix、B4、freeze ledger以及macOS/Linux/package/canonical/host/sealed qualification DAG；不得由B3f-L自动晋级P1产品状态。W1b-5c/5d/5e继续不执行。

## 31. v1.18 B3f L Final 67 closure与B3f R0入口

> 当前有效版本：`S18-P1-PLAN-v1.18`
>
> 本节冻结B3f-L同hash final 67 replay、独立132-lane verifier replay和下一阶段B3f-R低成本合同入口。第30节保留Batch H checkpoint。Teams记录见[`team-sessions/team-session-2026-09-07-17.md`](./team-sessions/team-session-2026-09-07-17.md)，SHA-256 `51041766bb0723257b62adf00803fd4926faeabf47ca65c14169df5e7b349021`。

### 31.1 B3f L host contract结论

B3f-L已在最终测试SHA-256 `915fbaaed6ca151c3b2b00a6983f081c1ea65cc4fc029b66b997cde82270ad07`和authority SHA-256 `68871f33db9c20c0aa5e676e31a82f894c0133d13ff03eb7105366169dd43a44`下完成exact 67个formal nodeid的单次fresh replay。Authority为`67 implemented / 0 planned / 67 total`，canonical JSON加单尾换行为56,657 bytes。

当前允许声明：**pytest events producer在policy声明的case、nodeid、serialized artifact和writer fault边界内fail closed，且该host contract已在同一测试hash下重放完整authority。** 仍禁止声称pytest全进程资源有界、runtime provenance完成、平台qualification、ABA-safe、power-loss durable或Release Go。

### 31.2 单次Final 67执行

证据包为`/private/tmp/ai-auto-lrc-b3f-l-final-67.XHtcj7pg`。执行前collect raw、提取nodeids和authority的67项顺序及双向集合精确相等；分类为limits32、writer34、runner1，targets为capture33、retention33、runner1。

单次pytest invocation返回0、耗时170秒；唯一JUnit suite包含67 testcase、0 failure/error/skip，stdout只有67个fresh root记录、JUnit路径和一次`67 passed in 170.19s`摘要，stderr为0 bytes。67个root均在本次调用窗口内生成且与Batch A-H旧root无交集。

```text
final.junit.xml            04b5e5d28b3c463129889e6019cb5a918c2649b06f94b0ba97b309f451b3fd10
final.stdout               dc7e1ac0aa2dc475107c15b0d9b45fa8d7c73a86831f22110a1fe9148ccde127
final.stderr               e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855
final-evidence-roots.txt   d5abc33acfc6c083bd3049814c81ec781646c1cdae270e83a3400f3b9ac0322b
independent-summary.json   4cc3da7dc3d5fdc5625c4a4ef594eddaaabec2eddc80a92afed836f7a12683dd
bundle-files.sha256        87cabccc972a8fa29e0de59dcb7176228fb825de886e35bcab1e45bed3cd78ef
```

Policy/events/runner/verifier/tests/authority及runner闭包共14项在start/pre-run/end/current逐字节一致；normalized freeze SHA-256为`53d70de8d11e8b6199effd99f44cc92edba33ba76fd98115851b9a342b9b0654`。Git status原本非clean，起止快照相同且SHA-256均为`52fa87daa2207dda8eb208db55e641628c3c4cf7571b1caa8f99aa52046d5b90`；通过条件是无漂移，不是工作树clean。

### 31.3 独立QA闭包

QA root为`/private/tmp/ai-auto-lrc-b3f-l-final-67-qa.eyNvS9BD`。QA没有重跑高成本67，而是独立解析现有bundle并对全部132 lanes重放verifier：

- 66个nonrunner roots、132 lanes、1422 artifacts逐一重哈希；
- 106个存在Gate的lane返回码与passed状态一致，stdout/stderr为空，输出Gate bytes与runner Gate相同；
- 26个无Gate lane均return2、stdout空、stderr精确`SECURITY_COVERAGE_INPUT_INVALID\n`、不生成输出Gate；
- 66个sentinel、56个producer marker、32个limit receipt、34个writer receipt闭合；
- 唯一runner root无capture/retention、pytest或Gate，tripwire未触发，8-entry no-follow tree before/after相等。

Artifact profile计数为FULL86、NO_EVENTS16、EARLY6、EARLY_CONFIGURE18、EARLY_CONFIGURE_PLUS_EVENTS2、FULL_PLUS_TEMP2、NO_EVENTS_PLUS_TEMP2。

```text
independent-audit.json     5065f14a87f530016f6d318cc737cd0838c287a7f5b133f26282dab9144434e6
lightweight.junit.xml      6f0a237a41f5f256485e038afa3138a43bbd877ddedd6d6867fe4687d96b90a9
doc-links.junit.xml        fddd475f2adfdce446fdad1fec8beebff8e3ea5c96b6515050698f2fc281e27e
qa-artifact-hashes.json    91fe63dcd0d7a0d22106634ea249017217e5a9bed0b31e6e1e6dda6b7b28c3b7
```

QA最终PASS前有6次外部审计脚本错误：缺repo import path、误冻结collect 0.02s为0.03s、误统一合法60/240秒deadline、误把受保护或故意无效events解析为JSON。旧脚本与部分replay目录全部保留，只修正外部QA脚本，没有修改仓库或原证据。

B3e仍为7 implemented/13 planned；Spec Inventory仍为274项；S18 P1仍为7 specs、5 implemented/2 planned、verification unverified、qualification unqualified。B3f-L不代签任何上位状态。

### 31.4 B3f R架构收敛

B3f-R目标是named core runtime的`installed-record-consistent` host binding，不是wheel、完整依赖图、签名或SBOM provenance。一次breaking迁移建议为：policy v2→v3、plugin-identity v1→v2、environment v4→v5、command v3→v4、run-manifest v4→v5、Gate v4→v5；pytest-events保持v3、security manifest保持v1、runner-error保持v2。新verifier只接受新版本，不dual-read；历史artifact只能由冻结旧verifier复核。

Policy v3冻结named distributions `coverage/pluggy/pytest/pytest-cov`、Python flags `-I/-S/-B`、uv flags `--offline/--frozen/--no-sync`、required import entries和dependency edges。Runner在Batch H existing-root Bash guard后只解析一次absolute uv，之后所有Python、pytest、helper和verifier都使用同一prefix：

```text
<ABS_UV> run --offline --frozen --no-sync python -I -S -B
```

当前host低成本探针已证明该argv能启动；初始sys.path不含site-packages。Bootstrap必须从未resolve的`.venv/bin/python3`、bounded `pyvenv.cfg`推导唯一site-packages，只append路径，不调用`site.addsitedir`、不执行`.pth/sitecustomize`，并按stable bytes `compile/exec`顺序加载`pluggy -> coverage -> pytest -> pytest_cov -> pytest_cov.plugin`。

Identity v2捕获Python/uv/venv/pyvenv.cfg、四个distribution的bounded whole METADATA/RECORD bytes、required entry bytes/hash/size、exact lock package object digest及local/plugin object identity。Runtime semantic digest排除run_id/target/attempt/timestamp，允许同host两lane比较。Environment v5、command v4、run-manifest v5和Gate v5必须与identity原子交叉绑定；failure class区分`RUNTIME_IDENTITY_INVALID`、`PLUGIN_IDENTITY_INVALID`、`EVIDENCE_TOOLCHAIN_BINDING_INVALID`与`RUNNER_CONFIGURATION_INVALID`。

初始cap只在representative v2 artifact生成后冻结；候选上限为identity 4 MiB、每dist METADATA/RECORD各256 KiB、每required entry 1 MiB、pyvenv.cfg 16 KiB。当前四dist的raw METADATA+RECORD约65,936 bytes，已有identity 65,536上限在base64/JSON前已经不足，禁止直接沿用。

### 31.5 PEP 376可执行勘误

第18.6节“RECORD拒绝`..`、缺hash或缺size”不能解释为每一row无例外。当前四dist均有标准self row `<dist-info>/RECORD,,`；pytest/coverage还有合法的`../../../bin/*`console-script row。可执行规则冻结为：

1. required/import entries必须是canonical POSIX-relative path，拒绝absolute、`.`和`..`；
2. whole RECORD完整capture，parent-path的nonrequired console-script row只作opaque captured bytes，永不resolve/open，也不进入installed-entry claim；
3. 只允许一个canonical `<dist-info>/RECORD,,` self row，其hash和size必须同时为空；
4. 其他row必须有strict unpadded urlsafe SHA-256和decimal size；所有path唯一、CSV三列、NUL-free；
5. verifier独立strict decode captured bytes、重算whole-file与required-entry digest，并与live endpoint交叉。

若未来决策坚持全局拒绝任何parent row，当前真实`.venv`无法GREEN，必须hard stop并变更环境，不能修改实现掩盖。

### 31.6 唯一下一批 B3f R0

R0只添加低成本合同RED，不修改产品、不跑真实security runner。必须新增以下稳定合同节点或等价精确节点：

```text
test_s18_b3f_r_isolated_no_site_probe_derives_exact_venv_site_packages
test_s18_b3f_r_bound_package_entries_compile_from_stable_bytes
test_s18_b3f_r_record_parser_accepts_only_one_self_record_exception
test_s18_b3f_r_record_parser_never_resolves_parent_path_rows
test_s18_b3f_r_policy_v3_freezes_named_runtime_contract
```

Synthetic RECORD matrix至少覆盖safe required entries、唯一self row、opaque `../../../bin/pytest`、duplicate path、absolute path、unsafe required path、non-SHA256、self row以外缺hash/size。RED原因必须来自尚不存在的B3f-R parser/policy/isolated runtime seam，不能通过改旧断言伪造。

R0后按R1 identity producer、R2 policy/verifier/artifact schemas原子迁移、R3 runner integration与真实双lane、R4 bootstrap writer parity和final-schema replay推进。B3f-R一旦修改runner/bootstrap/verifier/policy，本节B3f-L证据会历史化；最终schema closure必须重新replay B3f-L 67、B3c/B3d/B3e core。S18、W1b-5b、Release继续 **No-go**；W1b-5c/5d/5e继续不执行。

## 32. v1.19 B3f R0 contract RED checkpoint

> 当前有效版本：`S18-P1-PLAN-v1.19`
>
> 本节冻结B3f-R0五个未来合同的有效RED、测试设计独立QA和R1输入。第31节保留B3f-L final 67与B3f-R总体设计。Teams记录见[`team-sessions/team-session-2026-09-07-18.md`](./team-sessions/team-session-2026-09-07-18.md)，SHA-256 `f4a29205144742ac326c6f359f977244fb9e1d5f5777e378468a6a3b55c40cae`。

### 32.1 RED结果

测试文件从SHA-256 `915fbaaed6ca151c3b2b00a6983f081c1ea65cc4fc029b66b997cde82270ad07`变为`06df29df55ca0c42fe02e9d908dc423172a88993c5987e8855ff8ab634ab3160`；旧文件前370,411 bytes逐字不变，新测试为纯追加。Bootstrap、runner、verifier、policy、events、manifest、pyproject和uv.lock均未修改。

Fresh collect为exact 5 unique；formal结果为`5 failed / 0 error / 0 skip`、exit1、stderr空：

| Node | 精确RED |
|---|---|
| isolated no-site probe | missing `_derive_runtime_site_packages` |
| bound package entries | missing `_load_bound_runtime_modules` |
| RECORD self-row | missing `_parse_distribution_record` |
| RECORD parent-row | missing `_parse_distribution_record` |
| policy v3 authority | current policy schema 2, expected 3 |

证据根`/private/tmp/ai-auto-lrc-b3f-r0-red.79V9ayvj`：

```text
r0-summary.json          4c71b7ec169e30d19d1773986669d8f288767d49e899679b90b3a2b20b5f6759
red-final.junit.xml      56ffd5abe6a40e7db35da325a7a968729e10eb3ca7f1400754f7f497b538b2ca
red-final.stdout         6c302d5bf1de041e4ea12157c96b6af6020ca72758be7f49d65b12e99000608a
bundle-files.sha256      e109707bac8ff222527a8e03f93529e7af7946834d6136d714787bbeee25285a
```

首次Ruff暴露两处UP012冗余UTF-8 encode参数；只机械移除参数后，五个RED原因保持不变，首次日志保留。

### 32.2 合同内容

未来API冻结为：

```text
_derive_runtime_site_packages(executable, *, python_major_minor) -> Path
_load_bound_runtime_modules(entries) -> (ordered modules, ordered identities)
_parse_distribution_record(record_bytes, *, dist_info, required_paths) -> tuple[normalized rows]
```

测试helper只构造fixture、调用future seam并观察结果，没有定义或复制产品逻辑。合同直接要求：

- isolated/no-site/no-bytecode进程从synthetic venv executable和pyvenv.cfg得到exact versioned site-packages；
- 五个required entry遵循`pluggy -> coverage -> pytest -> pytest_cov -> pytest_cov.plugin`，同一个bytes对象用于hash、compile和exec；
- 不调用`site.addsitedir`，不执行`.pth`或`sitecustomize`；
- RECORD唯一canonical self row允许空hash/size，parent-path nonrequired行opaque保留且永不resolve/open；
- invalid RECORD 10项和unsafe required-path 5项在未来seam存在后逐项进入`raises`；
- policy v3冻结provenance、named distributions、required entries、dependency edges、uv/Python flags和byte limits。

### 32.3 独立QA

QA root为`/private/tmp/ai-auto-lrc-b3f-r0-contract-red-qa.8eKCvqxs`。Fresh exact5得到相同五个RED且无额外失败；B3f-L lightweight authority/collection为4 passed，py_compile、Ruff和diff check通过。QA未发现P0/P1设计问题或跨平台inode/mode/host小版本常量。

```text
independent-audit.json    a0f9155f7de82c451dd8130f1ce98540c17db58f2439b415d2d9186c1a472944
formal.junit.xml          355fd70cb50d421d6dba5b582a76e98edba5b8472ff9858f6e06b3df9381280b
b3fl-lightweight.junit    198dbf83c07218c623b48c128185118752117d792b02bfd24bb98ad0683e880a
checksums.json            1e71b7c4445f1d736ebaf5e6592166ac862607399e9bbd0d6523a3bf4ec16638
```

QA两次工具JavaScript拼写错误均在shell命令执行前失败；正确重试后通过，未修改仓库。

### 32.4 证据时效和唯一下一步

R0改变了contract test字节，所以第31节B3f-L final 67现在是历史checkpoint；不能在新test hash下继续称其current。B3f-R final schema落地后，必须重新生成B3f-L 67和B3c/B3d/B3e core closure，不能拼接第31节证据。

当前唯一下一步为R1 bootstrap producer基础。R1只实现三个seam、isolated runtime derivation、stable-byte module loader、strict RECORD parser和synthetic identity-v2构造/rejection matrix；不修改runner/verifier/policy对外schema，不运行真实security runner。R1目标是前四个R0节点GREEN，policy v3节点继续RED直到R2原子消费者迁移。

R1不得调用`site.addsitedir`或importlib.metadata首个匹配，不得resolve parent-path opaque RECORD row，不得声称identity v2已进入真实runner。R2才允许把policy、verifier、artifact factory、environment/command/run-manifest/Gate原子迁移。S18、W1b-5b、Release继续 **No-go**；W1b-5c/5d/5e继续不执行。

## 33. v1.20 B3f R1a bootstrap primitives closure与R1b入口

> 当前有效版本：`S18-P1-PLAN-v1.20`
>
> 本节冻结R1a三个bootstrap primitive、初版QA否决、补充RED/GREEN、最终独立QA与R1b可执行合同。第32节保留R0 RED checkpoint。完整Teams记录见[`team-sessions/team-session-2026-09-07-19.md`](./team-sessions/team-session-2026-09-07-19.md)，SHA-256 `271caf7e77870a024bf7d4b6a4d35aec5142bf872d3cf422d3c9ceba494e109a`。

### 33.1 当前裁决

R1a已经实现并验证：

```text
_derive_runtime_site_packages(executable, *, python_major_minor) -> Path
_load_bound_runtime_modules(entries) -> (ordered modules, ordered identities)
_parse_distribution_record(record_bytes, *, dist_info, required_paths)
    -> tuple[normalized rows]
```

最终状态：

```text
P0                                      0
R1a scope 内未关闭 P1                   0
R1b implementation start                Go
identity v2 publish / real runner         No-go
S18 / W1b-5b / Release                   No-go
W1b-5c / 5d / 5e                         未授权，不执行
```

允许声明的最大值是：**当前host上，三个R1a primitive在已测试输入边界内提供strict venv site derivation、same-byte ordered module load和PEP 376 RECORD parsing，并统一以`BootstrapError`拒绝已覆盖的敌意输入。** 不得扩大为runtime identity原子快照、完整rollback、identity v2已发布、真实runner已绑定、Linux或双平台qualification。

### 33.2 初版GREEN与QA否决均保留

初版实现证据根为`/private/tmp/ai-auto-lrc-b3f-r1a.y8GspEqC`，文件哈希为：

```text
security_pytest_bootstrap.py
9f3a6e0136ad5c0ad1595738fe193fcaa7233e52b58a163c555de8d606cbe7a5

test_security_coverage_gate.py
30ca83b76a0928d3bdedea8cdf1b7be073c8582c115bd76cdae265847105f324
```

实现角色当时得到R1a exact7通过、legacy selection 10通过、policy-v3唯一预期RED。独立QA在相同旧哈希下也得到exact7、legacy9、静态门和当前uv alias probe通过，但发现四种裸异常：5000位pyvenv version为`ValueError`、`python_major_minor=None`为`TypeError`、unhashable required path为`TypeError`、5000位RECORD size为`ValueError`。架构复核另发现错误`pyvenv.cfg.home`可被接受，且loader只清owned bindings而非transitive imports。

旧QA证据：

```text
/private/tmp/ai-auto-lrc-b3f-r1a-qa.EJcJzNki
qa-audit.json       53a8451759698f392a03daf6cf9973447b05833d13b378dc530eb18673ecde02
exception-probe     0b02bd8f077567c4899eac6c276682cbfa339909a74c695509eebb276005b8f7
```

该初版因此是 **P1 / non-accepting historical checkpoint**。后续GREEN不得删除、改写或掩盖这次QA否决。

### 33.3 补充RED/GREEN

补充证据根为`/private/tmp/ai-auto-lrc-b3f-r1a-supplement.gVRRFMqM`。新增四个节点：

```text
test_s18_b3f_r_derive_rejects_invalid_version_inputs_without_raw_errors
test_s18_b3f_r_derive_binds_home_and_current_uv_runtime
test_s18_b3f_r_record_rejects_invalid_inputs_and_freezes_uint63_size
test_s18_b3f_r_bound_module_loader_cleans_only_owned_bindings
```

补充正式RED为`3 failed / 1 passed`，失败只来自`len(None)`裸`TypeError`、home mismatch未拒绝和`set(required_paths)`裸`TypeError`。最小GREEN后四项全过，并冻结：

1. `python_major_minor`必须为exact two-element tuple；元素为非bool整数、范围`0..999`，major不得为0；
2. pyvenv version component在`int()`前做ASCII decimal、位数和`<=999`检查；
3. executable alias最多16跳，最终target为canonical single-link regular file；
4. `home`是canonical absolute、非symlink真实目录，且等于final target parent；
5. required paths先逐项验证字符串和canonical POSIX-relative语法，再集合去重；
6. RECORD size为ASCII decimal且`0 <= size <= 2**63 - 1`；
7. loader失败只清除owned names/parent attributes，不宣称transitive rollback。

最终实现结果：

```text
supplement final       4 passed
R1a exact7             7 passed
legacy selection       10 passed
policy-v3              1 expected failure only
py_compile/Ruff/diff   PASS
process gate           clear
```

最终文件哈希：

```text
scripts/security_pytest_bootstrap.py
320dd0434e7ca1a0f04c3f3229ac9d86f7a98b5183014f784cd42248322bf120

tests/contract/test_security_coverage_gate.py
f66a8a94ac71dc6809a226f77a0425dd7e35e259de4f91088c01d67c2d3e442c
```

实现证据：

```text
supplement-red.junit.xml          9c3ca6099bcceb0cfc6701c0c8e23fcc5cce46c5300f28bc0a7f08e0ff69dcb0
supplement-green-final.junit.xml  27395f6bea2aad61bc93402be9831c60249dbcda56123fe9598005cd7b92c7ac
r1a-exact7-green.junit.xml        98d53e68d504f7a0696a254cfd7b3b087779d9c5febf93fbc401b99dc4d247b1
supplement-summary.json           1ddc5c1e8b5b82e74f762f169a5288d8c6d6acb8e51fffa89fa5ef7d22bd9462
bundle-files.sha256               93f3c01708a3e65776400baf4e6f127ff1a22da7742af5f2a988948ec892e305
```

### 33.4 最终独立QA

独立QA根为`/private/tmp/ai-auto-lrc-b3f-r1a-supp-qa.58bkvehi`。绑定上述最终两文件哈希，结果为：

```text
supplement exact/formal    4 / 4 passed
R1a exact/formal           7 / 7 passed
legacy independent         9 passed
policy-v3                  1 expected failure: schema 2 != 3
py_compile/Ruff/diff       PASS
final process gate         clear
P0/P1                      0/0
```

实现角色legacy10与QA legacy9是不同显式node selection，不相加、不互相代签。QA敌意probe确认invalid tuple/list/None/bool/oversize version、5000位pyvenv version、relative/symlink/file/mismatched home、list/unhashable/non-string required paths、5000位RECORD size和`2**63`均只抛精确`BootstrapError`；`2**63-1`被接受。

当前真实`.venv/bin/python -I -S -B`证明alias最终指向`/Users/liu-haixiao/.pyenv/versions/3.11.4/bin/python3.11`，home为其parent，并派生当前`.venv/lib/python3.11/site-packages`；`site/sitecustomize/usercustomize`前后均未加载。这只是当前macOS host兼容oracle，不是Linux或双平台证明。

```text
qa-audit.json             d395ec2cf2e8fdf1573994032f1d627d8dc957192cade2bd65a0c90c7e2c7b2d
evidence-checksums.json   78e1369e859db538b8a2a8b6e743147be40901204199a3b4155ecd2daf6aa8b8
adversarial-probe.json    489ae1c777a2ed388d4cc350512a38b42bbd8e607a25663a4a40590d44bb12e1
bound-file-hashes.json    d02a50e7c04fdf9afea495ed409a2e4d97658edf1519511fc1f9035f7da5742b
final-process-gate.json   b8aef7e1e0dd4a033e7d82dbd7725180714697b7078b2b533a3dff79a023eaac
```

### 33.5 Loader failure进程模型

R1a的owned cleanup不是同进程rollback。R1b生产接入必须增加且同时通过：

```text
test_s18_b3f_r1b_loader_failure_path_is_statically_terminal
test_s18_b3f_r1b_loader_failure_exits_without_publish_or_pytest
```

合同要求loader在isolated bootstrap subprocess的生产路径只调用一次；任一validation/read/compile/exec失败必须直接退出2，之后禁止retry、继续import、`pytest.main`、identity构造或发布；retry只能创建全新subprocess。不得通过清理更多`sys.modules`名字声称恢复任意模块副作用。

### 33.6 R1b API与字段

R1b保留R1a三个seam签名，在其上增加：

```text
_capture_runtime_layout(executable, *, python_major_minor, base_prefix)
_capture_named_distribution(site_packages, *, canonical_name, required_paths)
_capture_lock_package(lock_path, *, canonical_name, required_dependencies)
_build_runtime_identity_v2(*, scope, runtime_layout, uv_identity,
                           uv_lock_sha256, distributions, plugins)
```

Runtime layout必须捕获unresolved executable、realpath、size/hash、venv root、base prefix、site-packages、home和pyvenv.cfg path/raw bytes/size/hash；并证明alias target、Python bytes与pyvenv before/after无漂移，`home.parent == base_prefix`。

每个named distribution必须来自site-packages唯一canonical direct-child dist-info；捕获Name、Version、dist-info、raw METADATA/RECORD bytes/size/hash、normalized rows和required entries raw bytes/size/hash。Whole-file digest只对raw bytes计算；opaque parent row永不join、resolve、stat或open；required entry捕获bytes必须直接驱动loader，禁止second live read。

Lock package必须按PEP 503 normalized name得到唯一exact package object，验证版本与required dependency edges，再对canonical exact object bytes计算digest。Builder必须无I/O、exact key set、拒绝未知/缺失字段，在最终JSON边界使用strict padded base64，并计算只排除run scope/timestamp的semantic runtime digest。

### 33.7 R1b exact 15合同与执行DAG

```text
1  test_s18_b3f_r1b_runtime_layout_binds_alias_target_pyvenv_and_base_prefix
2  test_s18_b3f_r1b_runtime_layout_rejects_alias_endpoint_swap
3  test_s18_b3f_r1b_runtime_layout_rejects_python_or_pyvenv_before_after_drift
4  test_s18_b3f_r1b_loader_failure_path_is_statically_terminal
5  test_s18_b3f_r1b_loader_failure_exits_without_publish_or_pytest
6  test_s18_b3f_r1b_distribution_resolution_requires_one_canonical_direct_child
7  test_s18_b3f_r1b_distribution_metadata_name_and_version_are_exact
8  test_s18_b3f_r1b_distribution_hashes_original_metadata_and_record_bytes
9  test_s18_b3f_r1b_distribution_never_resolves_or_opens_opaque_record_rows
10 test_s18_b3f_r1b_required_entry_drift_is_rejected_and_capture_bytes_drive_loader
11 test_s18_b3f_r1b_lock_package_resolution_is_pep503_unique
12 test_s18_b3f_r1b_lock_package_digest_binds_exact_canonical_object
13 test_s18_b3f_r1b_lock_package_requires_named_dependency_edges
14 test_s18_b3f_r1b_identity_v2_has_exact_shape_and_rejects_unknown_fields
15 test_s18_b3f_r1b_semantic_runtime_digest_excludes_only_run_scope
```

```text
R1b-0  exact15 contract RED
  -> R1b-1 runtime layout capture + TOCTOU rejection
  -> R1b-2 direct-child distributions + METADATA/RECORD/entries
  -> R1b-3 exact uv.lock package object + dependency edges
  -> R1b-4 pure identity-v2 builder + semantic digest
  -> R1b-5 loader fail-stop production-path contracts
  -> R1b-6 exact15 single-hash replay + R1a11 + expected policy RED + QA
  -> only then R2 atomic schema migration
```

R1b仍不得修改policy/verifier/runner对外schema、运行真实security runner或发布真实identity v2。完成判据为exact15在同一最终代码/测试哈希下全部GREEN，R1a原7加补充4回归通过，policy-v3仍只有预期RED，QA独立重算raw bytes/digests/field sets且无P0/P1。

### 33.8 上位状态与证据时效

本节不改变Spec Inventory 274项、B3e `7 implemented + 13 planned`、P1 `5 implemented + 2 planned / verification unverified / qualification unqualified`。R0与R1a均已改变contract test bytes，第31节B3f-L final67继续是历史checkpoint；B3f-R final schema后必须重新fresh replay B3f-L67和B3c/B3d/B3e core，禁止拼接旧证据。

当前唯一下一步为R1b exact15合同RED与identity producer foundation。R1b完成后才进入R2一次breaking migration：policy v3、identity v2 consumer、environment v5、command v4、run-manifest v5、Gate v5及verifier/artifact factories原子升级。S18、W1b-5b、Release继续 **No-go**；W1b-5c/5d/5e继续不执行。

## 34. v1.21 R1b 执行合同细化与计数勘误

> 版本：`S18-P1-PLAN-v1.21`；本节追加第33节的可执行接口细化。下面的设计裁决本身不表示实现或验证已完成，执行证据另行追加。

### 34.1 续接基线与覆盖计数

本轮启动时重新计算工作区，bootstrap 为 `320dd0434e7ca1a0f04c3f3229ac9d86f7a98b5183014f784cd42248322bf120`，旧 contract test 为 `f66a8a94ac71dc6809a226f77a0425dd7e35e259de4f91088c01d67c2d3e442c`，第33节完成时整份方案为 `5b14134df98e68b5ed092262d5b43cf521b8156cee791dfb5c14719da52267f2`。当前分支仍为 `improve-inference-reliability`，所有既存 dirty/untracked 文件保留。

明确勘误：第33.7节及 Teams 19 所写 `R1a11` 指两套 selection 共11次执行，不能解释为11个唯一用例。读取两份JUnit与当前函数定义后，实际为 `7 + 4 executions / 10 unique / 1 overlap`，重叠的是 `test_s18_b3f_r_bound_module_loader_cleans_only_owned_bindings`。后续回归使用10个唯一nodeid。实现角色legacy10较QA legacy9多 `test_s18_plugin_identity_record_field_is_only_the_plugin_record_entry_digest`，其余9个相同；两者不相加。

当前真实安装版本是coverage 7.16.0、pluggy 1.6.0、pytest 8.4.2、pytest-cov 6.3.0。旧fixture中的pytest 9.0.2是synthetic数据，不是本机安装事实。当前Python executable为33,815 bytes，uv.lock为201,107 bytes；这些是观测值，不是跨平台常量。

### 34.2 单次捕获与 loader 接口

保留 `_load_bound_runtime_modules(entries)` 的原 exact five-key descriptor 合同，新增唯一执行核心：

```python
_load_captured_runtime_modules(entries, captured_sources)
```

旧wrapper验证descriptors、每path stable-read一次，然后委托新核心。R1b直接传捕获的原始bytes tuple；新核心不做文件I/O，并对同一bytes对象完成size/hash/compile，把该次code object交给exec。禁止新增可选content字段、双descriptor schema、临时文件回写或monkeypatch reader来冒充捕获来源。

第33.6节 `_capture_named_distribution` 的返回值细化为三项：distribution evidence、ordered exact-five-key descriptors、同序的captured bytes tuple。此API在第33节尚未实现，本次细化不改变已实现的R1a API。Orchestrator按 `pluggy -> coverage -> pytest -> pytest_cov -> pytest_cov.plugin` 明确排序，不以dict迭代顺序隐式决定加载顺序。

### 34.3 真实 main 的 fail-stop 路径

增加 `_prepare_bound_runtime(executable, *, python_major_minor, base_prefix, lock_path)`，在真实 `main()` 的 `sys.flags.no_site` 分支调用一次。成功后沿用当前v1 document/guard/pytest路径；失败进入main error boundary并退出2。返回的legacy pytest-cov字段中 `record_sha256` 继续是plugin RECORD entry digest。

R1b期间保留当前非`-S`分支，使现有runner能够继续使用旧格式；R3统一切换runner时必须删除该分支并强制no-site。这个临时分支不能证明当前runner已经强制`-S`。

Fail-stop的静态用例必须检查真实main AST及orchestrator调用位置；动态用例必须在新的 `-I -S -B` subprocess中调用真实main，注入受控失败并断言调用一次、exit2、无traceback、无pytest执行、无identity final/temp及无继续执行。测试wrapper单独退出不能代签这个合同。真实venv还需一次orchestrator成功探针，证明当前四个distribution能够加载。

### 34.4 v2 builder 合同细化

拟议顶层字段为 `schema_version / provenance / scope / runtime / uv / uv_lock_sha256 / distributions / plugins / semantic_runtime_sha256`；`provenance` 唯一值是 `installed-record-consistent`。每层采用exact key set及严格类型检查，bool不能代替整数。

runtime在第33.6节layout字段之外，绑定implementation、version、cache_tag、system、machine、isolated、no_site、dont_write_bytecode；三个flag必须为true。uv绑定canonical path、version、SHA-256。每个distribution绑定原始METADATA/RECORD/required-entry bytes、hash/size和exact lock package object；每个lock capture增加 `lock_file_sha256`，必须与顶层whole-lock digest相等，拒绝来自不同lock观测的拼接。

Builder是无I/O纯函数，在最终JSON边界编码strict padded base64；必须独立重算raw bytes、normalized RECORD rows、exact package canonical bytes及其digest，并交叉检查name/version/required dependencies/plugin entry。未知或缺失nested字段、非法类型、重新绑定外层digest后的内部矛盾仍须拒绝。

Semantic digest排除自身和scope中的 `run_id / target / attempt / timestamp`，保留 `runner` 和全部runtime/distribution/lock/plugin语义。这延续第31.4节列出的四个排除字段，不排除整个scope。

### 34.5 必选 mutation 与阶段门

第33.7节15个稳定合同继续有效，R1b可在专门的contract测试文件实现，避免继续扩张旧文件。测试必须包含：同内容新inode的alias/target/config替换；METADATA/RECORD原始CRLF与parsed语义的区分；PEP503多候选；opaque row零路径访问；captured source与编译对象一致；任意lock package字段变化影响exact-object digest；nested shape、版本/RECORD/lock矛盾；真实main失败路径。

测试和源码改变后，旧R1a结果只能按旧hash引用。最终验收必须fresh运行R1b15、R1a10 unique、legacy10，并保留policy-v3唯一预期RED。R2 schema迁移、R3真实runner、R4最终schema replay和平台资格化仍各自需要执行与验证。

### 34.6 2026-09-07 本地续接 checkpoint：已实现，但 QA 不接受

本次按用户“将方案写到本地文件中，以免后续流失细节”的要求保存现场；只补文档，不继续修复代码。Teams 历史见 [Teams 20](./team-sessions/team-session-2026-09-07-20.md)。第34.1至34.5节的设计已形成实现与定向测试，但 **R1b 未验收：独立 QA 有两个未关闭 P1**。架构角色的有条件 Go 不覆盖 QA 的 non-accepting 结论。

本次重新计算并确认的冻结代码 SHA-256：

```text
scripts/security_pytest_bootstrap.py
b25f58ac5108ade6500d817c1d9448a3279e71f4ed8d028fdc8e291ddd3d1b91
tests/contract/test_security_runtime_identity_r1b.py
006a43c147f4305043104af43eedcf8866bacd00eb7fd89b6c3693858d5b13ef
tests/contract/test_security_coverage_gate.py
f66a8a94ac71dc6809a226f77a0425dd7e35e259de4f91088c01d67c2d3e442c
```

追加本 checkpoint 前，整份方案 SHA-256 为 `c8d6edd04739bfad2b63cd5d2e62bcd5e3ac210497df66d6b90e07ae663314fd`，此值仅绑定追加前文本，不是追加后的文件哈希。

| 验证集合 | 实现角色报告 | 独立 QA 报告 | 能证明的边界 |
| --- | --- | --- | --- |
| R1b exact15 | 15 passed | collect 15 / formal 15 passed | 冻结合同通过，不能覆盖下面的敌意反例 |
| R1a10 unique | 10 passed | collect 10 / formal 10 passed | 原 primitive 回归 |
| legacy10 | 10 passed | 10 passed | 显式选择集，不与 R1a 或其他集合盲目相加 |
| policy-v3 | 1 expected failure | 1 expected failure | 唯一原因为 schema 2 != 3，迁移仍待 R2 |
| 静态门 | py_compile / Ruff / diff-check PASS | QA 已完成独立探针 | 不能代签平台或发布资格 |

实现过程保留 initial RED 15 failed、first GREEN 14 passed / 1 failed、后续 refined/final GREEN；14/1 中失败来自测试把 runner 改成 Linux 却保留 Darwin runtime，产品正确拒绝，测试已改为先拒绝不一致平台，再比较一致平台变化。所有早期 Ruff 错误、retry、RED 和旧 GREEN 均保留，不覆盖失败历史。

### 34.7 R1b 两个阻塞 P1 与最小修复裁决

**P1-LOCK-ENDPOINT（待修复）**：`_capture_lock_package` 仅依赖 `_stable_read` 的 fd before/after，缺少整个 capture 操作外围的 pathname identity 闭合。QA 在 stable read 返回后，用相同 bytes/size/hash、不同 inode 的新文件 `os.replace` 当前 `uv.lock`，函数仍返回 identity；METADATA 同类替换已正确拒绝。

修复方案：在读取前记录 pathname 的 `_identity(lstat)`，stable read 后完成 parse、唯一 package 选择、依赖验证和 exact object canonicalization，在返回前再次检查 pathname identity；endpoint 不一致或检查失败统一抛 `BootstrapError`。不得通过再读文件内容覆盖第一次捕获，也不能只比较 digest。此方案保证 capture 窗口的 endpoint 闭合，不宣称返回后路径永不变化。

备选与取舍：仅比较 hash 能接受同内容换 inode，不能满足 endpoint 身份合同；全面改写通用 reader 会扩大 R1b 影响面。优先局部外层闭合，与 distribution 捕获策略保持一致。

**P1-FILE-LEAF（待修复）**：纯 `_build_runtime_identity_v2` 当前接受 `uv_identity.path="/"` 和 `plugins["scripts.pytest_security_events"]["file"]="/"`。这些字段描述 executable/plugin 文件，根目录不能作为文件 leaf。

修复方案：复用 canonical absolute path 校验，再对语义为文件的字段施加 lexical non-root-leaf 检查；保持 builder 无 I/O，不做 stat/open/resolve，不扩大为所有目录字段一律禁止 root。范围包括上述两个 QA 反例，并审查同类 executable/plugin 文件字段的一致性。若需要改变其他字段合同，应先记录额外裁决。

备选与取舍：builder 内 stat 可以检查真实文件但破坏纯函数和 captured evidence 边界；只依赖绝对路径语法无法拒绝根路径。因此使用词法检查，真实文件身份仍由 capture 层负责。

### 34.8 修复测试用例与 Teams 执行清单

下面是待执行用例，不是已 GREEN 的证据。优先扩充既有第12和第14个稳定合同；如新增 nodeid，必须同步 exact collection 清单并明确新计数，不能继续误称 exact15。

| 用例 | 前置 / 操作 | 精确期望 |
| --- | --- | --- |
| LOCK-01 正常捕获 | 读取有效、未变化 lock | 返回原始 whole-lock hash 与 exact package digest |
| LOCK-02 同内容换 inode | stable read 返回后以相同 bytes 的新 inode 原子替换 pathname | `BootstrapError`，禁止成功返回 identity；旧实现必须 RED |
| LOCK-03 检查窗口末端 | parse/canonicalization 期间触发 endpoint 替换 | 返回前拒绝，证明 after 检查覆盖整个 capture |
| FILE-01 uv 根路径 | 将合法 fixture 的 uv.path 单独改为 `/` | `BootstrapError`；旧实现必须 RED |
| FILE-02 plugin 根路径 | 将 local events 的 file 单独改为 `/` | `BootstrapError`；旧实现必须 RED |
| FILE-03 纯函数与正例 | 合法 canonical 文件路径，文件系统访问 seam 设为失败 | 成功构造，不访问文件系统；目录字段遵循原合同 |
| FAIL-STOP 回归 | 在真实 main 的 validation/read/compile/exec 各阶段注入错误 | exit 2，无 traceback、pytest、builder、writer、identity final/temp |

执行顺序与角色：

1. 主代理核对本节三个冻结哈希、Git dirty 状态及测试进程门；存在漂移先记录差异，不覆盖用户改动。
2. 唯一实现角色 `b3e_s_impl` 仅修改 bootstrap 和 R1b 专属测试；先证明 LOCK-02、FILE-01/02 在旧实现失败，再最小修复。旧 R1a/legacy 测试字节保持不变。
3. 创建新临时证据目录，保留旧目录；逐组运行 R1b 集合、R1a10 unique、legacy10、唯一 policy-v3 预期 RED，以及 py_compile/Ruff/diff-check；每次执行前确认无并发 pytest/security runner。
4. 冻结新源码/测试 hash，QA 在相同新 hash 上独立 collect/replay，并重做同内容 inode 替换、根路径、captured-loader、rebound-digest、真实 main 探针。后面三类因旧快照发现 P1 而未继续扩展，不能视为已经独立验证。
5. 架构审查确认捕获对象没有二次现场读取、builder 仍为纯函数；仅当独立 QA 无 P0/P1 且证据绑定同一新 hash，才记录 R1b closure。
6. 主代理追加新 checkpoint 和 Teams 结果，刷新四个上位指针，运行 docs/inventory 回归；之后才可开始 R2。

### 34.9 已冻结的补充接口细节与后续 DAG

v2 plugin 的 exact schema 为四字段 `{file, sha256, distribution, entry}`：pytest-cov 指向 `pytest-cov` / `pytest_cov/plugin.py`；local events 的 distribution/entry 均为 null。v1 五字段只留在 legacy adapter，不能混作 v2 schema。

`_prepare_bound_runtime` 要求参数 executable/base_prefix/Python version 与当前 sys 相符，并要求 `-I -S -B`；四个 lock capture 的 `lock_file_sha256` 一致。调用次数合同为 layout 1、distribution 4、lock 4、captured loader 1、legacy pytest-cov resolver 0。当前真实 main 仍输出 v1，v2 builder 不发布。

R2 必须把 preparation 返回值改为结构化 `PreparedBoundRuntime`，携带并复用本次 runtime/distribution/lock 捕获，不得为了构造 v2 再读现场路径。详细版本合同仍以第31至34节为准：

```text
R1b 两个 P1 RED -> GREEN -> 独立 QA / 架构验收
  -> R2 policy v3 / identity v2 consumer / environment v5 /
        command v4 / run-manifest v5 / Gate v5 原子迁移
  -> R3 single absolute uv prefix / no re-resolution / real dual lanes
  -> R4 bootstrap writer parity / final-schema replay
  -> fresh B3f-L67 + B3c/B3d/B3e core
  -> hostile matrix / B4 traceability / freeze ledger / 各平台 qualification
```

R3 必须删除非 `-S` legacy 分支并强制 no-site，统一绝对 uv 加 `run --offline --frozen --no-sync python -I -S -B`；当前实现不能代签此结果。旧 B3f-L final67 是历史 checkpoint，最终 schema 后必须重新运行，不能拼接旧证据。

当前 Spec Inventory 274 项、B3e `7 implemented + 13 planned`、P1 `5 implemented + 2 planned / verification unverified / qualification unqualified` 不晋级。S18、W1b-5b、Release 继续 **No-go**。不执行 W1b-5c/5d/5e，不运行真实 security runner/final67，不发布真实 identity v2，不改 runner/verifier/policy/events/manifest/pyproject/uv.lock 对外 schema；这些是当前 R1b 修复边界，并非后续阶段永久禁止修改的清单。

### 34.10 证据定位与续接保护

实现证据根：`/private/tmp/ai-auto-lrc-b3f-r1b.Tx8OCksH`。QA 证据根：`/private/tmp/ai-auto-lrc-b3f-r1b-qa.zKi8DW2Y`。本次读取 QA 的 `qa-summary.json` 和 `danger-probe.json` 确认两项 P1，未重新执行安全测试。

```text
实现 exact15-final-green.junit.xml
833d110cba6c94f79d83d11fa2a9f3d95a12e10d6749e38ab5707fd05f7152d1
实现 r1a10-final-green.junit.xml
673d205f6229d063b63796ac4ed96a51c0645964d414bebdb406224d8fcf35c5
实现 legacy10-final-green.junit.xml
c6583e7d6d991a6f5be20cffeb458941fb5a5d24ff2528267759390b4d0117c5
实现 policy-v3-final-expected-red.junit.xml
d83a11d2a599d09859cc30c60219e13c6d024777efbf272172a74838a8f0bc60
实现 summary.txt
7099815635a4c3af1fd2696ce4a0e8997246e2c6881996d3f1ea00371f77e8fa
实现 checksums.sha256
463751e59e33c466c609d131aeaeb1ae08c54a38fb258ab6229f071a23e9d8ef
```

以上实现证据 hash 来自实现角色已校验的冻结报告；续接时应重新核验索引。QA 另保留 `evidence-checksums.json`、`command-error.json`、`final-process-gate.json`；首次临时 probe 的 `ModuleNotFoundError: scripts` 是导入路径错误，不是产品测试失败，已保留原错误并只修复临时脚本后重跑。

临时证据目录可能被系统清理；本文和 Teams 记录持久保存结论、复现条件与校验定位，但不等于复制原始日志或完成证据归档。若目录丢失，必须 fresh 重跑，不能仅凭文档 hash 宣称验证有效。所有既有 modified/deleted/untracked 文件（包括根目录 `=`）继续保留；不执行 reset/checkout/clean、commit/push、CI、上传、同步、签名、发布或 archive/restore/destruction。

## 35. v1.22 R1b P1 修复与 R2 原子切换依赖勘误

> 版本：`S18-P1-PLAN-v1.22`；日期：2026-09-07。第34节和 [Teams 20](./team-sessions/team-session-2026-09-07-20.md) 保留旧快照与未验收结论。以下按执行顺序追加，最终验收状态以本节末尾的 QA checkpoint 为准。

### 35.1 修复范围与 RED

唯一实现角色只修改 `scripts/security_pytest_bootstrap.py` 和 `tests/contract/test_security_runtime_identity_r1b.py`。主代理开始时重算三份代码/测试 hash，与第34.6节一致；旧实现证据 `Tx8OCksH/checksums.sha256` 全部重新校验 OK。旧 coverage gate 测试、runner/verifier/events/policy/manifest/pyproject/uv.lock 均不修改。

新增反例扩充第12和第14个既有测试节点，仍为 exact15，未增加或隐藏 collection 节点：

- lock 两个替换时点分别执行并收集结果：stable-read 返回后、canonicalization 期间；每次都以相同 bytes、不同 inode 的文件 `os.replace`，两者在旧实现上均被错误接受。
- file leaf 四个反例分别执行并收集结果：uv.path 的 `/`、`//`，local events.file 的 `/`、`//`；四者在旧实现上均被错误接受。
- 先遍历收集所有错误接受，再统一断言，避免第一个失败遮蔽后续 mutation。RED 为两节点 `2 failed / 0 errors / 0 skipped`。

### 35.2 最小实现与声明边界

lock 的执行顺序现在为 pathname `_identity(lstat)` before → 一次 stable read → TOML parse/唯一 package/版本/依赖校验 → canonical bytes/package digest/whole-lock digest → pathname `_identity(lstat)` after → 返回第一次捕获的派生值。观测失败或 identity 不相等均抛 `BootstrapError`，没有 second content read。

文件检查新增纯词法 helper `_validated_file_leaf_text`，在 canonical absolute 校验之后要求 `Path(value).name` 非空，拒绝 `/` 和 `//`。精确应用集合是 runtime.executable、runtime.executable_realpath、runtime.pyvenv_cfg_path、uv.path、两个 plugins.*.file；不施加到 venv_root/base_prefix/site_packages/home 目录字段。测试保留根目录合法的内部 fixture 正例，不能把 synthetic fixture 当作本机布局事实。

before/after 只证明观测窗口内检测到的 endpoint 一致性，不排除同 inode swap-and-restore ABA，也不保证最后一次 pathname observation 之后永不改变。builder 继续无 I/O；文件实际存在和身份由 capture 层处理。

### 35.3 实现冻结与验证证据

```text
scripts/security_pytest_bootstrap.py
95a9be682e54a8e4b9f0a64d71435d5f938a20e549b755fe11c0f3c273be3782
tests/contract/test_security_runtime_identity_r1b.py
541f74b888587b1176201cba17f151db18211eabc0f842f7ec7dba548838eb30
tests/contract/test_security_coverage_gate.py（未改变）
f66a8a94ac71dc6809a226f77a0425dd7e35e259de4f91088c01d67c2d3e442c
```

证据根 `/private/tmp/ai-auto-lrc-b3f-r1b-fix.agHlxCej`：两节点 GREEN 2 passed；post-Ruff final exact15 15 passed、R1a10 unique 10 passed、legacy10 10 passed；policy-v3 仅 schema 2 != 3 的一个预期失败。首次 Ruff 报四个 B023 闭包绑定问题，显式绑定循环值后 Ruff PASS，并重新运行上述全部 final selection；py_compile/diff-check PASS。未把第一次 Ruff 失败或修复前 GREEN 覆盖。

```text
p1-red.junit.xml                         edfae2328d3b91d5b9ca50df06224f7847557c624a04916f8f320112a5e3a55a
p1-green.junit.xml                       3f8bc2033b41574e75242a82c43a80dcfd39d5d640970b5dbd9b4418a4ad0807
exact15-post-ruff-final-green.junit.xml   11f052e342f5dfef4753e016121d6df5771ba7fe451a58c30cb97c3a0b460b1a
r1a10-post-ruff-final-green.junit.xml     e502945f562aed1d818026b4014f71bcdbab0ab46fd188b2fc6dc588beb2529e
legacy10-post-ruff-final-green.junit.xml  cd89111f042bf817c2cf4c9ee6e6ae826df18819bd3505924b9442c2012a20dc
policy-v3-post-ruff-final-expected-red.junit.xml
19174d0a13f0dfcd1b90dd9e0f68bbfc5b19cf06fbae0c095848e08cca6697a7
checksums.sha256                         01b046740ab76350402603c7b2e8d5d6fd2d0a170b8b75d0f3454ae39c4421a0
execution-ledger.txt                     ba25c243e2ee2306abc2f372cfe23aff7a25fe7435f385a213451baeabf34717
```

主代理再次执行新索引校验，全 OK。`execution-ledger.txt` 是执行摘要；静态检查原始工具输出仍在执行轨迹中，不声称所有 raw stdout 已复制到临时目录。主代理一度误读不存在的 `execution-ledger.json`，随后按文件清单读取 `.txt`，未影响 checksum 校验或产品测试结果。实现角色已停写/停测，独立 QA 接手；此处的实现 GREEN 尚不能代签 QA。

### 35.4 冻结静态架构审查

架构角色独立重算第35.3节三个 hash，确认 lock final observation 位于 canonicalization 和两个 digest 之后、返回值不二读；六个文件字段与四个目录字段区分正确；builder 验证链无新增现场 I/O。静态范围内 P0 0 / P1 0。其结论仅允许进入同 hash 独立 QA，不替代动态验收。

### 35.5 R2 与 R3 切界勘误（已接受，未实施）

第31.4节和第34.9节原 DAG 将启动前缀切换及 legacy 分支删除放在 R3，但源码核查发现 R2 的实际生产依赖：当前 runner 非 `-S` 命令只会走 v1 main；environment、command、run-manifest writers 也内嵌于 runner。只更新 verifier/factory 会使真实 producer/writer 继续输出旧格式。因此以下内容必须前移并纳入 **R2 同一次原子 cutover**：

1. 单次解析 canonical absolute uv；所有 Python helper、bootstrap、writer、verifier 共用 `<ABS_UV> run --offline --frozen --no-sync python -I -S -B`，不得后续重新解析。
2. 删除 main 非 `-S` legacy 分支，真实 producer 发布 identity v2。
3. policy v3、environment v5、command v4、run-manifest v5、Gate v5 的 producer/writer/consumer/fixture 同步切换，新 verifier 只接受新版本，不 dual-read。
4. environment writer 删除额外启动 uv/import coverage/pytest 获取版本的逻辑，版本来自同次 prepared runtime evidence。

R3 保留真实 capture/retention 双 lane、同 host semantic digest 相等、PATH fake/no-re-resolution、uv version/endpoint drift、lock drift、flag 删除/重复/改序、`.pth/sitecustomize` sentinel 等 integration 验证。macOS/Linux 仍需分别取证，R2 不代表真实双平台通过。R4 writer parity、final-schema B3f-L67/B3c/B3d/B3e replay、B4/freeze ledger/平台资格化仍不可省略。

### 35.6 R2 内部数据边界与待冻结合同

`PreparedBoundRuntime` 最小内部字段建议：runtime_layout、uv_identity、uv_lock_sha256、distributions、loaded_modules、pytest_cov_plugin_identity。前四项保留同次捕获的 layout、runner uv observation、唯一 whole-lock hash、四个 installed/lock 对象；loaded_modules 是五个 captured-byte 模块对象；pytest-cov 四字段 identity 从这次 descriptors/evidence 派生。不重复保存可漂移的来源，也不在主路径保留 v1 adapter。

local events 的唯一 stable-read/load 应同时返回 module 与 v2 四字段 identity；main 组合 plugins 后调用 builder，不能再次读文件。必须新增合同：preparation 完成后将 runtime/distribution/lock/live-plugin reader 全设 tripwire，仍能完成 v2 build、guard 配置与发布。

R2 原子修改集合：bootstrap、policy、runner、verifier、coverage gate factory/tests、R1b main-success 的 v1 历史断言及必要的新 R2 tests。审计 `tests/fixtures/security_coverage_scenarios.json` 与 B3f-L runner/factory 的受影响断言；events v3、security manifest v1、runner-error v2、pyproject、uv.lock 保持原合同。

R2 开始编码前由实现/架构/QA 冻结以下精确合同；这些是下一阶段设计工作，不是当前 P1 修复的阻塞，也不能跳过而自由实现：

- runner → bootstrap uv observation 的 exact argv/数据格式；timestamp 的唯一来源与格式。
- environment v5 / command v4 / manifest v5 / Gate v5 exact key sets，artifact SHA 与 semantic digest 的交叉绑定位置。
- Gate bounded summary 不复制 raw bytes 或未经约束路径；identity 4 MiB 与各 runtime byte cap 的 representative artifact 验证。
- 精确 failure 分类：runtime envelope/schema/scope/provenance/uv 内部语义、distribution/RECORD/lock/semantic digest → `RUNTIME_IDENTITY_INVALID`；plugin mapping/local binding/registration → `PLUGIN_IDENTITY_INVALID`；uv/lock/tool/artifact 外部 hash 或 before/after 不一致 → `EVIDENCE_TOOLCHAIN_BINDING_INVALID`；exact argv/env/flags 配置不一致 → `RUNNER_CONFIGURATION_INVALID`。 malformed v2 sidecar 的 read/mode/envelope 归类还需通过测试冻结，不沿用全归 PLUGIN 的旧行为。

本轮未执行 R2。Spec Inventory 274、B3e 7 implemented + 13 planned、P1 5 implemented + 2 planned / verification unverified / qualification unqualified 均不晋级；S18、W1b-5b、Release 继续 No-go，W1b-5c/5d/5e 不执行。

### 35.7 R2 existing-root guard 事实勘误

主代理进一步核对 runner 与 `_b3f_existing_attempt_runner_source_order`，当前 input guard 实际是 Bash 调用 `python3 -I -B` 的嵌入式 Python，不是纯 Bash guard。第31.4节的“Batch H existing-root Bash guard”表述不能解释为当前已实现纯 shell 拒绝或当前完全不启动 Python。Batch H 已有证据仅按其实际 source-order/uv tripwire/不覆盖 existing attempt 合同解释。

R2 全部 Python 改用 ABS_UV 后，必须先用最早的 shell existing-root 检查（含 `-e` 与 `-L`，覆盖 dangling symlink）拒绝已存在目标，再解析/启动 uv，避免为了检查既有 attempt 而新启动 uv。完整 run_id/attempt/parent/no-follow 校验仍由统一前缀下的 helper 执行。更新相应 source-order 合同与反例，不能仅改测试字符串以通过。当前 runner 未为此改动，需在 R2 test-first 实施。

### 35.8 R1b 最终独立 QA 与验收 checkpoint

独立 QA 根 `/private/tmp/ai-auto-lrc-b3f-r1b-fix-qa.5CfHZ4bL` 绑定第35.3节最终三个 hash，结论 **PASS / P0 0 / P1 0**。fresh collect 精确15、formal 15 passed，R1a10 unique 10 passed，legacy10 10 passed；policy-v3 仍仅 schema 2 != 3 的预期失败。py_compile/Ruff/diff-check PASS，最终进程门 clear。主代理读取 QA summary/extended probe 并重新校验证据索引。

两个旧 P1 独立复测均关闭：lock 两时点同内容换 inode 都抛精确 `BootstrapError`，uv/events 的 `/` 与 `//` 全拒绝，关系一致的合法 root 目录 fixture 接受。补完的 probes 证明：

- captured loader 在 live 文件被改成失败源码后仍执行原 captured bytes；stable-read tripwire 未触发，hash/compile 使用相同 bytes 对象，module/sys.modules/父子绑定一致。
- pyvenv、METADATA、exact lock object、local plugin、uv 的合法内部 size/hash/canonical rebound 均改变 semantic digest；不能通过只检查旧外层 digest 遮蔽内部语义。
- builder 在 builtins.open、os.open/stat/lstat/readlink、Path.open/read_bytes/read_text/resolve/stat/lstat/exists/is_file/is_dir/iterdir 全部 tripwire 下仍成功。
- 独立 main 失败 probe 调用真实 main 得到返回2、prepare恰好一次、events/write为0、pytest未加载。probe 自身成功退出0表示断言成立，不混称为 main subprocess exit2；exact15 的生产失败路径合同另行通过。
- 当前 host 的 `.venv/bin/python -I -S -B` 真实 preparation 成功，派生 site-packages 正确，site/sitecustomize/usercustomize 未加载；仍不是 Linux、双平台或 release qualification。

```text
qa-summary.json          76e2d2946c3b320b16c08415f83a743225abe56bbf83477ca371bc8d13a6518c
extended-probe.json      0d904a1f234accbc77d318ab8cfd3a5f69ff35e2dfe9e4943656b06acb77a27c
evidence-checksums.json  36f3ddd3fa7002cf2d70a8ed9b2f493f2b657d8246a1ff170bceda54e1fc360f
```

QA 有一次工具编排 JavaScript 语法错误，发生在 shell 启动前，未执行测试或仓库操作，已保存在 summary。旧 QA P1、旧 GREEN、修复 RED、Ruff retry 和新 QA 记录全部保留。

**R1b producer foundation 在本冻结 hash 下完成验收；整体目标仍未完成。** 当前下一步是第35.5至35.7节 R2 exact 合同冻结与原子 cutover，不重复 R1b，也不直接进入真实双 lane、final67 或平台资格化。Teams 汇总见 [Teams 21](./team-sessions/team-session-2026-09-07-21.md)。S18、W1b-5b、Release 与产品/P1 inventory 状态保持第35.6节 No-go，不因局部验收晋级。

### 35.9 R2 exact 契约草案（proposed，非编码授权门）

以下保留架构角色的具体提案，避免下一轮丢失。R2/R3 前移依赖已在第35.5节接受，但本节字段设计尚需实现/QA 联合审查，第35.11节冲突未解决前不能把草案当作已冻结实现合同。

**启动与 uv observation**：最早纯 shell absolute/existing/dangling-link root 拒绝后，builtin `command -v uv` 一次解析 absolute candidate，校验 canonical parent、regular executable 非 symlink leaf。第一个 uv-prefix helper 完整验证 root/run_id/attempt 并 stable-hash uv，之后精确一次 `ABS_UV --version`，只接受单行 `uv <VERSION>`。后续 Python 均用第35.5节 final prefix。bootstrap path 后的 exact 参数提案为：

```text
--plugin-identity=<ABSOLUTE_OUTPUT>
--runtime-uv-path=<ABS_UV>
--runtime-uv-version=<VERSION>
--runtime-uv-sha256=<64-lowercase-hex>
--runtime-timestamp=<UTC_TIMESTAMP>
--
<pytest argv>
```

五个 options 各一次、固定顺序、非空；bootstrap 只验证并消费 observation，不重新解析/执行/stat/read uv，不创建 uv-observation sidecar。identity 的 uv path 与 command 第一个 token 一致；SHA 与 runner before/after observation 一致。

**时间权威**：每 lane 一次生成 `command.started_at`，格式拟为 `YYYY-MM-DDTHH:MM:SS.ffffffZ`，通过 runtime-timestamp 原样传入 identity.scope.timestamp；bootstrap 不独立取时间。finished_at 在返回后另取。semantic digest 仍排除该 scope timestamp，不排除 runner。

**schema delta**（旧 exact keys 未列出的保持，非任意扩展）：

| artifact | proposed delta | 数据来源 |
| --- | --- | --- |
| environment v5 | 新增 `runtime_identity:{artifact_sha256,semantic_runtime_sha256}`；tools 加 uv，coverage/pytest/uv 可为 version 或 null；repository 加 uv_executable_sha256_before/after | 版本来自 identity evidence，不再起 import 子进程；uv before/after 来自 runner observation |
| command v4 | 顶层键不增加；argv 改 absolute final prefix 与五个 options，started_at 成为 identity timestamp 权威 | runner 的同一字符串与同一 argv |
| run-manifest v5 | 保留 artifact_hashes，包括 plugin_identity_sha256；顶层增加 semantic_runtime_sha256 | raw artifact hash 与 identity semantic 分开绑定，不新增同义 runtime_identity_sha256 |
| Gate v5 | 移除旧 plugin_identity summary，增加 bounded runtime_identity summary | verifier 独立验证后派生；不回写任何 input artifact |

environment writer 为 tolerant extractor：identity absent/unreadable 时两个 identity引用及三个 tools 全 null；可读但不可提取时只保留实际 raw artifact hash，其余 null；可提取时提供完整候选值。writer 提取不是 verifier 验收。不要让缺失/损坏 identity 迫使 environment 写入失败，从而悄悄改变原 raw-completeness 分类。

**Gate summary proposed exact shape**：

```text
status: valid|invalid
artifact_sha256: sha256|null
schema_version: 2|null
provenance: installed-record-consistent|null
semantic_runtime_sha256: sha256|null
runtime: null|{implementation,version,system,machine,executable_sha256,
              pyvenv_cfg_sha256,isolated,no_site,dont_write_bytecode}
uv: null|{version,sha256}
uv_lock_sha256: sha256|null
distributions: fixed-four-name map of {
  version,metadata_sha256,record_sha256,lock_package_sha256,
  required_entries: policy-fixed map of {sha256,size}
}
plugins: fixed-two-name map of {sha256,distribution,entry}
```

仅完整 identity 验证成功后输出完整 summary。invalid 时保留 exact top keys，runtime/uv/uv_lock/provenance/semantic 为 null，distributions/plugins 为空；schema_version 的 invalid 分支值需按第35.11节统一。summary 不含 executable/uv/site-packages/dist-info/plugin file 路径，不复制 raw bytes、exact lock object 或 canonical lock bytes；名称/entry来自固定 policy 集，machine 来自 runner enum，version 需固定长度/regex 上限。

依赖方向为 identity → environment；identity + command + environment + raw artifacts → manifest；manifest → verifier → Gate。identity/environment/command 不引用 manifest 或 Gate，避免循环 hash。

**failure 与原 artifact profile 草案**：sidecar read/mode/envelope、v1 输入、runtime/distribution/lock/semantic 无效归 RUNTIME；合法 envelope 的 plugin mapping/binding 无效归 PLUGIN；artifact/environment/manifest/uv外部观察矛盾归 TOOLCHAIN；exact argv/env/flags归 CONFIG。envelope 不可解析时不猜测插件错误。identity根本缺失的 runner生产路径仍生成 runner-error v2，不强迫 Gate；events缺失但 required raw 齐全时仍 NO_EVENTS并生成 manifest/Gate；identity存在但损坏应由 Gate裁决；writer自身失败保留原 reason，不新增必需 sidecar。

### 35.10 R2 待评审的十二个测试节点

下列节点均 **planned，未添加或执行**，不能计入 current inventory 或通过率。命名可在 joint review 后冻结，预期精确失败集合仍受第35.11节约束。

| proposed node | 输入与 oracle |
| --- | --- |
| `test_s18_b3f_r2_existing_root_rejects_before_uv_resolution` | existing directory/file/dangling link；uv tripwire零调用、input-invalid、root不变 |
| `test_s18_b3f_r2_runner_resolves_one_absolute_uv_and_reuses_final_prefix` | fake uv记录所有调用；一次解析、同ABS_UV/final flags、裸uv/python3零调用 |
| `test_s18_b3f_r2_bootstrap_accepts_only_exact_uv_observation_argv` | options缺失/重复/改序及bad path/version/hash/time；exit2，无pytest/identity |
| `test_s18_b3f_r2_prepared_runtime_publishes_v2_without_live_reread` | preparation后关闭runtime/distribution/lock/plugin readers；v2 build/guard publication仍成功 |
| `test_s18_b3f_r2_timestamp_has_one_authority_and_cross_binding` | baseline与timestamp/started_at矛盾；raw hash重绑不能绕过scope验证 |
| `test_s18_b3f_r2_artifact_versions_are_exact_and_old_versions_fail_closed` | identity1/environ4/command3/manifest4逐项输入；按结构边界分别得到runtime-invalid Gate或input-invalid/no-Gate |
| `test_s18_b3f_r2_identity_read_mode_and_envelope_failures_are_runtime_invalid` | oversize/0644/invalid UTF8/duplicate key/unknown或missing top key；runtime-invalid，不猜测PLUGIN |
| `test_s18_b3f_r2_failure_classes_are_not_collapsed` | RECORD/plugin-entry/uv-after/command-flag独立mutation；精确分层failure集合 |
| `test_s18_b3f_r2_environment_uses_nullable_identity_observation_without_version_subprocess` | absent/corrupt/valid identity，版本subprocess tripwire；writer连续性与null/partial/full正确 |
| `test_s18_b3f_r2_manifest_cross_binds_identity_without_hash_cycle` | raw/semantic/environment引用漂移并重绑其他hash；TOOLCHAIN，输入无反向hash |
| `test_s18_b3f_r2_gate_runtime_summary_is_exact_bounded_and_path_free` | 固定集合最大合法输入；exact summary、无raw/path、固定大小上界 |
| `test_s18_b3f_r2_identity_limit_accepts_representative_and_rejects_plus_one` | representative v2、4MiB边界/plus-one和nested caps；边界可进入语义验证，超限bounded拒绝 |

### 35.11 主代理对草案的待解冲突（下轮先处理）

1. **损坏 identity 的 manifest continuity**：草案要求现存损坏 identity 仍生成 manifest/Gate，但 manifest新增 semantic字段若强制合法 SHA 就无法生成。需在 exact schema 中定义 null/invalid observation及其失败分类，禁止捏造 digest，也不能为此改变 EARLY/NO_EVENTS/FULL profiles。
2. **timestamp/argv 多重绑定**：单改 command.started_at 而不改 argv runtime-timestamp 时，既违反 identity scope 又违反 argv内部一致性，不能一律断言“仅 RUNTIME”。测试应分别构造单层一致/跨层矛盾输入，并锁定可重现的精确集合，不抑制真实独立失败。
3. **首次 uv observation 失败清理与错误边界**：root创建、uv hash与version查询的顺序，helper输出校验和失败时保留的文件/日志须明确；单次路径解析不等于供应链可信，不能声称 uv自测建立信任根。
4. **invalid summary**：schema_version在 malformed/v1/valid-v2-but-plugin-invalid 情况取2还是null、tools null与已知runtime坏值如何分类，须统一 writer/parser/Gate oracle。
5. **代表性容量**：4MiB是已有R0政策合同预期，但“恰好4MiB”不代表 arbitrary padding JSON合法。需独立区分bounded-read门与语义门，真实representative只作为当前host容量观察。

这些是架构草案复审任务，不是新的外部权限阻塞；仍在原重构目标范围内。不得只为让十二个草案节点通过而缩减第18.6、31至35节的整体合同或省略后续真实验证。

## 36. v1.23 R2 原子迁移执行合同

> 日期：2026-09-07；版本 `S18-P1-PLAN-v1.23`。第35.8节 R1b 完成仍有效；第35.9至35.11节草案由本节裁决补足。此为实施合同，不表示 R2 已实现或通过。主代理重新核对 R1b 三份冻结 hash 无漂移，当前无并发测试。

### 36.1 Joint review 收口与范围

架构与 QA 分别只读审核草案。QA 的四项编码前缺口为 manifest continuity、verifier independence、artifact profiles、policy/Gate exact schema；本节用 nullable合同、独立重算 oracle、三类profile和新增三个测试节点关闭设计缺口，实际实现仍必须证明。R2 为15个稳定节点，不再称12个；不以少数新测试替代所有受影响旧合同。

唯一实现角色修改 bootstrap、runner、verifier、policy 与对应 fixtures/tests；主代理维护docs，架构/QA只读。events保持v3、security manifest保持v1、runner-error保持v2，pyproject/uv.lock不修改。不得新增dual-read/v1主路径、通过重装工具规避本机事实或省略真实生产writer迁移。

### 36.2 uv 一次解析与 preflight

当前实际 `command -v uv` 为 `/opt/homebrew/bin/uv`，是指向 `../Cellar/uv/0.12.9/bin/uv` 的符号链接；final binary为42,042,496 bytes。其version stdout为 `uv 0.12.9 (Homebrew 2026-09-01 aarch64-apple-darwin)`。以上是本机观测，不是硬编码跨平台路径/版本。第35.9节“拒绝PATH alias、仅接受无suffix version”草案据此勘误。

生产顺序：

1. 最早纯 shell 检查 absolute artifact root 和 `-e || -L`，existing/dangling-link立即固定input-invalid退出2。必须在repository dirname/cd、command-v、uv/Python等子进程之前拒绝，不改变原root。
2. 在任何uv执行前unset已有Python/pytest/uv redirect环境。builtin `command -v uv` 精确一次，必须得到absolute path；最多16个leaf symlink hop，每跳canonicalize parent、相对target按link parent解释，拒绝cycle、空leaf、控制字符、超限。通过绝对 `/usr/bin/readlink` 读取link，不调用PATH中的readlink/realpath/dirname/basename；最终为canonical absolute regular executable非symlink leaf。
3. `/usr/bin/readlink` 与shell/OS的这段引导属于明确的 **OS bootstrap trust**，不是named Python runtime闭包或供应链认证。macOS/Linux各自资格化须验证工具存在/兼容；缺失即固定CONFIG失败，不隐式换工具。
4. resolved uv启动统一prefix helper读取uv hash A；final uv精确一次执行 `--version`；同prefix helper再读取hash B；A==B后用B作为before值。失败固定 `SECURITY_COVERAGE_RUNNER_CONFIGURATION_INVALID`、exit2、artifact root仍不存在；不泄露原工具错误或任意输出。
5. version必须单行、无控制/NUL、bounded，接受 `uv <VERSION>` 及一个可选受限ASCII括号build suffix；VERSION最多128字符、banner最多512 bytes，采用锚定grammar，拒绝额外行或尾部垃圾。只将VERSION存入identity，具体build由binary SHA绑定。不得截断未知banner后继续。
6. 完整input helper验证run_id/attempt、absolute canonical no-follow parent链、platform后唯一mkdir。后续所有Python helper/bootstrap/writer/verifier只用同一 `<ABS_UV> run --offline --frozen --no-sync python -I -S -B`；每lane结束观察uv after与before/identity交叉比较，不重新解析PATH alias。

“冻结endpoint”仅指固定canonical pathname及bytes observation，非持续inode监控，不排除ABA，也不把uv自测升级为供应链信任根。preflight root创建前失败不生成lane artifacts；创建后失败按已有runner错误生命周期保留证据，不自动删除。

### 36.3 Prepared runtime、argv 与时间

冻结内部 `PreparedBoundRuntime(runtime_layout, uv_identity, uv_lock_sha256, distributions, loaded_modules, pytest_cov_plugin_identity)`；`_prepare_bound_runtime(..., uv_identity=...)`返回它，不再丢失capture数据或返回v1 adapter。保留同次raw bytes、四个installed/lock对象、五个loaded module；uv observation来自runner输入，不在bootstrap重新stat/read/execute uv。

`_arguments` 返回 output、exact uv identity、timestamp、pytest argv。bootstrap path后严格接受第35.9节五个固定顺序options及`--`，各一次；uv.path与command首token一致。main强制`-I -S -B`，删除非no-site legacy分支。local events单次读取/加载返回module和v2四字段identity；builder/guard使用这些对象，禁止二读。私有历史辅助函数如仍用于primitive回归不得进入生产v1 fallback。

每lane started_at唯一生成，严格可解析UTC microsecond `YYYY-MM-DDTHH:MM:SS.ffffffZ`，原样传argv及identity.scope.timestamp；finished_at独立生成同格式。三者分别格式校验：command argv timestamp!=started_at → CONFIG；identity timestamp!=started_at → RUNTIME；可同时出现，不先遇CONFIG就跳过RUNTIME。command整体schema/时间类型非法仍input-invalid/exit2/no Gate，不猜测下游语义。

### 36.4 精确 schema、null 与连续性

采纳第35.9节schema delta和Gate summary字段集合，补充以下权威规则：

- policy顶层 exact keys为 schema_version/thresholds/limits/scripts/runners/runtime；schema3。runtime exact内容与R0 named-runtime authority一致；新增四个runtime byte limits，identity上限4MiB；nested exact key/type/duplicate拒绝，旧schema不dual-read。
- environment5的tools为exact coverage/pytest/uv，各VERSION|null；runtime_identity exact artifact_sha256/semantic_runtime_sha256，各SHA|null；repository新增uv_executable_sha256_before/after。writer从bounded identity提取候选值，不启动版本import子进程，不重读runtime现场。
- 最小提取定义为strict JSON object、schema_version精确整数2、字段类型正确；semantic仅64位小写hex才可提取。writer不负责验证runtime正确性，也不调用producer validator。absent/unreadable/oversize时raw/semantic/tools全null；可读但不可提取保留实际raw SHA，其余null；可提取的错误semantic可原样进入manifest，最终由verifier重算拒绝。
- manifest5保留原artifact_hashes exact keys，新增 `semantic_runtime_sha256: SHA|null`。null是未知，不是伪造成功摘要。identity完整runtime验证有效而manifest为null/不同 → TOOLCHAIN；identity semantic内在错误且manifest忠实复制 → RUNTIME，不虚构额外TOOLCHAIN。无权威semantic时不比较猜测值；raw可读且外部hash确实不等仍独立报TOOLCHAIN。
- Gate5完整top keys为 schema_version/gate/target/run_id/runner/attempt/coverage/junit/pytest_events/runtime_identity/capabilities/artifact_hashes/passed/failures；移除旧plugin_identity summary。
- Gate runtime_identity invalid时，无论envelope是否v2，schema_version/provenance/semantic/runtime/uv/uv_lock全部null，distributions/plugins空，status=invalid；只保留有完整bounded raw时的artifact SHA。valid时为第35.9节固定完整summary，schema2。此为主代理选择的统一fail-closed语义，不采用QA提出的invalid-envelope分级schema回显。
- Gate顶层artifact_hashes.plugin_identity_sha256在missing/unreadable/oversize时也为null，与nested raw hash一致；不能用sha256(empty)冒充没有读到的文件。真正可读空文件才有empty SHA；mode错误但完整raw可读仍保留实际SHA，语义summary无效。其他既有artifact hash规则不任意扩展。
- 保持 EARLY：缺identity/required raw → runner-error v2、无manifest/Gate；NO_EVENTS：events缺失但required raw齐全 → manifest/Gate；FULL或相应NO_EVENTS中identity存在但损坏 → environment/command/nullable manifest继续生成，Gate判RUNTIME。不可因候选semantic缺失提前改变profile。

### 36.5 Verifier 独立性与失败分类

verifier不import/reuse bootstrap或producer验证器。必须独立strict JSON/base64 decode，重算raw bytes/size/hash、RECORD normalized rows与required entry、METADATA name/version、exact lock canonical object/dependency、semantic digest，再与live endpoints和已读uv.lock/toolchain交叉。opaque parent RECORD rows只解析为证据，绝不resolve/stat/open。测试中producer validator设为bomb/accept-all不改变verifier拒绝结论。

failure采用可证实的 sorted unique union，不以早发现一个错误掩盖另一个：runtime envelope/内部语义/semantic/sidecar read/mode → RUNTIME；合法envelope内plugin mapping/registration → PLUGIN；外部raw/semantic/tool/uv before-after矛盾 → TOOLCHAIN；exact argv/env/flags → CONFIG。插件字段改动如同时导致semantic未重绑，应同时记录真实runtime错误；单类测试必须同步重绑无关字段以隔离oracle。对未知、无法读取的raw不要制造hash不等。

Gate bounded summary仅由完整验证成功值派生，不回显path/raw bytes/exact lock object；version有128长度/regex上限，names/entries/machine使用policy限定集合，四dist/五entry/两plugin固定上界。4MiB边界测试分开证明bounded-read门与语义门，任意padding不是合法JSON证明。当前host representative仅证明当前容量，不代签跨平台。

### 36.6 十五节点与执行顺序

第35.10节十二个稳定节点全部保留，另新增：

```text
test_s18_b3f_r2_verifier_recomputes_identity_without_producer_validator
test_s18_b3f_r2_artifact_profiles_preserve_early_no_events_and_malformed_identity
test_s18_b3f_r2_policy_and_gate_have_exact_current_schema
```

分别覆盖独立validator、EARLY/NO_EVENTS/FULL三类真实writer连续性、policy嵌套exact key/duplicate及Gate完整schema。基础failure四类各独立mutation，再增加二层union；不通过只断言字符串包含代替精确集合。

执行：独立R2测试文件15节点RED → producer/Prepared → policy+独立consumer → runner所有writer/prefix → factories与受影响旧断言原子迁移 → 同hash精确GREEN/静态门/独立QA。过程中允许暂时RED，但不得称部分schema为R2完成。主代理记录接口变动，保持旧证据历史化。

R2允许tmp副本runner+受控fake uv真实shell路径合同，可走到模拟writer/verifier与raw profiles；fake uv不得调用真实security测试，测试要区分stub回执和真实产物，不能以仅在run_one前退出代签所有writer调用。仅运行显式低成本node集合及collect/static，不运行整个coverage_gate文件、真实security双lane、final67或平台matrix。完成后R3再执行真实双lane和敌意integration；R4/final-schema replay/平台资格化仍未完成。S18、W1b-5b、Release仍No-go；5c/5d/5e不执行。

### 36.7 架构最终补充：uv bounded preflight

第36.2节version grammar冻结为完整匹配：`uv <VERSION>`，可选一个空格加一个非嵌套、非空、printable-ASCII的括号suffix；suffix内不允许括号，拒绝CR/LF/NUL/control及末尾垃圾。进程输出允许通常的一个终止LF，在校验前仅去掉该终止LF，不接受多行或多个尾随LF；VERSION采用版本regex且不超过128字符，整份stdout含终止LF不超过512 bytes。实际Homebrew banner是正例，嵌套括号/额外行/control/尾随垃圾进入既有uv节点反例，不新增节点计数。

uv binary hash采用bounded streaming，64MiB上限（高于当前42,042,496 bytes），单次读取最多剩余额度加1用于拒绝plus-one；regular executable/no-follow endpoint验证，读取前后身份检查。不得 `read_bytes()` 后才截断来声称bounded；哈希始终基于同一次读取。增加合法上限与上限+1的独立helper反例，不能执行伪造的大二进制来测试大小门。第36.4节 prose 的 uv_lock 始终指精确字段 `uv_lock_sha256`，不是新增别名。

### 36.8 首轮 RED scaffold 审查（非动态验收证据）

实现角色新增 `tests/contract/test_security_runtime_identity_r2.py`，初始collect精确15，初始JUnit为15 failed/0 error/0 skipped，证据根 `/private/tmp/ai-auto-lrc-b3f-r2.kekIET9M`，`exact15-red.junit.xml` SHA-256 `5e1135513cada6c23ad7d04bb708d4e5135387ce877a84d83230e413c6581113`。初始测试文件hash `0b3c4d2dc767e6db80ad87870d69d6cef6c29099c8323ca44f39e872f3e2b02e` 只绑定首轮scaffold，后续改动使其历史化。

主代理审查发现：多项仍为源码substring检查，不能证明运行行为；identity fixture使用非TOML lock文本且synthetic paths无live文件，不能作为独立consumer的合法输入；summary禁止子串executable误伤executable_sha256；禁止verifier包含bootstrap文件名字串误伤合法toolchain常量；existing-root测试尚未使用临时runner副本。这些是测试缺口，不是允许削弱consumer的理由。

已要求实现角色保留初始RED，修正为合法独立fixture与动态mutation后重新取得RED/GREEN。AST/源码检查仅补充依赖方向，不代签Prepared无二读、prefix全链、failure集合、schema拒绝或artifact profiles。只因初始15节点变绿不能称R2完成。

### 36.9 本地持久化与续接快照（未封板）

用户要求将方案写入本地以免流失细节。本次在既有 v1.23 下追加续接信息，不另建平行方案，不覆盖历史 RED、修复、retry 或验收结论。工作分支为 `improve-inference-reliability`；续接时须重新检查实际分支、worktree 和 Teams 状态。本节不是 R2 完成声明，也不是可复用的最终源码 hash。

| 对象 | 本次记录的状态 | 续接规则 |
| --- | --- | --- |
| R1b foundation | 第35.8节记录同 hash 独立验收通过 | 仅作历史基线；不得用旧 GREEN 代签当前改动 |
| R2 exact 合同 | 第36.1至36.7节已冻结，15节点见第35.10和36.6节 | producer、writer、consumer、fixture 必须原子闭合 |
| bootstrap / policy | Prepared/main-v2 与 policy3 迁移已开始 | 仍需动态测试；不能以类型定义或 schema 数字变化当验收 |
| 独立 verifier | runtime consumer 已落盘，实现角色报告语法检查通过；顶层集成继续中 | py_compile 只证明语法；环境、命令、manifest、Gate 交叉绑定待验证 |
| runner / factories / R2 tests | writer/prefix 和独立动态 fixture 迁移尚未验收 | 保留第36.8节初始 scaffold RED，不将其作为完整 oracle |
| 独立 QA | 已完成设计与 scaffold 只读审查 | 实现停写停测、冻结同一 hash 后再接手动态验收 |
| R3 / R4 / qualification | 尚未完成 | 不跳过真实双 lane、final-schema replay 或平台证据 |

当前源码允许处于过渡 RED 状态。角色分工与最新讨论保存在 [Teams 22](./team-sessions/team-session-2026-09-07-22.md)，通用恢复入口为 [交接文档](./AI_REFACTOR_HANDOFF.zh-CN.md) 第15.39节。权威合同以本方案为准；交接入口与讨论记录只作导航和历史，避免多处复制字段合同后漂移。

### 36.10 动态测试补强与未关闭审查项

以下为验收所需的具体补强，不新增节点计数、不扩大 R2 执行范围：

1. **独立 fixture**：测试侧手工生成真实临时 runtime 树、pyvenv、METADATA、RECORD、五个 required entries 和合法四包 TOML lock；独立计算 raw/base64/canonical hashes。不得调用 producer builder 生成 verifier 的唯一正例，也不得用不存在的路径迫使 live endpoint 校验放宽。
2. **真实 writer 路径**：仅运行临时复制的 runner，由受控 fake uv 记录完整调用链；实际验证 environment absent/corrupt/valid 三种候选提取，以及 EARLY、NO_EVENTS、malformed identity 的文件集合和 Gate 连续性。fake uv 不得启动真实 security 测试；stub 回执不能冒充真实 writer 产物。
3. **Prepared 与 main**：preparation 后把 runtime/distribution/lock/plugin readers 设为 tripwire，真实调用 guard 配置和 v2 独占发布；在隔离 main 中验证缺失、重复、错序 argv fail-stop。若 dataclass 与历史 importlib loader 不兼容，先定位实际原因，不通过批量改历史 loader 掩盖问题。
4. **时间与失败集合**：分别构造 argv timestamp、command.started_at、identity timestamp 的独立漂移和一致重绑；四类 failure 各做单因精确集合，再做两层 union。合法 envelope 下 runtime 错误不能遮蔽可独立证明的 plugin 错误。
5. **exact schema 与 bounded summary**：旧 schema、unknown/missing/nested drift、duplicate key、bool/float 版本反例必须进入真实 parser。summary 检查 exact keys 与绝对路径值，不禁止 `executable` 子串误伤 `executable_sha256`；依赖方向用 AST/import probe，不禁止合法文件名常量。
6. **read/mode/null**：通过实际 sidecar 验证权限、UTF-8、重复键、超限与 envelope；完整可读 raw 保留实际 SHA，未知 raw 为 null；invalid summary 的全部语义字段按第36.4节归零，不伪造 empty SHA。

本次架构只读 review 新发现 policy `schema_version != 3` 可接受浮点 `3.0`。主代理另观察 environment/command/manifest 的同类比较，以及 command 时间仅 regex 校验的风险。已交唯一实现角色处理：schema 必须严格整数；时间除格式外还必须是合法日历时间。**这些是进行中代码的待关闭审查项，不是已修复或最终 QA 结论。** 其余 policy exact shape、duplicate rejection、runtime authority 与 byte limits 在本次限定静态审查内未见新增缺口；该观察不替代动态测试。

### 36.11 下一次执行的顺序、证据与停止边界

1. 先读取本节与 Teams 22 的后续追加记录，检查实际 worktree 和现有代理；沿用 `b3e_s_impl` 唯一代码/测试写入者，不重复派发实现，不重放旧 R1b。保留所有已有 modified/deleted/untracked，包括根目录 `=`。
2. 实现角色完成独立 consumer 顶层集成、runner preflight/writers/final prefix、动态15节点与受影响旧 factories/断言。主代理只读审查并维护 docs；架构/QA 不并发改代码。
3. 实现角色记录显式低成本 selector、collect 数、动态 RED/GREEN、静态结果、源码/测试 SHA 和原始证据位置。每轮测试先确认无其他 pytest/runner 进程；不运行整个 `test_security_coverage_gate.py`、真实双 lane、final67 或平台 matrix。
4. 实现停写停测后，QA 在同一 hash 下独立验证动态 oracle、reader tripwire、nullable/profile、uv alias/banner、独立 consumer 与 failure union。失败则保留证据并回交实现；冻结 hash 漂移则不能沿用旧 QA。
5. 无并发测试后再运行文档治理检查：`uv run --offline --frozen --no-sync python -m pytest tests/contract/test_spec_inventory.py tests/contract/test_document_links.py -q -p no:cacheprovider`。记录当次结果，不复制历史 42 passed 作为当前证明。
6. 只有上述证据齐全才追加 R2 验收 checkpoint 和上位入口的冻结 hash；未齐全时继续标记 in-progress。之后依序 R3 真实双 lane/敌意 integration → R4 writer parity/final-schema replay → B3f-L67/B3c/B3d/B3e replay → B4/freeze ledger/各平台 qualification。

临时证据根可能被操作系统清理。方案已持久化不代表原始证据已备份；证据丢失时保留历史路径/hash，标记无法复验并重新取证，不能凭摘要恢复 PASS。此轮不新增 archive/restore、上传、同步、签名发布、commit/push 或破坏性清理动作。S18、W1b-5b、Release 继续 No-go，inventory 不晋级，W1b-5c/5d/5e 不执行。

### 36.12 Consumer 过程审查补充（源码修正待动态验证）

续接时确认工作分支仍为 `improve-inference-reliability`，实现角色继续运行且持有唯一代码/测试写入权。主代理只读核查发现并交回两项新缺口：

- malformed JSON 或顶层 exact shape 失败时，`record` 尚未赋值，后续 plugin 校验可能抛出 `UnboundLocalError`，无法按合同产生 invalid runtime summary。当前源码已初始化 record，并在 envelope 不合法时提前返回 RUNTIME；合法 envelope 仍继续独立 plugin 校验。
- sidecar `exact_package_object` 与实际 lock package 若仅使用 Python 深相等，嵌套 `1`、`1.0`、`True` 可能被视为相同，而 supplied canonical bytes 没有重绑该对象。当前源码已分别 canonicalize sidecar 和实际 package，比较完整字节，再核对 supplied canonical bytes/hash；不得通过 producer validator 复用来关闭独立性要求。

第36.10节 schema 严格整数与 command 合法日历日期要求也已在当前源码看到修正。以上均只证明修正已落盘，**尚未有本轮动态 GREEN 或独立 QA 验收**。反例须进入既有 malformed/envelope、exact schema、verifier independence/lock mutation 节点，不增加或虚报15节点计数。

架构与 QA 另在进行限定只读审查：顶层 command/runtime 外部绑定，以及合法 envelope 下 runtime/plugin 失败是否被错误短路。审查尚未结束，不把“未收到新问题”解释为通过。runner 原子迁移与动态 fixture/旧 factories 迁移继续按第36.11节执行。

### 36.13 Teams 过程复审待修复项

第36.12节之后，架构与 QA 完成该轮限定静态审查，未运行 pytest/runner、未改文件；以下问题已交唯一实现角色，未关闭，不作为最终 QA 验收结论：

| 来源 | 缺口与可复现反例 | 修复与测试要求 |
| --- | --- | --- |
| 架构 | command 只绑定 argv 首 token 与自身 uv-path option，未与 identity.uv.path 比较；两个不同 canonical pathname 的同内容二进制可逃过检查 | 私有验证事实保留 path 供 exact cross-binding，公开 Gate summary 仍 path-free；在既有 command/manifest 节点构造同 SHA 不同路径反例 |
| 架构 | 顶层用公开 summary.status=valid 门控全部 semantic/tool/uv 交叉；插件映射错误会令 summary invalid，并遮蔽独立的 environment/command uv 错误 | 展示 summary 与内部可验证事实分离；保留 sorted unique union。构造 plugin-only 错误并重绑 semantic，再叠加 before=after 但均与 identity/live 不等的 uv SHA，以及 command uv version/SHA 矛盾 |
| 架构 | command scope/sanitized_environment 结构类型未先验证，错误标量可能降级为 scope/config，list/dict 可能在直接 verify 的集合操作抛 TypeError | parser 明确检查 scope 字段和 env exact shape/type，environment/manifest scope 同步处理；错型走 GateFailure/input-invalid/no Gate，合法类型的错误值仍按既有语义分类 |
| QA | distribution 循环在 coverage 错误时退出，pytest-cov 尚未加入已验证集合，plugin 分支因此跳过 SHA 比较 | 合法 envelope + coverage metadata SHA 错 + cov plugin 另一合法64hex 应至少同时报 RUNTIME/PLUGIN；不能依赖所有 distributions 成功才检查独立可证明的插件绑定 |
| QA | sidecar 内容用 fd 读取，随后另 path.stat 取 mode；0644 原文件可在两步间被同 bytes 的0600新 inode 替换；stat 失败还会丢掉已完整读取 raw | mode 与同一 descriptor 的 fstat 绑定，并闭合 pathname identity；完整 bounded raw 仍保留实际 SHA，未知/超限 raw 才为 null。动态注入同内容换 inode、权限变化、读后 pathname 消失，禁止把坏 raw 伪装成合规文件 |

类型缺口的精确边界：当前 CLI main 已捕获 TypeError/KeyError，因此不能笼统声称 CLI 必然泄露 traceback；仍须修复 parser 的结构错误分类与直接调用异常合同。上述反例补入既有15节点，不新增 qualification、public artifact 字段或额外必需 sidecar。events schema3 保持原合同，不借本轮扩张重构范围。

uv live hash 与 identity 自述不等的内外归类，需以可验证事实裁决，不能推断究竟是 sidecar 篡改还是 binary 漂移。架构正在补充内部 binding facts 最小设计；在裁决与动态验证前，不声称 failure-union 已闭合。

### 36.14 内部分项验证事实与 uv 分类裁决

主代理接受架构补充设计，作为第36.13节修复合同；本节是待实现/验证的裁决，不是 GREEN。公开 schema、artifact 数量及 `_runtime_identity_report` 两值接口保持不变。

1. **内部 core 与公开 summary 分离**：私有 single-pass core 返回 summary、failures 与 binding facts；原 report helper 可作两值 wrapper，顶层直接调用同一 core 一次。facts 只供内部交叉校验，不序列化、不写新 sidecar、不进入 Gate 的 path-free summary。容器可用 namedtuple 或其他适合现有 loader 的形式，不要求 dataclass。
2. **按依赖建立事实**：exact envelope 不合法时不猜 plugin 语义。合法 envelope 下，scope、canonical semantic、uv claim/live、distribution 与 plugin 分项验证，独立累积错误；某项失败不能清空其他已经独立建立的事实。特别是较早 distribution 失败不能使 pytest-cov live/entry 对照全部跳过。保留同次捕获的数据，不为公开 summary 和外部绑定各读一次现场。
3. **semantic 权威**：只有 canonical bytes 重算与 claim 相等才产生 semantic fact；此后即使 plugin mapping 等语义不合格，仍可将这个已重算摘要与 manifest/environment 比较。若 claim 自身不等于重算值，该 fact 不成立，不能用坏摘要捏造额外 TOOLCHAIN。公开 summary 只要 identity 验证有失败仍整体 invalid/null。
4. **uv 内部与外部**：uv shape、lexical path、version/SHA 类型或格式、semantic 自洽错误归 RUNTIME。语法合法的 uv claim 指向合法 endpoint，但该 endpoint 无法安全读取，或 stable live hash 与 claimed hash 不等，归 TOOLCHAIN；此时 summary 仍 invalid。若另有内部错误则 RUNTIME/TOOLCHAIN 并集。claim 只表示已验证结构的自述，live hash 才表示当次现场观测，不把二者混称为已证明供应链可信。
5. **command 边界**：整体 schema/scope/env 类型非法仍 input-invalid/no Gate。schema 合法但 uv options 缺失/重复/错序、path 不自洽等归 CONFIG；结构合法自洽的 uv path/version/SHA 与 identity 的相应可验证事实不同归 TOOLCHAIN。某个无关 flag 产生 CONFIG，不能整体禁用仍合法的 uv 字段，否则再次遮蔽独立错误；也不能从 malformed 字段猜造 TOOLCHAIN。
6. **权限与 raw**：identity 专用读取结果须保留同一 fd 的 mode 与完整 bounded raw，闭合 pathname identity。读后 mode/pathname 不合格归 RUNTIME，不将已经完整取得的 raw SHA 改成 null；真正未取得完整 bounded bytes 时才为 null。不得依赖随后独立 `path.stat()` 修饰原 fd 的 mode。

最小反例继续纳入现有15节点：同 SHA 不同 uv path；plugin 错误叠加外部 uv/hash 错误；runtime 早错叠加 cov plugin SHA 错误；uv 内部错误与 live 矛盾的独立/并集；wrong flag 与合法但外部矛盾的 uv observation；同内容换 inode/mode 与读后 pathname 消失。R2 仍只执行受控临时 runner/fake uv 和低成本合同，真实双 lane 与平台证据留在后续阶段。

### 36.15 Runner 首版落盘与启动审查（未验收）

实现角色完成 runner 首版替换，报告文件 mode755、`bash -n` 与 bootstrap/verifier 的 py_compile 通过；主代理回读确认新 runner 已存在。替换期间曾短暂读取到 runner 不存在，未恢复旧文件、未启动测试；不得将该瞬间状态作为最终丢失文件结论。

主代理随后发现首版启动逻辑仍有动态必需修复项，均已反馈实现角色：

- version 查询用管道接 `python -`，但 Python 源码又占用 heredoc stdin，读取 banner 时会得到 EOF。必须遵守第36.7节完整原始输出验证，不能只修源码字符串计数；优先在统一 prefix helper 内完成唯一一次受控 subprocess 查询并限制输出。
- readlink 的 marker 保留了工具常规终止 LF，控制字符检查会误拒绝合法 Homebrew alias；末尾 printf 还可能覆盖 readlink 失败状态。必须区分工具追加的终止 LF 与真实 link target 中的控制字符，保留 cycle/hops/fail-closed 要求。
- preflight helper 的原始 stderr 尚未封住，可能在固定 CONFIG 诊断前泄漏工具错误；失败边界只能输出约定诊断。repository_root 的 subshell 计算不改变父 shell cwd，首次 uv 之前还须进入已确定仓库，防止统一 prefix 在错误项目下执行。
- environment 的 identity 提取未拒绝 duplicate JSON keys；manifest 的新增 semantic 提取还在无界 read_text。必须恢复第36.4节 bounded strict 候选语义，不能仅凭最终 verifier 拒绝而豁免 writer 合同。

架构/QA 分别继续限定审查 runner 前半 preflight 与后半 writer/profile，不运行真实脚本、不新增并发测试。本节所有问题仍待动态正反例证明；当前没有 R2 GREEN，首版 `bash -n` 只证明 shell 语法。

### 36.16 Runner 复审收口与具体反例

架构/QA 已完成第36.15节限定静态复审；以下裁决交实现角色处理，仍未动态验收：

- **version helper 失败传播**：heredoc 终止符后另起 `2>/dev/null` 是新的空命令，不会重定向前一个 helper，且会覆盖其失败状态。重定向必须属于实际调用。Popen 读取513 bytes 后不得先无条件 wait，再判断超限；持续输出可能填满 pipe，须有界拒绝并终止/回收 child，仍保持唯一 version 查询。
- **外层 helper 协议**：创建 root 前再次验证 hashA/hashB 各为 exact 64位小写hex，uv_version 为非空合法 VERSION 且长度不超过128。fake uv 对所有 run 返回空stdout/exit0，或在正常helper输出前后加固定notice，都必须 CONFIG 且尚未创建root；A==B 不等于 A/B 是合法 digest。
- **path/cycle**：control 检查覆盖初始 command-v candidate、每轮 canonical absolute path 和 readlink target；不能只查 target。seen paths 用 Bash 数组逐项 quoted equality，避免 `|` 拼接产生跨记录歧义。勘误：原 case 模式中变量已引用，`*?[]` 并不会因变量内容而变成 glob 语法，不以错误的“glob 注入”理由拒绝合法文件名。
- **uv hard link**：冻结合同只要求 canonical regular executable、非 symlink leaf、安全有界读取和身份稳定，不新增 uv single-link 限制。nlink 可纳入身份观测，但合法 hard-linked uv 不能仅因 nlink>1 被拒绝。runner 与 consumer 的 uv 读取语义一致；其他已有 runtime/evidence 文件限制不借此放宽。
- **输入与配置失败**：完整 input helper 明确证明 root/run_id/attempt/parent 非法时归 INPUT；uv/Python/helper 启动或执行故障归 CONFIG。若 child 已创建root后外层失败，按创建后生命周期保留证据，不自动清理，不新增提交 sidecar/回滚义务，也不声称root仍不存在。
- **coverage raw 闭合**：FULL/NO_EVENTS 都要求 `.coverage-capture` 或 `.coverage-retention`。shell raw-completeness 与 runner-error required 集合必须同时包含实际 coverage_name；只有JSON/JUnit/identity而缺 raw 时不能生成 manifest/Gate。该反例纳入现有 profile 节点，不伪造完整 profile。
- **strict JSON 常量**：候选 decoder 除重复键外还须拒绝 NaN/Infinity 等非JSON常量。nested 非法值但 schema/semantic/版本可提取的反例，仍只保留完整 raw SHA，semantic/tools 全null；后续 verifier 拒绝不能代替 writer 本身的 strict 合同。

本轮所有新问题、修正、retry继续保留。private facts core、fd绑定读取、runner修复和动态15节点尚未共同闭合；独立 QA 最终验收仍须等待实现冻结与明确执行锁交接。第36.12至36.16节是当前续接必读的过程记录，不得只读旧首版或 syntax PASS 后跳入 R3。

### 36.17 最新实现回报与复核未闭合项

实现角色报告第36.16节主要 runner 修正已落盘：唯一 version 子进程、有界读取与5秒终止、正确 stderr 重定向、readlink marker/状态、首次uv前cd、外层A/B/version校验、control/exact cycle、uv hard-link语义、INPUT结果区分、coverage raw required。consumer 已新增 private 三值core/两值wrapper、facts与单fd sidecar读取。主代理回读确认这些结构存在；实现角色报告静态检查通过，**尚未执行新 pytest，不作动态成功证明**。

主代理进一步回读 core，发现第36.14节仍未完全落实，已反馈实现角色继续修正：

1. scope 在建立facts前的外层try中失败，仍会跳过uv/semantic/distribution部分。应独立累积scope失败，再继续没有依赖该scope的可验证部分；不能将旧summary门控换成scope门控。
2. distribution_versions 暂时只从sidecar candidate name/version格式提取，尚非经过METADATA/RECORD/lock/live验证的分项事实。应逐distribution独立验证，单项失败不阻止其他项，且仅在该项验证成功后建立version fact；不得用伪造candidate与诚实environment的不等制造额外TOOLCHAIN。
3. 顶层command交叉仍以argv长度满足便读取固定索引并removeprefix；错序/坏prefix可能产生虚假的TOOLCHAIN。应先确认uv observation本身的exact位置、prefix、格式和路径自洽，再比较；无关flag的CONFIG不能禁用已合法的uv observation。
4. cov required entry成功读取后，独立plugin分支又读同endpoint。应复用同次captured bytes/观测；只有此前未capture时才独立读取，兼顾不短路与single-pass要求。

以上是对既有裁决的实现复核，不是新增范围。下一次从实际源码和实现角色状态续接，先完成这些修正以及动态fixture/旧factories迁移，再取得精确低成本RED/GREEN与冻结hash独立QA。主代理本轮只维护docs和只读审查，未并发启动pytest；S18、W1b-5b、Release与整体目标仍未完成。

### 36.18 首批动态证据与文件级并行分工

主代理读取当前证据根 `/private/tmp/ai-auto-lrc-b3f-r2.kekIET9M` 的 stdout/JUnit，确认以下执行事实：

| 记录 | 实际结果与边界 | JUnit SHA-256 |
| --- | --- | --- |
| consumer-fixture-retry | 独立临时runtime树下summary/independence两项正例通过；不是完整动态15 | 见原始JUnit，不据此代签后续改动 |
| dynamic-core-red | 4执行，2失败/2通过；timestamp的uv fact缺失是真实行为RED，failure_classes首次在源码substring处失败，尚未触达后续mutation | `9e093a3aba57b076073e14c5dabc71c4954cc22918a6bd18ce0177adafbe9b19` |
| dynamic-core-green1 | 4通过；包含已补的局部consumer mutation，不能代签顶层完整bundle交叉绑定 | `c6831e4bf7901165fe40e377dfbfabb0f9a280e6e290a854ba14c8aafce3d3ed` |
| exact15-retry1 | 13通过/2失败；失败为environment与profile源码substring旧断言，若干通过项仍为scaffold，不能称13项动态验收 | `433a6eea678c42536916ab56c4f976cd21f8f986c42ec142f6758892b0519d1e` |

这些集合有重叠，不相加为唯一测试计数；源码继续修改，尚无最终冻结hash。本轮读到的新增fixture已使用真实临时文件、合法TOML lock与手工identity，不再依赖producer builder；仍须补完整writer/control-flow和真实顶层verify oracle。

为减少串行等待，主代理与实现角色明确确认后调整第36.1节的**文件写入分工**，不改变产品合同或单一测试执行锁：

- `b3e_s_impl` 保留所有现有产品文件、R2 test本体、旧factories/断言的唯一写入权，负责接线；仍是唯一pytest/runner执行者。
- `p1_inventory_design` 仅获得新文件 `tests/contract/security_runtime_r2_runner_harness.py` 的写入权，编写tmp-copy runner + fake uv辅助工具；不得修改产品、test本体、其他helper或运行pytest/runner。该文件无新增test节点，不改变15节点计数。
- 辅助工具必须使用临时目录，完整记录fake uv调用；真实执行被复制runner的helper/writer控制流，但拦截bootstrap/security测试调用，绝不启动真实安全双lane。它可使用fixture供应商生成的raw样本，不能将stub Gate冒充真实verifier输出。实现接线后再由唯一执行者验证。
- `b3e_s_qa` 继续独立只读审查/后续验收，不参与该helper编写；架构角色不能以自己编写helper的结果代签独立QA。
- 主代理维护docs并审查结果；新helper交付后须明确停写、再移交给实现角色接线或修复。禁止两个角色同时编辑同一文件。

实现角色确认此前尚未创建/准备独立fake-uv helper，主代理确认新路径不存在后派发；因此这次是明确的独立文件所有权划分，不是覆盖已有工作。所有真实测试仍串行，R2尚未验收，No-go与后续R3/R4边界不变。

### 36.19 本地持久化 checkpoint：实现已交付，最终独立 QA 尚未开始

本节响应用户“将方案写到本地文件中，以免后续流失细节”，追加保存当前恢复点；第36.12至36.18节的过程问题、旧 RED 和 retry 保留原状。当前分支现场确认是 `improve-inference-reliability`。**实现角色报告完成 R2 产品/测试迁移，不等于 R2 已通过独立验收；整体重构仍未完成。** 本次仅更新文档和核对已有证据，不启动产品重构、最终 QA、真实 security 双 lane 或发布操作。

#### 36.19.1 角色交付与恢复时所有权

- `b3e_s_impl` 已完成并停写停测；它负责接线后修复 harness，因此架构角色最初交付的 `5318cd6c19df5e52ba8cad26931cd72381faf2634f9ea409d71491aaffe222c8` 仅为历史 hash。
- `p1_inventory_design` 已停止写入并把 harness 所有权交回实现角色，不得基于旧交付 hash 复验或覆盖当前文件。
- `b3e_s_qa` 最后完成的是过程静态审查，不是下表最终快照的独立验收；**最终 QA 尚未派发**。下次继续时显式交接唯一测试执行权，主代理和其他角色不得并发 pytest/runner。
- 主代理本次重新计算下表八项 SHA-256，均与实现交付报告一致；检查时没有发现 pytest/runner 进程。这个瞬时检查不能替代后续执行前重新检查。

#### 36.19.2 当前实现快照（待独立 QA，不是 release freeze）

| 文件 | SHA-256 |
| --- | --- |
| `scripts/security_pytest_bootstrap.py` | `caa411d25e58119e8b49a15228d08e2e19597eea3256adac0c8e62c302955954` |
| `scripts/verify_security_coverage.py` | `a4a6e8e7c5e7eabba6023f0760b7778f4e596151e08edfa38e0b93fb0d538d25` |
| `scripts/run_security_coverage.sh` | `449706c487ac525fc59bce4d3dba3db75c3bbe8ab319947580171d80704ced5d` |
| `packaging/security-coverage-policy.toml` | `dff4d4662133f77c19abadf1eca322660e4ccd9471e4933ff451f0bf48ff5ce8` |
| `tests/contract/security_runtime_r2_runner_harness.py` | `e817887597abf7c8c02b11884c5b8af90be84f05a52c3f5f0423c95abb925d37` |
| `tests/contract/test_security_runtime_identity_r2.py` | `514c6fdc0ef60b876483c8017e8b9831aca2cfb3c64584ffd8da371ae20549e3` |
| `tests/contract/test_security_coverage_gate.py` | `1dd44b3367f47f7551b928ac9b178f34d90f8e6f432ae7948f0c4927edc9b649` |
| `tests/contract/test_security_runtime_identity_r1b.py` | `8dabe49a4cdba603a372e2b1da026ce4247c71dba61822ed84134b13e04979f5` |

实现报告的修正包括：真实 Prepared capture → builder → guard 发布且发布阶段不二读；产品 METADATA 的 `email.header.Header` 值在 `_metadata_name_version` 转为普通 `str`，不能只在 fixture 转换来掩盖边界错误；sidecar 同 fd 权限与换 inode 竞态；private single-pass facts/独立失败并集；macOS Bash 3.2 `set -u` 空数组用空哨兵兼容；harness PATH 隔离防止 fake uv 被拒后回落到真实 uv。上述修正须由 QA 核查动态 oracle，不因本段摘要而视为问题关闭。

#### 36.19.3 最终选择集原始证据与计数边界

证据根：`/private/tmp/ai-auto-lrc-b3f-r2.kekIET9M`。主代理现场读取 stdout 和 JUnit：stdout 为 `46 passed in 27.41s`；JUnit 为 tests=46、failures=0、errors=0、skipped=0。实际组成如下，不与历史 retry 累加：

| 来源 | 实际 testcase 数 | 可证明范围 |
| --- | --- | --- |
| `test_security_runtime_identity_r2.py` | 15 | 第36节 exact15 均出现在该次 JUnit；是否每条 oracle 足以验收仍待 QA |
| `test_security_coverage_gate.py` 显式选择项 | 29 | plugin identity 和 legacy toolchain schema 受影响合同，不是整个文件或真实双 lane |
| `test_security_runtime_identity_r1b.py` | 2 | 仅 loader failure 静态终止与 main 失败退出；不是 R1b 全集 |

R2 的15个节点分别覆盖：existing root 前置拒绝、单一 absolute uv/prefix、精确 bootstrap argv、Prepared 发布不二读、timestamp 权威/交叉、artifact exact versions、identity read/mode/envelope、failure classes、nullable environment、manifest 无 hash cycle、bounded/path-free summary、identity size limit、独立 verifier、EARLY/NO_EVENTS/malformed profiles、policy/Gate schema。节点存在和计数通过不替代内部反例覆盖审查。

R1b 两项的精确函数名为 `test_s18_b3f_r1b_loader_failure_path_is_statically_terminal` 与 `test_s18_b3f_r1b_loader_failure_exits_without_publish_or_pytest`。本次 JUnit **不包含 R1a10 或 R1b exact15 全集**；不能把第35节历史绿色移植到当前已变化的代码上。后续 QA 要列出所需回归，另行保存新的显式 selector 和结果。

| 原始文件 | SHA-256 |
| --- | --- |
| `final-affected-selectors-green.stdout` | `4c2f6f239e1177dbbbe6140ead8d81a1768a6aa44abb067cee14be12108ffe1c` |
| `final-affected-selectors-green.junit.xml` | `8e020baf83b7fa4560ac657b812fc7d01b401281aa2daab1eeb6714b96441622` |
| `final-affected-selectors-red.stdout` | `4c2f6f239e1177dbbbe6140ead8d81a1768a6aa44abb067cee14be12108ffe1c` |
| `final-affected-selectors-red.junit.xml` | `8e020baf83b7fa4560ac657b812fc7d01b401281aa2daab1eeb6714b96441622` |

**证据命名警告**：green stdout 内打印的 JUnit 目标仍为 `final-affected-selectors-red.junit.xml`，且 red/green 两对文件各自 hash 完全相同。只认定一个46项执行结果，不认定两轮独立执行，也不把 `red` 文件名认作行为 RED。最终 fresh QA 必须用无歧义的新证据目录，记录实际命令、显式 nodeids、执行前后源码 hash 和原始结果。上述临时文件未在此次保存中复制或归档；系统清理后只能保留历史引用、标记证据不可复验并重新取证，不能从摘要重建 PASS。

实现另报告 `bash -n`、py_compile、Ruff check、`git diff --check` 通过及 runner mode755；本次不将它们改写为主代理独立重跑结果。**`ruff format --check` 仍有全文件格式漂移，未通过。** 实现认为是长期文件既有漂移，但尚未独立证明全部属于历史；当前不为此进行数千行机械重排。

#### 36.19.4 下一轮可执行 QA 清单与停止条件

1. 重新检查 worktree、八个 hash 和角色状态；任何 hash 漂移都要记录并重新确定验证快照，禁止覆盖用户 dirty/deleted/untracked（含根目录 `=`）。沿用现有代理，不重复创建实现任务。
2. 实现保持停写停测后，把单一执行锁显式交给 `b3e_s_qa`。先只读确认 exact15 全部使用真实行为断言，而不是 source substring、标志名或手工 union 代签；核对 fixture 独立性及 stub Gate 的 `harness_stub`/`not_verification_evidence` 标记。
3. 重点复核第36.13至36.17节反例：scope 不遮蔽 facts、distribution facts 真正验证后建立、cov captured bytes 复用、malformed command 不捏造 TOOLCHAIN、无关 CONFIG 不遮蔽合法外部矛盾、canonical lock 严格类型、同 fd mode/换 inode/raw SHA、真实 Prepared → builder，以及真实 writer 的 nullable/strict JSON/profile 控制流。
4. 从上述 JUnit 恢复精确46节点清单并与源码/collect 比对；明确 R1a/R1b/legacy 额外回归选择范围后进行 fresh 低成本复验。只允许显式合同、collect/static、临时复制 runner + fake uv；bootstrap 必须拦截，真实 verifier 可以显式调用。禁止整个 `test_security_coverage_gate.py`、真实双 lane、final67 和平台 matrix。
5. QA 保存新目录中的实际 selector、stdout/JUnit、源码/测试 hash 和证据索引，列出 P0/P1、覆盖与未覆盖边界。失败交回实现按 test-first 修复，再停写、换 hash、独立复验；禁止沿用旧绿色。
6. QA 释放执行锁后，主代理运行第36.11节的文档治理选择集。只有同 hash 独立 QA、回归范围、静态结果及文档门齐全，才能追加 R2 验收和四个上位入口的最终引用；本次上位入口仍保留 WIP，不伪造最终冻结 hash。

后续依赖顺序保持：R2 独立验收 → R3 真实双 lane/hostile integration → R4 writer parity/final-schema replay → B3f-L67/B3c/B3d/B3e replay → B4/freeze ledger/各平台 qualification。identity2/policy3/environment5/command4/manifest5/Gate5 为本轮原子迁移合同；events3、security manifest1、runner-error2、pyproject 和 uv.lock 不借本轮扩张。S18、W1b-5b、Release 继续 **No-go**，inventory 不晋级；不执行 W1b-5c/5d/5e、commit/push、CI、上传同步、签名发布、archive/restore 或破坏性清理。

#### 36.19.5 Teams 澄清：最终命令与结果文件命名

实现角色在本次仅只读澄清中确认：运行前预先取名 `red`，该次实际直接通过，随后将 stdout/JUnit 逐字复制成 `green` 文件，未进行第二次执行。该说明与主代理观测到的相同 hash 一致；不把这次执行写成经历了行为 RED → GREEN。实现角色保持停写停测，未因澄清重跑测试。

以下为实现提供的**历史实际命令**，供复核选择器，不是本次保存时执行的命令，也不是直接复用旧证据路径的授权。下次独立 QA 应采用新路径、显式记录真实退出码，并先确认选择范围：

```sh
.venv/bin/python -m pytest -q \
  tests/contract/test_security_runtime_identity_r2.py \
  tests/contract/test_security_coverage_gate.py::test_s18_plugin_identity_record_field_is_only_the_plugin_record_entry_digest \
  tests/contract/test_security_coverage_gate.py::test_s18_gate_rejects_invalid_plugin_identity_schema \
  tests/contract/test_security_coverage_gate.py::test_s18_gate_rejects_duplicate_plugin_identity_keys \
  tests/contract/test_security_coverage_gate.py::test_s18_gate_rejects_b3f_r_only_plugin_identity_fields \
  tests/contract/test_security_coverage_gate.py::test_s18_gate_rejects_plugin_identity_not_published_mode_0600 \
  tests/contract/test_security_coverage_gate.py::test_s18_gate_rejects_cross_scope_plugin_identity \
  tests/contract/test_security_coverage_gate.py::test_s18_gate_rejects_plugin_identity_origin_or_record_mismatch \
  tests/contract/test_security_coverage_gate.py::test_s18_gate_rejects_whole_record_file_hash_in_record_entry_field \
  tests/contract/test_security_coverage_gate.py::test_s18_gate_binds_plugin_identity_artifact_hash \
  tests/contract/test_security_coverage_gate.py::test_s18_gate_rejects_legacy_toolchain_evidence_schema \
  tests/contract/test_security_runtime_identity_r1b.py::test_s18_b3f_r1b_loader_failure_path_is_statically_terminal \
  tests/contract/test_security_runtime_identity_r1b.py::test_s18_b3f_r1b_loader_failure_exits_without_publish_or_pytest \
  --junitxml=/private/tmp/ai-auto-lrc-b3f-r2.kekIET9M/final-affected-selectors-red.junit.xml \
  | tee /private/tmp/ai-auto-lrc-b3f-r2.kekIET9M/final-affected-selectors-red.stdout
```

该命令文本没有展示 `pipefail` 设置，因此不从管道末端退出码推定 pytest 状态；当前通过结论来自实际 stdout 与零失败/错误的46项 JUnit。未来证据索引须单独记录 pytest 退出码，避免仅凭 tee 成功判断。

#### 36.19.6 本次文档保存验证

上述正文与 Teams 22 第10节落盘后，主代理独占执行文档治理选择集：`uv run --offline --frozen --no-sync python -m pytest tests/contract/test_spec_inventory.py tests/contract/test_document_links.py -q -p no:cacheprovider`，本次结果为 **42 passed in 12.12s，退出码0**；文档内部链接/锚点与 specification inventory 检查通过。`git diff --check` 同次退出码0（只覆盖 Git 可见的已跟踪差异；docs 当前为 untracked，不能将它当作新增文档的完整格式检查）。本小节为执行后追加的结果记录。

这42项是本次文档一致性验证，不是重新执行实现的46项，也不是 R2 独立 QA。只修改现有两份文档，未修改产品或测试、未提交或推送；四个上位入口仍指向第36节的最新 checkpoint，不更新为最终验收状态。

### 36.20 独立 QA 正式派发与主代理覆盖复审

整体目标恢复执行后，主代理重新核对第36.19.2节八个 hash，全部一致；检查时未发现 pytest/runner 进程，原有 dirty/deleted/untracked 保持。上一轮本地保存属于已完成的文档进展，不是产品验收。本轮正式把唯一测试执行权交给 `b3e_s_qa`，要求先审查 oracle/harness，再在新临时目录 fresh collect/执行第36.19.5节46项选择器及必要显式低成本回归，记录实际退出码、精确节点、前后 hash、原始输出与证据索引。实现角色保持停写停测；主代理只读审查/维护文档。

主代理回读当前测试发现以下**待 QA 判定的覆盖缺口**，不能仅凭15节点齐全放行：

- manifest 节点目前直接调用 parser 验证 baseline/unknown/null，没有该节点合同中的 raw/semantic/environment 跨产物漂移动态断言。
- policy/Gate 节点主要对 policy 值及 Gate 源码字符串断言，未在该节点覆盖 nested exact/duplicate 与完整 Gate schema；版本反例使用 `2.0` 而非历史缺陷的同值 `3.0`，需核对其他测试是否覆盖。
- failure_classes 有四类单因和 RUNTIME+PLUGIN 并集；PLUGIN+TOOLCHAIN、无关 CONFIG+合法 uv 外部矛盾及 malformed observation 不捏造 TOOLCHAIN 等裁决反例尚需核对。
- Prepared 主节点 stub 了 preparation；旧 Gate fixture 使用真实 capture → builder，仍需准确区分其证明范围与实际 `_prepare_bound_runtime`、加载、guard 连续性的证明，不能笼统称全部真实启动链通过。

产品只读复审另发现 input helper 调用没有像 hash/version helper 一样封住底层 stderr，且 mkdir 的所有 OSError 均归 INPUT；已要求 QA 在受控临时 fake uv/probe 中独立核实固定诊断与 INPUT/CONFIG 边界。此时尚无动态结论，不先宣称缺陷关闭或必然发生。

`p1_inventory_design` 同时仅做 R3 入场后的验证设计审阅，不改文件、不运行任何测试/probe；其结果须经主代理审阅，不能提前启动 R3，也不能代签其参与编写的 harness。当前 R2 仍未验收，所有 No-go/真实双 lane/final67/平台和外部写入边界不变。

### 36.21 QA 阶段证据与 test-first 修复清单（未验收）

QA 已确认第36.20节列出的动态 oracle 缺口成立，因此当前 R2 **不能验收**。QA 仍持测试锁，正在完成独立故障 probe；实现角色仅完成只读修复设计，未获写入/执行交接。

新的独立证据根为 `/private/tmp/ai-auto-lrc-b3f-r2-final-qa.lb8Tki`。主代理已回读 `history46-collect.stdout` 的46个精确 nodeids 与 `history46.stdout`：**46 passed in 33.36s**；QA 报告 formal pytest 退出码0、stderr为空，前后八项 hash 列表一致。JUnit SHA-256 为 `9ba7d22ba8f3988e8d31c1b39cb901dea9676eff8504cd32211a87c6e8595925`。本次是独立新执行，不是第36.19节文件复制；通过仅证明现有测试可复现，不关闭缺少 oracle 的合同。

Prepared 覆盖勘误：第36.20节指出主 R2 节点 stub preparation 属实；进一步读取已选择 R1b 节点内部 `_REAL_MAIN_SUCCESS_PROBE`，确认它实际调用 original prepare/loader/builder 并构造 guard，但 fake events、拦截 pytest.main 且禁止 writer。故已有真实 capture/load/build 证据，**缺的是捕获后 reader tripwire → guard 真实发布的连续验证**，不能夸大为完全未执行 prepare，也不能把分离用例相加成全链证明。

后续收到明确执行锁交接后，唯一实现角色按以下顺序在原15节点内补强，不改节点计数、不省略旧反例：

| 合同缺口 | 最小执行与 oracle |
| --- | --- |
| input helper 诊断/分类 | 受控 fake uv 对 input helper 输出 marker stderr + 非零；runner 只能输出固定 CONFIG 且 root 未创建。mkdir 的 EACCES/ENOSPC 是执行故障；FileExists 竞态仍 INPUT。先保存 RED，再最小修正重定向和异常分支 |
| 真正 Prepared 发布 | 复用 R1b 隔离 subprocess，真实 prepare/loader 与 local events 单次加载后设置读取 tripwire，真实 builder/guard/exclusive writer；仅拦截 pytest.main 不启动安全测试。断言实际文件 bytes、v2、0600、调用次数，不用 fake events 代签 events single-read |
| exact schema | policy3/identity2/environment5/command4/manifest5 分别加入同值 float 与 bool、旧版本、unknown/missing/nested drift；policy TOML duplicate 动态拒绝；完整 Gate 对照第36.4节14个顶层键及真实 nested exact key sets，不凭错误数量或源码字符串判断 |
| manifest 跨产物 | baseline full verify PASS；raw 空白变化、manifest semantic、environment semantic/raw 引用分别漂移，重绑非目标 artifact hash，精确 TOOLCHAIN；禁止只调用 `_run_manifest` 代签 |
| 独立错误并集 | PLUGIN+TOOLCHAIN、RUNTIME+PLUGIN、scope RUNTIME+live TOOLCHAIN；在不移动 bootstrap option 索引的后半无关 flag 上制造 CONFIG，再改变合法 command uv observation，精确 CONFIG+TOOLCHAIN。错序/坏 observation 只 CONFIG，不捏造 TOOLCHAIN；同 bytes/SHA 不同 uv canonical path 仍 TOOLCHAIN |
| private facts/single-pass | scope 错误不遮蔽独立 semantic/uv/distribution facts；早期 coverage 分项损坏不得建立 coverage version fact，但后续真正成功的 distribution 仍保留；cov endpoint 正常路径 read-count=1，plugin 分支复用已捕获 bytes |
| read/null/边界 | 完整读取后 pathname 消失仍保留 raw SHA；mode 错误进入真实 Gate 后 top/nested raw SHA 相等且语义全null；missing/unreadable/oversize 才为null而非empty SHA。nested cap 的边界读取与合法语义分开证明，不把 padding 等同合法身份 |
| writer strict/profile | nested duplicate 与 NaN/Infinity/-Infinity 即使候选字段可提取也全部拒绝提取，只保留完整 raw SHA；FULL/NO_EVENTS/损坏identity到达 verifier，required raw 缺失 EARLY。stub Gate 只能证明控制流，真实 consumer 判失败另须动态验证 |

实现只读另观察 consumer `_strict_json` 缺 `parse_constant`；先用动态 RED 判断其 strict boundary，再最小修复，不凭该观察提前修改冻结快照。多数条目首先是测试证据缺口，不预设产品一定错误，也不通过预改 verifier 让测试显得自然通过。

修复后的验收仍要求：新目录 RED/最小 GREEN → fresh exact15与显式受影响回归 → 停写停测和新 hash → 独立 QA。第36.19旧绿色与当前 QA fresh46 均历史保留，不覆盖、不累计成唯一覆盖数。

### 36.22 R3 入场后验证设计（proposed，当前不执行）

本节保存架构角色只读设计，经主代理审阅后仍标为 proposed；不是 R2 验收、R3 开工或已存在测试节点的声明。源码/测试 hash、所有 P0/P1、执行锁未闭合前不得启动。R2 已前移完成 absolute uv prefix/main legacy removal/writers，R3 不重复实现这些功能，验证真实 integration。仓库尚无确认存在的 `test_*r3` 节点，不编造 selector；进入阶段后先实现并 collect，再冻结精确选择集。

现有真实入口是 `scripts/run_security_coverage.sh ABSOLUTE_ARTIFACT_ROOT RUN_ID [ATTEMPT]`，一次调用固定 capture 后 retention，不另起并行 lane。artifact root 必须绝对且不存在；每例使用新外部目录，变异例使用独立临时 repo/runtime，绝不修改 canonical checkout 的 uv.lock、真实 .venv 或系统 uv。

| 场景 | fixture/执行与成本 | 必需观察与停止条件 |
| --- | --- | --- |
| 正常 capture + retention | 一次真实 full runner，高成本；两lane独立产物，不能以capture代签retention | 两Gate v5 PASS、独立coverage raw/JSON/JUnit/events3/identity2/environment5/command4/manifest5/stdout/stderr/verifier日志完整；任一缺件/非零/失败即停止 |
| 同host semantic一致 | 复用上行两lane，低成本 | 每lane identity/environment/manifest三方semantic相等且跨lane相等；排除run_id/target/attempt/timestamp，仅证明该host |
| PATH poison/no re-resolution | 临时PATH alias指向冻结真实uv，root创建后通过确定同步点原子替换alias为marker tripwire；一次真实双lane，高成本 | 两lane PASS、marker不存在、所有command和identity仍绑定原canonical uv、before=after；替换未发生或同步超时属于fixture无效，不能仅用sleep竞态得出PASS |
| uv version失败 | 私有endpoint仅针对version注入非零/超时/非法banner，受控run委托冻结工具；低成本preflight | exit2、stderr只有固定CONFIG、root不存在、不得进入pytest；不泄漏底层输出 |
| uv endpoint漂移 | 私有可安全执行endpoint，确定pytest启动同步点后原子换成不同bytes仍可委托工具的endpoint；高成本 | 不触碰系统uv；before/after矛盾，Gate若产生须含TOOLCHAIN、overall非零；无法确定同步或隔离则不执行 |
| lock漂移 | 临时repo中的retention测试只修改临时可解析lock；高成本 | capture control PASS，retention检测before/after且失败；记录mutation receipt和canonical lock前后未变。不得同步/联网/污染真实lock |
| 必需flags | 六个token逐一删除/重复，Python组与uv组各一个换序，共14个候选变体；每例新root，中高成本 | 到verifier的完整合法artifact按CONFIG失败；bootstrap/uv提前拒绝的无Gate profile须先裁决，不能把无Gate误写成CONFIG Gate；详见下方前置问题 |
| `.pth`/sitecustomize | 私有venv唯一site-packages注入两个不同marker，高成本真实双lane | 两marker不存在、两Gate PASS、只append已验证site root；私有runtime无法满足canonical executable/pyvenv合同则fixture无效，不降级成PYTHONPATH-only测试 |

**R3 开工前必须裁决**：flag删除会触发 bootstrap/uv 提前失败，预期应区分固定 preflight 拒绝、lane runner-error 与已生成 Gate，不能事后统一粉饰为 CONFIG Gate。删除 `--offline`/`--no-sync` 前须先证明网络禁止、disposable runtime 与私有缓存隔离机制；未证明则禁止执行该变体，而非放宽隔离。此项是未来测试合同设计，不授权联网、安装、同步或修改实际工具链。

每个变体保存执行argv、精确selector、实际退出码、原始stdout/stderr/JUnit、前后hash、mutation receipt和artifact索引；唯一执行锁串行。出现源码漂移、canonical状态改动、意外网络/sync或不符合已裁决profile的结果即停止后续矩阵，保存失败。超时须按受控子进程句柄终止并回收该次进程树，保留无效attempt，不与重跑合并。

现有 R2 fake-uv/stub-Gate、R1b semantic unit、synthetic loader sentinel只是前置合同；旧 hostile runner fixtures 仍有旧prefix预期，不能直接列为R3通过证据。R3仅形成执行host的 installed-record-consistent integration，不宣称完整import graph/wheel/SBOM/签名或另一平台合格。R4 writer parity/final-schema replay、B3f-L67/B3c/B3d/B3e、B4/freeze ledger与各平台qualification仍独立待完成。

### 36.23 独立 QA 已证实两个 runner P1：回归通过不等于验收

证据根沿用第36.21节的新 QA 目录。主代理已回读各 stdout、退出码和 JUnit hash：

| 执行集合 | 本次结果 | JUnit SHA-256 |
| --- | --- | --- |
| history46 | 46 passed in 33.36s；exit0 | `9ba7d22ba8f3988e8d31c1b39cb901dea9676eff8504cd32211a87c6e8595925` |
| r1a10 | 10 passed in 0.16s；exit0 | `218be576ecebbc0e9a59758441f814b7dfd75a61ca7c978b59c52d0440170af6` |
| r1b15 | 15 passed in 0.65s；exit0 | `8f868781acf57bce30f32aac2e3630ad8fa07a57b1fce17abc3295984f395890` |
| legacy10 | 10 passed in 0.24s；exit0 | `f22c35c571b8358d9f382f3b6a05d756290cdbed885aafc8f9b9b6470789c803` |
| focused-probe | **2 failed in 2.93s；exit1**，真实行为 RED | `00607a5f39e374428a99390618afad044cb77c5ec18f74fbe34a4aac0ff71b3b` |

集合有重叠，不相加为唯一节点计数；history46 collect 清单 SHA-256 为 `f124e29577f83e1fbcef81b216858e9a31c045c40bc2e804d53a60a83c1f5dad`。QA 报告 focused 执行前后八项 hash 相同，未改仓库文件；主代理读取输出确认以下两个 P1：

1. **input helper stderr 泄漏**：临时 fake uv 只拦截该 helper，写 `INJECTED_INPUT_HELPER_STDERR` 并 exit7。runner 实际 stderr 为该 marker 加固定 `SECURITY_COVERAGE_RUNNER_CONFIGURATION_INVALID`，不是精确固定诊断。root 不存在，runner exit2。最小修复为 input helper 调用上的正确 stderr 重定向，而非删除固定诊断断言。
2. **mkdir EACCES 错误归类**：在临时 fixture 中将 artifact parent 设为0500，真实 mkdir 失败；实际 stderr 为 `SECURITY_COVERAGE_RUNNER_INPUT_INVALID`，而输入形状有效、失败属于配置/执行边界，应为 CONFIG。fixture 恢复临时 parent 权限；不触碰真实仓库权限。ENOSPC 仍需实现阶段受控注入，不把 EACCES 一例扩写成所有 OSError 已动态验证。

前一 `independent-probe-retry0` 为6通过/1失败，其中6项补证了 scope/facts、单次 cov 读取、分项distribution失败隔离、同值版本、局部policy/Gate shape、失败并集和 pathname 消失等组合断言；它不是第36.21节完整永久回归矩阵。该 stdout 内 JUnit 名与后保存的 retry0 文件名不同，历史原文保留；以正式 focused-probe 的新命名、exit文件和hash作为两P1引用，不复制旧结果伪装新运行。

当前结论是 **R2 QA 未通过，须修复**。两个产品 RED 和第36.21节长期测试缺口同时交回实现；独立临时 probe 的通过不能替代仓库内持久回归用例。QA 此时正在收口证据索引，明确释放执行锁前实现不得写入或启动测试；释放后按原15节点补测试、最小产品修复、新hash复验。R3仅保留草案，不进入真实双lane。

QA 随后完成并明确释放执行锁。主代理回读最终 `QA-SUMMARY.md`，现场 SHA-256 为 `5a454825363b7a5b44ac0769dc3e4795ef23a53979992169c73cbc2273cd97a1`；确认 `final-frozen.sha256` 与 `history46-before.sha256` 字节相同，重新检查无 pytest/runner。`final-evidence.sha256` 生成早于 QA 索引末次追加，其中索引自身旧 hash 不再当前；以本段实测最终 hash 为准，raw focused/退出码/冻结列表不受此命名问题影响。

正式补充勘误：`independent-probe-retry0` 外层 zsh 未成功记录 pytest 实际退出码，故六项通过仅为 stdout 补充观察，不列正式验收执行；保留 retry0 原文。正式 focused-probe 有单独真实exit1和JUnit，两项产品RED成立。

**所有权交接已完成**：`b3e_s_impl` 重新获得唯一代码、测试、harness 写入权与 pytest/runner 执行权，先永久测试 RED → 两项最小runner修复 GREEN并及时报告，再补其余oracle；ENOSPC只做受控异常注入，禁止填满磁盘。QA/架构停止执行和写入，主代理仅只读审查与docs。本段是修复开工，不是两个P1已关闭；完成后必须新八项hash、精确selector、原始证据和同hash独立QA。

### 36.24 Runner 两项 P1 的永久 RED/GREEN（实现侧局部结果）

主代理续接时确认实现角色仍在运行、持唯一写入/测试执行权，随后读取其新证据：永久反例已合入现有 `test_s18_b3f_r2_existing_root_rejects_before_uv_resolution`，仍为15节点。harness 以完整 argv 精确识别 input helper；该节点一次收集 stderr 泄漏、EEXIST、EACCES、ENOSPC 四类结果，再统一比较，避免第一条失败遮蔽后续执行。

| 阶段 | 证据目录与结果 | JUnit SHA-256 |
| --- | --- | --- |
| 首次无效入口 | `/private/tmp/ai-auto-lrc-b3f-r2-p1-red.aZvR1I`，实现报告exit4 import failure | 不计为行为RED，保留原始尝试 |
| 正式永久RED | `/private/tmp/ai-auto-lrc-b3f-r2-p1-red-final.CXz0YH`，`minimal-red`，1 failed in 3.49s、exit1 | `2308cd8eaaa45cb85d1816ea98fdb3fd5c3c0abe6b0b65bea31d172ef9cf8ae8` |
| 最小GREEN | `/private/tmp/ai-auto-lrc-b3f-r2-p1-green.8BgkXx`，`minimal-green`，1 passed in 3.64s、exit0 | `2718adb25927c57d1c9515d2984769d0792e248d401caa6bba567ed889a4f061` |

主代理回读正式RED，确认 stdout 同时列出 secret marker 泄漏、EACCES/ENOSPC误报INPUT，而 EEXIST 没有 mismatch；回读GREEN与exit0并重算上述JUnit hash一致。这是行为RED→GREEN，不是用import error或文件名代签。

本次最小产品修复仅为 input helper 调用加 `2>/dev/null`，mkdir 异常拆为 FileExistsError→INPUT 与其他 OSError→helper exit1→外层CONFIG。新永久测试中的 errno 注入只替换临时 helper 的 mkdir 语句，不修改canonical runtime、不填盘，root均未创建；原existing file/directory/dangling-link不变断言保留。

主代理本次回读三项工作快照：runner `080ed84702dcabd438b34d443c8e37291f32d6d1c02bbe34f91c407e1f9170fc`、harness `ccac1ffc47b6c67fdb14338365265a544c3781bece65631ff528dada85bffea2`、R2 test `f8595e74c747265e1c4514684397ef4c70ddfc6e96b8e9b748166f38ff68f71d`。它们是进行中读取值，不是最终八文件冻结；实现仍在补其他oracle。实现另报告bash-n/相关py_compile/diff-check为0，未将Ruff format改写为通过。

**边界**：两P1只取得实现侧永久局部GREEN，尚未同hash独立QA关闭。主代理另要求检查 input helper 前半 parent.resolve/lstat 遇执行OSError时是否仍一律归INPUT；该疑点尚未动态确认，不把仅修mkdir夸大为所有helper故障分类闭合。第36.21节其余动态oracle继续实施，R2/S18/Release仍未验收，不进入R3。

### 36.25 Input validation 分类回归与文件级并行补强

第36.24节前半 validation 疑点已取得永久动态反例：在原existing-root节点加入 ENOENT/ENOTDIR/EACCES/EIO，临时helper只注入对应异常，不改canonical目录。正式RED仅EACCES/EIO误归INPUT，ENOENT/ENOTDIR正确；runner最小分流为确定missing/not-directory及形状异常→INPUT，其他执行OSError→helper非零→CONFIG。

| 阶段 | 原始目录与结果 | JUnit SHA-256 |
| --- | --- | --- |
| validation RED | `/private/tmp/ai-auto-lrc-b3f-r2-input-validation-red.RFtaBD`，1 failed in 6.58s、exit1 | `8a010cc5c7ddb9ad9e33002612453527815850850d81ded27f135aa079e06f06` |
| validation GREEN | `/private/tmp/ai-auto-lrc-b3f-r2-input-validation-green.0QL8WD`，1 passed in 6.40s、exit0 | `3c5dde31425a4d982a57f7d6bcaa4826b606e8a25c8cd7e4d857d89bc6424bd9` |

主代理已回读两轮stdout并重算JUnit hash一致。它们与前一最小P1集合重叠，不相加为唯一覆盖数量；均为实现侧局部证据，仍需最终快照独立QA。

为并行完成第36.21节而不产生文件冲突，实现角色明确确认 artifact/schema 三组尚未开始编辑，并移交**仅新文件** `tests/contract/security_runtime_r2_artifact_oracles.py` 给 `p1_inventory_design`；主代理确认该路径不存在后正式派发。该角色仅写普通assert helpers，不新增test节点、不运行pytest/runner/import probe、不改其他文件；独立QA继续不参与写代码。

约定API为 `assert_manifest_cross_bindings(tmp_path)`、`assert_non_identity_artifact_versions(tmp_path)`、`assert_policy_and_gate_exact_schema(tmp_path)`。它们负责完整verify的manifest/raw/semantic/environment漂移、policy/env/command/manifest同值float与bool、nested unknown/missing/type/duplicate、真实Gate exact schema。实现保留R2 test本体与其余全部文件写入权、唯一测试执行锁，负责接线；helper完成后须停写并移交实现，再验证。原identity2反例由实现留在本体中处理。

**快照范围补充**：新增helper一旦接线，最终独立QA必须记录原八文件加该helper的九项hash，不能遗漏新断言依赖；现有八项hash记录仍保留历史含义。不得因并行写辅助文件允许并行pytest。

主代理另从consumer源码发现single-pass潜在缺口：`_runtime_distribution_version_fact` 在读取cov required bytes后若lock分项失败，会返回None并丢掉captured entries，plugin分支可能再次读取同endpoint。第36.17节要求“已捕获则复用”不只限整体valid场景。已交实现添加晚期lock失败+read-count反例：cov读取应一次、失败distribution不得产生成功version fact、plugin仍独立校验。此时尚待该反例动态RED，不能提前宣称修复；应分离已安全捕获字节与整项验证成功事实，而非借cache保存来掩盖失败。

### 36.26 Single-pass 分支修复与 artifact helper 复审

晚期pytest-cov lock失败的single-pass缺口已动态复现。实现在原failure-classes节点添加计数：只修改lock分项、重绑semantic，必须RUNTIME失败且不得产生pytest-cov成功version fact，同时cov endpoint只读一次。

| 阶段 | 原始目录与结果 | JUnit SHA-256 |
| --- | --- | --- |
| late-lock RED | `/private/tmp/ai-auto-lrc-b3f-r2-single-pass-red.HJ15ch`，1 failed in 0.11s、exit1；cov_reads实际2、期望1 | `7af0ed89a9db13362f4b60d7e23b010cea6f658b7613bf6605b2e0d1b9e79992` |
| late-lock GREEN | `/private/tmp/ai-auto-lrc-b3f-r2-single-pass-green.NMzgHN`，1 passed in 0.69s、exit0 | `f92cb26f12b7ee6e1c6f03502de6e7243a550fdcacbc6c46fb766183e09b8597` |

主代理已读原始stdout/exit并重算JUnit hash。第一版修复把capture sink传入distribution helper，使entry验证成功后的bytes即使后续lock失败也保留供plugin复用；成功version/summary facts仍只在整项成功时建立。这只关闭late-lock分支的实现侧反例。

主代理随后回读发现capture sink赋值仍在entry自身bytes/size/hash/RECORD一致性判断后：若stable read成功但sidecar entry字段错误，仍会先抛错并丢弃bytes。已要求同节点补entry-binding-failure反例，cache应保留安全读取事实而非依赖sidecar自述通过；plugin独立验证仍应使用该次bytes，不能让cache把失败变成成功version事实。该相邻分支此checkpoint仍待动态验证，不用late-lock GREEN代签全部single-pass边界。

架构角色交付artifact/schema helper首版，主代理完整回读并核对 `4ce94c991becca4531db26f94ecc0a7b9eb1cab4d0311d56eb5263765b57172f`。其中manifest四个full-verify漂移、non-identity版本矩阵、Gate14顶层及nested exact结构已写入；架构只做AST/Ruff，未执行或import helper，故尚无动态GREEN。

复审发现首版policy仅覆盖runtime.python_flags层的unknown/missing/type/duplicate与schema3.0，未覆盖第36.21节接受的其他层。主代理已通知实现暂停接线/修改helper，并明确仅将此文件写入权返还架构角色，补top/thresholds/limits/scripts/runners/runtime/required_entries/required_dependencies层级及runtime固定集合反例。不要把本来合法可配置的threshold值误判非法；duplicate必须原始TOML直接进入真实parser。架构仍不得pytest/runner，完成后停写移交实现再运行，QA保持独立。

此时实现继续独占其余文件与测试执行权，补single-pass、Prepared及runtime oracle；helper仍处于独立文件修订中。最终九项hash/精确15节点与受影响回归、独立QA尚未完成；R2仍未验收，R3草案不执行。

### 36.27 Entry-failure single-pass、strict JSON 与 helper 第二轮交接

实现已在原failure-classes节点加入entry自身字段错误的读取计数，正式RED显示cov_reads=2；最小修复把cache赋值前移至bounded stable read成功后、sidecar语义比较之前。成功distribution version/summary仍在全部分项校验成功后才建立；entry或lock错误仍RUNTIME，plugin只复用安全capture字节继续独立验证。主代理已回读实现和以下原始输出并重算JUnit hash：

| 阶段 | 原始目录与结果 | JUnit SHA-256 |
| --- | --- | --- |
| entry-failure RED | `/private/tmp/ai-auto-lrc-b3f-r2-single-pass-entry-red.eYh1T1`，1 failed in 0.11s，实际read2/期望1 | `4e0b8b41c795aad4f7528aafd2a43dfb00728fbdc089f957e36d8939ca8992ff` |
| entry-failure GREEN | `/private/tmp/ai-auto-lrc-b3f-r2-single-pass-entry-green.84H88u`，1 passed in 0.67s | `99271e1002022dfdecedddacc491e1b1d6d2fa8ad2db04559b1126ac3e01e785` |
| facts/failure matrix probe | `/private/tmp/ai-auto-lrc-b3f-r2-failure-matrix-probe.wNDvnM`，1 passed in 1.54s | `def99454cdc8483266adaea566a1e77ba15067d778715d5786151be0a5112ce1` |
| strict JSON RED | `/private/tmp/ai-auto-lrc-b3f-r2-strict-json-red.NO12Sl`，1 failed in 0.09s；NaN/Infinity/-Infinity三种原始token均被接受 | `08efc48d376c1c06b1c3fdb9cfa9d4c41ec5359b2184b18b43dc27e3eebf9a5f` |
| strict JSON GREEN | `/private/tmp/ai-auto-lrc-b3f-r2-strict-json-green.ty2aHV`，1 passed in 0.03s | `5aa5f356cc2da3a2f073805cf91845e2e3585bbef6093e4b36bdd597b1c93abd` |

实现报告上述RED实际exit1、GREEN实际exit0；这些都是原节点内多反例，不按多目录累计节点数。strict JSON修复是在consumer `_strict_json` 中加入rejecting `parse_constant`，不改公共artifact版本，不因writer先拒绝常量而省略consumer自己的边界。当前正常read-count、scope保留分项facts、早coverage失败不遮蔽后续有效distribution、full failure union已写入永久节点；仍须同最终快照整体回归。

主代理复审full矩阵发现PLUGIN+TOOLCHAIN反例只改uv_after，可能仅靠独立的before!=after检查通过，无法捕捉原summary状态门控回归。已要求使用before=after=同一错误合法SHA、与identity/live矛盾且plugin错误的反例；CONFIG+合法command uv矛盾已保留option索引并只改后半无关flag。该补强不新增产品范围，而是把第36.13至36.14节原始反例落到准确oracle。

artifact helper第二轮已由架构停写交付；主代理回读新增TOML/JSON raw mutation与原Gate结构，并确认SHA-256 `a61bae3108a86110f797155e2a3b9883cbe16695984dbe26e4205b6fb9e81046`。新增policy top/thresholds/limits/scripts/runners/runtime/required_entries/required_dependencies的代表性unknown/missing/type/raw-duplicate，runtime固定集合/顺序错误；non-identity三个JSON文档新增原始duplicate-key字节经完整verify，不先解析丢弃重复键。未误冻结其他合法threshold数值。

**文件交接已明确完成**：helper唯一写入权正式交回 `b3e_s_impl`，可接线三API到原节点并运行；架构停止写入/测试，QA仍独立。架构仅AST/Ruff静态通过，未import或动态运行helper，故此hash是交付快照，不是GREEN证明。若实现后续修正helper，必须记录新hash，最终九文件完整冻结后再交独立QA。

本checkpoint剩余工作：helper动态接线/回归、真实Prepared与local-events捕获后tripwire→builder/guard发布、read/null/profile和nested cap等第36.21节其余oracle、整体显式选择集与静态门、停写新hash独立QA。整体R2仍NOT ACCEPTED，不能仅凭多个局部GREEN进入R3或晋级inventory。

### 36.28 用户要求本地保存：恢复索引与执行交接清单

本节将当前方案、讨论结论与未完成工作集中为恢复入口，避免仅凭聊天摘要续接。第36.1至36.8节是R2合同，第36.13至36.17节保存关键裁决，第36.21节是长期oracle补强清单，第36.23节是首轮独立QA未接受的事实，第36.24至36.27节是后续实现侧局部证据；各节历史结果不覆盖，也不自动适用于当前改动中的代码。Teams讨论见 [第22次讨论记录](./team-sessions/team-session-2026-09-07-22.md)。

#### 36.28.1 保存时状态与责任

主代理本次现场确认工作区仍含大量modified/deleted/untracked，docs本身未跟踪；没有清理或覆盖这些既有改动。Teams状态核实为：`b3e_s_impl`仍运行并独占产品/测试写入与pytest/runner执行权；`b3e_s_qa`已结束首轮QA并释放执行锁；`p1_inventory_design`已交回artifact helper且停止写入。主代理只维护文档，不并发测试。恢复时重新查询角色和锁，不把本节当永久锁状态。

保存期间实现角色新增回报如下，**本次主代理未复核这些新增原始输出，不列为独立验收**：artifact helper三个API已接入原有三个节点，首次fixture失败后retry为3 passed；read/path-disappear/null/full Gate与真实4MiB合法identity边界已补；真实Prepared capture → local events → reader tripwire → builder → guard真实writer的连续probe正在编写。identity `2.0`/`True`反例、Prepared执行、完整选择集、静态门及九文件冻结仍待完成。已回读的较早局部证据以第36.24至36.27节为准，不用新增口头回报替代原始证据核验。

#### 36.28.2 下一轮逐项收口，不从头重做

| 顺序 | 待完成动作 | 交付与接受条件 |
| --- | --- | --- |
| 1 | 沿用现有实现角色核对第36.21节每组oracle | 给出对应现有nodeid、反例输入、精确期望和原始结果；helper三API接线需动态验证，保留首次fixture失败；不靠源码字符串或节点数量代签 |
| 2 | 复核独立失败并集 | PLUGIN错误同时令uv before=after=同一错误合法SHA，且与identity/live矛盾，仍精确PLUGIN+TOOLCHAIN；不能只用before!=after触发另一条检查 |
| 3 | 完成真实Prepared连续链 | 真实prepare/local-events捕获后设置reader tripwire，再真实builder/guard/exclusive writer；只拦截pytest.main，验证实际bytes、identity2、0600及read-count，不用fake events代签单次加载 |
| 4 | 补齐read/schema/writer/profile边界 | identity同值float/bool；完整raw的真实SHA与未读raw的null；pathname消失；nested cap；nested duplicate与非JSON常量；FULL/NO_EVENTS与缺required的EARLY；真实consumer失败和stub控制流证据分开 |
| 5 | 实现侧fresh回归与静态检查 | exact15及明确列出的历史受影响selectors；history46/R1a10/R1b15/legacy10按实际修改核定，不复用旧GREEN、不累计重叠节点。保存selector、stdout/stderr/JUnit、真实exit；Ruff check与format check分别报告 |
| 6 | 停写停测并交回独立QA | 九文件新hash、前后快照、证据索引及明确执行锁交接齐全；任何字节变化使旧冻结失效。QA使用新目录独立复验，未接受则回实现，不能直接进入R3 |
| 7 | QA释放锁后验证文档并收口入口 | 串行执行文档治理两文件选择集，记录fresh结果；只有所有门闭合，才更新四个上位入口为最终验收引用 |

九文件冻结清单如下，**当前未冻结，不在此给出可能随实现漂移的最终hash**：

```text
scripts/security_pytest_bootstrap.py
scripts/verify_security_coverage.py
scripts/run_security_coverage.sh
packaging/security-coverage-policy.toml
tests/contract/security_runtime_r2_runner_harness.py
tests/contract/security_runtime_r2_artifact_oracles.py
tests/contract/test_security_runtime_identity_r2.py
tests/contract/test_security_coverage_gate.py
tests/contract/test_security_runtime_identity_r1b.py
```

后续依赖保持：R2独立验收 → 第36.22节R3 proposed设计的前置裁决与真实integration → R4 writer parity/final-schema replay → B3f-L67/B3c/B3d/B3e replay → B4/freeze ledger/各平台qualification。R3无现成已确认节点；flag提前失败profile与删除offline/no-sync前的network-denied、disposable runtime/cache隔离须先裁决，不能预写为已通过。

#### 36.28.3 保存和验证边界

本次只更新现有主方案和Teams讨论记录，并回读确认内容。第36.19.6节的42 passed只适用于当时文档，不覆盖之后新增章节；当前测试锁在实现侧，主代理没有重跑文档pytest，也不宣称新文档治理门通过。待执行命令仍为：

```sh
uv run --offline --frozen --no-sync python -m pytest tests/contract/test_spec_inventory.py tests/contract/test_document_links.py -q -p no:cacheprovider
```

该命令需等显式取得执行锁再运行。当前仅允许显式低成本合同、collect/static、临时runner+fake uv；fake uv必须拦截bootstrap，stub Gate必须标明`harness_stub`/`not_verification_evidence`。禁止整个`test_security_coverage_gate.py`、真实安全双lane、final67及平台矩阵；ENOSPC仅受控异常注入。保留根目录`=`和全部既有改动、RED/retry，不改真实`.venv`、系统uv、canonical uv.lock或目录权限。

临时目录中的raw证据仍是临时文件：本地Markdown保存了方案、裁决、路径和既有hash，不代表raw日志已经持久归档或可以离线恢复；临时文件丢失时不能仅凭摘要重新认证。未执行commit/push、CI、上传同步、签名发布、archive/restore、W1b-5c/5d/5e或破坏性清理。**本次文档保存完成不等于R2完成；S18、W1b-5b、Release继续No-go，inventory不晋级。**

### 36.29 新增局部证据回读与 Prepared fixture 安全修正

整体目标继续后，主代理已核实实现角色仍运行，未重新派生实现任务；QA仅获得read/null/cap/writer/profile的只读覆盖复审，不持执行锁、不写测试。以下新增原始stdout、实际exit和JUnit hash已由主代理读取、重算，更新第36.28节“仅实现回报”的证据状态，**仍不构成最终快照独立QA**：

| 集合 | 证据目录、结果与边界 | JUnit SHA-256 |
| --- | --- | --- |
| artifact首次 | `/private/tmp/ai-auto-lrc-b3f-r2-artifact-oracles-first.VdN8JQ`；3 failed in 0.27s、exit1；helper未建父目录，属于fixture失败，不是产品RED | `7ad87713eebbb6de2f842fd2d7fd11862beeef852317157029957a2ed534718a` |
| artifact retry | `/private/tmp/ai-auto-lrc-b3f-r2-artifact-oracles-retry.JQXag1`；3 passed in 1.69s、exit0 | `06642474c6d0f510f29d1dbba52ea5fbcc980545307d030c06ad36a87e50ece9` |
| read/null | `/private/tmp/ai-auto-lrc-b3f-r2-read-null-probe.SAexVi`；1 passed in 0.20s、exit0 | `c7682870f52f151ed9beec94e4fded74e0722d1b3dd32fbbaaa65ac8bfe69fdb` |
| identity容量边界 | `/private/tmp/ai-auto-lrc-b3f-r2-boundary-probe.i4LNi0`；1 passed in 0.11s、exit0 | `c74883dc99089e9e76abe53bf70288d54bbb3c9b66698a3ff9bffe04dde5b885` |
| Prepared首次 | `/private/tmp/ai-auto-lrc-b3f-r2-prepared-publication-first.p0Qzi3`；1 failed in 0.25s、exit1；pytest.main拦截遗漏，见下文 | `d86a4b603184d6e21d1f886c8782f2c90f0f6f21a9f9d02ad403ffef2a2ea1f1` |
| Prepared retry | `/private/tmp/ai-auto-lrc-b3f-r2-prepared-publication-retry.UQ6fkw`；1 passed in 0.22s、exit0 | `cd8e739bc3397046054d55818060cb66d3d8657b3cb2366ba772f47ae632cb05` |

主代理已回读artifact helper真实full-verify mutation、原始TOML/JSON duplicate与完整Gate shape断言，并确认三个API已接入原节点；首败修复为helper建立专用父目录。PLUGIN+TOOLCHAIN反例现已把uv before/after均改为同一错误合法SHA，避免只靠before!=after的独立检查通过；最终选择集仍须fresh覆盖此版本。

read/null新增实际mode变更、同bytes换inode、EOF后pathname消失、真空文件与missing/oversize区别，以及mode错误进入完整Gate后的raw绑定。容量节点将合法synthetic identity的cache_tag扩展到完整序列化4MiB，并重绑semantic，单独证明bounded read和consumer语义通过；这不是实际host代表容量或所有nested cap均已证明。nested cap、unreadable与独立invalid-summary oracle仍交QA核对，不从该单项GREEN扩大结论。

Prepared新probe使用隔离subprocess，调用原始prepare、local events loader、builder、guard及exclusive writer；成功加载events后把capture/read设为tripwire，仅pytest.main由fake触发guard。retry断言六项调用计数、events单读、真实v2规范字节、0600及single-link。uv参数仍是合成observation，因此只证明Prepared连续发布，不是真实uv双lane或consumer全面接受该输出。

**首次Prepared失败必须保留准确安全边界**：实现解释为漏装fake pytest.main，实际进入pytest并在插件重复注册处失败；主代理读取的外层stdout保留该失败，但未据此外推为安全测试执行通过。实现已在tracked_local中补拦截取得retry；主代理进一步要求在original_prepare返回后立即装fake，fake要求local-events已完成，再把reader tripwire保留在真实local读取之后，以防未来调用顺序回归误入真实pytest。另要求subprocess显式timeout=30。上述安全补强须新结果覆盖，旧retry不代签修改后快照；首次是否在collection前退出须在实现证据索引明确说明。

本轮仍由实现独占测试执行；QA只读复审结果、其余writer/profile补强、fresh回归/静态门与九文件冻结独立QA均未收口。文档治理测试也未并发执行，第36.28节后续顺序与No-go状态不变。

### 36.30 QA 只读补强清单与新结果适用边界

QA本次只读复审确认三组仍需补强的行为oracle，主代理已接受并交唯一实现角色；不是新的范围扩张，也不是另一次执行QA失败。审阅时测试文件hash为`f5b646d8797a6d889e06ccf9dfff532f03df25a21b2ce5d07900892430009850`，实现后续仍修改，因此该hash仅标识过程审阅，不能用于冻结验收。

1. **invalid summary独立期望**：测试不能调用产品`_runtime_invalid_summary`作为expected，否则helper与报告一起出错可同错同绿。改用测试内完整literal字段集合；missing/oversize/unreadable须经完整Gate证明top+nested raw均null，mode错误或真正空文件须保留实际raw SHA。不可读用仅针对临时identity的EACCES注入，不更改真实权限。主代理已在源码看到独立expected及三组full Gate断言，但尚无这些新增项的fresh执行证据。
2. **四项nested cap**：metadata、RECORD、required entry、pyvenv.cfg分别证明exact-limit与+1，分开检查有界读取和合法语义。总identity 4MiB测试不能代签这些分项上限。QA初评将大cache_tag称为合同冲突，主代理已校准：当前合同允许非空str，合法schema+重绑semantic的synthetic正例可以证明当前consumer容量边界，不因此新增cache_tag长度限制；仅不得宣传为实际host代表容量或全部nested限制已验证。
3. **writer严格候选与真实consumer profile**：保持schema2、64hex semantic和三个版本字段均可提取，只在深层放NaN/Infinity/-Infinity或duplicate；environment必须raw SHA真实、semantic与tools全null，manifest semantic=null。原semantic字段自身为NaN的测试不能捕捉宽松decoder回归。NO_EVENTS与损坏identity的stub只证控制流，仍须把相应临时runner产物交真实consumer并取得明确失败；fake uv继续无条件拦截bootstrap，不启动真实安全测试。

架构角色仅只读设计第3项最小fixture接线，重点是同一临时repo/source/policy/uv/path绑定的无无关失败baseline与变体，不获得文件写入或测试执行权。实现继续唯一执行，之后仍按第36.28节九文件冻结并交独立QA，不因本次只读审阅直接验收。

新增阶段结果：`/private/tmp/ai-auto-lrc-b3f-r2-remaining-focused.waub9S`，主代理已回读stdout/exit/JUnit并重算SHA-256 `b4ffc05432e854bd016daa75083faf55be9e46a3827875b17a4228b2e2891770`；**4 passed in 18.49s、exit0**，覆盖Prepared、artifact versions、read-mode、profiles四个原节点。实现澄清该执行包含Prepared timeout=30，但**不包含**稍后拦截前移/local-ready断言、独立literal expected、full Gate missing/oversize/unreadable及writer tools精确断言；故不能用此GREEN代签新增补强。主代理已回读拦截前移后的源码，动态结果仍待fresh执行。

以上新增文档只做回读；`git diff --check`退出码0不覆盖untracked docs，也不代替文档治理pytest。整体R2仍NOT ACCEPTED，保持第36.28节后续依赖、唯一执行锁和全部No-go边界。

#### 36.30.1 只读 QA 收口与 profile 接线裁决

QA最终报告绑定另一个过程读取快照`65f0e41302560b5f453c2a7e7bb34bbb2fa74d811cb7ed185e820b02f1f1edcd`；其后实现已加入部分literal/null补强，故报告不能当作当前源码未修复的直接证明。QA已结束只读任务、未取得执行锁；架构也已结束只读设计，两者均未写入或执行测试。

在第36.30节三组之外的准确补充（已交实现，不另增功能范围）：

- 深层strict writer用**同一模板TOKEN=0**先证明semantic与三个versions可提取，再改非法常量/duplicate，排除因额外`probe`字段或其他fixture错误导致的一律null假绿；每个失败变体同时断言tools全null。
- valid copied-runner逐target明确断言到达verifier（stub须有标记）；只看environment存在和exit0不能防止verifier调用被删除。
- 真实Prepared发布probe记录或断言实际raw size不超过4MiB，作为当前host代表容量观察；仍不代签其他平台。
- environment writer自身的identity absent/unreadable/oversize都需raw/semantic/tools全null，不能用verifier独立reader测试替代。absent后按required-raw合同EARLY；其余按文件存在性和既有profile走，不能因候选提取失败冒充成功。EACCES只受控注入临时fixture。
- 已存在的`tests/contract/test_security_coverage_gate.py::test_s18_gate_rejects_missing_pytest_events_with_stable_code`能证明一般consumer的精确`PYTEST_EVENTS_INVALID`，但未在旧显式选择集中；可纳入fresh回归，不必重复造一般consumer测试。其他选中节点已覆盖一般malformed identity consumer与full bundle PASS。它们各自的通过仍不能拼成“同一runner输出进入真实consumer”的连续证据。

为完成后一连续性，采用架构提出的最小方案，不重构harness、不增加公共schema：

1. 复用现有`RunnerHarness`。supplier以host runner、实际run_id/target/int attempt在独立staging目录调用`gate_contract._make_bundle`，**只取coverage/JUnit/events原始字节**；不能搬入该fixture的environment/command/run-manifest。
2. identity由`gate_contract._plugin_identity_document(..., repository_root=harness.repository_root)`生成，绑定临时repo local plugin；只为timestamp和uv.path/version/sha使用现有`{{RUNTIME_TIMESTAMP}}`/`{{UV_*}}`占位符，正常变体启用`rebind_identity_semantic=True`。run_id/target/attempt直接使用supplier实参，attempt保持整数。
3. environment、command和manifest全部由copied runner生成，不手工rebase路径/补hash。baseline显式`verifier_mode="real"`，两target均`gate_kind="real"`、failures为空且passed=true、runner exit0；baseline若出现无关配置失败，先修fixture而非放宽期望。
4. NO_EVENTS仅把events置None，required raw其余保持baseline，预期两target精确`["PYTEST_EVENTS_INVALID"]`、runner exit1。malformed仅覆盖identity原始bytes，**关闭semantic rebind**，预期两target精确`["RUNTIME_IDENTITY_INVALID"]`、runner exit1。否则fake bootstrap可能在JSON解析时exit98并改变为EARLY，不能当成consumer拒绝证据。
5. 调用记录必须证明bootstrap始终`bootstrap-stub`、只有copied verifier为`verifier-real`、无`blocked-program`；不得回落真实uv或执行真实pytest/security bootstrap。此为合成raw+真实writer/consumer连续合同，仍不是R3真实安全双lane。

主代理已回读上述fixture的`repository_root`参数与fake-uv占位符/semantic重绑/真实verifier分支，设计可接线；**尚未有baseline或变体动态结果，不提前称通过**。实现保留所有文件与唯一执行权，剩余nested cap、writer/null/profile和最终选择集继续由其执行，完成后九文件冻结再交独立QA。

### 36.31 Nested cap、null、真实 consumer profile 与 Prepared fresh 结果

本轮延续原实现角色与唯一测试执行锁；主代理只读审查并核对证据，架构只读复审四nested cap后已结束、没有运行测试或改文件。以下是实现侧新增执行，主代理已读取stdout/真实exit并重算JUnit hash；它们不替代最终九文件冻结后的独立QA。

| 显式节点 | 新证据目录与结果 | JUnit SHA-256 |
| --- | --- | --- |
| identity_limit | `/private/tmp/ai-auto-lrc-b3f-r2-nested-caps-final-retry.3yWLMM`；1 passed in 0.17s、exit0 | `da813b4cd83c259ad0ee979608a9e7d42ee2c368c03a64aa661d101fcd42e9aa` |
| identity_read_mode | `/private/tmp/ai-auto-lrc-b3f-r2-read-null-final.MQ1bgA`；1 passed in 0.31s、exit0 | `75c29f50fa49399d333e896cbd228934eb88bcb411e73aa43c3e713a7210a92b` |
| artifact_profiles | `/private/tmp/ai-auto-lrc-b3f-r2-profile-final.KaQl4T`；1 passed in 40.98s、exit0 | `ec267cb5d658fc558408cdd5cd96a83bc26bd554e690580fca2ac4a05449ffad` |
| prepared_runtime | `/private/tmp/ai-auto-lrc-b3f-r2-prepared-final.MjzCN6`；1 passed in 0.19s、exit0 | `6dae6eec7c206d1c3feef4a3122f16efe36b6be113119dcb9be23057922213ae` |

节点名称在表中仅缩写，完整名称由各JUnit与第36.6节固定15节点恢复，不能把表内简写当pytest selector。四nested子例仍是一个节点，不按反例数增加测试节点计数。

**nested cap证明**：METADATA以短合法header、RECORD以不超过200字节的唯一非required行、required entry以已重绑RECORD的coverage entry、pyvenv以合法额外键达到各自精确上限；live bytes、sidecar bytes/size/hash、必要normalized RECORD和semantic全部重绑。四组exact均通过、+1均精确RUNTIME失败；entry serialized identity低于4MiB，不由外层限制代签。早期`nested-caps-first.ViqV1G`、`nested-caps-retry.AOMLQy`、`nested-caps-label.P1wnQi`失败保留；主代理回读label确认失败停在RECORD exact，旧单超长字段已被短行替代，未放宽产品限制。

另一次fresh启动`/private/tmp/ai-auto-lrc-b3f-r2-nested-caps-final.AM10mI`使用pytest console入口导致`ModuleNotFoundError: scripts`，没有进入目标测试；JUnit SHA为`71293e4164c7b3b9a5d5c92e68edc3e0112911e2fd2e18b587d4744bd569acb1`。实现报告包装器误用zsh只读`status`导致退出码记录不完整，不能把它算产品RED。随后恢复既有`uv run --offline --frozen --no-sync python -m pytest`并单独记录真实exit，才取得上表GREEN；不通过安装依赖或修改PYTHONPATH掩盖入口问题。

**null与writer证明**：独立literal invalid summary和missing/oversize/受控EACCES的完整Gate双层null现已动态通过；已完整读到的mode错误、换inode/pathname消失与真空文件仍保留实际raw SHA。supplier以专用sentinel表示默认生成identity，None明确表示缺失，semantic rebind也同步绑定sentinel。writer新增同形有限TOKEN=0正例、三个非有限数及深层duplicate变体，并断tools全null；absent先生成nullable environment再EARLY，oversize保留既有到达stub的控制流。不可读测试已改为仅在临时environment helper中受控注入EACCES，不再依赖mode000的用户权限行为；它证明writer候选读取失败，不代签manifest读取失败或跨平台真实权限资格化。

**真实consumer连续性证明**：主代理读取profile临时产物的六个Gate v5，baseline capture/retention均passed=true、failures=[]、runtime valid；NO_EVENTS两target均仅`PYTEST_EVENTS_INVALID`且runtime valid；malformed identity两target均仅`RUNTIME_IDENTITY_INVALID`且runtime invalid。三次run的调用日志合计6个bootstrap-stub、6个verifier-real、6个environment-helper和3个version，无blocked-program/invalid-prefix。每run两次调用的精确计数同时由永久测试断言。coverage/JUnit/events raw来自fixture，runner生成environment/command/manifest，真实copied verifier校验；因此只是合成raw的真实writer/consumer合同，**不是R3实际security双lane执行**。

本次六个Gate原始位置在`/private/var/folders/jv/nkvs539n5757cl4j0405cdhh0000gn/T/pytest-of-liu-haixiao/pytest-1056/test_s18_b3f_r2_artifact_profi0/`下的`real-verifier-*`；默认pytest临时目录可能被后续轮次自动清理。主代理已要求实现复制此明确子目录到profile证据根保留（不删除源），并为最终选择集使用各新证据目录下**从未存在过的专用basetemp子路径**，不得复用会被pytest清理的既有证据目录。本checkpoint尚未把复制请求写成已完成，也不视作W1b archive/restore资格化。

Prepared fresh已覆盖fake pytest在真实prepare返回后立即安装、local-ready断言、真实local-events单读后tripwire、真实builder/guard/writer、subprocess timeout和当前host输出raw_size<=4MiB；uv仍为合成observation。实现继续执行failure-class与剩余精确选择集，随后提供九文件新hash、静态原始结果与索引，再交独立QA。旧R2 NOT ACCEPTED尚未解除；文档门仍待取得执行锁后fresh验证，R3及全部No-go边界不变。

#### 36.31.1 补充回归与 profile 原始产物保留确认

实现已将上述明确的pytest-1056 profile子目录只复制到`/private/tmp/ai-auto-lrc-b3f-r2-profile-final.KaQl4T/profile-artifacts`，源未删除；主代理对完整源/目标执行只读`diff -qr`，退出码0、无差异。该副本含三类真实verifier场景及其他stub/nullable场景的raw、Gate和调用日志，可避免后续默认pytest轮换丢失本次证据；仍是临时证据目录内的保留，不是仓库归档、跨机备份或restore资格化。

另两组fresh结果已由主代理回读实际exit/stdout并重算JUnit：

| 集合 | 证据目录与结果 | JUnit SHA-256 |
| --- | --- | --- |
| failure-class原节点 | `/private/tmp/ai-auto-lrc-b3f-r2-failure-matrix-final.ARrEV1`；1 passed in 1.59s、exit0 | `94746ca5ef5e979a0df5dab1dea5c7b08941241e765901c65d39053ecb77ff65` |
| artifact三个原节点 | `/private/tmp/ai-auto-lrc-b3f-r2-artifact-oracles-final.fCAPb0`；3 passed in 1.84s、exit0；使用证据根下新专用basetemp | `3aa24e942b3bdf296ae5ad12c225a1d41b9f39daaccd6641dbb3dfa5a4da2d4f` |

实现开始collect核对和exact15整体回归，仍持唯一执行锁；尚无本轮完整exact15、历史受影响回归或最终九hash独立QA结论，不将表内局部结果累计为整体验收。

#### 36.31.2 Exact15 自然完成与观察超时勘误

本轮collect证据在`/private/tmp/ai-auto-lrc-b3f-r2-collect15-final.euHz6f`，实际收集15项、0.02s；stdout SHA-256为`69b168d591de9af8d1072a31af86b6ffb2868db918ad4ebc2edf5029902e10de`。

完整执行证据在`/private/tmp/ai-auto-lrc-b3f-r2-exact15-final.jU4pqi`，stdout为**15 passed in 63.65s、exit_code.txt=0**，stderr为空；JUnit SHA-256为`18e0872d3bc51f0cf6cf10ce6bc49dfefe83704fec4b5a09ee241ac6e4b60b09`。主代理已读取所有15个testcase名称并与collect逐项核对，XML计数为15 testcase、0 failure、0 error、0 skipped，专用pytest-tmp产物保留在此证据根下。

实现曾根据中间仅13个进度点和暂缺结果文件判断“异常中止”，准备另起attempt。主代理现场读取同目录已完整生成的JUnit、stdout及exit，确认原执行已自然完成，立即要求纠正该过早判断、沿用有效证据而不是因观察超时重跑。**此attempt不记为基础设施无效或产品RED**；不得把“尚未观察到最终文件”当成终止证据。后续长任务保留原session_id并续读到真实终态，不因一次观察窗口超时重启。

这是实现侧本轮exact15整体GREEN，不是旧46项证据复用，也不是独立QA。历史受影响显式回归、静态原始结果、九文件冻结与执行锁交接仍待完成；R2验收和全部上位No-go状态不变。

### 36.32 Lint 后新字节回归与显式节点并集

扩大历史回归前实现修正RUF036，将测试supplier的union类型顺序从`bytes | None | object`调整为`bytes | object | None`。测试文件字节变化，因此第36.31.2节exact15保留为历史，重新执行当前字节；主代理读取当前R2测试SHA-256为`c72b1c3d98aaac450facc083413957833b1e6f1ce70fb9df923f2001ad1a8f56`，不是旧`b6cf1919...`。

Ruff format全文件检查实现报告exit1、7个Python文件would be reformatted；尚不将该回报冒充主代理独立静态执行。沿用本方案既有规则：不为未跟踪文件的全文件格式漂移进行无关机械重排；check/compile/bash语法与format必须分别报告，不能写“所有静态检查全绿”。最终交付仍须提供各项原始输出。

| 集合 | 新证据目录与结果 | JUnit SHA-256 |
| --- | --- | --- |
| post-lint exact15 | `/private/tmp/ai-auto-lrc-b3f-r2-exact15-post-lint-final.P7gVNM`；15 passed in 62.32s、exit0、stderr空 | `9124c6212c700e694c0e1ef8bbedd25cf9247178526220d6f9427c8aa357f13a` |
| affected32 | `/private/tmp/ai-auto-lrc-b3f-r2-affected32-final.fAqxad`；32 passed in 3.65s、exit0、stderr空 | `ee9f7a6c05ed141449f988a8feecb6979bec1299c20c3c53b4d08a2964a59e76` |

主代理已读取上表实际stdout/exit、重算JUnit hash，XML分别15与32个testcase且failure/error/skipped均0；post-lint的15个名称与上轮exact15一致。affected32收集证据在`/private/tmp/ai-auto-lrc-b3f-r2-affected32-collect-final.5wIB81`，stdout SHA-256为`5316fca1abcae6b595c03ec9230a42b3fe4a119c52150e6b704591a898242606`，显式入口见该目录`selectors.txt`。

主代理以收集nodeid作集合比较确认：本轮exact15与affected32交集为空；二者并集没有遗漏首次独立QA的history46任何节点，唯一新增项是`test_security_coverage_gate.py::test_s18_gate_rejects_missing_pytest_events_with_stable_code`。因此本轮准确称**分组fresh验证47个唯一节点，覆盖原history46并增加missing-events**，不声称47或46项在同一pytest进程执行；后续R1a/R1b/legacy与它们可能重叠，不把各组计数直接累加。

实现已确认post-lint exact15同session自然完成并续读了最终状态；未因观察超时重启。此时继续R1a10/R1b15/legacy10的补充显式回归，尚未停写冻结或向QA交执行锁；旧NOT ACCEPTED须由同最终快照独立复验解除，R3和No-go边界保持。

### 36.33 本地持久化 checkpoint：实现交锁，独立 QA 待接手

用户要求将方案写到本地以免后续丢失细节。本节追加当前事实，不删除第36.23节首轮NOT ACCEPTED、各RED/fixture错误/retry或观察超时勘误，不将实现GREEN改写为独立验收。

**所有权**：实现角色 `b3e_s_impl` 已明确停止产品/测试写入和 pytest/runner 执行，并正式释放唯一执行锁给主代理/后续QA。主代理再次只读检查未发现 pytest/runner 匹配进程，核对九文件9/9 OK；这只是当次观察，下一次执行前仍须复核。现有 QA `b3e_s_qa` 与架构 `p1_inventory_design` 的已结束审阅不是最新冻结快照的最终验收。本轮不重新派发产品测试；主代理仅持锁进行文档治理核验，随后释放。

**文档职责与恢复顺序**：本文件拥有执行合同、当前状态及后续门槛；[Teams 22](./team-sessions/team-session-2026-09-07-22.md)保留角色讨论与交接历史；四个上位入口仅指向本节，不复制测试细节。先读36.33–36.34，再读36.28的导航及36.1–36.8冻结合同；36.13–36.17为失败分类/单读等裁决，36.21、36.29–36.31为补强oracle及其证明边界，36.22是尚未执行的R3草案。

#### 36.33.1 已完成的补充回归与静态结果

| 实现侧集合 | 原始证据目录、结果 | JUnit SHA-256 |
| --- | --- | --- |
| R1a10 | `/private/tmp/ai-auto-lrc-b3f-r2-r1a10-final.aIfaPr`；10 passed in 0.15s，exit0 | `3690366ab56cb0de06cfb820cf1e0bd7ad32e94b3401370cdfab85ebed40966c` |
| R1b15 | `/private/tmp/ai-auto-lrc-b3f-r2-r1b15-final.g4I2gV`；15 passed in 0.65s，exit0 | `9b5db13767a05e30a2411a71d42e24b89a23c0f45fa2f20c21f94699d00062c5` |
| legacy10 | `/private/tmp/ai-auto-lrc-b3f-r2-legacy10-final.QrDCmq`；10 passed in 0.24s，exit0 | `9523835ee7fb7dc1263fe37f8e63ef8c57f2c9090bad2fb1f504e8aedf9d0ca2` |

主代理已回读三组stdout/exit并重算JUnit，stderr均空。与第36.32节post-lint exact15和affected32存在跨组重叠，不能直接相加宣称唯一节点数；仅exact15与affected32的并集为47个唯一节点，且是分组执行。

最终静态根为 `/private/tmp/ai-auto-lrc-b3f-r2-static-final.NdMCMw`。主代理回读的是实现侧原始结果，不冒充独立重新执行：AST parse、py_compile、bash-n、Ruff check、git diff check、runner-mode均exit0，runner为0755；**Ruff format check仍exit1，7 files would be reformatted**，完整差异保留，未批量格式化。九文件均untracked，git diff check不单独覆盖这些内容；不能概括为所有静态门绿色。

#### 36.33.2 已保存到仓库的证据索引与冻结清单

- [实现证据索引快照](./evidence/b3f-r2-implementation/EVIDENCE-INDEX.md)：保存15个R2节点与正例/反例、独立oracle、结果、RED/GREEN及无效fixture尝试的映射。原文件SHA-256为 `cc596a0b1ade75c6e4f10f5d761384f6d4eeabd01a3704a20f138c6df7426be6`；它是实现侧历史证据索引，不取代本节当前状态。
- [九文件SHA-256冻结清单](./evidence/b3f-r2-implementation/nine-files.sha256)：从仓库根执行 `shasum -a 256 -c docs/evidence/b3f-r2-implementation/nine-files.sha256`。任一不匹配即停止复用该快照，记录漂移、重新冻结并安排独立QA，不回滚用户改动。
- [affected32精确选择清单](./evidence/b3f-r2-implementation/affected32-selectors.txt)：13个函数级selector经参数展开为32个nodeid；不是32行，也不能执行整个gate测试文件。R2入口为 `tests/contract/test_security_runtime_identity_r2.py` 的15节点，须collect核对后使用。

这些文本已在docs本地保存，不再只依赖会话和临时目录。**原始JUnit/stdout/stderr、profile raw及format diff仍在索引中的临时目录，并未随本次文档保存做完整归档或跨机备份。** 如果原始路径丢失，hash只能标识历史记录，不能恢复原文件或代签fresh验证；相关结论降为历史待复验。不得凭记忆重建一个同名证据目录冒充原始记录。

### 36.34 下一轮可执行交接单与验收门

本节是后续计划，以下QA/R3步骤本轮尚未执行。整体目标未完成，S18、W1b-5b、Release继续No-go，inventory不晋级。

1. **Preflight与所有权**：沿用现有Teams角色，不重复创建实现/QA；确认无其他写入或pytest/runner，九hash匹配，保留所有modified/deleted/untracked（含根目录`=`）。QA明确独占执行锁，实现不写不测；主代理只读核验，避免并发pytest。
2. **独立只读审查**：QA重读最新九文件，不能复用旧快照审阅。逐项核对首轮stderr泄漏与mkdir错误分类P1、strict JSON非有限数/duplicate、独立literal invalid summary、完整Gate双层raw-null、失败类别并集及单读cache。特别验证nested四项cap exact/+1的合法重绑、Prepared真实builder/writer单读与fake安装时机，以及同形writer正例/非法候选和真实copied-consumer profile。
3. **Fresh显式低成本回归**：在全新证据根下使用从未存在过的专用basetemp；collect上述R2文件与affected32清单，核对展开并集47节点，可同进程执行或分组但必须如实说明。再按原索引恢复R1a10/R1b15/legacy10的确切selector并collect核对，不猜测名称；记录重叠。统一使用 `uv run --offline --frozen --no-sync python -m pytest` 入口与 `-q -p no:cacheprovider`，记录完整argv、nodeid、前后hash、stdout/stderr、真实exit、JUnit及SHA。超时只续读原session至终态，不因暂缺结果文件重启。
4. **安全边界**：仅临时复制runner和fake uv；bootstrap必须stub且调用日志证明无真实uv回落，只有明确指定copied verifier可真实执行。stub Gate必须带 `harness_stub` / `not_verification_evidence`，不得算验证证据。EACCES/ENOSPC受控异常注入，不改系统uv、真实`.venv`/uv.lock/权限，不填盘。不得运行整个 `test_security_coverage_gate.py`、真实security双lane、final67或平台矩阵。
5. **QA交付与失败闭环**：QA输出同快照的独立结论、问题级别与证据；零失败不能替代oracle审阅。失败则保留原结果，由实现test-first修复，产生新hash，再独立复验；通过也只解除R2本层门。结束时明确停测交锁，主代理再核对证据并fresh执行文档治理两文件测试，所有门满足后才追加R2验收入口。Ruff format差异仍单列，遵守既有不做无关批量格式化规则。
6. **后续依赖不跳步**：R2独立验收 → R3前置裁决/真实集成 → R4与final-schema replay → B3f-L67/B3c/B3d/B3e证据刷新 → B4/freeze ledger/各平台qualification。R3的flag提前失败profile须先裁决；去掉offline/no-sync前须证明network-denied、disposable runtime与cache隔离，当前不提供虚构R3 selector。

持续禁止commit/push、CI、upload/sync、签名发布、W1b-5c/5d/5e和破坏性清理；本地方案保存不是上述任何动作的授权。

#### 36.34.1 本轮文档治理验证与执行锁释放

上述方案、Teams记录、四个上位导航及三个本地证据文本保存后，主代理运行：

```sh
uv run --offline --frozen --no-sync python -m pytest tests/contract/test_spec_inventory.py tests/contract/test_document_links.py -q -p no:cacheprovider
```

实际结果为 **42 passed in 12.32s，exit0**（exec session 45431自然完成），覆盖规格清单治理与docs内部链接/锚点。本记录在该执行后追加，不能把它当作产品测试、R2独立QA或发布资格。保存的证据索引SHA与原件一致，affected32选择清单与原件diff一致，九文件hash再次9/9 OK；git diff check为0，但不代替untracked文件内容检查。

主代理文档验证已结束，现释放唯一pytest/runner执行锁，无新QA执行被派发；下次仍从36.34第1项重新确认所有权。当前仅完成方案本地持久化，整体重构与资格化目标仍未完成。

### 36.35 当前九文件快照的独立 QA 已派发

整体目标继续执行；前轮方案落盘与42项文档治理属于已完成进展。主代理现场重算本地九文件冻结清单9/9 OK、检查未见pytest/runner，确认实现角色已completed且停写停测。现将唯一pytest/runner执行权交现有 `b3e_s_qa`：先重审当前九文件oracle，再新目录fresh执行exact15+affected32及明确的补充回归，保存前后hash、原始结果与独立结论。第36.34.1节“未派发”只描述前轮状态，本节追加此次交接。

主代理与实现不并发测试；主代理只读审阅和文档更新，架构 `p1_inventory_design` 仅只读核对R3草案、14个flags变体失败阶段及network-denied/disposable runtime/cache隔离前提，不运行probe、不写产品文件、不启动R3。当前仅派发，尚无新的QA结果；不能据此关闭NOT ACCEPTED或升级任何资格。

### 36.36 R3 flags 失败阶段与隔离前置裁决（设计收口，尚未执行）

架构只读审查已返回；主代理回读runner命令数组、bootstrap flags检查、verifier exact argv和既有离线包测试隔离代码后采纳下列设计约束。它细化第36.22节，**不是R2验收或R3执行证据**。

**变异范围**：只改临时repo内runner的bootstrap `command=(...)` 数组（当前294–310行）；preflight/hash/timestamp/environment/manifest/verifier helpers均保持原prefix。变异器须断言唯一匹配，记录原行/新行SHA、token及index、临时runner SHA与mutation receipt，禁止全文件replace。正常root创建之前失败不是这14例预期结果，应先判定fixture/endpoint无效并停止。

| 变体组 | 数量 | 在前置条件成立时的预期profile |
| --- | --- | --- |
| 删除Python `-I`、`-S`、`-B`各一项 | 3 | bootstrap flags检查exit2；无pytest/identity/coverage/JUnit，runner继续写environment/command，再生成各lane的runner-error v2：stage=raw-completeness、reason=REQUIRED_RAW_ARTIFACT_MISSING；无manifest/Gate，overall=1，不是CONFIG Gate |
| 重复Python三flags各一项、Python组三项换序一次 | 4 | 冻结CPython先经argv接受性确认且flags仍true；真实bootstrap/pytest产物完整，Gate精确RUNNER_CONFIGURATION_INVALID；若解释器未到bootstrap，先判fixture前置失败，不改写为Gate通过 |
| 删除 `--frozen` | 1 | 保留offline/no-sync，确认uv接受后产物完整，Gate仅CONFIG |
| 删除 `--offline` | 1 | 必须先现场证明OS断网、私有缓存和隔离用户环境；保留frozen/no-sync，能够到Gate时仅CONFIG；沙箱不可用或出现网络访问尝试即停止，不把uv早退当所需Gate证据 |
| 删除 `--no-sync` | 1 | 必须先有临时repo内disposable venv、私有cache、OS断网，canonical checkout/runtime不可写且前后不变；预先在同隔离环境确认可到bootstrap，否则本变体前置未满足。不能用缺缓存/同步失败的EARLY代签CONFIG Gate |
| 重复uv三flags各一项、uv组三项换序一次 | 4 | 先绑定冻结uv path/version/SHA做真实CLI接受性characterization；接受者到Gate且仅CONFIG，CLI拒绝者为lane runner-error/无Gate；不能用wrapper吞掉或规范化重复项，不能预设所有14例都生成Gate |

上表“CONFIG”完整代码为 `RUNNER_CONFIGURATION_INVALID`。任何其他独立失败都须保留并分析，不删除失败项凑精确集合；正常对照必须先无无关失败。字符化执行、正式变异执行、真实双lane均属于R3后续工作，不复用R2 fake uv作为真实CLI证明。

可复用的**既有实现模式而非本次资格证明**：

- runner的一次canonical uv解析、独立helpers prefix、env unset、`-I -S -B`、`--noconftest`、固定plugins、`no:cacheprovider`和绝对不存在artifact root。
- `tests/package/test_offline_wheelhouse.py` 的 `_cold_environment` 私有cache模式与macOS `sandbox-exec` 的 `(deny network*)`，并用 `connect_ex` 返回EPERM/EACCES证明OS拒绝。主代理已回读源码，但本轮未运行该包测试或沙箱probe；必须针对整条R3 runner重新验证，不能以文件存在代签。
- R2 harness的临时repo、alias、调用日志和artifact索引设计可借鉴；它始终stub bootstrap，不能直接承接R3真实启动声明。Linux Docker隔离设计也不能代签当前host或顺带升级Linux资格。

**入场停止条件**：不能证明OS网络禁令；disposable venv不能满足temp uv.lock、canonical executable/pyvenv关系并通过baseline；缓存或写路径仍落到真实checkout/.venv；企图仅用UV_PROJECT_ENVIRONMENT/UV_PYTHON重定向（runner会unset）；冻结uv接受性未知；mutation匹配不唯一；源码/执行锁漂移。只阻断相应R3变体，不反向改变R2已冻结合同。R3开始后先建立这些前置证据，再创建/collect真实节点，不提前填入不存在的selector。

**外层隔离证据单独绑定**：command和verifier只约束既有sanitized env键，Gate不记录sandbox profile或私有cache/runtime。每个R3 attempt另存receipt，绑定profile原始bytes/SHA、断网probe结果、临时repo/runtime/cache绝对根及前后目录身份/hash、canonical checkout/.venv/uv前后观察、实际runner argv/exit。Gate PASS或CONFIG不能代签隔离。若保留UV_OFFLINE=1作纵深保护，删除CLI `--offline`用例只证明exact argv缺失被拒绝且OS独立断网，不宣称uv真正进入在线模式。

### 36.37 第二轮独立 QA：深层 JSON 连续性 P1 与修复交接

QA在当前冻结九文件上完成只读复审，确认此前literal/null/nested cap/Prepared/writer与真实consumer补强均有对应oracle；随后根据主代理新疑点进行独立隔离probe，**确认新的P1，停止计划中的47节点回归**。不是47节点已失败或已通过。

原始根 `/private/tmp/ai-auto-lrc-b3f-r2-independent-final-qa.Wasltj`，已保存 [QA证据索引快照](./evidence/b3f-r2-recursion-qa/EVIDENCE-INDEX.md)，其SHA-256为 `77160c10cb3200a1215124355fc3b9de6838f44f6aa4f985e8c3c18df5635bcd`。结构化动态结果 `recursion-probe.stdout.json` SHA-256为 `01596fe242802f754a2d9102b31a1dbff5b58eed59a0d4370c72a43314a87b15`；主代理已回读并重算。probe wrapper exit0仅表示记录成功，**内嵌copied runner实际exit1**，不能记为pytest GREEN或虚构JUnit。

输入为4256 bytes的深嵌套JSON（2000层数组），payload SHA-256 `5bdc6e2a852b21401512062716297d5ef75e65fc837fe17e4220937f9b5eb02a`。两lane各调用一次bootstrap-stub，environment helper的json.loads均抛RecursionError，runner stderr出现两份traceback；environment/manifest/Gate全部缺失，runner-error为ENVIRONMENT_ARTIFACT_WRITE_FAILED、environment_exit_code=1、mode0600。这违反36.4的可读但不可提取→保留raw SHA/null→manifest/Gate连续性，不是要求支持任意深度JSON。

QA确认九文件after hash与before一致、最终进程门为空，已明确停测释放锁。主代理正式交回原实现角色唯一产品/测试写入与执行权，按以下最小闭环推进：

1. 原R2 profile节点补同形有限正例与深嵌套候选永久RED；不改变recursionlimit，不删除原截断/非有限/duplicate反例。
2. environment和manifest候选提取器仅增加RecursionError拒绝分支；完整raw SHA保留，semantic/tools归null，无traceback，真实copied consumer最终仅RUNTIME。consumer runtime core已捕获RuntimeError，本轮不因猜测扩改它。
3. 同时补两个非产品缺陷的harness安全oracle：stub Gate显式断言harness_stub与not_verification_evidence均true；未知program主动调用证明blocked-program及exit97，不执行未知脚本、不回落真实uv。
4. 永久RED→最小GREEN→新字节显式回归/静态九hash→停写交锁→独立QA。旧九hash与实现GREEN保留历史，不能覆盖修复后快照；R3设计仍未执行，所有No-go保持。

### 36.38 深层 JSON 永久 RED/GREEN 与实际 consumer 产物

实现按原profile节点补反例后取得正式pytest RED：`/private/tmp/ai-auto-lrc-b3f-r2-recursion-permanent-red.md5wPu`，**1 failed in 17.40s、exit1**，JUnit SHA-256 `5b100975754e77d2459dda057cde79a8216ce9f798c85583e06876b3d863c029`。主代理已回读，失败精确在deep_stub.returncode（1而非0），两lane environment helper均RecursionError；新增stub标记exact dict、未知program exit97/blocked/marker未执行断言此前已通过到达。这是永久测试RED，不同于36.37的观察probe wrapper exit0。

产品仅修改runner的environment/manifest两个候选提取器，在既有异常分支中加入RecursionError；没有改consumer、schema、递归限制或容量上限。同节点GREEN在 `/private/tmp/ai-auto-lrc-b3f-r2-recursion-runner-green-probe.2U2VmC`，**1 passed in 42.57s、exit0**，JUnit SHA-256 `29a02676a86889ab09928ff43beca8d978dd3536053a8dfd3cd622e07cffdfb3`，stderr为空。主代理已回读stdout/exit并重算hash。

主代理进一步读取该根专用pytest-tmp下deep-identity-real的两lane真实Gate与environment：Gate passed=false且failures精确为RUNTIME_IDENTITY_INVALID；top/nested raw SHA与4256-byte payload一致，runtime语义字段全null、distributions/plugins为空；environment raw SHA保留、semantic和coverage/pytest/uv全部null。调用日志为bootstrap-stub2、verifier-real2、environment-helper2，未调用真实bootstrap。永久用例还覆盖manifest semantic null、stub标记与无traceback、未知program主动拒绝。以上证明该payload的writer/consumer连续性，不是实际安全双lane或R3证据。

实现此时仍持唯一执行权，继续新字节exact15+affected32及静态/必要补充回归；尚未冻结交回QA。新的P1只有实现侧RED/GREEN，不能在独立同快照复验前宣布R2 accepted。旧本地nine-files.sha256明确历史化，新的冻结清单须另存而非覆盖旧QA输入。

### 36.39 递归修复后的新快照与最终独立复验交接

实现已完成并明确停写停测、释放唯一执行锁。主代理读取全部下列动态/静态原始结果，重算JUnit和索引hash，核对新九文件9/9 OK；现将唯一pytest/runner执行权交现有QA，主代理只读/docs，实现不再修改。此为新一轮独立复验开始，不是已通过。

| 当前实现侧集合 | 原始证据根与结果 | JUnit SHA-256 |
| --- | --- | --- |
| exact15 | `/private/tmp/ai-auto-lrc-b3f-r2-recursion-exact15-final.WvvowB`；15 passed in 74.43s，exit0 | `92cffd3e20defd05091d4c1a53a9377c23ae9ceab5af2ad130f20d4d189f6691` |
| affected32 | `/private/tmp/ai-auto-lrc-b3f-r2-recursion-affected32-final.A43sKb`；32 passed in 3.89s，exit0 | `9bc96aed4eebae79c05fe39e02cf0fd01eaa67a20143ab62268595162b41f060` |

两组stderr空，XML分别15/32项、failure/error/skipped均0，仍分组而非同进程47。R1a10、完整R1b15、legacy10本轮实现未重跑，旧结果仅历史；新QA已明确接到这些补充组的fresh复验要求，不用旧GREEN代签。

新静态根 `/private/tmp/ai-auto-lrc-b3f-r2-recursion-static-final.PIUe64`：bash-n、七Python AST、py_compile、Ruff check、git diff check、runner-mode均exit0（0755），Ruff format仍exit1/7 files，不做批量format；untracked内容不由git diff check单独证明。静态前后九hash一致。

已本地保存 [修复证据索引](./evidence/b3f-r2-recursion-implementation/EVIDENCE-INDEX.md)（SHA-256 `b5e4144f822cae7b984f61aeaefdb21545a472ff5b740036f815da08f9a73189`）和 [新九文件冻结清单](./evidence/b3f-r2-recursion-implementation/nine-files.sha256)。从仓库根校验新清单，不再用旧b3f-r2-implementation清单验证当前修复：

```sh
shasum -a 256 -c docs/evidence/b3f-r2-recursion-implementation/nine-files.sha256
```

只有runner变为 `b8fdaf4abe6e2248ad3478ad68e2022b207e8174fe63138a960ecaee2df0ca96`、R2 test变为 `b75ecc23a7e122e51b82cdb3fb1f8dfbd3846ddc4196b068d148fce4d6d435e7`，其余七文件与前次QA快照一致。旧清单和RED索引保留不覆盖。

QA任务为差异审阅+新证据根下fresh47与补充组，沿用36.34的串行、fake-bootstrap、原始证据和结束交锁要求；不重新开展无关架构范围。文档治理尚须等QA释放锁后fresh运行；R2/整体目标仍未完成，R3、真实安全双lane、final67和平台资格化不提前执行。

### 36.40 主代理 fresh 复验通过，独立验收仍未完成

递归修复后的最终QA任务被执行环境安全机制中止，返回agent errored，**没有新的独立验收结果**。不把任务派发、过去只读审阅或实现GREEN代签为最终QA。主代理现场检查未见遗留pytest/runner；只发现之前明确记录的QA证据根，未找到本次新的完成报告。没有重派相同受阻任务或改写其风险描述规避该机制。

主代理重新核对新九hash9/9 OK后接管唯一测试执行权，完成既有本地合同的普通回归验证，不冒称独立QA、不修改产品代码。新证据根 `/private/tmp/ai-auto-lrc-b3f-r2-root-final.gqI2my`，含实际命令、collect清单、工具捕获的完整stdout、单独stderr、真实exit及JUnit：

| 主代理执行 | 结果 | JUnit SHA-256 |
| --- | --- | --- |
| exact15 + affected32，同进程47节点 | 47 passed in 73.80s，exit0，stderr空 | `b8bf1162d6315a9587fa9fe0d03f36fea1c891b408c2bc645c6ba9f2ae0c712e` |
| R1a10 + 完整R1b15 + legacy10，同进程35节点 | 35 passed in 1.07s，exit0，stderr空 | `9db6b9177f4435f90928982666f8d002a03a7ffaf6a8a20b2be3b647cd164900` |

两次collect分别确认47和35；对比展开nodeid，仅两个R1b loader及一个record-field节点跨组重叠，因此产品合同合计**79个唯一节点**，不是82。执行后九文件仍9/9匹配第36.39节新清单。所有bootstrap仍受既有harness拦截，未执行真实security双lane、整个gate测试文件、final67或R3。

当前结论：递归P1已有独立发现、永久RED、最小修复GREEN及主代理fresh回归；**最终同快照独立验收仍缺失**。下一步需要恢复可用的独立验收执行能力，或由具备独立审阅职责的人员依据冻结文件与精确选择清单提供可核验证据；不得把主代理本次结果改名为独立QA，也不降低该验收门后跳到R3。此次不是整体目标完成，所有No-go/外部写入边界维持。

#### 36.40.1 文档治理结果与本轮停测交接

本轮索引与精确展开节点已保存到 `docs/evidence/b3f-r2-root-review/`。主代理随后fresh运行test_spec_inventory.py与test_document_links.py，**42 passed in 12.92s、exit0、stderr空**，JUnit为同证据根的docs.junit.xml，SHA-256 `f42c1682f99f1309b5fca5cd41a334460a47e9be9d06e8d53edfd19791cc543b`。它覆盖本轮方案/上位导航/Teams/索引链接与规格约束，不是产品或独立QA证据；本结果段在该执行后追加。

主代理已完成本轮测试并释放唯一pytest/runner执行权。下一轮先读36.40、核对36.39新九hash与实际进程，再恢复缺失的独立验收，不重复宣布本轮结果为新执行。当前外部执行能力问题只出现于本轮最终QA任务；本轮仍取得P1修复与fresh回归实质进展，整体goal保持active，不作完成或blocked声明。

### 36.41 R2 独立验收完成与 R3 首个实施切片

2026-09-09，用户要求继续实现。独立 QA 在第36.39节冻结九文件上完成源码/oracle审阅及fresh精确回归，结论为 **ACCEPTED，仅限R2合同**；P0/P1均0。两组分别47 passed in79.49s、35 passed in1.03s，去重79节点，均exit0、无失败/错误/跳过，前后九hash不变。[独立证据索引](./evidence/b3f-r2-independent-qa-20260909/EVIDENCE-INDEX.md)保存证据路径与结论；主代理重算57份原始产物checksum全部通过，再fresh执行文档治理两文件，42 passed in8.50s。独立角色已停测交锁，主代理接管下一切片。

第36.40节的最终QA缺失是历史状态，不再阻断当前R2；九文件内容没有因本次验收改变。该验收不晋级产品inventory、不解除S18/W1b-5b/Release No-go。

R3首个切片只实现第36.22节的正常真实capture+retention和同host semantic一致性：原始runner、bootstrap、verifier、两份真实测试与原阈值保持不变。使用系统网络禁令、私有HOME/cache/TMPDIR和对当前checkout/运行环境的写入禁令，先用实际probe证实隔离，再串行运行；原始命令、退出码、全部产物及前后hash保存到全新外部证据根。该正常对照复用只读现有runtime，不声称满足后续会修改runtime的变体前置条件。

新增入口采用先RED再实现；任一正常lane失败或缺件即停止敌意矩阵并保留失败，不把完整raw或模拟Gate视作PASS。PATH/endpoint/lock/flags/.pth变体、disposable runtime、R4与平台资格仍独立待完成。未授权commit/push、发布或恢复操作。

### 36.42 R3 macOS 正常对照切片通过

2026-09-09，新增`tests/system/security_runtime_r3_baseline.py`和`tests/system/test_security_runtime_identity_r3.py`。原始runner/consumer/bootstrap及冻结九文件未修改，原portable层选择不变；新system层提供正常真实双lane与长路径OS隔离probe。无路径pytest仍会收集system层，不能理解为只允许显式调用。

最终快照外层 **2 passed in180.37s、exit0**。capture真实测试282 passed in67.30s，retention257 passed、1个manifest声明的macOS不适用Linux节点skip in106.64s；两Gate均PASS，required分别24/24和15/15全部通过。combined/line/branch分别为capture89.2171%/91.1274%/84.7003%、retention93.6785%/95.0440%/89.5122%，未放宽阈值。两lane的identity/environment/manifest/Gate semantic一致，源码、完整venv及工具前后清单一致。

系统沙箱拒绝IP网络和checkout/runtime写入，只允许本次证据根内Unix socket bind；实际probe确认IP connect/bind与三个文件写端点拒绝，并确认Unix bind成功。长路径probe经过永久RED→最小GREEN；初版沙箱误挡本地socket的4个fixture失败、旧contract位置GREEN和中间主动终止attempt均历史化保留，不合并为最终通过。执行环境的进程回收改进不是全面取消/敌意矩阵证明。

完整命令、最终两文件hash、原始证据根、JUnit、两lane与隔离清单、历史失败、后续入口见 [R3正常对照索引](./evidence/b3f-r3-baseline-20260909/EVIDENCE-INDEX.md)。独立角色已审阅最终源码并独立核对产物；动态测试由主代理执行，不能称独立重新执行。stderr中的原始CoverageWarning保留，未以“日志全空”代替实际结果。

当前解除的是R2独立验收缺口，并完成R3正常macOS切片。下一步从第36.22/36.36节的敌意场景与disposable runtime前置条件继续；不重复实现或扩大此正常对照。R3整体、R4/final-schema replay、Linux与双平台、S18/W1b-5b/Release继续未完成/No-go，inventory不晋级。README双语运行入口和三个上位计划导航已同步。

#### 36.42.1 最终治理与标记语义修正

新增system目录触发既有marker治理的隐含假设：凡存在同名目录，marker必须恰好等于目录节点。这与既有9个retention合同上的system标签冲突；该标签本来表示跨目录POSIX能力，而非测试层。首次spec治理为1 failed、40 passed in8.30s，原始JUnit保留于`/private/tmp/lrc-r3-spec-final-20260909.junit.xml`。

在`test_every_declared_marker_selects_collected_tests`中仅对system保留目录节点必须全部被标记的包含断言；component/golden/package继续精确相等，各marker非空和全节点子集检查保留。不改变原retention标签、portable选择、产品inventory或安全policy。修正后spec **41 passed in8.47s**，链接检查另组 **1 passed in0.04s**；JUnit分别为`/private/tmp/lrc-r3-spec-green-20260909.junit.xml`和`/private/tmp/lrc-r3-doc-links-20260909.junit.xml`。三份本轮Python文件Ruff check/format和git diff check通过。该治理修正不修改已验证的R3两文件或九文件冻结输入，双lane证据不重命名、不重跑冒充新结果。


## 36.43 2026-09-12 用户交付决定：文档与开发分支推送

用户明确要求异常场景暂不全覆盖，优先完善技术文档、系统说明、使用指南与 README 顶部 AI 使用提示词，并推送远端。本次提交/推送已有用户授权，早期“等待提交批准”记录保留为历史，不阻止本次开发快照交付。

当前权威入口为[文档导航](README.md)及[项目状态](PROJECT_STATUS.zh-CN.md)。保留 R2 冻结验收与 R3 macOS 正常对照证据；不扩大其结论、不补跑完整异常矩阵、不更改原始阈值。未完成事项标记暂缓/未验证，S18 / W1b-5b / Release No-go 不变。本轮只向 `improve-inference-reliability` 开发分支提交及推送，不覆盖远端 main，不发布发行版。
