# 贡献指南

感谢关注 AgentRig！这是一份如何参与贡献的说明。

## 开发环境

需要 Python 3.12+、[uv](https://docs.astral.sh/uv/)、Node.js 20+。

```bash
uv sync --extra dev
cd web && npm ci
```

## 跑测试与检查

提交前请确保以下检查通过：

```bash
uv run ruff check src tests examples
uv run mypy src/agentrig
uv run pytest
cd web && npm run typecheck && npm run build
```

一键验收平台闭环:

```bash
uv run agentrig demo
```

## 改动流程

1. fork → 从 `main` 拉 feature 分支（**不要直接在 main 上改**）
2. 改动 + 测试（上述四项全过）
3. commit 用约定式前缀：`feat:` / `fix:` / `docs:` / `refactor:` / `test:` / `chore:`
4. PR 描述：动机、改了什么、怎么验证

## 增加回归用例

可以通过两种方式创建 V1 用例：

- Web 控制台：`/evaluation/test-cases`
- MCP 原子工具：`create_test_case`，配合 [`skills/core/`](./skills/) 工作流

用例由 MCP 创建后是 draft。approved/rejected 审核只能通过 Web 或 HTTP API 完成。

## 前端开发

```bash
# 终端 1：起后端（默认 127.0.0.1:8000）
uv run agentrig serve
# 终端 2：前端热重载（vite，proxy /api → 后端）
cd web && npm run dev
```

生产构建产出 `web/dist/client`，由 `agentrig serve` 同服务挂载。

## 代码风格

- **Python**：ruff + mypy strict；注释用中文
- **TypeScript**：strict；注释用中文
- **文档/skill**：正文中文，`description` / slogan 双语

## 目录速览

```
src/agentrig/
├── cases/         用例与 selector
├── targets/       Target、版本与 Driver
├── profiles/      ExecutionProfile
├── tool_results/  Fixture / Sample / Curator / Real Tool Provider
├── agents/        Simulation Curator 与 Evidence Judge
├── evaluations/   Rule / Judge / External 判定
├── runs/          Planner / Scheduler / Executor / 事件
├── proxy/         CaseRun 级 MCP Proxy
├── mcp/           编码 Agent 使用的原子 MCP Tools
└── infrastructure/database/

web/               React Router V1 管理界面
skills/core/       Codex/Claude Code 三份工作流 Skill
examples/v1/       三条可执行纵向 Demo
docs/              当前 V1 架构与接入说明
```

## 行为准则

参与即视为同意遵守 [Code of Conduct](./CODE_OF_CONDUCT.md)。
