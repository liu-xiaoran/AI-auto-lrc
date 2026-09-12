# S18 P1 B3f L Batch D Teams 验收记录

日期：2026-09-07

模式：Teams 单实现角色 架构只读裁决 QA静态硬停止与独立复验 主任务文档治理

权威方案：[`../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第26节`S18-P1-PLAN-v1.13`

## 1. 结论

Batch D十四条pre-publication I/O records在marker语义修复后GREEN，authority为52 implemented/15 planned/67。该结果证明host copied-plugin mutation合同、writer syscall阶段隔离、partial write/no-progress处理和capture/retention双lane证据，不证明B3f-L闭合、pytest全进程资源有界、B3f-R或平台qualification。

## 2. Teams架构裁决

Fault injection只允许在copied plugin的精确call site包装，按目标output完整绝对路径生效；禁止全局monkeypatch共享`os`。Trace在attempt外no-throw写入，receipt绑定raw trace、目标output/temp/PID、注入位置、deadline/elapsed和全部bound hashes。Control lane调用真实`os`且不得记录trace。

File-close必须绑定temp fd并先真实close后注入错误，不能按close调用次数误伤directory fd。Write-zero只能发生一次zero write，之后不得再write/fsync/link；partial-write-success必须至少两次正数write且累计精确等于content bytes。Cleanup异常不得覆盖主异常。

## 3. Marker hard stop与修复

QA在启动pytest前发现实现把`stderr.count(PYTEST_EVENTS_PUBLICATION_FAILED) == 2`当作合同，违反方案“marker精确一次”。架构复核证明producer只抛出一个`EventsPublicationError`；raw stderr第二个substring来自traceback源码行回显。

最终oracle要求恰好一条按行锚定的terminal `EventsPublicationError`记录。Raw substring count 2只作展示观察，不作通过门；也不冻结异常必须是stderr最后一行。禁止修改producer异常链或过滤stderr来迎合字符串计数。旧十四个roots保留为characterization/superseded GREEN，新测试hash下重新fresh运行。

## 4. 结果与证据

十二条失败场景均为pytest/outer 1/1、terminal producer marker精确一条、NO_EVENTS十一件、Gate `COMMAND_FAILED, PYTEST_EVENTS_INVALID`、final/temp absent。两个partial-write-success为0/0、marker null、FULL/Gate PASS；两次正数write累计分别为capture 7216、retention 4774 bytes，final为0600 single-link。

```text
RED root              /private/tmp/ai-auto-lrc-s18-b3f-batch-d-red.pFUmI3
implementation final  /private/tmp/ai-auto-lrc-s18-b3f-batch-d-final2.RBiZk4
implementation checks /private/tmp/ai-auto-lrc-s18-b3f-batch-d-final2-checks.BE7ueO
QA root               /private/tmp/ai-auto-lrc-s18-b3f-batch-d-qa.fhlORH
QA exact log          cf16d2d131516298b917351f82a8a7a7e9b7f096c973e72a0eaf6b2ecab361fd
QA exact JUnit        9bc9988a2734feaec580c85b3ccd2396b6253ee6be3ae50bdd0dcb4b26fe53a7
QA roots list         08bd49bafc1aa61d6ad9b6b9c314e8cfcb98986f285f861265b9f677c642a996
evidence checksum     140fa52d4903cede72c15396b45f2e4077a19148bb36e4a43764bd615aff4e9f
QA artifact manifest  5d28fa724fdc9b6e43ece082fc837c90ba808b6e62d757ae684321fb5b52aee6
ordered receipts      9dfcb5283cea562efc0f68a672da5f15a8ff01ff3597e336a1b0b0bddaf181f2
```

```text
policy     c7e02af2303a1ada48590493abfc605737c3185327aeec1eceb19eb5355a39cd
events     aa44ed1307b221c3cdd538e31942a0005abf399f3ff76a1b3a0e042454c91ef6
runner     ba633df67a85b2854a82e41fdb607bed6dd652bd0dbfd3c8788eb45a01972bb8
verifier   354db6f314a75b3468ebb76ceface16a5f8a990a3fc24a3533a8e08fbecaf074
tests      56efc37cae5ca7aab28636660343c788b14a480aa66d702264fb1f06d4961d34
authority  9921474a3f3a83efc29f7ee6f91f7280db423b96dfa23989d486d8572060ee57
```

QA另行串行replay全部28个target/control verifier lanes并逐字比较Gate。Py_compile、Ruff、4项authority/collection、`git diff --check`全部PASS。

## 5. 透明性与下一步

实现和QA各有一次workdir误写导致命令在创建进程前失败，均无状态变化并保留为command error。QA先对旧marker断言hard stop，修复后才在冻结hash下fresh复跑；没有删除旧RED、attempt或superseded GREEN。

15条仍planned。唯一下一步为Batch E六条existing-final/preexisting-temp/publish-race，目标checkpoint 58/9/67；不得进入Batch F-H、B3f-R或平台qualification。S18、W1b-5b、Release继续No-go，未执行commit/push/CI/upload/sync/sign/publish/archive/restore/delete/destruction。
