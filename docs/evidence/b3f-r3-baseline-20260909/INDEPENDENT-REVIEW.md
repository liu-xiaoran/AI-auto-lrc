# R3 正常 macOS 对照：独立源码与原始产物审阅

日期：2026-09-09。审阅角色：`/root/r2_independent_qa`。

**限定结论：最终正常 macOS baseline 的源码与原始证据审阅通过；本切片未发现未解决的 P0/P1。** 本角色独立阅读最终源码、重算原始产物绑定并核验 JUnit/事件记录，**未独立重跑 pytest、runner 或 verifier**。执行来自主代理，本报告不能改称独立重跑或完整 R3 验收。

## 范围与快照

最终入口为 `tests/system/security_runtime_r3_baseline.py` 与 `tests/system/test_security_runtime_identity_r3.py`：

```text
d7c440a5f73308cbcba545eddf72892e7953ae53765f10086d2e026923a46409  tests/system/security_runtime_r3_baseline.py
ca39945175c8d4376cd91311d4f00e4430aad31ac36d41cffad8d5ebc1533060  tests/system/test_security_runtime_identity_r3.py
```

两文件当前 hash 与此前独立静态审阅一致，并与本次 before/after 快照中的记录相同。harness 没有替换原始 runner、bootstrap、verifier、两 lane 测试或 policy。迁至 system 后，固定选择 unit/contract/component 的 portable 层不再收集这两个 macOS 专用节点；但 pyproject 默认 testpaths 仍为 tests，无路径 pytest 仍可能收集 system，不能宣称技术上“仅显式执行”。

正常对照根：`/private/tmp/lrc-r3-verified-20260909/test_s18_b3f_r3_real_dual_lane0`。

外层 JUnit：`/private/tmp/lrc-r3-verified-20260909.junit.xml`，SHA-256 为 `a7fcc73d4b48e892fa2e221c49d2362bcecc249c8c4e88ae362cacae8198bf77`。直接解析为 2 testcases，failure/error/skipped 均 0，suite time 180.368s；其中长路径 probe 1.075s、真实双 lane 节点 179.282s。

## 隔离、命令与前后绑定

`runner.argv.json` 实际启动 `/usr/bin/sandbox-exec -f <本根>/isolation.sb <原仓库>/scripts/run_security_coverage.sh <本根>/attempt s18-r3-baseline 1`。`runner.exit.json` 和 `isolation-probe.exit.json` 均为 returncode 0、timed_out false。

profile 保留 deny network*，仅允许本次 canonical 证据根内的 network-bind，没有 network-inbound/outbound 例外。probe 实际结果为 IP connect 拒绝、IP bind 拒绝、证据根内 Unix socket bind 成功，三个文件写打开端点均拒绝。准确语义是 **IP 网络拒绝，允许证据根内 Unix socket bind**。

写保护覆盖 checkout、真实 Python base_prefix `/Users/liu-haixiao/.pyenv/versions/3.11.4` 及 canonical uv `/opt/homebrew/Cellar/uv/0.12.9/bin/uv`。私有 HOME/cache/TMPDIR 均在证据根。lane command 保留 `run --offline --frozen --no-sync python -I -S -B`、真实 bootstrap、原测试文件、严格 xfail 及原 80% 阈值。

长路径 probe 的实际绝对 socket 路径为 182 bytes，其原始 stdout 证明 local_socket_bound=true、IP connect/bind 拒绝及三写拒绝。源码在 probe 子进程切换到私有 TMPDIR 后 bind 短相对名，未扩大 sandbox 范围。

`before.json` 与 `after.json` 各 8,248,566 bytes、23,957 条记录，独立读取确认逐字节相同；SHA-256 均为 `e914a63bd7185fc9879adb1acc746c3b9c846f4f6a380791d10c5ea07ec41db3`，与 receipt 一致。内容覆盖输入文件、完整 .venv 清单、uv 和真实 Python endpoint 的 hash/inode/mode/size/mtime/symlink。profile 实算 SHA 为 `74ef7d257f1bdedfddc3d596e97998d55de33066a72b1107a4803b7a081690d0`，也与 receipt 一致。前后观测不排除 ABA。

## 原始结果与独立交叉核验

| 对象 | capture | retention |
| --- | --- | --- |
| command exit | 0 | 0 |
| 原始 JUnit | 282 passed，0 skipped，67.294s | 257 passed，1 skipped，106.638s |
| macOS required | 24/24 passed | 15/15 passed |
| Gate | schema5，passed=true，failures=[] | schema5，passed=true，failures=[] |
| combined coverage | 89.21706516643225% | 93.67850692354004% |
| statement coverage | 91.12741827885257% | 95.04396482813749% |
| branch coverage | 84.70031545741325% | 89.51219512195122% |
| critical targets | 全部 100% line/branch | 全部 100% line/branch |
| Gate SHA-256 | `886831e7d262f61e3635e4b1107b7282504a2ed9b525cf9b34f49b6207285d6c` | `e0fbb23e8dfd79d950a4dc074fe2f910cf73d1ccb0e4b270046ffafbbc99ab54` |
| JUnit SHA-256 | `04ca7d6a13a9e0dc6b983395ccd6e093f6df6a341aecdc4a1f5e7f11e50e6f11` | `fb16ff148d5345d7bb25eb931e25edffb94f06f8628bb13ad3f5b8b72803ad0f` |

