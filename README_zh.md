# AI-auto-lrc v2

## 交给 AI 的使用提示词（复制后替换路径）

下面的提示词包含明确的项目地址，可单独粘贴到新对话。
请替换输入占位符，也可以让 AI 继续询问缺少的文件。
实际执行仍需要 AI 能访问仓库并运行终端；仅提供本地路径，不会让普通聊天 AI 自动获得电脑文件访问权限。

```text
请帮我使用 AI-auto-lrc v2 生成 LRC。
仓库地址：https://github.com/liu-xiaoran/AI-auto-lrc
克隆地址：https://github.com/liu-xiaoran/AI-auto-lrc.git
使用分支：main
主文档语言：英文，每页提供对应中文版本。
文档导航：https://github.com/liu-xiaoran/AI-auto-lrc/blob/main/docs/README.zh-CN.md
使用指南：https://github.com/liu-xiaoran/AI-auto-lrc/blob/main/docs/USER_GUIDE.zh-CN.md
项目状态：https://github.com/liu-xiaoran/AI-auto-lrc/blob/main/docs/PROJECT_STATUS.zh-CN.md

本地项目目录（可选）：<项目绝对路径，或尚未克隆>
歌词文件：<UTF-8 歌词绝对路径>
音频文件：<对应歌曲音频绝对路径>
输出文件（可选）：<新的 LRC 绝对路径，或请建议一个新文件名>

请用上面的准确地址识别项目，不要只凭项目名猜测。
如果已有本地仓库，核对 remote 和分支并保留本地改动。
如果尚未克隆且你能访问终端和网络，将 main 克隆到新目录，
按使用指南准备 Git LFS、依赖和运行资产。
先阅读上面的文档，或已核对的本地仓库中对应文件；
集成或改代码时，再读该仓库的 docs/TECHNICAL_GUIDE.zh-CN.md 和 CLAUDE.zh-CN.md。
如果无法访问仓库、输入文件或终端，请说明缺少的能力，
询问所需材料或给出由我执行的命令，不要声称已经运行。
未填写的占位符表示信息缺失，不是可直接使用的路径。
核对当前分支、Python 3.10/3.11、pyproject.toml/uv.lock 及六项运行资产。
使用 v2 的 ai-auto-lrc CLI；从项目外运行时使用该环境可执行文件。
默认 CPU、MTL、行级、严格完整、不分离人声，使用规范真实输出路径。
依赖与资产齐备后离线执行；缺少必要路径先向我确认，不猜测歌曲或歌词。
不要自动启用 partial、更换 decoder、下载可选模型或编造时间戳。
已有输出需要按我的覆盖意图处理，否则选新文件。检查实际退出码、LRC 内容、
行数和时间单调性，报告命令、输出位置与错误；成功运行不等于准确率合格。
本轮不要求异常全覆盖，不把未验证的平台、安全或发布门禁描述为通过。
```

[文档导航](docs/README.zh-CN.md) · [如何使用](docs/USER_GUIDE.zh-CN.md) · [系统说明](docs/SYSTEM_OVERVIEW.zh-CN.md) · [技术文档](docs/TECHNICAL_GUIDE.zh-CN.md) · [当前进展](docs/PROJECT_STATUS.zh-CN.md)

> 2026-09-12：按用户决定暂缓异常场景全覆盖，当前 v2 已合入 `main`，安装以主分支为入口；版本仍为 Alpha，发布门禁保持未通过。当前说明以英文为主，每篇提供对应中文版。


离线优先的歌词—音频对齐工具，输出标准行级 LRC，也可显式选择逐词时间戳。

[English (primary)](README.md) · [简体中文](README_zh.md) · [v2 执行与测试计划](docs/AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md) · [LegacyV1 交接事实](docs/AI_REFACTOR_HANDOFF.zh-CN.md)

> 当前状态：`2.0.0a0` 开发版本。v2 API 和核心适配器已经实现，但发布资格仍在验证中。当前 checkout 不是生产发行版，也不能作为对齐质量证明。

## v2 锁定行为

