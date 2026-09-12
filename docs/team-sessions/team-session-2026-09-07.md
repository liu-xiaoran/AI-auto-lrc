# Dev Team 会话：S18 当前 checkpoint 与剩余重构方案

日期：2026-09-07  
模式：PM / Architect / Developer / QA 并行只读复核，由主任务统一落盘  
主题：在不改写历史证据的前提下，把已完成的 R0.2/R1.2/Security Gate、剩余 P0/P1 与最终资格化步骤收敛为可执行方案。

> 本文保留 Teams 角色观点和合成结论，不复制易漂移的完整 hash 或测试数。当前唯一详细执行事实源是 [`../W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md`](../W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md) 第 17.10 节。

## 问题定义

当前字节下，schema v2 toolchain closure、per-required-runner success/fail-closed、CAP-01/09/17 Linux exact nodes、CAP-12 两平台 native no-replace、macOS 三轮和 Linux 统一 Security Gate 都已有可重算证据。需要决定如何记录这个 checkpoint，并把真实 runner test-drift integration、P1 hardening、package/canonical/host 刷新和 sealed evidence 复核组成下一阶段的可回滚 DAG。

## PM

1. **First reaction**：双平台 Security Gate 是有价值的 current checkpoint，但不能被包装成 S18 或 W1b-5b 完成。
2. **Key concerns**：P1 不能在 DoD 中静默消失；package/canonical/security 不能互代；W1b-5c/5d/5e 和 Release 不得因局部绿色自动开放。
3. **First action**：将 17.9 历史化，以 append-only 17.10 锁定当前声明、缺口、停止条件和最短恢复路径。
4. **Question for the team**：P1 五项是全部纳入本轮，还是有具名 owner 和风险接受者的 accepted defer？

## Architect

1. **First reaction**：应把剩余工作拆成 COV-015、source freeze、JUnit grammar、xfail/config、ABA/claim、package、canonical 和 docs 独立回滚单元。
2. **Key concerns**：`_source_symbols(path)` 与稍后 hash 存在双读 TOCTOU；JUnit classname/name 当前宽松拼接；before/after 端点 hash 不能证明 ABA-safe。
3. **First action**：先以隔离副本闭合 COV-015，再按 SRC → JUnit → XFAIL → ABA/claim 顺序推进 P1，最后统一刷新证据。
4. **Question for the team**：哪些文件变化应使 Security、package 或 canonical 证据失效，是否已逐类锁定？

## Developer

1. **First reaction**：R0.2 与 R1.2 的生产/合同行为已形成可执行基线，下一步不应重做 Linux exact nodes 或 native rename 测试。
2. **Key concerns**：COV-015 尚缺真实 runner 集成而不是 verifier JSON 篡改测试；P1 不应合并成一次大改；当前 dirty worktree 中的旧成果和根 `./=` 必须保留。
3. **First action**：用受控 fake `uv`/pytest 从真实 runner 入口制造 test bytes drift，保留 RED/fixture/GREEN 为不同 attempt。
4. **Question for the team**：若 COV-015 只增加闭包外 contract test 而不改受约束字节，是否按失效矩阵允许保留当前 Security checkpoint？

## QA

1. **First reaction**：六个 macOS lane 和 Linux `attempt-003` 的 source/test/policy/manifest/runner/verifier/pytest-config 闭包已由 raw artifact 重算一致，可以作为 current security 基线。
2. **Key concerns**：必须保留 Linux `attempt-001/002` 和 runtime-count flaky；macOS 只允许一个精确 device exclusion；required missing/deselected/skip/xfail/fail/error 必须立即停止。
3. **First action**：在 17.10 中写入 current hashes、六个 macOS Gate/JUnit/coverage hashes、Linux 终态 hashes 与输入一致性结论。
4. **Question for the team**：最终 sealed evidence 的 reviewer 如何与 producer 逻辑分离，以免把同一份自报结果称为独立验证？

## Synthesis

- 四角色一致同意：17.9 必须保留为 historical，当前事实 append 到 17.10，不覆盖原有 RED 和失败 attempt。
- 四角色一致将 `S18-COV-015` 真实 runner integration 视为剩余 P0 阻断；现有 before/after 实现和 verifier 直接合同不能代替它。
- P1 归属是当前唯一需显式锁定的范围决策：默认纳入 S18/W1b-5b DoD；只有具名、有风险接受和声明收缩的 accepted defer 才允许后移。
- 失效矩阵必须按 evidence domain 执行：Security、package、canonical 分别重跑，不无条件全量重做，也不互相代签。
- **Blocking issue**：COV-015、P1 决策、package/canonical/host 最终刷新和 sealed evidence 独立复核未完成前，S18、W1b-5b 与 Release 保持 No-go。

## 已落盘决议

完整的当前字节、evidence 索引、P0/P1 测试、执行 DAG、失效矩阵、停止/回滚和 DoD 已写入 S18 主方案第 17.10 节。恢复时从该节 A1 开始，不再从历史 17.9 的首个未勾选项重来。
