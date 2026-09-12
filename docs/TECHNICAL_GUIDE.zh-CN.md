# 技术指南

[English (primary)](TECHNICAL_GUIDE.md) · [简体中文](TECHNICAL_GUIDE.zh-CN.md) · [文档导航](README.zh-CN.md)

## 结构与职责

| 模块 | 职责 |
|---|---|
| `t2l/api.py` | 公共 API、runtime 包装与 process 入口 |
| `t2l/contracts.py`、`t2l/errors.py` | 不依赖推理框架的值对象、验证和领域错误 |
| `t2l/composition.py` | 默认依赖组装；资产、设备、语言和模型资源构造 |
| `t2l/application/align_lyrics.py`、`ports.py` | 用例顺序、端口协议、完整性策略 |
| `t2l/domain/lrc.py` | LRC 渲染与帧时间转换 |
| `t2l/adapters/lyrics_io.py`、`lyrics.py` | CLI 文本解码、歌词清理与准备 |
| `t2l/adapters/audio.py` | 解码器与音频准备 |
| `t2l/adapters/assets.py` | 资产定位、校验、私有副本 |
| `t2l/adapters/legacy_v1_inference.py` | 特征、checkpoint、推理、DTW/BDR |
| `t2l/adapters/cli.py`、`output.py` | CLI 参数/错误映射、stdout/原子文件输出 |
| `t2l/mtl/model.py`、`utils.py` | 冻结的 LegacyV1 模型与数值逻辑 |

依赖方向为 CLI/API → application/domain → 端口，composition 注入适配器。application/domain 不导入 torch、torchaudio、fastText、Demucs 或输出 sink。后验和 Mel 张量留在推理适配层。

## 公共 API 合约

从 `t2l` 导入 `AlignmentRequest`、`AlignmentResult`、`RuntimeConfig`、`create_runtime`、`process`。`process(request, *, runtime=None)` 可使用默认运行时；连续任务建议显式创建并复用 runtime。

| AlignmentRequest 字段 | 类型/默认 | 含义 |
|---|---|---|
| lyrics | `tuple[str, ...]`，必填 | 已解码的歌词行 |
| audio_path | `Path`，必填 | 音频输入 |
| timestamp_mode | `line` | `line` / `word` |
| acoustic_model | `MTL` | `Baseline` / `MTL` / `Baseline_BDR` / `MTL_BDR` |
| allow_partial | `False` | 显式接受非空连续前缀 |
| vocal_separation | `None` | 显式 `VocalSeparationOptions`；默认不分离 |

| RuntimeConfig 字段 | 默认 | 边界 |
|---|---|---|
| asset_root | `None` | API 显式根须为绝对 `Path`；CLI 会先 resolve 输入 |
| device | `auto` | CUDA 可用则 CUDA，否则 CPU；无 MPS |
| offline | `True` | `False` 配置被拒绝；Demucs 可选路径仍存在未落实的离线约束 |
| decoder | `torchaudio` | `librosa-mono` 只能显式选择，无自动回退 |
| seed | `0` | 非负整数 |
| max_alignment_bytes | `536870912` | DTW 分配估算上限，不是进程总内存限制 |

`AlignmentResult` 提供 `status`、`lrc`、`spans`、`diagnostics` 等结构化信息，以 [contracts.py](../t2l/contracts.py) 为精确字段依据。完整性不满足时默认抛出领域错误；partial 仅保留可证明的连续前缀。API 不写 LRC 或主动输出进度，底层准备仍涉及输入读取与私有资产复制，依赖可能输出警告。

错误类及稳定代码以 [errors.py](../t2l/errors.py) 为准。API 保留非领域的意外异常；CLI 将其映射为退出码 1，不应吞掉 KeyboardInterrupt/SystemExit/GeneratorExit。CLI 退出码和调用示例见[使用指南](USER_GUIDE.zh-CN.md)。

## 资产与运行时生命周期

