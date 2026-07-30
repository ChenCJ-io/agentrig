# AgentRig V1 编码 Agent Skills

这组 Skill 指导 Codex、Claude Code 等外部编码 Agent 使用 AgentRig MCP。V1 中外部编码
Agent 是执行控制方：负责选案、提交运行、读取原子证据，并可在关闭 Evidence Judge 时
回写自己的判定。

| Skill | 用途 |
|---|---|
| [`build-test-case`](./core/build-test-case/) | 查重后创建或修改 draft/rejected 多轮用例 |
| [`run-test-cases`](./core/run-test-cases/) | 异步执行单个、批量、多版本、重复和 A/B 测试 |
| [`harvest-tool-samples`](./core/harvest-tool-samples/) | 从已存档 Real Tool 证据显式创建 Sample 草稿 |

## 前置条件

1. 启动 AgentRig：`uv run agentrig serve`。
2. 将 `http://127.0.0.1:8000/mcp/` 配置为编码 Agent 的 MCP Server。
3. 在 AgentRig 中创建 Target；密钥只用 `env:VARIABLE_NAME` 引用。
4. 创建 ExecutionProfile，明确工具控制方式、Provider 顺序和主评判器。

## 共同原则

- 只使用 V1 原子工具；不寻找旧的 `upsert_test_case`、`run_single_case` 或全局 Trace 工具。
- MCP 可以管理 draft/rejected 用例和 draft Sample，但不能执行人工审核。
- 一个 `run_cases` 同时覆盖单用例与批量；结果通过 Run ID 异步查询。
- Fixture、approved Sample、Simulation Curator、Real Tool 按 Profile 配置顺序降级。
- Real Tool 只有在部署允许、Profile 启用且用户明确授权时才调用。
- Rule、Evidence Judge 和 External 判定分别存档；当前状态以用例的主评判器为准。
- 所有判断引用 CaseRun 中真实的脱敏事件，不依据不可观察的内部实现。
