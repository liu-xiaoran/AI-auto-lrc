# S18 P1 B3f L unit mutation Teams 验收记录

日期：2026-09-07

模式：Teams 实现 架构审计 QA 对抗复核 主任务独立验证

详细事实源：[`../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第 21 节 `S18-P1-PLAN-v1.8`

## 1. 结论

B3f-L 五文件 unit/mutation tranche已实现并在当前宿主通过；整个 B3f-L仍为 PARTIAL / No-go，唯一 blocker是方案第 20.7 节的独立 scenario authority与 capture/retention双 lane real-runner matrix。

主任务在所有代理停止写入、无其他 pytest/runner进程后独立得到 `44 passed, 213 deselected`和完整 `257 passed in 189.45s`。该结果不代签尚未存在的 real-runner nodes。

## 2. Teams 发现与修正

QA 在早期新增测试中拒绝了 zero-write脚本自身 TypeError、伪 8 MiB边界、未检查 open flags/mode与多次 write、缺 partial-write异常、缺 temp-open fault等弱 oracle。实现端逐项补强后形成 31项 unit合同和63项 mutation/characterization回归。

架构终审随后发现两个可执行 P1：最坏 phase模板低估3 bytes，5000位十进制limit在有界检查前触发 `int()`异常。两项均先保存精确 RED，再由实现修复，并由架构和QA独立定向复验通过。

Spec Inventory曾在实现中间态因参数 ID `B3F-L-007-zero`命中 decorated product ID grammar而 RED。最终 collected参数改用小写机器ID，scenario编号只作描述字段；该失败保存在 `/private/tmp/ai-auto-lrc-s18-v17-doc-verify2.f5xHxv`。

## 3. 证据与最终字节

主任务独立定向证据：`/private/tmp/ai-auto-lrc-s18-b3fl-root-targeted.NzQhgB`，JUnit SHA-256 `d413cfb3b8bcfc5fbb82a5b122dd0c4581581f24a65e9587aa5a067791d233cb`。

主任务独立完整证据：`/private/tmp/ai-auto-lrc-s18-b3fl-root-full.UAlfK6`，JUnit SHA-256 `de08a1d9f9825be83377c62dd78573d3a051dc56ccaf7f65d9e8ac069fd494e2`。

最终五文件 SHA-256：

| 文件 | SHA-256 |
|---|---|
| `scripts/pytest_security_events.py` | `aa44ed1307b221c3cdd538e31942a0005abf399f3ff76a1b3a0e042454c91ef6` |
| `scripts/run_security_coverage.sh` | `b79298af7ad80392f10c1f04c505ca5724d4dc80fff1afc163c18f77f368c15c` |
| `scripts/verify_security_coverage.py` | `9a324d972ded9c50f4b8009b2e90479b0c089758ba29a647d22a89b1031a4300` |
| `packaging/security-coverage-policy.toml` | `c7e02af2303a1ada48590493abfc605737c3185327aeec1eceb19eb5355a39cd` |
| `tests/contract/test_security_coverage_gate.py` | `4f118218ed8e9e08b3e813f42b5509dc35c92f82305f488abf437bc55f2484fc` |

并发污染的 `253 passed, 1 failed` attempt继续保存在 `/private/tmp/ai-auto-lrc-s18-b3fl-contract-green.845NcG`，不能删除、覆盖或与串行结果合并。

## 4. 唯一下一步与声明边界

下一步只执行方案第20.7节：先在现有 contract test建立独立scenario authority，再以 capture/retention双 lane逐一覆盖limit boundary与writer fault，冻结另一lane PASS、inner/outer exit、Gate排序、exact artifact set、mutation hash、sentinel和PID-temp evidence。

在这些 real-runner nodes全部存在并通过前，不批准整个B3f-L，不进入B3f-R，不刷新macOS/Linux/package/canonical/host/sealed资格证据。S18、W1b-5b、Release继续No-go；W1b-5c/5d/5e未授权。
