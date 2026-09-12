# AI-auto-lrc v2 可执行重构与测试计划

> 状态：设计基线已锁定，R1–R6 已部分实施，R7a 已完成；W1b-5 S16–S17 已完成声明范围，S18 coverage/package/evidence qualification 进行中；Release No-go
> 文档修订：v12（2026-09-06，Teams S18 架构、测试与交付复核）
> 基线提交：`db8e714eceb73e88496f0f705a56cd8c571e0278`
> 关联事实文档：[`AI_REFACTOR_HANDOFF.zh-CN.md`](./AI_REFACTOR_HANDOFF.zh-CN.md)
> 恢复与来源：[`BASELINE_PROVENANCE.md`](./BASELINE_PROVENANCE.md)
> 适用范围：正式推理能力 C01–C10；X01–X03、训练和旧评估不在本轮范围内

评审方式：Teams 第二轮形成主体方案，第三轮再由系统架构、ML/测试架构和交付/运维架构角色专项复核。API/CLI 方向审查公共合同、数据/端口责任、错误映射和原子写；ML 方向审查 LegacyV1 计算图、checkpoint、decoder、DTW/BDR、golden、并发和资源预算；交付方向审查离线安装、wheelhouse、Git/LFS 恢复、迁移、发布与回滚反证。本文是主代理对三方意见去重、解决编号和责任冲突后的决策稿。

## 0. 目的、使用方式与证据边界

本文把交接文档中的现状事实转成可分批实施、可自动验收、可独立回滚的 v2 重构方案。它同时是：

1. 架构实施清单；
2. 测试规格和测试用例目录；
3. PR/里程碑 Go/No-go 门禁；
4. 后续 AI 或维护者继续工作时的决策基线。

本文不是“已完成”声明。标为“目标”“建议测试”的模块、接口和用例只有在对应代码、测试和 CI 证据落地后才算实现。交接文档中的 30 个轻量用例是 `legacy-v1` 历史基线；当前 v2 已新增 unit/contract/component/package 测试，以及 feature、checkpoint numeric/rendering 和真实 decoder/API/installed CLI canonical harness/oracle。它们仍不能替代冷缓存双平台安装、完整资源预算、Git/LFS 恢复和签名发布演练。当前跨工作包 Gate 与恢复入口见文末第 32 节；第 15、21–31 节是按时间追加的阶段证据，后续不得用较新的绿色数字覆盖历史基线或把不同环境的结果混写。

## 1. 已锁定决策

以下决策不应在普通实现 PR 中被重新解释。如需改变，必须单独提出 ADR、影响分析和替代测试门禁。

| 主题 | v2 决策 | 明确不做 |
|---|---|---|
| 仓库定位 | 当前仓库作为新的 v2 仓库；旧人工实现仓库单独保留 | 不在 v2 仓库长期背负公开 v1 兼容层 |
| Git 历史 | 最终重新初始化 Git；执行前必须创建并验证可恢复 bundle | 不直接删除 `.git`，不在未验证备份时重置 |
| 重构范围 | 仅 C01–C10 正式推理能力 | X01–X03、训练、旧评估不进入 core |
| Python | `>=3.10,<3.12` | 未验证前不宣称支持 3.12+ |
| 依赖事实源 | `pyproject.toml + uv.lock` | 不并行维护手写 Pipfile/requirements 作为事实源 |
| 默认输出 | 标准行级 LRC | 不默认输出增强逐字 LRC |
| 默认模型 | MTL，架构 profile 为 `legacy-v1` | 不在重构中更换 checkpoint 或模型语义 |
| 人声分离 | 默认关闭，显式启用才加载 Demucs | 不默认下载权重，不让 core 隐式依赖 Demucs |
| 离线 | 默认离线；核心路径不得访问网络 | 不以在线下载成功作为 core 可用条件 |
| 部分对齐 | 默认严格拒绝；只有显式允许才能产出 partial | 不把非空但不完整的 LRC 当作完整成功 |
| 解码器 | 默认 `torchaudio`；`librosa-mono` 是显式 policy | 不做依赖环境决定的静默 fallback |
| CLI 输出 | 无 `-o` 时 stdout 只含 LRC；有 `-o` 时 stdout 为空并原子写文件 | 日志、warning、进度不得污染 stdout |
| Python API | 返回结构化 `AlignmentResult`，不写文件、不打印 | 不只返回裸字符串，不接收 v1 五元模型 tuple |
| v1 行为 | 仅以 characterization/oracle 形式保存在测试证据中 | 不发布旧 CLI、旧 `process()` 或兼容 shim |
| 数值后端 | 内部保留冻结的 `legacy-v1` backend 读取现有 checkpoint | 不在本轮修复历史 LSTM 轴语义 |

### 1.1 冻结的 LegacyV1 数值协议

- 输入采样率：22,050 Hz；channel-first；多声道只取第一个声道。
- Mel：128 bins，`n_fft=512`，`win_length=512`，`hop_length=256`；其余当前默认参数要在 manifest 中显式固化。
- 时间池化：3；帧时钟：`seconds_per_frame = 768 / 22050`；frame 0 offset 为 0。
- 时间戳毫秒转换：截断，不四舍五入。
- phone 0–38：现有 ARPABET 顺序；空格 39；CTC blank/unknown 40。
- Baseline 输出 41 类；MTL 输出 `41 × 47`，沿 melody 维求和后 `log_softmax`。
- BDR `alpha=0.8`；普通 DTW 与 BDR DTW 各自保留现有转移、tie-break 和回溯语义。
- 第 1 层 LSTM `batch_first=True`；第 2、3 层 `batch_first=False`。旧 checkpoint 严格加载成功不能证明更改此语义是兼容的。
- posterior smoothing 的调用位置和分布保持；canonical oracle 每次运行固定 CPU 和 seed 0。

已知证据：把第 2、3 层改成 `batch_first=True` 后，旧权重仍可加载，但固定输入最大输出差异约为 Baseline 1.4072、MTL 0.2068、BDR 0.0104。因此这项“修复”必须属于新模型架构版本，而不是本次重构。

## 2. 目标架构

### 2.1 设计原则

1. 应用用例只编排能力，不直接依赖 torch、torchaudio、librosa、Demucs、fastText 或文件写入。
2. 领域对象表达完整性、时间轴和诊断，避免用一个 LRC 字符串隐式表达成功。
3. LegacyV1 是内部适配器和明确的模型 profile，不是整个 v2 代码结构。
4. CLI 是唯一文件输入/输出边界；Python API 无 stdout、stderr 和文件副作用。
5. 端口保持粗粒度，避免为每个函数引入抽象层，也不引入 DI 框架或插件市场。

### 2.2 建议目录

```text
t2l/
  __init__.py                    # 只导出 v2 公共 API
  api.py                         # process/create_runtime
  contracts.py                   # request/result/value objects/enums
  errors.py                      # 稳定错误 code、stage、details
  composition.py                 # 唯一默认装配根
  application/
    align_lyrics.py              # AlignLyricsUseCase
    ports.py                     # 粗粒度 Protocol
  domain/
    lyrics.py                    # 行、token、phone、span 值对象
    alignment.py                 # 完整性判定和对齐结果
    lrc.py                       # 纯 renderer
  adapters/
    lyrics_legacy_v1.py          # 现有清理/路由/转写/G2P 行为
    audio.py                     # decoder、声道、重采样 policy
    vocals_demucs.py             # 可选依赖，惰性 import
    assets.py                    # asset root 与 manifest 校验
    legacy_v1_inference.py       # 冻结声学模型、smoothing、DTW/BDR
    cli.py                       # v2 CLI 和原子文件 sink
  mtl/
    model.py                     # 迁移期冻结的模型定义
tests/
  unit/
  contract/
  component/
  golden/
  e2e/
  performance/
```

### 2.3 数据流

```text
CLI / Python API
  -> AlignmentRequest
  -> AlignLyricsUseCase
       -> LyricsPreparationPort -> LyricsPlan + PhoneEncoding
       -> AudioPreparationPort  -> AudioBuffer
       -> InferencePort         -> Posteriorgram + AlignmentOutcome
       -> completeness policy   -> complete / partial / error
       -> LrcRenderer           -> serialized LRC
  -> AlignmentResult
  -> CLI sink: stdout XOR atomic output file
```

应用层可以让 tensor/ndarray 保留在推理适配器内部，不要求为了“纯领域”在热路径中反复复制大数组。

## 3. v2 合同草案

### 3.1 Python API

```python
@dataclass(frozen=True, slots=True)
class AlignmentRequest:
    lyrics: tuple[str, ...]
    audio_path: Path
    timestamp_mode: Literal["line", "word"] = "line"
    acoustic_model: Literal[
        "Baseline", "MTL", "Baseline_BDR", "MTL_BDR"
    ] = "MTL"
    allow_partial: bool = False
    vocal_separation: VocalSeparationOptions | None = None


@dataclass(frozen=True, slots=True)
class RuntimeConfig:
    asset_root: Path | None = None
    device: Literal["auto", "cpu", "cuda"] = "auto"
    offline: bool = True
    decoder: Literal["torchaudio", "librosa-mono"] = "torchaudio"
    seed: int = 0
    max_alignment_bytes: int = 512 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class AlignmentResult:
    lrc: str                         # 无末尾换行，CLI serializer 再补一个
    status: Literal["complete", "partial"]
    spans: tuple[TokenAlignment, ...]
    diagnostics: tuple[Diagnostic, ...]
    model_profile: str               # "legacy-v1"
    timebase: Timebase
    expected_token_count: int
    allow_partial: InitVar[bool] = False  # 仅用于构造时不变量校验


def process(
    request: AlignmentRequest,
    *,
    runtime: AlignmentRuntime | None = None,
) -> AlignmentResult: ...


def create_runtime(
    config: RuntimeConfig = RuntimeConfig(),
) -> AlignmentRuntime: ...
```

`process()` 是单次调用便利入口；需要复用惰性资源或并发控制的调用方应显式持有 `AlignmentRuntime`。模型 tuple、`out_file`、`verbose`、`vocalize` 等 v1 参数不进入 v2 API。

并发合同也属于 runtime 接口的一部分：同一 runtime 的 provider、失败 cache、checkpoint model 和 per-runtime lock 不与其他 runtime 共享；NLTK module/cache/search path 是受控的进程级状态，本版禁止同进程混用不同资产版本。同一 LegacyV1 model/device 的 feature/model forward/smoothing 先串行化；纯 DTW、completeness 和 renderer 不在该锁内。G2P/FastText/Kakasi 当前仅对初始化加锁，在并发调用安全性完成真实后端证明前，不得宣称同 provider 并发可用；若证明不安全，则调用也必须串行化。初始化失败在当前 runtime 内缓存并向等待者重抛，重试要创建新 runtime。

当前实现的 eager/lazy 边界必须按阶段表述：`create_runtime()` 会解析 package manifest schema、解析并 hash LID 文件、构造 Mel transform；fastText model、NLTK zip 校验、G2P 实例、checkpoint/model 仍是惰性。如果未来要求 `create_runtime()` 只解析 schema，必须先改代码并用 contract test 证明，不能只修改文档描述。当前 `RuntimeConfig.offline=False` 会立即抛出 `T2L_CONFIG_INVALID`；在单独 ADR 定义并实现在线模式以前，不得静默等同于离线，也不得产生网络访问。

### 3.2 值对象不变量

- `PhoneSpan`、`FrameSpan` 都是整数 `[start, end)` 半开区间，且自身保证 `0 <= start < end`；仅 `PhoneSpan(length=...)` 在值对象层校验 `end <= length`，`FrameSpan` 是否超出 posterior frame count 由 inference adapter 校验。
- 同一序列内 spans 单调且不重叠；是否允许空隙由具体类型明确声明。
- `AudioBuffer.samples` 的公共不变量为 float32、shape `[channels, samples]`、finite、至少一个 channel 和一个 sample；这些条件由 concrete audio adapter 在构造前建立，不由无 NumPy/torch 依赖的 contracts 类自行检测。
- `Posteriorgram` 为二维 finite 数值，至少 41 类，并携带 `FrameClock`。
- `AlignmentResult.status=complete` 时，必须满足 `aligned_token_count == expected_token_count`。
- `status=partial` 只能在请求显式 `allow_partial=True` 时构造，且 diagnostics 至少含 expected、aligned、首个缺口和 stage。

### 3.3 错误模型

所有已知领域错误继承 `T2LError`，保存原始 `__cause__`，并提供稳定字段：

| 类型 | `code` 示例 | `stage` |
|---|---|---|
| `ConfigurationError` | `T2L_CONFIG_INVALID` | `configuration` |
| `LyricsInputError` | `T2L_LYRICS_INVALID` | `lyrics` |
| `AudioDecodeError` | `T2L_AUDIO_DECODE_FAILED` | `audio_decode` |
| `SourceSeparationError` | `T2L_VOCALS_FAILED` | `source_separation` |
| `AssetNotFoundError` | `T2L_ASSET_NOT_FOUND` | `asset_resolution` |
| `CheckpointError` | `T2L_MODEL_LOAD_FAILED` | `model_load` |
| `ModelRuntimeError` | `T2L_MODEL_RUNTIME_FAILED` | `model_inference` |
| `AlignmentInputError` | `T2L_ALIGNMENT_INVALID` | `alignment` |
| `IncompleteAlignmentError` | `T2L_ALIGNMENT_PARTIAL` | `alignment` |
| `OutputWriteError` | `T2L_OUTPUT_WRITE_FAILED` | `output` |

不得把 Demucs/CUDA OOM 重分类成音频文件无效，也不得丢弃 decoder 的原始 cause。

上表是目标注册表，不代表当前已全部实现。当前 manifest schema 失败仍可能以 `ManifestValidationError(ValueError)` 落入 CLI code 1；冻结 reference 的 `AlignmentValueError` 也尚未全部统一映射；fastText、Kakasi 和 G2P backend 初始化错误仍有原样传播路径。RC 前必须完成第 16.7 节的边界映射；保留 cause 仅指已知边界包装，Python API 中的未知异常必须原样传播。

### 3.4 CLI 合同

```text
ai-auto-lrc LYRICS AUDIO
  [-o OUTPUT_FILE]
  [--timestamps line|word]
  [--acoustic-model Baseline|MTL|Baseline_BDR|MTL_BDR]
  [--allow-partial]
  [--device auto|cpu|cuda]
  [--asset-root PATH]
  [--decoder torchaudio|librosa-mono]
  [--separate-vocals]
  [--demucs-model mdx|mdx_extra|mdx_q|mdx_extra_q]
  [--demucs-index -1|0|1|2|3]
  [--verbose]
  [--debug]
```

输出规则：

- 无 `-o`：stdout 是 UTF-8 LRC，恰好一个末尾换行；stderr 可输出诊断和进度。
- 有 `-o`：stdout 必须是 0 字节；同一 serializer 的字节原子写入目标文件。
- 已知错误：stderr 单行 `<code>: <message>`；只有 `--debug` 输出 traceback。
- 默认只写 warning/error；`--verbose` 才增加阶段进度，但仍只写 stderr。
- `--demucs-*` 未配合 `--separate-vocals` 时是配置错误，不静默忽略。
- 输出父目录可以创建；临时文件必须位于同一目录，flush、fsync 后 `os.replace`；失败时保留旧目标并清理临时文件。

退出码最终决策：

| code | 语义 | 是否可能有 LRC 输出 |
|---:|---|---|
| 0 | 完整成功 | 是 |
| 1 | 未分类内部错误 | 否 |
| 2 | argparse 或配置错误 | 否 |
| 3 | 用户显式允许且实际产生 partial | 是 |
| 4 | 歌词输入错误 | 否 |
| 5 | 音频解码或人声分离错误 | 否 |
| 6 | 资产、checkpoint、模型或设备错误 | 否 |
| 7 | 对齐输入、对齐失败或默认拒绝 partial | 否 |
| 8 | 输出文件写入错误 | 否 |

`3` 采用“结果已产出但不完整”的可观测语义。调用脚本必须能区分完整成功与显式降级；因此不使用 0 表示 partial。

当前 CLI 实现边界：`--verbose` 已解析但尚未接入 observer，partial stderr 尚未输出锁定的 `expected/aligned/first_gap`，`--debug` 仍直接打印原始 traceback。在统一 redactor 与 installed-console subprocess 测试完成前，不得把这三项写成发布级能力；若 traceback 无法可靠消毒，debug 只能移入明确的本地开发接口。直接调用 `main()` 只算 unit/contract 证据，安装后 console script 子进程才能关闭 CLI required gate。

### 3.5 资产解析

解析顺序固定为：

1. `RuntimeConfig.asset_root` / CLI `--asset-root`；
2. `T2L_ASSET_ROOT`；
3. 仅开发 checkout 可用的源码根目录探测。

绝不搜索任意 CWD。manifest 记录资产逻辑名、相对路径、SHA-256、大小、architecture id、feature spec id、phone inventory id 和来源/许可字段。文件存在但 hash、key 或 shape 不匹配时必须失败关闭。

当前已核验 hash：

| 资产 | SHA-256 |
|---|---|
| Baseline | `b420ea97032691b3f51e271c0b688a85e168d7b7ee89baf6725f601ccd07bb45` |
| MTL | `826559e7e810bf8f90223d8fd5c66525c01ad4dd9cdc19d019f39f784e7ed3c1` |
| BDR | `a3955b290311bec16f04253eac328147d444f275f263315490ec5faf1a668fc9` |
| LID | `8f3472cfe8738a7b6099e8e999c3cbfae0dcd15696aac7d7738a8039db603e83` |
| demo MP3 | `e5d68541c999bec2a6ff7f4eeba0ad893c56895e8509855abb5ca9e292c980b8` |
| demo 歌词 | `f15162581177f5f5383cb4921c71c929ecdc93281c19468357fcb57ed0f1361c` |
| 合成 440 Hz/250 ms MP3 codec fixture | `55bfeaa909966bef5f8c74ab9e01ac13d2b4e8b17d41bf07ccc44536df250ab8` |

## 4. 实施路线与依赖

```text
R0 仓库安全重置
  -> R1 环境、打包与 CI
    -> R2 LegacyV1 证据与 golden
      -> R3 v2 合同与编排骨架
        +-> R4 歌词、语言、G2P
        +-> R5 音频、资产、模型
              R4 + R5
                 -> R6 对齐、渲染、CLI
                   -> R7a 旧入口/范围清理 -> R7b 资格验证与 v2 RC
```

### R0 仓库安全重置

目标：建立可恢复证据后，才执行用户已决定的新 Git 历史。

交付物：

- 包含全部 refs 的 Git bundle，并执行 `git bundle verify`；
- 基线提交、origin、当前分支、Git LFS 版本和全部受控资产 hash 清单；
- `git lfs fsck` 结果和许可证/来源记录；
- 新仓库首次提交中包含事实交接文档、本计划和恢复说明。

Go：bundle 可在临时目录 clone，基线提交可 checkout，LFS 对象和 hash 可追溯。
No-go：bundle 未验证、LFS 只保留 pointer、资产来源记录缺失或工作区变更未盘点。

### R1 环境、打包与 CI

目标：先得到可冻结安装，再迁移业务结构。

- 创建 `pyproject.toml` 和 `uv.lock`；canonical 数值环境优先固定旧声明的 torch/torchaudio 2.1.2 与 NumPy 1.26.3，并验证可解析性。
- core、`vocals` optional extra、dev/test 分组明确分离。
- `pytest` 和 `python -m pytest` 在 editable install 后行为一致。
- 建立 Python 3.10/3.11 Linux CI；macOS 3.11 负责安装与真实解码 smoke。

依赖发布约束不能只验证“本机可安装”：当前元数据调查显示 `fasttext==0.9.2`、`av==10.0.0`、`demucs==4.0.1` 没有目标 CPython 3.10/3.11 平台 wheel；`fasttext-wheel==0.9.2` 是候选替代，但必须验证 `fasttext` import、标签和概率等价；`av` 随 X01 移出 core；`julius==0.2.7`、`kroman==1.1` 只能作为有版本、责任人和到期日的纯 Python sdist 白名单，由 CI 预构建 wheel。Demucs 只进入 separation wheelhouse。

Go：clean clone 可 `uv sync --frozen`；核心测试断网通过；无第二依赖事实源漂移；目标平台可以从本地 wheelhouse 脱离源码树安装。
No-go：torch/torchaudio 组合不匹配，未启用 Demucs 仍触发 optional import/download，或 core 安装依赖未批准的原生 sdist 编译。

### R2 LegacyV1 证据与 golden

目标：在改变模块结构前冻结 C01–C10 的真实输入、中间结果和输出。

- 为现有 30 个测试补 characterization，而不是修改其断言以迎合新设计。
- 建立 checkpoint manifest、固定输入数值 fingerprint、授权短音频 golden。
- canonical CPU、seed 0，同一案例连续运行 3 次。
- 记录 token、phone、spans、Mel shape、posterior 摘要、word frames、line/word LRC。

Go：checkpoint strict load、key 集合、shape、frame spans 和 LRC 稳定；golden 全程无网络。
No-go：只靠 fake/model-load 通过就声称数值兼容，或使用宿主 torchaudio 2.11 生成正式 oracle。

### R3 v2 合同与编排骨架

目标：先引入值对象、错误层、ports 和全 fake 用例，不搬迁数值实现。

- 建立 `contracts.py`、`errors.py`、`application/ports.py` 和 `AlignLyricsUseCase`。
- 旧实现先被薄适配器调用；v2 API 不暴露旧 tuple 或文件写入。
- 严格/partial 状态在编排层统一判定。

Go：全 fake 测试证明阶段顺序、早失败、无 I/O 副作用、结构化错误和完整性不变量。
No-go：应用层 import torch/Demucs/fastText，或完整性仍由 renderer 静默决定。

### R4 歌词、语言与 G2P

目标：把清理、行组织、整行语言路由、转写和 G2P 分层，同时保持 LegacyV1 token/phone 语义。

- fastText 和 G2P 由 runtime 内惰性、线程安全 provider 持有。
- 保留语言优先级：假名 -> CJK -> Hangul -> Cyrillic -> fastText top-1。
- 保留混合文本整行主导、数字现状、贪婪 metadata regex 和 unknown->blank，仅增加 diagnostics。

Go：五种语言、混合文字、数字、空行、标签、重复 token 的 token/phone/span oracle 完全一致。
No-go：顺便改成 token 级语言识别、新增 UNK 类或更换 G2P。

### R5 音频、资产与模型

目标：隔离 decoder、可选 Demucs、资产解析和 LegacyV1 推理。

- 默认 torchaudio；`librosa-mono` 只能显式选择。
- Demucs 惰性 import；启用但 extra/本地权重缺失时返回稳定错误。
- 模型由 manifest 选择 architecture；未知 checkpoint 不靠“能加载”猜测。
- hash 和 LFS pointer 校验必须早于反序列化；受支持时使用 `torch.load(..., weights_only=True)`。若旧格式暂不兼容，只允许 manifest 白名单内且 hash 完全匹配的本地 checkpoint。
- LegacyV1 模型计算图、state-dict key、首声道和 smoothing 不变。

Go：WAV/MP3、mono/stereo、重采样、asset root、三个 checkpoint、所有输出 shape/fingerprint 通过。
No-go：改变声道混合、LSTM 轴、Mel 默认或更新 checkpoint 才能通过。

### R6 对齐、渲染与 CLI

目标：统一完整性判定、时间轴、renderer 和单目标 CLI 输出。

- 普通 DTW/BDR 先保留 reference backend，不在此阶段优化算法。
- 分配 DP 大矩阵前完成 finite、shape、整数和 span 校验。
- renderer 只消费结构化结果和 `FrameClock`。
- CLI 实现退出码、stderr、stdout XOR 文件和原子覆盖。

Go：strict/partial、路径耗尽、tie-break、时间截断、输出字节和故障注入测试全部通过。
No-go：任何路径返回无法判断完整性的裸字符串，或失败覆盖旧输出文件。

### R7a 旧入口与范围清理

目标：删除不在范围的代码/依赖，将 v2 公开面积收敛到 C01–C10。

- X01–X03、训练和旧评估从 v2 包移除；保留适用许可证和来源说明。
- 删除公开 v1 API/CLI，不提供兼容 shim；迁移文档逐项说明“不再支持”或 v2 替代。
Go：旧入口、训练/旧评估和多份依赖事实源已清理，冻结模型实现和适用许可证保留。
No-go：误删 LegacyV1 数值实现/许可证，或仍对外暴露 v1 shim。

### R7b 资格验证与 v2 RC

目标：在 R7a 清理已完成的基础上，完成跨平台、离线、数值、性能、迁移、恢复和发布证据。R7a 完成不代表 R7b Go。

- wheel 安装、console script、任意 CWD、断网、Python 3.10/3.11、质量/性能报告全部验证。
- canonical golden、installed subprocess、TOCTOU、并发、离线 wheelhouse、迁移与恢复门禁全部关闭。

Go：全部 required gate 绿色，文档默认值与运行结果一致，RC 证据可追溯。
No-go：用轻量绿测代替真实 golden，或把未跑的 GPU/Demucs 资格写成已验证。

## 5. 测试结构与执行分层

### 5.1 建议测试文件

```text
tests/
  unit/
    test_contract_values.py
    test_lyrics_cleaning.py
    test_language_routing.py
    test_phone_encoding.py
    test_alignment_validation.py
    test_lrc_renderer.py
  contract/
    test_python_api_contract.py
    test_cli_contract.py
    test_error_contract.py
    test_ports_contract.py
  component/
    test_audio_decoders.py
    test_demucs_adapter.py
    test_asset_locator.py
    test_checkpoint_manifest.py
    test_legacy_v1_model.py
    test_dtw_reference.py
  golden/
    test_legacy_v1_text_golden.py
    test_legacy_v1_numeric_golden.py
    test_offline_e2e_golden.py
  e2e/
    test_cli_subprocess.py
    test_wheel_install.py
    test_cwd_independence.py
  performance/
    test_runtime_benchmarks.py
    test_alignment_memory.py
```

### 5.2 markers

- 无 marker：纯单元/合同，PR 必跑，不需要网络、真实模型或 GPU。
- `component`：真实本地小文件或 checkpoint，PR asset job 必跑。
- `golden`：canonical CPU、固定锁和 LFS 资产，PR asset job 必跑。
- `package`：构建或检查 wheel/sdist、隔离安装目录和 installed console script；是否覆盖冷依赖安装由具体规格单独声明。
- `slow`：长音频或完整 demo，nightly/RC。
- `vocals`：真实 Demucs，仅 nightly/人工资格；不得成为 core 安装前提。
- `cuda`：显式 GPU runner；未执行时报告 skipped，不得报告已验证。
- `performance`：固定 runner 的基准比较；普通共享 runner 不设硬性能门槛。

测试必须默认禁网。确需网络的资产准备步骤与测试执行步骤分离；测试阶段只消费已校验的本地缓存。

## 6. 现有测试到目标覆盖的映射

| 现有证据 | 保留用途 | 仍需补齐 |
|---|---|---|
| `tests/test_cli.py` parser/标准化 | v1 characterization | 完整子进程、纯 stdout、stderr、退出码、原子写 |
| `tests/test_t2l.py` decoder fake/异常 | v1 characterization | 真实 WAV/MP3、显式 decoder policy、空音频、CWD |
| `tests/test_t2l.py` UTF-8 写出 | v1 characterization | v2 API 无写出、CLI 同一 serializer、失败保留旧文件 |
| `tests/test_wrapper.py` 首声道/inference mode | LegacyV1 单元证据 | 真实 Mel、checkpoint、posterior、并发与 RNG 隔离 |
| `tests/test_alignment.py` shape/span 最小校验 | reference DTW 单元证据 | finite、非整数、tie-break、路径耗尽、BDR alpha |
| 当前全部 30 例 | 快速回归基线 | 不证明真实模型、五语、质量、打包、离线和性能 |

## 7. 可执行测试用例规格

以下 ID 是稳定追踪号，共定义 162 条基础规格；参数化展开后实际 pytest case 会更多。实现时测试函数名可以调整，但 PR 描述和能力矩阵应保留 ID。

### 7.1 API、用例编排与错误

