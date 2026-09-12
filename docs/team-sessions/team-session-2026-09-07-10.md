# S18 P1 B3f L Batch B Teams 验收记录

日期：2026-09-07

模式：Teams 单实现角色 架构fixture审查 QA独立real runner复验 主任务文档治理

权威方案：[`../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第24节`S18-P1-PLAN-v1.11`

## 1. 结论

Batch B六条nodeid real-runner records全部GREEN，authority为34 implemented/33 planned/67。当前只证明ASCII 4096边界、ASCII 4097 char fast-path与decomposed Unicode 4097 UTF-8 byte-path；B3f-L仍未闭合。

## 2. Fixture 与架构裁决

Pytest默认转义非ASCII parameter ID。实现采用复制目标module的dynamic global-key，以ASCII函数名前缀和raw Unicode bracket suffix创建真实collected nodeid，避免修改产品pyproject/runner并绕过ID escaping。QA确认该方案只新增一个item、alias删除、canonical grammar通过、raw bytes不被normalize。

Boundary chars=bytes4096并FULL PASS；ASCII +1为4097/4097；multibyte +1为chars2754、bytes4097且NFC不同。Case count和serialized upper bound均远低于更后置limit，不会抢先触发。

## 3. 证据与hash

```text
implementation  6 passed in 12.91s
QA              6 passed in 13.28s
authority       4 passed in 0.15s
QA root         /private/tmp/ai-auto-lrc-s18-b3f-batch-b-qa.t5HJQy
QA JUnit        78e58581fb6e86668bbdcae0c25479636e80b79f7f2c92ab12de5058074b6a14
core checksums   562fcf7c1088e95e141e9ea2d0de3d574c6b570754c86213aefd0cf8964fca6a
QA manifest      9a17a4c8760dd693a2ec90d8b883dbc9bfd5e363c29348aa71c5de0712c26ef5
```

```text
policy     c7e02af2303a1ada48590493abfc605737c3185327aeec1eceb19eb5355a39cd
events     aa44ed1307b221c3cdd538e31942a0005abf399f3ff76a1b3a0e042454c91ef6
runner     ba633df67a85b2854a82e41fdb607bed6dd652bd0dbfd3c8788eb45a01972bb8
verifier   354db6f314a75b3468ebb76ceface16a5f8a990a3fc24a3533a8e08fbecaf074
tests      be3ccca37715c1f027232d71a58f85c7ca9fa8ea11a93b1ea089dac7c8d2c2c9
authority  59d8c9cae97108482c34a7b50b6e577bfdf57f566a1533e3c1c0dd935d0eb31f
```

## 4. 下一步与边界

下一步只执行Batch C四条serialized 8 MiB边界/+1。33条仍planned；未运行full suite，后续test变化会历史化本批证据，最终必须67条同hash replay。S18、W1b-5b、Release继续No-go；未执行commit/push/CI/upload/sync/sign/publish/archive/restore/delete/destruction。
