# EditFlow 彩排证据与正式录制台账

> 更新时间：2026-08-14（Asia/Shanghai）  
> 用途：统一 PPT、视频、报名表和答辩口径  
> 规则：彩排 ID 证明方案已经跑通，但正式视频必须生成新 ID

## 1. 一句话结论

公开脱敏的 EditFlow 已经跑通完整链路：真实 Agno + DeepSeek 决策、Prompt Before/Candidate、
差异驱动用例、30 次回归、真实本地 MCP 采样、人工 Sample 审核、Sample-only 零真实工具尝试回放，
以及 Web 助手自然语言规划、确认和提交。当前可以进入正式录制准备，不能直接把彩排素材冒充现场。

## 2. 彩排权威数据

| 证据组 | ID | 可说的结论 |
|---|---|---|
| Before | `run_4122698d707e4dc29d4740dbc355dfa5` | 同一 Case 5 次中 2 次行为失败，证明 broad Prompt 不稳定 |
| Candidate headline | `run_3ee1800bcbbe4f4e92e2e44fc48825ac` | 与 Before 同 Manifest、同 Case Snapshot，5/5 通过 |
| Candidate matrix | `run_38a956103b0c495b81bffaf0c272e84a` | 6 Cells、30 Attempts，30/30 通过 |
| Asset miss | `run_6696d3b7d2db40a98c5fd3b4de7d9f4e` | 可有界改写检索，但空结果后不调用 apply，5/5 通过 |
| MCP capture | `run_6791c49056af4da4b236d3e550d2869e` | 本地 MCP `editflow__inspect_image` 真调用 1 次 |
| Sample replay | `run_6294d74c3814420dad8d780d322861d1` | 5 个 Sample hit，Replay Run 内 real_tool Attempt 为 0 |
| Web Assistant | `plan_1a8bdd9c183a45a0a2753f935c189090` | 重复执行要求人工确认，确认与提交分离 |
| Web Run | `run_76307bc45f55414490c598033d6d28b9` | 普通用户入口最终 3/3 通过 |

机器事实源：[editflow-rehearsal-evidence.json](./editflow-rehearsal-evidence.json)。

## 3. 平台优势如何由证据支撑

| 平台优势 | 不是口号的原因 |
|---|---|
| 真实决策、受控副作用 | DeepSeek 真实选择工具；Fixture/Sample 只替换外部结果 |
| 身份可比 | Before/Candidate 分别冻结 Prompt SHA，Candidate 必须重启后再跑 |
| 重复不是多轮 | 每个 Cell 下 5 个独立 Attempt，可见 3/5 到 5/5 的稳定性变化 |
| 失败可归因 | 行为失败与 Fixture miss 被分开；错误 Case 先修再重跑 |
| 证据可复用 | real_tool 事件显式生成 Draft Sample，人工批准后可回放 |
| 对普通用户可用 | Web 助手能把自然语言变成可编辑 Plan，不要求用户理解 MCP |
| 人工边界真实存在 | MCP 不能批准 Case/Sample；重复执行的 confirm 与 submit 分离 |
| 不绑定单一 Agent | EditFlow 公开复现；lassist 保留为真实生产形态兼容附录 |

## 4. 正式录制台账（2026-08-14，干净录制库）

录制环境：录制专用 AgentRig（sqlite `editflow-recording-20260814.db`，seed preflight：7 Draft / 0 Sample /
0 Run）+ EditFlow 8094 + 本地工具 MCP 8095；驱动方为参赛人授权的 Claude Code（Agent 动作走 AgentRig
MCP，Case/Sample 批准走 Web 审核端点，MCP 无批准权限）。机器事实源：
[editflow-recording-evidence.json](./editflow-recording-evidence.json) 与
[editflow-recording-ledger.json](./editflow-recording-ledger.json)。

| 正式证据 | 实测值 | 硬门槛核对 |
|---|---|---|
| Baseline tag / commit | `recording-baseline-v1` / `f38257dd` | 工作树干净（`worktree_dirty=false`）✅ |
| Candidate commit | `12475f39` | 验收后提交，工作树干净 ✅ |
| Before / Candidate Prompt SHA | `43157c…9572` / `71adb390…f7fd` | 不同 ✅ |
| New Case | `case_editflow_one_step_mixed_chain` | MCP 现场创建 Draft，经 Web 审核 approved ✅ |
| Before Run / Manifest | `run_61e7649365274a238f566e40328d9c03` / `sha256:bb5008e6…6766aa` | 5 独立 Attempt：2 Pass / 3 `behavior_regression` ✅ |
| Candidate headline Run | `run_b8ac3aa9d5b1437ba0954144ff6024ea` | 同 Manifest，5/5 → ACCEPT ✅ |
| Candidate matrix Run | `run_3afacf3d9e304498b677265b11044793` | 6 Cells / 30 Attempts，30/30 ✅ |
| Capture Run / source event | `run_db173d3e5b314568bfad82d2b3fc59ef` / `evt_32fb37661a564843b5973c60ad7ff80d` | `source=real_tool`，命中 1 次 ✅ |
| Sample | `sample_934464c5a0414796839cac6d821b1339` | `source_type=real_tool`、Web 审核 approved ✅ |
| Replay Run | `run_1a209c84b61f4390bf468af8865f0b90` | 5/5；Run 内 real_tool Attempt=0 ✅ |
| Assistant Session / Plan / Run | `asst_5740815c6ef248d2992f77c6fc8d970e` / `plan_a0d80e75e2634b5f81fe751a197bbdbb` / `run_a1c88bc8ed83474a9261df9e1d0d23fb` | 确认与提交分离，3/3 ✅ |
| Final Decision | ACCEPT | hard Case 5/5、矩阵 30/30、仓库检查通过 ✅ |

## 5. 禁止混用

- 不把 `run_38a956…` 等彩排 ID 说成正式拍摄现场生成；
- 不把 Sample-only 的“本 Run 无 real_tool Attempt”扩大成全系统永久零调用；
- 不把 `completed` 说成 `pass`；
- 不把 AgentRig 的受控工具结果说成真实图像处理；
- 不把 lassist 私有资产、Prompt、图片或路径放入公开视频；
- 不把 AgentTeams 可选角色说成每次 Rule/Fixture 评测的必需组件。
