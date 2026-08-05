export type BadgeTone = "neutral" | "accent" | "success" | "warning" | "danger";

export function tone(value: string): BadgeTone {
  if (["completed", "submitted", "ready", "delivered", "authorized", "succeeded"].includes(value)) return "success";
  if (["failed", "timed_out", "cancelled", "offline", "error", "denied"].includes(value)) return "danger";
  if (["running", "dispatched", "confirmed", "executing", "eligible"].includes(value)) return "accent";
  if (["queued", "created", "draft", "pending", "awaiting_confirmation", "stale"].includes(value)) return "warning";
  return "neutral";
}

export function statusLabel(value: string): string {
  const labels: Record<string, string> = {
    cancelled: "已取消",
    completed: "已完成",
    confirmed: "已确认",
    created: "已创建",
    delivered: "已送达",
    dispatched: "已派发",
    draft: "草稿",
    failed: "失败",
    idle: "空闲",
    offline: "离线",
    pending: "待处理",
    queued: "排队中",
    ready: "就绪",
    authorized: "已授权",
    awaiting_confirmation: "等待确认",
    denied: "已拒绝",
    stale: "已过期",
    superseded: "已替代",
    executing: "执行中",
    bypassed: "已绕过",
    eligible: "按需调用",
    not_needed: "不需要",
    running: "运行中",
    submitted: "已提交",
    succeeded: "已完成",
    timed_out: "已超时",
  };
  return labels[value] ?? value.replaceAll("_", " ");
}

export function decisionKindLabel(value: string): string {
  const labels: Record<string, string> = {
    clarification: "信息澄清",
    scope_selection: "范围选择",
    execution_strategy: "执行策略",
    submission: "提交决策",
    diagnosis: "证据诊断",
    recovery: "恢复建议",
    asset_draft: "资产沉淀",
  };
  return labels[value] ?? value;
}

export function decisionActionLabel(value: string): string {
  const labels: Record<string, string> = {
    ask_user: "向用户确认关键信息",
    no_action: "保留现状并解释",
    create_plan: "生成有界评测计划",
    create_plan_revision: "生成新的计划修订",
    update_draft_plan: "更新评测计划草稿",
    request_plan_confirmation: "请求确认精确计划",
    confirm_plan: "确认当前计划",
    submit_plan: "提交一个评测运行",
    cancel_plan: "取消当前计划",
    cancel_run: "停止评测运行",
    retry_invocation_delivery: "重试同一 Worker 投递",
    request_worker_correction: "请求 Worker 纠正输出",
    create_case_draft: "沉淀测试用例草稿",
    create_sample_draft: "沉淀工具结果样本",
    create_target_draft: "创建被测 Agent 草稿",
  };
  return labels[value] ?? value.replaceAll("_", " ");
}

export function policyLabel(value: string): string {
  return {
    allow: "Core 已允许",
    require_confirmation: "需要用户确认",
    deny: "Core 已拒绝",
    stale: "事实已变化",
  }[value] ?? value;
}

export function evidenceKindLabel(value: string): string {
  const labels: Record<string, string> = {
    assistant_event: "用户/会话事件",
    evaluation_plan: "评测计划",
    run: "评测运行",
    case_run: "用例运行",
    run_event: "运行事件",
    evaluation: "评测结论",
    agent_invocation: "Worker 调用",
    test_case: "测试用例",
    target: "被测 Agent",
    execution_profile: "执行配置",
    tool_sample: "工具结果样本",
    target_check: "连通性检查",
    runtime_health: "运行时健康",
  };
  return labels[value] ?? value;
}

export function shortId(value: string): string {
  return value.length > 18 ? `${value.slice(0, 10)}…${value.slice(-5)}` : value;
}
