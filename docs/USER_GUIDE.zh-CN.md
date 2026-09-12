# 使用指南

## 1. 获取当前开发版本

先准备 Git、Git LFS、uv 和 Python 3.11。首次下载依赖及模型可能需要网络；在受限网络环境中应事先准备依赖缓存与完整资产。

```bash
git clone --branch main https://github.com/liu-xiaoran/AI-auto-lrc.git
cd AI-auto-lrc
git lfs install
git lfs pull
uv sync --frozen --python 3.11 --group test
uv run --frozen --no-sync ai-auto-lrc --help
```

已有 checkout 先保存本地改动，再切换或拉取所需分支；不要为照抄命令清除未提交内容。当前 v2 已合入主分支 `main`，本指南以该分支为安装入口。安装依据只使用 `pyproject.toml` 和 `uv.lock`，不要恢复旧 `requirements.txt` 或 `Pipfile`。

资产根必须包含以下六个文件，下载后不能仍是 Git LFS pointer：

```text
checkpoints/checkpoint_Baseline
checkpoints/checkpoint_MTL
checkpoints/checkpoint_BDR
lid.176.ftz
assets/nltk_data/corpora/cmudict.zip
assets/nltk_data/taggers/averaged_perceptron_tagger.zip
```

前三个 checkpoint 和 fastText 文件由 LFS 管理，NLTK zip 随源码提供。运行时检查包内 manifest 的大小和 SHA-256；不要使用同名的未知模型替换，也不要修改 manifest 规避错误。安装 wheel 时只有 manifest 入包，以上运行资产须另行准备并显式指向它们的根目录。

## 2. 首次运行仓库示例

在仓库根执行，下面通过 `pwd -P` 避免符号链接目录。输出选择仓库下的普通目录；若该文件已存在会被替换。

```bash
PROJECT_ROOT="$(pwd -P)"
uv run --offline --frozen --no-sync ai-auto-lrc   "$PROJECT_ROOT/demofile/original_txt.txt"   "$PROJECT_ROOT/demofile/original_track.mp3"   --asset-root "$PROJECT_ROOT" --device cpu   -o "$PROJECT_ROOT/output/demo.lrc"
```

终端进度不代表完成，应检查命令退出码为 0，并打开生成文件。已有示例实测为 58 行，输出时间戳单调；行数与格式正确不能替代试听确认对齐准确性。

## 3. 处理自己的歌曲

准备与音频完全对应的歌词文件，推荐 UTF-8、一行一句，不含歌名/制作人员等不演唱内容。不同现场版、删节版、前奏或歌词版本会影响结果。CLI 会移除已有时间标签，但不是通用的复杂 LRC 解析器。

将占位路径替换为实际文件，路径含空格时保留引号：

```bash
uv run --offline --frozen --no-sync ai-auto-lrc   "/absolute/path/lyrics.txt" "/absolute/path/song.wav"   --asset-root "/absolute/path/AI-auto-lrc" --device cpu   -o "/absolute/path/output/song.lrc"
```

从仓库外运行时，直接使用已安装环境的可执行文件，例如 `/absolute/path/AI-auto-lrc/.venv/bin/ai-auto-lrc`，并显式传入资产根；不要依赖任意当前目录寻找模型。输出路径各级目录不可为符号链接，macOS 的 `/var` 常指向 `/private/var`，应使用真实路径。

常用选择：

| 需求 | 参数/方式 |
|---|---|
| 播放器常用行级 LRC | 默认，或 `--timestamps line` |
| token 时间戳 | `--timestamps word`，播放器兼容性需自行验证 |
| 模型路径 | `--acoustic-model Baseline`、`MTL`、`Baseline_BDR`、`MTL_BDR` |
| 稳定复现本地 CPU 路径 | `--device cpu` |
| 输出到 stdout | 省略 `-o`；shell `>` 重定向不具备程序原子输出保护 |
| 增加诊断 | `--verbose`；定位内部错误可用 `--debug`，分享日志前检查路径和内容 |
| 显式接受不完整结果 | `--allow-partial`，非空连续前缀结果返回 3；禁止当作通用失败重试方案 |

不要自动更换 decoder、允许 partial 或添加人声分离来隐藏失败。批量处理应逐首记录退出码，给不同输入使用不同输出文件；先串行复用 runtime 验证容量，不假设多个线程线性提速。

## 4. Python 集成

以下脚本在已安装该项目的环境中执行。替换路径，API 的 `lyrics` 是已经解码的字符串 tuple，不是歌词文件名。

```python
from pathlib import Path
from t2l import AlignmentRequest, RuntimeConfig, create_runtime

asset_root = Path("/absolute/path/AI-auto-lrc").resolve()
lyrics_path = Path("/absolute/path/lyrics.txt")
audio_path = Path("/absolute/path/song.wav")
lines = tuple(lyrics_path.read_text(encoding="utf-8-sig").splitlines())
runtime = create_runtime(RuntimeConfig(asset_root=asset_root, device="cpu"))
result = runtime.process(AlignmentRequest(lyrics=lines, audio_path=audio_path))
print(result.status)
print(result.lrc)
# 调用方负责保存。普通 Path.write_text 不具备 CLI 原子 sink 的全部保护。
```

runtime 可以供多首歌曲复用。结构化结果和错误类型见[技术指南](TECHNICAL_GUIDE.zh-CN.md)。

## 5. 退出码与排查

以下“输出”指本次生成的结果；失败时路径上可能仍有以前的文件，不能以文件存在判断本次成功。

| 退出码 | 含义 | 处理 |
|---:|---|---|
| 0 | 完整成功 | 检查文本、行数、时间单调并试听 |
| 1 | 未分类内部错误 | 保留命令与 stderr，使用 debug 定位 |
| 2 | 命令或配置无效 | 查看 help、路径及参数组合 |
| 3 | 显式允许的 partial | 标记部分结果，不能冒充完整成功 |
| 4 | 歌词输入错误 | 检查编码、空文本及歌词内容 |
| 5 | 解码/分离错误 | 确认文件可读、格式支持、未意外启用分离 |
| 6 | 资产/模型/设备错误 | 检查 LFS、六项资产、manifest、Python/设备环境 |
| 7 | 对齐失败或严格模式拒绝 partial | 检查歌曲与歌词版本，保留失败事实 |
| 8 | 输出写入失败 | 检查真实路径、权限、符号链接、输入别名及目标类型 |

可选 Demucs 依赖可通过 `uv sync --frozen --extra vocals --group test` 安装，使用时必须显式传 `--separate-vocals`。它可能下载权重，尚未完成离线与质量验收；`RuntimeConfig.offline=True` 不能保证该可选路径不联网。本指南的默认运行不需要它。

## 6. 更新与验证

更新源码后重新运行 `uv sync --frozen --python 3.11 --group test` 和示例。不要仅依据 `--help`、导入成功或单元测试绿色判断模型已经可用。当前完成范围和暂缓事项见[项目状态](PROJECT_STATUS.zh-CN.md)，开发检查命令见[技术指南](TECHNICAL_GUIDE.zh-CN.md)。
