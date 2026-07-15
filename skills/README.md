# AgentRig 测试 Skill 包

教编码 Agent（Claude Code / Codex 等）怎么用 AgentRig 的 MCP 工具做**回归测试**。

## 为什么有这组 skill

AgentRig 的差异化不止在工具，更在「CC 会用工具做测试」这套方法论。光给工具，CC
不一定知道**何时查重、何时取真实样本、rubric 怎么写**。这组 skill 把实战沉淀的方法论
固化成 CC 能读的指令——装上即得「开箱即用的测试能力包」。

## 三件套（core/）

| Skill | 何时用 | 核心动作 |
|---|---|---|
| [`build-test-case`](./core/build-test-case/) | 给业务 agent 构建/更新回归用例 | 查重 → 取真实样本 → 设计断言 → upsert → 停下等确认 |
| [`run-test-cases`](./core/run-test-cases/) | 跑用例 + 诊断失败 | run_single_case → 读 reasons → 区分假红/真红 |
| [`harvest-tool-samples`](./core/harvest-tool-samples/) | 采集真实工具返回样本 | 从 proxy trace 捞真实返回 → 喂给 mock（零失真） |

## 前置条件

- AgentRig 已起：`uv run agentrig serve`（暴露 `/mcp` 工具 + `/proxy` 代理）
- 在编码工具的 MCP 配置里把 AgentRig 配为 server（server 名 `agentrig`）
- 被测 agent 若要真跑：配 `AGENTRIG_AGENT__SERVER_URL`，或通过 `/proxy` 走工具代理

## 核心方法论（贯穿三件套）

1. **查重先于构建** —— 先 `list_test_cases`，别重复造用例
2. **真实样本零失真** —— mock 基于真实工具返回（`get_real_tool_samples`），别凭空臆造
3. **判可观测，不判内部机制** —— rubric/expectations 断言 agent 的可观测行为（调了什么工具、说了什么），不测服务端内部实现
4. **编译器式自我修正** —— `upsert_test_case` 报错 → 按错误改 → 重试，直到接受
5. **人机边界** —— 构建完停下等 approve，不要全自动跑

> 示例里用 `echo` / `reverse` / `search` 等中性工具名。接你自己的 agent 时，换成它的真实工具名。
