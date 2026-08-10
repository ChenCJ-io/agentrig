# Security Policy / 安全策略

AgentRig 执行被测 Agent、代理工具调用并保存运行证据。鉴权绕过、Secret 泄露、SSRF、任意代码
执行、角色越权和证据完整性问题都属于安全边界的一部分。

## Supported versions / 支持版本

当前仅维护最新的 `0.2.x` Alpha：

| Version | Supported |
|---|---|
| `0.2.x` | ✅ |
| `0.1.x` | ❌ |
| `< 0.1` | ❌ |

## Report privately / 私密报告

**不要为安全漏洞创建公开 Issue，也不要在公开日志中附带凭据或业务数据。**

Please do **not** open a public issue for a vulnerability or attach secrets and business data to public logs.

使用 GitHub Private Vulnerability Reporting：

1. 打开仓库的 **Security** 页面；
2. 选择 **Report a vulnerability**；
3. 私密提交报告。

直接入口：[Create a private security advisory](https://github.com/ChenCJ-io/agentrig/security/advisories/new)。

## What to include / 报告内容

- 受影响的版本、commit 和部署方式；
- 漏洞类型与影响范围；
- 最小复现步骤或概念验证；
- 是否涉及真实 Secret、个人信息或业务数据；
- 已知缓解措施和建议修复（如有）。

请使用最小测试数据，不要扩大访问范围、破坏数据或持续访问不属于你的系统。

## Response process / 响应流程

维护者目标是在 72 小时内确认收到报告，然后在私密 Advisory 中沟通复现、严重性、修复和披露
时间。修复完成前，请不要公开漏洞细节。

## Security-relevant areas / 重点边界

以下问题应通过私密渠道报告：

- Bearer Token、Matrix Token、模型 Key 或 Target Secret 泄露；
- Target 出站策略、DNS/私网限制或工具 allowlist 绕过；
- Python/subprocess Driver 未授权代码执行；
- Manager、Curator、Judge MCP 角色越权；
- RunEvent、Evaluation、Evidence ref 或导出校验可被伪造/覆盖；
- 多租户身份、短期 Scope、日志脱敏或报告导出的隔离缺陷；
- 依赖中对 AgentRig 实际部署构成可利用影响的漏洞。

一般使用问题、功能建议和非安全 Bug 请按 [SUPPORT.md](./SUPPORT.md) 处理。
