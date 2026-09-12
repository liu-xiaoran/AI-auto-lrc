# W1b-5 retention manager 最小实现执行计划

> 状态：**In progress / S16–S17 已完成声明范围；S18 coverage、package 与最终 evidence 未闭合，W1b-5b 和 Release No-go**
>
> 修订：v4（2026-09-06，Teams PM、架构、开发、QA S18 qualification 复核）
>
> 上位设计：[`W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md`](./W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md) 第 19 节
>
> 事实边界：本文件只细化 W1b-5a/5b；文中接口、文件和测试在代码真实存在且测试通过前都不是实现证据。

## 0. 本轮结论

本轮只实现已获授权且可逆的本地能力：

1. 校验版本化 secret rules 与 assessment retention policy；
2. 复用现有 receipt verifier，验证已封存 run 的历史完整性；
3. 对 sealed run 的完整文件闭包做 binary-safe、stable-read secret scan；
4. 在 sealed run 外的 `.control` 目录原子发布扫描报告与 append-only 事件；
5. 独立重算并验证 inspection、completion marker 和事件绑定。

本轮 CLI **只能**提供 `inspect` 和 `verify-inspection`。不得出现 `prepare-export`、`verify-export`、`export`、`upload`、`sync`、`archive`、`expire`、`prune`、`destroy` 等子命令或等价 Python API。上位设计第 19.2 节描述的是完整远期组件边界；本文件收窄并锁定首个可实现批次。

扫描通过只说明“本次冻结规则没有在已扫描字节中命中，且扫描过程没有失败”，不说明不存在 secret，不提升 receipt qualification，不证明 checkpoint/source 可独立恢复，也不解除 Release No-go。

## 1. 架构决策与不可变边界

### 1.1 采用的设计

| 决策 | 选择 | 原因 |
|---|---|---|
| 职责位置 | 新增独立 `scripts/manage_evidence_retention.py` | capture 负责生成事实；retention manager 负责事实之外的控制记录，避免把未来破坏性职责混入 capture runner |
| receipt 复验 | 优先调用 `capture_test_gate.verify_receipt_at(run_fd, receipt_name, mode, repo_root_fd)`；Path API 只作兼容入口 | archived run、receipt、SEALED 与 closure 相对调用方已打开的 run fd 读取；current-source 同时传 repo fd；不复制或绕过 receipt qualification/closure 逻辑 |
| sealed run | 永远只读 | 不修改文件、目录 mode、`receipt.json`、`SEALED` 或任何 artifact |
| 控制面 | `<retention-root>/.control/<run-id>/` | inspection 与事件不进入 receipt closure，也不污染只读事实目录 |
| assessment 状态 | 16 项治理决策必须全部 `unresolved/null`，且 `mode=assessment-only` | 当前 owner、期限、archive/key、RPO/RTO、销毁审批均未由 D-REL 锁定；未来 operational policy 使用另一 schema/API |
| 扫描方法 | bytes 流式扫描 + 有界内置匹配器 | 非 UTF-8 文件不漏扫；不执行任意用户 regex，避免 regex ReDoS 和解释差异 |
| 并发 | run-scoped 非阻塞独占文件锁 | 同一 run 只有一个发布者；不同 run 可并行 |
| 提交点 | hash-chained event 是最终状态提交点 | inspection 目录先发布但 event 失败时仍是 orphan，不得被视为有效状态 |
| 重扫 | v1 每个 run 只允许一个已提交 inspection | 避免在未定义重扫、规则升级和 blocked→pass 语义前引入状态回退 |

### 1.2 明确拒绝的替代方案

- 不把扫描字段写回 receipt：这会破坏 W1b-4 的封存 hash 和历史事实。
- 不扫描部分 allowlist 后报绿：漏掉 logs、source snapshot 或 binary artifact 会产生假阴性。
- 不接受任意 regex 规则：Python bytes regex 没有可靠的每次匹配超时，恶意或错误规则可使 inspection 挂死。
- 不在 assessment policy 上接受命令行 `--force`、approval 或临时 owner：这些输入不能把非 operational policy 升级为 operational。
- 不先实现 local export 再补授权：即使只写本地，复制敏感 bytes 也是新的数据扩散能力。
- 不通过删除旧 inspection 来重试：控制记录必须 append-only，已发布对象不可覆盖。

## 2. 能力分解

| ID | 能力 | 输入 | 成功输出 | 失败边界 |
|---|---|---|---|---|
| RET-C01 | rules strict loader | rules JSON bytes | `SecretRules` | 未知键、重复 ID、非 ASCII term、非法 matcher、hash/大小超限失败 |
| RET-C02 | assessment strict loader | assessment JSON bytes、rules hash | `RetentionAssessment` | 未知键、bool-as-int、decision/mode 矛盾、rule binding 不同失败 |
| RET-C03 | receipt adapter | receipt、mode、可选 repo root | 已验证 receipt document | 只传播为 `RECEIPT_INVALID`；qualification 不作为 retention 授权 |
| RET-C04 | exact closure inventory | sealed run root | 排序且唯一的普通文件记录 | 多件、少件、symlink、hardlink、特殊文件、路径逃逸失败 |
| RET-C05 | stable byte scanner | inventory、rules、assessment limit | 每文件 hash、size、classification、脱敏 hits/errors | 截断、超限、读取竞态、规则执行错误只能 blocked |
| RET-C06 | inspection builder | receipt/rules/assessment/scanner 结果 | 确定性 report core | 不保存命中原文、上下文、secret hash、绝对路径或 qualification |
| RET-C07 | control publisher | report、actor、当前 ledger | inspection + COMPLETE + event | 独占 staging、fsync、原子 rename；event 前均不算提交 |
| RET-C08 | ledger verifier | `.control/<run-id>/events` | 单调、连续、hash-chain 完整的状态 | 重号、跳号、覆盖、状态回退、文件名/hash 不一致失败 |
| RET-C09 | inspection verifier | receipt、report、marker、event、rules、assessment | 无写入的独立复验成功 | 重新扫描字节并比较，不信任 report 自报结果 |
| RET-C10 | CLI boundary | 两个子命令参数 | 机器可读摘要和稳定退出码 | parser 中不存在任何导出、归档或销毁命令 |

## 3. 文件与模块边界

本批新增：

```text
scripts/manage_evidence_retention.py
packaging/evidence-secret-rules.json
packaging/evidence-retention-assessment.json
tests/contract/test_evidence_retention.py
```

为降低首批改动面，v1 先保持单脚本；内部按下列区域分层，函数不得跨层读取隐式全局状态：

```text
schema/value objects
  -> safe path + stable byte I/O
  -> receipt adapter + closure inventory
  -> matcher compiler + streaming scanner
  -> inspection/event serializer
  -> control transaction + ledger verifier
  -> public API
  -> argparse CLI
```

只有 receipt adapter 可以导入 `scripts.capture_test_gate`。scanner、ledger 与 publisher 不得调用 capture 私有 `_...` 函数；现有 `_read_stable_regular()` 会整文件读取且不拒绝 hardlink，不满足本轮流式扫描合同。

### 3.1 公共 Python API

```python
class RetentionError(RuntimeError):
    code: str


@dataclass(frozen=True, slots=True)
class InspectionResult:
    inspection_path: Path
    control_event_path: Path
    state: Literal["SCANNED_PASS", "SCANNED_BLOCKED"]
    run_id: str
    inspection_id: str

    @property
    def report_path(self) -> Path: ...

    @property
    def control_directory(self) -> Path: ...

    @property
    def status(self) -> str: ...


def load_secret_rules(
    path: Path,
    *,
    expected_sha256: str | None = None,
) -> SecretRules: ...


def load_retention_assessment(
    path: Path,
    *,
    rules: SecretRules,
    expected_sha256: str | None = None,
) -> RetentionAssessment: ...


def inspect_run(
    *,
    receipt: Path,
    rules_path: Path,
    assessment_path: Path,
    expected_rules_sha256: str | None = None,
    expected_assessment_sha256: str | None = None,
    actor: str,
    mode: Literal["archived-integrity", "current-source"] = "archived-integrity",
    repo_root: Path | None = None,
) -> InspectionResult: ...


def verify_inspection(
    *,
    receipt: Path,
    inspection: Path,
    control_event: Path,
    rules_path: Path,
    assessment_path: Path,
    expected_rules_sha256: str | None = None,
    expected_assessment_sha256: str | None = None,
    mode: Literal["archived-integrity", "current-source"] = "archived-integrity",
    repo_root: Path | None = None,
) -> InspectionResult: ...
```

`inspect_run()` 在 event 成功提交前不得返回。`verify_inspection()` 必须全程只读，不能更新访问时间以外的业务状态、补 marker、修复 ledger 或清理 orphan。

### 3.2 CLI 合同

```text
python scripts/manage_evidence_retention.py inspect
  --receipt ABS
  [--rules ABS --expected-rules-sha256 HEX]
  [--assessment ABS --expected-assessment-sha256 HEX]
  --actor ID
  [--mode archived-integrity|current-source]
  [--repo-root ABS]

python scripts/manage_evidence_retention.py verify-inspection
  --receipt ABS
  --inspection ABS
  --control-event ABS
  [--rules ABS --expected-rules-sha256 HEX]
  [--assessment ABS --expected-assessment-sha256 HEX]
  [--mode archived-integrity|current-source]
  [--repo-root ABS]
```

约束：

- `--mode=current-source` 时 `--repo-root` 必填；archived 模式传入 repo root 应拒绝，避免产生“用到 checkout”的歧义。
- checked-in 默认配置使用代码中编译期固定的 raw-byte SHA-256；自定义 `--rules` 或 `--assessment` 必须分别与对应 `--expected-*-sha256` 成对出现。expected digest 是完整性输入，不是 export/archive/destruction 授权或签名证明。
- `actor` 长度 1–128，只允许 ASCII 字母、数字和 `._:@/-`；不得包含控制字符、HOME、空白或绝对路径。
- stdout 只输出一行 JSON 摘要：`run_id`、`inspection_id`、`state`；不输出绝对路径和命中详情。
- stderr 只输出 `<CODE>: <sanitized message>`；不回显配置内容、secret、HOME 或绝对路径。
- argparse 退出码 2；`SCANNED_PASS`/有效复验为 0；已成功提交的 `SCANNED_BLOCKED` 为 3；结构、I/O、锁和事务错误为 1。
- secret 命中是成功完成的 blocked assessment，不抛出携带命中内容的异常。

## 4. exact-key schema

### 4.1 `evidence-secret-rules.json`

顶层 exact keys：

```json
{
  "schema": "ai-auto-lrc/evidence-secret-rules",
  "schema_version": 1,
  "rule_set_id": "w1b5-assessment-v1",
  "scanner_id": "ai-auto-lrc-byte-scanner-v1",
  "chunk_bytes": 65536,
  "rules": []
}
```

每个 rule exact keys：

```json
{
  "rule_id": "SEC-AUTH-SCHEME",
  "category": "credential",
  "matcher": "scheme-value-ascii-ci",
  "terms": ["Bearer", "Basic"],
  "max_value_bytes": 512
}
```

v1 只允许以下 matcher：

| matcher | 语义 | `max_value_bytes` |
|---|---|---:|
| `literal-ascii` | 对每个 ASCII term 做精确 bytes 搜索 | 必须为 0 |
| `literal-ascii-ci` | 对 ASCII 大小写折叠后的 term 搜索 | 必须为 0 |
| `scheme-value-ascii-ci` | term + 至少一个 ASCII 空白 + 1..N 个非空白/非控制字节 | 1..4096 |
| `assignment-value-ascii-ci` | 有 token 边界的 key + 可选空白 + `:`/`=` + 可选空白 + 1..N value | 1..4096 |

规则必须按 `rule_id` 字典序排列且唯一；`category` 和 `rule_id` 只允许 `[A-Z0-9_-]`/`[a-z0-9-]` 的既定格式；term 必须是 1–128 bytes 的可打印 ASCII，数组非空、排序且唯一。不得支持 regex、glob、脚本、动态 import 或外部命令。

首版规则至少覆盖：

- Unix/macOS 用户路径标记：`/Users/`、`/home/`；
- Authorization scheme：`Bearer`、`Basic` 后的值；
- assignment keys：`token`、`api_key`、`apikey`、`secret`、`password`、`credential`、`access_key`、`private_key`；
- PEM/private key header；
- 常见云 access-key prefix：`AKIA`、`ASIA`；
- 项目测试 sentinel：`sentinel-secret`。

这些规则本身不得包含真实 credential。规则 hash 是文件原始 bytes 的 SHA-256，不是解析后 JSON 的 hash。

### 4.2 `evidence-retention-assessment.json`

顶层 exact keys：

```json
{
  "schema": "ai-auto-lrc/retention-assessment",
  "schema_version": 1,
  "assessment_id": "w1b5-local-assessment-v1",
  "created_at_utc": "2026-09-06T00:00:00Z",
  "mode": "assessment-only",
  "decision_state": "pending-human-approval",
  "capabilities": {},
  "classifications": [],
  "decisions": {},
  "scanner": {}
}
```

嵌套 exact keys 与 assessment 值：

| 对象 | exact keys | v1 assessment 约束 |
|---|---|---|
| `capabilities` | `inspect`,`scan`,`prepare_export`,`archive`,`expire`,`destroy` | 仅 `inspect=true`、`scan=true`；其余必须为 `false` |
| `classifications` | 数组 | 必须按字典序精确等于 `captured-input,checkpoint,log-raw,metadata,source-raw,test-evidence,unknown` |
| `decisions` | 16 个冻结治理决策键 | 每项精确为 `{status:"unresolved",value:null,decision_id:null}` |
| `scanner` | `rule_set_id`,`rule_set_sha256`,`max_file_bytes`,`on_error` | hash 必须绑定实际 rules bytes；`max_file_bytes` 为非 bool 正整数；`on_error="block"` |

派生规则：

- `mode` 只接受 `assessment-only`，`decision_state` 只接受 `pending-human-approval`。
- owner、期限、export、archive、key、RPO/RTO、checkpoint 与 destruction 决策一律 unresolved/null；占位字符串同样非法。
- operational policy 不得复用此 schema；本批 manager 以 `ASSESSMENT_SCHEMA_INVALID` 拒绝其他 schema/mode。
- CLI 参数、actor 或未来 approval 不能覆盖 assessment 字段。
- assessment hash 使用原始文件 bytes，不使用解析后 JSON hash。

### 4.3 文件分类

分类只由 sealed-run canonical relative path 派生，不接受 receipt、扩展名或调用方自报：

| path | classification |
|---|---|
| `receipt.json`、`SEALED` | `metadata` |
| `inputs/**` | `captured-input` |
| `artifacts/**` | `test-evidence` |
| `source/**` | `source-raw` |
| `logs/**` | `log-raw` |
| 未来明确的 checkpoint byte path | `checkpoint` |
| 其他 | `unknown`，并产生 `CLASSIFICATION_UNKNOWN` blocked error |

canonical runtime 中只有 checkpoint size/hash 记录，不含 checkpoint bytes；不得把该记录分类成“可恢复 checkpoint”。

### 4.4 `secret-scan.json`

exact keys：

```text
schema, schema_version, run_id, layer, inspection_id,
receipt_sha256, sealed_sha256, rules_sha256, assessment_sha256,
scanner_id, mode, files, errors, export_allowed, created_at,
aggregate_sha256
```

`files[]` exact keys：`path,size,sha256,classification,hits`。`hits[]` exact keys：`rule_id,start_byte,end_byte`，区间为 0-based `[start,end)`。读取失败时仍要有该 path 的 file record，`sha256=null`，并在 `errors[]` 写稳定 code；只要存在 error，状态必为 blocked。

`errors[]` exact keys 为 `code,path`；没有具体文件时 `path=null`。数组按 `(path,code)` 排序并去重。`export_allowed` 在本批永远为 `false`。

报告严禁包含：

- matched bytes、解码文本、前后文、行号或 secret hash；
- HOME、绝对路径、credential value；
- receipt qualification、claim 或 spec IDs；
- “secret-free”“safe-to-export”“release-ready”等超出证据边界的结论。

`aggregate_sha256` 的输入为 domain prefix `ai-auto-lrc/secret-scan/v1\0` 加 canonical compact JSON 编码后的 `{files,errors}`；inspection 完整文件的 SHA-256 另由 `COMPLETE` 和 event 绑定。

### 4.5 `COMPLETE` 与 event

`COMPLETE` exact keys：

```json
{
  "inspection_id": "...",
  "inspection_sha256": "64hex",
  "state": "SCANNED_PASS"
}
```

event exact keys：

```text
schema, schema_version, sequence, previous_event_sha256,
event_type, from_state, to_state, run_id, receipt_sha256,
assessment_sha256, actor_claim, actor_assurance, occurred_at, details
```

第一个 event 必须是 sequence 1、`previous_event_sha256=null`、`event_type="INSPECTION_COMMITTED"`、`from_state="LOCAL_SEALED"`，to state 只能是 `SCANNED_PASS` 或 `SCANNED_BLOCKED`。`details` exact keys：`inspection_id,inspection_sha256,completion_sha256,rules_sha256,error_codes,matched_rule_ids`；两组 ID 排序且唯一，不含 hit 内容。

`actor_assurance` 在 v1 固定为 `self-asserted-local`。`actor_claim` 只是经过字符集和敏感词检查的本地调用者标签，不是认证 principal，不能用于批准 export、archive、restore、expire 或 destroy。未来如需认证身份，必须升级 schema 和 verifier，不得重新解释 v1 字段。

