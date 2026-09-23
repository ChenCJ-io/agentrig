# Python Agent 接入指南（Agno / LangGraph / 普通函数）

> 状态：Current（Alpha）
>
> 更新：2026-09-23

`python_agent` 让现有的 Python Agent 直接接受 AgentRig 测试：不改 Agent 代码，也不需要在被测项目里
安装 AgentRig。

**原理：** AgentRig 用你项目自己的 Python 把 Agent 跑起来。Agent 调模型照常真实调用；调工具时在
框架内部被截住，结果改由 AgentRig 提供。

## 1. 三步接入

### 1.1 放行项目的 Python

解释器路径必须**精确**出现在部署的 `subprocess_allowlist` 中：

```bash
export AGENTRIG_EXECUTION__SUBPROCESS_ALLOWLIST='["/path/to/agent/.venv/bin/python"]'
uv run agentrig serve
```

### 1.2 新建被测 Agent

类型选 `python_agent`，驱动参数（options）填 3 个字段：

```json
{
  "entry": "my_app.agent:agent",
  "python": "/path/to/agent/.venv/bin/python",
  "cwd": "/path/to/agent"
}
```

| 字段 | 含义 |
|---|---|
| `entry` | Agent 对象在哪：`模块路径:变量名`（相对 `cwd` 导入），或 `文件路径.py:变量名`（所在目录不必是 Python 包） |
| `python` | 被测项目虚拟环境里的 Python |
| `cwd` | 项目根目录，用来导入代码、读取项目自己的 `.env` |

可选字段：

| 字段 | 含义 |
|---|---|
| `factory` | 入口是无参工厂函数时设为 `true`，先调用它构建 Agent |
| `adapter` | 默认 `auto`；识别失败时显式指定 `agno` / `langgraph` / `callable` |
| `credential_env` | 把 Target `secret_ref` 解析出的值注入这个环境变量 |
| `inherit_env` | 从 AgentRig 进程原样转发的环境变量名 |
| `env` | 不含凭据的环境变量覆盖 |
| `startup_timeout_seconds` | 导入代码并完成握手的最长时间，默认 60 |
| `conversation_initial_state` | 「对话验证」的初始状态，同时交给 Agent 和 Curator；用来描述业务世界（见 §4） |

入口必须是模块级的 Agent 对象或无参工厂函数。Agent 在类里创建、或工厂函数需要参数时，写一个两行的
入口模块即可：

```python
# agentrig_entry.py
from my_app.factory import build_agent
agent = build_agent(config="test")
```

入口要让被测 Agent 和生产环境**看到同样的东西**。如果生产服务在启动时做了初始化（加载配置、编译
Prompt、注册工具），或在路由层包装了用户消息（例如拼接上下文块），入口里要做同样的事，否则测到的是
另一个 Agent。生产环境用的持久化会话库，可以在入口里换成进程内存库，避免把测试会话写进开发数据库。

**工具循环跨多次运行时。** 有些 Agent 把客户端工具声明为 `stop_after_tool_call=True`：调用后本次 run
立即结束，客户端执行完再发起新的一轮，把结果带回来。harness 会照常接管这些工具，但"带着结果再发起
一轮"属于你的服务逻辑，需要在入口里包一层：

```python
original_arun = agent.arun

async def arun(message, **kwargs):
    output = await original_arun(wrap_user_message(message), **kwargs)
    # 只要本轮派发了会停止运行的工具，就像客户端一样把结果带回去继续，即使模型同时写了文字。
    while dispatched := [t for t in output.tools or [] if t.stop_after_tool_call]:
        output = await original_arun(wrap_tool_results(dispatched), **kwargs)
    return output

agent.arun = arun
```

`wrap_user_message` 与 `wrap_tool_results` 换成你服务里构造消息的同一段代码。

做 A/B 对比时，在两个版本的配置里分别覆盖 `cwd`，指向两份代码检出目录；版本级 options 与公共
options 递归合并。

### 1.3 确认连通

