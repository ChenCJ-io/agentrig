---
name: harvest-tool-samples
description: 从 AgentRig proxy 录的 trace 采集真实工具调用与返回样本，喂给 mock，让用例贴合真实 agent 行为（零失真）。Harvest real tool call/result samples from AgentRig proxy traces to feed mocks with zero distortion.
---

# harvest-tool-samples

采集**真实工具返回样本**，让 mock 不凭空臆造。这是「用例可信度」的关键输入。

## 何时用

- 写用例前，想拿真实工具返回结构作 mock 参考（配合 `build-test-case`）
- mock 和真实行为对不上（用例假红），想校准
- 用户让你「录一下这个 agent 的真实行为」

## 前提：trace 从哪来

AgentRig 的 trace 来自 **proxy 模式**：被测 agent（MCP client）连 AgentRig 的 `/proxy`，
agent 调工具时调用从 proxy 过，proxy 转发后端真实 server 并**录下每次调用的参数 + 返回**。

所以要先让 agent 真跑过一次（通过 `/proxy` 用工具），才有 trace 可采。

## 采集

调 `get_real_tool_samples`：

- 不传参 → 返回所有工具的真实样本
- 传 `tool_name`（如 `"fs__read"`，带命名空间前缀）→ 只返回该工具的

返回每条样本：
```json
{
  "tool_name": "fs__read",
  "arguments": {"path": "/etc/hosts"},
  "source": "real",
  "is_error": false,
  "result": ["127.0.0.1 localhost"]
}
```

> 默认只取 `source: "real"`（真实后端返回）。mock 的样本不混进来（避免自证循环）。

## 用法

1. 采目标工具的真实样本（`get_real_tool_samples(tool_name)`）
2. 看真实 `arguments` 的形状 + `result` 的结构
3. 写 `case.mock` 时，**按真实结构**构造返回值（参数不同可微调，但结构对齐）
4. 这样 mock 出来的用例，agent 跑起来行为贴近真实，断言才有意义

## 注意

- 样本是**结构参考**，不是逐字复制（参数要适配你的用例场景）
- 没有真实样本（agent 没真跑过 proxy）→ 至少按工具 `inputSchema` 构造合理占位，
  并标注「mock 未校准，待真实样本」
- `is_error: true` 的样本是**边界/错误返回**，测 agent 对异常的处理时有用，别当正常返回