event 文件名为 `00000001-<event-file-sha256>.json`。event 内容不包含自身 hash，避免哈希环。

## 5. 安全读取与全闭包扫描

### 5.1 前置顺序

`inspect_run()` 必须按固定顺序执行：

1. 对 receipt、rules、assessment 和可选 repo root 做无 symlink component 的路径预检；
2. stable-read rules 和 assessment 原始 bytes，strict parse 并校验相互 hash 绑定；
3. 打开 sealed run fd，并调用 `capture_test_gate.verify_receipt_at(run_fd, receipt_name, mode, repo_root_fd)`；
4. 从已验证 document 取得 `run_id`/layer，但不读取 qualification 作为授权；
5. 推导 `sealed_root=receipt.parent`、`retention_root=sealed_root.parent` 和 control path；
6. 获取 run lock；锁内重新执行步骤 2–4，避免 TOCTOU；
7. 验证 ledger 为空且没有已提交 inspection；
8. 枚举并扫描完整 closure；
9. 发布 inspection；
10. 发布 event，作为最终提交点。

receipt、rules、assessment schema 本身无效时直接失败且不发布 inspection。配置已有效后发生的 file limit、file mutation、matcher runtime 或 closure safety 错误应形成 `SCANNED_BLOCKED` 报告；无法安全确定 run/control target 的错误不得写控制层。

### 5.2 inventory 与文件身份

- 从 sealed root 递归枚举所有目录项；路径按 canonical POSIX relative path 排序且唯一。
- 每层目录与最终文件使用 `lstat()`；任何 symlink 或非目录父项失败。
- 最终项必须为普通文件，且 `st_nlink == 1`；FIFO、socket、device、目录 hardlink/异常 inode 均拒绝。
- inventory 集合必须与 `verify_receipt_at()` 已接受的闭包一致；不得排除 dotfile 或按扩展名过滤。
- scanner 不读取 `.control`，因为它是 sealed root 的同级目录，不属于事实闭包。

### 5.3 每文件 stable-read

1. `lstat(path)` 保存 `(dev,ino,mode,nlink,size,mtime_ns,ctime_ns)`；
2. 用 `O_RDONLY|O_NOFOLLOW` 打开；平台没有 `O_NOFOLLOW` 时仍以 open 前后 identity 比较 fail closed；
3. `fstat(fd)` 必须与步骤 1 完全一致；
4. size 超过 assessment limit 时不读部分内容，记录 `SCAN_LIMIT_EXCEEDED` 并 blocked；
5. 固定 `chunk_bytes` 流式读取；同一数据流同时更新 SHA-256 和 matcher；
6. matcher 保留 `max_pattern_width-1` overlap，命中换算成文件绝对 byte offset并去重，防止跨 chunk 漏检或重复；
7. EOF 后 `fstat(fd)`，关闭后再次 `lstat(path)`；全部 identity 必须一致；
8. 实际读取 byte count 必须等于初始 size；否则 `FILE_CHANGED_DURING_SCAN`。

任何一步失败都不能保留已计算 hash 当作可信值，也不能用 `errors="replace"` 解码后继续报 pass。

### 5.4 全局资源上限

当前实现固定以下上限，任何调用方都不能通过 CLI 放宽：

| 预算 | 固定值 | 语义 |
|---|---:|---|
| `MAX_RUN_ENTRIES` | 4096 | 一棵 sealed run 目录树允许观察的目录项总数；目录和普通文件都计数 |
| `MAX_RUN_FILES` | 4096 | 一个 sealed run 可进入扫描记录的普通文件总数 |
| `MAX_RUN_BYTES` | 1 GiB | 一个 sealed run 的普通文件声明总字节数 |
| `MAX_RUN_SNAPSHOT_METADATA_BYTES` | 512 KiB | 初始/复验 tree snapshot 的 compact JSON 元数据预算 |
| `MAX_TOTAL_HITS` | 2048 | 全 run 共享的物化 hit 上限，不是逐文件上限 |
| `MAX_REPORT_METADATA_BYTES` | 512 KiB | 文件元数据、错误与命中结构的有界预算 |
| `MAX_REPORT_BYTES` | 1 MiB | `secret-scan.json` 的最终序列化上限 |

hit 上限在物化时执行；达到上限后保留已经记录的有界 hit，并加入 `SCAN_HIT_LIMIT_EXCEEDED`，结果只能是 `SCANNED_BLOCKED`。report 超限必须在 event 提交前失败。S14 已把 entry、file、declared bytes 与 snapshot metadata 四种预算前移到递归枚举和排序之前；同一个 `_SnapshotBudget` 跨整棵树共享，迭代器在 cap+1 立即停止，只有预算内的有界列表会进入排序。初始 snapshot、二次 snapshot 和 `_scan_tree()` 都重新执行预算，不得只信任第一次通过结果。

### 5.5 current-source 平台边界

Linux 使用 `/proc/self/fd/<repo-fd>` 把 Git 与工作树读取锚定到已打开的 repository fd。macOS 使用 `F_GETPATH` 恢复路径，并在读取前后复验 `(dev,ino)`；这能发现持续性的父路径换位，但不能排除读取期间发生并恢复的 swap/ABA。Git 的 `rev-parse`、`diff`、`status`、`ls-files` 与文件枚举也是多次顺序观察，不构成一个事务级文件系统快照。

S15 要求 current-source verifier 连续完成两次完整 observation；两次完整结果不同即返回 `CURRENT_SOURCE_OBSERVATION_UNSTABLE`，相同后才允许与 receipt 的 captured source 比较。CLI 的有效结论固定为 `diagnostic-current-source-observation`、`transactional=false`、`aba_excluded=false` 与 `observation_model=sequential-double-observation`。程序化 verifier 返回的仍是原 receipt document，其中保存的 qualification 不是本次 current-source 验证的 effective qualification，调用方不得据此升级声明。

retention report schema v1 无法持久表达上述限制，因此 `inspect --mode current-source` 在任何 receipt、配置、路径或 `.control` I/O 前以 `CURRENT_SOURCE_DIAGNOSTIC_ONLY` 拒绝；已有 artifact 的 `verify-inspection --mode current-source` 仍允许只读诊断。它不证明工作树在整个验证区间从未变化，不证明 gate 运行期间没有瞬态修改后恢复，也不构成 source/checkpoint 独立恢复、生产资格或 Release 证明。

## 6. 控制层事务、并发与恢复

### 6.1 布局

```text
<retention-root>/.control/<run-id>/
  LOCK
  events/
    00000001-<event-sha256>.json
  inspections/
    <inspection-id>/
      secret-scan.json
      secret-rules.json
      retention-assessment.json
      COMPLETE
```

`.control`、run control、events、inspections 和 staging 目录必须是 `0700`；LOCK、JSON 与 marker 必须是 `0600`。最终验证不仅检查权限不宽于目标值，而是检查精确 mode，并拒绝 symlink/hardlink。

### 6.2 锁

- 用 `os.open(..., O_CREAT|O_RDWR|O_NOFOLLOW, 0o600)` 打开固定 `LOCK`，复验 regular、`nlink=1` 和 mode；
- Unix/macOS/Linux 使用 `fcntl.flock(fd, LOCK_EX|LOCK_NB)`；锁竞争返回 `CONTROL_LOCKED`，不等待、不写 staging；
- 持锁范围覆盖二次 receipt/config 复验、ledger 校验、扫描、inspection/event 发布；
- LOCK 文件可以永久存在，锁语义由 descriptor 决定，不用删除文件模拟解锁。

### 6.3 发布顺序

1. `mkdir` exclusive 创建 `inspections/.incomplete-<inspection-id>`；
2. 以 `O_EXCL` 写 `secret-scan.json`，flush + `fsync(file)`；
3. 以 `O_EXCL` 写 `COMPLETE`，绑定 inspection hash，flush + `fsync(file)`；
4. `fsync(staging-dir)`；
5. 同文件系统 rename 为 `inspections/<inspection-id>`；
6. `fsync(inspections-dir)`；
7. 构造 sequence 1 event，在 `events/.incomplete-...` 以 `O_EXCL` 写入并 fsync；
8. rename 到最终 hash 文件名，`fsync(events-dir)` 和 run control dir；
9. 重新读取并验证 report、marker、event、mode；成功后才返回。

event 是提交点。步骤 5 成功、步骤 8 失败时，inspection 是 orphan：

- 不进入有效 ledger 状态；
- `verify-inspection` 必须因缺少有效 event 拒绝；
- 不修改原 run；
- v1 不自动删除 orphan，保留供人工核查；再次 inspect 因存在 orphan 应返回 `CONTROL_RECOVERY_REQUIRED`，避免静默堆积或覆盖。

## 7. verifier 责任

`verify_inspection()` 不能只比 hash，必须独立执行：

1. 复验 rules/assessment strict schema 和原始 bytes hash；
2. 调用 `verify_receipt_at()`，相对调用方已打开的 run fd 复验 SEALED 和完整 receipt closure；
3. 验证 inspection/control-event 都位于同一推导 control root，路径链无 symlink；
4. 验证目录/文件权限、普通文件、`nlink=1`；
5. 验证 COMPLETE 绑定 inspection bytes；
6. 从 sequence 1 开始重算全部 event 文件名 hash、previous hash、连续 sequence 和合法 transition；
7. 验证指定 event 唯一绑定指定 inspection、receipt、rules 和 assessment；
8. 重新扫描 sealed closure，比较 files、hits、errors、aggregate 和派生 state；
9. 验证 `export_allowed=false` 且报告不含禁止字段；
10. current-source 模式再次由 receipt verifier 绑定当前 checkout。

verifier 不信任 report 中的 classification、state、rule IDs 或 file hash；都必须重算。

## 8. 稳定错误模型

| code | 条件 | 是否可提交 blocked report |
|---|---|---|
| `RECEIPT_INVALID` | receipt/SEALED/archived/current-source 验证失败 | 否 |
| `CURRENT_SOURCE_DIAGNOSTIC_ONLY` | retention schema v1 尝试发布 current-source inspection；必须在任何 control I/O 前拒绝 | 否 |
| `CURRENT_SOURCE_OBSERVATION_UNSTABLE` | capture verifier 的两次完整 current-source observation 不一致 | 否；retention verifier 对外归一为 `RECEIPT_INVALID` |
| `RULE_SCHEMA_INVALID` | rules exact schema 或静态 matcher 无效 | 否 |
| `ASSESSMENT_SCHEMA_INVALID` | assessment exact schema/类型/值无效 | 否 |
| `ASSESSMENT_NOT_SAFE` | assessment 试图启用 inspect/scan 之外能力或填入治理决策 | 否 |
| `RULE_BINDING_MISMATCH` | assessment rule ID/hash 与实际 rules 不同 | 否 |
| `EXPECTED_DIGEST_INVALID` | expected digest 缺失、格式非法或与参数组合冲突 | 否 |
| `RULE_TRUST_MISMATCH` | rules 原始 bytes 与 expected digest 不同 | 否 |
| `ASSESSMENT_TRUST_MISMATCH` | assessment 原始 bytes 与 expected digest 不同 | 否 |
| `RULE_SET_ID_MISMATCH` | rules 与 assessment 的 rule-set ID 不同 | 否 |
| `CLOSURE_MISMATCH` | 多件、少件、路径集合不一致 | 是，前提是 run 已安全确定 |
| `UNSAFE_FILE_TYPE` | 非普通文件 | 是 |
| `SYMLINK_FORBIDDEN` | 任一路径组件或文件是 symlink | 视 target 是否已安全确定；不确定时否 |
| `HARDLINK_FORBIDDEN` | 普通文件 `nlink != 1` | 是 |
| `CLASSIFICATION_UNKNOWN` | path 无稳定分类 | 是 |
| `FILE_CHANGED_DURING_SCAN` | path/fd/final identity 或大小改变 | 是 |
| `SCAN_RULE_ERROR` | 有效 matcher 执行内部失败 | 是 |
| `SCAN_LIMIT_EXCEEDED` | 文件超 assessment limit | 是 |
| `SCAN_RUN_LIMIT_EXCEEDED` | 全 run 目录 entry 数、普通文件数、声明字节数或 snapshot/report 元数据预算超限 | 是 |
| `SCAN_HIT_LIMIT_EXCEEDED` | 全 run 物化命中达到固定上限 | 是，且结果只能 blocked |
| `REPORT_LIMIT_EXCEEDED` | report 在 event 提交前超过固定上限 | 否 |
| `SECRET_MATCHED` | 至少一个规则命中 | 是，正常 blocked 结果 |
| `CONTROL_LOCKED` | 同 run 有 publisher | 否 |
| `INSPECTION_ALREADY_COMMITTED` | v1 已有有效 inspection/event | 否 |
| `EVENT_SEQUENCE_INVALID` | 序号、文件名或状态转换非法 | 否 |
| `EVENT_HASH_CHAIN_INVALID` | previous hash 或 event hash 不一致 | 否 |
| `CONTROL_PUBLICATION_FAILED` | write/fsync/rename/mode/final verify 失败 | 否；已发布 inspection 可能为 orphan |
| `CONTROL_RECOVERY_REQUIRED` | staging、orphan、invalid ledger 或其他非空无效控制态 | 否；只读人工审计，不自动删除/修复 |
| `CONTROL_COMMIT_UNCERTAIN` | event 可能已可见后发生 fsync、source 或最终复验失败 | 否；禁止直接重跑，先独立核验 exact event/inspection |
| `NO_REPLACE_UNSUPPORTED` | 平台没有安全的原子 no-replace rename primitive | 否；fail closed，不使用普通 rename fallback |
| `INSPECTION_INVALID` | marker/report/event/重扫比较失败 | 否 |
| `COMMAND_NOT_SUPPORTED` | 代码层收到未支持 action | 否；argparse 不注册该 action |

错误消息只描述字段或 canonical relative path。底层异常通过 `raise ... from error` 保留给 Python 调用方，但 CLI 必须消毒后输出。

## 9. QA RED 测试计划

首个改动必须是 `tests/contract/test_evidence_retention.py` 的 RED；实现提交不得与首批测试设计混在一起。fixture 可以复用 `test_evidence_capture.py` 的 fake repository/capture 思路，但应在新文件建立最小 helper，禁止测试依赖另一个 test module 的私有函数。

### 9.1 fixture

| fixture/helper | 责任 |
|---|---|
| `sealed_run_factory(layer="portable")` | 创建临时 Git repo 和真实 sealed capture，返回 repo/retention/receipt；不得手工伪造一个绕过 verifier 的 run |
| `rules_factory(**mutation)` | 从冻结有效 rules deep copy 后进行单一 schema/matcher 变异 |
| `policy_factory(**mutation)` | 自动绑定实际 rules hash；默认 assessment/non-operational |
| `rewrite_sealed_file(path, bytes)` | 显式临时放宽 mode、变异并恢复所需父目录，只用于 receipt/scan 反证 |
| `fault_injector(point)` | monkeypatch write/fsync/rename/open/read 的单一提交点，断言原 run hash/mode 不变 |
| `assert_no_secret(material, *outputs)` | 同时检查 stdout、stderr、report、event 和 exception message 不含 sentinel |

### 9.2 第一批：schema、API 和命令边界

| ID | 建议 nodeid | 核心断言 |
|---|---|---|
| RET-T01a | `test_ret_t01_rules_reject_missing_unknown_and_wrong_typed_keys` | exact-key、bool-as-int、空 rules 失败 |
| RET-T01b | `test_ret_t01_policy_rejects_missing_unknown_and_wrong_typed_keys` | 所有嵌套对象 exact-key |
| RET-T01c | `test_ret_t01_rules_reject_duplicate_or_unsorted_ids_and_terms` | 输出顺序不可由 parser 悄悄修复 |
| RET-T08a | `test_ret_t08_rules_reject_regex_glob_script_and_oversized_terms` | 不存在任意执行 matcher |
| RET-T12a | `test_ret_t12_assessment_policy_requires_explicit_null_owners` | assessment 合法且不可 operational |
| RET-T12b | `test_ret_t12_operational_or_placeholder_policy_is_rejected` | manager 不接受自报 operational |
| RET-T03a | `test_ret_t03_policy_must_bind_exact_rules_bytes` | 解析等价但 bytes 不同也需更新 hash |
| RET-T19a | `test_ret_t19_parser_exposes_only_inspect_and_verify_inspection` | forbidden subcommands 均无法解析 |

### 9.3 第二批：receipt、closure 与 scanner

| ID | 建议 nodeid | 核心断言 |
|---|---|---|
| RET-T02a | `test_ret_t02_inspect_calls_receipt_verifier_before_scanning` | 无 SEALED/篡改 receipt 时无 control publication |
| RET-T02b | `test_ret_t02_current_source_requires_repo_and_rejects_drift` | 两种 mode 保持既有边界 |
| RET-T04a | `test_ret_t04_rejects_symlink_hardlink_fifo_socket_and_device` | 每种类型独立参数化；不打开特殊文件 |
| RET-T05a | `test_ret_t05_rejects_extra_missing_and_duplicate_closure_entries` | exact closure，不漏 dotfile |
| RET-T05b | `test_ret_t05_rejects_path_fd_or_final_identity_change` | open 前、读取中、读取后三个竞态点 |
| RET-T06a | `test_ret_t06_utf8_credentials_block_without_echoing_material` | token/HOME/PEM 命中，所有输出脱敏 |
| RET-T07a | `test_ret_t07_binary_sentinel_across_chunk_boundary_is_detected` | 非 UTF-8 + 跨 chunk 命中 |
| RET-T07b | `test_ret_t07_overlap_deduplicates_same_hit` | byte range 精确、唯一 |
| RET-T08b | `test_ret_t08_limit_and_matcher_runtime_errors_cannot_pass` | hash 为 null、errors 非空、state blocked |
| RET-T09a | `test_ret_t09_every_regular_closure_file_has_one_scan_record` | receipt/SEALED/inputs/logs/source/artifacts 全覆盖 |
| RET-T28a | `test_ret_t28_report_has_exact_keys_and_no_qualification_claims` | 禁止字段无法出现 |

