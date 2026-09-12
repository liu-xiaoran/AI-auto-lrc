# AI-auto-lrc documentation

[English (primary)](README.md) · [简体中文](README.zh-CN.md)

Updated: 2026-09-12; version: `2.0.0a0`. **English is the primary documentation language.** Use the Chinese companion linked on each page when preferred. Current guides explain operation; historical execution plans provide traceability.

| Purpose | English (primary) | 简体中文 |
|---|---|---|
| Ask an AI assistant to run the project | [README and copyable prompt](../README.md) | [README 与提示词](../README_zh.md) |
| Install, generate LRC, and troubleshoot | [User guide](USER_GUIDE.md) | [使用指南](USER_GUIDE.zh-CN.md) |
| Understand capabilities and processing | [System overview](SYSTEM_OVERVIEW.md) | [系统说明](SYSTEM_OVERVIEW.zh-CN.md) |
| Integrate the API, develop, and test | [Technical guide](TECHNICAL_GUIDE.md) | [技术指南](TECHNICAL_GUIDE.zh-CN.md) |
| Review completion, evidence, and deferred work | [Project status](PROJECT_STATUS.md) | [项目状态](PROJECT_STATUS.zh-CN.md) |
| Migrate old callers | [v1-to-v2 migration](V1_TO_V2_MIGRATION.md) | [v1 到 v2 迁移](V1_TO_V2_MIGRATION.zh-CN.md) |
| Check the historical baseline and recovery references | [Baseline provenance](BASELINE_PROVENANCE.md) | [基线来源与恢复](BASELINE_PROVENANCE.zh-CN.md) |
| Work on the code with an AI agent | [AI development guidance](../CLAUDE.md) | [AI 开发指引](../CLAUDE.zh-CN.md) |

`main` contains the Alpha snapshot for local core workflows, including the merged v2 work. Exhaustive abnormal scenarios are deferred by user decision; unverified release gates remain unverified. The project status page defines the current scope.

## Language and maintenance

Default filenames without language suffixes are English. Chinese companions use `.zh-CN.md`; the existing root Chinese README keeps `README_zh.md`. Update commands, public defaults, results, and limits in both versions together. English pages link to English guides by default, and Chinese pages to Chinese guides.

## Historical source records

The following are original Chinese execution/review records, not the primary usage documentation or new validation evidence:

- [v2 execution and test plan](AI_REFACTOR_V2_EXECUTION_PLAN.zh-CN.md).
- [Frozen LegacyV1 handoff](AI_REFACTOR_HANDOFF.zh-CN.md).
- [S18 implementation plan](S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md).
- [Controlled evidence capture plan](W1B_CONTROLLED_EVIDENCE_CAPTURE_PLAN.zh-CN.md).
- [Retention manager execution plan](W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md).
- [Security qualification plan](W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md).

Original team reviews remain under `docs/team-sessions/`; evidence indexes and review artifacts remain under `docs/evidence/`. Use the bilingual [project status](PROJECT_STATUS.md) for current conclusions and direct evidence links. Preserve original dates, hashes, and frozen acceptance scope when consulting these records.