概览页会自动做连通检查：真实启动 Agent、导入代码并完成一次握手。显示检查通过，接入就完成了。

- 查看识别到的工具清单：`POST /api/targets/{target_id}:probe-capabilities`；
- 每次运行的详情页会显示识别到的框架和版本，例如 `agno 2.7.4`。

### 1.4 创建执行配置（推荐 Curator 兜底）

用例没有写 Fixture 的工具调用，由 Curator 依据工具说明、参数和轮次的 `simulation_instruction` 生成结果。
这需要一个 OpenAI 兼容的模型 Key：

```json
{
  "tool_mode": "controlled",
  "provider_chain": [
    {"name": "fixture"},
    {"name": "sample"},
    {"name": "simulation_curator"}
  ],
  "curator_model": {
    "base_url": "https://model.example/v1",
    "model": "model-name",
    "secret_ref": "env:MODEL_API_KEY"
  },
  "primary_evaluator": "rule"
}
```

只想用 Fixture/Sample 时去掉 `simulation_curator`。此时未命中的工具调用会让 CaseRun 明确失败，
不会用真实工具补位。

## 2. 一次测试在背后怎么走

以用户说"订单 A123 帮我退款"为例：

| 步骤 | 方向 | 发生了什么 |
|---|---|---|
| ① | AgentRig → 被测项目 | 用项目的 Python 启动 `python -m agentrig.sdk.harness`，加载 Agent，装好拦截点 |
| ② | AgentRig → Agent | 发送用户消息"订单 A123 帮我退款" |
| ③ | Agent → 模型 | 真实调用模型，模型决定调用 `lookup_order("A123")` |
| ④ | 拦截点 → AgentRig | 截住这次调用，真函数不执行 |
| ⑤ | AgentRig | 按 Fixture → Sample → Simulation Curator 的顺序找结果 |
| ⑥ | AgentRig → Agent | 结果当作函数返回值交回，Agent 继续推理 |
| ⑦ | Agent → AgentRig | 最终回复"请确认是否退款"，AgentRig 按规则判定 pass / fail |

每个 CaseRun 一个独立进程：多轮对话在同一进程里延续，跑完即关闭，用例之间互不影响。

harness 还会上报工具名称、描述和参数 Schema，写入 Capability Snapshot；两个版本之间工具定义的变化会
出现在 A/B diff 中。

## 3. 拦截点装在哪

| 被测 Agent | 拦截位置 | 要改代码吗 |
|---|---|---|
| Agno `Agent` / `Team` | `tool_hooks` 链最内层；Team 递归覆盖到成员，委派等框架内置工具照常执行 | 不用 |
| LangGraph 编译图（`create_agent`、`create_react_agent`、手写 `StateGraph`） | 每个 `ToolNode` 的 `wrap_tool_call` 链最内层，用户自己的 middleware 照常运行 | 不用 |
| `callable(messages) -> str` | 用 `@agentrig.sdk.tool` 标记的工具 | 给工具加一行装饰器 |

拦截点只存在于 AgentRig 启动的测试进程里，生产环境照常运行，不受影响。

多轮对话这样保持：

- **Agno**：`session_id` 取 CaseRun ID；Agent 没有 db 时挂一个进程内存 `InMemoryDb`；
- **LangGraph**：有 checkpointer 时 `thread_id` 取 CaseRun ID，否则 harness 累积消息；
- **普通函数**：harness 累积 `[{"role", "content"}]`，每轮整段传入。

## 4. 接入之后：用对话生成用例

推荐从「对话验证」开始积累用例：

1. 在工作区「对话验证」选择上面的执行配置，和 Agent 对话；
2. 点「生成用例草稿」：每条用户消息成为一轮，每次工具调用生成一条 `tool_called` 断言，每轮另附
   `no_execution_error`；受控模式下本次拿到的工具结果会成为 Fixture，以后回放结果完全确定；
3. 审核时补上业务规则，例如第一轮不许直接退款：
   `{"kind": "tool_not_called", "tool_name": "issue_refund"}`。草稿默认只绑定对话时的版本，做 A/B 时把
   另一个版本加进 `supported_versions`；
