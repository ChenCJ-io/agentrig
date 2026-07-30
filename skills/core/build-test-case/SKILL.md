---
name: build-test-case
description: 使用 AgentRig V1 MCP 原子工具创建或修改多轮测试用例，包含查重、Fixture/Sample 选择、有限断言和 draft 人工审核边界。
---

# 构建 AgentRig V1 测试用例

本 Skill 用于创建或修改测试用例。它不负责审核，也不在写完后自动执行。

## 工作顺序

1. 调用 `get_test_case_schema` 获取当前写入结构，不凭记忆猜字段。
2. 用 `list_test_cases`、`find_cases_by_tool` 和 `list_tags` 查重。
3. 已有同一场景时，先 `get_test_case`，再用 `update_test_case` 做最小修改。
4. 没有重复场景时，用 `create_test_case` 创建 draft。
5. 回读用例，向用户概括覆盖范围、工具结果来源和评判方式，然后停止。

approved 用例不可由 MCP 修改或删除。不要规避这条人工审核边界；需要变更时请用户在
Web 中处理审核状态或另建用例。

## 工具结果怎么选

按场景采用一种或组合使用：

- 确定、场景专属的结果：写到对应轮次的 `fixtures`。
- 可跨用例复用的真实结构：先用 `list_samples(status="approved")` 查 Sample。
- 结果需要根据前文动态生成：填写 `simulation_instruction`，执行时选择包含
  `simulation_curator` 的 ExecutionProfile。
- 只有用户明确允许真实调用时，才建议使用包含 `real_tool` 的 Profile。

Fixture 结构：

```json
{
  "tool_name": "orders__create",
  "match_arguments": {"sku": "A-1"},
  "result": {"order_id": "O-100", "status": "created"},
  "repeatable": false
}
```

同一轮多个同名 Fixture 按顺序、默认一次性消费。Fixture 属于用例，不要为它填写
`sample_id`。

## 断言与评判

Rule 只使用以下有限断言：

- `first_action`
- `tool_called`
- `tool_not_called`
- `tool_call_order`
- `tool_arguments_equal`
- `tool_arguments_schema`
- `text_contains`
- `text_regex`
- `no_execution_error`

断言只检查可观察行为，不检查缓存命中、内部函数或私有状态。

- 适合确定性判断：`primary_evaluator: "rule"`，并提供断言。
- 需要语义判断：`primary_evaluator: "evidence_judge"`，并提供 case 或 turn rubric。
- 希望 Codex/Claude Code 根据完整运行证据判断：使用
  `primary_evaluator: "external_controller"`；执行后由控制方调用
  `submit_external_verdict`。

## 多轮用例

`turns.position` 必须从 1 连续递增。后续轮次沿用同一 Driver 会话；后一次 Curator
调用可以看到本 CaseRun 之前的脱敏事件和模拟状态。不要把期望答案写进
`simulation_instruction`。

## 完成边界

创建或修改成功后，不调用 `run_cases`，也不能通过 MCP 审核。告诉用户：

- 用例 ID 与当前 draft/rejected 状态；
- 覆盖了哪些轮次和工具；
- 使用 Fixture、Sample 还是 Curator；
- 主评判器；
- 是否要继续执行。
