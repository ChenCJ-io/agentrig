---
name: build-test-case
description: 为业务 agent 构建或更新一个 AgentRig 回归测试用例。查重、取真实工具样本、设计断言、写 mock，最后停下等确认。Build or update an AgentRig regression test case: dedupe, harvest real tool samples, design assertions, write mock, then pause for approval.
---

# build-test-case

给被测的业务 agent 构建一条回归用例。**不是凭空写**，而是基于真实工具返回 +
对 agent 行为的理解。

## 何时用

- 你改了业务 agent 的代码，想针对本次改动加一条回归用例
- 用户让你「给这个 agent / 这个改动补个测试」
- 已有用例需要更新（agent 行为变了，旧断言不再合适）

## 流程（按顺序）

### 1. 先查重，别重复造

调 `list_test_cases` 看现有用例。按「被测工具 / 场景」判断是否已有覆盖本次改动的用例。
有 → 优先更新（`upsert_test_case` 同 id 覆盖），没有 → 新建。

### 2. 取真实工具样本（零失真）

调 `get_real_tool_samples`（可选传 `tool_name` 过滤），拿**真实工具的返回结构**。

> ⚠️ mock 的值要贴合真实返回，别脑补。脑补的 mock 测的是「你想象的 agent」，
> 不是真实 agent。真实样本来自 proxy 录的 trace（agent 真跑过 `/proxy` 才有）。
> 没有真实样本时，至少按工具的 inputSchema / 返回类型构造合理的占位。

### 3. 设计断言（判可观测，不判内部）

用 `expected_tools` / `expectations` / `rubric` 三选一或组合：

- `expected_tools: [...]` —— agent **应该调用**这些工具（最常用）
- `expectations: [{kind, ...}]` —— 结构化断言：
  - `{"kind":"expected_tools","tools":[...]}` —— 等价上面
  - `{"kind":"text_contains","needle":"退款"}` —— 回复文本应包含某词
  - `{"kind":"tool_call_order","tools":["search","summarize"]}` —— 按顺序调用
  - `{"kind":"not_called","tools":["delete"]}` —— 不应调用（防误操作）
- `rubric: "..."` + `judge_mode: "ai"` —— 自然语言判据，交 LLM 判（需配 LLM provider）

> 断言只判**可观测结果**（调了什么、说了什么），不判服务端内部机制——否则换实现就假红。

### 4. 写 mock

`mock` 是 `{工具名: 返回值}` 字典，作工具调用的回放返回。基于第 2 步真实样本写：

```json
{
  "search": {"hits": [{"id": "a1", "title": "..."}], "total": 1},
  "summarize": "摘要内容..."
}
```

### 5. upsert（编译器式自我修正）

调 `upsert_test_case`，`case` 字段：

```json
{
  "id": "search-then-summarize",
  "name": "搜索后摘要",
  "user_message": "帮我搜一下 X 并总结",
  "expected_tools": ["search", "summarize"],
  "mock": {"search": {...}, "summarize": "..."},
  "tags": ["search-flow"]
}
```

**报错就改**：字段不符 / 类型错 → 按错误信息修 → 重试，直到 `upserted: ...`。
不要一次写完美，像编译器迭代。

### 6. 停下，等 approve

构建完**不要自动跑**。告诉用户：「已构建用例 X（断言：应调 search+summarize），
要跑吗？」等人确认后再交给 `run-test-cases`。

## 反模式（别这么做）

- ❌ 不查重直接新建 → 用例库膨胀、重复
- ❌ mock 脑补，不查真实样本 → 测的是想象，不防真回归
- ❌ 断言内部实现（如「应走 cache 分支」）→ 换实现就假红
- ❌ 构建完全自动跑 + 自动改 → 越界，人机边界要守住
