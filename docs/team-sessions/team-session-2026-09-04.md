# AI-auto-lrc v2 Teams 细化评审（2026-09-04）

> 状态：决策已写入本地，实施进行中；Release No-go  
> 主计划：[`../AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md`](../AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md)  
> 事实交接：[`../AI_REFACTOR_HANDOFF.zh-CN.md`](../AI_REFACTOR_HANDOFF.zh-CN.md)

## 评审主题

在不改变 LegacyV1 数值协议的前提下，完成 v2 的离线 G2P 资产接线、installed-wheel 验证与可执行测试门禁。约束是：默认不联网，资产由 package 内 manifest 绑定，数据实体由显式 asset root 或受控开发根提供，任何缺失或损坏都必须失败关闭，不得回退到 CWD、用户 cache 或在线下载。

## PM 视角

### 首要判断

本轮的用户价值不是“本机可以跑 G2P”，而是任意干净环境可以根据明确的资产契约重现同一结果，且错误时不会偷偷联网或产出半成品。

### 关键关切

- 交付不能依赖开发者的 NLTK cache，否则 package smoke 会假绿。
- 资产缺失、hash 错误和版本不兼容必须给出稳定、可行动的错误，且不得留下输出文件。
- “测试全绿”只能在证据所属环境内表述；本机 component 绿不等于 Linux 3.10 数值 golden 或 RC 可发布。

### 第一行动

先将 G2P 资产策略、版本约束、错误语义和分层测试写入主计划，再实施 wiring，避免代码替决策。

### 团队问题

本轮 Go 是“源码开发环境可用”，还是“installed wheel + 外部资产包可用”？本文决定采用后者。

## Architect 视角

### 首要判断

依赖方向锁定为 `composition -> AssetLocator -> OfflineG2PProvider -> LegacyV1PhoneEncoder -> LegacyV1LyricsAdapter`。Encoder 只理解 G2P callable，不识别 manifest、文件路径或 NLTK；composition 是唯一 concrete wiring 点。

### 关键关切

- `create_runtime()` 若解压、读取或导入 G2P 资产，就破坏了惰性合同和错误隔离。
- Provider 或失败 cache 若为模块级单例，会让一个 runtime 的 asset root/失败污染另一个 runtime。
- `nltk.data.path` 是进程级可变状态；只能在已校验资产上做加锁、去重的绑定，不能把用户 cache 变成隐式 fallback。

### 可执行设计

1. `load_legacy_v1_profile()` 只解析 package 内 manifest schema，不读取 NLTK zip 内容。
2. composition 将两个 `RuntimeAssetSpec` 转成 `AssetSpec`，封装为惰性 `prepare_resources()` callback。
3. Provider 首次使用时调用 callback；`AssetLocator.resolve()` 依次校验路径、LFS pointer、size 和 SHA-256。
4. 两个资产必须归属同一个受控 `nltk_data` 根；然后在全局锁中去重绑定该根。
5. Provider 只在该根上显式查找所需资产；检查完成后才允许 import `g2p_en.G2p`。
6. Provider 的 ready/failure/cache/lock 为 runtime 实例所有；普通 `Exception` 缓存，`KeyboardInterrupt/SystemExit/GeneratorExit` 不缓存。

### 团队问题

外部 NLTK 资产是否允许独立于 package 更新？决定：物理上外置，但必须与 package 内 manifest 的 hash/size/source/license 成组匹配；未引入单独的远程更新通道。

## Developer 视角

### 首要判断

不更换 g2p-en 算法，也不增加在线 fallback。最小安全变更是增加可注入的资产准备 callback，并将 NLTK 锁到能消费 LegacyV1 旧 tagger zip 的版本。

### 关键关切

- g2p-en 2.1.0 在 import 阶段检查旧 tagger/cmudict，缺失时会调用 `nltk.download()`；必须在 import 前使检查命中。
- NLTK 3.10.3 的 `pos_tag(lang="eng")` 要求 `averaged_perceptron_tagger_eng`，而已锁定的 LegacyV1 资产是旧 `averaged_perceptron_tagger.zip`。
- 多 runtime 不应共享 Provider 失败；但各 root 中的 NLTK 内容由同一 manifest hash 绑定，因而进程级 path 注册可以加锁并幂等。

### 第一行动

