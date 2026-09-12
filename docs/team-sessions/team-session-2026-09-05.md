# AI-auto-lrc v2 Teams 可执行重构与测试方案（2026-09-05）

本文固化 2026-09-05 的 Teams 讨论、能力边界、执行顺序、测试设计和证据口径，作为后续会话的恢复入口。规范性目标仍以 [`AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md`](../AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md) 为准；LegacyV1 历史事实和 v2 当前能力入口见 [`AI_REFACTOR_HANDOFF.zh-CN.md`](../AI_REFACTOR_HANDOFF.zh-CN.md)。若三者冲突，以当前源码和直接自动化测试为事实依据，并先修正文档再扩大资格声明。

当前结论是：v2 核心重构可继续实施，portable required gate 与 Linux x86_64 单平台 cold-install gate 已在当前工作树通过，但 Release 仍为 **No-go**。functional canonical、portable、单平台 package 和 release provenance 是四种不同证据，任何一层不得代替另一层。仓库当前没有 CI workflow，因此本文的 gate 都是可执行的本地门禁，不得描述为托管平台的 required check。

## 1. 本轮范围与不变量

本轮保留以下决策，不在实现中暗改：

- 不修改冻结的 `t2l/mtl/model.py` 和 `t2l/mtl/utils.py`，不借重构改变 LegacyV1 数值协议。
- 不恢复已经删除的旧 `main.py`、`t2l/t2l.py`、`ext/`、训练和旧评估公共入口。
- natural non-empty partial 没有批准的 confidence/cutoff 语义，继续 Deferred；`aligned=0` 是 incomplete failure，不是 partial result。
- 不篡改 macOS Torch wheel 的内部 tag，不降低 `pip check` 强度，不以宿主已安装依赖代替冷安装。
- 不把 dirty-worktree canonical 写成 clean commit、signed release、SBOM 或 attestation 证明。
- 不新增 CI workflow、ADR、发布或 Git 历史操作；这些动作需要独立授权或决策。

## 2. Teams 四角色结论

### PM

第一优先级是用户可感知的真实输入到真实输出：真实 MP3、公开 Python API、installed CLI、四个模型路由、line/word LRC。该链路已经取得 Linux canonical functional evidence；下一步不应继续增加 fake happy-path，而应关闭资源上限和双平台冷安装。

产品侧必须先决定三个资源限制的默认值、单位、配置入口和迁移策略，并决定 runtime 的公开关闭语义。未决定前，开发者只能补不改变公共合同的底层安全性，不能自行发明错误码、生命周期状态或 partial 行为。

### Architect

系统边界保持为 `public API/CLI -> application use case -> ports -> adapters -> LegacyV1 inference/domain renderer`。`t2l.composition` 是唯一默认 concrete wiring 点；domain/application 不得反向 import adapter、Torch、音频库、Demucs、fastText 或文件 sink。

运行时资源采用 owner-local 所有权和 runtime-local 锁。LID、G2P 和 checkpoint 的校验对象必须是消费时持有的同一不可变字节快照，不能先按路径校验、再按路径重新打开。`MaterializedAssetSet.close()` 可以先做到并发、幂等、互不干扰；公开 `AlignmentRuntime.close()` 必须等 close/in-flight、close 后错误、临时 runtime 自动关闭和 NLTK 全局路径租约语义锁定后再做。

### Developer

每个工作包只允许修改一个可回滚边界，并用独立 pytest nodeid 和机器可读 gate 报告证明。当前已具备本地 gate policy、coverage/JUnit verifier 和 portable/package/canonical 分层 runner；后续实现不应再靠人工阅读 coverage 文本或总测试数判断。

可直接实施的下一步是：资源合同获批后增加 fail-fast；把已经通过的 Linux cold wheelhouse 流程迁入受控 artifact/CI；建立 Demucs 独立资产 manifest；最后才做恢复和发布绑定。每个工作包失败时保留失败 artifact，不更新 qualification。

### QA

Required 层必须同时满足测试零失败、零 error、零 skip、用例来源没有跨层混入。coverage 还必须同时满足整体 line、changed executable line 和关键函数 line/branch 三类阈值；其中 coverage.py 展示的 branch-aware 综合百分比不能冒充纯 line coverage。

测试结果必须绑定提交或 dirty-worktree 状态、Python/OS、lock hash、asset/oracle hash、选择器、通过/失败/skip 数。portable、package、canonical 分别生成独立 JUnit；Release 只能在全部 RC required 层零 skip 且 provenance 完整后产生。

## 3. 目标架构与证据流

```text
CLI -----------------------------+
                                 v
Python API -> AlignmentRequest -> application use case
                                      |
                         ports + ProgressObserverPort
                                      |
              +-----------------------+-----------------------+
              v                       v                       v
       lyrics/G2P adapters      audio/model adapters     atomic output adapter
              |                       |
              +----------> structured alignment <--------+
                                      |
                              pure LRC renderer

portable evidence  -> unit + contract + component, source checkout
package evidence   -> built artifact + isolated installed environment
canonical evidence -> pinned Linux/CPython/assets/oracles, offline/read-only verify
release evidence   -> clean signed source + both platform packages + SBOM/attestation/rollback
```

数据和副作用边界：

- Python API 接收已解码歌词行和音频路径，返回 `AlignmentResult`；不得写文件、stdout/stderr 或访问网络。
- CLI 独占歌词文件读取、stderr progress、stdout 或原子文件输出；stdout 与文件输出互斥。
- application 只编排 port、完整性策略和 diagnostics，不知道具体文件路径、第三方模型或下载器。
- renderer 是纯函数；完整性判定必须在 renderer 前完成。
- package/canonical runner 只消费已构建 artifact；不能从 checkout、宿主 `.pth`、用户 cache 或网络旁路依赖。

## 4. C01 到 C10 可执行能力卡

### C01 CLI 歌词音频对齐

