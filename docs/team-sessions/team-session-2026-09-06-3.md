# AI-auto-lrc 重构方案持久化 Teams 会话

日期：2026-09-06  
模式：PM / Architect / Developer / QA  只读分析；由主任务统一写入文档  
主题：把 S12a–S15 已完成事实、S16–S18 可执行测试方案和全部 v2 剩余工作包固化到本地，避免后续会话丢失细节。

## 项目上下文

AI-auto-lrc 正处于 v2 安全证据链重构期。当前工作区包含大量必须保留的 modified/deleted/untracked 成果；本轮不 commit、push、创建 CI、上传、签名、发布、自动删除、清理、归档或恢复。W1b-5c export、5d archive、5e destruction 未获授权，Release 保持 No-go。

## PM

1. **First reaction**：应立即建立可恢复执行的单一事实文档；S12a–S15 仅算已验证阶段成果，不等于可发布。
2. **Key concerns**：锁定当前重构范围与大量保留改动；S16–S18 按明确 DoD 执行；SBOM、attestation、签名、rollback 未闭环即 Release No-go。
3. **First action**：建立 Markdown 骨架，写明事实、DoD、证据、依赖、禁止边界和恢复入口。
4. **Question for the team**：谁负责逐项签署 S16–S18 DoD 与最终发布放行？

## Architect

1. **First reaction**：S15 只在“current-source 是 diagnostic sequential observation、retention schema-v1 不发布该模式”的范围内可 Go，不能声明 transactional 或 ABA-excluded。
2. **Key concerns**：程序化 verifier 返回原 receipt，旧 qualification 可能被误用；`source` 没有 exact-key 拒绝矛盾声明；macOS `F_GETPATH`、Git 子命令间 ABA 和独立 system case 仍缺。
3. **First action**：在唯一技术入口锁死 effective assurance 边界，并先补 unknown-key、process-crash 和真实平台 RED。
4. **Question for the team**：是否用 additive typed outcome 表达本次验证 assurance，而不改变 sealed receipt document？

## Developer

1. **First reaction**：应把已验证事实、未闭合风险与门禁写成唯一恢复入口，严格区分完成项和计划。
2. **Key concerns**：锁定 S16→S17→S18 及 runtime close、恢复、SBOM/attestation/签名依赖；在途改动按切片可回退；每步需命令、预期输出、失败码和产物路径。
3. **First action**：先写现状快照，再补逐项验收、回滚与禁止边界。
4. **Question for the team**：谁签署最终 Go，S16 前是否先冻结 Demucs/package 的并行文件边界？

## QA

1. **First reaction**：S12a–S15 已闭合局部合同，但仅属分层诊断证据，不能升级为 Release Go。
2. **Key concerns**：S16–S18 并发、崩溃、CLI/ownership、Linux 未完成；macOS/package、资源、Demucs、runtime close、恢复仍缺真实证据；SBOM、attestation、签名、rollback 未闭合，flaky/skip 必须单列。
3. **First action**：固化测试矩阵、证据层级、run ID、flaky、Gate、续跑顺序和禁止边界。
4. **Question for the team**：各缺口 owner、验收环境与最终 Go 签署人是谁？

## 综合结论

- 一致意见：建立三个层次的事实源。W1b-5 专项计划维护字段、错误码和 node 级测试；v2 主计划维护跨工作包 DAG；handoff 只提供当前恢复索引。
- 阻断项：S16–S18 的 process/system/Linux 证据、资源与 lifecycle 决策、双平台 package、真实 Demucs、独立恢复和 release supply chain 未闭合。局部绿测不能晋级 Release。
- 明确张力：current-source CLI 已正确降级，但程序化 API 返回的 sealed document 仍可能含旧 qualification。短期文档禁止误读并新增 unknown-key RED；中期只允许 additive typed outcome，不修改历史 document。
- 执行顺序：S16 -> S17 -> S18 -> W1b-5b 复审 -> 资源预算 -> 双平台 package -> Demucs -> runtime close -> 经授权恢复 -> 经授权 SBOM/attestation/签名/staging/rollback。文档落盘后的宿主 checkpoint 已实跑为 `646 passed, 18 skipped, 22 warnings in 123.64s`，静态与链接检查通过；最新 PASS/BLOCKED sealed evidence 也已完成 `0/0` 与 `3/3` 的独立 verify，sealed tree signature 前后不变。
- 管理要求：首次失败、flaky、skip、平台模拟和证据生成后的源码变化都必须记录；不得只保留最终绿色。

## 本次落盘位置

- W1b-5 唯一技术入口：[`../W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md`](../W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md) 第 19 节。
- 跨工作包唯一执行入口：[`../AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md`](../AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md) 第 29 节。
- 当前交接入口：[`../AI_REFACTOR_HANDOFF.zh-CN.md`](../AI_REFACTOR_HANDOFF.zh-CN.md) 第 15.10 节。
- S12a–S15 实施/反审历史：[`team-session-2026-09-06-2.md`](./team-session-2026-09-06-2.md) 第五次复核。

## 当前 Gate

| 范围 | 结论 |
|---|---|
| S12a/S13a/S13b/S14 | 已声明合同 Go；不等于 crash/power-loss/platform qualification |
| S15 capture current-source | diagnostic-only Go；`transactional=false`、`aba_excluded=false` |
| S15 retention current-source inspect | frozen / No-go；schema v1 禁止发布 |
| W1b-5a | Conditional Go，仅 trusted local assessment-only |
| W1b-5b | No-go，等待 S16–S18 和最新 evidence |
| W1b-5c/5d/5e | 未授权、未实现 |
| v2 Release | No-go |

## 未决人类决策

- rules/assessment digest owner、rotation approver、ADR/审计路径与 W1b-5b Go signer；
- Linux/macOS required runner owner；
- `D-RESOURCE` 三类资源默认上限与迁移策略；
- `D-MACOS-TORCH` 的一致制品/受控重建/依赖升级路线；
- `D-RUNTIME-CLOSE` 的 in-flight、幂等和资源释放语义；
- `D-REL` 的 export/archive/destruction、key custody、RPO/RTO、签名和发布权限。

在这些决策未签收前，可以继续写 RED 和执行本地只读/测试验证，但不能形成相应治理或 Release Go。
