# 评审映射与答辩 FAQ

## 评分证据映射

| 评审关注点 | AgentRig 证据 | 演示动作 |
|---|---|---|
| 场景价值 | 真实工具昂贵/有副作用，纯 Mock 绕过决策 | Real MCP 采一次，Sample-only 回放五次 |
| Agent 与 Skill | EditFlow Agno Agent；项目 Prompt Skill；AgentRig MCP | Codex 读取 Skill、治理 Case、修 Prompt |
| 技术真实性 | DeepSeek、HTTP/SSE、Session、Prompt SHA、Manifest | Before/Candidate 身份和 Timeline 下钻 |
| 评测可靠性 | Cell 下独立 Attempt；Rule 与生命周期解耦 | 同 Case 从 3/5 到 5/5，最终 30/30 |
| 安全治理 | Case/Sample Draft；人类批准；confirm 与 submit 分离 | 展示两次人工边界 |
| 失败诊断 | behavior、case、evaluator、infra 分离 | 展示 Fixture miss 先修 Case，不算行为回归 |
| 普通用户可用 | 模型助手自然语言生成可编辑 Plan | Plan → confirm → submit → 3/3 Run |
| 开源复用 | MIT、协议无关 Driver/Provider、公开 EditFlow | lassist 作为生产形态兼容附录 |

## 高频问题

### 这是不是 AgentScope 的开源版？

是同一类评测闭环在开源环境中的产品化延伸：部分前端工作台和交互经验可以复用，但 AgentRig 把内部
依赖拆成 Target、Driver、Provider、Case、Manifest、Cell、Attempt、Evidence 和 Gate 等公开合同。
AgentScope 的业务资产、Prompt 和数据不会被复制出来；公开 EditFlow 从零构建，MIT 可复现。

### 为什么不直接调用真实工具？这不就是 Mock 吗？

Agent 的模型推理、协议、Session、工具选择和参数仍是真实的；受控的是工具执行结果。纯 Mock 通常连
Agent 决策都绕过，而 AgentRig 在模型决定调用之后才选择 Fixture、Sample、Simulator 或 Real Tool。
彩排还真实调用了一次本地 MCP，再把持久化结果治理为 Sample。

### 你们怎么证明 Sample 回放真的省资源？

Capture Run 有 1 个 `real_tool` hit；Replay Run 五次都有 Sample hit，事件审计中 `real_tool` Provider
Attempt 为 0。准确说法是“该 Replay Run 无真实工具尝试”，不是声称整个系统永久零调用。

### 这不就是 LLM-as-Judge 吗？

不是。Judge 只是可选端口。本次核心用确定性 Rule，证据来自工具事件；此外还有身份快照、Manifest、
人工审核、独立 Attempt、恢复、报告和 Gate。Judge 不能覆盖 Rule 或发明不存在的证据。

### Codex 和 Web 助手为什么没有相同计划？

二者模型能力、上下文和角色不同，输出不同方案完全合理。AgentRig 统一的是可选资产、执行边界、人工
确认语义和证据格式。只有做严格 A/B 时，才要求同一冻结 Manifest 下的输入可比。

### 为什么要跑五次？

真实模型有方差。彩排 Before 单次看可能成功，但五次中有两次行为失败；只跑一次会漏掉问题。每次重复
是独立 Session/Attempt，不是把一个会话里的多轮消息当成重复。

### `completed` 为什么可能是 Fail？

`completed` 只表示执行生命周期结束，业务是否通过由 Evaluation 决定。Before Run 正是 completed，
但 Cell 因 2 个行为失败而判定 fail。Web 助手的终态消息也明确要求继续读取 Cell/Attempt。

### Fixture miss 为什么不算 Agent 失败？

如果模型做了合理的只读检查或有界查询改写，但 Case 没有提供结果，这是用例合同错误。彩排先将其归类
为 `CASE_INVALID`，修 Fixture 后重新冻结并跑出 30/30；不能把测试基础设施错误嫁祸给 Agent。

### AgentRig 是否替被测 Agent 选工具？

不会。路由在 EditFlow 的 Agno Agent 中；Candidate 只改模型可见 Prompt 与工具 description，HTTP 适配层
没有关键词路由。AgentRig 观察调用、提供受控结果并独立判断契约。

### 多 Agent 是不是核心卖点？

核心评测不依赖多 Agent。Manager/Assistant、Curator、Judge 是复杂规划、动态模拟、语义裁决时的可选
扩展。本次 Fixture + Rule 场景保持确定、低成本，不为比赛强行调用角色。

### 目前还没有闭合什么？

正式视频尚未录制，彩排 ID 不能冒充正式 ID；Sample 只覆盖 `inspect_image`；动态 real-MCP 引用等值以
Timeline 证明，Rule 还没有通用跨事件变量；AgentTeams 外部 Live、Kubernetes 和目标容量需独立环境验收。
