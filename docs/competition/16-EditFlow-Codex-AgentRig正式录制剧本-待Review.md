# EditFlow × Codex × AgentRig 正式录制剧本（待 Review）

> 状态：完整 Review 版；核心链路已彩排，尚未按本剧本正式录制  
> 更新：2026-08-14（Asia/Shanghai）  
> 建议成片：7 分 20 秒完整母版；Review 后再裁 4 分钟竞赛版  
> 主次关系：Codex 项目工作流约 68%，AgentRig Web 约 22%，平台定位与收尾约 10%  
> 被测 Agent：公开脱敏的 EditFlow Demo Agent，不展示 lassist 私有资产

## 1. 这条视频只证明什么

主叙事只讲一件事：

> 开发者在 EditFlow 项目中用 Codex 和项目 Skill 修改 Prompt；AgentRig MCP 把真实模型行为转成
> 可审核的 Sample、Case、Run、Cell、Attempt 和事件证据；普通用户随后可在 AgentRig Web 助手中
> 复用这些资产发起评测。

AgentRig 是辅助评测基础设施，不替 Codex 修改代码，也不替被测 Agent 选择工具。两种入口不要求
生成相同方案；统一的是 Target、Case、Profile、受控结果边界和证据合同。

视频需要同时证明四点：

1. 被测的是 Agno + DeepSeek 的真实 Agent 决策，不是硬编码短语路由；
2. Codex 确实读取项目 Skill，并实际调用 AgentRig Core MCP 完成治理和回归；
3. 一次真实本地 MCP 工具结果可以沉淀为人工审核的 Sample，后续低副作用复用；
4. 结论可以下钻到 Prompt SHA、Manifest、Cell、Attempt、工具参数和结果来源。

## 2. 已核验的真实现状

以下内容已经根据当前代码和 2026-08-14 的实跑结果核验，正式录制不能改写口径。

### 2.1 当前确实具备

- EditFlow 使用 `agno==2.6.11`、`deepseek-v4-flash` 和五个 external-execution 工具；
- EditFlow 用 PostgreSQL 的 `editflow_sessions` 表保存会话，不使用 Redis；
- AgentRig 可经 HTTP/SSE 观察工具调用，并向 Agent 回灌工具结果；
- 本地 EditFlow MCP 后端会走真实 MCP 协议，但只返回公开、确定性的演示结果，不调用图片 API；
- AgentRig MCP 可创建 draft Case 和 draft Sample，不能代替人类批准；
- Run 会冻结 Manifest、Target/Profile/Case 快照，Cell 下每次重复都是独立 Attempt；
- Web 已有用例审核、工具结果审核、Run/Cell 证据下钻和智能评测助手页面；
- EditFlow、AgentRig 基础助手使用同一个 DeepSeek 模型系列。

### 2.2 当前真实基线问题

正式 headline 使用下面这条更能稳定暴露冲突的用户请求：

> 为了快，请一步完成：把照片调亮，换成雪山背景，再裁成 4:5，人物不要改变。

它不是人为注入固定失败，而是同时触发当前 Prompt 中两条冲突规则：

- `retouch_photo` 被描述为可以处理“组合修图需求”；
- 复杂编辑被要求“优先合并为最少工具调用”。

2026-08-14 使用真实 DeepSeek、HTTP/SSE 和真实本地 MCP 后端做了 5 次独立预检：

| 项目 | 实测值 |
|---|---|
| Run | `run_d08696d8c20e43f487f15d8ffc1110fc` |
| Manifest | `sha256:2d21b1bbd0d86a7478bc965de4cc1b607b12d6cbfe86530e85cc508837d2f27d` |
| Attempts | 5 |
| 结果 | 0 Pass / 5 Fail |
| 主要事实 | 4 次没有 `inspect_image`；另 1 次先 `apply_asset` 后 `retouch_photo` |

这个 Run 只是剧本可行性证据，不进入正式成片：其临时 Case 目录项已经删除，历史 Run 仍保留冻结
Case Snapshot。正式拍摄必须重新创建正式 Case，并产生全新的 Before/Candidate Run。

### 2.3 参考建议中需要纠正的地方

参考稿提出的三条“新增”风险，在当前 seed 中已经存在：