### 9.4 第三批：事务、事件与独立复验

| ID | 建议 nodeid | 核心断言 |
|---|---|---|
| RET-T14a | `test_ret_t14_existing_inspection_or_event_is_never_overwritten` | v1 单 inspection；碰撞失败 |
| RET-T15a | `test_ret_t15_fault_before_inspection_rename_leaves_no_committed_state` | event 不存在，原 run byte/mode hash 不变 |
| RET-T15b | `test_ret_t15_fault_after_inspection_rename_leaves_detectable_orphan` | verifier 拒绝 orphan；重试不覆盖 |
| RET-T15c | `test_ret_t15_event_is_the_only_commit_point` | 只有 event 成功且 final verify 后 API 返回 |
| RET-T18a | `test_ret_t18_control_directories_and_files_have_exact_private_modes` | 0700/0600，过宽也失败 |
| RET-T22a | `test_ret_t22_ledger_rejects_duplicate_gap_bad_hash_and_bad_transition` | 每种 ledger 破坏独立参数化 |
| RET-T16a | `test_ret_t16_verify_rejects_tampered_report_marker_or_event` | 三类 hash binding |
| RET-T16b | `test_ret_t16_verify_rescans_and_rejects_later_sealed_byte_change` | 不能只验证旧 report hash |
| RET-T29a | `test_ret_t29_old_inspection_cannot_bind_new_receipt_rules_or_assessment` | 防跨 run/旧规则重放 |
| RET-T03b | `test_ret_t03_concurrent_inspect_has_one_committer` | 一个成功/blocked commit，另一个 CONTROL_LOCKED 或 already committed |
| RET-T30a | `test_ret_t30_result_never_changes_receipt_qualification_or_release_gate` | report/event 不出现 claim/spec/qualification |

### 9.5 CLI contract

| ID | 建议 nodeid | 核心断言 |
|---|---|---|
| RET-CLI-01 | `test_cli_pass_emits_one_sanitized_json_line_and_exit_zero` | stdout 无绝对路径 |
| RET-CLI-02 | `test_cli_secret_match_commits_blocked_and_exits_three` | stderr/stdout 不含 sentinel |
| RET-CLI-03 | `test_cli_known_failure_is_single_line_sanitized_and_exit_one` | 无 traceback、HOME、control char |
| RET-CLI-04 | `test_cli_current_source_argument_contract_is_strict` | mode/repo-root 组合精确 |
| RET-CLI-05 | `test_cli_forbidden_commands_exit_two_without_side_effects` | export/archive/destroy 均不存在 |

## 10. 实施 DAG 与任务卡

### PR/批次 A：QA RED 与 schema fixtures

允许修改：

- 新增 `tests/contract/test_evidence_retention.py`；
- 新增两个 packaging JSON；
- 必要的文档链接。

完成条件：

- schema/parser/API/forbidden-command 测试以“模块或能力缺失”的预期原因 RED；
- rules/assessment fixture 可被人工审查，且不含 credential、绝对路径和已决治理值；
- 不新增 export/archive/destroy 实现。

回滚：删除新测试与 fixtures，不影响 capture。

### PR/批次 B：safe I/O、schema 与 scanner

实现 RET-C01–C06，不发布控制层。先让 schema、closure、chunk boundary、binary-safe、redaction 测试转绿。

完成条件：

- 每个普通 closure 文件恰好一个 record；
- 跨 chunk、非 UTF-8、hardlink、特殊文件、三阶段 mutation 和 size limit 反证全绿；
- 内存复杂度为 `O(chunk_bytes + hit metadata)`，不得按文件大小整文件读入；
- hit metadata 可配置总上限；达到上限产生 blocked error，不能无限占用内存。

回滚：删除 manager；sealed capture 不受影响。

### PR/批次 C：control transaction 与 ledger

实现 RET-C07/C08：锁、private modes、inspection/marker/event 原子发布和 orphan 检测。

完成条件：

- fault injection 覆盖每个 write/fsync/rename 边界；
- 同 run 并发最多一个提交者；不同 run 可并行；
- 任一失败前后 sealed run 的 tree hash 和 mode inventory 完全一致；
- event 是唯一提交点，orphan 不可被误认。

回滚：停止调用 manager；保留 `.control` 审计件，不自动删除。

### PR/批次 D：independent verifier 与 CLI

实现 RET-C09/C10，补齐 CLI subprocess tests 和整套 `RET-T01–T30` 中属于 5a/5b 的映射。

完成条件：

- verifier 重扫，不只信任 hash；
- parser 只有两个子命令；
- stdout/stderr/exception secret hygiene 通过；
- 全量静态、合同与现有 capture 回归通过。

回滚：Python inspection records 仍可保留，CLI 入口可独立撤回；不触碰 capture。

## 11. 验证命令与证据保存

实现阶段建议按成本递增执行：

```bash
uv run pytest -q tests/contract/test_evidence_retention.py
uv run pytest -q tests/contract/test_evidence_capture.py tests/contract/test_evidence_retention.py
uv run ruff check scripts/manage_evidence_retention.py tests/contract/test_evidence_retention.py
uv run pytest -q tests/unit tests/contract
uv run pytest -q
```

若 `scripts` 未纳入当前 coverage source，不能用总 coverage 百分比代替 retention 测试证据；应保存稳定 nodeid 清单、通过/失败数和 failure injection case IDs。真实 inspection 必须使用仓库外、路径链无 symlink 的 retention root；macOS 不使用 `/tmp`，而使用经显式核对的 `/private/tmp/...`。

## 12. Go/No-go

W1b-5a/5b 只有同时满足以下条件才是 Go：

- 两个 schema 文件、manager 和测试真实存在；
- 上述 5a/5b 测试全部通过，无 xfail/skip 冒充完成；
- 至少一次无命中 `SCANNED_PASS` 和一次 binary sentinel `SCANNED_BLOCKED` 的真实本地 run 被独立 `verify-inspection` 复验；
- 全部 control 输出均为 private mode，原 sealed run tree hash/mode 前后不变；
- CLI inventory 证明不存在 forbidden commands；
- 文档仍明确 export、archive、expiry/destruction、独立恢复和 Release 为 No-go。

以下任一情况保持 No-go：

- assessment 复用 operational schema/mode，或任一治理决策不是 unresolved/null；
- scan error、limit、truncation 或 unknown classification 被当作 pass；
- report、stderr 或 event 回显 secret/绝对路径；
- inspection 没有 event 仍被视为有效；
- 只跑 unit mock，没有真实 sealed capture；
- 用 W1b-5 局部绿测提升 canonical/release 资格。

## 13. 等待人类决策的后续工作

在 `D-REL` 明确签收三类 owner、保留期限、允许导出的 classification/purpose、approval TTL/人数、加密 provider、key custody/rotation、RPO/RTO、checkpoint 内容寻址策略、销毁与 tombstone 规则前：

- W1b-5c local export：**不实现**；
- W1b-5d encrypted archive/restore：**不实现**；
- W1b-5e expiry/destruction：**不实现**；
- 任何 upload、CI artifact、对象存储、Git/issue 同步：**不实现**。

后续若获得决策，应先新增 ADR 和新的 QA RED，不直接扩展本批 parser。特别是 destructive command 必须放入独立工具和独立评审，不能追加到 capture runner 或本批只读 manager。

## 14. 接手清单

后续代理开始实现前必须逐项确认：

- [ ] 阅读上位方案第 19 节与本文件，不从聊天记录猜 schema；
- [ ] `git status --short`，保护当前 dirty worktree 和其他角色改动；
- [ ] 确认 `scripts/manage_evidence_retention.py`、两个 packaging JSON、retention tests 的真实状态；
- [ ] 先看 QA RED 的失败原因，避免实现与测试合同错位；
- [ ] 优先复用 `verify_receipt_at()`，保留 Path API 兼容，不耦合 capture 私有 helper；
- [ ] 保持 parser 只有 `inspect`/`verify-inspection`；
- [ ] 每批运行定向测试和 capture 回归；
- [ ] 记录真实命令、case 数、run state 和独立 verify 结果；
- [ ] 不把 assessment 结果写成 operational、exportable、recoverable 或 release-ready。

## 15. 2026-09-06 实施快照与二次反审

本节是后续接手的事实入口；第 0–14 节仍是目标合同。当前代码已经完成一版
assessment-only `inspect`/`verify-inspection`，但布局、schema 与安全边界尚未全部
收敛到目标合同，因此不得依据首轮绿测把 W1b-5a/5b 标记为 Go。

### 15.1 当前已存在的实现与证据

- 实现：`scripts/manage_evidence_retention.py`；
- 配置：`packaging/evidence-secret-rules.json`、
  `packaging/evidence-retention-assessment.json`；
- 合同测试：`tests/contract/test_evidence_retention.py`；
- 首轮定向结果：`47 passed`；Ruff、compileall 与 `git diff --check` 通过；
- 真实 canonical receipt 已执行一次 assessment，得到 `SCANNED_BLOCKED`：
  245/245 文件被记录，12 个文件、18 个 finding，CLI/verify 均为 blocked；
- 该结果只证明首版实现按首版规则发现了命中，不能证明控制包可信、secret-free、
  可导出、可归档或 release-ready。

### 15.2 Teams 共识：必须先关闭的阻断项

| 优先级 | 阻断项 | 当前风险 | 目标状态 |
|---|---|---|---|
| P0 | 全路径父链安全 | receipt、retention、assessment、rules、control 的祖先 symlink 可改变实际读写位置 | 任何读写前逐组件 `lstat`；控制层尽量采用 descriptor-relative open/create，并在发布前后复验父目录 identity |
| P0 | rules/assessment 信任锚 | verifier 可信任一套被整体替换的弱规则与自洽 hash | control 包保存原始 canonical bytes 快照；CLI verifier 仍接收外部 expected rules/assessment，逐字节 hash 绑定，禁止只信内部链 |
| P0 | 最终 TOCTOU | 最后一次 source snapshot 与 publish/return 之间仍可变化 | publish 前、event commit 前、commit 后返回前各做 source closure/identity 复验；变化时不得返回有效 inspection |
| P0 | 规则内容泄漏 | `pattern_base64` 可逆保存规则 pattern | report 仅保存 rule ID、matcher/kind 与规则集 hash；原始规则只进入独立 private snapshot，不进入 scan report/event/CLI |
| P0 | 资源耗尽 | 整文件 join 与任意 Python regex 可造成内存放大或灾难回溯 | v1 移除任意 regex；只用第 4.1 节有界 matcher；扫描前按 `st_size` 拦截超限并流式 hash/match |
| P1 | 原子提交 | 固定目录 check-then-rename 可覆盖竞态目标，event 不是唯一提交点 | inspection 使用唯一 ID 发布；hash-named event 以 no-replace 语义最终提交；orphan 可识别且不自动删除 |
| P1 | 锁与权限 | 临时 lock 哨兵、宽松 mode/owner 检查不足 | 永久 `LOCK` + 持 fd `flock`；目录精确 0700、文件精确 0600，校验 uid、nlink 与无 symlink |
| P1 | schema/binding | manifest/report/event 的类型、时间、actor、hash 与嵌套 exact keys 未完全闭合 | 每层 exact schema；拒绝 bool-as-int；所有 ID、时间、hash、状态、actor claim 与 source/config binding 交叉验证 |
| P1 | 分类与闭包 | `source/*.patch` 可误归 metadata；未知路径可能默认 artifact；超限仍声称 complete | `source/**` 固定 `source-raw`；未知分类 blocked；未完整读取时 `closure.complete=false` 且不得报 pass |
| P1 | CLI 证据边界 | stdout 暴露绝对路径，blocked 退出码与冻结合同不一致 | stdout 仅 `run_id/inspection_id/state`；blocked=3；错误单行脱敏；parser 仅两个子命令 |

`actor` 是本地调用者自报标签，不是认证身份或审批。目标 schema 必须将其表达为
`actor_claim`，或同时记录 `actor_assurance="self-asserted-local"`，且不得作为未来
export/archive/destruction 的授权来源。

### 15.3 冻结后的可执行重构切片

后续必须按以下顺序推进；每个切片先新增失败合同并确认 RED，再改实现到 GREEN：

1. **Slice S1 — schema/config trust**：冻结 assessment/rules exact schema，移除
   `regex-bytes` 和 report 内的 `pattern_base64`；新增两个 config snapshot，并把外部
   expected hash 接入 verifier。
2. **Slice S2 — path + bounded I/O**：实现祖先无 symlink 检查、stable descriptor read、
   size-before-read、有界流式 matcher；覆盖 literal/assignment/scheme 跨 chunk 命中。
3. **Slice S3 — report correctness**：修正全闭包、classification、limit/error/complete
   语义，收紧 report 每层 exact schema 与排序/唯一约束。
4. **Slice S4 — control transaction**：迁移到
   `run-control/{LOCK,inspections/,events/}`；用 `flock`、唯一 inspection、原子 no-replace
   hash event 和 fsync 链建立唯一提交点。
5. **Slice S5 — independent verifier**：从外部 rules/assessment 信任锚重新加载并重扫；
   验证 config snapshot、report、COMPLETE、event、receipt/SEALED 与源树前后 identity。
6. **Slice S6 — CLI + regression**：实现冻结 CLI/退出码/脱敏 JSON；跑定向、capture
   回归、全量宿主、静态检查与真实 pass/blocked receipt。

### 15.4 必加测试矩阵

| 组 | 必加反证 |
|---|---|
| 路径 | receipt parent symlink；assessment/rules parent symlink；`.control`/run-control parent symlink；词法路径不能逃逸 retention root |
| 配置 | checked-in assessment/rules 原始 bytes hash 一致；外部 expected hash 与 snapshot/manifest/report/event 全绑定；弱规则整包重写失败 |
| 扫描 | 大文件在累积前停止；literal、assignment、scheme 跨 chunk；非 UTF-8；hit 去重与总量上限；禁止任意 regex |
| 竞态 | open 前、读取中、读取后、inspection publish 前、event commit 前、commit 后 source mutation 均不能返回有效结果 |
| 事务 | 并发仅一提交者；已有目标绝不覆盖；inspection orphan 无 event 时无效；event 名称/hash/sequence/transition 破坏失败 |
| schema | source/scanner/assessment/closure/file/finding/manifest/marker/event 的缺键、增键、错型、bool-as-int、非法 ID/time/hash |
| 权限 | control 任一级 symlink/hardlink/owner 不符/目录非 0700/文件非 0600 均失败 |
| CLI | checked-in defaults；pass=0；blocked=3；failure=1；argparse=2；stdout/stderr 单行 JSON 且不含 secret、HOME、绝对路径 |
| 漂移 | source patch 全归 `source-raw`；未知路径 blocked；超限/读取失败使 `complete=false`；原 sealed run bytes/mode 前后不变 |

### 15.5 本轮允许修改与禁止事项

允许修改仅限 manager、两份 assessment/rules 配置、retention 合同测试，以及第 0 节列出的
本地文档。不得删除或覆盖已有真实 `.control` 记录；重新做真实验证时必须生成新的
canonical receipt。

继续禁止：`prepare-export`、upload/sync、archive、expire、prune/destroy、CI、签名、发布、
自动清理、commit 与 push。W1b-5c/5d/5e、macOS cold install、Demucs 离线权重/许可、
独立 checkpoint/source 恢复、SBOM/attestation/signing/rollback 未完成，Release 保持
**No-go**。

## 16. S7–S11 前的加固版实施结果与反审（历史检查点）

本节保留 69-node 阶段的历史证据和当时决策，已由第 17 节取代，不能再作为当前恢复入口。

### 16.1 已实现且已验证的增量

本轮已经把首版四文件 control package 重构为 assessment-only 两阶段控制面：

- assessment 与未来 operational policy 分 schema/API；当前文件固定为
  `evidence-retention-assessment.json`，16 项治理决策全部 unresolved/null；
- rules 改为四种有界 ASCII matcher，不再执行任意 regex，也不在 report/event 中保存
  `pattern_base64`；默认 assignment terms 补齐 `token/api_key/apikey/secret/password/
  credential/access_key/private_key`；
- scanner 在读取前检查单文件大小，流式 hash/match，支持跨 chunk 命中；
- control 包保存 rules/assessment 原始 bytes 私有快照；verifier 重新加载调用方提供的
  外部配置并独立重扫 sealed closure；
- control 使用永久 `LOCK + flock`、0700 目录、0600 文件、唯一 inspection 与
  hash-named event；macOS 使用 `renameatx_np(RENAME_EXCL)`，Linux 使用
  `renameat2(RENAME_NOREPLACE)`；