| ID / 建议测试 | 输入与 fixture | 动作 | 精确断言 |
|---|---|---|---|
| API-001 `test_defaults_are_locked` | 最小 request | 构造 `AlignmentRequest` | line、MTL、strict、无 separation；对象不可变 |
| API-002 `test_complete_result_invariants` | 2 tokens、2 spans | 构造 complete result | status=complete；计数相等；timebase/profile 存在 |
| API-003 `test_complete_rejects_missing_span` | 2 tokens、1 span | 构造 complete result | 在 renderer 前抛不变量错误 |
| API-004 `test_partial_requires_opt_in` | fake inference 返回少 1 span | strict 调用 | 抛 `IncompleteAlignmentError`；后续 renderer 未调用 |
| API-005 `test_partial_reports_first_gap` | 同上，allow partial | 调用用例 | status=partial；expected=2、aligned=1、first_gap=1 |
| API-006 `test_use_case_stage_order` | 记录调用的 fake ports | 完整调用 | 顺序严格为 lyrics、audio、inference、validate、render |
| API-007 `test_early_failure_stops_pipeline` | lyrics fake 抛错 | 调用 | audio/inference/render 调用次数均为 0 |
| API-008 `test_api_has_no_io_side_effects` | fake ports + capsys/tmp cwd | 调用顶层 API | stdout/stderr 均空；目录树无新增文件 |
| API-009 `test_known_error_preserves_cause` | decoder fake 抛 `EOFError` | 经 adapter/API 调用 | v2 类型/code/stage 正确；`__cause__` identity 不变 |
| API-010 `test_unknown_error_not_misclassified` | model fake 抛自定义 RuntimeError | 调用 | 不变成 `AudioDecodeError`；内部边界保留 traceback |
| API-011 `test_runtime_reuses_lazy_providers` | 带计数的 LID/G2P providers | 同 runtime 调用两次 | 两个 provider 各初始化 1 次 |
| API-012 `test_runtimes_are_isolated` | 两个 runtime、不同 fake | 分别调用 | 无状态串用；计数和输出分别归属各自 runtime |
| API-013 `test_public_signature_is_v2_only` | `inspect.signature(t2l.process)` | 导入公共 API | 精确为 `(request, *, runtime=None)`；顶层无旧散参数/tuple |
| API-014 `test_no_public_legacy_namespace` | 枚举 wheel 中 `t2l` 公共模块 | 导入/检查 | 不发布 `t2l.legacy.v1`、旧 CLI 或 v1 shim |
| API-015 `test_diagnostics_are_not_duplicated` | lyrics/outcome 分别返回唯一 diagnostic，另覆盖 partial policy | 调用用例 | 每个来源 diagnostic 在最终结果中恰好出现一次；partial policy 最多追加一个完整性 diagnostic |

### 7.2 CLI、stdout/stderr、退出码与原子写

所有 CLI 合同测试以子进程执行安装后的 `ai-auto-lrc`，不能只直接调用 `main()`。

`allow_partial` 是 application contract 支持的条件能力，不代表默认 LegacyV1 backend 当前可触达。冻结 backend 对合法可达输入强制完整终态；零前缀回溯耗尽始终 fail closed 并映射 CLI code 7。因此 `CLI-004`、`CLI-022` 在新 partial ADR、截断判据和 numeric oracle 批准前为 `deferred`；fake outcome 只证明 application/CLI 合同，不构成 backend qualification。

| ID | Given / When | 精确断言 |
|---|---|---|
| CLI-001 | 无 `-o`，complete fake/fixture | code=0；stdout 等于 `serialized_lrc + b"\n"`；无额外字节 |
| CLI-002 | 有 `-o`，complete | code=0；stdout=b""；目标文件字节与 CLI-001 stdout 完全相同 |
| CLI-003 | 日志级别正常 | 所有 progress/warning 只在 stderr；stdout 仍可直接 pipe 为 LRC |
| CLI-004 | allow partial 且真实产生 partial，无 `-o` | code=3；stdout 有 partial LRC；stderr 含稳定 partial code 和计数 |
| CLI-005 | 默认 strict，同一 incomplete 输入 | code=7；stdout=b""；stderr 单行 `T2L_ALIGNMENT_PARTIAL:` 开头 |
| CLI-006 | argparse 缺参数/非法枚举 | code=2；stdout=b""；stderr 是 usage/错误 |
| CLI-007 | `--demucs-model` 无 `--separate-vocals` | code=2；不会 import Demucs，不访问网络 |
| CLI-008 | 歌词为空 | code=4；stdout 空；stderr 单行稳定错误 |
| CLI-009 | decoder 双失败 | code=5；stdout 空；错误不包含 traceback（无 `--debug`） |
| CLI-010 | checkpoint hash 错 | code=6；stdout 空；错误包含逻辑资产名而非敏感环境 dump |
| CLI-011 | 未知内部错误 | code=1；stdout 空；非 debug 仅通用消息 |
| CLI-012 | CLI-011 加 `--debug` | code=1；stderr 有 traceback 和原始异常链 |
| CLI-013 | 输出父目录不存在 | 自动创建父目录；code=0；文件完整 |
| CLI-014 | 目标已有 OLD，serializer 失败 | code=8；旧文件仍为 OLD；无残留 temp |
| CLI-015 | 目标已有 OLD，`os.replace` 失败 | code=8；旧文件仍为 OLD；无残留 temp |
| CLI-016 | Unicode 路径和歌词 | 文件为 UTF-8；内容字节与 stdout 模式一致 |
| CLI-017 | 从仓库外 CWD 运行 | 显式 asset root 成功；不读取 CWD 同名恶意 checkpoint |
| CLI-018 | 完整成功但 stderr 有 warning | code 仍为 0；warning 不进入 stdout/file |
| CLI-019 | 文件名含换行/ANSI 控制符 | stderr 对不可见字符做转义；不能伪造第二条日志或终端控制序列 |

#### 7.2.1 原子文件 sink 的故障点

成功路径必须是真实 `tmp_path` 文件操作，不能只 mock `open()`；仅在故障注入点窄范围 monkeypatch。

| ID | 注入点 | 精确断言 |
|---|---|---|
| OUT-001 | 父目录不存在 | 创建父目录；写 UTF-8；恰好一个尾换行；无 temp 残留 |
| OUT-002 | 目标已有 `OLD` | `os.replace` 恰好一次；temp 与目标同目录；最终为完整 `NEW` |
| OUT-003 | write/flush 抛 `ENOSPC` | replace 未调用；旧目标逐字节不变；cause identity 保留 |
| OUT-004 | fsync 抛 `EIO` | replace 未调用；旧目标不变；temp 清理 |
| OUT-005 | replace 抛 `EACCES` | 旧目标不变；temp 清理；`T2L_OUTPUT_WRITE_FAILED` |
| OUT-006 | 初始无目标且任一阶段失败 | 目标仍不存在，不能留下半文件 |
| OUT-007 | 目标是 symlink | 默认拒绝，不间接覆盖 link target；错误稳定 |
| OUT-008 | 两线程写同一目标 | 最终只能完整等于候选 A 或 B，不能拼接/截断；无 temp 残留 |
| OUT-009 | 输入 LRC 有 0/1/多个尾换行 | serializer 统一成恰好一个 `\n` |

`KeyboardInterrupt`、`SystemExit`、`GeneratorExit` 不得被包装成普通领域错误；CLI 被中断时同样不得覆盖旧目标。

### 7.3 歌词文件编码

C03 只在 CLI 文件 adapter 中存在；Python API 接收已经解码的 `tuple[str, ...]`。迁移期先冻结当前探测规则，再决定是否替换探测库。

| ID | 输入 | 精确断言 |
|---|---|---|
| ENC-001 | UTF-8、UTF-8 BOM 中文文件 | 解码文本无 BOM；换行拆分稳定 |
| ENC-002 | detector 返回 `GB2312` 的 GBK fixture | 实际以 `GBK` 解码，中文逐字相等 |
| ENC-003 | detector 返回 None | 回退严格 UTF-8；不使用 locale 默认编码 |
| ENC-004 | detector 给错误编码/bytes 非法 | `LyricsInputError`，code/stage/cause 正确；audio 未调用 |
| ENC-005 | 文件不存在、目录、权限错误 | 歌词读取阶段错误；stdout 空；不进入语言/音频/模型 |
| ENC-006 | CRLF/LF/末尾无换行 | 得到一致的逻辑行 tuple；显示文本不带换行符 |

探测置信度和所选 encoding 应进入 diagnostic/stderr verbose 信息，但不能混入 LRC。若后续移除 `chardet`，必须先用这些 fixtures 证明新 adapter 的合同等价或单独批准行为变化。

### 7.4 歌词清理、语言路由与 phone

文本用例先冻结 LegacyV1 行为；任何看似不合理的结果都记录为 oracle，不在抽层 PR 中修正。

| ID | 输入重点 | 精确断言 |
|---|---|---|
| TXT-001 | 纯空白/仅标签 | `LyricsInputError(LYRICS_EMPTY)` |
| TXT-002 | 首行无可对齐字符、后续有效 | `pre_lines_unprocessed` 和有效行顺序与 v1 一致 |
| TXT-003 | 有效行后的空行/无 phone 行 | 追加到上一显示 token 的换行语义不变 |
| TXT-004 | `[01:02.003]text` | 仅行首时间标签被移除 |
| TXT-005 | `[ar:a][ti:b]text` | 固定当前贪婪 metadata 行为的精确 snapshot |
| TXT-006 | 标签在行中间 | 不按行首规则移除 |
| TXT-007 | 全角字母、空格和标点 | `q2bs` 后文本逐字符相等 |
| TXT-008 | 纯 ASCII 英文 | 不调用 fastText；返回单个 `(display, phonetic)` |
| TXT-009 | 含假名+CJK | 路由为 ja，证明假名优先于 CJK |
| TXT-010 | CJK+Hangul | 路由为 zh，证明 CJK 优先于 Hangul |
| TXT-011 | Hangul+Cyrillic | 路由为 ko |
| TXT-012 | Cyrillic+无脚本文本 | 路由为 ru |
| TXT-013 | 无上述脚本 | fastText top-1 被调用一次；低置信仅诊断，不改标签 |
| TXT-014 | 中/日/韩/英/俄固定短句 | display、romanized token 和数量精确 snapshot |
| TXT-015 | 混合文字 | 保持整行主导路由，不做 token 级重判 |
| TXT-016 | 数字和标点 | 固定当前切分、附着和丢弃行为 |
| TXT-017 | G2P 返回带重音 ARPABET | 所有末尾数字剥离 |
| TXT-018 | G2P 返回未知 phone | index=40；diagnostic unknown_count 精确增加 |
| TXT-019 | 两词两行、重复词 | word/line spans 均为整数 `[start,end)`，顺序和空格 39 精确 |
| TXT-020 | provider 并发首次访问 | 只初始化一次；所有调用看到同一已完成实例，无半初始化 |

### 7.5 音频、decoder 与 Demucs

| ID | fixture / 动作 | 精确断言 |
|---|---|---|
| AUD-001 | 真实 mono WAV，torchaudio policy | float32 `[1,n]`；采样率和 decoder id 正确 |
| AUD-002 | 真实 stereo WAV，两声道值不同 | buffer 保留 `[2,n]`；LegacyV1 特征只消费 channel 0 |
| AUD-003 | 44.1k WAV -> 22.05k | 输出 sample rate 22050；长度按定义；非空 finite |
| AUD-004 | 真实小 MP3 | canonical 锁内成功；不触发 librosa |
| AUD-005 | torchaudio 抛 ImportError/codec error | 默认 policy 抛 `AudioDecodeError`，不静默 fallback |
| AUD-006 | 显式 `librosa-mono` | 调用 librosa 且输出 `[1,n]`；metadata 标记 mono policy |
| AUD-007 | 空文件/decoder 返回零 samples | 稳定 `AUDIO_EMPTY`，cause 规则明确 |
| AUD-008 | NaN/Inf waveform | 在模型前失败；模型调用次数为 0 |
| AUD-009 | 默认请求 | Demucs 模块未 import；下载/API 调用次数为 0 |
| AUD-010 | 开启 separation 但未安装 extra | 稳定 `VOCALS_DEPENDENCY_MISSING`，无裸 ImportError traceback |
| AUD-011 | fake Demucs 无 `vocals` source | `SourceSeparationError`；不返回 `None` 给重采样 |
| AUD-012 | bag index -1/0/3/4 | -1 使用 ensemble；合法 index 精确选择；越界配置错误 |
| AUD-013 | fake Demucs forward | model 已 `eval()`；`torch.inference_mode()` 为 true |
| AUD-014 | offline=true、缓存缺失 | 立即失败并给资产提示；绝不尝试下载 |

### 7.6 资产、manifest 与 checkpoint

| ID | 输入/动作 | 精确断言 |
|---|---|---|
| AST-001 | config、env、dev root 同时存在 | 严格选择 config；返回 resolution provenance |
| AST-002 | env 与 dev root 存在 | 选择 env |
| AST-003 | 只有 CWD 同名文件 | 不选择；抛 `ASSET_NOT_FOUND` |
| AST-004 | symlink/路径逃逸 | 按安全策略拒绝 asset root 外解析 |
| AST-005 | 文件缺失 | 错误列逻辑名和已检查 root，不输出无关环境变量 |
| AST-006 | hash 一位变化 | 加载前失败；模型构造/反序列化次数为 0 |
| AST-007 | 三个官方 checkpoint | SHA 与第 3.5 节完全相等 |
| AST-008 | LFS pointer 文本代替对象 | 报 `ASSET_LFS_POINTER`，不交给 `torch.load` |
| AST-009 | manifest architecture/profile 不匹配 | strict 失败，不以 state-dict 可加载覆盖 manifest |
| AST-010 | state-dict 缺 key/多 key/shape 改变 | 三类均分别诊断；`strict=True` |
| AST-011 | Baseline/MTL/BDR | 每个 key 集合为 golden；当前每个模型 state-dict 38 个模型键 |
| AST-012 | wheel 安装环境 | 无内置模型时给配置提示；不隐式寻找源码/CWD |
| AST-013 | manifest 白名单外的 pickle/checkpoint | 不反序列化；`torch.load` 调用次数为 0 |

### 7.7 LegacyV1 特征、模型与确定性

| ID | 固定输入 | 精确断言 |
|---|---|---|
| NUM-001 | 1 秒 deterministic waveform | Mel spec 参数、dtype、device、shape 与 manifest 一致 |
| NUM-002 | stereo 左 0/右 1 | 特征等于 mono 左声道结果，不等于均值/右声道结果 |
| NUM-003 | Baseline checkpoint | strict load；输出 `[1,T,41]`；finite |
| NUM-004 | MTL checkpoint | strict load；原始输出 `[1,T,41,47]` |
| NUM-005 | MTL posterior | 沿维 47 求和后 `[T,41]`，再 log-softmax；顺序锁定 |
| NUM-006 | BDR checkpoint | 输出 `[1,T,1]` 或规范化后的 `[T]`，与 manifest 一致 |
| NUM-007 | 模型模块结构 | 第 1/2/3 LSTM `batch_first` 精确为 true/false/false |
| NUM-008 | seed 0，同输入运行 3 次 | posterior fingerprint、frame spans、LRC 每次相同 |
| NUM-009 | API 前后 NumPy RNG | 调用不改变调用方全局 RNG 状态 |
| NUM-010 | API 前后 torch global RNG | v2 局部 generator 不改变调用方全局 RNG 状态 |
| NUM-011 | 同 checkpoint 固定 tensor | 数值数组 `rtol=1e-5, atol=1e-6`；argmax/frame spans 精确相等 |
| NUM-012 | 第 2/3 层轴语义突变哨兵 | 若改成 true，fingerprint 测试必须失败 |
| NUM-013 | CPU inference | 全部 forward 在 inference mode；无 grad tensor |
| NUM-014 | 共享 runtime CPU 并发 | LegacyV1 inference 被串行化、`max_active_count==1`；输出与串行一致 |

浮点容差只允许用于 posterior 比较；最终 word frame pairs 和 LRC 字节必须完全相等。

### 7.8 DTW、BDR、完整性与 renderer

| ID | 输入 | 精确断言 |
|---|---|---|
| ALN-001 | posterior 非 2D/少于 41 类 | 分配 DP 前 `AlignmentInputError` |
| ALN-002 | posterior 含 NaN/+Inf/-Inf | 分配 DP 前失败，错误含第一个非法坐标 |
| ALN-003 | span 为 float/bool/object | 拒绝；不隐式截断成整数 |
| ALN-004 | span 空、负数、end<=start、越界 | 各自稳定 details；均在 DP 前失败 |
| ALN-005 | spans 无序/重叠 | 拒绝；相邻半开区间允许 `end==next.start` |
| ALN-006 | 歌词为空/帧少于 `lyrics+2` | 稳定失败，required/actual 精确 |
| ALN-007 | tie-heavy 小矩阵 | reference 路径和 frame pairs 精确 snapshot |
| ALN-008 | 同一 tie-heavy 输入重复运行 | 普通 DTW 与 BDR 各自 deterministic |
| ALN-009 | BDR prediction 短/含非 finite | DP 前失败 |
| ALN-010 | BDR line start 越界/非整数 | DP 前失败 |
| ALN-011 | BDR 固定矩阵 | alpha 精确为 0.8；改变 alpha 哨兵失败 |
| ALN-012 | reference 返回缺失/零长尾部，或进入已知回溯耗尽 | adapter 只保留首个合法连续前缀；已知回溯耗尽转成结构化 incomplete；不制造 frame，不宣称 reference 会自然返回非空 partial |
| ALN-013 | 少 span/多 span | strict 都失败；partial 只接受可解释的少 span，不吞多 span |
| ALN-014 | frame 0、frame 1、长分钟 | 秒换算为 `frame*768/22050`，毫秒截断 |
| ALN-015 | line renderer | 每个有效行一个 `[mm:ss.xxx]`；无 word tags |
| ALN-016 | word renderer | 行 tag + `<mm:ss.xxx>`；token 文本和空白字节稳定 |
| ALN-017 | complete/partial renderer | renderer 不改变 status；partial diagnostics 不丢失 |
| ALN-018 | 结果无尾换行 -> CLI serialization | API `lrc` 无尾换行；CLI/file 恰好一个尾换行 |

#### 7.8.1 四个可直接编码的 reference DTW 用例

以下结果已在基线提交的当前实现上复核，可直接成为首批 deterministic 单元测试：

1. 单 phone：`posterior=zeros((3,41))`，lyrics=`["AA"]`，spans=`[[0,1]]`。普通与 BDR 都必须返回 frames=`[[1,2]]`、score=`0.0`。
2. 两词含空格：`posterior=zeros((5,41))`，lyrics=`["AA"," ","B"]`，spans=`[[0,1],[2,3]]`。普通与 BDR 都返回 `[[1,2],[3,4]]`、score=`0.0`。
3. tie-heavy：`posterior=zeros((8,41))`，lyrics=`["AA","B","K"]`，spans=`[[0,1],[1,2],[2,3]]`。普通与 BDR 都返回 `[[4,5],[5,6],[6,7]]`、score=`0.0`。结果看似偏晚，但它精确保护当前 tie-break。
4. 有峰值：创建 `full((7,41),-10.0)`，blank 列 40 设为 -1，frame 1 的 AA 列 0 设为 0，frame 4 的 B 列 6 设为 0；lyrics=`["AA"," ","B"]`，spans=`[[0,1],[2,3]]`。普通与全零 boundary 的 BDR 都返回 `[[1,3],[4,6]]`、score=`-14.0`。

frame spans 必须精确相等，score 用 `rtol=1e-6, atol=1e-6`。未来 optimized backend 还要对固定 seed 生成的 1,000 个合法随机矩阵与 reference 做 differential testing；随机生成器版本、dtype 和 seed 都写入 manifest。

### 7.9 离线 golden 与端到端

| ID | 场景 | 必须保存/断言的证据 |
|---|---|---|
| GOL-001 | 授权短音频 + 英文，Baseline | 输入/hash、tokens、phones、Mel shape、posterior fingerprint、frames、line LRC |
| GOL-002 | 同输入，MTL | 同上；MTL 为 v2 默认模型 |
| GOL-003 | 同输入，MTL_BDR | 同上；额外保存 boundary fingerprint |
| GOL-004 | 五语各至少一个短片段 | 覆盖率、单调性、完整状态；不得仅验证“无异常” |
| GOL-005 | 混合文字/数字/标签/空行 | 精确 token/phone/line 输出 snapshot |
| GOL-006 | mono WAV 与 stereo WAV | decoder/channel metadata 和最终 frames |
| GOL-007 | MP3 canonical decode | 固定锁内 LRC/frame 可复现；断网 |
| GOL-008 | 任意 CWD console script | 与仓库根运行 stdout 字节相等 |
| GOL-009 | strict incomplete fixture | 无输出，错误和退出码 7 |
| GOL-010 | allow-partial 同 fixture | 输出 partial，退出码 3，diagnostic 精确 |

`GOL-010` 和第 18.4 节的 `GOL-013` 当前为 `deferred`；只有产品批准新的 non-empty partial 语义后，才能晋级为 RC required。`GOL-009` 仍 required，用于证明零前缀或默认拒绝不完整结果时的零输出和 code 7。

行为保持门槛：

- v1 在 canonical 条件下完整成功的样例，v2 不得变成失败。
- refactor 阶段 phone、word/line spans、word frame pairs 和 LRC 必须完全相等。
- 若跨受支持 patch 版本 posterior 不能 bitwise 相等，可使用 `rtol=1e-5, atol=1e-6`；frame pairs 仍必须完全相等。
- 质量资格集的 frame 结果至少 99% 在 +/-1 frame 内；P50/P90 不得恶化超过 `max(1 frame, 5%)`。
- 不得新增截断、非单调时间戳或未解释的 partial。

### 7.10 并发、故障注入和边界攻击

| ID | 场景 | 精确断言 |
|---|---|---|
| ADV-001 | 16 线程同时首次使用同 runtime | LID/G2P/model 初始化各 1 次；所有结果一致；无 deadlock |
| ADV-002 | 两个 runtime 用不同 asset roots | 不交叉缓存 checkpoint/provider |
| ADV-003 | 同 runtime 初始化失败后重试，再创建新 runtime | 同 runtime 缓存同一失败且只尝试 1 次；新 runtime 才可重新加载并成功 |
| ADV-004 | SIGINT/异常发生在 temp file 写入后 | 旧目标保留；temp 被清理或下次安全识别 |
| ADV-005 | 只读目录/磁盘写满 fake | code=8；不产生截断目标 |
| ADV-006 | 极长歌词但很短 posterior | 输入门禁先失败，不分配与歌词乘积同量级 DP |
| ADV-007 | 巨大/畸形音频 header | decoder 失败受控，不输出 partial 文件 |
| ADV-008 | CWD 放置同名恶意 checkpoint | 永不读取；显式 root/manifest 决定资产 |
| ADV-009 | monkeypatch socket/connect | core/golden 任意网络尝试立即使测试失败 |
| ADV-010 | 未安装 optional extras | `import t2l`、默认 API、CLI help 均成功 |
| ADV-011 | 估算 DP 内存超过 512 MiB | 分配前失败，details 含 estimated/limit；不得等 OOM 后再分类 |
| ADV-012 | sentinel secret 在环境中 | stdout/stderr/JUnit/benchmark JSON 均不得包含 sentinel 值 |

并发测试使用 `threading.Barrier`/`Event` 同步，不用 `sleep()` 猜时序。同一 runtime 的 inference fake 必须观测到 `max_active_count==1`；两个不同 runtime 可观测到 2。初始化失败在同一 runtime 内只尝试一次，16 个等待者获得同一 code/details；新 runtime 才允许重新尝试。全局状态/并发 suite 使用 `-n 0` 独立运行。

### 7.11 打包、CI 与发布

| ID | 操作 | 精确断言 |
|---|---|---|
| PKG-001 | Python 3.10/3.11 `uv sync --frozen` | lock 无变更；安装成功；`pip check` 通过 |
| PKG-002 | build wheel + sdist | 构建成功；不包含 checkpoint/demo/训练代码 |
| PKG-003 | 临时 venv 安装 wheel | `import t2l` 和 `ai-auto-lrc --help` 成功 |
| PKG-004 | 仓库外 CWD 运行 wheel | 无 CWD import/path 依赖 |
| PKG-005 | wheel 无 vocals extra | 默认推理不 import Demucs；显式启用给稳定错误 |
| PKG-006 | dependency boundary scan | domain/application 禁止导入外部推理库和文件 sink |
| PKG-007 | LFS/manifest check | pointer、缺文件、hash mismatch 任一使 asset job 失败 |
| PKG-008 | 文档命令 smoke | README 中每条受支持命令在 temp dir 实际执行 |
| PKG-009 | license inventory | root、MTL 来源、pykakasi 和资产许可条目均存在 |
| PKG-010 | source tree scan | X01–X03、train/eval 不进入 wheel 或公共命名空间 |
| PKG-011 | wheel metadata | 项目 wheel 为 `py3-none-any`；`Requires-Python >=3.10,<3.12`；extras 精确 |
| PKG-012 | 本地 wheelhouse 离线安装 | Linux x86_64 与 macOS arm64 支持矩阵脱离源码树安装；`pip check` 为 0 |

`fasttext-wheel` 候选替换必须用同一 LID hash 和代表性的中文、日文、韩文、英文、俄文、低置信文本做组件测试：top-1 label 完全相等，概率绝对误差不超过 `1e-6`，公开 `fasttext` import/API 不变。若不满足，不能为消除编译依赖而静默切换。

覆盖率是补充门禁，不替代真实集成证据：新增/修改行 diff coverage 至少 90%；CLI 输出、strict/partial、资产校验、原子写、optional dependency 错误达到 100% branch coverage；RC 前 v2 代码整体 line coverage 至少 80%。LegacyV1 遗留模型不要求一次性补到 80%，但所有触及行必须有直接合同或 oracle。

## 8. Fixture、fake 与 golden 生命周期

### 8.1 分类

| 类型 | 用途 | 是否允许更新 |
|---|---|---|
| pure fixture | 小矩阵、歌词行、值对象；进入 Git | 行为合同变化并经评审后 |
| fake port | 验证编排、异常和调用次数；进入测试代码 | 接口变化时同步 |
| generated audio | 测试时生成 deterministic WAV | 生成算法变化需评审 |
| static codec fixture | 极短 MP3/WAV，验证真实 decoder | 必须有来源、生成命令、hash |
| numeric fingerprint | Mel/posterior 摘要和 state keys | 只能由显式模型/profile 变更更新 |
| offline golden | 授权音频/歌词、frames、LRC | 走受控再生流程，不可直接手改 |
| qualification corpus | 五语人工真值和质量指标 | 数据版本升级时单独评审 |

当前 static codec fixture 为项目自行合成的 440 Hz 正弦波，不含第三方录音或作品。二进制文件与可重现命令、ffmpeg 版本、SHA-256、便携断言和当前宿主观测分别位于 `tests/fixtures/audio/sine-440hz-250ms-mono-22050.mp3` 和同名 JSON；`AUD-004` 只证明显式 torchaudio policy 的真实 codec 解码与无 librosa fallback，不把跨平台 MP3 PCM bytes 声明为 exact golden。

### 8.2 golden manifest 必填字段

```text
case_id
schema_version
generated_from_commit
python_version
lockfile_sha256
platform/cpu
seed
audio_sha256 / lyrics_sha256
asset_manifest_sha256
decoder / channel_policy / separation
model_name / architecture_id / checkpoint_sha256
feature_spec_id / phone_inventory_id / frame_clock
tokens / phones / word_spans / line_spans
posterior_shape / posterior_fingerprint
word_frame_spans / line_frame_spans
line_lrc_sha256 / word_lrc_sha256
rights_source / allowed_uses
```

### 8.3 生成与更新流程

1. 在 canonical CPython 3.10 锁定环境中断网运行；不得用当前宿主 torchaudio 2.11 临时结果生成 oracle。
2. 校验输入、checkpoint、LID 和 lockfile hash。
3. 固定 CPU、seed 0，连续运行 3 次；frames 和 LRC 必须一致。
4. 将候选 golden 与旧 oracle 做结构化 diff，说明每个变化属于合同变化、模型变化还是环境漂移。
5. 由维护者批准后，用专用脚本整体再生；禁止直接编辑 JSON/LRC expected 文件。
6. PR 保存再生命令、环境摘要和 diff artifact。

