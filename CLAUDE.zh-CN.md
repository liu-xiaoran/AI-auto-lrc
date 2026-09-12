# CLAUDE.md 中文版

[English (primary)](CLAUDE.md) · [简体中文](CLAUDE.zh-CN.md)

面向 AI-auto-lrc v2 的 AI 开发指引。

## 当前交付决定（2026-09-12）

先阅读 `docs/README.zh-CN.md` 和 `docs/PROJECT_STATUS.zh-CN.md` 了解当前用途和范围。用户已明确授权更新文档、推送开发快照，随后要求合并并推送到 `main`。安装入口为 `main`，使用保留双方历史的正常合并。本次交付的提交/推送授权已满足，不要重复确认。异常全覆盖是暂缓，不是通过。保留现有检查与冻结证据；未授权发行标签、强制推送或重写主分支历史。

## 事实依据

改变公开行为或 LegacyV1 数值前阅读：

1. `docs/AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md`：v2 合约、里程碑、测试 ID 与 Go/No-go 门禁。
2. `docs/AI_REFACTOR_HANDOFF.zh-CN.md`：冻结的 `legacy-v1` 行为及证据快照。
3. `docs/BASELINE_PROVENANCE.zh-CN.md`：恢复与资产来源。

交接文档是历史证据，不改写成当前 v2 状态，不把计划或单机检查描述为发布资格。

## 锁定的 v2 决策

- Python `>=3.10,<3.12`，依赖事实源仅为 `pyproject.toml + uv.lock`。
- 公开 API：`AlignmentRequest`、`AlignmentResult`、`RuntimeConfig`、`create_runtime`、`process(request, *, runtime=None)`。
- 默认行级 LRC、MTL、严格完整性、离线、torchaudio，关闭 Demucs。
- partial 必须显式选择，CLI 返回 `3`。
- CLI stdout 与原子文件输出互斥；API 不写 LRC、不主动打印进度，但资产准备可创建私有副本，依赖可输出警告。
- 不发布 v1 CLI、旧散参数 `process()`、五元模型 tuple 或兼容 shim。
- 不从 torchaudio 隐式回退到 librosa；`librosa-mono` 必须显式选择。
- 不按任意 CWD 搜索资产，核心路径不隐式下载。可选 Demucs 可能下载权重，离线约束尚未验收。
- 保留 LegacyV1 架构和数值：22050 Hz、Mel 128/512/256、pooling 3、帧时钟 `768/22050`、首声道、LSTM `batch_first=True/False/False`、MTL reduction 顺序、BDR alpha 0.8。
- X01-X03、训练与旧评估不进入 v2 分发。

## 架构边界

```text
t2l.api / CLI
  -> application.AlignLyricsUseCase
       -> LyricsPreparationPort
       -> AudioPreparationPort
       -> InferencePort
       -> completeness policy
       -> LrcRendererPort
```

`t2l.composition` 是唯一默认组装入口。domain/application 不导入适配器、torch、torchaudio、librosa、Demucs、fastText 或输出 sink。后验/Mel/boundary 张量留在 LegacyV1 适配器内。CLI 负责歌词文件解码与 LRC 输出；API 运行时可读取音频、配置的本地资产并准备私有副本，但不写 LRC 或主动打印进度。默认核心路径离线；可选 Demucs 仍有未解决的离线约束缺口。

## 环境和命令

```bash
git lfs install
git lfs pull
uv sync --frozen --python 3.11 --group dev
```

基础单元和组件测试（完整精选核心测试见 `docs/TECHNICAL_GUIDE.zh-CN.md`）：

```bash
uv run --offline --frozen --no-sync python -m pytest tests/unit -q -p no:cacheprovider
uv run python -m pytest tests/component -q -p no:cacheprovider
```

验证：

```bash
uv lock --check
uv run ruff check .
uv run python -m compileall t2l tests
uv build
```

不要为测试通过临时安装未声明的包。打包测试必须使用声明的测试/构建工具链；不要为已删除的 v1 测试把 Demucs 加回核心依赖。

## 测试规则

- 行为改动遵循 RED → GREEN → REFACTOR。
- 测试名、docstring 或参数 ID 保留执行计划中的稳定规范 ID。
- 单元测试离线且轻量；contract 目录也包含较重的安全/进程 fixture。真实资产/解码器使用 `component`，canonical 对比使用 `golden`，进程/平台隔离使用 `system`；仅使用已注册 marker。
- 并发测试使用 `Barrier`/`Event`，不用 `sleep()`。
- 后验数组可以使用批准的容差；phone ID、帧对、完整性状态和 LRC 字节必须精确。
- fake-only 测试不能证明真实解码器、checkpoint 路径、自然 partial、安装 wheel、离线构建或恢复流程合格。
- 不改 golden、放宽容差、启用 partial 或换 decoder 来隐藏回归。
- API 保留意外异常，CLI 映射为 1；不将 KeyboardInterrupt、SystemExit 或 GeneratorExit 包装为领域失败。

## 改动和提交门禁

已批准的执行计划是 Gate 1，按小步实现与验证。提交前说明文件范围、验证证据、未闭合门禁和 Conventional Commit 信息；仅在缺少授权时等待 Gate 2 批准。未获得明确授权时不推送或重写 Git 历史。

已验证 Git bundle 不含 LFS 对象或当前未跟踪变更。保留用户改动并检查 `git status`；独立 LFS/工作区归档和离线恢复演练未通过前，不声称灾难恢复完成。

## 文档语言约定

当前说明文档以英文为主，默认文件名不带语言后缀；中文对应版本使用 `.zh-CN.md`，根目录 README 保留 `README_zh.md`。同步维护双语版本的命令、参数、默认值和验证边界；每页提供语言切换和相应语言的导航。历史执行计划、团队评审与证据原文保留为历史记录，不将其译文或摘要当作新验收证据。
