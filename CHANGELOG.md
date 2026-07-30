# Changelog

本文件记录 AgentRig 的版本变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [Unreleased]

## [0.1.0a0] - 2026-07-30

首个 V1 alpha：由 Codex/Claude Code 通过 MCP 控制测试选择与执行，平台提供可组合的
Agent 测试运行时。

### Added

- 用例、运行目标、运行配置、执行、评判和工具样本六个独立领域模块。
- 异步单用例/批量执行、多版本展开、部分跳过、重复运行、A/B 对比、取消与中断恢复标记。
- `controlled`、`proxy`、`direct` 三种工具执行模式。
- Fixture、审核样本、Simulation Curator 和真实工具 Provider 链及可配置降级。
- Simulation Curator 与 Evidence Judge 两个可选内置 Agent。
- Rule、Evidence Judge、外部 Codex/Claude Code 三类评判记录；最终状态以外部控制方为准。
- HTTP/SSE、Pixcake HTTP/SSE、OpenAI-compatible、Python 和 subprocess Driver。
- SQLite/PostgreSQL 持久化、Alembic migration、凭据引用、日志脱敏和真实工具权限边界。
- 31 个原子 MCP 工具、V1 HTTP API、React Router 管理界面和三条纵向 Demo。
- AgentScope/Pixcake 真实兼容测试，覆盖单工具、跨轮回滚和同轮连续工具调用。

### Changed

- 以领域服务和 Repository 接口替代早期单文件 Runner、旧 Transport/Mock/Judge 原型。
- 文档收敛为总体架构、实现接入与 V1 验收三份权威说明。
- 前端改为 React Router SPA，并随 wheel 打包生产静态资源。

### Removed

- 删除早期三 Agent/发布 Gate 设计、竞品草稿、旧 Demo Agent、旧 API 与重复测试体系。
- 删除旧 `judges`、`mcp_tools`、`mock`、`providers`、`storage`、`transports` 等平行实现。
