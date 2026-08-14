# lassist 真实闭环与迁移前端验收

> 初次验收：2026-08-11 23:44—2026-08-12 00:12（Asia/Shanghai）  
> 录制冻结：2026-08-13（Asia/Shanghai）  
> 验收性质：本机真实 Agent 联调；用例为 Draft，不能替代正式发布证据  
> 页面入口：`http://127.0.0.1:8020`

> 2026-08-14 参赛定位更新：本报告保留为“真实生产形态兼容证据”，不再作为公开主视频。公开视频
> 使用从零编写的 MIT EditFlow，避免暴露 lassist/Pixcake 私有 Prompt、工具、数据和路径。

## 1. 验收结论

AgentRig 已用真实 lassist HTTP/SSE Agent 跑通以下闭环：

```text
Target 连接检查
  → Preview Canonical Manifest（不调用 Agent）
  → expected_manifest_hash 确认提交
  → 真实两轮对话与同一 session
  → fixture 结果注入
  → Cell / Attempt / Timeline
  → rule 4/4 评判
  → RunReport / QualityReport
  → 单目标验收结论：通过
```

浏览器随后从 Overview 进入 Run、Cell 和验收报告，未使用核心 API Mock；页面无横向溢出，
Axe `critical/serious` 为 0。

基础智能助手也完成真实 Provider 验收：DeepSeek 不支持 `json_schema` / `json_object` 时，模型客户端
有界回退到 JSON Prompt，随后由 `BasicAssistantOutput` 严格校验并返回中文直接回答。回退只处理
400/422 或无效 JSON，不会重试鉴权失败，也不会改用规则助手。当前 8020 的 Provider 状态为 ready。

## 2. 权威标识与结果

| 项目 | 实测值 |
|---|---|
| Target | `target_lassist_local`，`pixcake_http_sse`，`http://127.0.0.1:8000` |
| Case | `compat_tc_from_error_080`，多轮修图后撤销最近操作，Draft |
| Profile | `profile_lassist_fixture_rule`，controlled + fixture + rule |
| Manifest Hash | `sha256:7fb6947cd4c0e3ec3751229fd0715fcf3ff543d7e916b57a33a9bddd45d9de8e` |
| Run | `run_f4198ddbe0a348abb77fa3349024067e` |
| Cell | `sha256:8e6af2e2515dcc055cc28b2fdd0a702092202c53d1ea82e91625372dbf7d9038` |
| Attempt | `eval_attempt_8798858dad9c4e008789a63dcbefb99c` |
| 结果 | 1 Cell、1 Attempt、2 Turn、2 Tool Call、Pass |
| 评判 | `apply_image_prompt → rollback_to_tool_call`，4/4 rule assertions passed |
| 证据质量 | 2/2 引用有效，100%；Provider error 0；脱敏已应用 |
| 耗时 | Run 94.24 s；4 次 driver request，P95 25.15 s |

单目标 Run 不执行 A/B 发布门禁。前端直接使用业务评判与证据完整性给出验收结论；只有 baseline / candidate
成对 Run 才调用 Release Gate，避免把“不适用”显示成系统错误，也不会为展示额外调用被测 Agent。

## 3. AgentScope 同源闭环核对

同一时段只读核对本机 AgentScope：健康检查通过，存在 262 个 Case 和 520 个 Batch Run；最近一条
`br_49d38e5c0def4639` 为 1 Cell / 5 Attempt 的 completed Run，5 个 Attempt 全部完成。

这说明 AgentRig 要对齐的是 AgentScope 已验证的产品闭环和界面表达，而不是强制两种入口生成相同方案：

- AgentScope 保留业务专用的 tool profile、prompt identity 和场景资产；
- AgentRig 提供开源、通用的 Target、Manifest、Cell/Attempt、证据、恢复与报告契约；
- Codex + Skill + MCP 与 Web 智能助手可以形成不同计划，只要各自明确范围、资源成本并留下可审计证据。

## 4. 前端迁移验收

已迁移并接入真实 API 的页面：

- Target Overview：连接、资产、最近 Run 与质量边界；
- Evaluation：三步 Preview、Manifest Hash 确认、Run、Cell、Timeline、Recovery、Report；
- Assets：Case、审核、Sample、Profile；
- Assistant：统一 Provider 健康状态，基础模型与 AgentTeams 拓扑分开展示；
- UI Core：统一 Shell、状态页、Markdown、ID 复制、中国时区和响应式几何。

工作区页面已按路由拆包，旧 `ProductPage` 只作为尚未迁移页面的 Feature Flag 回退，不再进入新评测主链
首屏包。顶部 Target 上下文使用实际 `device_info.app_version`，并根据 endpoint 显示本机/远程，避免把
版本列表第一项误写成当前版本。

本机截图：

- `.agentrig/competition-live/lassist-real-acceptance.png`：真实 Run 验收结论；
- `.agentrig/competition-live/lassist-real-assistant.png`：真实模型中文回答与基础助手拓扑。

## 5. 可重复验收

```bash
# 全量本地门禁
scripts/accept_v23.sh local

# 已存在真实 lassist Run 时，只验收 Browser → AgentRig → SQLite 证据链
cd web
AGENTRIG_WEB_API_TARGET=http://127.0.0.1:8020 \
AGENTRIG_E2E_LASSIST_BACKEND=1 \
AGENTRIG_E2E_LASSIST_RUN_ID=run_f4198ddbe0a348abb77fa3349024067e \
npm run e2e -- lassist-live.spec.ts
```

## 6. 诚实边界