现有 demo 已获用户授权作为 v2 golden 来源，但原 MP3 约 325.868 秒，不适合作为每个 PR 的快速用例。R2 应从它派生一个 30–60 秒、歌词边界明确的短案例，同时在 manifest 中记录原文件 hash、裁剪区间、生成命令和授权继承；完整 demo 放入 nightly/RC。

首个正式 oracle 环境固定为 CPython 3.10、Linux x86_64 CPU、float32、`torch.set_num_threads(1)`、`OMP_NUM_THREADS=1`、`MKL_NUM_THREADS=1` 和 seed 0。Python 3.11、macOS 与其他 CPU 只运行 portability suite，不能自动覆盖 canonical oracle。

## 9. 性能与资源门禁

### 9.1 测量方法

- 固定 CPU runner、固定频率策略和同一锁文件；不得跨机器直接比较绝对数值。
- 每个 case 先 warmup 1 次，再运行至少 5 次取 median；同时保存 P90。
- 分开记录 import、冷启动/模型加载、特征、声学推理、alignment、render、端到端 RTF 和 peak RSS。
- 基线与候选在同一 job 依次运行，顺序交替，减少系统漂移。

### 9.2 门槛

- 30 秒 warm CPU 推理 median：`new <= max(baseline * 1.10, baseline + 0.25s)`。
- alignment 单阶段 median：`new <= max(baseline * 1.10, baseline + 0.10s)`。
- peak RSS：`new <= max(baseline * 1.10, baseline + 64 MiB)`。
- 连续 20 次短请求：RSS 线性斜率不超过 2 MiB/次，GC 后末值不超过稳定起始值 64 MiB。
- PR 共享 runner 只做 smoke 和报告；固定 performance runner/nightly 才做硬门禁。
- 连续两次独立 job 越线才判定性能回归；单次越线最多自动重跑一次并保留两份数据，不能无限重跑至绿色。
- 若未来 optimized DTW 转默认，必须同时满足：所有 tie-heavy/随机合法矩阵和真实 golden frame spans 100% 一致、score `rtol=1e-6, atol=1e-6`、代表性长输入 median 至少快 2 倍、peak DP memory 不高于 reference 的 60%。
- 不把双向 LSTM 分块/流式推理当透明优化；它改变全局上下文，需新 profile 和质量评测。

## 10. CI 分层与证据留存

### 10.1 PR fast（每个 PR，目标 5 分钟内）

- Python 3.10/3.11：unit + contract；
- import boundary、compile、lock freshness、wheel metadata；
- 默认断网；无 LFS 大资产；
- 现有 30 个 characterization 继续通过。

### 10.2 PR asset（触及 C05–C08、manifest 或 lock 时 required）

- 下载/恢复步骤先校验 LFS 和 manifest；随后切断网络；
- checkpoint strict load、numeric fingerprint、短 WAV/MP3、offline golden；
- Linux CPU canonical 环境；结果上传 manifest 和结构化 diff。

### 10.3 nightly

- 完整 demo、五语资格集、真实 Demucs cached weights、长输入 DTW；
- 固定 runner 性能/RSS；
- 可用时 CUDA 单独报告，不与 CPU 证据混写。

### 10.4 RC

- Linux 与 macOS clean install；Python 3.10/3.11；
- wheel/console/CWD/断网/asset missing/partial/atomic write；
- 许可证、来源、迁移指南和质量/性能报告归档。

所有门禁输出至少保存：提交 SHA、job id、Python/OS、lock hash、asset manifest hash、测试选择、通过/失败/skip 数、golden diff 和性能 JSON。skip 必须列原因；没有 runner 不等于已验证。

PR artifact 保存 90 天，main/nightly 保存 365 天，RC/release 证据随 release 长期保存。release 还应保留 wheel SHA-256、wheel 内容清单、SBOM、许可证清单和 provenance attestation。安全/许可证例外必须记录版本、原因、责任人和到期日，默认最长 30 天。

## 11. 能力—里程碑—测试追踪

| 能力 | 主要里程碑 | Required 测试组 |
|---|---|---|
| C01 CLI | R3、R6、R7b | CLI-001..028、OUT-001..009、GOL-008..010、PKG-003..005 |
| C02 Python API | R3 | API-001..015 |
| C03 编码读取 | R4、R6 | ENC-001..006、CLI-008、016 |
| C04 歌词清理 | R2、R4 | TXT-001..007、015..016 |
| C05 语言/G2P | R2、R4 | TXT-008..020、GOL-004..005 |
| C06 音频/Demucs | R5 | AUD-001..014、GOL-006..007 |
| C07 模型推理 | R2、R5 | AST-006..013、NUM-001..014 |
| C08 DTW/BDR/LRC | R2、R6 | ALN-001..021、GOL-001..003、GOL-011..014 |
| C09 标准 LRC | R6 | ALN-014..018、CLI-001..002 |
| C10 错误诊断 | R3、R6 | API-009..010、CLI-004..012、OUT-003..007、ADV-004..005、012 |

## 12. 评审分歧与最终取舍

### 12.1 partial 退出码

候选方案一是“显式允许即 code 0”，优点是 shell 流水线不把它当失败；缺点是自动化无法区分完整与不完整。最终采用 code 3，因为“不完整”会改变结果可信度，必须进入机器可读状态。stdout/file 仍可产出，调用方可显式接受 0 或 3。

### 12.2 是否保留 v1 shim

保留一个小版本有迁移便利，但 v1 的默认 Demucs、五元 tuple、输出目录和宽松截断与 v2 合同冲突，shim 很容易形成伪兼容。用户已决定旧仓库单独保留，因此 v2 不发布 shim；只保留 characterization、oracle 和迁移表。

### 12.3 decoder fallback

自动 torchaudio -> librosa 回退提高“能打开”的概率，但 stereo 会变 mono，且错误类型/依赖环境会改变数值输入。最终采用显式 policy；默认 torchaudio 失败即阶段化错误，用户明确选择 `librosa-mono` 才改变行为。

### 12.4 是否在重构中优化 DTW

先保持 reference backend。只有 profiling 证明瓶颈，且 optimized backend 满足第 9.2 节的路径、score、速度和内存门槛后，才能单独切换。架构重排、数值变化和性能优化不得混入同一 PR。

## 13. 明确延期

- 修复第 2、3 层 LSTM 的 `batch_first`；
- 新 checkpoint、采样率、Mel、phone inventory 或 UNK 类；
- token 级混合语言识别和原生多语言 G2P；
- 默认声道平均或 torchaudio/librosa 波形统一；
- 流式/分块 BiLSTM 推理；
- GPU 数值等价承诺；
- 把 Demucs 效果、BDR 收益或五语质量提升当作重构成果；
- 恢复训练/旧评估链路；
- 微服务、动态插件注册中心、DI 框架和全仓一次性 strict typing。

## 14. 每个实施 PR 的模板

每个 PR 必须回答：

1. 本 PR 改变哪个合同，明确不改变哪些合同？
2. 对应能力 ID、测试 ID 和里程碑是什么？
3. 是否触及 LegacyV1 数值协议、asset manifest、lockfile 或 golden？
4. 执行了哪些 fast/asset/nightly 测试，哪些未执行，原因是什么？
5. stdout/stderr、strict/partial、离线和 CWD 是否受影响？
6. 如何独立 revert？回滚是否需要恢复 lock、manifest 或资产？
7. 文档、迁移表和证据 artifact 是否同步？

禁止通过放宽容差、更新 golden、开启 `allow_partial` 或切换 decoder 来掩盖回归。任何预期的数值变化都必须独立成模型/profile 变更，并由维护者批准。

## 15. 当前实施快照与恢复入口

本节是可更新的执行快照；第 1–14 节仍是规范性设计和门禁。更新本节时必须保留日期、命令、环境和失败原因，不能只改一个“通过数”。

### 15.1 已落地但尚未构成 RC 证明的内容

- v2 公共合同、稳定错误层、四个粗粒度 port、应用用例、composition root 和顶层 API 已存在；
- 歌词/编码、音频、资产、LegacyV1 推理、LRC renderer、CLI、原子输出 adapter 已存在；
- 三个 checkpoint 的 hash、size、38-key 结构签名、LegacyV1 特征参数和 LSTM 轴语义已进入 manifest；
- manifest 已显式绑定 distribution `ai-auto-lrc`、package version `2.0.0a0`、profile `legacy-v1` 与 profile contract version `1`；`AST-019` 证明任何绑定不兼容都会在 LID materialization、模型 adapter 与 checkpoint/runtime asset 加载前，以 `T2L_ASSET_MANIFEST_INVALID`/`asset_resolution` 失败关闭；
- LID 与两个 NLTK runtime asset 的 path/hash/size/source/license 已进入两份 manifest；`OfflineG2PProvider` 已通过 composition 中的惰性 callback 接入同一 `AssetLocator`，LID `AssetSpec` 也由 profile manifest 构造，不再维护 composition 硬编码副本；
- runtime 已显式拒绝 `offline=False`；manifest 不兼容稳定映射为 `T2L_ASSET_MANIFEST_INVALID`/`asset_resolution`/CLI exit 6，冻结 alignment 输入错误映射为 `T2L_ALIGNMENT_INVALID`/exit 7，未知 `IndexError` 不被误分类为 partial；
- `t2l.errors` 已建立只读错误注册表：46 个稳定 code 统一绑定异常类型、stage、必填 details、cause policy、CLI exit code 与安全消息策略；生产代码 AST 扫描拒绝未登记 `T2L_*`，未登记或类型/stage 漂移在 CLI 边界 fail closed；
- diagnostics 已按 lyrics -> inference -> policy 汇合并按值去重；CLI `--verbose` 阶段、partial 计数和 `--debug` traceback 消毒已有定向测试；
- `ProgressEvent`、`ProgressObserverPort` 与 `NullProgressObserver` 已落地：Python API 显式使用 Null observer，alignment 事件由 application use case 发出，CLI 只把稳定事件序列化到 stderr；
- CLI 已关闭本轮 signal/broken-pipe/locale/version 与输出类型安全：replace 前 SIGINT=130、closed pipe=141、UTF-8 不依赖 locale、installed `--version` 对齐 metadata，directory/FIFO/device/symlink path fail closed，新建和覆盖目标 mode 明确为 `0600`；
- checkpoint 现在一次读取不可变 bytes snapshot，在同一 snapshot 上执行 LFS/hash/size 校验并用 `BytesIO` 交给 `torch.load`；`AST-016` 已反证校验后路径替换与原地覆盖都不能改变被反序列化字节；
- LID 与两个 G2P zip 已改为运行时私有 `MaterializedAssetSet`：每个源文件从同一打开句柄读取，读取前后 FD identity 与当前路径 identity 必须一致，hash/size/LFS 校验只针对同一份 bytes；完整集合验证成功后才发布 0400 文件与 0500 目录，fastText、NLTK/G2P 持有 snapshot owner 覆盖消费生命周期，`AST-020` 已反证 symlink、原子替换、原地覆盖和混版本集合；
- LegacyV1 成功、checkpoint 失败和 alignment memory-limit 失败均已验证不改变调用方 NumPy/Torch 全局 RNG；domain/application AST 边界已禁止反向导入 adapters、Torch、torchaudio、librosa、Demucs、fastText 与 NumPy；
- `PhoneticConverter` 和 `OfflineG2PProvider` 的第三方调用均受 runtime-local `RLock` 保护：同 runtime 串行，不同 runtime 可并行；模型/G2P 首次初始化的缓存、控制流异常清理和 SIGINT 锁等待恢复已由 `CONC-001/004/005` 覆盖，失败不会留下半初始化或 sticky control-flow failure；
- 真实 MP3 已在 Linux x86_64/CPython 3.10 canonical 环境串起 decoder -> 四公开模型路由 -> public Python API -> installed console script -> line/word LRC；CLI 从源码树外 CWD 运行，导入路径固定为 site-packages，系统断网与 socket guard 同时生效，Demucs 未请求也未导入；
- portable coverage 门禁已通过 `scripts/run_portable_coverage.sh` 固化，只统计源码树 unit/contract/component 并排除冻结 `t2l/mtl`；package 与 canonical 使用各自独立门禁；
- `g2p-en==2.1.0` 的间接 NLTK 版本已显式锁定为 `nltk==3.8.1`，避免 NLTK 3.10.3 对 `_eng` 新资产格式的非兼容要求；
- `pyproject.toml`、`uv.lock`、core/vocals/test 依赖分组和 console script 已建立；
- R7a 的旧 CLI/API、X01–X03、训练/旧评估和多份依赖事实源已删除，冻结的 `t2l/mtl/model.py`/`utils.py` 和许可证保留；R7b 资格门禁仍未完成；
- package harness 已使用 `uv build`、sdist -> wheel、隔离安装、`python -I` 和源码树外 CWD，并排除 checkpoint/demo/旧入口/训练评估模块；`PKG-010` 还验证禁用模块无 import spec、不被 `pkgutil` 枚举且旧名称不进入公共 API；
- `PKG-005` 已证明 installed wheel 的 import、help 和默认真实 MP3 -> LRC pipeline 不导入 Demucs、网络/download 事件为 0；显式 `--separate-vocals` 在缺少 extra 时稳定返回 exit 5/`T2L_VOCALS_DEPENDENCY_MISSING`。它不证明 Demucs 已安装但权重缺失的路径，也不替代冷 wheelhouse 安装；
- Git bundle `AI-auto-lrc-pre-v2-db8e714.bundle` 已通过 `git bundle verify`，其 SHA-256 为 `6b51c9e10c69958ec31b27a2395f36f21fe3f632f691b7bb7777b41d4f4ad30a`；但 bundle 不包含 LFS 实体对象和当前未提交工作区，不能单独称为完整灾难恢复包。

### 15.2 2026-09-04 至 2026-09-05 验证快照

| 验证 | 结果 | 证据边界 |
|---|---|---|
| 环境 | macOS 26.6.2 arm64，CPython 3.11.4，uv 0.12.9 | 属于可移植开发证据；不是 canonical Linux CPython 3.10/CPU oracle |
| `tests/unit tests/contract` | `168 passed, 5 warnings` | 单元、fake、错误 registry、progress/CLI/输出合同、package/profile compatibility、inventory 与文档链接治理门禁；不是安装资格 |
| `tests/component` | `52 passed, 17 warnings` | 包含真实 checkpoint 与 G2P/LID TOCTOU、全局 RNG、runtime-local 并发、SIGINT 恢复、WAV/MP3 codec、离线 G2P、LID manifest 和四模型路由 |
| `tests/package` 宿主默认 | `6 passed, 4 skipped in 20.18s` | wheel/sdist/installed CLI 基础合同通过；4 个 cold wheelhouse gate 因未显式提供当前 wheelhouse 按设计 skip。v8 的 macOS 临时 wheelhouse 已被本轮源码/manifest 变更 supersede，不复用其 9-pass 数字 |
| `tests/golden` 宿主收集 | `13 skipped` | 三份 oracle schema 可读，但 macOS arm64 按设计拒绝冒充 canonical；canonical 结果见下三行 |
| 宿主全量 | `235 passed, 17 skipped, 22 warnings in 32.02s` | macOS arm64、CPython 3.11 portability 结果；13 个 canonical-only golden 与 4 个需显式 wheelhouse 的 package case按设计 skip，不得写成 canonical/cold gate 通过 |
| portable line coverage | `220 passed`；v2 `85.36%`，门槛 `80%` | `scripts/run_portable_coverage.sh` 统计 unit/contract/component，排除冻结 `t2l/mtl`；不替代 package、canonical、diff coverage 或关键分支 100% 要求 |
| 真实离线 G2P | `nltk 3.8.1`; `hello -> HH AH0 L OW1`; download/network 熔断下成功 | 证明当前两个 zip 可被 g2p-en 2.1.0 在空用户 cache 中消费；尚非 Linux 矩阵 |
| Ruff / compileall / lock | `All checks passed`；compileall code 0；`uv lock --check` 解析 88 packages | 静态质量、语法和 lock 无漂移；`uv.lock` SHA-256 `3f20a0afdd3bfa055c7a98c413b305e84aa0a3ad1af2c254b094bb8440cd31eb` |
| `uv build --no-python-downloads` | wheel + sdist 成功；wheel SHA-256 `03726df745e66ae817db22c16b54a91eca6ac822a14a849834bdce41931ddd9a`，sdist SHA-256 `75fd80acee9d43f64ab4a36e976f4297557fe9b4be42e42d33d30c66507e4751` | 本地构建证据；尚未绑定 signed tag/provenance，也未声明 reproducible hash |
| canonical feature oracle | Linux x86_64、CPython 3.10.21、`torch/torchaudio==2.1.2+cpu`、CUDA 无、CPU 单线程；与 numeric/public-e2e 合并 verify 共 `13 passed, 7 warnings in 143.22s` | 资格化 `NUM-001/002` 的 feature-only Mel 与首声道语义；Mel `[1,1,128,87]`，SHA-256 `d2905b77c6f59ad415d2f25aa94454ef81b0ac6c87f555ab8fb0523578fd0b04`；feature oracle SHA-256 `8d2bcbb5bd2593baaf5c947333406c5246ea2e622cb22bff2f39e806cbc1880a` |
| canonical numeric/rendering oracle | 同一 canonical 环境；真实 Baseline、MTL 与 BDR checkpoints；生成器同进程三次一致；完整 verify `13 passed, 7 warnings in 143.22s` | 资格化 `NUM-015/016`：10 个 tensor 抽取点 v1/v2 bitwise exact、`max_abs_diff=0`，四路均 complete，frames 与 line/word LRC exact；numeric oracle SHA-256 `428fe6cb410330448c428fafc3f6785c9547bdcb873b3493c8d32c67f9051352`。旧 numeric 用例继续作为辅助断言，但不再认领 `GOL-011/012` |
| canonical real decoder/API/installed CLI oracle | 同一 canonical 环境；项目生成 MP3；系统 `--network none` 加 socket guard；repo 外 CWD；installed site-packages import；三次候选一致 | 资格化 `GOL-001/002/003/007/008/011/012`；四路 public API 与 installed CLI 字节一致，line/word LRC exact，Demucs 未加载；public-e2e oracle SHA-256 `c6acf7f7ceec656084cadcc69606bdefe05e6fbbbbc1277c03c80238c732e50c` |
| 测试目录 | `unit/contract/component/package/golden`；`component/golden/package` marker 已建立本地收集门禁 | `slow/vocals/cuda/performance` 尚无真实测试，不声明空 marker；仓库尚无 CI workflow，不得把本地门禁写成 CI required |
| 稳定测试 ID | inventory schema v2；文档与 `tests/spec_inventory.json` 共 274 个唯一 ID；80 个 evidence binding，194 个保持 `planned`；80 个 ID 映射到 73 个不同 pytest 节点 | 69 个默认 `implemented-unqualified`；`NUM-001/002`、`NUM-015/016` 与 `GOL-001/002/003/007/008/011/012` 共 11 个为对应 scope 的 `qualified-canonical`；无 `qualified-release` |
| 真实音频 fixture | PCM16 mono/stereo WAV 和项目生成的 440 Hz、250 ms、mono、22050 Hz MP3，MP3 SHA-256 `55bfeaa909966bef5f8c74ab9e01ac13d2b4e8b17d41bf07ccc44536df250ab8` | 已证明默认 torchaudio 解码、声道顺序、44.1 kHz -> 22.05 kHz 重采样和 MP3 不调用 librosa fallback；不等于 canonical audio golden |
| 四公开模型路由 | Baseline、MTL、Baseline_BDR、MTL_BDR 在真实 checkpoint + 真实 decoder MP3 上的 canonical public API 与 installed CLI 测试通过 | `GOL-012` 已在 functional canonical scope 内完成；仍不是 clean release provenance，也不证明 natural partial |
| installed-wheel 真实 CLI | canonical image 内安装当前项目，从仓库外 CWD 执行 console script；atexit 审计导入 `/workspace/.venv/lib/python3.10/site-packages/t2l/__init__.py`，四路输出与 API 字节相等 | `GOL-008/012` functional canonical 通过；该镜像构建阶段仍可联网，不证明空 wheelhouse/`--no-index` 安装，`PKG-012/017/019` 仍未完成 |

Canonical candidate 在容器内连续三次一致，验证运行使用 `--network none --read-only`。numeric oracle 已绑定 feature oracle、profile manifest、`uv.lock`、numeric helper、v2 adapter 和 renderer 的 SHA-256；但 Docker build 阶段仍可联网获取 uv 和依赖，`generated_from_commit` 指向基线提交，候选 v2 adapter 来自当前 dirty worktree。因此它是 canonical functional evidence，不是冷 wheelhouse、clean commit 或 release provenance。

Inventory schema v2 已把“实现证据”与“资格状态”拆开，可表达 `implemented-unqualified`、`qualified-portable`、`qualified-canonical`、`qualified-release`；任何 `qualified-release` 认领都必须携带 release provenance。多 ID 映射一个节点时，必须参数化成独立 JUnit case，或输出可由 CI 验证的稳定 ID property；一个绿色 testcase 不能默认代表多个 ID 均已资格化。

#### 15.2.1 Gate 状态

| Gate | 当前状态 |
|---|---|
| 本机 unit/contract/component/package | Go，portable/local evidence |
| Inventory schema v2 与 marker collection | Go，本地 pytest 门禁；implementation/qualification 已分离 |
| Portable v2 line coverage | Go，`85.36% >= 80%`；diff coverage 与关键分支 100% 仍未自动化 |
| Canonical `NUM-001/002` feature | 功能通过，release provenance 未闭环 |
| Canonical `NUM-015/016` checkpoint numeric/rendering | 功能通过，release provenance 未闭环 |
| Canonical `GOL-001/002/003/007/008/011/012` 真实 decoder/API/installed CLI | 功能通过，release provenance 未闭环 |
| Natural zero-prefix fail-closed `ALN-021` | 已实施 |
| Natural non-empty partial `ALN-019/020/GOL-013` | Deferred/No-go，待产品/算法 ADR |
| macOS arm64 cold sdist build | Go，`PKG-013/014/015/018`；系统断网、空 cache、发布 sdist 与受控 build-system wheelhouse |
| Cold offline wheelhouse install | No-go；58 包离线安装完成后，`pip check` 因上游 Torch 2.1.2 wheel 文件名 arm64、内部 tag x86_64 冲突而失败，`PKG-019` 保持 planned |
| Linux x86_64 + macOS 双平台 wheelhouse | No-go；`PKG-012/017` 保持 planned |
| Git/LFS/dirty-state 独立恢复 | No-go |
| Release | No-go |

当前总判定：**Implementation in progress；Release No-go**。未执行 Git 历史重建、发布、force-push 或任何不可逆切换。

### 15.3 下一批工作顺序

1. 保持第 16 节数据/port/错误/runtime 合同冻结；只有在用户明确批准创建 `docs/adr/` 后，才展示草案并逐项写入 ADR，首批覆盖 G2P 资产、NLTK pin 和 partial 语义；
2. 保持 274-ID inventory schema v2 与源码 evidence 双向一致；当前 80 个 ID 已绑定 73 个独立 pytest 节点，69 个为 `implemented-unqualified`、11 个为 `qualified-canonical`、194 个保持 `planned`，无 `qualified-release`；
3. 将 natural non-empty partial 视为产品/算法决策，而非已知 LegacyV1 修复：冻结 reference DTW/BDR 只产生完整终态或零前缀回溯耗尽；若仍要 code 3，先批准新 confidence/cutoff 语义、oracle 和迁移影响；
4. 保持已完成的 decoder -> public API -> installed CLI canonical golden；后续任何触及 audio/lyrics/model/profile/CLI 的改动都必须重生三份候选、保持单进程三次一致并完整运行 13 项 canonical verify，不得只更新 hash；
5. 保持已完成的 `CONC-001/004/005` runtime-local 锁、一次初始化、RNG 与 SIGINT 恢复语义；下一步由产品/架构先批准 `max_audio_samples`、`max_posterior_cells`、`max_phone_count`，再实现 `RES-003/004/005`，不得用现有一帧 alignment 下界冒充完整资源合同；
6. 对 Torch 2.1.2 macOS arm64 wheel 内外 tag 冲突做独立 ADR：选项只有取得一致的受信制品、可审计地重建/重签制品，或升级 Torch 并重跑全部 canonical；不得修改下载 wheel 元数据、降级检查器或跳过 `pip check`。Linux builder 已修复 release-source staging 与 `uv export --emit-index-url`，但必须重新完成真实 Linux x86_64 下载、冷安装、`pip check`、import/CLI smoke；双平台证据完成前不得晋级 release qualification；
7. 保持已完成的 CLI、checkpoint/G2P/LID TOCTOU、第三方调用期并发安全与 canonical 回归；继续完成 Demucs 本地权重 manifest、多 runtime 资源释放、完整资源预算、diff coverage 和 required marker 零 skip；
8. 完成 Git+LFS+dirty-state 独立恢复、迁移、staging 发布和上一版本回滚演练后，才允许进入 RC Go 评审。

## 16. Teams 第三轮架构合同增量

### 16.1 文档生命周期

三类事实必须分开维护：

| 文档 | 性质 | 更新规则 |
|---|---|---|
| `AI_REFACTOR_HANDOFF.zh-CN.md` | 冻结的 `legacy-v1` 历史事实快照 | 只允许勘误或增加勘误记录，不用 v2 现状覆盖其能力/测试数字 |
| 本执行计划 | v2 目标合同、执行顺序、测试规格和当前快照 | 合同变化先更新 ADR/本计划，再实现；快照必须带日期和证据 |
| `BASELINE_PROVENANCE.md` 与 release evidence manifest | 恢复、来源、hash 和发布证据 | 追加式维护；禁止静默替换已有 hash 或授权状态 |

授权状态必须拆成 `authorized_for_internal_test_generation` 与 `redistribution_rights_verified`。前者为真只允许受控本地/CI 使用；后者未验证时，原始或派生 fixture 均不得进入公开 wheel、sdist 或 release artifact。

### 16.2 C01–C10 实现责任矩阵

| 能力 | v2 主入口/所有者 | 关键数据与端口 | 允许副作用 | 主要失败/回滚单元 | 完成判定 |
|---|---|---|---|---|---|
| C01 CLI | `t2l.adapters.cli` | `AlignmentRequest`、顶层 API、atomic sink | 读歌词文件；stdout XOR 输出文件；stderr 诊断 | 参数/输入/输出错误；回滚 CLI adapter 与文档 | 安装后子进程、退出码、UTF-8、signal、输入防覆盖全部通过 |
| C02 Python API | `t2l.api`、`AlignLyricsUseCase` | request/result、四个业务 port | 可经 runtime 只读音频/资产；禁止写文件、打印、联网 | 稳定 `T2LError` 或原样未知异常；回滚 API/use case | 公共签名、静默、完整性和 runtime 隔离合同通过 |
| C03 编码读取 | CLI lyrics file adapter | bytes -> `tuple[str,...]` | 只读歌词文件 | `LyricsInputError`；回滚编码 adapter | BOM/GBK/strict UTF-8/路径/换行 fixtures 通过 |
| C04 歌词清理 | `LyricsPreparationPort` concrete adapter | `LyricsPlan(tokens,payload,diagnostics)` | 无文件/网络副作用 | `LyricsInputError`；回滚歌词 adapter | legacy token/line/span oracle 精确一致 |
| C05 语言/G2P | runtime-scoped phonetic provider | `LyricsPlan.payload` 内部 phone 编码 | 只读本地 LID；默认不得联网 | provider 初始化失败；回滚 provider/资产对 | 五语、脚本优先级、unknown、并发惰性加载通过 |
| C06 音频/Demucs | `AudioPreparationPort` concrete adapter | `AudioBuffer`、decoder/separation policy | 只读音频和显式本地模型 | audio/separation 错误；回滚 decoder/policy | 真实 WAV/MP3、声道、重采样、可选依赖、断网通过 |
| C07 模型推理 | `LegacyV1Inference` | `InferencePort.align -> AlignmentOutcome` | 只读 manifest/checkpoint；占用 CPU/GPU/RAM | asset/model 错误；回滚 code+manifest+lock 成组 | 三 checkpoint、四公开路由、numeric golden 和 mutation 哨兵通过 |
| C08 对齐/BDR/LRC | LegacyV1 adapter 拥有 posterior/smoothing/reference DTW；应用层拥有完整性；renderer 拥有序列化 | `AlignmentOutcome`、`TokenAlignment`、`Timebase` | 无外部 I/O | alignment/partial 错误；回滚 adapter/contract/golden | reference/BDR、natural partial、frame/LRC exact 通过 |
| C09 标准 LRC | `t2l.domain.lrc` | validated spans -> 无尾换行 `str` | 无副作用 | 输入不变量错误；回滚 renderer | v2 直接生成标准 line LRC；不是公开 enhanced→standard 工具 |
| C10 错误诊断 | `t2l.errors` + CLI mapping | code/stage/details/cause/exit code | CLI 仅向 stderr 输出消毒消息 | 回滚 error registry 与 mapping | code 唯一、映射完整、cause 保留、debug 仍不泄密 |