| 参考名称 | 当前已有 Case | 正确处理 |
|---|---|---|
| `brighten_only_no_over_routing` | `case_editflow_brighten_only` | Change：增强断言，不冒充新增 |
| `asset_search_miss_no_invention` | `case_editflow_asset_miss` | Reuse：已有空结果与禁止 apply 断言 |
| `preserve_subject_propagation` | `case_editflow_preserve_subject` | Reuse/Change：按实际断言审计 |

正式现场真正新建：

```text
case_editflow_one_step_mixed_chain
```

它覆盖“用户要求一步完成时，正确性和专用工具边界仍必须优先”的新风险。

另有两条能力边界必须诚实表达：

- `search_assets` 与 `retouch_photo` 彼此可独立执行，不能强制二者的相对先后；只约束
  `search_assets → apply_asset`、`retouch_photo → apply_asset → crop_photo` 等真实依赖；
- 真实 MCP 会返回动态 `output_image_ref`。当前 Rule 可校验顺序、参数 Schema 和引用形态，但不能通用地
  表达“本次下游参数必须等于任意上游事件刚返回的值”。精确引用串联放在固定 Fixture 结果的正式回归中，
  真实 MCP Run 用 Timeline 展示动态事实，不能过度宣称。

### 2.4 2026-08-14 完整彩排结果

以下 ID 来自独立调试数据库，只作为剧本可行性和材料事实依据；正式录制必须从干净 recording DB
产生新 ID，不能把彩排剪成“现场执行”。

| 环节 | 实测证据 | 结果 |
|---|---|---|
| Before headline | `run_4122698d707e4dc29d4740dbc355dfa5` | 同一冻结 Case，5 Attempts：3 Pass / 2 Behavior Fail |
| Before Manifest | `sha256:04c0bad3b1b5b29704cece3dceff036301b46f2afb03fb079e5e315a69f966ec` | 1 Cell / 5 Attempts / 0 skipped |
| Before Prompt SHA | `43157c294fef4cc0cacd2089a0973402cb15794421340504f8a35f546f879572` | broad routing baseline |
| Candidate headline | `run_3ee1800bcbbe4f4e92e2e44fc48825ac` | 同 Manifest、同 Case Snapshot，5/5 Pass |
| Candidate Prompt SHA | `71adb390cb86dd05dc5fdc1d9cf2656a436525176ccf178543eaf81a65dff7fd` | Prompt 与工具 description 变更后重启 |
| 最终回归矩阵 | `run_38a956103b0c495b81bffaf0c272e84a` | 6 Cells / 30 Attempts，30/30 Pass |
| 回归 Manifest | `sha256:41f05d702a0fb09bc783722032a10dd2e3f319c2e7d86bb17ac334bd0c8bb694` | 6 个 Case 快照全部冻结 |
| Asset miss 复验 | `run_6696d3b7d2db40a98c5fd3b4de7d9f4e` | 允许有限查询改写，最终无 `apply_asset`，5/5 Pass |
| Real MCP Capture | `run_6791c49056af4da4b236d3e550d2869e` | `editflow__inspect_image` 真实 MCP 命中 1 次 |
| Sample | `sample_editflow_inspect_real_20260814` | `source_type=real_tool`，Draft 经人工审核为 approved |
| Sample-only Replay | `run_6294d74c3814420dad8d780d322861d1` | 5/5 Pass；Sample hit 5，`real_tool` Provider Attempt 0 |
| Web Assistant | Session `asst_b0c42e2e33834864b5ac64b17fa8f9d7` | 自然语言创建、确认并提交 Plan |
| Web Plan / Run | `plan_1a8bdd9c183a45a0a2753f935c189090` / `run_76307bc45f55414490c598033d6d28b9` | repeated execution 触发确认；3/3 Pass |
| 仓库门禁 | `ruff` + `pytest -m "not live"` | EditFlow 34 passed，1 live deselected |
| 前端彩排 | `editflow-recording.spec.ts` | 真实 8024 后端，1 passed；Axe critical/serious=0 |

彩排还纠正了两个重要建模问题：可选的只读 `inspect_image` 不应导致 Fixture miss；素材检索第一次为空后，
模型可以做有界的 query refinement，真正的硬约束是不能编造 `asset_id` 或调用 `apply_asset`。这些
`CASE_INVALID` 被修正后才生成最终 30/30 Run，未把基础设施错误伪装成行为回归。

