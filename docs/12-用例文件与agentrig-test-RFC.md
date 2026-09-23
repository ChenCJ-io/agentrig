# 用例进仓库：用例文件与 `agentrig test` RFC

> RFC ID：AR-RFC-0006
>
> 状态：Accepted（B1—B3 待实施）
>
> 版本：0.2
>
> 日期：2026-09-23（提出并接受）
>
> 范围：用例写成代码仓库里的文件；本地与 CI 用一条命令运行；Web 草稿导出为文件
>
> 前置文档：[Python Agent 接入指南](./05-Python-Agent接入指南.md)、[总体架构](./00-总体架构.md)

**一句话目标：用例和 Agent 代码放在同一个仓库、在同一个 PR 里评审；`agentrig test` 一条命令在本地和
CI 跑完，出现回归就返回非零退出码。**

评审时回答的四个问题（目录与文件格式、命令行为与退出码、CI 里的 Curator 策略、分期顺序）已于 2026-09-23
按 §9 的推荐确认。

---

## 1. 为什么做

- **版本对不上。** 现在用例只存在 AgentRig 数据库里：Agent 代码在 Git，用例在数据库，改提示词和改
  用例没法在同一个 PR 里评审；
- **CI 里跑不起来。** CI 只有代码仓库，没有 AgentRig 数据库。要跑回归，得先起服务、调接口发起运行，
  再拿运行 ID 跑门禁；
- **真实 Agent 验证给出的约束**（2026-09-23，一个 38 个工具的生产级 Agno Agent）：
  - 一条两轮用例回放约 90 秒，每轮消耗 2.5–5 万输入 token，必须能挑着跑、能并发；
  - 入口常常要复刻服务逻辑，入口代码要能和用例放在一起；
  - Curator 需要业务世界描述才能给出可信结果，项目级要有默认描述；
  - "对话生成草稿、审核时补规则"是最顺手的写法，草稿要能导出成文件。

## 2. 业界怎么做

| 工具 | 用例放在哪 | 怎么跑 |
|---|---|---|
| promptfoo | 仓库里的 `promptfooconfig.yaml` | `promptfoo eval`，CI 用 GitHub Action |
| DeepEval | 仓库里的 pytest 测试文件 | `deepeval test run` |
| LangSmith / Langfuse | 平台上的数据集 | 用 SDK 拉取数据集运行评测 |

共同点：CI 以仓库内容为准，平台负责展示和追溯结果。

## 3. 我们已经有什么

- 用例、Target、执行配置都有 Pydantic 契约（例如 `TestCaseCreate`），HTTP、MCP 和 Web 共用同一套校验；
- `ServiceContainer` 可以在进程内构建，`agentrig report`、`agentrig gate` 已经这样用；执行、Rule 评判、
  质量报告和门禁都不需要起 HTTP 服务；
- `python_agent` Driver 让现有 Python Agent 不改代码即可接入；
- 「对话验证」可以一键生成用例草稿；
- 门禁命令已有退出码约定：0 通过、1 命令错误、2 门禁失败、3 无法判定。

## 4. 目标与非目标

**目标**

- 用例写成仓库里的 YAML 文件，字段与现有用例完全一致；
- `agentrig test` 在进程内执行，使用临时数据库，不需要起服务；输出控制台摘要、JUnit 和 Markdown，
  退出码可以直接用于 CI；
- 按目录、标签、名称挑选用例，并发执行；
- 默认 Fixture → Sample → Curator，另提供不需要模型 Key 的严格模式；
- Web 草稿可以导出为 YAML 文件。

**非目标（本期不做）**

- 替代数据库与 Web：它们继续负责运行证据和工作台；
- CI 里的 A/B 对比：v1 只判断"选中的用例全部通过"，A/B 留在 Web；
- 真实工具结果录制（`agentrig record`）与 GitHub Action，另行设计；
- 文件与服务端之间的双向同步。

## 5. 总体设计

### 5.1 目录约定

```text
my-agent-repo/
├── agentrig/
│   ├── project.yaml        被测 Agent、执行配置、默认世界描述
│   ├── entry.py            可选：入口包装，按文件路径引用
│   └── cases/
│       ├── refund/
│       │   └── confirm_first.yaml
│       └── projects/
│           └── open_latest.yaml
└── my_app/
```

