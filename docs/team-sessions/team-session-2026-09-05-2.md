# AI-auto-lrc v2 Teams W1b-3 续会（2026-09-05）

本次续会复核已落盘的 v2 架构、C01–C10 能力卡、工作包 DAG 与测试矩阵，目标是让后续会话能从 W1b-3 直接编码，同时不把 Linux 单平台证据外推成双平台或 Release 资格。项目上下文来自现有仓库和文档；仓库没有 `PROJECT-CONTEXT.md`，本轮未新建。

## PM

### 首要判断

方案基本足以从 W1b-3 续接，但必须把“已实现能力、测试通过、资格完成”继续分开；Release 仍为 No-go。

### 关键关切

- W1b-3 仅闭合 Linux package sidecar，不得外推 macOS、双平台或 release。
- `D-REL`、`D-MAC`、`D-RES`、`D-DEM`、`D-LIFE` 的 owner、批准人和截止条件必须显式。
- C01–C10 每项必须同时列入口、合同、nodeid、未证明项，避免把 fake 或单层绿测读成产品闭环。

### 第一行动

固化 W1b-3 的前置、产物、反证、完成定义与失败状态检查表。

### 团队问题

谁最终签收 retention 范围和 package sidecar 的长期保存责任？

## Architect

### 首要判断

方案足以从 W1b-3 恢复，但必须以 W1b-0/1/2 的 capture 合同、dirty source identity 和验证命令为入口；sidecar 本身不等于资格升级。

### 关键关切

- W1b-3/4 依赖 capture/verifier，W1b-5 最后收口；W3–W7 继续等待各自决策锁。
- sidecar 只产分层 artifact；capture 负责独占 run、前后快照、receipt 和退出码。
- C01–C10 必须闭合 spec ID -> nodeid -> artifact hash -> qualification -> 回滚点；未决项保持 planned。

### 第一行动

冻结 W1b-3 package sidecar 的正反合同与 artifact closure 表。

### 团队问题

sidecar 命名、保留期限和最终 owner 是否已经批准？

## Developer

### 首要判断

方案基本可续接，但 W1b-3 必须有唯一入口、字段表和文件边界，不能只写目标。

### 关键关切

- 输入必须锁定 package gate、source snapshot、wheelhouse manifest、image digest 与 `.pth` observation；输出 sidecar 临时写入后原子发布。
- 缺件、多件、symlink、跨层、source drift 或 gate 非零只能生成 diagnostic，并保留原退出码。
- 测试命令和允许修改文件须逐项列出；回滚只撤回本轮增量，严禁 reset/restore 用户 dirty worktree。

### 第一行动

先把 W1b-3 恢复表转成失败合同测试，再改 runner。

### 团队问题

package 无 wheelhouse 时应保留何种 sidecar closure？

## QA

### 首要判断

现有 `W1B-T20` 能阻止明显占位 sidecar，但不能证明每个字段来自同一次真实冷安装；W1b-3 必须把“存在性检查”升级为“字段语义与跨件绑定”。

### 关键关切

- 每个高价值字段都要有单字段篡改负例，真实 positive 不能替代反证。
- Linux positive、无 wheelhouse negative、source drift 与 sidecar publish failure 必须分别 capture，不能拼接不同 run 的结果。
- archived-integrity 只证明历史 bytes 自洽；current-source 才能说明与当前 checkout 相符，两者都不得升级 release。

### 第一行动

冻结 schema 及 T01–T14 测试矩阵，再以 RED -> producer -> capture verifier -> real Linux 的顺序放行。

### 团队问题

secret sentinel 命中后是仅禁止导出，还是连本地 `implemented-unqualified` 也必须降级为 diagnostic？该语义需在 W1b-5 由 `D-REL` 签收。

## 综合结论

四个角色一致同意：当前总体架构不需要重写；需要补的是 W1b-3 的字段级合同和失败矩阵。三位以上角色共同提出的阻断项为：sidecar 不能自报资格、所有证据必须绑定同一次 capture、Linux 不得外推双平台、长期 retention/secret 规则仍缺 owner。因此本轮把以下决议写入 [`../W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md`](../W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md) 第 15 节：

1. `package-platform.json` 使用严格 schema v1，并与逐字节 `wheelhouse-manifest.json` 副本共同构成 package sidecar。
2. 宿主 producer 负责 immutable image identity 和原子发布；容器 verifier 只输出可观察事实；capture 独立语义复验并派生 qualification。
3. 无 wheelhouse 时不生成占位 sidecar，保留原 gate failure、required skip 与缺件 diagnostic。
4. W1b-3 分成合同、容器 observation、宿主 producer、capture 集成和真实 Linux 复验五个可回滚子批次。
5. W1b-3 结束后最高仍是 Linux scope `implemented-unqualified`；W1b-4/5、macOS、资源预算、Demucs、runtime close 和 Release 保持 No-go。

## 未决张力

- image 的批准 digest、sidecar/receipt 的长期 owner、期限、加密与销毁方式仍属于 `D-REL`/`D-MAC`，本次没有替人类做决定。
- secret sentinel 命中时的本地资格降级规则尚未锁定；W1b-3 先保证不导出、不上传和显式记录，最终语义留给 W1b-5。
- 本次只保存讨论和可执行方案，不创建 ADR。需要把 image/retention 策略升级为 accepted architecture decision 时，应先由指定 decider 审阅草案再写入 `docs/adr/`。

## 实施回写：W1b-3a–3e

团队方案已实际执行，不再只是讨论稿：容器 observation、宿主 producer、package scope runner、capture semantic verifier 和正反合同均已落地。三个并行实施角色分别负责 Linux observation、immutable-image/atomic producer 与 capture consumer；主线程完成接口合并、真实门禁和文档收口。

QA 顺序按本会结论执行：合同/producer 快速层 -> 默认无 wheelhouse 负例 -> 真实 Linux positive -> receipt 双模式验证 -> 宿主全量与静态/构建门禁。真实 positive 首先发现 consumer 错误拒绝标准 `package-gate.json` 的诊断字段；修复并补回归后，后续 capture 为 `33 passed, 3 deselected, 0 skipped`，四件套、run ID、source identity 和 semantic closure 全部通过。

最终角色共识保持不变：W1b-3 只关闭 Linux package sidecar，最高 `implemented-unqualified`。T14 的长期 secret/export/retention 语义留在 W1b-5；canonical sidecar、macOS/双平台与 Release 均未被本轮结果外推。详细恢复数据见 [`../W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md`](../W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md) 第 16 节，主路线状态见 [`../AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md`](../AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md) 第 25 节。
