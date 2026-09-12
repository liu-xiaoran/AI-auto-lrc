# AI-auto-lrc v2 Teams W1b-5 retention 与受控导出（2026-09-06）

本次会话在 W1b-4 canonical sidecar 已实现并完成一次真实 Docker capture 后，评审 W1b-5 retention、secret scan、受控导出、归档与销毁边界。仓库没有 `PROJECT-CONTEXT.md`；上下文由当前代码和 W1b 专项方案提炼。PM 由主线程承担，Architect、Developer、QA 三个角色并行只读分析，最终由主线程综合并落盘。

## PM

### 首要判断

W1b-5 的价值是让证据在不意外泄漏、不过期误用和不自动删除的前提下可被盘点与交接，而不是增加上传或发布能力。应将可立即实现的本地扫描/验证，与必须经人类决议的归档、密钥和销毁严格拆开。

### 关键关切

- 默认无网络、无导出、无删除；任何放宽都要求显式 policy 和审批绑定。
- owner、期限、密钥 custody、RPO/RTO 和销毁责任没有决议前，文档不能替业务方填默认值。
- 完成 W1b-5 也不晋级 canonical/release；checkpoint/source 独立恢复仍需后续工作包。

### 第一行动

冻结 threat model、数据分类、生命周期、policy/approval/manifest schema 和负例，再允许写 manager。

### 团队问题

谁是 evidence/security/release 三类 owner，谁有权批准导出、到期和销毁？

## Architect

### 首要判断

W1b-4 可回写为已实现，但仅证明 canonical functional historical integrity；W1b-5 未决前不得上传、自动清理或晋级 release。capture 的只读事实目录和 lifecycle 控制面必须分离。

### 关键关切

- receipt 与约 128 MiB checkpoint 等大资产应分层留存，不能把 hash 记录冒充内容恢复。
- 生命周期采用不可回退、可审计的 `LOCAL_SEALED -> ARCHIVED -> EXPIRED -> DESTROYED` 事件链；扫描/导出是附属事件，不改写原 receipt。
- 加密密钥独立于制品；恢复演练同时验证密文、元数据、checkpoint 引用和 closure。

### 第一行动

先冻结 retention manifest、owner、期限、存储级别、密钥版本及 export receipt schema，再写失败合同。

### 团队问题

secret 命中是否一律阻止外传？密钥丢失、介质损坏和 checkpoint 不可用时，RPO/RTO 与责任人是什么？

## Developer

### 首要判断

先回写 W1b-4 的实际 schema、十二件 closure、真实 capture 与两种 verify 边界；W1b-5 实现应拆成 policy、扫描/导出、retention/销毁三批，避免在同一个命令中混合只读和破坏性职责。

### 关键关切

- 新 manager 只接收 receipt、policy、approval 和目标目录，不接受外部 passed/qualification。
- 导出清单使用版本化 exact-key JSON，逐文件记录 path/size/hash/classification，并绑定 source receipt、policy、approval 和 scanner。
- 任何失败保留原件、禁止半包、原子发布；目标存在时拒绝覆盖。

### 第一行动

先冻结 policy schema 与 RET-T01–T30 负例；再实现只读 inspect/scan，最后接 local-only export。

### 团队问题

owner、保留期限、加密密钥来源及允许导出的敏感级别，是否已有可审计的人类决议？

## QA

### 首要判断

W1b-4 只证明 canonical 功能与历史完整性；release、独立恢复继续 No-go。W1b-5 必须以“任何漏扫、拼接、半包、越权或恢复不完整都失败”为验收基线。

### 关键关切

- 反证矩阵覆盖缺件、篡改、跨 run、过期 approval、symlink/hardlink/FIFO、源竞态和恢复失败。
- 扫描覆盖日志、source snapshot、receipt、sidecar 和所有 artifact；二进制命中不可因解码失败漏报，报告不可回显 secret。
- 归档必须原子、只读、可独立复验；到期只记录状态，不自动删除。

### 第一行动

先冻结 threat model、artifact closure、故障注入表和分批 Go/No-go，再批准实现。

### 团队问题

恢复在哪种隔离环境验证，谁批准解密/导出，删除审计和最终 Go 由谁签署？

## 综合结论

