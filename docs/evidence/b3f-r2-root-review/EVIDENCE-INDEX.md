# R2 递归修复后主代理复验证据

本索引只记录主代理fresh复验，不是独立QA验收。最新执行状态由[主方案](../../S18_P1_EXECUTABLE_REFACTOR_PLAN.zh-CN.md)第36.40节拥有。

- 证据根：`/private/tmp/ai-auto-lrc-b3f-r2-root-final.gqI2my`。
- 输入快照：[新九文件清单](../b3f-r2-recursion-implementation/nine-files.sha256)，执行前后9/9匹配。
- [47节点](./47-nodeids.txt)：同进程47 passed in73.80s，exit0，stderr空；JUnit `b8bf1162d6315a9587fa9fe0d03f36fea1c891b408c2bc645c6ba9f2ae0c712e`。
- [35补充节点](./35-nodeids.txt)：同进程35 passed in1.07s，exit0，stderr空；JUnit `9db6b9177f4435f90928982666f8d002a03a7ffaf6a8a20b2be3b647cd164900`。
- XML分别47/35 testcase，failure/error/skipped均0。
- 两组重叠两个R1b loader节点和一个record-field节点，合计79个唯一节点；不将执行次数相加为覆盖数。
- 原始命令为根内`47-command.sh`、`35-command.sh`；collect、stdout、stderr、exit、JUnit及独立未复用的pytest basetemp同根保存。
- stdout由工具原始分块按顺序保存，stderr单独重定向；exit为对应exec终态，不是输出文本推断。
- 未运行整个gate文件、真实bootstrap/security双lane、final67、R3、平台、CI、上传、commit或push。
- 最终独立QA任务被执行环境中止，没有结论；不能把本索引改名为独立验收。
- 本地保存的是文本索引/精确节点；原始测试目录仍是临时目录，并非完整归档或跨机备份。

文档治理fresh结果：42 passed in12.92s，exit0、stderr空；原始docs-command.sh/stdout/stderr/exit/JUnit同证据根保存，JUnit SHA-256为 `f42c1682f99f1309b5fca5cd41a334460a47e9be9d06e8d53edfd19791cc543b`。本结果在验证后追加，不改变产品资格。
