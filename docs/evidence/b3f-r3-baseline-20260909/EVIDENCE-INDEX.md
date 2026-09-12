# R3 macOS 正常对照证据 — 2026-09-09

本次完成 R3 的正常真实双lane与同host semantic一致性切片，未完成整个R3异常矩阵。产品与阈值未修改；新增的是独立系统测试入口及其执行环境。

## 最终实现与入口

- [系统测试](../../../tests/system/test_security_runtime_identity_r3.py)：长路径前置probe、真实双lane及跨产物绑定。
- [执行环境](../../../tests/system/security_runtime_r3_baseline.py)：系统沙箱、私有HOME/cache/TMPDIR、进程回收、原始证据与前后完整清单。
- helper SHA-256：`d7c440a5f73308cbcba545eddf72892e7953ae53765f10086d2e026923a46409`。
- test SHA-256：`ca39945175c8d4376cd91311d4f00e4430aad31ac36d41cffad8d5ebc1533060`。

新增节点位于tests/system，原portable层固定选择unit/contract/component，不会收集这两个macOS节点；无路径pytest仍会按testpaths发现它们。当前宿主为macOS arm64、CPython3.11.4，运行环境合同仍为installed-record-consistent，不是供应链认证。

```sh
PYTHONDONTWRITEBYTECODE=1 uv run --offline --frozen --no-sync python -m pytest \
  tests/system/test_security_runtime_identity_r3.py -q -p no:cacheprovider \
  --basetemp=/private/tmp/lrc-r3-verified-20260909 \
  --junitxml=/private/tmp/lrc-r3-verified-20260909.junit.xml
```

这是本次已执行命令；后续执行必须使用新的basetemp/JUnit路径，不能覆盖本次证据。

## 最终动态结果

外层由主代理执行，**2 passed in180.37s、exit0**。JUnit SHA-256为 `a7fcc73d4b48e892fa2e221c49d2362bcecc249c8c4e88ae362cacae8198bf77`。外层终态由工具捕获，JUnit已留存；两lane完整stdout/stderr另有原始文件。

| 真实lane | 测试 | 必需节点 | combined / line / branch | Gate |
| --- | --- | --- | --- | --- |
| capture | 282 passed in67.30s，0 skip/failure | 24/24通过 | 89.2171% / 91.1274% / 84.7003% | PASS，failures=[] |
| retention | 257 passed、1 skipped in106.64s，0 failure | 15/15通过 | 93.6785% / 95.0440% / 89.5122% | PASS，failures=[] |

retention唯一skip为Linux mknod device语义，当前macOS不适用；不称“所有测试零skip”。两lane的critical targets全部达到当前policy要求。未更改测试选择、阈值、manifest或产品runner。

identity2 / environment5 / command4 / manifest5 / Gate5 / events3齐备；两lane identity、environment、manifest、Gate的semantic均为 `959272d6d18c4600127c20b2fde8aca347360badf67fc820f1157615af4eb7d5`。原始coverage数据库分别为`.coverage-capture`与`.coverage-retention`，并保留coverage JSON、JUnit、原始日志及verifier日志。

## 隔离与前后绑定

正常对照根：`/private/tmp/lrc-r3-verified-20260909/test_s18_b3f_r3_real_dual_lane0`。

