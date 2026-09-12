# AI 重构交接文档 Legacy 基线与 v2 现状

> **当前恢复入口：本文件第 15.23 节与 `S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md` 第 19 节。** 下方第 15.22/15.14/15.13 阅读提示保留为历史导航，不得作为当前起点。

> v2 的目标架构、分阶段实施、逐条测试规格、当前证据和发布门禁见 [`AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md`](./AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md)。本文第 0–14 节保留 `db8e714` 的重构前事实快照；当前 v2 实现先读第 15.14 节，再读 S18 专项方案第 17 节和主计划第 32 节。

> 本文面向后续接手本仓库重构工作的 AI 或维护者。历史部分描述的是**基线提交的可观察实现**，不是当前工作树、产品路线图或模型效果承诺。不得根据历史入口已被删除而恢复 v1 shim，也不得把 dirty-worktree 功能证据写成 release 证明。

## 0. 文档基线与证据规则

| 项目 | 值 |
|---|---|
| 仓库 | `track-lrc-align` / `AI-auto-lrc` |
| 核验分支 | `improve-inference-reliability` |
| 核验提交 | `db8e714` |
| 核验日期 | 2026-09-04 |
| 主要支持范围 | 推理 CLI 与 `process()` Python API |
| 明确不在支持范围 | 当前 checkout 中的训练与评估链路 |

事实优先级如下：

1. 当前提交中的可执行源码；
2. 对该行为有直接断言的自动化测试；
3. 本文；
4. README、注释和历史脚本。

若本文与更新后的源码或测试冲突，以源码和测试为准，并同步更新本文。测试通过只表示对应断言仍成立，不表示真实模型质量、部署环境或许可证合规已经得到证明。

### 0.1 状态标记

| 标记 | 含义 |
|---|---|
| **[已实现]** | 可从正式 CLI 或 `process()` Python API 到达的现有行为 |
| **[受测试]** | 该条所述能力合同有直接自动化断言；不代表真实模型质量或端到端部署已验证 |
| **[部分受测试]** | 只有该能力的部分关键行为有直接自动化断言；未覆盖项必须在第 10 节和事实索引中列明 |
| **[未接入]** | 仓库中有代码，但正式歌词对齐主链不调用它 |
| **[不可运行/不自包含]** | 当前 checkout 缺少模块、数据或外部资产，不能作为现成能力运行 |
| **[环境依赖]** | 依赖模型文件、Git LFS、当前工作目录、网络、设备或第三方运行环境 |
| **[待确认]** | 无法仅凭仓库可靠判断，需要维护者或资产所有者补证 |
| **[建议]** | 面向未来重构的原则，不是当前行为 |

### 0.2 阅读顺序

后续 AI 建议按以下顺序阅读：

