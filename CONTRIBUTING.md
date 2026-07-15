# 贡献指南

感谢关注 AgentRig!这是一份如何参与贡献的说明。

## 开发环境

需要 Python 3.12+、[uv](https://docs.astral.sh/uv/)、Node.js 18+。

```bash
uv sync --extra dev          # 后端依赖
cd web && npm install        # 前端依赖
```

## 跑测试与检查

提交前请确保三绿:

```bash
uv run ruff check            # 代码规范
uv run mypy                  # 类型检查（strict）
uv run pytest                # 后端单测
cd web && npm run build      # 前端构建
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

## 加一条回归用例

AgentRig 的核心是「用例积累飞轮」。欢迎为被测 agent 补回归用例：

- 用前端编辑器（`/cases/new`）
- 或通过 MCP 工具（`upsert_test_case`）让 Claude Code 自主构建——装上 [`skills/core/`](./skills/) 三件套即可，见 [`docs/quickstart.md`](./docs/quickstart.md)

## 前端开发

```bash
# 终端 1：起后端
AGENTRIG_SERVER__PORT=8081 uv run agentrig serve
# 终端 2：前端热重载（vite，proxy /api → 后端）
cd web && npm run dev
```

生产构建：`cd web && npm run build`（产出 `web/dist`，由后端 `agentrig serve` 单服务挂载）。

## 代码风格

- **Python**：ruff + mypy strict；注释用中文
- **TypeScript**：strict；注释用中文
- **文档/skill**：正文中文，`description` / slogan 双语

## 目录速览

```
src/agentrig/      后端（transports / proxy / mock / judges / providers / mcp_tools / api）
web/               前端（React + Vite + Tailwind）
skills/core/       CC 测试 skill 三件套
examples/          demo_agent / sample_agent（确定性被测 agent）
docs/              设计文档 + quickstart + acceptance
```

## 行为准则

参与即视为同意遵守 [Code of Conduct](./CODE_OF_CONDUCT.md)。
