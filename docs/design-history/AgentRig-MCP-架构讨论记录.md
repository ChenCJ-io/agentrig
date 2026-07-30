# AgentRig MCP 架构讨论记录

> 用途：只记录双方已经明确的事实和仍待讨论的问题
> 规则：未讨论、未确认的设计不写成既定方案；完整架构文档仅在明确要求时整理
> 日期：2026-07-28
> 状态：已确认决策记录；当前实现结果以 `../00-总体架构.md` 和
> `../01-核心Agent价值复核与讨论交接.md` 为准

## 已确认事实

1. 第一阶段先开发由 Claude Code/Codex 控制的 MCP 版本。
2. MCP 模式直接绕过 Regression Manager；Regression Manager 不在这条执行链路中。
3. Claude Code/Codex 根据实际改动自行选择用例。
4. 一次执行可能只跑一个用例，也可能批量跑多个用例，取决于实际场景。
5. MCP 模式中涉及的内部智能能力只有：
   - Simulation Curator
   - Evidence Judge
6. Simulation Curator 用于需要模拟工具环境的场景，不负责选择用例。
7. Evidence Judge 是可选能力，不是执行链路的必经步骤。
8. 关闭 Evidence Judge 时，Claude Code/Codex 可以直接：
   - 获取执行结果；
   - 获取运行日志或 Trace；
   - 根据这些事实自行分析成功、失败和可能原因。
9. AgentRig 必须向 Claude Code/Codex 提供足够完整的执行结果、日志和证据查询能力。
10. 完整设计采用渐进讨论方式：先讨论并确认事实，再记录；只有明确要求时才汇总成完整文档。

## 当前最小执行链路

```text
Claude Code / Codex
  → 选择一个或多个用例
  → 发起执行
  → Simulation Curator 按需补充模拟环境
  → AgentRig 执行并保存结果、日志和 Trace
  → 可选 Evidence Judge
  → Codex 读取结果并自行分析
```

## 待讨论

1. 统一执行接口的异步返回、等待和详细结果查询方式。
2. 内部统一执行记录如何组织，以及运行 ID 如何设计。
3. Codex 最少需要哪些结果、日志和 Trace 查询接口。
4. Simulation Curator 在什么条件下自动触发，什么条件下必须由 Codex 显式请求。
5. Evidence Judge 的开启方式：全局配置、单次执行参数，还是 Codex 执行后的独立调用。

## 已确认设计决策

### D1：单用例和批量共用一个执行模型

1. 对 MCP v1 而言，单用例执行是批量执行只有一个用例时的特例。
2. 核心执行接口接收一个或多个 `case_id`，不维护两套执行架构。
3. 用例会继续按版本、通道和重复次数展开成独立执行任务。
4. 执行任务使用受限并发，不串行跑完整批次。
5. MCP v1 不保留 `run_single_case` 包装工具；执行单个用例时直接调用 `run_cases` 并传入
   一个 `case_id`。

现有 AgentScope 已具备可复用的并发基础：

- `CaseBatchRunner` 使用 `asyncio.Semaphore(parallel_count)`；
- 默认并发数为 5，限制范围为 1—16；
- 每个任务单独创建 `CaseRunner + AgentSSEClient`，不共享可变会话状态。

迁移时需要保留当前单跑的优势：完整逐轮结果。合并执行入口不等于把单跑降级成只有批量摘要。

### D2：统一执行入口异步返回 Run ID

1. 无论提交一个还是多个用例，统一执行入口都不阻塞等待完成。
2. 提交成功后立即返回 `run_id`。
3. 后续通过独立的状态和结果查询接口跟踪执行。
4. 不在提交接口中增加“单用例直接等待并返回完整结果”的第二种返回语义。

### D3：执行入口同时支持明确用例和条件选择

1. 调用方可以直接传一个或多个 `case_id`。
2. 调用方也可以传 selector，按能力、工具、普通标签和审核状态等条件选择一批相关用例。
3. selector 只在提交阶段解析一次。
4. 服务端将解析后的 `resolved_case_ids` 随 `run_id` 保存并返回，执行过程中不再动态扩大或
   缩小范围。
5. 这两种方式最终进入同一个执行计划和并发执行链路。

### D4：开源 Core 支持版本维度，不内置业务通道

1. `version` 是开源 Core 的通用执行维度。
2. Pixcake 的 `chat_channel` 不进入开源 Core；通道、地区、模型 Provider 等额外矩阵维度
   由具体项目通过适配层或二开实现。
3. 调用方显式传 `version` 时，只针对该版本规划执行。
4. 调用方不传 `version` 时，按每个用例声明的全部适用版本展开任务并执行。
5. 因此一个 run 可以包含同一用例在多个版本上的独立执行结果。

### D5：部分版本不兼容时执行可运行子集

1. 显式指定版本后，只执行声明支持该版本的用例。
2. 不兼容用例不阻断其他兼容用例执行。
3. 提交结果返回结构化 `skipped_cases`，至少包含 `case_id` 和跳过原因。
4. 如果解析后没有任何可执行任务，则不创建 `run_id`，直接返回明确错误。

### D6：版本执行目标支持同地址切换和独立地址

1. 不假设所有版本都由同一个 Agent 地址提供。
2. 支持同一地址通过版本参数加载不同版本。
3. 支持不同版本配置不同的 Agent 地址或启动配置。
4. baseline/candidate 对比使用同一套版本执行目标机制，不另建专用执行链路。
5. 版本到地址、参数和接入方式的关系由用户配置，开源 Core 不写死 Pixcake 的
   `device_info` 或复合版本名协议。

### D7：同时支持注册版本和临时执行目标

1. 长期回归和 CI 可以预先注册 AgentTarget 与 TargetVersion，执行时传
   `target_version_id`。
2. Codex 本地快速验证可以直接传临时 endpoint、driver 和版本参数，不要求先在平台注册。
3. 两种输入在提交阶段统一解析成不可变的执行目标快照。
4. Run 保存实际使用的 driver、endpoint 摘要、版本参数和配置指纹，后续修改注册配置不影响
   已发生运行的解释与审计。
5. 临时配置只属于本次 Run，不自动升级为长期注册资产。

### D8：v1 覆盖多种 Agent 接入方式

v1 需要支持：

1. 通用 HTTP/SSE Agent。
2. Pixcake HTTP/SSE Agent。
3. OpenAI-compatible Agent。
4. 本地 subprocess Agent。
5. 用户自定义 Python Driver。

所有 Driver 必须将各自协议转换成统一执行事件，Core 和用例模型不直接依赖具体协议字段。

“被测 Agent 使用挂载在 MCP Server 上的业务工具”不属于 Agent Driver 类型，而属于 D10
定义的 `proxy` 工具控制模式。V1 不内置“被测 Agent 自身通过某个 MCP 工具暴露 chat/run
能力”的 Driver；特殊项目可以通过自定义 Python Driver 接入。

待确认：“支持”是要求每种 Driver 都具备完整的一等能力，还是允许部分 Driver 在 v1 标为
实验性接入。

### D9：Driver 使用基础契约与可选能力声明

