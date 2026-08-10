# AgentRig GOAI Demo 视频分镜与旁白

> 目标成片：6 分 30 秒–7 分 15 秒，1920×1080，H.264/AAC，中文旁白与烧录字幕。
>
> 官方验证点：至少一条完整场景，可核验 Agent 协作、工具调用、输出结果、异常处理、执行证据和关键技术亮点。

## 1. 录制配置

- 演示入口：`http://127.0.0.1:8010/targets/target_lassist_local/assistant`
- 浏览器：Chrome 独立窗口，仅保留 AgentRig 一个标签，进入全屏。
- 演示数据：优先使用已完成的脱敏会话和 Run，避免把模型等待时间录入成片。
- 录制前执行：`scripts/local_demo.sh verify`。
- 禁止出镜：`.env`、Cookie、Matrix token、模型请求头、终端环境变量、未脱敏错误正文。
- 镜头中只保留截断后的 ID；需证明关联时，使用页面已脱敏 request/response event ID。

## 2. 时码与分镜

| 时码 | 时长 | 画面与操作 | 屏幕标注 |
|---|---:|---|---|
| 00:00–00:18 | 18s | 标题卡，随后直接切到“参赛验收 · 成功回归”结果画面 | `AgentRig · 多 Agent 可审计评测基础设施` |
| 00:18–00:48 | 30s | 展示右侧“实际执行路径”：Manager、Core Gate、lassist、Curator、Judge | `3 个不同职能 Agent / AgentTeams v1.1.2` |
| 00:48–01:28 | 40s | 指向当前计划：1 Case、1 CaseRun、`simulation_curator`、`evidence_judge`；指向用户确认与 plan revision | `NO CONFIRMATION → NO RUN` |
| 01:28–02:05 | 37s | 指向 Curator/Judge 两张 Worker 证据卡，展示请求、响应 event ID 和 result ref | `Matrix 定向投递 / 双向事件可核验` |
| 02:05–03:20 | 75s | 点击“查看 Run”，展示用户输入、`apply_image_prompt` 工具调用、Curator 受控结果和 assistant 后续回复 | `真实 lassist / 受控 ToolResult / append-only RunEvent` |
| 03:20–04:02 | 42s | 展示 Rule 3/3 和 Evidence Judge pass，指出两份 Evaluation 独立存档，Judge 引用真实 event ID | `Rule ≠ Judge / 未知 evidence_ref 会被拒绝` |
| 04:02–04:32 | 30s | 返回助手，切换到“参赛验收 · 确认策略” | `失败也是有效评测结果` |
| 04:32–05:22 | 50s | 展示被测 Agent 未请求二次确认即直接调用编辑工具；Rule `tool_not_called` fail，Judge 引用同一工具事件判 fail | `completed ≠ pass` |
| 05:22–05:55 | 33s | 展示超时/恢复证据摘要：旧 Attempt 保留事件与 Rule，新 Run 不覆盖旧记录 | `显式终态 / 幂等恢复 / 不伪造未发生结论` |
| 05:55–06:28 | 33s | 展示 Skill 清单：6 Manager + 2 Worker + 3 Core；指出角色隔离 MCP | `11 Skills / 3 套最小权限 MCP` |
| 06:28–06:55 | 27s | 回到成功 Run 证据画面，收束 | `AgentTeams 管协作 · AgentRig 管事实` |

## 3. 旁白稿

### 00:00–00:18

Agent 不缺一次成功的 Demo，缺的是每次升级后都能回答：哪里变了，为什么通过，证据是什么。AgentRig 将一次性演示变成可持续回归的评测基础设施。

### 00:18–00:48

这条真实路径中，AgentTeams Manager 负责理解目标和编排计划，Simulation Curator 负责生成受控工具结果，Evidence Judge 负责依据冻结证据独立裁决。被测的 lassist 是评测对象，不计入三个协作 Agent。

### 00:48–01:28