- 正式入口：`ai-auto-lrc` -> `t2l.adapters.cli:main`。
- 输入合同：歌词路径、音频路径、model/profile、decoder policy、timestamp mode、strict/partial policy 和可选输出路径；目录、FIFO、device、symlink 等非普通目标必须失败关闭。
- 输出合同：stdout 与原子文件二选一；stdout 只含 LRC，progress/warning/error 只到 stderr；新建和覆盖目标 mode 为 `0600`。
- 失败合同：registered error 决定安全消息和 exit code；SIGINT 为 130，closed pipe 为 141，unknown error 为泛化 exit 1。
- 已有证据：参数、locale、version、signal、broken pipe、路径安全、原子写；canonical 四路 installed CLI 与 API 字节一致。
- 待补：macOS 冷安装后的 CLI、Linux 候选的受控 artifact/CI 持久化、Demucs installed-extra、staging/rollback。测试必须从源码树外 CWD 执行，并审计 `t2l.__file__`。

### C02 Python 推理 API

- 正式入口：`t2l.create_runtime(config)` 和 `t2l.process(request, runtime=...)`。
- 数据合同：输入为 frozen request/config 值对象；输出为结构化 `AlignmentResult`，包含 status、word/line spans、timebase、profile 和 diagnostics。
- 副作用合同：API 本身不创建文件、不写终端、不联网；资产和模型只允许通过 runtime 显式只读加载。
- 并发合同：同一 runtime 的非线程安全第三方实例串行化；不同 runtime 不共享同一把锁；确定性初始化失败可 sticky，控制流异常不得污染缓存。
- 已有证据：四路真实 public API canonical、并发一次初始化、RNG 不污染、SIGINT 后可恢复。
- 待补：公开 runtime close、close 与 in-flight 行为、临时 runtime 自动释放、GPU 和大输入资源限制。

### C03 歌词文件编码探测

- 所有者：CLI lyrics I/O adapter；Python API 继续接收已解码文本。
- 输入/输出：普通文件 bytes -> 确定的 Unicode 行序列；BOM、候选编码和不可解码位置必须可诊断。
- 安全边界：不信任 locale，不静默替换控制字符，不把 CWD 或用户默认编码当隐式配置。
- 已有证据：UTF-8/BOM、候选编码、不可解码和 `LC_ALL=C` 子进程。
- 待补：Windows/macOS/Linux 更广 locale、超大歌词的 bounded read、恶意或冲突 BOM/encoding 负例。

### C04 歌词清理与行组织

- 所有者：`LegacyV1LyricsAdapter.prepare()`；一次生成 display tokens、phonetics、phones、word/line 半开区间和 diagnostics。
- 不变量：各索引长度与顺序一致；无中间缺口；diagnostics 按值去重；不把不可发音文本伪造成 phone。
- 已有证据：标签、空行、重复 token、数字、混合文本、结构化 spans 和 public-e2e lyrics plan。
- 待补：极长歌词的 `max_phone_count` 预检和错误映射；natural non-empty partial 继续等待产品/算法 ADR。

### C05 行级语言识别与离线 G2P

- 所有者：`PhoneticConverter` + `OfflineG2PProvider`；encoder 只依赖 G2P callable，不理解 manifest、NLTK 或路径。
- 资产合同：LID 为单成员 materialized set，G2P 两个 zip 为不可分割集合；显式 asset root，默认断网，校验/消费同一快照。
- 并发/释放：同 runtime 锁保护初始化和调用；初始化中断清理 owner 并允许重试；owner close 并发幂等且不同 snapshot 互不影响。
- 已有证据：真实 `hello -> HH AH0 L OW1`、空 cache/断网、hash/size/license、TOCTOU、并发和中断。
- 待补：五语 canonical 矩阵、公开 runtime close、NLTK 全局 search path lease/refcount。

### C06 音频解码与可选 Demucs

- 所有者：audio preparation port 的 concrete adapter；decoder policy 显式。
- 默认合同：torchaudio 成功即使用；`librosa-mono` 只有显式选择时改变声道语义；Demucs 默认关闭且不得 import/download。
- 输出合同：`AudioBuffer` 明确 dtype、channel-first、采样率和 sample 数；重采样和 mono/stereo 语义不可由 fallback 隐式改变。
- 已有证据：WAV/MP3 component、真实 MP3 canonical waveform/Mel fingerprint、默认路径 Demucs 零 import/零请求、缺少 vocals extra 的稳定错误；`AUD-011/012` 已覆盖缺少 `vocals`、`-1/0/3/4` 和短 bag；separation 重采样顺序为 decoder 原始 rate -> model rate -> 22050；只有 Demucs 自身缺失的 `ModuleNotFoundError` 归类为 dependency missing，backend 内部 `ImportError` 归类为 vocals failed。
- 待补：`max_audio_samples` 单位和 metadata probe、probe/load TOCTOU、真实离线 Demucs 权重 manifest/来源/许可、本地 repo 强制、installed-extra 断网运行、runtime-local 单次初始化和双平台 codec。

### C07 声学模型加载与推理

- 所有者：`LegacyV1Inference`；Baseline、MTL、Baseline_BDR、MTL_BDR 按请求惰性加载。
- 不变量：profile/model contract version 先于资产加载校验；checkpoint 从同一 immutable bytes snapshot strict load；局部 seed 不改变调用方 NumPy/Torch RNG。
- 并发合同：同一 runtime 的 feature/model forward/smoothing 串行化；初始化一次；不同 runtime 的并行能力只按实测声明。
- 已有证据：feature/numeric canonical、四路真实 public-e2e、checkpoint TOCTOU、并发和 RNG。
- 待补：`max_posterior_cells` 的精确定义和 forward 前预检、CUDA、性能基线、signed asset binding。

### C08 DTW BDR 对齐与 LRC 渲染

- 所有者：LegacyV1 inference 产生结构化 spans，domain renderer 只负责 line/word 视图。
- 不变量：DTW/BDR、tie-break、timebase 和 frame 边界保持；完整性在输出前判定；partial 只能是从 token 0 开始的非空连续前缀。
- 资源合同：已有 `max_alignment_bytes` 和一帧下界预检；不能把该优化写成完整 `RES-003/005`。
- 已有证据：reference vectors、numeric canonical、四路真实 public-e2e、Baseline_BDR line/word exact。
- 待补：phone/posterior/DP 的完整资源预算、natural partial ADR、性能固定 runner。