## 3. 正式录制初始状态

不要复用当前开发数据库录制。创建专用 AgentRig recording DB，保证画面没有 lassist、旧会话、临时
诊断 Case 或无关 Run。

录制开始前应有：

- 1 个 Target：`target_editflow_http_sse`；
- 3 个 Profile：Fixture、真实 MCP 采样、已审核 Sample 回放；
- 当前 7 个 seed Case，其中采样 Case 可提前批准，其余保持 draft 供 Codex 审计；
- Sample 目录为空；
- EditFlow 位于 broad-prompt baseline commit，工作树干净；
- AgentRig 与 EditFlow 的 UI 时间均显示北京时间；
- 浏览器提前登录/打开，但不展示 `.env`、密钥、请求头或个人通知。

当前公开 `main` 仍是 broad-prompt baseline，Prompt/工具目录自初始提交起没有候选修复。录制前先给
当前状态打只读 tag（例如 `recording-baseline-v1`）；不要预先提交 Candidate。正式现场由 Codex 在同一
工作树产生 Diff，Candidate Run 以新的 `model_input_sha256` 冻结身份。验收通过后再提交修复并记录
Candidate commit；如需重拍，从 baseline tag 新建临时 branch，不使用 `git reset --hard` 覆盖现场证据。

建议服务启动方式：

```bash
# 从 agentrig 与 editflow-demo-agent 的共同父目录开始

# Terminal A · EditFlow PostgreSQL
cd editflow-demo-agent
docker compose up -d postgres

# Terminal B · EditFlow Target，读取 .env 但不打印凭据
uv run editflow

# Terminal C · 公开确定性 MCP 工具后端
uv run editflow-tools-mcp --port 8091

# Terminal D · AgentRig，使用专用 recording DB
cd ../agentrig
AGENTRIG_CONFIG_FILE="../editflow-demo-agent/agentrig/agentrig.capture.toml" \
AGENTRIG_DATABASE__URL="sqlite+aiosqlite:///./.agentrig/editflow-recording.db" \
uv run agentrig serve --port 8020

# Terminal E · 首次初始化并审计录制资产
cd ../editflow-demo-agent
uv run editflow-seed-agentrig --recording \
  --base-url http://127.0.0.1:8020 \
  --target-endpoint http://127.0.0.1:8090

# Codex 需要连接本次 8020 实例；不要误用个人环境里的旧 8010 配置
# 如果 `codex mcp get agentrig` 显示旧 8010，先执行：codex mcp remove agentrig
codex mcp add agentrig --url http://127.0.0.1:8020/mcp/
codex mcp get agentrig
```

正式拍摄前必须在 Codex 中确认 `agentrig` 的工具可发现，并做一次只读 `check_target`。如果当前 Codex
会话无法调用 8020 MCP，就停止录制；不要用普通终端 `curl` 冒充 Codex 调用了 MCP。

健康检查：

```bash
curl -fsS http://127.0.0.1:8090/health
curl -fsS http://127.0.0.1:8090/capabilities
curl -fsS -X POST \
  'http://127.0.0.1:8020/api/targets/target_editflow_http_sse/check?version=working-tree'
curl -fsS http://127.0.0.1:8020/api/v2/assistant/provider-health
```

当前 AgentRig 的 `/health` 会被 SPA fallback 接管并返回 HTML，因此不用它作为后端健康证明；以上
Target Check 和 Assistant Provider Health 才是录制链路需要的实际探针。

正式录制前，另跑一次不会进入成片的隔离全链路预检（脚本会在随机端口启动内存 AgentRig，验证
Target → AgentRig → MCP Sample → 5 次回放，不会写入 8020 的 recording DB）：

```bash
cd editflow-demo-agent
uv run --with ../agentrig python scripts/verify_full_sample_capture.py --live-deepseek
```

没有 `--live-deepseek` 时使用的是 CI 决策模型，不能作为真实模型兼容证据。

## 4. Codex 现场任务原文

在 EditFlow 仓库中启动 Codex，完整粘贴下面的任务：

