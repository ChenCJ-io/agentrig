# AgentRig V1 纵向 Demo

三个示例均使用内存数据库和本地确定性 Stub，不需要真实模型 Key；它们验证的是正式
Driver、执行器、Provider、Judge 和 MCP HTTP Proxy 的真实装配链路。

```bash
uv run python -m examples.v1.http_sse_controlled
uv run python -m examples.v1.openai_evidence_judge
uv run python -m examples.v1.mcp_proxy_sample_curator
```

| Demo | 覆盖链路 |
|---|---|
| `http_sse_controlled` | HTTP/SSE Driver → 工具调用 → controlled Fixture → Rule |
| `openai_evidence_judge` | OpenAI-compatible Driver → 证据归档 → Evidence Judge |
| `mcp_proxy_sample_curator` | 被测 Agent → Streamable HTTP MCP Proxy → Sample / Curator |

Demo 中的模型客户端只返回固定结构化数据。接真实服务时，仅需把 Target endpoint、
`secret_ref` 和 Profile 的模型配置改成部署值；密钥仍通过 `env:VARIABLE_NAME` 引用。