### C09 标准与逐字 LRC 输出

- v2 不再发布旧“增强转标准”独立 CLI；`TimestampMode` 从同一结构化 alignment 直接选择 line 或 word renderer。
- 输出合同：UTF-8、时间单调、格式精确、末尾换行策略稳定；API 与 CLI 的差异只允许是 CLI 末尾一个 LF。
- 已有证据：unit snapshot、四路 canonical API/CLI byte exact、原子 sink。
- 待补：macOS cold wheel 与双平台聚合证明、极长时间轴和超大输出的性能/资源边界；Linux 单平台 cold wheel 已有 installed CLI exact 证据。

### C10 领域错误与可观测性

- 事实源：`t2l.errors.ERROR_REGISTRY`；每个稳定 code 绑定异常类型、stage、required details、cause policy、CLI exit 和 safe-message policy。
- producer/consumer：动态错误只通过注册表工厂构造；CLI 只通过注册表消费；未登记或类型/stage 不匹配时降级为 `T2L_ERROR`/exit 1。
- observer：Python API 使用 Null observer；CLI 只把稳定阶段事件写到 stderr；非 debug 消息必须去路径、密钥和 traceback。
- 已有证据：registry AST/contract、unknown/debug/redaction、progress 顺序、compatibility fail-fast。
- 待补：资源上限和真实 Demucs backend 的新错误项；它们必须先决策、注册、生产、消费和测试，不能只加字符串。

## 5. 工作包与依赖顺序

| 顺序 | 工作包 | 允许的修改范围 | 退出条件 | 回滚单元 |
|---|---|---|---|---|
| P0 | 本地质量门禁固化 | `packaging/quality-gates.toml`、gate scripts、gate self-tests | portable 为零 skip；overall line >= 80%；diff line >= 90%；关键函数 line/branch 100% | policy、runner、verifier、定向测试 |
| P1 | 资源合同 | request/config、ports、lyrics/audio/inference 预检、registry、tests | `max_phone_count`、`max_audio_samples`、`max_posterior_cells` 在昂贵步骤前失败；spy 调用数为 0；`RES-003/005` 可登记 | 三个阈值和对应预检 |
| P2 | Linux cold wheelhouse | builder、Linux verifier、package tests、artifact manifest | amd64/CPython 3.11 断网只读、空 cache、sdist 离线 build、no-index install、`pip check`、imports、真实 CLI 全绿；manifest 路径/symlink/tag/`.pth` fail-closed；verify/install 只消费私有 snapshot；`PKG-019` 仅 Linux scope | 单平台 builder/verifier；持久化制品与 snapshot TOCTOU 待完成 |
| P3 | macOS 制品策略 | 用户批准的 ADR 后才允许实现 | 可信上游制品、可审计重建并重签、或升级 Torch 三选一；重跑全部 canonical/package | ADR 对应依赖和 wheelhouse |
| P4 | Demucs optional 路径 | 独立 manifest、extra、adapter、package/component tests | 默认零 import；缺 extra/缺权重/hash 错误稳定；installed extra 断网真实执行 | vocals extra 与权重资产 |
| P5 | 恢复与发布 | recovery bundle、CI/release config、SBOM、attestation、signing、rollback drill | clean signed source；Linux/macOS 矩阵；全部 RC required 零 skip；`AST-022`；首个 `qualified-release` | 发布配置和可撤回制品 |

P1 和 P2 在产品资源决策完成后可并行；P3 必须先有用户批准的 ADR；P4 可与 P2 并行但不能提升 core release；P5 依赖 P1–P4 和 clean provenance。任何工作包不得改写 canonical oracle 来“修复”生产回归。

## 6. 需要先锁定的人类决策

### 6.1 资源单位与错误

- `max_phone_count`：按 phone 个数还是 token/span 个数计；默认值；配置入口；是否属于 lyrics/exit 4 或 alignment/exit 7。
- `max_audio_samples`：按每声道 frame、总 scalar、源采样率 frame 或重采样后 frame 计；未知 duration 和畸形 header 的处理。
- `max_posterior_cells`：按 `frames * 41`，还是 MTL raw `frames * 41 * 47`；能否在 model forward 前可靠推导。
- 每个超限错误的稳定 code、stage、required details、safe message 和迁移策略。

### 6.2 Runtime 生命周期

- `close()` 遇到 in-flight `process()` 是等待完成还是立即拒绝。
- close 后调用使用什么稳定错误；CLI 和 `process(runtime=None)` 是否在 `finally` 关闭临时 runtime。
- NLTK 全局 search path 使用 lease/refcount 还是进程期保留。
- 释放模型/CUDA 是否只删除本 runtime 引用，禁止影响其他 runtime 的全局 cache。

### 6.3 macOS Torch 制品

必须在以下方案中明确选择并记录取舍：使用上游 tag 一致制品；对来源可验证的 sdist/源码做可审计重建并重新签名；升级 Torch/torchaudio 并重跑所有 feature、numeric、public-e2e canonical。不得直接改下载 wheel 的 `WHEEL` 文件。

## 7. 测试用例设计

### 7.1 P0 本地质量门禁

| 用例 | 层级 | 动作 | 必须断言 |
|---|---|---|---|
| QG-01 policy 固定 | contract | 解析 `quality-gates.toml` | overall 80、diff 90、仅冻结文件排除、五类 critical、三层 zero-skip |
| QG-02 diff 边界 | contract | 构造 9/10 与 8/10 executable line | 90% 通过；80% 失败；注释/空行不进入分母 |
| QG-03 untracked/frozen | contract | 临时 Git 仓库增加 tracked/untracked/frozen Python | untracked 被统计；冻结路径排除；缺 coverage record 失败 |
| QG-04 critical branch | unit/contract | 构造 function summaries | 任一关键函数 line 或 branch 非 100% 即失败 |
| QG-05 JUnit 隔离 | contract | 构造 skip、failure、空 suite、跨层 classname | required 层逐项失败；不能混用 package/golden 证据 |
| QG-06 runner wiring | contract | 检查可执行位和选择器 | portable/package/canonical 各写独立 JUnit，不共用结果 |

