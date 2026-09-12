# Dev Team 会话：W1b-5 S17 输入边界与真实 CLI

日期：2026-09-06  
模式：PM / Architect / Developer / QA；角色评审只读，由主任务实施、验证和回写  
主题：在 S16 完成后细化并实施 S17 的 config special-file/owner、真实 CLI 脱敏和 capture `source` exact-key 合同，同时隔离当前宿主无法关闭的 Linux device required gate。

## PM

1. **First reaction**：S17 是输入边界与真实 CLI 证据切片，必须先锁定拒绝点和输出合同，不能用 macOS 结果代替 Linux device。
2. **Key concerns**：hardlink/FIFO/socket/wrong-owner 必须在 control 写入前拒绝且不阻塞；真实 subprocess 同时断言退出码、stdout/stderr 无路径、secret、traceback；source unknown-key exact 拒绝要兼容既有 v1 错误合同。
3. **First action**：建立 config 类型 × API/CLI × 副作用矩阵，再做最小实现并跑定向、联合与宿主全量。
4. **Question for team**：Linux root/device runner 与最终 S17 Go 签署人是谁？

## Architect

1. **First reaction**：S17 应把“拒绝危险对象”和“CLI 不泄露路径”固化为跨平台合同；Linux device 必须由真实 Linux 证据支撑。
2. **Key concerns**：anchored parent 下先 nofollow stat 判 regular，再以 `O_NOFOLLOW|O_NONBLOCK|O_CLOEXEC` 打开并复核 identity；FIFO 必须在 open 前拒绝；`source` 顶层使用 exact-key allowlist，错误输出不能含路径。
3. **First action**：冻结 macOS 与真实 Linux 的参数化负向矩阵及 CLI 子进程脱敏断言。
4. **Question for team**：若 Linux runner 不能安全创建 device fixture，谁提供隔离环境和权限？

## Developer

1. **First reaction**：现有 `_stable_bytes()` 已具备 regular、uid、nlink、nonblocking、nofollow、限长与前后 identity 复核，S17 应用合同证明而非重写读取器。
2. **Key concerns**：测试 helper 不能先 `read_bytes()` FIFO；Unix socket 使用绝对路径可能超过 macOS 长度上限；source exact-key 新增时必须保留旧 `observation_limit` 错误优先级。
3. **First action**：新增危险 config、wrong-owner、真实 CLI、unknown source claim RED；只在 capture verifier 加顶层 exact-key 检查。
4. **Question for team**：Linux device 证明是否明确推迟到 S18 required runner，而不在 macOS 增加一个可预期 skip？

## QA

1. **First reaction**：已有 control 特殊文件和部分 CLI 脱敏，但配置节点、Linux device、receipt source 严格形状仍有缺口。
2. **Key concerns**：CLI 需精确 exit/stderr 与零泄漏；config special node 仅允许对应 schema error 且无 `.control`；Linux block/char 只允许 `UNSAFE_FILE_TYPE`，macOS skip 不算通过。
3. **First action**：定向矩阵连续 20 轮，再跑 capture、retention、联合和宿主全量；首次失败与测试假设错误都要保留。
4. **Question for team**：Linux required runner 与 flaky 零容忍由谁签署？

## 综合结论

- config 读取生产实现无需新 I/O primitive；S17 增加 hardlink/FIFO/socket/wrong-owner 合同，证明它们在 control tree 创建前 fail closed。
- capture `source` 顶层冻结为六个 exact keys：`before`、`after`、两个 aggregate、`stable_during_run`、`observation_limit`；额外的 `transactional`、`aba_excluded`、`qualification` 均拒绝。
- 兼容性张力明确保留：缺失或篡改 `observation_limit` 继续优先返回 `source.observation_limit is invalid`；只有额外未知 key 返回 `source has an invalid shape`。
- 真实 CLI 对 sensitive actor 返回单行稳定 token，不回显输入；secret 文件名会进入被封存的 status/summary 并正确导致 `SCANNED_BLOCKED`，但 stdout 仍不回显文件名或 secret。
- Linux block/char device 没有当前 Darwin 宿主证据，因此 S17 只能给 macOS 可执行范围 Conditional Go，不能整体关闭。

## RED 与修正记录

首轮定向：`10 passed, 6 failed, 304 deselected`。

- 3 个真实生产 RED：`source` 接受 `transactional=true`、`aba_excluded=true`、`qualification=release`；
- 2 个 fixture RED：Unix socket 绝对路径超过 macOS `AF_UNIX` 长度，改为在 config parent cwd 下绑定 basename；
- 1 个期望 RED：secret filename 被 source status/summary 扫描器正确命中，实际应为 exit 3 / `SCANNED_BLOCKED`，不是 exit 0。

修正后定向为 `16 passed`。随后连续 20 轮均为 `16 passed, 304 deselected`，共 320 次 case execution；单轮耗时 6.32–12.14 秒，无失败。

第一次 capture+retention 联合为 `1 failed, 319 passed`：旧 S15 的 missing observation-limit 用例期望 `source.observation_limit` 精确错误，但 exact-key 校验提前返回 shape error。生产校验顺序修正为 type → observation_limit value → exact-key，旧+新相关 5 个节点通过，联合重跑为 `320 passed`。此失败必须保留，不能只报告重跑绿色。

## 当前验证与 Gate

2026-09-06，Darwin 25.6.0 arm64、Python 3.11.4：

```text
S17 targeted initial:       10 passed, 6 failed
S17 targeted fixed:         16 passed
S17 stability:              20/20 rounds passed; 320 case executions
capture contract:           145 passed in 23.91s
retention contract:         175 passed in 57.91s
combined first:             1 failed, 319 passed
combined retry:             320 passed in 102.99s
host full:                  670 passed, 18 skipped, 22 warnings in 190.60s
ruff / compileall / diff:   PASS
document relative links:    1 passed
```

| 范围 | Gate |
|---|---|
| S17 macOS config/CLI/source-shape | Conditional Go；本轮合同已闭合 |
| S17 Linux block/char device | No-go / required runner 未执行 |
| W1b-5b | No-go；等待 S18、Linux 和 evidence refresh |
| W1b-5c/5d/5e | 未授权、未实现 |
| Release | No-go |

下一步进入 S18 的 branch/关键安全分支 coverage 和 Linux/package/canonical qualification。精确入口见 [`../W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md`](../W1B5_RETENTION_MANAGER_EXECUTION_PLAN.zh-CN.md) 最新章节；禁止事项不变。

## 后续 S18 勘误

本会话保留 S17 当时“Linux device 未执行”的历史事实，不回写覆盖。随后 S18 已在 Linux/amd64 Python 3.11.9 受控容器完成 S16+device `9 passed` 和 `/proc/self/fd`+source `9 passed`；其范围、证据缺口与当前 Gate 见 [`team-session-2026-09-06-6.md`](./team-session-2026-09-06-6.md) 和 [`../W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md`](../W1B5_S18_SECURITY_QUALIFICATION_PLAN.zh-CN.md)。