显式 pin `nltk==3.8.1`，在临时 HOME/cache 中把 `nltk.download` 替换为 fail-fast，用当前两个 zip 验证 import、构造和首次 `g2p("hello")`。若失败，停止并重新做版本/资产决策，不允许在运行时下载补齐。

### 团队问题

是否需要支持同一进程的多个不同 NLTK asset root？决定：允许不同路径，但每份内容必须通过同一 manifest hash；本轮不支持同进程混用不同版本的 NLTK 资产集。

## QA 视角

### 首要判断

需要在 unit、contract、component、package/system 四个边界分别反证；单纯 monkeypatch factory 只能证明控制流，不能证明真实 g2p-en 在干净环境离线可用。

### 关键关切

- 宿主已有 NLTK 资产会让测试假绿；必须清空 HOME/XDG/NLTK cache 并阻断网络。
- 显式 config root 缺资产时，即使 env/dev-root 中有合法副本也必须失败。
- package 测试必须从 wheel 安装环境、源码树外 CWD 运行，并检查 `t2l.__file__` 确实不在 checkout 内。

### 测试矩阵

| 层级 | 绑定的现有 ID | fixture/动作 | 精确断言 |
|---|---|---|---|
| Unit | `API-011`, `TXT-020` | fake locator/factory，并发首次访问 | 同 runtime 初始化一次；失败缓存；新 runtime 可重试 |
| Unit | `AST-006`, `AST-017` | 空 root、翻转一 byte | factory/import 调用为 0；不回退 env/dev-root |
| Contract | `TXT-017..019` | 英文、重音、未知 phone、多行 | phone 序列、space=39、unknown=40、word/line 半开 span 精确 |
| Contract | `OFF-004` | 监视 import 与 zip 读取 | `create_runtime()` 不导入 g2p-en，不打开 NLTK zip |
| Component | `OFF-001`, `OFF-005` | 真实 zip、临时 cache、socket/download 熔断 | 缺失时 import=0；完整时首次 G2P 成功且网络尝试=0 |
| Component | `AST-024`, `PKG-009` | package 内 manifest + 外部 zip | logical name/path/hash/size/source/license 完全一致 |
| Package | `AST-014`, `PKG-023` | wheel install、`python -I`、源码树外只读 CWD | package manifest 来自 wheel，不导入 checkout |
| Package/System | `PKG-025`, `OFF-003/019` | 显式外部 asset root、空 cache、断网 | 真实歌词准备/短音频完成；缺资产时零输出 |

### 团队问题

为避免宿主 cache 污染，package test 是否允许完全继承当前环境？决定：不允许；除了显式 asset root 和必要的 locale，测试必须构造最小环境。

## 综合决策

1. NLTK 数据作为外部 runtime assets，不塞进 wheel；package 内 manifest 是路径、hash、size、source 和 license 的唯一信任基线。
2. `create_runtime()` 只读 manifest 文本并组装对象；首次真实 G2P 才校验 zip、绑定 NLTK data root 并导入 g2p-en。
3. 显式 root 一旦选中就不得回退。缺失、LFS pointer、size/hash 错误均在 G2P factory 前失败。
4. 锁定 `g2p-en==2.1.0` 的 LegacyV1 行为，并显式 pin 与旧 tagger zip 兼容的 NLTK 版本；不以新资产或在线下载掩盖版本漂移。
5. 单测锁定编排和错误，component 使用真实 NLTK/g2p-en，package/system 在安装后、源码树外、空 cache/断网环境反证。
6. 本轮只能关闭 G2P 离线 wiring 风险，不会自动解锁 canonical Linux 3.10 numeric golden、natural partial、四模型真实路由、发布或恢复 Go。

## 执行顺序与回滚单元

| 顺序 | 任务 | 必须证据 | 回滚单元 |
|---:|---|---|---|
| 1 | pin NLTK 版本并验证真实 G2P | 临时 cache + `nltk.download` fail-fast + `g2p("hello")` | `pyproject.toml` + `uv.lock` |
| 2 | 实施 manifest-to-provider 惰性 wiring | unit/contract；factory 前 fail closed | lyrics/composition/provider 变更 |
| 3 | 实施真实 asset component 测试 | 实际 zip hash/size/license + 断网 G2P | component tests + fixtures |
| 4 | 实施 installed-wheel 歌词准备 smoke | sdist -> wheel -> 隔离安装 -> 外部 root | package harness |
| 5 | 串行运行 fast/component/package/full/lint/build | 命令、计数、warning 和未覆盖边界 | 本轮整组变更 |
| 6 | 更新主计划快照 | 现在时、环境、证据边界、仍 No-go 项 | 文档快照 |

