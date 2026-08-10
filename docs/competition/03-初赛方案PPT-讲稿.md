# 初赛方案 PPT 讲稿

共 15 页：12 页主方案 + 3 页评审附录。正式陈述控制在 8 分钟，附录用于评委追问；提交版
同时提供 Keynote 终检后的 PDF 稳定版和可编辑 PPTX。

## 01｜让企业 Agent 的每次变化都有证据

Agent 不缺一次成功的 Demo，缺的是每次升级后都能回答四个问题：哪里变了、为什么通过、
证据是什么、能不能安全重跑。AgentRig 是一套多 Agent 可审计评测基础设施：AgentTeams
负责协作，AgentRig 负责事实、验证与审计。

## 02｜Agent 的风险，不止是回答错一次

真正困难的不是看到一次错误，而是事后无法复原它为什么这样做：输出存在随机性，真实工具有
成本和副作用，Judge 可能脱离运行事实，多轮状态与审批又共同影响行为。AgentRig 的目标是把
聊天质量问题，变成可以持续验证的工程问题。

## 03｜从一句目标，到一条可审计 Run

用户只描述目标。Manager 先查询 Case、Target、Profile 与历史 Run，生成可预览、可修订的计划；
用户确认必须绑定真实 user event 与同一 plan revision；系统随后执行 Rule 和 Judge，保存证据并
解释结果。关键边界只有一句：没有确认，不产生 Run。

## 04｜三种职责，三条不可越过的边界

- Manager 把目标变成可确认计划，但不能直接调用原始 `run_cases`。
- Simulation Curator 生成合理、Schema 合法的工具结果，但看不到 rubric 与预期答案。
- Evidence Judge 基于冻结证据独立裁决，但不能改执行，也不能造证据。

这不是为了凑 Agent 数量，而是同时避免越权执行、目标泄漏和执行者自评。

## 05｜AgentTeams 是运行时事实

AgentTeams v1.1.2 管理三角色的身份、生命周期和工作区；Matrix 负责定向投递与回执；MinIO 保存
版本化角色包和 Skills；Higress 隔离三套 MCP route。AgentRig 只保存协作事件与业务 invocation
之间的 event ID、hash、结果引用和终态映射，Core 不依赖 AgentTeams 的内部类型。

## 06｜两条责任链，一份权威事实

协作链从 Web Assistant、Manager、Matrix 到 Curator/Judge；事实链从 EvaluationPlan、Core Run、
Target/Driver 到 Evidence Store。两层之间只通过 Adapter 合同传递 event、hash 和 status。
任何 Agent 都不能用聊天文本改写已经发生的 RunEvent。

## 07｜可复用能力，不是一次性 Prompt

AgentRig 提供 11 个版本化 Skill：6 个 Manager、2 个 Worker、3 个 Core。每个比赛核心 Skill
不只写名称，还定义输入输出、调用条件、依赖、失败处理、安全边界、验证复用和版本回滚。
Manager、Curator、Judge 使用三套最小权限 MCP 工具集，Prompt 从来不是权限边界。

## 08｜结论必须回到证据

Case、Target、Profile 在计划阶段形成冻结快照；运行过程中只追加 RunEvent。Rule Evaluator 做
确定性断言，Evidence Judge 做语义判断，两份 Evaluation 独立存档。Judge 只能引用本次 Run
真实存在的 event ID；任何未知 `evidence_ref` 在进入事实库前都会被拒绝。

## 09｜模型提议，确定性后端放行

计划状态严格经过 `draft → confirmed → submitted`，确认绑定 user event 与 plan revision。
密钥只保存 `env:`/Secret 引用；模型和 Worker 输入统一脱敏；重复提交复用幂等键；超时、取消、
失败都是显式终态。AgentTeams 故障不会破坏 Core 与既有证据。

## 10｜真实产品，不是概念图

页面展示的是本机 lassist/Pixcake Agent 的真实运行：左侧是评测会话，中间是 Manager 诊断和
证据引用，右侧是三角色状态、当前计划与实际执行路径。成功闭环和策略回归都能追到 Run、
Evaluation 与 Matrix 双向 event ID。

## 11｜可运行、可替换、可复核

Core 在无模型、无 AgentTeams 时仍能完成确定性回归。当前快照包含 134 项后端测试、30 项 Web
单测、2 项 E2E 与 0 项历史密钥命中。Driver 支持 Pixcake、OpenAI-compatible、ACP 和 subprocess；
Driver、Provider、Evaluator、Skill、Adapter 都是可替换契约，工程包采用 MIT License。

## 12｜从“看起来能跑”到“证据足够发布”

当前已完成三 Agent 协作、成功/策略回归证据和开源工程包；下一阶段补齐可执行 Trace 报告、
恢复/性能指标与版本对比；规模化阶段再进入 PostgreSQL、Kubernetes、OTel/SLS 和发布门禁。

收束句：AgentRig 不替 Agent 做决定，而是让每次变化都留下可核验的证据。

## 13｜附录 A：三个 Agent 的身份合同

表格按角色、能力、输入、输出、依赖、决策边界和审计追踪逐项对照。评委可以直接把这些字段与
Identity 清单、MCP route、Invocation 和 Matrix event ID 交叉核验。

## 14｜附录 B：11 个 Skill 如何被工程化

左侧给出 11 个 Skill 的完整 inventory，右侧对齐官方合同字段：名称/类型、使用场景、输入、输出、
调用条件、依赖工具、失败处理、安全边界、验证/复用、版本/回滚。Skill 随 Git 版本管理，
AgentTeams 基线锁定 v1.1.2；回滚完整 Release 与角色包，不在现场热替换 Prompt。

## 15｜附录 C：上下文能力与验证台账

赛题要求四选二；当前实现 Agent 记忆、共享状态和轨迹可观测三项，RAG 对此评测场景不是必要
依赖。当前验证台账为：后端 134 passed / 6 skipped，Web 30 unit + 2 E2E，参考场景 3 个，
Gitleaks 0 命中，Curator/Judge 双向 Matrix 回执可核验。

边界同样明确：云端 OTel/SLS、Kubernetes 与公开 Release/Tag 仍未完成，不写成当前能力。