1. 所有正式 Driver 必须支持：
   - 启动执行；
   - 发送用户输入；
   - 返回文本或结构化事件；
   - 报告完成或错误；
   - 超时和取消；
   - 关闭资源。
2. Driver 可以额外声明：
   - streaming；
   - multi_turn；
   - tool_call_observation；
   - tool_result_injection；
   - session_resume；
   - usage_metrics；
   - full_trace。
3. 用例声明运行所需的 Driver 能力。
4. 任务执行前进行能力匹配；缺少能力的用例进入 `skipped_cases`，并返回缺少的能力。
5. 不允许在缺少必要能力时静默降级并产生看似可信的评测结果。

### D10：v1 支持三种可配置的工具控制方式

1. `controlled`：
   - Agent 输出工具调用；
   - AgentRig 解析并提供工具结果；
   - 适用于当前 AgentScope 式外部工具循环。
2. `proxy`：
   - Agent 通过 AgentRig 提供的 MCP Proxy 调用工具；
   - AgentRig 在代理层记录、替换或放行结果。
   - 该模式覆盖被测 Agent 的业务工具挂载在 MCP Server 上的场景。
3. `observe_only`：
   - Agent 自己执行工具；
   - AgentRig 只采集可获得的日志、Trace 和结果，不注入模拟返回。
4. 工具控制方式由目标版本配置，执行时也可使用允许范围内的临时配置。
5. Simulation Curator 只适用于 `controlled` 和 `proxy`。
6. 用例要求模拟工具环境但执行目标只支持 `observe_only` 时，任务在执行前明确跳过。

### D11：工具结果使用可降级的 Provider 链

1. 工具结果来源按用户配置的 Provider 顺序解析。
2. v1 内置：
   - case fixture；
   - recorded replay；
   - approved sample；
   - intelligent simulation；
   - real tool。
3. 某个 Provider 未配置、不可用或没有匹配结果时，继续尝试下一个 Provider，不直接阻塞
   整次执行。
4. 每次工具解析保存尝试过的 Provider、未命中原因和最终来源。
5. 开源默认链路为 fixture → replay → approved sample → fail。
6. intelligent simulation 和 real tool 默认关闭，必须由用户显式启用。

### D12：Replay 与 Approved Sample 合并为 Sample Provider

1. Replay 和 Approved Sample 不再作为两个独立 Provider。
2. 两者统一由 `SampleProvider` 从样本库查询和匹配。
3. 样本库内部允许不同粒度：
   - 单次工具调用结果；
   - 有顺序的多步工具调用序列。
4. 样本记录保留来源、版本、匹配规则、审核状态和是否允许参数变形等元数据。
5. “Replay”变为 SampleProvider 的一种序列匹配方式，而不是独立架构组件。
6. 默认 Provider 链相应简化为：
   fixture → sample → fail。
7. intelligent simulation 和 real tool 仍为用户显式启用的后续 Provider。

### D13（已撤销）：样本库并入 Simulation Curator 子系统

> 本决策被 D16 取代：Sample Provider 与 Simulation Curator 保持独立。

1. 对执行引擎不再暴露独立的 Sample Provider。
2. Simulation Curator 是一个完整子系统，内部包含：
   - Sample Library：样本存储、版本约束、审核状态和来源；
   - Sample Search：按工具、参数、版本和状态检索候选；
   - Curator Agent：理解场景、选择/组合/变形样本，必要时生成候选；
   - Validator：校验输出 Schema、安全约束和多轮状态一致性；
   - Provenance Recorder：记录使用的样本、变形、模型和最终来源。
3. 用户显式指定 `sample_id` 时，Curator 直接读取该样本并校验，不需要 Agent 再做自由选择。
4. 用户未指定样本时，Curator 根据工具调用、对话、版本和当前状态检索并分析候选。
5. 对外 Provider 链简化为：
   fixture → simulation_curator → real_tool。
6. Sample Library 在代码和存储上仍是独立模块，但属于 Simulation Curator 的内部能力，不再是
   与 Curator 并列的产品概念。

### D14：用例作者构建的工具结果属于 Fixture

1. 用户在构建用例时直接填写的工具结果是该用例的 Fixture，不是 Sample Library 中的
   `sample_id`。
2. Fixture 随用例版本保存，主要用于精确控制该场景的工具返回、错误和调用顺序。
3. `sample_id` 只用于引用 Sample Provider 共享样本库中的可复用样本。
4. 用例在一次工具调用上允许三种表达：
   - 内联 Fixture：直接保存预期工具结果；
   - 指定 `sample_id`：引用共享样本；
   - 不指定结果来源：运行时交给 Simulation Curator 分析。
5. 用例 Fixture 不自动写入共享样本库，避免未经审核的数据污染其他用例。

### D15：v1 不提供 Fixture 提升为共享样本

1. 用例 Fixture 与 Sample Provider 的共享样本库保持隔离。
2. v1 不提供“将 Fixture 保存/提升为共享样本”的操作。
3. Fixture 不自动复制、同步或沉淀到样本库。
4. 共享样本只通过独立的真实结果采集或样本导入入口进入。
5. Fixture 提升和审核流程留到后续版本再讨论。

### D16：Sample Provider 与 Simulation Curator 保持独立

1. Sample Provider 负责从共享样本库做确定性检索和结果返回。
2. Simulation Curator 不负责选择共享样本，只在 Fixture 和 Sample Provider 均未命中后处理。
3. 命中多条样本时，Sample Provider 按稳定排序直接返回第一条，不调用 Agent 做选择。
4. 当前 Provider 链为：
   fixture → sample → simulation_curator → real_tool。
5. Sample Provider 的返回仍需经过统一 Schema 和安全校验。

### D17：v1 不设计样本优先级

1. Sample Provider 的匹配过程已经保证命中样本满足工具、版本、参数和可用状态要求。
2. 命中多条时按存储层定义的稳定顺序返回第一条。
3. v1 不增加 `priority`、偏好评分或 Agent 二次选样机制。
4. 结果只需记录最终使用的 `sample_id` 和匹配依据。

### D18：启用 Simulation Curator Provider 即代表允许智能生成

1. 不额外设计 `allow_synthesis` 开关。
2. Provider 链中包含 `simulation_curator` 时，表示允许它在前序 Provider 未命中后生成候选。
3. 未配置 `simulation_curator` 时，执行过程不会调用 Curator Agent。
4. Curator 生成的候选必须经过统一 Validator；只有校验通过才能作为工具结果返回。

### D19：Simulation Curator 输出校验失败时允许修正一次

1. Curator 生成的候选必须先经过统一 Validator，不合格的结果不能交给被测 Agent。
2. 首次校验失败时，将明确的校验错误反馈给 Curator，允许其修正重试。
3. 默认修正重试 1 次，即一次初始生成加一次修正；重试次数允许项目级配置。
4. 重试后仍不合格，则将本 Provider 记为不可用，并继续尝试 Provider 链中的下一项。
5. 如果后面配置了 Real Tool，则继续调用 Real Tool；如果没有可用的后续 Provider，则按工具结果解析失败处理。