- Python `>=3.10,<3.12`。
- 默认输出标准行级 LRC。
- 默认声学路径为 `MTL`，使用冻结的 `legacy-v1` profile。
- 人声分离默认关闭；Demucs 是可选 extra，默认路径不得加载。
- 核心路径默认离线；运行资产必须预先存在并通过包内 manifest 校验。
- 默认严格拒绝不完整对齐；显式 `--allow-partial` 只允许连续前缀结果，并返回退出码 `3`。
- 默认 decoder 是 `torchaudio`；`librosa-mono` 必须显式选择，不自动回退。
- 不带 `-o` 时 stdout 只含 UTF-8 LRC；带 `-o` 时 stdout 为空，文件采用原子替换。
- Python API 返回结构化结果，不写 LRC、不主动打印进度；运行时仍读取输入并准备私有资产副本，依赖可能产生警告。

## 开发环境安装

模型 checkpoint 和 fastText 语言识别模型不进入 wheel，必须作为本地资产提供。开发 checkout 通常通过 Git LFS 获取：

```bash
git lfs install
git lfs pull
uv sync --frozen --python 3.11 --group test
```

需要可选人声分离能力时：

```bash
uv sync --frozen --extra vocals --group test
```

`pyproject.toml + uv.lock` 是 v2 唯一依赖事实源。旧 `requirements.txt`、`Pipfile` 和 `Pipfile.lock` 已退役，不再是 v2 安装入口。

## 运行资产

资产根按以下优先级解析：

1. `RuntimeConfig.asset_root` 或 CLI `--asset-root`；
2. `T2L_ASSET_ROOT`；
3. 仅在识别为开发 checkout 时使用仓库根。

当前 LegacyV1 资产根包含：

```text
checkpoints/checkpoint_Baseline
checkpoints/checkpoint_MTL
checkpoints/checkpoint_BDR
lid.176.ftz
assets/nltk_data/corpora/cmudict.zip
assets/nltk_data/taggers/averaged_perceptron_tagger.zip
```

API 显式 asset root 必须是绝对 Path；CLI 会规范化传入路径，推荐始终提供绝对路径。资产在反序列化前检查路径逃逸、Git LFS pointer、文件大小和 SHA-256；程序绝不在任意当前工作目录搜索同名 checkpoint。

## 命令行

```bash
uv run ai-auto-lrc 歌词文件 音频文件 \
  --asset-root /绝对路径/资产根
```

默认命令把带一个尾换行的 LRC 写到 stdout，不创建输出文件。写入文件时使用：

```bash
uv run ai-auto-lrc lyrics.txt song.wav \
  --asset-root /绝对路径/资产根 \
  -o output/song.lrc
```

主要选项：

```text
--timestamps line|word
--acoustic-model Baseline|MTL|Baseline_BDR|MTL_BDR
--allow-partial
--device auto|cpu|cuda
--asset-root 绝对路径
--decoder torchaudio|librosa-mono
--separate-vocals
--demucs-model mdx|mdx_extra|mdx_q|mdx_extra_q
--demucs-index -1|0|1|2|3
--verbose
--debug
```

`--demucs-model` 和 `--demucs-index` 必须与 `--separate-vocals` 一起使用。默认路径不会导入或下载 Demucs。可选分离路径可能下载权重，当前 offline 配置未在该分离器中完整执行，离线能力尚未验收。

### 退出码

| 退出码 | 语义 | 是否可能已有 LRC |
|---:|---|---|
| 0 | 完整成功 | 是 |
| 1 | 未分类内部错误 | 否 |
| 2 | CLI/配置错误 | 否 |
| 3 | 用户显式允许的 partial | 是 |
| 4 | 歌词输入错误 | 否 |
| 5 | 音频解码或人声分离错误 | 否 |
| 6 | 资产、checkpoint、模型或设备错误 | 否 |
| 7 | 对齐错误或 strict 拒绝 partial | 否 |
| 8 | 输出文件写入错误 | 否 |

进度和诊断只进入 stderr。有意接受 partial 的脚本可以同时处理 `0` 和 `3`；只接受 `0` 则保持严格完整性。

## Python API

