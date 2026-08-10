# Changelog

本文件记录 AgentRig 的版本变更。格式遵循 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，版本号遵循 [SemVer](https://semver.org/lang/zh-CN/)。

## [Unreleased]

### Changed

- 重构中英文项目首页，增加价值定位、真实界面、架构、可验证场景、分层 Quick Start、成熟度与
  文档导航，移除首页中过度密集的部署细节。
- 新增统一快速开始/安全部署手册与支持指南，重构文档门户、贡献指南、安全策略、Issue 表单和
  PR 模板，并使所有校验命令与当前 CI 保持一致。
- 补齐包和 GitHub 仓库的对外描述、文档/安全入口与主题元数据。
- 持久化数据库启动前强制校验 Alembic revision，避免 ORM 自动建表与迁移历史分叉。
- Run 选择、重复展开、CaseRun 数量及 API 分页增加部署级上限。
- V2 调用方身份默认不再信任客户端自报 Header，仅允许可信代理显式配置身份 Header。
- Target HTTP(S) 出站增加 URL、私网地址、DNS 解析和主机 allowlist 校验。
- Run 报告与 Target 数据导出改由服务端遍历完整分页生成，统一脱敏并拒绝超限或并发变化下的残缺文件。
- 本机比赛脚本不再包含个人绝对路径，并统一文档、PPT 与实际 11 项 Skill 清单。
- CI 增加锁定 Python 运行时依赖和前端依赖漏洞审计。

## [0.2.0a0] - 2026-08-01

首个 V2 alpha：在保持 V1 Core 兼容的基础上加入智能评测助手和 AgentTeams 三 Agent 协作。

### Added

- 持久化 AssistantSession/Event/Turn、EvaluationPlan 与 AgentInvocation 六张 V2 表。
- `/api/v2` 会话、事件流、计划状态机、协作健康和 Agent 调用接口，以及智能助手 Web 页面。
- Manager、Simulation Curator、Evidence Judge 三角色 AgentTeams/Matrix Bridge 集成。
- 三套最小权限角色 MCP、七项 AgentTeams Skill 和可构建的三角色部署包。
- Run 终态通知、消息/结果幂等、断线恢复、角色令牌隔离和外部协作故障投影。

### Changed

- RunPlanner 增加无副作用预览与先暂存后调度能力，EvaluationPlan 提交复用同一规划路径。
- Curator/Judge 通过稳定端口支持本地实现或 AgentTeams Worker，V1 Core 默认行为不变。
- 数据库扩展为 17 张表，版本升级至 `0.2.0a0`。

## [0.1.0a1] - 2026-07-31

第二个 V1 alpha：补齐 ACP/Goose 真实接入、部署预检、诊断证据和安全交付闭环。

### Added

- stdio ACP Driver、CaseRun MCP Proxy 注入、运行目录隔离和分级子进程清理。
- Driver/Target/Profile/Sample/Run JSON Schema 发现工具，以及 CaseRun 事件筛选分页。
- Goose `v1.45.0` + `deepseek-v4-flash` 真实兼容测试，覆盖 Fixture、approved Sample、
  多轮上下文、并发和故意失败诊断。
- Web 访问令牌设置/更新入口；API 返回 401 时自动显示认证对话框。
- GitHub Actions：Python 3.12/3.13 测试、Ruff、Mypy、前端构建、包构建和 wheel 隔离安装。
- `v*` Tag 校验版本后创建 GitHub Release 并上传 sdist/wheel；Alpha 阶段不自动发布 PyPI。

### Changed

- ACP Target 写入时即校验 command、cwd、allowlist、Secret 和隔离配置；
  `check_target` 会执行真实 initialize/session 探针。
- Run 与 CaseRun 明确区分“调度完成”和“评测通过”，前端会直接显示失败数量。
- Codex MCP 和容器 ACP 部署文档增加 Bearer Token 与
  `host.docker.internal` Proxy 安全配置。

### Fixed

- Target 版本配置改为递归合并，避免嵌套 `device_info` 父字段丢失。
- 拒绝未知 Driver 和无效 ACP options，不再把 JSON Schema 中的业务属性名误判为明文密钥。
- Driver request/session、工具前文本、Provider、validation 和工具结果事件按真实时序存档。
- Driver 执行失败改为 `evaluation_error`，取消和中断使用明确的终态语义。
- wheel 在全新工作目录执行 `agentrig db upgrade` 时自动创建默认 `.agentrig` 数据库目录。

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