### D20：Simulation Curator 与评测答案隔离

1. Curator 只接收生成合理工具结果所需的模拟上下文：
   - 工具名称、调用参数和返回 Schema；
   - 当前工具调用发生前的对话上下文；
   - 用例的场景背景和初始化数据；
   - 用户专门填写的模拟说明。
2. Curator 不接收用例的期望答案、断言和评分规则。
3. Curator 负责模拟环境反馈，不应知道什么结果会使被测 Agent 通过评测。
4. 执行层需要分别组装模拟上下文和评测上下文，避免因复用完整用例对象而意外泄漏。

### D21：Curator 在同一次用例执行中获得完整历史上下文

1. 同一次用例执行内，后一次 Curator 调用必须知道此前已经发生的全部可用上下文，而不只是当前工具参数。
2. 该上下文至少包含此前的用户/Agent 消息、工具调用、实际采用的工具结果以及已经形成的模拟状态。
3. 这样 Curator 可以保持多次工具调用之间的事实和因果一致性，例如先创建再查询。
4. 上下文只在当前 `case_run_id` 内连续；不同用例、目标版本和重复轮次之间相互隔离。
5. “完整历史上下文”仍受 D20 约束，不包含期望答案、断言或评分规则。
6. 执行引擎负责保存并组装上下文，Curator Agent 不保留跨 `case_run_id` 的隐式记忆。

### D22：Curator 在每次新运行中默认重新生成

1. 再次执行同一用例时，Simulation Curator 默认重新生成工具结果。
2. v1 不设计跨运行缓存、自动复用或自动冻结上一次 Curator 结果的机制。
3. 后续可根据成本、稳定性和复现需求再优化复用策略。

### D23：Curator 调用只保存必要的审计信息

1. 每次 Curator 调用保存最终生成的工具结果。
2. 保存实际使用的 Provider、模型和配置版本。
3. 保存各次生成尝试及 Validator 的成功或失败信息。
4. 保存对应的工具调用标识和 `case_run_id`，使其能关联回完整运行日志。
5. 完整对话沿用用例运行日志，不在 Curator 调用记录中重复复制。

### D24：保留可复用的执行配置 Profile

1. `profile_id` 表示一组可复用的执行配置，不表示被测 Agent 的运行版本。
2. 用例选择、被测目标及版本、执行配置是三个独立维度：
   - `case_ids` 或 `selector` 决定运行哪些用例；
   - `target` 和 `version` 决定测试哪个 Agent 及其版本；
   - execution profile 决定如何执行和评测。
3. Profile 可包含 Provider 链、Evidence Judge 开关、并发、超时、重试以及工具控制模式等配置。
4. `run_cases` 支持项目默认配置、`profile_id` 和本次调用覆盖，优先级为：
   本次调用覆盖 > Profile > 项目默认配置。
5. 启动运行后，将解析完成的最终配置冻结到 `run_id`。

### D25：执行入口不能修改用例定义

1. `run_cases` 只允许选择用例和调整本次执行参数，不能修改用例中的对话、Fixture、断言或期望结果。
2. 如果后续允许 Agent 修改用例，必须通过独立的用例编辑工具完成，并生成新的用例修订版本和审计记录。
3. `run_id` 始终绑定启动时解析出的用例版本；运行开始后的用例编辑不影响该次运行。
4. Codex/CC 可以提出用例修改建议，但不能在一次执行过程中暗改用例后继续运行。

### D26：V1 只有两个平台内置 Agent

1. V1 平台内部只包含两个 Agent：
   - Simulation Curator：在前序工具结果 Provider 未命中时生成候选工具结果；
   - Evidence Judge：根据执行证据进行可选的智能评判。
2. Codex/CC 是 V1 的外部控制者，负责选用例、发起或编排执行，并可自行分析结果。
3. 用例筛选、并发调度、Provider 链、Schema 校验和结果存储均为确定性服务，不包装成 Agent。
4. V1 不开发 Regression Manager 或平台内置执行助手。
5. V2 再开发一个平台内部的执行助手，承担当前 Codex/CC 的用例选择、执行编排和结果分析职责；其设计不进入 V1 实施范围。

### D27：Codex/CC 决定评判路径，不要求重复回写 Judge 结果

1. Rule、Evidence Judge 以及 Codex/CC 产生的评判结果分别保存，互不覆盖。
2. 用户查看运行详情时，可以看到每个评判器各自的输出和依据。
3. 用户启用 Evidence Judge 且 Judge 已经给出判定时，Codex/CC 可以直接认可该结果，无需重复回写一份相同结论。
4. 外部判定回写主要用于用户不想配置自己的模型 Key、主动关闭 Evidence Judge，并让 Codex/CC 根据运行证据自行判断的场景。
5. 如果 Codex/CC 主动回写外部判定，则表示控制者明确给出了本次主评测结论。
6. 执行生命周期状态与评测结论分开：
   - 执行状态由执行引擎维护，例如 queued、running、completed、failed、cancelled；
   - pass/fail 等评测结论来自本次实际采用的评判路径。

### D28：执行时显式指定主评判器

1. 不根据是否存在某种评判结果来猜测主评判路径，执行配置需要显式指定 `primary_evaluator`。
2. v1 支持三种主评判器：
   - `evidence_judge`：使用平台内置 Evidence Judge 的判定；
   - `external_controller`：关闭或不依赖 Judge，等待 Codex/CC 回写判定；
   - `rule`：使用固定规则的判定。
3. 其他评判器的结果仍可并列保存和展示，但不自动改变主结论。
4. `external_controller` 模式下，在 Codex/CC 尚未回写时显示 `awaiting_verdict`，不自动回退到 Evidence Judge。

### D29：同一批次允许不同用例使用不同主评判器

1. 每个用例可以声明自己的默认 `primary_evaluator`。
2. Execution Profile 可以为运行提供统一覆盖，本次 MCP 调用也可以临时覆盖。
3. 解析优先级为：本次调用覆盖 > Profile 覆盖 > 用例默认值。
4. 最终评判配置按每个 `case_run` 冻结，因此同一个 `run_id` 下可以同时存在 Rule、Evidence Judge 和 external controller 模式的用例。

### D30：异步运行结果采用三层查询结构

1. `get_run(run_id)` 返回批次整体状态及完成、运行中、跳过和失败等进度计数。
2. `list_case_runs(run_id)` 分页返回各用例×目标版本的执行摘要。
3. `get_case_run(case_run_id)` 返回单项的完整对话、工具调用、Provider 轨迹和各评判器结果。
4. 单个 `case_run` 完成后立即可以查询，不要求等待同一 `run_id` 下的其他任务全部结束。
5. 结果需要按 `case_run` 持续落库，不能只在整批完成后一次性保存。

### D31：V1 支持协作式取消批次运行

1. 提供 `cancel_run(run_id)`。
2. 尚未开始的 `case_run` 直接标记为 `cancelled`。
3. 已在运行的任务在下一个安全节点协作式停止，不承诺强行中断任意外部调用。
4. 已完成、失败或跳过的单项结果全部保留。
5. 批次整体状态标记为 `cancelled`，同时保留每个 `case_run` 的真实终态。
6. Real Tool 已经产生的外部副作用不自动回滚，执行记录需要明确标识相关调用及结果。

