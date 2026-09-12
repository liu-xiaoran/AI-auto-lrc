# S18 P1 B3f R0 Contract RED Teams 记录

日期：2026-09-07

模式：Teams 架构runtime预审 单实现角色合同RED QA独立静态与fresh RED复核 主任务文档治理

权威方案：[`../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第32节`S18-P1-PLAN-v1.19`

## 1. 结论

B3f-R0五个低成本合同节点已建立并经独立QA确认有效。Fresh collect为exact 5 unique，formal结果为5 failed/0 error/0 skip；失败只来自三个未来bootstrap seam不存在和policy仍为v2。没有修改bootstrap、runner、verifier、policy或运行真实security runner。

R0改变了contract test SHA，因此第31节B3f-L final 67证据成为历史checkpoint。B3f-R final schema完成前不重复旧schema 67；最终schema closure必须重新replay B3f-L、B3c/B3d/B3e core。

## 2. RED节点与未来API

```text
test_s18_b3f_r_isolated_no_site_probe_derives_exact_venv_site_packages
test_s18_b3f_r_bound_package_entries_compile_from_stable_bytes
test_s18_b3f_r_record_parser_accepts_only_one_self_record_exception
test_s18_b3f_r_record_parser_never_resolves_parent_path_rows
test_s18_b3f_r_policy_v3_freezes_named_runtime_contract
```

未来seam冻结为：

```text
_derive_runtime_site_packages(executable, *, python_major_minor) -> Path
_load_bound_runtime_modules(entries) -> (ordered modules, ordered identities)
_parse_distribution_record(record_bytes, *, dist_info, required_paths) -> tuple[normalized rows]
```

测试直接约束`-I/-S/-B`、同一stable bytes对象hash/compile/exec、禁止`site.addsitedir/.pth/sitecustomize`、RECORD唯一self row、opaque parent row永不resolve/open，以及policy v3的named runtime/required entries/dependency edges/limits。Invalid RECORD矩阵10项、unsafe required-path矩阵5项已经写入；当前因seam guard fail-fast未深入，R1实现后将直接命中产品函数。

## 3. 实现与QA证据

实现RED：`/private/tmp/ai-auto-lrc-b3f-r0-red.79V9ayvj`

```text
tests before  915fbaaed6ca151c3b2b00a6983f081c1ea65cc4fc029b66b997cde82270ad07
tests after   06df29df55ca0c42fe02e9d908dc423172a88993c5987e8855ff8ab634ab3160
formal        5 failed / 0 error / 0 skip
```

| Artifact | SHA-256 |
|---|---|
| `r0-summary.json` | `4c71b7ec169e30d19d1773986669d8f288767d49e899679b90b3a2b20b5f6759` |
| `red-final.junit.xml` | `56ffd5abe6a40e7db35da325a7a968729e10eb3ca7f1400754f7f497b538b2ca` |
| `red-final.stdout` | `6c302d5bf1de041e4ea12157c96b6af6020ca72758be7f49d65b12e99000608a` |
| `bundle-files.sha256` | `e109707bac8ff222527a8e03f93529e7af7946834d6136d714787bbeee25285a` |

独立QA：`/private/tmp/ai-auto-lrc-b3f-r0-contract-red-qa.8eKCvqxs`

```text
independent-audit.json   a0f9155f7de82c451dd8130f1ce98540c17db58f2439b415d2d9186c1a472944
formal.junit.xml         355fd70cb50d421d6dba5b582a76e98edba5b8472ff9858f6e06b3df9381280b
b3fl-lightweight.junit   198dbf83c07218c623b48c128185118752117d792b02bfd24bb98ad0683e880a
checksums.json           1e71b7c4445f1d736ebaf5e6592166ac862607399e9bbd0d6523a3bf4ec16638
```

QA确认旧测试前370,411 bytes保持旧SHA，新测试为纯追加；helper只做fixture与观测，没有定义三个产品seam。Bootstrap/runner/verifier/policy/events/manifest/pyproject/uv.lock哈希不变，B3f-L lightweight authority 4 passed，py_compile、Ruff、diff check通过。

透明记录：实现侧首次Ruff有两处UP012，机械移除冗余encode参数后RED不变；QA有两次工具JS拼写错误，均在命令执行前失败。所有日志保留。

## 4. 唯一下一步

R1只实现bootstrap producer基础seams与identity v2构造，不修改runner/verifier/policy的对外schema，不跑真实security runner。R1必须让isolated-site、stable-byte modules和两项RECORD测试GREEN；policy v3节点继续保持RED直到R2原子消费者迁移。R1同时新增synthetic rejection matrix覆盖dist-info唯一性、METADATA/RECORD/entry drift、required dependency与`.pth/sitecustomize`规避，但不能通过importlib.metadata首个匹配或`site.addsitedir`绕过。

R1完成后仍不能发布identity v2到真实runner；只有R2把policy、verifier、artifact factories和所有schema原子迁移后，才允许进入R3真实双lane。S18、W1b-5b、Release继续No-go；W1b-5c/5d/5e不执行。
