# Demo 视频分镜与旁白

> 完整母版目标：7:20；先保证事实和说服力，再在 Review 后做 4 分钟减法。
>
> 主画面：Codex 项目工作流；辅助画面：AgentRig Web；被测对象：公开 EditFlow。
> 禁止：旧机械女声、zoompan、跨 Run 拼证据、暴露 lassist 私有资产。

## 分镜总表

| 时间 | 画面 | 旁白核心 | 必须露出的证据 |
|---|---|---|---|
| 00:00—00:20 | 标题钩子 | 一次 Prompt 修改如何证明没有修一处坏三处 | Prompt Diff + Timeline |
| 00:20—00:52 | EditFlow README/能力 | 真实模型与协议，受控图片副作用 | Agno、DeepSeek、5 tools、PostgreSQL |
| 00:52—01:25 | Codex 读取 Skill | 先冻结身份和不变量，不直接改 Prompt | commit、Before Prompt SHA、Case IDs |
| 01:25—02:10 | MCP Case 审计 + Web 审核 | 查重、Reuse/Change/New/Exclude、人工冻结 | 真 New Case；Draft → approved |
| 02:10—02:55 | Before Run/Cell | 单次成功不够，5 次暴露随机回归 | 1 Cell/5 Attempts；3 Pass/2 Fail |
| 02:55—03:32 | Prompt/description Diff | 只改模型可见边界，不在 HTTP 层写路由 | 精简 Diff；34 tests |
| 03:32—03:55 | 重启与身份对比 | SHA 不变就不算 Candidate | `43157c…` → `71adb3…` |
| 03:55—05:00 | Candidate + Matrix + Timeline | 同 Case 5/5；六 Case 30/30；内部行为可见 | Manifest、30/30、参数与引用 |
| 05:00—05:48 | Real MCP → Sample → Replay | 真采一次、人审、低成本复用 | real_tool 1；Sample approved；5 hit/0 real |
| 05:48—06:35 | Web Assistant | 普通用户自然语言规划，确认与提交分离 | Plan、repeated execution、Run 3/3 |
| 06:35—07:05 | Codex 验收报告 | 结论绑定身份、资产与证据 | Decision、Run/Manifest、Limitations |
| 07:05—07:20 | 平台闭环卡 | AgentRig 是开放评测基础设施 | Driver/Provider/Evidence/Gate |

## 完整旁白稿

### 场景 1｜问题

> Agent 的 Prompt 改动会同时影响工具选择、参数、调用顺序和结果引用。一次回答看起来正确，并不能证明
> 回归稳定。AgentRig 要解决的是：怎样让每次 Agent 变化都留下可重复、可审核的行为证据。

### 场景 2｜真实与受控边界

> 公开演示使用 EditFlow，一个 Agno 和 DeepSeek 驱动的修图 Agent。模型推理、HTTP/SSE、Session 和
> 工具选择都是真实的；五个图片工具通过 external execution 交给 AgentRig。图片结果来自公开的本地
> MCP 服务，不上传图片，也不调用第三方图片 API。我们保留决策真实性，同时隔离工具成本和副作用。

### 场景 3｜Skill 先于修改

> Codex 在项目里读取 Prompt 回归治理 Skill。它先冻结 Git、模型、进程和 model input SHA，再定义允许
> 修改的工具边界，以及图片引用、素材来源、人物保护和中文回答这些不变量。没有证据之前，不直接改 Prompt。

### 场景 4｜用例治理

> Codex 通过 AgentRig MCP 查重。单项调亮、素材未命中和人物保护已经存在，所以被复用或增强；旧混合
> 用例的不公平 Fixture 被修正。真正现场新增的是：即使用户要求一步完成，也不能绕过专用工具边界。
> 所有资产先是 Draft，最终由人类审核冻结，MCP 不能批准自己创建的 Case。

### 场景 5｜Before

