# Codex + Skill + AgentRig MCP 真实评测

> 彩排日期：2026-08-14（Asia/Shanghai）  
> 工作目录：公开 `editflow-demo-agent`  
> 被测模型：`deepseek-v4-flash`  
> 当前状态：核心链路已用同等 MCP/HTTP API 实测；正式录制须在 Codex UI 生成新 ID

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

## 彩排结果

| 环节 | 实测值 |
|---|---|
| Before Prompt SHA | `43157c294fef4cc0cacd2089a0973402cb15794421340504f8a35f546f879572` |
| Before | `run_4122698d707e4dc29d4740dbc355dfa5`，3/5 Pass、2 behavior fail |
| Candidate Prompt SHA | `71adb390cb86dd05dc5fdc1d9cf2656a436525176ccf178543eaf81a65dff7fd` |
| Candidate headline | `run_3ee1800bcbbe4f4e92e2e44fc48825ac`，同 Manifest，5/5 |
| Candidate matrix | `run_38a956103b0c495b81bffaf0c272e84a`，6 Cells / 30 Attempts，30/30 |
| Capture | `run_6791c49056af4da4b236d3e550d2869e`，real MCP hit 1 |
| Sample | `sample_editflow_inspect_real_20260814`，real_tool provenance，approved |
| Replay | `run_6294d74c3814420dad8d780d322861d1`，5/5，real_tool Attempt 0 |
| Repository | Ruff pass；34 non-live tests passed |

Before 与 Candidate headline 的 Manifest 都是
`sha256:04c0bad3b1b5b29704cece3dceff036301b46f2afb03fb079e5e315a69f966ec`，证明 Case 与执行选择没有在
两批之间偷换；变化来自模型输入身份。

## 为什么这体现生态闭环

项目 Skill 保存 EditFlow 特有的工具边界与回归门槛；Codex 理解 Prompt Diff、编辑代码并选择评测范围；
AgentRig MCP 提供通用资产和执行 API；Core 冻结事实、控制副作用并持久化证据；Web 承担人工审核和普通
用户入口。各组件不要求使用同一个模型，也不要求生成同一计划，但共同遵循可审计合同。

## 正式录制口径

- 从 baseline tag 和空 recording DB 开始；
- 在 Codex UI 真实展示 Skill 读取和关键 MCP 调用；
- 至少完整展示一个 New Case；其他 Case 可以快速剪辑；
- 等待可剪掉，但 Run/Cell/Event 必须来自同一正式批次；
- 彩排 ID 只出现在 PPT“已验证”台账，不冒充录制现场；
- 结论必须随现场事实变化，不预写 ACCEPT。

## 旧 lassist 实测的角色

2026-08-13 的 lassist Codex MCP 1/1 Pass 仍是兼容附录，证明 AgentRig 能接入真实生产形态 Agent；公开
视频不展示其私有路径、Prompt、工具文案或数据。主叙事改用 EditFlow，解决脱敏和可复现问题。
