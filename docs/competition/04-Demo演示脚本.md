# Demo 演示脚本

## 演示目标

完整母版用 7 分 20 秒证明一条真实闭环：Codex 在公开 EditFlow 项目中读取 Skill、治理 Case、运行
Before、修改 Prompt、运行 Candidate 和回归；AgentRig 把真实决策变成可审核 Sample 与可下钻证据；
普通用户最后通过 Web 助手复用资产。AgentRig 是辅助评测基础设施，Codex 是开发主入口。

## 录制前准备

```bash
# EditFlow Target / MCP backend
curl -fsS http://127.0.0.1:8090/health
curl -fsS http://127.0.0.1:8090/capabilities

# AgentRig 实际链路探针；/health 当前会落到 SPA，不作为证明
curl -fsS -X POST \
  'http://127.0.0.1:8020/api/targets/target_editflow_http_sse/check?version=working-tree'
curl -fsS http://127.0.0.1:8020/api/v2/assistant/provider-health

# 干净录制目录审计
cd ../editflow-demo-agent
uv run editflow-seed-agentrig --recording \
  --base-url http://127.0.0.1:8020 \
  --target-endpoint http://127.0.0.1:8090
```

`--recording` 必须返回 7 个 Draft、New Case absent、Sample=0、Run=0。Codex MCP 必须指向本次 8020，
不能误用个人配置中的旧 8010。浏览器 1920×1080、100% 缩放，关闭通知，不展示 `.env`、密钥、私有路径。

## 第一幕｜定位与真实边界（约 50 秒）

展示 PPT 第 1—4 页和 EditFlow `/capabilities`。讲清：真实的是 Agno、DeepSeek、HTTP/SSE、Session 和
工具选择；受控的是图片工具结果。AgentRig 不选工具，也不执行关键词路由。

## 第二幕｜Codex 读取 Skill 并治理用例（约 80 秒）

在 EditFlow 仓库给 Codex 完整任务。保留以下动作：

```text
$prompt-regression-governance
freeze Git / model / model_input_sha256
list_test_cases(tags=[editflow])
get_test_case / get_test_case_schema
update draft cases
create case_editflow_one_step_mixed_chain
```

切 Web 用例审核，由人类批准正式矩阵。旁白明确三条建议新增风险已有 Case，真正 New Case 只有
`case_editflow_one_step_mixed_chain`，防止把预置资产冒充现场生成。

## 第三幕｜Before 与最小 Prompt 修复（约 105 秒）

Codex Preview 1 Cell / 5 Attempts / 0 skipped，携带 Manifest Hash 提交。展示同一 Before Run 中通过和
失败 Attempt，强调 `completed ≠ pass`。下钻失败 Timeline，确认是 `inspect_image` 顺序不稳定等行为回归，
不是 Provider miss。

随后展示精简 Diff：收窄 `retouch_photo`，背景/素材/比例使用专用工具，修改步骤消费最新图片引用。
执行 `ruff` 与非 Live 测试；重启 EditFlow，并排展示 Before/Candidate Prompt SHA 不同。

## 第四幕｜Candidate 与 30 次回归（约 65 秒）

先展示 headline 同 Manifest 从 2/5 到 5/5；再展示六 Case × 五次的最终矩阵。至少展开一条混合修图
Timeline，画面必须能看见：

- `inspect_image` 在改变图片前；
- `search_assets` 返回 `background-snow-01`；
- `retouch_photo` 和 `apply_asset` 都有 `preserve_subject=true`；
- `apply_asset.image_ref=image-demo-edit-01`；
- `crop_photo.image_ref=image-demo-edit-02` 且 `ratio=4:5`；
- 单项调亮没有搜索、应用素材或裁剪；
- 素材空结果可以有限改写查询，但最终不调用 `apply_asset`。

## 第五幕｜Real Tool → Sample → Replay（约 48 秒）

运行 inspect-only Capture Case：展示 `provider=real_tool`、`backend_tool_name=editflow__inspect_image` 和
`source=real_tool`。Codex 使用 `tool_call event.id` 创建 Draft Sample；切 Web 工具结果审核，由人类批准；
再展示 Sample-only 5/5，5 个 Sample hit、该 Replay Run 中 0 个 `real_tool` Provider Attempt。

## 第六幕｜Web 助手辅助入口（约 47 秒）

普通用户输入“用已有调亮用例验证 EditFlow，受控结果，重复三次，先生成计划”。展示：模型生成 Plan；
`repeated execution` 要求确认；确认后尚无 Run；提交后创建 Run；终态 3/3。不要说它必须复制 Codex 方案。

## 第七幕｜证据报告与平台优势（约 45 秒）

Codex 用一屏输出 Decision、两份 Prompt SHA、Run/Manifest、Case 分类、硬用例 Attempts、Sample 来源、
仓库门禁和限制。最后回到平台架构：多 Driver、多 Provider、Rule/Judge、人工审核、报告和 Gate；lassist
作为真实生产形态兼容附录，EditFlow 作为公开可复现主场景。

## 失败预案

- Before 5/5：停止红转绿叙事，不复用彩排失败；改讲风险审计或重新选择真实问题。
- Provider miss：先归类 `CASE_INVALID` 并修 Case，不算模型失败。
- Candidate hard Case 有一次 Fail：只能 `PARTIAL/REJECT`，不能挑绿色 Attempt。
- Prompt SHA 未变：停止 Candidate，重启并重新冻结身份。
- Sample 未批准：停在 Draft；Codex 不得绕过人工边界。
- Web 助手慢：剪掉等待，但保留同一 Session/Plan/Run 的真实事件。

完整逐秒旁白、减法顺序和 ledger 见
[16-EditFlow-Codex-AgentRig正式录制剧本-待Review.md](./16-EditFlow-Codex-AgentRig正式录制剧本-待Review.md)。
