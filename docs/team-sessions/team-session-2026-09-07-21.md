# Teams 21：R1b 两项 P1 修复验收与 R2 依赖收敛

日期：2026-09-07。权威方案：[S18 P1 v1.22 第35节](../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)。前序 [Teams 20](./team-session-2026-09-07-20.md) 保留旧 QA non-accepting 快照。

## 1. 本轮角色与结果

| 角色 | 实际工作 | 结论 |
| --- | --- | --- |
| `b3e_s_impl` | 唯一代码/测试写入者，补反例 RED、局部修复、post-Ruff 全部选择集 replay | exact15 15 passed / R1a10 10 passed / legacy10 10 passed；policy 唯一预期 RED |
| `b3e_s_qa` | 新 hash 下独立回归和扩展危险点 probes，不修改仓库 | 两个 P1 关闭，P0/P1 0/0，PASS |
| `p1_inventory_design` | 冻结静态审查与 R2/R3 依赖分析，不运行测试 | R1b 无架构阻塞；R2 必须包含真实启动与 writer cutover |
| 主代理 | 核对当前源码、校验证据索引、协调串行测试、维护权威文档 | R1b 按冻结 hash 验收；整体重构未完成 |

## 2. 关键讨论与裁决

- lock 不仅要 fd stable read，还需包围 parse/canonicalization/digests 的 pathname before/after；同内容不同 inode 反例在旧实现 RED、新实现 GREEN。
- executable/plugin 文件 leaf 不能是 `/` 或 `//`；用词法检查保持 builder 无 I/O，不禁止合法目录根路径。
- before/after 不是同 inode ABA 或最终观测后永不变化的证明。
- exact15 节点数未增加；新增 mutation 在两个节点内独立触达，失败后聚合断言，避免首例遮蔽。
- R2 仅修改 consumer 会与 runner 的 v1 producer/writer 冲突；ABS_UV 前缀、no-site 强制、legacy 分支删除、environment 版本重解析删除必须随 schema 原子切换前移。R3 留给真实双 lane 与敌意 integration 验证。
- 当前 input guard 是 shell 调用 Python，不是纯 Bash；R2 要在 uv 执行前先拒绝 existing/dangling-link root，不能把历史文档措辞当成已实现能力。

## 3. 证据定位与状态边界

最终三份 hash、RED/GREEN/QA hash 和 test oracle 统一记录在权威方案第35.3、第35.8节，不在多个文档复制可漂移证据。

实现证据根：`/private/tmp/ai-auto-lrc-b3f-r1b-fix.agHlxCej`；独立 QA 根：`/private/tmp/ai-auto-lrc-b3f-r1b-fix-qa.5CfHZ4bL`。原始静态工具输出仍在执行轨迹，执行 ledger 为摘要，不宣称完成永久原始日志归档。

R1b 验收仅为当前 host producer foundation。未执行 R2、真实 security runner、final67、平台资格化、commit/push 或 W1b-5c/5d/5e。下一步从权威方案的 R2 精确合同与原子迁移接续。
