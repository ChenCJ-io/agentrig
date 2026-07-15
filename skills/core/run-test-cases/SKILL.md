---
name: run-test-cases
description: 跑 AgentRig 回归用例并诊断失败。读 reasons 区分假红（mock/断言不准）与真红（agent 真回归），给出可信结论。Run AgentRig regression cases and diagnose failures: tell real regressions from false-reds via reasons.
---

# run-test-cases

跑用例，看结果，**诊断失败**。重点是别把「假红」当「真回归」报告。

## 何时用

- 用 `build-test-case` 构建完用例、用户确认后
- 改完业务 agent 代码，跑相关用例看有没有回归
- 用户问「这次改动有没有破坏什么」

## 跑

调 `run_single_case(case_id)`。返回字段：

| 字段 | 含义 |
|---|---|
| `passed` | 总结论（true/false） |
| `reasons` | 判定理由列表（**诊断核心**） |
| `tool_calls` | agent 实际调用的工具 |
| `missing_expected_tools` | 该调没调的工具 |
| `error` | 执行错误（transport 连不上 / max_rounds 超限等） |
| `transport` | `real`（连真实 agent）/ `echo`（降级自测，无 agent） |
| `judge_mode` | rule / ai / off |

## 诊断（passed=false 时按 reasons 分类）

### A. 执行错误（`error` 非空）
- `transport: echo` 但本该 `real` → 没配 `AGENTRIG_AGENT__SERVER_URL`，或配错
- `max_rounds exceeded` → agent 陷入 tool-call 死循环（真 bug）
- 连接错误 → 被测 agent 没起 / URL 错

**这是环境/接线问题，不是 agent 回归。** 先修环境再跑。

### B. 断言失败（reasons 含 `expected_tools missing` / `text_missing` / `order_violation`）
分两种：

- **假红（mock 不准）**：mock 返回的值让 agent 没走到该调的工具。
  验证：调 `get_real_tool_samples` 对比，mock 是否偏离真实返回。偏离 → 修 mock 重跑。
- **真红（agent 回归）**：mock 准、输入对，但 agent 真的没调预期工具 / 输出错。
  这是本次改动引入的回归，**如实报告**。

### C. 不该调的调了（reasons 含 `unexpected_calls`）
agent 调了 `not_called` 列的工具（如 `delete`）。通常是真问题（误操作风险）。

## 多用例

逐个 `run_single_case`，或建议用户跑全量。汇总：N 条里 X pass / Y fail，
fail 的按上面分类给结论。

## 判定模式注意

- `judge_mode: rule`（默认）—— 结构化断言，确定、可复现，**优先用**
- `judge_mode: ai` —— LLM 按 rubric 判，灵活但有不确定性，结论要附上 `reasons`（LLM 原话）
- `judge_mode: off` —— 只判有没有 error

## 输出给用户

- **pass**：「用例 X 通过（调了 search+summarize，无 error）」
- **假红**：「用例 X 红，但疑似 mock 不准（search 返回结构与真实样本不符），建议修 mock 重跑」
- **真红**：「用例 X 红，agent 没调 summarize——疑似本次改动引入回归，建议查 <相关代码>」

> 别笼统说「测试失败」。给可信结论 + 依据，把假红挑出来，真红才报警。