### D32：V1 不自动重跑失败用例

1. `case_run` 执行失败后直接记录为失败，平台不自动从头重跑。
2. 是否重新执行由 Codex/CC 根据失败原因和上下文决定。
3. Codex/CC 再次调用 `run_cases` 时创建普通的新 Run；V1 不设计 attempt 关联模型。
4. Simulation Curator 因候选未通过 Validator 而进行的一次修正属于单次生成过程内部，不视为用例重跑。
5. 按 Driver 能力判断幂等性、按工具副作用实施不同自动重试策略等复杂机制不进入 V1。

### D33：V1 只提供批次级并发控制

1. Execution Profile 或本次调用只设置一个批次级 `concurrency`。
2. 项目配置提供默认并发数和最大上限。
3. 未传时采用项目默认值，传入值超过项目上限时按上限执行。
4. V1 不实现按被测 Agent、版本或 Provider 分组的多级并发限制。
5. 特殊目标的限流由对应 Driver 自行处理；限流导致的执行失败正常记录，由 Codex/CC 决定是否重跑。

### D34：MCP 支持创建用例，并保护已审核用例不被删除

1. V1 MCP 提供明确的用例创建能力。
2. 用例创建与用例执行是两个独立操作；`run_cases` 不能在执行过程中创建或修改用例。
3. V1 MCP 也提供删除用例的能力。
4. Codex/CC 只能删除尚未通过人工审核的用例。
5. 人工审核通过的用例不能通过 MCP 删除。
6. 已审核用例是否需要废弃、归档或由人工解除审核，后续在用例生命周期设计中单独确定。

### D35：MCP 只能修改未审核用例

1. Codex/CC 可以通过 MCP 修改尚未通过人工审核的用例。
2. 人工审核通过的用例不能通过 MCP 直接修改。
3. 调整已审核用例需要人工操作；“基于已审核用例创建新草稿版本”作为后续能力再设计。
4. 用例修改不影响已经启动的 `run_id`，运行始终使用启动时冻结的用例快照。

### D36：V1 用例采用三种审核状态

1. `draft`：草稿，可由 MCP 修改或删除。
2. `approved`：人工审核通过，MCP 不可修改或删除。
3. `rejected`：人工驳回，可由 MCP 根据审核意见继续修改或删除。
4. V1 暂不增加独立的“待审核”状态，避免引入额外提交流程。
5. 审核通过或驳回只能由人工在平台界面操作，MCP 不能自行批准用例。

### D37：未审核用例也允许执行

1. `draft`、`approved` 和 `rejected` 状态的用例都允许执行。
2. 执行草稿或被驳回用例用于调试和验证，不代表该用例已经通过人工审核。
3. 运行记录需要保存启动时的用例审核状态和内容快照。

### D38：selector 默认排除被驳回用例

1. selector 未显式传入审核状态时，默认包含 `draft` 和 `approved`。
2. selector 默认排除 `rejected`，避免批量执行时混入已经被人工判定为不适用的用例。
3. 调用方显式指定 `review_status` 时，可以选择 `rejected`。
4. 明确传入 `case_ids` 时不应用 selector 的默认审核状态过滤。

### D39：V1 不增加用例集，沿用能力标签组织相关用例

1. V1 不设计独立的“用例集”或 Suite 实体。
2. 相关用例通过 `cap.<能力或工具名>` 形式的能力标签组织，一个用例可以拥有多个能力标签。
3. MCP 提供能力标签列表及覆盖数量，并支持 selector 按一个或多个能力标签选择用例。
4. 按工具寻找相关用例时，可以同时使用人工维护的 `cap.*` 标签和用例轮次中的预期工具信息补充召回。
5. 调用方需要完全精确控制时仍直接传 `case_ids`。
6. 该设计沿用当前 AgentScope 已有的 `list_tags`、能力筛选、`find_cases_by_tool` 和 selector 能力，不新增一套分组模型。

### D40：能力标签不强制对应真实工具

1. `cap.*` 表示用户定义的能力分类，不与工具注册表强绑定。
2. 工具型能力、业务行为、纯文本能力和安全行为都可以使用能力标签。
3. 例如 `cap.search`、`cap.order.create`、`cap.clarification` 和 `cap.safety.refusal` 均为合法能力标签。
4. 平台可以根据工具名建议能力标签，但不能限制用户只能使用已注册工具名。

### D41：能力标签直接保存在用例中，不建设标签注册表

1. Codex/CC 创建或修改未审核用例时，可以直接传入任意合法的 `cap.*` 字符串。
2. V1 不创建独立标签记录，也不维护标签显示名称、说明、颜色等元数据。
3. `list_tags` 从现有用例中动态聚合唯一标签和使用数量。
4. 后续出现明确的标签治理需求时，再增加标签注册表。

### D42：用例继续采用多轮对话模型

1. 一个用例包含初始化上下文和一个或多个用户轮次。
2. 每个用户轮次可以配置自己的 Fixture、模拟说明和评测要求。
3. 被测 Agent 在一个用户轮次中可以进行多次工具调用。
4. 当前轮 Agent 完成响应后，执行器再发送下一轮用户消息。
5. 同一次用例执行中的全部轮次共享对话历史和模拟状态。

### D43：初始化数据由集成方自由定义

1. `initial_state` 是开放配置的任意 JSON 对象，AgentRig 核心不规定内部业务字段。
2. 核心层完整保存和传递未知字段，不解释 Pixcake 或其他业务语义。
3. Driver 在启动用例时通过初始化钩子自行处理，例如创建业务对象、准备数据库、挂载文件或建立会话。
4. Driver 可以提供自己的 Schema 做提前校验，但该能力不是所有 Driver 的强制要求。
5. 文件和密钥使用引用，不在用例中直接保存二进制内容或明文密钥。
6. 启动运行后，将实际使用的初始化数据冻结到对应 `case_run`。

### D44：自定义 Driver 通过本地插件类加载

1. AgentRig 提供 HTTP/SSE、OpenAI-compatible、MCP 等内置 Driver。
2. 特殊业务可以在配置中声明本地 Python 插件入口，例如 `my_package.driver:MyAgentDriver`，无需修改核心代码。
3. Driver 的 `options` 为开放配置，由具体 Driver 自行定义和校验。
4. V1 只加载部署环境中已经安装的本地代码，不允许通过 MCP 动态上传并执行 Python 代码。
5. 修改 Driver 实现或加载配置后，通过重启服务生效；V1 不实现运行时代码热加载。

### D45：部署配置、用户数据与密钥分开存放

1. 配置文件保存数据库连接、并发上限、项目默认值和允许加载的 Driver 插件等部署级配置。
2. 数据库保存被测目标、版本、Execution Profile、用例、样本和运行记录等用户可管理数据。
3. API Key、Token 等敏感信息只保存在环境变量中。
4. 数据库、Profile 和用例中只保存 `secret_ref`，不保存明文密钥。
5. UI 可以动态维护数据库中的目标与 Profile，但不能通过普通业务操作改变插件加载白名单等部署级配置。