1. [第 15.13 节当前恢复入口](#1513-s18-qualification-当前恢复入口)；
2. [S18 安全资格与证据收口执行方案](./W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md)；
3. 主计划第 32 节和 W1b-5 执行计划第 22 节；
4. 只有处理 Legacy 兼容行为时，才回读第 1–14 节的能力总览、调用链、外部接口和数值协议。

---

## 1. 能力总览

当前仓库的可交付定位是：接收歌词文本与音频文件，执行语言转写、音频预处理、声学推理和强制对齐，产出 LRC。仓库**不是**开箱可训练、可评估的完整机器学习工程。

### 1.1 能力矩阵

| 编号 | 能力 | 状态 | 正式入口 | 主要输入 | 主要输出 | 核心依赖 | 关键边界 |
|---|---|---|---|---|---|---|---|
| C01 | [CLI 歌词音频对齐](#c01) | [已实现][部分受测试][环境依赖] | `main.py::cli()` | 歌词文件路径、音频路径、CLI 参数 | 终端内容、标准 LRC 文件 | C02–C08 | 参数解析和标准化函数受测试；完整 CLI 与真实模型端到端未测试 |
| C02 | [Python 推理 API](#c02) | [已实现][部分受测试][环境依赖] | `t2l.t2l::process()` | `list[str]`、音频路径、模型/输出选项 | LRC 字符串；可选直接写文件 | C04–C08 | 格式早失败和 UTF-8 写出受测试；完整真实推理未测试 |
| C03 | [歌词文件编码探测](#c03) | [已实现] | CLI 调用 `ext.t2lutils::__get_file_encoding()` | 歌词文件路径 | 编码名称 | `chardet` | 只属于 CLI 文件读取前置层；探测结果不保证正确 |
| C04 | [歌词清理、行组织](#c04) | [已实现] | `process()` | 原始歌词行 | 可转写行、显示词片段 | 正则、C05 | 无直接行为测试；仅清除特定行首标签；数字处理仍有 FIXME |
| C05 | [行级语言识别与多语言转写](#c05) | [已实现][环境依赖] | `t2l.phonetic::phonetize()` | 单行文本 | `(显示文本, 拉丁转写)` 序列 | fastText、pypinyin、pykakasi、kroman、cyrtranslit | 整行选一种语言；混合语言无 token 级保证 |
| C06 | [音频解码、回退与可选人声分离](#c06) | [已实现][部分受测试][环境依赖] | `preprocess_audio()` / `separate_vocals()` | 音频文件路径 | channel-first tensor、采样率 | torchaudio、librosa、julius、Demucs | 回退/异常/inference mode 受测试；真实文件和模型未测试 |
| C07 | [声学模型推理](#c07) | [已实现][部分受测试][环境依赖] | `t2l.mtl.wrapper::align()` | 音频 tensor、phone 序列及索引 | phoneme posterior 派生的词帧边界 | PyTorch、checkpoint | fake model 覆盖输入/推理边界；真实 checkpoint 未测试 |
| C08 | [DTW/BDR 对齐与 LRC 生成](#c08) | [已实现][部分受测试] | `alignment()` / `alignment_bdr()` / `gen_lrc()` | posterior、phone、半开区间索引、显示歌词 | 词帧区间、增强或行级 LRC | NumPy/PyTorch | 对齐器有直接测试；`gen_lrc()` 及其截断降级无直接测试 |
| C09 | [CLI 增强 LRC 转标准 LRC](#c09) | [已实现][受测试] | `main.py::to_standard_lrc()` | 含 `<MM:SS.mmm>` 标签的 LRC | 移除词时间戳后的 LRC | 正则 | 只匹配当前固定毫秒格式 |
| C10 | [领域错误分类](#c10) | [已实现][部分受测试] | `TxtValueError`、`AudioValueError`、`AlignmentValueError` | 各阶段非法状态 | 可区分的异常 | Python 异常链 | 音频/对齐错误和第三方传播受测试；`TxtValueError` 无直接测试 |
| X01 | [音频语言识别](#x01) | [未接入][环境依赖] | `t2l/slid.py` 独立函数 | 16 kHz 音频 tensor | Whisper 语言概率 | faster-whisper、可选 Demucs | 不被 CLI 或 `process()` 调用；依赖内部 API |
| X02 | [增强 LRC 转 JSON 结构](#x02) | [未接入] | `ext/lrc2json.py::lrc_to_json()` | 增强 LRC 文本 | Python token 字典嵌套列表 | 正则 | 不返回 JSON 文本；无正式入口、无测试、存在越界与解析风险 |
| X03 | [繁体转简体](#x03) | [未接入] | `ext/traditional_to_simplified.py::t2s()` | 字符串 | 简体字符串 | OpenCC | 主链不会自动繁转简 |
| N01 | [模型训练](#n01) | [不可运行/不自包含] | `t2l/mtl/train.py` | 外部数据、配置、模型 | checkpoint（意图） | DALI/Jamendo/HDF 等 | 缺少 `t2l/mtl/test.py`、未声明依赖和外部数据 |
| N02 | [模型评估](#n02) | [不可运行/不自包含] | `t2l/mtl/eval.py`、`eval_bdr.py` | 外部数据与 checkpoint | 评估结果（意图） | 同上 | 当前 checkout 无法形成自包含执行链 |

### 1.2 逐项能力卡

以下能力卡把 1.1 的每一项展开为可交接、可复核的合同。卡片中的“成功”只表示函数或命令按当前控制流完成；凡涉及模型效果的能力，成功返回都不等价于时间轴准确或歌词内容正确。

<a id="c01"></a>

#### C01 CLI 歌词音频对齐 [已实现][部分受测试][环境依赖]

| 项目 | 当前细节 |
|---|---|
| 入口与调用 | `python main.py <lrc_file> <music_file> [选项]`；`main.py::__main__` 调用 `cli()`，参数合同见 3.1。 |
| 前置条件 | 两个位置参数可读；Python 依赖可导入；从仓库根目录运行时才能按现有相对路径找到 checkpoint 与 `lid.176.ftz`；默认人声分离还要求 Demucs 权重可取得。 |
| 处理步骤 | argparse 校验参数 → C03 探测编码 → `readlines()` 得到原始行 → C02 `process()` → 将增强 LRC 打到 stdout → C09 删除词时间戳 → 创建 `out_dir` → 以音频 basename 写标准 LRC。 |
| 成功输出与副作用 | stdout 至少包含增强 LRC 和保存路径，verbose 默认开启时还混有设备、模型、推理进度与分数；写入 `<out_dir>/<audio_basename>.lrc`，已有同名文件直接截断覆盖。 |
| 失败与原子性 | argparse 非法参数以退出码 2 结束；文件、编码、依赖、模型、设备和对齐异常均未被 CLI 统一捕获。增强 LRC 已打印后若目录创建或文件写入失败，不会回滚 stdout，也没有临时文件/原子替换。 |
| 直接证据 | parser 默认值/取值范围与 C09 受测试；完整 `cli()`、退出码、真实文件读取、目录创建和覆盖行为没有端到端测试。 |
| 重构保护点 | 同时核对“终端增强 LRC”和“磁盘标准 LRC”两个产物；若要提供纯 stdout、原子写或结构化退出码，应作为显式 CLI 版本变更。 |

<a id="c02"></a>

#### C02 `process()` Python 推理 API [已实现][部分受测试][环境依赖]

| 项目 | 当前细节 |
|---|---|
| 入口与调用 | `from t2l.t2l import process`；事实签名见 3.2。代码没有专门类型层，`txt_lines` 只要可迭代且元素支持 `strip()` 即可进入处理。 |
| 前置校验 | 仅 `format == 'lrc'` 在任何音频工作前显式校验；`line_only`、`vocalize`、模型 tuple 与 Demucs index 在 API 层没有统一类型/范围校验。 |
| 处理步骤 | C04 清理和组织歌词 → C05 转写 → C06 解码/可选分离 → G2P 生成 phone 与索引 → C07 模型推理 → C08 对齐和 LRC 生成 → 可选 UTF-8 写文件。 |
| 成功输出与副作用 | 返回 LRC `str`；`out_file` 非空时以 UTF-8 覆盖写入与返回值完全相同的内容。首次转写/G2P、模型加载和 Demucs 可能初始化全局对象、占用设备或触发第三方下载；verbose 可写 stdout。 |
| 路径与写出 | 不创建 `out_file` 的父目录，不执行标准 LRC 转换，也不采用 CLI 的 basename 命名规则。`out_file` 写失败发生在完整推理之后。 |
| 失败模型 | 无有效歌词抛 `TxtValueError`；音频双 decoder/空数据抛 `AudioValueError`；非法对齐输入抛 `AlignmentValueError`；格式/模型/音频 shape 使用普通 `ValueError`；其余 I/O、导入、checkpoint、Demucs、CUDA 异常原样传播。 |
| 直接证据 | 已测试格式早失败和 UTF-8 写出相等性；完整歌词解析、多语言、真实音频、真实 checkpoint、返回 LRC 时间准确性均未测试。 |

<a id="c03"></a>

#### C03 歌词文件编码探测 [已实现]

| 项目 | 当前细节 |
|---|---|
| 入口 | `ext.t2lutils::__get_file_encoding(path)`；名称虽以双下划线开头，但它是模块级函数，由 CLI 直接调用。 |
| 输入读取 | 使用 `open(path, 'rb')`，随后调用 `readlines()`；因此即使 detector 提前结束 feed，文件内容仍已一次性读入内存。 |
| 判定流程 | 按行 feed `UniversalDetector`；只有 `detector.done` 且已处理至少 4 行时才提前停止；结束后 `close()` detector。 |
| 规范化输出 | 检测结果 `GB2312` 被改成 `GBK`；无可用 encoding 时返回字符串 `utf8`；其他名称原样交给 Python `open(..., encoding=...)`。 |
| 副作用与失败 | 记录一次 encoding info 日志；文件不存在/无权限等 I/O 异常直接传播。函数不试解码、不验证置信度，也不保证候选编码能成功读取全文。 |
| 范围与证据 | 只服务 CLI，C02 调用方必须自行解码；无直接自动化测试。重构时如改成流式探测或置信度门槛，应补充短文件、空文件、GB2312/GBK 和误判样例。 |

<a id="c04"></a>

#### C04 歌词清理、行组织 [已实现]

| 项目 | 当前细节 |
|---|---|
| 输入单位 | 对 `txt_lines` 逐元素 `strip()`，所以原始行首尾空白和换行符不会作为原样文本保留。 |
| 标签清理 | 先用 `^\[[\d.:]+\]\s*` 删除一个数字/点/冒号时间标签，再用 `^\[[a-zA-Z]{2}:.+\]\s*` 删除元数据。第二条的 `.+` 是贪婪匹配：以元数据开头时可能跨过后续 `[...]` 一并删除到本行最后一个右方括号，而不只是删除一个标签。 |
| token 形成 | C05 返回 `(显示片段, 拉丁转写)`；若转写含非 `[a-z'~]` 字符，就按空白、常见标点和数字再次切分。代码用 `wd.find(ph, widx0)` 回配显示切片，但未显式处理 `find()` 返回 `-1`，复杂混合文本可能产生不直观切片。 |
| 无 phone 文本 | 尾部无 phone 字符尽量附到当前最后一个显示 token；本行没有有效 token 且已有有效行时，原行以 `\n` 追加到上一行最后一个 token；首个有效行之前的内容累计为无时间戳前缀。 |
| 空/无效歌词 | 空行也会进入上述未处理文本累计/追加逻辑；所有行最终都无有效 token 时抛 `TxtValueError`。数字被切分/附着，没有稳定的数字朗读合同。 |
| 输出协议 | 产生顺序对应的 `phonetics: list[list[str]]`、`lines: list[list[str]]` 和 `pre_lines_unprocessed: str`；`phonetics` 与 `lines` 的 token 数和顺序必须保持一致。 |
| 证据与重构点 | 没有直接行为测试。拆分 parser 前应先为标签顺序、全空输入、前导/中间无效行、数字、重复 token 和混合文字建立 characterization tests。 |

<a id="c05"></a>

#### C05 行级语言识别与多语言转写 [已实现][环境依赖]

| 项目 | 当前细节 |
|---|---|
| 加载时机 | `process()` 通过薄包装延迟导入 `t2l.phonetic`；该模块导入时创建 `pykakasi` 对象并从 CWD 同步加载 `lid.176.ftz`。直接导入该模块则立即发生加载。 |
| 输入规范化 | `q2bs()` 将全角 ASCII 和一组中文标点映射为半角；完全 ASCII（包括空字符串）直接返回 `[(原文, 原文)]`，不调用 fastText。 |
| 语言选择 | 整行只选一个分支，优先级为日文假名 → CJK 汉字 → Hangul → Cyrillic → fastText top-1；置信度低于 0.5 只 warning，不拒绝。 |
| 分语言行为 | 中文用 `lazy_pinyin` 后按字符回配；日文用 Hepburn 字段并过滤非 `[a-z'~]`；韩文用 `kroman` 和位置搜索重建；英文按空白切分并保留显示分隔区域；俄文按空格位置配对转写。 |
| 输出 | 返回顺序化 `(显示片段, 拉丁转写)` 列表；随后所有转写仍交给英语 `g2p_en`，不是语言原生 phone。 |
| 失败/降级 | fastText 返回非五语标签时记录 error 并返回空列表；俄文原文词数少于转写词数时可能 `IndexError`；韩文和中文回配依赖字符位置假设；混合行由最先命中的文字系统支配。 |
| 证据与重构点 | 无直接测试。不能把“存在五个分支”升级为准确率承诺；替换转写库必须与 C07 checkpoint 的 41 类 phone 空间联合验证。 |

<a id="c06"></a>

#### C06 音频解码、回退与可选人声分离 [已实现][部分受测试][环境依赖]

| 项目 | 当前细节 |
|---|---|
| 直接解码 | `preprocess_audio()` 先调用 `torchaudio.load()`；成功结果保留 channel-first 多声道。仅 `RuntimeError`/`OSError` 或空 tensor 触发 librosa 回退。 |
| 回退差异 | `librosa.load()` 默认 `mono=True`，所以回退路径会混成一维单声道，再升维为 `[1, samples]`；指定 `sr` 时 librosa 可在读取时重采样，torchaudio 成功路径则由 Julius 后续重采样。两条成功路径的声道语义不同。 |
| 领域错误 | librosa 的常见解码/I/O/值/EOF 错误被包装为 `AudioValueError`，cause 是最后一次异常，并在消息中附带先前 torchaudio 错误；不在捕获列表中的 decoder 异常原样传播。 |
| Demucs 模型 | 字符串名称经 `get_model()` 加载，`0..3` 硬编码选择 bag 子模型，否则保留 bag，并移动到设备、设为 eval；bag 实际不足 4 个时仍可能 `IndexError`。传入预加载对象时 `demucs_idx` 被忽略，调用方负责设备、eval 状态和 source 合同。 |
| 分离流程 | 原采样率解码 → 按模型采样率重采样 → mono 复制为双声道 → `torch.inference_mode()` 调用 Demucs → 按名称选择 `vocals` → 再重采样到 22,050 Hz。没有幅度归一化。 |
| 输出与边界 | 返回 `[channels, samples]` tensor 和采样率；模型无 `vocals` source 时 `vocals` 保持 `None`，会在重采样或 C07 中以非领域异常失败。Demucs/下载/CUDA/OOM 不重分类为音频值错误。 |
| 直接证据 | fake decoder/model 覆盖回退、异常链、第三方异常传播和 inference mode；真实 codec、多声道差异、重采样数值、权重下载、source 缺失与音质均未测试。 |

<a id="c07"></a>

#### C07 声学模型加载与推理 [已实现][部分受测试][环境依赖]

| 项目 | 当前细节 |
|---|---|
| 模型选择 | 字符串方法支持 `Baseline`、`MTL` 及追加 `_BDR` 的两种变体；也可传 `(ac_model, bdr_model, model_type, bdr_flag, device)` 五元 tuple，tuple 结构不做显式 schema 校验。 |
| 资产与设备 | loader 按 CWD 读取 `./checkpoints/checkpoint_{Baseline|MTL}` 和可选 `checkpoint_BDR`；`cuda=True` 仅在 `torch.cuda.is_available()` 时生效，CPU 加载使用 `map_location='cpu'`。 |
| 音频输入 | 接受 `[samples]` 或 `[channels, samples]`，拒绝空维度/空样本/其他 rank，统一转 `float32`，固定只取首声道。预加载 tuple 的 device 与模型实际位置由调用方保证。 |
| 特征与前向 | 22,050 Hz Mel（128 bins、FFT 512）→ CNN/Residual CNN → `(2,3)` 池化 → Linear → 3 层 BiLSTM → classifier；整个声学和可选 BDR forward 位于 `torch.inference_mode()`。第 1 层 LSTM 使用 `batch_first=True`，第 2/3 层却为 `False`，当前 tensor 没有在层间转置；这是 checkpoint 所基于的现状，不能在普通清理中静默“修正”。 |
| posterior | Baseline 直接得到 41 类；MTL 先得到 `41 × 47` logits，再沿 melody 维求和为 41 类，随后 `log_softmax`；再加入 PyTorch RNG 生成的极小正噪声并取 log。 |
| 返回与复杂度边界 | 调用 C08 后返回 `(word_align, words)`，其中 `words` 只是入参透传，正式 `process()` 传入 `None` 且忽略第二项。模型完整输出帧数被用于对齐，不按原 waveform 长度额外截断。 |
| 直接证据 | fake model 测试覆盖首声道、float32、一维/非法 shape、完整帧数、inference mode、BDR CPU NumPy 边界和 quiet 模式；真实 state dict、CPU/GPU 一致性、资源占用和数值质量未测试。 |

<a id="c08"></a>

#### C08 DTW/BDR 对齐与 LRC 生成 [已实现][部分受测试]

| 项目 | 当前细节 |
|---|---|
| 对齐输入 | `song_pred[audio_frames, classes]`、phone 列表、word `[start,end)` 索引；BDR 另收 boundary curve 与 line-start phone。blank 固定为 40，未知 phone 也映射到 40。 |
| 前置校验 | 至少 41 类、至少 1 个 phone、帧数至少 `phone_count + 2`、word 区间非空/有序/不重叠/界内、BDR 长度足够、line-start 界内。当前不校验索引必须为整数，也不检查 posterior/BDR 是否有限值。 |
| 普通 DTW | 在传入 tensor 的设备上构造约 `audio_frames × (2*phones+1)` 的 DP/回溯状态，复杂度和内存随音频帧与 phone 数乘积增长；路径耗尽时会 warning 并为剩余词补最后帧零长度区间。 |
| BDR DTW | wrapper 先转 CPU NumPy，再用 Python/NumPy 双层循环；在 line-start phone 转移上叠加 `log(boundary) * 0.8`。它与普通 DTW共享输入合同，但回溯取词没有同等的 `path_i` 越界保护。 |
| 对齐输出 | `word_align` 为与 word 顺序对应的 `[start_frame,end_frame]`，另返回累计 score；它们仍是帧坐标/实现类型，不是秒或稳定序列化 API。 |
| LRC 生成 | 每行首词 start frame 生成 `[MM:SS.mmm]`；增强模式在每个可用 token 前加 `<MM:SS.mmm>`；固定乘 `256/22050*3`，时间戳截断到毫秒，最终字符串无额外尾换行。 |
| 不足时降级 | 行开始前已无对齐结果则 warning 并停止后续行；行内耗尽则保留余下文本但不再加词时间戳。返回字符串不携带结构化 incomplete 标记。 |
| 直接证据 | 对齐输入、半开区间、普通/BDR 最小路径受测试；DP 性能、非有限值、浮点索引、BDR 回溯边界、score 语义和 `gen_lrc()` 降级均未直接测试。 |

<a id="c09"></a>

#### C09 增强 LRC 转标准 LRC [已实现][受测试]

| 项目 | 当前细节 |
|---|---|
| 入口 | `main.py::to_standard_lrc(enhanced_lrc)`；纯字符串转换，不读写文件。 |
| 算法 | 全局执行 `re.sub(r'<\d+:\d{2}\.\d{3}>', '', text)`；分钟可任意位，秒固定两位，小数固定三位。 |
| 保留/删除 | 删除任何位置符合模式的尖括号标签，保留方括号行标签及全部其他字符；它不解析 LRC 行结构，也不验证时间范围、排序或标签与 token 的对应关系。 |
| 边界 | `<1:2.3>`、`<01:02.34>`、带空格/符号或其他精度的标签不会删除；正文中偶然出现同形字符串也会被删除。 |
| 使用关系 | CLI 总会对 C02 返回值调用它后写磁盘；`process(out_file)` 不调用它。 |
| 直接证据 | 已测试长分钟 `<100:01.234>` 和多标签删除；没有属性测试或畸形标签测试。 |

<a id="c10"></a>

#### C10 领域错误分类与诊断传播 [已实现][部分受测试]

| 项目 | 当前细节 |
|---|---|
| 公共类型 | `TxtValueError`、`AudioValueError`、`AlignmentValueError` 都继承 `ValueError`，但没有共同的项目专用基类，也没有稳定错误码/结构化字段。 |
| 歌词错误 | 仅“所有行处理后都无有效 token”明确抛 `TxtValueError`；逐行转写内部的 `IndexError` 等不会自动转成歌词错误。 |
| 音频错误 | 双 decoder 失败或最终音频为空抛 `AudioValueError`；双失败保留 librosa cause，并把 torchaudio 失败文本拼入消息。非法音频 rank 在 C07 抛普通 `ValueError`。 |
| 对齐错误 | shape、最短帧数、word/line 索引与 BDR 长度前置问题抛 `AlignmentValueError`；DP 内部越界/数值问题仍可能是原生异常。 |
| 原样传播 | 文件/Unicode、依赖导入、fastText、checkpoint/state-dict、Demucs 下载、CUDA/OOM、输出写入等不重分类；CLI 不做最终异常到退出码的映射。 |
| 直接证据 | 音频异常链、部分第三方传播和对齐输入错误受测试；`TxtValueError`、CLI 展示、模型加载错误及写文件错误没有直接测试。 |
| 重构保护点 | 若新增统一错误层，至少保留阶段、原始 `__cause__`、输入错误与环境/设备错误的区别，并避免把部分 LRC 结果误标为完整成功。 |

<a id="x01"></a>

#### X01 音频语言识别 [未接入][环境依赖]

| 项目 | 当前细节 |
|---|---|
| 入口与可达性 | `t2l.slid::detect_language()` 和手工 `test_slid()`；C01/C02 不导入或调用它。 |
| 输入合同 | 注释要求 16 kHz tensor；实现取所有前导维的 index 0 作为 mono，并调用 `.cpu()`，所以普通 list/NumPy、空 shape 或错误采样率没有兼容处理。 |
| 模型路径 | 字符串模型名会实例化 `WhisperModel`，CUDA 用 `int8_float16`、CPU 用 `int8`，可能下载权重；预加载对象需暴露内部 feature extractor、encoder 和 model。 |
| VAD 行为 | 默认先取 speech chunks，按 `duration_after_vad / duration` 计算保留比例；低于阈值返回 `[(None, 1-ratio)]`，空音频可能除零。 |
| 输出 | 正常返回 `(language_code, probability)` 列表；直接调用 faster-whisper 内部 API 并剥离 token 包装，不提供稳定版本适配层。 |
| 风险与证据 | requirements 与 Pipfile 锁定的 faster-whisper/ctranslate2 版本不同；无自动化测试，手工函数会加载真实模型和文件并打印。正式化前需明确 16 kHz 强制、空音频、VAD sentinel 和版本合同。 |

<a id="x02"></a>

#### X02 增强 LRC 转 JSON 结构 [未接入]

| 项目 | 当前细节 |
|---|---|
| 入口与真实返回 | `ext.lrc2json::lrc_to_json(text)`；名称含 JSON，但实际返回 Python `list[list[dict]]`，不执行 `json.dumps()`，也没有正式 CLI/API 暴露。 |
| 解析流程 | 全局删除所有 `[...]` 内容 → 按换行 → 按 `<...>` 交替切分 → 两位分钟时间片进入全局 `timelist`，其他非空片段成为一个 `word` 字段并分配全局 idx。 |
| 时间赋值 | 每个 token 的 start 取同 idx 时间；end 取下一时间，最后 token 使用 start+1 秒。跨行仍共用一个全局时间序列。 |
| 可观测副作用 | 对每个切分片段无条件 `print()`；调用方无法通过参数关闭。 |
| 已知失败 | `parse_time()` 不检查 match/小数是否存在；时间少于 token 时仍访问 `timelist[idx]`；token 时间只接受两位分钟，与 C09 长分钟合同不一致；文本片段可包含多个自然语言词却仍作为一个 token。 |
| 证据与正式化门槛 | 无测试。接入前需决定返回 Python 对象还是 JSON 文本、行时间是否保留、严格/宽松解析、末 token end 规则、长分钟和错误类型。 |

<a id="x03"></a>

#### X03 繁体转简体 [未接入]

| 项目 | 当前细节 |
|---|---|
| 入口与初始化 | 导入 `ext.traditional_to_simplified` 时创建全局 `OpenCC('t2s')`，`t2s(text)` 直接返回 `cc.convert(text)`。 |
| 当前可达性 | C01/C02/C04/C05 均不调用，因此繁体输入不会被主链自动转换。 |
| 未决语义 | 尚未决定转换仅用于发音归一化，还是同时替换最终显示歌词；两种选择会分别影响 checkpoint 输入或用户可见文本。 |
| 失败与证据 | 依赖/字典加载错误原样传播；无入口、错误合同、缓存生命周期或自动化测试。接入前至少需要“显示保留原文”和“转写使用转换文本”的产品决策。 |

<a id="n01"></a>

#### N01 模型训练 [不可运行/不自包含]

| 项目 | 当前细节 |
|---|---|
| 意图入口 | `t2l/mtl/train.py` 定义 Baseline/MTL 训练、验证、TensorBoard 和 checkpoint 写出；上游 README 示例使用 `python train.py ...`。 |
| 当前硬阻塞 | 导入不存在的 `t2l.mtl.test::validate`；`data.py` 导入仓库外 `DALI`，并使用无法在当前包布局可靠解析的 `from utils import ...`。 |
| 未声明依赖 | `data.py` 直接需要 `h5py`、`sortedcontainers`，训练日志需要 TensorBoard；它们未列入 `requirements.txt`/Pipfile 的直接依赖。 |
| 外部资产 | 需要 DALI v2 标注/音频、预分离人声、HDF 目录和训练输出目录；仓库没有可授权、可下载、可校验的最小 fixture。 |
| 启动不一致 | README 的脚本式命令与源码相对 import 不兼容；改用 `python -m t2l.mtl.train` 又会先遇到上述缺失模块/绝对 import。 |
| 可交付边界 | 现有文件只能作为研究实现线索，不能视为可运行训练产品。移除该状态前需补齐模块、依赖锁、数据准备、最小训练/恢复命令和至少一个可重复 smoke test。 |

<a id="n02"></a>

#### N02 模型评估 [不可运行/不自包含]

| 项目 | 当前细节 |
|---|---|
| 意图入口 | `t2l/mtl/eval.py` 评估 Baseline/MTL；`eval_bdr.py` 组合声学与 boundary 模型，目标数据为 Jamendo。 |
| 当前硬阻塞 | 两个脚本都导入不存在的 `.test` 并调用其中预测函数，同时复用 N01 的数据层与缺失/未声明依赖。 |
| 外部资产 | 需要 Jamendo 标注、音频/预分离人声、HDF、预测输出目录和匹配 checkpoint；仓库没有 golden 指标、容差、数据版本或资产 hash。 |
| 参数差异 | 评估脚本使用自己的参数/命名（如 lowercase `baseline`、BDR `alpha` 默认 0.1），不能直接当作 C07 正式推理默认值 `Baseline` 与 `alpha=0.8` 的证明。 |
| 证据限制 | compileall 只证明语法可编译，不执行这些 import；当前 30 个 pytest 也不收集这两条路径。 |
| 可交付边界 | 在数据版本、指标定义、预测文件格式、可重复命令和预期阈值补齐前，不得用这些脚本声称 checkpoint 精度已验证。 |

### 1.3 “支持语言”的准确解释

仓库存在中文、日文、韩文、英文和俄文处理分支，但该表述必须附带以下条件：

- 语言判断以**整行**为单位；
- 每行只进入一个语言分支；
- 各语言先转写为拉丁文本，随后统一交给英语 `g2p_en`；
- 最终使用的是与现有声学 checkpoint 耦合的 ARPAbet 风格 phone 表；
- 当前测试不验证多语言转写正确率、混合语言表现或对齐精度。

因此，“支持五种语言”表示存在可达处理路径，不表示具有独立的五语原生音系模型，也不构成质量保证。

---

## 2. 正式运行主链与能力关联

### 2.1 CLI 真实调用链

```mermaid
flowchart TD
    A[main.py::cli] --> B[ext/t2lutils.py<br/>探测歌词文件编码]
    B --> C[读取歌词为 list[str]]
    C --> D[t2l/t2l.py::process]
    D --> E[清除特定行首 LRC/元数据标签<br/>组织显示词与转写词]
    E --> F[t2l/phonetic.py<br/>整行语言识别与拉丁转写]
    F --> G[t2l/mtl/utils.py::gen_phone_gt_opt<br/>g2p_en → phone 序列与半开区间索引]
    D --> H{vocalize?}
    H -->|否| I[torchaudio.load<br/>失败回退 librosa.load]
    H -->|是| J[音频解码 → Demucs 人声分离]
    I --> K[22,050 Hz 音频]
    J --> K
    G --> L[t2l/mtl/wrapper.py::align]
    K --> L
    L --> M[MelSpectrogram<br/>AcousticModel<br/>可选 BoundaryDetection]
    M --> N[utils.alignment 或 alignment_bdr]
    N --> O[t2l/t2l.py::gen_lrc]
    O --> P[process 返回 LRC 字符串]
    P --> Q[CLI 打印返回值]
    P --> R[to_standard_lrc 移除词时间戳]
    R --> S[创建 out_dir<br/>写入 音频基名.lrc]
```

### 2.2 各层数据形态

| 阶段 | 输入形态 | 输出形态 | 下游依赖的合同 |
|---|---|---|---|
| CLI 读取 | 歌词文件路径 | 保留行分隔的 `list[str]` | `process()` 自行 strip 并解析每行 |
| 歌词清理 | 原始行 | `lines: list[list[str]]` 与 `phonetics: list[list[str]]` | 两者的词片段顺序必须一致 |
| 多语言转写 | 单行 Unicode 文本 | `(原文片段, 拉丁转写)` 列表 | 原文用于恢复显示，转写用于 G2P |
| G2P | 按行组织的转写 token | `lyrics_p`、`idx_word_p`、`idx_line_p` | 索引是 phone 序列中的 `[start, end)` |
| 音频预处理 | 文件路径 | `[channels, samples]` tensor、采样率 | 推理目标采样率为 22,050 Hz |
| wrapper | 音频、phone、索引 | `word_align: list[[start_frame, end_frame]]` | 每项顺序对应一个显示词片段 |
| LRC 生成 | 词帧边界、显示行 | LRC 字符串 | 每帧约 34.8 ms；词边界不足时降级 |
| CLI 标准化 | `process()` 返回值 | 去掉 `<...>` 标签的文本 | 方括号行时间戳保留 |

### 2.3 能力依赖与隐式耦合

| 上游 | 下游 | 当前耦合 | 重构前必须确认 |
|---|---|---|---|
| 编码探测 | CLI 文本读取 | 只在 CLI 执行，API 接收已解码字符串 | 是否保持 CLI/API 职责分离 |
| 语言转写 | `g2p_en` | 所有语言收敛到英语 G2P 可处理的拉丁文本 | 新转写是否仍匹配 phone 表和 checkpoint |
| G2P | 声学模型/DTW | phone 顺序、空格 phone、未知 phone 和 blank 语义耦合 | phone 字典与类别布局是否兼容 |
| 音频预处理 | Mel/模型 | 22,050 Hz、首声道策略 | 改采样率或声道策略会改变 posterior 时间轴 |
| Mel/模型 | 对齐器 | 特征参数、频率池化、posterior 帧率耦合 | 时间分辨率是否需要同步迁移 |
| 对齐器 | `gen_lrc()` | frame index 直接乘固定 resolution | 不能只改模型 hop 而不改时间转换 |
| 词索引 | 对齐器/LRC | `[start, end)`、顺序与显示 token 一一对应 | 拆分歌词层时必须保留索引语义 |
| 当前工作目录 | 模型资产 | `./checkpoints/...`、`lid.176.ftz` | 从其他目录启动会改变资产解析结果 |

不可随意拆开的隐式状态还包括：模块级 fastText 模型、懒加载的全局 G2P 对象、wrapper 中 NumPy seed 及推理时由 PyTorch RNG 生成的平滑噪声。仅设置 `np.random.seed(7)` 不保证完整确定性。

---

## 3. 外部接口合同

### 3.1 CLI 合同 [已实现][部分受测试][环境依赖]

入口：`main.py::cli()`。

```text
python main.py <歌词文件> <音频文件> [选项]
```

| 参数 | 类型/可选值 | 默认值 | 语义 |
|---|---|---|---|
| `lrc_file` | 路径，必填 | 无 | 歌词文本文件；先通过 chardet 探测编码 |
| `music_file` | 路径，必填 | 无 | 要对齐的音频文件；输出文件使用其 basename |
| `-f/--format` | 仅 `lrc` | `lrc` | SRT 未实现，argparse 会拒绝其他值 |
| `-l/--line_only` | `0` 或 `1` | `0` | `0` 为词/字级增强 LRC，`1` 为仅行时间戳 |
| `-v/--vocalize` | `0` 或 `1` | `1` | 是否先运行 Demucs 人声分离 |
| `-m/--model` | `mdx`、`mdx_extra`、`mdx_q`、`mdx_extra_q` | `mdx_extra` | Demucs 模型，不是声学对齐模型名称 |
| `-i/--idx` | `-1`、`0`、`1`、`2`、`3` | `-1` | `-1` 使用 model bag；`0..3` 选择一个子模型 |
| `-o/--out_dir` | 路径 | `demofile` | 标准 LRC 输出目录；不存在时由 CLI 创建 |

#### CLI 输出

默认 `line_only=0` 时有两个不同产物：

1. `process()` 返回的增强 LRC 被打印到终端，其中行时间戳为 `[MM:SS.mmm]`，词/字片段时间戳为 `<MM:SS.mmm>`；
2. CLI 调用 `to_standard_lrc()` 移除尖括号时间戳，并把结果写入 `<out_dir>/<音频基名>.lrc`。

`line_only=1` 时返回值本身已经只有行时间戳，标准化步骤通常不再移除内容。

注意：当前 stdout **不是稳定的纯 LRC 数据流**。默认 verbose 路径可能打印设备、模型、推理阶段和分数信息，CLI 最后还打印标准文件保存路径。未来若要提供可管道消费的纯 stdout，需要作为显式接口变更设计，不能假定现状已经如此。

#### CLI 输入与路径边界

- 编码探测将 `GB2312` 映射为 `GBK`；无法得到编码时回退字符串 `utf8`。
- 探测到一个编码不代表解码一定成功；文件不存在、权限不足和错误编码仍保留 Python I/O/Unicode 异常。
- checkpoint 和 `lid.176.ftz` 按**进程当前工作目录**解析，不按 `main.py` 所在目录解析。
- 输出目录会被创建；同名 `.lrc` 文件会直接覆盖。
- CLI 对 Demucs index 有范围约束，而直接调用 Python API 时没有同等级别的显式 index 校验。

#### CLI 测试锚点

- `tests/test_cli.py::test_parser_defaults_and_integer_index`
- `tests/test_cli.py::test_parser_rejects_unsupported_values`
- `tests/test_cli.py::test_to_standard_lrc_removes_word_timestamps_with_long_minutes`

这些测试不执行完整 `cli()`，因此未直接覆盖歌词文件读取、目录创建、覆盖文件和终端完整输出顺序。

### 3.2 `process()` Python API 合同 [已实现][部分受测试][环境依赖]

事实源签名：

```python
process(
    txt_lines,
    audio_file,
    mtl_model='MTL',
    demucs_model='mdx_extra',
    demucs_idx=-1,
    line_only=False,
    out_file=None,
    verbose=True,
    vocalize=True,
    format='lrc',
)
```

| 参数 | 当前语义 |
|---|---|
| `txt_lines` | 可迭代歌词行；调用方负责把文件正确解码成字符串 |
| `audio_file` | 传给音频 decoder 的路径 |
| `mtl_model` | `Baseline`、`MTL`、`Baseline_BDR`、`MTL_BDR`，或 `load_mtl_model()` 返回的预加载 tuple |
| `demucs_model` | Demucs 模型名称字符串，或可直接应用的已加载模型对象 |
| `demucs_idx` | model bag 子模型索引；字符串模型路径中 `0..3` 选子模型，其他值实际保留 model bag |
| `line_only` | `False` 插入尖括号词时间戳；`True` 只生成行时间戳 |
| `out_file` | 可选文件路径；直接以 UTF-8 写入**与返回值相同**的内容 |
| `verbose` | 控制本项目多数进度 `print()` 以及 Demucs progress 参数 |
| `vocalize` | `True` 运行 Demucs；`False` 直接对齐原音频 |
| `format` | 仅精确字符串 `lrc` 被接受；否则在音频处理前抛 `ValueError` |

返回值是 LRC 字符串。`process()` 不创建 `out_file` 的父目录，也不执行 CLI 的“增强 LRC → 标准 LRC”转换。

`mtl_model` 预加载 tuple 的当前形态为：

```text
(ac_model, bdr_model, model_type, bdr_flag, device)
```

这是可用的性能优化接口，但 tuple 是无类型、位置敏感的内部表示。若未来改成对象，应提供兼容层或清晰版本边界。

### 3.3 CLI 与 Python API 差异

| 维度 | CLI | `process()` API | 重构守则 |
|---|---|---|---|
| 歌词来源 | 文件路径 | 已解码的行序列 | 不把文件 I/O 隐式塞入核心 API |
| 编码 | CLI 探测 | 调用方负责 | 编码错误属于边界层职责 |
| 返回 | 进程退出，无 Python 返回合同 | 返回 LRC 字符串 | 保持核心结果可组合 |
| stdout | 进度、LRC、保存提示可能混合 | `verbose` 时有进度；调用方决定是否打印返回值 | 不宣称 stdout 是纯 LRC |
| 文件内容 | 标准化后 LRC | 与返回值完全相同 | 两条写出路径不能混为一谈 |
| 父目录 | `out_dir` 自动创建 | 不创建 `out_file` 父目录 | 如变更需明确兼容策略 |
| 文件命名 | 音频 basename + `.lrc` | 调用方完整指定 | 不把 CLI 命名规则当核心算法合同 |
| 参数校验 | argparse 限定 Demucs 选项 | 部分参数只在深层代码产生行为/异常 | API 若加强校验，需考虑既有调用方 |
| 异常展示 | argparse 或未捕获异常显示 | Python 异常 | 不吞掉 cause 或错误阶段 |

---

## 4. 歌词读取、清理与行组织

### 4.1 文件编码探测 [已实现]

`main.py` 调用 `ext/t2lutils.py::__get_file_encoding()`：

1. 以二进制打开歌词文件，并通过 `readlines()` 一次性读入各行；
2. 将各行 feed 给 `chardet.UniversalDetector`；
3. detector 已完成且至少处理超过三行时提前结束；
4. 将 `GB2312` 改为 `GBK`；
5. detector 未提供可用 encoding 时返回 `utf8`。

该能力只负责给 CLI 的 `open(..., encoding=...)` 提供候选编码。它不验证歌词语义，也不属于 `process()` 的 Python API。

### 4.2 行首标签清理 [已实现]

`process()` 对每行执行 `strip()`，随后依次删除：

- 行首形如 `[...]` 且内容只由数字、点、冒号组成的时间戳；
- 行首形如 `[xx:...]` 的两字母元数据标签。

已知边界：

- 两条正则各只执行一次且顺序固定；`[时间][ar:...]正文` 会由两次替换依次删除两类标签；
- 元数据正则中的 `.+` 是贪婪匹配；`[ar:...][时间]正文` 或多个连续方括号段可能被从第一个元数据标签一直删除到本行最后一个 `]`，存在过度删除风险；
- 连续时间标签、非两字母起始标签、非当前正则覆盖的时间格式可能保留；
- 此处只清理输入，不保留已有时间信息用于增量修正。

### 4.3 显示文本与对齐 token 的组织 [已实现]

每行先经 `phonetize()` 得到 `(显示片段, 转写)`，再按标点、空白和数字等分隔符拆分可供 G2P 的片段。无 phone 的尾部字符会尽量附加到上一个显示词；若当前行没有有效词：

- 在已有有效行之后，会把原行通过换行追加到上一行最后一个显示 token；
- 在第一个有效行之前，会累计到 `pre_lines_unprocessed`，最终原样前置到 LRC 结果，且这些行没有时间戳；
- 若所有行都没有有效内容，则抛出 `TxtValueError`。

源码中明确保留“如何处理数字”的 FIXME。后续重构不得把当前的数字丢弃/附着行为误写成稳定的数字朗读支持。

---

## 5. 语言识别、转写与统一 phone 空间

### 5.1 模型加载时机 [环境依赖]

`t2l/t2l.py::phonetize()` 使用延迟 import。正常从 `process()` 进入时，第一次实际转写会导入 `t2l/phonetic.py`，模块导入期间执行：

```python
fasttext.load_model('lid.176.ftz')
```

因此：

- 仅导入 `t2l.t2l` 不会立刻加载 fastText；
- 首次转写会按 CWD 查找模型并产生加载成本；
- 直接导入 `t2l.phonetic` 则会立即加载；
- 该模块级模型对象是共享全局状态，缺少显式生命周期和依赖注入。

### 5.2 语言检测优先级 [已实现]

`detect_language()` 对整行按以下顺序判断：

1. 日文平假名/片假名 → `ja`；
2. CJK 汉字 → `zh`；
3. Hangul → `ko`；
4. Cyrillic → `ru`；
5. 其余交给 fastText，取 top-1。

纯 ASCII 文本在 `phonetize()` 中更早直接返回，不调用 `detect_language()`。fastText 低置信度只记录 warning，仍返回 top-1 标签；不支持的标签会记录 error 并返回空结果。

顺序本身影响混合文字：例如同一行既有日文假名又有汉字时进入日文分支；有汉字和 Hangul 时因 CJK 规则在前而进入中文分支。这是当前代码优先级，不是语言学保证。

### 5.3 语言处理矩阵

| 输入类别 | 识别方式 | 前置转写 | 显示片段组织 | 最终 phone 化 | 主要边界 |
|---|---|---|---|---|---|
| 中文 | CJK 正则 | `pypinyin.lazy_pinyin` | `convertPairsPinyin` 尝试对应原字符 | `g2p_en.G2p` | 多音字、数字、拉丁夹杂、繁体不自动转换 |
| 日文 | 假名正则优先 | `pykakasi` Hepburn | `convertPairsJp` | `g2p_en.G2p` | 混合拉丁文本、罗马化差异、GPL 依赖 |
| 韩文 | Hangul 正则 | `kroman.parse` | `convertPairsKorean` 以字符串位置重建 | `g2p_en.G2p` | 映射依赖字符/转写位置假设 |
| 英文/纯 ASCII | ASCII 直接路径；非 ASCII 拉丁文本可走 fastText | 原文/空白切词 | 保留分隔区域 | `g2p_en.G2p` | 非词典词、符号、数字发音 |
| 俄文 | Cyrillic 正则 | `cyrtranslit.to_latin` | `convertPairsRussian` 按空格配对 | `g2p_en.G2p` | 原文和转写词数必须大致对应，混合行脆弱 |

俄文配对实现按转写词循环索引原文词数组，长度不一致时可能越界。该路径没有自动化测试保护。

### 5.4 G2P 与 phone 字典 [已实现][受测试]

`t2l/mtl/utils.py::_get_g2p()` 首次调用时创建全局 `G2p()`。`gen_phone_gt_opt()`：

1. 对每个转写 token 调用英语 G2P；
2. 删除 ARPAbet phone 末尾的重音数字；
3. 在词之间加入空格 phone；
4. 生成词和行在完整 phone 序列中的索引。

当前 `phone_dict` 有 40 个可识别项（39 个 ARPAbet phone 加空格），声学类别 index `40` 被用作 CTC blank。任何不在 `phone_dict` 中的 G2P 输出也会由 `phone2seq()` 映射到 `40`，即与 blank 合并。

这意味着未知 phone 不会形成独立“unknown”类别。未来若新增 unknown 类、换 G2P 或改变 phone 顺序，必须与 checkpoint、posterior 类别布局和对齐逻辑共同迁移。

---

## 6. 音频预处理、人声分离与模型推理

### 6.1 音频解码 [已实现][受测试]

`t2l/t2l.py::preprocess_audio()` 的顺序是：

1. 调用 `torchaudio.load()`；
2. 若其抛出 `RuntimeError`/`OSError`，或返回空 tensor，则调用 `librosa.load()`；
3. librosa 路径捕获常见运行时、I/O、值、EOF 和 audioread decode 错误；
4. 两个 decoder 均失败时抛 `AudioValueError`，异常 cause 指向 librosa 失败，并在消息中附带 torchaudio 错误；
5. 将非 tensor 结果转为 tensor；
6. 若调用方指定采样率且当前采样率不同，使用 `julius.resample_frac()`；
7. 一维音频升维为 `[1, samples]`。

`process(vocalize=False)` 指定 22,050 Hz。人声分离路径先按原采样率解码，再按 Demucs 模型采样率和最终 22,050 Hz 分阶段重采样。

两条 decoder 的成功语义并不完全相同：torchaudio 成功时保留 channel-first 多声道；librosa 回退未传 `mono=False`，因此会先混为单声道，再升维成 `[1, samples]`。后续 wrapper 无论如何只取首声道，但 decoder 切换仍可能改变送入模型的波形。

“音频解码能力”不表示任意 codec、损坏文件、容器、声道布局都能成功。decoder 之外的异常不应被统一包装为 `AudioValueError`。

### 6.2 Demucs 人声分离 [已实现][受测试][环境依赖]

可选模型：`mdx`、`mdx_extra`、`mdx_q`、`mdx_extra_q`。字符串模型由 `demucs.pretrained.get_model()` 获取；在没有本地缓存时，第三方库可能访问网络下载权重。

当前行为：

- 设备为 CUDA（可用时）或 CPU；
- mono 输入扩展为两个相同声道；
- `demucs.apply_model()` 在 `torch.inference_mode()` 下运行；
- 遍历 `model.sources` 并取名称为 `vocals` 的 source；
- `0..3` 从 model bag 中选择子模型；其余 index 保留原 model bag；
- 输出重采样到目标 22,050 Hz。

传入字符串模型时 loader 会负责移动到当前设备并调用 `eval()`；传入预加载模型对象时不会执行这两步，且 `demucs_idx` 被忽略，调用方必须保证设备、eval 状态、采样率和 `sources` 合同。

已知边界：子模型选择硬编码接受 `0..3`，没有先检查实际 bag 长度；如果模型没有名为 `vocals` 的 source，局部变量会保持 `None`，后续重采样或声学推理会失败。当前没有专门的领域错误或测试覆盖这些情况。

### 6.3 wrapper 音频输入合同 [已实现][受测试]

`t2l/mtl/wrapper.py::align()` 接受：

- 一维 `[samples]`；或
- channel-first 二维 `[channels, samples]`。

它拒绝空维度、空样本和三维输入，将数据转为 `float32`，然后固定使用 `audio[:1]`，即**只取首声道**。这一策略是为兼容此前输出而明确保留的行为；不得在普通清理中改为 flatten、拼接左右声道或自动混音。

### 6.4 特征和声学模型 [已实现][受测试][环境依赖]

固定信号/模型参数：

| 参数 | 当前值 | 耦合对象 |
|---|---:|---|
| 采样率 | 22,050 Hz | 音频预处理、Mel、时间轴 |
| FFT | 512 | checkpoint 输入分布 |
| Mel bins | 128 | CNN layer norm 和输入 shape |
| CNN feature channels | 32 | checkpoint state dict |
| 频率/时间池化 kernel | `(2, 3)` | 模型输出帧率 |
| acoustic RNN dim | 256 | checkpoint state dict |
| acoustic BiLSTM 层 | 3 | checkpoint state dict |
| BDR RNN dim | 32 | BDR checkpoint |
| BDR 融合系数 | `alpha = 0.8` | BDR 对齐分数 |

`AcousticModel` 由 CNN、Residual CNN、MaxPool、Linear、三层双向 LSTM 和 classifier 组成：

- Baseline 输出 41 类；
- MTL classifier 输出 `41 × 47`，reshape 后沿 melody 维求和得到 41 类歌词 posterior；
- 输出随后做 `log_softmax`；
- 模型 forward 在 `torch.inference_mode()` 下运行；
- 为 smoothing 加入由 PyTorch RNG 生成的极小均匀噪声。

需要特别保留并先建 characterization test 的现状：第一层 `BidirectionalLSTM` 以 `batch_first=True` 构造，后两层以 `batch_first=False` 构造，但层间没有显式 transpose。后两层因此会按不同维度语义解释第一层输出；这可能是历史缺陷，却也是现有 checkpoint 训练/推理图的一部分。没有模型迁移与真实质量对比时，不应只把参数统一为 `batch_first=True`。

`BoundaryDetection` 使用相似骨干和 sigmoid 输出。BDR posterior 被取 log 并乘 `0.8`，仅在 line-start phone 位置影响 DP 分数。

模型类名、模块层次、参数形状和 state-dict key 均属于 checkpoint 二进制兼容的一部分。无迁移器时不能任意重命名层、改变维度或调整特征参数。

### 6.5 模型与资产定位 [环境依赖]

| 资产 | 用途 | 当前位置/获得方式 | 不可用时 |
|---|---|---|---|
| `checkpoint_Baseline` | 41 类声学模型 | `./checkpoints/`，Git LFS | Baseline 无法加载 |
| `checkpoint_MTL` | 41×47 MTL 模型 | `./checkpoints/`，Git LFS | 默认推理无法加载 |
| `checkpoint_BDR` | 边界检测模型 | `./checkpoints/`，Git LFS | `*_BDR` 方法无法加载 |
| `lid.176.ftz` | fastText 语言识别 | CWD 根路径，Git LFS | `t2l.phonetic` 导入失败 |
| Demucs 权重 | 可选人声分离 | 第三方缓存/可能下载 | 默认 vocalize 路径失败 |
| CUDA | 可选加速 | 运行环境 | 回退 CPU；速度和资源需求不同 |

`.gitattributes` 明确将三个 checkpoint 和 `*.ftz` 交给 Git LFS。普通 clone 后若没有执行 `git lfs pull`，文件可能只是 pointer，路径存在也不代表内容可加载。

本次 checkout 中三个 checkpoint 已是实际二进制而非 LFS pointer；2026-09-04 使用当前解释器在 CPU 上分别调用 `load_mtl_model('Baseline')` 与 `load_mtl_model('MTL_BDR')` 成功，覆盖了 Baseline、MTL 和 BDR 三个 state dict 的结构加载。该结果仍不证明模型可完成真实前向、GPU 兼容或对齐质量，且不应外推到其他 clone。

---

## 7. 对齐数据协议与 LRC 生成合同

这是后续重构最需要保护的内部协议。

### 7.1 phone 索引合同 [受测试]

`idx_word_p` 与 `idx_line_p` 表示 phone 序列中的 `[start, end)` 半开区间。有效区间必须：

- 为二维 `N × 2`；
- 至少包含一个区间；
- `0 <= start < end <= phoneme_count`；
- 按顺序排列；
- 相邻区间不得重叠；
- line-start 也必须落在 phone 序列内。

`gen_phone_gt_opt()` 生成的两词示例可表现为：

```text
lyrics_p:      [phone_of_word_1, " ", phone_of_word_2, " "]
idx_word_p:    [[0, 1], [2, 3]]
```

对齐器内部再将 phone 索引转换为交替的 phone/blank DP 列。不要因为 DP 内部使用 `2 * idx + 1` 而把外部索引改成闭区间。

### 7.2 posterior 与路径合同 [受测试]

普通和 BDR 对齐入口都要求：

- posterior shape 为 `[audio_frames, classes]`；
- `classes >= 41`；
- `phoneme_count >= 1`；
- `audio_frames >= phoneme_count + 2`；
- blank 类固定为 index `40`；
- BDR prediction 展平后至少有 `audio_frames` 项。

最小一 phone 的有效例子需要 3 个音频帧，测试期望对齐结果为 `[[1, 2]]`。

对齐结果是 frame index，而不是秒数。普通 torch DP 与 BDR NumPy DP 都应接受同一半开区间索引合同。BDR 路径在 wrapper 中显式接收 CPU NumPy posterior 和 boundary prediction。

两条实现的运行特性和降级并不对称：普通路径在 tensor 所在设备上分配 DP 状态并对逐帧转移做部分向量化；BDR 路径在 CPU NumPy 上使用 Python 双层循环。两者空间量级均约为 `audio_frames × (2 * phoneme_count + 1)`。普通路径在提取词区间时对路径耗尽有 warning/补零长度区间保护，BDR 路径没有对应的 `path_i` 上界保护。

当前前置校验也不检查 posterior/BDR 是否包含 `NaN`/`Inf`，不要求 word/line 索引为整数 dtype。调用方应继续提供有限浮点分数和整数索引；不能把“通过 shape 校验”解读为输入完全有效。

### 7.3 时间分辨率合同

`model.py`、`wrapper.write_csv()` 和 `t2l.gen_lrc()` 都使用：

```text
resolution = 256 / 22050 * 3 ≈ 0.03482993197 秒/帧
```

其中乘以 3 与模型时间轴上的池化有关。修改 Mel hop、模型池化、重采样率或 posterior 帧率时，必须同步验证时间换算；否则代码仍能运行，但 LRC 时间会系统性漂移。

LRC 时间戳采用截断而非四舍五入：

```text
MM:SS.mmm
```

分钟至少显示两位但可以超过两位。`to_standard_lrc()` 已测试能处理如 `<100:01.234>` 的长分钟词标签。

### 7.4 `gen_lrc()` 输出与降级行为 [已实现]

- 每个显示行取其第一个词的 start frame 作为 `[行时间戳]`；
- `line_only=False` 时，每个非空显示片段前插入自己的 `<词时间戳>`；
- `line_only=True` 时不插入尖括号时间戳；
- 对齐结果少于歌词 token 时，行开始前若已经耗尽，会记录 warning 并停止生成后续行；
- 在某一行内部耗尽时，后续文本仍可输出，但不再插入词时间戳；
- 返回值不带额外末尾换行。

这是一种“尽量产出”的现有降级策略，不等价于完整对齐成功。它当前没有专门的自动化测试锚点。未来如要改为严格失败、补齐或结构化 warning，必须先决定兼容策略并增加回归样例。

---

## 8. 失败模型与异常边界

| 失败类别 | 当前异常 | 发生阶段 | 典型条件 | 不应混同 |
|---|---|---|---|---|
| 歌词无效 | `TxtValueError` | 歌词清理/转写后 | 没有任何有效显示词 | checkpoint、设备或音频错误 |
| 格式不支持 | `ValueError` | `process()` 开始 | `format != 'lrc'` | 音频加载失败 |
| 音频不可用 | `AudioValueError` | decoder/空音频检查 | torchaudio 与 librosa 均失败，或结果为空 | Demucs、CUDA、模型加载错误 |
| 对齐输入无效 | `AlignmentValueError` | DTW/BDR 前置校验 | shape、帧数、索引或 BDR 长度非法 | 歌词文件编码错误 |
| 模型方法无效 | `ValueError` | `load_mtl_model()` | 非 Baseline/MTL 系列 | decoder 错误 |
| 环境/第三方错误 | 原异常类型 | Demucs、CUDA、checkpoint、依赖导入 | OOM、权重缺失、state dict 不兼容等 | 用户音频值错误 |

### 8.1 必须保留的诊断语义

- 音频双 decoder 失败时，`AudioValueError.__cause__` 保留最后 decoder 异常；
- torchaudio 的先前错误被加入异常消息；
- `separate_vocals()` 不捕获并重分类 Demucs/CUDA 错误；
- 对齐器在分配巨大 DP 矩阵前校验基础 shape 和最短路径条件。

**[建议]** 未来可以建立统一的公共错误层，但必须保留错误发生阶段、原始 cause 和“输入错误/资产错误/设备错误”的区别。不要为了让 CLI 提示统一而把所有异常压成 `AudioValueError`。

---

## 9. 非主链代码与不可承诺能力

### 9.1 `t2l/slid.py`：音频语言识别 [未接入]

用途：用 faster-whisper 的 language detection，配合 VAD，从 16 kHz 音频返回语言概率列表。

边界与风险：

- `main.py` 和 `process()` 均不调用它；
- 默认可加载 `tiny` Whisper 模型，可能触发网络下载；
- 直接使用 `feature_extractor`、`encode` 和 `model.detect_language` 等实现细节，对 faster-whisper 版本敏感；
- requirements 与 Pipfile 对 faster-whisper/ctranslate2 的版本不一致；
- 没有本仓库自动化测试；
- `test_slid()` 是带打印和真实模型/文件依赖的手工函数，不是 pytest 回归测试。

在补齐公开入口、版本合同、错误模型和隔离测试前，不能把它列为正式 CLI 能力。

### 9.2 `ext/lrc2json.py`：增强 LRC 转 JSON 结构 [未接入]

意图输出结构类似：

```json
[
  [
    {"word": "synthetic-token", "idx": 0, "start": 1.2, "end": 1.8}
  ]
]
```

已知问题：

- 函数名虽含 JSON，实际返回 Python 嵌套 `list`/`dict`，没有序列化为 JSON 文本；
- 解析过程中无条件 `print()`；
- `parse_time()` 未验证 regex match 就调用 `.groups()`；
- 小数部分缺失时拼接会失败；
- 只接受两位分钟的 token 时间正则，与 CLI 已支持的长分钟标签不一致；
- token 数大于时间数时访问 `timelist[idx]` 可能越界；
- 所有行共享一个全局 token/time index，最后一个 token 的 end 被人为设为 start+1 秒；
- 没有正式入口、异常合同或测试。

它不能被视为稳定 JSON API。

### 9.3 `ext/traditional_to_simplified.py`：繁转简 [未接入]

模块级创建 `OpenCC('t2s')` 并提供 `t2s()`。正式主链没有调用它，因此当前“中文处理”不会自动把繁体字转换为简体字。若未来接入，需要先评估文本显示是否保持原文、转换仅用于发音还是也影响输出，以及对应测试。

### 9.4 训练与评估 [不可运行/不自包含]

涉及：

- `t2l/mtl/data.py`
- `t2l/mtl/train.py`
- `t2l/mtl/eval.py`
- `t2l/mtl/eval_bdr.py`

当前阻塞项包括：

1. `train.py` 导入不存在的 `.test::validate`；
2. `eval.py`/`eval_bdr.py` 导入不存在的 `.test`；
3. `data.py` 依赖当前仓库未包含的 `DALI`；
4. `data.py` 使用 `from utils import ...` 顶层绝对导入，包内执行不可靠；
5. `data.py` 直接导入 `h5py` 与 `sortedcontainers`，训练日志使用 TensorBoard，但这些都未作为直接依赖列入 requirements/Pipfile；
6. 上游 README 使用 `python train.py`/`python eval.py` 风格命令，而源码使用包相对 import；直接脚本执行与 `python -m ...` 都会在当前缺失项上失败；
7. 数据层要求外部 DALI/Jamendo 注释、HDF、音频和预分离人声；
8. 训练/评估命令、数据准备、数据版本、指标阈值和可复现最小样例没有形成闭环；
9. 这些路径没有纳入轻量测试；`compileall` 不执行 import，不能证明它们可启动。

这些代码可作为上游研究实现和未来修复线索，但在缺失项补齐并建立可复现命令前，不得宣称本仓库“支持训练/评估”。

---

## 10. 测试事实、覆盖边界与重构门槛

### 10.1 当前测试规模

静态统计：

- 4 个测试文件；
- 25 个测试函数；
- pytest 参数化展开后 30 个测试用例。

测试被设计为不加载真实 checkpoint、不下载 Demucs 模型、不要求 GPU，也不依赖真实音频文件。

### 10.2 已有直接回归保护

| 行为 | 测试锚点 |
|---|---|
| 长分钟增强时间戳转标准 LRC | `tests/test_cli.py::test_to_standard_lrc_removes_word_timestamps_with_long_minutes` |
| CLI 默认值和整数 index | `tests/test_cli.py::test_parser_defaults_and_integer_index` |
| CLI 拒绝非法格式、布尔整数、index、模型 | `tests/test_cli.py::test_parser_rejects_unsupported_values` |
| 非 LRC 在音频处理前失败 | `tests/test_t2l.py::test_process_rejects_unsupported_format_before_audio_work` |
| torchaudio 失败后回退 librosa | `tests/test_t2l.py::test_preprocess_audio_falls_back_to_librosa` |
| 双 decoder 错误消息和 cause | `tests/test_t2l.py::test_preprocess_audio_reports_both_decoder_failures` |
| DecodeError/EOFError 被包装为 AudioValueError | `tests/test_t2l.py::test_preprocess_audio_wraps_decoder_errors` |
| Demucs/CUDA 错误不被重分类 | `tests/test_t2l.py::test_separate_vocals_does_not_reclassify_model_errors` |
| Demucs forward 使用 inference mode | `tests/test_t2l.py::test_demucs_apply_runs_in_inference_mode` |
| `process(out_file)` 显式 UTF-8 且文件等于返回值 | `tests/test_t2l.py::test_process_writes_utf8_output` |
| 首声道、完整模型帧数、声学 inference mode、quiet verbose | `tests/test_wrapper.py::test_align_uses_left_channel_and_inference_mode` |
| 不按 waveform 长度截断模型输出 | `tests/test_wrapper.py::test_align_uses_full_model_output_for_frame_count` |
| NumPy 音频转 float32 | `tests/test_wrapper.py::test_align_converts_numpy_audio_to_float32` |
| BDR inference mode 和 CPU NumPy 边界 | `tests/test_wrapper.py::test_bdr_alignment_receives_cpu_numpy_predictions` |
| 一维音频输入 | `tests/test_wrapper.py::test_align_accepts_one_dimensional_audio` |
| 空/非法音频 shape 被拒绝 | `tests/test_wrapper.py::test_align_rejects_empty_or_invalid_audio_dimensions` |
| 普通对齐最短帧数 | `tests/test_alignment.py::test_alignment_rejects_two_frames_for_one_phoneme` |
| 歌词长于可用路径 | `tests/test_alignment.py::test_alignment_rejects_lyrics_longer_than_available_path` |
| BDR prediction 长度 | `tests/test_alignment.py::test_alignment_bdr_rejects_short_boundary_prediction` |
| 空 word index | `tests/test_alignment.py::test_alignment_rejects_empty_word_indices` |
| 无序/重叠 index | `tests/test_alignment.py::test_alignment_rejects_unordered_or_overlapping_word_indices` |
| posterior 维数和至少 41 类 | `tests/test_alignment.py::test_alignment_rejects_invalid_posterior_shape` |
| 生成的半开区间被普通 DTW 接受 | `tests/test_alignment.py::test_generated_half_open_word_indices_are_accepted` |
| 生成的半开区间被 BDR 接受 | `tests/test_alignment.py::test_generated_half_open_word_indices_are_accepted_by_bdr` |
| 最小有效输入输出且无调试 stdout | `tests/test_alignment.py::test_alignment_minimum_valid_input_is_quiet` |

### 10.3 现有测试没有证明的内容

即使全部 30 个用例通过，也**没有**证明：

- Git LFS 拉取的 checkpoint 可实际加载；
- 默认 MTL 模型可对真实歌曲完成推理；
- Demucs 权重可下载、可离线使用或能提升质量；
- CUDA 路径、显存需求和 CPU 性能；
- 中文、日文、韩文、英文、俄文转写质量；
- 混合语言、数字、标点和罕见字符的正确行为；
- 音频与歌词端到端时间精度；
- BDR 对真实 posterior 的收益；
- `gen_lrc()` 截断降级的所有边界；
- 从非仓库根目录启动时的行为；
- 训练/评估链路可运行；
- 依赖、模型、demo 音频和歌词的许可证合规。

**[建议]** 任何改动触及以上区域时，不得仅以轻量绿测作为正确性证据。应先建立最小、可复现、获得授权的真实基线，并明确记录环境、资产 hash、输入样例和预期输出。

---

## 11. 工程、供应链与合规风险登记册

| 风险 | 证据 | 可能影响 | 原则级建议 |
|---|---|---|---|
| CWD 相对路径 | `lid.176.ftz` 与 `./checkpoints/...` | 从其他目录启动失败 | 变更前先建立多 CWD 基线，再设计资产解析兼容层 |
| 模块级全局状态 | fastText、G2P、NumPy seed | 初始化成本、并发、测试隔离和可重入性不清晰 | 显式化生命周期，但保留延迟加载与兼容行为 |
| 推理非完全确定 | smoothing 使用 PyTorch RNG；仅设置 NumPy seed | 同一输入 score/路径可能有微小差异 | 先量化差异，再决定随机策略和可复现合同 |
| 依赖事实源漂移 | requirements 与 Pipfile 版本/包集合不同 | 环境不可复现、独立模块破坏 | 明确唯一受支持安装源后再统一，不盲目升级 |
| 可能首次联网 | Demucs、faster-whisper | 离线部署失败、下载时间和供应链变化 | 区分核心推理资产与可选下载，记录缓存/离线方案 |
| `pykakasi` GPL | `phonetic.py` 注释及依赖 | 分发组合的许可义务 | 发布/再授权前由合格人员确认组合与传播义务 |
| 根许可证归属信息待确认 | 根 `LICENSE` 声明 Apache-2.0；末尾 `Copyright [yyyy] [name...]` 位于许可证标准附录示例中，并非仓库版权声明 | 仅凭许可证正文无法确认仓库及各资产的具体权利人/NOTICE 信息 | 由维护者确认版权、NOTICE 与资产级许可；不要把标准附录占位符误判为许可证无效 |
| 子目录另有 MIT 许可 | `t2l/mtl/LICENSE` | 上游代码归属和 notice 需要保留 | 重构/移动代码时保留来源、版权和适用许可记录 |
| demo/模型资产授权 | 仓库内未见足够来源说明 | 对外分发风险 | [待确认] 权利人、来源、允许用途和再分发条件 |
| 无 CI/linter/type checker | 仓库配置中未发现 | 仅本地测试，风格/类型问题不受门禁 | 在行为基线稳定后逐步加入，不把工具修复与业务重构混做一次提交 |
| 未接入模块依赖内部 API | `slid.py` | 第三方升级后静默失效 | 若正式化，先封装最小受支持 API 并锁定测试 |
| 静默/半静默降级 | G2P unknown→blank、LRC 截断、fastText 低置信仍继续 | 输出存在但质量不可知 | 增加结构化可观测性前先保持现有返回合同 |

本表不是法律意见，也不是安全或模型质量认证。

---

## 12. 给后续 AI 的重构守则

1. **先分类合同。** 区分 CLI 合同、`process()` API 合同和内部对齐协议，不能用内部清理替代外部兼容分析。
2. **模型相关常量按兼容变更处理。** phone 表、blank=40、类别 shape、采样率、Mel 参数、pooling、时间 resolution、state-dict key 任一变化都需要 checkpoint 级验证。
3. **同时检查两个 CLI 产物。** 默认终端中的增强 LRC 与文件中的标准 LRC 语义不同；`process(out_file)` 又是第三种写出责任。
4. **不夸大语言支持。** 有转写分支不等于混合语言可靠，也不等于使用原生语言 phone 模型。
5. **保留错误诊断价值。** 不把 decoder、Demucs、CUDA、checkpoint 和 alignment 错误统一包装成同一种输入错误。
6. **不自动接入实验工具。** `slid.py`、`lrc2json.py` 和繁转简必须先获得入口、合同、错误模型和测试。
7. **不把遗留训练代码视为已支持。** 在数据、缺失模块和最小命令可复现前保持 `[不可运行/不自包含]`。
8. **触及未测试区先建基线。** 真实 checkpoint、真实音频、多语言、GPU、CWD 和下载行为必须用受控样例验证。
9. **将路径和全局状态显式化时保留时机语义。** 尤其关注 fastText 首次转写加载、G2P 懒加载和预加载模型 tuple 的既有调用方。
10. **小步提交、证据随变更。** 每次只改变一类合同，新增测试并同步本文；不要在同一变更中同时重组目录、升级依赖、替换模型和改变输出。

---

## 13. 事实索引与维护约定

### 13.1 源码—能力—测试索引

以下表格仅适用于 `db8e714` Legacy 基线。当前入口只看第 15.1 和第 15.8 节；不得根据本表恢复已经删除的 `main.py`、`t2l/t2l.py`、`ext/`、训练或旧评估公共入口。

| 能力 | 主要源码与符号 | 测试证据 | 当前状态 |
|---|---|---|---|
| C01 CLI | `main.py::build_parser`、`cli` | `tests/test_cli.py` 只覆盖 parser 与转换函数；完整 `cli()` 未测试 | [已实现][部分受测试][环境依赖] |
| C02 API | `t2l/t2l.py::process` | `test_process_rejects_unsupported_format_before_audio_work`、`test_process_writes_utf8_output`；完整真实推理未测试 | [已实现][部分受测试][环境依赖] |
| C03 编码 | `ext/t2lutils.py::__get_file_encoding` | 无直接测试 | [已实现] |
| C04 歌词组织 | `t2l/t2l.py::process` | 无直接行为测试；现有 process 测试会 mock 转写和对齐依赖 | [已实现] |
| C05 语言转写 | `t2l/phonetic.py` | 无直接测试 | [已实现][环境依赖] |
| C06 音频/Demucs | `preprocess_audio`、`separate_vocals`、`__vocalize` | `tests/test_t2l.py` 覆盖回退、异常传播和 inference mode；真实文件/模型未测试 | [已实现][部分受测试][环境依赖] |
| C07 模型 wrapper | `wrapper.py::align`、`load_mtl_model`；`model.py` | `tests/test_wrapper.py` 使用 fake model 覆盖输入与推理边界；真实 checkpoint 未测试 | [已实现][部分受测试][环境依赖] |
| C08 对齐/LRC | `utils.py::alignment`、`alignment_bdr`；`t2l.py::gen_lrc` | 对齐器有直接测试；`gen_lrc` 降级无直接测试 | [已实现][部分受测试] |
| C09 标准化 | `main.py::to_standard_lrc` | `test_to_standard_lrc_removes_word_timestamps_with_long_minutes` | [已实现][受测试] |
| C10 异常 | `TxtValueError`、`AudioValueError`、`AlignmentValueError` | `tests/test_t2l.py`、`tests/test_alignment.py` 覆盖音频/对齐和第三方传播；`TxtValueError` 无直接测试 | [已实现][部分受测试] |
| X01 音频语言识别 | `t2l/slid.py::detect_language` | 无 | [未接入] |
| X02 LRC JSON | `ext/lrc2json.py` | 无 | [未接入] |
| X03 繁转简 | `ext/traditional_to_simplified.py` | 无 | [未接入] |
| N01/N02 训练评估 | `t2l/mtl/data.py`、`train.py`、`eval.py`、`eval_bdr.py` | 无 | [不可运行/不自包含] |

### 13.2 维护规则

发生以下变化时必须重新核对本文：

- CLI 参数、默认值、stdout 或文件命名/格式；
- `process()` 签名、返回值、写文件语义或模型预加载表示；
- 语言检测优先级、转写库、G2P、phone 字典；
- 采样率、声道策略、Mel/模型结构、posterior shape；
- `[start, end)` 索引、blank 类、最短帧数、BDR 输入；
- checkpoint/LID/Demucs 资产定位；
- 领域异常和第三方异常传播；
- 未接入模块进入正式主链；
- 训练/评估变为可复现能力。

状态升级规则：

- 只有存在正式入口且输入、输出和失败边界明确，才标记 `[已实现]`；
- 只有该条所述能力合同的主要行为都有直接自动化断言时，才增加 `[受测试]`；仅覆盖部分关键行为时使用 `[部分受测试]`，并在测试索引中列明未覆盖范围；
- 新增但未接入主链的代码默认标记 `[未接入]`；
- 训练/评估只有在依赖、数据和最小命令可重复执行后，才能移除 `[不可运行/不自包含]`；
- 无法从仓库确认的许可证、资产来源或质量结论保持 `[待确认]`，不得由 AI 猜测补全。

---

## 14. 本次验证结果与后续真实基线

本交接文档完成后，已在仓库根目录实际执行：

```bash
PYTHONDONTWRITEBYTECODE=1 python -m pytest -q -p no:cacheprovider
# 结果：30 passed in 1.20s

python -m compileall -q main.py t2l tests
# 结果：退出码 0，无语法错误输出
```

本轮 `compileall` 产生的 `__pycache__` 已清理。上述结果只验证当前轻量测试和语法，不扩展第 10.3 节列出的证明范围。

另完成了不运行真实音频推理的 CPU checkpoint 加载：

```text
Baseline  Baseline  False  cpu  acoustic_params=4771497  boundary_params=0
MTL_BDR  MTL       True   cpu  acoustic_params=5739015  boundary_params=152033
```

这证明当前 checkout 的三个本地 checkpoint 能被当前模型类读取，但不证明真实 posterior、DTW 结果或歌词时间准确。

尝试扩大到真实依赖冒烟时，当前活动解释器为 Python 3.11.4，仓库没有已建好的 Pipenv 环境，也没有按 requirements 安装完整依赖：CLI 编码路径缺 `chardet`，多语言路径缺 `pypinyin`，繁转简路径缺 `opencc`；当前 torchaudio 真实 MP3 读取还因缺 `torchcodec` 抛 `ImportError`，该类型不会触发现有 librosa 回退。`lrc_to_json()` 的一个合法输入可返回 Python `list[list[dict]]`，与第 9.2 节描述一致。检查期间 Pipenv 自动创建的空虚拟环境已立即删除，未安装依赖。

因此本轮没有宣称完整 CLI、五语转写、真实音频解码或端到端推理成功。要复现正式运行路径，应在仓库声明的 Python 3.9/3.10 范围内建立隔离环境后重新安装并锁定依赖；不要把当前未配置的全局 Python 失败直接归因为业务代码回归。

除此以外，建议在获得授权和完整 Git LFS 资产后另建真实基线：

- 默认 CLI demo；
- `vocalize=0/1` 各一例；
- Baseline、MTL 与 BDR 变体；
- CPU 与可用时的 CUDA；
- 五种语言各一组受控歌词；
- 混合语言、数字、空行、已有 LRC 标签；
- 从仓库根目录和其他 CWD 启动；
- stdout、`process(out_file)` 和 CLI 标准文件分别做 golden 输出。

真实基线应记录依赖版本、设备、模型文件 hash、输入资产来源和允许用途。没有这些证据时，只能说明“代码路径存在”，不能说明“质量等价”或“部署已验证”。

---

## 15. 2026-09-05 v2 当前实现附录

本附录用于消除第 0–14 节与当前 dirty worktree 之间的时态歧义。原 `main.py`、`t2l/t2l.py`、`t2l/mtl/wrapper.py`、`ext/`、训练和旧评估入口已按 R7a 删除；不得根据历史能力卡恢复这些公共入口。当前权威架构、测试 ID、命令、hash 和 No-go 先看本附录最后一个“唯一当前恢复入口”，再看主计划文末当前 Gate。

### 15.1 C01 到 C10 现行交接矩阵

| 能力 | v2 正式入口与数据合同 | 已落地实现 | 当前直接证据 | 仍未证明 |
|---|---|---|---|---|
| C01 CLI | `ai-auto-lrc` -> `t2l.adapters.cli:main`；stdout XOR 原子文件；稳定 exit code | 参数、UTF-8、verbose/debug、signal、broken pipe、路径类型、0600 mode、installed version 均已合同化 | 宿主 contract/package；canonical 四路 installed CLI、repo 外 CWD、site-packages import | 双平台 cold wheelhouse、staging、签名发布 |
| C02 Python API | `t2l.create_runtime(config)` + `t2l.process(request, runtime=...)`；返回结构化 `AlignmentResult` | API 无文件/stdout 副作用，结果包含 status、spans、timebase、profile、diagnostics | real MP3 的四路 public API canonical exact | GPU、Demucs 和大规模输入资源上限 |
| C03 歌词文件编码 | CLI 的 lyrics I/O adapter；解码结果再进入纯歌词计划 | UTF-8/BOM、候选编码、不可解码和控制字符错误稳定；API 继续接收已解码行 | unit/contract 编码矩阵和 locale 子进程 | 更广泛真实语料与平台 locale 矩阵 |
| C04 歌词清理与行组织 | `LegacyV1LyricsAdapter.prepare()` -> self-contained lyrics plan | tokens、phonetics、phones、word/line 半开 spans 和 diagnostics 一次生成 | unit/component；public-e2e lyrics plan snapshot | natural non-empty partial 的产品语义 |
| C05 语言和 G2P | `PhoneticConverter` + `OfflineG2PProvider`，资产由 manifest 和显式 root 绑定 | LID 与 NLTK zip 私有 materialized set；默认离线；同 runtime 锁；中断可重试 | 真实 `hello -> HH AH0 L OW1`、断网/空 cache、TOCTOU、并发 | 五语完整 canonical 矩阵、多 runtime 显式释放 |
| C06 音频与 Demucs | `AudioAdapter.decode()`；decoder policy 显式；Demucs optional 且默认关闭 | torchaudio 默认、librosa-mono 仅显式、声道/重采样固定、无静默 fallback | WAV/MP3 component；real MP3 canonical decode fingerprint；Demucs 未加载反证 | Demucs 权重 manifest、installed extra 真实离线执行、双平台 codec |
| C07 声学推理 | `LegacyV1Inference`；profile 冻结，四路模型按请求惰性加载 | checkpoint 不可变 bytes snapshot；strict load；runtime-local 一次初始化；seed 局部化 | feature/numeric canonical、四路 public-e2e、并发和 RNG | CUDA、性能门槛、signed release 资产绑定 |
| C08 DTW BDR LRC | inference 产生结构化 spans；domain renderer 纯函数输出 line/word LRC | LegacyV1 DTW/BDR/tie-break/timebase 保持；完整性在 renderer 前判定 | reference/vector、numeric、real public-e2e；Baseline_BDR 已补齐 | non-empty partial ADR；完整 posterior/DP 资源预算 |
| C09 标准 LRC | v2 不再发布旧“增强转标准”独立 CLI；line/word 由 `TimestampMode` 直接选择 | 行级与逐字 renderer 都是同一结构化结果的视图 | unit snapshots；四路 canonical API/CLI byte exact | 旧独立命令兼容性不在范围内 |
| C10 错误与可观测性 | `t2l.errors.ERROR_REGISTRY` + `T2LError`；observer 只到 stderr | 46 个稳定 code 绑定 type/stage/details/cause/exit/safe-message；未知错误 fail closed | registry AST/contract、CLI redaction、progress 顺序、compatibility fail-fast | 新 optional backend 的细粒度 code 需先注册；release 观测与运营告警 |

### 15.2 2026-09-05 验证和资格边界（历史快照，以第 15.5–15.6 节为准）

- 宿主全量：`235 passed, 17 skipped, 22 warnings`；portable coverage `85.36%`。
- canonical：Linux x86_64、CPython 3.10.21、CPU-only、断网、只读运行，`13 passed, 7 warnings`。
- inventory：274 个稳定 ID；80 个有实现证据；11 个 `qualified-canonical`；0 个 `qualified-release`。
- real decoder/public API/installed CLI 已形成 functional canonical；这关闭了历史第 14 节所述“未验证真实链路”的缺口。
- Linux/macOS cold wheelhouse、完整资源预算、Demucs 实际 optional-extra、Git/LFS/dirty-state 恢复、signed release binding、SBOM、attestation 和 rollback drill 未完成。

该快照总判定为 **Implementation in progress；Release No-go**。当前验证数字和恢复入口见第 15.5–15.6 节；不得先清理当前大量 modified/deleted/untracked 文件，它们属于 v2 重构成果。

### 15.3 当前 Teams 执行方案入口

2026-09-05 的四角色架构结论、C01–C10 可执行能力卡、资源与 runtime 待决策项、P0–P5 工作包、测试用例和本地 gate 实测已固化到 [`team-sessions/team-session-2026-09-05.md`](./team-sessions/team-session-2026-09-05.md)。后续接手者应以该文件作为会话恢复清单，以主计划第 22 节作为当前门禁摘要；不得用本文第 0–14 节的 LegacyV1 历史入口覆盖 v2 现状。

### 15.4 W1b-3 Linux package sidecar 更新

W1b-3a–3e 已于 2026-09-05 完成实现和真实 Linux capture。接手者应从主计划第 25 节和 W1b 专项方案第 16 节恢复：package 四件套现在由真实 `linux/amd64` 断网冷安装产生并由 capture 独立重算，Linux scope 最高为 `implemented-unqualified`。不得再依据本文较早段落恢复 `LAYER_CLOSURE_UNIMPLEMENTED` 到 package 分支，也不得把 Linux 单平台结果写成 `PKG-012/017` 或 release 证明。W1b-4 的后续状态见第 15.5 节。

### 15.5 W1b-4 canonical sidecar 更新

W1b-4a–4f 已于 2026-09-06 完成实现、合同反证和真实 Docker capture。接手者应从主计划第 27 节和 W1b 专项方案第 18 节恢复：canonical 十二件 closure 由 host producer、container observer、capture consumer 三段产生并独立重算；base repo digest、build iid、container inspect、runtime probe、site-packages origin、三份 oracle 与源码 snapshot 已交叉绑定。canonical 缺件只报 `REQUIRED_ARTIFACT_MISSING`，完整但语义无效只报 `RUN_ARTIFACT_BINDING_INVALID`，旧 `LAYER_CLOSURE_UNIMPLEMENTED` 不得恢复。

文档回写前宿主全量为 `481 passed, 18 skipped, 22 warnings`；真实 canonical 为 `13 passed, 7 warnings, 0 skipped`，两种 receipt verify mode 均在各自边界内有效。W1b-4 当前为 **Go / implemented-unqualified**，但 `claim.spec_ids=[]`，且 checkpoint 只有 size/hash 记录；这不是独立恢复、qualified-canonical 或 release 证明。

### 15.6 首版 W1b-5 恢复入口（历史，已由 15.8 取代）

当时下一阶段的字段级上位方案是 W1b 专项方案第 19 节；该阶段的编码与安全加固恢复入口是 [`W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md`](./W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md) 第 15 节，四角色初评与二次反审保存在 [`team-sessions/team-session-2026-09-06-2.md`](./team-sessions/team-session-2026-09-06-2.md)，当时总体 Gate 在主计划第 28.1 节。当前入口统一见第 15.8 节。

首版 assessment-only manager、配置和合同测试已经存在，定向记录为 `47 passed`，但这不是 W1b-5a/5b 完成证据。二次 Teams 评审仍有五个 P0：父链 symlink、source/publish TOCTOU、外部 rules/assessment trust anchor、可逆 pattern 泄漏、任意 regex/整文件读取 DoS；P1 还包括 transaction/event ledger、嵌套 exact schema、精确权限、分类和 CLI 输出/退出码。接手者必须按执行计划第 15.3 节 S1–S6 顺序推进，并执行第 15.4 节新增测试矩阵；不得只重复现有 47 个 nodeid 后宣称 Go。

当前实现范围只允许 `inspect`、`scan` 和 `verify-inspection`。5c local export、5d encrypted archive/restore、5e expiry/destruction 均未获授权，必须等待 `D-REL` 锁定 owner、期限、密钥 custody、RPO/RTO、checkpoint 策略和双人销毁审批。

当前总判定仍为 **Implementation in progress；Release No-go**。W1b-5、macOS cold install、`PKG-012/017` 双平台、完整资源预算、Demucs 实际离线能力、`AlignmentRuntime.close()`、独立恢复、SBOM、attestation、签名和 rollback 均未关闭。禁止自动上传、prune、删除、commit、push 或发布；不要清理当前 dirty worktree。

### 15.7 S7–S11 前的 W1b-5 恢复入口（历史，已由 15.8 取代）

加固版当前验证为 retention `69 passed`、retention+capture `200 passed`、宿主全量
`550 passed, 18 skipped, 22 warnings`；实际 sealed PASS/BLOCKED verify 退出码为 0/3。
但最终反审发现 path-based 父目录替换竞态、独立 expected digest 缺失、全局 hit/report
上限的已提交后自失效，以及特殊文件/identity/transaction/ledger 等测试缺口。因此不得将
15.6 的首版 47 项或本节 69 项解释为 W1b-5a/5b Go。

该历史阶段要求接手者从 [`W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md`](./W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md)
第 16.2–16.3 节的 S7 descriptor paths 开始；S7–S11 目前已经实施，不能再按这段恢复。
仍然不要删除/覆盖现有 `.control`，不要退化原子 no-replace，不要新增
export/archive/destroy；当前执行顺序见第 15.8 节。

### 15.8 W1b-5 S7–S11 实施后的唯一当前恢复入口

S7–S11 已经实施并进入合同测试。当前验证为 retention `125 passed`、capture `135 passed`、联合 `260 passed in 88.21s`；锁定环境宿主全量为 `610 passed, 18 skipped, 22 warnings in 145.79s`。18 个 skip 仍是 canonical-only 和缺 wheelhouse 的分层门禁，不是 Release 通过。旧的 47、69、200、550 数字只保留为历史检查点。

新的 receipt 验证公共入口为：

```python
verify_receipt_at(
    run_fd: int,
    receipt_name: str,
    mode: str,
    repo_root_fd: int | None = None,
) -> dict[str, Any]
```

原 `verify_receipt(Path, ...)` 保持兼容，但会打开 run/repository fd 后委托 fd-aware verifier。archived 模式下 receipt、SEALED、logs、source、inputs、artifacts、artifact binding 和 sealed closure 都相对 run fd 读取；目录逐级拒绝 symlink，leaf 使用 nonblocking no-follow open，FIFO 不会阻塞。

current-source 必须保留平台边界：Linux 使用 `/proc/self/fd`；macOS 使用 `F_GETPATH` 加前后 `(dev,ino)` 复验。Git 与工作树扫描是多次顺序观察，不是原子 checkout snapshot，不能排除读取期间的 swap-and-restore/ABA，也不构成 source/checkpoint 独立恢复。

retention manager 当前只允许 `inspect` 和 `verify-inspection`。默认 rules/assessment 由代码内 raw-byte digest 绑定；自定义 path 必须同时提供对应 expected digest。该 digest 证明“输入 bytes 与调用方给定值一致”，不自动证明调用方有治理授权、签名信任或 export/archive/destruction 权限。`actor_claim` 的 assurance 固定为 `self-asserted-local`，不是认证身份。

Teams 第三次反审结论：W1b-5a 只在 checked-in defaults、受信脚本和 local assessment-only 前提下为 **Conditional Go**；W1b-5b 仍为 **No-go / hardening required**。两个 P0 是：

1. `LOCK`、ledger、write、rename、fsync 与 final verify 没有持有同一组 control fd 贯穿整个事务，需关闭同 UID 替换控制树后的 lock split；
2. event 原子 rename 已可能成功后的 post-stat、cleanup、mode/fsync/source/final-verify 失败尚未全部统一为 `CONTROL_COMMIT_UNCERTAIN`。

下一位接手者只从 W1b-5 执行计划第 17.5 节 S12 开始，不得重做 S1–S11：

1. S12 transaction fd context；
2. S13 event may-be-visible 单向错误状态机；
3. S14 目录遍历物化前的 file/byte/metadata 限流；
4. S15 macOS/Git swap/ABA 反证或 diagnostic-only 降级；
5. S16–S18 双进程 crash/并发、真实 CLI/ownership、security coverage 与 Linux 实跑；
6. 人类指定 digest owner、rotation approver、ADR/审计位置与 Go 签署人。

出现 staging、orphan、invalid ledger 或 `CONTROL_COMMIT_UNCERTAIN` 时，不得删除 `.control`、补写 event、修改 hash 或直接重跑。用原 receipt、exact inspection、exact event、相同 mode 和独立保存的 expected digests 执行只读 `verify-inspection`，然后人工升级；当前不存在自动恢复或清理 API。

最新字段、能力闭合矩阵、测试 node、真实 PASS/BLOCKED run IDs 和人工恢复 runbook 的唯一技术入口是 [`W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md`](./W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md) 第 17 节；跨工作包 Gate 在主计划第 28.3 节；角色讨论历史在 [`team-sessions/team-session-2026-09-06-2.md`](./team-sessions/team-session-2026-09-06-2.md) 第三次复核。

W1b-5c export、5d archive/restore、5e expiry/destruction 仍是未授权、未实现。继续禁止 upload/sync、自动 prune/delete、CI、签名、发布、commit 和 push；不要清理当前 dirty worktree。Release 继续 **No-go**。

### 15.9 S12/S13 第一批实现后的唯一当前恢复入口

不要再从第 15.8 节的“S12 尚未实现”状态开始。当前工作区已经实现三个持久 control fd 与 active transaction anchor，并在 event no-replace rename syscall 成功时建立 commit latch；新增 S12/S13 9 个节点全部通过。主任务独立证据：

```text
S12/S13:            9 passed, 125 deselected in 3.88s
retention+capture:  269 passed in 58.95s
host full suite:    619 passed, 18 skipped, 22 warnings in 113.84s
ruff/compile/diff:  PASS
```

本批不能标为 S12/S13 完全闭合。第四次 Teams 反审要求下一位只从专项计划第 18.4 节 S12a/S13a 开始：

1. 从 pinned `run_control_fd` 相对打开并绑定 `inspections/events`，补 context 初始化 swap；
2. 覆盖 ledger 后、inspection publish 后、event rename 后和 final verify 中途的 control tree swap；
3. 在 final verify 后、API return 前再次复核 control namespace；
4. 冻结并测试 `LOCK_UN`、lock close、context exit 在 event 可见后的错误语义；默认保持单向 `CONTROL_COMMIT_UNCERTAIN`，除非人类 ADR 明确另设状态；
5. fault 撤销后独立验证 uncertain artifact 的 hash、mode、linkage 与 retry/ledger 分类；
6. S12a/S13a 通过后才继续 S14–S18。

第 15.8 节的 PASS/BLOCKED run IDs 生成于 S12/S13 代码之前，只能当历史证据；完成 S12a/S13a 后必须使用最新代码重新生成并独立 verify。当前 18 个 skip 仍是 13 个 canonical-only 和 5 个缺 wheelhouse package case，不能视为 Release 通过。

Gate 保持：W1b-5a Conditional Go（checked-in defaults、受信本地 assessment-only）；W1b-5b No-go / hardening required；5c/5d/5e 未授权、未实现；Release No-go。继续禁止 upload/sync、自动 prune/delete、archive/restore、CI、签名、发布、commit 和 push，不要清理 dirty worktree。

### 15.10 S12a–S15 实施后的唯一当前恢复入口

不要再从第 15.9 节的 S12a/S13a required 状态恢复。当前生产代码已经完成：

- `inspections/events` 从 pinned `run_control_fd` 相对打开并核对同一 generation；final verifier 后、API return 前再次复核 control namespace；
- event-visible 状态覆盖 `LOCK_UN`、lock-fd close 与 context exit；主异常优先，event 已可见后的纯 teardown 失败精确为 `CONTROL_COMMIT_UNCERTAIN`；
- sealed tree 的 entry/file/declared-byte/snapshot-metadata 预算在递归枚举和排序前执行，cap+1 立即停止；
- current-source 连续两次完整 observation，不一致为 `CURRENT_SOURCE_OBSERVATION_UNSTABLE`；CLI 固定标记 diagnostic、non-transactional、ABA-not-excluded；retention schema-v1 的 current-source inspect 在任何 control I/O 前以 `CURRENT_SOURCE_DIAGNOSTIC_ONLY` 拒绝。

当前测试事实：retention `154 passed`，capture `142 passed`，联合重跑 `296 passed in 69.54s`。第一次联合运行曾为 `1 failed, 295 passed`，失败节点是 external trust-anchor 合同且后续单跑/重跑通过；该顺序疑似 flaky 必须保留并继续追踪。S15 与文档落盘后的宿主全量已实跑为 `646 passed, 18 skipped, 22 warnings in 123.64s`；Ruff、compileall、`git diff --check` 和本批文档相对链接检查通过。S15 前的 634 只保留为历史检查点。

最新 PASS/BLOCKED evidence 已在 `/private/tmp/ai-auto-lrc-w1b5-final-20260906-02/` 完成真实 capture、inspect 和独立 verify：PASS exit `0/0`，BLOCKED exit `3/3`，两棵 sealed tree signature 前后不变。精确 run、inspection、event 与 signature 见专项计划第 19.2 节；它仍不是 current-source、power-loss、恢复或 Release 证明。

下一位只按以下顺序继续：

1. 已完成文档落盘后的静态检查和宿主全量 checkpoint；保留首次联合 flaky 记录；
2. 最新 PASS/BLOCKED sealed evidence 已完成；旧 run ID 仍不得作为 S12–S15 证据；
3. 下一步执行 S16 真实双进程竞争与 staging/inspection/event/fsync/teardown crash 分类；
4. S17 真实 CLI 脱敏、config hardlink/FIFO/socket/wrong owner、Linux device 与 source unknown-key；
5. S18 安全脚本 branch coverage、Linux `renameat2`/`/proc/self/fd`、package/canonical required runner 零意外 skip；
6. 再做 W1b-5b Go/No-go 复审；5c/5d/5e 不随之自动开放。

W1b-5 的精确测试矩阵和错误语义见 [`W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md`](./W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md) 第 19 节；跨工作包资源预算、双平台 package、Demucs、runtime close、独立恢复、SBOM/attestation/签名/rollback 的执行 DAG 见 [`AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md`](./AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md) 第 29 节；Teams 原始讨论见 [`team-sessions/team-session-2026-09-06-2.md`](./team-sessions/team-session-2026-09-06-2.md) 第五次复核。

当前 Gate：W1b-5a Conditional Go（trusted local assessment-only）；W1b-5b No-go；current-source 只可作 diagnostic observation，transactional/ABA-excluded/qualification/source-restorability 均 No-go；5c/5d/5e 未授权、未实现；Release No-go。

继续禁止 commit、push、创建 CI、upload/sync、签名、发布、自动删除、清理、归档或恢复。保留全部 modified/deleted/untracked 工作区成果。

### 15.11 S16 完成后的唯一当前恢复入口

不要再从第 15.10 节的“S16 下一步”开始。S16 已实现并在当前 Darwin arm64/Python 3.11.4 宿主验证：

- 两个真实独立 publisher 通过 pipe barrier 同时竞争，最多一个有效 commit；loser 仅允许 `CONTROL_LOCKED` 或 `INSPECTION_ALREADY_COMMITTED`；
- `staging-fsynced`、`inspection-fsynced`、`event-renamed`、`events-fsynced`、`run-fsynced`、`teardown-entered` 六个真实父进程 SIGKILL checkpoint；
- 每个残留态由两个 fresh classifier subprocess 连续得到相同结果；classifier、verify、retry 零写入；sealed run 不变；
- crash 后 flock 由 kernel 释放；staging/orphan 不自动清理；每个状态最多一个 published inspection 和 event；
- 测试 worker 只 monkeypatch 私有 seam，生产 CLI、环境变量、配置和 API 没有 crash switch。

首轮 RED 为 `7 passed, 1 failed`，双 publisher loser 曾返回 `SYMLINK_FORBIDDEN`/`CONTROL_PUBLICATION_FAILED`；trace 定位为首次并发初始化时 `_open_lock()` 的 `O_CREAT` 得到 `ENOENT`。生产修复是在 pinned run dirfd 上先 `O_CREAT|O_EXCL`，仅 `FileExistsError` 后无创建重开，并在 flock 前后核对 lock fd/目录项 `(dev, ino)`。不得撤销为单次 `O_CREAT`，也不得放宽 loser 错误集合。

最新验证：

```text
S16 three rounds:      8 passed / 8 passed / 8 passed
retention:             162 passed in 52.15s
capture + retention:   304 passed in 82.53s
host full:             654 passed, 18 skipped, 22 warnings in 131.61s
static/diff/doc links: PASS
```

下一位只从 S17 开始：真实 CLI 脱敏；rules/assessment hardlink、FIFO、socket、wrong-owner；Linux device；source unknown-key fail closed。然后执行 S18 branch coverage、Linux/macOS/package/canonical qualification 和最新 evidence refresh，再复审 W1b-5b。

S16 只获得当前 macOS process-crash hardening Go；power-loss、祖先目录 durability、`F_FULLFSYNC`、Linux required、同 UID 主动完整 ABA、自动恢复均未证明。W1b-5b、Release 继续 No-go；5c/5d/5e 仍未授权。精确事实和测试矩阵见 [`W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md`](./W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md) 第 20 节；Teams 讨论见 [`team-sessions/team-session-2026-09-06-4.md`](./team-sessions/team-session-2026-09-06-4.md)。

继续禁止 commit、push、创建 CI、upload/sync、签名、发布、自动删除、清理、归档或恢复。保留全部 modified/deleted/untracked 工作区成果。

### 15.12 S17 当前宿主完成后的唯一恢复入口

不要再从第 15.11 节的“S17 下一步”开始。当前 macOS 可执行范围已新增 16 个 S17 节点：rules/assessment hardlink、FIFO、socket、伪造 wrong-owner；真实 CLI secret/HOME/控制字符拒绝与 secret filename blocked 脱敏；capture `source` 顶层 unknown claim fail-closed。

首轮定向 `10 passed, 6 failed` 必须保留：3 个 production RED，2 个 Unix socket 绝对路径过长 fixture 错误，1 个 secret filename 应为 blocked 的期望错误。修正后定向 16 个节点连续 20 轮全过。第一次联合 `1 failed, 319 passed` 是新增 exact-shape 提前覆盖 S15 `observation_limit` 精确错误；生产顺序修正后旧+新 5 个节点通过，联合重跑 `320 passed`。

```text
capture:              145 passed in 23.91s
retention:            175 passed in 57.91s
combined retry:       320 passed in 102.99s
host full:            670 passed, 18 skipped, 22 warnings in 190.60s
static/diff/doc links: PASS
```

下一位只从 S18 开始：

1. 两个安全脚本独立 line/branch coverage 与关键分支清单；
2. Linux `renameat2`、`/proc/self/fd`、block/char device、S16 双进程矩阵；
3. package/canonical required runner 的 collected/passed/skipped/deselected；
4. 最新代码 PASS/BLOCKED evidence refresh；
5. W1b-5b Go/No-go 复审。

Linux device 和真实跨 uid 尚未执行，因此 S17 只是当前 macOS config/CLI/source-shape Conditional Go，不是完整双平台 Go。精确事实见 [`W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md`](./W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md) 第 21 节；Teams 记录见 [`team-sessions/team-session-2026-09-06-5.md`](./team-sessions/team-session-2026-09-06-5.md)。W1b-5b 与 Release 继续 No-go；5c/5d/5e 未授权。禁止事项和 dirty worktree 保留要求不变。

### 15.13 S18 qualification 当前恢复入口

本节取代第 15.12 节中“Linux device 未执行”和“下一位只从 S18 开始”的旧时态。不要重做已经完成声明范围的 S16/S17；先读 [`W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md`](./W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md)，再从其 S18-0 policy/manifest/verifier 合同继续。

当前分层状态：

| Lane | 当前结果 | 恢复动作 |
|---|---|---|
| capture coverage | line 79.1966%、branch 67.6768%、combined 75.7545% | 先写 formal artifact owner/mode/nlink、closure budget 等真实 RED，再补其余安全分支 |
| retention coverage | line 86.3192%、branch 76.25%、combined 83.8452% | branch 仍低于 S18 80%；补关键分支并纳入独立 manifest |
| Linux security | S16+device 9 passed；proc-fd/source 9 passed | 以 exact nodeids 重跑并保存 JUnit/environment/hash；不作性能或跨 uid声明 |
| macOS package | 34 passed、1 failed、1 deselected；stale wheelhouse manifest | 完整重建 wheelhouse，禁止手改 hash |
| canonical | 当前 image 13 passed、0 skipped | 最终源码稳定后重建重跑 |
| host/evidence | 全量数字与 sealed evidence 早于最新测试/代码 | 最后刷新，不推测 skip 数 |

执行顺序：security policy/manifest/verifier → capture/retention 独立 coverage → Linux exact-node bundle → macOS package 重建 → canonical/host/static → 最新 PASS/BLOCKED evidence → W1b-5b 复审。精确事实见 W1b-5 计划第 22 节，跨工作包状态见主计划第 32 节，Teams 讨论见 [`team-sessions/team-session-2026-09-06-6.md`](./team-sessions/team-session-2026-09-06-6.md)。

当前只有 Linux functional 与 canonical functional 局部 Go；S18、package、W1b-5b 和 Release 均为 **No-go**。W1b-5c/5d/5e 未授权。继续禁止 commit、push、创建 CI、upload/sync、签名、发布、自动删除、清理、归档或恢复，并保留全部 dirty worktree 成果。

### 15.14 S18 方案落盘后的当前交接入口

第 15.13 节保留 S18 启动时的 RED。当前 raw coverage 已推进到 capture 273 passed、line/branch 90.7280%/84.4660%，retention 244 passed、1 个声明的 Linux-device platform skip、line/branch 93.9320%/89.1089%；macOS package 在补齐 `PKG-024` 后为 37 passed、0 skip/fail。Verifier 合同 41 passed，但 nested walker 仍需独立命名和度量，最终 manifest/security Gate、Linux package、canonical/host/evidence refresh 尚未完成。

接手者不要从旧百分比重新探索，也不要直接把外层 walker 的 100% 写成安全闭环。先读 [`W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md`](./W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md) 第 17 节，按 R0 manifest 裁决 → R1 walker 提取 → R6 同源 refresh 执行；R2–R5 是后续大型函数重构波次，不得与资格 evidence 刷新混成一次不可回滚改动。S18、W1b-5b、Release 继续 No-go，5c/5d/5e 仍未授权。

### 15.15 S18 当前恢复入口

第 15.14 节和主方案第 17.8 节现为 historical checkpoint。当前可执行事实、17 项能力逐项状态、P0测试规格、Linux runner v2、回滚单元与最终DoD统一维护在 [`W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md`](./W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md) 第 17.9 节；本交接文档不复制易漂移hash和测试数字。

接手者从第 17.9.5 节的第一个未完成波次开始，并保留所有RED、skip、retry、modified/deleted/untracked文件及仓库根 `./=`。当前S18、W1b-5b、W1b-5c/5d/5e和Release仍为No-go；不commit、push、创建CI、上传、签名、发布、清理、归档、恢复或销毁。

### 15.16 S18 2026-09-07 当前恢复入口

第 15.15 和 S18 主方案第 17.9 节已是 historical checkpoint。当前已验证的 R0.2/R1.2、macOS/Linux Security Gate、剩余 `S18-COV-015`、P1 测试与最终 package/canonical/host/sealed-review DAG 统一见 [`W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md`](./W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md) 第 17.10 节。本文不复制当前 hash 或 pass 计数。

下一位接手者从第 17.10.7 节 A1 开始，不重做已完成的 Linux exact-node/native rename 测试。继续保留全部历史证据、dirty worktree 和根 `./=`；S18、W1b-5b、Release 仍 No-go，5c/5d/5e 未授权。

### 15.17 S18 P1 加固与最终资格化当前入口

第 15.16 节和 S18 主方案第 17.10 节保留 COV-015 尚未完成时的历史恢复指令。`S18-COV-015` 的真实 runner integration 已完成；当前应从 [`W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md`](./W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md) 第 17.11 节恢复。该节已经把 SRC frozen bytes、JUnit canonical grammar、strict xfail/config/events、ABA claim boundary、证据失效矩阵、package 证据强度差异和最终 B0–B13 DAG 固化为唯一详细执行方案。

恢复时先确认正在进行的 P1 原子切片是否已产生完整 RED/GREEN 和最终 SHA，再从第 17.11.5 节第一个未验收步骤继续。不要从 17.10 的 A1 重做 COV-015，也不要把 macOS functional package lane 与 Linux capture-bound receipt 合并声称为等强双平台 qualification。

### 15.18 S18 P1 版本化方案入口

第 15.17 节和 S18 17.11 保留初始 P1 设计。当前 Teams 对抗审阅已把恢复点前移到 pytest hermeticity：entry-point plugin、`PYTEST_PLUGINS`、`PYTEST_ADDOPTS`、`conftest.py`、plugin module shadowing 及 JUnit/events outcome consistency 尚未闭合。

后续只从 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 版本 `S18-P1-PLAN-v1.0` 恢复；文件 SHA-256 为 `027d0350f8d3d2074828a2f2cf6a3645808f7e1bf7fb59ac27081d6857fb8c61`。执行者必须先重算 hash，再从其 DAG 第一个未完成步骤继续。当前默认起点是 B1 hostile environment/plugin/conftest RED，不得直接刷新旧平台 Gate。

当前 95 个 security contracts 只构成 historical checkpoint。S18、W1b-5b、Release 继续 No-go，5c/5d/5e 未授权。

### 15.19 S18 P1 当前冻结指针

第 15.18 的 v1.0 指针保留为首次落盘 checkpoint。当前执行版本已升级为 `S18-P1-PLAN-v1.2`，补齐真实 XFAIL runner、plugin identity、events 生成端 limits、toolchain lock binding 和 typed ABA 测试。权威文件 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 的 SHA-256 为 `ebc7bd3dcee085ca590d22df4d7fe2bc097a76efc4c463b5ed21e8ba06128683`。

恢复时只从该文件第 15.4 节继续；当前默认起点仍为 hostile real-runner RED。任何旧 macOS/Linux 绿色均为 diagnostic/historical，不能跳过 hermeticity 修复。

### 15.20 S18 P1 最终架构冻结指针

第 15.19 的 v1.2 指针保留为中间 checkpoint。当前权威版本为 `S18-P1-PLAN-v1.3`，文件 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) SHA-256 `1ee9a126586c4321714a84bd195db0fb36cf4c6925dba06940b5723dbb539429`。从其第 16.5 节第一个未完成步骤继续；不要从旧 B3 或 ABA 直接跳到平台刷新。

当前 Gate 不变：S18、W1b-5b、Release 仍为 No-go；W1b-5c/5d/5e 未授权。继续禁止 commit、push、CI、upload/sync、签名、发布、archive、restore、delete 和 destruction；保留全部 dirty worktree、根 `./=`、RED、fixture error、flaky、retry 和旧 attempt。

### 15.21 S18 P1 v1.4 当前恢复入口

第 15.20 节保留 v1.3 checkpoint。最新 Teams 续接已把当前实现状态和后续无歧义执行规范固化到 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第 17 节，版本 `S18-P1-PLAN-v1.4`，SHA-256 `9cb1a2c534cab265aa43ec0b5e3d651392ba3e9ae4cce81406a834772dd07c68`。

下一位从第 17.8 节 B3c trusted plugin identity RED 继续。不要重做 B3b hostile host contracts 或 B3d phase characterization；二者是可复核 implementation checkpoint，但在 B3c schema/toolchain closure 后仍需 rebase/reverify。S18、W1b-5b、Release 继续 No-go，5c/5d/5e 未授权，全部 dirty worktree、根 `./=` 和历史 attempt 必须保留。

### 15.22 S18 P1 v1.5 当前恢复入口

第 15.21 节保留 v1.4 checkpoint。当前权威方案为 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第 18 节，版本 `S18-P1-PLAN-v1.5`，SHA-256 `59d42eaed5f5323255d510e3f6f4e5bd784c8d84ea329ffb1f01f1098dc4f262`。Teams 裁决为 [`team-sessions/team-session-2026-09-07-4.md`](./team-sessions/team-session-2026-09-07-4.md)，SHA-256 `91af3b63a6e9ec313c8ad343a71d993aa6e6339bdc5604fe6dfc0b1df12481c1`。

唯一下一步为方案第 18.1/18.4 节的 B3e-S：先冻结稳定 scenario IDs、scenario manifest 和 P1 ID authority，再修正 B3c RECORD/no-replace 语义并进入 B3f-L、B3f-R。B3c/B3e 当前只有 host implementation/contract checkpoint；不得从 B3c RED 重做，也不得据此启动最终平台资格化。

当前 Gate：S18、W1b-5b、Release 继续 No-go；5c/5d/5e 未授权。必须保留 dirty worktree、根 `./=`、全部 RED/fixture error/retry/skip/旧 attempt；禁止 reset、checkout、clean、commit、push、CI、upload/sync、签名、发布、archive、restore、delete 和 destruction。

### 15.23 S18 P1 v1.6 当前恢复入口

第 15.22 节保留 B3e-S 执行前的 v1.5 checkpoint。当前权威方案为 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第 19 节，版本 `S18-P1-PLAN-v1.6`，SHA-256 `c14dc85959176d8e018713fbecaf064ca28c204f16e24e6280635406508217c8`。本轮 Teams 记录为 [`team-sessions/team-session-2026-09-07-5.md`](./team-sessions/team-session-2026-09-07-5.md)，SHA-256 `dd139646c3fbbec6c89ee7e3305e496066fc54a637372beb731bc933249b3293`。

B3e-S 的 7 个 stable host scenario、13 个 planned macOS/Linux scenario、exact artifact allowlist 和 required XFAIL run-true 语义已落地；首批 7 个 P1 record 已由独立完整字段 authority 与隔离 collection sidecar 约束。当前全部 P1 record 仍为 `unverified/unqualified`，不得把 196-pass security contract 或 41-pass inventory contract 当作平台 evidence closure。

唯一下一步为方案第 19.6 节的 B3c RECORD field semantics/no-replace correction，然后执行 B3f-L、B3f-R 与最终 schema replay。不得从 B3e-S 重做，也不得跳到 Linux、package、canonical、host 或 sealed qualification。S18、W1b-5b、Release 继续 No-go，5c/5d/5e 未授权；全部禁止事项和历史保留要求不变。

### 15.24 S18 P1 v1.7 B3f L 当前恢复入口

第 15.23 节保留 B3c 收口前的 v1.6 checkpoint。当前权威方案为 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第 20 节，版本 `S18-P1-PLAN-v1.7`，SHA-256 `a1cf11e7e9700a6689959a88d0a6abee5395c582b48a1e881db96013dbd34afc`。Teams 记录为 [`team-sessions/team-session-2026-09-07-6.md`](./team-sessions/team-session-2026-09-07-6.md)，SHA-256 `ceac0ee80f76681cdbc59fe2e42f119154853fe9344dbd89dc68bb5371c52720`。

B3c schema v1 的 RECORD entry 语义、identity hard-link no-replace、mode `0600` 和 whole-RECORD 错误 mutation 已完成 host contract；最终 security contract 为 `207 passed`。identity writer 的 write-zero、异常清理和精确 fsync 顺序仍是已复现缺口，不得扩大为完整 writer fault closure。

唯一下一步为方案第 20.4 至 20.7 节的 B3f-L characterization RED、producer limits、writer 状态机与 capture/retention real-runner matrix；随后才执行 B3f-R 和 final-schema replay。S18、W1b-5b、Release 继续 No-go，5c/5d/5e 未授权；禁止操作和历史保留要求不变。

### 15.25 S18 P1 v1.8 B3f L real runner 恢复入口

第 15.24 节保留 B3f-L 执行前的 v1.7 checkpoint。当前权威方案为 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第 21 节，版本 `S18-P1-PLAN-v1.8`，SHA-256 `e33a9a312dcf49096f1af89276074f71beb8f243b1a3a0eabbf7e2a45868ebe4`。Teams 验收记录为 [`team-sessions/team-session-2026-09-07-7.md`](./team-sessions/team-session-2026-09-07-7.md)，SHA-256 `a386eb6a4f38e60b536362ff2a1ab7e40b25500b6040da5d132c23e2e66e1e3d`。

B3f-L 五文件 unit/mutation tranche已实现，主任务独立回归为 `44 passed`定向和`257 passed`完整合同；整个B3f-L仍为PARTIAL/No-go。唯一下一步是方案第20.7与21.5节的独立scenario authority和capture/retention双lane real-runner matrix；不得重做已绿unit RED，也不得提前进入B3f-R。S18、W1b-5b、Release继续No-go，5c/5d/5e未授权。

### 15.26 S18 P1 v1.9 B3f L 57 条续接入口

第15.25节保留real-runner authority建立前的v1.8 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第22节，版本`S18-P1-PLAN-v1.9`，SHA-256 `9e688a4edc94b308257f4ef72072e7ca9f06cd0a421db99e213cfbfd21cb8bf9`；Teams决策记录[`team-sessions/team-session-2026-09-07-8.md`](./team-sessions/team-session-2026-09-07-8.md) SHA-256 `a05f078026ce77feba9e4eddbc6085db3b59088c722099c7c1f184e656086afd`。

B3f-L authority现有67条exact 15-field records，10条代表性capture/retention real-runner records已implemented，57条保持planned。下一位只从方案第22.7节Batch A开始，按八批完成剩余57条并在最终同hash下fresh replay全部67条；不得把10/67 checkpoint写成B3f-L闭合，也不得提前进入B3f-R。S18、W1b-5b、Release继续No-go，5c/5d/5e和全部既有禁止事项不变。

### 15.27 S18 P1 v1.10 B3f L Batch B 恢复入口

第15.26节保留Batch A执行前的v1.9 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第23节，版本`S18-P1-PLAN-v1.10`，SHA-256 `c46808ba2fd421a20225ab145cf9715bd974576d4e3b8a5b23b166f484c485bd`；Teams记录[`team-sessions/team-session-2026-09-07-9.md`](./team-sessions/team-session-2026-09-07-9.md) SHA-256 `84dfea124230a7027a200fd00a3919d6e2b47c36e9da153767989f4c04ac47b5`。

Batch A的18条configure argv real-runner records已GREEN，authority当前28 implemented/39 planned/67 total。唯一下一步是第23.5节Batch B的6条nodeid boundary、ASCII +1和multibyte +1；按真实characterization后再晋级，目标checkpoint为34/33/67。B3f-L、S18、W1b-5b和Release继续No-go，禁止事项不变。

### 15.28 S18 P1 v1.11 B3f L Batch C 恢复入口

第15.27节保留Batch B前的v1.10 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第24节，版本`S18-P1-PLAN-v1.11`，SHA-256 `8cc36822ec315d2e905d057e64121ee94c31bb21245e34578efa53f65ff37d2a`；Teams记录[`team-sessions/team-session-2026-09-07-10.md`](./team-sessions/team-session-2026-09-07-10.md) SHA-256 `b72d2f78957377b5d99d447692c6ce9f2a04b2adc7738b3e4afbde27015fd5d0`。

Batch B六条nodeid边界/+1已GREEN，authority为34 implemented/33 planned/67。唯一下一步是第24.5节Batch C四条serialized 8 MiB/+1真实runner；不得降低limit或以synthetic serializer代签。B3f-L、S18、W1b-5b、Release继续No-go，禁止事项不变。

### 15.29 S18 P1 v1.12 B3f L Batch D 恢复入口

第15.28节保留Batch C前的v1.11 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第25节，版本`S18-P1-PLAN-v1.12`，SHA-256 `3bd00bca522b46880f75ad06e940865bab8b61241cd97a96d716e42dd0da8200`；Teams记录[`team-sessions/team-session-2026-09-07-11.md`](./team-sessions/team-session-2026-09-07-11.md) SHA-256 `60ffbcbeec2a1dc21610e58982874c1c44b3cecfb21075d3070c02a6aa9bfca1`。

Batch C四条serialized hard-check records已GREEN，authority为38 implemented/29 planned/67；normal producer自然可达8 MiB的旧解释已被纠正为target-only exact collection ceiling fault injection。唯一下一步是第25.6节Batch D十四条pre-publication I/O。B3f-L、S18、W1b-5b、Release继续No-go。

### 15.30 S18 P1 v1.13 B3f L Batch E 恢复入口

第15.29节保留Batch D前的v1.12 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第26节，版本`S18-P1-PLAN-v1.13`，SHA-256 `7c6beb0c6c5c2fe6e3071d7e4a053dbaf94a4f37e0fff64ee629d9479a17eeef`；Teams记录[`team-sessions/team-session-2026-09-07-12.md`](./team-sessions/team-session-2026-09-07-12.md) SHA-256 `9bd312ae5da31ef2db556cca6063d76cdeae68fa1f33fd57ee0d0dd1486b8dff`。

Batch D十四条pre-publication I/O records已在marker语义修复后通过独立QA，authority为52 implemented/15 planned/67。唯一下一步是第26.6节Batch E六条existing-final、preexisting-temp与publish-race；目标仅为58/9/67。B3f-L、S18、W1b-5b、Release继续No-go，禁止事项不变。

### 15.31 S18 P1 v1.14 B3f L Batch F 恢复入口

第15.30节保留Batch E前的v1.13 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第27节，版本`S18-P1-PLAN-v1.14`，SHA-256 `c273c92020eb3f9bc47d6537d1fce10513221af5119f9d69f4e10e23a098eae5`；Teams记录[`team-sessions/team-session-2026-09-07-13.md`](./team-sessions/team-session-2026-09-07-13.md) SHA-256 `781823e419f0f4bd4841c8adc40286baea9928a02629a12f5358ce657a5b80b5`。

Batch E六条protected-object/publish-race records已通过独立QA，authority为58 implemented/9 planned/67；“runner前预置”已勘误为copied plugin import阶段、producer检查或syscall前预置。唯一下一步是第27.5节Batch F六条post-publication records，目标仅为64/3/67。B3f-L、S18、W1b-5b、Release继续No-go。

### 15.32 S18 P1 v1.15 B3f L Batch G 恢复入口

第15.31节保留Batch F前的v1.14 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第28节，版本`S18-P1-PLAN-v1.15`，SHA-256 `47e48deb8260e7171e23cfd8bd8adc7e4e6bf578a2196595588ad739aba1ecfb`；Teams记录[`team-sessions/team-session-2026-09-07-14.md`](./team-sessions/team-session-2026-09-07-14.md) SHA-256 `065d19d9455c1429a82cb8509ede5f94e906050a51bc9d1dd0b2847b62771da1`。

Batch F六条post-publication records已通过独立QA，authority为64 implemented/3 planned/67。唯一下一步是第28.5节Batch G两条exact syscall-order，目标仅为66/1/67；不得跳过Batch H或提前最终67条同hash replay。B3f-L、S18、W1b-5b、Release继续No-go。

### 15.33 S18 P1 v1.16 B3f L Batch H 恢复入口

第15.32节保留Batch G前的v1.15 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第29节，版本`S18-P1-PLAN-v1.16`，SHA-256 `30b9df622cf930cb36e7a250193dd7386a379db9f4197d8d2e667f51b12ea248`；Teams记录[`team-sessions/team-session-2026-09-07-15.md`](./team-sessions/team-session-2026-09-07-15.md) SHA-256 `f70cd4737f8705996936cafe2345b7d52bf4919a2a7fa301e5e4f414cd298178`。

Batch G两条record-only syscall-order records已通过独立QA，authority为66 implemented/1 planned/67，唯一planned为existing-attempt:runner。下一步只执行第29.5节Batch H一条global runner-input合同；随后必须最终同hash fresh replay全部67条。B3f-L、S18、W1b-5b、Release继续No-go。

### 15.34 S18 P1 v1.17 B3f L 最终67条恢复入口

第15.33节保留Batch H前的v1.16 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第30节，版本`S18-P1-PLAN-v1.17`，SHA-256 `a12aff9eaa2e3bb86f21efb7833d079bb4b82bb51dcb7ec2bf83e98ac6298398`；Teams记录[`team-sessions/team-session-2026-09-07-16.md`](./team-sessions/team-session-2026-09-07-16.md) SHA-256 `b9943d2f5e5688765a092d52b9f95394631ef5f342cf5325f05530333698a76c`。

Batch H唯一global runner-input record已通过架构审查和独立QA，authority为67 implemented/0 planned/67。该计数不等于B3f-L闭合；下一步只执行第30.5节最终同hash fresh replay全部67条，并独立审计全部roots。不得进入B3f-R或平台资格化，S18、W1b-5b、Release继续No-go。

### 15.35 S18 P1 v1.18 B3f R0 恢复入口

第15.34节保留final 67前的v1.17 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第31节，版本`S18-P1-PLAN-v1.18`，SHA-256 `a6250365667cee35caf2784c68a96932e3336b57328e607fcc6790e47e84f488`；Teams记录[`team-sessions/team-session-2026-09-07-17.md`](./team-sessions/team-session-2026-09-07-17.md) SHA-256 `51041766bb0723257b62adf00803fd4926faeabf47ca65c14169df5e7b349021`。

B3f-L已在同一最终hash下完成67/67单次fresh replay并通过132-lane独立verifier审计。下一步只执行第31.6节B3f-R0低成本合同RED与PEP 376语法冻结；不得提前修改runtime producer/verifier或运行平台资格化。S18、W1b-5b、Release继续No-go。

### 15.36 S18 P1 v1.20 B3f R1b恢复入口

第15.35节保留R0执行前的v1.18 checkpoint。当前权威方案为[`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第33节，版本`S18-P1-PLAN-v1.20`，SHA-256 `5b14134df98e68b5ed092262d5b43cf521b8156cee791dfb5c14719da52267f2`；Teams记录[`team-sessions/team-session-2026-09-07-19.md`](./team-sessions/team-session-2026-09-07-19.md) SHA-256 `271caf7e77870a024bf7d4b6a4d35aec5142bf872d3cf422d3c9ceba494e109a`。

B3f-R0五项合同RED和R1a三个bootstrap primitives已完成；初版R1a的裸异常、home未绑定和rollback过强声明已保留为P1历史，并通过补充RED/GREEN及独立QA关闭。当前只允许进入第33.7节R1b exact15 identity producer合同；不得跳到R2 schema迁移、真实security runner、final-schema replay或平台资格化。S18、W1b-5b、Release继续No-go，W1b-5c/5d/5e不执行。

### 15.37 S18 P1 v1.21 R1b QA P1 恢复入口

前一入口保留为历史 checkpoint。当前权威方案为 [S18 P1 执行方案](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第34节（尤其34.6至34.10），版本 `S18-P1-PLAN-v1.21`，整份 SHA-256 `cc3705d97e7b9d6c75b0e91059f0ba9d88d5f1fe91de836290553d0677f457e7`；[Teams 20](./team-sessions/team-session-2026-09-07-20.md) SHA-256 `f5a1822407d8523093ada70700520cc9c964379be6c3f6db92d4cf1c3055e63a`。

R1b 定向回归通过，但独立 QA 发现 lock pathname 同内容换 inode 未拒绝、文件身份字段接受根路径两个 P1，当前 **未验收**。下一次执行从第34.8节局部 test-first 修复与新 hash 独立 QA 开始，不能跳到 R2。本次仅持久化方案，不修改代码或消费资格；产品/P1计数不晋级。S18、W1b-5b、Release 继续 No-go，不执行 W1b-5c/5d/5e。后续完整 DAG、测试用例、原始证据失效处理均以权威方案为准。

### 15.38 S18 P1 v1.22 R1b 验收与 R2 恢复入口

前一入口保留旧 QA P1 checkpoint。当前权威方案为 [S18 P1 执行方案](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第35节，版本 `S18-P1-PLAN-v1.22`，整份 SHA-256 `6b6c29dedb130396f1ab5ec6c7e4bda9637fecf65ce3892e373d8bac1ab48fc8`；[Teams 21](./team-sessions/team-session-2026-09-07-21.md) SHA-256 `069f7663cded80d73a3f37b52807fd121a610c9dc3b99e8a16a2ab9ced2dc67a`。

两个 R1b P1 已在新 hash 下经 RED/GREEN、架构与独立 QA 关闭；exact15、R1a10 unique、legacy10 均通过，policy-v3 仍是唯一预期 RED。R1b producer foundation 完成，不代表真实 runner、identity-v2 publication、Linux/双平台或 Release qualification。下一步先解决第35.11节草案冲突，冻结 R2 exact 契约后执行第35.5节原子 cutover；第35.9至35.10节字段/十二节点仍为 proposed/planned，不计为实现。S18、W1b-5b、Release 继续 No-go，inventory不晋级，W1b-5c/5d/5e不执行。

### 15.39 S18 P1 v1.23 R2 进行中恢复入口

当前工作入口转至 [S18 P1 执行方案](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第36节和 [Teams 22](./team-sessions/team-session-2026-09-07-22.md)。第35节R1b最终hash仅为历史已验收基线；R2正在原子迁移，代码与文档尚未最终封板，因此本入口不提供冒充完成的固定hash。

先核对第36节最后checkpoint与真实worktree/进程状态后续接。不得复用旧R1b绿色、初始15-node scaffold RED或部分schema更改代签R2。真实双lane、final67和平台qualification仍待后续，inventory不晋级；S18、W1b-5b、Release继续No-go，5c/5d/5e不执行。

### 15.40 R2 方案本地保存与待独立 QA 入口

最新恢复点为 [S18 P1 执行方案](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第36.33–36.34节；实现已停写停测并交锁，九文件候选快照已核对。精确测试选择、证据索引与hash已保存到docs，原始测试产物仍在临时目录；本次不是完整证据归档。

R2尚未独立验收；下一步为同快照独立QA，不是R3。四项入口继续WIP，S18、W1b-5b、Release继续No-go；详情与验收门仅以权威方案最新checkpoint为准，不从旧绿色或聊天摘要推断完成。

### 15.41 R2 递归修复后的当前状态

最新恢复点为 [S18 P1执行方案](./S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第36.40节，新九文件清单位于第36.39节。深层JSON候选解析的P1已最小修复，主代理fresh47+35回归通过（去重79节点）；最终独立QA任务被执行环境中止，没有验收结论。独立验收门仍保留，不能据主代理复验启动R3；S18、W1b-5b、Release继续No-go。R3仅完成失败profile与隔离前置设计，不是执行或平台资格证据。