每 lane 的 16 项 artifact 绑定均通过独立读取实际文件、重算 SHA 与 run-manifest/Gate 对齐。生产输入 hash 同时与 before 快照及当前文件相同。environment 的 source/test/policy/manifest/runner/verifier/bootstrap/pytest_config/events plugin/uv.lock/uv 前后值分别一致。

两 lane 的版本为 identity2、environment5、command4、manifest5、events3、Gate5，均为精确整数；scope 为本 run_id、对应 target、macos、attempt1，identity timestamp 与 command.started_at 相同。identity 文件均 mode0600。两份 raw coverage 数据库路径正确、SQLite header 有效，大小分别 147456/122880 bytes。

本角色没有调用 producer/consumer 重算 semantic，而是直接按冻结规则移除 semantic_runtime_sha256、将 scope 归为 runner，计算 canonical JSON SHA。两个 identity 分别重算为：

```text
959272d6d18c4600127c20b2fde8aca347360badf67fc820f1157615af4eb7d5
```

此值与两 lane 的 identity/environment/manifest/Gate 全部一致。uv path/SHA 同时绑定 command 首 token、真实 endpoint 当前 bytes、before 快照及 environment 前后值。runtime 为本机 Darwin arm64、CPython3.11.4、uv0.12.9，不代表其他主机或 Linux。

从 security manifest 独立提取 macOS required 节点后，逐项核对原始 JUnit 成功状态，确认 capture24、retention15 全部 passed、没有 required skip。完整 JUnit 节点集合与 events 集合一致，没有 failure/error/xfail。retention 唯一 skip 为 `test_ret_s17_linux_block_and_char_devices_fail_before_control_write`，原因 `requires Linux mknod device semantics`，与 manifest 的 macOS platform_exclusions 精确匹配；不能将 257+1 写为 258 passed。

一次审阅辅助脚本在遍历 skipped 用例的 null call phase 时发生 TypeError；发生于只读 JSON 核对，未执行产品或测试、未写报告。之后按 events 合同区分未执行的 null phase，再完成两 lane 的集合/skip/xfail 核对；不是产品回归或 pytest 失败。

## 保留的限制

两 lane 的 stderr.log 均包含 coverage 的 `module-not-measured` 警告，分别指向预先导入的 capture/retention 模块；不能写为 stderr 空。两份 verifier.stderr.log 为空，真实 Gate 按原阈值和 critical-target 规则通过；不据此声称所有 import 阶段行均已测量。

此前 harness 的 Unix socket 误拒绝、coverage 文件名 oracle、长路径 probe 缺陷及取消运行由主代理保留为历史，不被本次通过覆盖。这里只审阅最终快照，不把历史 harness 失败改称产品回归。

当前仅完成正常 macOS 双 lane 与同 host semantic 一致性。敌意 PATH/endpoint/lock/flags/.pth 矩阵、disposable runtime 前置条件、R4、final-schema replay、Linux/双平台资格、冷安装、恢复与 Release 均未在本审阅中执行或获得资格。整体 R3/Release 不能据此宣布完成。主代理仍须完成本轮最终文档治理。

本角色本轮未执行 pytest/runner/verifier、未修改产品或测试；唯一写入为本独立审阅报告。执行锁始终归主代理。

## 后续 marker 治理修正的独立只读复审

主代理最终文档治理暴露同名目录规则的集成缺口。独立回读 `/private/tmp/lrc-r3-spec-final-20260909.junit.xml`：41 testcases、1 failure、0 errors/skipped，唯一失败为 `test_every_declared_marker_selects_collected_tests`。新建 tests/system 触发原“marker 必须恰好等于同名目录”分支，导致原已位于 retention 合同文件的 system 节点被误判 outside；这是治理规则与已有跨目录标签语义冲突。

独立静态复审确认本次最小修正合理：仅 system 分支改为 `expected <= selected`，要求 system 目录所有节点均带该标签，同时允许已有 retention 节点保留 system；全局 selected 非空与 selected <= all_nodes 不变，component/golden/package 的目录精确相等规则不变。pyproject 原声明明确 system 是 POSIX process/signal/filesystem 能力标签，已有 retention 测试的该标签也确实早已存在，未通过移除标签、放宽产品 inventory 或修改 portable 范围规避失败。此差异未发现 P0/P1。

审阅时 `tests/contract/test_spec_inventory.py` SHA-256 为 `80eee78ab7a540f5542b30ca2f935d2b9c89d0922c51ceaf9ffd5df90e7ef7d8`；前述两个 baseline 文件 hash 再次确认未变，本追加不改写原始 baseline 快照和执行结论。治理修正的动态复验由主代理持锁执行，本角色未重跑；此处仅记录独立代码及原始 RED 产物审阅。