```python
from pathlib import Path

from t2l import AlignmentRequest, RuntimeConfig, create_runtime

runtime = create_runtime(
    RuntimeConfig(
        asset_root=Path("/absolute/path/to/assets"),
        decoder="torchaudio",
        offline=True,
    )
)

result = runtime.process(
    AlignmentRequest(
        lyrics=("第一行", "第二行"),
        audio_path=Path("song.wav"),
        timestamp_mode="line",
        acoustic_model="MTL",
    )
)

print(result.status)
print(result.lrc)
print(result.spans)
print(result.diagnostics)
```

重复调用时可以复用一个 runtime，以复用其惰性语言/模型资源；不同 runtime 的缓存相互隔离。当前 LegacyV1 adapter 会在同一 runtime 内串行执行模型加载和推理。

## 架构

```text
CLI / Python API
  -> AlignmentRequest
  -> AlignLyricsUseCase
       -> LyricsPreparationPort
       -> AudioPreparationPort
       -> InferencePort（LegacyV1 特征/模型/DTW/BDR）
       -> strict/partial 完整性策略
       -> LrcRendererPort
  -> AlignmentResult
  -> 仅 CLI：stdout XOR 原子文件 sink
```

`t2l.composition` 是默认 composition root。application/domain 不依赖 torch、torchaudio、librosa、Demucs、fastText 或文件输出。LegacyV1 冻结现有 checkpoint 架构、首声道策略、帧时钟（`768 / 22050` 秒/帧）、MTL reduction 顺序、BDR alpha 和历史 LSTM 轴语义。

## 测试

轻量单元测试（完整核心验证命令见技术指南）：

```bash
uv run --offline --frozen --no-sync python -m pytest tests/unit -q -p no:cacheprovider
```

包含本地 LegacyV1 checkpoint 的组件测试：

```bash
uv run python -m pytest tests/component -q -p no:cacheprovider
```

构建与静态检查：

```bash
uv sync --frozen --group dev
uv lock --check
uv run ruff check .
uv run python -m compileall t2l tests
uv build
```

当前已有 Linux CPython 3.10 functional canonical、真实 WAV/MP3、并发初始化和 Linux x86_64 冷缓存离线安装证据；它们仍不是发布证明。发布计划尚要求 natural non-empty partial 的产品语义、完整资源门禁、macOS 冷安装与双平台聚合、Demucs 离线能力、clean signed provenance、SBOM/attestation 以及恢复/回滚演练。本机或单平台绿色不能替代这些门禁。

macOS / Python 3.11 的 R3 真实安全运行环境正常对照有独立系统测试入口，耗时约数分钟，不包含在上述 portable/contract 层中：

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --offline --frozen --no-sync python -m pytest \
  tests/system/test_security_runtime_identity_r3.py -q -p no:cacheprovider
```

该入口串行执行原始 capture/retention 测试与验证器，拒绝 IP 网络和项目/运行环境写入，仅允许在临时证据目录内绑定 Unix socket。日志、产物和前后文件摘要保存在 pytest 临时目录；需要保留路径时可显式指定全新 `--basetemp`。这只验证当前 macOS 正常对照，不代替异常矩阵、其他平台或发布资格；原始对照记录见 [S18 历史执行方案](docs/S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第36.41–36.42节，当前范围见[项目状态](docs/PROJECT_STATUS.zh-CN.md)。

## 从 v1 迁移

v2 明确不发布旧 `t2l.t2l.process(...)` 散参数接口、五元模型 tuple、隐式 decoder fallback、默认 Demucs，也不自动执行增强 LRC → 标准 LRC 转换。调用方必须迁移到 `AlignmentRequest`/`AlignmentResult`，显式选择输出、decoder、partial 和人声分离策略。

逐参数迁移方式和退出码处理见 [v1 到 v2 迁移指南](docs/V1_TO_V2_MIGRATION.zh-CN.md)。冻结的 v1 行为边界见[交接文档](docs/AI_REFACTOR_HANDOFF.zh-CN.md)，完整验收门禁见[v2 计划](docs/AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md)。

## 许可证与来源

参见 [LICENSE](LICENSE) 和 [基线来源与恢复](docs/BASELINE_PROVENANCE.zh-CN.md)。部分语言处理依赖和模型资产有各自许可证。仅获准内部生成测试并不等于已验证可再分发；release artifact 必须通过计划中的许可证和 provenance 门禁。
