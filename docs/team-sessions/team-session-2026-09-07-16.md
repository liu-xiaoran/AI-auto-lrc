# S18 P1 B3f L Batch H Teams 验收记录

日期：2026-09-07

模式：Teams 单实现角色 架构只读裁决 QA独立递归身份审计 主任务文档治理

权威方案：[`../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第30节`S18-P1-PLAN-v1.17`

## 1. 结论

`B3F-L-012-existing-attempt:runner` 已完成真实runner输入合同并通过独立QA，authority原子晋级为67 implemented/0 planned/67。该记录只证明当前冻结runner在已存在absolute attempt root上于pytest启动链之前拒绝，并保持递归目录端点状态不变；它没有pytest exit、Gate、producer marker、capture/retention双lane或external replay。

Batch H单条GREEN不等于B3f-L闭合。下一步仍必须在同一最终测试hash下，从fresh roots collect并一次性replay全部67条，不得拼接Batch A-H历史证据。

## 2. 架构裁决与可执行合同

直接调用当前工作树真实`scripts/run_security_coverage.sh`，不复制仓库、不修改runner/plugin/verifier、不使用fake uv完成执行，也不套用Batch D-G writer mutation helper。输入fixture位于fresh external execution root下的既存`attempt-001`，包含root/嵌套目录、普通文本、空文件、含NUL的二进制、nlink=2硬链接对和relative symlink。

before/after清单从`.`开始，按POSIX relative path bytes排序，使用`lstat()`且不跟随symlink；每项记录path、type、mode、dev、ino、nlink、size、regular content SHA-256、symlink target及其SHA-256。清单canonical JSON带单尾换行并绑定hash，receipt/stdout/stderr/tripwire全部位于attempt外。

真实调用的精确oracle为：

```text
outer exit = 2
stdout = b""
stderr = b"SECURITY_COVERAGE_RUNNER_INPUT_INVALID\n"
```

PATH只前置一个外部`uv` tripwire；若pytest启动链触发uv，它会写外部marker并以97退出。本次marker不存在。该动态证据必须与冻结runner hash及静态guard顺序合并解释，不能单独提升为通用进程监控保证。

## 3. RED GREEN与独立QA

TDD RED在authority仍为66/1/67时建立，且没有启动runner：

```text
/private/tmp/ai-auto-lrc-batch-h-red.j7oLuZ
unsupported B3f runner recipe: existing-attempt; recursive receipt unavailable
```

首次GREEN候选`/private/tmp/ai-auto-lrc-s18-b3f-existing-attempt-pql1ihg9`因错误冻结symlink mode为0777而失败；macOS实际为0755。修正为记录真实mode并验证before/after逐字段相等，没有弱化递归身份合同。一次附加审计还因错误读取Batch G copied root中不存在的contract文件而`FileNotFoundError`；随后用当前冻结hash和diff check重跑实质审计，没有伪造历史diff。

实现证据：

```text
root    /private/tmp/ai-auto-lrc-s18-b3f-existing-attempt-l2y9oi53
bundle  /private/tmp/ai-auto-lrc-batch-h-final.MgnpVI
```

独立QA：

| 验证 | 结果 | 证据/hash |
|---|---|---|
| authority / collection | `4 passed in 0.43s` | `lightweight.junit.xml` `5dd18dbd3a9c18bc231b1b5fc77b83609bb48487270629bff8f70d5f322abacd` |
| fresh exact 1 | `1 passed in 0.05s` | JUnit `ed15fa0eab1c334b42c02c800597b567fdefe38002c73c4d9900f4aa45d36b75`；log `3047bfb011884c22cbef095e577e5838c337dbd031de34d11b2f060f83b0ec11` |
| independent audit | PASS | `abf194b862f823291c6f24ad6e2a4aba613092e110860d8b6b3fe30e1ef09731` |
| fresh root | 8-entry tree闭合 | `/private/tmp/ai-auto-lrc-s18-b3f-existing-attempt-ykhuwhvt`；manifest `3481fda2323c34bef41fc67e5acefffa7cec724712ea6d6edbe9105e2ad50f8f` |
| QA root | 保留 | `/private/tmp/ai-auto-lrc-batch-h-qa.PsvXoo` |

QA独立重算runner顺序、结果bytes、8项递归清单、root身份、hardlink、symlink、tripwire和authority canonical bytes。一次checksum-only命令最后参数误写为`/privatelk?`，部分成功后报错；正确只读重试取得全部校验和，该错误保留且不算合同RED。

## 4. 冻结状态与声明边界

```text
policy     c7e02af2303a1ada48590493abfc605737c3185327aeec1eceb19eb5355a39cd
events     aa44ed1307b221c3cdd538e31942a0005abf399f3ff76a1b3a0e042454c91ef6
runner     ba633df67a85b2854a82e41fdb607bed6dd652bd0dbfd3c8788eb45a01972bb8
verifier   354db6f314a75b3468ebb76ceface16a5f8a990a3fc24a3533a8e08fbecaf074
tests      915fbaaed6ca151c3b2b00a6983f081c1ea65cc4fc029b66b997cde82270ad07
authority  68871f33db9c20c0aa5e676e31a82f894c0133d13ff03eb7105366169dd43a44
authority  56,657 bytes
count      67 implemented / 0 planned / 67 total
```

证据证明调用前后递归端点状态相同，不证明过程中不存在写入后恢复的ABA；也只证明当前host、当前继承环境下的调用，不证明恶意`BASH_ENV`或exported shell function等任意父环境。有限`generated_artifacts`枚举不是“不新增”的主证据，完整recursive manifest差集才是。

## 5. 最终67条执行门

执行前必须同时冻结policy、events plugin、runner、verifier、tests和67-record canonical authority，并保存exact 67 collected nodeids及双向相等结果；另记录manifest、bootstrap、pyproject、uv.lock、capture/retention source与test哈希。确认无其他pytest/runner后，只允许从fresh exclusive roots一次性replay 67条。

最终replay必须验证：其余66条保持target/control结构和FULL/NO_EVENTS/EARLY分类；所有存在Gate的lane都由external verifier重放且与runner Gate一致；唯一runner节点不生成capture/retention、pytest exit或Gate；B3e七个implemented场景和13个platform planned场景不缩水；P1 inventory与产品计划不得因B3f authority自动晋级。任一冻结对象漂移都使本轮历史化并要求完整重跑。

B3f-L、S18、W1b-5b和Release在最终67条replay前继续No-go；B3f-R、final-schema replay、hostile matrix、B4及平台qualification均未由Batch H代签。W1b-5c/5d/5e继续不执行。
