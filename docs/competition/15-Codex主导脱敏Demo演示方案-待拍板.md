# Codex 主导的脱敏 EditFlow Demo 演示方案

> 状态：方向已拍板，完整链路已彩排；正式录制待执行  
> 更新：2026-08-14（Asia/Shanghai）  
> 主次：Codex 开发治理为主，AgentRig Web 助手为辅  
> 详细剧本：[16-EditFlow-Codex-AgentRig正式录制剧本-待Review.md](./16-EditFlow-Codex-AgentRig正式录制剧本-待Review.md)

## 1. 已拍板结论

公开参赛主场景使用从零编写、MIT 开源的 **EditFlow Demo Agent**，不展示 lassist 私有代码、Prompt、
工具文案、图片和路径。lassist 保留为内部/附录兼容证据，证明 AgentRig 不是只为 Demo 定制。

```text
开发者 + Codex + EditFlow 项目 Skill
                  │ AgentRig MCP
                  ▼
      Case 治理 / Before / Prompt Diff / Candidate
                  │
        Run / Cell / Attempt / Timeline / Sample
                  │
      AgentRig Web 人工审核 + 普通用户辅助入口
```

AgentRig 不替 Codex 改 Prompt，也不替 EditFlow 选工具；它负责评测资产、结果 Provider、身份冻结、重复执行、
证据、人工边界和验收报告。

## 2. 被测 Agent

EditFlow 是 Agno + DeepSeek 的单 Agent 修图助手，PostgreSQL 只保存一张 Session 表，不使用 Redis。

| 工具 | 专属职责 |
|---|---|
| `inspect_image` | 查询尺寸和主体 |
| `retouch_photo` | 调亮、调色、皮肤和画面清理 |
| `search_assets` | 搜索公开演示素材 |
| `apply_asset` | 应用本轮搜索返回的素材 ID |
| `crop_photo` | 按明确比例裁剪 |

模型推理、HTTP/SSE、Session、工具选择和参数真实；Fixture/Sample/MCP 返回虚构图片引用，不处理图片字节。

## 3. 要修复的真实问题

用户要求一步完成“调亮、雪山背景、4:5、人物不变”。Baseline 把 `retouch_photo` 描述得过宽，又要求
复杂编辑优先最少调用，导致模型偶尔先调亮后检查，或跨越专用工具边界。彩排 Before 在同一冻结 Case
下五次有两次 behavior fail，不是人为固定红灯。

Candidate 的最小修改：

- `retouch_photo` 只做当前图片像素调整；
- 背景/装饰使用 search + apply，比例使用 crop；
- 人物保护前先 inspect；
- 每个修改步骤消费最新 `output_image_ref`；
- 搜索为空时可有限改写，但不得编造 `asset_id`；
- 正确性与数据依赖高于减少工具调用。

## 4. 用例治理

| 分类 | Case | 处理 |
|---|---|---|
| Change | `case_editflow_mixed_chain` | 公平 Fixture，约束真实依赖与引用 |
| Change | `case_editflow_brighten_only` | 防过度路由，人物约束前检查 |
| New | `case_editflow_one_step_mixed_chain` | 正式现场创建，不预置 |
| Reuse | background / preserve / crop / asset miss | 覆盖专用链、约束、负向边界 |
| Exclude | inspect sample capture | 只用于 Sample 支线 |

Fixture 只提供结果，不把正要测试的 `image_ref`、`asset_id`、`preserve_subject` 或 `ratio` 同时当命中门槛。
合理的可选 inspect 和有界查询改写不应产生假红灯。

## 5. 已完成彩排

- Before：`run_412269…`，3/5；Candidate headline：`run_3ee180…`，同 Manifest 5/5；
- 最终矩阵：`run_38a956…`，6 Cells / 30 Attempts，30/30；
- Real Tool → Sample → Replay：真实 MCP 1 次，Sample hit 5，Replay real_tool Attempt 0；
- Web Assistant：自然语言 Plan、重复执行确认、分离提交、Run 3/3；
- EditFlow：34 tests；Web：typecheck、真实 Browser E2E 和 Axe 通过。

## 6. 正式视频结构

完整母版 7:20：场景与边界 0:52、Skill/Case 1:18、Before/Fix 1:45、Candidate 1:28、Sample 0:48、
Web 0:47、结论与收尾 0:42。Review 后再按比赛硬限制做 4 分钟减法，优先删解释，不删身份、Attempts、
人工审核和 Sample 来源。

## 7. 平台优势

1. **真实决策、受控副作用**：比纯 Mock 更真实，比全 Real 更安全经济；
2. **身份冻结与方差可见**：Prompt SHA + Manifest + 独立 Attempt；
3. **Case 也是治理资产**：Draft、人工审核、不可变快照和错误归因；
4. **真实结果可资产化**：Real Tool 事件 → Draft Sample → 人审 → Sample-only；
5. **开发者与普通用户双入口**：方案可不同，事实内核一致；
6. **框架与裁决可替换**：Driver/Provider/Rule/Judge/Gate 独立；
7. **开源与生产形态互证**：EditFlow 可复现，lassist 证明兼容真实复杂 Agent。

## 8. 正式录制前剩余动作

1. 为 EditFlow baseline/candidate 准备干净 tag/commit；
2. 创建全新 recording DB，`--recording` preflight 必须 clean；
3. Codex MCP 改到录制实例 8020；
4. 按 ledger 产生正式 Case、Run、Sample、Plan ID；
5. 录制 Codex、Case/Sample 人审、Candidate Timeline 和 Web Assistant；
6. 更新 PPT/视频中的彩排 ID 为正式 ID，或明确标注“彩排”；
7. 执行隐私、音视频、Browser、PPT/PDF 和提交包验收。
