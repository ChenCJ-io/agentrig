import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  Bot,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Clock3,
  FilePenLine,
  GitBranch,
  LoaderCircle,
  MessageSquarePlus,
  Play,
  Send,
  ShieldCheck,
  Sparkles,
  UserRound,
  UsersRound,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type FormEvent, type ReactNode } from "react";
import ReactMarkdown from "react-markdown";
import { Link } from "react-router";
import remarkGfm from "remark-gfm";

import {
  cancelEvaluationPlan,
  confirmEvaluationPlan,
  createAssistantSession,
  getAgentTeamsHealth,
  getAssistantSession,
  getEvaluationPlan,
  listAgentInvocations,
  listAssistantEvents,
  listAssistantSessions,
  sendAssistantMessage,
  streamAssistantEvents,
  submitEvaluationPlan,
  type AgentInvocation,
  type AssistantEvent,
  type AssistantEventPage,
  updateEvaluationPlan,
} from "~/api/v2";
import { Badge } from "~/components/ui/badge";
import { Button } from "~/components/ui/button";

import styles from "./assistant-page.module.css";

export function AssistantPage() {
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [message, setMessage] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [editingPlan, setEditingPlan] = useState(false);
  const [goalDraft, setGoalDraft] = useState("");
  const [selectionDraft, setSelectionDraft] = useState("");
  const [reasoningDraft, setReasoningDraft] = useState("");
  const messageEndRef = useRef<HTMLDivElement>(null);

  const sessions = useQuery({
    queryKey: ["v2", "sessions"],
    queryFn: listAssistantSessions,
    refetchInterval: 3_000,
  });
  useEffect(() => {
    if (!selectedId && sessions.data?.items[0]) {
      setSelectedId(sessions.data.items[0].id);
    }
  }, [selectedId, sessions.data]);

  const session = useQuery({
    queryKey: ["v2", "session", selectedId],
    queryFn: () => getAssistantSession(selectedId!),
    enabled: Boolean(selectedId),
    refetchInterval: 2_000,
  });
  const events = useQuery({
    queryKey: ["v2", "events", selectedId],
    queryFn: () => listAssistantEvents(selectedId!),
    enabled: Boolean(selectedId),
  });

  useEffect(() => {
    if (!selectedId) return;
    let stopped = false;
    let reconnectTimer: ReturnType<typeof setTimeout> | undefined;
    let activeRequest: AbortController | undefined;
    const key = ["v2", "events", selectedId] as const;

    const connect = async () => {
      const cached = queryClient.getQueryData<AssistantEventPage>(key);
      const cursor = cached?.items.reduce((value, item) => Math.max(value, item.seq), 0) ?? 0;
      activeRequest = new AbortController();
      try {
        await streamAssistantEvents(
          selectedId,
          cursor,
          (incoming) => {
            queryClient.setQueryData<AssistantEventPage>(key, (current) => {
              const existing = current?.items ?? [];
              if (existing.some((item) => item.id === incoming.id)) return current;
              const items = [...existing, incoming].sort((left, right) => left.seq - right.seq);
              return {
                items,
                total: Math.max(current?.total ?? 0, items.length),
                limit: current?.limit ?? 500,
                after_seq: current?.after_seq ?? 0,
              };
            });
            void queryClient.invalidateQueries({ queryKey: ["v2", "session", selectedId] });
            if (incoming.plan_id) {
              void queryClient.invalidateQueries({ queryKey: ["v2", "plan"] });
            }
            if (incoming.invocation_id || incoming.event_type === "run_status") {
              void queryClient.invalidateQueries({ queryKey: ["v2", "invocations", selectedId] });
            }
          },
          activeRequest.signal,
        );
      } catch (error) {
        if (!stopped && !activeRequest.signal.aborted && !(error instanceof TypeError)) {
          console.warn("assistant event stream disconnected", error);
        }
      }
      if (!stopped) reconnectTimer = setTimeout(() => void connect(), 1_500);
    };

    void connect();
    return () => {
      stopped = true;
      activeRequest?.abort();
      if (reconnectTimer) clearTimeout(reconnectTimer);
    };
  }, [queryClient, selectedId]);
  const plan = useQuery({
    queryKey: ["v2", "plan", session.data?.active_plan_id],
    queryFn: () => getEvaluationPlan(session.data!.active_plan_id!),
    enabled: Boolean(session.data?.active_plan_id),
    refetchInterval: 2_000,
  });
  const invocations = useQuery({
    queryKey: ["v2", "invocations", selectedId],
    queryFn: () => listAgentInvocations(selectedId!),
    enabled: Boolean(selectedId),
    refetchInterval: 2_000,
  });
  const health = useQuery({
    queryKey: ["v2", "agentteams-health"],
    queryFn: getAgentTeamsHealth,
    refetchInterval: 10_000,
  });

  const refreshWorkspace = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["v2", "sessions"] }),
      queryClient.invalidateQueries({ queryKey: ["v2", "session", selectedId] }),
      queryClient.invalidateQueries({ queryKey: ["v2", "events", selectedId] }),
      queryClient.invalidateQueries({ queryKey: ["v2", "plan"] }),
    ]);
  };

  const createSession = useMutation({
    mutationFn: () => createAssistantSession(newTitle.trim() || "新的评测会话"),
    onSuccess: async (created) => {
      setSelectedId(created.id);
      setNewTitle("");
      setNotice("评测会话已创建，正在准备 AgentTeams 协作房间。");
      await refreshWorkspace();
    },
    onError: (error) => setNotice(errorMessage(error)),
  });

  const send = useMutation({
    mutationFn: (content: string) =>
      sendAssistantMessage(
        selectedId!,
        content,
        session.data?.active_plan_id ?? null,
      ),
    onSuccess: async () => {
      setMessage("");
      setNotice(null);
      await refreshWorkspace();
    },
    onError: (error) => setNotice(errorMessage(error)),
  });

  const confirm = useMutation({
    mutationFn: async () => {
      const current = plan.data;
      if (!selectedId || !current) throw new Error("没有可确认的计划");
      const receipt = await sendAssistantMessage(
        selectedId,
        `确认执行 ${current.id} revision ${current.revision}`,
        current.id,
      );
      return confirmEvaluationPlan(current.id, receipt.event_id);
    },
    onSuccess: async () => {
      setNotice("计划已绑定真实用户确认，可以提交运行。");
      await refreshWorkspace();
    },
    onError: (error) => setNotice(errorMessage(error)),
  });

  const editPlan = useMutation({
    mutationFn: () =>
      updateEvaluationPlan(plan.data!.id, {
        goal: parseJsonObject(goalDraft, "目标"),
        selection: parseJsonObject(selectionDraft, "执行选择"),
        reasoning_summary: parseJsonObject(reasoningDraft, "理由摘要"),
      }),
    onSuccess: async () => {
      setEditingPlan(false);
      setNotice("计划已更新，并使用同一 Planner 重新生成预览。");
      await refreshWorkspace();
    },
    onError: (error) => setNotice(errorMessage(error)),
  });

  const submit = useMutation({
    mutationFn: () => submitEvaluationPlan(plan.data!.id),
    onSuccess: async () => {
      setNotice("计划已提交，Run 将在后台继续执行。");
      await refreshWorkspace();
    },
    onError: (error) => setNotice(errorMessage(error)),
  });

  const cancel = useMutation({
    mutationFn: () => cancelEvaluationPlan(plan.data!.id),
    onSuccess: async () => {
      setNotice("计划已取消。");
      await refreshWorkspace();
    },
    onError: (error) => setNotice(errorMessage(error)),
  });

  function submitMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = message.trim();
    if (content && selectedId) send.mutate(content);
  }

  const groupedAgents = useMemo(
    () => summarizeAgents(invocations.data?.items ?? []),
    [invocations.data],
  );
  const latestEventId = events.data?.items.at(-1)?.id;
  useEffect(() => {
    messageEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [latestEventId, send.isPending]);

  return (
    <div className={styles.workspace}>
      <aside className={styles.sessions}>
        <header>
          <div>
            <span className="eyebrow">智能评测会话</span>
            <strong>评测会话</strong>
          </div>
          <MessageSquarePlus size={16} />
        </header>
        <form
          className={styles.newSession}
          onSubmit={(event) => {
            event.preventDefault();
            createSession.mutate();
          }}
        >
          <input
            onChange={(event) => setNewTitle(event.target.value)}
            placeholder="输入新会话标题"
            value={newTitle}
          />
          <Button disabled={createSession.isPending} size="sm" type="submit">
            新建
          </Button>
        </form>
        <div className={styles.sessionList}>
          {sessions.data?.items.map((item) => (
            <button
              className={item.id === selectedId ? styles.selectedSession : ""}
              key={item.id}
              onClick={() => setSelectedId(item.id)}
              type="button"
            >
              <span>
                {item.status === "archived" ? <Archive size={13} /> : <Sparkles size={13} />}
                <strong>{item.title}</strong>
              </span>
              <small>{item.last_event_seq} 个事件 · {shortId(item.id)}</small>
            </button>
          ))}
          {!sessions.data?.items.length ? (
            <p className={styles.empty}>创建会话后，用自然语言描述评测目标。</p>
          ) : null}
        </div>
        <footer>
          <i className={health.data?.matrix_reachable ? styles.online : ""} />
          <span>{health.data?.enabled ? "AgentTeams 已启用" : "仅核心模式"}</span>
          <small>{health.data?.matrix_reachable ? "Matrix 与协作角色运行正常" : "正在检查协作运行时"}</small>
        </footer>
      </aside>

      <main className={styles.conversation}>
        <header className={styles.conversationHeader}>
          <div>
            <span className="eyebrow">AgentTeams · 智能评测控制室</span>
            <h1>{session.data?.title ?? "智能评测助手"}</h1>
            <p>自然语言规划 · 人工确认 · 可审计执行</p>
          </div>
          <div className={styles.roomState}>
            <Badge tone={session.data?.matrix_room_id ? "success" : "warning"}>
              {session.data?.matrix_room_id ? "Matrix 房间已就绪" : "等待协作房间"}
            </Badge>
            <code>{session.data?.matrix_room_id ? shortId(session.data.matrix_room_id) : "—"}</code>
          </div>
        </header>

        {notice ? (
          <div className={styles.notice} role="status">
            <CircleAlert size={14} />
            <span>{notice}</span>
            <button onClick={() => setNotice(null)} type="button"><XCircle size={13} /></button>
          </div>
        ) : null}

        <div className={styles.messages}>
          {(events.data?.items ?? []).map((item) => (
            <EventMessage event={item} key={item.id} />
          ))}
          {send.isPending ? (
            <div className={`${styles.message} ${styles.managerMessage}`}>
              <span className={styles.avatar}><Bot size={14} /></span>
              <div><small>评测主控 Manager</small><p><LoaderCircle className={styles.spin} size={14} /> 正在投递…</p></div>
            </div>
          ) : null}
          {selectedId && !events.data?.items.length ? (
            <div className={styles.welcome}>
              <span><Sparkles size={22} /></span>
              <small>智能协作评测</small>
              <h2>从一句评测目标开始</h2>
              <p>Manager 会查询正式资产并生成结构化计划；只有你确认后才会提交运行。</p>
              <div className={styles.promptGrid}>
                {QUICK_PROMPTS.map((prompt) => (
                  <button key={prompt.label} onClick={() => setMessage(prompt.value)} type="button">
                    <strong>{prompt.label}</strong>
                    <small>{prompt.description}</small>
                    <ChevronRight size={13} />
                  </button>
                ))}
              </div>
            </div>
          ) : null}
          <div ref={messageEndRef} />
        </div>

        <form className={styles.composer} onSubmit={submitMessage}>
          <div className={styles.composerBox}>
            <textarea
              disabled={!selectedId || !health.data?.enabled || send.isPending}
              onChange={(event) => setMessage(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              placeholder={
                health.data?.enabled
                  ? "描述评测目标、范围或你想追查的问题…"
                  : "当前为 Core 模式；启用 AgentTeams 后可使用智能助手"
              }
              value={message}
            />
            <footer>
              <span>Enter 发送 · Shift + Enter 换行</span>
              <Button
                disabled={!message.trim() || !selectedId || !health.data?.enabled || send.isPending}
                type="submit"
                variant="primary"
              >
                <Send size={14} /> 发送
              </Button>
            </footer>
          </div>
        </form>
      </main>

      <aside className={styles.context}>
        <section className={styles.agentTeam}>
          <header>
            <div><span className="eyebrow">评测团队</span><strong>协作角色</strong></div>
            <UsersRound size={16} />
          </header>
          <AgentRow icon={<Bot size={14} />} label="评测主控 Manager" status={health.data?.enabled ? "ready" : "offline"} />
          <AgentRow icon={<GitBranch size={14} />} label="结果模拟 Curator" status={groupedAgents.curator} />
          <AgentRow icon={<ShieldCheck size={14} />} label="证据裁决 Judge" status={groupedAgents.judge} />
        </section>

        <section className={styles.planCard}>
          <header>
            <div><span className="eyebrow">评测计划</span><strong>当前计划</strong></div>
            {plan.data ? <Badge tone={tone(plan.data.status)}>{statusLabel(plan.data.status)}</Badge> : null}
          </header>
          {plan.data ? (
            <>
              <div className={styles.planGoal}>
                <small>评测目标 · 修订版本 {plan.data.revision}</small>
                <p>{planGoal(plan.data.goal)}</p>
              </div>
              <dl className={styles.planStats}>
                <div><dt>用例</dt><dd>{plan.data.preview.resolved_case_ids?.length ?? 0}</dd></div>
                <div><dt>用例运行</dt><dd>{plan.data.preview.planned_case_runs ?? 0}</dd></div>
                <div><dt>跳过</dt><dd>{plan.data.preview.skipped_items?.length ?? 0}</dd></div>
              </dl>
              <div className={styles.planMeta}>
                <span>结果提供链</span>
                <p>{plan.data.preview.providers?.join(" → ") || "—"}</p>
                <span>评判器</span>
                <p>{plan.data.preview.primary_evaluators?.join(", ") || "—"}</p>
              </div>
              {editingPlan ? (
                <div className={styles.planEditor}>
                  <label>评测目标 JSON<textarea onChange={(event) => setGoalDraft(event.target.value)} value={goalDraft} /></label>
                  <label>执行选择 JSON<textarea onChange={(event) => setSelectionDraft(event.target.value)} value={selectionDraft} /></label>
                  <label>理由摘要 JSON<textarea onChange={(event) => setReasoningDraft(event.target.value)} value={reasoningDraft} /></label>
                  <div>
                    <Button disabled={editPlan.isPending} onClick={() => editPlan.mutate()} size="sm" variant="primary">保存并预览</Button>
                    <Button disabled={editPlan.isPending} onClick={() => setEditingPlan(false)} size="sm">放弃</Button>
                  </div>
                </div>
              ) : null}
              {plan.data.confirmation.reasons.length ? (
                <div className={styles.confirmation}>
                  <CircleAlert size={13} />
                  <span>{plan.data.confirmation.reasons.join(" · ")}</span>
                </div>
              ) : null}
              <div className={styles.planActions}>
                {plan.data.status === "draft" ? (
                  <>
                    <Button
                      onClick={() => {
                        setGoalDraft(JSON.stringify(plan.data!.goal, null, 2));
                        setSelectionDraft(JSON.stringify(plan.data!.selection, null, 2));
                        setReasoningDraft(JSON.stringify(plan.data!.reasoning_summary, null, 2));
                        setEditingPlan(true);
                      }}
                      size="sm"
                    >
                      <FilePenLine size={13} /> 编辑
                    </Button>
                    <Button disabled={confirm.isPending || editingPlan} onClick={() => confirm.mutate()} size="sm" variant="primary">
                      <CheckCircle2 size={13} /> 确认计划
                    </Button>
                  </>
                ) : null}
                {plan.data.status === "confirmed" ? (
                  <Button disabled={submit.isPending} onClick={() => submit.mutate()} size="sm" variant="primary">
                    <Play size={13} /> 提交运行
                  </Button>
                ) : null}
                {["draft", "confirmed"].includes(plan.data.status) ? (
                  <Button disabled={cancel.isPending} onClick={() => cancel.mutate()} size="sm">
                    取消
                  </Button>
                ) : null}
                {plan.data.run_id ? (
                  <Link className={styles.runLink} to={`/evaluation/batches/${plan.data.run_id}`}>
                    查看 Run <ChevronRight size={13} />
                  </Link>
                ) : null}
              </div>
              {plan.data.last_error ? (
                <pre className={styles.planError}>{JSON.stringify(plan.data.last_error, null, 2)}</pre>
              ) : null}
            </>
          ) : (
            <p className={styles.empty}>Manager 创建计划后，这里显示结构化预览与确认边界。</p>
          )}
        </section>

        <section className={styles.invocations}>
          <header>
            <div><span className="eyebrow">协作证据链</span><strong>Worker 调用证据</strong></div>
            <Badge tone={invocations.data?.total ? "accent" : "neutral"}>{invocations.data?.total ?? 0}</Badge>
          </header>
          {(invocations.data?.items ?? []).slice(0, 6).map((item) => (
            <article className={styles.invocationCard} key={item.id}>
              <div className={styles.invocationTitle}>
                <span>{item.agent_role === "simulation_curator" ? <GitBranch size={12} /> : <ShieldCheck size={12} />}</span>
                <p><strong>{roleName(item.agent_role)}</strong><small>{shortId(item.id)}</small></p>
                <Badge tone={tone(item.status)}>{statusLabel(item.status)}</Badge>
              </div>
              <dl className={styles.evidenceGrid}>
                <div><dt>请求事件</dt><dd title={item.request_event_id ?? ""}>{item.request_event_id ? shortId(item.request_event_id) : "待生成"}</dd></div>
                <div><dt>响应事件</dt><dd title={item.response_event_id ?? ""}>{item.response_event_id ? shortId(item.response_event_id) : "待生成"}</dd></div>
                <div><dt>结果引用</dt><dd title={item.result_ref ?? ""}>{item.result_ref ? shortId(item.result_ref) : "待生成"}</dd></div>
              </dl>
              <footer><span>用例运行</span><code>{shortId(item.case_run_id)}</code></footer>
            </article>
          ))}
          {!invocations.data?.items.length ? <p className={styles.empty}>尚无 Worker 调用。</p> : null}
        </section>
      </aside>
    </div>
  );
}

function EventMessage({ event }: { event: AssistantEvent }) {
  if (!["user_message", "assistant_message", "system_notice", "error", "run_status"].includes(event.event_type)) {
    return (
      <div className={styles.activity}>
        <Clock3 size={12} />
        <span>{activityName(event)}</span>
        <code>{event.invocation_id ? shortId(event.invocation_id) : event.plan_id ? shortId(event.plan_id) : event.run_id ? shortId(event.run_id) : `#${event.seq}`}</code>
      </div>
    );
  }
  const user = event.actor_type === "user";
  const content = String(event.payload.content ?? event.payload.message ?? event.event_type.replaceAll("_", " "));
  return (
    <div className={`${styles.message} ${user ? styles.userMessage : styles.managerMessage}`}>
      <span className={styles.avatar}>{user ? <UserRound size={14} /> : <Bot size={14} />}</span>
      <div>
        <small>{user ? "你" : event.actor_id}</small>
        <div className={styles.messageBody}>
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{content}</ReactMarkdown>
        </div>
        <footer>
          <time>{new Date(event.created_at).toLocaleTimeString()}</time>
          <span>#{event.seq}</span>
          {user ? <em>{event.delivery_status}</em> : null}
        </footer>
      </div>
    </div>
  );
}

const QUICK_PROMPTS = [
  {
    label: "运行成功样例",
    description: "lassist 背景增强全链路",
    value: "使用 target_lassist_local、profile_lassist_agentteams 和已批准用例 case_lassist_three_agent_demo，生成一次评测计划。不要扩大范围。",
  },
  {
    label: "验证安全策略",
    description: "图片编辑二次确认门禁",
    value: "只运行已批准用例 case_lassist_confirmation_gate_failure，使用本机 lassist 和当前 AgentTeams Profile，验证图片编辑前的二次确认策略。",
  },
  {
    label: "解释最近结果",
    description: "只引用本次 Run 证据",
    value: "解释最近一次运行的结果，只引用本次 Run 的证据，并区分执行错误与评测失败。",
  },
] as const;

function roleName(role: AgentInvocation["agent_role"]) {
  return role === "simulation_curator" ? "结果模拟 Curator" : "证据裁决 Judge";
}

function activityName(event: AssistantEvent) {
  if (event.event_type === "assistant_activity" && event.invocation_id) {
    return `${String(event.payload.agent_role ?? "Worker")} 已提交可验证回执`;
  }
  const labels: Record<string, string> = {
    plan_created: "Manager 已生成评测计划",
    plan_updated: "评测计划已更新",
    plan_confirmed: "用户确认已绑定计划",
    plan_submitted: "计划已提交运行",
    collaboration_intervention: "协作成员消息",
  };
  return labels[event.event_type] ?? event.event_type.replaceAll("_", " ");
}

function AgentRow({ icon, label, status }: { icon: ReactNode; label: string; status: string }) {
  return (
    <div className={styles.agentRow}>
      <span>{icon}</span>
      <p><strong>{label}</strong><small>AgentTeams</small></p>
      <Badge tone={tone(status)}>{statusLabel(status)}</Badge>
    </div>
  );
}

function summarizeAgents(items: AgentInvocation[]) {
  const latest = (role: AgentInvocation["agent_role"]) =>
    items.find((item) => item.agent_role === role)?.status ?? "idle";
  return {
    curator: latest("simulation_curator"),
    judge: latest("evidence_judge"),
  };
}

function parseJsonObject(value: string, label: string): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label}必须是 JSON 对象`);
  }
  return parsed as Record<string, unknown>;
}

function tone(value: string): "neutral" | "accent" | "success" | "warning" | "danger" {
  if (["completed", "submitted", "ready", "delivered"].includes(value)) return "success";
  if (["failed", "timed_out", "cancelled", "offline", "error"].includes(value)) return "danger";
  if (["running", "dispatched", "confirmed"].includes(value)) return "accent";
  if (["queued", "created", "draft", "pending"].includes(value)) return "warning";
  return "neutral";
}

function statusLabel(value: string) {
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
    running: "运行中",
    submitted: "已提交",
    timed_out: "已超时",
  };
  return labels[value] ?? value.replaceAll("_", " ");
}

function shortId(value: string) {
  return value.length > 18 ? `${value.slice(0, 10)}…${value.slice(-5)}` : value;
}

function planGoal(goal: Record<string, unknown>) {
  return String(goal.normalized_goal ?? goal.user_request ?? "已准备评测目标");
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}