### D46：V1 同时支持 SQLite 和 PostgreSQL

1. SQLite 用于个人使用和快速启动。
2. PostgreSQL 用于正式部署、多人使用和较高并发。
3. 两种数据库复用统一的数据模型，并通过 SQLAlchemy 和 Alembic 管理访问与迁移。
4. V1 不支持 MySQL，避免扩大兼容实现和测试范围。

### D47：V1 使用进程内异步调度器

1. V1 使用进程内 `asyncio` 调度器执行异步运行，不依赖 Redis 或 Celery。
2. 启动请求先落库，再立即返回 `run_id`，后台按批次级并发配置执行。
3. 服务重启时，将尚未结束的任务标记为 `interrupted`，不自动恢复或重跑。
4. 重启前已经完成并落库的单项结果继续保留。
5. V1 调度服务按单进程运行，不支持多个服务进程共同消费任务。
6. 核心代码定义 `RunScheduler` 接口，后续可以增加外部队列或分布式实现。

### D48：MCP 与 HTTP 是共享核心服务的薄入口

1. MCP 工具只负责参数接收、权限上下文传递和结果投影，不承载用例选择、执行或评判业务逻辑。
2. HTTP API 同样作为薄入口。
3. MCP、HTTP、后续 UI 和 V2 平台助手共同调用同一套应用服务。
4. 用例、运行、结果、评判、Driver、Provider 和持久化逻辑不能复制到不同入口中。

### D49：V1 后端采用单进程、同端口部署

1. 一个 AgentRig 后端进程同时承载 `/mcp/`、`/api/`、健康检查和进程内 `RunScheduler`。
2. MCP 与 HTTP 共用数据库连接、配置、应用服务和调度状态。
3. Web 前端保持独立工程，通过 `/api/` 调用后端。
4. V1 不把 MCP、HTTP API 和调度器拆成多个后端服务。

### D50：V1 采用单工作区和可选访问 Token

1. V1 按单工作区部署，不实现账号、组织隔离和复杂角色权限。
2. MCP 和 HTTP API 支持配置统一访问 Token；仅本地使用时可以关闭。
3. 人工审核接口只通过 Web/HTTP API 提供，不暴露为 MCP 工具。
4. Codex/CC 即使持有 MCP 访问 Token，也不能通过 MCP 将用例设为 `approved` 或 `rejected`。
5. 多用户、组织隔离和 RBAC 留到后续版本。

### D51：V1 的两个 Agent 作为独立专用组件实现

1. V1 不引入多 Agent 调度框架。
2. Simulation Curator 和 Evidence Judge 分别实现清晰的生成与评判接口。
3. 两者各自拥有独立的 Prompt、输入输出 Schema、模型配置和版本记录。
4. 两者共用可替换的模型调用接口。
5. V1 首先支持 OpenAI-compatible 模型服务，可配置 base URL、model 和 `secret_ref`。
6. V2 的平台执行助手可以复用和调用这两个 Agent，但该助手不进入 V1。

### D52：Evidence Judge 不使用数值评分

1. Evidence Judge 的 `verdict` 只允许 `pass`、`fail` 或 `inconclusive`。
2. 输出包含简短结论 `summary`。
3. 输出包含每条评测要求的判断结果及其 `evidence_refs`。
4. `evidence_refs` 引用具体消息、工具调用或校验记录，不能只给无依据结论。
5. 保存实际使用的 Judge 配置和模型版本。
6. V1 不提供数值评分字段。

### D53：Evidence Judge 读取完整评测证据，但不接触密钥

1. Judge 输入包含启动时冻结的用例内容和评测要求。
2. 输入包含完整对话、工具调用和工具结果。
3. 输入包含工具结果实际来自 Fixture、Sample、Curator 或 Real Tool 的来源记录。
4. 输入包含 Schema 校验、Rule 评判、执行异常、超时和跳过原因。
5. API Key、认证头和 Driver 内部密钥不能进入 Judge 上下文。
6. Evidence 在持久化和传入 Judge 前完成统一脱敏。

### D54：Judge 调用失败不等同于用例评测失败

1. Evidence Judge 输出格式不合格时，将校验错误反馈给 Judge，默认允许修正 1 次。
2. 修正后仍不合格，或模型调用本身失败时，记录 `evaluation_error`。
3. `evaluation_error` 不能伪装成 `fail` 或 `inconclusive`。
4. 被测 Agent 已经正常执行完成时，用例执行状态仍为 `completed`。
5. Judge 失败后，该用例的主评测结论暂时不可用；Codex/CC 可以提交外部判定。

### D55：外部判定与 Evidence Judge 使用同一结果结构

1. Codex/CC 外部判定的 `verdict` 同样只允许 `pass`、`fail` 或 `inconclusive`。
2. 外部判定包含 `summary` 和 `evidence_refs`。
3. 平台自动记录来源是 Codex 或 Claude Code、提交时间和对应 `case_run_id`。
4. 外部判定不使用数值评分。
5. 外部判定可以重写该 `case_run` 当前的 Codex/CC 判定，但不能修改原始消息、工具调用、
   校验结果或其他执行证据。

### D56：每个 case_run 只保留一份当前外部判定

1. Codex/CC 可以再次提交外部判定以修正此前结果。
2. 每个 `case_run` 只保留一份当前 Codex/CC 判定，再次提交时直接重写该判定。
3. V1 不设计 `supersedes_evaluation_id` 或外部判定版本链。
4. 重写外部判定不影响 Evidence Judge、Rule 或任何原始执行证据。

### D57：Judge 的模型重试不产生多份评判记录

1. Evidence Judge 对模型调用或输出格式进行重试，属于同一次评判过程。
2. 一次 `case_run` 的一次 Judge 评判最终只形成一份 Judge 结果或一份 `evaluation_error`。
3. V1 不提供 Evidence Judge 多次重判和新旧 Judge 结果替代机制。
4. Rule 在一次 `case_run` 中也只计算并保存一次。
5. Codex/CC 外部判定也只保留当前结果，不维护历史替代链。

### D58：V1 Rule Judge 使用有限的结构化断言

1. 支持检查首个动作是调用工具、只回复文本或拒绝。
2. 支持检查必须调用和禁止调用的工具。
3. 支持检查工具调用顺序。
4. 支持工具参数与期望值匹配，或通过指定 JSON Schema。
5. 支持回复文本包含指定内容或匹配正则。
6. 支持检查执行过程没有异常。
7. 规则既可以配置到具体用户轮次，也可以配置为整个多轮用例的规则。
8. V1 不提供脚本断言或通用可编程表达式语言。

### D59：运行前校验主评判器配置

1. `primary_evaluator=rule` 时，用例至少需要一条结构化断言。
2. `primary_evaluator=evidence_judge` 时，用例至少需要自然语言评测要求。
3. `primary_evaluator=external_controller` 时，允许没有预设评测要求，由 Codex/CC 根据完整证据判断。
4. 缺少必要评判配置时不调用被测 Agent，将该执行项记为 `skipped`，原因是 `invalid_evaluation_config`。
5. 不能因为用例没有断言或评测要求而自动判定为通过。