## 完成定义

本次子任务只有在以下全部满足时才能称为“G2P 离线 wiring 完成”：

- 两个 runtime assets 与两份 manifest 一致且通过 hash/size 校验；
- `create_runtime()` 不 import g2p-en，不打开 NLTK zip 内容；
- 实际 G2P 在临时 HOME/cache 与网络/download 熔断下成功；
- 空 root、坏 hash 和显式 root 不回退都有反证；
- installed wheel 在源码树外使用外部 asset root 完成歌词准备；
- 全量测试、Ruff、compileall、lock check 和 build 均为当前工作区新证据。

本次子任务完成也不等于 v2 RC Go；主计划第 19.3 节仍是总门禁。

## Teams 第五轮架构方案与测试证据收敛

### 架构与 API 复核

团队确认 `allow_partial` 只是 application contract 支持的条件能力，不是冻结 LegacyV1 backend 已可触达的生产状态。合法可达输入上，reference DTW/BDR 强制完整终态；可复现的回溯耗尽是 `aligned=0`，必须 fail closed 和 CLI code 7。因此 non-empty partial 的 `CLI-004/022`、`ALN-019/020`、`GOL-010/013` 改为 deferred，必须等待新的 confidence/cutoff 语义、numeric oracle 和迁移影响获批。fake outcome 仍可测试编排合同，但不能资格化真实 backend。

复核还区分了 runtime 的当前 eager/lazy 阶段：当前 eager 是 manifest schema、LID path/size/hash 和 Mel transform 构造；当前 lazy 是 fastText model、NLTK zip/G2P 和 checkpoint/model。Provider、失败 cache、checkpoint model 和 per-runtime lock 属于 runtime，但 NLTK module/cache/search path 是进程级受控状态。计划已不再把“惰性 runtime”作为没有阶段边界的泛化声明。

### QA 与交付复核

`tests/spec_inventory.json` 的 `implemented` 只表示稳定 ID 已绑定可收集 pytest 节点，不表示 canonical、跨平台、CI required 或 release qualification 已通过。本轮新增 `API-015` 作为 diagnostics 去重规格，稳定 ID 总数从 273 增为 274；当前 47 个 evidence binding 映射到 42 个不同 pytest 节点，其余 227 个保持 planned。Inventory schema v2 已将资格维度拆为 `implemented-unqualified / qualified-portable / qualified-canonical / qualified-release`；当前仅 `NUM-001/002` 是 feature-only `qualified-canonical`，`NUM-015/016` 与 `GOL-011/012` 已有 source evidence 但仍等待 numeric canonical oracle 收口，无 `qualified-release`。

当前 marker 事实只有 `component/golden/package`。`slow/vocals/cuda/performance` 在有真实测试前不声明空 marker。多个稳定 ID 共用一个 pytest 节点不会自动形成多个 JUnit testcase；必须参数化或输出可验证的 JUnit properties。仓库当前没有 CI workflow，本地 pytest/Ruff/lock 门禁不得描述为 CI required。

### ML 与 canonical 证据复核

首个 canonical LegacyV1 feature oracle 已在 Linux x86_64、CPython 3.10.21、NumPy 1.26.3、`torch/torchaudio==2.1.2+cpu`、CUDA 无、CPU 单线程环境完成。候选在同一进程连续三次一致；Mel shape 为 `[1,1,128,87]`，SHA-256 为 `d2905b77c6f59ad415d2f25aa94454ef81b0ac6c87f555ab8fb0523578fd0b04`；manifest SHA-256 为 `0cd68498dcb35ad92dea2981ff10b7f66f71dbfefb2bb4714f6807c506d7a849`；verify 结果为 `2 passed, 2 warnings in 2.71s`。

该证据仅关闭 `NUM-001/002` 的 feature-only Mel 与首声道语义。它不覆盖 checkpoint/logits/posterior/frame/LRC/真实音频 golden；Docker build 阶段仍联网，只有 verify 运行阶段是 `--network none --read-only`；候选 v2 adapter 来自 dirty worktree，尚无 clean commit/source hash/release provenance 绑定。

### 最终决议