### 7.2 P1 资源合同

| 规格 | 场景 | 必须断言 |
|---|---|---|
| `RES-003` | phone 数量等于/超过阈值 | 边界值通过，超限稳定失败；decoder/model/DP spy 均为 0 |
| `RES-005` audio | header 可知、未知、畸形、probe/load 被替换 | 超限在 materialize 前拒绝；TOCTOU 失败关闭；错误 details 不泄露绝对路径 |
| `RES-005` posterior | 四模型 route 的 shape upper bound | forward 前可推导时 model spy 为 0；不能推导时不得宣称 pre-forward gate |
| `RES-003/005` DP | 一帧下界和完整矩阵预算 | 必然超限在 span/model/allocation 前拒绝；精确边界不误拒绝 |
| `RES-004` | 固定 runner 上 paired baseline/new | warm-up 与 measurement 分离；阶段计时 JSON；median/p95/RSS 门槛按主计划第 9 节 |

性能资格还必须锁定 runner identity、30 秒和短请求 fixture、paired baseline artifact、阶段计时 schema、dirty-worktree provenance 和 artifact owner；普通宿主测量只作诊断。

### 7.3 P2/P3 Package 矩阵

| 场景 | Linux package 断言 | macOS package 断言 |
|---|---|---|
| manifest 闭包 | 全部文件 size/SHA-256 可重算，无未登记文件 | 同左 |
| wheel tag | 每个 wheel tag 与 CPython 3.11/Linux x86_64 tag 集有交集 | 每个 wheel tag 与 CPython 3.11/macOS arm64 tag 集有交集 |
| 网络/cache | 系统连接被拒绝；HOME/XDG/pip/uv/Torch/HF/Demucs cache 为空 | 使用平台级网络熔断并重复同一断言 |
| build/install | 发布 sdist 离线隔离 build；全新 venv `--no-index` 安装 | 同左；Torch 内外 tag 必须一致 |
| runtime | `pip check`、15 个直接依赖 import、无 `.pth`/checkout import | 同左 |
| user path | repo 外恶意 CWD 执行真实 MP3 -> 精确 LRC | 同左 |
| 负例 | wrong tag、损坏 hash、网络可用、host `.pth`、源码路径任一导致 gate 失败 | 同左 |

Linux 单平台通过最多把 `PKG-019` 记为 Linux scope 的 implemented-unqualified。`PKG-012/017` 要求 Linux 和 macOS 矩阵，不能提前资格化。

### 7.4 P4 Demucs

- 默认请求：`demucs` module before/after 集合为空，network/download 事件为 0。
- 未安装 extra：稳定 `T2L_VOCALS_DEPENDENCY_MISSING`、exit 5、无 traceback。
- 已安装 extra 但无权重：稳定 asset error，不能联网下载。
- 权重 LFS pointer、size/hash mismatch、source 缺失：各自独立 nodeid，全部在模型执行前失败。
- 权重有效：断网 installed-wheel 环境对短音频执行真实 separation，验证 sample rate、channel、dtype、source name 和临时资源释放。
- 并发：同 runtime 只初始化一次；中断不形成 sticky 半成品；不同 runtime 的 owner 互不删除。

### 7.5 P5 恢复与发布

- 在隔离目录从 Git bundle 恢复目标 commit，并证明不存在对原工作树或用户 cache 的读取。
- LFS 实体、lock、profile manifest、三份 canonical oracle 和 package manifest hash 全部重算一致。
- 由恢复出来的 clean source 构建 Linux/macOS 制品，重新执行 portable/package/canonical required gate，零 skip。
- 生成并核对 SBOM、provenance attestation、签名、tag -> commit -> artifact hash 绑定。
- staging smoke 后执行上一版本 rollback drill；记录开始/结束、恢复目标、数据兼容和结果。

## 8. 当前可复验证据

2026-09-05 在当前 dirty worktree、macOS arm64、CPython 3.11.4 上执行：

```bash
AI_AUTO_LRC_GATE_ARTIFACT_DIR=/tmp/ai-auto-lrc-w1-portable.Pd78d5 \
  scripts/run_test_gate.sh portable HEAD
```

结果：`276 passed, 22 warnings, 0 skipped in 18.63s`，portable JUnit gate 通过。机器可读 coverage gate 显示：

- 纯 line coverage：`1726 / 1975 = 87.392405%`，满足 `>= 80%`；
- changed executable line：`1696 / 1868 = 90.792291%`，满足 `>= 90%`；
- `cli-output`、`strict-partial`、`asset-validation`、`atomic-output`、`optional-dependency-error` 共 14 个关键函数，line 和 branch 均为 `100%`；
- coverage.py 终端显示的 branch-aware 综合值是 `84.47%`，它不是上述纯 line 百分比。

同一工作树的宿主全量回归为 `314 passed, 18 skipped, 22 warnings in 37.85s`。18 个 skip 是 13 个 canonical-only golden 与 5 个未注入 wheelhouse 的 package gate；分层结果为 unit + contract `224 passed, 5 warnings`，component `52 passed, 17 warnings`。新增 5 个 package 用例来自 W2 私有快照竞态，新增 22 个 contract 用例来自 W1a evidence manifest。这些结果证明本地回归状态，不是 RC required 零 skip。

W1a 已实现标准库-only 的本地 evidence manifest `create/verify`。它绑定当前 HEAD、tracked diff 与 untracked 内容 hash、宿主环境、lock/profile/oracle、JUnit/gate JSON 和可选 package wheelhouse/image digest；拒绝路径逃逸、symlink、非普通文件、读取中替换、artifact hash 漂移与跨层结果。gate JSON 增加输入 JUnit/policy hash，verifier 从 JUnit 重算统计。schema v1 明确拒绝 `qualified-canonical` 和 `qualified-release` 自报。

