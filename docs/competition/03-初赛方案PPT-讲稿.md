# 初赛方案 PPT 讲稿

完整版共 22 页：一页纸速览 + 三 Agent 协同设计与实证 + 主叙事 + 生产实证 + 合规落地。建议陈述 8—10 分钟；正式比赛如有更短硬限制，
保留第 1、2、4、6—13 页，其余移到答辩附录。

## 01｜让 Agent 的每次变化都有证据

Agent 不缺一次成功 Demo，缺的是升级后还能回答：改了什么、行为哪里变了、为什么变、是否可以发布。
AgentRig 把一次真实决策变成可重复、可比较、可归因的评测证据。

## 02｜一页纸速览

一句话:AgentRig 是以 AgentTeams 为协同基点的多 Agent 低副作用评测与回归平台。四个评分维度
各对应一行证据:场景(公开 EditFlow + 真实生产日用)、协同(Manager/Curator/Judge 三职能,
v1.1.2 历史 Live)、Skill 工程(11 个合同 + PI 存档)、落地(CI 全绿、MIT 双仓、全部 ID 可回溯)。

## 03｜真实工具回归的两难

图片处理、支付、发信和生产写入可能昂贵、缓慢或不可逆；纯 Mock 又绕过模型、协议、Session 和
工具选择。AgentRig 的核心定位是：真实推理，受控副作用，确定性证据。

## 04｜我们控制什么，不控制什么

被测 Agent 仍由自己的模型决定是否调用工具、调用哪个工具以及参数。AgentRig 只在工具边界提供
Fixture、已审核 Sample、Simulator 或 Real Tool，并独立记录事实和裁决；它不替 Agent 回答业务问题。

## 05｜平台闭环：Identity → Asset → Run → Evidence → Gate

Target/Prompt/工具能力先冻结身份；Case 与 Profile 定义风险和副作用边界；Preview 生成 Canonical
Manifest；Run 展开 Cell 与独立 Attempt；Timeline、Rule/Judge 和 Report 形成发布证据。任何一层变化，
都应该产生新的快照或 Run，而不是覆盖历史。

## 06｜两种入口，不要求同一种方案

开发者在项目中用 Codex + Skill + AgentRig MCP 完成风险分析、用例治理和 Prompt 修改；普通用户用
AgentRig Web 助手自然语言复用已有资产。两个模型能力和上下文不同，方案不同是允许的；统一的是
Target、Case、Profile、人工确认和证据合同。

## 07｜三职能 Agent 设计

按官方指引一页讲清:Manager 目标理解与计划、Curator 受控模拟、Judge 独立裁决;任务由 Plan/Matrix
拆解,上下文按角色隔离传递(Curator 只见冻结输入,Judge 只见冻结 rubric 与脱敏证据);Rule 先做
确定性验证,Judge 补语义;异常走结构化失败与 fail-closed 门禁;审批只在 Web 人工入口。

## 08｜三角色协同实证

完整三角色闭环在 AgentTeams v1.1.2 中真实运行过:用户确认 → Plan revision → Manager 提交 →
Matrix request → Curator/Judge role MCP → response → 证据引用入 Timeline。v1.2.2 双基线兼容包
已实现、外部集群 Live 观测 Pending——我们如实标注,不用旧证据冒充新版本。

## 09｜公开场景：EditFlow 修图 Agent

EditFlow 是公开的 Agno + DeepSeek Agent，使用 PostgreSQL Session 和五个 external-execution
工具。模型推理与 HTTP/SSE 真实；本地 MCP 返回公开确定性修图结果，不上传图片、不调用图片 API。

## 10｜Before：单次成功掩盖了随机回归

headline 要求一步完成调亮、雪山背景、4:5 裁剪并保持人物。Broad Prompt 允许 `retouch_photo` 吞并
组合编辑。正式录制 Before 在同一冻结 Case 下 5 次得到 2 Pass / 3 Behavior Fail，说明“跑一次成功”不足以
作为验收依据。

## 11｜Codex + Skill：从 Prompt Diff 生成评测资产

Codex 先读取项目 `prompt-regression-governance`，再通过 MCP 查重并把 Case 分类为 Reuse、Change、
New、Exclude。真正现场新增的是“一步完成不能绕过专用工具边界”；Case/Sample 先是 Draft，只能由
人类批准。

## 12｜最小修复与身份变化