1. R7 拆成 R7a 旧入口/范围清理和 R7b 资格验证/RC；R7a 完成不代表 R7b Go。
2. 第五轮时的本机全量为 `173 passed, 2 skipped, 15 warnings`，当时 canonical feature verify 为 `2 passed, 2 warnings`；这是历史快照，必须与下方第六轮证据分开表述。
3. manifest/alignment 错误映射、CLI verbose/debug、LID manifest 接线和 diagnostics 去重已完成定向实现与测试；完整错误注册表、内部 progress port、checkpoint/G2P TOCTOU 和并发调用安全仍是明确的未完成实施项。
4. Coverage、真实 decoder/audio API/CLI golden、cold offline wheelhouse、Git/LFS/dirty-state 恢复、发布 provenance 和 rollback 演练未完成，总判定继续为 Release No-go。

## Teams 第六轮本地固化与 canonical 收口

方案固化时重新按 provenance 依赖顺序生成并验证 canonical oracle：先更新 feature oracle 对最新 profile manifest 与 `uv.lock` 的绑定，再据此重生成 numeric oracle。一次中间 verify 因 numeric oracle 仍绑定旧 feature oracle SHA-256 而正确失败；没有放宽比较，而是重生成下游 oracle 后再验证。

最终环境为 Linux x86_64、CPython 3.10.21、CPU-only `torch/torchaudio==2.1.2+cpu`、NumPy 1.26.3、单线程、CUDA 无。完整 `scripts/run_canonical_legacy_v1_golden.sh verify` 结果为 `6 passed, 4 warnings in 7.21s`：

- `NUM-001/002`：Mel 与首声道语义，feature oracle SHA-256 `86983116b2e9b75a1bf29876eb205cd93c534ae783e22aa80ab207106e8e23c2`；
- `NUM-015/016`：10 个 feature/logits/reduction/posterior/boundary 抽取点 v1/v2 bitwise exact，`max_abs_diff=0`；
- `GOL-011/012`：Baseline、MTL、Baseline_BDR、MTL_BDR 四路均 complete，真实 checkpoint、frames、line/word LRC exact；
- numeric oracle SHA-256 `36dff740ea1711f46fa18910bee902a46a5db7ad49566dd12ae81e8c395bf7e5`，并绑定 feature oracle、profile manifest、`uv.lock`、helper、adapter 和 renderer 哈希。

本轮同时关闭本轮范围内的 `PKG-005/010`：installed wheel 的默认 import/help/真实 MP3 -> LRC 不导入 Demucs且无网络/download 事件；显式缺少 vocals extra 稳定返回 exit 5；禁用模块在安装后无 spec、不被枚举且旧名称不进入公共 API。它们不证明冷缓存 `--no-index` 安装，也不证明已安装 Demucs 但本地权重缺失的路径。

最终本机验证为：unit/contract `133 passed`，component `41 passed`，package `5 passed`，宿主 golden `6 skipped`，全量 `188 passed, 6 skipped, 18 warnings`；Ruff、compileall、`uv lock --check`、`uv build --no-python-downloads` 与 `git diff --check` 均通过。Inventory 仍为 274 个稳定 ID，其中 47 个有 evidence binding；6 个 numeric/feature ID 为 `qualified-canonical`，41 个为 `implemented-unqualified`，没有 `qualified-release`。

这些结果是 dirty-worktree canonical functional 与 portable package evidence，不是 clean release provenance。真实 decoder/audio API/CLI golden、natural non-empty partial、cold wheelhouse、TOCTOU、跨平台矩阵、恢复和发布仍保持 No-go。

## Teams 第七轮并行实施与统一验收

本轮三个角色分工分别关闭 progress contract、CLI/输出文件安全和 checkpoint TOCTOU，主代理补充 portable coverage 门禁，并在同一最终工作树串行复验。

- API/架构线：新增 frozen `ProgressEvent`、`ProgressObserverPort`、`NullProgressObserver`；Python API 使用 Null，application 发出 alignment 事件，CLI 只序列化边界事件。`PORT-005`、`PORT-008`、`CLI-003` 已登记。
- 交付线：完成 `CLI-023..028` 与 `OUT-006..009`；SIGINT=130、closed pipe=141、mode=0600、Unicode locale 独立、version metadata 一致，并拒绝 directory/FIFO/device/symlink path；hardlink 也不能绕过输入覆盖保护。
- ML/资产线：完成 `AST-016`。Checkpoint 只读取一次 immutable bytes snapshot，在同一字节上做 LFS/hash/size 校验并交给 `torch.load(BytesIO(...))`；路径原子替换和原地覆盖均不能改变被加载内容。
- 主线程：新增 `scripts/run_portable_coverage.sh` 与配置门禁；只统计 unit/contract/component，排除冻结 `t2l/mtl`，package 与 canonical 独立运行。

