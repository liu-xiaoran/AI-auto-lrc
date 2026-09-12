# S18 P1 Teams 方案冻结记录 2026-09-07 第三轮

## 目标

把分散在 S18 17.11、交接入口、代码审阅和聊天中的剩余方案收敛成一个可执行、可验证、可恢复的本地事实源，并补齐 pytest hermeticity、plugin identity、JUnit/events 一致性和 ABA 声明边界测试。

## 角色结论

### Architect

- 继续向超长主文档内嵌实现细节会降低检索和执行准确性；应新建聚焦 P1 方案，主文档只追加版本/hash 指针。
- runner、verifier、plugin、pytest config、policy、manifest 和 raw artifacts 组成同一资格化闭包；任何相关字节变化都会历史化旧 macOS/Linux Security Gate。
- immutable execution snapshot 不是本轮最小修复，必须保持 endpoint observation 的声明上限。

### Security reviewer

- 当前 runner 自动加载未绑定的 `typeguard._pytest_plugin`，证明 95 个合同通过不等于 pytest 执行环境封闭。
- `--disable-plugin-autoload` 不会阻止 `PYTEST_PLUGINS`；恶意 plugin 可以移除 xfail marker，使 non-strict XPASS 被记录为普通 PASS。
- 需要同时关闭 entry-point autoload、清理 `PYTEST_PLUGINS`/`PYTEST_ADDOPTS`、禁止 conftest，并只显式加载 `pytest_cov` 和受约束 events plugin。
- `scripts` namespace package 存在同名包 shadowing 风险；必须证明实际加载 path/hash，而不是只 hash 仓库同名文件。

### Developer

- 采用原子切片：hermetic boot、plugin identity、event consistency、ABA claim，分别保留 RED/GREEN 和回滚边界。
- 不把 P1 修复与 R2–R5 大型 verifier/runner 结构重构混合。
- pending 文件范围限定为 runner、verifier、events plugin、必要 schema/policy/manifest/config 和 Gate contracts。

### QA

- 直接篡改 JSON 只能验证 verifier；hermeticity 和 xfail 绕过必须有真实 pytest/runner integration。
- 当前 `call_outcome` 仅校验枚举，未与 JUnit 状态交叉；required JUnit PASS 对应 `not-run`/`failed`/`skipped` events 仍可能通过，必须新增参数化 RED/GREEN。
- macOS、Linux、package、canonical、host、sealed evidence 分别签署，不能互相替代。

### Skeptic

- 独立执行方案必须成为唯一权威入口，并在四份主文档追加固定相对路径、版本和 SHA-256，否则仍会产生导航漂移。
- 最终证据刷新应使用独立运行账本，不能把大量 attempt/hash 再写回架构正文造成下一轮漂移。

## 决策

1. 新建 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 作为唯一执行方案。
2. 当前 B3 状态调整为 `Implemented / qualification blocked`，不是已资格化完成。
3. 将 hermetic pytest boot 和实际 plugin identity 提升为 P0，优先于 ABA 和双平台重跑。
4. 将 JUnit/events outcome consistency 列为 P1 必做项。
5. ABA 只锁定最大声明，不实现 immutable snapshot。
6. 方案完成落盘后只做文档链接和 Spec Inventory 校验；不因文档落盘自动开始高成本平台资格化。

## 仍需执行的裁决

- plugin identity 采用 regular package + events identity，还是绝对路径 bootstrap；默认推荐前者，但必须先取得对抗测试 RED。
- W1b-5b 是否接受 macOS functional package + Linux capture-bound package 的 platform-scoped 结论；若不接受，需另立 macOS capture-bound 工作包。

## 当前 Gate

S18、W1b-5b、Release 继续 No-go。commit、push、CI、upload/sync、签名、发布、W1b-5c/5d/5e 仍未授权。

## 最终安全审阅增补

最终只读审阅确认，现有 XFAIL runner integration 使用 fake `uv` 复制预制 artifacts，不能替代真实 runner 的 XFAIL、两种 XPASS、环境注入和 plugin 写出失败闭环。方案据此升级为 `S18-P1-PLAN-v1.1`。