四个角色一致把以下事项定为阻断条件：修改原 sealed run、默认允许导出、扫描错误按通过处理、归档未加密却登记 `ARCHIVED`、到期自动删除、只有 checkpoint hash 却声称可恢复，以及用 W1b-5 局部绿测晋级 release。

实施决议：

1. W1b-4 更新为 Go，但边界固定为 `implemented-unqualified` 与 historical integrity；Release 继续 No-go。
2. 新增独立 retention manager，不把归档/删除职责塞入 capture runner。事实层、控制层、导出层、归档层、销毁层分别建模。
3. 先实施 5a schema/threat model 和 5b read-only inspect/scan；5c local-only export 需要 operational policy 与 approval；5d/5e 需要 `D-REL`，不得用默认值代替决议。
4. secret scan 采用定义明确的 byte/structured rules、全闭包记录和 fail-closed parser；它只证明已定义规则未命中，不承诺发现所有 secret。
5. export 从 allowlist 重建新 bundle并原子发布，不复制未知件，不覆盖目标，不包含网络传输能力。
6. 原 run 永不改写。lifecycle 事件放在独立控制层，hash-chain、sequence 单调；`EXPIRED` 不等于已删除。
7. checkpoint 内容寻址、KMS/key custody、RPO/RTO、双人销毁审批和 tombstone 期限必须由人类锁定。

字段级 schema、DAG、RET-T01–T30 与 Go/No-go 见 [`../W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md`](../W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md) 第 19 节。

## 二次评审：首版实现后的安全反证

首版 assessment-only manager、两份配置和合同测试已经落地，定向测试记录为 `47 passed`。该结果证明首版合同可执行，不证明控制包已有独立信任锚，也不关闭下列安全缺口，因此 W1b-5a/5b 仍为 **No-go / hardening required**，Release 继续 **No-go**。编码级事实、六个冻结切片与新增测试矩阵统一见 [`../W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md`](../W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md) 第 15 节。

### PM 二次结论

- **First reaction**：首版已经把范围压缩为本地 `inspect`/`scan`/`verify-inspection`，但 `47 passed` 只是开发检查点，不是能力验收。
- **Key concerns**：不得因已有可运行 manager 就提前开放 export/archive/destroy；每个 P0/P1 必须有可独立反证的测试；human governance 决策继续保持 unresolved。
- **First action**：冻结第 15.3 节六个切片及第 15.4 节测试矩阵，逐片 RED→GREEN，不跨片宣称完成。
- **Question**：由谁签收外部 rules/assessment trust anchor 及后续 D-REL 决议，仍需人类明确。

### Architect 二次结论

- **First reaction**：事实层与控制层的方向正确，但当前自洽 hash 链不等于外部可信，event 也尚未成为不可混淆的最终提交点。
- **Key concerns**：父链 symlink 可改变真实读写目标；source 最后复验到发布/返回之间仍有 TOCTOU；assessment/rules 需要控制包之外的预期 hash 信任锚。
- **First action**：先完成 schema/config trust 和 descriptor-relative path/I/O，再重构 transaction/ledger；任何中间 inspection 没有有效 event 都只能是 orphan。
- **Question**：外部 expected hash 由何种版本化介质持有，必须在实现前锁定，不能由同一个控制包自证。

### Developer 二次结论

- **First reaction**：当前实现可通过首版合同，但扫描报告嵌入可逆 `pattern_base64`、允许任意 regex 并整文件读取，不能作为安全实现收口。
- **Key concerns**：规则内容泄漏；regex 灾难回溯与整文件 join 导致 CPU/内存 DoS；异常清理、no-replace、exact schema/权限和未知分类仍需加严。
- **First action**：以受限 bytes matcher、size-before-read 和 chunk 流式 hash/scan 替代任意 regex/整文件读取，再做事务与 CLI 收口。
- **Question**：`verify-inspection` 是否显式接收外部 expected rules/assessment；若否，必须提供另一独立不可变锚。

### QA 二次结论

- **First reaction**：现有 47 个 nodeid 可以保留为首版回归，但不足以覆盖最终威胁模型。
- **Key concerns**：缺少父链 symlink、publish 前后 source mutation、弱规则整包替换、大文件读取前阻断、orphan/event 提交点和精确权限反证。
- **First action**：按第 15.4 节补齐 path、config、scan、race、transaction、schema、permission、CLI、drift 九组负例；每个实现切片先确认 RED。
- **Question**：真实 pass/blocked receipt 与外部配置锚由谁保存和独立复验，需在 Go 评审中指定责任人。