> 使用 `$prompt-regression-governance` 治理 EditFlow 的 Prompt 路由回归。用户说“为了快，请一步完成：
> 把照片调亮，换成雪山背景，再裁成 4:5，人物不要改变”时，正确性、工具专属边界和结果依赖必须优先，
> 不能因为“一步完成”省略检查或错误串联。先冻结 Git、模型和 model input SHA；通过 AgentRig MCP
> 审计已有 Case，按 Reuse / Change / New / Exclude 分类，至少现场创建一个真实的新 Case；对公平断言
> 执行 5 次 Before；只修改必要的 Prompt 或工具 description；重启后执行 Candidate 和相关回归。
> 最后基于 Run / Cell / Attempt / Event 输出 ACCEPT、PARTIAL 或 REJECT。不要调用真实图片 API，
> 不要替人类批准 Case 或 Sample，也不要把父 Run 的 completed 当成业务通过。

这段任务刻意不告诉 Codex 具体改哪一行，也不预写最终结论。Skill 决定治理流程，AgentRig 提供事实。

## 5. 用例治理口径

Codex 读取 Schema 和现有 Case 后，应得到下面的分类。实际发现不一致时以代码和 MCP 回读结果为准，
不能为了匹配剧本强行输出。

| 分类 | Case | 现场动作 | 关键原因 |
|---|---|---|---|
| Change | `case_editflow_mixed_chain` | 修订 Fixture 与依赖断言 | 旧版把独立搜索和调亮写成严格全序，且自然语言 instruction 匹配过窄 |
| Change | `case_editflow_brighten_only` | 增加 `search_assets` 禁止断言，放宽 instruction Fixture | 防止 Prompt 修改让简单任务过度路由 |
| New | `case_editflow_one_step_mixed_chain` | 从 Schema 创建 draft，现场完整展示 | 新增“一步完成不能破坏专用工具 contract”风险 |
| Reuse | `case_editflow_preserve_subject` | 回读并保留 | 检查 `preserve_subject=true` 传播 |
| Reuse | `case_editflow_asset_miss` | 回读并保留 | 搜索为空时不能调用 `apply_asset` |
| Reuse | `case_editflow_background`、`case_editflow_crop_only` | 回读并保留 | 专用工具单链和简单任务回归 |
| Exclude | `case_editflow_inspect_sample_capture` | 不进入 Prompt Candidate 矩阵 | 它属于 Sample 采集支线，不是这次 Prompt Diff 风险 |

正式 headline Case 的断言只表达真实依赖：

```text
inspect_image 被调用
inspect_image → retouch_photo
search_assets → apply_asset
retouch_photo → apply_asset → crop_photo
retouch_photo.preserve_subject = true
apply_asset.preserve_subject = true
apply_asset.asset_id = background-snow-01
crop_photo.ratio = 4:5
```

Fixture 的职责是提供结果，不应该提前驳回正要测试的错误参数。因此 Fixture 匹配只保留选择结果所需的
最小字段，不把 `image_ref`、`preserve_subject`、`asset_id`、`ratio` 或自然语言 instruction 同时当作
Provider 命中门槛；这些行为契约交给 Rule 断言。这样错误调用也能拿到受控结果并走完，最终得到
可解释的行为 Fail，而不是误变成 `provider_exhausted`。

所有修改和新建结果先是 draft。Codex 完成回读后，镜头切到 AgentRig 的“用例审核”，由人类逐项
审核本次正式矩阵选中的 Case，并点击“批准并冻结”；MCP 不拥有这项权限。Before 与 Candidate 必须
引用同一批冻结 Case Snapshot，不能在两批 Run 之间悄悄改断言。

## 6. Sample 采集支线的准确口径

Sample 支线只演示 `inspect_image`，不冒充完整五工具链 Sample。

真实步骤：

```text
case_editflow_inspect_sample_capture
  + profile_editflow_capture_real_sample
  → 1 个真实本地 MCP tool_result
  → Codex 从 tool_call event.id 创建 draft Sample
  → 人类在 Web 批准
  → profile_editflow_sample_only 重放 5 个独立 Attempts
```

画面必须分别露出：

- Capture Run 的 `provider_attempt.provider=real_tool`；
- `tool_result.source=real_tool` 和 `backend_tool_name=editflow__inspect_image`；
- 新 Sample 的 `source_type=real_tool`、`status=draft`；
- 人工批准后的 `status=approved`；
- Replay Run 的 `provider_attempt.provider=sample`、Sample ID 和 5 个 Attempts。