本轮现场 manifest 为 `/tmp/ai-auto-lrc-w1-portable.Pd78d5/evidence-manifest.json`，SHA-256 `8299bf756f5298adc0f911355f037a6b6b480046f21e58ff4361340cf560c582`，资格级别刻意保持 diagnostic。W1 尚未完成的部分是：实际启动 gate 的 capture runner、运行前后 source snapshot、唯一受控 run directory、portable coverage 闭包、package 容器 sidecar、canonical immutable image receipt、失败 run receipt 和长期 retention；因此不能把这份事后组装的本地 manifest 提升为受控资格证据。其后文档更新已改变 source hash，所以该 manifest 现在会被 current-source 校验以 source mismatch 正确拒绝，只能保留为历史 diagnostic。

W1b 的完整执行设计已独立固化在 [`W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md`](../W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md)，包括 Teams 四角色结论、capture 唯一编排边界、运行状态机、原 gate rc 优先级、历史 dirty evidence 边界、分层 artifact closure、28 个候选测试和 W1b-0 至 W1b-5 回滚批次。它仍是待实施方案，不改变本节 Gate。

同日执行：

```bash
AI_AUTO_LRC_GATE_ARTIFACT_DIR=/tmp/ai-auto-lrc-package-gate-current \
  scripts/run_test_gate.sh package
```

结果：pytest 为 `29 passed, 5 skipped in 23.50s`，随后 zero-skip verifier 正确拒绝。五个 skip 都是未提供 `AI_AUTO_LRC_WHEELHOUSE` 的 cold wheelhouse 用例。这证明默认 package required gate 当前为 **No-go**；不能引用 29 个通过用例将其改写为 package qualification。

同日使用包含当前 C06 源码的临时 Linux x86_64/CPython 3.11.9 v10 wheelhouse 候选执行完整 package gate，结果为 `31 passed, 3 macOS-only skipped in 62.10s`；offline wheelhouse 文件为 `22 passed, 3 macOS-only skipped in 36.50s`。验证环境为 Docker `--platform linux/amd64 --network none --read-only`、4 GiB tmpfs、空 HOME/XDG/HF/Torch/Demucs/NLTK/pip/uv cache、`PIP_NO_INDEX=1`、`python -I`，无源码树和宿主 `.venv` 挂载。发布 sdist 离线 build、全新 venv no-index install、`pip check`、15 个直接依赖加 installed `t2l` 共 16 个 import、`.pth` baseline hash 前后不变、真实 MP3 CLI `[00:00.034]hello\n` 全部通过。

v10 候选目录为 `/tmp/ai-auto-lrc-linux-v9.NA8l9z/linux-x86_64-py311-v10`，manifest SHA-256 为 `f5d0157395ba10b0a29ea595fb5c33ac276e54a5c2a2cbda2f7e756f9127cd7a`，candidate sdist SHA-256 为 `2431888f2c196a860ede24b07206cb8499a28e36939cdc08d93e3848e39f4d6d`。57 个 runtime wheels 共 342,733,931 bytes，2 个 build-system wheels 共 890,710 bytes，sdist 为 55,357 bytes。该目录是临时 evidence，不是长期受控 release artifact。

Linux verifier 现有 20 个轻量实例：除原有 manifest/path/symlink/tag/`.pth` 负例外，W2 新增 manifest symlink、校验后源路径替换、复制中原地覆盖、复制后 snapshot 篡改和 snapshot 完成后源目录变化；结果为 `20 passed`。manifest/artifact 使用 `O_NOFOLLOW` 和完整身份比较，复制时同步重算 size/hash，私有 snapshot 完成后再做完整 manifest 校验。真实 cold gate 后续的 requirements、runtime/build-system wheels、release sdist、tag 检查、pip `--find-links` 和 manifest evidence hash 都只引用容器 tmpfs 中每次唯一的 snapshot。这份证据只把 `PKG-019` 登记为 Linux scope 的 `implemented-unqualified`；`PKG-012/017` 明确要求 Linux/macOS 双平台矩阵，继续保持 planned。

C06 新增 `AUD-011/012`：缺 `vocals` 在最终 resample 前失败，模型选择 `-1/0/3/4` 与短 bag 均有独立断言；修复重复重采样，并收紧 Demucs 缺依赖与 backend 内部 import failure 的错误分类。这些是最小 adapter 合同，不是 P4 真实权重或 installed-extra 证据。

canonical runner 已修复 macOS Bash 3.2 空数组在 `set -u` 下的兼容问题。`audio.py` provenance 变化后的 public-e2e candidate 同进程三次一致，人工审查只更新 `provenance.audio_adapter_sha256`；decoder bytes、waveform、Mel、posterior、boundary、frames 和四路 API/CLI LRC 均未变化。最新 canonical full verify 为 Linux x86_64、CPython 3.10.21、CPU-only、运行阶段断网且只读，`13 passed, 7 warnings, 0 skipped in 144.45s`。它资格化的是 functional canonical，不是 release provenance。

当前 inventory 为 274 个稳定 ID：92 implemented、85 个不同 nodeid、81 implemented-unqualified、11 qualified-canonical、182 planned、0 qualified-release。

## 9. 统一执行与恢复命令

最小恢复检查：

```bash
git status --short
uv lock --check
uv run --frozen --no-sync python -m pytest tests/unit tests/contract -q -p no:cacheprovider
uv run --frozen --no-sync python -m pytest tests/component -q -p no:cacheprovider
AI_AUTO_LRC_GATE_ARTIFACT_DIR=/tmp/ai-auto-lrc-portable scripts/run_test_gate.sh portable HEAD
AI_AUTO_LRC_GATE_ARTIFACT_DIR=/tmp/ai-auto-lrc-package scripts/run_test_gate.sh package
scripts/run_canonical_legacy_v1_golden.sh verify
uv run --frozen --no-sync ruff check .
uv run --frozen --no-sync python -m compileall -q t2l tests
uv build --no-python-downloads
git diff --check
```

`package` 在没有显式 wheelhouse 时预期失败，不能为了总命令变绿而排除 skip。canonical 成本较高，只在 oracle/provenance 依赖变化或 RC 汇合时运行。后续接手者必须先保留当前工作树，再依据当前提交选择有意义的 `base-ref`；`HEAD` 只是本轮 dirty refactor 的恢复基线。

