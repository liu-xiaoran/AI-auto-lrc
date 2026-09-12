# AI-auto-lrc v1 到 v2 迁移指南

[English (primary)](V1_TO_V2_MIGRATION.md) · [简体中文](V1_TO_V2_MIGRATION.zh-CN.md) · [文档导航](README.zh-CN.md)

本文面向已经调用 v1 CLI 或 Python `process()` 的集成方。v2 是显式破坏性版本：它通过 `legacy-v1` profile 保留 LegacyV1 模型数值协议，但不发布旧模块、旧参数签名、五元模型 tuple、默认 Demucs、隐式 decoder fallback 或“stdout 增强 LRC 加自动写标准 LRC”的双输出行为。

迁移完成的判定不是“旧命令还能跑”，而是调用方已经改用 v2 的结构化请求与结果、显式资产根和输出策略，并正确区分 complete、用户接受的 partial 和 strict failure。

## 1. CLI 参数迁移矩阵

<!-- v1-cli-migration-start -->
| v1 参数 | v1 默认 | v2 替代 | v2 默认 | 结论 |
|---|---|---|---|---|
| `lrc_file` | 必填 | `lyrics_file` 位置参数 | 必填 | 重命名；仍由 CLI 负责文件解码 |
| `music_file` | 必填 | `audio_file` 位置参数 | 必填 | 重命名；不再决定隐式输出文件名 |
| `-f/--format` | `lrc` | 无 | LRC | 删除；v2 本轮只发布 LRC，不保留单值开关 |
| `-l/--line_only` | `0` | `--timestamps` 的 `line` 或 `word` | `line` | 替换；v1 的 `0` 对应 `word`，v1 的 `1` 对应 `line`；默认从 word 改为 line |
| `-v/--vocalize` | `1` | `--separate-vocals` | 关闭 | 替换为布尔 flag；默认从开启改为关闭 |
| `-m/--model` | `mdx_extra` | `--demucs-model` | `mdx_extra` | 重命名；只有同时传 `--separate-vocals` 才合法；不要与 `--acoustic-model` 混淆 |
| `-i/--idx` | `-1` | `--demucs-index` | `-1` | 重命名；只有同时传 `--separate-vocals` 才合法 |
| `-o/--out_dir` | `demofile` | `-o/--output` | 无 | 目录变成完整文件路径；省略时只写 stdout，不自动创建标准 LRC 副本 |
<!-- v1-cli-migration-end -->

v2 新增 `--acoustic-model`、`--allow-partial`、`--device`、`--asset-root`、`--decoder`、`--verbose` 和 `--debug`。它们都表达独立策略，不能从当前环境或可用依赖隐式推断。默认 acoustic model 为 `MTL`，decoder 为 `torchaudio`，device 为 `auto`，timestamps 为 `line`，partial 关闭，人声分离关闭。

### 1.1 CLI 输出变化

v1 默认同时把增强 LRC 和进度写到 stdout，并在 `out_dir` 中覆盖写标准 LRC。v2 严格使用一个输出目标：

- 不传 `-o`：stdout 只包含 UTF-8 LRC 和恰好一个尾换行；日志、进度和错误只进入 stderr；
- 传 `-o FILE`：stdout 为空，LRC 以原子替换写入完整目标路径；
- 输出不得与歌词或音频输入指向同一对象，也不得是目录、FIFO、device 或 symlink，且拒绝符号链接祖先；
- `--timestamps line` 直接生成标准行级 LRC，`--timestamps word` 直接生成逐字时间戳 LRC，不再运行独立的增强转标准步骤。

迁移前：

```bash
python main.py lyrics.txt song.mp3 --line_only 1 --vocalize 0 --out_dir output
```

迁移后：

```bash
uv run ai-auto-lrc lyrics.txt song.mp3 \
  --asset-root /absolute/path/to/assets \
  --timestamps line \
  --decoder torchaudio \
  --acoustic-model MTL \
  -o output/song.lrc
```

## 2. Python API 参数迁移矩阵