- CLI 只暴露 `inspect`/`verify-inspection`，PASS=0、BLOCKED=3、已知失败=1、
  argparse=2，stdout 不输出绝对路径。

主线程独立验证结果：

```text
retention + capture contracts: 200 passed
host full suite:              550 passed, 18 skipped, 22 warnings
retention nodeids:            69 passed, 0 skipped, 0 xfail
real sealed PASS verify:      exit 0
real sealed BLOCKED verify:   exit 3
ruff / compileall / JSON / diff-check: PASS
```

18 个 skip 仍是既有 13 个 canonical-only golden 与 5 个未注入 wheelhouse 的 package
gate，不能解释为 release 零 skip。真实 verify 使用本轮测试生成但由实际
`capture_test_gate.capture_gate()` 封存的两个独立 run。current-source 证据根为
`/private/tmp/ai-auto-lrc-w1b5-current.yOJORt/`，规则原始 bytes SHA-256 为
`ab396187f0e53e26d9eb63cd3d4051a3103233b0cc4154d1199248247398df3c`；run IDs 为：

```text
PASS    20260906T095234057670Z-f8511a13273b442da38033b9d4198212
BLOCKED 20260906T095234492518Z-07186967d8ed4bfe8000f67da08e85be
```

### 16.2 最终 Teams 反审仍未关闭的 P0

尽管上述测试全绿，W1b-5a/5b 仍不得标 Go：

1. **父目录 identity 未固定**：祖先只做逐次 `lstat`；后续 open/mkdir/rename/flock
   仍是 path-based。静态 symlink 负例不能排除“检查后替换父目录”的竞态。S7 必须
   用 dirfd/openat 风格解析，或持有并逐层复验父目录 `(dev,ino,uid,mode,nlink)`；
   source/config/control 的所有敏感 I/O 都必须相对已验证 descriptor 执行。
2. **缺少独立 expected digest**：外部 rules/assessment 仍只是调用方选择的可变路径。
   弱规则与自洽 assessment 可以从头产生 PASS。S8 必须要求调用方提供独立保存的
   `expected_rules_sha256` 与 `expected_assessment_sha256`，并绑定 rules 的
   `rule_set_id` 与 assessment scanner 的 `rule_set_id`；内部 snapshot/hash 不能自证。
3. **全局 hit/report 上限未闭合**：实测单文件 11,050 个 literal 命中时，report 为
   2,222,008 bytes；当前先提交 inspection/event，再因 verifier 的 1 MiB 读取上限失败，
   留下已提交但无法复验的控制态。S9 必须在命中物化前执行全 run 上限，在 event 前
   验证 report 大小与自复验可读性，且发布失败不得被下次运行误报为 committed。
4. **特殊文件竞态未闭合**：sealed leaf 在 `lstat` 后、`open` 前被替换为 FIFO 可能阻塞；
   hardlink/FIFO/socket/device、owner UID 与 scanner identity 三阶段尚无完整反证。

### 16.3 下一批唯一执行顺序

| Slice | 实现 | 必须先新增并确认 RED 的测试 |
|---|---|---|
| S7 descriptor paths | root-to-leaf dirfd walker；openat/O_NOFOLLOW；父目录 identity pin；control 相对 fd mkdir/open/rename/fsync | parent-swap race；leaf swap to symlink/FIFO；before-open/during-read/after-read identity；wrong owner/hardlink/FIFO/socket/device |
| S8 external trust root | inspect/verify 强制 expected rules/assessment digest；rule-set ID 交叉绑定；明确 digest 的离线权威来源与轮换方式 | weak-rules-from-start false PASS；equivalent JSON bytes drift；rule ID/hash mismatch；snapshot 与 expected digest 全链重绑 |
| S9 global boundedness | 全 run file/byte/hit metadata/report byte 上限；matcher 在物化前截断；event 前执行同一 reader 的 self-check | 11,050-hit reproduction；多文件累计上限；report 上限不提交；hit 截断仍 blocked 且可复验 |
| S10 transaction recovery | event 发布后的 ledger 验证；区分 committed、invalid event 与 orphan；unsupported no-replace fail closed | write/fsync/rename fault matrix；ghost commit；orphan 重试；fallback platform；duplicate/gap/bad transition/rehashed invalid event |
| S11 contract completion | current-source 参数组合、真实并发、精确 offsets、path/actor secret hygiene | inspect/verify × archived/current-source/repo-root；两个 publisher；overlap offset；secret filename/actor claim |

### 16.4 当时 Gate（已由第 17 节取代）

- W1b-5a：**No-go / hardening required**（S8 expected digest 与 rule-set ID 交叉绑定未闭合）；
- W1b-5b：**No-go / hardening required**（S7、S9、S10、S11 未闭合）；
- W1b-5c/5d/5e：**blocked-by-D-REL / 未实现**；
- Release：**No-go**。

`69 passed` 只作为该历史实现的回归基线。S7–S11 后续已经实施；当前状态、残余风险和
下一位接手者的唯一执行顺序见第 17 节。

## 17. S7–S11 实施后当前事实与下一批执行方案

本节是 W1b-5a/5b 的唯一当前事实入口。第 15–16 节保留首版和 69-node 阶段的历史，不能用来恢复当前代码或 Gate。

### 17.1 已实施的 S7–S11

| Slice | 已实现内容 | 当前证据 | 仍不能声称 |
|---|---|---|---|
| S7 descriptor paths | manager 的 root-to-leaf dirfd walker、目录 `O_DIRECTORY|O_NOFOLLOW`、leaf `O_NOFOLLOW|O_NONBLOCK`、父目录换位与特殊文件反证；capture 新增稳定公共 API `verify_receipt_at()` | parent swap、symlink、FIFO、socket、hardlink、owner/mode、before/during/after-read identity 合同已绿 | device fixture、control fd 在整个事务内始终绑定同一 inode、macOS current-source 原子快照 |
| S8 external trust root | 默认 rules/assessment raw bytes digest 编译进代码；自定义 path 必须提供 expected digest；rules/assessment rule-set ID 与 SHA 双绑定 | 弱规则从起点替换、等价 JSON 字节漂移、ID/hash mismatch 反证已绿 | digest 的治理 owner、签名 trust store 或供应链授权已经建立 |
| S9 global boundedness | 4096 files、1 GiB、2048 hits、512 KiB metadata、1 MiB report 固定上限；hit 在物化时截断；report 在 event 前检查 | 单文件 11,050 hits、多文件累计、report 超限、独立 verifier 重扫已绿 | 超大目录树在枚举/字典物化前已经限流 |
| S10 transaction recovery | macOS `renameatx_np(RENAME_EXCL)`、Linux `renameat2(RENAME_NOREPLACE)`；无安全 primitive 时 fail closed；ledger 区分 empty/staging/orphan/valid/invalid；event 后失败引入 `CONTROL_COMMIT_UNCERTAIN` | write/fsync/rename fault、orphan、unsupported no-replace、duplicate/gap/bad transition/rehashed invalid event 已绿 | control 目录锚贯穿事务；event 可能可见后的所有失败已统一归类 uncertain；自动恢复已实现 |
| S11 contract completion | archived/current-source 参数矩阵、两个 publisher 并发、overlap 精确 offset、敏感 filename 与 actor claim hygiene | 参数、并发、offset、CLI/报告脱敏合同已绿 | `actor_claim` 是认证身份；current-source 排除瞬态 swap/ABA 或 Git 多命令间漂移 |

### 17.2 RET-C01–C10 能力闭合度

| 能力 | 现行细节 | 状态 | 下一验收条件 |
|---|---|---|---|
| RET-C01 rules loader | exact-key schema、四种有界 matcher、排序唯一、ASCII term、raw-byte digest；默认 digest 为 `ab396187f0e53e26d9eb63cd3d4051a3103233b0cc4154d1199248247398df3c` | 技术闭合 | 指定默认 digest owner、轮换审批与记录位置后才可形成治理闭环 |
| RET-C02 assessment loader | assessment-only、16 项决策全为 unresolved/null、危险 capability 为 false；默认 digest 为 `78f67c28156916d443f45a246ddfef2d693a3319f28ffb5e185e6fdf6a7a54f3` | 技术闭合 | 同 RET-C01；不得把完整性 hash 当授权 |
| RET-C03 receipt adapter | archived 模式相对 run fd 读取 receipt、SEALED、logs、source、inputs 与 artifacts；Path API 兼容并委托 fd-aware verifier | archived 闭合；current-source 部分闭合 | macOS swap/ABA 与 Git 多观察点漂移测试通过，或把该模式明确降级为观察性诊断 |
| RET-C04 closure inventory | closure 排序唯一；实现拒绝非普通文件/目录、hardlink、错误 owner、可写 sealed node 与 identity 漂移；symlink/FIFO/socket 已有直接反证 | 文件安全基本闭合；device 与资源部分未闭合 | 增加 Linux device 反证，并在递归枚举写入全量 dict 前执行文件数/元数据预算 |
| RET-C05 byte scanner | binary-safe 流式 hash/scan、跨 chunk overlap、0-based `[start,end)`、全 run hit 上限；失败只能 blocked | 闭合 | 保持现有合同，不新增 regex/glob/script |
| RET-C06 inspection builder | report/event 不保存匹配原文、上下文、secret hash、绝对路径或 qualification；敏感 basename 不可逆脱敏 | 闭合 | schema 变更必须先新增 exact-key RED |
| RET-C07 control publisher | private mode、`LOCK+flock`、staging、文件/目录 fsync、唯一 inspection、原子 no-replace event | 部分闭合，P0 | 持有同一组 control/run/inspections/events fd 贯穿锁、ledger、write、rename、fsync 和 final verify |
| RET-C08 ledger verifier | 可确定区分 `EMPTY`、`STAGING_PRESENT`、`ORPHAN_INSPECTION`、`LEDGER_INVALID`、`COMMITTED_VALID` | 验证闭合；恢复未实现且未授权 | 完成人工只读处置 runbook；不得自动删除、补 hash 或覆盖重试 |
| RET-C09 independent verifier | 重载外部配置、复验快照与 expected digest、重扫 sealed closure、复算 report/marker/event/ledger | archived 基本闭合；受 RET-C07/current-source 边界限制 | 关闭事务锚 P0，并锁死 event 可见后的错误语义 |
| RET-C10 CLI boundary | 仅 `inspect`、`verify-inspection`；pass=0、blocked=3、known failure=1、argparse=2；stdout/stderr 脱敏 | 闭合 | 禁止增加 export/archive/destroy 的别名或等价 Python API |

### 17.3 当前可复验测试证据

2026-09-06 主线程在当前共享 dirty worktree 上实际执行：

```text
retention contract:            125 passed
capture contract:              135 passed
retention + capture:           260 passed in 88.21s
host full suite:               610 passed, 18 skipped, 22 warnings in 145.79s
ruff:                          PASS
compileall:                    PASS
rules/assessment JSON parse:   PASS
compiled digest vs raw bytes:  PASS
git diff --check:              PASS
```

18 个 skip 仍由 13 个 canonical-only golden 和 5 个未注入 `AI_AUTO_LRC_WHEELHOUSE` 的 package gate 构成；它们不能被解释为 package、双平台或 Release 资格。

合同测试分组和剩余风险：

| 分组 | 当前结果 | 关键场景 | 尚未覆盖 |
|---|---:|---|---|
| 原 RET-T01–T30 | 69 passed | schema、scanner、两阶段提交、ledger、CLI 基线 | 只证明旧合同回归 |
| S7 | 20 passed | parent swap、特殊文件、三阶段 identity、owner/mode | 事务级 control ABA、device 与部分 config owner 组合 |
| S8 | 4 passed | custom expected digest、弱规则、字节漂移、rule-set 绑定 | digest 发布、保管和轮换治理 |
| S9 | 3 passed | 11,050 hits、多文件全局 cap、oversize report | `MAX_RUN_FILES`、`MAX_RUN_BYTES`、真实 metadata 上限 |
| S10 | 11 passed | inspection/event fault、orphan、no-replace、invalid ledger | event/run fsync、进程崩溃、完整 duplicate/staging 矩阵 |
| S11 | 18 passed | mode 参数、checkout drift、双线程 publisher、offset、hygiene | 双进程竞争；secret filename 的真实 CLI subprocess |
| capture fd-aware | 135 passed | run/repo fd、SEALED symlink/FIFO、checkout drift、SIGTERM | macOS `F_GETPATH` 的 transient swap/ABA；Linux 分支实机资格 |

可直接复验的命令：

```bash
uv run --frozen --no-sync python -m pytest -q -p no:cacheprovider \
  tests/contract/test_evidence_retention.py \
  tests/contract/test_evidence_capture.py

uv run --frozen --no-sync python -m pytest -q -p no:cacheprovider

uv run --frozen --no-sync ruff check \
  scripts/manage_evidence_retention.py \
  scripts/capture_test_gate.py \
  tests/contract/test_evidence_retention.py \
  tests/contract/test_evidence_capture.py

uv run --frozen --no-sync python -m compileall -q \
  scripts/manage_evidence_retention.py \
  scripts/capture_test_gate.py \
  tests/contract/test_evidence_retention.py \
  tests/contract/test_evidence_capture.py

shasum -a 256 \
  packaging/evidence-secret-rules.json \
  packaging/evidence-retention-assessment.json

git diff --check
```

### 17.4 最新真实 sealed PASS 与 BLOCKED 复验

测试控制仓库由真实 `capture_test_gate.capture_gate()` 封存，retention CLI 使用 checked-in defaults 创建控制包，随后主线程再次独立执行 `verify-inspection`。证据根：

```text
/private/tmp/ai-auto-lrc-w1b5-final-20260906-01/
```

| 状态 | run ID | inspection ID | verify exit | sealed tree signature 前后 |
|---|---|---|---:|---|
| PASS | `20260906T102647633323Z-a7c8b2386c964600a2382c52b494ac93` | `cd56eaa47daa4b7fa25ea6f75cdd4b84` | 0 | `ba895c357a2574a58e7b3f4ff5dd150408b77dbfda886092d1d50f8afb20b2eb`，不变 |
| BLOCKED | `20260906T102648245827Z-71bbbc6f191241f6b39ba76b100371f5` | `a510b09c85934a078d54f8973384efd0` | 3 | `39659951cf33b07dd38f404520f7e6c2c4c94cbd1f2ddb7ca48f959303525a74`，不变 |

该证据证明当前代码能创建并复验有界的本地 assessment 结果，且复验不改变 sealed tree 的文件 bytes/mode/closure；它不是 canonical、跨平台、独立恢复或 Release 证明。

### 17.5 Teams 最终反审与下一批 RED

S7–S11 已实现不等于架构闭合。第三次 Teams 反审保留以下两个 P0 和三个 P1：

1. **P0 control transaction anchor**：`_directory_fd()` 能安全完成一次解析，但 mkdir/list/write/fsync/rename 会分别从 Path 重新打开。`LOCK` 可能锁住旧 inode，而后续操作进入同 UID 替换后的 control tree，形成 lock split。
2. **P0 event commit uncertainty**：原子 event rename 成功后，target post-stat、temporary cleanup、target mode check、events/run fsync、source check 或 final verify 仍可能失败；只要 event 可能已可见，错误必须单向收敛为 `CONTROL_COMMIT_UNCERTAIN`。当前若 post-stat 或 `_private_file()` 失败，仍可能误报普通 publication failure。
3. **P1 tree enumeration bound**：文件数与总字节上限在完整 snapshot dict 形成后才检查；超大目录树仍可能先消耗过量内存。
4. **P1 current-source snapshot**：macOS `F_GETPATH` 与多次 Git/文件观察不是原子快照，不能排除 swap-and-restore/ABA。
5. **P1 governance**：默认 digest 的 owner、轮换审批、ADR/审计记录位置尚未由人类签收。

下一批必须按以下可执行顺序实施，每个切片先确认 RED，再改实现：

| Slice | 生产改动 | 新增测试场景 | 通过准则 |
|---|---|---|---|
| S12 transaction fd context | 一次打开并持有 retention/control/run/inspections/events fd 与 identity；锁、ledger、staging、rename、fsync、final verify 全部相对这些 fd | 获取 flock 后替换 `run_control`；逐级替换 control/inspections/events；同 UID 攻击者创建同名树 | 不写替代树；原事务失败关闭；无第二提交者；原 sealed run 不变 |
| S13 commit state machine | 在 rename syscall 返回成功的瞬间设置 `event_may_be_visible=True`；所有后置失败统一映射 uncertain；cleanup 不得覆盖主异常 | event rename 成功后注入 post-stat、temp unlink、target mode、events fsync、run fsync、source check、final verify 失败 | 每个场景只允许 `CONTROL_COMMIT_UNCERTAIN`；ledger 可被只读 verifier 明确分类；不得返回 committed success |
| S14 pre-materialization bounds | 遍历过程中递增检查 entry/file/metadata/byte 预算，不先构造无界 snapshot | 超过 4096 entry 的浅层和深层树；大量长 basename；目录在枚举期间增长 | 达到预算即 fail closed；内存随固定预算有界；不发布 event |
| S15 current-source adversarial | 抽象平台 anchor；记录观察 epoch；若无法提供事务语义则在合同中明确 diagnostic-only | macOS `F_GETPATH` 父路径 swap/restore；Git 子命令之间修改再恢复；文件枚举 ABA | 能稳定检测则失败；无法检测的场景必须从 qualification 条件排除并在 receipt/report 中明示 |
| S16 process crash + concurrency | 用两个独立 subprocess 竞争同一 run；在 staging、inspection rename、event rename、events/run fsync 后强制终止 | 双进程同时发布；每个 crash point 后重新启动只读检查 | 最多一个有效 commit；staging/orphan/uncertain 分类稳定；不得把崩溃后的控制态误报成功 |
| S17 CLI and ownership completion | 补齐真实 CLI subprocess、rules/assessment special-file/owner、Linux device fixture | secret filename/HOME/control chars；config hardlink/FIFO/socket/wrong owner；Linux device | stdout/stderr 不泄漏；危险输入在 control write 前失败；无副作用 |
| S18 qualification matrix | 为两个安全脚本建立独立 branch/关键函数 coverage；在 Linux 实跑 260；package/canonical 使用各自 required runner | coverage gate、Linux `renameat2`/`/proc/self/fd`、零 skip package/canonical | 各层证据独立保存且零意外 skip；不得用 macOS 260 代替 Linux 或发布资格 |