> Preview 把一个 Case 展开成一个 Cell 和五个独立 Attempt，并冻结 Canonical Manifest。Before 五次中
> 三次通过、两次行为失败：有时检查被放到调亮之后。父 Run 虽然 completed，业务结论仍然 fail。
> 这就是只跑一次会漏掉的模型方差。

### 场景 6｜最小修改

> Codex 只修改模型可见输入：自由修图只负责像素调整，背景和素材必须走搜索与应用，比例必须走裁剪；
> 每次修改图片后，下一步消费最新的 output image reference。HTTP 适配层没有加入关键词路由，也没有
> 为视频写死答案。仓库测试通过后，必须重启进程。

### 场景 7｜身份与 Candidate

> AgentRig 观察到 model input SHA 从 `43157c` 变为 `71adb3`。如果 SHA 没变，Candidate 就没有验收资格。
> 同一个冻结 Case 和 Manifest 再跑五次，结果从三比二变成五比零。

### 场景 8｜回归矩阵与内部证据

> Candidate 继续运行六个相关 Case，共三十个独立 Attempt，全部通过。这里不是只显示一个绿色总分：
> Timeline 记录检查、搜索、调亮、应用素材和裁剪；素材 ID 来自搜索结果，人物保护传播到相关工具，
> 每个图片引用来自前一步结果。简单调亮没有被过度路由，素材为空时也没有编造 ID。

### 场景 9｜真实结果资产化

> 对需要真实结果的场景，AgentRig 先通过本地 MCP 执行一次 inspect image，并持久化 real tool 事件。
> Codex 只能从这条证据创建 Sample 草稿；人类审核后，Sample-only Profile 回放五次。五次都命中 Sample，
> 这个 Replay Run 里的真实工具尝试为零。真实来源、人工责任和重复成本被放进同一条链。

### 场景 10｜普通用户入口

> 不使用 Codex 的普通用户，也能在 Web 助手里描述评测目标。模型生成可编辑计划；因为要重复三次，
> Core 要求人工确认。确认后仍没有 Run，另一次提交才真正执行，最终三个 Attempt 全部通过。不同模型
> 可以提出不同方案，但都落到同一种 Case、Run、Cell、Attempt 和证据合同。

### 场景 11｜证据化结论

> 最终结论不是“看起来修好了”。它同时引用 Before 和 Candidate Prompt SHA、Case 分类、Manifest、
> Cell、Attempt、Sample 来源、仓库门禁和已知限制。任何 hard Case 没有全部通过，Codex 就必须给出
> Partial 或 Reject，而不是挑选一个绿色结果。

### 场景 12｜收尾

> AgentRig 不替模型思考，也不绑定一个框架。它用可替换 Driver 接入 Agent，用多种 Provider 控制工具
> 结果，用 Rule、Judge、人工审核、报告和 Gate 治理结论。Codex 负责改变 Agent，AgentRig 负责把每次
> 改变变成可复用、可执行、可追溯的评测资产。

## 4 分钟减法版

Review 后如需压缩，保留 12 个场景但缩短为：15、18、18、25、28、20、12、35、25、28、16、10 秒，
合计约 250 秒，再删 10 秒转场。不得删除 Prompt SHA、独立 Attempts、人工审核和 Sample 来源。

## 剪辑与真实性要求

- 每个段落的 Run/Cell/Attempt/Timeline 来自同一 Run；
- 可剪等待和日志滚动，不可跨 Run 拼“完美轨迹”；
- Codex UI 必须是真实执行；若使用静态摘录，明确标注；
- 正式录制使用新 ledger，彩排 `run_38a956…` 等 ID 不冒充现场；
- 画面固定硬切，不做 zoompan、鼠标追踪或后期防抖；
- 旁白优先真人；TTS 使用自然中文男声，场景级响度约 -16 LUFS；
- 术语 Run、Cell、Attempt、Sample、Manifest 全片统一。
