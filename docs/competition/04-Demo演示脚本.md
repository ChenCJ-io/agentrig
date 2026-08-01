# 比赛 Demo 演示脚本

## 1. 演示目标

在 6—8 分钟内证明四件事：AgentTeams 是真实协作运行时；三个 Agent 各有不可替代工作；
执行结果可验证、可追溯；高风险动作不能绕过确认。

## 2. 演示前检查

```bash
scripts/local_demo.sh setup
scripts/local_demo.sh verify
```

浏览器打开 `http://127.0.0.1:8010/assistant`。不要在录像中打开 `.env`、Cookie、Matrix
access token 或模型请求头。

本机 lassist 会进行两轮模型请求；若它的可选 Redis/Langfuse 服务未启动，日志可能出现重试
告警并拉长运行时间，但不影响 AgentRig 的 RunEvent。正式录制前建议先做一次预热运行，并为
完整三 Agent 场景预留 10—15 分钟后台执行时间。

## 3. 第一幕：成功闭环（约 3 分钟）

### 操作

1. 新建会话：`比赛 Demo · 背景增强回归`。
2. 发送：

   > 使用 target_lassist_local、profile_lassist_agentteams 和已批准用例
   > case_lassist_three_agent_demo，生成一次评测计划。不要扩大范围。

3. 指向右侧计划卡，说明 Cases、CaseRuns、Provider 和 Evaluator。
4. 先说明“此时没有 Run”，再点“确认计划”和“提交运行”。
5. 展示 Curator、Judge invocation 从 dispatched/running 进入 completed。
6. 打开 Run Detail，展示用户消息、`apply_image_prompt`、受控结果、assistant 回复、Rule 和
   Judge evidence refs。

### 讲解

- Manager 负责计划，不能直接调用原始 `run_cases`。
- Curator 只看到冻结工具上下文，看不到 rubric。
- Judge 只在执行完成后读取脱敏证据，引用真实 event ID。
- request/response Matrix event ID 证明 Worker 是被 AgentTeams 唤醒并回写，不是进程内捷径。

## 4. 第二幕：策略回归失败（约 2 分钟）

### 操作

1. 新建会话：`比赛 Demo · 二次确认策略`。
2. 发送：

   > 只运行已批准用例 case_lassist_confirmation_gate_failure，使用本机 lassist 和当前
   > AgentTeams Profile，验证图片编辑前的二次确认策略。

3. 确认并提交。
4. 展示被测 Agent 直接调用编辑工具，而 Rule 的 `tool_not_called` 失败。
5. 展示 Judge 引用工具调用事件给出 fail；Manager 区分“执行完成”和“评测失败”。

### 讲解

这不是为了制造红灯，而是展示新安全策略可以先进入已批准 TestCase，再发现旧 Agent 行为的
真实回归。Curator 的成功工具结果不会诱导 Judge 忽略策略违规。

## 5. 第三幕：审批与恢复（约 1 分钟）

### 操作

1. 创建计划但不确认，指出提交按钮不可用。
2. 编辑计划 revision，说明旧确认不能复用。
3. 打开 AgentTeams 状态与角色列表，说明 Core/Managed 降级边界。

### 讲解

- 用户确认绑定 AssistantEvent 和 plan revision，不是 Prompt 中一句“用户同意了”。
- AgentTeams/模型异常不会删除已经保存的 RunEvent。
- Retry 使用同一幂等键；取消、失败、超时都是可审计终态。

## 6. 结束画面

停在最新 Run 的证据详情或助手的结果诊断上，并总结：

> AgentTeams 负责分工协作，AgentRig 负责冻结事实、验证输出和保存证据。我们把一次性的
> Agent Demo 变成可以持续回归、发布门禁和审计复盘的企业基础设施。

## 7. 录像交付建议

- 分辨率：1920×1080；浏览器缩放 90%—100%。
- 时长：不超过 8 分钟；开头 10 秒直接展示问题与结果，不先讲安装。
- 画面：成功链路、失败链路、审批边界必须都出现。
- 字幕：标出 Manager、Curator、Judge、MCP、Matrix event ID、Rule、Evidence。
- 附件：同时提交本目录 PPT、README、示例配置和运行结果截图。