现有 `test_ret_t05_source_mutation_around_commit_never_returns_valid_inspection` 对 after-event-commit 仍允许多个错误码，不能证明 S13。必须新增“一旦可能可见只能 uncertain”的精确断言，不得仅扩大允许集合。

### 17.6 trust-root 轮换与人工恢复 runbook

默认 trust root 是代码中固定的两个 raw-byte SHA-256，不是签名或审批。任何默认 rules/assessment 更新必须在同一个受审改动中同步：配置原始 bytes、assessment 中的 `rule_set_id/rule_set_sha256`、代码常量、合同 fixtures、本文 digest 和一份决策记录。必须由人类补齐 `rules digest owner`、`assessment digest owner`、`rotation approver`、`rotation record/ADR path`；在此之前，W1b-5a 只能是受信本地脚本前提下的 conditional Go。

遇到控制态异常时只允许只读判断：

| 观察状态 | 稳定结果 | 操作边界 |
|---|---|---|
| 无 inspection/event | `EMPTY` | 可正常执行一次 inspect |
| 仅 staging | `STAGING_PRESENT` / `CONTROL_RECOVERY_REQUIRED` | 保存现场并人工审计；不自动删除或重试覆盖 |
| inspection 无 event | `ORPHAN_INSPECTION` / `CONTROL_RECOVERY_REQUIRED` | 用 receipt、inspection、expected digests 和相同 mode 做只读核验；不把它登记为 committed |
| event 可能已发布但最终步骤失败 | `CONTROL_COMMIT_UNCERTAIN` | 定位 exact event/inspection 后运行 `verify-inspection`；在结论明确前不得再次 inspect |
| event/inspection 完整有效 | `COMMITTED_VALID` / `INSPECTION_ALREADY_COMMITTED` | 读取既有结果；不创建第二个 sequence 1 |
| event、sequence、transition 或 hash 语义无效 | `LEDGER_INVALID` / `CONTROL_RECOVERY_REQUIRED` | 人工升级；不改 hash、不补 event、不删历史 |

本 runbook 只定义诊断与升级路径，不授权自动修复、删除、归档或恢复。自动恢复 API 仍不存在。

### 17.7 当前 Gate 与禁止边界

- W1b-5a：**Conditional Go / local assessment-only**。strict schema、bounded matcher、默认 digest 和交叉绑定已实现；治理 owner、轮换批准与签名 trust store 未闭合。
- W1b-5b：**No-go / hardening required**。本地功能与 125-node 合同有效，但 S12 control transaction anchor 与 S13 commit uncertainty 两个 P0 未关闭。
- W1b-5c/5d/5e：**blocked-by-D-REL / 未授权 / 未实现**。
- Release：**No-go**。

继续禁止 `prepare-export`、export、upload/sync、archive/restore、expire、prune/destroy、orphan 自动清理、CI、签名、发布、commit 和 push。独立 checkpoint/source 恢复、macOS/双平台 cold install、完整资源预算、Demucs、runtime close、SBOM、attestation 和 rollback 仍由上位计划单独关闭，不能由 W1b-5 局部绿测替代。

## 18. S12/S13 第一批实现、第四次 Teams 反审与续接方案

本节是 S12/S13 的当前事实源；第 17.4 节的 PASS/BLOCKED receipt 生成于本批代码之前，只保留为 S7–S11 历史证据。S12/S13 完全关闭前必须用最新代码重新生成两类 receipt 并独立复验。

### 18.1 已实施的生产改动

`scripts/manage_evidence_retention.py` 已完成第一批 control transaction 加固，未改变公共 Python API、CLI 子命令、JSON schema 或文件布局：

- 在获得 flock 前打开并持有 `run_control`、`inspections`、`events` 三个目录 fd；
- transaction 内 `_directory_fd()` 通过 active context 锚定到已打开的控制目录，不再把后续读写重定向到同 UID replacement tree；
- 在 flock 后及 inspection/event 提交边界复验外部 namespace identity；
- no-replace event rename syscall 成功返回时、任何 post-stat 前设置 commit latch；
- post-stat、temporary unlink、target mode、events/run fsync 和 final verify 失败统一映射为 `CONTROL_COMMIT_UNCERTAIN`；
- event 可见前临时件清理为 best-effort，不覆盖主异常；macOS 仍使用 `renameatx_np(RENAME_EXCL)`，Linux 仍使用 `renameat2(RENAME_NOREPLACE)`，没有普通 rename fallback。

这证明核心修复进入真实生产调用链，但实现尚未满足第 17.5 节原定的完整 fd context：retention/control 父级没有作为独立 pin 保存，`inspections/events` 初始化仍分别从绝对 Path 打开，而不是从 pinned `run_control_fd` 相对打开。

### 18.2 contract-first RED 到当前 GREEN

新增 9 个精确 nodeid：

| 组 | 场景 | 精确期望 | 当前结果 |
|---|---|---|---|
| S12 | flock 后立即替换 `run-control` | replacement inspections/events 保持空；`CONTROL_PUBLICATION_FAILED` | GREEN |
| S12 | flock 后立即替换 `inspections` | replacement 不接收 inspection/event；`CONTROL_PUBLICATION_FAILED` | GREEN |
| S12 | flock 后立即替换 `events` | replacement 不接收 event；`CONTROL_PUBLICATION_FAILED` | GREEN |
| S13 | event rename 后 target post-stat 失败 | `CONTROL_COMMIT_UNCERTAIN` | GREEN |
| S13 | event rename 后 temporary unlink 失败 | `CONTROL_COMMIT_UNCERTAIN` | GREEN |
| S13 | event rename 后 target mode check 失败 | `CONTROL_COMMIT_UNCERTAIN` | GREEN |
| S13 | event rename 后 events fsync 失败 | `CONTROL_COMMIT_UNCERTAIN` | GREEN |
| S13 | event rename 后 run fsync 失败 | `CONTROL_COMMIT_UNCERTAIN` | GREEN |
| S13 | event rename 后 final verify 失败 | `CONTROL_COMMIT_UNCERTAIN` | GREEN |

主任务在锁定环境独立复验：

```text
S12/S13 targeted: 9 passed, 125 deselected in 3.88s
retention + capture: 269 passed in 58.95s
host full suite: 619 passed, 18 skipped, 22 warnings in 113.84s
ruff: PASS
compileall: PASS
git diff --check: PASS
```

18 个 skip 仍为 13 个 canonical-only golden 与 5 个未注入 `AI_AUTO_LRC_WHEELHOUSE` 的 package case；它们不能被 619 个通过项吸收，也不构成 Release 资格。

### 18.3 四角色判断与明确分歧

| 角色 | 判断 | 阻断理由 |
|---|---|---|
| PM | W1b-5b 继续 No-go | S14–S18、trust-root owner/rotation approver 和最终 Go 签署未闭合；局部 9 GREEN 不能晋级工作包 |
| Architect | S12/S13 完整关闭 No-go | child fd 未从 pinned parent 相对打开；final verifier 返回后缺 control namespace 复核；teardown 异常可能绕过 uncertain 分类 |
| Developer | 第一批实现可回归 | 三个 pinned fd、active context 和 rename commit latch 已进入生产调用链；公共接口和 no-replace 平台分支保持不变 |
| QA | 已声明的 3+6 合同 Go，完整矩阵 No-go | 只覆盖 flock 后立即换位；缺中后段换位、post-event 全出口、teardown、crash 和 uncertain artifact 恢复验证 |

尚有一个必须冻结的语义分歧：event 已完成 directory durability 和 independent verify 后，如果仅 `LOCK_UN`、lock fd close 或 context close 失败，究竟应当抑制并记录为已提交成功，还是仍返回 `CONTROL_COMMIT_UNCERTAIN`。在新增合同前不得由实现自行选择。为保持第 17.5 节“一旦 event 可能可见，后续任何失败只允许 uncertain”的强合同，本方案默认采用后者，除非人类通过 ADR 明确批准新的 committed-but-cleanup-failed 状态。

### 18.4 S12a/S13a 必须先补的精确 RED

| ID | 故障注入点 | 必须断言 | 预期稳定码 |
|---|---|---|---|
| RET-S12A-01..03 | context 初始化时在 run/child open 之间替换 `run-control`、`inspections`、`events` | child 必须属于 pinned parent；replacement 不接收写入 | `CONTROL_PUBLICATION_FAILED` |
| RET-S12A-04..06 | ledger 后、staging 前替换三类控制目录 | replacement 与 displaced tree 都需计数；不得静默转向 replacement | `CONTROL_PUBLICATION_FAILED` |
| RET-S12A-07..09 | inspection publish 后、event write 前替换三类控制目录 | replacement 不接收 event；orphan 保留供只读恢复 | `CONTROL_PUBLICATION_FAILED` |
| RET-S12A-10..12 | event rename 后、post-event check 前替换三类控制目录 | event/inspection 已可能可见，不得返回 success | `CONTROL_COMMIT_UNCERTAIN` |
| RET-S12A-13..15 | final verify 中途、当前最后一次 namespace check 之后替换三类控制目录 | return 前必须再次绑定 control namespace；返回 Path 不得指向未核验 replacement | `CONTROL_COMMIT_UNCERTAIN` |
| RET-S13A-01 | post-event control namespace check 失败 | 精确单码，不用允许集合 | `CONTROL_COMMIT_UNCERTAIN` |
| RET-S13A-02..03 | final verify 前、后的 source check 失败 | 精确单码 | `CONTROL_COMMIT_UNCERTAIN` |
| RET-S13A-04..06 | `LOCK_UN`、lock close、context exit 分别失败 | 不得泄漏 raw `OSError` 或降级为 publication failure | 默认 `CONTROL_COMMIT_UNCERTAIN`，ADR 可改 |
| RET-S13A-07 | fault 撤销后独立验证 uncertain artifact | filename/content hash、private mode、inspection linkage、ledger/retry 分类全部稳定 | verify success 或精确 `CONTROL_RECOVERY_REQUIRED` |
| RET-S13A-08 | 精确 API/CLI/layout golden | `inspect_run`/`verify_inspection` 签名、仅两个子命令、`INSPECTION_FILES` 与布局不漂移 | 无兼容性差异 |

测试不能只断言 replacement 为空：还必须检查被移走的原控制树，防止实现先完整提交到旧 inode、最后才报错却被误判为安全。event 可见后的场景必须验证真实 artifact 和后续只读分类，不能只数目录项。

### 18.5 最小生产修正顺序

1. 扩充 context 为 parent-child 绑定：先 pin retention/control/run，再用 `openat(run_fd, "inspections"/"events")` 打开子目录；逐级核对 `fstat(child_fd)` 与 `stat(name, dir_fd=parent_fd, follow_symlinks=False)` 的 identity。
2. 保持 transaction I/O 只使用 pinned fd；Path 仅用于入参、诊断显示和最终返回，不再作为 control I/O authority。
3. final verifier 返回后、构造 `InspectionResult` 前再次执行 control namespace binding；验证函数内部不得混用 pinned 文件读取和当前 Path `.lstat()`。
4. 将 event visibility phase 提升到 inspect transaction 级别，使 post-event namespace/source/final verify 和 teardown 都在同一错误边界内。
5. 按冻结语义处理 unlock/close/context-exit；cleanup/close 错误不得覆盖已经存在的业务异常；所有 fd 在正常、异常、锁竞争和 context 初始化中断路径逆序关闭。
6. 通过 S12a/S13a 后再进入原 S14–S18；不得用本轮 134 节点跳过资源界限、macOS/Git ABA、双进程 crash、真实 CLI/ownership、Linux/coverage qualification。

### 18.6 当前 Gate

- S12 三个 flock 后立即换位合同：**Go**。
- S13 六个 post-event 故障分类合同：**Go**。
- 原 125 retention 节点兼容性：**Go**。
- S12/S13 完整事务和故障矩阵：**No-go / S12a-S13a required**。
- W1b-5a：**Conditional Go / checked-in defaults + trusted local assessment-only**。
- W1b-5b：**No-go / hardening required**。
- W1b-5c/5d/5e：**未授权、未实现**。
- Release：**No-go**。

禁止边界不变：不自动删除、清理、导出、上传、归档、恢复、签名、创建 CI、commit、push 或发布。

## 19. S12a–S15 实施后唯一当前恢复入口与 S16–S18 执行方案

本节取代第 18 节作为 W1b-5a/5b 的唯一当前事实入口。第 15–18 节和其中的 47、69、125、134、200、260、269、550、610、619 等数字继续保留为历史检查点，不得静默覆盖；下一位维护者不得重新实施 S1–S15。第 17.4 节的 PASS/BLOCKED receipt 生成于 S12–S15 之前，只能作为历史 evidence，不能证明当前代码。

### 19.1 已实施的能力事实

| Slice | 已进入生产代码的能力 | 直接合同 | 仍未证明 |
|---|---|---|---|
| S12a control fd generation | `inspections/events` 从 pinned `run_control_fd` 相对打开；child identity 与同一个当前 run fd 复核；final verifier 后、API return 前再次核对 control namespace | S12a/S13a 共 5 个精确节点；API signature、CLI 命令清单、目录布局、0600/0700 权限均锁定 | standalone verifier 的全路径 pin、nlink generation、移除 `ContextVar` 隐式依赖、真实进程 crash |
| S13b teardown state | event-visible phase 延伸到 teardown；`LOCK_UN`、lock-fd close、context exit 独立执行；主业务异常优先 | 2 个 teardown 节点；event 已可见且仅 teardown 失败固定为 `CONTROL_COMMIT_UNCERTAIN`，未可见固定为 `CONTROL_PUBLICATION_FAILED` | 掉电后的 durability；自动恢复仍不存在且未授权 |
| S14 pre-materialization budget | 新增 `MAX_RUN_ENTRIES=4096` 与 `MAX_RUN_SNAPSHOT_METADATA_BYTES=512 KiB`；共享 `_SnapshotBudget` 同时约束 entry/file/declared bytes/metadata；`scandir` 流式消费并在 cap+1 停止 | 10 个节点：浅/深树共享预算、file/byte/metadata 独立边界、exact-cap、lazy iterator、4096/4097 真实 OS、两次 snapshot 增长、inspect 超限无 `.control` | adversarial memory/RSS benchmark 不在本切片；不能把有界枚举写成完整运行时资源资格 |
| S15 diagnostic current-source | exact 校验 `source.observation_limit`；连续两次完整 source observation；不一致返回 `CURRENT_SOURCE_OBSERVATION_UNSTABLE`；CLI 强制 diagnostic 字段 | S15 transition slice 19 个节点；capture 142、retention 154；archived inspect/verify 回归保持 | macOS `F_GETPATH` swap/restore、Git 子命令间 ABA、独立进程 system case；transactional/ABA-excluded/qualification 均未实现 |

兼容性表述必须精确：receipt/report/event 的 schema version、公共函数 signature、目录布局和 no-replace primitive 保持不变；但 current-source CLI JSON 增加了明确限制字段，retention current-source inspect 从可接受改为稳定拒绝。这是有意的公共行为变化，不能写成“所有公共合同零变化”。

### 19.2 当前验证事实与 flaky 记录

2026-09-06 在当前共享 dirty worktree 上已得到：

```text
S12a/S13a targeted:                  5 passed
S13b teardown targeted:              2 passed
S14 targeted:                       10 passed
S15 transition targeted:            19 passed, 277 deselected
capture contract full:             142 passed
retention contract full:           154 passed
capture + retention retry:         296 passed in 69.54s
host full after S15/docs:           646 passed, 18 skipped, 22 warnings in 123.64s
ruff/compileall/diff/link checks:   PASS
```

第一次 capture+retention 联合运行得到 `1 failed, 295 passed`：`test_ret_t03_verifier_requires_external_config_trust_anchors` 期望 `RULE_BINDING_MISMATCH`、实际得到 `ASSESSMENT_SCHEMA_INVALID`。该节点单独运行通过，capture 全文件后再运行也通过，随后同一联合命令重跑为 `296 passed`。这必须作为潜在顺序依赖/flaky evidence 保留；一次重跑成功不能抹掉首次失败。若再次出现，先使用 `--lf -vv` 和确定的收集顺序定位共享状态泄漏，再允许继续 Gate。

S15 与文档落盘后的宿主全量已实跑为 `646 passed, 18 skipped, 22 warnings in 123.64s`；四文件 Ruff、compileall、`git diff --check` 和本批文档相对链接检查均通过。最后一个 S15 前的 `634 passed` 继续作为历史检查点。18 个已知 skip 仍为 13 个 canonical-only golden 与 5 个缺 wheelhouse 的 package gate，不能被通过数吸收。