修改只触及模型可见 Prompt 和 `retouch_photo` description：像素调整、素材应用和裁剪重新分工，
每个变更步骤消费最新 `output_image_ref`。重启后 Prompt SHA 从 `43157c…9572` 变为 `71adb3…f7fd`；
HTTP 层没有关键词路由或为视频写死的答案。

## 13｜Candidate：同 Case 从 2/5 到 5/5

Candidate headline 与 Before 使用相同 Manifest 和 Case Snapshot，5/5 通过。最终六 Case 回归矩阵
`run_3afacf…` 有 6 Cells、30 个独立 Attempt，30/30 通过；简单调亮不过度路由，空素材不编造 ID，
人物约束和图片引用按契约传播。

## 14｜不只给绿灯：可以下钻到内部行为

Run 页展示 30/30；Cell 页展示五个 Attempt；Timeline 展示 `inspect_image`、`search_assets`、
`retouch_photo`、`apply_asset`、`crop_photo` 的参数、Fixture 来源与结果引用。AgentRig 验证的是内部
行为合同，而不只是最终文字或一个聚合分数。

## 15｜真实 MCP 结果如何变成零副作用回归资产

Capture Run 通过 AgentRig 调用本地 `editflow__inspect_image` 一次，持久化 `source=real_tool` 事件。
Codex 从事件创建 Draft Sample，人类审核后，Sample-only Run 五次全部命中 Sample，且该 Replay Run
中 `real_tool` Provider Attempt 为 0。真实来源和重复成本被同时治理。

## 16｜普通用户也能完成评测

Web 助手接收自然语言，生成 1 Case × 3 Attempts 的 Draft Plan。重复执行触发人工确认；确认后明确
尚未创建 Run，另一次提交才创建 `run_a1c88b…`，最终 3/3 通过。普通用户无需理解 MCP，但仍进入同一种
Run、Cell、Attempt 与证据结构。

## 17｜为什么它是平台，而不是 Demo 脚本

Driver 接入 HTTP/SSE、OpenAI-compatible、AgentScope/AG-UI；Provider 支持 Fixture、Sample、Simulator、
Real Tool；Rule/Judge、人工审核、Release Gate、生产 Trace、失败模式、耐久执行和审计日志组成可扩展
控制面。核心模块可单独使用；Manager 常驻规划，Curator/Judge 按场景条件触发。

## 18｜从 AgentScope 实践到开源闭环

AgentRig 与 AgentScope 共享同一类评测闭环经验，并复用了部分前端工作台设计，但把内部依赖抽成协议无关、
可本地部署的 MIT 开源合同。公开 EditFlow 证明可复现；真实 lassist 兼容验证证明不是只适配演示 Agent。

## 19｜真实生产使用

这套治理不是为比赛准备的:在真实生产 Agent 工程里,同一个 prompt-regression-governance Skill
由 Claude Code / Codex 以 goal 模式整段驱动——建 PI 档案、冻结基线、精读能力路由、手术级 diff
瘦身、哨兵异常归因、逐波回归。页面三张实拍:完整会话、失败归因过程、v4 终态汇总。

## 20｜生产级 PI 验收报告

PI-20260815-01(Router 上线捆绑,四表面描述瘦身 −16%):55 Cell 正式矩阵、2064 项单测基线、
v1→v4 四轮实证输入修正、既有缺口 before 归因闭环,最终 ACCEPT 带披露——语义 1 个 Cell 4/5 的
判定口径争议如实写进报告。证据不粉饰,是这套方法的核心卖点。

## 21｜合规、风险与落地计划

工具与云产品逐项披露:AgentTeams(协同基点)、Agno+DeepSeek(商业 API,密钥环境注入,可替换
任意 OpenAI 兼容模型)、Codex/Claude Code、PostgreSQL、MCP/OTLP;贡献边界(基于真实实践重构,
本次新增开源内核与公开场景);MIT+SBOM+Gitleaks;里程碑:v1.2.2 集群 Live → K8s → 容量 SLO。

## 22｜证据台账与诚实边界

正式录制硬证据：Before 2/5、Candidate headline 5/5、最终矩阵 30/30、Sample replay 5/5、Web Run 3/3、
EditFlow 34 tests、真实 Browser E2E 与 Axe 0 serious/critical。全部 Run ID 来自干净录制库并记录在台账；Sample 仅覆盖
`inspect_image`；动态引用等值以 Timeline 展示；AgentTeams 外部 Live 和目标容量不冒充本次结论。

收束句：Codex 负责思考和改变软件，AgentRig 负责把每次改变变成可复用、可执行、可追溯的评测资产。
