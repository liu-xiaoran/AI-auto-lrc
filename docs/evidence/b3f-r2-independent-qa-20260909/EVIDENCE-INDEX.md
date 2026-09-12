# R2 独立验收证据索引 — 2026-09-09

结论：**ACCEPTED，仅限定 R2 冻结合同范围**。独立角色 `/root/r2_independent_qa` 未参与这九文件的实现或修复；本轮只读审查和全新回归完成。P0 0 / P1 0；本范围未发现未解决的阻断缺陷。历史独立 QA 中止不计为通过，本报告只使用本次产生的证据。

## 冻结范围与执行所有权

权威合同：[S18 P1 执行方案](../../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)，第36.1–36.8、36.13–36.17、36.21、36.34、36.37–36.40及补强 oracle。入口指导为根目录 CLAUDE.md。

[新九文件清单](../b3f-r2-recursion-implementation/nine-files.sha256) 已在本轮执行前校验9/9 OK。全新证据根：`/private/tmp/ai-auto-lrc-r2-independent-qa-20260909.hood4qvn`。`before.sha256` / `after.sha256` 逐字节相等，均绑定上述冻结清单；无产品或测试代码修改。执行前、执行组之间及最终未见其他 pytest/runner 进程。主代理保持不测试、不修改九文件，两个正式组串行执行。

执行前按已批准清单逐项 collect：

- [47个确切节点](../b3f-r2-root-review/47-nodeids.txt)：R2 exact15 + affected32，collect实际顺序与清单完全相同。
- [35个确切节点](../b3f-r2-root-review/35-nodeids.txt)：R1a10 + R1b15 + legacy10，collect实际顺序与清单完全相同。

## 新执行结果

| 组 | 本次结果 | JUnit SHA-256 |
| --- | --- | --- |
| 47节点，同进程 | 47 passed in 79.49s，exit0，stderr空；failure/error/skipped均0 | `857c6340388df1f7d546f78eb8d768b6ca4a437be03ecf0944b97663b5bf20db` |
| 35节点，同进程 | 35 passed in 1.03s，exit0，stderr空；failure/error/skipped均0 | `583d00a57adbb6905ad8149fc9e5f2c6403ce56842769113ebf72c1b4d66ee94` |

两组共82次节点执行，**79个唯一节点**。三项重叠为 `test_s18_plugin_identity_record_field_is_only_the_plugin_record_entry_digest`、`test_s18_b3f_r1b_loader_failure_path_is_statically_terminal`、`test_s18_b3f_r1b_loader_failure_exits_without_publish_or_pytest`。

完整命令保存在 `47.argv.json` / `35.argv.json`，collect命令另存对应 `*-collect.argv.json`。共同入口为 `uv run --offline --frozen --no-sync python -m pytest -q -p no:cacheprovider`，节点逐项作为独立argv传入。正式组各使用从未存在过的 `pytest-47` / `pytest-35` basetemp和独立JUnit。各组均保存stdout、stderr、真实exit、elapsed；没有重启、追加整文件选择、安装、依赖同步、联网或工具修改。本轮工具执行未被拒绝。

## 独立源码及 oracle 审查

九文件的R2生产路径、测试夹具和本轮补强已结合实际源码审阅；不以节点全绿或源码子串单独代替合同验收。