- 本次 Case 是历史 Draft，仅用于真实协议和界面闭环验收；正式录制应先在 Assets 中批准选定 Case。
- fixture 只替代实际修图副作用，模型推理、SSE、工具选择、跨轮 session 和评判均为真实链路。
- lassist 没有返回 token/cost，因此报告明确显示不可用，不做估算。
- 基础智能评测助手仍需配置模型 Provider；未配置时页面明确禁用输入，不退回规则助手。

## 7. 2026-08-12 录制前扩展回归

该阶段原计划固定使用 `target_lassist_local`。当前这些 Run 仅保留为兼容附录；公开录制主套件已迁移到
EditFlow。若内部继续复跑 lassist，仍按 lassist
`prompt-regression-governance` 的语义场景口径，把每个正向场景重复 3 次；确定性的故意失败诊断只跑 1 次，
避免无意义消耗。当前已经完成一轮 3 次稳定性验收，保留当时的 Run 作为录制素材：

| 场景 | Run | Attempt | 结果 |
|---|---|---:|---|
| 背景增强 → `apply_image_prompt` | `run_c677c7d81dfe49158f3795d17af5e1a6` | 3 | 3/3 Pass |
| 修图 → 跨轮撤销 | `run_d9d228fbcd054ca1a96525194fe014d7` | 3 | 3/3 Pass |
| 查询项目 → 使用返回 ID 打开 | `run_73888e6da6c348139da0bc70436b932b` | 3 | 3/3 Pass |
| 错误期望 ID=999 的参数级诊断 | `run_5c5730c762614f8a871af0183cf3e501` | 1 | 1/1 稳定 Fail（预期） |

前三个正向 Run 合计 9 个 Attempt 全部通过；诊断 Run 中，lassist 真实调用
`open_project(project_id=430409687)`，AgentRig 根据冻结用例中的错误期望 `project_id=999` 稳定判定
`behavior_regression`，并把工具顺序、真实参数和失败断言关联到同一 Cell 证据。这一用例用于演示失败归因，
不表示 lassist 本身执行错误。

多轮撤销 Run 的质量报告记录：12 次真实 Driver 请求、6 次受控 Provider 结果注入、Provider 错误 0、
证据引用 6/6 有效、P95 用例耗时 16.55 秒、P95 Driver 请求 6.98 秒、脱敏已应用。lassist 仍未返回
token/cost，所以成本字段保持“不可用”。

录制前一键复跑：

```bash
uv run python scripts/run_lassist_recording_suite.py --repeat 3
```

机器可读结果写入 `.agentrig/competition-live/lassist-recording-suite.json`。新套件默认执行策略为：

- 三个真实语义正向场景各 3 次；
- 一个确定性参数诊断场景 1 次；
- 每个场景均先 Preview Canonical Manifest，再带 `expected_manifest_hash` 提交；
- 真实 lassist 模型、HTTP/SSE、session 和工具决策；fixture 只替代 Pixcake 客户端修图副作用。

浏览器已分别验收三次通过 Run 与三次失败 Run，支持 `Attempt 3/3`，Axe critical/serious 为 0，页面无
横向溢出。截图：

- `docs/competition/assets/live/lassist-pass-01-overview.png` 至 `04-acceptance.png`；
- `docs/competition/assets/live/lassist-fail-01-overview.png` 至 `04-acceptance.png`。

## 8. 2026-08-13 双入口实测

### 8.1 Web 智能评测助手

真实 Provider 接收自然语言目标，创建 Draft Plan `plan_60552ccfed2a425482ac6be05d24f8d8`：

- 1 Case / 1 Attempt，未确认、未提交；
- 用户明确要求只生成计划，真实工具副作用为 0；
- 完成截图为 `docs/competition/assets/live/lassist-assistant-plan.png`；
- 本次模型响应约 228 秒，因此正式视频使用完成后的真实截图，不现场等待。

### 8.2 Codex + 项目 Skill + AgentRig MCP

在 lassist 仓库读取 `prompt-regression-governance` 后，Codex 依次调用 Target 检查、运行 Schema、
Preview、带 `expected_manifest_hash` 的提交和终态查询，生成真实 Run：

- Run：`run_3618a91114c44e6a8d74eb8fffdd4ed6`；
- Manifest：`sha256:5f9674e9d5940dbc358472a44a014228c5f5093af931b65407ee395df4f9592e`；
- 1 Cell / 1 Attempt；`evaluation_outcomes.pass=1`；
- controlled fixture，无真实图片副作用；
- 执行摘要：`.agentrig/competition-live/codex-lassist-evaluation.md`。

两种入口没有被要求输出同一计划。它们统一使用 AgentRig 的资产与证据契约，并分别保留自己的模型、
上下文和规划能力。

### 7.1 10.0.0 点修候选哨兵

AgentScope Draft 用例 `tc_from_error_176` 与 `tc_from_error_182` 已通过真实 lassist 协议接入兼容测试：

- “头发换成银白色，同时把照片变成冬日雪景”连续 3/3 通过：一次 `apply_creative` 内正确隔离局部
  发色 mask 与全图冬日雪景；
- “美白一点”始终正确绑定图片 45 和 `cluster_id=25`，但 4 次观察中有 2 次 prompt 为“美白一点”、
  2 次为“面部皮肤美白一点”，表现为 2/4 语义参数稳定性，尚不适合作为主录制绿例。

上述点修用例在 AgentScope 仍为 Draft，当前只作为模型波动和 Prompt 回归候选证据；必须完成
review/approve 并达到 3/3 后，才能进入正式录制主套件。