同时新增两个最终资格化前的能力：events 生成端 case/nodeid/serialized-byte 上限，以及 `pytest_cov`/`uv.lock`/installed-vs-lock 工具链绑定。macOS 双 lane 绿色和 Linux capture 绿色仅保留为诊断 checkpoint；Linux retention 的非 root `mknod` 失败只表示临时容器权限不足，不推导代码兼容性结论。

## 可执行性勘误

- pytest autoload 采用环境变量 `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` 与 argv `--disable-plugin-autoload` 双重关闭，同时清理 `PYTEST_PLUGINS` 和 `PYTEST_ADDOPTS`。
- Security coverage runner 不生成 receipt；ABA 测试分别验证 security Gate/run-manifest exact schema 和 capture receipt 已存在的 typed false/observation-model 字段，不做全文关键词不存在断言。
- Spec Inventory 的首次 RED 来自 V2 source plan 导航词被截取为未知稳定 ID；最小文本消歧后，document links、Spec Inventory 和 security contracts 联合结果为 `100 passed in 23.45s`，未扩大 ignored list。

## 最终架构冻结

- hermetic runner 还需唯一 `-c pyproject.toml`；verifier 应构造完整 expected argv，而不是继续接受 required-token 子集。
- JUnit/events outcome 可造成重绑 hash 后的假阳性，优先级提升为 P0。
- 产品 Spec Inventory 当前绿色不代表 P1 工作包 traceability。B7 前需在现有 inventory 增加独立 `work_package_specs.S18_P1` schema，或形成具名 accepted defer；不得把 P1 ID 混入产品 ID 计数。
- B8 freeze ledger 分 common closure 和 per-platform runtime digest；两个平台只有 common digest 相同时才能合并声明。
- 最终 docs append 后必须再跑 links、P1 traceability、typed claim 和 diff 检查，但纯文档变化不使已冻结的 Security artifact 失效。

## 第四轮续接复审与 v1.4 裁决

用户要求把细化方案写入本地，避免跨会话丢失。主任务再次组织 Teams 只读复审，代理均未直接修改文档，由主任务统一 append。

### Architect 与 Security

- v1.3 的 C4 仍把 regular package + plugin 自报 identity 作为推荐候选，存在自证循环，无法证明 pluggy 实际注册的对象。
- 最终裁决改为 absolute trusted bootstrap：`python -I -B`、绝对 bootstrap path、stable-read trusted bytes、预装载 plugin object、registration identity guard、独立 `plugin-identity.json`。
- pytest-cov source、distribution/version/RECORD 与 `uv.lock` 的最小绑定前移到 B3c；B3f 只补广义 runtime closure 和 producer limits。
- 新增 `PLUGIN_IDENTITY_INVALID`，与 command/environment、command failure、toolchain binding 失败分离。

### Developer 与 Packaging reviewer

- 新文件责任限定为 `scripts/security_pytest_bootstrap.py`；runner、verifier、policy、manifest 和 contracts 只做 B3c 所需的原子变更。
- 不新增 `scripts/__init__.py` 作为信任根。它会改变 PEP 420 namespace 的内部 import 语义，也不能防 `sitecustomize`、`sys.modules` 或 import hook。
- package 侧增加 source-tree wheel、sdist、sdist-built-wheel 和 cold-install private tooling 排除合同，防止 bootstrap/scripts 意外成为 public API。

### QA

- B3b 的 host GREEN、B3d 的 schema v2/三阶段一致性和 130-pass checkpoint 需要进入 current ledger，但都不能提升为跨平台 qualification。
- B3c 必须有 local scripts shadow、fake pytest-cov、sitecustomize/sys.modules、同名不同注册对象的真实 RED/GREEN，以及 identity/command/manifest mutation。
- B3e、B3f、B4a/B4b/B4c 必须统一记录 RED、GREEN、mutation、platform scope、exit code、Gate exact failures 和不可覆盖 evidence layout。

### 最终决定

完整可执行内容只追加到 [`S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md`](../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md) 第 17 节，版本 `S18-P1-PLAN-v1.4`。本 Teams 文件保存分歧、角色意见和裁决理由，不复制完整 schema 与测试矩阵。

当前第一步为 B3c trusted plugin identity RED；B3b/B3d 只保留 host implementation checkpoint。S18、W1b-5b、Release 继续 No-go，5c/5d/5e 仍未授权。