## 10. Go No-go 与下一次会话入口

| Gate | 当前状态 | 下一动作 |
|---|---|---|
| portable required + coverage | Go，本地、dirty-worktree scope | 将 JSON/JUnit 作为每次实施的交付物；未来接入 CI 时再配置 required check |
| functional canonical | Go，最近一次 Linux pinned scope | provenance 变化后按 feature -> numeric -> public-e2e 顺序重生成候选并人工审查 |
| Linux cold wheelhouse | Go，Linux scope、implemented-unqualified；W2 私有 snapshot 已通过真实候选 | 持久化受控 evidence、固定 image digest；CI 需独立授权；不得升级为双平台资格 |
| macOS cold install | No-go | 先批准 Torch 制品 ADR，再重建和复验 |
| 完整资源预算 | No-go | 先锁定单位、阈值、错误和迁移，再实现 P1 |
| Demucs optional-extra | No-go | 建立权重 manifest 和 installed offline test |
| Runtime 公开 close | No-go | 先锁定生命周期语义；当前只有底层 owner close 安全性 |
| Release | **No-go** | P1–P5、双平台、零 skip、clean signed provenance、SBOM、attestation、rollback drill |

下一次会话先回答第 6 节的人类决策；无需新产品决策的实施可从 P2 的 artifact 持久化和私有 snapshot TOCTOU 开始。不得通过删除测试、放宽阈值、复用其他层证据或无审查更新 canonical oracle 来消除真实失败。

## 11. Teams 续会的执行级细化

### 11.1 四角色复核与综合

**PM。** 当前核心价值链已经有 functional canonical 和 Linux 单平台安装证据，下一目标不是增加更多 fake happy-path，而是把未决合同和发布边界变成有人签收的决策。首先建立决策登记表，给资源阈值、macOS Torch、Demucs 许可/错误语义和 runtime close 指定 owner、截止条件和验收人；没有签收的事项继续 No-go。

**Architect。** 现有分层和 LegacyV1 冻结边界正确，但候选证据不能推出发布就绪。工作包必须形成带前置依赖、产物、反证测试和 No-go 的 DAG；Linux/macOS 分账，Demucs 锁定本地权重仓库和许可，runtime 证明初始化/释放/失败缓存，release 绑定 tag -> commit -> lock -> artifact -> asset -> SBOM/attestation。

**Developer。** 按可回滚纵切批次推进，先冻结合同再实现。每包按 contract test -> adapter/port -> migration -> package/platform verify 排序；完成定义同时包含 tests、inventory、离线反证、回滚点和证据归档。未决资源、partial、close、macOS 与 Demucs 许可不得由实现代码替代决策。

**QA。** 通过数不等于资格化，结论必须绑定环境、制品与反证。portable、canonical、package、release 使用独立 evidence；canonical oracle 不随失败自动更新；双平台 package、Demucs、资源预算、恢复和 release 必须冷装、断网、故障注入并在 required 层零 skip。

**综合结论。** 四个角色一致认为 Release 继续 No-go。三个以上角色共同指出的阻塞项是：macOS Torch 策略未锁、资源单位/阈值未锁、Demucs 权重许可与本地加载未锁、公开 runtime close 未锁、证据尚未绑定 clean signed source。开发可以立即推进的只有不改变公共语义的 P2 制品持久化、私有 snapshot TOCTOU 和 evidence schema；其余工作先经过对应决策锁。

### 11.2 决策锁

| 决策 ID | 必须由人确定 | 记录内容 | 未决时允许做什么 | 未决时禁止声称 |
|---|---|---|---|---|
| `D-RES` | PM + Architect | 三个资源上限的单位、默认值、配置入口、错误 code/stage/details、旧调用迁移；`RES-004` runner/fixture/schema/owner | 写测试草案、采集诊断数据 | `RES-003/004/005` implemented 或资源有界 |
| `D-MAC` | Maintainer + Release owner | 受信上游制品、可审计重建并重签、升级 Torch 三选一 | 保留失败 evidence、验证候选来源 | macOS cold install、双平台 `PKG-012/017` |
| `D-DEM` | Architect + Legal/Release owner | model/repo logical name、manifest schema、错误分类、16 个 `.th` 与 4 个 YAML 的来源/hash/size/license/再分发权 | 保持默认关闭、完善 fake adapter 边界 | 真实离线 Demucs、可再分发 vocals extra |
| `D-LIFE` | API owner + Architect | close 遇 in-flight、close 后错误、临时 runtime、NLTK lease/refcount、模型/CUDA 释放范围 | 保持底层 owner-local close 测试 | 公开 runtime 生命周期已完成 |
| `D-REL` | Release owner | artifact retention、CI 权限、签名者、SBOM/attestation 格式、staging/rollback owner | 本地生成 schema 和 dry-run evidence | required CI、签名发布、qualified-release |

决策记录必须写明选择、未选方案、兼容影响、回滚条件和批准人；没有批准人或日期的记录只能是 proposal，不得解除 Gate。

### 11.3 可执行工作包 DAG

```text
                     +--> D-RES  --> W3 resource gates --------+
                     +--> D-MAC  --> W4 macOS package ---------+
W0 docs checkpoint --+--> D-DEM  --> W5 Demucs offline -------+--> W7 recovery/release
        |            +--> D-LIFE --> W6 runtime close --------+
        +--> W1 controlled evidence ---------------------------+
        +--> W2 private snapshot (complete) -------------------+
```

