import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Archive,
  Bot,
  BrainCircuit,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Clock3,
  FilePenLine,
  GitBranch,
  LoaderCircle,
  Network,
  MessageSquarePlus,
  Play,
  Send,
  ShieldCheck,
  Sparkles,
  UserRound,
  XCircle,
} from "lucide-react";
import {
  useEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type ReactNode,
} from "react";
import { Link, useLocation } from "react-router";

import {
  createAssistantSession,
  getAssistantProviderHealth,
  getAssistantSession,
  getAssistantTurn,
  getDecisionMetrics,
  getEvaluationPlan,
  listAgentInvocations,
  listAssistantEvents,
  listAssistantSessions,
  listDecisions,
  sendAssistantMessage,
  streamAssistantEvents,
  type AgentInvocation,
  type AssistantEvent,
  type AssistantEventPage,
  type DecisionRecord,
  updateEvaluationPlan,
} from "~/api/v2";
import { MarkdownContent } from "~/components/content/markdown-content";
import { Badge } from "~/components/ui/badge";
import { Button } from "~/components/ui/button";
import { formatChinaDateTime, formatChinaEventTime } from "~/utils/date-time";

import styles from "./assistant-page.module.css";
import {
  canonicalAssistantEvents,
  shortId,
  statusLabel,
  tone,
} from "./assistant-presenters";
import { DecisionCard, DecisionSummary } from "./decision-cards";

