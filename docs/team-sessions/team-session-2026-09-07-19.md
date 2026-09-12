# S18 P1 B3f R1a Bootstrap Primitives 与 R1b 设计 Teams 记录

日期：2026-09-07

模式：Teams 单实现角色 RED→GREEN、独立 QA、只读架构复核、主任务 append-only 文档治理

权威方案：[`../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第 33 节 `S18-P1-PLAN-v1.20`

## 1. 结论

B3f-R1a 已完成三个 bootstrap primitive 及其补充安全合同。初版实现虽然通过实现角色的 7 个定向节点，但独立 QA 发现裸 `TypeError`/`ValueError`，架构复核又发现 `pyvenv.cfg.home` 未与 executable 最终 target 绑定，因此初版不得作为无条件 GREEN。问题、旧哈希和旧证据全部保留；补充 RED 精确复现后完成最小修复，并由独立 QA 与架构角色在新哈希下复核。

最终裁决：

```text
P0                                      0
R1a scope 内未关闭 P1                   0
R1b implementation start                Go
identity v2 publish / 真实 runner         No-go
S18 / W1b-5b / Release                   No-go
W1b-5c / 5d / 5e                         未授权，不执行
```

R1a 只提供 R1b composer 可调用的 primitives；它没有发布 identity v2、没有修改 policy/verifier/runner 对外 schema，也没有证明 runtime identity 的原子快照、完整模块 rollback、Linux 或双平台 qualification。

## 2. Teams 分工与写边界

| 角色 | 职责 | 写权限 | 本轮结果 |
|---|---|---|---|
| 实现角色 `b3e_s_impl` | 测试先行实现三个 primitive；补充修复错误归一化与 home binding | 仅 `scripts/security_pytest_bootstrap.py`、`tests/contract/test_security_coverage_gate.py` | 初版 GREEN 后响应 QA P1，完成补充 RED/GREEN |
| QA 角色 `b3e_s_qa` | 独立 collect/formal、敌意输入、真实 uv probe、静态门 | 只读 | 初版给出 P1；补充修复后无 P0/P1 |
| 架构角色 `p1_inventory_design` | 审查 seam、rollback 声明、R1b API/测试门 | 只读 | 冻结 fail-stop、TOCTOU、R1b 15 项合同 |
| 主任务 | 证据汇总、边界裁决、append-only 文档治理 | 仅 `docs/` | 保留失败历史并建立 R1b 恢复入口 |

工作树原有 modified、deleted、untracked 项，包括根目录 `./=`，均不属于本轮清理范围。未执行 reset、checkout、clean、删除、commit、push、CI、上传、同步、签名、发布、archive 或 restore。

## 3. R1a 初版实现 checkpoint

初版只修改 bootstrap 与 contract test，新增：

```text
_derive_runtime_site_packages(executable, *, python_major_minor) -> Path
_load_bound_runtime_modules(entries) -> (ordered modules, ordered identities)
_parse_distribution_record(record_bytes, *, dist_info, required_paths)
    -> tuple[normalized rows]
```

初版实现角色证据根：

```text
/private/tmp/ai-auto-lrc-b3f-r1a.y8GspEqC
```

结果：

```text
R0 baseline                     4 expected failures
refined RED                     3 expected failures
R1a exact-7                     7 passed
legacy bootstrap selection      10 passed
policy-v3                       1 expected failure
```

旧文件哈希：

```text
scripts/security_pytest_bootstrap.py
9f3a6e0136ad5c0ad1595738fe193fcaa7233e52b58a163c555de8d606cbe7a5

tests/contract/test_security_coverage_gate.py
30ca83b76a0928d3bdedea8cdf1b7be073c8582c115bd76cdae265847105f324
```

关键证据：

```text
green1.junit.xml
97eee72cd8e4bd6c9fd537d4a80142aecb6f9bbccf65188d164d78ffe532d50f

legacy-bootstrap.junit.xml
9e64486aea31e40460fcc20da27fb0960c77a1a6553703e3d847ae9db771bf03

r1a-summary.json
f7836072802c73ec2230a50d5428a5caeebbea9c6dfdf08962aa1082e0df874b
```

首次 refined tests 的 Ruff 出现一个 `RUF007`，实现角色只机械改用 `itertools.pairwise`；原输出保留。该 checkpoint 随补充修复产生的新文件哈希而历史化。

## 4. 初版独立 QA 否决

QA 在旧哈希下独立得到 exact 7/7、legacy 9/9、policy-v3 唯一预期 RED、真实 `-I -S -B` site derivation 与静态门通过，但敌意输入 probe 发现：

| Seam | 输入 | 初版实际结果 | 合同期望 |
|---|---|---|---|
| derive | `python_major_minor=None` | 裸 `TypeError` | `BootstrapError` |
| derive | `pyvenv.cfg` 5000 位 version component | 裸 `ValueError` | `BootstrapError` |
| RECORD parser | `required_paths` 含不可哈希 list | 裸 `TypeError` | `BootstrapError` |
| RECORD parser | 5000 位 decimal size | 裸 `ValueError` | `BootstrapError` |

旧 QA 证据根：

```text
/private/tmp/ai-auto-lrc-b3f-r1a-qa.EJcJzNki

qa-audit.json
53a8451759698f392a03daf6cf9973447b05833d13b378dc530eb18673ecde02

exception-probe.json
0b02bd8f077567c4899eac6c276682cbfa339909a74c695509eebb276005b8f7
```

架构角色在同一旧哈希上补充确认两个问题：

1. 错配的 `pyvenv.cfg.home` 会被接受，未证明 venv alias、最终 Python target 与配置属于同一解释器；
2. loader 失败只清理五个 owned `sys.modules` 名和 parent attribute，transitive `email.*` 等 residue 仍存在；原测试名中的 `rolls_back` 强于实际证明。

因此初版判定为 **P1 / 不能无条件通过**。`main()` 恰好捕获 `ValueError` 不能修复 provider seam 合同，且不捕获 `TypeError`。禁止通过扩大 `main()` 的通配捕获或删除失败记录掩盖问题。

## 5. 补充 RED 与最小 GREEN

补充证据根：

```text
/private/tmp/ai-auto-lrc-b3f-r1a-supplement.gVRRFMqM
```

新增四个合同节点：

```text
test_s18_b3f_r_derive_rejects_invalid_version_inputs_without_raw_errors
test_s18_b3f_r_derive_binds_home_and_current_uv_runtime
test_s18_b3f_r_record_rejects_invalid_inputs_and_freezes_uint63_size
test_s18_b3f_r_bound_module_loader_cleans_only_owned_bindings
```

正式补充 RED 为 `3 failed / 1 passed`。三个失败精确暴露：

```text
len(None) -> raw TypeError
home mismatch -> accepted
set(required_paths) -> raw TypeError for unhashable list
```

补充 GREEN 冻结：

- `python_major_minor` 只接受 exact length-2 tuple；bool、负数、list、错误长度及 `>999` 均在 seam 边界成为 `BootstrapError`；
- pyvenv version component 在 `int()` 前完成 ASCII decimal、位数和 `<=999` 上界检查；
- `_validate_executable_alias` 返回经过 bounded symlink-chain 检查的 canonical final target；
- `home` 必须是 canonical absolute、非 symlink 的真实目录，且精确等于 final target 的 parent；
- `required_paths` 先逐项验证字符串与 canonical POSIX relative path，再做集合去重；
- RECORD size 冻结为 `0 <= size <= 2**63 - 1`，`2**63` 与 5000 位输入 fail closed；
- loader 只承诺清除 owned bindings，不宣称 transitive rollback。

最终实现结果：

```text
补充首次 GREEN                 4 passed
补充最终 GREEN                 4 passed
原 R1a exact-7                 7 passed
实现角色 legacy selection      10 passed
policy-v3                      1 expected failure: schema 2 != 3
```

JUnit SHA-256：

```text
supplement-red.junit.xml
9c3ca6099bcceb0cfc6701c0c8e23fcc5cce46c5300f28bc0a7f08e0ff69dcb0

supplement-green-final.junit.xml
27395f6bea2aad61bc93402be9831c60249dbcda56123fe9598005cd7b92c7ac

r1a-exact7-green.junit.xml
98d53e68d504f7a0696a254cfd7b3b087779d9c5febf93fbc401b99dc4d247b1

legacy-bootstrap-green.junit.xml
66e455ef904635fd47afe6c6fc10bc07aa73884ac169e6fa1c549d54f83d7753

policy-v3-expected-red.junit.xml
8859c12cdd06279d3d6e70a4e9b7dd9206cb169e47fbc29576b73ba61c533b82
```

汇总：

```text
supplement-summary.json
1ddc5c1e8b5b82e74f762f169a5288d8c6d6acb8e51fffa89fa5ef7d22bd9462

bundle-files.sha256
93f3c01708a3e65776400baf4e6f127ff1a22da7742af5f2a988948ec892e305
```

真实 uv probe 首次误传相对 alias 并被合同正确拒绝，错误日志与 absolute alias 成功重试均保留。成功重试证明当前 macOS host：

```text
alias          /Users/liu-haixiao/ai_code/AI-auto-lrc/.venv/bin/python
final target   /Users/liu-haixiao/.pyenv/versions/3.11.4/bin/python3.11
bound home     /Users/liu-haixiao/.pyenv/versions/3.11.4/bin
site-packages  /Users/liu-haixiao/ai_code/AI-auto-lrc/.venv/lib/python3.11/site-packages
```

## 6. 补充修复独立 QA

独立 QA 证据根：

```text
/private/tmp/ai-auto-lrc-b3f-r1a-supp-qa.58bkvehi
```

结果：

```text
supplemental exact collect/formal     4 / 4 passed
R1a exact collect/formal              7 / 7 passed
independent legacy selection          9 passed
policy-v3                             1 expected failure only
py_compile / Ruff / diff check        PASS
final pytest/security-runner gate     clear
P0 / P1                               0 / 0
```

实现角色的 legacy 10 与 QA 的 independent legacy 9 是不同的显式 node selection，不得相加或互相代签。

QA 独立确认以下敌意输入只抛精确 `BootstrapError`：invalid tuple/list/None/bool/oversize version、5000 位 pyvenv version、relative/symlink/file/mismatched home、list/unhashable/non-string required paths、5000 位 RECORD size 和 `2**63`；`2**63 - 1` 正常接受。

真实 `-I -S -B` probe 前后均未加载 `site`、`sitecustomize`、`usercustomize`。Loader failure probe 同时证明 owned bindings 消失、预存无关模块身份不变、transitive residue 仍存在；最后一项是声明边界，不是失败。

```text
qa-audit.json
d395ec2cf2e8fdf1573994032f1d627d8dc957192cade2bd65a0c90c7e2c7b2d

evidence-checksums.json
78e1369e859db538b8a2a8b6e743147be40901204199a3b4155ecd2daf6aa8b8

adversarial-probe.json
489ae1c777a2ed388d4cc350512a38b42bbd8e607a25663a4a40590d44bb12e1

bound-file-hashes.json
d02a50e7c04fdf9afea495ed409a2e4d97658edf1519511fc1f9035f7da5742b

final-process-gate.json
b8aef7e1e0dd4a033e7d82dbd7725180714697b7078b2b533a3dff79a023eaac
```

最终绑定文件：

```text
scripts/security_pytest_bootstrap.py
320dd0434e7ca1a0f04c3f3229ac9d86f7a98b5183014f784cd42248322bf120

tests/contract/test_security_coverage_gate.py
f66a8a94ac71dc6809a226f77a0425dd7e35e259de4f91088c01d67c2d3e442c
```

## 7. Loader fail-stop 裁决

禁止把同一 Python 进程中的 `sys.modules` 清理描述为完整 rollback。R1b 接入时必须冻结：

1. loader 在 isolated bootstrap subprocess 的生产路径只调用一次；
2. 任一 validate/read/compile/exec 失败直接退出 2；
3. 失败后不得 retry、继续 import、调用 `pytest.main`、构造或发布 identity；
4. retry 必须创建新的 isolated subprocess；
5. owned-binding cleanup 只是 best-effort cleanup，不撤销 transitive import 或模块副作用。

对应两个不可删除的 R1b 合同为：

```text
test_s18_b3f_r1b_loader_failure_path_is_statically_terminal
test_s18_b3f_r1b_loader_failure_exits_without_publish_or_pytest
```

## 8. R1b 最小内部 API

R1b 保留三个 primitive 的签名，在其上增加四个 composer：

```python
_capture_runtime_layout(
    executable: Path,
    *,
    python_major_minor: tuple[int, int],
    base_prefix: Path,
) -> dict[str, object]

_capture_named_distribution(
    site_packages: Path,
    *,
    canonical_name: str,
    required_paths: tuple[str, ...],
) -> tuple[dict[str, object], tuple[dict[str, object], ...]]

_capture_lock_package(
    lock_path: Path,
    *,
    canonical_name: str,
    required_dependencies: tuple[str, ...],
) -> dict[str, object]

_build_runtime_identity_v2(
    *,
    scope,
    runtime_layout,
    uv_identity,
    uv_lock_sha256,
    distributions,
    plugins,
) -> dict[str, object]
```

Runtime layout 最小字段：

```text
executable / executable_realpath / executable_size / executable_sha256
venv_root / base_prefix / site_packages / home
pyvenv_cfg_path / pyvenv_cfg_bytes / pyvenv_cfg_size / pyvenv_cfg_sha256
```

Named distribution 最小字段：

```text
name / version / dist_info
metadata_bytes / metadata_size / metadata_sha256
record_bytes / record_size / record_sha256 / record_rows
required_entries[path].bytes / .size / .sha256
```

Lock package 最小字段：

```text
name / version / exact_package_object / canonical_package_bytes
lock_package_sha256 / required_dependencies
```

Builder 无 I/O，拒绝未知/缺失字段，使用 strict padded base64 进入最终 JSON，并计算排除 run scope/timestamp 的 semantic runtime digest。Whole METADATA/RECORD digest 必须直接基于捕获的原始 bytes，不能基于 normalized rows JSON。Opaque RECORD row 永远不得进入 join/resolve/stat/open。

## 9. R1b 15 项必选合同

```text
1  test_s18_b3f_r1b_runtime_layout_binds_alias_target_pyvenv_and_base_prefix
2  test_s18_b3f_r1b_runtime_layout_rejects_alias_endpoint_swap
3  test_s18_b3f_r1b_runtime_layout_rejects_python_or_pyvenv_before_after_drift
4  test_s18_b3f_r1b_loader_failure_path_is_statically_terminal
5  test_s18_b3f_r1b_loader_failure_exits_without_publish_or_pytest
6  test_s18_b3f_r1b_distribution_resolution_requires_one_canonical_direct_child
7  test_s18_b3f_r1b_distribution_metadata_name_and_version_are_exact
8  test_s18_b3f_r1b_distribution_hashes_original_metadata_and_record_bytes
9  test_s18_b3f_r1b_distribution_never_resolves_or_opens_opaque_record_rows
10 test_s18_b3f_r1b_required_entry_drift_is_rejected_and_capture_bytes_drive_loader
11 test_s18_b3f_r1b_lock_package_resolution_is_pep503_unique
12 test_s18_b3f_r1b_lock_package_digest_binds_exact_canonical_object
13 test_s18_b3f_r1b_lock_package_requires_named_dependency_edges
14 test_s18_b3f_r1b_identity_v2_has_exact_shape_and_rejects_unknown_fields
15 test_s18_b3f_r1b_semantic_runtime_digest_excludes_only_run_scope
```

第 2、3 项是 TOCTOU 门；第 4、5 项是 fail-stop 门，均不得删减或用静态 helper 单独代签。R1b 仍不修改 policy/verifier/runner 对外 schema，不运行真实 security runner，不发布真实 identity v2；policy-v3 节点必须继续 RED，直到 R2 原子消费者迁移。

## 10. R1b 执行顺序与完成判据

```text
R1b-0  添加15项合同，确认失败只来自composer/identity-v2 seam不存在
  -> R1b-1 runtime layout stable capture + TOCTOU rejection
  -> R1b-2 named distribution direct-child/METADATA/RECORD/entry capture
  -> R1b-3 canonical exact uv.lock package object + dependency edges
  -> R1b-4 pure identity-v2 builder + semantic digest
  -> R1b-5 loader production integration的static/dynamic fail-stop合同
  -> R1b-6 exact15 fresh replay + legacy R1a + policy预期RED + 独立QA
  -> only then R2 atomic schema migration
```

R1b 完成判据：15 项同一最终代码/测试哈希下全部 GREEN；R1a 11 项（原 7 加补充 4）回归通过；policy-v3 仍只有预期 RED；不存在裸输入异常、opaque path 访问、second live read、loader failure 后继续、identity publication 或真实 runner 调用；QA 重算 bytes/digest/field sets 并确认无 P0/P1。

R1b 不改变 Spec Inventory 274 项、B3e `7 implemented + 13 planned` 或 P1 `5 implemented + 2 planned / verification unverified / qualification unqualified`。B3f-L final 67 继续只是历史 checkpoint，最终 schema 后必须完整 fresh replay，不能拼接旧证据。