### 16.3 完整数据字典

| 对象 | 精确责任与关键字段 | 可见性/不变量 |
|---|---|---|
| `AlignmentRequest` | `lyrics`、`audio_path`、`timestamp_mode`、`acoustic_model`、`allow_partial`、`vocal_separation` | 公共、冻结；只接受已解码歌词 tuple 和 `Path` |
| `RuntimeConfig` | `asset_root`、`device`、`offline`、`decoder`、`seed`、`max_alignment_bytes` | 公共、冻结；asset root 显式优先且失败关闭；预算为正整数 |
| `VocalSeparationOptions` | `demucs_model`、`demucs_index` | 公共、冻结；未显式构造即关闭 separation |
| `LyricsToken` | `token_index`、`line_index`、`text` | 应用边界值对象；index 非负 |
| `LyricsPlan` | `tokens`、adapter 私有 `payload`、`diagnostics` | 应用边界；token index 必须为从 0 开始的连续序列；phone payload 不成为公共 API |
| `AudioBuffer` | opaque `samples`、`sample_rate`、只读 `metadata` | 应用边界；具体 dtype/rank/finite 由 audio adapter 在构造前验证，contracts 不导入 torch/NumPy |
| `FrameSpan` / `PhoneSpan` | `start`、`end`；phone 可带 `length` | 严格整数且拒绝 bool；非空半开区间；序列单调不重叠 |
| `TokenAlignment` | token/line/text + `FrameSpan` | token 元数据必须和 `LyricsPlan` 同索引项一致 |
| `Timebase` | `sample_rate=22050`、`hop_length=256`、`time_pooling=3`、`frame_offset=0` | 唯一公共时钟名称；`seconds_per_frame=768/22050`；毫秒截断 |
| `AlignmentOutcome` | spans、expected count、diagnostics、profile、timebase | 仅 inference port 输出；不决定 strict/partial，不暴露 posterior tensor |
| `AlignmentResult` | lrc、status、spans、diagnostics、profile、timebase、expected count | 公共、冻结；API LRC 无尾换行；complete 数量相等；partial 见状态机 |
| `Diagnostic` | code、stage、message、不可变 details | 公共、冻结；不携带 secret、完整环境或未消毒路径 |

`Posteriorgram`、Mel、boundary curve 和模型 tensor 都属于 LegacyV1 adapter 内部数据，只能进入受控 golden artifact，不能跨 application port 或进入公共 API。

### 16.4 Port、装配和 side-effect 合同

| Port | 精确签名意图 | concrete 所有权 |
|---|---|---|
| `LyricsPreparationPort.prepare` | decoded lines -> one self-contained `LyricsPlan` | lyrics adapter；不得双返回 `PhoneEncoding` |
| `AudioPreparationPort.prepare` | path + explicit decoder/separation -> `AudioBuffer` | audio adapter；不得静默 decoder fallback |
| `InferencePort.align` | lyrics + audio + model/device/seed/budget -> `AlignmentOutcome` | LegacyV1 adapter；内部拥有 feature、model、smoothing、DTW/BDR |
| `LrcRendererPort.render` | validated lyrics/spans + timestamp mode/timebase -> newline-free `str` | pure domain renderer |
| `ProgressObserverPort` | frozen `ProgressEvent` stable stage event，不携带 tensor/secret | Python API 注入 `NullProgressObserver`；CLI `--verbose` 注入 stderr observer，alignment 事件由 application 发出 |

`t2l.composition` 是唯一默认 concrete wiring 点；application/domain 不得 import adapters、torch、torchaudio、librosa、Demucs 或 fastText。CLI 独占歌词**文件**读取和 LRC 输出写入；Python API 可经 runtime 只读音频、模型和 LID 资产，但不得创建/修改文件、写 stdout/stderr 或访问网络。原子 sink 当前承诺“进程级同文件系统原子替换”，不宣称掉电持久性；若要承诺 durable rename，必须新增父目录 `fsync` 与平台测试。

### 16.5 Runtime 状态机与并发

```text
NEW -> INITIALIZING -> READY
                   -> FAILED(cached code/details/cause summary)
READY -> CLOSED（仅未来需要显式资源释放时启用）
```

- provider 实例、失败 cache、checkpoint model 和 per-runtime lock 只在 runtime 内共享；NLTK module/cache/search path 是受控进程级状态；
- 当前 eager：manifest schema、LID path/size/hash、Mel transform 构造；当前 lazy：fastText model、NLTK zip/G2P、checkpoint/model；相同惰性资源同一 runtime 只初始化一次；
- 同一 runtime 的 LegacyV1 feature/model forward/smoothing 在当前版本串行化；纯 DTW/completeness/renderer 不在该锁内；不同 runtime 的真实可并行范围以并发测试证据为准；
- 初始化失败缓存稳定 code/details 和受控 cause 摘要，所有等待者结果一致；不要求反复抛同一个异常实例；
- 同一 runtime 失败后不自动重试，新 runtime 才允许重试，避免惊群与半初始化状态；
- 锁等待中断后必须释放资源，后续调用不能死锁。

### 16.6 完整性状态机

```text
aligned == expected > 0                       -> complete
0 < aligned < expected + contiguous prefix   -> partial candidate
partial candidate + allow_partial=true        -> partial
partial candidate + allow_partial=false       -> T2L_ALIGNMENT_PARTIAL
aligned == 0                                  -> incomplete failure, never result partial
aligned > expected / gap / duplicate /
disorder / overlap / metadata差异          -> invalid, never partial
```

partial 只表示从 token 0 开始的尾部截断，不能表示中间缺口。`T2L_ALIGNMENT_PARTIAL` 可表示“不完整失败”，但只有 `0 < aligned < expected`、连续前缀且显式 opt-in 才能形成 `status=partial`；`aligned=0` 只是结构化 incomplete failure，CLI code 7，不是 partial result。当前枚举和定向搜索证据表明，冻结的 LegacyV1 DTW/BDR 对合法可达输入强制完整终态，尚未找到自然的“非空连续短前缀”；BDR 可自然进入的回溯耗尽为 `aligned=0`，必须 fail closed。因此 `ALN-019/020`、`CLI-004/022`、`GOL-010/013` 在新语义批准前为 `deferred`；如果产品仍需要可观测的非空 partial，必须用单独 ADR 定义置信度/截断准则、数值 oracle 和迁移语义，不得从零长 span 伪造。

### 16.7 错误注册与可观测性

错误注册表的事实源已由 `t2l.errors` 导出并由合同测试交叉检查。当前 46 个稳定 code 各自唯一映射异常类型、stage、必填 details、cause 策略、CLI exit code、非 debug 安全消息；生产代码 AST 扫描禁止未注册的 `T2L_*` 字符串散落在 adapter。动态构造统一经过 `create_registered_error()`，CLI 消费统一经过 `registration_for()`/`ERROR_REGISTRY`；未注册或类型/stage 不匹配时降级为泛化 `T2L_ERROR`/exit 1，不以字符串启发式继续路由。

| 边界失败 | 目标稳定映射 | 当前差距 |
|---|---|---|
| manifest/package/profile 不兼容 | `T2L_ASSET_MANIFEST_INVALID`，`asset_resolution`，exit 6 | package/profile compatibility binding 已由 `AST-019` 在任何资产或模型加载前关闭；signed release binding `AST-022` 仍待完成 |
| reference 输入校验失败 | `T2L_ALIGNMENT_INVALID`，`alignment`，exit 7 | 已包装冻结 `AlignmentValueError` 并保留 cause；未知 `IndexError` 原样传播 |
| G2P 资产失败 | 对应 `T2L_ASSET_*`，`asset_resolution`，exit 6 | path/size/hash 已稳定，继续保持 factory/import 调用为 0 |
| G2P/FastText/Kakasi backend 初始化失败 | 已知稳定失败必须注册；未登记 backend `Exception` 在 CLI 泛化为安全 internal error | registry 已防止 code/type/stage 漂移；后续仍需为真实调用期并发与多 runtime 释放补门禁 |
| `aligned=0` 回溯耗尽 | `T2L_ALIGNMENT_PARTIAL`，`alignment`，exit 7，零输出 | 已结构化；不得降级为 `status=partial` |

- `KeyboardInterrupt`、`SystemExit`、`GeneratorExit` 不包装；SIGINT CLI 目标为 code 130；
- 未知 `Exception` 在 Python API 原样传播，在 CLI 映射 code 1；
- `--debug` 允许 traceback，但异常消息、路径和环境中的 sentinel secret 仍必须消毒；
- progress 事件只能来自 observer，不能由 adapter 直接 `print()`；
- CLI 非 verbose 只输出 warning/error；verbose 阶段顺序必须稳定，始终不进入 stdout/file。

### 16.8 资产信任、供给与更新

`config > env > dev-root` 是选择优先级，不是失败回退链：显式 root 一旦选择，缺失、权限、hash、schema 或 profile 错误都必须失败关闭。发布 manifest 位于 wheel/sdist 内，并包含 schema version、生成提交、兼容 package/profile、logical name、relative path、size、SHA-256、来源和许可。checkpoint、LID 和所有运行时必需资产都进入信任链；Demucs optional 资产使用独立但同规则的 manifest。

release evidence 必须绑定 `signed tag -> source commit -> wheel/sdist hash -> bundled manifest hash -> external asset hash`。校验与反序列化之间要消除 TOCTOU：使用同一打开的文件、不可变受控副本，或加载前再次比对文件身份和 hash。资产更新按完整集合原子切换，并保留上一组 package/manifest/assets 兼容组合用于回滚。

当前已完成 checkpoint、LID 与 G2P runtime asset 的 manifest path/size/hash 前置校验；`AST-018` 已用真实 LID 文件验证 path/hash/size/source/license/profile 字段一致。Checkpoint 的 `AST-016` 已通过不可变 bytes snapshot 消除“校验路径后再次打开”的竞态，并反证原子替换与原地覆盖。LID 与两个 G2P zip 的 `AST-020` 已通过私有 `MaterializedAssetSet` 消除“校验源路径后由第三方重新打开源路径”的竞态：同一 FD 快照完成 identity、LFS、size、hash 校验，全集合通过后才发布，fastText/OfflineG2PProvider 持有 owner 直到 runtime 生命周期结束。它保证正常进程内旧完整集合、失败关闭或新完整集合，不保证对同 UID 可主动 `chmod`/写入私有目录的恶意本地进程构成 OS 安全边界。

manifest schema 与 package/profile 兼容性绑定 `AST-019` 已关闭：运行时交叉校验已安装 distribution metadata、代码版本、profile ID、profile contract version 与 manifest 声明，并且在 LID materialization、checkpoint/runtime asset 解析和模型 adapter 构造之前失败关闭。仍未关闭的是 signed release 对 package/manifest/assets 的独立绑定 `AST-022`。因此 `AST-016/018/019/020` 只能证明当前 dirty-worktree 的功能与读取一致性，不能扩张为 release provenance 已解决。

### 16.9 离线 G2P 资产接线合同

NLTK 数据实体作为外部 runtime assets，不进入 wheel；wheel 内的 LegacyV1 manifest 锁定两个 zip 的 logical name、relative path、size、SHA-256、source 和 license。开发 checkout 中的同名文件只是受控开发根实体，不是 CWD fallback。

```text
create_runtime
  -> load package manifest schema; eagerly validate LID and build Mel transform
  -> do not open/hash NLTK zip or import g2p-en
  -> create runtime-local OfflineG2PProvider(callback)
first English phone encoding
  -> callback resolves both RuntimeAssetSpec values through the same AssetLocator
  -> validate path/LFS pointer/size/SHA-256 and common nltk_data layout
  -> lock + idempotently register only the verified root
  -> find required resources against that root
  -> import g2p_en.G2p and construct once
  -> cache READY or ordinary Exception within this runtime
```

实现约束：

- `LegacyV1PhoneEncoder` 只依赖 G2P callable，不接触 manifest、NLTK 或文件系统；
- `prepare_resources` 为无参惰性 callback，成功时返回已校验 `nltk_data` 根；它和 G2P factory 在同一 runtime 初始化临界区内执行；
- 进程级 `nltk.data.path` 注册必须加锁、去重且优先放置已校验根；不同路径的实体必须通过同一 package manifest hash，本轮不支持同进程混用不同版本资产集；
- 资产缺失/损坏时不进入 G2P import/factory；Provider 初始化失败只缓存普通 `Exception`，进程中断类 `BaseException` 原样传播且可在同 runtime 再试；
- `g2p-en==2.1.0` 与旧 `averaged_perceptron_tagger.zip` 的可重现组合显式 pin `nltk==3.8.1`；升级 NLTK 或转换 `_eng` 资产必须作为单独 ADR/manifest/golden 变更；
- `create_runtime()` 可以按现有合同校验 LID 路径，但不得 import g2p-en，不得打开、解压或 hash NLTK zip；首次英文 G2P 才允许这些只读操作。

稳定失败映射：

| 失败 | 期望 code/stage | import/factory | 回退 |
|---|---|---:|---:|
| 显式 root 缺少 zip | `T2L_ASSET_NOT_FOUND` / `asset_resolution` | 0 | 禁止 |
| size 不匹配 | `T2L_ASSET_SIZE_MISMATCH` / `asset_resolution` | 0 | 禁止 |
| SHA-256 不匹配 | `T2L_ASSET_HASH_MISMATCH` / `asset_resolution` | 0 | 禁止 |
| manifest 资产布局不共根 | `T2L_G2P_ASSET_LAYOUT_INVALID` / `asset_resolution` | 0 | 禁止 |
| 校验后 NLTK 仍无法查找资产 | `T2L_G2P_ASSET_MISSING` / `lyrics` | 0 | 禁止 |
| 未知 G2P backend 异常 | 未知异常原样传播 | 1 | 无隐式重试 |

本轮 Teams 的角色观点、冲突和执行顺序已保存到 [`team-sessions/team-session-2026-09-04.md`](./team-sessions/team-session-2026-09-04.md)。

## 17. 并行实施、迁移、恢复与发布

### 17.1 Contract freeze 与汇合协议

R3 Go 时生成版本化的 request/result/port/error contract；R4 和 R5 不得各自修改公共签名。若必须改动，先用独立 contract PR 更新 ADR、fake contract suite 和文档，再同时 rebase 两条实现线。R6 开始前必须通过 composition integration gate，证明每个 concrete adapter 满足同一 port contract。

### 17.2 v1 -> v2 迁移矩阵

| v1 行为 | v2 行为 | 迁移动作 |
|---|---|---|
| 旧 CLI 参数和脚本入口 | `ai-auto-lrc` console script | README 逐参数列删除/替代；示例必须在临时目录 smoke |
| 默认 Demucs 开启或隐式行为 | 默认关闭，显式 `--separate-vocals` | 为需要者安装 `vocals` extra 并准备本地权重；断网缺失时失败关闭 |
| 默认增强逐字 LRC | 默认标准 line LRC；word 必须显式选择 | 下游先确认消费格式；不能依赖增强→标准公开工具 |
| 宽松截断 | strict 默认失败；显式 partial code 3 | shell 明确接受 0 或 3，并记录 partial diagnostic |
| v1 五元 tuple / 散参数 `process()` | `AlignmentRequest` / `AlignmentResult` | 改为 request object；读取 status/spans/diagnostics |
| 自动 decoder fallback | 默认 torchaudio；librosa-mono 显式 | 配置中固定 decoder，不按安装环境改变 |
| 源码相对路径/CWD 资产 | config/env/dev-root manifest | 部署显式设置绝对 asset root，并校验 hash |
| 旧仓库 | 冻结提交 `db8e714...` + 恢复包 | 双跑期间只读；失败时 pin 回已知良好版本，不提供 v1 shim |

消费者清单必须列出 owner、当前版本、v2 适配 PR、双跑结果、cutover 日和 rollback 版本；R7b 只有在所有已知消费者为 `migrated/retired/explicitly deferred` 时才能 Go。

### 17.3 里程碑回滚矩阵

| 阶段 | rollback unit | 触发信号 | 必须保留的 artifact | 恢复后验收 |
|---|---|---|---|---|
| R0 | 原 refs + bundle + 独立 LFS/工作区归档 | 新历史无法恢复、资产缺失 | refs/status/remote/LFS OID/hash/secret-scan 清单 | 断网空 cache checkout 基线并跑 legacy 轻测 |
| R1 | `pyproject.toml + uv.lock + wheelhouse` 成组 | clean install/build 失败 | 上一 lock、wheelhouse manifest、构建工具 wheel | 空 cache `--no-index` install、build、`pip check` |
| R2 | golden manifest + fixtures + oracle 生成器 | 未批准数值变化 | 上一 manifest、hash、环境指纹、授权记录 | 重新生成 fingerprint/frame/LRC 一致 |
| R3 | API/contracts/errors/application 一组 | 公共合同或副作用回归 | 合同快照、fake suite、ADR | 公共签名、静默、状态机和错误映射通过 |
| R4 | lyrics/phonetic adapter + LID | token/phone oracle 改变 | LID、文本 golden、provider 版本 | 五语和 legacy token/phone snapshot 一致 |
| R5 | audio/assets/model + manifest | decoder/模型数值/加载门禁回归 | code、lock、manifest、checkpoint 兼容组 | 三个 checkpoint strict load、四个公开模型路由、真实音频、numeric golden |
| R6 | alignment/renderer/CLI/sink | partial、时间戳或文件原子性回归 | reference oracle、CLI contract、上一 wheel | natural partial、LRC bytes、故障注入通过 |
| R7a | 旧入口/范围清理集 | 旧入口或许可证回归 | 删除清单、冻结文件 hash、许可证 | 公开命名空间和 package 内容检查 |
| R7b | 完整已知良好 release 集 | staging/正式发布或消费者回归 | 上一 wheel/sdist/lock/manifest/assets/SBOM/evidence | 断网降级安装和消费者 smoke |

回滚不得删除用户 LRC、共享模型缓存或旧 release；package 与 manifest/assets 必须按兼容矩阵成组切换。

### 17.4 Git 恢复协议

`git bundle` 不包含 LFS 对象、未提交/未跟踪/ignored 文件、reflog、本地 hook 或完整远端配置。执行历史重建前必须：

1. 进入写冻结并保存 `git status --porcelain=v2`、全部 refs/tags、remote、默认分支、submodule、Git/LFS 版本；
2. 对 LFS objects 建独立归档，记录 Git OID、SHA-256、大小和总量；
3. 对 dirty/untracked 内容做受控快照并先 secret scan；
4. 在无原仓库、空 Git/LFS cache、断网临时目录实际恢复；
5. 对恢复的 commit、checkpoint、LID、demo 和测试结果复核；
6. 未得到单独授权不得 force-push 或覆盖受保护旧分支；优先新 remote/新默认分支。

### 17.5 离线构建与发布/撤回

- wheelhouse 分 runtime、vocals、test、build-system 四类，覆盖 setuptools/wheel/backend 及传递依赖；
- 目标平台用空 pip/uv/XDG/HF/Torch/Demucs cache 和系统级断网验证 wheel install、sdist→wheel、`pip check` 与 smoke；
- lock 禁止未批准 VCS、可变 branch URL、无 hash direct URL 和 yanked 包；sdist 白名单记录责任人、原因、平台、再构建命令和到期日；
- release 只从 clean、受保护、签名 tag 构建；version/tag/METADATA/provenance commit 必须一致；
- 先 staging/TestPyPI 类仓库验证，再正式发布；正式制品不可覆盖同版本；
- bad release 顺序：停止推广 -> yank/撤回 -> 恢复上一已知良好组合 -> 必要时发布新 patch；
- release evidence manifest 机器可读地关联 job、tag、commit、wheel、sdist、SBOM、lock、asset/golden/performance hash；required RC 零 skip、零 allowed failure；
- 普通 PR job 不持有上传凭据；release job 最小权限；长期证据不能只依赖会过期的 CI artifact。

## 18. Teams 第三轮新增测试规格

本节在第 7 节 162 条基础规格之上新增 112 条，稳定规格总数为 **274**。新增前缀用于消除评审中的编号冲突：并发使用 `CONC-*`，资源使用 `RES-*`，离线使用 `OFF-*`，属性/变形使用 `PROP-*`，恢复/迁移/发布/文档分别使用 `GIT-*`、`MIG-*`、`REL-*`、`DOC-*`。所有 ID 必须进入 pytest 节点名、docstring 或 `pytest.param(id=...)`，并能在 JUnit 中检索。

### 18.1 Port 与依赖边界

| ID | 精确断言 |
|---|---|
| PORT-001 | 四个业务 port 的签名、关键字参数和返回类型与第 16.4 节一致 |
| PORT-002 | 每个 concrete adapter 通过同一共享 contract suite，不为 fake/real 维护两套合同 |
| PORT-003 | `t2l.composition` 是唯一默认 concrete wiring 点；其他模块不直接实例化跨层依赖 |
| PORT-004 | application/domain 静态扫描不导入 adapters、torch、torchaudio、librosa、Demucs、fastText 或 output sink |
| PORT-005 | lyrics port 只返回自包含 `LyricsPlan`，不暴露第二个 `PhoneEncoding` 返回值 |
| PORT-006 | inference port 只返回 `AlignmentOutcome`，不暴露 v1 tuple、posterior tensor 或裸 score |
| PORT-007 | renderer 只能在完整性校验之后调用；invalid/strict partial 时调用次数为 0 |
| PORT-008 | Null observer 使 API 永远静默；CLI observer 只把稳定阶段事件写入 stderr |

### 18.2 CLI 输出安全补充

| ID | 精确断言 |
|---|---|
| CLI-020 | output 与 lyrics 为同一路径或同一 inode时，code=2/稳定配置错，歌词字节不变 |
| CLI-021 | output 与 audio 为同一路径或同一 inode时，拒绝且音频字节不变 |
| CLI-022 | natural partial + `-o`：code=3、stdout 0 字节、输出文件为完整原子序列化结果 |
| CLI-023 | replace 前 SIGINT：code=130、旧目标保留、无临时文件残留 |
| CLI-024 | stdout consumer 提前关闭：按既定 broken-pipe 语义退出，不输出 traceback 或二次错误 |
| CLI-025 | 新文件 mode 遵守固定 umask；覆盖旧文件是否保留 mode 的策略被精确测试 |
| CLI-026 | directory、FIFO、device、目标 symlink 和 symlink parent 按安全策略拒绝 |
| CLI-027 | `LC_ALL=C` 下 Unicode 歌词/路径仍按 UTF-8 bytes 处理，不依赖终端 locale |
| CLI-028 | `--version` 与安装包 metadata 完全一致，且无源码树导入 |

### 18.3 资产信任链补充

| ID | 精确断言 |
|---|---|
| AST-014 | installed wheel 从源码树外读取包内 manifest，`__file__` 指向隔离安装目录 |
| AST-015 | tag commit、wheel hash、bundled manifest hash 和 provenance subject 四者一致 |
| AST-016 | hash 校验后、反序列化前替换文件必须失败，不能把被替换内容交给 `torch.load` |
| AST-017 | 显式 config root 缺失/损坏时不得回退 env 或 dev-root |
| AST-018 | LID 的 path/hash/size/source/license/profile 字段完整且可验证 |
| AST-019 | manifest schema 或 package/profile 版本不兼容时在加载前失败 |
| AST-020 | 资产集合更新中断后仍只能看到上一组或下一组完整集合，不能混版本 |
| AST-021 | world-writable root、越界 symlink 或非法权限按已锁定策略失败 |
| AST-022 | manifest 与 checkpoint 同时篡改但 release binding 不匹配时独立验证失败 |
| AST-023 | config/env 中相对 asset root 一律拒绝，不能间接恢复 CWD 依赖 |
| AST-024 | package 内 manifest 对两个 NLTK runtime asset 的 logical name/path/hash/size/source/license 完整锁定，开发实体与之一致 |

### 18.4 LegacyV1 数值、四路由与 natural partial

| ID | 前置/动作 | 精确断言 | 层级/风险 |
|---|---|---|---|
| NUM-015 | canonical Linux CPython 3.10/CPU、官方资产、同一非平凡 waveform；冻结 v1 与 v2 同进程运行 | Mel、raw logits、MTL reduction、posterior、boundary 在批准容差内；frames/score/LRC exact | golden，极高 |
| NUM-016 | 固定 waveform 和明确编码规则；抽取 Mel/Baseline posterior/MTL raw+posterior/BDR curve | 固定 shape、dtype、C-contiguous little-endian bytes、SHA-256；三次一致 | golden，极高 |
| NUM-017 | 分别突变 LSTM 轴、MTL 求和轴、首声道、BDR alpha、`strict=False` | 每个错误突变都必须被对应测试捕获；mutation job 不能 allowed-failure | mutation，极高 |
| NUM-018 | 成功、checkpoint 失败、alignment 失败三条路径 | NumPy/torch 调用方全局 RNG 前后逐字节一致 | component，高 |
| ALN-019 | 固定 posterior/phones/spans 让 reference DTW 与 BDR 自然回溯耗尽 | 返回结构化 incomplete 连续前缀；不制造零长 span，不由 renderer 猜测 | unit/component，极高 |
| ALN-020 | 同一 natural incomplete，分别 strict/partial | strict 在 render 前失败；partial 仅接受非空连续前缀，计数和 first gap 精确 | contract，极高 |
| ALN-021 | 单 token、7 帧、全零有限 posterior/boundary 进入冻结 BDR | 回溯耗尽转为 `IncompleteAlignmentError(expected=1, aligned=0, first_gap=0)`，cause 保留 `IndexError`；普通 DTW 的无关 `IndexError` 不得误分类 | component，高 |
| GOL-011 | 授权短音频、Baseline_BDR | tokens/phones/Mel/two curves/frames/line+word LRC 固定，补齐第四公开路由 | golden，极高 |
| GOL-012 | 同一音频/歌词，参数化四个公开模型贯穿 API/CLI | checkpoint 选择正确；BDR 仅两路加载；profile/model 名进入证据 | golden/e2e，极高 |
| GOL-013 | 可自然产生 incomplete 的真实后端 fixture，连续运行三次 | incomplete 位置稳定；strict 零输出/code7；partial 字节稳定/code3 | golden/e2e，高 |
| GOL-014 | mono 与左右不同 stereo，四模型 | stereo 结果等于左声道 mono，不等于右/均值；frames exact | golden，极高 |

numeric golden manifest 额外固定 tensor 抽取点、dtype/layout/endianness、序列化算法、SHA-256、exact/rtol/atol 字段、允许的 torch/torchaudio patch 范围和再生审批。只有 posterior 可使用容差；phone、frame pairs 和 LRC 始终 exact。

### 18.5 并发与资源预算

| ID | 前置/动作 | 精确断言 |
|---|---|---|
| CONC-001 | Barrier 同时释放 16 线程，混合四模型首次请求 | 每种资源最多初始化一次；相同请求结果一致；无 deadlock |
| CONC-002 | Event 阻塞 fake forward；同 runtime 与不同 runtime 两组调用 | 同 runtime `max_active=1`；不同 runtime `max_active=2`；不使用 sleep 猜时序 |
| CONC-003 | 第一次初始化确定失败，16 等待者；随后同 runtime 再调和新 runtime 调用 | 旧 runtime loader 总调用数 1，等待者 code/details 一致；新 runtime 才能重试成功 |
| CONC-004 | seed 0/1 多轮交错推理并快照全局 RNG | 同 seed 稳定；不同 seed 只影响 smoothing；全局 RNG 不变 |
| CONC-005 | 锁等待者被 SIGINT/异常中断 | 锁释放、无半初始化缓存、后续调用成功且不永久阻塞 |
| RES-001 | 预算分别设为 `estimated` 和 `estimated-1` | 前者允许；后者在 DP allocator 前失败并报告 estimated/limit |
| RES-002 | 用极大虚拟 shape/phone count 做估算，不实际分配 | 无整数溢出、负数或 wraparound；模型/DP allocator 调用为 0 |
| RES-003 | 极长歌词 + 极短音频 | 在昂贵推理/DP 前拒绝，allocation spy 为 0 |
| RES-004 | 固定 runner、warmup 后 20 次短音频推理 | 输出阶段耗时/RSS JSON，带 commit/lock/asset hash，并满足第 9 节门槛 |
| RES-005 | decoder 声明超大 samples/duration 或畸形 header | materialize 大 tensor 前失败，稳定资源错误而不是依赖 OOM |

