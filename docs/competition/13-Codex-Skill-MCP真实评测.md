# Codex + Skill + AgentRig MCP 真实评测

> 录制日期：2026-08-14（Asia/Shanghai）  
> 工作目录：公开 `editflow-demo-agent`  
> 被测模型：`deepseek-v4-flash`  
> 当前状态：核心链路已完成正式录制；Codex CLI 已真实读取 Skill 并经 MCP 执行回归确认

## 目标

验证开发者能在被测 Agent 项目中，让 Codex 读取项目级 Prompt 回归 Skill，并通过 AgentRig MCP 完成
用例治理、Before、Prompt 修改、Candidate、工具结果采样和证据化结论，而不是复制固定 API 调用。

## 使用的项目 Skill

`editflow-demo-agent/.codex/skills/prompt-regression-governance/SKILL.md` 规定：

- 先冻结 Git、模型、进程、Prompt SHA 和风险，不直接编辑；
- 审计 Case，并按 Reuse / Change / New / Exclude 分类；
- 先 Preview，提交时携带 `expected_manifest_hash`；
- 重复必须是独立 Attempt；
- 区分 behavior、case、evaluator 和 infrastructure；
- 修改模型可见输入后重启，验证新 Prompt SHA；
- hard Case 未全通过时不得 ACCEPT；
- 结论引用 Run、Cell、Attempt、Event 和限制。

## 真实执行链

```text
check_target / get_target / get_execution_profile
  → list_test_cases / get_test_case / get_schema
  → update draft Case / create live New Case
  → human approve Case
  → preview_run_cases
  → run_cases(expected_manifest_hash)
  → get_run_summary / list_run_cells / list_case_run_events
  → edit Prompt + tool description
  → repository checks + process restart + new Prompt SHA
  → Candidate headline + regression matrix
  → Real Tool capture
  → create_sample(source_tool_call_id=tool_call event.id)
  → human approve Sample
  → Sample-only replay
  → ACCEPT / PARTIAL / REJECT report
```

MCP 可以创建和修改 Draft，不能批准 Case 或 Sample。人工审核不是演示装饰，而是权限边界。

## 正式录制结果

| 环节 | 实测值 |
|---|---|
| Before Prompt SHA | `43157c294fef4cc0cacd2089a0973402cb15794421340504f8a35f546f879572` |
| Before | `run_61e7649365274a238f566e40328d9c03`，2/5 Pass、3 behavior fail |
| Candidate Prompt SHA | `71adb390cb86dd05dc5fdc1d9cf2656a436525176ccf178543eaf81a65dff7fd` |
| Candidate headline | `run_b8ac3aa9d5b1437ba0954144ff6024ea`，同 Manifest，5/5 |
| Candidate matrix | `run_3afacf3d9e304498b677265b11044793`，6 Cells / 30 Attempts，30/30 |
| Capture | `run_db173d3e5b314568bfad82d2b3fc59ef`，real MCP hit 1 |
| Sample | `sample_934464c5a0414796839cac6d821b1339`，real_tool provenance，approved |
| Replay | `run_1a209c84b61f4390bf468af8865f0b90`，5/5，real_tool Attempt 0 |
| Codex CLI 确认批次 | `run_33efe83470d54f728f1dc6b0dad36153`，同 Manifest，5/5（Codex 真实会话提交） |
| Repository | Ruff pass；34 non-live tests passed |

Before 与 Candidate headline 的 Manifest 都是
`sha256:bb5008e637bc33dafb626ea314eb5917de7efdaf2639eab0a9001021586766aa`，证明 Case 与执行选择没有在
两批之间偷换；变化来自模型输入身份。

## 为什么这体现生态闭环

项目 Skill 保存 EditFlow 特有的工具边界与回归门槛；Codex 理解 Prompt Diff、编辑代码并选择评测范围；
AgentRig MCP 提供通用资产和执行 API；Core 冻结事实、控制副作用并持久化证据；Web 承担人工审核和普通
用户入口。各组件不要求使用同一个模型，也不要求生成同一计划，但共同遵循可审计合同。

## Codex CLI 真实会话（2026-08-15）

`codex exec`（codex-cli 0.147.0）在 `editflow-demo-agent` 中真实读取
`$prompt-regression-governance` Skill，经 agentrig MCP 冻结 Target/Case 身份、展示
baseline→candidate 的最小 Prompt Diff，并提交 `repeat_count=5` 的回归批次：

- Run：`run_33efe83470d54f728f1dc6b0dad36153`，5/5 `evaluation_state=pass`，每次 8/8 断言；
- Manifest 与 Before/Candidate 完全一致（`sha256:bb5008e6…6766aa`）；
- Codex 自行执行 Ruff 与 34 项非 live 测试，全部通过；
- Codex 对本会话给出 **PARTIAL**——因为它只被要求跑 headline，没有跑全量 smoke 矩阵，
  按 Skill 第 7 步不允许自称 ACCEPT。完整 ACCEPT 由台账中的 30/30 矩阵支撑。
  这正是治理 Skill 约束真实 Agent 不过度宣称的第一手证据；
- 会话未修改任何文件、未批准任何资产；终端实拍见
  `assets/live/codex-01-skill-session.png` 与 `codex-02-regression-verdict.png`。

## 正式录制口径

- 台账中的 ID 全部来自正式录制库，画面与结论一一对应；
- Run/Cell/Event 均来自同一正式批次，不跨批次拼接；
- 结论随现场事实变化：Codex 会话如实输出 PARTIAL，而非预写 ACCEPT。

## 旧 lassist 实测的角色

2026-08-13 的 lassist Codex MCP 1/1 Pass 仍是兼容附录，证明 AgentRig 能接入真实生产形态 Agent；公开
视频不展示其私有路径、Prompt、工具文案或数据。主叙事改用 EditFlow，解决脱敏和可复现问题。
