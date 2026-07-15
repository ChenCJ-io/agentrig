# AgentRig CC 测试 Skill 包

> 最后更新：2026-07-07 · 状态：✅ 评估定稿
> 数据来源：`streaming-chat-v1/.claude/skills` 11 个 skill 实勘

## 核心结论

业务 agent（streaming-chat）沉淀的 CC skill 是**意外加分项**——质量高、约 60% 通用、提炼出的「agent 回归测试方法论」是任何 LLM agent 项目都适用的硬通货。建议作为 AgentRig 开源的一部分（形态 A 随主仓库），让用户 clone 即得「开箱即用的 CC 测试能力包」。

## 为什么 skill 是飞轮的关键使能

飞轮 = **CC 看代码 + 读数据生成用例**。前提是 **CC 得会用 AgentRig 的 MCP 工具**。skill 正是教 CC 怎么用的载体——把「何时调 upsert_test_case、何时调 get_real_tool_samples、怎么设计 rubric」这套方法论固化成 CC 能读的指令。

- **没有 skill**：用户装上 AgentRig，CC 不一定知道怎么高效用这些工具写测试
- **有 skill**：开箱即用，CC 立刻是「测试专家」

降低的是 **agent-native 接入门槛**（CC 的认知门槛），呼应 `07` 校准的尺子。

## 沉淀的测试方法论金句（这些本身是资产）

带实战证据的真知，新用户不用重新踩坑：

- **失败层级模型**：decision / render / client / LLM 幻觉四层，不同层不同诊断
- **rubric 判可观测结果，不判服务端内部机制**（避免测实现而非测行为）
- **结构型签名走 assertions 机判，别交 AI judge**（实战证据：false-fail 0.4→1.0）
- **真实样本零失真**：from_sample_id 优先，CC 别脑补工具返回
- **查重先于构建**：find_cases_by_tool 避免重复
- **编译器式自我修正**：upsert 后 errors→path 反馈循环
- **人机边界**：构建完停下等 approve，不全自动

## 三件套（v0.1 必发）

streaming-chat 沉淀的 7 个 AgentRig 相关 skill 里，三个核心是开源级教材：

### 1. build-test-case（case 构建流水线）
查重(find_cases_by_tool) → 取真实样本(get_tool_result_samples, from_sample_id 零失真) → 校准 schema(get_case_schema, 不硬编码) → 设计 rubric(判可观测不判内部) → upsert(编译器式自我修正) → 停下等 approve

### 2. run-test-cases（执行 + 失败诊断）
版本×通道矩阵防假红；失败先隔离判定层(enable_llm_eval=false)再猜因；rule 假红 vs 真红判据；issues/AI judge 推测 vs run_time.log 事实

### 3. harvest-tool-samples（真实样本采集）
只收真实会话(conv_*)、排除 mock 回放(session_*)；按工具名聚合

## 通用 vs streaming-chat 专有

| skill | 通用度 | 开源？ |
|---|---|---|
| build-test-case | 主体框架通用，示例 streaming-chat | ✅ 脱敏（替换 search_tool/item_id）|
| run-test-cases | 执行诊断流程通用 | ✅ 脱敏 |
| harvest-tool-samples | 采样方法论通用，脚本耦合 streaming-chat 日志 | ✅ 脱敏（脚本标「示例需改」）|
| fix-bug-from-errors | 错误管线方法论通用，脚本耦合错误 JSON | 🟡 v0.2（或标示例脚本）|
| analyze-session / mine-cases-from-sessions | 耦合 streaming-chat DB schema | ❌ 不开放（留 examples）|
| weekly-report | 仅引用 | 🟡 v0.2 |

## 开源形态：A（随主仓库 `agentrig/skills/`）

```
agentrig/skills/
├── core/                          # v0.1 必发（核心三件套）
│   ├── build-test-case/           # case 构建流水线
│   ├── run-test-cases/            # 执行 + 诊断
│   └── harvest-tool-samples/      # 真实样本采集
├── observability/                 # v0.2
│   └── fix-bug-from-errors/
└── README.md                      # 说明这组 skill 教 CC 怎么用 AgentRig
```

**形态 A 理由**：
1. **强工具耦合**——skill 几乎只对 AgentRig MCP 有意义，独立包安装/版本对齐成本高
2. **双向受益**——skill 踩坑笔记是平台行为的事实文档，随 API 演进同步，避免漂移（skill 自己反复强调「随 agent-scope 演进更新，别腐化」）
3. **clone 即得**——契合「开箱即用测试平台」定位

## 开源前脱敏清单（核心三件套，2-3 天）

1. **业务词替换**：search_tool / item_id / masks / aigcType / ai_culling / project_state / 9.x 版本号 / wechat → 中性占位（search_tool / item_id）
2. **§7 通用化或移除**：reference.md「附件保真三形态」是点修专有，降级为通用「会话上下文物化契约」或删
3. **MCP 前缀统一**：散见的 `mcp__agent-scope__*` 与裸工具名统一为开源 server 名（`agentrig`）
4. **补 `skills/README.md`**：目录级说明
5. **双语 frontmatter**：description 字段（CC 触发匹配关键）加英文，面向国际
6. **脚本标注**：`extract_tool_samples.py` 等标「示例脚本，需按你的日志格式适配」

## 竞品对比（加分项）

| | MCP 工具 | 教 CC 怎么用的 skill 包 |
|---|---|---|
| Langfuse / promptfoo / mcp-eval | 有/无 | ❌ 都没有 |
| **AgentRig** | 六组 20 工具 | ✅ **开箱即用的测试能力包** |

「不仅给工具，还给教 CC 怎么用工具做测试的方法论包」——独特加分，强化飞轮（CC 会用工具才能持续生成用例）。

## 对 PR 计划的影响（已写进 `05`）

新增 Phase 1.9（skill 包脱敏，2-3 天），v0.1-alpha 带 `skills/core/` 三件套。Phase 1.9 独立（只依赖 Phase 4 MCP 六组脱敏），可与 Phase 1.6/1.7 并行。