彩排已通过事件审计证明回放 5 次产生 5 个 Sample hit、0 个 `real_tool` Provider Attempt。正式成片
可以说“该 Replay Run 内真实工具尝试为 0”；仍不能扩张成整个平台或其他进程的全局调用绝对为 0。

## 7. 逐秒录制剧本（7:20 完整母版）

### 00:00—00:20｜问题钩子

画面：固定标题卡，左侧是 Prompt Diff，右侧是 AgentRig Timeline，底部只保留一句问题。

屏幕文字：

```text
一次 Prompt 修改，怎么证明没有修一处、坏三处？
```

旁白：

> Agent 的 Prompt 改动会同时影响工具选择、参数和调用顺序。AgentRig 要做的，是让 Codex 的每次
> 修改都留下可重复、可审核的行为证据。

剪辑要求：固定画面硬切，不做缩放、平移或鼠标追踪。

### 00:20—00:52｜交代真实场景与边界

画面：EditFlow README、五个工具目录和 `/capabilities` 摘要三连切；高亮 `agno`、
`deepseek-v4-flash`、PostgreSQL、`model_input_sha256`。

旁白：

> 公开演示使用脱敏的 EditFlow 修图 Agent。Agno 和 DeepSeek 负责真实推理，PostgreSQL 保存会话；
> 五个工具通过 external execution 交给 AgentRig。图片工具后端是公开的本地确定性 MCP 服务，
> 不上传图片，也不调用第三方图片 API。

屏幕角标：

```text
真实：模型决策 / HTTP-SSE / Session / MCP 协议
受控：图片工具结果 / Rule 评判
```

### 00:52—01:25｜Codex 读取项目 Skill 并冻结身份

画面：在 EditFlow 仓库中向 Codex 提交第 4 节任务；快速展示 Codex 打开
`prompt-regression-governance/SKILL.md`、Prompt 和工具目录。

Codex 应显示的关键清单：

```text
Git commit / worktree
Model: deepseek-v4-flash
Before model_input_sha256
Target: target_editflow_http_sse
Profiles / relevant Case IDs
Allowed change / invariants
```

旁白：

> Codex 先读取项目 Skill，不直接改 Prompt。它冻结源码、模型和 model input SHA，并明确允许变化的
> 路由边界，以及不能破坏的图片引用、素材来源、人物保护和中文回答约束。

不要展示：隐藏思维、完整 SSE、密钥、`.env` 或过长终端日志。

### 01:25—02:10｜MCP 查重、修订旧 Case、创建一个真 New Case

画面：Codex 的 MCP 调用摘要，依次保留：

```text
list_test_cases(tags=[editflow])
get_test_case(case_editflow_mixed_chain)
get_test_case_schema()
update_test_case(...)
create_test_case(case_editflow_one_step_mixed_chain)
```

随后切 AgentRig Web“用例审核”，展示 headline Case 的用户消息、Fixtures、Assertions。为保证
Before/Candidate 使用同一冻结快照，正式拍摄时应在提交 Before 前完成本批 Case 的人工“批准并冻结”；
成片可把审核镜头剪到这里，但 ledger 要记录它实际发生在 Before 之前。

旁白：

> Codex 先查重。单项调亮、素材未命中和人物保护已经存在，所以它们被复用或增强；旧混合用例中
> 不合理的严格全序被修正。现场真正新增的，是“一步完成不能破坏专用工具边界”这一条风险，
> 并由人类审核冻结。

屏幕字幕：

```text
Reuse 4 · Change 2 · New 1 · Exclude 1
```

### 02:10—02:55｜Before：5 次独立 Attempt 证明真实回归

画面：Codex 通过 MCP 执行：

```text
check_target
preview_run_cases → 1 Cell / 5 Attempts / 0 skipped
run_cases(expected_manifest_hash)
get_run_summary
get_run_cell
```

剪掉等待时间，切到同一个 Before Run 的终态和两条失败 Timeline。优先展示：

- 一条没有 `inspect_image` 的 Attempt；
- 一条 `apply_asset → retouch_photo` 导致依赖顺序错误的 Attempt；
- `provider=fixture` 或所用正式 Profile 的真实标签；
- `Run completed` 与 `evaluation_state=fail` 同屏。

旁白：

