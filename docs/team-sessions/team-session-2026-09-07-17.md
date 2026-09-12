# S18 P1 B3f L Final 67 Teams 验收记录

日期：2026-09-07

模式：Teams 单执行角色 单次同hash replay QA独立132 lane重放 架构B3f R预审 主任务文档治理

权威方案：[`../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第31节`S18-P1-PLAN-v1.18`

## 1. 结论

B3f-L已在同一最终测试与authority hash下完成exact 67 nodeid的单次fresh replay，并通过独立QA。Host contract允许新增的最大声明是：pytest events producer在policy声明的case、nodeid、serialized artifact与writer fault边界内fail closed。该结论不扩展到pytest全进程资源有界、B3f-R runtime provenance、平台qualification或Release。

下一阶段只能进入B3f-R Batch R0低成本合同RED；B3f-R修改runner/bootstrap/verifier/policy后，本次B3f-L证据将成为历史记录，最终schema下仍需重新生成对应closure。

## 2. Final 67执行证据

执行包：`/private/tmp/ai-auto-lrc-b3f-l-final-67.XHtcj7pg`

```text
single pytest invocation  exit 0  elapsed 170s
JUnit                     67 cases 0 failure/error/skip
limits / writer / runner  32 / 34 / 1
capture/retention/runner  33 / 33 / 1
tests                     915fbaaed6ca151c3b2b00a6983f081c1ea65cc4fc029b66b997cde82270ad07
authority                 68871f33db9c20c0aa5e676e31a82f894c0133d13ff03eb7105366169dd43a44
authority bytes           56,657
```

| Artifact | SHA-256 |
|---|---|
| `final.junit.xml` | `04b5e5d28b3c463129889e6019cb5a918c2649b06f94b0ba97b309f451b3fd10` |
| `final.stdout` | `dc7e1ac0aa2dc475107c15b0d9b45fa8d7c73a86831f22110a1fe9148ccde127` |
| `final.stderr` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `final-evidence-roots.txt` | `d5abc33acfc6c083bd3049814c81ec781646c1cdae270e83a3400f3b9ac0322b` |
| `independent-summary.json` | `4cc3da7dc3d5fdc5625c4a4ef594eddaaabec2eddc80a92afed836f7a12683dd` |
| `bundle-files.sha256` | `87cabccc972a8fa29e0de59dcb7176228fb825de886e35bcab1e45bed3cd78ef` |

Start/pre-run/end共14项冻结对象逐字节一致；normalized freeze SHA-256均为`53d70de8d11e8b6199effd99f44cc92edba33ba76fd98115851b9a342b9b0654`。Git status本来非clean，起止快照相同且SHA-256均为`52fa87daa2207dda8eb208db55e641628c3c4cf7571b1caa8f99aa52046d5b90`，没有把clean当成通过前提。

## 3. 独立QA

QA root：`/private/tmp/ai-auto-lrc-b3f-l-final-67-qa.eyNvS9BD`

QA没有重跑高成本67，而是独立解析单一JUnit、fresh roots时间窗、authority和freeze，并对132 lanes逐一重算：

- 67个formal nodeid exact unique，与authority顺序及双向集合相等；
- 67个fresh roots全部在单次final窗口内生成，与Batch A-H旧roots交集为0；
- 66个nonrunner roots形成132 lanes，独立重哈希1422 artifacts；
- 106个gate-present lanes经独立verifier replay得到相同return和逐字节Gate；
- 26个gate-absent lanes均return2、stdout空、stderr精确`SECURITY_COVERAGE_INPUT_INVALID\n`且不生成Gate；
- 66个sentinel closure、56个producer marker、32个limit receipt、34个writer receipt通过；
- runner-only root无lane/pytest/Gate，tripwire未触发，8-entry no-follow tree before/after相同。

Artifact profile精确计数：FULL 86、NO_EVENTS 16、EARLY 6、EARLY_CONFIGURE 18、EARLY_CONFIGURE_PLUS_EVENTS 2、FULL_PLUS_TEMP 2、NO_EVENTS_PLUS_TEMP 2。

| QA artifact | SHA-256 |
|---|---|
| `independent-audit.json` | `5065f14a87f530016f6d318cc737cd0838c287a7f5b133f26282dab9144434e6` |
| `lightweight.junit.xml` | `6f0a237a41f5f256485e038afa3138a43bbd877ddedd6d6867fe4687d96b90a9` |
| `doc-links.junit.xml` | `fddd475f2adfdce446fdad1fec8beebff8e3ea5c96b6515050698f2fc281e27e` |
| `qa-artifact-hashes.json` | `91fe63dcd0d7a0d22106634ea249017217e5a9bed0b31e6e1e6dda6b7b28c3b7` |

QA脚本最终PASS前有6次非契约失败，分为4类：临时脚本缺repo import path、误把collect耗时0.02s冻结为0.03s、把合法60/240秒deadline简化为一个值、把受保护或故意无效events强制当JSON解析。所有旧脚本与部分replay目录保留；只修改外部QA脚本，没有修改仓库或原证据。

## 4. 状态隔离

B3e仍为7 implemented/13 platform planned；Spec Inventory仍为274项；S18 P1仍为7 specs、5 implemented/2 planned、verification unverified、qualification unqualified。B3f-L closure不自动修改任何产品、P1、macOS/Linux、package、canonical、host或sealed状态。

## 5. B3f R0唯一下一批

架构预审已证明当前host上`uv run --offline --frozen --no-sync python -I -S -B`可启动；初始sys.path不含site-packages，但可以从未resolve的`.venv/bin/python3`、bounded `pyvenv.cfg`推导唯一versioned site-packages，并在不调用`site.addsitedir`、不执行`.pth/sitecustomize`的情况下append后加载`pluggy -> coverage -> pytest -> pytest_cov -> pytest_cov.plugin`。也已用stable bytes `compile/exec`验证依赖顺序可行。

R0只添加低成本合同RED，不修改产品或运行真实security runner。测试覆盖：isolated no-site venv推导、五个required module stable-byte compile、RECORD唯一self-row例外、parent-path row只opaque捕获且永不resolve，以及policy v3 named runtime contract。

PEP 376规则必须勘误为：required/import entries禁止absolute、`.`和`..`；唯一canonical`<dist-info>/RECORD,,` self row允许hash/size同时为空；其他row必须有SHA-256与decimal size；真实RECORD里的`../../../bin/*`非required console-script row只能作为opaque bytes捕获，禁止resolve/open。若坚持全局拒绝任何`..`row，当前真实`.venv`无法满足，必须hard stop而不是修改实现掩盖。

R0 GREEN后再依次执行R1 identity producer、R2 policy/verifier/artifact schema原子迁移、R3 runner integration/真实双lane、R4 bootstrap writer parity与final-schema replay。S18、W1b-5b、Release继续No-go；W1b-5c/5d/5e不执行。