`max_alignment_bytes` 仅覆盖 alignment DP 时，必须另行定义 `max_audio_samples`、`max_posterior_cells` 和 `max_phone_count`；未定义这些限制前，RES-003/005 为 RC No-go。

### 18.6 离线与属性/变形测试

| ID | 精确断言 |
|---|---|
| OFF-001 | 清空全部相关 cache 并启用 suite 级网络熔断；任何 DNS/socket/urllib/torch.hub/子进程网络尝试立即失败并给调用栈 |
| OFF-002 | offline=true 且 Demucs/模型缓存缺失：默认路径绝不加载 Demucs；显式 separation 立即稳定失败，无下载重试 |
| OFF-003 | 本地 wheelhouse、空 venv、`--no-index`：支持矩阵 install + `pip check` + core smoke 全通过 |
| OFF-004 | `create_runtime()` 只组装 provider：不 import g2p-en，不打开、解压或读取 NLTK zip 内容 |
| OFF-005 | 临时 HOME/XDG/NLTK cache + socket/download 熔断 + 已校验外部 zip：首次真实 G2P 成功且网络尝试为 0 |
| PROP-001 | Hypothesis 生成 spans：合法半开区间保持单调；bool/float/重叠/越界总在 DP 前拒绝 |
| PROP-002 | 1,000 个固定 seed 小 posterior 对独立朴素 DTW oracle：frames exact、score 在 `1e-6` 内 |
| PROP-003 | 每帧所有 class 同加常数：路径不变，score 只发生可计算平移 |
| PROP-004 | 41 类后追加有限无关类：已有 phone/blank 路径与 score 不变 |
| PROP-005 | BDR log-curve 全零：BDR 与普通 DTW 的 frames/score exact 相等 |
| PROP-006 | 任意改变 stereo 右声道：LegacyV1 Mel/posterior/frames 全部不变 |
| PROP-007 | 任意置换 MTL 的 47 melody 维：归约后的 41 类 posterior 不变 |
| PROP-008 | 合法 frames 全部平移 k：token 顺序不变，时间戳按 `k*768/22050` 平移并保持截断/单调 |
| PROP-009 | 逐字段突变 manifest identity/path/hash/profile：全部 fail closed 且 `torch.load` 为 0 次 |
| PROP-010 | checkpoint 首/中/尾随机翻转一 byte：hash 门禁失败，模型构造/反序列化为 0 次 |

### 18.7 打包、恢复、迁移、发布和文档

| ID | 精确断言 |
|---|---|
| PKG-013 | 空 cache、`--no-index`、build isolation 使用受控 wheelhouse 成功 |
| PKG-014 | 从发布 sdist 离线构建 wheel，而不是从源码 checkout 构建 |
| PKG-015 | setuptools/wheel/build backend 及传递依赖全部来自 wheelhouse |
| PKG-016 | lock 无未批准 VCS、可变 direct URL、缺 hash来源或 yanked dependency |
| PKG-017 | Linux/macOS wheelhouse 文件 tag 与目标 interpreter/ABI/platform 兼容 |
| PKG-018 | 未批准 sdist 数为 0；白名单项 owner/reason/expiry/rebuild command 完整 |
| PKG-019 | 空 HOME/XDG/HF/Torch/Demucs cache 且系统级断网时 core install/test 成功 |
| PKG-020 | requirements/Pipfile 不再是安装入口或依赖事实源，并有 CI 漂移扫描 |
| PKG-021 | wheel-from-tree 与 wheel-from-sdist 的 metadata、package files、manifest hash 和 entry point 等价 |
| PKG-022 | 重复构建内容清单一致；若声明 reproducible build，则制品 hash 也一致 |
| PKG-023 | `python -I`、空 `PYTHONPATH`、只读外部 CWD 时模块 `__file__` 位于隔离安装目录 |
| PKG-024 | 恶意 CWD 放同名 `t2l`、checkpoint、manifest 时仍使用已安装 wheel + 显式 asset root；真实短 WAV 结果等于干净 CWD |
| PKG-025 | installed wheel 在源码树外、临时 HOME/cache、socket/download 熔断下，使用外部 asset root 完成真实英文歌词准备 |
| GIT-001 | bundle 的 `--all` refs 与保存清单完全相等 |
| GIT-002 | 断网、空 LFS cache 从 bundle + 独立 LFS 归档恢复三个 checkpoint |
| GIT-003 | 恢复后的 checkpoint/LID/demo hash 与基线完全一致 |
| GIT-004 | dirty/untracked 未盘点时历史重建 gate 必须失败 |
| GIT-005 | 恢复目录可 checkout 基线并运行 legacy 轻量测试 |
| GIT-006 | 新历史切换不改写旧 tag/受保护分支，未授权 force-push 被拒绝 |
| GIT-007 | 恢复包 secret scan 无凭据、token 或私钥 |
| GIT-008 | 恢复说明每条命令在空临时目录实际执行成功 |
| MIG-001 | 每个 v1 CLI 参数在迁移矩阵中有删除/替代/默认变化结论 |
| MIG-002 | CLI/API 迁移示例在隔离临时目录实际执行 |
| MIG-003 | 默认值变化表与 `--help`、dataclass、README 完全一致 |
| MIG-004 | 旧 API/CLI import 明确失败且迁移文档给出替代，不靠 shim |
| MIG-005 | v1/v2 canonical 双跑差异只出现于批准的破坏性变化表 |
| MIG-006 | pin 回上一已知良好 wheel/仓库可断网恢复运行 |
| MIG-007 | 调用脚本明确区分 complete=0、partial=3、strict failure=7 |
| REL-001 | dirty tree、非 tag commit 或 unsigned/unprotected tag 禁止 release |
| REL-002 | tag、项目版本、wheel METADATA 和 provenance source commit 一致 |
| REL-003 | staging 安装、CLI、恶意/只读 CWD、离线 smoke 全通过 |
| REL-004 | wheel/sdist 签名或 attestation 可由独立 verifier 验证 |
| REL-005 | 上一版本 wheel + lock + manifest + assets 可断网恢复 |
| REL-006 | 坏版本演练可 yank/回退且不覆盖同版本制品 |
| REL-007 | package 降级不加载仅兼容新版本的资产 |
| REL-008 | release job 最小上传权限，普通 PR job 无发布凭据 |
| REL-009 | evidence manifest 中每个 artifact hash 可重算且匹配 |
| REL-010 | 独立环境验证 SBOM、provenance、wheel 签名和 tag |
| REL-011 | required RC job 不允许 skip、continue-on-error 或非 canonical 代跑 |
| REL-012 | CI artifact 过期后长期证据仍可读取并校验 |
| REL-013 | SBOM/资产清单覆盖 core、vocals、build tools、checkpoint 和 LID |
| REL-014 | 日志、JUnit、benchmark 和证据包通过 sentinel secret scan |
| DOC-001 | 两份主文档和 ADR 的内部链接、锚点、文件路径全部有效 |
| DOC-002 | README、迁移和恢复文档中的支持命令全部由 CI smoke |
| DOC-003 | CLI/API 默认值、manifest profile 和文档表格自动交叉检查 |
| DOC-004 | 恢复文档在断网空目录完成演练 |
| DOC-005 | 文档不依赖个人绝对路径、短期 CI URL 或敏感信息 |
| DOC-006 | release artifact 包含适用 LICENSE/NOTICE、manifest schema 和恢复索引 |

### 18.8 测试收集和证据规则

- 当前真实声明且有收集项的 marker 只是 `component/golden/package`；`slow/vocals/cuda/performance` 尚无真实测试，不为“配置完整”声明空 marker。CI 在真实 workflow 落地后额外断言各 marker 收集数量，防止资产测试误混 fast suite；
- 只有声称实现计划规格的节点必须携带稳定 ID；辅助回归测试可以不绑 ID，但不得作为资格完成证据。多 ID 测试必须参数化为独立 JUnit case，或通过 JUnit property 输出每个稳定 ID 并由 CI 解析验证；
- golden/e2e 记录 fixture hash、asset manifest hash、Python/OS、torch/torchaudio、decoder backend、seed、提交和 lock hash；
- mutation job至少验证 LSTM 轴、MTL sum axis、首声道、BDR alpha、partial exit code、checkpoint `strict=False` 六类错误变更会失败；
- offline RC 使用系统级网络隔离和冷 cache；monkeypatch socket 只算 fast 级辅助证据；
- `PKG-*` 测试不得依赖 uv 环境预装 pip：要么把构建工具声明为 test/build 依赖，要么直接调用项目选定的 uv/build 工具；测试自己临时补装依赖视为失败；
- required 测试未执行、被 skip、只在非 canonical 环境通过或只由 fake 覆盖时，状态必须是 `not-qualified`，不能写为 pass。

## 19. ADR 与执行任务卡

### 19.1 必须建立的 ADR

| ADR 主题 | 覆盖的锁定决策 |
|---|---|
| 仓库身份与 v1 退役 | 新历史、无公开 shim、旧仓库恢复方式 |
| hexagonal 边界 | coarse port、composition root、数据与 side-effect taxonomy |
| API/CLI/partial | 请求结果、stdout XOR file、退出码 3、完整性状态机 |
| LegacyV1 数值冻结 | profile、LSTM 轴、时钟、MTL reduction、BDR alpha |
| 离线资产安全 | root precedence、manifest trust、hash/LFS/TOCTOU |
| decoder/Demucs | 显式 decoder、Demucs 默认关闭和 optional extra |
| Python/依赖/打包 | `>=3.10,<3.12`、uv lock、wheelhouse、sdist policy |
| 证据与发布 | golden、CI 分层、signed tag、attestation、rollback |

每个 ADR 至少含 `status/date/deciders/context/decision/alternatives/consequences/risks/supersedes`；第 1 节每个锁定决策应链接到 accepted ADR。没有相应 ADR 的重大合同变化不能混入实现 PR。

### 19.2 单任务可执行模板

每张实现任务卡必须能独立交给一个角色执行，并包含：

1. `Task ID / Capability / Milestone / ADR`；
2. 修改和禁止修改的模块；
3. 输入合同、输出合同、side effects 和稳定错误；
4. 前置 artifact/fixture/环境；
5. 先失败的测试 ID，以及通过后的精确断言；
6. required 命令、marker、canonical/portable 环境标签；
7. rollback unit、触发条件、恢复 artifact 和恢复后测试；
8. 未验证项与证据边界；
9. 提交前确认工作区只包含本任务预期文件。

### 19.3 第三轮 Teams 总体 Go/No-go

只有同时满足以下条件才可建议 v2 RC Go：

- C01–C10 的模块、port、数据、错误、测试、ADR 和 rollback 格全部非空或有明确 N/A 理由；
- Git bundle、独立 LFS/dirty-state 归档和断网空 cache 恢复演练闭环；
- canonical numeric golden、四模型路由、natural partial、真实 WAV/MP3、并发和资源门禁闭环；
- clean signed tag 构建，version/tag/wheel/provenance 一致；
- 空 cache、系统断网完成 build、install、core tests，Linux/macOS wheelhouse 都有 hash 清单；
- manifest 绑定 release 并覆盖 checkpoint、LID 和所有必需资产；
- installed wheel 在源码树外、恶意 CWD、只读 CWD 可运行，且输出不能覆盖输入；
- staging、独立签名验证、迁移/恢复文档 smoke 和上一版本回滚演练通过；
- required RC 零 skip、零 allowed failure；来源/许可没有占位结论。

任一项不满足即保持 Release No-go；“测试数量很多”“本机全绿”“checkpoint 能 strict load”或“bundle verify 通过”都不能单独替代上述闭环。

## 20. Teams 第八轮错误合同、资产集合与冷安装收敛

本轮由 API/架构、ML/资产、交付/发布三个方向并行复核，主代理负责统一编号、证据边界和最终串行验收。三条线共享同一原则：稳定合同只由一个事实源生成，文件系统校验与实际消费必须绑定同一不可变内容，安装证明必须来自空缓存和系统级断网，而不是宿主依赖旁路。

### 20.1 API 与错误合同决议

- `t2l.errors.ERROR_REGISTRY` 是 46 个稳定错误码的唯一注册表，条目为 frozen `ErrorRegistration`，注册表本身只读；
- 每项必须声明 exception type、stage、required details、cause policy、CLI exit code 和 safe-message policy；
- producer 通过 `create_registered_error()` 构造动态错误，CLI 通过 registry 解析退出码和消息策略，不再复制字符串分类逻辑；
- AST contract 扫描全部生产 Python，拒绝未登记 `T2L_*`、重复 code、异常类型/stage/required-details 漂移；
- 未登记或类型/stage 不一致的 `T2LError` 必须 fail closed 到 `T2L_ERROR`/exit 1；未知普通 `Exception` 在 CLI 使用泛化安全消息；`KeyboardInterrupt`、`SystemExit`、`GeneratorExit` 保持既定传播/退出语义；
- 对应 implemented evidence 为 `API-009`、`CLI-011`、`CLI-012`。注册表完成不代表所有第三方 backend 都已经拥有细粒度稳定 code，新增 code 仍需先注册、再生产、再消费。

### 20.2 ML、资产与可重复性决议

- `AST-020` 的架构单位不是“逐文件 resolve”，而是运行时私有、不可分割的 `MaterializedAssetSet`；LID 为单成员集合，两个 NLTK zip 为同一双成员集合；
- 每个源文件从同一打开句柄读完，并比较读取前后 `fstat` 及当前路径 `lstat` 的 dev/inode/size/mtime；symlink、读取中原地覆盖和读取后原子替换均失败关闭；
- LFS/size/SHA-256 只校验该句柄读出的同一份 bytes；所有成员校验成功后，才在 private `TemporaryDirectory` 中 exclusive create、flush、fsync、回读核对并发布；
- 发布权限为文件 0400、目录 0500；`PhoneticConverter` 与 `OfflineG2PProvider` 持有 snapshot owner 覆盖 fastText/NLTK 消费生命周期，初始化失败时清理；
- 更新竞态的允许结果只有上一组完整集合、结构化失败或下一组完整集合，禁止新旧混合；这不是同 UID 恶意进程模型下的 OS 隔离承诺；
- `NUM-018` 证明成功、checkpoint 失败和 alignment memory-limit 失败不会改变调用方 NumPy/Torch 全局 RNG；`PKG-006` 以 AST 锁定 domain/application 的依赖方向。

### 20.3 冷 wheelhouse 设计与证据边界

联网准备阶段从冻结 `uv.lock` 导出带 hash 的 core requirements，通过 `pip download --require-hashes` 下载目标平台制品；仅 `distance==0.1.3`、`julius==0.2.7`、`kroman==1.1` 可按有 owner/reason/expiry/rebuild command 的 policy 使用 sdist，并必须使用受控 build-system wheels 离线预构建为 wheel。最终 wheelhouse 只在全部成功后原子发布，并携带 target tag、输入 hash 和每个文件的 size/SHA-256 manifest。

macOS candidate gate 在空 HOME、pip/uv/XDG/HF/Torch/Demucs cache 下，先用 `sandbox-exec` 证明网络连接被拒绝，再从发布 sdist 通过 wheelhouse 离线构建 wheel。最终权威 wheelhouse 为本轮临时验证目录中的 `macos-arm64-py311-final`：目标 CPython 3.11.4/macOS arm64，总大小 172,575,308 bytes；runtime 57 个 wheel/171,577,758 bytes，build-system 2 个 wheel/890,710 bytes，frozen requirements 38,975 bytes，唯一发布 sdist 54,539 bytes；manifest SHA-256 为 `ad95aa6a69dad0c0d4df59032c3cc6105c594405c8a3d74591014b1f6fe0028d`。这些数字用于本轮证据核对，临时目录不是长期 release artifact。

`PKG-013/014/015/018` 已通过：系统网络熔断有效，发布 sdist 使用受控 build-system wheelhouse 离线构建成功，runtime/build-system 最终目录无 sdist，三个例外均有 policy 且预构建为 wheel，manifest 中所有文件的 size/SHA-256 可重算。完整 cold install 未通过：58 个包虽可 `--no-index` 安装，但 `pip check` 与 `uv pip check` 均拒绝上游 `torch-2.1.2-cp311-none-macosx_11_0_arm64.whl`，因为其内部 `WHEEL` 写入 `Tag: cp311-cp311-macosx_11_0_x86_64`。本轮没有修改 wheel 元数据、降级检查器或删除 `pip check`，因此 `PKG-019` 保持 planned/No-go。

即使 macOS arm64 candidate 全绿，`PKG-012/017` 所要求的 Linux x86_64 与 macOS 双平台 wheelhouse/tag/ABI 证据仍未完成，且没有 signed tag、SBOM、attestation 或 release provenance，因此不得产生 `qualified-release`。

### 20.4 本轮测试清单

| 规格 | 层级 | 可执行断言 | 当前证据状态 |
|---|---|---|---|
| `API-009`, `CLI-011`, `CLI-012` | unit/contract | registry 唯一只读；生产错误均登记；unknown/debug/exit 策略由 registry 决定 | implemented-unqualified |
| `AST-020` | unit/component | symlink、路径替换、原地覆盖、更新中断不能让 fastText/G2P 消费混合或未经验证内容 | implemented-unqualified |
| `NUM-018` | component | 三条成功/失败路径前后 NumPy/Torch 全局 RNG state 逐字节相同 | implemented-unqualified |
| `PKG-006` | contract | domain/application 不得导入 adapter 或重依赖 | implemented-unqualified |
| `PKG-018` | package | wheelhouse policy 完整、sdist 全部获批、最终目录只含 wheel、manifest hash 可重算 | implemented-unqualified；最终 gate 通过 |
| `PKG-013/014/015` | package/system | 系统断网、空缓存、发布 sdist、离线 build isolation | implemented-unqualified；最终 gate 通过 |
| `PKG-019` | package/system | 全新 venv 离线安装、`pip check`、依赖 import 与 CLI smoke 全通过 | planned/No-go；上游 Torch wheel 内外 tag 冲突 |
| `PKG-012/017` | package/system | Linux x86_64 与 macOS 双平台冷安装及 wheel tag/ABI 匹配 | planned/No-go |

### 20.5 汇合与退出条件

本轮已完成构建、macOS 网络拒绝 package gate、同一工作树串行总验收和 hash 重算。参数化后的最终证据为：宿主全量 `220 passed, 10 skipped, 19 warnings`；portable coverage `206 passed`、line `84.26%`；canonical `6 passed, 4 warnings`；unit/contract `161 passed`，component `45 passed`，显式最终 wheelhouse 的 package `9 passed`，宿主 golden `6 skipped`。`PKG-013/014/015` 已拆成三个稳定 JUnit case；Ruff、compileall、`uv lock --check`、`uv build --no-python-downloads` 与 `git diff --check` 全部通过。

最终 hash 为：`uv.lock` `3f20a0afdd3bfa055c7a98c413b305e84aa0a3ad1af2c254b094bb8440cd31eb`；profile manifest `b0c0d99ee791b4ba478eb10d531c0dbff904179befc4e8f4915958810db8a684`；feature oracle `86983116b2e9b75a1bf29876eb205cd93c534ae783e22aa80ab207106e8e23c2`；numeric oracle `c9016543e1bf55b51169b0bc2e02cbd84c97760a50fdcdd4fe18f63939cb37a2`；wheel `c0989068b56ec7090a1c65184c4a42e4d01d02f10a633ae774e546be20d4e7fa`；sdist `4da49e28034b9e26aa33330e72d0aab05b4f69a6fe7f0bfee0252f801ee2e670`。

退出结论保持分层：本轮新代码与 macOS cold sdist build 可合入候选，完整 cold install、Linux 双平台、真实 decoder/audio API/CLI golden、natural non-empty partial、恢复、签名与发布仍 No-go。任何后续工作不得以 host-only import、已完成的 58 包安装或 arm64 build 结果替代 `pip check`、cross-platform 或 release 证据。

## 21. Teams 第九轮真实端到端 并发与兼容性执行基线

本节记录 2026-09-05 第九轮 Teams 实施与统一验收结果，是后续继续工作的精确恢复入口。第 20 节保留为第八轮历史快照；当两节数字或状态不一致时，以本节和第 15 节的 v9 快照为当前事实，但不得删除旧快照或把历史失败改写为从未发生。

### 21.1 四角色决议与边界

| 角色 | 主要决议 | 本轮交付 | 明确保留的 No-go |
|---|---|---|---|
| PM | 优先关闭用户可感知的真实输入到真实 CLI 输出，不以 fake 或单独 checkpoint 数值等价代替产品链路 | 项目生成 MP3、四路公开 API、installed CLI、line/word LRC 的 canonical evidence | natural non-empty partial 没有已批准语义；不得自行定义 confidence/cutoff |
| Architect | 先固定 compatibility、runtime ownership、锁粒度和失败顺序，再扩展资源/发布能力 | package/profile compatibility binding；runtime-local lock；控制流异常清理；canonical provenance 依赖链 | `AST-022`、完整资源上限、Demucs 资产和 release provenance 未闭环 |
| Developer | 生产改动必须可由独立 nodeid 证明，并保持冻结模型文件与四路数值协议不变 | 并发/中断增强、alignment 一帧下界预检、wheelhouse builder staging/index 修复、public-e2e harness | 不修改 `t2l/mtl/model.py` 与 `t2l/mtl/utils.py`；不通过更新 checkpoint 解决失败 |
| QA | 证据按 portable、canonical、platform package、release 四层分离；候选生成和资格验证不能混为一项 | inventory 迁移、三份 oracle 三次一致、13 项完整 canonical、宿主全量与 coverage 复验 | Linux/macOS 不能互相代替；dirty-worktree canonical 不能晋级 release |

团队共识：真实 decoder 到 installed CLI 的功能链路已经关闭；下一优先级是完整资源合同和双平台冷安装，而不是继续堆叠 fake happy-path。若没有用户批准的 ADR，不创建 `docs/adr/`，也不改变 partial 或 macOS Torch 制品策略。

### 21.2 本轮能力细化与生产合同

#### 21.2.1 真实 decoder 到公开输出

输入是仓库自行生成、可再分发的 440 Hz、250 ms、mono、22,050 Hz MP3，文件 SHA-256 为 `55bfeaa909966bef5f8c74ab9e01ac13d2b4e8b17d41bf07ccc44536df250ab8`。canonical 环境实际把它解码为 little-endian float32 `[1, 6912]`，waveform SHA-256 为 `7fd29c3be04ae2bda8f86ad5eae90d46235b7e09e19d0d767aaf4f2772be0367`；Mel 为 `[1, 1, 128, 28]`，SHA-256 为 `58e8aff4036d35ec2c1114a55bf8cacd216dfea566cb8df60dc5719871e35be5`。posterior 为 `[9, 41]`，BDR curve 为 `[9]`。

Baseline、MTL、Baseline_BDR、MTL_BDR 四条路由都必须经过 `t2l.process(request, runtime=t2l.create_runtime(config))`，不能直接调用 adapter 冒充 public API。同一份 wheel 安装到 canonical venv 后，console script 必须从仓库外 CWD 执行；`PYTHONPATH` 只能包含 network guard；atexit import audit 必须确认 `t2l` 来自 `/workspace/.venv/lib/python3.10/site-packages/t2l/__init__.py` 且不在 `/workspace/t2l`。四路 CLI stdout 与 API LRC 字节相同，仅在末尾增加一个 LF，stderr 为空。

Baseline_BDR 的固定示例为：line API `[00:00.069]a`，word API `[00:00.069]<00:00.069>a`。Docker 同时使用 `--network none` 和 socket denial guard；manifest 中 `network_attempted=false`；Demucs 的 before/after module 集合均为空，且请求未启用人声分离。

#### 21.2.2 Runtime 并发和资源所有权

`PhoneticConverter` 的 fastText predict 与 Kakasi conversion 连同首次初始化受 runtime-local `RLock` 保护；同一 runtime 的第三方对象不并发进入，不同 runtime 不共享这把锁并允许重叠。`OfflineG2PProvider` 同样用 runtime-local `RLock` 保护初始化和调用，并持有私有 materialized asset owner 覆盖 NLTK/G2P 消费生命周期。

初始化的确定性普通异常继续按 runtime 缓存为 sticky failure；`KeyboardInterrupt`、`SystemExit`、`GeneratorExit` 等控制流异常不能写入 sticky failure。G2P 初始化被中断时必须关闭私有资产集合、删除半初始化引用并允许下一次调用重新初始化。线程等待锁时收到真实 SIGINT，等待者必须退出，holder 最终释放锁，runtime 不得写入 `_models` 或 `_model_failures` 半成品，后续同 runtime 必须能成功加载。

LegacyV1 alignment 现在依据既有 `max_alignment_bytes` 计算一帧内存下界；若一帧也必然超限，必须在 phone span materialization、模型 predict 和 DP allocation 之前拒绝。这个检查只是提前失败优化，不代表完整 `RES-003/005`：`max_audio_samples`、`max_posterior_cells` 和 `max_phone_count` 的阈值与错误 details 仍需产品/架构批准。

#### 21.2.3 Package Profile Manifest 兼容性

`t2l/_version.py` 提供无副作用的代码版本事实源，当前 `PACKAGE_VERSION` 为 `2.0.0a0`；顶层 `t2l.__version__` 与之相同。两份 LegacyV1 manifest 的 compatibility 区块固定：distribution `ai-auto-lrc`、package version `2.0.0a0`、profile ID `legacy-v1`、profile contract version `1`。

运行时必须交叉校验已安装 distribution metadata、当前代码版本、compatibility profile 与顶层 profile、profile contract version。任何一项不兼容都在 feature、checkpoint、LID/G2P runtime asset 解析，以及模型 adapter 构造之前失败，稳定映射为 `CheckpointError`、`T2L_ASSET_MANIFEST_INVALID`、stage `asset_resolution`、CLI exit 6。源码树 fallback 只用于开发导入，不允许覆盖已安装 metadata 的不一致。

#### 21.2.4 Wheelhouse builder

发布 sdist 现在从 staging 的最小 `release-source` snapshot 构建，支持只读 checkout，并避免更新源码树中的 egg-info。`uv export` 使用 `--emit-index-url`，导出结果必须同时包含 PyPI 与 `https://download.pytorch.org/whl/cpu`，否则锁中的 `torch==2.1.2+cpu` 和 `torchaudio==2.1.2+cpu` 无法由 pip 解析。

Linux 第一次真实 `--platform linux/amd64` 尝试已证明环境是 CPython 3.11.9、`x86_64`、首个 tag `cp311-cp311-manylinux_2_36_x86_64`，不是宿主模拟。该次构建在修复前以 exit 1 终止，因为导出未携带 PyTorch CPU index；候选目录为空，没有 cold install、`pip check` 或 CLI smoke 证据。修复只经轻量导出验证，尚未重新下载完整 wheelhouse，因此 `PKG-012/017/019` 保持 planned。

### 21.3 新增与迁移测试绑定

