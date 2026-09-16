---
name: run-test-cases
description: 使用 AgentRig V1 的异步 run_cases 统一执行单用例、批量、多版本、重复或 A/B 测试，查询原子证据并在需要时回写外部判定。
---

# 执行与分析 AgentRig V1 用例

单用例和批量使用同一个 `run_cases`。不要寻找 `run_single_case`、`rerun_case` 或汇总型
“自动分析”工具；V1 由 Codex/Claude Code 组合原子工具。

## 提交前

1. 用 `list_test_cases` 或明确的 `case_ids` 选择用例。
2. 用 `get_target` 查看 Target 和版本配置；先用 `list_driver_types` 确认 Driver 部署就绪，
   必要时用 `get_target_schema` 核对 options，再调用 `check_target`。
3. 用 `get_execution_profile` 确认：
   - `tool_mode`；
   - Provider 顺序；
   - 主评判器覆盖；
   - 并发、超时和重复次数；
   - Curator/Judge 是否配置。
4. 如果 Profile 包含 `real_tool`，再次确认用户已允许真实调用。

不传 `version` 时，每个用例按自己的 `supported_versions` 展开；Target 另外登记但
该用例不支持的版本会出现在 `skipped_items`。单个请求最多包含
baseline 和 candidate 两个 Target；普通运行只传 candidate。

## 提交

调用 `run_cases`，可传明确 `case_ids` 或 selector，二者只能选一个。调用会立即返回
`run_id`、实际选中的用例和结构化 `skipped_items`。

`skipped_items` 是单项结果，不代表整个批次失败。先解释版本不兼容、Driver 能力不足或评判
配置错误，再继续观察可执行项。

## 查询异步进度

1. 轮询 `get_run(run_id)`，不要高频请求。
2. 执行过程中可以随时调用 `list_case_runs(run_id)` 查看已完成项。
3. 父 Run 到达 completed、cancelled 或 failed 后，对需要分析的单项调用
   `get_case_run(case_run_id)`。
4. 事件很多时改用 `list_case_run_events` 按类型和分页读取；不要为了摘要反复拉取完整快照。

CaseRun 中要分别读取：

- `status`：执行是否完成、失败、取消或跳过；
- `evaluation_state`：pass、fail、inconclusive、awaiting_verdict 或 evaluation_error；
- `events`：用户消息、助手回复、工具调用、Provider 尝试、工具结果、校验、usage 和错误；
- `evaluations`：Rule、Evidence Judge、External 各自的存档结果。

不要把执行失败等同于业务断言 fail，也不要用父 Run 的 completed 代替单项结论。

## Codex/Claude Code 自己判定

当主评判器是 `external_controller` 时：

1. 读取完整 CaseRun 的脱敏事件；
2. 根据用例 rubric/断言和运行证据形成 pass、fail 或 inconclusive；
3. 用 `get_case_run.events[].id` 或 `list_case_run_events.items[].id` 填写
   `evidence_refs`；
4. 调用 `submit_external_verdict`，并在 `submitted_by` 标明控制方。

同一 CaseRun 再次提交会覆盖当前 External 记录，但不会修改 Rule、Judge 或原始证据。
如果启用了 Evidence Judge 且控制方认可其结果，不需要额外回写。

## 失败与重跑

- `provider_exhausted`：逐项看 `provider_attempt`，区分未命中、不可用和校验失败。
- `target_unreachable` / `driver_capability_missing`：属于接入或环境问题。
- `case_timeout` / `cancelled` / `interrupted`：属于执行状态，不推断业务通过。
- `evaluation_error`：评判失败，不等于 agent 行为 fail。

V1 不自动重跑。是否重新调用 `run_cases` 由控制方或用户根据原因决定。