用户只描述评测目标。Manager 查询已批准用例、Target 和 Profile，生成可预览计划。范围、数量、结果提供链和评判器都在提交前显式展示。确认必须绑定同会话的真实用户事件和同一 plan revision；没有确认，就没有 Run。

### 01:28–02:05

Curator 和 Judge 是两个独立 Worker。AgentRig 保存 Matrix 的请求与响应事件 ID、输入输出 hash、结果引用和终态。这证明任务确实经过 AgentTeams 定向投递和 Worker 回写，不是进程内的伪造捷径。

### 02:05–03:20

进入 Run 详情可以看到完整事实链：用户要求背景增强，lassist 真实产生 `apply_image_prompt` 工具调用。Curator 只读取冻结的工具上下文，看不到 rubric，它返回的候选还要通过 JSON Schema 和状态验证，才能作为受控 ToolResult 回注给被测 Agent。所有步骤都写入 append-only RunEvent。

### 03:20–04:02

执行结束后，确定性 Rule 三项全部通过；Evidence Judge 又独立对三个语义标准判定 pass，并引用本次 Run 的真实 event ID。两份 Evaluation 相互独立，Judge 不能覆盖 Rule，也不能发明不存在的证据。

### 04:02–05:22

评测平台不应只演示绿灯。在二次确认策略场景中，用例要求编辑前先向用户确认，但旧版 lassist 直接调用了工具。即使 Curator 成功返回工具结果，Rule 的 `tool_not_called` 仍然失败，Judge 也引用同一工具事件判定 fail。执行完成，不等于评测通过。

### 05:22–05:55

故障也不会被抹掉。首次负向运行触发有界超时后，系统保留已有 RunEvent、Rule 失败和 Curator 回执，不伪造尚未发生的 Judge 结论。修正配置后新建 Run，旧 Attempt 依然可审计，幂等恢复不会覆盖历史。

### 05:55–06:28

AgentRig 共提供十一个可复用 Skill：六个 Manager Skill、两个 Worker Skill 和三个 Core Skill。每个核心 Skill 都声明输入输出、调用条件、依赖工具、失败处理和安全边界。Manager、Curator 和 Judge 使用三套物理隔离的 MCP 工具集，Prompt 不是权限边界。

### 06:28–06:55

AgentTeams 负责谁与谁协作，AgentRig 负责什么是已发生的事实。我们不替 Agent 做决定，而是让每个决定都经过分工、验证并留下证据，最终成为企业 Agent 的持续回归、发布门禁和审计基础设施。

## 4. 字幕必标关键词

`Manager` · `Simulation Curator` · `Evidence Judge` · `AgentTeams` · `MCP` ·
`Matrix request/response event ID` · `EvaluationPlan revision` · `apply_image_prompt` ·
`Rule 3/3` · `Evidence refs` · `completed ≠ pass` · `idempotency` · `append-only RunEvent`

## 5. 成片验收

- [x] 时长 6 分 55 秒，前 18 秒已给出问题和结果。
- [x] 成功、策略失败、审批/恢复边界都出现。
- [x] 画面中可识别三个 Agent 与各自不可替代工作。
- [x] 可看到真实工具调用、Curator 结果、Rule、Judge 与证据引用。
- [x] 没有密钥、Cookie、Token、未脱敏日志、邮箱、通讯录或其他私人页面出镜。
- [x] 旁白音量稳定，字幕时序单调无重叠，关键中英文术语已抽帧复核。
- [x] MP4 与 SRT 是自包含文件，不依赖本机绝对路径。

成片位置：`dist/competition/GOAI-2026-AgentRig-初赛材料/AgentRig-GOAI-2026-Demo.mp4`。
系统录屏接口因 macOS 隐私权限不可用；为避免修改用户安全设置，成片使用 Computer Use 获取的
真实 AgentRig 界面画面、方案页、macOS 中文旁白和烧录字幕合成。构建脚本为
`scripts/build_competition_video.py`，所有演示结论均来自已完成的真实 Run 与可核验事件证据。