最终统一证据：宿主全量 `206 passed, 6 skipped, 18 warnings`；portable coverage `192 passed`、line `84.11% >= 80%`；canonical `6 passed, 4 warnings`；unit/contract `150 passed`；component `42 passed`；package `5 passed`；Ruff、compileall、lock check、build 和 diff check 通过。Inventory 共 274 个 ID，其中 61 个有 evidence binding、6 个为 `qualified-canonical`、无 `qualified-release`。

本轮没有把 checkpoint 的 snapshot 结论扩张到 G2P/LID。真实 decoder/audio API/CLI golden、G2P/LID 路径消费 TOCTOU、冷 wheelhouse、diff coverage、跨平台、恢复、签名与发布仍为后续 required gate，总判定保持 Release No-go。

## Teams 第八轮错误合同、资产集合与冷安装收敛

本轮继续按 API/架构、ML/资产、交付/发布分工并行实施，主代理将讨论结论、测试绑定和证据边界写回主计划 v8。

- API/架构线建立 frozen、只读的错误注册表，统一 46 个稳定 code 的异常类型、stage、必填 details、cause policy、CLI exit code 和安全消息；生产代码 AST 扫描禁止未登记或漂移的错误合同，`API-009`、`CLI-011/012` 已绑定 evidence。
- ML/资产线以 `MaterializedAssetSet` 关闭 `AST-020`：LID 与 G2P 资产从稳定 FD 读取和校验，全集合通过后才发布私有只读 snapshot；fastText/NLTK 消费者持有 owner，故障注入覆盖 symlink、原子替换、原地覆盖和集合更新中断。该结论不扩张为同 UID 恶意进程隔离，也不关闭 `AST-019/022`。
- 主线程补充 `NUM-018`，证明 LegacyV1 成功及两类已知失败不改变调用方 NumPy/Torch 全局 RNG；补充 `PKG-006`，以 AST 固定 domain/application 依赖方向。
- 交付线已形成平台特定 wheelhouse builder、受控 sdist policy 和 macOS 系统断网 package gate。联网阶段使用 frozen export 与 `--require-hashes`；只有三个登记 sdist 可离线重建为 wheel；离线阶段必须从发布 sdist 构建、全新 venv 安装、`pip check` 并反证网络、宿主 `.pth`、源码树和 cache 旁路。

Inventory 最终为 274 个稳定 ID：71 个绑定实现证据，映射到 64 个不同 pytest 节点；65 个为 `implemented-unqualified`，6 个为 `qualified-canonical`，203 个保持 `planned`，无 `qualified-release`。`PKG-013/014/015` 已参数化为三个独立 JUnit case，`PKG-018` 使用独立 manifest/policy case；`PKG-019` 因完整 cold install 未闭环而退回 planned。

macOS arm64 最终 wheelhouse 只包含 57 个 runtime wheels、2 个 build-system wheels、1 个发布 sdist和 frozen requirements；manifest SHA-256 为 `ad95aa6a69dad0c0d4df59032c3cc6105c594405c8a3d74591014b1f6fe0028d`。系统网络熔断、空 cache、发布 sdist 离线构建及 manifest/policy 检查通过。58 包 `--no-index` 安装完成后，标准 pip 25 与 uv 都在 `pip check` 发现上游 Torch 2.1.2 wheel 文件名为 macOS arm64、内部 `WHEEL` tag 却为 macOS x86_64；团队决定不篡改 wheel、不降级检查器、不删除门禁，因此 `PKG-019`、`PKG-012/017` 继续 No-go。

参数化后的最终复验：宿主全量 `220 passed, 10 skipped, 19 warnings`；portable coverage `206 passed`、line `84.26%`；canonical `6 passed, 4 warnings`；unit/contract `161 passed`；component `45 passed`；显式最终 wheelhouse 的 package `9 passed`；宿主 golden `6 skipped`。`PKG-013/014/015` 已拆成三个独立 case。Ruff、compileall、lock check、build 和 diff check 通过。最终 numeric oracle SHA-256 为 `c9016543e1bf55b51169b0bc2e02cbd84c97760a50fdcdd4fe18f63939cb37a2`，wheel/sdist SHA-256 分别为 `c0989068b56ec7090a1c65184c4a42e4d01d02f10a633ae774e546be20d4e7fa` 和 `4da49e28034b9e26aa33330e72d0aab05b4f69a6fe7f0bfee0252f801ee2e670`。