### 二次综合阻断项

| 优先级 | 阻断项 | Go 前必须证明 |
|---|---|---|
| P0 | 父链 symlink | receipt、retention、assessment、rules、control 全路径逐组件安全，词法路径不能逃逸 |
| P0 | source/publish TOCTOU | scan 前后、inspection 发布前、event commit 前及返回前的 closure/identity 变化均不能返回有效结果 |
| P0 | 外部 trust anchor | rules/assessment snapshot、report、manifest、event 与控制包之外的 expected hash 全绑定 |
| P0 | pattern 泄漏 | report/event/CLI 不保存 `pattern_base64`、原始 pattern、命中内容或上下文 |
| P0 | regex/内存 DoS | 不执行任意 regex；按 stat size 先阻断，采用有界 chunk scanner，并限制 hit/总量 |
| P1 | transaction/ledger | no-replace 原子发布；event 是最终提交点；orphan 不被视为有效状态 |
| P1 | exact control contract | JSON 嵌套 exact-key、duplicate-key、bool-as-int、ID/time/hash、排序唯一与交叉绑定全部 fail closed |
| P1 | 权限与分类 | owner/nlink/symlink 和精确私有 mode 受验；`source/**` 不误分，unknown 必须 blocked |
| P1 | CLI | 仅 `inspect`/`verify-inspection`；pass=0、blocked=3、failure=1、argparse=2；输出不含绝对路径和 secret |

实施顺序冻结为六个最小可测试切片：S1 schema/config trust → S2 path + bounded I/O → S3 report correctness → S4 control transaction → S5 independent verifier → S6 CLI + regression。完整完成条件和测试矩阵只在 W1b-5 执行计划第 15.3–15.4 节维护；本会话文件仅保存角色判断与阻断理由，避免形成第二份字段规范。

二次评审继续禁止 export、upload/sync、archive、expire、prune/destroy、自动清理、CI、commit、push 和发布。只有六个切片及对应新增反证真实通过后，才可重新评审 W1b-5a/5b；即使届时通过，也不晋级 canonical/release。

## S7–S11 前的实现复核（历史检查点）

加固版已完成 69 个 retention nodeid，并与 capture 合同联合得到 `200 passed`；宿主全量为
`550 passed, 18 skipped, 22 warnings`。两个由真实 capture gate 生成的 sealed run 分别完成
PASS/exit 0 与 BLOCKED/exit 3 的独立 verify。以上是有效回归证据，但最终 Architect/QA
反审又确认四类未关闭 P0：path-based 父目录替换竞态、缺独立 expected digest、全局
hit/report 上限导致的已提交后自失效、以及 leaf 特殊文件/identity 三阶段反证缺失。

因此四角色最终共识是：当前实现记为 **partial implementation / hardening required**，
W1b-5a/5b 均不标 Go。下一批 S7–S11、11,050-hit 可复现实证和强制测试清单统一保存在
[`../W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md`](../W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md)
第 16 节；本会话不复制字段规范。

## 第三次复核：S7–S11 实施后的架构与 QA 反审

### PM

- **判断**：S7–S11 已形成可执行合同，不得再把它们写成“下一批”；但技术绿测不能代替 trust-root owner、轮换审批和最终 Go 签收。
- **范围**：W1b-5a 只允许 local assessment-only conditional Go；W1b-5b 在两个事务 P0 关闭前不进入 production-safe；5c/5d/5e 继续未授权。
- **交接要求**：主计划只维护跨工作包 Gate，handoff 只维护恢复地图，W1b-5 专项方案第 17 节是唯一字段、测试与 runbook 事实源；历史数字不可被静默改写。
- **未决人类问题**：谁持有默认 rules/assessment digest，谁批准轮换，记录写入哪个 ADR/审计位置，谁签 W1b-5a/5b Go。

### Architect

