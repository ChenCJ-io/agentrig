---
name: harvest-tool-samples
description: 从 AgentRig V1 已存档的 Real Tool 运行证据显式创建 Sample 草稿，并遵守人工审核和禁止自动采集边界。
---

# 从真实运行证据创建 Sample

V1 不提供全局 Trace 抓取，也不会把 Real Tool 返回自动写进样本库。Sample 只能由控制方
从某个已存档的工具调用证据显式创建，初始状态一定是 draft。

## 前提

- 对应 CaseRun 的 Profile 包含 `real_tool`；
- 部署配置和 Profile 都允许该真实工具；
- 用户明确允许这次真实调用；
- 运行已停止，工具调用与结果已写入事件流。

如果任一条件不满足，不要尝试绕过授权。

## 工作顺序

1. 用 `get_run` 确认 Run 已停止。
2. 用 `list_case_runs` 找到目标 CaseRun。
3. 调用 `get_case_run`，在事件中找到：
   - `event_type: "tool_call"`；
   - 对应的 `tool_result.payload.source: "real_tool"`；
   - `tool_result.payload.tool_call_event_id` 指回该 tool_call 事件。
4. 使用 tool_call 事件本身的 `id`（形如 `evt_...`）调用：

```json
{
  "value": {
    "name": "订单查询真实样本",
    "source_tool_call_id": "evt_..."
  }
}
```

即 `create_sample` 会从该证据复制工具名、参数和结果，返回 draft Sample。
5. 调用 `get_sample` 回读，检查脱敏后的内容和版本适用范围。
6. 告诉用户到 Web 审核。MCP 不能批准或停用 Sample。

## 重要边界

- 不从 Fixture、Sample 或 Curator 结果反向创建“真实样本”。
- 不自动批量采集整个 Run。
- 不把 Sample 草稿描述成已可回放；只有 approved Sample 会被 Provider 命中。
- 不在 Sample 中写入 Token、Cookie、Authorization、密码或其他明文凭据。
- 一个 Sample 命中多个候选时，V1 按稳定顺序使用第一个，不设置偏好权重。
