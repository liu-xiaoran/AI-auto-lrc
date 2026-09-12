# S18 P1 Teams 续接评审 2026-09-07 第四轮

## 目标

复核 `S18-P1-PLAN-v1.4` 与当前工作区是否一致，把 B3c、B3e 的实际实现状态、B3f 的可执行架构、测试 oracle 和无损恢复入口写回本地权威方案。评审仅做只读检查，文档由主任务统一追加；代理没有直接修改仓库文件。

## 角色结论

### Architect

- v1.4 仍把 B3c 和 B3e 写成 planned，并把恢复起点放在 B3c RED；当前工作区已完成 B3c 实现和 B3e 核心真实 runner 场景，必须建立新 checkpoint，避免重复实施。
- B3f 必须拆成两个原子子包：B3f-L 约束 events producer，B3f-R 绑定单一 uv Python 与 named core runtime closure。
- B3f 会改变 policy、plugin、runner、verifier、argv 和 evidence schema；正式 B3e 平台证据应在 B3f 后重放，否则会立即历史化。
- identity 当前字段 `record_sha256` 表示 RECORD entry 声明的源码 digest，不是整份 RECORD 文件 hash；在 B3f-R 前不得宣称 wheel provenance、完整 import graph 或 portable self-contained replay。

### QA

- 当前 security contract 全文件由主任务独立验证为 `179 passed`，它是 macOS host contract checkpoint，不是正式 platform evidence closure。
- B3e 核心场景覆盖 XFAIL、两类 XPASS、bootstrap/identity 失败和 events 发布失败，但参数化 nodeid 未显式设置稳定 `ids=`；正式 traceability 和 evidence 前必须修正。
- hostile fixture 仍需拆出真实 installed entry-point、marker removal、selection injection、ancestor/repository conftest 等独立场景；每个场景要有稳定 scenario ID、pytest/outer exit、Gate failures 和 artifact allowlist。
- B3f-L 必须覆盖 exact boundary、`+1`、Unicode byte/character 差异与 writer fault matrix；B3f-R 必须覆盖 no-site、distribution/lock 唯一性、origin/RECORD/METADATA 漂移和 uv/lock endpoint drift。

### Handoff reviewer

- v1.4 方案尾部可通过细读恢复，但文件首屏仍显示 v1.0，Handoff 首屏仍指向历史节，容易让新执行者从错误步骤开始。
- 新版本需要一个 Current Resume Capsule：当前 hash、branch/HEAD、状态表、可复制 preflight、证据易失性、停止条件和唯一下一步。
- `/private/tmp` 证据易失且部分只有外层 JUnit；路径消失只能记录为 historical evidence unavailable，不能推导从未执行，也不能擅自重跑或提升声明。
- 每次方案字节变化后必须重算 SHA-256，并在 Handoff、V2 主计划、Retention 和 S18 主资格方案追加同一版本、section、下一步与 Gate 指针。

## 裁决

1. 新增 `S18-P1-PLAN-v1.5`，第 18 节成为唯一恢复段；第 17 节保留为历史 checkpoint。
2. B3c 状态为 host implementation complete、host contracts green、formal platform evidence pending；B3e 状态为 core scenarios implemented、host contracts green、full matrix and platform evidence pending。
3. 当前最大声明只允许描述两个注册 pytest plugin object 与观察到的入口 bytes 已绑定；不允许使用 supply-chain trusted、wheel verified、complete import graph、dual-platform qualified、ABA-safe、transactional 或 immutable snapshot。
4. 下一步先建立稳定 B3e scenario IDs 和 P1 ID authority，再解决 B3c RECORD 字段与 no-replace 规范；随后顺序执行 B3f-L、B3f-R，并在最终 schema 下重放 B3c–B3e。
5. B3f-L 只约束 events plugin 自身累积与 sidecar 写出，不声称限制 pytest 全进程的内存、CPU 或 collection 开销。
6. B3f-R 只绑定 named core runtime closure；没有绑定 wheel artifact 与 lock hash 时，不得把 installed RECORD 自洽写成 wheel provenance。
7. B4b 先冻结 typed claim authority，B4a 再做 swap-and-restore characterization；characterization 的 GREEN 表示声明边界正确，不表示 ABA 防护已实现。
8. S18、W1b-5b、Release 继续 No-go；commit、push、CI、upload/sync、签名、发布、5c/5d/5e 和 destructive cleanup 仍未授权。

## 文档责任

完整状态表、schema、测试矩阵、preflight、evidence index 和恢复 DAG 只维护在 `docs/S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md` 第 18 节。本文件只保留角色意见和裁决理由，避免形成第二份易漂移执行规范。
