# AgentRig：被测 Agent 上下文选择与联动一致性 RFC

> RFC ID：AR-RFC-0003
>
> 状态：Proposed
>
> 版本：0.1
>
> 日期：2026-08-11
>
> 优先级：P0 上下文一致性，P1 元数据完整性
>
> 前置设计：`05-V2-完整产品与界面开发设计.md`
>
> 相关契约：`03-V2-智能评测助手与AgentTeams-开发设计.md`、
> `09-V2.3-Agent运行时验证与生产证据闭环/04-Target-Capability-Snapshot.md`

本 RFC 记录 Target 工作区顶部“被测 Agent”区域的产品语义、当前缺口与拟议修复。
核心问题不是少一个下拉菜单，而是页面展示的 Target、助手会话绑定的 Target 和实际
EvaluationPlan/Run 使用的 Target 缺少统一、可见、可验证的上下文规则。

RFC 被接受和实施前，不将当前顶栏解释为已具备 Target 切换能力。

---

## 0. 决策摘要

1. Target 工作区顶栏从“静态运行信息”升级为明确标注的“当前被测 Agent”上下文
   选择器。
2. `/targets/:targetId/*` 中的 `targetId` 是当前工作区 Target 的权威来源；选择新
   Target 必须更新 URL，不使用仅存在于组件内存的隐式选择。
3. Target 名称、环境、版本、Driver/协议、健康状态必须来自当前 Target 或当前历史
   资源的冻结快照；不再硬编码“本机”，不再默认把 `versions[0]` 当作已选版本。
4. 切换 Target 后，Target 范围内的会话、计划、运行、资产、证据和能力信息必须一起
   切换；平台级用户、通知和 Evaluator Team 定义不随 Target 切换。
5. AssistantSession 在创建时绑定 Target 工作区，会话列表必须按该绑定筛选。切换
   Target 不会修改原会话、已确认 Plan 或已创建 Run。
6. Run、CaseRun、Comparison 和 Report 继续以冻结快照为权威执行事实；顶栏切换只导航
   工作区，绝不重写历史记录。

---

## 1. 背景与当前实现

### 1.1 用户看到的界面

智能评测助手顶部展示了一组类似以下的信息：

```text
Public deterministic HTTP/SSE reference target | 本机 | baseline | http_sse
```

这组信息在视觉上像“当前被测 Agent”选择器，但当前没有下拉、搜索、切换或焦点
交互，用户无法判断它是可操作上下文、状态摘要，还是演示用静态标签。

### 1.2 代码现状（2026-08-11）

相关实现分布在：

- `web/app/components/shell/app-shell.tsx`：根据路由 `context.targetId` 查找 Target，但顶栏使用不可
  交互的 `div`；
- 环境标签固定渲染为“本机”；
- 版本标签直接使用 `target.versions[0].version`；
- Driver 标签来自 `target.driver_type`；
- `web/app/pages/v2/assistant-page.tsx`：新会话把路由 Target ID 写入
  `AssistantSession.workspace_id`，但会话列表查询未按 `workspace_id` 筛选，并会自动选中
  跨 Target 的最近会话；
- Core Manager 规划时优先把 `AssistantSession.workspace_id` 匹配为 Target ID，Plan 最终又在
  `selection.targets[]` 中保存实际执行目标。

因此，当前同一页面存在三个可能不一致的 Target 来源：

```text
顶栏 / URL Target
       │
       ├── 当前 AssistantSession.workspace_id
       │
       └── EvaluationPlan.selection.targets[] / Run 冻结快照
```

### 1.3 问题定性

这是一个“导航上下文与执行上下文可能错位”的一致性问题，具体风险包括：

- 用户无法直接切换被测 Agent，只能返回目录后重新进入；
- “本机”和第一个版本可能不是真实当前上下文；
- 顶栏显示 Target A 时，中间区域可能选中 Target B 的助手会话；
- 用户可能在错误的心智模型下确认评测计划；
- 前端查询缓存如果不包含 Target ID，切换时可能短暂展示上一 Target 的数据；
- 历史资源与当前可变 Target 配置的展示语义不够清晰。

Plan 和 Run 的冻结契约可以防止已创建执行事实被后续配置覆盖，但不能消除用户在创建、
修订和确认之前选错 Target 的风险。

---

## 2. 目标与非目标

### 2.1 目标