最新代码生成的独立 evidence 位于 `/private/tmp/ai-auto-lrc-w1b5-final-20260906-02/`：

| 状态 | run ID | inspection ID | event | inspect/verify exit | sealed tree signature 前后 |
|---|---|---|---|---:|---|
| PASS | `20260906T121354206779Z-7695fdb3f20f4a82860ce50466c8b66d` | `d03dcfa0c111419da5f0bf22298ed301` | `00000001-8e29f0d9a3763b3333562c91203a3017941539de02ecd87c53ad1336e12800d4.json` | `0 / 0` | `575028a3f66fb803a62c4ef658ffd812adea2029d8fabadc4d24cf5e392abe05`，不变 |
| BLOCKED | `20260906T121354206777Z-0cfb37137ccf42af8303b21fc73b1463` | `dbd8d2449ab34512ace4a6ba38f2ef6a` | `00000001-bd7c16f1f1ac2c6870fb9482c6abe1f28db544b324bbf53ce6ea9e5c651f51f8.json` | `3 / 3` | `c99edd6d6419c0ed30ccbb4246af07d1461157c204462e6b7bafed8bf412e7f8`，不变 |

两份 run 均由真实 `capture_gate` 封存，再由 retention CLI 使用 checked-in defaults 创建 inspection/event，最后由独立 CLI 调用复验。它证明当前代码的 local archived assessment 与 sealed-tree 不变性，不证明 current-source transaction、power-loss durability、跨平台、恢复或 Release。

### 19.3 S15 的精确 Go/No-go

| 范围 | Gate | 可作出的最大声明 |
|---|---|---|
| capture current-source CLI | Go / diagnostic-only | 两次顺序 observation 一致，且当前 aggregate 与 captured source 一致 |
| retention current-source inspect | No-go / frozen | schema v1 无法诚实表达限制，因此禁止发布 artifact |
| 已有 artifact 的 current-source verify | Go / diagnostic-only | 只读复验；返回 document 中的 qualification 不能解释为本次有效资格 |
| archived inspect/verify | Go / local historical integrity | 封存字节和绑定关系的历史完整性 |
| transactional snapshot / ABA exclusion / source restorability | No-go | 不得声称已证明 |
| W1b-5a | Conditional Go | checked-in defaults + trusted local assessment-only；不含治理/签名授权 |
| W1b-5b | No-go / hardening required | 等待 S16–S18 与最新 evidence 闭合 |
| W1b-5c/5d/5e | 未授权、未实现 | 不得创建 export/archive/destroy 或等价 API |
| Release | No-go | 本工作包的局部绿色不能晋级 release |

S15 尚有三个明确 P1：

1. `verify_receipt()`/`verify_receipt_at()` 仍返回原 receipt document；后续应新增 additive typed outcome 或在公共文档锁死 effective assurance，不能篡改已封存 document。
2. `source` 当前校验 `observation_limit` 的值，但没有拒绝全部未知 key；应先加 RED，拒绝附带 `transactional:true`、`aba_excluded:true` 等自相矛盾字段，或冻结 unknown keys 不具声明语义。
3. 两次 observation 之间的变化可检测；单次 observation 内完整发生并恢复的 ABA 不可检测。真实 macOS/Git/system tests 未通过前，这一限制不能关闭。

### 19.4 S16 独立进程并发、崩溃与恢复分类

目标不是“进程没报错”，而是在真实 subprocess 终止和竞争后，磁盘上最多存在一个有效 commit，且只读 verifier 能稳定分类每一种残留状态。先写 RED，再改生产代码；不得用 thread test 代替 process test。

| ID | 安排与故障点 | 必须断言 |
|---|---|---|
| RET-S16-01 | 进程 A 持有 flock 并由 barrier 暂停，进程 B 对同一 run 执行 inspect | B 精确 `CONTROL_LOCKED`；B 不创建 staging/inspection/event |
| RET-S16-02 | 两个独立进程由 barrier 同时竞争并允许任一者先获得锁 | 最多一个进程获得有效 commit；loser 只允许由实际时序决定的 `CONTROL_LOCKED` 或 `INSPECTION_ALREADY_COMMITTED`；两个 success 禁止 |
| RET-S16-03 | staging 文件和目录已 fsync 后 SIGKILL publisher | 重启只读分类为 `STAGING_PRESENT`/`CONTROL_RECOVERY_REQUIRED`；不自动删除、不重试覆盖 |
| RET-S16-04 | inspection no-replace rename 与 inspections-dir fsync 后、event 创建前 SIGKILL | 精确识别 `ORPHAN_INSPECTION`/`CONTROL_RECOVERY_REQUIRED`；不得登记 committed |
| RET-S16-05 | event no-replace rename 后、events-dir fsync 前 SIGKILL | 重启只按实际存在的完整 bytes 分类；存在且全量复验通过才可 `COMMITTED_VALID`，否则 recovery-required；不得根据父进程 marker 猜成功 |
| RET-S16-06 | events-dir fsync 后、run-dir fsync 前 SIGKILL | 同上，并单独记录此测试只模拟 process crash，不冒充真实 power-loss durability |
| RET-S16-07 | run-dir fsync 后、API return/teardown 前 SIGKILL | 独立 verifier 证明唯一 event/inspection linkage、hash、mode、sequence；重试不得生成 sequence 1 的第二份 commit |
| RET-S16-08 | 对每个 crash fixture 连续运行两次只读 verifier | 分类和错误码稳定，验证本身零写入；sealed run tree signature 不变 |

实现只允许增加测试注入 seam 和必要的状态分类修正；不得新增自动清理/恢复。退出条件：S16 全部 required 节点在 macOS 宿主通过；process-crash 与 power-loss 的声明分开；全量 retention/capture 无新增 flaky。

### 19.5 S17 CLI、ownership 与特殊文件完成

| ID | 输入/动作 | 必须断言 |
|---|---|---|
| RET-S17-01 | 真实 CLI subprocess，run/actor/filename 含 HOME、控制字符与 sentinel secret | exit/stdout/stderr 精确；无绝对路径、secret、匹配原文或 traceback 泄漏 |
| RET-S17-02 | rules/assessment 分别替换为 hardlink、FIFO、Unix socket | 在任何 `.control` 写入前 fail closed；FIFO 不阻塞；sealed run 不变 |
| RET-S17-03 | rules/assessment owner 错误或 mode 过宽 | 精确配置错误；不创建 staging/inspection/event |
| RET-S17-04 | Linux required runner 提供 block/char device fixture | `UNSAFE_FILE_TYPE`；无 skip、无 control 副作用 |
| RET-S17-05 | public API/CLI 命令与参数 golden | 仍只有 `inspect`、`verify-inspection`；current-source inspect 精确 `CURRENT_SOURCE_DIAGNOSTIC_ONLY` |
| RET-S17-06 | capture receipt `source` 增加未知声明 key 或篡改 observation limit | verifier fail closed；不能把未知 key 当 qualification |

macOS 无法创建/安全使用 device fixture 时必须由 Linux required runner 关闭 RET-S17-04；宿主 skip 只能作为平台说明，不能标完成。退出条件：所有危险输入在 control write 前失败；CLI 输出脱敏；公共行为差异与错误码文档同步。

### 19.6 S18 qualification matrix 与证据刷新

1. 为 `scripts/manage_evidence_retention.py` 和 `scripts/capture_test_gate.py` 生成独立 line/branch coverage JSON；安全分支清单至少覆盖 path traversal、special file、owner/mode/nlink、budget cap、event visibility、teardown、no-replace、ledger/recovery 和两种 verify mode。清单中每一分支必须命中，不能仅用高 aggregate 百分比替代。
2. Linux 实机/受控 runner required 执行 `renameat2(RENAME_NOREPLACE)`、`/proc/self/fd`、device fixture、S16 双进程矩阵；意外 skip 数必须为 0。macOS 结果不能代替 Linux。
3. package 与 canonical 使用各自 required runner，分别报告 collected/passed/skipped/deselected；缺 wheelhouse 或专用环境必须保持 No-go，不能由宿主 18 skip 隐藏。
4. 文档落盘后重跑下面的本地命令，再以最新代码生成 PASS 与 BLOCKED 两个全新 sealed run，并从独立调用重新执行 `verify-inspection`。证据根必须位于仓库外；记录 run ID、inspection ID、退出码与 sealed-tree signature，receipt hash 不回写仓库形成 current-source 循环。

```bash
uv run --frozen --no-sync python -m pytest -q -p no:cacheprovider \
  tests/contract/test_evidence_retention.py \
  tests/contract/test_evidence_capture.py

uv run --frozen --no-sync python -m pytest -q -p no:cacheprovider

uv run --frozen --no-sync ruff check \
  scripts/manage_evidence_retention.py \
  scripts/capture_test_gate.py \
  tests/contract/test_evidence_retention.py \
  tests/contract/test_evidence_capture.py

uv run --frozen --no-sync python -m compileall -q \
  scripts/manage_evidence_retention.py \
  scripts/capture_test_gate.py \
  tests/contract/test_evidence_retention.py \
  tests/contract/test_evidence_capture.py

git diff --check
```

每条命令记录实际 exit code、时长、passed/skipped/warnings；任何 flaky、意外 skip、collection 差异或重跑后才成功都单列，不能只保留最后一次绿色。S18 退出后才能重新评审 W1b-5b；S18 本身不授权 5c/5d/5e 或 Release。

### 19.7 续接 DAG、停止条件与人类决策

```text
文档落盘 + S15 后静态检查/宿主全量（646）+ 最新 PASS/BLOCKED evidence（已完成）
  -> S16 process crash/concurrency
  -> S17 CLI/ownership/Linux special files
  -> S18 coverage/Linux/package/canonical qualification matrix
  -> W1b-5b Go/No-go 复审
  -> 仅在 D-REL 获批后，另行设计/实施 5c/5d/5e
```

每个 slice 的 rollback unit 仅包含该 slice 新增的生产代码和测试；当前大量 modified/deleted/untracked 文件是待保留成果，不得通过 reset、checkout、clean 或删除来“回滚”。遇到同一稳定 blocker 时保存命令、stderr、fixture 和磁盘分类，停止进入下一 slice；不得扩大允许错误集合来获得绿色。

仍需人类指定：rules digest owner、assessment digest owner、rotation approver、ADR/审计路径、W1b-5b Go signer、Linux/macOS required runner owner。未指定不阻止继续写 RED 和执行本地诊断，但阻止治理闭环与 Go 签收。

禁止边界保持不变：不 commit、push、创建 CI、上传、签名、发布、自动删除、清理、归档或恢复；不执行 W1b-5c export、5d archive、5e destruction；不修改或清理用户现有 dirty worktree。Release 保持 **No-go**。

## 20. S16 实施完成后的唯一当前恢复入口

本节取代第 19.4 节的“S16 尚待实施”状态，但不覆盖第 19 节中 S15、S17、S18、evidence 和禁止边界。下一位维护者不得重做 S1–S16；只从第 20.5 节的 S17 开始。

### 20.1 首轮 RED 与生产根因

真实独立进程 S16 首轮得到 `7 passed, 1 failed, 154 deselected`。唯一失败是 `test_ret_s16_two_subprocess_publishers_never_double_commit`：一个 publisher 正常生成唯一 inspection/event，另一个在 control tree 首次并发初始化中先后出现过 `SYMLINK_FORBIDDEN` 和 `CONTROL_PUBLICATION_FAILED`。临时仅测试 worker traceback 将直接原因定位为 `_open_lock()`：对 pinned `run_fd` 执行 `os.open("LOCK", O_CREAT|O_RDWR|...)` 时抛出 `FileNotFoundError(ENOENT)`。

这不是允许的竞争结局。loser 的稳定集合仍严格只有：

```text
CONTROL_LOCKED
INSPECTION_ALREADY_COMMITTED
```

不得把首轮错误加入允许集合，也不得用 retry-until-green、线程测试或 `sleep()` 掩盖。

### 20.2 最小生产修正

`_open_lock()` 现在在同一个 pinned run directory descriptor 上执行两阶段协议：

1. 先用 `O_RDWR|O_NOFOLLOW|O_CLOEXEC|O_CREAT|O_EXCL` 创建 `LOCK`；
2. 仅 `FileExistsError` 进入跟随者路径，并用不含 `O_CREAT` 的 flags 重开；
3. 其他 create/open/stat 错误统一 fail closed 为 `CONTROL_PUBLICATION_FAILED`；
4. flock 前核对打开 fd 与 `LOCK` 目录项的 `(dev, ino)`，并继续强制 regular、当前 uid、`0600`、`nlink=1`；
5. `LOCK_EX|LOCK_NB` 成功后再次在 pinned namespace 核对 `(dev, ino)`；只有真实锁竞争返回 `CONTROL_LOCKED`。

为合法并发初始化所需，目录 stat/open identity 比较忽略 `st_nlink` 的 child-count 变化，只比较 `(dev, ino, uid, mode)`；目录仍必须是当前 uid 和 `0700`。这不放宽文件的 `nlink=1` 合同。

生产 CLI、环境变量、配置和公共 API 中没有加入 crash switch。`tests/fixtures/retention_crash_worker.py` 只在独立测试进程 monkeypatch 现有私有 seam；临时 `--trace-errors` 和 traceback 输出已移除。

### 20.3 S16 已实现测试矩阵

| 节点 | 真实行为 | 精确结果 |
|---|---|---|
| lock contention | A 在真实 flock 后由 pipe barrier 暂停；B 为独立 CLI | B=`CONTROL_LOCKED`，零 staging/inspection/event；释放 A 后唯一 commit |
| two publishers | 两个 child 收齐 `before-start` token 后同时 GO | 精确一个 success；loser 仅 `CONTROL_LOCKED` 或 `INSPECTION_ALREADY_COMMITTED` |
| `staging-fsynced` + SIGKILL | staging 文件与目录完成 fsync 后由父进程发送真实 SIGKILL | `STAGING_PRESENT`；retry=`CONTROL_RECOVERY_REQUIRED` |
| `inspection-fsynced` + SIGKILL | inspection rename 与 inspections fsync 后终止 | `ORPHAN_INSPECTION`；retry=`CONTROL_RECOVERY_REQUIRED` |
| `event-renamed` + SIGKILL | event no-replace rename 返回后、events fsync 前终止 | `COMMITTED_VALID`；独立 verify 成功；retry=`INSPECTION_ALREADY_COMMITTED` |
| `events-fsynced` + SIGKILL | events fsync 后终止 | 同上；明确不等于 power-loss durable |
| `run-fsynced` + SIGKILL | run-control fsync 后终止 | 同上，且 inspection/event 各一 |
| `teardown-entered` + SIGKILL | 最终 verify 后、第一次 unlock 前终止 | kernel 释放 flock；同上，重试不产生第二 commit |

每个 crash fixture 都由两个 fresh classifier subprocess 连续读取，stdout 完全一致；classifier、独立 verifier 和 retry 前后 control tree signature 不变；sealed run tree signature 始终不变。父子同步使用 pipe/pass-fds 与 `select` 十秒 deadline，不使用时间猜测。

### 20.4 当前实测与声明边界

2026-09-06，Darwin 25.6.0 arm64、Python 3.11.4：

```text
双 publisher 原失败节点修复后：  1 passed, 161 deselected
S16 round 1：                   8 passed, 154 deselected in 4.60s
S16 round 2：                   8 passed, 154 deselected in 4.61s
S16 round 3：                   8 passed, 154 deselected in 4.77s
retention contract：           162 passed in 52.15s
capture + retention：          304 passed in 82.53s
host full suite：              654 passed, 18 skipped, 22 warnings in 131.61s
ruff / compileall / diff：      PASS
document relative links：       1 passed
```

本轮联合 `304 passed` 未复现第 19.2 节保留的首次联合 flaky，但这不证明旧顺序依赖已被定位或根治。18 个宿主 skip 仍是 canonical-only 与缺 cold wheelhouse 的 package case。

可声明的最大范围：当前 macOS 宿主上，合作进程在同一稳定 control namespace 中竞争时最多一个有效 commit；六个真实 process `SIGKILL` checkpoint 的重启分类稳定、只读且 fail closed。不可声明：物理断电持久、祖先目录 durability、macOS `F_FULLFSYNC`、Linux required 分支、同 UID 主动完整 ABA、自动恢复、跨机恢复或 Release。

### 20.5 下一步与 Gate

```text
S16 macOS process-crash hardening（完成）
  -> S17 CLI / config ownership / special files / source unknown keys
  -> S18 branch coverage / Linux / package / canonical qualification
  -> 刷新最新代码 PASS/BLOCKED evidence
  -> W1b-5b Go/No-go 复审
```

| 范围 | 当前 Gate |
|---|---|
| S16 process concurrency/crash | **Go / macOS current-host scope** |
| power-loss / 同 UID 主动 ABA / recovery authority | **No-go** |
| W1b-5a | **Conditional Go / trusted local assessment-only** |
| W1b-5b | **No-go / 等待 S17–S18 与 evidence refresh** |
| W1b-5c/5d/5e | **未授权、未实现** |
| Release | **No-go** |

本次角色讨论和首轮 RED 细节保存在 [`team-sessions/team-session-2026-09-06-4.md`](./team-sessions/team-session-2026-09-06-4.md)。继续禁止 commit、push、创建 CI、上传、签名、发布、自动删除、清理、归档或恢复；保留全部 modified/deleted/untracked 工作区成果。

