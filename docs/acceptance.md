# AgentRig 验收清单

平台核心能力的逐项验收方式。每项都可在本地一键跑出结论。

## 一键自检（推荐起点）

```bash
uv run agentrig demo
```

起内置 sample agent（`search → summarize` 两步 tool-calling），跑一条多步用例，
打印验收报告。**退出码 0 = 平台核心闭环工作正常**。一次性覆盖：真实 transport、
mock 注入、多轮 tool-calling 回路、机判。

## 验收项

| 能力 | 如何验 | 预期 |
|---|---|---|
| MCP server 起服务 | `uv run agentrig serve`，curl `ping` | `pong` |
| 真实 transport 闭环 | `uv run agentrig demo` | `tool_calls=[search, summarize]`，PASS |
| mock 注入（L0 inline） | demo 用例的 `mock` | 工具返回被 mock 替换（非真实） |
| 多层 mock（L1 剧本/L1.5 等价/L2 样本） | 单测 `tests/mock/` | 各层路由命中 |
| 机判 rule | demo 的 `tool_call_order` 断言 | `PASS` + 无 reason / `FAIL` + reason |
| proxy 录 trace + 真实样本 | 配 `PROXY__BACKENDS` + `get_real_tool_samples` | 返回真实工具返回样本 |
| 用例持久化 | `AGENTRIG_DATABASE__URL=agentrig.db` | 重启后用例仍在 |
| LLM provider（ai 判） | 配 `AGENTRIG_LLM__*` + `judge_mode=ai` | `ai_judge` 返回判定 |
| TOML 配置 | 写 `agentrig.toml` | 配置值生效 |

## 自动化测试

```bash
uv run pytest -q      # 全量单测（含 demo 验收、e2e 真实闭环）
uv run ruff check     # 规范
uv run mypy           # 类型（strict）
```

## 手动端到端（CC 经 MCP 驱动）

见 [`quickstart.md`](./quickstart.md)：起 `demo_agent` + `serve`，把 AgentRig 配进
Claude Code，让 CC 用 [`skills/core/`](../skills/) 构建并跑一条用例。

## 内置 demo agent

| agent | 路径 | 特点 |
|---|---|---|
| demo_agent | `examples/demo_agent.py` | 单步（echo/reverse），最简 |
| sample_agent | `examples/sample_agent.py` | 两步（search→summarize），多轮，`agentrig demo` 用它 |

两者都是 deterministic（不经 LLM），便于写出确定性的回归用例。
