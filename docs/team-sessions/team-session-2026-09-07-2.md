# Dev Team 会话 S18 P1 加固与测试设计复审

日期：2026-09-07  
模式：Architect、Developer、QA、交接审阅并行只读复核，主任务统一落盘  
当前执行事实源：[`../W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md`](../W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md) 第 17.11 节

## 讨论目标

在不覆盖历史 evidence 的前提下，确认 COV-015 完成后的恢复点，细化 SRC、JUnit、XFAIL、ABA 的实现与测试，并判断这些变化对 Security、package、canonical 和最终 W1b-5b Gate 的影响。

## Architect

- P1 必须按 frozen source、canonical JUnit、xfail events、ABA claim boundary 分成独立回滚单元；不得合并成一次不可定位的 verifier 大改。
- before/after hash 是 sequential endpoint observation，只能发现端点不同，不能证明 swap-and-restore/ABA 不存在。
- immutable execution snapshot 若未来实施，必须冻结完整执行闭包和 dirty/untracked bytes；复制单个 test 或依赖 `git archive` 不足以建立该声明。
- macOS functional/package lane 与 Linux capture-bound receipt 的证据强度不同。没有 macOS 等强 capture 时，最高只能分别声明 platform-scoped 结果。

## Developer 与 QA

- `S18-COV-015` 已通过真实 runner isolation integration，不应继续作为 P0 blocker；旧 17.10 状态必须保留为历史。
- SRC-001、JUNIT-001、JUNIT-002 已按 RED/GREEN 完成，完整 verifier contracts 为 `64 passed`；生产改动只在 verifier，测试改动只在 verifier contract 文件。
- 真实 pytest/JUnit characterization 证明：XFAIL 会写 `pytest.xfail` skipped，XPASS(strict=true) 会写 failure，XPASS(strict=false) 会写与普通 PASS 不可区分的空 testcase。
- 因此只设置 `xfail_strict=true` 并读取 JUnit 不足以关闭 XFAIL-001；必须增加受哈希约束的 pytest events plugin/sidecar，记录 collection marker 和 call report 语义。
- required XFAIL、XPASS(strict=false)、XPASS(strict=true) 都应稳定拒绝；配置、plugin 或 sidecar binding 漂移必须 fail closed。

## 交接审阅

- `AI_REFACTOR_HANDOFF`、`AI_REFACTOR_V2_EXECUTION_PLAN` 和旧 team session 仍指向 COV-015 blocked/A1 恢复点，需追加新版本指针，不能改写历史段落。
- P1 改动 verifier、runner 或 `pyproject.toml` 后，17.10 的 macOS/Linux Security artifact 立即历史化；`pyproject.toml` 变化也使旧 wheelhouse/package artifact 历史化。
- package、canonical、host 和 sealed evidence 必须晚于 P1 最终字节冻结。旧 package/canonical/sealed 结果只保留 historical，不得代签 current。
- 授权边界不变：不 commit/push/建 CI/upload/sync/签名/发布/archive/restore/delete/destruction；W1b-5c/5d/5e 和 Release 不因局部绿色自动开放。

## 方案组织分歧与裁决

一位审阅者建议新建独立 P1 方案，避免继续扩张超长主文档；另一项约束要求 S18 当前事实继续 append 到既有唯一事实源。主任务选择把完整方案追加为主方案第 17.11 节，并在交接文档和跨工作包计划只追加短指针。这样保持单一事实源，不产生两份会独立漂移的执行规范。本会话文件只保存角色观点，不复制完整字段和测试矩阵。

## Teams 合成结论

1. 当前恢复点从 COV-015 后移到 XFAIL events schema/plugin 设计；SRC/JUnit 不重做。
2. XFAIL-001 必须覆盖 required XFAIL、non-strict XPASS、strict XPASS、config/plugin runtime drift，并同时有 sidecar exact-schema 负例。
3. ABA-001 本轮只锁定声明边界，不实现 immutable snapshot，也不让所有正常 Gate 固定失败。
4. P1 最终字节冻结后，依次刷新 verifier contracts/Spec Inventory、macOS 三轮、Linux attempt、package 分层、canonical、host/static、sealed evidence 和 independent review。
5. S18、W1b-5b 和 Release 继续 No-go；5c/5d/5e 继续未授权。

## 已落盘结果

- 主方案新增第 17.11 节，包含架构裁决、pytest events schema、测试用例、DAG、失效矩阵、stop/rollback 和 DoD。
- `AI_REFACTOR_HANDOFF.zh-CN.md` 新增第 15.17 节，指向当前恢复入口。
- `AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md` 新增第 32.4 节，锁定 package 证据分层和跨工作包依赖。