| 工作包 | 前置 | 允许修改范围 | 必须产物 | 可执行验收 | 失败后的状态 |
|---|---|---|---|---|---|
| `W0` 文档检查点 | 无 | 主方案、Teams 文档 | 最新事实、决策锁、DAG、测试目录 | 文档链接/规格 inventory/quality contract 定向测试；`git diff --check` | 文档保持未完成标记，不改变实现资格 |
| `W1` 受控 evidence | 无 | evidence schema、package/gate 辅助脚本与测试；不创建 CI workflow | manifest、JUnit、coverage/gate JSON、runner/version/image digest、retention 说明 | 同一次 run 的 hash 可重算；缺字段、路径逃逸、跨层结果必须失败 | **W1a schema/verifier 已完成，capture/retention 未完成**；Linux 临时候选仍仅 implemented-unqualified |
| `W2` 私有 snapshot | 无；完成后接入 `W1` schema | Linux verifier 与 package tests | 已验证 bytes 的 tmpfs 私有 snapshot；build/install 仅消费 snapshot | manifest symlink、校验后路径替换、复制中原地覆盖、snapshot 终态篡改、snapshot 后源目录修改；真实 v10 cold install | **当前工作树已完成**；`PKG-019` 仍不升级，失败保留诊断证据 |
| `W3` 资源 gate | `D-RES` | config/request、lyrics/audio/inference/DP 预检、registry、tests/inventory | 三类稳定错误和性能 evidence | 边界值、超限、未知 metadata、shape upper bound；spy 证明昂贵步骤为 0 | 对应 `RES-*` 保持 planned |
| `W4` macOS package | `D-MAC` | dependency/lock、builder/verifier、platform package tests | tag 一致的 macOS wheelhouse 和完整 manifest | 平台级断网、空 cache、sdist build、no-index install、`pip check`、imports、真实 CLI | macOS 与 `PKG-012/017` 继续 No-go |
| `W5` Demucs offline | `D-DEM`，复用 `W1/W2` | vocals extra、独立权重 manifest、本地 repo adapter、package/component tests | 可审计权重集合、vocals wheelhouse、真实断网执行 evidence | 默认零 import；缺 extra/权重/hash/license/本地 repo fail-closed；有效权重真实 separation；单次初始化 | core 保持可用，Demucs P4 继续 No-go |
| `W6` runtime close | `D-LIFE` | public API/composition、runtime owner、NLTK lease、tests | 明确状态机和 close API | in-flight、并发 close、close 后调用、临时 runtime finally、多 runtime 隔离、中断恢复 | 只保留底层 owner close，不暴露未完成 API |
| `W7` 恢复与发布 | `W1-W6`、`D-REL`、独立发布授权 | recovery/release scripts/config、SBOM/attestation/signing/staging | clean source 恢复包、双平台制品、签名和 rollback 记录 | 隔离恢复后重跑全部 RC required 零 skip；tag/commit/hash 闭包；撤回演练 | `qualified-release=0`，不得发布 |

并行规则：`W2` 和 `W1a` 已完成，下一无决策工作为 `W1b capture/retention`；四个决策锁可与其并行讨论；`W3-W6` 只在各自决策通过后实施，彼此可并行但测试环境隔离；`W7` 永远最后。canonical 和真实 wheelhouse 使用共享 Docker/CPU/磁盘资源时串行，避免相互污染和假超时。

### 11.4 统一 evidence schema

下列是 W1/W7 的目标 schema；字段缺失时 verifier 必须拒绝，而不是填默认值：

```json
{
  "schema_version": "1",
  "claim": {"gate": "portable|canonical|package|release", "spec_ids": []},
  "source": {"head": "40-hex", "dirty": true, "diff_sha256": "64-hex"},
  "environment": {
    "os": "...",
    "arch": "...",
    "python": "...",
    "container_image_digest": "sha256:...",
    "network_policy": "..."
  },
  "inputs": {
    "lock_sha256": "64-hex",
    "profile_manifest_sha256": "64-hex",
    "asset_manifest_sha256": "64-hex",
    "oracle_sha256": []
  },
  "run": {
    "command_id": "...",
    "selectors": [],
    "started_at_utc": "...",
    "duration_seconds": 0,
    "exit_code": 0,
    "passed": 0,
    "failed": 0,
    "errors": 0,
    "skipped": 0
  },
  "artifacts": {"junit_sha256": "64-hex", "gate_json_sha256": "64-hex"},
  "qualification": {"level": "diagnostic|implemented-unqualified|qualified-canonical|qualified-release"}
}
```

package evidence 还必须列出 wheelhouse manifest/sdist hash、解释器 tag 集、`.pth` baseline/snapshot、`t2l.__file__` 和 CLI stdout hash；release evidence 还必须列出 tag、commit、签名、SBOM、attestation、Linux/macOS 子证据和 rollback receipt。JSON 不保存 secret、用户目录绝对路径或可复用凭证。

当前落地的 W1a schema v1 只允许生成 diagnostic 或在本地重算通过后的 implemented-unqualified 证据，明确拒绝 `qualified-canonical` 和 `qualified-release`。它尚未闭合 coverage、实际容器 sidecar、运行前后 source identity 和递归 release 子证据；这些字段完成前，不得因为目标示例中出现更高 qualification 字符串就认为工具已经支持该级别。

### 11.5 测试待办目录

以下 ID 是工作包内的候选测试名，不自动成为 `tests/spec_inventory.json` 稳定 ID；只有合同获批、实现落地并通过 inventory 校验后才登记。