1. 让用户始终知道当前工作区属于哪个被测 Agent，并能直接切换。
2. 让 URL、顶栏、页面查询、助手会话和新建 Plan 默认使用同一 Target 上下文。
3. 确保 Target 切换不会取消运行中任务，也不会修改历史 Plan、Run、CaseRun 或 Report。
4. 让 Target 关联元数据有权威来源、缺失语义和加载/错误状态。
5. 使上下文选择支持键盘、读屏、深链接和浏览器刷新。

### 2.2 非目标

- 不在顶栏内实现 Target 创建、编辑或删除；
- 不把 Target 选择器扩展为任意多 Target 编排器；
- 不改变现有 A/B Run 的 `baseline/candidate` 和冻结快照契约；
- 不在 Target 切换时自动提交、取消或重跑任何评测；
- 不让 Target 选择同时改变项目/租户安全边界；
- 不在本 RFC 中建设跨 Target 对比产品流程。

---

## 3. 上下文模型

### 3.1 四层 Target 语义

| 层级 | 权威来源 | 是否可切换 | 用途 |
|---|---|---:|---|
| 工作区 Target | URL `:targetId` | 是 | 导航、列表筛选、新建资源默认值 |
| 助手会话 Target | `AssistantSession.workspace_id` | 否 | 限定会话的规划目标 |
| 草稿 Plan Target | `EvaluationPlan.selection.targets[]` | 可通过 Plan revision 修订 | 预览即将执行的范围 |
| 执行事实 Target | Run/CaseRun 冻结快照 | 否 | 执行、证据、评判、报告与审计 |

当前 `workspace_id` 已被 Core Manager 当作 Target ID 使用。P0 保留该存储与线上契约以避免
不必要迁移，但明确它在 Target 工作区中表示会话所属 Target。如果后续的 Workspace 领域需要
同时容纳多个 Target，应新增显式 `target_id` 并单独迁移，不在本次修复中悄然改变字段语义。

### 3.2 一致性不变量

- Target 工作区内展示的 AssistantSession 必须满足
  `session.workspace_id == route.targetId`；
- 新 AssistantSession 的 `workspace_id` 必须等于提交时的路由 Target ID；
- 普通单 Target Plan 的 `selection.targets[*].target_id` 必须与会话 Target 相同；
- 已确认 Plan 如需更换 Target，必须创建新 draft/revision 并重新确认；
- 已创建 Run 只读取自身冻结快照，不反向读取顶栏当前值；
- 路由 Target 与资源归属不一致时，页面必须拒绝混合展示，返回明确错误或导航到
  资源的规范 Target 路由。

---

## 4. 交互决策

### 4.1 顶栏结构

顶栏展示为：

```text
当前被测 Agent  [ Target 名称 ⌄ ]  [环境]  [版本上下文]  [Driver/协议]  [健康状态]
```

- Target 名称是按钮/组合框，打开后可按名称或 ID 搜索有权访问的 Target；
- 每个选项展示名称、简短 ID、Driver 和健康摘要；
- 当前 Target 有明确选中标记；
- 加载、空目录、无权限、Target 已删除和查询失败都有独立状态，不静默回退到
  其他 Target；
- 组合框支持 Tab、上下方向键、Enter 和 Escape，具有可读标签、`aria-expanded` 和焦点
  恢复。

### 4.2 切换行为

选择 Target B 时：

1. 若当前有未保存的本地表单或 Plan 编辑，先使用项目统一的离开确认；
2. 导航到 B 的等价 Target 工作区路由，例如
   `/targets/A/assistant` → `/targets/B/assistant`；
3. 清理当前页面的短期选中状态，重新选择 B 范围内的会话/列表项；
4. 以 B 作为 query key 的一部分重新读取数据；加载期间不显示 A 的旧数据；
5. A 中已提交的 Run 和 AgentInvocation 继续在服务端运行，切换动作不触发取消。

对于带资源 ID 的详情路由，如 `/runs/:runId`，不能把 A 的资源 ID 直接拼接到 B 的路由。
切换后导航到 B 的对应列表页；用户如需查看原资源，仍可通过原 Target 的规范深链接返回。

### 4.3 版本与 A/B 语义

版本标签不得仅因为它排在 `versions[]` 第一位就显示为“当前版本”。显示优先级为：