| 规格 | 权威 pytest nodeid | 核心断言 | 当前资格 |
|---|---|---|---|
| `AST-019` | `tests/contract/test_composition.py::test_ast_019_compatibility_fails_before_asset_or_model_loading` | package version 与 profile contract version 两类不兼容均在 LID/model/assets 前失败 | implemented-unqualified |
| `CONC-001` | `tests/component/test_runtime_concurrency.py::test_conc_001_four_routes_initialize_each_runtime_resource_once` | Barrier 同时释放 16 个四路由请求；每种 runtime 资源初始化一次；同路由 tensor 相等；无 deadlock | implemented-unqualified |
| `CONC-004` | `tests/component/test_runtime_concurrency.py::test_conc_004_interleaved_seeds_are_local_and_preserve_global_rng` | seed 0/1 多轮交错；同 seed bitwise 稳定；不同 seed 只影响 smoothing；调用方 RNG 不变 | implemented-unqualified |
| `CONC-005` | `tests/component/test_runtime_concurrency.py::test_conc_005_sigint_interrupts_lock_wait_without_poisoning_runtime` | 真实 SIGINT 中断已确认 acquire 的等待者；无半初始化缓存；后续加载成功 | implemented-unqualified |
| `GOL-001` | `tests/golden/test_legacy_v1_public_e2e_golden.py::test_gol_001_real_mp3_baseline_public_api_is_exact` | 真实 MP3 的 Baseline public API 全链路 exact | qualified-canonical |
| `GOL-002` | `tests/golden/test_legacy_v1_public_e2e_golden.py::test_gol_002_real_mp3_mtl_public_api_is_exact` | 真实 MP3 的 MTL public API 全链路 exact | qualified-canonical |
| `GOL-003` | `tests/golden/test_legacy_v1_public_e2e_golden.py::test_gol_003_real_mp3_mtl_bdr_public_api_is_exact` | 真实 MP3 的 MTL_BDR posterior/boundary/alignment/LRC exact | qualified-canonical |
| `GOL-007` | `tests/golden/test_legacy_v1_public_e2e_golden.py::test_gol_007_real_mp3_decode_is_pinned_and_offline` | encoded bytes、decoder backend、waveform/Mel fingerprint 固定，系统与进程网络熔断 | qualified-canonical |
| `GOL-008` | `tests/golden/test_legacy_v1_public_e2e_golden.py::test_gol_008_installed_cli_is_cwd_independent` | repo 外 CWD、installed site-packages import、stdout 字节不受 CWD 影响 | qualified-canonical |
| `GOL-011` | `tests/golden/test_legacy_v1_public_e2e_golden.py::test_gol_011_real_mp3_baseline_bdr_public_route_is_exact` | 补齐 Baseline_BDR 的真实 public 路由及 line/word LRC | qualified-canonical |
| `GOL-012` | `tests/golden/test_legacy_v1_public_e2e_golden.py::test_gol_012_all_real_public_routes_match_installed_cli` | 四路 API 与 installed CLI exact，CLI 只多一个 LF，Demucs 未加载 | qualified-canonical |

`GOL-011/012` 已从旧 `test_legacy_v1_numeric_golden.py` 迁移。旧 numeric 测试仍保留四路 tensor/frames/rendering 辅助断言，但其 docstring 不再声明这两个稳定 ID，inventory 的 implemented nodeid、qualification scope 和 environment manifest 均指向 public-e2e。

### 21.4 统一验证结果和不可扩张边界

| 验证命令/层级 | v9 结果 | 允许的结论 |
|---|---|---|
| `python -m pytest -q -p no:cacheprovider` | `235 passed, 17 skipped, 22 warnings in 32.02s` | 宿主 portability 全量通过；17 个显式 gate skip 不算资格通过 |
| unit + contract | `168 passed, 5 warnings` | 合同、边界、inventory 和 compatibility 通过 |
| component | `52 passed, 17 warnings` | 本机真实资源、并发、TOCTOU 与模型路由通过 |
| package 默认 | `6 passed, 4 skipped in 20.18s` | 基础 wheel/sdist/installed CLI 通过；当前 cold wheelhouse 未提供 |
| portable coverage | `220 passed`，`85.36% >= 80%` | v2 非冻结代码 line coverage 达门槛；不代表 diff/branch coverage 达标 |
| canonical full verify | `13 passed, 7 warnings in 143.22s` | Linux x86_64/CPython 3.10 CPU functional canonical 通过；不是 clean release provenance |
| Ruff、compileall、`uv lock --check`、`uv build --no-python-downloads`、`git diff --check` | 全部 exit 0 | 静态、语法、锁、本机构建和 diff 格式通过 |

当前 inventory 为 274 个稳定 ID，其中 80 个有实现证据、映射到 73 个不同 pytest nodeid；69 个为 `implemented-unqualified`，11 个为 `qualified-canonical`，194 个保持 planned，0 个为 `qualified-release`。

当前 SHA-256：

- `uv.lock`：`3f20a0afdd3bfa055c7a98c413b305e84aa0a3ad1af2c254b094bb8440cd31eb`
- 两份 LegacyV1 profile manifest：`ec6185216b39ce22236badd4b2587c311710b076f05d83597ba0de1b46424bef`
- feature oracle：`8d2bcbb5bd2593baaf5c947333406c5246ea2e622cb22bff2f39e806cbc1880a`
- numeric oracle：`428fe6cb410330448c428fafc3f6785c9547bdcb873b3493c8d32c67f9051352`
- public-e2e oracle：`c6acf7f7ceec656084cadcc69606bdefe05e6fbbbbc1277c03c80238c732e50c`
- 本地 wheel：`03726df745e66ae817db22c16b54a91eca6ac822a14a849834bdce41931ddd9a`
- 本地 sdist：`75fd80acee9d43f64ab4a36e976f4297557fe9b4be42e42d33d30c66507e4751`

这些 hash 绑定当前 dirty worktree。没有 clean commit、signed tag、SBOM 或 attestation，不得声称 reproducible release；v8 的临时 macOS wheelhouse manifest 和 package 9-pass 结果已被本轮 package/profile/source 变更 supersede，后续必须重建，不能直接沿用。

### 21.5 下一阶段可执行重构包

按以下顺序执行；前一包的退出条件未满足时，不启动依赖它的 release 认领。

1. 完整资源合同：先由 PM/Architect 确认 `max_audio_samples`、`max_phone_count`、`max_posterior_cells` 的默认值、配置入口、稳定错误 details 和迁移策略；再在 decoder metadata、lyrics plan、posterior allocation 与 DP 前分别 fail fast。测试必须用 allocation/model spies 证明昂贵步骤调用数为 0，并完成 `RES-003/004/005`。回滚单元仅包含资源配置、预检和对应测试。
2. Linux x86_64 wheelhouse：使用已修 builder 重新联网准备并原子发布 candidate；随后在 `--network none --read-only`、空 HOME/cache、全新 venv、`PIP_NO_INDEX=1` 下从发布 sdist 构建 wheel，执行 `pip check`、依赖 import、真实 core CLI smoke 和文件 hash 重算。只有全链通过才登记 `PKG-012/017/019`；任何下载或平台 tag 失败都保留失败 artifact，不产生最终目录。
3. macOS Torch 制品决策：经用户批准后建立 ADR，在“上游一致制品”“可审计重建并重签”“升级 Torch 并重跑全部 canonical”中选择；禁止修改下载 wheel 的内部 WHEEL 元数据、降低 pip/uv 检查强度或删除 `pip check`。决策落地后重建 macOS arm64 wheelhouse，与 Linux 共同关闭双平台矩阵。
4. Demucs optional 路径：建立独立权重 manifest、来源/许可、离线权重缺失与 hash 错误、已安装 extra 的真实执行、未安装 extra 的稳定 exit 5、默认路径零 import/零下载。Demucs 通过前只能声称 core 默认关闭可用。
5. 恢复与发布：建立 Git bundle + LFS 实体 + dirty-worktree 独立恢复包，在隔离目录验证 checkout、资产、lock、构建、canonical；完成迁移 smoke、staging、SBOM、attestation、签名绑定、上一版本 rollback drill。只有 `AST-022` 和全部 RC required 零 skip 后，才允许出现首个 `qualified-release`。

### 21.6 后续恢复和验收命令

后续维护者先阅读本节、第 15 节和 `tests/spec_inventory.json`，检查工作树，不得清理用户变更。建议串行执行：

```bash
uv run --frozen --no-sync python -m pytest tests/unit tests/contract -q -p no:cacheprovider
uv run --frozen --no-sync python -m pytest tests/component -q -p no:cacheprovider
uv run --frozen --no-sync python -m pytest tests/package -q -p no:cacheprovider
scripts/run_portable_coverage.sh
scripts/run_canonical_legacy_v1_golden.sh verify
uv run --frozen --no-sync ruff check .
uv run --frozen --no-sync python -m compileall -q t2l tests
uv lock --check
uv build --no-python-downloads
git diff --check
```

若 profile、feature、inference adapter、renderer、audio、lyrics、API、composition 或 CLI 的 provenance 发生变化，先按 `candidate`、`numeric-candidate`、`public-e2e-candidate` 顺序生成候选；每个生成器必须在同一进程三次一致。由维护者审查差异后才能用 patch 更新 manifest，再执行完整 `verify`。禁止通过放宽 hash、删除 import audit、使用宿主 `.pth`、允许网络或缩小到单路测试来恢复绿色。

### 21.7 第九轮 Gate 判定（已由第 22 节取代）

下表保留第九轮当时的判断，仅用于解释后续增量；当前状态必须读取第 22.2 节实测和第 22.4 节 Gate，不得继续引用本表中的 Linux 候选状态作为最新结论。

| Gate | 判定 |
|---|---|
| 真实 decoder -> public API -> installed CLI canonical | Go，functional canonical；非 release |
| runtime-local 并发、RNG、SIGINT 恢复 | Go，portable/component；多 runtime 显式释放仍待补 |
| package/profile compatibility `AST-019` | Go，implemented-unqualified；signed release binding 仍 No-go |
| 完整资源预算 `RES-003/004/005` | No-go，阈值与合同未批准 |
| Linux x86_64 cold wheelhouse `PKG-012/017/019` | No-go，builder 已修但未重跑完整候选 |
| macOS arm64 cold install | No-go，上游 Torch 2.1.2 wheel 内外 tag 冲突，且 v8 candidate 已 supersede |
| natural non-empty partial | Deferred/No-go，待产品/算法 ADR |
| Demucs optional-extra 真实离线能力 | No-go |
| Git/LFS/dirty-state 独立恢复与 `AST-022` | No-go |
| Release | **No-go** |

本轮未创建 ADR，未修改冻结模型文件，未执行 Git 历史重建、commit、push、force-push 或发布。实施状态可以继续推进，但 Release 判定必须保持 No-go。

## 22. Teams 第十轮本地质量门禁与执行方案固化

本轮完整讨论、逐项能力卡、P0–P5 工作包、人类待决策项和测试矩阵见 [`team-sessions/team-session-2026-09-05.md`](./team-sessions/team-session-2026-09-05.md)。本节只保留后续实施必须先看到的门禁事实和恢复入口。

### 22.1 本地门禁事实

- `packaging/quality-gates.toml` 固定 overall line `>= 80%`、changed executable line `>= 90%`；只排除冻结的 `t2l/mtl/model.py` 和 `t2l/mtl/utils.py`。
- CLI 输出、strict/partial、资产校验、原子写、optional dependency error 采用函数级关键目标；14 个目标都要求 line 和 branch 为 `100%`。函数级范围避免把同文件中无关的 Demucs 算法分支错误归入 optional dependency 合同。
- `scripts/verify_quality_gates.py` 从 branch-enabled coverage JSON 计算纯 line 百分比，从 `git diff <base-ref> -- t2l` 加上 untracked Python 计算 diff coverage，并拒绝缺 coverage record 或空 changed executable set。
- portable、package、canonical 各自读取独立 JUnit；required 层零测试、failure/error、skip 或跨层 classname 都失败。三种证据不能复用或互相冒充。
- `scripts/run_test_gate.sh` 是本地统一入口；仓库仍没有 CI workflow，本节不得被引用为托管平台 required check 已配置。
- `MaterializedAssetSet.close()` 已采用 owner-local lock，支持同一 owner 的并发幂等关闭，并保证两个 runtime snapshot 的释放互不干扰；这只是底层所有权安全，不等于已定义 `AlignmentRuntime.close()`。公开 close 仍需先锁定 in-flight 行为、close 后错误、临时 runtime 自动释放、NLTK 全局路径 lease/refcount 与模型/CUDA 释放边界。

### 22.2 2026-09-05 实测

宿主全量回归为 `314 passed, 18 skipped, 22 warnings in 37.85s`。18 个 skip 由 13 个 canonical-only golden 和 5 个未注入 wheelhouse 的 package gate 组成，属于分层选择结果，不是 Release 零 skip 证明。分层回归为：unit + contract `224 passed, 5 warnings`；component `52 passed, 17 warnings`；package 新增 5 个 W2 快照竞态用例，contract 新增 22 个 W1a evidence manifest 用例。

`AI_AUTO_LRC_GATE_ARTIFACT_DIR=/tmp/ai-auto-lrc-w1-portable.Pd78d5 scripts/run_test_gate.sh portable HEAD` 通过：`276 passed, 22 warnings, 0 skipped in 18.63s`。机器可读报告仍为 overall pure line `1726/1975 = 87.392405%`、diff executable line `1696/1868 = 90.792291%`，14 个关键函数 line/branch 全部 `100%`。coverage.py 终端的 branch-aware 综合值为 `84.47%`，不能代替纯 line 指标。

W1a 新增标准库-only 的 `scripts/evidence_manifest.py`，为本地 evidence 提供 `create/verify`：绑定 layer/spec IDs、当前 Git HEAD、tracked diff 与 untracked 内容的组合 hash、宿主 OS/arch/Python/network policy、lock/profile/oracle、JUnit/gate JSON，以及 package wheelhouse manifest/image digest。artifact/input 路径必须是规范相对路径并逐级拒绝 symlink/非普通文件；读取使用同一 FD 并比较前后身份。gate JSON 现在记录输入 JUnit SHA-256 和 quality policy SHA-256，evidence verifier 从 JUnit 重算 pass/fail/error/skip 并交叉核对。

schema v1 明确拒绝自报 `qualified-canonical` 和 `qualified-release`；只有 capture-bound 容器回执与递归 release 闭包落地后才能引入更高 schema。本轮现场 portable manifest 为 diagnostic，路径 `/tmp/ai-auto-lrc-w1-portable.Pd78d5/evidence-manifest.json`，SHA-256 `8299bf756f5298adc0f911355f037a6b6b480046f21e58ff4361340cf560c582`，其 JUnit SHA-256 为 `8c5601a728ae82053e3f037e16edca20e58807292572b688945d83e42358a689`。它证明 schema 在生成当时可重算本地状态，不把事后组装的 manifest 作为受控资格证据。随后文档继续更新，这份历史 manifest 现在会被 current-source 校验以 source mismatch 正确拒绝；它不再匹配当前工作树，只能保留为历史 diagnostic。

W1b 的 capture/retention 架构、状态机、退出码优先级、current-source 与 archived-integrity 双验证模式、三层 artifact closure、28 个候选故障注入测试和分批回滚点已固化在 [`W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md`](./W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md)。该文件是实施方案，不是 W1b 已完成或资格升级的证据。

默认 package 回归为 `29 passed, 5 skipped in 23.50s`；五个 skip 都来自未提供 `AI_AUTO_LRC_WHEELHOUSE` 的 cold wheelhouse 用例，required zero-skip verifier 因而必须失败。默认 package required 继续为 No-go，不能用 29 个通过用例冒充 package qualification。

随后使用冻结 `uv.lock` 在 `python:3.11.9-slim-bookworm` 的真实 `linux/amd64` 容器生成包含当前 C06 源码的 v10 单平台候选，并以 `AI_AUTO_LRC_WHEELHOUSE=/tmp/ai-auto-lrc-linux-v9.NA8l9z/linux-x86_64-py311-v10` 执行完整 `tests/package`：`31 passed, 3 macOS-only skipped in 62.10s`；其中 offline wheelhouse 文件为 `22 passed, 3 macOS-only skipped in 36.50s`。验证容器使用 `--network none --read-only`、4 GiB tmpfs、空 HOME/XDG/HF/Torch/Demucs/NLTK/pip/uv cache、`PIP_NO_INDEX=1` 与 `python -I`，没有挂载源码树或宿主 `.venv`；验证了：

- 网络探针以 `ENETUNREACH` 失败；
- 57 个 runtime wheels 和 2 个 build-system wheels 的 size/SHA-256 闭包与 CPython 3.11 Linux x86_64 tag；
- 发布 sdist 在 build isolation 中离线构建，全新 venv 完成 no-index 安装且 `pip check` 通过；
- 15 个直接依赖模块加 installed `t2l` 共 16 个 import，不存在 checkout import；fresh venv 创建后记录全部 `.pth` 相对路径和 hash，安装后、`pip check` 前要求 snapshot 完全不变，baseline `.pth` 也不得引用 installation root 之外路径；
- 真实 MP3 经 installed CLI 精确输出 `[00:00.034]hello\n`。

manifest/snapshot verifier 现有 20 个轻量实例。原有用例覆盖 hash、size、未登记文件、五种恶意或非规范路径、文件和父目录 symlink、重复 path、wrong tag、外部 `.pth`、安装中新建 executable `.pth`，以及 fresh venv baseline `.pth` 正例；W2 新增 manifest symlink、校验后源路径替换、复制中原地覆盖、复制后 snapshot 篡改和 snapshot 完成后源目录变化。manifest 和 artifact 均以 `O_NOFOLLOW` 打开并比较 device/inode/mode/size/mtime/ctime；复制时同步计算 size/hash，快照完成后再执行完整 manifest 校验。该组定向验证为 `20 passed`。

真实 cold gate 现在在容器 tmpfs 中创建每次唯一的私有 wheelhouse snapshot。首次校验后，runtime/build-system wheels、requirements、release sdist、wheel tag 检查、pip build/install 的 `--find-links` 和最终 manifest evidence hash 全部只引用 snapshot，不再重开原 wheelhouse。源目录在 snapshot 完成后变化不会影响私有副本；任何复制前路径替换、复制中身份/内容变化或 snapshot 终态不一致都会在启动 build/install 前失败并删除半成品 snapshot。

该临时候选的 `manifest.json` SHA-256 为 `f5d0157395ba10b0a29ea595fb5c33ac276e54a5c2a2cbda2f7e756f9127cd7a`，发布 sdist 为 `2431888f2c196a860ede24b07206cb8499a28e36939cdc08d93e3848e39f4d6d`；57 个 runtime wheels 共 342,733,931 bytes，2 个 build-system wheels 共 890,710 bytes，candidate sdist 为 55,357 bytes。它把 `PKG-019` 登记为 Linux scope 的 `implemented-unqualified`；`PKG-012/017` 要求 Linux/macOS 双平台矩阵，仍因 macOS Torch tag 阻塞而保持 planned。amd64 容器运行于 Docker Desktop Linux/aarch64 daemon 的模拟层，不是原生 x86_64 性能证据，也不是长期受控制品。

C06 本轮新增 `AUD-011/012` 并登记为 `implemented-unqualified`：Demucs 缺少 `vocals` source 时在最终 resample 前稳定返回 `T2L_VOCALS_FAILED`；`-1/0/3/4` 和实际短 bag 的模型选择边界都有独立断言。separation 链路修复为 decoder 原始采样率 -> Demucs model rate -> 22050，消除先降到 22050、再升到 model rate、再降到 22050 的重复重采样。只有 `ModuleNotFoundError.name` 是 `demucs` 或其子模块时才映射 `T2L_VOCALS_DEPENDENCY_MISSING`，backend 内部普通 `ImportError` 映射 `T2L_VOCALS_FAILED`。这些只关闭最小 adapter 合同，不能证明真实离线 Demucs P4。

canonical runner 修复了 macOS Bash 3.2 在 `set -u` 下展开空 evidence-mount 数组时报 `unbound variable` 的问题。`audio.py` provenance 变化后重新生成 public-e2e candidate，三次同进程结果一致；人工审查确认只有 `provenance.audio_adapter_sha256` 更新，decoder bytes、waveform、Mel、posterior、boundary、frames 和四路 API/CLI LRC 均未变化。最新 Linux x86_64/CPython 3.10.21 functional canonical 为 `13 passed, 7 warnings, 0 skipped in 144.45s`，证据位于 `/tmp/ai-auto-lrc-canonical-gate-v10-2/canonical.xml`。这是 functional evidence，不是 clean release provenance。

inventory 当前有 274 个稳定 ID，其中 92 个有实现证据并映射到 85 个不同 pytest nodeid；81 个为 `implemented-unqualified`，11 个为 `qualified-canonical`，182 个为 planned，0 个为 `qualified-release`。

### 22.3 后续执行锁定

本节保留第十轮当时的执行锁；W1 capture runner 的最新实施状态已由第 23 节取代。

1. 先由 PM/Architect 锁定 `max_phone_count`、`max_audio_samples`、`max_posterior_cells` 的单位、阈值、入口、错误 details 和迁移语义，再实现 `RES-003/005`；性能 `RES-004` 还要固定 runner、fixture、paired baseline、计时 schema 和 artifact owner。
2. W2 verify -> private snapshot -> build/install 已完成并以真实 v10 wheelhouse 回归。W1a 的本地 manifest/hash/cross-layer verifier 也已完成，但 W1 仍缺 capture runner：必须由唯一新建的 run directory 启动实际 gate，捕获真实 exit，比较运行前后 source snapshot，并按层闭合 portable coverage、package Linux sidecar、canonical immutable image receipt；失败运行也要原子保存 diagnostic receipt。之后再持久化 Linux 候选并固定 image digest。CI workflow 属于外部执行面，必须取得用户独立授权后再接入。Linux 单平台仍只维持 `PKG-019` 的 implemented-unqualified，不能关闭 `PKG-012/017`。
3. macOS Torch 制品必须先经用户批准的 ADR 选择受信上游、可审计重建并重签或升级依赖；禁止篡改下载 wheel 的内部 tag。
4. Demucs P4 在实现前先锁定权重 logical name/repo/details、manifest 错误是否统一进入 `asset_resolution/exit 6`、backend 已安装但本地 repo 不可解析时的错误分类，以及 16 个 `.th`/4 个 YAML 的来源、hash、大小、许可和再分发授权。实现必须用显式本地 repo，禁止 `pretrained.get_model(name)` 隐式创建 RemoteRepo；补齐 vocals wheelhouse、approved-sdist policy、installed-extra 断网真实执行和 runtime-local single initialization。默认 core 路径继续要求零 import/零下载。
5. 最后建立独立恢复包、双平台 matrix、SBOM、attestation、签名、staging 和上一版本 rollback drill；全部 RC required 零 skip 且绑定 clean source 后，才能产生首个 `qualified-release`。

### 22.4 当前 Gate 与恢复结论

| Gate | 当前状态 | 不可越过的下一条件 |
|---|---|---|
| portable required + coverage | Go，本地 dirty-worktree scope | 每次实现继续输出独立 JUnit/coverage JSON；不得外推 release |
| functional canonical | Go，Linux pinned functional scope | provenance 变化必须候选三次一致、人工审查、再完整 verify |
| Linux x86_64 cold install | Go，`PKG-019` Linux scope、implemented-unqualified；W2 私有 snapshot 已完成 | 持久化受控 evidence、固定 image digest；不得外推双平台或 release |
| 默认 package required | No-go，未注入 wheelhouse时有 5 个预期 skip | required 层必须零 skip，不能删除或绕过用例 |
| `PKG-012/017` 双平台 | No-go | 先解决 macOS Torch tag，再以同一证据 schema 聚合 Linux/macOS |
| 完整资源预算 | No-go | 人类锁定单位、阈值、错误、迁移和 `RES-004` runner/schema/owner |
| Demucs optional-extra | No-go；仅最小 adapter 合同可用 | 权重资产、许可、本地 repo、wheelhouse、真实断网执行和生命周期闭环 |
| Runtime 公开 close | No-go | 锁定 in-flight、close 后错误、临时 runtime、NLTK lease/refcount 与模型释放语义 |
| 恢复与 Release | **No-go** | clean source、双平台零 skip、`AST-022`、SBOM、attestation、签名和 rollback drill |

后续恢复先读取本节和 Teams 文档第 11 节，再检查工作树并保留全部现有变更。任何实施不得通过放宽阈值、删除 skip、复用其他层证据或无审查更新 oracle 来恢复绿色。本轮未创建 ADR、CI workflow、commit、push 或发布，也未修改冻结模型文件。

## 23. Teams 第十一轮 W1b Capture 实施与验证

W1b 的详细合同与测试目录见 [`W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md`](./W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md) 第 14 节。本轮新增 `scripts/capture_test_gate.py` 和 28 个 capture 合同实例，并扩展 quality gate JSON：JUnit/coverage 共同绑定 capture run ID、各自输入 SHA-256、policy SHA-256，coverage 另绑定 base-ref。run ID 的 CLI/environment 冲突或非法格式 fail closed；无 run ID 的旧直接调用明确输出 null，只能作为 legacy diagnostic。

W1b-0 合同、W1b-1 capture core 和 W1b-2 portable closure 已落地。capture 使用仓库外独占 staging，保存 before/after source、二进制日志和分层 artifact，转发 SIGINT/SIGTERM，按原 gate rc 优先级在 `finally` 封存，并以只读 `SEALED` marker、原子 rename 和正式 verifier 自校验完成发布。source identity 覆盖 staged/unstaged/delete/rename/mode、untracked binary/symlink；FIFO 等特殊文件只能 diagnostic。本段是 W1b-2 时点快照：当时 package/canonical 固定 `LAYER_CLOSURE_UNIMPLEMENTED`；package 的后续语义闭包见第 25 节，canonical 仍未实现。

真实 portable capture 为 `311 passed, 22 warnings, 0 skipped`，overall pure line `1726/1975 = 87.392405%`，changed executable line `1696/1868 = 90.792291%`；同一次 receipt 的四件套和 source 前后 hash 交叉一致。capture/quality/W1a 定向为 `48 passed`，宿主全量为 `349 passed, 18 skipped, 22 warnings in 48.18s`。静态、语法、lock、build 和 diff 门禁全绿；本地 wheel/sdist SHA-256 分别为 `880b2a4c5ece1cbb0e5c793e96c3ba0f6f05a4bc1475b552a7ac6b6c787544ef` 与 `ba54d172b173784b9dae05e3112db4a3a48e205d27e97f5b8e8cbd5e57ad6d7a`。

W1b-2 时点未注入 wheelhouse 的 package capture 保留原 exit 1，receipt 为 diagnostic，原因包含 5 个 required skip、缺 package platform/wheelhouse sidecar 和当时的 `LAYER_CLOSURE_UNIMPLEMENTED`。第 25 节完成 W1b-3 后，package 缺件负例不再使用该原因；W1b-4/W1b-5、macOS、完整资源预算、Demucs、runtime close、恢复/签名/SBOM/attestation 仍未完成，Release 继续 **No-go**。本轮没有修改 production provenance 或 canonical oracle，因此未重复执行高成本 canonical。

## 24. Teams 第十二轮方案持久化与恢复索引

本轮没有重写总体架构，而是把下一纵切 W1b-3 细化到可以直接实现。四角色原始结论与张力保存在 [`team-sessions/team-session-2026-09-05-2.md`](./team-sessions/team-session-2026-09-05-2.md)；严格 schema、组件责任、五段实施 DAG、14 个候选反证用例和完成定义以 [`W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md`](./W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md) 第 15 节为唯一来源。

后续接手按以下顺序恢复，不从聊天记录推断：

1. 先读本文第 23–24 节确认当前 Gate，再读 W1b 专项方案第 15 节。
2. 检查并保留整个 dirty worktree；只允许修改第 15.2 节列出的 package 增量文件。
3. 从 W1b-3a 的 schema/负例开始，依次推进 3b observation、3c producer、3d capture 集成、3e 真实 Linux；每个子批次均可独立撤回。
4. 任何无 wheelhouse、tag-only image、run ID 不一致、sidecar 缺件/篡改、required skip 或 source drift 都保持 diagnostic；不得以占位文件恢复绿色。
5. 完成 W1b-3 仍只允许 Linux scope `implemented-unqualified`。W1b-4/5、macOS、`PKG-012/017`、资源预算、Demucs、runtime close、恢复/签名/SBOM/attestation 与 Release 均保持 No-go。

文档权威顺序固定为：本文管理总体路线和稳定测试 ID；W1b 专项方案管理当前 evidence 纵切的字段合同；Teams 文件保留评审过程和分歧；`AI_REFACTOR_HANDOFF.zh-CN.md` 管理 legacy 事实与能力边界。若四者冲突，以可执行测试和当前代码事实为准，并在同一批次修正文档，不允许选择性引用较宽松的一份。

## 25. Teams 第十三轮 W1b-3 Linux package sidecar 实施结果

第 24 节的 W1b-3a–3e 已按顺序完成，字段合同和完整证据见 [`W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md`](./W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md) 第 16 节。实现新增宿主 producer，并扩展容器 observation、package scope runner 和 capture consumer：不可变 repo digest 与实际 image ID 双绑定，容器使用 `linux/amd64`、断网、只读根和最小 evidence bundle；manifest 逐字节复制但不复制 328 MiB wheelhouse；sidecar 原子发布；capture 独立重算 JUnit/gate/policy/run、manifest、scope、build/install、`.pth`、imports、origin、CLI 和 network。