| 合同 | 本轮审阅与动态证据 |
| --- | --- |
| 深层JSON连续性 | runner environment/manifest的两个strict JSON候选提取分支捕获RecursionError；raw SHA在提取前建立，拒绝后semantic/tools保持null。consumer core捕获RuntimeError覆盖RecursionError。永久profile节点同时含同形有限正例、2000层深例、nested duplicate、NaN/Infinity/-Infinity，没有扩大recursionlimit或容量上限。 |
| harness执行边界 | fake uv精确识别prefix及program；bootstrap路径始终进入stub并终止，未知program最终exit97。仅显式指定的copied verifier分支exec真实consumer，embedded Python为复制runner的helper；没有真实uv回落。所有日志汇总：bootstrap-stub38、verifier-real8、verifier-stub26、预期blocked-program1，invalid-prefix/poison均0。主动未知program用例断言exit97、stdout/stderr空、marker未生成；不是只检查分类源码。 |
| stub产物归属 | stub-success写入exact标记，永久测试断言 `harness_stub=true` 与 `not_verification_evidence=true`。本轮回读deep stub两lane Gate，完整值仅两标记与target；这些回执不计consumer验证证据。 |
| Prepared捕获与发布 | main唯一prepare→local events读取加载→builder→guard。真实隔离subprocess执行original prepare及local events，再将capture/read入口设tripwire；真实builder与exclusive writer发布，pytest.main在prepare返回后拦截。动态计数prepare/local_events/events_reads/builder/pytest_main/writer均1。此为连续发布合同，未运行真实安全测试。 |
| 私有事实与分类并集 | consumer将公开invalid summary与内部uv/semantic/distribution facts分离；scope失败不吞独立事实、失败distribution不伪造version fact。PLUGIN+TOOLCHAIN使用before=after且同时偏离identity/live的SHA；CONFIG+TOOLCHAIN保留option位置而改后半flag；malformed observation只CONFIG；同内容不同uv path为TOOLCHAIN。各用精确sorted unique集合断言。 |
| 单读复用 | cov live entry捕获写入独立cache早于entry/lock后续语义失败，plugin分支复用捕获bytes。有效、entry绑定失败、晚期lock失败三个动态分支均cov读取一次；早期coverage失败不跳过后续distribution/plugin验证。 |
| read/null与边界 | sidecar mode由同fd fstat绑定并闭合pathname观测。完整读后换inode、改mode、pathname消失保留raw SHA并无效化；missing/unreadable/oversize为null，空文件为真实empty SHA；真实Gate顶层和nested raw一致，invalid summary使用独立literal oracle。identity合法4MiB与四nested cap exact/+1通过合法字段/摘要重绑区分语义门和读取门。 |
| schema与跨产物绑定 | policy3/identity2/environment5/command4/manifest5/Gate5的exact shape、float/bool/旧版本/unknown/missing/duplicate用动态输入拒绝；baseline full verify通过后再单独漂移manifest/environment semantic/raw引用，精确TOOLCHAIN。Gate顶层14字段及nested固定集合有完整断言。 |
| 单次uv解析及preflight | shell existing/dangling root检查在工具解析前；uv alias有16-hop/cycle/control界限，bounded hash与version A/version/B先于root创建；后续统一绝对prefix。input验证ENOENT/ENOTDIR为INPUT，EACCES/EIO与mkdir EACCES/ENOSPC为CONFIG，stderr固定且不泄漏。只使用受控临时副本动态验证。 |
| R1b及primitive回归 | 35节点覆盖当前schema下的layout/loader/RECORD/lock/builder/guard/exclusive writer；成功probe的fake pytest不混称真实pytest/security lane。 |

## 原始产物回读

`artifact-review.json` 保存JUnit解析、去重集合、deep profile两lane字段及产物SHA、全部harness调用种类和Prepared输出事实。该文件是只读产物核对摘要，不是额外pytest或新的产品probe。

深例原始identity共4256 bytes，SHA-256：`5bdc6e2a852b21401512062716297d5ef75e65fc837fe17e4220937f9b5eb02a`。实际文件位于 `pytest-47/test_s18_b3f_r2_artifact_profi0/deep-identity-real/security-runtime-r2-runner-harness/run-1/artifacts/`：

- capture与retention真实copied consumer Gate均passed=false，failures精确为 `RUNTIME_IDENTITY_INVALID`。
- 两Gate顶层plugin_identity SHA与nested artifact SHA均等于输入；runtime schema/provenance/semantic/runtime/uv/uv_lock均null、distributions/plugins为空。
- 两environment的raw SHA保留，semantic及coverage/pytest/uv均null；两manifest semantic均null。
- deep real日志为bootstrap-stub2、verifier-real2、environment-helper2；没有真正执行security bootstrap。永久节点确认runner stdout/stderr无Traceback。

真实Prepared文件为 `pytest-47/test_s18_b3f_r2_prepared_runti0/real-prepared-publication.json`：202292 bytes，schema2，mode0600，nlink1，SHA-256 `dde044d56f0305dbe5406118193bf63614e811c91fc98cdf29130c48099c90a5`。其真实capture/writer计数由冻结永久测试断言，原文件已回读确认。

`evidence-checksums.sha256` 索引57份原始/核对文件，包括各组命令、输出、exit、JUnit、前后hash、process gate、deep两profile的关键产物与日志及Prepared文件。可在上述证据根执行 `shasum -a 256 -c evidence-checksums.sha256` 复核。原始临时目录可能被系统清理；本索引不是原始日志的永久归档，目录丢失后不得仅凭索引hash复用通过结论。

## 风险、边界与交锁

R2当前冻结合同的独立验收完成，深层JSON连续性P1在本快照独立关闭。本次没有执行整个coverage gate文件、真实capture/retention安全双lane、final67、R3、R4或平台矩阵，也不证明Linux、wheel冷安装、供应链真实性、端点ABA防护、恢复演练或生产发布资格。Ruff format历史差异仍单列，本轮未做format或重跑其检查。

后续必须由主代理核验本索引与原始证据，再fresh执行文档治理门后追加正式R2入口；R3正常真实双lane、敌意集成、R4与final-schema replay等独立门不能省略。S18、W1b-5b、Release整体No-go及inventory资格状态不因本R2验收自动晋级。

本QA已停写产品/测试、**停止全部pytest/runner执行并释放唯一执行权给主代理**。`final-process-gate.json`记录pgrep退出1、stdout/stderr空，未见遗留pytest/runner。唯一仓库写入为本证据索引。