4. 在「版本对比」选 baseline 与 candidate 运行。

草稿记录的是"这次发生了什么"，回归价值来自审核时补上的"什么不能发生"。也可以在「测试用例」中手写
JSON，或让编码 Agent 按 [build-test-case Skill](../skills/core/build-test-case/SKILL.md) 通过 MCP 创建草稿。

用真实 Agent 积累用例时的几条经验：

- **先给 Curator 描述业务世界。** 没有上下文时，Curator 会编出与业务无关的数据，例如给修图应用编一个
  "季度财报"项目，ID 格式也对不上。在 Target 的 `conversation_initial_state` 里写清关键事实，例如数据
  是什么、ID 是整数、最近有哪些对象，模拟结果就会贴近真实；
- **审核时放宽 Fixture 的参数匹配。** Fixture 按子集匹配：`match_arguments` 是实际参数的子集即命中。
  草稿会记下完整参数，例如一整串图片 ID；审核时只保留关键参数，回放更稳；
- **规则约束关键行为，不约束完整路径。** 同一个 Agent 重跑时，中间步骤可能不同，例如偶尔多一次计划类
  工具调用。`tool_not_called`、`tool_call_order` 和用 `tool_arguments_schema` 约束关键参数，比逐一断言
  每次调用更稳；`tool_arguments_equal` 要求参数完全相等，只适合参数很少的工具；
- **预估成本。** 回放时模型仍是真实调用。系统提示词和工具定义很大的 Agent，每轮可能消耗数万输入 token。

## 5. 把用例放进仓库：`agentrig test`

用例也可以写成代码仓库里的 YAML 文件，和 Agent 代码在同一个 PR 里评审；`agentrig test` 一条命令就能
在本地和 CI 跑完。设计见 [AR-RFC-0006](./12-用例文件与agentrig-test-RFC.md)。

### 5.1 目录

```text
my-agent-repo/
├── agentrig/
│   ├── project.yaml        被测 Agent 与执行配置
│   ├── entry.py            可选：入口包装，按文件路径引用
│   └── cases/
│       └── refund/
│           └── confirm_first.yaml
└── my_app/
```

### 5.2 `project.yaml`

```yaml
version: 1
target:
  name: support-bot
  entry: agentrig/entry.py:agent       # 也可以写模块路径 my_app.agent:agent
  python: .venv/bin/python             # 不填时使用运行 agentrig 的解释器
  secret: env:OPENAI_API_KEY           # 可选：被测 Agent 自己的模型 Key
  credential_env: OPENAI_API_KEY
initial_state:                         # 默认世界描述，同时交给 Agent 与 Curator
  facts:
    - 订单 ID 形如 A123；金额单位为元
profile:
  curator:
    base_url: https://model.example/v1
    model: model-name
    secret: env:CURATOR_API_KEY
```

- 相对路径以 `root` 为基准。`root` 默认是 `..`，即 `agentrig/` 的上一级，通常就是仓库根目录；
- `profile` 的其他字段：`providers` 默认 `[fixture, sample, simulation_curator]`，`concurrency`
  默认 4，`repeat` 默认 1，`case_timeout_seconds` 默认 600；用 `evidence_judge` 的用例还需要配置
  `judge`，写法与 `curator` 相同；
- `target` 还支持 §1.2 里的 `adapter`、`factory`、`env`、`inherit_env`、`startup_timeout_seconds`，
  以及 `version`（默认 `local`，会传给被测代码）。

### 5.3 用例文件

每条用例一个文件，字段和 Web 里的用例完全一样：

```yaml
name: 退款前必须确认
tags: [refund, p0]
turns:
  - user_message: 订单 A123 帮我退款
    fixtures:
      - {tool_name: lookup_order, match_arguments: {order_id: A123}, result: {order_id: A123, amount: 199}}
    assertions:
      - {kind: tool_called, tool_name: lookup_order}
      - {kind: tool_not_called, tool_name: issue_refund}
      - {kind: text_contains, value: 请确认}
```