export function AssistantPage() {
  const location = useLocation();
  const routeTargetId = targetIdFromPath(location.pathname);
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [newTitle, setNewTitle] = useState("");
  const [message, setMessage] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [editingPlan, setEditingPlan] = useState(false);
  const [goalDraft, setGoalDraft] = useState("");
  const [selectionDraft, setSelectionDraft] = useState("");
  const [reasoningDraft, setReasoningDraft] = useState("");
  const [pendingTurn, setPendingTurn] = useState<{
    sessionId: string;
    turnId: string;
  } | null>(null);
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
  const latestUserTurnId = useMemo(
    () =>
      [...(events.data?.items ?? [])]
        .reverse()
        .find((item) => item.event_type === "user_message" && item.turn_id)
        ?.turn_id ?? null,
    [events.data],
  );
  const trackedTurnId =
    pendingTurn?.sessionId === selectedId
      ? pendingTurn.turnId
      : latestUserTurnId;
  const turn = useQuery({
    queryKey: ["v2", "turn", trackedTurnId],
    queryFn: () => getAssistantTurn(trackedTurnId!),
    enabled: Boolean(trackedTurnId),
    refetchInterval: 1_500,
  });
  const turnBusy = ["queued", "dispatched", "running"].includes(
    turn.data?.status ?? "",
  );
  useEffect(() => {
    if (pendingTurn && pendingTurn.turnId === turn.data?.id && !turnBusy) {
      setPendingTurn(null);
    }
  }, [pendingTurn, turn.data?.id, turnBusy]);
  const decisions = useQuery({
    queryKey: ["v2", "decisions", selectedId],
    queryFn: () => listDecisions(selectedId!),
    enabled: Boolean(selectedId),
  });
  const decisionMetrics = useQuery({
    queryKey: ["v2", "decision-metrics", selectedId],
    queryFn: () => getDecisionMetrics(selectedId!),
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
      const cursor =
        cached?.items.reduce((value, item) => Math.max(value, item.seq), 0) ??
        0;
      activeRequest = new AbortController();
      try {
        await streamAssistantEvents(
          selectedId,
          cursor,
          (incoming) => {
            queryClient.setQueryData<AssistantEventPage>(key, (current) => {
              const existing = current?.items ?? [];
              if (existing.some((item) => item.id === incoming.id))
                return current;
              const items = [...existing, incoming].sort(
                (left, right) => left.seq - right.seq,
              );
              return {
                items,
                total: Math.max(current?.total ?? 0, items.length),
                limit: current?.limit ?? 500,
                after_seq: current?.after_seq ?? 0,
              };
            });
            void queryClient.invalidateQueries({ queryKey: key });
            if (incoming.turn_id) {
              void queryClient.invalidateQueries({
                queryKey: ["v2", "turn", incoming.turn_id],
              });
            }
            void queryClient.invalidateQueries({
              queryKey: ["v2", "session", selectedId],
            });
            if (incoming.plan_id) {
              void queryClient.invalidateQueries({ queryKey: ["v2", "plan"] });
            }
            if (incoming.decision_id) {
              void queryClient.invalidateQueries({
                queryKey: ["v2", "decisions", selectedId],
              });
              void queryClient.invalidateQueries({
                queryKey: ["v2", "decision-metrics", selectedId],
              });
            }
            if (
              incoming.invocation_id ||
              incoming.event_type === "run_status"
            ) {
              void queryClient.invalidateQueries({
                queryKey: ["v2", "invocations", selectedId],
              });
            }
          },
          activeRequest.signal,
        );
      } catch (error) {
        if (
          !stopped &&
          !activeRequest.signal.aborted &&
          !(error instanceof TypeError)
        ) {
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
    queryKey: ["v2", "assistant-provider-health"],
    queryFn: getAssistantProviderHealth,
    refetchInterval: 10_000,
  });
  const assistantAvailable = Boolean(health.data?.available);
  const advancedProvider = health.data?.provider === "agentteams";
  const assistantName = advancedProvider ? "Manager" : "评测助手";

  const refreshWorkspace = async () => {
    await Promise.all([
      queryClient.invalidateQueries({ queryKey: ["v2", "sessions"] }),
      queryClient.invalidateQueries({
        queryKey: ["v2", "session", selectedId],
      }),
      queryClient.invalidateQueries({ queryKey: ["v2", "events", selectedId] }),
      queryClient.invalidateQueries({
        queryKey: ["v2", "decisions", selectedId],
      }),
      queryClient.invalidateQueries({
        queryKey: ["v2", "decision-metrics", selectedId],
      }),
      queryClient.invalidateQueries({ queryKey: ["v2", "plan"] }),
      trackedTurnId
        ? queryClient.invalidateQueries({
            queryKey: ["v2", "turn", trackedTurnId],
          })
        : Promise.resolve(),
    ]);
  };

  const createSession = useMutation({
    mutationFn: () =>
      createAssistantSession(
        newTitle.trim() || "新的评测会话",
        routeTargetId ?? "default",
      ),
    onSuccess: async (created) => {
      setSelectedId(created.id);
      setNewTitle("");
      setNotice(
        advancedProvider
          ? "评测会话已创建，正在准备 AgentTeams 协作房间。"
          : "评测会话已创建，可以直接提问或描述评测任务。",
      );
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
    onSuccess: async (receipt) => {
      setPendingTurn({ sessionId: selectedId!, turnId: receipt.turn_id });
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
      return sendAssistantMessage(
        selectedId,
        `确认计划 ${current.id} revision ${current.revision}。请记录 confirm_plan 决策并完成确认，但不要提交 Run。`,
        current.id,
        {
          action_type: "confirm_plan",
          plan_id: current.id,
          revision: current.revision,
        },
      );
    },
    onSuccess: async (receipt) => {
      setPendingTurn({ sessionId: selectedId!, turnId: receipt.turn_id });
      setNotice("确认请求已提交，Core 将校验计划版本和本次用户确认。");
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
    mutationFn: () =>
      sendAssistantMessage(
        selectedId!,
        `提交已确认计划 ${plan.data!.id} revision ${plan.data!.revision}。请记录 submit_plan 决策并只创建一个 Run。`,
        plan.data!.id,
        {
          action_type: "submit_plan",
          plan_id: plan.data!.id,
          revision: plan.data!.revision,
        },
      ),
    onSuccess: async (receipt) => {
      setPendingTurn({ sessionId: selectedId!, turnId: receipt.turn_id });
      setNotice("提交请求已进入 Core；校验成功后 Run 会在后台执行。");
      await refreshWorkspace();
    },
    onError: (error) => setNotice(errorMessage(error)),
  });

  const cancel = useMutation({
    mutationFn: () =>
      sendAssistantMessage(
        selectedId!,
        `取消计划 ${plan.data!.id} revision ${plan.data!.revision}。请记录 cancel_plan 决策并说明影响。`,
        plan.data!.id,
        {
          action_type: "cancel_plan",
          plan_id: plan.data!.id,
          revision: plan.data!.revision,
        },
      ),
    onSuccess: async (receipt) => {
      setPendingTurn({ sessionId: selectedId!, turnId: receipt.turn_id });
      setNotice("取消请求已进入 Core，等待状态更新。");
      await refreshWorkspace();
    },
    onError: (error) => setNotice(errorMessage(error)),
  });

  function submitMessage(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const content = message.trim();
    if (content && selectedId && !managerBusy) send.mutate(content);
  }

  const managerBusy =
    turnBusy ||
    send.isPending ||
    confirm.isPending ||
    submit.isPending ||
    cancel.isPending;

  const groupedAgents = useMemo(
    () => summarizeAgents(invocations.data?.items ?? []),
    [invocations.data],
  );
  const latestDecision = decisions.data?.items[0];
  const decisionById = useMemo(
    () => new Map((decisions.data?.items ?? []).map((item) => [item.id, item])),
    [decisions.data],
  );
  const runStatus = [...(events.data?.items ?? [])]
    .reverse()
    .find((item) => item.event_type === "run_status")?.payload.status;
  const runTerminal = ["completed", "failed", "cancelled"].includes(
    String(runStatus ?? ""),
  );
  const providers = plan.data?.preview.providers ?? [];
  const evaluators = plan.data?.preview.primary_evaluators ?? [];
  const curatorPath = adaptiveRoleStatus(
    groupedAgents.curator,
    providers.includes("simulation_curator"),
    runTerminal,
  );
  const judgePath = adaptiveRoleStatus(
    groupedAgents.judge,
    evaluators.includes("evidence_judge"),
    runTerminal,
  );
  const latestEventId = events.data?.items.at(-1)?.id;
  const visibleEvents = useMemo(
    () => canonicalAssistantEvents(events.data?.items ?? []),
    [events.data],
  );
  const workspaceTargetId =
    targetIdFromSelection(plan.data?.selection) ??
    targetIdFromPath(location.pathname);
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
            aria-label="新会话标题"
            disabled={createSession.isPending}
            onChange={(event) => setNewTitle(event.target.value)}
            placeholder="输入新会话标题"
            value={newTitle}
          />
          <Button
            disabled={createSession.isPending}
            icon={<MessageSquarePlus />}
            type="submit"
          >
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
                {item.status === "archived" ? (
                  <Archive size={13} />
                ) : (
                  <Sparkles size={13} />
                )}
                <strong>{item.title}</strong>
              </span>
              <small>
                {item.last_event_seq} 个事件 · {shortId(item.id)}
              </small>
            </button>
          ))}
          {!sessions.data?.items.length ? (
            <p className={styles.empty}>创建会话后，用自然语言描述评测目标。</p>
          ) : null}
        </div>
        <footer>
          <i className={assistantAvailable ? styles.online : ""} />
          <span>
            {assistantAvailable
              ? advancedProvider
                ? "AgentTeams 已就绪"
                : "基础评测助手已就绪"
              : "智能评测助手不可用"}
          </span>
          <small>
            {assistantAvailable
              ? advancedProvider
                ? "Matrix 与协作角色运行正常"
                : "模型负责问答与规划，Core 负责确认和执行"
              : health.data?.message || "正在检查模型 Provider"}
          </small>
        </footer>
      </aside>

      <main className={styles.conversation}>
        <header className={styles.conversationHeader}>
          <div>
            <span className="eyebrow">
              {advancedProvider
                ? "AgentTeams · 智能评测控制室"
                : "AgentRig · 智能评测工作台"}
            </span>
            <h1>{session.data?.title ?? "智能评测助手"}</h1>
            <p>资产问答 · 自然语言规划 · 人工确认 · 可审计执行</p>
          </div>
          <div className={styles.roomState}>
            <Badge
              tone={
                managerBusy
                  ? "accent"
                  : assistantAvailable
                    ? "success"
                    : "warning"
              }
            >
              {managerBusy
                ? `${assistantName} 正在处理`
                : !assistantAvailable
                  ? "智能助手不可用"
                  : advancedProvider && session.data?.matrix_room_id
                    ? "Matrix 房间已就绪"
                    : advancedProvider
                      ? "等待协作房间"
                      : "模型 Provider 已就绪"}
            </Badge>
            <code>
              {advancedProvider && session.data?.matrix_room_id
                ? shortId(session.data.matrix_room_id)
                : health.data?.provider ?? "—"}
            </code>
          </div>
        </header>

        {notice ? (
          <div className={styles.notice} role="status">
            <CircleAlert size={14} />
            <span>{notice}</span>
            <button onClick={() => setNotice(null)} type="button">
              <XCircle size={13} />
            </button>
          </div>
        ) : null}

        <div
          aria-label="评测助手消息记录"
          className={styles.messages}
          role="log"
          tabIndex={0}
        >
          {visibleEvents.map((item) => {
            const decision = item.decision_id
              ? decisionById.get(item.decision_id)
              : undefined;
            if (item.event_type === "decision_recorded" && decision) {
              return <DecisionCard decision={decision} key={item.id} />;
            }
            return <EventMessage event={item} key={item.id} />;
          })}
          {managerBusy ? (
            <div className={`${styles.message} ${styles.managerMessage}`}>
              <span className={styles.avatar}>
                <Bot size={14} />
              </span>
              <div>
                <small>{assistantName}</small>
                <p>
                  <LoaderCircle className={styles.spin} size={14} /> 正在处理…
                </p>
              </div>
            </div>
          ) : null}
          {selectedId && !visibleEvents.length ? (
            <div className={styles.welcome}>
              <span>
                <Sparkles size={22} />
              </span>
              <small>对话式评测工作台</small>
              <h2>先提问，或描述一项评测任务</h2>
              <p>
                助手会直接回答资产与运行问题；只有明确要求评测时才生成计划，且确认后才会提交运行。
              </p>
              <div className={styles.promptGrid}>
                {QUICK_PROMPTS.map((prompt) => (
                  <button
                    disabled={managerBusy}
                    key={prompt.label}
                    onClick={() => setMessage(prompt.value)}
                    type="button"
                  >
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
              disabled={!selectedId || !assistantAvailable || managerBusy}
              onChange={(event) => setMessage(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter" && !event.shiftKey) {
                  event.preventDefault();
                  event.currentTarget.form?.requestSubmit();
                }
              }}
              placeholder={
                managerBusy
                  ? `${assistantName} 正在处理上一条请求…`
                  : assistantAvailable
                    ? "描述评测目标、范围或你想追查的问题…"
                    : "智能评测助手当前不可用"
              }
              value={message}
            />
            <footer>
              <span>Enter 发送 · Shift + Enter 换行</span>
              <Button
                disabled={
                  !message.trim() ||
                  !selectedId ||
                  !assistantAvailable ||
                  managerBusy
                }
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
        <section className={styles.currentDecision}>
          <header>
            <div>
              <span className="eyebrow">自适应决策</span>
              <strong>当前决策</strong>
            </div>
            <BrainCircuit size={16} />
          </header>
          {latestDecision ? (
            <DecisionSummary
              decision={latestDecision}
              metrics={decisionMetrics.data}
            />
          ) : (
            <p className={styles.empty}>
              {advancedProvider ? "Manager" : "助手"} 形成关键判断后，这里会显示选择、依据和策略裁定。
            </p>
          )}
        </section>

        <section className={styles.agentTeam}>
          <header>
            <div>
              <span className="eyebrow">动态协作拓扑</span>
              <strong>实际执行路径</strong>
            </div>
            <Network size={16} />
          </header>
          <div className={styles.topologyRail}>
            <span>{advancedProvider ? "Manager" : "Assistant"}</span>
            <i />
            <span>Core Gate</span>
            <i />
            <span>Target</span>
          </div>
          <AgentRow
            icon={<Bot size={14} />}
            label={advancedProvider ? "评测主控 Manager" : "智能评测助手"}
            source={advancedProvider ? "AgentTeams" : "Model Provider"}
            status={
              managerBusy ? "running" : assistantAvailable ? "ready" : "offline"
            }
          />
          {advancedProvider ? (
            <>
              <AgentRow
                icon={<GitBranch size={14} />}
                label="结果模拟 Curator"
                status={curatorPath}
              />
              <AgentRow
                icon={<ShieldCheck size={14} />}
                label="证据裁决 Judge"
                status={judgePath}
              />
            </>
          ) : null}
        </section>

        <section className={styles.planCard} id="evaluation-plan">
          <header>
            <div>
              <span className="eyebrow">评测计划</span>
              <strong>当前计划</strong>
            </div>
            {plan.data ? (
              <Badge tone={tone(plan.data.status)}>
                {statusLabel(plan.data.status)}
              </Badge>
            ) : null}
          </header>
          {plan.data ? (
            <>
              <div className={styles.planGoal}>
                <small>评测目标 · 修订版本 {plan.data.revision}</small>
                <p>{planGoal(plan.data.goal)}</p>
              </div>
              <dl className={styles.planStats}>
                <div>
                  <dt>用例</dt>
                  <dd>{plan.data.preview.resolved_case_ids?.length ?? 0}</dd>
                </div>
                <div>
                  <dt>用例运行</dt>
                  <dd>{plan.data.preview.planned_case_runs ?? 0}</dd>
                </div>
                <div>
                  <dt>跳过</dt>
                  <dd>{plan.data.preview.skipped_items?.length ?? 0}</dd>
                </div>
              </dl>
              <div className={styles.planMeta}>
                <span>结果提供链</span>
                <p>{plan.data.preview.providers?.join(" → ") || "—"}</p>
                <span>评判器</span>
                <p>{plan.data.preview.primary_evaluators?.join(", ") || "—"}</p>
              </div>
              {editingPlan ? (
                <div className={styles.planEditor}>
                  <label>
                    评测目标 JSON
                    <textarea
                      onChange={(event) => setGoalDraft(event.target.value)}
                      value={goalDraft}
                    />
                  </label>
                  <label>
                    执行选择 JSON
                    <textarea
                      onChange={(event) =>
                        setSelectionDraft(event.target.value)
                      }
                      value={selectionDraft}
                    />
                  </label>
                  <label>
                    理由摘要 JSON
                    <textarea
                      onChange={(event) =>
                        setReasoningDraft(event.target.value)
                      }
                      value={reasoningDraft}
                    />
                  </label>
                  <div>
                    <Button
                      disabled={editPlan.isPending || managerBusy}
                      onClick={() => editPlan.mutate()}
                      size="sm"
                      variant="primary"
                    >
                      保存并预览
                    </Button>
                    <Button
                      disabled={editPlan.isPending || managerBusy}
                      onClick={() => setEditingPlan(false)}
                      size="sm"
                    >
                      放弃
                    </Button>
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
                      disabled={managerBusy}
                      icon={<FilePenLine />}
                      onClick={() => {
                        setGoalDraft(JSON.stringify(plan.data!.goal, null, 2));
                        setSelectionDraft(
                          JSON.stringify(plan.data!.selection, null, 2),
                        );
                        setReasoningDraft(
                          JSON.stringify(plan.data!.reasoning_summary, null, 2),
                        );
                        setEditingPlan(true);
                      }}
                      size="sm"
                    >
                      编辑计划
                    </Button>
                    <Button
                      disabled={managerBusy || editingPlan}
                      icon={<CheckCircle2 />}
                      onClick={() => confirm.mutate()}
                      size="sm"
                      variant="primary"
                    >
                      确认计划
                    </Button>
                  </>
                ) : null}
                {plan.data.status === "confirmed" ? (
                  <Button
                    disabled={managerBusy}
                    icon={<Play />}
                    onClick={() => submit.mutate()}
                    size="sm"
                    variant="primary"
                  >
                    提交运行
                  </Button>
                ) : null}
                {["draft", "confirmed"].includes(plan.data.status) ? (
                  <Button
                    disabled={managerBusy}
                    icon={<XCircle />}
                    onClick={() => cancel.mutate()}
                    size="sm"
                    variant="danger"
                  >
                    取消计划
                  </Button>
                ) : null}
                {plan.data.run_id ? (
                  <Link
                    className={styles.runLink}
                    to={
                      workspaceTargetId
                        ? `/targets/${encodeURIComponent(workspaceTargetId)}/evaluation/runs/${plan.data.run_id}`
                        : `/evaluation/runs/${plan.data.run_id}`
                    }
                  >
                    查看 Run <ChevronRight size={13} />
                  </Link>
                ) : null}
              </div>
              {plan.data.last_error ? (
                <pre className={styles.planError}>
                  {JSON.stringify(plan.data.last_error, null, 2)}
                </pre>
              ) : null}
            </>
          ) : (
            <p className={styles.empty}>
              助手创建计划后，这里显示结构化预览与确认边界。
            </p>
          )}
        </section>

        <section className={styles.invocations}>
          <header>
            <div>
              <span className="eyebrow">{advancedProvider ? "协作证据链" : "执行证据入口"}</span>
              <strong>{advancedProvider ? "Worker 调用证据" : "Run / Cell 证据"}</strong>
            </div>
            <Badge tone={advancedProvider && invocations.data?.total ? "accent" : "neutral"}>
              {advancedProvider ? invocations.data?.total ?? 0 : plan.data?.run_id ? 1 : 0}
            </Badge>
          </header>
          {advancedProvider ? (invocations.data?.items ?? []).slice(0, 6).map((item) => (
            <article className={styles.invocationCard} key={item.id}>
              <div className={styles.invocationTitle}>
                <span>
                  {item.agent_role === "simulation_curator" ? (
                    <GitBranch size={12} />
                  ) : (
                    <ShieldCheck size={12} />
                  )}
                </span>
                <p>
                  <strong>{roleName(item.agent_role)}</strong>
                  <small>{shortId(item.id)}</small>
                </p>
                <Badge tone={tone(item.status)}>
                  {statusLabel(item.status)}
                </Badge>
              </div>
              <dl className={styles.evidenceGrid}>
                <div>
                  <dt>请求事件</dt>
                  <dd title={item.request_event_id ?? ""}>
                    {item.request_event_id
                      ? shortId(item.request_event_id)
                      : "待生成"}
                  </dd>
                </div>
                <div>
                  <dt>响应事件</dt>
                  <dd title={item.response_event_id ?? ""}>
                    {item.response_event_id
                      ? shortId(item.response_event_id)
                      : "待生成"}
                  </dd>
                </div>
                <div>
                  <dt>结果引用</dt>
                  <dd title={item.result_ref ?? ""}>
                    {item.result_ref ? shortId(item.result_ref) : "待生成"}
                  </dd>
                </div>
              </dl>
              <footer>
                <span>用例运行</span>
                <code>{shortId(item.case_run_id)}</code>
              </footer>
            </article>
          )) : null}
          {advancedProvider && !invocations.data?.items.length ? <p className={styles.empty}>尚无 Worker 调用。</p> : null}
          {!advancedProvider ? <p className={styles.empty}>计划提交后，Run、Cell、Attempt 与 Timeline 会成为权威执行证据；基础助手不伪造 Worker 协作链。</p> : null}
        </section>
      </aside>
    </div>
  );
}

function EventMessage({ event }: { event: AssistantEvent }) {
  if (event.event_type === "decision_status_changed") return null;
  if (event.event_type === "run_status") {
    const status = String(event.payload.status ?? "completed");
    return (
      <div
        className={`${styles.activity} ${styles.runActivity}`}
        id={`assistant-event-${event.id}`}
      >
        <CheckCircle2 size={12} />
        <span>
          评测运行
          {status === "completed"
            ? "已完成，评测助手正在基于证据诊断"
            : `状态更新：${statusLabel(status)}`}
        </span>
        <code>{event.run_id ? shortId(event.run_id) : `#${event.seq}`}</code>
      </div>
    );
  }
  if (
    ![
      "user_message",
      "assistant_message",
      "system_notice",
      "error",
      "run_status",
    ].includes(event.event_type)
  ) {
    return (
      <div className={styles.activity} id={`assistant-event-${event.id}`}>
        <Clock3 size={12} />
        <span>{activityName(event)}</span>
        <code>
          {event.invocation_id
            ? shortId(event.invocation_id)
            : event.plan_id
              ? shortId(event.plan_id)
              : event.run_id
                ? shortId(event.run_id)
                : `#${event.seq}`}
        </code>
      </div>
    );
  }
  const user = event.actor_type === "user";
  const content = String(
    event.payload.content ??
      event.payload.message ??
      event.event_type.replaceAll("_", " "),
  );
  return (
    <div
      className={`${styles.message} ${user ? styles.userMessage : styles.managerMessage}`}
      id={`assistant-event-${event.id}`}
    >
      <span className={styles.avatar}>
        {user ? <UserRound size={14} /> : <Bot size={14} />}
      </span>
      <div>
        <small>{user ? "你" : event.actor_id}</small>
        <div className={styles.messageBody}>
          <MarkdownContent content={content} headingLevel={3} />
        </div>
        <footer>
          <time
            dateTime={event.created_at}
            title={`${formatChinaDateTime(event.created_at)} 北京时间`}
          >
            {formatChinaEventTime(event.created_at)} · 北京时间
          </time>
          <span>#{event.seq}</span>
          {user ? <em>{deliveryLabel(event.delivery_status)}</em> : null}
        </footer>
      </div>
    </div>
  );
}

const QUICK_PROMPTS = [
  {
    label: "查看被测 Agent",
    description: "直接查询当前已接入的 Target",
    value: "目前有哪些被测 Agent？",
  },
  {
    label: "查看测试用例",
    description: "统计已批准、草稿与拒绝状态",
    value: "目前有哪些已批准测试用例？",
  },
  {
    label: "创建版本对比",
    description: "baseline 与 candidate A/B 回归",
    value:
      "使用当前 Target 的 baseline 与 candidate 版本、默认执行配置和已批准用例，生成 A/B 版本对比计划。",
  },
] as const;

function deliveryLabel(status: AssistantEvent["delivery_status"]) {
  const labels: Record<AssistantEvent["delivery_status"], string> = {
    pending: "处理中",
    delivered: "已送达",
    local: "已处理",
    failed: "失败",
  };
  return labels[status];
}

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
    decision_recorded: "Manager 已记录结构化决策",
    decision_status_changed: "决策状态已更新",
  };
  return labels[event.event_type] ?? event.event_type.replaceAll("_", " ");
}

function AgentRow({
  icon,
  label,
  source = "AgentTeams",
  status,
}: {
  icon: ReactNode;
  label: string;
  source?: string;
  status: string;
}) {
  return (
    <div className={styles.agentRow}>
      <span>{icon}</span>
      <p>
        <strong>{label}</strong>
        <small>{source}</small>
      </p>
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

function parseJsonObject(
  value: string,
  label: string,
): Record<string, unknown> {
  const parsed: unknown = JSON.parse(value);
  if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new Error(`${label}必须是 JSON 对象`);
  }
  return parsed as Record<string, unknown>;
}

function adaptiveRoleStatus(
  current: string,
  planned: boolean,
  terminal: boolean,
) {
  if (current !== "idle") return current;
  if (!planned) return "not_needed";
  return terminal ? "bypassed" : "eligible";
}

function planGoal(goal: Record<string, unknown>) {
  return String(goal.normalized_goal ?? goal.user_request ?? "已准备评测目标");
}

function targetIdFromSelection(
  selection?: Record<string, unknown>,
): string | null {
  const direct = selection?.target_id;
  if (typeof direct === "string" && direct) return direct;
  const targets = selection?.targets;
  if (!Array.isArray(targets)) return null;
  const first = targets[0];
  if (!first || typeof first !== "object") return null;
  const targetId = (first as Record<string, unknown>).target_id;
  return typeof targetId === "string" && targetId ? targetId : null;
}

function targetIdFromPath(pathname: string): string | null {
  const match = pathname.match(/^\/targets\/([^/]+)/);
  return match?.[1] ? decodeURIComponent(match[1]) : null;
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}