真实 Linux capture 为 `33 passed, 3 deselected, 0 skipped`，四件套完整，source before/after 相等，raw/normalized/capture exit 均为 0；`current-source` 当时为 valid、`implemented-unqualified`，`archived-integrity` 为 valid、historical diagnostic。真实执行发现并修复 package consumer 对标准 quality-gate 扩展字段的错误整对象比较，并补充 `required_markers`、`outside_layer`、`failures` 正反合同。

本轮验证：W1b-3 联合快速层 `155 passed, 5 skipped`；宿主全量 `421 passed, 18 skipped, 22 warnings`；Ruff、compileall、shell 语法、lock、build 和 diff 检查全绿。无 wheelhouse 负例仍返回 1、不生成占位 sidecar，原因仅为真实 gate 非零与两个 required artifact 缺失。

Gate 更新：Linux x86_64/CPython 3.11 package sidecar 与 `PKG-019` 保持 **Go / implemented-unqualified**；W1b-4/5、macOS、`PKG-012/017`、资源预算、Demucs、runtime close、恢复、SBOM、attestation、签名、rollback 和 Release 均继续 **No-go**。未创建 CI workflow、commit、push、签名、上传或发布。

## 26. Teams 第十四轮 W1b-4 canonical sidecar 方案锁定（已由第 27 节实施结果取代）

W1b-4 的四角色评审保存在 [`team-sessions/team-session-2026-09-06.md`](./team-sessions/team-session-2026-09-06.md)，字段级唯一实施入口为 [`W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md`](./W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md) 第 17 节。方案固定为 host producer、container observer、capture consumer 三段：base image继续使用不可变repo digest；本地build image以iidfile/inspect得到的实际image ID为身份并按ID运行；三份oracle与Dockerfile等输入逐字节封存；network/rootfs/tmpfs/platform/Python/CPU/thread和installed origin由真实探针证明。

artifact closure、strict schema、无环hash链、4a–4f DAG、CAN-T01–T30快速反证和真实Docker Go定义均已落盘。正式closure另保存producer、observer与canonical runner源码副本，使其provenance hash可由archived consumer重算。checkpoint本批只记录并稳定重算size/hash，不复制约128 MiB内容；这限制archived evidence为历史完整性证明，不构成独立资产恢复。本节记录方案锁定时的 No-go；实施后的当前状态以第 27 节为准。即使完成也最高为`implemented-unqualified`，不追认inventory中的functional canonical资格，不解除W1b-5或Release No-go。

## 27. Teams 第十五轮 W1b-4 canonical sidecar 实施结果

第 26 节方案和 W1b 专项方案第 17 节的 W1b-4a–4f 已完成。实现新增 `scripts/run_canonical_gate.py` 和容器 observer，并扩展 canonical runner、capture consumer 与三组 contract tests。host producer、container observer、capture consumer 三段边界已经成为真实代码：base repo digest与inspect image ID绑定；build使用iidfile和labels并只按实际image ID运行；network/rootfs/tmpfs/platform/Python/CPU/thread与site-packages origin来自实际探针；Dockerfile、三份oracle、profile、fixture和producer/observer/runner源码进入十二件正式closure；consumer从私有字节重算语义。

错误合同已收口：canonical缺件仅为`REQUIRED_ARTIFACT_MISSING`；closure完整但语义或跨件绑定无效仅为`RUN_ARTIFACT_BINDING_INVALID`；伪造`LAYER_CLOSURE_UNIMPLEMENTED`会被receipt verifier拒绝。producer失败不生成gate，多文件发布失败不留下可晋级半套closure；candidate模式与非capture verify没有被改变。

实测结果：

- W1b-4联合快速层`215 passed, 5 skipped`；五个skip为默认package未注入wheelhouse。
- 文档回写前宿主全量`481 passed, 18 skipped, 22 warnings in 67.90s`；18个skip精确为13个专用canonical runner用例和5个默认cold package用例。
- Ruff、compileall、shell syntax、lock、build和diff检查全绿。
- 真实Docker capture为`13 passed, 7 warnings, 0 skipped in 143.43s`，raw/normalized/capture exit均0，source before/after相等；archived verify为valid historical diagnostic，当时的current-source为valid `implemented-unqualified`。
- 实际base为`python@sha256:8c97ebedc32fd60935cdf5992e935753e2a0f98231830028050e1e04bd3c13c2`，base image ID为`sha256:db825c749364f7f06c8fb165b360d9de94ba5c14727e2e446c1b4202a30224e7`，build iid为`sha256:a434bed0c04e82424c9956c4aea835d6087e480c3e43a73cfa5be7160aebfe63`；network拒绝码101、rootfs errno 30、installed origin为site-packages。

Gate更新：W1b-4为**Go / implemented-unqualified**，但`claim.spec_ids=[]`。checkpoint仍只记录size/hash，receipt不构成独立恢复证明。W1b-5、macOS/双平台、资源预算、Demucs、runtime close、恢复、SBOM、attestation、签名、rollback和Release均继续**No-go**。完整字段、artifact hash和历史run边界见W1b专项方案第18节。

## 28. Teams 第十六轮 W1b-5 retention 与受控导出方案锁定

W1b-5的四角色评审保存在[`team-sessions/team-session-2026-09-06-2.md`](./team-sessions/team-session-2026-09-06-2.md)，字段级唯一实施入口为[`W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md`](./W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md)第19节。后续接手不得从聊天记录补全设计；按下列顺序恢复：

W1b-5a/5b 的编码级最小执行基线见 [`W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md`](./W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md)。它把初始 CLI 收窄为 `inspect`/`verify-inspection`，并冻结 assessment policy、byte scanner、控制层提交点和 QA RED；与上位远期方案冲突时，5a/5b 首批实现以该最小基线为准。

1. 保留现有dirty worktree，先验证W1b-4当前测试和receipt边界；不要修改sealed run。
2. 从W1b-5a exact-key schema/threat model和RET-T01–T30负例开始，再做5b只读inspect/secret scan。
3. retention manager独立于capture runner；事实目录、控制目录和export目录分离。任何scan/parser/closure错误都阻止导出，报告不得回显secret。
4. 5c只允许显式policy与approval绑定的仓库外local-only bundle；default deny、allowlist重建、无network/upload/prune/destroy命令、原子发布且独立复验。
5. 5d encrypted archive与5e expiry/destruction在`D-REL`锁定owner、期限、KMS/key custody、RPO/RTO、checkpoint策略和双人销毁审批前不得实施。到期只记`EXPIRED`，不自动删除。
6. 每个子批次单独报告Go/No-go；设计文字、skip或局部绿测不能关闭未实现批次，也不能晋级release。

当前工作入口为5a，但`D-REL`仍是5c operational policy与5d/5e的决策闸门。未创建CI workflow、commit、push、签名、上传、自动prune或发布。

### 28.1 首版实施事实与二次 Teams Gate（历史检查点）

assessment-only manager、rules/assessment 配置和合同测试已经存在，首轮定向结果为 `47 passed`。该数字只证明首版合同通过；二次 Teams 评审确认其仍存在 P0 父链 symlink、source/publish TOCTOU、外部 rules/assessment trust anchor 缺失、可逆 pattern 保存、任意 regex 与整文件读取 DoS，以及 P1 transaction/ledger、嵌套 exact schema、精确权限、分类与 CLI 边界未收口。因此 W1b-5a/5b 当前仍为 **No-go / hardening required**，不得登记为已完成或晋级资格。

后续唯一恢复顺序为 [`W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md`](./W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md) 第 15.3 节的六个切片：S1 schema/config trust → S2 path + bounded I/O → S3 report correctness → S4 control transaction → S5 independent verifier → S6 CLI + regression。每片必须先增加 RED，再实现 GREEN；需补的 path/config/scan/race/transaction/schema/permission/CLI/drift 矩阵见同文件第 15.4 节。角色原始结论与综合阻断理由见 [`team-sessions/team-session-2026-09-06-2.md`](./team-sessions/team-session-2026-09-06-2.md)“二次评审”。

当前只允许继续加固 `inspect`、`scan` 和 `verify-inspection`。5c export、5d archive/restore、5e expiry/destruction 继续 blocked-by-D-REL；checkpoint/source 独立恢复、macOS/双平台、SBOM、attestation、签名和 rollback 仍未完成，Release 继续 **No-go**。

### 28.2 S7–S11 前的加固版实施结果与 No-go（历史检查点）

本轮已完成 69 个 retention 合同节点；retention+capture 联合为 `200 passed`，宿主全量为
`550 passed, 18 skipped, 22 warnings`，实际 sealed PASS/BLOCKED 独立 verify 分别返回 0/3。
同时完成 bounded matcher、rules/assessment snapshot、两阶段 inspection/event、private mode、
独立重扫和 CLI 收口。完整事实见 W1b-5 执行计划第 16.1 节。

最终 Teams 反审确认这些数字仍不足以关闭 W1b-5a/5b：父目录尚未由 dirfd/openat 固定，
配置缺独立 expected digest，11,050-hit 实证会留下 event 已提交但 report 超 verifier 上限的
自失效状态，特殊文件/owner/scanner identity/fault-orphan/ledger/current-source/真实并发矩阵
仍未闭合。后续唯一入口为 W1b-5 执行计划第 16.2–16.3 节 S7–S11；当前 Gate 保持
**W1b-5a/5b No-go / hardening required，Release No-go**。

### 28.3 S7–S11 实施后当前 Gate 与恢复入口

S7–S11 已经实施，不得再从第 28.1 的 S1 或第 28.2 的 S7 重新开始。当前事实如下：

- retention contract：`125 passed`；capture contract：`135 passed`；联合：`260 passed in 88.21s`；
- 锁定环境宿主全量：`610 passed, 18 skipped, 22 warnings in 145.79s`；18 个 skip 为 13 个 canonical-only golden 与 5 个未注入 wheelhouse 的 package case；
- 默认 rules/assessment raw-byte digest 分别为 `ab396187f0e53e26d9eb63cd3d4051a3103233b0cc4154d1199248247398df3c` 与 `78f67c28156916d443f45a246ddfef2d693a3319f28ffb5e185e6fdf6a7a54f3`；
- 最新测试控制 sealed PASS/BLOCKED 均被独立 `verify-inspection` 复验，退出码为 0/3，sealed tree signature 前后不变；
- `verify_receipt_at()`、external expected digest、全局 hit/report 上限、no-replace、ledger 分类、current-source 参数矩阵、并发/offset/hygiene 已进入合同。

第三次 Teams 反审没有因为测试全绿而提升生产声明。当前仍有两个 P0：

1. `LOCK`、ledger、write、rename、fsync 和 final verify 没有在整个事务中持有同一组 control/run/inspections/events fd，存在同 UID 替换控制树后 lock split 的可能；
2. event 原子 rename 已可能成功后，target post-stat、temporary cleanup、mode check 和其他后置失败尚未全部单向映射为 `CONTROL_COMMIT_UNCERTAIN`。

同时保留三个 P1：目录树在全量 snapshot 物化后才检查文件/元数据预算；macOS `F_GETPATH` 与多次 Git/文件观察不是原子 current-source snapshot；默认 digest 的 owner、轮换审批和 ADR/审计位置尚未锁定。

当前 Gate：

| 范围 | 状态 | 解释 |
|---|---|---|
| W1b-5a schema/trust binding | Conditional Go | 本地受信脚本、checked-in defaults、assessment-only 范围可用；不代表签名供应链或治理授权 |
| W1b-5b inspect/scan/verify | No-go / hardening required | 功能合同 GREEN，但 control transaction anchor 与 commit uncertainty 两个 P0 未关闭 |
| W1b-5c export | 未授权、未实现 | 必须等待 D-REL 与 operational policy/approval |
| W1b-5d archive/restore | 未授权、未实现 | key custody、encryption、RPO/RTO 未决 |
| W1b-5e expiry/destruction | 未授权、未实现 | 双人审批、tombstone 与法律/审计边界未决 |
| Release | No-go | 本批不能替代 macOS/双平台、资源、Demucs、runtime close、恢复、SBOM、attestation、签名与 rollback |

后续唯一执行顺序：

1. S12：建立贯穿整个 control transaction 的 fd context，关闭 lock split；
2. S13：建立 `event_may_be_visible` 单向状态机，补齐 post-rename 全 fault matrix；
3. S14：把 file/byte/metadata 限额前移到目录遍历物化过程中；
4. S15：对 macOS `F_GETPATH` 和 Git 多观察点做 swap/ABA 反证，无法提供事务语义时将 current-source 固定为 diagnostic-only；
5. S16–S18：补双进程竞争与 crash recovery、真实 CLI/ownership 矩阵、安全脚本 branch coverage 和 Linux 分支实跑；
6. 人类指定 digest owner、rotation approver、ADR/审计位置与 W1b-5 Go 签署人；
7. 再重新生成 PASS/BLOCKED sealed evidence、执行联合 260 与宿主全量，并由 PM/Architect/QA 重新签收。

字段、测试 node、恢复 runbook 和最新真实 run IDs 统一维护在 [`W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md`](./W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md) 第 17 节。禁止在主计划复制第二套字段规范。

### 28.4 S12/S13 第一批实现后的第四次 Teams Gate

S12/S13 第一批生产实现与 9 个精确合同已经进入工作区。当前独立复验为 retention `134 passed`、retention+capture `269 passed in 58.95s`、宿主全量 `619 passed, 18 skipped, 22 warnings in 113.84s`，ruff、compileall 与 `git diff --check` 均通过。新增节点证明 flock 后立即替换 run-control/inspections/events 不会把 inspection/event 写入 replacement tree，并证明 event no-replace rename 成功后的 post-stat、temporary unlink、mode、events/run fsync 和 final verify 失败统一为 `CONTROL_COMMIT_UNCERTAIN`。

第四次 PM/Architect/Developer/QA 复核没有将 W1b-5b 升级为 Go。当前实现仍缺 pinned parent 到 child 的相对打开与 identity binding、事务中后段 swap 反证、final verify 后 return 前的 control namespace 复核、unlock/close/context-exit 稳定语义，以及 uncertain artifact 的独立恢复和真实 crash 测试。继续顺序为 S12a/S13a → S14 → S15 → S16–S18；精确 node、故障注入点和生产修正只在 W1b-5 专项方案第 18 节维护。

当前跨工作包 Gate：W1b-5a 仍为受信本地 assessment-only 的 Conditional Go；W1b-5b 仍为 No-go / hardening required；5c/5d/5e 未授权、未实现；macOS/双平台、完整资源预算、Demucs、runtime close、独立恢复、SBOM、attestation、签名、rollback 与 Release 全部保持 No-go。第 28.3 节的 125/260/610 与旧 receipt 只作为历史检查点，不得覆盖本节事实，也不得把旧 receipt 当成 S12/S13 最终证据。

## 29. 2026-09-06 当前可执行重构总方案（唯一跨工作包恢复入口）

本节取代第 28.4 节作为跨工作包的当前恢复入口。W1b-5 的字段、错误码、故障注入和 node 级事实只在 [`W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md`](./W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md) 第 19 节维护；本节只维护依赖、阶段 Gate 与剩余 v2 工作包。历史测试数字继续保留，不回写成当前值。

### 29.1 当前基线与证据等级

- S12a/S13a/S13b 已完成 parent-child fd binding、return 前 namespace recheck 和 teardown 错误收敛；S14 已完成枚举物化前的 entry/file/byte/metadata 预算；S15 已把 current-source 收窄为两次顺序观察的 diagnostic-only，并禁止 retention schema-v1 发布该模式。
- 当前 capture/retention 合同分别为 `142 passed`、`154 passed`，联合重跑为 `296 passed in 69.54s`。第一次联合运行曾有 `1 failed, 295 passed` 的顺序疑似 flaky，必须保留。
- S15 与文档落盘后的宿主全量已实跑为 `646 passed, 18 skipped, 22 warnings in 123.64s`；Ruff、compileall、`git diff --check` 与本批文档相对链接检查通过。S15 前的 `634 passed` 继续作为历史检查点。最新 PASS/BLOCKED sealed evidence 已在仓库外生成并独立 verify，inspect/verify exit 分别为 `0/0` 与 `3/3`，sealed-tree signature 前后不变；精确 ID 见 W1b-5 专项计划第 19.2 节。18 个 skip 仍分属 canonical-only 与缺 wheelhouse package 门禁。
- W1b-5a 仅为 trusted local assessment-only 的 Conditional Go；W1b-5b、5c/5d/5e、macOS 双平台、完整资源预算、真实 Demucs、runtime close、独立恢复、SBOM、attestation、签名、rollback 与 Release 均为 No-go。

证据必须分四层保存，禁止互相替代：

| 层 | 允许证明 | 不能替代 |
|---|---|---|
| host portable/contract | 公共合同、故障注入、平台无关语义 | Linux/macOS 系统调用、cold package、canonical 数值、Release |
| platform package | 指定 OS/arch/Python 的断网构建、安装与 tag | 另一平台、canonical、签名发布 |
| canonical | 指定 image/资产/oracle 的功能和历史完整性 | 独立恢复、平台 package、Release |
| release | clean protected signed source、长期 evidence、恢复和 rollback | 不接受 dirty-tree、skip 或本地自报替代 |

### 29.2 执行 DAG 与并行边界

```text
A. 文档/证据 checkpoint
   -> B. W1b-5 S16 -> S17 -> S18 -> W1b-5b 复审
   -> C1. 完整资源预算
   -> C2. Linux/macOS package 双平台
   -> C3. Demucs optional 离线实跑
   -> C4. AlignmentRuntime.close 生命周期
   -> D. 独立恢复（需显式授权）
   -> E. SBOM + attestation + 签名 + staging + rollback（需显式发布授权）
   -> RC Go/No-go
```

B 完成前不再扩张 evidence manager 的公开能力。C1–C4 在合同冻结后可以逻辑并行，但当前共享 dirty worktree 中不得让多个执行者同时修改同一文件；每个包必须使用独立文件清单、独立 nodeids 和独立验证记录。高成本 package、canonical、Demucs 与恢复演练串行执行，避免 cache、CPU/RAM 和 artifact provenance 互相污染。

### 29.3 A/B：先稳定 W1b-5 证据链

1. **已完成 checkpoint**：文档落盘后宿主全量为 `646 passed, 18 skipped, 22 warnings in 123.64s`，Ruff、compileall、`git diff --check` 和文档相对链接检查通过；联合合同首次失败与 retry 记录均已保留。
2. **已完成 evidence refresh**：最新 PASS/BLOCKED sealed runs 已在仓库外创建并独立 `verify-inspection`；精确 run/inspection/event/signature 已写入专项计划，receipt hash 未回写仓库。
3. 按专项计划第 19.4 节完成 S16：真实 subprocess flock、双 publisher、staging/inspection/event/fsync/teardown crash；最多一个有效 commit，只读分类稳定。
4. 按第 19.5 节完成 S17：真实 CLI 脱敏、config hardlink/FIFO/socket/wrong-owner、Linux device 和 source unknown-key 反证。
5. 按第 19.6 节完成 S18：两份安全脚本 branch/关键分支 coverage、Linux `renameat2`/`/proc/self/fd`/device/system tests、package/canonical required runner 零意外 skip。
6. 独立 Architect/QA 复审后才允许重新评估 W1b-5b。5c/5d/5e 仍等待 D-REL，不随 5b 自动开放。

### 29.4 C1：完整运行时资源预算

依赖：先由 PM/Architect 形成 `D-RESOURCE`，锁定 `max_audio_samples`、`max_phone_count`、`max_posterior_cells` 的默认值、配置入口、稳定错误 details 和迁移策略；现有 `max_alignment_bytes` 不能冒充这些上限。

实现顺序：decoder metadata 预检 -> lyrics plan phone count 预检 -> posterior shape 预检 -> DP exact byte estimator -> 真实测量报告。所有预检必须发生在大 tensor/model/DP allocator 前，错误从注册表产生，不能依赖 OOM。

required tests：`RES-001..005`，其中 allocation/model spies 必须为 0；极大虚拟 shape 不实际分配；固定 runner warmup 后 20 次记录阶段耗时和 RSS，并绑定 commit/lock/asset hash。退出条件是每个资源入口都有 exact-cap 与 cap+1 合同、错误 details 稳定、宿主与 canonical 回归不变。未完成前 C02/C07/C08 不能声称大规模输入生产安全。

### 29.5 C2：Linux/macOS package 双平台

Linux：使用现有 snapshot/cold-gate 流程在真实 `linux/amd64`、CPython 3.11、断网、只读 root、空 HOME/cache、全新 venv 中从发布 sdist 构建 wheel，执行 `pip check`、依赖 imports、installed CLI 和 manifest hash 重算。

macOS：先通过 `D-MACOS-TORCH` 在“获得上游一致制品”“受控重建并重新建立 provenance”“升级 Torch 并重跑全部 canonical”中选择。禁止修改下载 wheel 的内部 `WHEEL` tag、降低 pip/uv 检查或删除 `pip check`。决议后重建 arm64 wheelhouse，不能复用已被后续源码/profile 变化 supersede 的临时候选。

required tests：`PKG-012/013/014/015/017/018/019/021/022/023/024/025`。每个平台 required runner 报告零意外 skip；wheelhouse manifest 固定 target tag、每件 size/hash、build/runtime 分类和 sdist policy。只有双平台分别全绿才关闭 `PKG-012/017`，单平台结果最高仍为 platform-scoped implemented-unqualified。

### 29.6 C3：Demucs optional 离线能力

实现必须保持 core 默认关闭、零 import、零下载。新增独立 Demucs weight manifest，包含 model/index、relative path、size、SHA-256、source、license、兼容 package/profile；已安装 `vocals` extra 且显式请求时才进入真实 separation。decoder rate -> Demucs model rate -> 22050 的现有一次链路不得退化。

required tests：未安装 extra 稳定 `T2L_VOCALS_DEPENDENCY_MISSING`；内部普通 `ImportError` 与缺 `vocals` source 稳定 `T2L_VOCALS_FAILED`；缺权重/hash 错误在 backend 前失败；空 HF/Torch/Demucs cache 与网络熔断下真实短音频成功；默认路径模块集合 before/after 不出现 Demucs；`demucs_index=-1/0/3/4` 和短 bag 边界保持。退出条件还包括 installed wheel、仓库外 CWD、双平台 codec 与资产来源/许可均有证据；否则只保留 adapter-contract Go。

### 29.7 C4：`AlignmentRuntime.close()` 生命周期

先形成 `D-RUNTIME-CLOSE`，决定 in-flight 请求是等待完成还是拒绝/取消、close 是否可重复、context-manager 语义及 GPU/临时 materialized assets 的释放责任。默认建议采用：`close()` 幂等；已开始请求完成后释放；进入 CLOSING 后拒绝新请求；完成后 CLOSED；不得异步杀死正在执行的 Python 调用。该建议未形成 ADR 前不得进入公共合同。

required tests：NEW/INITIALIZING/READY/FAILED/CLOSING/CLOSED 的合法转换；16 等待者与 close barrier；close 两次；close 后 process 精确稳定错误；失败初始化后的清理；不同 runtime 隔离；materialized asset owner、模型/GPU handle 和临时目录各释放一次；signal/异常下无 deadlock。公共 API、错误码和迁移文档必须同批更新。退出条件是生命周期合同、并发系统测试和资源泄漏测量共同通过。

### 29.8 D：独立恢复包（当前未授权执行）

设计目标仍是 `GIT-001..008`：保存全 refs bundle、独立 LFS/checkpoint 实体、dirty/untracked 清单与 bytes、lock/wheelhouse/manifest/oracle、来源和许可；在断网空目录重新 checkout、恢复资产、构建并运行 legacy/canonical smoke。恢复包必须通过 sentinel secret scan，且命令在隔离临时目录实际演练。

当前用户边界禁止归档和恢复，所以本阶段只保留设计与 RED，不创建真实恢复包、不复制用户工作区、不删除/覆盖任何原文件。只有获得明确授权、确定存储位置/retention/key custody/RPO/RTO 后才能执行；checkpoint hash 本身不等于内容可恢复。

### 29.9 E：供应链、签名与 rollback（当前未授权执行）

依赖：D 已通过，W1b-5c/5d/5e 的 D-REL 已签收，clean protected source 和发布凭据边界明确。执行时必须绑定：

```text
signed tag
  -> source commit
  -> wheel/sdist hash
  -> bundled manifest hash
  -> checkpoint/LID/G2P/Demucs asset hash
  -> SBOM + provenance/attestation
  -> long-lived evidence manifest
```

required tests：`REL-001..014`、`AST-022`、`DOC-001..006`。先 staging 安装和恶意/只读 CWD smoke，再由独立 verifier 验证签名/attestation/SBOM；随后执行上一已知良好 wheel+lock+manifest+assets 的断网 rollback drill。required RC 必须零 skip、零 allowed failure，正式制品不得覆盖同版本。当前不创建 CI、不签名、不上传、不发布、不 yank；这些动作必须另获明确授权。

### 29.10 每个工作包的交付模板与停止规则

每个包必须在本地文档追加以下九项：范围/不变量；生产文件；测试 nodeids；前置 artifact/环境；RED 证据；GREEN 命令与实际输出；rollback unit；未验证项；新 Gate。若首次失败、flaky、skip、平台模拟或证据生成后源码又变化，必须显式记录。

出现以下任一情况立即停止进入下一包：公共 schema/API 未先冻结；要靠扩大错误允许集合才能变绿；required runner 意外 skip；测试依赖源码 checkout 或网络；artifact hash/identity 无法重算；需要 commit/push/CI/上传/签名/发布/归档/恢复/删除但尚未获授权。

当前禁止事项：不 commit、push、创建 CI、上传、签名、发布、自动删除、清理、归档或恢复；不执行 W1b-5c/5d/5e；不清理当前大量 modified/deleted/untracked 文件。最终 Gate 保持 **Implementation in progress；Release No-go**。

## 30. W1b-5 S16 完成后的跨工作包 checkpoint

本节取代第 29.2 节中“S16 下一步”的状态，其他跨工作包依赖不变。S16 新增真实独立进程 lock contention、双 publisher 和六个 SIGKILL checkpoint；测试 worker 只 monkeypatch 私有 seam，生产 CLI/config/API 没有 crash switch。

首轮双 publisher RED 暴露真实生产竞态：两个进程同时首次初始化 control tree 时，loser 在 `_open_lock()` 的 `O_CREAT` 路径得到 `ENOENT`，曾表现为 `SYMLINK_FORBIDDEN`/`CONTROL_PUBLICATION_FAILED`。修复没有放宽允许集合，而是在 pinned run dirfd 上采用 `O_CREAT|O_EXCL` 创建、仅 `FileExistsError` 后无创建重开，并在 flock 前后核对 lock fd 与目录项 identity。

当前 macOS arm64 实测为 S16 连续三轮各 `8 passed`，retention `162 passed`，capture+retention `304 passed`，宿主全量 `654 passed, 18 skipped, 22 warnings`；静态、编译、diff 和文档链接检查通过。精确时间、状态矩阵和 RED 见 [`W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md`](./W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md) 第 20 节。

跨工作包 DAG 现在是：

```text
W1b-5 S16（macOS process-crash scope Go）
  -> W1b-5 S17
  -> W1b-5 S18 + Linux required runner + evidence refresh
  -> W1b-5b 复审
  -> 完整资源预算 / 双平台 package / Demucs / runtime close
  -> 经单独授权的恢复与 release supply chain
```

S16 不关闭 Linux、power-loss durability、同 UID 主动完整 ABA、自动恢复、package skip 或 release provenance。W1b-5b 和 Release 均继续 No-go；5c/5d/5e 仍未授权。Teams 记录见 [`team-sessions/team-session-2026-09-06-4.md`](./team-sessions/team-session-2026-09-06-4.md)。

## 31. W1b-5 S17 当前宿主 checkpoint

S17 已在当前 macOS 宿主完成 config special-file/owner 负向合同、真实 CLI sensitive-input 脱敏和 capture `source` exact-key。rules/assessment 的 hardlink、FIFO、socket 均在 `.control` 创建前拒绝；伪造 wrong-owner 分支同样 fail closed；CLI 对 secret/HOME/控制字符不回显；receipt `source` 中额外的 `transactional`、`aba_excluded`、`qualification` 声明被拒绝。