- `isolation.sb`拒绝IP网络，仅允许证据根内Unix socket bind；不开放network-outbound/inbound例外。
- 实际probe证实IP connect、IP bind被拒绝，项目配置、venv配置和uv endpoint的写打开被拒绝，同时证据根内Unix socket可创建。
- 长路径节点构造超过108-byte的绝对socket路径，再以子进程cwd+短相对名称实际bind；没有扩大沙箱权限。
- 正常对照只读复用现有runtime；不声称已满足后续会修改runtime的disposable环境前置条件。
- `before.json`与`after.json`保存当前输入文件、完整.venv目录树、uv和真实Python的内容hash、inode、mode、mtime、size、symlink。两份原始清单SHA均为 `e914a63bd7185fc9879adb1acc746c3b9c846f4f6a380791d10c5ea07ec41db3`。
- receipt SHA为 `e788305f2d0619d29ff5e85493c339c16ee761d1e5d37eb7c786588ecfcdcafc`，包含私有目录、profile摘要、前后清单摘要、probe事实和runner exit0。profile SHA为 `74ef7d257f1bdedfddc3d596e97998d55de33066a72b1107a4803b7a081690d0`。
- 同根`evidence-checksums.sha256`索引43份正常/长路径probe和两lane原始文件及外层JUnit，主代理重算43/43通过；清单SHA为`2df0db02e44b8510110d0901a564123430f464201596ffc7c32164587516ce3f`。不以索引代替原始bytes，临时目录不是永久归档。

## RED、无效尝试与修复

1. 新入口最初因helper缺失collect ERROR/exit2，这是实现前scaffold RED，不是产品缺陷。
2. `/private/tmp/ai-auto-lrc-r3-baseline-20260909-a`：外层1 failed in206.87s；capture正常PASS，retention有4个AF_UNIX fixture bind失败，Gate为COMMAND_FAILED+JUNIT_CONTAINS_FAILURE。原因是初版sandbox连本地特殊文件fixture也阻断。最小修正仅允许本次证据根内network-bind，并增加IP bind/connect拒绝与Unix bind正例。另修正新增oracle的`.coverage.{target}`拼写，保持原始runner产物名不变。
3. `/private/tmp/ai-auto-lrc-r3-baseline-20260909-b`：旧contract位置1 passed in186.01s、两Gate PASS。这是历史正常运行，不代替最终system位置快照。
4. `/private/tmp/ai-auto-lrc-r3-baseline-20260909-final`：迁移后的中间运行因进一步发现默认临时路径长度问题，由主代理SIGINT停止；外层exit2、no tests ran，runner.exit为-9/interrupted=true，确认无遗留bootstrap。该attempt不计通过。回收观察不冒充全面取消/进程树资格化。
5. 永久长路径节点在`/private/tmp/lrc-r3-long-red`实测1 failed in3.01s，probe报AF_UNIX path too long；最小修改为probe子进程chdir私有TMPDIR后bind短名称，在`/private/tmp/lrc-r3-long-green`得到1 passed in1.16s。最终同快照再运行两个system节点，结果见上。

所有失败保留；没有恢复旧GREEN、降低阈值、替换真实bootstrap或生成stub Gate。

## 审阅与剩余范围

最终文档治理发现并修正marker目录假设：system是跨目录POSIX能力标签，不能因新建tests/system就排除已有retention合同标签。原始RED为1 failed、40 passed in8.30s（`/private/tmp/lrc-r3-spec-final-20260909.junit.xml`）；仅将system目录覆盖条件改为包含，保留其他层精确相等、所有marker非空/总节点子集。随后spec41 passed in8.47s（`/private/tmp/lrc-r3-spec-green-20260909.junit.xml`），链接检查单独1 passed in0.04s（`/private/tmp/lrc-r3-doc-links-20260909.junit.xml`）。修正位于[规格治理测试](../../../tests/contract/test_spec_inventory.py)，不改baseline两文件或安全policy；它是独立的治理验证，不计入539个实际lane通过节点。三份本轮Python文件Ruff check/format与git diff check通过。

最终两文件经过独立只读源码审阅，未发现未解决P0/P1；最终原始产物的[独立复核](./INDEPENDENT-REVIEW.md)单独记录。独立审阅与独立重新执行不同，本次动态执行者是主代理。

仍待：PATH alias变更、私有uv endpoint/lock漂移、14个flags变体、`.pth`/sitecustomize、disposable runtime及对应OS隔离证明，随后R4/final-schema replay、其他平台与发布资格。S18/W1b-5b/Release继续No-go，产品inventory不晋级。未commit/push、安装/同步、上传或发布。
