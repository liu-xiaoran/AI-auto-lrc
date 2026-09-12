# S18 P1 B3f L Batch F Teams 验收记录

日期：2026-09-07

模式：Teams 单实现角色 架构post-publication裁决 QA独立call-site审计 主任务文档治理

权威方案：[`../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第28节`S18-P1-PLAN-v1.15`

## 1. 结论

Batch F六条temp-unlink-retry/directory-fsync/directory-close records已GREEN，authority为64 implemented/3 planned/67。该结果证明link后的commit-uncertain分类、final保留和精确cleanup/directory call-site合同，不证明B3f-L闭合、B3f-R或平台qualification。

## 2. 架构与实现裁决

LINK成功后立即记录final/temp同inode、nlink2、0600的六字段身份；之后任何错误必须COMMIT_UNCERTAIN且final不得回滚。File与directory descriptor按call-site role区分，不能按fd整数或调用次数猜测。

最终结构审查发现主directory close和outer-finally close一度共用DIR_CLOSE wrapper。团队将其拆为DIR_CLOSE与CLEANUP_DIR_CLOSE，旧exact-6保留为superseded GREEN，新hash下全部重跑。最终两个directory-close root只有一次主close，均先真实close再注错；所有六个root的cleanup directory close为0。

## 3. 实测结果

- Temp-unlink-retry：首次publish unlink受控失败，outer cleanup对同一owned temp真实成功；final 0600/nlink1，temp absent，无directory调用。
- Directory-fsync：publish unlink和dir open成功，精确dir fd fsync前注错，同fd dir close真实成功。
- Directory-close：dir fsync真实成功，主close真实完成后注错，无double-close。
- 六条均pytest/outer 1/1、单条terminal COMMIT_UNCERTAIN、FULL 12、Gate仅COMMAND_FAILED；control全部FULL PASS，十二次external replay逐字一致。

## 4. 证据

```text
RED roots             /private/tmp/ai-auto-lrc-s18-b3f-fcjigjxx
                      /private/tmp/ai-auto-lrc-s18-b3f-batch-f-red.qFQ5hQ
trace-key failure     /private/tmp/ai-auto-lrc-s18-b3f-yzsj9oij
implementation final  /private/tmp/ai-auto-lrc-s18-b3f-batch-f-final2.djeTwM
QA root               /private/tmp/ai-auto-lrc-batch-f-qa.qW6ETK
QA exact log          d068a99966f0819947653ca097c36d043eb5aa5daa08e2de7d8b873e5c86e296
QA exact JUnit        0767b2bc6f59051b059fda3ba87de08d4dbda737dda3137e1120c1ad966449be
QA roots list         d04218fc826e38f287da3909d4e8cbe2f5eb984c79ff57298ffbcf0afe8464da
key checksums         8400f104070c4bf2da27816657ce26f6c44cc62a649ed48f2a27f3114ca61284
independent audit     2e10e41356420168122f968d19f91c049bce3abdb5e19f9465eefdd37fd1fd91
```

```text
policy     c7e02af2303a1ada48590493abfc605737c3185327aeec1eceb19eb5355a39cd
events     aa44ed1307b221c3cdd538e31942a0005abf399f3ff76a1b3a0e042454c91ef6
runner     ba633df67a85b2854a82e41fdb607bed6dd652bd0dbfd3c8788eb45a01972bb8
verifier   354db6f314a75b3468ebb76ceface16a5f8a990a3fc24a3533a8e08fbecaf074
tests      7b680054b918e9ed64a68708bf6f7d02cf75b755d95d3aec1e8d9b081ec47f9a
authority  70fa1e697a86e8119867200e9876e8354c753a68c77d36c9bc64c8c8b9e00938
```

## 5. 透明性与下一步

Unsupported recipe RED、trace detail字段冲突失败和拆分cleanup close前的superseded GREEN均保留。QA两次JUnit路径输入错误均未启动pytest/runner，之后重新进程门并正确全绿。

3条仍planned。唯一下一步为Batch G两条exact syscall-order，目标66/1/67；不得跳过Batch H或提前最终replay。S18、W1b-5b、Release继续No-go，未执行commit/push/CI/upload/sync/sign/publish/archive/restore/delete/destruction。