## 21. S17 当前宿主实施完成后的唯一恢复入口

本节取代第 20.5 节中“S17 下一步”的状态。S1–S16 不得重做；S17 的 macOS 可执行部分已实施，Linux block/char device required 尚未执行，因此下一位从 S18/Linux qualification 开始。

### 21.1 已闭合能力

| 能力 | 实现/合同 | 结果 |
|---|---|---|
| config special file | rules 与 assessment 各自覆盖 hardlink、FIFO、Unix socket | 分别精确 `RULE_SCHEMA_INVALID` / `ASSESSMENT_SCHEMA_INVALID`；不阻塞；`.control` 不存在；sealed tree 不变 |
| config owner | 两类 config 通过 stat fixture 伪造非当前 uid | 同上，读取前 fail closed；当前宿主无法真实 chown，因此属于逻辑 owner 分支证据 |
| CLI sensitive actor | secret、绝对 HOME、内嵌 HOME、换行控制字符均由真实 subprocess 执行 | exit 1、stdout 空、stderr 精确 `ASSESSMENT_SCHEMA_INVALID: request rejected`；不回显输入、路径或 traceback；无 `.control` |
| CLI secret filename | untracked 文件名包含 scanner sentinel | status/summary 扫描正确导致 exit 3 / `SCANNED_BLOCKED`；stdout 只含 run/inspection/state，不回显文件名或 secret |
| source exact shape | `source` 顶层只允许 `before`、`after`、两个 aggregate、`stable_during_run`、`observation_limit` | `transactional`、`aba_excluded`、`qualification` 等额外声明以 `source has an invalid shape` 拒绝 |
| error compatibility | `observation_limit` 缺失或值篡改 | 继续优先返回旧合同 `source.observation_limit is invalid` |

生产 config reader 未重写：它已在 anchored parent 下 nofollow stat regular/uid/nlink，随后使用 `O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC` 打开，复核 fd identity、限长读取并执行 after/current identity check。S17 用真实特殊节点合同固定这些行为。capture verifier 的生产变化仅是 `source` 顶层 exact-key allowlist 和兼容校验顺序。

### 21.2 RED、测试修正与首次联合回归

首轮 S17 定向为 `10 passed, 6 failed, 304 deselected`：

1. 三个真实生产 RED：receipt `source` 接受 `transactional=true`、`aba_excluded=true`、`qualification=release`；
2. 两个测试 fixture 问题：macOS `AF_UNIX` 绝对路径过长，改为 config parent cwd + basename bind；
3. 一个测试期望问题：secret filename 会被 source status/summary 扫描器正确识别，稳定状态应为 `SCANNED_BLOCKED` 而非 pass。

修正后定向为 `16 passed`，连续 20 轮全部通过，共 320 次 case execution，单轮 6.32–12.14 秒。

第一次 capture+retention 联合为 `1 failed, 319 passed`：S15 missing observation-limit 合同期望精确字段错误，新增 shape check 提前返回通用错误。生产顺序改为 source type → observation-limit → exact-key 后，旧+新 5 个节点通过，联合重跑 `320 passed`。该失败不得从后续文档移除。

### 21.3 最新验证

```text
S17 targeted fixed:         16 passed
S17 stability:              20/20 rounds passed; 320 case executions
capture contract:           145 passed in 23.91s
retention contract:         175 passed in 57.91s
combined first:             1 failed, 319 passed
combined retry:             320 passed in 102.99s
host full:                  670 passed, 18 skipped, 22 warnings in 190.60s
ruff / compileall / diff:   PASS
document relative links:    1 passed
```

18 个宿主 skip 仍是 13 个 canonical-only golden 与 5 个缺 cold wheelhouse 的 package case。第 19.2 节更早的 external trust-anchor 顺序疑似 flaky 也继续保留；本轮首次联合失败是已定位并修正的独立兼容性问题。

### 21.4 未关闭项与下一步

- Linux block/char device `UNSAFE_FILE_TYPE` 需要真实受控 Linux runner；macOS 不新增预期 skip 来冒充该证据。
- wrong-owner 当前使用 stat fixture；真实不同 uid 文件需要隔离 runner，不把模拟写成系统级 ownership proof。
- S17 不提供 export/archive/destroy/recovery，也不升级 current-source 为 transactional/ABA-excluded。

```text
S17 macOS config/CLI/source shape（Conditional Go）
  -> S18 两个安全脚本 branch + 关键分支 coverage
  -> Linux renameat2 / proc-fd / device / S16 process matrix
  -> package/canonical required runner 零意外 skip
  -> 最新代码 PASS/BLOCKED evidence refresh
  -> W1b-5b Go/No-go 复审
```

W1b-5b 与 Release 继续 **No-go**；5c/5d/5e 仍未授权、未实现。角色讨论、RED 分流和 20 轮证据见 [`team-sessions/team-session-2026-09-06-5.md`](./team-sessions/team-session-2026-09-06-5.md)。继续禁止 commit、push、创建 CI、上传、签名、发布、自动删除、清理、归档或恢复。

## 22. S18 qualification 当前事实与唯一执行入口

本节取代第 21.4 节中“Linux device 未执行”和“S18 尚未开始”的时态。完整的 policy schema、能力逐条映射、测试矩阵、runner 边界、证据目录、停止条件与 DoD 已冻结在 [`W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md`](./W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md)，该文件是 S18 的唯一详细执行规格；本节只保存当前事实和恢复入口。

### 22.1 架构决议

1. `scripts/capture_test_gate.py` 与 `scripts/manage_evidence_retention.py` 分别生成 branch-enabled coverage JSON、JUnit 和 Gate；禁止合并 numerator/denominator 或用 `t2l`/另一脚本补分。
2. 新增独立 `security-coverage-policy.toml`、capability manifest、只读 verifier 和 runner；不改变现有 `quality-gates.toml` 的 `t2l` portable 语义。
3. 两个脚本分别要求 coverage.py combined >= 80%、statement line >= 80%、branch >= 80%；critical target line/branch 100%，required nodeids 0 skip/fail/deselected。aggregate 绿色不能替代任何一项。
4. capture 自身 formal artifact 的 uid/mode/nlink 与 closure entry/metadata/bytes budget 必须先写 RED；retention 后置扫描不能替代 capture 输入边界。
5. macOS、Linux、package、canonical 是不可替代的证据域；S18 仍不证明 power-loss、`F_FULLFSYNC`、完整 ABA、真实跨 uid、独立恢复或 Release provenance。

### 22.2 Coverage 当前 RED

| 目标 | Statement line | Branch | Combined | 判定 |
|---|---:|---:|---:|---|
| capture-only，145 passed | 1104/1394 = 79.1966% | 402/594 = 67.6768% | 75.7545% | RED |
| capture，追加 retention 调用 | 1106/1394 = 79.3400% | 402/594 = 67.6768% | 75.8551% | RED；跨 suite 补分无效 |
| retention，175 passed + 1 platform skip | 1060/1228 = 86.3192% | 305/400 = 76.25% | 83.8452% | branch RED；combined 通过不构成资格 |

原始 JSON SHA-256 分别为：

- capture-only：`bb0a0a1e4e4c2cd5e516da3a80e7f0c4c6734b821c638c2800faab46fdd08c6f`；
- capture + retention：`d1de8536b15db6013d4672f30b41d5ddc3130e4c453b79eb399626f0503d102c`；
- retention：`c38ef9beb65c7968849ddbdeaa81f94591e7ae667ff9d45d6dc6bff1503bfd77`。

不得降低 80%、扩大 omit、删除安全分支、添加 `pragma: no cover` 或合并高覆盖文件取得绿色。

### 22.3 Linux required 功能实测

旧 canonical Python 3.10.21 runner 首次 collection 因 `datetime.UTC` ImportError 失败；这是 runner 错配，不修改生产代码迁就。成功 runner 为 `python:3.11.9-slim-bookworm`、容器 `linux/amd64`、Docker Desktop daemon `linux/arm64` 29.7.2、repo 只读挂载：

```text
S16 + Linux block/char device:  9 passed, 167 deselected in 13.44s
/proc/self/fd + source contract: 9 passed, 136 deselected in 5.37s
```

这证明本次容器中实际执行 Linux `renameat2(RENAME_NOREPLACE)`、`/proc/self/fd` anchor、block/char device `UNSAFE_FILE_TYPE` 和 S16 process/SIGKILL/flock 路径。它不是原生 x86_64 性能、cold package、真实跨 uid 或 power-loss 证明。最终 qualification 必须用 exact nodeids 重跑，保存 JUnit、环境、命令、source hash，且 required set 0 skip。

### 22.4 Package 与 canonical

macOS package 使用的旧 wheelhouse 已被当前输入 supersede：`34 passed, 1 failed, 1 deselected`；`PKG-018` 检出 manifest `pyproject_sha256=53a80382c01518ebd94b747268dc4c54ed396e2f9e3dd0c1536f24dfc589792a`，当前为 `261e426e194d46308cdb1ca3117bb4015693691cd0704cfd071d1476240fed19`。JUnit SHA-256 为 `ea0c267722761f2e5747946df93d6ff109acd18cde4a456332f20ee7db7b9aef`。禁止手改 manifest hash；必须完整重建 wheelhouse 后再跑 cold Gate。Package 当前 **No-go**。

当前源码重建的 canonical image `sha256:d429650aacae3d9c8a50dfb1ff3e73e065e49eca3016bf3662e5ca2e7d7f5b19` 在断网、只读 rootfs 的 `linux/amd64` 环境得到 `13 passed, 0 skipped, 7 warnings in 143.57s`。JUnit SHA-256 为 `63e5393d835134814f57a1b4dc0a8135c68a52527e75cfe9867b23a2544000a5`，Gate JSON SHA-256 为 `4579f84294956c30fe113f79b50fa046c6eb41cd8b39dd86b7f5d599e94df24c`。最大结论是 current dirty-source functional canonical Go / implemented-unqualified；最终 S18 代码变化后仍须重建重跑。

### 22.5 恢复顺序与 Gate

`670 passed, 18 skipped` 是新增 Linux-only device test 之前的宿主历史值，禁止推测新 skip 数。`/private/tmp/ai-auto-lrc-w1b5-final-20260906-02/` 也早于 S17/S18，只能作为 historical evidence。

下一位从以下顺序继续，不重做已经闭合的 S16/S17：

```text
S18 policy + manifest + verifier 合同 RED
  -> capture/retention 独立 line/branch 与 critical target 闭合
  -> Linux exact-node JUnit/provenance 刷新
  -> macOS wheelhouse 完整重建并重跑 package
  -> 最终源码 canonical 重建
  -> targeted/full/static/doc 回归
  -> 最新 PASS/BLOCKED evidence 与独立 verify
  -> W1b-5b Go/No-go 复审
```

当前 Gate：Linux functional 与 canonical functional 为局部 Go；capture/retention security coverage、package、最终回归和 evidence refresh 为 No-go。S18、W1b-5b、Release 均为 **No-go**；W1b-5a 仍只允许 checked-in defaults + trusted local assessment-only；5c/5d/5e 未授权、未实现。Teams 讨论见 [`team-sessions/team-session-2026-09-06-6.md`](./team-sessions/team-session-2026-09-06-6.md)。

### 22.6 2026-09-06 S18 方案固化勘误

第 22.2–22.5 节保留 S18 首轮 RED 和当时恢复状态，不再作为最新入口。当前 capture raw coverage 为 273 passed、line 90.7280%、branch 84.4660%；retention 为 244 passed、1 个声明的 Linux-device platform skip、line 93.9320%、branch 89.1089%；macOS package 在补齐 `PKG-012/017/024` 后为 37 passed、0 skip/fail。Security verifier 合同 41 passed，但 nested walker 独立度量、最终 manifest 和同源双 lane Gate 尚未闭合，因此 S18/W1b-5b/Release 仍为 No-go。

为避免事实复制漂移，critical 判据、分歧裁决、R0–R6 重构波次、测试矩阵、raw evidence hash 与最终 checklist 仅由 [`W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md`](./W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md) 第 17 节维护；本文件后续只链接该 canonical 入口。

### 22.7 S18 当前逐能力恢复入口

第 22.6 节和S18主方案第 17.8 节现为historical checkpoint。当前CAP-01..17逐条合同、native no-replace测试、per-required-runner语义成对规则、runner/verifier hash闭包、Linux security v2边界和最终验收顺序统一见 [`W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md`](./W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md) 第 17.9 节。

本文件不复制当前hash或pass计数。W1b-5b继续No-go；5c export、5d archive/restore、5e destruction未授权、未实现，不能因任何局部Gate绿色自动开始。

### 22.8 S18 2026-09-07 当前恢复入口

第 22.7 和 S18 主方案第 17.9 节已是 historical checkpoint。当前 native no-replace 双平台证据、per-required-runner 语义成对、toolchain hash 闭包、剩余 `S18-COV-015`/P1 与最终刷新顺序统一见 [`W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md`](./W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md) 第 17.10 节；本文不复制易漂移数字。

W1b-5b 继续 No-go；5c export、5d archive/restore、5e destruction 未授权、未实现。恢复时从第 17.10.7 节 A1 开始。

### 22.9 S18 P1 版本化恢复入口

第 22.8 节的 A1 恢复指令已历史化。`S18-COV-015`、SRC frozen bytes、JUnit canonical grammar 和基础 XFAIL events 链路已经实现；新的阻断是 pytest hermetic boot、实际 plugin identity、JUnit/events outcome consistency 和 ABA claim boundary。

当前唯一执行方案为 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)，版本 `S18-P1-PLAN-v1.0`，SHA-256 `027d0350f8d3d2074828a2f2cf6a3645808f7e1bf7fb59ac27081d6857fb8c61`。Retention 工作包只消费该方案最终 current Security evidence，不复制其易漂移的测试数、平台 attempt 或 package/canonical hash。

W1b-5b 继续 No-go；5c export、5d archive/restore、5e destruction 未授权、未实现。

### 22.10 S18 P1 当前冻结指针

第 22.9 的 v1.0 指针保留为首次落盘 checkpoint。当前有效执行版本为 `S18-P1-PLAN-v1.2`；权威文件 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) SHA-256 为 `ebc7bd3dcee085ca590d22df4d7fe2bc097a76efc4c463b5ed21e8ba06128683`。

Retention 只在 hermetic Security Gate、typed ABA boundary 和最终字节冻结后消费 current evidence。旧双平台或 package/canonical artifact 不得因本指针更新而恢复资格。

### 22.11 S18 P1 最终架构冻结指针

当前权威版本为 `S18-P1-PLAN-v1.3`，文件 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) SHA-256 `1ee9a126586c4321714a84bd195db0fb36cf4c6925dba06940b5723dbb539429`。Retention 只消费与该版本 freeze ledger 和平台声明一致的 current evidence；第 22.10 及更早指针均为历史 checkpoint。

### 22.12 S18 P1 v1.4 消费边界

第 22.11 节保留 v1.3 checkpoint。当前权威版本为 `S18-P1-PLAN-v1.4`，文件 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) SHA-256 `9cb1a2c534cab265aa43ec0b5e3d651392ba3e9ae4cce81406a834772dd07c68`。

Retention 不消费 B3b/B3d 的 host implementation checkpoint，也不消费仅有 path/hash 自报的 plugin identity。只有 B3c trusted loaded identity、B3e/B3f、typed claim boundary、P1 traceability 和 common/per-platform freeze ledger 全部 current 后，才可消费对应平台的新 Security evidence。W1b-5b 继续 No-go，5c export、5d archive/restore、5e destruction 仍未授权。

### 22.13 S18 P1 v1.5 消费边界

第 22.12 节保留 v1.4 checkpoint。当前权威方案为 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第 18 节，版本 `S18-P1-PLAN-v1.5`，SHA-256 `59d42eaed5f5323255d510e3f6f4e5bd784c8d84ea329ffb1f01f1098dc4f262`；Teams 裁决 [`team-sessions/team-session-2026-09-07-4.md`](./team-sessions/team-session-2026-09-07-4.md) SHA-256 `91af3b63a6e9ec313c8ad343a71d993aa6e6339bdc5604fe6dfc0b1df12481c1`。

唯一下一步为 B3e-S，随后执行 B3f-L/B3f-R 和最终 schema 下的 B3c–B3e 重放。Retention 不消费 179-pass host checkpoint、未持久化的 pytest `tmp_path` inner attempt、仅 installed RECORD 自洽的 provenance 或未冻结的 claim surface；只消费 B4、P1 traceability、common/per-platform freeze ledger 和对应平台最终 Security evidence 全部 current 后的结果。

W1b-5b 继续 No-go；5c export、5d archive/restore、5e destruction 仍未授权。

### 22.14 S18 P1 v1.6 消费边界

第 22.13 节保留 B3e-S 前的 v1.5 checkpoint。当前权威方案为 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第 19 节，版本 `S18-P1-PLAN-v1.6`，SHA-256 `c14dc85959176d8e018713fbecaf064ca28c204f16e24e6280635406508217c8`；Teams 记录 [`team-sessions/team-session-2026-09-07-5.md`](./team-sessions/team-session-2026-09-07-5.md) SHA-256 `dd139646c3fbbec6c89ee7e3305e496066fc54a637372beb731bc933249b3293`。

