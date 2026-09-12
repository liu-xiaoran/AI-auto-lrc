# S18 P1 B3f L Batch E Teams 验收记录

日期：2026-09-07

模式：Teams 单实现角色 架构时序裁决 QA独立身份与replay审计 主任务文档治理

权威方案：[`../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第27节`S18-P1-PLAN-v1.14`

## 1. 结论

Batch E六条existing-final/preexisting-temp/publish-race records已GREEN，authority为58 implemented/9 planned/67。该结果证明configure预检、preexisting temp ownership和真实link/EEXIST no-replace race的host mutation合同，不证明B3f-L闭合、B3f-R或平台qualification。

## 2. 架构与时序裁决

Runner会在启动时拒绝已有artifact root，随后才创建lane目录。因此protected fixture不能在shell runner启动前预置；正确时点是copied plugin import阶段、真实child PID已知且pytest_configure尚未执行。Target guard同时绑定完整绝对output与canonical `--security-events/--security-target` argv；禁止glob、预测PID、环境变量seam和全局os monkeypatch。

Protected object以lstat证明regular并记录dev/ino/mode/nlink/size/sha256。Preexisting temp由真实child PID精确命名，writer真实open返回EEXIST且从未获得ownership。Publish race在file fsync/close后、link前创建competitor，并由真实os.link返回EEXIST；不能由synthetic link failure代签。

## 3. 实测结果

- Existing-final：pytest/outer 4/1，configuration marker精确一次，EARLY_CONFIGURE+protected final七项，无Gate，replay INPUT_INVALID；0640 final六字段不变，writer未进入。
- Preexisting-temp：1/1，terminal publication marker精确一条，NO_EVENTS+PID temp十二项，Gate `COMMAND_FAILED, PYTEST_EVENTS_INVALID`；0640 protected temp六字段不变，无cleanup unlink。
- Publish-race：1/1，同一terminal marker，FULL十二项但competitor events内容无效，Gate同上；0640 winner六字段不变且与owned temp不同inode，owned temp被精确清理，无directory调用。
- 三类control均canonical、FULL/Gate PASS、events 0600 single-link、无fixture或trace泄漏。

## 4. 证据

```text
RED root              /private/tmp/ai-auto-lrc-s18-b3f-batch-e-red.TGZwzp
implementation final  /private/tmp/ai-auto-lrc-s18-b3f-batch-e-final.BByAxr
QA root               /private/tmp/ai-auto-lrc-batch-e-qa.nnN2Qw
QA exact log          460be167c416c53c5cab739ac8042294c2249d19cfa73c9664881e843e5a8d16
QA exact JUnit        e49d77c095ef2170c55993492ac30925b1879b66a479ac4ac09ba75d02929946
QA roots list         255ea5dfcbd6a4fdc1a702423a2fa370b7c3f2cd6c14cec78c64cf35c10846f3
key checksums         548a2ad6c6e7628f30f45e1f21b09f2d36622c36c76fad5a91fd224caf01f75e
independent audit     e5422d223e620d1c92fcb34ba68c8957a653c19011a80ed9d6b6c7ed749ab260
```

```text
policy     c7e02af2303a1ada48590493abfc605737c3185327aeec1eceb19eb5355a39cd
events     aa44ed1307b221c3cdd538e31942a0005abf399f3ff76a1b3a0e042454c91ef6
runner     ba633df67a85b2854a82e41fdb607bed6dd652bd0dbfd3c8788eb45a01972bb8
verifier   354db6f314a75b3468ebb76ceface16a5f8a990a3fc24a3533a8e08fbecaf074
tests      bc713de0b96630470a91978dd5705d96d80e3eb90e5c66d23bff521a93dc0188
authority  08d8fb9c7ac9be77aac5ea4f7c25884c28d87b5f1cd945cc7995cde4846cc38e
```

## 5. 透明性与下一步

实现方一次误用直接pytest入口造成collection import失败、一次错误workdir未创建进程；QA一次roots grep范围错误、一次组合pgrep自观察、一次错误workdir未启动。均已修正并透明保留，不算合同RED。Authority晋级前曾遗漏configure phase existing-final的参数集合，正式冻结前已修复。

9条仍planned。唯一下一步为Batch F六条temp-unlink-retry/directory-fsync/directory-close，目标64/3/67；不得进入Batch G-H、B3f-R或平台qualification。S18、W1b-5b、Release继续No-go，未执行commit/push/CI/upload/sync/sign/publish/archive/restore/delete/destruction。