| 候选测试 | 层级 | 前置/故障注入 | 必须断言 |
|---|---|---|---|
| `P2-T01` | unit/package | manifest 校验后用 rename 替换源 wheel | snapshot copy 拒绝 hash/inode 不一致，或只消费已验证 bytes；不得安装替换内容 |
| `P2-T02` | unit/package | manifest 校验后原地覆盖源 wheel | 复制阶段重新 hash 并失败关闭；不进入 build/install |
| `P2-T03` | unit/package | 私有 snapshot 完成后修改原目录 | snapshot hash 不变，后续命令参数只引用 snapshot |
| `P2-T04` | package/system | 复制期间并发修改大文件 | 结果只能是完整旧 bytes、完整新 bytes 因 hash 不符失败；禁止混合内容通过 |
| `P2-T05` | contract | evidence 缺 image digest/JUnit/hash 或混入 portable classname | schema verifier 逐项失败并指出稳定字段路径 |
| `RES-T01` | unit/component | 三个上限的 `limit-1/limit/limit+1` | 精确边界不误拒绝；超限稳定 code/details；昂贵 spy 为 0 |
| `RES-T02` | component | audio header 未知/畸形和 probe/load 替换 | 无法证明安全时 fail-closed；details 不泄露绝对路径 |
| `RES-T03` | component | 四模型 route shape upper bound | 能预估的在 forward 前拒绝；不能预估时不得宣称 pre-forward gate |
| `DEM-T01` | unit/package | 默认 separation 关闭 | `sys.modules` 前后无 Demucs；network/download 事件为 0 |
| `DEM-T02` | package | 未安装 extra | `T2L_VOCALS_DEPENDENCY_MISSING`、exit 5、无 traceback |
| `DEM-T03` | package | extra 已安装，缺权重/坏 hash/LFS pointer/未声明文件 | 在 backend 执行前按已批准 asset error 失败；绝不创建 RemoteRepo |
| `DEM-T04` | package/system | 有效本地 repo、断网、installed wheel、短音频 | 真实 separation 的 rate/channel/dtype/source 正确；临时资源释放 |
| `DEM-T05` | component | 同 runtime 并发、初始化中断、两个 runtime | 单次初始化；中断不 sticky 半成品；owner 互不删除 |
| `LIFE-T01` | component | process in-flight 时 close | 严格符合 `D-LIFE` 的等待或拒绝语义，无死锁、无跨 runtime 释放 |
| `LIFE-T02` | unit/component | close 后 process、重复 close、临时 runtime 异常 | 稳定错误；close 幂等；`finally` 精确一次释放 |
| `REL-T01` | system | 隔离目录恢复 Git bundle/LFS/lock/assets | 不读原 checkout/cache；全部 hash 闭包一致 |
| `REL-T02` | system | 缺签名、SBOM、任一平台 evidence、任一 required skip | qualification verifier 拒绝产生 `qualified-release` |
| `REL-T03` | staging | 发布候选后执行上一版本 rollback | receipt 包含目标版本、开始/结束、兼容检查和恢复结果 |

W2 当前已经实现 `P2-T01/T02/T03` 的核心断言，并额外覆盖 manifest symlink、snapshot 终态被修改以及四类输入在 snapshot 完成后不受源目录变化影响。`P2-T04` 的真实并发大文件压力版本仍可作为纵深防御，但不替代现有确定性复制中 mutation test。`P2-T05` 的路径、symlink、hash、JUnit/gate 跨层和 image-digest 核心负例已由 W1a 完成；同一次 capture、coverage/package/canonical layer closure 和 retention 仍属于 W1b。

### 11.6 每个工作包的完成定义

一个工作包只有同时满足以下条件才算完成：

1. 合同、实现、迁移说明和测试同一批次可回滚，且不触碰冻结模型文件。
2. 新稳定行为拥有唯一 pytest nodeid；inventory 的状态只按实际证据更新。
3. 正向、边界、反向和中断/并发用例按风险覆盖；至少一个测试证明 gate 在坏输入下会红。
4. portable/package/canonical 使用各自 runner 和 JUnit，零测试、failure、error、required skip 或跨层 classname 都失败。
5. evidence JSON 绑定 source、环境、输入 hash、选择器、结果和 artifact；dirty worktree 必须显式记录。
6. 文档同步能力边界、错误语义、当前证据和仍未关闭的 No-go，不把 planned 文案写成 implemented。
7. 执行 `ruff`、`compileall`、`uv lock --check`、build 和 `git diff --check`；canonical/package 大门禁按 provenance 影响范围串行运行。
8. 未经独立授权不创建 CI workflow、不 commit/push、不签名、不发布；失败制品保留用于诊断，但不得进入最终 artifact 目录。

## 12. Teams 第十一轮：W1b 第一纵切落地

### 12.1 四角色验收结论

- PM：本轮交付的是可复核的本地 capture 闭环，不是 release 资格；retention 期限、归档介质与 owner 继续由 `D-REL` 决定。
- Architect：capture 已成为唯一编排者，source、gate、artifact、receipt 和退出码处于同一运行事务；W1a manifest 与 W1b capture receipt 使用独立 schema，避免不兼容扩展。
- Developer：W1b-0/1/2 已完成最小纵切；package/canonical 以显式 `LAYER_CLOSURE_UNIMPLEMENTED` 保持 diagnostic，后续分批接 sidecar。
- QA：28 个 capture 实例覆盖真实失败、信号、并发、源码类型和 sealed 完整性；`SIGKILL`、掉电、secret 导出审计、完整 package/canonical closure 仍是公开缺口。

共同判定：portable capture-bound local scope 为 Go；W1b 整体仍未完成，Release 继续 No-go。任何文档更新都会改变 source hash，所以 receipt hash 不回写为“仍匹配当前 checkout”的永久声明。

### 12.2 实测

- capture/quality/W1a 合同：`48 passed`
- 真实 portable capture：`311 passed, 22 warnings, 0 skipped`
- 宿主全量：`349 passed, 18 skipped, 22 warnings in 48.18s`
- overall line：`1726/1975 = 87.392405%`
- changed executable line：`1696/1868 = 90.792291%`
- Ruff、compileall、`uv lock --check`、`uv build --no-python-downloads`、`git diff --check`：通过
- package negative capture：原 exit 1；`29 passed, 5 skipped`；diagnostic receipt 可通过 archived-integrity

### 12.3 下一入口

1. W1b-3：让真实 Linux wheelhouse verifier输出并封存 platform/image/sdist/wheel/tag/`.pth`/import/CLI sidecar，再用 v10 或新候选 capture；不得复制 328 MiB wheelhouse，只保存 manifest 副本和闭包 hash。
2. W1b-4：canonical runner记录 Dockerfile/base digest、实际 build image ID、三份 oracle与运行环境 sidecar；schema v1仍不产生 `qualified-canonical`。
3. W1b-5：锁定 retention owner/期限/加密/销毁和 secret 导出扫描；不自动 prune或上传。
4. 其余 W3-W7继续受 `D-RES/D-MAC/D-DEM/D-LIFE/D-REL` 决策锁约束。