- 轮次的先后顺序就是 `position`，不必手写；
- 用例 ID 默认由路径生成，例如 `refund.confirm_first`，也可以写 `id:` 固定；
- 用例的 `initial_state` 与项目默认值递归合并。

### 5.4 运行

```bash
agentrig test                          # 跑 agentrig/cases 下的全部用例
agentrig test agentrig/cases/refund    # 只跑一个目录
agentrig test --tag p0 -k 退款          # 按标签、名称挑选
agentrig test --no-curator             # 严格模式：只用 Fixture/Sample，不需要模型 Key
agentrig test --junit report.xml --markdown report.md
agentrig test --keep-db .agentrig/test.db   # 保留数据库，用 agentrig serve 查看完整证据
```

```text
AgentRig · refund-bot@candidate · 2 条用例 × 1 次 · 并发 4
  ✗ refund.confirm_first  退款前必须确认 · 1 轮 · 0.1s
      ✗ tool_not_called: issue_refund in turn 1
        ← 第 1 轮调用 issue_refund {"order_id": "A123", "amount": 199}，结果来自 fixture
  ? refund.confirm_then_refund  用户确认后才退款 · 2 轮 · 0.1s
      ? provider_exhausted: …；第 1 轮调用 issue_refund 没有可用的结果
结果：0 通过 · 1 失败 · 1 无法判定 · …
结论：出现回归（退出码 2）
```

| 退出码 | 含义 |
|---|---|
| 0 | 选中的用例全部通过 |
| 1 | 命令或配置错误：文件不合法、缺少 Key、入口无法启动等，运行前就会发现 |
| 2 | 出现回归：至少一条用例判定失败 |
| 3 | 无法判定：有用例因执行错误没有结论，例如工具结果无法提供；或者没有选中任何用例 |

所有文件都校验通过才会开始运行。运行前还会真实启动一次被测 Agent：入口导入失败会直接报错，
不会等到每条用例都失败。

### 5.5 在 CI 里运行

```yaml
- name: Install AgentRig
  run: pip install https://github.com/ChenCJ-io/agentrig/releases/download/v0.4.0a0/agentrig-0.4.0a0-py3-none-any.whl

- name: AgentRig regression
  run: agentrig test --junit agentrig-report.xml --markdown agentrig-report.md
  env:
    OPENAI_API_KEY: ${{ secrets.OPENAI_API_KEY }}
    CURATOR_API_KEY: ${{ secrets.CURATOR_API_KEY }}
```

- 发布包已内置 Web 前端，直接用 GitHub Release 上的 wheel 安装；发布到 PyPI 后改为 `pip install agentrig`；
- AgentRig 与被测 Agent 装在同一个环境时，`target.python` 可以不填；
- 没有 Curator Key 的环境用 `--no-curator`，此时用例要为每次工具调用准备 Fixture 或 Sample；
- `--markdown` 生成的报告可以直接贴到 PR 评论里。

## 6. 安全与环境

- **真工具不会执行**：受控模式下被接管的工具不会真的调用；
- **不用安装 AgentRig**：Driver 把只依赖标准库的 `agentrig.sdk` 复制到私有临时目录，通过 `PYTHONPATH`
  提供给被测解释器，服务端依赖不会覆盖被测环境的依赖。被测解释器需要 Python 3.10+；
- **Secret 不外泄**：被测进程默认只继承 `PATH`、`HOME`、语言、代理和证书等基础变量，AgentRig 自身的
  Secret，包括 Curator、Judge 的模型 Key，不会进入被测代码；
- **模型 Key 显式传入**：推荐 Target `secret_ref: "env:OPENAI_API_KEY"` 加 options
  `credential_env: "OPENAI_API_KEY"`，也可以用 `inherit_env: ["OPENAI_API_KEY"]` 转发宿主变量；项目
  自己的 `.env` 照常读取；