### D60：Fixture 采用有序、默认一次性消费的匹配方式

1. 每个用户轮次可以保存一个有序 Fixture 列表。
2. Fixture 按工具名和可选参数条件匹配。
3. 默认返回第一个尚未消费且匹配的 Fixture，并在当前 `case_run` 中将其标记为已消费。
4. 需要多次返回同一结果时，可以显式设置 `repeatable=true`。
5. 当前轮没有可用 Fixture 时，继续进入 Provider 链的 Sample Provider。

### D61：Sample 参数匹配只使用规范化后的精确比较

1. Sample Provider 默认对工具调用 JSON 参数规范化后进行精确匹配。
2. 每个工具可以配置需要忽略的动态字段，例如时间戳或 request id。
3. V1 不加载自定义参数等价判断插件。
4. Sample Provider 不调用 LLM 进行模糊匹配或二次选样。
5. 特殊业务优先使用 Fixture；后续确认忽略字段仍不能满足需求时，再增加 Sample Matcher 插件。
6. 运行记录保存实际使用的匹配规则和命中的 `sample_id`。

### D62：共享 Sample 只有人工审核通过后才能命中

1. 从 Real Tool 采集或由用户导入的 Sample 初始状态为 `draft`。
2. 人工确认后，Sample 状态变为 `approved`。
3. Sample Provider 只查询和返回 `approved` Sample。
4. 不再使用的 Sample 标记为 `disabled`，不物理删除，以保留历史运行引用。
5. MCP 可以创建和维护草稿 Sample，但不能自行将 Sample 批准为可用。

### D63：Real Tool 只有用户双重授权后才能调用

1. 项目部署配置必须明确允许调用的真实工具或工具服务器。
2. 本次使用的 Execution Profile 必须显式将 `real_tool` 放入 Provider 链。
3. 缺少任一层授权时，执行引擎都不能调用真实工具。
4. 默认允许列表为空，开箱状态不会进行任何真实工具调用。
5. 运行记录明确标记所有 Real Tool 调用及其潜在副作用。

### D64：Real Tool 结果不会自动进入 Sample 库

1. Real Tool 的工具调用和返回结果自动保存为本次运行证据。
2. Real Tool 返回值不会自动创建共享 Sample。
3. 用户明确选择某次工具调用后，平台才基于该结果创建 Sample 草稿。
4. 由真实结果创建的 Sample 仍需人工审核通过后，才能被 Sample Provider 命中。

### D65：V1 按新架构重构，不维护 Alpha 内部兼容

1. 当前 Alpha 代码作为能力参考和可复用测试资产来源，不作为必须保持的模块边界。
2. 允许重构内部 Python API、领域模型和数据库结构。
3. 不围绕现有 `simulator`、`mock`、`providers`、`transports` 等重叠概念继续打补丁。
4. MCP 层不为当前 Alpha 入口保留兼容包装。

### D66：代码采用按业务能力拆分的模块化单体

1. 仓库级目录采用常规结构：`src/`、`web/`、`migrations/`、`tests/` 和 `docs/`。
2. Python 后端按业务能力拆分：
   - `cases`：用例、轮次、能力标签和人工审核；
   - `runs`：执行计划、调度、单项执行和运行证据；
   - `tool_results`：Fixture、Sample、Provider 链和结果校验；
   - `evaluations`：Rule、外部判定和主评测结论；
   - `targets`：被测目标、版本、Driver 接口和内置 Driver；
   - `agents`：Simulation Curator、Evidence Judge 和模型调用接口；
   - `profiles`：Execution Profile 和配置解析；
   - `infrastructure`：数据库、部署配置、密钥和日志；
   - `api`、`mcp`、`cli`：三个薄入口。
3. `api`、`mcp` 和 `cli` 只能调用各业务模块公开的 Service。
4. 业务模块不能反向依赖入口。
5. SQLAlchemy、环境变量等实现细节集中在 `infrastructure`，不渗入业务模型。
6. Web 前端保持为仓库根目录下的独立工程，通过 HTTP API 使用同一套后端服务。

### D67：V1 先完成 MCP 后端，再接通核心管理界面

1. V1 第一阶段完成业务模块重构、数据库、HTTP API 和 Codex/CC 使用的 MCP。
2. V1 第二阶段接通核心 Web 管理界面。
3. V1 完成标准包含：
   - 用例列表、编辑和人工审核；
   - Target、版本和 Execution Profile 配置；
   - 发起运行、查看进度和单项详情；
   - 分别展示 Rule、Evidence Judge 和 Codex/CC 的结论；
   - Sample 草稿和人工审核。
4. 平台内置的对话式执行助手仍属于 V2，不进入 V1。

### D68：MCP 用例与发现工具组

V1 提供以下工具：

1. `list_tags`
2. `list_test_cases`
3. `get_test_case`
4. `find_cases_by_tool`
5. `get_test_case_schema`
6. `create_test_case`
7. `update_test_case`
8. `delete_test_case`

补充边界：

- `get_test_case_schema` 返回当前可写字段、Fixture 和评测规则结构；
- `update_test_case` 与 `delete_test_case` 只能操作 `draft` 或 `rejected`；
- MCP 不提供批准或驳回用例的工具。

### D69：MCP 执行与结果工具组

V1 提供以下工具：

1. `check_target`
2. `run_cases`
3. `get_run`
4. `list_case_runs`
5. `get_case_run`
6. `cancel_run`
7. `submit_external_verdict`

补充边界：

- `run_cases` 是统一执行入口；
- 单用例执行直接调用 `run_cases` 并传入一个 `case_id`；
- 重跑不增加独立工具或 attempt 关联，Codex/CC 直接再次调用 `run_cases`；
- `submit_external_verdict` 重写该 `case_run` 当前的外部判定，不修改运行证据。

### D70：MCP 允许管理被测目标和执行方案

1. V1 MCP 提供 Target 的列表、详情、创建、修改和删除能力。
2. V1 MCP 提供 Execution Profile 的列表、详情、创建、修改和删除能力。
3. Codex/CC 仍可以在 `run_cases` 中传入临时 Target 和本次运行配置覆盖。
4. Target 的 Driver `options` 和 Profile 的执行配置保持高度可扩展。
5. MCP 只能保存 `secret_ref`，不能提交或读取明文密钥。
6. 已启动的运行使用冻结快照，后续修改 Target 或 Profile 不影响该次运行。
7. Web 界面显示“被测目标”和“执行方案”，代码中使用 `Target` 和 `ExecutionProfile`。

### D71：Target/Profile 直接删除，不设计恢复状态

1. `delete_target` 和 `delete_execution_profile` 直接删除对应的已保存配置。
2. 已启动运行使用自己的冻结快照，不受原 Target 或 Execution Profile 删除影响。
3. 历史运行继续通过快照展示当时使用的名称和完整配置。
4. V1 不为 Target/Profile 设计停用、隐藏、恢复或重新启用状态；需要时重新创建配置。

