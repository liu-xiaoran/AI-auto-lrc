# Dev Team Session: B3e-S 与 P1 machine authority v1.6

日期：2026-09-07

模式：PM / Architect / Developer / QA 四视角并行审查

权威方案：[`../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第 19 节
上下文：仓库没有 `PROJECT-CONTEXT.md`；本次只使用已审阅的交接文档、测试代码和实际命令结果作为项目上下文。

## 议题

在不扩大 S18 资格声明的前提下，完成 B3e-S 稳定 scenario ID/manifest，并把首批 P1 traceability 从 inventory 自报升级为独立代码 authority；通过 hostile mutation 证明语义映射、状态、scope、nodeid、evidence ref 和 collection producer 不能只靠修改 inventory 自签。全部讨论与裁决必须落盘，保留 RED、fixture/runner error、retry、skip 和旧 attempt。

## PM

### First reaction

交付价值不是增加一个 JSON 表，而是确保下一位恢复者能唯一回答“哪些能力已实现、由哪些 exact node 证明、当前能宣称到哪一级”。本轮必须把 host contract 与 verification/qualification 明确分开。

### Key concerns

- B3e-S 的 planned hostile matrix 不能被 7 个 host scenario 代签。
- P1 inventory 不能因普通测试绿色自动升级为 host-verified、evidence-closed 或 platform-qualified。
- 交接入口必须从 v1.5/B3e-S 更新为 v1.6/B3c correction，避免恢复者重做已完成切片。

### First action

把 current-state authority、可执行 mutation、最大声明和唯一下一步作为一个原子 DoD，并把结果追加到权威方案与上位交接文档。

### Question for the team

哪些安全性质是本轮可真实验证的，哪些必须留到首次状态晋级前由独立 evidence verifier 完成？

## Architect

### First reaction

独立 ID 集不足以构成 authority；必须冻结 ID 到完整 record 的映射。path/hash 校验也不等于 evidence 语义验证，更不等于状态迁移治理。

### Key concerns

- authority 应逐字段冻结 implementation、verification、qualification、runner/target scope、nodeids 和 evidence refs。
- future promotion 必须有逐 kind 语义 verifier 与单调 transition ledger；仅存在的 JSON 文件加正确 hash 仍可协同自签。
- evidence 读取需要 canonical spelling、regular file、bounded descriptor read 和稳定 identity；仍不得扩大为 same-UID、cross-UID 或 power-loss 声明。

### First action

将 inventory record 与代码 authority exact equality 作为 current-state Gate，并把 evidence semantic verification/transition artifact 明确排入 B4c 之前的阻断。

### Question for the team

首次从 unverified 晋级时，哪个 producer-external verifier 对四种 evidence kind 分别负责，transition authority 由谁批准？

## Developer

### First reaction

初版 record equality 正确，但 evidence mutation 曾被同一个 authority mismatch 兜底，可能假绿；collection 也不能继续解析可伪造 stdout。

### Key concerns

- path/hash helper 必须单独测试，否则删掉真实检查仍可能由 record drift 让 mutation 绿色。
- canonical raw spelling 要覆盖 `..`、`./`、重复 `/` 和 macOS case-drift alias。
- 未经 authority 接受的 path 不应先被读取；受权 path 必须有大小上限和同 fd 前后 identity 检查。

### First action

拆分 evidence reader 合同与 promotion 拒绝合同；用 `O_NOFOLLOW/O_NONBLOCK` 有界 descriptor read，逐目录项核对 exact case，并先比较 authority 后读取 current refs。

### Question for the team

未来 evidence 是否要求 `st_nlink == 1`，以及是否必须把 ancestor directory identity 纳入同一次 stable-read closure？

## QA

### First reaction

最初两个自签绕过已复现，但 `_collect_nodes()` 仍继承 `PYTEST_ADDOPTS/PYTEST_PLUGINS` 并信任 stdout，可用 hostile plugin 打印伪 nodeid、同时 ignore 真实文件后绕过。

### Key concerns

- collection 必须在隔离环境内关闭 entry-point/plugin/conftest 注入并固定 pytest config。
- collection 结果必须来自真实 `session.items` 的结构化 sidecar，而不是普通 stdout 文本。
- malformed spec/evidence 缺字段或类型错误应稳定 fail closed，不得泄漏为 `KeyError`/`TypeError`。

### First action

构造 hostile plugin + injected `--ignore` 重放，要求插件未加载、伪 stdout 未消费、7 个 authority node 仍来自真实 collection；再补 missing/non-object/nonstring schema mutation。

### Question for the team

是否需要把 collector sidecar 自身升级为持久 evidence？裁决：本轮只作 host inventory contract；最终 qualification 仍由正式平台 evidence pipeline 产生。

## 讨论中的实际 RED 与修正

1. 初始 anti-self-signing RED：4 个 record mapping drift 与 1 个 synthetic evidence promotion 均未被拒绝，`5 failed`；保留于 `/private/tmp/ai-auto-lrc-s18-p1-anti-self-red.u0FSoE`。
2. 第一次 retry：missing/noncanonical 抛出未规范化 `FileNotFoundError`，`8 passed, 2 failed`；保留于 `/private/tmp/ai-auto-lrc-s18-p1-anti-self-green.rUln6Z`。
3. 初版 collection 隔离使用 `-I` 后，仓库 `scripts` namespace package 从 import path 消失，导致 8 个 collection error；修正为先从受信 site 导入 pytest，再显式加入已解析仓库根，同时保留 `-I/-B`、环境清理和 `--noconftest`。
4. QA hostile replay 在修正前得到 `HOSTILE_COLLECT_BYPASS_ACCEPTED=True`；修正后为 `PLUGIN_LOADED=False`、`FORGED_ACCEPTED=False`、`AUTHORITY_PRESENT=True`。
5. Developer 复核发现 macOS case-insensitive alias；增加逐目录项 exact-name 校验及 case-drift mutation 后，path/hash/size/I/O-order 定向 `12 passed`。

## Synthesis

- 阻断共识：current inventory authority 必须是代码内完整 record mapping；collection 必须隔离外部 pytest 环境并绑定结构化 `session.items`。
- 已解决张力：PM 希望形成可恢复 checkpoint，Architect/QA 拒绝把普通绿色升级为 qualification。最终保留全部 7 项 `unverified/unqualified`，仅声明 host contract。
- 已解决张力：path/hash 检查需要可执行合同，但不能暗示 evidence 语义有效。实现只验证 current authority 接受的 canonical bounded bytes；逐 kind verifier 和 transition ledger 仍是显式 blocker。
- 当前 GREEN：B3e-S 定向 `24 passed, 172 deselected`；security contract `196 passed`；最终 P1 inventory contract `41 passed`；Ruff、format、`py_compile` 与 JSON parse 通过。
- 唯一下一步：B3c RECORD field semantics/no-replace correction，然后 B3f-L、B3f-R；最终 schema 下重放 B3c–B3e 后，再执行完整双平台 hostile evidence 和 B4 traceability。

## Gate

允许：B3e-S stable scenario IDs/manifest/exact artifact allowlist，以及当前 P1 inventory record/collection authority 已实现并通过 host contract。

禁止宣称：evidence artifact 语义已独立验证、future promotion 无法协同自签、完整 hostile matrix、Linux qualification、双平台 raw closure、ABA-safe、immutable snapshot、transactional execution、power-loss durability、W1b-5b Go 或 Release Go。

S18、W1b-5b、Release 继续 No-go；W1b-5c/5d/5e 未授权。禁止 commit、push、CI、upload/sync、签名、发布、archive、restore、delete、destruction；保留 dirty worktree、根 `./=` 和全部历史 attempt。