| v1 `process()` 参数 | v2 替代 | 迁移说明 |
|---|---|---|
| `txt_lines` | `AlignmentRequest.lyrics` | 必须是已解码字符串组成的 tuple |
| `audio_file` | `AlignmentRequest.audio_path` | 必须是 `pathlib.Path` |
| `mtl_model` | `AlignmentRequest.acoustic_model` | 只接受四个公开路由名称；不再接受五元预加载 tuple |
| `demucs_model` | `VocalSeparationOptions.demucs_model` | 仅在人声分离显式启用时构造 options |
| `demucs_idx` | `VocalSeparationOptions.demucs_index` | 只接受 `-1..3`，构造时立即校验 |
| `line_only` | `AlignmentRequest.timestamp_mode` | `True -> "line"`，`False -> "word"`；v2 默认 `line` |
| `out_file` | 调用方文件逻辑或 v2 CLI `-o` | Python API 不写 LRC；成功后消费 `AlignmentResult.lrc` |
| `verbose` | CLI `--verbose` 或自定义 observer 边界 | 顶层 Python API 不主动打印进度；依赖可能产生警告 |
| `vocalize` | `AlignmentRequest.vocal_separation` | `None` 表示关闭；不再默认开启 Demucs |
| `format` | 无 | 删除；v2 本轮只返回 LRC 结构化结果 |

v1 返回裸 LRC 字符串。v2 返回 `AlignmentResult`，调用方必须至少检查 `status`、`lrc`、`spans`、`expected_token_count`、`model_profile`、`timebase` 和 `diagnostics`。运行时配置独立放入 `RuntimeConfig`；其中 `asset_root` 必须是绝对受控根，`offline` 固定为 `True`，默认 `decoder="torchaudio"`、`device="auto"`、`seed=0`、`max_alignment_bytes=536870912`。

运行时准备仍会读取输入并创建私有资产副本。可选 Demucs 未完整执行 offline 约束，可能下载权重；边界见[技术指南](TECHNICAL_GUIDE.zh-CN.md)。

迁移后 Python 示例：

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
        lyrics=("First line", "Second line"),
        audio_path=Path("song.mp3"),
        timestamp_mode="line",
        acoustic_model="MTL",
    )
)
if result.status != "complete":
    raise RuntimeError("alignment was not complete")
print(result.lrc)
```

## 3. 旧入口的处理

以下旧模块和符号被有意删除，不提供兼容 shim：

| v1 入口 | v2 处理 |
|---|---|
| `main.py` | 使用安装后的 `ai-auto-lrc` console script |
| `t2l.t2l.process` | 使用顶层 `t2l.process(AlignmentRequest, runtime=...)` 或 `runtime.process(request)` |
| `t2l.init_model` | 使用 `create_runtime(RuntimeConfig(...))`；模型保持 runtime 私有惰性资源 |
| `t2l.mtl.wrapper` | 不再是公共 API；选择 `AlignmentRequest.acoustic_model` |
| `ext.lrc2json` | 不在 v2 core 范围内 |
| `ext.traditional_to_simplified` | 不在 v2 core 范围内 |

如果导入这些模块失败，应修正调用方；不要把源码目录加入 `PYTHONPATH`，也不要复制旧文件到 wheel 中绕过迁移。

## 4. 退出码和自动化脚本

调用方必须分开处理以下结果：

| 退出码 | 语义 | 可消费 LRC |
|---:|---|---|
| `0` | complete | 是 |
| `3` | 调用方显式传入 `--allow-partial` 且结果为连续非空前缀 | 是，但必须标记不完整 |
| `7` | alignment 失败或 strict 模式拒绝 partial | 否 |

当前冻结 LegacyV1 backend 尚无已批准的 natural non-empty partial 生成语义；`3` 是公共合同保留值，不代表真实 backend 已能稳定产生。自动化脚本必须保持 strict 为默认，只有业务明确接受不完整输出时才同时接受 `0` 和 `3`。

```bash
set +e
ai-auto-lrc lyrics.txt song.mp3 --asset-root /absolute/path/to/assets -o output.lrc
status=$?
set -e

case "$status" in
  0) echo "complete" ;;
  3) echo "partial output requires explicit downstream handling" >&2 ;;
  7) echo "strict alignment failure; no output may be consumed" >&2; exit 7 ;;
  *) exit "$status" ;;
esac
```

## 5. 迁移验收清单

1. 旧模块不再被 import，五元模型 tuple 不再跨进程或跨版本持久化。
2. 每次调用都显式提供受控绝对 asset root；核心路径不依赖 CWD、用户 cache 或在线下载。
3. timestamps、decoder、acoustic model、partial 和 vocal separation 都由调用方明确选择或接受文档化默认值。
4. Python 调用检查结构化状态；CLI 调用只消费一个输出目标，并区分退出码 `0`、`3`、`7`。
5. 在源码树外 CWD 和空 `PYTHONPATH` 中运行 installed console script。
6. 发布前还需通过主计划中的双平台 cold wheelhouse、完整资源预算、恢复、签名和 rollback gate；迁移 smoke 通过不等于 Release Go。