1. Run/CaseRun/Report 详情页的冻结版本；
2. 当前 AssistantSession 活跃 Plan 中的显式版本；
3. Target 只有一个可用版本时的唯一版本；
4. 多版本但尚未产生执行选择时，显示“多版本”或“未指定”。

A/B Plan 应显示 `baseline ↔ candidate`，而不是只显示其中一侧。Target 选择器不代替 Plan 中
的版本选择和人工确认。

### 4.4 环境、协议和健康信息

| 信息 | 权威来源 | 缺失时行为 |
|---|---|---|
| Target 名称/ID | Target 资产 | 页面报错，不伪造名称 |
| 环境 | 显式 Target 环境元数据 | 显示“未标注”或省略，不固定显示“本机” |
| 版本 | Plan/冻结快照/Target 版本契约 | 显示“未指定” |
| Driver/协议 | `driver_type` 与 Capability Snapshot | 显示“未知”，不自行推断 |
| 健康状态 | 最近一次 Target check/probe 及时间 | 显示“未检查” |

环境不得通过 endpoint 字符串猜测。P0 如果暂无类型化环境字段，宁可省略该标签；
P1 在 Target Schema 中新增可选的环境展示元数据，并对历史 Target 保持可空兼容。

---

## 5. 联动范围

| 区域/数据 | 是否随 Target 切换 | 规则 |
|---|---:|---|
| 顶栏名称、环境、版本、Driver、健康 | 是 | 全部来自新 Target 上下文 |
| 总览、对话验证、运行、报告、能力 | 是 | 查询和 query key 必须包含 Target ID |
| 智能助手会话列表 | 是 | 只显示 `workspace_id` 匹配的会话 |
| 当前选中会话、Plan、Decision 和 Invocation | 是 | 切换后清空旧选择，再选中新 Target 的内容 |
| TestCase、Sample、Profile | 按适用性联动 | 全局资产可存续，但页面只展示对当前 Target 可用或明确标注不兼容的项 |
| Manager/Curator/Judge 定义 | 否 | Evaluator Team 是平台级执行能力 |
| Manager/Curator/Judge 实际调用证据 | 是 | 属于当前 Session/Run 的调用必须联动 |
| 通知、用户菜单、平台运行状态 | 否 | 保持平台全局语义 |
| 已提交或历史 Run | 否 | 继续运行并保留原冻结快照 |

---

## 6. API 与前端状态契约

### 6.1 P0 API

复用现有 Target 接口，新增助手会话范围过滤：

```http
GET /api/targets?limit=100
GET /api/targets/{target_id}
GET /api/v2/assistant/sessions?workspace_id={target_id}&limit=50
POST /api/v2/assistant/sessions
```

`POST /assistant/sessions` 在 P0 继续接收 `workspace_id`，但服务端必须验证该 ID 在当前项目
内对应真实 Target。`GET /assistant/sessions` 的 `workspace_id` 过滤必须与项目隔离条件同时生效。

不引入另一个可变的“当前 Target”服务端全局状态；URL 与资源归属已经足以完成可重放
的上下文表达。

### 6.2 前端缓存与请求

- Target 范围查询的 query key 必须包含 `targetId`；
- 助手会话从 `['v2', 'sessions']` 调整为类似
  `['v2', 'sessions', targetId]`；
- mutation 必须在发送时捕获当前 Target ID，不依赖切换前的闭包或缓存项；
- 响应返回后如果路由已切换，不得把旧 Target 数据注入新 Target 视图；
- 当 Target 不可访问或已删除时展示明确的 not-found/forbidden 状态，不自动选择列表
  第一项代替。

### 6.3 历史资源

Run/CaseRun 详情页的标题与元数据必须优先使用冻结 `target_snapshot` 和
`TargetCapabilitySnapshot`。当前 Target 资产后续改名、改 endpoint 或改 Driver 时，历史执行事实
不随之改写。

---

## 7. 错误、竞态与安全边界

- 用户在请求进行中切换 Target：可取消纯读前端请求，但已被服务端接收的写操作按
  原幂等契约完成，不伪装为已取消；
- Target 在下拉菜单打开后被删除：选择时重新校验，失败后留在当前页面并提示；
- Session 与路由 Target 不一致：前端不渲染该 Session，服务端关键写操作再次校验；
- 用户只能在选择器中看到当前项目且有权访问的 Target；
- endpoint、secret reference 和未脱敏 Capability 不进入选择器选项或前端埋点；
- Target 切换日志只记录用户/项目、from/to Target ID、路由与时间，不记录凭据和消息
  正文。