### D72：MCP Sample 工具组只维护草稿

V1 提供以下工具：

1. `list_samples`
2. `get_sample`
3. `create_sample`
4. `update_sample`
5. `delete_sample`

补充边界：

- MCP 创建的 Sample 状态一律为 `draft`；
- MCP 只能修改或删除 `draft` Sample；
- `approved` Sample 不能由 MCP 修改或停用；
- 批准 Sample 以及停用已批准 Sample 只能由人工在 Web/HTTP API 操作；
- `create_sample` 既可以直接接收样本内容，也可以接收 `source_tool_call_id` 从 Real Tool
  运行证据创建草稿，不自动批准。

### D73：A/B 两边的 Curator 独立生成，不共享动态结果

1. A/B 的每个 `case_run` 保持独立模拟上下文和状态。
2. Simulation Curator 根据各自分支此前的完整上下文独立生成工具结果。
3. V1 不在 A/B 分支之间共享或缓存 Curator 结果。
4. 一般情况下，两边面对相近工具调用时生成结果不会出现本质差异；运行记录仍需保存各自的 Provider 来源和生成结果，供用户识别环境差异。
5. 用户需要严格相同的工具环境时，应使用明确的 Fixture 或已批准 Sample，而不是依赖动态 Curator。

### D74：A/B 只保存配对关系和两边原子结果

1. baseline 和 candidate 分别正常执行，并分别产生自己的 Rule、Evidence Judge 或外部评判结果。
2. 系统使用 `comparison_pair_id` 关联两边对应的 `case_run`。
3. V1 后端不计算主结论变化、工具调用差异、文本差异或时延差异。
4. V1 不建设 Comparison Engine，也不额外调用对比 Judge。
5. Codex/CC 或前端读取两边原子运行结果后自行比较。
6. 后续出现明确需求时，再增加专门的差异计算能力。

### D75：MCP 优先提供原子工具，不增加重复的聚合入口

1. 不增加 `get_comparison_pair`；Codex/CC 通过 `list_case_runs` 和 `get_case_run` 读取两边结果并自行比较。
2. 不增加 `run_single_case`；`run_cases` 同时覆盖一个和多个用例。
3. 不增加 `create_sample_from_tool_call`；统一由 `create_sample` 接收不同来源。
4. 不增加重跑专用工具或 attempt 关联模型。
5. MCP 工具只有在能够减少必要的底层协议处理、权限检查或大体量数据传输时才新增，不能仅为了替 Codex/CC 编排多个已有原子操作。
6. V1 不增加单独的 MCP Agent Driver；被测 Agent 使用 MCP 业务工具由 `proxy` 模式处理，
   被测 Agent 自身通过 MCP 暴露执行入口的特殊情况交给自定义 Python Driver。
7. V1 不增加 A/B 差异聚合服务，只保存配对标识和两边结果。

### D76：Driver 按正式支持与实验性支持区分

1. V1 正式支持通用 HTTP/SSE、Pixcake HTTP/SSE、OpenAI-compatible 和自定义 Python Driver 接口。
2. 本地 subprocess Driver 在 V1 标记为实验性。
3. subprocess Driver 只保证其明确声明的基础能力，不承诺统一支持 streaming、多轮会话和工具结果注入。
4. 所有 Driver 继续通过能力声明与用例要求进行运行前匹配，不支持的执行项明确跳过。

### D77：运行证据使用按 case_run 追加的统一事件流

1. 每个 `case_run` 拥有按 `seq` 递增的事件流。
2. 事件最小字段为 `event_id`、`case_run_id`、`seq`、`event_type`、`payload` 和 `created_at`。
3. 用户消息、Agent 消息、工具调用、Provider 尝试、工具结果、校验和错误等事实通过不同 `event_type` 保存。
4. `case_run` 自身只保存执行状态、关键摘要和冻结配置。
5. 各评判器结果单独保存，其 `evidence_refs` 直接引用事件 ID。
6. V1 不为每种 Trace 事实分别建设复杂的专用表。

### D78：V1 不建设用例修订历史

1. `draft` 和 `rejected` 用例直接原地修改。
2. `approved` 用例保持不可修改。
3. 每次运行将当时的完整用例保存到 `case_run.case_snapshot`。
4. 历史运行依靠自己的快照解释，不依赖当前用例内容。
5. “基于已审核用例创建新修订版本”留到出现明确需求后再设计。

### D79：持久化语义事件，不保存逐 Token 原始帧

1. Driver 可以在内部接收逐 Token 或 SSE 分片。
2. 文本分片在内存中合并后，作为完整 `assistant_message` 事件保存。
3. 工具调用、Provider 尝试、工具结果和错误仍分别及时落库。
4. V1 默认不保存完整的底层 HTTP/SSE 原始帧。
5. 只保存规范化证据和必要的脱敏调试元数据，避免运行记录被大量流式分片撑大。

### D80：执行状态与评测结论使用独立状态模型

1. Run 状态为 `queued`、`running`、`completed`、`cancelled`、`interrupted` 或 `failed`。
2. CaseRun 状态为 `queued`、`running`、`completed`、`failed`、`skipped`、`cancelled` 或 `interrupted`。
3. 被测 Agent 正常执行结束时，即使评测结论为 `fail`，CaseRun 状态仍为 `completed`。
4. 部分 CaseRun 失败或跳过时，父 Run 在全部单项收尾后仍为 `completed`。
5. 父 Run 的 `failed` 只表示执行计划或调度器本身发生致命错误。
6. 评测结论独立使用 `pass`、`fail`、`inconclusive`、`awaiting_verdict` 或 `evaluation_error`。

### D81：V1 只保留两层超时

1. `case_timeout_seconds` 限制整个 `case_run` 的总执行时间。
2. Driver、Real Tool、Simulation Curator 和 Evidence Judge 分别在自身配置中设置单次请求超时。
3. V1 不增加轮次超时或 Provider 链总超时等更多层级。
4. 任一超时都记录具体组件和结构化错误码，不自动重试。
5. 被测 Agent 因超时未正常完成时，CaseRun 状态为 `failed`。

### D82：运行证据在落库前统一脱敏

1. 统一脱敏组件默认遮盖 `authorization`、`cookie`、`api_key`、`token` 和 `secret` 等常见敏感键。
2. 项目配置可以增加需要遮盖的 JSON 字段路径。
3. Driver 可以声明额外的敏感字段。
4. 事件在持久化前统一将敏感值替换为 `[REDACTED]`。
5. Curator、Judge、MCP、HTTP 和 Web 只能访问脱敏后的证据。
6. V1 不另外保存原始敏感副本。

### D83：V1 的 secret_ref 只支持环境变量

1. `secret_ref` 使用 `env:VARIABLE_NAME` 格式引用环境变量。
2. V1 不接入 Vault、云厂商 Secret Manager 或自定义 Secret Resolver。
3. 后续出现明确部署需求时，再扩展密钥解析接口。

### D84：版本是只做精确匹配的不透明字符串

