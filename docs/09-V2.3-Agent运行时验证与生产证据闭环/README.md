# AgentRig V2.3—V2.5 方案文档包

> 文档包 ID：AR-RFC-0002
>
> 状态：Implemented（本地确定性验收完成；外部 Live 验收待执行）
>
> 版本：1.0
>
> 日期：2026-08-11
>
> 当前实现权威边界：`../00-总体架构.md`、`../06-V2.1-基于证据的自适应评测闭环-开发设计.md`
>
> 前置方案：`../07-V2.2-可复现交付与质量门禁-RFC.md`

本目录把 AgentRig 下一阶段工作分成一份总方案和九份专题设计，并提供统一实施、验收矩阵与运行
手册。01—09 的代码、迁移、API/CLI、Web 入口和确定性测试均已实现；本地验收、真实 Reference
Backend 浏览器链路和 PostgreSQL 17.7 双 Worker/retention 集成已完成。AgentScope v2.0.6 与
AgentTeams v1.1.2/v1.2.2 Live acceptance 已提供可执行入口，但在对应环境实际执行前不标记为
`Verified`。

## 当前验收快照（2026-08-11）

- 本地统一入口：`scripts/accept_v23.sh local`；外部环境入口：`scripts/accept_v23.sh live`；
- 本次实测：Python 3.12/3.13 均为 `189 passed, 9 skipped`，Web `35 passed`，Browser contract `2 passed`，
  真实后端 Browser `1 passed`，Ruff/mypy/typecheck/build 全部通过；
- 数据库迁移：`20260810_0005` 已完成 SQLite 全量升级、0005 降级与再次升级；
- 浏览器：Mock/accessibility 契约测试与无核心 API Mock 的真实 FastAPI/SQLite/Reference Target 链路；
- 首次无 live 变量的全量套件产生 9 个 AgentScope/legacy Pixcake/Goose/PostgreSQL skip，不计为通过；
- PostgreSQL 17.7 实测：4 个 Repository/双 Worker/并发终态/OTLP-retention 集成用例和 migration 往返通过；
- 发布包：sdist/wheel 构建成功，隔离 Python 3.12 安装后 migration、内置 Web、安全 manifest 烟测通过；
- 外部待执行：AgentScope v2.0.6、AgentTeams 双基线观测文件和目标部署容量/SLO benchmark；
- 详细命令、环境变量、产物和退出码见 [验收运行手册](./11-验收运行手册.md)。

## 阅读顺序

1. 先阅读 [总体方案与路线图](./00-总体方案与路线图.md)，确认产品定位、范围、依赖和里程碑。
2. 按当前迭代阅读对应专题文档；专题中的契约和验收口径比总方案中的摘要更具体。
3. 开始排期前使用 [实施拆分与验收矩阵](./10-实施拆分与验收矩阵.md) 建立 issue、负责人和交付门槛。
4. 发布或环境验收时按 [验收运行手册](./11-验收运行手册.md) 生成本地与 Live 证据。

## 文档清单

| 编号 | 方案 | 状态 | 目标里程碑 | 主要依赖 |
|---|---|---|---|---|
| 00 | [总体方案与路线图](./00-总体方案与路线图.md) | Implemented / Local Verified | V2.3—V2.5 | V2.1、V2.2 |
| 01 | [V2.2 收口：质量报告与发布门禁](./01-V2.2收口-质量报告与发布门禁.md) | Implemented / Local Verified | V2.3 | 已有 Run/CaseRun/Evaluation |
| 02 | [AgentTeams v1.2.2 双基线兼容](./02-AgentTeams-v1.2.2-双基线兼容.md) | Implemented / Live Pending | V2.3 | 现有 v1.1.2 竞争基线 |
| 03 | [AgentScope 2.0 与 AG-UI Driver](./03-AgentScope-2.0与AG-UI-Driver.md) | Implemented / Live Pending | V2.3 | Driver/Event v1 |
| 04 | [Target Capability Snapshot](./04-Target-Capability-Snapshot.md) | Implemented / Local Verified | V2.3 | Driver probe、CaseRun snapshot |
| 05 | [AgentScope 专项安全回归套件](./05-AgentScope-专项安全回归套件.md) | Implemented / Live Pending | V2.3 | 03、04 |
| 06 | [OTLP 生产证据接入与 Trace 转 Case](./06-OTLP生产证据接入与Trace转Case.md) | Implemented / Integration Verified | V2.4 | Project、脱敏与保留策略 |
| 07 | [人工标注与 Judge 对齐](./07-人工标注与Judge对齐.md) | Implemented / Local Verified | V2.4 | 06、现有 Evaluation |
| 08 | [Failure Signal 与复发监控](./08-Failure-Signal与复发监控.md) | Implemented / Local Verified | V2.5 | 06、07、Release Gate |
| 09 | [Project 边界与耐久执行基础](./09-Project边界与耐久执行基础.md) | Implemented / Integration Verified | V2.4—V2.5 | PostgreSQL、迁移策略 |
| 10 | [实施拆分与验收矩阵](./10-实施拆分与验收矩阵.md) | Implemented | 全程 | 00—09 |
| 11 | [验收运行手册](./11-验收运行手册.md) | Implemented | 全程 | 00—10 |

## 文档权威关系

- 当前产品事实以代码、迁移、Schema、自动化测试及本目录的实施状态段为准；早期方案中的“建议”
  不覆盖已经落地的契约。
- V2.2 的 ReleaseEvidence、QualityReport、ComparisonReport 和 ReleaseGate 决策继续有效；01 号
  文档记录其完整收口实现。
- v1.1.2 的比赛证据是历史事实，升级 AgentTeams 时不得覆盖、伪造或重新解释。
- 生产 Trace 与测试 Run 是两个事实域。任何专题文档都不得把采样 Trace 变成执行真相。
- 如专题文档之间冲突，优先遵守：安全不变量 → 不可变证据 → 专题的明确契约 → 总方案摘要。

## 统一状态标记

每份专题文档应按以下状态推进：

```text
Proposed → Accepted → In Progress → Implemented → Verified
                    ↘ Rejected / Superseded
```

进入 `Accepted` 前必须确认负责人、依赖、迁移方式和 Definition of Done；进入 `Verified` 前必须存在
可重复的自动化或 live acceptance 证据。