首轮定向 `10 passed, 6 failed` 中包含 3 个真实生产 RED、2 个 macOS Unix-socket 路径过长 fixture 问题和 1 个 secret filename 状态期望问题。修正后 16 个节点连续 20 轮全过。第一次联合为 `1 failed, 319 passed`，定位为新增 shape check 改变旧 `observation_limit` 精确错误顺序；保持旧错误优先后联合重跑 `320 passed`。

最新独立结果为 capture `145 passed`、retention `175 passed`、宿主全量 `670 passed, 18 skipped, 22 warnings`，静态/编译/diff/link 通过。详细证据见 [`W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md`](./W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md) 第 21 节和 [`team-sessions/team-session-2026-09-06-5.md`](./team-sessions/team-session-2026-09-06-5.md)。

S17 只能给 macOS 可执行范围 Conditional Go：Linux block/char device 与真实跨 uid 仍缺 required runner。跨工作包下一入口为 S18 coverage/Linux/package/canonical qualification，再刷新 evidence 并复审 W1b-5b。Release、5c/5d/5e 和自动恢复授权均无变化。

## 32. W1b-5 S18 qualification checkpoint

本节取代第 31 节中“Linux device 未执行”的时态。S18 的唯一详细执行规格是 [`W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md`](./W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md)；W1b-5 当前技术事实入口是 [`W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md`](./W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md) 第 22 节。

当前 capture 独立 coverage 为 combined `75.7545%`、statement line `79.1966%`、branch `67.6768%`，RED；retention 为 combined `83.8452%`、line `86.3192%`、branch `76.25%`，但 S18 已冻结 branch `>=80%`，同样 RED。两个脚本的 checked-in security policy、capability manifest、只读 verifier 和 required-node JUnit 绑定尚未实现。

Linux/amd64 Python 3.11.9 只读源码 runner 中，S16+device 为 `9 passed`，proc-fd/source 为 `9 passed`；这关闭本轮 Linux syscall functional 子门禁，不证明原生 x86_64 性能或真实跨 uid。macOS package 因旧 wheelhouse manifest 的 `pyproject_sha256` 与当前源码不一致保持 No-go，禁止手改 hash。当前源码重建 canonical image `sha256:d429650aacae3d9c8a50dfb1ff3e73e065e49eca3016bf3662e5ca2e7d7f5b19` 的断网只读运行 `13 passed, 0 skipped`，只获得 functional canonical implemented-unqualified。

`670 passed, 18 skipped` 是 Linux-only device test 加入前的宿主历史值，现有 PASS/BLOCKED evidence 也早于 S17/S18，均须在最终代码稳定后刷新。跨工作包入口现为：

```text
S18 policy/manifest/verifier
  -> capture + retention 独立 coverage closure
  -> Linux exact-node evidence
  -> macOS package 完整重建
  -> canonical + host/full/static/evidence refresh
  -> W1b-5b 复审
  -> 其余 C1–C4 资源、package、runtime、恢复与 supply-chain 工作包
```

Linux functional 与 canonical functional 为局部 Go；S18、package、W1b-5b 与 Release 整体仍为 **No-go**。5c/5d/5e 继续未授权、未实现。Teams 记录见 [`team-sessions/team-session-2026-09-06-6.md`](./team-sessions/team-session-2026-09-06-6.md)。

### 32.1 S18 可执行重构方案已固化

本节上方数值保留为 S18 首轮 RED。最新 raw 结果已推进到 capture 273 passed、line/branch 90.7280%/84.4660%，retention 244 passed、1 个声明的 Linux-device platform skip、line/branch 93.9320%/89.1089%，macOS package 37 passed、0 skip/fail。Checked-in security policy/manifest/verifier/runner 和 41 个 verifier 合同已存在，但 nested walker 尚需抽取并独立设为 critical，最终双 lane Gate、Linux package、canonical/host/evidence refresh 尚未完成。

架构决策与逐步实施只在 [`W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md`](./W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md) 第 17 节维护：原子 fail-closed seam 要求 line/branch 100%，大型 orchestration/diagnostic aggregator 保留 capability symbol 和 required success/fail nodeid，并受独立全文件 80% 约束。该分层不降低任何门槛。当前仍是 Implementation in progress，Release No-go。

### 32.2 S18 逐能力执行规格入口

第 32 节和第 32.1 节保留首轮RED及R1前状态。当前架构裁决、17项能力的已有证据/缺口/required runner/完成判据、P0测试矩阵、R0.2→R1.2→R6.1执行DAG和回滚规则只在 [`W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md`](./W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md) 第 17.9 节维护。

跨工作包状态不变：S18与W1b-5b未签署，5c/5d/5e未授权，Release No-go。任何后续资源、恢复或supply-chain工作包不得越过第 17.9.7 节DoD。

### 32.3 S18 2026-09-07 执行入口

第 32.2 及 S18 主方案第 17.9 节保留当时计划和 RED。当前 schema v2/toolchain closure、per-runner 语义成对、平台能力证据、剩余 P0/P1、失效矩阵和最终 DoD 只在 [`W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md`](./W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md) 第 17.10 节维护。

恢复时从第 17.10.7 节 A1 开始。S18/W1b-5b/Release 仍 No-go；5c/5d/5e 未授权，不因 current Security checkpoint 自动开放。

### 32.4 S18 P1 与 package 证据分层入口

第 32.3 节和 S18 主方案第 17.10 节保留 S18 的 target-test drift integration 完成前时态。当前跨工作包入口已更新为 [`W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md`](./W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md) 第 17.11 节：target-test drift integration、SRC frozen bytes 和 JUnit canonical grammar 已完成，剩余顺序为 strict xfail/config/events → ABA claim boundary → 最终字节冻结 → Security 双平台刷新 → package 分层 → canonical/host/sealed review → W1b-5b Teams 复审。

### 32.5 S18 P1 hermetic execution 勘误入口

第 32.4 节的 strict xfail/events 实现已形成合同 checkpoint，但对抗审阅证明 pytest 仍可受未绑定 plugin、环境注入、conftest 和同名 package 影响；events outcome 也尚未与 JUnit 逐 node 闭合。当前详细执行入口改为 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)，版本 `S18-P1-PLAN-v1.0`，SHA-256 `027d0350f8d3d2074828a2f2cf6a3645808f7e1bf7fb59ac27081d6857fb8c61`。

后续顺序以该方案的 B0–B15 为准。本总计划不复制测试矩阵和证据路径；在其 DoD 全部有 current evidence 前，S18、W1b-5b 和 Release 仍为 No-go。

### 32.6 S18 P1 当前冻结指针

第 32.5 的 v1.0 指针保留为历史。当前版本 `S18-P1-PLAN-v1.2` 已把最终安全审阅纳入可执行 DAG；权威文件 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) SHA-256 为 `ebc7bd3dcee085ca590d22df4d7fe2bc097a76efc4c463b5ed21e8ba06128683`。

本计划中的 S18 导航文字不作为新的产品规格 ID；Spec Inventory 的 source plan 仍是本文件，禁止用扩大 ignored list 的方式掩盖导航误匹配。

### 32.7 S18 P1 最终架构冻结指针

当前权威版本为 `S18-P1-PLAN-v1.3`，文件 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) SHA-256 `1ee9a126586c4321714a84bd195db0fb36cf4c6925dba06940b5723dbb539429`。该版本明确分离 V2 产品 inventory 与 P1 工作包 traceability，并以 common/per-platform freeze ledger 约束跨平台声明。

第 32.6 及更早指针保留为历史；后续状态只追加，不改写本节 hash。

package 工作包必须继续执行第 29.5 节的双平台标准，但证据强度不得混写。Linux 可以使用 capture-bound package receipt；当前 macOS functional/package lane 若没有等强 sidecar/capture，只能得到 platform-scoped 结果。若 W1b-5b 或后续 Release 要求同强双平台 qualification，必须先补 macOS capture 设计并验证；若本轮接受较窄范围，则必须记录 owner、风险接受者、截止条件和最大声明，不能用一句“已通过”替代该决策。

P1 中 `pyproject.toml`、runner 或 verifier 的修改会使旧 Security Gate 历史化；`pyproject.toml` 同时会使旧 wheelhouse/package artifact 历史化。因此 package、canonical 和 sealed evidence 必须晚于 P1 最终字节冻结。S18/W1b-5b/Release 仍为 No-go，5c/5d/5e 与独立恢复、供应链工作包仍未授权。

### 32.8 S18 P1 v1.4 执行边界

当前权威方案已升级为 `S18-P1-PLAN-v1.4`：[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)，SHA-256 `9cb1a2c534cab265aa43ec0b5e3d651392ba3e9ae4cce81406a834772dd07c68`。新增内容只细化 P1 security execution、evidence 和 traceability，不改变本文件的 V2 产品规格 ID、274 项计数或 qualification 语义。

跨工作包调度从方案第 17.8 节继续：B3c trusted bootstrap/identity → B3d reverify → B3e/B3f → B4a/B4b/B4c → B7/B8。只有完成 common/per-platform freeze ledger 后才能进入双平台 Security、package、canonical、host 和 sealed evidence；任何局部绿色均不得提前开放 W1b-5b、Release 或未授权的 5c/5d/5e。

### 32.9 S18 P1 v1.5 当前执行边界

第 32.8 节保留 v1.4 checkpoint。当前权威方案为 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第 18 节，版本 `S18-P1-PLAN-v1.5`，SHA-256 `59d42eaed5f5323255d510e3f6f4e5bd784c8d84ea329ffb1f01f1098dc4f262`；Teams 裁决 [`team-sessions/team-session-2026-09-07-4.md`](./team-sessions/team-session-2026-09-07-4.md) SHA-256 `91af3b63a6e9ec313c8ad343a71d993aa6e6339bdc5604fe6dfc0b1df12481c1`。

唯一下一步为 B3e-S 稳定 scenario IDs、scenario manifest 与 P1 ID authority；之后按 B3c 语义修正 → B3f-L → B3f-R → 最终 schema 下重放 B3c–B3e → B4b/B4a/B4c → B7/B8 执行。本变更不改变 V2 产品规格 ID、274 项计数或 qualification 语义。

当前 179 个 security contracts 仅为 macOS host checkpoint，不是 Linux、正式 evidence closure 或平台资格化。S18、W1b-5b、Release 继续 No-go，5c/5d/5e 仍未授权。

### 32.10 S18 P1 v1.6 machine authority 边界

第 32.9 节保留 B3e-S 执行前的 v1.5 checkpoint。当前权威方案为 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第 19 节，版本 `S18-P1-PLAN-v1.6`，SHA-256 `c14dc85959176d8e018713fbecaf064ca28c204f16e24e6280635406508217c8`；Teams 记录 [`team-sessions/team-session-2026-09-07-5.md`](./team-sessions/team-session-2026-09-07-5.md) SHA-256 `dd139646c3fbbec6c89ee7e3305e496066fc54a637372beb731bc933249b3293`。

B3e-S stable scenario authority 与首批 P1 current-state record/collection authority 已通过 host contract。本变化不修改 V2 产品规格 ID、274 项计数、ranges、qualification levels/overrides 或 implemented mapping；所有 P1 record 仍为 `unverified/unqualified`。future evidence promotion 必须补逐 kind 独立语义 verifier 和单调 transition ledger，不能只同步修改 authority、inventory 与普通 hash 文件。

后续只从 B3c RECORD/no-replace correction 继续，再执行 B3f-L、B3f-R、final-schema replay 和完整跨平台 hostile evidence。S18、W1b-5b、Release 继续 No-go；5c/5d/5e 仍未授权。

### 32.11 S18 P1 v1.7 B3f L 执行边界

第 32.10 节保留 B3c 收口前的 v1.6 checkpoint。当前权威方案为 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第 20 节，版本 `S18-P1-PLAN-v1.7`，SHA-256 `a1cf11e7e9700a6689959a88d0a6abee5395c582b48a1e881db96013dbd34afc`；Teams 记录 [`team-sessions/team-session-2026-09-07-6.md`](./team-sessions/team-session-2026-09-07-6.md) SHA-256 `ceac0ee80f76681cdbc59fe2e42f119154853fe9344dbd89dc68bb5371c52720`。

B3c 已在当前宿主完成 RECORD entry/no-replace/mode/whole-RECORD mutation 合同，未改变 V2 产品规格 ID、274 项计数、ranges、qualification levels/overrides 或 implemented mapping。B3f-L 是 events producer、runner、verifier、policy 和 contract test 的五文件原子迁移；不得把它写成 pytest 全进程资源有界，也不得提前加入 B3f-R runtime/provenance 字段。

唯一下一步从方案第 20.4 节 B3f-L characterization RED 开始，按第 20.9 节 DAG 继续。当前 host contract、macOS、Linux、package、canonical、host 和 sealed evidence 继续分层，不能互相代签；S18、W1b-5b、Release 继续 No-go，5c/5d/5e 未授权。

### 32.12 S18 P1 v1.8 B3f L partial 边界

第32.11节保留B3f-L执行前的v1.7 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第21节，版本`S18-P1-PLAN-v1.8`，SHA-256 `e33a9a312dcf49096f1af89276074f71beb8f243b1a3a0eabbf7e2a45868ebe4`；Teams记录[`team-sessions/team-session-2026-09-07-7.md`](./team-sessions/team-session-2026-09-07-7.md) SHA-256 `a386eb6a4f38e60b536362ff2a1ab7e40b25500b6040da5d132c23e2e66e1e3d`。

B3f-L policy v2、events v3、runner/verifier等值链和writer unit fault matrix已形成host contract，但第20.7 real-runner authority仍缺失。本变化不修改V2产品规格ID、274项计数或qualification语义。唯一下一步是B3f-L capture/retention双lane真实边界与fault场景；完成前不得进入B3f-R或刷新平台证据。S18、W1b-5b、Release继续No-go，5c/5d/5e未授权。

### 32.13 S18 P1 v1.9 B3f L authority 边界

第32.12节保留authority建立前的v1.8 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第22节，版本`S18-P1-PLAN-v1.9`，SHA-256 `9e688a4edc94b308257f4ef72072e7ca9f06cd0a421db99e213cfbfd21cb8bf9`；Teams记录[`team-sessions/team-session-2026-09-07-8.md`](./team-sessions/team-session-2026-09-07-8.md) SHA-256 `a05f078026ce77feba9e4eddbc6085db3b59088c722099c7c1f184e656086afd`。

B3f-L已冻结67条authority并实现其中10条代表性real-runner records，另57条planned。本变化不修改V2产品规格ID、274项计数、qualification levels或implemented mapping；B3f host authority不得自动晋级P1产品record。只按方案第22.7节关闭57条并完成最终67条同hash replay，随后才进入B3f-R与final-schema replay。S18、W1b-5b、Release继续No-go，5c/5d/5e未授权。

### 32.14 S18 P1 v1.10 B3f L Batch A 边界

第32.13节保留Batch A前的v1.9 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第23节，版本`S18-P1-PLAN-v1.10`，SHA-256 `c46808ba2fd421a20225ab145cf9715bd974576d4e3b8a5b23b166f484c485bd`；Teams记录[`team-sessions/team-session-2026-09-07-9.md`](./team-sessions/team-session-2026-09-07-9.md) SHA-256 `84dfea124230a7027a200fd00a3919d6e2b47c36e9da153767989f4c04ac47b5`。

Batch A关闭18条plugin configure defense-in-depth records，authority为28 implemented/39 planned。它不修改V2的274个产品规格、qualification或P1状态；host mutation record不能代签产品状态。下一步只执行Batch B六条nodeid real-runner，再按第22.10节最终67条同hash replay。S18、W1b-5b、Release继续No-go，5c/5d/5e未授权。

### 32.15 S18 P1 v1.11 B3f L Batch B 边界

第32.14节保留Batch B前的v1.10 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第24节，版本`S18-P1-PLAN-v1.11`，SHA-256 `8cc36822ec315d2e905d057e64121ee94c31bb21245e34578efa53f65ff37d2a`；Teams记录[`team-sessions/team-session-2026-09-07-10.md`](./team-sessions/team-session-2026-09-07-10.md) SHA-256 `b72d2f78957377b5d99d447692c6ce9f2a04b2adc7738b3e4afbde27015fd5d0`。

Batch B关闭6条ASCII/Unicode nodeid byte-bound records，authority为34 implemented/33 planned。它不修改V2产品规格、qualification或P1状态；下一步只执行Batch C四条serialized artifact byte边界，最终仍须67条同hash replay。S18、W1b-5b、Release继续No-go。

### 32.16 S18 P1 v1.12 B3f L Batch C 边界

第32.15节保留Batch C前的v1.11 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第25节，版本`S18-P1-PLAN-v1.12`，SHA-256 `3bd00bca522b46880f75ad06e940865bab8b61241cd97a96d716e42dd0da8200`；Teams记录[`team-sessions/team-session-2026-09-07-11.md`](./team-sessions/team-session-2026-09-07-11.md) SHA-256 `60ffbcbeec2a1dc21610e58982874c1c44b3cecfb21075d3070c02a6aa9bfca1`。

Batch C关闭4条sessionfinish exact-limit防线records，authority为38 implemented/29 planned；它只证明受控collection estimator失效下的host mutation contract，不证明normal producer自然可达8 MiB，也不修改V2产品/P1状态。下一步Batch D十四条pre-publication I/O，最终仍须67条同hash replay。S18、W1b-5b、Release继续No-go。

### 32.17 S18 P1 v1.13 B3f L Batch D 边界

第32.16节保留Batch D前的v1.12 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第26节，版本`S18-P1-PLAN-v1.13`，SHA-256 `7c6beb0c6c5c2fe6e3071d7e4a053dbaf94a4f37e0fff64ee629d9479a17eeef`；Teams记录[`team-sessions/team-session-2026-09-07-12.md`](./team-sessions/team-session-2026-09-07-12.md) SHA-256 `9bd312ae5da31ef2db556cca6063d76cdeae68fa1f33fd57ee0d0dd1486b8dff`。

Batch D十四条只构成pre-publication writer host mutation checkpoint，authority为52/15/67；不代签B3f-L闭合、B3f-R、平台或pytest全进程资源边界。下一步只执行Batch E六条受保护existing/preexisting/race身份合同。

### 32.18 S18 P1 v1.14 B3f L Batch E 边界

第32.17节保留Batch E前的v1.13 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第27节，版本`S18-P1-PLAN-v1.14`，SHA-256 `c273c92020eb3f9bc47d6537d1fce10513221af5119f9d69f4e10e23a098eae5`；Teams记录[`team-sessions/team-session-2026-09-07-13.md`](./team-sessions/team-session-2026-09-07-13.md) SHA-256 `781823e419f0f4bd4841c8adc40286baea9928a02629a12f5358ce657a5b80b5`。

Batch E六条只构成protected-object和真实link/EEXIST race的host mutation checkpoint，authority为58/9/67；不修改V2产品/P1状态。下一步只执行Batch F六条post-publication错误分类，最终仍须67条同hash replay。

### 32.19 S18 P1 v1.15 B3f L Batch F 边界

第32.18节保留Batch F前的v1.14 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第28节，版本`S18-P1-PLAN-v1.15`，SHA-256 `47e48deb8260e7171e23cfd8bd8adc7e4e6bf578a2196595588ad739aba1ecfb`；Teams记录[`team-sessions/team-session-2026-09-07-14.md`](./team-sessions/team-session-2026-09-07-14.md) SHA-256 `065d19d9455c1429a82cb8509ede5f94e906050a51bc9d1dd0b2847b62771da1`。

Batch F六条只构成post-publication commit-uncertain host mutation checkpoint，authority为64/3/67；不修改V2产品/P1状态。下一步只执行Batch G exact syscall-order，然后Batch H，最终仍须67条同hash replay。

### 32.20 S18 P1 v1.16 B3f L Batch G 边界

第32.19节保留Batch G前的v1.15 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第29节，版本`S18-P1-PLAN-v1.16`，SHA-256 `30b9df622cf930cb36e7a250193dd7386a379db9f4197d8d2e667f51b12ea248`；Teams记录[`team-sessions/team-session-2026-09-07-15.md`](./team-sessions/team-session-2026-09-07-15.md) SHA-256 `f70cd4737f8705996936cafe2345b7d52bf4919a2a7fa301e5e4f414cd298178`。

Batch G两条只构成冻结events writer的record-only syscall-order host checkpoint，authority为66/1/67；不修改V2产品/P1状态。下一步只执行Batch H，之后最终67条同hash replay仍不可省略。

### 32.21 S18 P1 v1.17 B3f L Batch H 边界

第32.20节保留Batch H前的v1.16 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第30节，版本`S18-P1-PLAN-v1.17`，SHA-256 `a12aff9eaa2e3bb86f21efb7833d079bb4b82bb51dcb7ec2bf83e98ac6298398`；Teams记录[`team-sessions/team-session-2026-09-07-16.md`](./team-sessions/team-session-2026-09-07-16.md) SHA-256 `b9943d2f5e5688765a092d52b9f95394631ef5f342cf5325f05530333698a76c`。

Batch H只构成当前host上existing-attempt input guard的runner contract，authority为67/0/67；它不修改V2的274个产品规格、qualification或P1状态，也不证明B3f-L已完成最终同hash replay。下一步只执行全部67条fresh replay与独立审计，不得自动晋级产品状态。

### 32.22 S18 P1 v1.18 B3f L closure与R0边界

第32.21节保留final 67前的v1.17 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第31节，版本`S18-P1-PLAN-v1.18`，SHA-256 `a6250365667cee35caf2784c68a96932e3336b57328e607fcc6790e47e84f488`；Teams记录[`team-sessions/team-session-2026-09-07-17.md`](./team-sessions/team-session-2026-09-07-17.md) SHA-256 `51041766bb0723257b62adf00803fd4926faeabf47ca65c14169df5e7b349021`。

B3f-L host contract已完成final 67同hash replay，但不修改V2产品274项、P1实现/验证/qualification状态。下一步B3f-R0只建立named runtime与PEP 376合同RED；runtime schema迁移和最终schema replay尚未发生，不得自动提升产品状态。

### 32.23 S18 P1 v1.20 B3f R1b执行入口

第32.22节保留R0前的v1.18 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第33节，版本`S18-P1-PLAN-v1.20`，SHA-256 `5b14134df98e68b5ed092262d5b43cf521b8156cee791dfb5c14719da52267f2`；Teams记录[`team-sessions/team-session-2026-09-07-19.md`](./team-sessions/team-session-2026-09-07-19.md) SHA-256 `271caf7e77870a024bf7d4b6a4d35aec5142bf872d3cf422d3c9ceba494e109a`。

R1a已在补充RED/GREEN与独立QA后关闭两个阻塞P1，允许开始R1b exact15 identity producer foundation；仍不修改V2产品规格ID、274项计数、P1 implemented/verification/qualification状态。R1b不得发布真实identity v2、运行真实security runner或提前迁移policy/verifier/runner schema；R2才执行policy v3至Gate v5的原子消费者迁移。

### 32.24 S18 P1 v1.21 R1b QA P1 执行边界

前一入口保留为历史 checkpoint。当前权威方案为 [S18 P1 执行方案](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第34节（尤其34.6至34.10），版本 `S18-P1-PLAN-v1.21`，整份 SHA-256 `cc3705d97e7b9d6c75b0e91059f0ba9d88d5f1fe91de836290553d0677f457e7`；[Teams 20](./team-sessions/team-session-2026-09-07-20.md) SHA-256 `f5a1822407d8523093ada70700520cc9c964379be6c3f6db92d4cf1c3055e63a`。

R1b 定向回归通过，但独立 QA 发现 lock pathname 同内容换 inode 未拒绝、文件身份字段接受根路径两个 P1，当前 **未验收**。下一次执行从第34.8节局部 test-first 修复与新 hash 独立 QA 开始，不能跳到 R2。本次仅持久化方案，不修改代码或消费资格；产品/P1计数不晋级。S18、W1b-5b、Release 继续 No-go，不执行 W1b-5c/5d/5e。后续完整 DAG、测试用例、原始证据失效处理均以权威方案为准。

### 32.25 S18 P1 v1.22 R1b 验收与 R2 执行入口

前一入口保留旧 QA P1 checkpoint。当前权威方案为 [S18 P1 执行方案](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第35节，版本 `S18-P1-PLAN-v1.22`，整份 SHA-256 `6b6c29dedb130396f1ab5ec6c7e4bda9637fecf65ce3892e373d8bac1ab48fc8`；[Teams 21](./team-sessions/team-session-2026-09-07-21.md) SHA-256 `069f7663cded80d73a3f37b52807fd121a610c9dc3b99e8a16a2ab9ced2dc67a`。

两个 R1b P1 已在新 hash 下经 RED/GREEN、架构与独立 QA 关闭；exact15、R1a10 unique、legacy10 均通过，policy-v3 仍是唯一预期 RED。R1b producer foundation 完成，不代表真实 runner、identity-v2 publication、Linux/双平台或 Release qualification。下一步先解决第35.11节草案冲突，冻结 R2 exact 契约后执行第35.5节原子 cutover；第35.9至35.10节字段/十二节点仍为 proposed/planned，不计为实现。S18、W1b-5b、Release 继续 No-go，inventory不晋级，W1b-5c/5d/5e不执行。

### 32.26 S18 P1 v1.23 R2 进行中执行入口

当前工作入口转至 [S18 P1 执行方案](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第36节和 [Teams 22](./team-sessions/team-session-2026-09-07-22.md)。第35节R1b最终hash仅为历史已验收基线；R2正在原子迁移，代码与文档尚未最终封板，因此本入口不提供冒充完成的固定hash。

先核对第36节最后checkpoint与真实worktree/进程状态后续接。不得复用旧R1b绿色、初始15-node scaffold RED或部分schema更改代签R2。真实双lane、final67和平台qualification仍待后续，inventory不晋级；S18、W1b-5b、Release继续No-go，5c/5d/5e不执行。

### 32.27 R2 方案本地保存与待独立 QA 入口

最新恢复点为 [S18 P1 执行方案](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第36.33–36.34节；实现已停写停测并交锁，九文件候选快照已核对。精确测试选择、证据索引与hash已保存到docs，原始测试产物仍在临时目录；本次不是完整证据归档。

R2尚未独立验收；下一步为同快照独立QA，不是R3。四项入口继续WIP，S18、W1b-5b、Release继续No-go；详情与验收门仅以权威方案最新checkpoint为准，不从旧绿色或聊天摘要推断完成。

### 32.28 R2 递归修复后的当前状态

最新恢复点为 [S18 P1执行方案](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第36.40节，新九文件清单位于第36.39节。深层JSON候选解析的P1已最小修复，主代理fresh47+35回归通过（去重79节点）；最终独立QA任务被执行环境中止，没有验收结论。独立验收门仍保留，不能据主代理复验启动R3；S18、W1b-5b、Release继续No-go。R3仅完成失败profile与隔离前置设计，不是执行或平台资格证据。

### 32.29 R2 独立验收完成与 R3 正常对照

2026-09-09 最新入口为 [S18 P1 执行方案](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第36.41–36.42节。R2冻结九文件已通过独立源码审阅与79个唯一节点fresh回归；主代理重算57份原始证据并通过42项文档治理。旧“最终独立QA缺失”状态保留为历史，当前R2合同已验收。R3正常macOS对照已实现：最终system层2项通过，真实capture282项和retention257项通过，两Gate PASS；retention有1个声明的平台不适用skip。完整异常矩阵、R4、平台与发布资格仍待完成。产品inventory不晋级，S18/W1b-5b/Release继续No-go。


## 32.30 2026-09-12 用户交付决定：文档与开发分支推送

用户明确要求异常场景暂不全覆盖，优先完善技术文档、系统说明、使用指南与 README 顶部 AI 使用提示词，并推送远端。本次提交/推送已有用户授权，早期“等待提交批准”记录保留为历史，不阻止本次开发快照交付。

当前权威入口为[文档导航](README.md)及[项目状态](PROJECT_STATUS.zh-CN.md)。保留 R2 冻结验收与 R3 macOS 正常对照证据；不扩大其结论、不补跑完整异常矩阵、不更改原始阈值。未完成事项标记暂缓/未验证，S18 / W1b-5b / Release No-go 不变。本轮只向 `improve-inference-reliability` 开发分支提交及推送，不覆盖远端 main，不发布发行版。