- **已确认**：默认 raw-byte digest、自定义 expected digest、rule-set ID/SHA 交叉绑定、有界 matcher、run fd receipt verifier、no-replace、ledger 分类和两子命令 CLI 均已落地。
- **P0-1**：单次 `_directory_fd()` 是安全的，但 `LOCK`、ledger、write、rename、fsync 与 final verify 会多次从 Path 打开。锁住旧 `LOCK` inode 后，同 UID 替换 `run_control` 可能使后续写进入另一控制树，形成 lock split。
- **P0-2**：event rename 系统调用成功后，target post-stat、temporary cleanup、mode check 或 fsync 仍可能失败；只要 event 可能已可见，所有后置失败必须统一为 `CONTROL_COMMIT_UNCERTAIN`，当前实现仍有误分支。
- **平台边界**：Linux `/proc/self/fd` 是真实 fd anchor；macOS `F_GETPATH` 加前后 identity 不是事务快照。Git 多命令与文件枚举也不原子，不能排除 transient swap/ABA。

### Developer

- **实现事实**：retention 为 125 个 node，capture 为 135 个 node；默认 digest、五类全局限额、`verify_receipt_at()`、actor self-asserted hygiene 与稳定错误码已进入代码。
- **下一实现**：S12 建立 transaction fd context；S13 建立 `event_may_be_visible` 单向状态；S14 把资源上限前移到枚举物化期间；S15 明确 current-source 可证明范围。
- **禁止变更**：不得退化为普通 rename，不得自动删除 orphan/invalid ledger，不得新增 export/archive/destroy，不得把 expected digest 重新解释为授权。

### QA

当前锁定环境证据：

```text
retention:          125 passed
capture:            135 passed
combined:           260 passed in 88.21s
host full suite:    610 passed, 18 skipped, 22 warnings in 145.79s
ruff/compile/json/digest/diff-check: PASS
```

必须使用 `uv run --frozen --no-sync`；系统 Python 的依赖版本不同，不能作为正式回归证据。18 个 skip 是 13 个 canonical-only golden 和 5 个缺 wheelhouse package case，不能被“通过数”吸收。

| 测试域 | 当前 GREEN | 下一批必须新增的 RED |
|---|---|---|
| S7 descriptor/path | parent swap、symlink/hardlink/FIFO/socket、identity、owner/mode | 获取 flock 后替换完整 control tree；device 与 config owner 组合 |
| S8 trust binding | custom digest、弱规则、JSON byte drift、ID/hash | digest 发布、轮换、保管只能由治理证据签收 |
| S9 boundedness | 11,050 hits、多文件 hit cap、oversize report | `MAX_RUN_FILES`、`MAX_RUN_BYTES`、metadata limit 在物化前触发 |
| S10 transaction | write/fsync/rename、orphan、no-replace、invalid ledger | post-event 全 fault matrix、双进程崩溃、staging/duplicate state |
| S11 mode/hygiene | 参数矩阵、checkout drift、双线程、offset、脱敏 | 真实 CLI subprocess、双进程 publisher、macOS swap/ABA |
| Capture | 135 个 fd-aware 合同 | Linux 实跑 `/proc/self/fd` 与 `renameat2`；安全脚本 branch coverage |

### 最新本地真实复验

使用当前代码重新生成两个测试控制 sealed run，独立 `verify-inspection` 结果为：

| 状态 | run ID | inspection ID | 退出码 | sealed tree |
|---|---|---|---:|---|
| PASS | `20260906T102647633323Z-a7c8b2386c964600a2382c52b494ac93` | `cd56eaa47daa4b7fa25ea6f75cdd4b84` | 0 | signature 前后不变 |
| BLOCKED | `20260906T102648245827Z-71bbbc6f191241f6b39ba76b100371f5` | `a510b09c85934a078d54f8973384efd0` | 3 | signature 前后不变 |

证据根为 `/private/tmp/ai-auto-lrc-w1b5-final-20260906-01/`。它证明本地 assessment 闭环和 sealed run 不变性，不证明 canonical、跨平台、独立恢复或 Release。

### 第三次综合 Gate

| 范围 | 结论 |
|---|---|
| W1b-5a | Conditional Go，仅限 checked-in defaults、受信脚本、local assessment-only；治理与签名信任未闭合 |
| W1b-5b | No-go / hardening required；合同 GREEN，但 control transaction anchor 与 commit uncertainty 两个 P0 未闭合 |
| W1b-5c/5d/5e | 未授权、未实现、blocked-by-D-REL |
| Release | No-go |

四角色一致要求下一位从 S12 开始，不重做 S1–S11。不得自动上传、归档、恢复、删除、清理、commit、push、签名或发布。

## 第四次复核：S12/S13 第一批实现与测试矩阵反审

### PM

