# track-lrc-align

> AI 驱动的歌词对齐工具 — 从纯文本歌词和音频文件生成带时间戳的 LRC 文件，支持逐字或逐句对齐。

[English](README.md)

## 概述

`track-lrc-align` 接受歌词文本文件和音频文件，生成同步的 LRC 文件。它使用 CNN-RNN 声学模型配合 DTW（动态时间规整）对齐算法，将音素映射到音频帧。内置的 [Demucs](https://github.com/adefossez/demucs) 人声分离功能可隔离人声，提升对齐精度。

**支持语言**：中文（zh）、日文（ja）、韩文（ko）、英文（en）、俄文（ru）

## 安装

```bash
git clone https://github.com/liu-xiaoran/auto-lrc.git
cd auto-lrc

# 模型检查点需要 Git LFS
git lfs install
git lfs pull

pip install -r requirements.txt
```

> 推荐使用 Python 3.9 / 3.10。项目依赖 PyTorch 和 Demucs，建议使用 GPU 以获得合理的运行速度。

运行不加载检查点、不下载 Demucs 模型的轻量 CPU 回归测试：

```bash
python -m pytest -q
```

## 快速开始

```bash
python main.py demofile/original_txt.txt demofile/original_track.mp3
```

以默认设置运行完整流水线：逐字对齐、Demucs 人声分离（mdx_extra 集成模型）。终端打印增强型 LRC（含逐字时间戳），标准 LRC 文件（仅行级时间戳）自动保存到 `demofile/original_track.lrc`。

### 命令行参数

```
python main.py <歌词文件> <音频文件> [选项]

选项：
  -f, --format     输出格式：仅支持 lrc（默认）
  -l, --line_only  1 = 逐句时间戳，0 = 逐字时间戳（默认）
  -v, --vocalize   1 = 通过 Demucs 分离人声（默认），0 = 跳过
  -m, --model      Demucs 模型：mdx | mdx_extra（默认）| mdx_q | mdx_extra_q
  -i, --idx        Demucs 模型索引：-1 = 集成（默认），0-3 = 单个子模型
  -o, --out_dir    标准 LRC 输出目录（默认：demofile）
```

### 示例

```bash
# 逐字对齐 + 人声分离（默认）
# 终端打印增强型 LRC，标准 LRC 保存到 demofile/song.lrc
python main.py lyrics.txt song.mp3

# 逐句对齐，不分离人声（更快）
python main.py lyrics.txt song.mp3 -l 1 -v 0

# 使用更轻量的 Demucs 模型
python main.py lyrics.txt song.mp3 -m mdx_q

# 指定标准 LRC 输出目录
python main.py lyrics.txt song.mp3 -o output
```

## Python API

```python
from t2l.t2l import process

lrc = process(
    txt_lines,              # list[str]：歌词行列表
    "song.mp3",             # 音频文件路径
    mtl_model="MTL",        # "Baseline" | "MTL" | "Baseline_BDR" | "MTL_BDR"
                            # 或通过 init_model 预加载的模型元组
    demucs_model="mdx_extra",
    demucs_idx=-1,
    line_only=False,        # True = 逐句，False = 逐字
    out_file="output.lrc",  # 可选：写入文件
    verbose=True,
    vocalize=True,          # 设为 False 跳过 Demucs，直接使用原始音频
    format="lrc"
)
print(lrc)
```

`format` 参数当前仅接受 `"lrc"`，其他值会抛出 `ValueError`。直接对齐多声道原始音频（`vocalize=False`）时，为兼容既有输出并避免声道首尾串接，程序使用第一个声道。

如需避免多次调用时重复加载模型，可使用 `t2l.init_model`：

```python
from t2l.t2l import process
from t2l.init_model import load_mtl_model

model = load_mtl_model("MTL")  # 只加载一次
lrc1 = process(lines1, "song1.mp3", mtl_model=model)
lrc2 = process(lines2, "song2.mp3", mtl_model=model)
```

## 工作原理

```
歌词文本 + 音频文件
  │
  ├─ phonetic.py
  │   语言检测：正则匹配 CJK/西里尔字母 → fastText 回退（lid.176.ftz）
  │   音素化：将字符转为 ASCII 音素
  │     zh → pypinyin
  │     ja → pykakasi
  │     ko → kroman
  │     ru → cyrtranslit
  │     en → g2p_en
  │
  ├─ t2l.py
  │   音频加载：torchaudio.load → librosa.load（回退）
  │   人声分离：Demucs（mdx_extra 集成模型，4 个子模型）
  │   重采样至 22050 Hz
  │
  ├─ mtl/wrapper.py
  │   梅尔频谱图（128 bins，FFT 512）
  │   CNN-RNN 声学模型 → 音素后验概率图
  │   DTW 对齐（utils.alignment / alignment_bdr）
  │
  └─ gen_lrc()
      帧索引 → [MM:SS.mmm] 时间戳
      输出含逐字 <timestamp> 标签的 LRC
```

### 模型检查点

存储在 `./checkpoints/`，通过 Git LFS 管理：

| 检查点 | 类型 | 说明 |
|---|---|---|
| `checkpoint_Baseline` | 单任务 | 声学模型，41 个音素类 |
| `checkpoint_MTL` | 多任务 | 默认模型，类数 (41, 47) |
| `checkpoint_BDR` | 边界检测 | 1.8 MB，与 `*_BDR` 变体配合使用 |

对齐流水线的 `method` 参数接受 `"Baseline"`、`"MTL"`、`"Baseline_BDR"` 或 `"MTL_BDR"`。BDR 变体包含边界检测，可获得更精确的字词起始时间。

### 关键参数

| 参数 | 值 | 说明 |
|---|---|---|
| 采样率 | 22050 Hz | 重采样目标采样率 |
| 帧分辨率 | ~0.0348s | `256 / 22050 * 3` 秒/帧 |
| 梅尔特征数 | 128 | 用于 `train_audio_transforms` |
| FFT 大小 | 512 | 频谱图计算 |

## 输出

CLI 产生两种输出：

1. **增强型 LRC** — 打印到终端，含逐字 `<mm:ss.xxx>` 时间戳，用于精细对齐
2. **标准 LRC** — 保存到 `demofile/`（或 `-o` 指定的目录），仅含行级 `[mm:ss.xxx]` 时间戳，兼容标准 LRC 播放器

标准 LRC 文件名取自音频文件名，例如 `song.mp3` → `demofile/song.lrc`。

## 输出格式

### 逐字 LRC

```lrc
[00:00.120]<00:00.120>Hel<00:00.240>lo<00:00.360> <00:00.480>World
[00:01.000]<00:01.000>这<00:01.120>是<00:01.240>一<00:01.360>首歌
```

每个字/词前有其开始时间戳（尖括号），每行以行级时间戳（方括号）开头。

### 逐句 LRC

```lrc
[00:00.120]Hello World
[00:01.000]这是一首歌
```

仅包含行级时间戳。

## 依赖

核心依赖（完整列表见 `requirements.txt`）：

- **PyTorch / torchaudio** — 音频处理与模型推理
- **Demucs** — 人声/伴奏分离
- **librosa** — 音频加载回退方案
- **fastText** — 非 CJK 文本的语言检测
- **pypinyin / pykakasi / kroman / cyrtranslit / g2p-en** — 各语言音素化

> `pykakasi`（日文罗马化）采用 GPL 许可证。如计划以其他许可证使用本项目，请注意此依赖。

## 许可证

详见 [LICENSE](LICENSE)。