定位优先级：显式配置 → `T2L_ASSET_ROOT` → 经识别的开发 checkout。禁止任意 CWD 同名搜索。包内权威 manifest 为 `t2l/_assets/legacy_v1_manifest.json`，开发镜像为 `assets/legacy_v1_manifest.json`，运行字节另行供应。完整六项资产路径见[使用指南](USER_GUIDE.zh-CN.md)。加载前检查大小、哈希、路径与 LFS placeholder；通过私有副本避免后续直接使用可变源资产。

`create_runtime` 提前验证 manifest、准备语言识别资产与 Mel 构造；checkpoint、fastText 对象与 G2P 按需加载。不同 runtime 缓存隔离，同一 runtime 的模型加载和推理有锁并串行执行。目前没有公共 close/context-manager 合约，不能将现有缓存复用视为完整服务生命周期验收。

Demucs 通过可选 extra 提供，其 `get_model` 可能下载权重。当前分离器没有完整接收并强制执行 offline 配置，因此仅核心默认路径可按预置资产离线使用。

## 冻结数值协议

| 参数 | LegacyV1 约定 |
|---|---|
| 采样率 | 22050 Hz |
| Mel | 128 bins，FFT 512，hop 256 |
| 时间轴 | pooling 3；每帧 `768 / 22050` 秒 |
| 多声道默认策略 | 首声道，不偷偷更换为平均混音 |
| 音素表 | 41 项，space 39，blank 40 |
| MTL | 保留 41×47 reduction 顺序 |
| BDR | alpha 0.8 |
| LSTM | 历史 `batch_first=True/False/False` |
| 时间戳 | 毫秒截断；行标签 `[mm:ss.mmm]`，token 标签 `<mm:ss.mmm>` |

不要通过修改 checkpoint 架构、golden、精度容差或 decoder 来使失败转绿。自然 partial 与跨语言质量仍需独立产品验收。

## 输出一致性

CLI 无 `-o` 时 stdout 为 UTF-8 LRC 加一个尾换行；有 `-o` 时 stdout 为空，使用原子文件 sink。sink 创建父目录、替换既有普通文件，并拒绝输入别名、非普通文件和任一级符号链接祖先。失败时旧文件可能仍保留，调用方必须以本次退出码判定成功。shell 重定向和 Python 自行写文件不继承这些保护。

## 开发与验证

```bash
uv sync --frozen --python 3.11 --group dev
uv lock --check --offline
```

面向默认核心路径的基础验证（依赖和本地资产已准备好）：

```bash
PYTHONDONTWRITEBYTECODE=1 uv run --offline --frozen --no-sync python -m pytest \
  tests/unit tests/component tests/test_alignment.py \
  tests/contract/test_cli_contract.py tests/contract/test_cli_subprocess.py \
  tests/contract/test_application_ports.py tests/contract/test_composition.py \
  tests/contract/test_dependency_boundaries.py tests/contract/test_migration_contract.py \
  tests/contract/test_error_registry.py tests/contract/test_document_links.py \
  tests/contract/test_spec_inventory.py -q -p no:cacheprovider
```

`tests/contract` 还含安全、进程与证据运行器测试，不应将整个目录称为快速测试。`component` 需要本地资产/解码器；`golden` 需要锁定 canonical 环境；`package` 检查构建/安装；`system` 涉及真实进程和平台隔离。直接执行全仓 pytest 会扩展验证范围，本轮文档交付不要求覆盖完整异常矩阵。

按变更需要执行静态检查与构建：

```bash
uv run --offline --frozen --no-sync ruff check .
uv run --offline --frozen --no-sync python -m pytest tests/package/test_wheel_metadata.py -q
uv build --offline
```

以上为维护命令，不表示每条都已在本轮通过；实际结果以[项目状态](PROJECT_STATUS.zh-CN.md)的交付验证记录为准。不在测试中临时安装未声明依赖，不重录 golden 规避回归，不以 fake、正常对照或单平台通过替代发布验收。

本轮按用户决定暂缓异常全覆盖，后续恢复安全资格工作时应依据[安全计划](W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md)和[S18 实施计划](S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)的冻结证据续接。