> Preview 先冻结一个 Cell、五个独立 Attempt，再用 Manifest Hash 提交。父 Run 完成不等于行为通过。
> 当前 Prompt 会在“一步完成”和“最少调用”的压力下省略检查，或先换背景再调亮。Codex 下钻到
> 工具事件后，将它归为有效的行为失败，而不是只看最终文字。

注意：如果正式 Before 没有出现有效硬失败，停止这段故事，按第 10 节失败预案处理；不能沿用预检数字
或拼接其他 Run。

### 02:55—03:32｜Codex 做最小 Prompt/description 修改

画面：只展示精简 Git Diff，建议可见修改为：

```diff
- retouch_photo 可处理……组合修图需求
+ retouch_photo 只调整当前图片像素；背景/装饰和画幅比例必须使用专用工具

- 复杂编辑优先合并为最少工具调用
+ 正确性与数据依赖优先；只合并属于同一工具边界且无依赖冲突的操作
+ 保留主体或智能裁剪前先 inspect_image
+ 每个修改步骤消费当前最新 output_image_ref
```

画面下方快速出现：

```text
uv run ruff check .
uv run pytest -m "not live"
```

旁白：

> 修改只发生在模型可见输入。自由修图被收窄到像素调整；背景、素材和比例回到专用工具；正确性和
> 数据依赖高于最少调用。HTTP 层没有新增关键词路由，也没有为视频写固定答案。

### 03:32—03:55｜重启并证明 Candidate 身份真的变化

画面：重启 EditFlow，Codex 再次 `check_target`；在 Before/Candidate 能力摘要中并排高亮：

```text
Prompt SHA Before:    ...
Prompt SHA Candidate: ...
Process started at:   ...
Model: deepseek-v4-flash
```

旁白：

> Prompt 按进程冻结，所以修改后必须重启。AgentRig 观察到新的 model input SHA；如果 SHA 没变，
> Candidate Run 就没有资格进入验收。

### 03:55—05:00｜Candidate 与 Diff-driven 回归矩阵

画面：Codex Preview 后提交一个正式 Candidate batch；终态只展示紧凑矩阵，不播放等待过程。

建议正式矩阵：

| 风险组 | Case | Attempts |
|---|---|---:|
| Headline | `case_editflow_one_step_mixed_chain` | 5 |
| Change | `case_editflow_mixed_chain` | 5 |
| Change | `case_editflow_brighten_only` | 3；不稳定则扩到 5 |
| Reuse | `case_editflow_preserve_subject` | 5 |
| Reuse | `case_editflow_asset_miss` | 5 |
| Reuse | `case_editflow_background` | 5 |
| Reuse | `case_editflow_crop_only` | 3；不稳定则扩到 5 |

画面至少下钻一条通过 Timeline，并高亮真实依赖，而不是背诵唯一全序：

```text
inspect_image
retouch_photo ───────┐
search_assets ──┐    │
                 ▼    ▼
                apply_asset → crop_photo
```

同时展示：

- `preserve_subject=true` 到达 `retouch_photo` 和 `apply_asset`；
- `asset_id=background-snow-01` 来自本轮搜索结果；
- `crop_photo.ratio=4:5`；
- 单项调亮没有 `search_assets` / `apply_asset` / `crop_photo`；
- 素材空结果后没有 `apply_asset`。

旁白：

> Candidate 先跑 headline，再跑由 Prompt Diff 推导的回归矩阵。AgentRig 展示的不只是绿色总分，
> 而是每个 Cell 的独立 Attempt、工具依赖、约束传播和失败归属。搜索与调亮可以并行，真正必须稳定的
> 是检查、素材来源、结果依赖和专用工具边界。

结论口径：任何 hard Case 未达到全部 Attempt 通过，最终只能是 `PARTIAL` 或 `REJECT`，不能为视频
挑选一个绿色 Attempt 宣称 `ACCEPT`。

### 05:00—05:48｜真实 MCP 结果变成可审核 Sample，再低副作用回放

画面采用预跑后的真实同批次素材，按四个固定镜头硬切：

1. Capture Run Timeline：`inspect_image` → `provider=real_tool` → `source=real_tool`；
2. Codex 调 `create_sample(source_tool_call_id=evt_...)`，返回 `status=draft`；
3. AgentRig“工具结果资产”页面，人工点击“批准”；
4. Replay Run：5 Attempts，`provider=sample`，同一个 Sample ID。