- **First reaction**：S12/S13 的 9 个精确合同降低了两个 P0 风险，但不足以将整个 W1b-5b 升为 Go；文档必须区分“已声明场景 GREEN”和“完整事务矩阵仍 No-go”。
- **Key concerns**：S14–S18 未关闭；trust-root owner、rotation approver 和 Go signer 未指定；旧 sealed receipt 不能追认为新代码证据。
- **First action**：同步本轮 RED→GREEN、真实测试数字、缺口与下一批 owner，再生成最新 PASS/BLOCKED evidence。
- **Question**：谁负责签署 W1b-5b local assessment-only Go，并承担 digest 轮换审批？

### Architect

- **First reaction**：pinned fd 与 event commit latch 已进入生产调用链，但还存在初始化和事务尾部窗口。
- **Key concerns**：`inspections/events` 分别从绝对 Path 打开，未从 pinned parent 相对绑定；final verify 返回后缺最后一次 control namespace check；unlock/close/context-exit 可绕过 uncertain 分类。
- **First action**：先写 context-init/mid-transaction/final-verify/teardown RED，再做 parent-child pin、return 前复核和 teardown 状态机。
- **Question**：独立 verify 成功后若仅 teardown 失败，是 suppress/diagnostic success，还是仍为 `CONTROL_COMMIT_UNCERTAIN`？

### Developer

- **First reaction**：第一批修复保留公共 API/CLI/schema/layout，并通过全部 9 个新合同与既有 125 个 retention 节点。
- **Key concerns**：当前 context 只有 run/inspections/events 三个 fd；ContextVar 是兼容旧 helper 的过渡层；transaction 级 event phase 还未覆盖 finally。
- **First action**：在合同冻结后从 pinned run fd 相对打开 children，把 event phase 延伸到 return/teardown，并避免 cleanup/close 覆盖主异常。
- **Question**：是否允许为 teardown 失败新增公共状态；若不允许，必须保持既有 `CONTROL_COMMIT_UNCERTAIN` 单码。

### QA

- **First reaction**：flock 后立即 swap 的 3 个 S12 和 post-event 的 6 个 S13 场景精确、可重复、当前 GREEN；完整故障矩阵仍未被证明。
- **Key concerns**：缺中后段换位；post-event namespace/source/teardown 没有直接 fault injection；uncertain artifact 只做数量断言，未独立验证 hash、mode、linkage 与 recovery 分类。
- **First action**：新增 S12a/S13a 精确 RED，并同时检查 replacement 与 displaced tree；event 可见后只允许单一稳定码。
- **Question**：真实 crash/power-loss 场景由哪个平台 runner 保存证据并负责复验？

### 本轮真实验证

```text
S12/S13 targeted: 9 passed, 125 deselected in 3.88s
retention + capture: 269 passed in 58.95s
host full suite: 619 passed, 18 skipped, 22 warnings in 113.84s
ruff: PASS
compileall: PASS
git diff --check: PASS
```

18 个 skip 为 13 个 canonical-only golden 和 5 个缺 wheelhouse 的 package case。四角色一致同意：S12 已声明的 3 个场景 Go；S13 已声明的 6 个场景 Go；完整 S12/S13、W1b-5b 与 Release 仍 No-go。

### 下一批冻结动作

1. S12a：context 初始化、ledger 后、inspection publish 后、event rename 后与 final verify 中途的 run/inspections/events swap。
2. S13a：post-event namespace、两次 source check、unlock、lock close、context exit 的精确 fault injection。
3. 生产修正：pinned parent-child openat/identity binding、return 前 namespace check、transaction 级 event visibility、稳定 teardown。
4. fault 撤销后对 uncertain artifact 做独立 verify 或精确 recovery 分类。
5. 完成后重跑 retention、capture、宿主全量，并以最新代码重新生成 PASS/BLOCKED receipt。
6. S12a/S13a 通过后依次执行 S14–S18；不得跳过资源、ABA、crash、CLI/ownership、Linux/coverage 资格。

详细测试 ID、实现顺序和 Gate 只在 [`../W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md`](../W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md) 第 18 节维护。本会话保存角色判断，不复制字段 schema。禁止自动上传、归档、恢复、删除、清理、commit、push、签名或发布。

## 第五次复核：S12a–S15 实施、diagnostic current-source 与后续测试

### 实施事实