---

## 8. 验收标准

### 8.1 P0 功能与一致性

- [ ] Target 工作区顶栏明确显示“当前被测 Agent”并可打开选择器；
- [ ] 用户可搜索并切换至第二个 Target，URL 同步变更；
- [ ] 刷新或打开深链接后，仍以 URL Target 为当前上下文；
- [ ] 顶栏不再硬编码“本机”，不再把多版本 Target 的第一项默认显示为已选版本；
- [ ] 助手会话列表只包含当前 Target 的会话，新会话绑定当前 Target；
- [ ] 切换 Target 后，不展示原 Target 的选中会话、Plan、Decision 或 Invocation；
- [ ] 从 Target B 会话生成的单 Target Plan 只引用 B，确认前预览明确展示 B 的名称、ID
  和版本选择；
- [ ] 切换 Target 不修改、取消或重跑原 Target 的会话、Plan 和 Run；
- [ ] 历史 Run/CaseRun/Report 仍展示它们各自的冻结 Target 与 Capability Snapshot；
- [ ] 路由 Target 与资源归属不一致时不混合展示；
- [ ] 选择器支持键盘全流程与读屏可读名称。

### 8.2 自动化验收

1. 纯函数测试：Target 路由映射、详情页回退、版本展示优先级。
2. 组件测试：加载、空列表、查询失败、已删除 Target、键盘和焦点恢复。
3. API 测试：`workspace_id` 过滤、项目隔离、非法 Target 会话创建拒绝。
4. Playwright 真实后端 E2E：创建 Target A/B 及各自会话，切换后验证 URL、顶栏、会话、
   Plan 预览和历史 Run 不串数据。
5. 竞态测试：A 的查询在切换到 B 后才返回，B 页面仍不渲染 A 的响应。

---

## 9. 实施拆分

### Phase 0：契约和回归测试

- 固化路由 Target、Session Target、Plan Target 和冻结 Target 的优先级；
- 用两个 Target 添加可复现的串数据回归测试；
- 补充会话 `workspace_id` 过滤的 Repository/Service/API 测试。

### Phase 1：可选择顶栏与路由切换

- 实现 Target picker 和无障碍交互；
- 实现相对页面路由映射与详情页安全回退；
- 将 Target 范围查询缓存键全部绑定 `targetId`。

### Phase 2：助手会话与 Plan 一致性

- API 支持 `workspace_id` 过滤并验证会话所属 Target；
- 切换 Target 时重置选中会话和会话派生查询；
- 在 Plan 预览和确认界面显示 Target 身份，服务端守住一致性不变量。

### Phase 3：元数据完整性

- 去除“本机”和第一版本的隐式假设；
- 接入显式环境元数据、最近健康检查和 Capability Snapshot 摘要；
- 完成历史详情页的冻结信息展示与规范路由校验。

---

## 10. 风险与回滚

| 风险 | 影响 | 缓解 |
|---|---|---|
| 快速切换导致旧请求后返 | 页面短暂串数据 | Target 化 query key、AbortSignal、响应归属校验 |
| 详情页路由直接替换 ID | 打开不属于新 Target 的资源 | 详情页切换后回到对应列表 |
| 会话列表改为筛选后看似“丢失” | 用户误以为历史被删除 | 明确显示当前 Target，切回原 Target 即可查看 |
| 环境元数据缺失 | 旧 Target 标签不完整 | 允许“未标注”，不伪造本机状态 |
| 前端检查被绕过 | 仍可能在错误会话下写入 | 关键不变量同时由服务端校验 |

回滚时可通过 feature flag 把 Target picker 暂时退回只读展示，但已上线的 Session 筛选、
Target 化 query key 和服务端一致性校验应保留；这些属于数据安全修复，不应随视觉回滚撤销。

---

## 11. 评审结论模板

评审时需确认：

- [ ] 接受 URL `:targetId` 作为工作区 Target 权威来源；
- [ ] 接受 P0 继续使用 `AssistantSession.workspace_id` 表达会话 Target 绑定；
- [ ] 接受切换 Target 时不保留跨 Target 的选中会话与未保存表单；
- [ ] 接受多版本未显式选择时显示“多版本/未指定”，不默认第一项；
- [ ] 接受环境元数据缺失时显示未知或省略，不猜测。
