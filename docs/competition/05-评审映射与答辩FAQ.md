# 评审映射与答辩 FAQ

## 1. 评分项证据映射

| 评审项 | 权重 | AgentRig 证据 | 演示动作 |
|---|---:|---|---|
| 场景价值与行业可复制性 | 25% | Driver/Provider/Evaluator 可替换；支持不同 Agent 协议 | 从 lassist 说明扩展到客服、研发、运维 Agent 的方式 |
| 多 Agent 协同与自主闭环 | 25% | 三 Identity、Matrix 投递、Invocation 状态机、用户确认 | 展示三角色实时状态和双向 event ID |
| Skill 工程体系与生态复用 | 25% | 10 个 Skills；角色包；Schema、失败、重试和安全合同 | 打开核心 Skill 清单并演示触发链 |
| 工程落地与安全可审计 | 20% | 一键部署、MCP 隔离、RunEvent/Evaluation、脱敏、幂等 | 展示成功与失败 Run 证据及权限边界 |
| 开放/开源贡献 | 5% | MIT、README、接口契约、示例、测试、安全与贡献指南 | 展示公共仓库和全新环境启动命令 |

## 2. 常见问题

### Q1：这不就是 LLM-as-Judge 平台吗？

不是。Judge 只是可选的语义评判端口。AgentRig 的核心还包括版本化 TestCase、Target Driver、
受控工具结果 Provider、确定性 Rule、不可变 RunEvent、计划审批、幂等执行和证据引用校验。
Judge 不能覆盖 Rule，也不能发明不存在的证据。

### Q2：为什么一定需要三个 Agent？

三者的知识和权限刻意不同：Manager 有全局业务上下文但不能直接执行；Curator 能生成工具
结果但看不到评判标准；Judge 能看 rubric 和证据但不能改变执行。合并会产生自评、目标泄漏或
越权执行风险。

### Q3：AgentTeams 是否只是消息转发？

不是。Manager/Worker 身份、生命周期、工作区、Skill、Matrix 唤醒、任务状态和协作轨迹都由
AgentTeams 承载。AgentRig 保存 Matrix request/response event ID 和业务 invocation 的映射，
可以现场从数据库和房间两侧核验。

### Q4：为什么还需要 AgentRig Core？

协作框架擅长决定谁做什么，但业务事实不能只存在聊天历史里。Core 负责状态机、快照、权限、
Schema 校验、执行证据和权威结论。这样 AgentTeams 或模型重启不会改变已经发生的事实。

### Q5：模拟工具结果会不会让评测失真？

Curator 输出只是候选，必须满足工具 Schema；它看不到 rubric，不能为了通过评测优化结果。
严格一致性场景还可以选择 Fixture、已批准 Sample、真实工具 allowlist 或 observe-only 模式。

### Q6：为什么不直接调用真实工具？

企业回归中真实工具可能收费、修改数据或无法复现。AgentRig 按风险选择 Fixture、Sample、
Curator、Real Tool 或 Proxy，不用一个策略覆盖所有场景。真实工具需要配置、用例和运行时三重授权。

### Q7：RAG 在哪里？

当前场景不需要知识库 RAG。按赛题的四选二要求，我们实现了持久化会话/Agent 记忆、共享状态
管理和可观测轨迹三项。后续 RAG 通过 MCP/Skill 接入，不改变 TestCase、RunEvent 或 Evaluation
合同。

### Q8：失败如何处理？

区分测试失败、评判错误、Worker 失败和平台故障。每类都有独立状态与错误码；已有证据不被
删除；允许的传输重试复用幂等键；格式修正次数有限；不可恢复错误进入明确终态。

### Q9：项目当前真实完成度如何？

已完成 AgentTeams v1.1.2 本机部署、三角色包、Matrix/Higress/MinIO、V1 Core、V2 Web、真实
lassist 三 Agent 闭环与自动测试。云端 OTel/SLS 和 Kubernetes 是复赛增强项，不伪装为已完成。

### Q10：与 AgentScope Eval 等方案有什么区别？

AgentRig 更关注协议无关的执行控制和证据治理：被测 Agent 可以是 HTTP-SSE、OpenAI、ACP 或
subprocess；工具结果可由多种 Provider 控制；评判结论必须回到统一 RunEvent/Evaluation 事实链。
AgentTeams 是其多 Agent 协作平面，而不是替代评测内核。
