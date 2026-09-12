# S18 P1 B3f L real runner authority Teams 决策记录

日期：2026-09-07

模式：Teams 单实现角色 架构只读裁决 QA只读终审 主任务文档治理

权威执行方案：[`../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第22节 `S18-P1-PLAN-v1.9`

## 1. 结论

B3f-L real-runner authority已建立67条不可缩减记录，当前精确为 `10 implemented / 57 planned`。10条来自cases 4096/4097、link failure、永久temp unlink和directory open五个variant的capture/retention双lane。

这只是代表性host mutation checkpoint，不是第20.7节或整个B3f-L闭合。唯一后续入口是主方案第22.7节的八个批次；在57条全部真实GREEN并完成最终同hash 67-record replay前，不进入B3f-R。

## 2. Teams 分工与审阅结论

实现角色单独写入产品与合同代码，建立15字段authority、真实copied-runner harness、target-only mutation、exact artifacts、全mutated-file hash receipt、sentinel和PID-derived temp证据；未使用fake uv，未向产品runner增加测试专用argv/env seam。

架构角色冻结67条组成、planned到implemented单调晋级、EARLY/no-Gate边界、八批执行DAG与最终同hash replay门。其裁决是 `publication_phase=collection` 与EARLY artifact profile正交；不改成 `collection-early`，不新增第16个字段。

QA在实现停止、无长runner并发时只读检查：authority exact 15字段、67条唯一记录、`10/57`计数、implemented outer nodeid与实际collection双向相等、小写参数ID、无decorated Spec ID。轻量authority/collection复验为 `4 passed in 0.13s`。

主任务只负责汇总已验证事实、保留历史checkpoint、写入v1.9与同步上位恢复入口；没有替代理解不明的planned结果，也没有把代表性GREEN扩大为资格化声明。

## 3. 关键架构裁决

### 3.1 Authority 与 mutation receipt 分离

Authority exact字段保持15个；`mutation_recipe_id`只属于外层receipt。planned记录不保存猜测的exit、marker、artifacts或nodeid，真实节点稳定GREEN后才原子晋级。

### 3.2 EARLY 不生成伪 Gate

4097 cases在collection阶段以pytest exit4结束，pytest-cov没有生成coverage raw/JSON。runner因此只保留7件EARLY raw和runner-error v2，不构造run-manifest或Gate。外部verifier返回exit2、`SECURITY_COVERAGE_INPUT_INVALID`且无输出，用来证明不完整raw不能升级为Gate。

`expected_gate_failures=null`表示Gate不存在；`[]`只表示Gate实际执行并PASS。二者不可互换。

### 3.3 runner error schema v2

runner-error v2精确保存stage、reason、pytest/environment/command exits、qualification、present/missing artifacts和present hashes。B3e plugin import/identity conflict兼容场景已经通过，EARLY扩展没有静默改变既有错误路径。

### 3.4 Verifier 不派生无意义双报

永久temp-unlink导致events final与PID temp同inode、`nlink=2`。bounded read拒绝该events后，verifier不得再用替代空bytes派生 `EVIDENCE_BINDING_INVALID`。最终Gate只保留有独立语义的 `COMMAND_FAILED, PYTEST_EVENTS_INVALID`；外部replay与runner Gate一致。

### 3.5 测试注入边界

Harness复制隔离仓库并对目标文件做target-conditional mutation；所有被改文件保存base/mutated hash。每次只故障一个lane，另一lane完整PASS。PID temp按受控子进程PID精确推导，不使用glob。产品runner不暴露测试专用seam。

## 4. 已验证证据

| 证据 | 结果 | 路径 |
|---|---|---|
| 最终代表checkpoint | `19 passed in 60.06s` | `/private/tmp/ai-auto-lrc-s18-b3f-final-checkpoint.pw2ENR/run.log` |
| link failure双lane | `2 passed in 9.62s` | `/private/tmp/ai-auto-lrc-s18-b3f-link-pair.LxLsmX/run.log` |
| temp unlink修复后双lane | `2 passed in 9.51s` | `/private/tmp/ai-auto-lrc-s18-b3f-temp-verifier-fix.9ZVtiC/run.log` |
| cases plus one EARLY双lane | `2 passed in 9.70s` | `/private/tmp/ai-auto-lrc-s18-b3f-cases-plus-one-green.Beq4ca/run.log` |
| runner-error v2 B3e兼容 | `2 passed` | `/private/tmp/ai-auto-lrc-s18-runner-error-v2.E3PEXK` |
| QA authority/collection | `4 passed in 0.13s` | QA只读终审 |
| v1.9 docs links与Spec Inventory | `42 passed in 8.83s` | `/private/tmp/ai-auto-lrc-v19-docs.gtblzE`；JUnit SHA-256 `6dfb13623fd74c6846a4455a37b2b3c07c3a75557e50f1f0c010d8dd8b6e6887` |

最终代码与authority SHA-256：

```text
policy     c7e02af2303a1ada48590493abfc605737c3185327aeec1eceb19eb5355a39cd
events     aa44ed1307b221c3cdd538e31942a0005abf399f3ff76a1b3a0e042454c91ef6
runner     ba633df67a85b2854a82e41fdb607bed6dd652bd0dbfd3c8788eb45a01972bb8
verifier   354db6f314a75b3468ebb76ceface16a5f8a990a3fc24a3533a8e08fbecaf074
tests      690169df567d1db212157235e8f6cd6063093a0025efa3ef422f3149c3cb197e
authority  de990f4e997eb4f6872306d8c65058ca7a15136886ac5e8137985f8aaa6628b5
```

旧RED、zsh glob runner error、temp-unlink三项Gate旧attempt和全部retry继续保留；不能删除或重写为GREEN。

## 5. 后续执行与测试用例

剩余57条按主方案第22.7节执行：configure invalid/duplicate 18条、nodeid 6条、serialized 4条、pre-publication I/O 14条、preexisting/race 6条、post-publication 6条、syscall order 2条、existing attempt 1条。

每个target-specific测试必须同时断言command argv、pytest/outer exit、marker次数、Gate存在性与有序failure、artifact exact set、final/temp/sentinel状态、所有mutation和artifact hashes、控制lane PASS、producer-external replay。EARLY场景改为断言external verifier INPUT_INVALID/no output。

每批结束先执行authority/collection轻量门，再执行该批真实双lane；后续批次修改test bytes会把早期证据历史化，因此最后必须在同一冻结hash下fresh replay全部67条并完成完整contract/docs/inventory/static检查。

## 6. 声明和授权边界

当前最大声明仅是10条代表性real-runner records完成host contract、57条planned。不得声称B3f-L完成、真实8 MiB或nodeid边界闭合、pytest全进程资源有界、B3f-R完成、Linux或双平台qualification、ABA-safe、immutable snapshot、transactional或power-loss durable。

S18、W1b-5b、Release继续No-go；W1b-5c/5d/5e未授权。未执行commit、push、CI、upload/sync、签名、发布、archive、restore、delete或destruction。
