# Teams 20：R1b 实现、独立 QA P1 与本地续接记录

日期：2026-09-07。类型：既有 Teams 结果的落盘，不是新一轮修复或重新验证。

权威方案：[S18 P1 v1.21 第34节](../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)。本记录只保留角色结论与讨论脉络；修复合同、用例、hash、执行 DAG 和续接限制以方案第34.6至34.10节为唯一当前来源。此前记录 [Teams 19](./team-session-2026-09-07-19.md) 保留为 R1a 历史。

## 1. 角色与最终结论

| 角色 | 范围 | 结论 |
| --- | --- | --- |
| `b3e_s_impl` | 唯一代码/测试写入者 | R1b exact15、R1a10、legacy10 GREEN，policy-v3 唯一预期 RED；已停写 |
| `b3e_s_qa` | 独立只读 QA | 同 hash 回归通过，但两个敌意反例形成 P1，non-accepting；已停止旧 hash 探针 |
| `p1_inventory_design` | 只读架构审查 | 接口/单次捕获/真实 main 边界一致，有条件 Architecture Go，等待独立 QA；R3 No-go |
| 主代理 | 文档与协调 | QA P1 未关闭，因此不接受 R1b closure；本次只保存方案，不派发修复 |

架构的 P0/P1 0/0 是其静态审查范围的结论，不是全体团队共识，也不覆盖 QA 的两个 P1。常规测试 GREEN 与安全验收不通过可以同时成立。

## 2. 讨论收敛

- 单次捕获：保留旧 five-key descriptor wrapper，captured loader 成为唯一 compile/exec 核心，直接使用捕获 bytes，不再读取现场路径。
- 身份边界：v2 builder 为纯函数；v1 publication 继续保持，原子消费者迁移属于 R2。v2 plugin 使用无歧义四字段，不沿用 v1 的 record 字段含义。
- 生命周期：真实 main 在 no-site 分支只调用一次 preparation；失败只能退出，owned binding cleanup 不能声明任意模块副作用已回滚。
- QA 反例一：lock 相同内容换 inode 后仍成功；需包围整个 capture 的 pathname before/after 闭合。
- QA 反例二：uv 和 local plugin 的文件字段接受 `/`；需无 I/O 的 non-root-leaf 校验，不扩展为所有目录禁止根路径。
- 计数：R1a 原 exact7 加 supplement4 是11次执行、10个唯一用例、1个重叠；后续用 R1a10 unique 回归。

## 3. 证据与未完成项

实现证据：`/private/tmp/ai-auto-lrc-b3f-r1b.Tx8OCksH`。QA 证据：`/private/tmp/ai-auto-lrc-b3f-r1b-qa.zKi8DW2Y`。主代理落盘时重算三个源码/测试 hash，与两角色冻结报告一致，并读取 QA summary/probe 验证 P1 记录。

当前未完成：两个 P1 的 test-first 修复、新 hash 下 QA fresh replay、扩展 captured-loader/rebound-digest/main 独立探针及 R1b 最终验收。之后仍需 R2/R3/R4、final-schema replay、hostile matrix、B4、freeze ledger 和各平台 qualification。

本次仅文档持久化；S18、W1b-5b、Release 继续 No-go，不触发后续执行。临时证据未复制归档，详细复现与失效处理见权威方案第34.10节。
