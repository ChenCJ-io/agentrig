"""导入即失败的被测模块，验证 harness 启动错误能回报给 AgentRig。"""

raise RuntimeError("agent configuration is missing")