- S12a/S13a：child control fd 从 pinned run fd 相对打开；同 generation namespace recheck 覆盖事务中后段和 API return 前。
- S13b：event-visible phase 覆盖 unlock/close/context exit；主异常优先，event 已可见后的 teardown-only 失败固定为 `CONTROL_COMMIT_UNCERTAIN`。
- S14：共享 budget 在目录枚举/排序前限制 entry、file、declared bytes 和 compact snapshot metadata；cap+1 立即停止。
- S15：current-source 两次完整顺序 observation；不稳定精确拒绝；CLI 强制 diagnostic/non-transactional/ABA-not-excluded；retention schema-v1 current-source inspect 在 control I/O 前冻结。

当前证据为 retention `154 passed`、capture `142 passed`、联合重跑 `296 passed in 69.54s`。第一次联合运行的 `1 failed, 295 passed` 作为潜在顺序 flaky 保留。S15 与文档落盘后的宿主全量为 `646 passed, 18 skipped, 22 warnings in 123.64s`；静态与链接检查通过。最新 PASS/BLOCKED sealed evidence 已在仓库外完成 inspect/verify `0/0` 与 `3/3`，sealed tree signature 前后不变，精确 ID 见专项计划第 19.2 节。

### PM

- **First reaction**：应立即建立可恢复执行的单一事实文档；S12a–S15 只是已验证阶段成果，不等于可发布。
- **Key concerns**：锁定当前重构范围与保留改动；S16–S18 和上位 v2 包必须有明确 DoD；SBOM、attestation、签名、rollback 未闭环即 Release No-go。
- **First action**：把事实、DoD、证据、依赖、禁止边界和恢复入口写入主计划。
- **Question**：谁负责签署 S16–S18 与最终 Go？

### Architect

- **First reaction**：按“current-source 只作诊断、retention v1 不发布”的冻结合同，S15 transition slice 可 Go；不能据此宣称事务快照或排除 ABA。
- **Key concerns**：程序化 verifier 返回原 receipt，调用方可能误读旧 qualification；`source` 未 exact-key 拒绝矛盾声明；macOS/Git/system 对抗证据仍缺。
- **First action**：把 effective assurance 与 receipt document 分离写入文档，先补 unknown-key 和真实 adversarial RED，再做 process crash。
- **Question**：是否采用 additive typed verification outcome，避免改变 sealed document？

### Developer

- **First reaction**：已验证事实、未闭合风险与门禁应成为唯一恢复入口，并严格区分完成项和计划。
- **Key concerns**：锁定 S16→S17→S18 及 runtime close、恢复、SBOM/attestation/签名依赖；在途改动按切片可回退；每步写清命令、预期输出、失败码和 artifact 路径。
- **First action**：以当前快照为起点补逐项验收和停止条件，不重做 S1–S15。
- **Question**：S16 前是否需要冻结 Demucs/package 的并行文件边界？

### QA

- **First reaction**：S12a–S15 只闭合局部合同且属于分层诊断证据，不能升级为 Release Go。
- **Key concerns**：S16–S18 并发、crash、CLI/ownership、Linux 未完成；macOS/package、资源、Demucs、runtime close、恢复仍缺真实证据；flaky/skip 必须单列。
- **First action**：固化测试矩阵、证据层级、flaky、Gate、续跑顺序与禁止边界。
- **Question**：各缺口的 owner、required 环境和最终 Go 签署人是谁？

### 综合结论

四个角色一致认为：**当前阻断项不是缺更多“通过数量”，而是缺 process/system/platform/release 分层证据和人类治理签收。** S15 的明确张力是：CLI 已诚实降级，但程序化 API 仍返回含历史 qualification 的原 document；短期必须用文档和 unknown-key RED 防误用，中期只能新增 typed outcome，不能修改 sealed receipt。

执行顺序冻结为：文档与最新 evidence checkpoint -> S16 独立进程/crash -> S17 CLI/ownership/Linux special files -> S18 coverage/Linux/package/canonical qualification -> W1b-5b 复审。上位剩余工作按资源预算 -> 双平台 package -> Demucs -> runtime close -> 经授权的独立恢复 -> 经授权的供应链/rollback 推进。精确方案见专项计划第 19 节和主计划第 29 节。

禁止事项不变：不 commit、push、创建 CI、上传、签名、发布、自动删除、清理、归档或恢复；5c/5d/5e 未授权；Release No-go。