本轮收口日期为 2026-09-05。Release 总判定继续 No-go；下一步需对 Torch macOS 制品策略做 ADR，并继续 Linux wheelhouse、真实 decoder/audio API/CLI golden、并发/资源、Git/LFS/dirty-state 恢复、签名和发布证据。

## Teams 第九轮真实端到端 并发与兼容性收敛

本轮延续 PM、Architect、Developer、QA 四视角，按三条可并行、最终串行汇合的工作流执行：真实 decoder 到 public API/installed CLI canonical；runtime 并发和中断恢复；package/profile compatibility 与 Linux wheelhouse。主代理统一处理 inventory、oracle 依赖、回归和文档，不允许子工作流独立扩张资格结论。

- PM：优先关闭真实用户输入到真实 CLI 输出，确认项目生成 MP3、Baseline/MTL/Baseline_BDR/MTL_BDR、line/word LRC 都进入 canonical；natural non-empty partial 继续延期，不能由实现者自行创造语义。
- Architect：用 runtime-local `RLock` 约束 fastText/Kakasi/G2P 的非线程安全实例；控制流异常不形成 sticky failure；manifest compatibility 绑定 distribution、package version、profile 和 profile contract version，并在所有资产/模型加载前失败关闭。
- Developer：完成 `CONC-001/004/005`、`AST-019` 和真实 public-e2e harness；wheelhouse builder 改为 staging release-source，并让 `uv export` 输出 PyPI 和 PyTorch CPU index。冻结的 `t2l/mtl/model.py` 与 `t2l/mtl/utils.py` 未修改。
- QA：把 `GOL-011/012` 从旧 numeric 节点迁移到真实 public-e2e 节点；新登记 `GOL-001/002/003/007/008`。三份 candidate 均要求单进程三次一致，最终在 Linux x86_64/CPython 3.10/CPU/断网/只读容器中统一 verify。

最终统一证据：宿主全量 `235 passed, 17 skipped, 22 warnings`；unit/contract `168 passed`；component `52 passed`；默认 package `6 passed, 4 skipped`；portable coverage `220 passed`、line `85.36%`；canonical `13 passed, 7 warnings`。Inventory 共 274 个 ID，其中 80 个绑定实现证据、73 个独立 pytest nodeid、69 个 `implemented-unqualified`、11 个 `qualified-canonical`、194 个 planned、0 个 `qualified-release`。Ruff、compileall、lock check、build 和 diff check 全部通过。

本轮新增 canonical 确认：真实 MP3 解码为 `[1,6912] @ 22050`，四路 public API 与 installed CLI 字节一致；CLI 从仓库外 CWD 执行，`t2l` 来自 installed site-packages，系统断网和 socket guard 生效，Demucs 未请求或导入。三份 oracle 最新 SHA-256 分别为 feature `8d2bcbb5bd2593baaf5c947333406c5246ea2e622cb22bff2f39e806cbc1880a`、numeric `428fe6cb410330448c428fafc3f6785c9547bdcb873b3493c8d32c67f9051352`、public-e2e `c6acf7f7ceec656084cadcc69606bdefe05e6fbbbbc1277c03c80238c732e50c`。

Linux wheelhouse 首次真实 amd64 候选以 exit 1 终止，原因是旧 builder 未把 PyTorch CPU index 输出到 requirements，候选目录为空，未产生可复用的 cold-install 证据。builder 已修但未重复长下载，故 `PKG-012/017/019` 继续 planned。`RES-003/004/005` 也继续 No-go：现有一帧 alignment 下界不是完整 `max_audio_samples/max_posterior_cells/max_phone_count` 合同。

第九轮总体判定：真实端到端、并发和 package/profile compatibility 可作为当前 dirty-worktree 的功能证据；macOS/Linux 冷安装、完整资源预算、Demucs、Git/LFS/dirty-state 恢复、`AST-022`、SBOM、attestation、签名与 rollback drill 尚未完成。Release 继续 No-go。完整执行顺序、nodeid、hash 和恢复命令已固化到主计划 v9 第 21 节。
