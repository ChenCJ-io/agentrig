# Changelog

本文件记录 AgentRig 的版本变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [0.1.0a0] - 2026-07-15

首个公开 alpha：后端闭环 + MCP + CC skill + 前端 web，端到端可验收。

### Added — 后端核心

- **AgentTransport 抽象**：Protocol + NormalizedEvent，驱动任意 tool-calling agent
- **StreamingChatTransport**：外置 tool-calling SSE agent 的参考 transport（POST `/chat/stream`）
- **EchoTransport**：脚本驱动的降级 transport（无 agent 环境冒烟/单测）
- **MCP Proxy/aggregator**：对上是 server、对下是 client；命名空间前缀、动态发现后端工具、mock 注入、全量 trace
- **四层 mock**：L0 内联 / L1 剧本 / **L1.5 等价变形**（参数归一化）/ L2 样本库
- **机判**：`rule_judge`（expected_tools / text_contains / tool_call_order / not_called）+ `ai_judge`（LLM 按 rubric）+ `off`
- **录制泛化**：`get_real_tool_samples`，从 proxy trace 捞真实工具返回样本给 CC 写用例
- **用例持久化**：`TestCaseRepo` Protocol + SQLite / 内存后端（按 `AGENTRIG_DATABASE__URL` 选）
- **LLM provider 抽象**：`LLMProvider` Protocol + `OpenAICompatProvider`
- **TOML 配置**：`agentrig.toml`（优先级 构造参数 > env > TOML > 默认）

### Added — 接入与工具

- **MCP 工具组**：authoring（upsert/list/get case）、execution（run_single_case）、sampling（get_real_tool_samples）
- **REST API**（`/api`）：overview / cases CRUD / run / tool-samples，供前端调用
- **CC 测试 skill 包**（`skills/core/`）：build-test-case、run-test-cases、harvest-tool-samples（双语 frontmatter）
- **一键验收**：`agentrig demo`（起内置 sample agent 跑通真实 tool-calling 闭环 + 机判）
- **内置被测 agent**：`demo_agent`（单步）、`sample_agent`（两步 search→summarize）

### Added — 前端 web

- React + Vite + Tailwind，按设计稿一比一实现四页：
  - **Overview**：Release Gate + 4 metric 卡 + 近期运行表 + 用例增长
  - **Test cases**：列表 + 过滤 + 搜索 + 状态 badge + 分页
  - **Case editor**：scenario 输入 + 断言编辑 + mock JSON + 运行目标/最近结果/覆盖面板
  - **Run detail**：判定 badge + 工具调用时间线 + agent 回复 + 判定理由
- **中英文切换**（i18n context + 全文字典 + 侧栏一键切换）

### Added — 文档与治理

- 设计文档（`docs/01-08`）+ `quickstart.md` + `acceptance.md`
- `CONTRIBUTING.md` / `CODE_OF_CONDUCT.md` / `SECURITY.md`
- CI（GitHub Actions）：后端 ruff/mypy/pytest（3.12+3.13）+ 前端 build

### 修复的 Bug

- `case_runner` 只对本轮新 tool_calls 生成 mock（原传累积 `rd.tool_calls` 致多步 agent 死循环）
- `aggregator` 的 `type: ignore` code typo（`no-untyped-decorator` → `untyped-decorator`）

### 脱敏

- 全仓清理内部代号（`lassist` → `streaming_chat` / `StreamingChatTransport`），`Lassist`/`Pixcake`/`agent_client` 零残留
