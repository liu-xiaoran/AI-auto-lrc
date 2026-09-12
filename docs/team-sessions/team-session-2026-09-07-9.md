# S18 P1 B3f L Batch A Teams 验收记录

日期：2026-09-07

模式：Teams 单实现角色 架构只读裁决 QA独立真实runner复验 主任务文档治理

权威方案：[`../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第23节`S18-P1-PLAN-v1.10`

## 1. 结论

Batch A的9个configure argv variant在capture/retention双lane全部GREEN，authority从10/57晋级为 `28 implemented / 39 planned / 67 total`。整个B3f-L仍为PARTIAL；下一步只执行Batch B的6条nodeid boundary/+1。

## 2. 架构裁决

旧计划把invalid/duplicate limit写成runner configuration error，但真实代码边界是copied runner在command array后注入、events plugin于pytest_configure拒绝。Teams接受它作为plugin defense-in-depth，不为测试新增产品runner pre-validator。

真实oracle为pytest exit4、outer1、`PYTEST_EVENTS_CONFIGURATION_INVALID`、early-configure六件、no Gate。该profile无JUnit，不能复用4097 collection的七件EARLY。Policy preflight错误、完整evidence command drift和plugin configure错误继续分属三个不同信任边界。

## 3. 实现与防假绿

Mutation只改复制runner且只影响目标lane；invalid替换单值，duplicate紧邻复制同一token。Receipt唯一mutated file为runner，绑定base/mutated hash；plugin/test不变。目标lane保存runner-error v2和六件exact artifacts，external verifier INPUT_INVALID/no output；控制lane FULL PASS并独立replay。

5000位十进制值真实进入command和receipt，marker精确一次，无Traceback、INTERNALERROR或Python integer conversion异常。Duplicate token count精确为2，防止first/last-wins实现假绿。

## 4. 证据

| 证据 | 结果 | 路径或hash |
|---|---|---|
| TDD RED | unsupported Batch A recipe | `/private/tmp/ai-auto-lrc-s18-b3f-batch-a-red.WPzjfa/run.log` |
| 首个characterization | zero capture实测六件profile | `/private/tmp/ai-auto-lrc-s18-b3f-ewqg0ncp` |
| 实现方18节点 | `18 passed in 38.26s` | `/private/tmp/ai-auto-lrc-s18-b3f-batch-a-final.Nhl1ru/run.log` |
| QA fresh 18节点 | `18 passed in 38.22s` | `/private/tmp/ai-auto-lrc-s18-b3f-batch-a-qa.amGKK3`；JUnit `08f9975eb9a3fa5b9d1c1e269576354b6991dfe6cf71e9b56006ce59838cdfaa` |
| QA authority/collection | `4 passed in 0.13s` | JUnit `a795975d94375c674b09dbcdf7a17cd25e1e81188a103241c7ab6030c5ae8952` |
| 468核心文件checksum | 闭合 | `5822799ff8cc94f8cf808b762e17dcd955c1540b3ed81cee21a452ee572fa516` |
| QA hash manifest | 闭合 | `3fec6debb54ba536ca514a0225e493a25d1b53607a347600631f1086b1202eeb` |

最终代码/authority SHA-256：

```text
policy     c7e02af2303a1ada48590493abfc605737c3185327aeec1eceb19eb5355a39cd
events     aa44ed1307b221c3cdd538e31942a0005abf399f3ff76a1b3a0e042454c91ef6
runner     ba633df67a85b2854a82e41fdb607bed6dd652bd0dbfd3c8788eb45a01972bb8
verifier   354db6f314a75b3468ebb76ceface16a5f8a990a3fc24a3533a8e08fbecaf074
tests      dca43ce13777fcd5971e8e630f8ff59bdaf37ba854334b8d56b34165e97b935e
authority  b663323b82622aafe97e38301cc53245b20fca6d9724d0f591391c131c8cf331
```

## 5. 边界

本批最多证明28条real-runner records的host mutation contract。39条仍planned，既有10条证据因test byte变化是历史checkpoint，最终必须67条同hash fresh replay。未运行full contract，不构成B3f-L、B3f-R、平台qualification或Release批准。

未执行commit、push、CI、upload/sync、签名、发布、archive、restore、delete或destruction；W1b-5c/5d/5e未授权。