1. AgentRig 不要求版本符合 SemVer；分支名、Git commit、模型和 Prompt 版本组合等字符串均可使用。
2. 用例的 `supported_versions` 未填写或包含 `*` 时，表示支持本次 Target 的全部版本。
3. 用例明确填写版本列表时，只支持完全匹配的版本。
4. `run_cases` 未指定版本时，执行 Target 可用版本与用例支持版本的交集。
5. V1 不实现版本范围比较、大小排序或自动推断兼容关系。

### D85：V1 用例暂不绑定 Target

1. 用例只描述场景、轮次、Fixture、评测要求和支持版本，不保存所属 Target。
2. `run_cases` 在执行时组合用例与注册或临时 Target。
3. 同一用例可以运行在不同 Target 或 A/B 两边。
4. 平台只校验版本兼容性和 Driver 能力，不判断用例属于哪个 Agent。
5. V1 以单个逻辑 Agent 的回归为主要场景；多 Agent 评测及用例归属模型留到后续设计。

### D86：未指定运行版本时默认按用例支持版本全部展开

1. `run_cases` 明确传入 version 时，只规划该版本。
2. `run_cases` 未传 version 时，按每个用例的 `supported_versions` 全部展开。
3. Target 为某版本配置了独立地址或启动参数时，使用该版本配置。
4. Target 没有单独配置某个用例版本时，使用默认 Target 配置，并由 Driver 透传该版本参数。
5. 用例支持 `*` 且 Target 登记了多个版本时，执行 Target 登记的全部版本。
6. 只有用例和 Target 都没有任何版本信息时，才规划一个无版本执行项。

### D87：selector 使用字段内 OR、字段间 AND

1. 同一 selector 字段中的多个值使用 OR 语义。
2. 不同 selector 字段之间使用 AND 语义。
3. 按工具筛选时，同时检查 `cap.<tool>` 标签和轮次中的预期工具信息，再与其他字段做 AND。
4. V1 不支持嵌套布尔表达式或自定义查询语言。
5. selector 仍只在提交时解析一次，并将最终用例 ID 冻结到 Run。

### D88：L0-L4 等分类作为普通标签

1. V1 不建设独立的 Level 字段、筛选轴或注册表。
2. `L0` 至 `L4`、优先级和来源等分类直接作为普通 tag 保存。
3. 只有 `cap.*` 前缀用于识别能力标签，其余标签都按普通字符串处理。
4. selector 通过 `tags` 字段筛选这些分类，不提供独立 `level` 参数。

### D89：V1 数据库控制在 11 张核心表

1. 用例相关：`test_cases`、`case_turns`、`case_tags`。
2. 样本相关：`samples`。
3. 执行配置相关：`targets`、`target_versions`、`execution_profiles`。
4. 运行相关：`runs`、`case_runs`、`run_events`、`evaluations`。
5. Fixture 和评测要求等轮次内容保存在 `case_turns` 的 JSON 字段中。
6. Sample 的单次结果或有序序列保存在 `samples` 的 JSON 内容中。
7. Profile 的 Provider 链和运行配置保存为 JSON。
8. V1 不创建标签注册、用例修订、重跑 attempt、A/B 差异、用户组织等附加表。

### D90：V1 通过轮询查询运行进度

1. MCP 通过 `get_run`、`list_case_runs` 和 `get_case_run` 轮询运行进度与结果。
2. Web 前端同样使用 HTTP 定时查询。
3. V1 不提供 Run 进度 WebSocket 或 SSE 推送。
4. 被测 Agent 自身使用 HTTP/SSE 属于 Driver 协议，与平台运行进度通知无关。

## 暂不作为当前结论

此前输出的总体架构、评审版和工程附录属于探索性草稿，其中关于 EvaluationJob、RunSpec、
完整状态机、Web Assistant 和 AgentTeams 的内容尚未逐项确认，不能视为当前实施依据。

## 现有 AgentScope 实现核对

核对时间：2026-07-28。事实来源为当前运行中的 `http://localhost:8002/mcp/`、AgentScope
活文档和 `ts-agent-scope/mcp_tools/` 源码。

### 当前 MCP

1. MCP 服务名为 `pixcake-agent-scope`，当前运行版本为 `1.27.2`。
2. 服务采用 stateless streamable HTTP，MCP 工具是平台 REST/查询能力的薄入口。
3. 当前实际暴露 24 个工具，分为六组：
   - 用例发现；
   - 单用例/批量执行；
   - 结果查询；
   - 用例与真实样本构建；
   - Codex 外部判定回写；
   - 生产错误观测。
4. 当前没有 MCP prompts 和 resources。
5. 活文档中的工具数量存在漂移：`MCP工具.md` 写 22 个，`CLAUDE.md` 写 18 个；运行服务
   实际为 24 个。

### 单用例与批量是两种实际入口

1. `run_single_case`：
   - 阻塞执行一个用例；
   - 返回逐轮 `agent_text`、工具调用及参数、参数校验、`chat_request` 和时延；
   - 适合修改后的快速复验和失败深读。
2. `run_tests`：
   - 接收明确的 `case_ids`，或由 Codex 给 selector；
   - 异步返回 batch run id；
   - 支持重复运行、版本×通道矩阵和 A/B；
   - 批量结果只保留精简投影，不提供完整逐轮明细。
3. 平台内部复用执行和批量结果表，但 MCP 没有要求 Codex 先创建统一的 EvaluationJob。

### Evidence Judge 当前就是可选项

1. 单用例通过 `enable_llm_eval=false` 关闭 AI Judge。
2. 批量通过 `config.use_ai_evaluation=false` 关闭 AI Judge。
3. 关闭后 Codex 可以读取单跑的完整逐轮事实并自行判定。
4. `submit_external_verdict` 支持 Codex 将 `pass/fail + reason` 回写留痕。
5. 外部判定与平台内嵌 Rule/AI 判定共存，不覆盖原判定，也不代替用例 review/approve。

### Simulation Curator 的现有雏形

当前没有名为 Simulation Curator 的独立 Agent 或 MCP 工具。已有能力位于执行器内部的
`ToolMockHub`：

```text
L0  用例 turn 内联 mock
  → L1 生产剧本/客户端结果回放及参数等价变形
  → L2 已审核真实工具结果样本
  → L3 preset 或 Qwen 智能模拟兜底
```

它在被测 Agent 发出工具调用时自动解析工具结果。现状已经具备 Curator 的部分能力，但尚未
形成独立身份、显式请求、候选审核或冻结流程。

### 用例选择权的现状

1. `list_tags`、`list_test_cases`、`find_cases_by_tool`、`get_test_case` 只提供发现原子能力。
2. 读取代码 diff、判断影响面和最终选择一个或多个用例的责任在 Codex。
3. 当前 MCP 链路中不存在 Regression Manager。

### Skill 文件核对

这条是设计阶段的历史核对结果：当时尚未取得可复用的 Skill 正文。当前 AgentRig 已在
仓库根目录的 `skills/core/` 提供构建用例、执行用例和采集工具样本三份 Skill，实际内容
以当前源码为准。
