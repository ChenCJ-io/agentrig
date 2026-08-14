# AgentScope → AgentRig 前端迁移总方案

> 状态：P0/P1 implemented and live verified  
> 更新日期：2026-08-11  
> 范围：AgentRig `web/` 与 AgentScope `frontend/`  
> 相关总方案：[`../11-AgentRig-真实评测生态闭环与参赛录制优化方案.md`](../11-AgentRig-真实评测生态闭环与参赛录制优化方案.md)

## 1. 一句话结论

AgentRig 不再继续平行维护一套“类 AgentScope”页面；以 AgentScope 已验收的前端为视觉与交互上游，
将通用展示组件抽取到 AgentRig，用 AgentRig 自己的 ViewModel、Adapter、API 和权限上下文驱动。

迁移的对象是**界面能力**，不是 AgentScope 整个应用。

## 2. 为什么现在可以迁移

两个前端已经具备足够的同源基础：

- React、React Router、TanStack Query、Lucide、TypeScript 和 Vite 主版本一致；
- `Button`、`Badge`、`Panel`、`StatCard` 等基础组件已存在直接复用；
- Shell、Tokens、CSS Modules 和路由骨架同构；
- AgentScope 已有 Evaluation、Conversation、Assets 成熟页面及视觉回归基线；
- AgentRig 后端已有 Target、Case、Run、CaseRun、Report、Sample、Profile 和 Assistant 数据。

差距主要位于展示层拆分、视觉精修和验收工程，不需要重新选技术栈。

## 3. 迁移后的用户主路径

```text
选择被测 Agent
  → 查看连接和评测概览
  → 选择 Case / Profile / 工具结果策略
  → Preview 计划与资源影响
  → 确认并运行
  → Run Summary → Cell Matrix → Attempt Timeline
  → 失败归因 / Recovery / 验收结论
```

智能评测助手是该主路径的自然语言入口，不再是另一套脱离评测资产的 AgentTeams 演示界面。

## 4. 迁移原则

1. **AgentRig 契约是事实源**：页面不逆向要求后端伪造 AgentScope 字段。
2. **保留 AgentRig URL 与 Target 范围**：不照搬 AgentScope 的非 Target Scoped 路由。
3. **先抽展示，后接数据**：组件 Props 只依赖通用 ViewModel。
4. **真实错误优先**：后端失败时不使用 Fixture 伪装成成功页。
5. **按录制主路径迁移**：先完成 Overview、Preview、Run、Cell、Assistant。
6. **小切片可回退**：每个路由可通过 Feature Flag 回到旧页面。
7. **不带入私有资产**：Pixcake/Evoto、钉钉、内部 URL、用户数据和 Fixture 不进入开源历史。
8. **复用也要可持续**：不把 AgentScope 的 7000 行页面复制成 AgentRig 的新巨型页面。

## 5. 目标分层

```text
AgentRig Pages
  └─ Feature Controllers     路由、Query、Mutation、SSE、状态机
      └─ AgentRig Adapters   API DTO → ViewModel
          └─ ViewModels      通用展示契约
              └─ UI Features    从 AgentScope 抽取的组件
                  └─ UI Core        Token、Button、Panel、Table、Markdown、Shell 几何
```

AgentScope 专有字段只能通过 `dimensions`、`extensions` 或 AgentScope 自己的外层组件展示，
不允许进入 AgentRig 通用 Props。

## 6. 文档导航

| 文档 | 回答的问题 |
|---|---|
| [`01-迁移资产清单与边界.md`](01-迁移资产清单与边界.md) | 哪些直接复用、哪些需抽象、哪些禁止迁移 |
| [`02-目标架构与数据适配.md`](02-目标架构与数据适配.md) | 目录、ViewModel、Adapter、路由和状态如何设计 |
| [`03-页面迁移批次与任务清单.md`](03-页面迁移批次与任务清单.md) | 先迁哪些页面，每一批如何验收 |
| [`04-视觉验收与同步治理.md`](04-视觉验收与同步治理.md) | 如何做截图、响应式、Axe、回退和后续同步 |

## 7. 总体批次

| 批次 | 目标 | 交付物 | 粗估 |
|---|---|---|---:|
| F0 | 来源、授权与视觉基线 | 来源清单、私有扫描、路由截图 | 1–2 人日 |
| F1 | UI Core 和 Shell 几何 | Tokens 兼容层、Markdown、Table/State、Shell | 2–3 人日 |
| F2 | 参赛评测主链 | Overview、Preview、Run、Cell、Report | 4–6 人日 |
| F3 | 智能评测助手 | Session Rail、Message、Plan/Run Card、Composer | 2–3 人日 |
| F4 | Case 与工具结果资产 | Case Catalog/Editor、Sample/Profile Workbench | 3–5 人日 |
| F5 | 回归门禁与旧页下线 | Route Manifest、双桌面基线、Axe、删旧页 | 2–3 人日 |

参赛 P0 只要求 F0–F3 和 F5 中的核心路由，前端总投入预计 11–17 人日。其中 F3 的 2–3 人日
与总方案 M4 的 Web Assistant 工作重叠，做整体排期时不重复计算。F4 与完整治理界面可在赛后继续。

## 8. P0 交付判定

P0 完成必须同时满足：

- 五个核心页面使用真实 AgentRig API，无私有 Fixture 回退；
- lassist 真实场景能从 Preview 走到 Run、Cell、Attempt 和验收结论；
- 页面能区分 Loading、Empty、Error、Partial、Running 和 Terminal；
- 1280×1000 与 1600×1000 通过视觉基线，1024 不溢出；
- 主链路 Axe 无 critical/serious 违规；
- 新旧页可通过 Flag 切换，回退不需要数据迁移；
- 开源扫描不包含 AgentScope 私有品牌、内部域名、用户数据和鉴权实现。

## 9. 不在本次迁移中解决

- 不为了对齐界面而引入 Pixcake/Evoto 业务概念；
- 不强制 Codex 与 Web 助手生成相同评测方案；
- 不通过前端 Mock 弥补 Manifest、Cell/Attempt、Timeline 等后端契约缺口；
- 不同步 AgentScope 全部平台管理、Prompt/Preference 和 Evoto 页面；
- 不在首批引入独立组件库发布流程，先在 AgentRig `web/` 内完成边界验证。

## 10. 实施与验收结果

Overview、Evaluation、Cell Timeline、Report、Assets 与 Assistant 已接入 AgentRig 真实 API，并通过
fixture 浏览器契约、响应式/Axe 门禁和真实 lassist Browser 验收。权威 Run、Cell、Attempt、证据质量
与诚实边界见[真实闭环验收记录](../competition/12-lassist真实闭环验收.md)。