- 默认读取 `./agentrig/project.yaml`，可以用 `--config` 指定其他位置；
- `agentrig/` 目录里不放 `__init__.py`；入口按文件路径引用，避免和 `agentrig` 包重名。

### 5.2 文件格式

`project.yaml` 描述被测 Agent 和执行方式：

```yaml
version: 1
target:
  name: support-bot
  entry: agentrig/entry.py:agent       # 也可以写模块路径 my_app.agent:agent
  python: .venv/bin/python             # 相对仓库根目录
  cwd: .
  secret: env:OPENAI_API_KEY           # 被测 Agent 自己的模型 Key
  credential_env: OPENAI_API_KEY
initial_state:                         # 默认世界描述，同时交给 Agent 与 Curator
  facts:
    - 订单 ID 形如 A123；金额单位为元
profile:
  providers: [fixture, sample, simulation_curator]
  curator:
    base_url: https://model.example/v1
    model: model-name
    secret: env:CURATOR_API_KEY
  concurrency: 4
  repeat: 1
  case_timeout_seconds: 600
```

每条用例一个文件：

```yaml
name: 退款前必须确认
tags: [refund, p0]
turns:
  - user_message: 订单 A123 帮我退款
    fixtures:
      - tool_name: lookup_order
        match_arguments: {order_id: A123}
        result: {order_id: A123, amount: 199}
    assertions:
      - {kind: tool_called, tool_name: lookup_order}
      - {kind: tool_not_called, tool_name: issue_refund}
      - {kind: text_contains, value: 请确认}
```

- 字段与现有 `TestCaseCreate` 完全一致，用同一个模型校验；轮次的先后顺序就是 `position`，不必手写；
- 用例的 `initial_state` 与项目默认值递归合并；
- 用例 ID 默认由路径生成（`refund.confirm_first`），也可以写 `id:` 固定；
- 从 Web 导出的文件与手写的文件是同一种格式。

### 5.3 `agentrig test`

```bash
agentrig test                          # 跑 agentrig/cases 下的全部用例
agentrig test agentrig/cases/refund    # 只跑一个目录
agentrig test --tag p0 -k 退款          # 按标签、名称挑选
agentrig test --no-curator             # 严格模式：只用 Fixture/Sample，不需要模型 Key
agentrig test --junit report.xml --markdown report.md --keep-db .agentrig/test.db
```

执行过程：

1. 读取 `project.yaml` 与用例文件，全部校验通过才开始。任何一个文件不合法都直接报错，不会跑一半；
2. 在临时目录建 SQLite，进程内构建 `ServiceContainer`。入口解释器只对本次运行放行：本地命令本来就会
   执行仓库里的代码，放行名单用来保护多用户的服务端部署；
3. 写入 Target、执行配置与用例，提交一次运行并等待完成；
4. 输出结果：

```text
support-bot · 3 条用例 × 1 次 · 并发 4
  ✓ projects.open_latest        2 轮   96s
  ✗ refund.confirm_first        第 1 轮 tool_not_called(issue_refund)
        ← issue_refund(order_id=A123)，结果来自 fixture
  ✓ refund.lookup_only          1 轮   31s
2 通过 · 1 失败 · 输入 41.2 万 token / 输出 3.1 千 token
```

退出码与 `agentrig gate` 保持一致：

| 退出码 | 含义 |
|---|---|
| 0 | 选中的用例全部通过 |
| 1 | 命令或配置错误：文件不合法、缺少 Key、入口导入失败等 |
| 2 | 出现回归：至少一条用例判定失败 |
| 3 | 无法判定：有用例因执行错误（工具结果无法提供、超时等）没有结论，或者没有选中任何用例 |

`repeat: N` 时，一条用例的每次尝试都通过才算通过；v1 不做通过率阈值。

`--keep-db` 会保留本次的 SQLite 文件，用它启动 `agentrig serve` 就能在 Web 里查看完整证据。

### 5.4 Curator 策略

- 默认 `fixture → sample → simulation_curator`，与 2026-09-23 的决定一致；
- 配置了 Curator 但环境里没有对应的 Key：启动前直接报错（退出码 1），提示设置 Key 或加 `--no-curator`。
  不自动降级，避免本地和 CI 跑的不是同一种测试；
