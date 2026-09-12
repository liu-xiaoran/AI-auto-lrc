# AI-auto-lrc v2 Teams W1b-4 canonical sidecar（2026-09-06）

本次会话在 W1b-3 Linux package sidecar 已真实闭合后，评审 W1b-4 canonical sidecar。仓库仍没有 `PROJECT-CONTEXT.md`；上下文由当前代码、W1b 专项方案和三份 canonical oracle 的只读检查提炼。PM 由主线程承担，Architect、Developer、QA 三个角色并行只读分析，最终由主线程综合并落盘。

## PM

### 首要判断

W1b-4 的产品价值不是新增一套 golden，而是让已有 functional canonical 运行成为一次可封存、可重算、不能靠旧 artifact 或可变 tag 拼接的 capture。完成后仍只允许 `implemented-unqualified`。

### 关键关切

- 不更新三份 oracle、production 代码或 canonical 环境来换取绿色。
- 不把 W1b receipt 追认为现有 inventory 的 `qualified-canonical`，更不外推 release。
- 高成本 Docker gate 串行；先用 mock/contract 关闭 schema、image、oracle 和 probe 反例。

### 第一行动

把 canonical artifact closure、schema、失败矩阵、真实验收命令和回滚点写成唯一实施入口。

### 团队问题

W1b-5 的长期 retention、secret export 与 checkpoint 内容寻址 owner 由谁签收？

## Architect

### 首要判断

采用 `host producer -> container observer -> capture consumer` 三段信任边界。base image 使用不可变 repo digest；本地 build image 通常没有 RepoDigest，因此以 `docker build --iidfile` 得到并 inspect 的 content-addressed image ID 为身份，运行必须按 ID。

### 关键关切

- 三份 oracle 与 Dockerfile 必须作为正式 artifact 逐字节封存，archived verifier 不能只信 sidecar hash。
- network、read-only rootfs、`/tmp` tmpfs、平台、Python、CPU/thread 与 installed origin 必须由容器内实际探针提供，并与宿主 container inspect 交叉验证。
- `PYTHONPATH=/workspace` 使 harness 源码 import 与 installed distribution provenance 不同；sidecar 必须如实分账，不能把 installed CLI 的 site-packages 结论外推给整个 pytest 进程。

### 第一行动

冻结 strict schema、无环 hash 链和 build/run-by-IID 合同。

### 团队问题

checkpoint 只保存 size/hash 是否满足当前 functional retention，还是由 W1b-5 引入内容寻址快照？

## Developer

### 首要判断

W1b-3 的 stable-read、strict JSON、repo-digest inspect、原子发布和 receipt 复验可复用；wheelhouse、sdist、`.pth` 与 CPython 3.11 合同不可复用。

### 关键关切

- 新增宿主 producer 和容器 observer；capture-bound verify 走 producer，三个 candidate 模式保持原行为。
- build 后读取 iidfile、inspect labels，create/run/inspect 都按 image ID；tag 仅保留显示用途。
- observer 使用隔离子进程从 site-packages 导入 `t2l`，同时明确主 pytest harness 来自 image workspace snapshot；无需修改 Dockerfile 或重基线 oracle。

### 第一行动

先实现无 Docker 的 producer/observer fixture，再接入真实 runner。

### 团队问题

canonical gate 是否需要直接反向绑定 runtime sidecar hash？本轮决定由 capture receipt 同时绑定二者并由 consumer 交叉验证，避免 gate/sidecar hash 环。

## QA

### 首要判断

现有 13 项 canonical functional test 很强，但当前 runner 按 mutable tag 运行、没有 runtime sidecar、没有实际 probe，capture 仍固定 `LAYER_CLOSURE_UNIMPLEMENTED`；因此 W1b-4 当前是 No-go。

### 关键关切

- 每个 oracle、Dockerfile、run ID、gate、image、probe 和 installed origin 都要有单字段篡改反证。
- fake complete closure 只证明 consumer；真实 Docker capture 必须另跑，并在文档最终写入后再生成 current-source receipt。
- public-e2e oracle 当前 live hash与旧文档快照不同，consumer必须重算私有副本，禁止抄文档常量。

### 第一行动

按 schema -> producer -> consumer -> integration -> real Docker 顺序放行。

### 团队问题

真实 SIGKILL 只要求没有有效 `SEALED`，是否由 W1b-5 再加入长期清理策略？

## 综合结论

四个角色一致同意以下阻断条件：只按 tag 运行、只记录 Docker argv、oracle 只有 hash没有私有字节、installed origin 指向 workspace、sidecar 自报高资格，任一存在都不能关闭 W1b-4。

实施决议：

1. 正式 closure 扩为 JUnit、gate、runtime sidecar、Dockerfile、三份 oracle、profile manifest、fixture metadata，以及 producer、observer、canonical runner 三份源码快照；`uv.lock`继续使用 capture inputs snapshot。源码快照让 archived consumer 能独立重算 sidecar 中的 provenance hash。
2. checkpoint 本轮记录角色、相对路径、size/hash，并在 capture 时稳定重算；不把约 128 MiB checkpoint 复制进每个 receipt。archived-integrity只证明已封存 bytes及记录自洽，不声称可脱离资产存储恢复 checkpoint。
3. build image允许 `RepoDigests=[]`，但必须有有效 iidfile/inspect image ID、输入 labels并按 ID运行；base image仍必须是完整 repo digest。
4. observer实际验证 network denial、rootfs write denial、`/tmp` writable、Linux/x86_64/CPython 3.10/CPU单线程和 site-packages installed probe。
5. 完整闭包只移除 canonical 的 `LAYER_CLOSURE_UNIMPLEMENTED`，receipt最高仍为 `implemented-unqualified`；`claim.spec_ids=[]`。
6. 不修改 Dockerfile、三份 oracle或 production provenance；若实现必须改这些输入，停止并按 candidate -> review -> verify 的既有流程建立独立批次。

字段级方案、DAG和测试矩阵见 [`../W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md`](../W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md) 第 17 节。

## 实施回写

第 17 节方案随后已按 W1b-4a–4f 实现，不再以本文件 QA 段落中的“当前 No-go”作为现状。当前事实如下：

- 新增 host producer `scripts/run_canonical_gate.py`、container observer `tests/golden/canonical_capture_observer.py` 和两组 canonical contract tests，并完成 runner/capture consumer 接线。
- 十二件 closure、iidfile/run-by-image-ID、真实 network/rootfs/tmpfs/installed probes、oracle/profile/fixture/checkpoint/lock aggregates、源码快照 provenance 和 receipt 独立复验均已落地。
- 联合快速层 `215 passed, 5 skipped`；2026-09-06 文档回写前宿主全量 `481 passed, 18 skipped, 22 warnings in 67.90s`；Ruff、compileall、shell、lock、build、diff 门禁均通过。
- 真实 Docker capture 为 `13 passed, 7 warnings, 0 skipped in 143.43s`，source 前后相等，raw/normalized/capture exit 均为 0；两种 verify mode 均在各自边界内有效。
- W1b-4 当前为 **Go / implemented-unqualified**，不是 qualified-canonical 或 release 证明。checkpoint 独立恢复、W1b-5、双平台、SBOM、attestation、签名和 rollback 继续 No-go。

字段、hash、历史 run 与当前恢复状态见 W1b 专项方案第 18 节；下一阶段 Teams 结论见 [`team-session-2026-09-06-2.md`](./team-session-2026-09-06-2.md)。