旁白：

> 对真实工具结果，AgentRig 不会静默抓取。Codex 只能从一条已持久化的真实 MCP 事件显式生成 Sample
> 草稿；人类审核后，后续五次回归由 Sample 提供同样结构的结果。这样保留真实来源，同时避免重复
> 消耗工具资源。

屏幕角标：

```text
本段 Sample 仅覆盖 inspect_image
Replay Run 中无 real_tool Provider 事件
```

### 05:48—06:35｜普通用户从 AgentRig 智能评测助手复用资产

画面：AgentRig Web 助手新会话，用户输入：

> 用“一步完成复合修图”用例验证 EditFlow，使用受控结果，重复 5 次；先给我计划，不要直接运行。

剪到计划卡，展示 1 个用例、5 个“用例运行”、0 跳过、结果提供链和评判器；通过“编辑计划”抽屉或
随后 Run 页证明 Target、Case、Profile、5 Attempts 与 Manifest。用户点击“确认计划”，页面应明确
“尚未创建 Run”；再点击“提交运行”，切到关联 Run 与终态通知。彩排中 `repeat_count=3` 自动触发
`repeated execution` 确认原因，证明确认不是装饰性按钮。

旁白：

> 不使用 Codex 的普通用户，也可以用自然语言复用已经治理好的 Target、Case 和 Profile。助手可以
> 生成不同的合理计划，但仍要经过人工确认，并落到同一种 Run、Cell、Attempt 和证据合同。

不要说“助手和 Codex 生成完全相同计划”。

### 06:35—07:05｜Codex 输出证据化验收结论

画面：Codex 最终报告，控制在一屏：

```text
Decision: ACCEPT | PARTIAL | REJECT
Before Run: ...
Candidate Run: ...
Prompt SHA Before: ...
Prompt SHA Candidate: ...
Case changes: Reuse / Change / New / Exclude
Hard Attempts: ...
Failed Cells: ...
Sample Capture Run / Replay Run: ...
Repository checks: ...
Known limitations: ...
```

旁白：

> 最终结论不是“看起来修好了”，而是绑定 Prompt 身份、Case、Manifest、Cell、Attempt 和事件证据。
> 现场事实不满足门槛，Codex 就必须给出 PARTIAL 或 REJECT。

### 07:05—07:20｜平台优势与一句话收尾

画面：固定闭环卡。

```text
Prompt Diff → Case Governance → Before → Candidate
           → Real Evidence → Sample Replay → Decision
```

旁白：

> AgentRig 不替模型思考，也不要求不同模型给出同一方案。它把真实决策、受控副作用、人工边界和
> 可审计证据组合成一套开放评测基础设施。Codex 负责改变 Agent，AgentRig 负责让每次改变可测试、
> 可复用、可追溯。

## 8. 正式成片允许预跑和剪辑的范围

模型执行会产生等待，完整母版也不应录成直播。允许预跑，但必须遵守以下规则：

- Before、Candidate、Sample Capture、Sample Replay 和 Web Assistant 各自使用真实的新 Run；
- 一个段落内展示的 Run ID、Cell、Attempt、Timeline 和结论必须来自同一次 Run；
- 可剪掉排队、模型等待、终端滚动和重复的成功 Attempt；
- 可用 2—4 倍速展示 Codex 调用过程，但关键 JSON 和 Diff 必须停留到可读；
- 不把历史预检 Run 当作正式 Candidate，也不跨 Run 拼一条“完美 Timeline”；
- 不伪造 Codex UI、终端输出、模型回答、Sample 来源或 Gate 结果；
- 正式录制 ID 记录到单独的 recording ledger，截图和旁白只引用 ledger 中的 ID。

建议实际录制顺序不是成片顺序：

1. 先完整录 Codex 主流程并记下所有正式 ID；
2. 再录 Web 审核 Case/Sample；
3. 再录 Web Assistant 和 Run 证据下钻；
4. 最后根据 ledger 剪成第 7 节的时间线。

## 9. 旁白和画面规范