- `--no-curator` 是严格模式：Fixture/Sample 未命中的调用会让该用例无法判定（退出码 3），结果完全确定，
  不需要 Key；
- `project.yaml` 的 `initial_state` 作为默认世界描述，交给 Curator，用例可以覆盖。

### 5.5 Web 与文件之间

- 用例详情页增加「导出为文件」，下载 YAML；对应接口 `GET /api/test-cases/{case_id}/export?format=yaml`；
- 命令行：`agentrig cases export <case_id> --db <path>` 或 `--server <url>`；
- 推荐写法：「对话验证」→ 生成草稿 → 审核补规则 → 导出 → 提交到仓库；
- 把文件导入服务端放到后续版本；v1 用 `--keep-db` 查看本次运行的证据。

### 5.6 入口的两种写法

- 模块路径：`my_app.agent:agent`，相对 `cwd` 导入；
- 文件路径：`agentrig/entry.py:agent`，harness 按路径加载，不要求所在目录是 Python 包。

## 6. 数据与兼容

- 不改数据库结构，不需要迁移；
- 新增显式依赖 PyYAML（它已随 `uvicorn[standard]` 间接安装）；
- 现有 Web、HTTP、MCP 流程不变。

## 7. 成本与耗时

真实 Agent 每条用例需要 1–2 分钟，每轮消耗数万 token，所以：

- 默认并发 4；
- 推荐按标签分层，例如 `p0` 在每个 PR 跑，全量每天跑一次；
- 控制台汇总 token 用量；执行配置里有价格快照时，同时显示费用。

## 8. 分期与验收

| 阶段 | 内容 | 预计 | 验收 |
|---|---|---|---|
| B1 | 文件格式与校验；`agentrig test`（进程内、临时库、挑选、并发、控制台/JUnit/Markdown、退出码）；Curator 策略；文件路径入口 | 1 周 | 示例仓库里改坏提示词后，`agentrig test` 退出码为 2，报告指出违规调用 |
| B2 | Web 与命令行导出 YAML；`agentrig init` 生成目录骨架 | 3 天 | 对话生成的草稿导出后，原样可跑 |
| B3 | 文档与示例（LangGraph、Agno 各一个）；真实 Agent 回归 | 2 天 | 按文档从零接入，10 分钟内在本地跑出第一次红灯 |

## 9. 决策（2026-09-23 已确认）

| 决策 | 结论 |
|---|---|
| 目录与文件名 | `agentrig/project.yaml` + `agentrig/cases/**/*.yaml` |
| 文件格式 | YAML，显式依赖 PyYAML |
| 退出码 | 与 `agentrig gate` 一致：0 / 1 / 2 / 3 |
| 缺少 Curator Key | 直接报错，不自动降级为严格模式 |

## 10. 风险

- **模型非确定性导致偶发失败**：规则只约束关键行为；需要时用 `repeat` 观察分布；
- **Curator 带来的非确定性**：导出的草稿用 Fixture 固定结果；CI 可以用严格模式；
- **成本**：分层、并发与 token 汇总；
- **同一用例在文件和数据库里各有一份**：v1 每次使用临时库，不存在冲突；做导入时再处理。

## 11. 被否决的方案

- **用例写成 pytest 测试函数**：表达力强，但与 Web、MCP 和导出格式割裂，非 Python 团队也难维护；
- **CI 连接一个共享的 AgentRig 服务**：需要部署与凭据，违背"CI 只有仓库"的前提，保留为以后的可选模式；
- **用例存成 JSON**：机器友好，但手写与评审都不方便。

## 12. Definition of Done

- [ ] B1–B3 的验收全部通过；
- [ ] 接入指南与 README 以"用例进仓库"为主路径改写对应段落；
- [ ] CI 覆盖文件校验、用例挑选、退出码、JUnit/Markdown 输出与严格模式。

## 13. 实施状态

| 阶段 | 状态 |
|---|---|
| B1 文件格式与 `agentrig test` | Pending |
| B2 导出与 `agentrig init` | Pending |
| B3 文档、示例与真实 Agent 回归 | Pending |
