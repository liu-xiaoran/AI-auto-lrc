# AI-auto-lrc 文档导航

[English (primary)](README.md) · [简体中文](README.zh-CN.md)

更新日期：2026-09-12；版本：`2.0.0a0`。**英文为主文档。** 每页提供对应中文版语言链接。当前指南用于操作，历史执行计划用于追溯。

| 目的 | English（主版本） | 简体中文 |
|---|---|---|
| 让 AI 协助运行 | [README and copyable prompt](../README.md) | [README 与提示词](../README_zh.md) |
| 安装、生成 LRC、排查问题 | [User guide](USER_GUIDE.md) | [使用指南](USER_GUIDE.zh-CN.md) |
| 了解能力和处理流程 | [System overview](SYSTEM_OVERVIEW.md) | [系统说明](SYSTEM_OVERVIEW.zh-CN.md) |
| API 集成、开发与测试 | [Technical guide](TECHNICAL_GUIDE.md) | [技术指南](TECHNICAL_GUIDE.zh-CN.md) |
| 查看完成情况、证据和暂缓事项 | [Project status](PROJECT_STATUS.md) | [项目状态](PROJECT_STATUS.zh-CN.md) |
| 迁移旧调用方 | [v1-to-v2 migration](V1_TO_V2_MIGRATION.md) | [v1 到 v2 迁移](V1_TO_V2_MIGRATION.zh-CN.md) |
| 查看历史基线与恢复依据 | [Baseline provenance](BASELINE_PROVENANCE.md) | [基线来源与恢复](BASELINE_PROVENANCE.zh-CN.md) |
| 与 AI 协作开发 | [AI development guidance](../CLAUDE.md) | [AI 开发指引](../CLAUDE.zh-CN.md) |

`main` 包含用于本地核心流程的 Alpha 快照，v2 成果已合入。按用户决定，异常场景暂不全覆盖；未验证的发布门禁仍保持未验证。当前范围以项目状态为准。

## 语言与维护

不带语言后缀的默认文件为英文；中文使用 `.zh-CN.md`，已有根目录中文 README 保留 `README_zh.md`。命令、公开默认值、结果和边界需要双语同步更新。英文页面默认链接英文指南，中文页面默认链接中文指南。

## 历史原始记录

以下为中文执行/评审原文，不是主要使用说明，也不构成新的验证证据：

- [v2 执行与测试计划](AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md)。
- [LegacyV1 冻结交接](AI_REFACTOR_HANDOFF.zh-CN.md)。
- [S18 实施计划](S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)。
- [受控证据采集计划](W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md)。
- [留存管理执行计划](W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md)。
- [安全资格计划](W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md)。

原始团队评审位于 `docs/team-sessions/`，证据索引与审查记录位于 `docs/evidence/`。当前结论和证据链接见双语[项目状态](PROJECT_STATUS.zh-CN.md)。查阅历史记录时保留原始日期、哈希和冻结验收范围。
