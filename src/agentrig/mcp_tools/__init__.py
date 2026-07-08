"""MCP 工具组（六组：discovery/authoring/execution/results/verdict/observability）。

每组一个模块，提供 `register(mcp)` 把工具注册到 FastMCP。工具逻辑是纯函数
（可单测），register 是瘦封装（委托纯函数 + 全局 repo）。
"""