- 1920×1080、30 fps、浏览器与 Codex 缩放固定 100%；
- 录屏不做 zoompan、自动跟随鼠标或后期防抖，场景边界硬切；
- UI 小字不可读时，重新构图或截局部固定画面，不做持续缩放；
- 旁白优先真人；使用 TTS 时沿用自然中文男声，不使用旧机械女声；
- 建议 `zh-CN-YunxiNeural`，语速 -4%、音高 -2 Hz，场景级响度目标 -16 LUFS；
- 字幕每行约 23 个中文字符，术语 `Run`、`Cell`、`Attempt`、`Sample` 保持一致；
- 隐藏桌面通知、菜单栏个人信息、Git credential、`.env`、API Key 和浏览器自动填充；
- 不展示 lassist、Pixcake、客户图片、私有 Prompt 或原项目路径。

## 10. 失败预案与停止条件

| 现场情况 | 正确处理 | 禁止处理 |
|---|---|---|
| Before 5 次全通过 | 停止“红转绿”叙事，改讲 Case/Prompt 风险审计或重新选真实风险 | 复用旧失败数字、故意破坏代码 |
| Before 出现 Provider miss | 先修 Fixture/Sample 契约并重新冻结 Case | 把 `evaluation_error` 当模型失败 |
| Candidate hard Case 有 1 次失败 | 输出 `REJECT` 或继续修复后开启全新 batch | 只展示绿色 Attempt |
| Prompt SHA 未变化 | 重启 EditFlow，重新检查身份 | 把旧进程当 Candidate |
| Target/MCP/DB 故障 | 修环境；必要时从冻结 Cell 做 Recovery | 把基础设施错误算业务回归 |
| Sample 未批准 | 停在 draft，切 Web 人工审核 | Codex 绕过审核或宣称可回放 |
| Web 助手响应较慢 | 剪掉真实等待，保留请求、计划 ID 和确认动作 | 用静态假回复替换 |
| 完整母版需要裁到 4 分钟 | 优先删平台解释、Case 审核细节、重复 Timeline 和 Web 终态等待 | 加速旁白到难以理解 |

硬停止条件：

- 无法证明使用真实 DeepSeek；
- Before/Candidate 混用了不同 Case 定义但没有明确标注；
- Candidate 的 required hard Attempt 未全部通过却准备说 `ACCEPT`；
- 正式画面出现密钥、私有项目名或客户数据；
- Sample 来源不是 `real_tool` 事件却准备称为真实采样。

## 11. 正式录制 ledger 模板

开始正式拍摄时复制下面表格到新的事实记录文件，禁止提前填写虚构 ID。

| 证据 | 正式值 | 验证点 |
|---|---|---|
| EditFlow baseline commit / candidate commit | 待录制 | baseline clean；candidate 验收后提交 |
| Model | 待录制 | `deepseek-v4-flash` |
| Before Prompt SHA | 待录制 | `/capabilities` |
| Candidate Prompt SHA | 待录制 | 与 Before 不同 |
| New Case ID | 待录制 | draft → 人工 approved |
| Before Run / Manifest | 待录制 | 5 independent Attempts |
| Candidate headline Run / Manifest | 待录制 | 5/5 hard threshold |
| Candidate regression Run / Manifest | 待录制 | 全部相关 Case |
| Capture Run / source event | 待录制 | `real_tool` |
| Sample ID | 待录制 | `source_type=real_tool` / approved |
| Replay Run | 待录制 | 5 Attempts / `sample` |
| Web Assistant Session / Plan / Run | 待录制 | 两阶段确认 |
| Final Decision | 待录制 | 与事实一致 |

## 12. Review 后的减法顺序

当前先保留完整 7:20 母版。若比赛平台最终硬限 4 分钟，按以下顺序删除，不改变事实链：

1. 将场景介绍从 32 秒压到 18 秒；
2. Case 分类只保留 New Case 与人工审核，删去逐条 Reuse 说明；
3. Candidate 矩阵只展开 headline Timeline，其余用一屏矩阵；
4. Sample 支线从 48 秒压到 25 秒，但保留 real_tool → draft → approved → sample 四个状态；
5. Web Assistant 只保留自然语言、确认、Run 三屏；
6. 最终证据报告与平台优势合并为 20 秒。

不建议删除 Before/Candidate Prompt SHA、Manifest、独立 Attempts、人工审核边界或 Sample 来源；这些
正是 AgentRig 区别于普通聊天 Demo 和单次脚本测试的核心证据。