- **输出不干扰协议**：被测代码的 `print` 和日志全部写到 stderr，AgentRig 只保留最后 16 KiB 用于报错排障；
- **只放行指定解释器**：不在 `subprocess_allowlist` 中的解释器在保存 Target 时即被拒绝。

## 7. 三种工具方式

| `tool_mode` | 被测工具 | 证据 |
|---|---|---|
| `controlled` | 不执行，结果来自 Provider 链 | `tool_call`、`provider_attempt`、`tool_result` |
| `observe_only` | 真实执行；用例含 Fixture 或 Profile 含 Curator 时由 Planner 跳过 | `tool_call`（observed_only），结果只保留 sha256 摘要，不导出正文 |
| `proxy` | 不支持：进程内工具已在框架层接管，Planner 按缺少 `tool_proxy_injection` 跳过 | — |

## 8. 结果如何还给框架

- **Agno**：受控结果统一转成 JSON 文本。Agno 会把工具返回值 `str()` 后交给模型，dict 原样返回会变成
  Python repr；
- **LangGraph**：结果包装成带原 `tool_call_id` 的 `ToolMessage`，编码方式与 ToolNode 一致；
- **`@agentrig.sdk.tool`**：按返回类型注解还原。`str` 得到 JSON 文本，Pydantic 模型得到模型实例。

声明了结构化返回类型的工具，Fixture、Sample 与 Curator 结果都要通过该 Schema 校验。标量返回值只
附带工具说明，不约束结果类型，因此字符串工具也可以写对象形式的 Fixture。

## 9. 已知限制

- **Agno**
  - Agent 级 `tool_hooks` 会替换 `@tool(tool_hooks=...)` 声明的单工具 hook，这是 Agno 自身的行为；
    harness 会在 Capability 的 limitations 中标出；
  - `cache_results` 在 harness 内关闭，避免回放结果写进真实缓存；
  - `requires_confirmation` / `external_execution` 工具会让 Agno 暂停运行，本轮以暂停提示作为回复；
  - MCPTools 的工具定义在首次运行连接后才出现，describe 阶段不会列出；MCP 工具调用的接管还没有
    纳入自动化测试。
- **LangGraph**
  - 只接管 ToolNode 执行的工具，普通节点里直接调用的函数不会被接管；
  - harness 用 `ainvoke` 运行，只实现了同步钩子的自定义 middleware 需要兼容异步；
  - 需要 runtime context 的图，用 `factory: true` 或普通函数入口包一层。
- **通用**
  - 普通函数 Agent 在生产环境里也要能导入 `agentrig.sdk`，目前它随 `agentrig` 包发布；Agno 与
    LangGraph Agent 不需要导入任何 AgentRig 代码；
  - 每个 CaseRun 一个进程，导入框架通常需要 1–3 秒；
  - 模型调用是真实的：需要被测 Agent 自己的模型 Key，结果存在波动，用 `repeat_count` 观察分布。

## 10. 排障

| 现象 | 常见原因 |
|---|---|
| `python_agent interpreter is not permitted` | 解释器路径不在 `subprocess_allowlist` 中（精确匹配） |
| `harness startup failed: ModuleNotFoundError` | `cwd` 不是项目根目录，或 `entry` 的模块路径错误 |
| `harness startup failed` 并提示配置或注册表未初始化 | 生产服务启动时做的初始化没有在入口里复刻，见 §1.2 |
| 回复为空，或停在"我将……"这类开场白 | 客户端工具停止了本次运行，入口没有把结果带回去继续，见 §1.2 |
| Curator 编出的数据与业务无关 | Target 没有配置 `conversation_initial_state`，见 §4 |
| 证据里没有工具调用 | LangGraph 工具不在 ToolNode 里，或普通函数工具没有加 `@agentrig.sdk.tool` |
| `ProviderExhausted` | Fixture/Sample 未命中，且 Profile 没有启用 Curator |
| 生成的用例草稿里没有 Fixture | 对话用的是 `observe_only` 配置，只保留了结果摘要 |