Retention 不消费 B3e-S 的 host scenario contract、196-pass security contract、41-pass P1 inventory contract 或 `/private/tmp` 实施 attempt；它们没有把任何 P1 record 晋级为 verified/qualified。只有完成 B3c/B3f、最终 schema replay、逐 kind evidence 语义验证、transition ledger、B4 typed claim/ABA、common/per-platform freeze ledger 和对应平台最终 Security evidence 后，Retention 才可消费匹配 scope 的 current result。

唯一 Security 恢复点是方案第 19.6 节的 B3c RECORD/no-replace correction。W1b-5b 继续 No-go；5c export、5d archive/restore、5e destruction 未授权、未实现。

### 22.15 S18 P1 v1.7 消费边界

第 22.14 节保留 B3c 收口前的 v1.6 checkpoint。当前权威方案为 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第 20 节，版本 `S18-P1-PLAN-v1.7`，SHA-256 `a1cf11e7e9700a6689959a88d0a6abee5395c582b48a1e881db96013dbd34afc`；Teams 记录 [`team-sessions/team-session-2026-09-07-6.md`](./team-sessions/team-session-2026-09-07-6.md) SHA-256 `ceac0ee80f76681cdbc59fe2e42f119154853fe9344dbd89dc68bb5371c52720`。

Retention 不消费 B3c 的 `207 passed` host contract，也不消费本轮 `/private/tmp` JUnit。只有 B3f-L/B3f-R、final-schema replay、完整 hostile matrix、逐 kind evidence verifier、transition ledger、B4 typed claim/ABA、common/per-platform freeze ledger 和对应平台最终 Security evidence 全部 current 后，Retention 才能消费匹配 scope 的结果。

唯一 Security 恢复点是方案第 20.4 节 B3f-L characterization RED。W1b-5b 继续 No-go；5c export、5d archive/restore、5e destruction 未授权、未实现。

### 22.16 S18 P1 v1.8 消费边界

第22.15节保留B3f-L执行前的v1.7 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第21节，版本`S18-P1-PLAN-v1.8`，SHA-256 `e33a9a312dcf49096f1af89276074f71beb8f243b1a3a0eabbf7e2a45868ebe4`；Teams记录[`team-sessions/team-session-2026-09-07-7.md`](./team-sessions/team-session-2026-09-07-7.md) SHA-256 `a386eb6a4f38e60b536362ff2a1ab7e40b25500b6040da5d132c23e2e66e1e3d`。

Retention不消费B3f-L的unit/mutation tranche、`257 passed` host contract或`/private/tmp` JUnit。唯一Security恢复点是方案第20.7与21.5节的real-runner scenario authority；只有B3f-L完整闭合并继续完成B3f-R、final-schema replay、B4、freeze ledger和对应平台最终evidence后，Retention才可消费匹配scope的结果。W1b-5b继续No-go；5c/5d/5e未授权、未实现。

### 22.17 S18 P1 v1.9 消费边界

第22.16节保留authority建立前的v1.8 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第22节，版本`S18-P1-PLAN-v1.9`，SHA-256 `9e688a4edc94b308257f4ef72072e7ca9f06cd0a421db99e213cfbfd21cb8bf9`；Teams记录[`team-sessions/team-session-2026-09-07-8.md`](./team-sessions/team-session-2026-09-07-8.md) SHA-256 `a05f078026ce77feba9e4eddbc6085db3b59088c722099c7c1f184e656086afd`。

Retention不消费当前10/67代表性real-runner checkpoint、runner-error v2、authority hash或`/private/tmp` evidence；57条仍planned，B3f-L未闭合。只有完成57条、最终67条同hash replay、B3f-R、final-schema replay、B4、freeze ledger和对应平台最终evidence后，Retention才能消费匹配scope的结果。W1b-5b继续No-go；5c export、5d archive/restore、5e destruction未授权、未实现。

### 22.18 S18 P1 v1.10 消费边界

第22.17节保留Batch A前的v1.9 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第23节，版本`S18-P1-PLAN-v1.10`，SHA-256 `c46808ba2fd421a20225ab145cf9715bd974576d4e3b8a5b23b166f484c485bd`；Teams记录[`team-sessions/team-session-2026-09-07-9.md`](./team-sessions/team-session-2026-09-07-9.md) SHA-256 `84dfea124230a7027a200fd00a3919d6e2b47c36e9da153767989f4c04ac47b5`。

Retention不消费当前28/67 Batch A host checkpoint或其EARLY raw；39条仍planned，后续test bytes还会使批次证据历史化。只有最终67条同hash replay、B3f-R、final-schema replay、B4、freeze ledger和对应平台最终evidence全部current后才能消费匹配scope的结果。W1b-5b继续No-go；5c export、5d archive/restore、5e destruction未授权、未实现。

### 22.19 S18 P1 v1.11 消费边界

第22.18节保留Batch B前的v1.10 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第24节，版本`S18-P1-PLAN-v1.11`，SHA-256 `8cc36822ec315d2e905d057e64121ee94c31bb21245e34578efa53f65ff37d2a`；Teams记录[`team-sessions/team-session-2026-09-07-10.md`](./team-sessions/team-session-2026-09-07-10.md) SHA-256 `b72d2f78957377b5d99d447692c6ce9f2a04b2adc7738b3e4afbde27015fd5d0`。

Retention不消费34/67 Batch B host checkpoint；33条仍planned且最终同hash replay未完成。只有B3f-L/R、final-schema replay、B4、freeze ledger与平台最终evidence全部current后才能消费匹配scope。W1b-5b继续No-go；5c/5d/5e未授权。

### 22.20 S18 P1 v1.12 消费边界

第22.19节保留Batch C前的v1.11 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第25节，版本`S18-P1-PLAN-v1.12`，SHA-256 `3bd00bca522b46880f75ad06e940865bab8b61241cd97a96d716e42dd0da8200`；Teams记录[`team-sessions/team-session-2026-09-07-11.md`](./team-sessions/team-session-2026-09-07-11.md) SHA-256 `60ffbcbeec2a1dc21610e58982874c1c44b3cecfb21075d3070c02a6aa9bfca1`。

Retention不消费38/67 Batch C host checkpoint；29条仍planned，最终同hash replay未完成。只有B3f-L/R、final-schema replay、B4、freeze ledger与平台最终evidence全部current后才能消费匹配scope。W1b-5b继续No-go；5c/5d/5e未授权。

### 22.21 S18 P1 v1.13 消费边界

第22.20节保留Batch D前的v1.12 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第26节，版本`S18-P1-PLAN-v1.13`，SHA-256 `7c6beb0c6c5c2fe6e3071d7e4a053dbaf94a4f37e0fff64ee629d9479a17eeef`；Teams记录[`team-sessions/team-session-2026-09-07-12.md`](./team-sessions/team-session-2026-09-07-12.md) SHA-256 `9bd312ae5da31ef2db556cca6063d76cdeae68fa1f33fd57ee0d0dd1486b8dff`。

Retention不消费52/67 Batch D host checkpoint；15条仍planned且最终同hash replay未完成。Batch E仍须对existing-final、preexisting-temp、publish-race分别执行retention身份不变oracle，不能由capture代签。W1b-5b继续No-go；5c/5d/5e未授权。

### 22.22 S18 P1 v1.14 消费边界

第22.21节保留Batch E前的v1.13 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第27节，版本`S18-P1-PLAN-v1.14`，SHA-256 `c273c92020eb3f9bc47d6537d1fce10513221af5119f9d69f4e10e23a098eae5`；Teams记录[`team-sessions/team-session-2026-09-07-13.md`](./team-sessions/team-session-2026-09-07-13.md) SHA-256 `781823e419f0f4bd4841c8adc40286baea9928a02629a12f5358ce657a5b80b5`。

Retention不消费58/67 Batch E host checkpoint；9条仍planned且最终同hash replay未完成。Batch F仍须为temp-unlink-retry、directory-fsync、directory-close分别运行retention target fault与capture control，不能跨lane代签。W1b-5b继续No-go；5c/5d/5e未授权。

### 22.23 S18 P1 v1.15 消费边界

第22.22节保留Batch F前的v1.14 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第28节，版本`S18-P1-PLAN-v1.15`，SHA-256 `47e48deb8260e7171e23cfd8bd8adc7e4e6bf578a2196595588ad739aba1ecfb`；Teams记录[`team-sessions/team-session-2026-09-07-14.md`](./team-sessions/team-session-2026-09-07-14.md) SHA-256 `065d19d9455c1429a82cb8509ede5f94e906050a51bc9d1dd0b2847b62771da1`。

Retention不消费64/67 Batch F host checkpoint；3条仍planned且最终同hash replay未完成。Batch G的syscall-order仍须独立运行retention target trace与capture control，不能由已有fault traces拼接代签。W1b-5b继续No-go；5c/5d/5e未授权。

### 22.24 S18 P1 v1.16 消费边界

第22.23节保留Batch G前的v1.15 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第29节，版本`S18-P1-PLAN-v1.16`，SHA-256 `30b9df622cf930cb36e7a250193dd7386a379db9f4197d8d2e667f51b12ea248`；Teams记录[`team-sessions/team-session-2026-09-07-15.md`](./team-sessions/team-session-2026-09-07-15.md) SHA-256 `f70cd4737f8705996936cafe2345b7d52bf4919a2a7fa301e5e4f414cd298178`。

Retention不消费66/67 Batch G host checkpoint；唯一planned为global runner-input existing-attempt，且最终同hash replay未完成。Batch G retention trace不能代签B3f-L整体或任何消费状态。W1b-5b继续No-go；5c/5d/5e未授权。

### 22.25 S18 P1 v1.17 消费边界

第22.24节保留Batch H前的v1.16 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第30节，版本`S18-P1-PLAN-v1.17`，SHA-256 `a12aff9eaa2e3bb86f21efb7833d079bb4b82bb51dcb7ec2bf83e98ac6298398`；Teams记录[`team-sessions/team-session-2026-09-07-16.md`](./team-sessions/team-session-2026-09-07-16.md) SHA-256 `b9943d2f5e5688765a092d52b9f95394631ef5f342cf5325f05530333698a76c`。

Retention不消费67/0/67计数或Batch H runner-input checkpoint：最终67条同hash replay、B3f-R、final-schema replay、B4、freeze ledger和对应平台最终evidence仍未完成。W1b-5b继续No-go；5c export、5d archive/restore、5e destruction未授权、未实现。

### 22.26 S18 P1 v1.18 消费边界

第22.25节保留final 67前的v1.17 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第31节，版本`S18-P1-PLAN-v1.18`，SHA-256 `a6250365667cee35caf2784c68a96932e3336b57328e607fcc6790e47e84f488`；Teams记录[`team-sessions/team-session-2026-09-07-17.md`](./team-sessions/team-session-2026-09-07-17.md) SHA-256 `51041766bb0723257b62adf00803fd4926faeabf47ca65c14169df5e7b349021`。

Retention仍不消费B3f-L final 67 host closure：B3f-R会改变runtime schema并使其历史化，且final-schema replay、B4、freeze ledger和平台最终evidence仍未完成。W1b-5b继续No-go；5c/5d/5e未授权。

### 22.27 S18 P1 v1.20 消费边界

第22.26节保留R0前的v1.18 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第33节，版本`S18-P1-PLAN-v1.20`，SHA-256 `5b14134df98e68b5ed092262d5b43cf521b8156cee791dfb5c14719da52267f2`；Teams记录[`team-sessions/team-session-2026-09-07-19.md`](./team-sessions/team-session-2026-09-07-19.md) SHA-256 `271caf7e77870a024bf7d4b6a4d35aec5142bf872d3cf422d3c9ceba494e109a`。

Retention不消费R0 RED、R1a primitives、当前host uv/home probe、初版或补充JUnit。只有R1b exact15、R2原子schema迁移、真实双lane、final-schema B3f-L/B3c/B3d/B3e replay、B4、freeze ledger和对应平台最终evidence全部current后，才可消费匹配scope的结果。W1b-5b继续No-go；5c export、5d archive/restore、5e destruction未授权、未实现。

### 22.28 S18 P1 v1.21 R1b QA P1 消费边界

前一入口保留为历史 checkpoint。当前权威方案为 [S18 P1 执行方案](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第34节（尤其34.6至34.10），版本 `S18-P1-PLAN-v1.21`，整份 SHA-256 `cc3705d97e7b9d6c75b0e91059f0ba9d88d5f1fe91de836290553d0677f457e7`；[Teams 20](./team-sessions/team-session-2026-09-07-20.md) SHA-256 `f5a1822407d8523093ada70700520cc9c964379be6c3f6db92d4cf1c3055e63a`。

R1b 定向回归通过，但独立 QA 发现 lock pathname 同内容换 inode 未拒绝、文件身份字段接受根路径两个 P1，当前 **未验收**。下一次执行从第34.8节局部 test-first 修复与新 hash 独立 QA 开始，不能跳到 R2。本次仅持久化方案，不修改代码或消费资格；产品/P1计数不晋级。S18、W1b-5b、Release 继续 No-go，不执行 W1b-5c/5d/5e。后续完整 DAG、测试用例、原始证据失效处理均以权威方案为准。

### 22.29 S18 P1 v1.22 R1b 验收与 R2 消费边界

前一入口保留旧 QA P1 checkpoint。当前权威方案为 [S18 P1 执行方案](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第35节，版本 `S18-P1-PLAN-v1.22`，整份 SHA-256 `6b6c29dedb130396f1ab5ec6c7e4bda9637fecf65ce3892e373d8bac1ab48fc8`；[Teams 21](./team-sessions/team-session-2026-09-07-21.md) SHA-256 `069f7663cded80d73a3f37b52807fd121a610c9dc3b99e8a16a2ab9ced2dc67a`。

两个 R1b P1 已在新 hash 下经 RED/GREEN、架构与独立 QA 关闭；exact15、R1a10 unique、legacy10 均通过，policy-v3 仍是唯一预期 RED。R1b producer foundation 完成，不代表真实 runner、identity-v2 publication、Linux/双平台或 Release qualification。下一步先解决第35.11节草案冲突，冻结 R2 exact 契约后执行第35.5节原子 cutover；第35.9至35.10节字段/十二节点仍为 proposed/planned，不计为实现。S18、W1b-5b、Release 继续 No-go，inventory不晋级，W1b-5c/5d/5e不执行。

### 22.30 S18 P1 v1.23 R2 进行中消费边界

当前工作入口转至 [S18 P1 执行方案](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第36节和 [Teams 22](./team-sessions/team-session-2026-09-07-22.md)。第35节R1b最终hash仅为历史已验收基线；R2正在原子迁移，代码与文档尚未最终封板，因此本入口不提供冒充完成的固定hash。

先核对第36节最后checkpoint与真实worktree/进程状态后续接。不得复用旧R1b绿色、初始15-node scaffold RED或部分schema更改代签R2。真实双lane、final67和平台qualification仍待后续，inventory不晋级；S18、W1b-5b、Release继续No-go，5c/5d/5e不执行。

### 22.31 R2 方案本地保存与待独立 QA 入口

最新恢复点为 [S18 P1 执行方案](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第36.33–36.34节；实现已停写停测并交锁，九文件候选快照已核对。精确测试选择、证据索引与hash已保存到docs，原始测试产物仍在临时目录；本次不是完整证据归档。

R2尚未独立验收；下一步为同快照独立QA，不是R3。四项入口继续WIP，S18、W1b-5b、Release继续No-go；详情与验收门仅以权威方案最新checkpoint为准，不从旧绿色或聊天摘要推断完成。

### 22.32 R2 递归修复后的当前状态

最新恢复点为 [S18 P1执行方案](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第36.40节，新九文件清单位于第36.39节。深层JSON候选解析的P1已最小修复，主代理fresh47+35回归通过（去重79节点）；最终独立QA任务被执行环境中止，没有验收结论。独立验收门仍保留，不能据主代理复验启动R3；S18、W1b-5b、Release继续No-go。R3仅完成失败profile与隔离前置设计，不是执行或平台资格证据。

### 22.33 R2 独立验收完成与 R3 正常对照

2026-09-09 最新入口为 [S18 P1 执行方案](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第36.41–36.42节。R2冻结九文件已通过独立源码审阅与79个唯一节点fresh回归；主代理重算57份原始证据并通过42项文档治理。旧“最终独立QA缺失”状态保留为历史，当前R2合同已验收。R3正常macOS对照已实现：最终system层2项通过，真实capture282项和retention257项通过，两Gate PASS；retention有1个声明的平台不适用skip。完整异常矩阵、R4、平台与发布资格仍待完成。产品inventory不晋级，S18/W1b-5b/Release继续No-go。


## 22.34 2026-09-12 用户交付决定：文档与开发分支推送

用户明确要求异常场景暂不全覆盖，优先完善技术文档、系统说明、使用指南与 README 顶部 AI 使用提示词，并推送远端。本次提交/推送已有用户授权，早期“等待提交批准”记录保留为历史，不阻止本次开发快照交付。

当前权威入口为[文档导航](README.md)及[项目状态](PROJECT_STATUS.zh-CN.md)。保留 R2 冻结验收与 R3 macOS 正常对照证据；不扩大其结论、不补跑完整异常矩阵、不更改原始阈值。未完成事项标记暂缓/未验证，S18 / W1b-5b / Release No-go 不变。本轮只向 `improve-inference-reliability` 开发分支提交及推送，不覆盖远端 main，不发布发行版。
