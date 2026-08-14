import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  Clock3,
  Database,
  FileCheck2,
  FileSearch,
  GitBranch,
  Layers3,
  RefreshCcw,
  RotateCcw,
  ShieldCheck,
  Siren,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useState, type ReactNode } from "react";

import {
  getProductionTrace,
  listAnnotations,
  listExecutionAttempts,
  listExecutionJobs,
  listFailurePatterns,
  listFailureSignals,
  listIngestSources,
  listPatternMonitors,
  listPatternTimeline,
  listProductionTraces,
  listProjects,
  listReviewItems,
  projectAction,
  type Annotation,
  type ExecutionJob,
  type FailurePattern,
  type FailureSignal,
  type ProductionSpan,
  type ProductionTrace,
  type ReviewItem,
  type TraceCaseDraftPreview,
  type TraceCaseDraftResult,
} from "~/api/governance";
import { Badge } from "~/components/ui/badge";
import { Button } from "~/components/ui/button";

import styles from "./governance-page.module.css";

export type GovernanceSection = "production" | "reviews" | "failures" | "jobs";

export function governanceSection(pathname: string): GovernanceSection {
  if (pathname.startsWith("/reviews")) return "reviews";
  if (pathname.startsWith("/failure-patterns")) return "failures";
  if (pathname.startsWith("/jobs")) return "jobs";
  return "production";
}

export function GovernancePage({ pathname }: { pathname: string }) {
  const section = governanceSection(pathname);
  const projects = useQuery({ queryKey: ["governance", "projects"], queryFn: listProjects });
  const [projectId, setProjectId] = useState("default");

  useEffect(() => {
    const available = projects.data?.items ?? [];
    if (available.length && !available.some((item) => item.id === projectId)) {
      setProjectId(available[0]!.id);
    }
  }, [projectId, projects.data]);

  const selectedProject = projects.data?.items.find((item) => item.id === projectId);
  return (
    <div className={styles.workspace}>
      <header className={styles.pageHeader}>
        <div>
          <span className="eyebrow">Project 治理 · 生产证据闭环</span>
          <h1>{sectionTitle(section)}</h1>
          <p>{sectionDescription(section)}</p>
        </div>
        <label className={styles.projectPicker}>
          <span>当前 Project</span>
          <select
            aria-label="当前 Project"
            onChange={(event) => setProjectId(event.target.value)}
            value={projectId}
          >
            {(projects.data?.items ?? []).map((project) => (
              <option key={project.id} value={project.id}>{project.name}</option>
            ))}
          </select>
          <small>{selectedProject?.default_environment ?? "正在读取环境"}</small>
        </label>
      </header>
      {projects.error ? <ErrorNotice value={projects.error} /> : null}
      {section === "production" ? <ProductionWorkspace projectId={projectId} /> : null}
      {section === "reviews" ? <ReviewWorkspace projectId={projectId} /> : null}
      {section === "failures" ? <FailureWorkspace projectId={projectId} /> : null}
      {section === "jobs" ? <JobWorkspace projectId={projectId} /> : null}
    </div>
  );
}

function ProductionWorkspace({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const traces = useQuery({
    queryKey: ["governance", projectId, "traces"],
    queryFn: () => listProductionTraces(projectId),
    refetchInterval: 10_000,
  });
  const sources = useQuery({
    queryKey: ["governance", projectId, "sources"],
    queryFn: () => listIngestSources(projectId),
  });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [expected, setExpected] = useState("保持原任务语义，并满足生产证据中的安全不变量。");
  const [userMessage, setUserMessage] = useState("");
  const [actor, setActor] = useState("production-reviewer");
  const [notice, setNotice] = useState<string | null>(null);
  const [preview, setPreview] = useState<TraceCaseDraftPreview | null>(null);

  useEffect(() => {
    const items = traces.data?.items ?? [];
    if (!selectedId || !items.some((item) => item.id === selectedId)) {
      setSelectedId(items[0]?.id ?? null);
    }
  }, [selectedId, traces.data]);

  const detail = useQuery({
    queryKey: ["governance", projectId, "trace", selectedId],
    queryFn: () => getProductionTrace(projectId, selectedId!),
    enabled: Boolean(selectedId),
  });
  const draftPayload = {
    source_span_ids: (detail.data?.spans ?? []).map((item) => item.id),
    template_user_message: userMessage.trim() || null,
    expected_behavior: expected.trim(),
    required_capabilities: [],
    target_versions: [],
    annotation_ids: [],
    failure_pattern_id: null,
    created_by: actor.trim(),
  };
  const previewDraft = useMutation({
    mutationFn: () => projectAction<TraceCaseDraftPreview>(
      projectId,
      `/production/traces/${encodeURIComponent(selectedId!)}/case-drafts:preview`,
      draftPayload,
    ),
    onSuccess: (value) => {
      setPreview(value);
      setNotice("草稿映射预览已生成；尚未创建测试用例。");
    },
  });
  const createDraft = useMutation({
    mutationFn: () => projectAction<TraceCaseDraftResult>(
      projectId,
      `/production/traces/${encodeURIComponent(selectedId!)}/case-drafts`,
      draftPayload,
    ),
    onSuccess: (value) => {
      setPreview(value.preview);
      setNotice(`已创建只读 lineage ${shortId(value.lineage.id)} 与用例草稿 ${value.case_id}。`);
    },
  });
  const createReview = useMutation({
    mutationFn: () => projectAction<ReviewItem>(projectId, "/review-items", {
      subject_kind: "production_trace",
      subject_id: selectedId,
      queue: "production-evidence",
      priority: 20,
      assignment: null,
      cohort: detail.data?.trace.environment ?? null,
      required_reviews: 2,
      created_reason: "Production Trace requires independent evidence review",
      created_by: actor.trim(),
    }),
    onSuccess: (value) => setNotice(`Trace 已进入审核队列：${shortId(value.id)}。`),
  });
  const retention = useMutation({
    mutationFn: () => projectAction<{
      trace_count: number;
      span_count: number;
      dry_run: boolean;
    }>(projectId, "/production/retention:run", {
      source_id: null,
      dry_run: true,
      actor: actor.trim(),
    }),
    onSuccess: (value) => setNotice(
      `保留策略 dry-run：${value.trace_count} 条 Trace、${value.span_count} 条 Span 将被处理。`,
    ),
  });
  const toggleSource = useMutation({
    mutationFn: ({ id, enabled }: { id: string; enabled: boolean }) => projectAction(
      projectId,
      `/production/ingest-sources/${encodeURIComponent(id)}:${enabled ? "disable" : "enable"}`,
    ),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["governance", projectId, "sources"] });
    },
  });

  const failures = [traces.error, sources.error, detail.error, previewDraft.error, createDraft.error, createReview.error, retention.error].filter(Boolean);
  const trace = detail.data?.trace;
  return (
    <>
      <MetricStrip items={[
        ["Production Traces", traces.data?.total ?? "—", "与 Run 数据域隔离"],
        ["Ingest Sources", sources.data?.length ?? "—", `${sources.data?.filter((item) => item.enabled).length ?? 0} 个已启用`],
        ["当前 Span", detail.data?.spans.length ?? "—", "只显示脱敏结构化证据"],
        ["Lineage", preview ? "已预览" : "待生成", preview?.mapping_version ?? "Trace → draft Case"],
      ]} />
      {notice ? <Notice>{notice}</Notice> : null}
      {failures.map((failure, index) => <ErrorNotice key={index} value={failure} />)}
      <div className={styles.productionGrid}>
        <Panel className={styles.sourcePanel} eyebrow="受控接入" title="OTLP Sources" actions={
          <Button disabled={retention.isPending || !actor.trim()} icon={<RotateCcw />} onClick={() => retention.mutate()} size="sm">Retention dry-run</Button>
        }>
          <div className={styles.sourceList}>
            {(sources.data ?? []).map((source) => (
              <article key={source.id}>
                <span><i data-enabled={source.enabled} /><strong>{source.name}</strong></span>
                <small>{source.allowed_service_names.join(", ")} · {source.retention_days}d</small>
                <button disabled={toggleSource.isPending} onClick={() => toggleSource.mutate({ id: source.id, enabled: source.enabled })} type="button">
                  {source.enabled ? "停用" : "启用"}
                </button>
              </article>
            ))}
            {!sources.isLoading && !sources.data?.length ? <Empty icon={Database} title="尚无 Ingest Source">默认关闭；创建并启用 Source 后才接受 OTLP。</Empty> : null}
          </div>
        </Panel>
        <Panel className={styles.traceListPanel} eyebrow="生产事实" title="Trace Inbox" actions={
          <Button icon={<RefreshCcw />} onClick={() => void traces.refetch()} size="sm">刷新</Button>
        }>
          <div className={styles.masterList}>
            {(traces.data?.items ?? []).map((item) => (
              <MasterButton
                active={selectedId === item.id}
                key={item.id}
                meta={`${item.service_name} · ${item.environment ?? "unknown"}`}
                onClick={() => setSelectedId(item.id)}
                status={item.status}
                title={item.name}
              />
            ))}
            {!traces.isLoading && !traces.data?.items.length ? <Empty icon={Activity} title="尚无 Production Trace">发送 OTLP/HTTP traces 后会显示在这里。</Empty> : null}
          </div>
        </Panel>
        <section className={styles.detailPanel}>
          {trace ? (
            <>
              <header className={styles.detailHeader}>
                <div><span className="eyebrow">Trace 详情</span><h2>{trace.name}</h2><code>{trace.id}</code></div>
                <StatusBadge value={trace.status} />
              </header>
              <div className={styles.detailScroll}>
                <div className={styles.factGrid}>
                  <Fact label="Service" value={trace.service_name} />
                  <Fact label="Environment" value={trace.environment ?? "unknown"} />
                  <Fact label="Started" value={formatDate(trace.started_at)} />
                  <Fact label="Ingest" value={trace.ingest_status} />
                </div>
                <EvidenceHashes values={[
                  ["Trace content", trace.content_hash],
                  ["Redaction policy", trace.redaction_policy_hash],
                ]} />
                <section className={styles.timelineSection}>
                  <header><div><span className="eyebrow">Span Timeline</span><h3>{detail.data?.spans.length ?? 0} 条结构化事件</h3></div><Badge tone={detail.data?.missing_parent_span_ids.length ? "warning" : "success"}>{detail.data?.missing_parent_span_ids.length ? "存在缺失父节点" : "父链完整"}</Badge></header>
                  <div className={styles.timeline}>
                    {(detail.data?.spans ?? []).map((span, index) => <SpanEvent index={index} key={span.id} span={span} />)}
                  </div>
                </section>
                <section className={styles.actionForm}>
                  <header><div><span className="eyebrow">Evidence → Asset</span><h3>生成只读映射预览与草稿</h3></div><ShieldCheck size={16} /></header>
                  <label>泛化后的用户消息<textarea onChange={(event) => setUserMessage(event.target.value)} placeholder="留空时由安全元数据生成，不复制生产正文" value={userMessage} /></label>
                  <label>预期行为<textarea onChange={(event) => setExpected(event.target.value)} value={expected} /></label>
                  <label>操作人<input onChange={(event) => setActor(event.target.value)} value={actor} /></label>
                  {preview ? <div className={styles.previewBox}><strong>{preview.generalized_user_message}</strong><p>{preview.expected_behavior}</p><small>{preview.mapping_hash} · 移除 {preview.removed_fields.length} 个字段</small></div> : null}
                  <footer>
                    <Button disabled={!expected.trim() || !actor.trim() || previewDraft.isPending} onClick={() => previewDraft.mutate()}>预览映射</Button>
                    <Button disabled={!expected.trim() || !actor.trim() || createDraft.isPending} onClick={() => createDraft.mutate()} variant="primary">创建 Case 草稿</Button>
                    <Button disabled={!actor.trim() || createReview.isPending} icon={<FileCheck2 />} onClick={() => createReview.mutate()}>送双人审核</Button>
                  </footer>
                </section>
              </div>
            </>
          ) : <Empty icon={FileSearch} title="选择一条 Trace">查看 Span、脱敏状态、Hash 与 Trace→Case lineage。</Empty>}
        </section>
      </div>
    </>
  );
}

function ReviewWorkspace({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const reviews = useQuery({
    queryKey: ["governance", projectId, "reviews"],
    queryFn: () => listReviewItems(projectId),
    refetchInterval: 10_000,
  });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [reviewer, setReviewer] = useState("reviewer-a");
  const [label, setLabel] = useState<Annotation["label"]>("pass");
  const [confidence, setConfidence] = useState<Annotation["confidence"]>("high");
  const [rationale, setRationale] = useState("");
  const [evidenceRef, setEvidenceRef] = useState("");
  const [notice, setNotice] = useState<string | null>(null);

  useEffect(() => {
    const items = reviews.data?.items ?? [];
    if (!selectedId || !items.some((item) => item.id === selectedId)) setSelectedId(items[0]?.id ?? null);
  }, [reviews.data, selectedId]);
  const selected = reviews.data?.items.find((item) => item.id === selectedId);
  useEffect(() => {
    if (selected) setEvidenceRef(`${selected.subject_kind.replace("production_", "")}:${selected.subject_id}`);
  }, [selected]);
  const annotations = useQuery({
    queryKey: ["governance", projectId, "annotations", selectedId],
    queryFn: () => listAnnotations(projectId, selectedId!),
    enabled: Boolean(selectedId),
  });
  const annotate = useMutation({
    mutationFn: () => projectAction<Annotation>(projectId, `/review-items/${encodeURIComponent(selectedId!)}/annotations`, {
      reviewer_id: reviewer.trim(),
      label,
      criteria: [],
      evidence_refs: [evidenceRef.trim()],
      rationale_summary: rationale.trim(),
      confidence,
      supersedes: null,
    }),
    onSuccess: async () => {
      setRationale("");
      setNotice("Annotation 已追加；历史 revision 保持不变。");
      await queryClient.invalidateQueries({ queryKey: ["governance", projectId, "annotations", selectedId] });
      await queryClient.invalidateQueries({ queryKey: ["governance", projectId, "reviews"] });
    },
  });
  const resolve = useMutation({
    mutationFn: (disputed: boolean) => projectAction(projectId, `/review-items/${encodeURIComponent(selectedId!)}:resolve`, {
      adjudicator_id: reviewer.trim(),
      role: "adjudicator",
      label: disputed ? null : label,
      status: disputed ? "disputed" : "resolved",
      rationale_summary: rationale.trim() || (disputed ? "Independent reviewers remain disputed." : "Current independent annotations support this label."),
    }),
    onSuccess: async (_, disputed) => {
      setNotice(disputed ? "分歧已显式保留，未伪装成金标。" : "GoldLabel 已生成并保留来源 Annotation。 ");
      await queryClient.invalidateQueries({ queryKey: ["governance", projectId, "reviews"] });
    },
  });
  const openCount = reviews.data?.items.filter((item) => !["resolved", "dismissed"].includes(item.status)).length ?? 0;
  const disputedCount = reviews.data?.items.filter((item) => item.status === "adjudication").length ?? 0;
  return (
    <>
      <MetricStrip items={[
        ["Review Queue", reviews.data?.total ?? "—", "CaseRun 与 Production 统一入口"],
        ["Open", openCount, "等待独立标注"],
        ["Adjudication", disputedCount, "分歧不会自动转金标"],
        ["Current Revisions", annotations.data?.length ?? "—", "append-only annotations"],
      ]} />
      {notice ? <Notice>{notice}</Notice> : null}
      {[reviews.error, annotations.error, annotate.error, resolve.error].filter(Boolean).map((error, index) => <ErrorNotice key={index} value={error} />)}
      <div className={styles.workbench}>
        <Panel className={styles.masterPanel} eyebrow="统一审核队列" title="Review Items" actions={<Button icon={<RefreshCcw />} onClick={() => void reviews.refetch()} size="sm">刷新</Button>}>
          <div className={styles.masterList}>
            {(reviews.data?.items ?? []).map((item) => <MasterButton active={selectedId === item.id} key={item.id} meta={`${subjectLabel(item.subject_kind)} · ${shortId(item.subject_id)}`} onClick={() => setSelectedId(item.id)} status={item.status} title={item.created_reason} />)}
            {!reviews.isLoading && !reviews.data?.items.length ? <Empty icon={FileCheck2} title="审核队列为空">CaseRun 或 Production Trace 送审后会显示在这里。</Empty> : null}
          </div>
        </Panel>
        <section className={styles.detailPanel}>
          {selected ? <>
            <header className={styles.detailHeader}><div><span className="eyebrow">Review Item</span><h2>{subjectLabel(selected.subject_kind)}</h2><code>{selected.id}</code></div><StatusBadge value={selected.status} /></header>
            <div className={styles.reviewLayout}>
              <div className={styles.detailScroll}>
                <div className={styles.factGrid}><Fact label="Subject" value={selected.subject_id} /><Fact label="Queue" value={selected.queue} /><Fact label="Required" value={`${selected.required_reviews} reviewers`} /><Fact label="Snapshot" value={shortId(selected.subject_snapshot_hash)} /></div>
                <section className={styles.annotationList}><header><span className="eyebrow">Append-only evidence</span><h3>{annotations.data?.length ?? 0} 条 Annotation</h3></header>{(annotations.data ?? []).map((item) => <article key={item.id}><span>R{item.revision}</span><div><header><strong>{item.reviewer_id}</strong><StatusBadge value={item.label} /></header><p>{item.rationale_summary}</p><footer>{item.evidence_refs.join(", ")} · {item.confidence}</footer></div></article>)}{!annotations.isLoading && !annotations.data?.length ? <Empty icon={FileSearch} title="尚无标注">提交第一条独立 Annotation。</Empty> : null}</section>
              </div>
              <form className={styles.sideForm} onSubmit={(event) => { event.preventDefault(); annotate.mutate(); }}>
                <header><span className="eyebrow">Independent review</span><h3>追加 Annotation</h3></header>
                <label>Reviewer<input onChange={(event) => setReviewer(event.target.value)} value={reviewer} /></label>
                <div className={styles.formPair}><label>Label<select onChange={(event) => setLabel(event.target.value as Annotation["label"])} value={label}><option value="pass">pass</option><option value="fail">fail</option><option value="inconclusive">inconclusive</option><option value="evaluation_error">evaluation_error</option></select></label><label>Confidence<select onChange={(event) => setConfidence(event.target.value as Annotation["confidence"])} value={confidence}><option value="high">high</option><option value="medium">medium</option><option value="low">low</option></select></label></div>
                <label>Evidence ref<input onChange={(event) => setEvidenceRef(event.target.value)} value={evidenceRef} /></label>
                <label>公开理由<textarea onChange={(event) => setRationale(event.target.value)} placeholder="说明结论与证据之间的关系" value={rationale} /></label>
                <Button disabled={!reviewer.trim() || !evidenceRef.trim() || !rationale.trim() || annotate.isPending} type="submit" variant="primary">追加标注</Button>
                <hr />
                <p>只有独立标注达到要求后才可形成 GoldLabel；分歧可显式保留。</p>
                <div className={styles.formActions}><Button disabled={!reviewer.trim() || resolve.isPending || (annotations.data?.length ?? 0) < selected.required_reviews} onClick={() => resolve.mutate(false)}>形成金标</Button><Button disabled={!reviewer.trim() || resolve.isPending || !(annotations.data?.length)} onClick={() => resolve.mutate(true)} variant="danger">保留分歧</Button></div>
              </form>
            </div>
          </> : <Empty icon={FileCheck2} title="选择 Review Item">查看冻结主体、Annotation revision 与裁决入口。</Empty>}
        </section>
      </div>
    </>
  );
}

function FailureWorkspace({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const patterns = useQuery({ queryKey: ["governance", projectId, "patterns"], queryFn: () => listFailurePatterns(projectId), refetchInterval: 10_000 });
  const signals = useQuery({ queryKey: ["governance", projectId, "signals"], queryFn: () => listFailureSignals(projectId) });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [signalId, setSignalId] = useState("");
  const [title, setTitle] = useState("");
  const [owner, setOwner] = useState("runtime-owner");
  const [actor, setActor] = useState("failure-reviewer");
  const [reason, setReason] = useState("");
  const [targetStatus, setTargetStatus] = useState("new");
  const [resolvedRunId, setResolvedRunId] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => {
    const items = patterns.data?.items ?? [];
    if (!selectedId || !items.some((item) => item.id === selectedId)) setSelectedId(items[0]?.id ?? null);
  }, [patterns.data, selectedId]);
  useEffect(() => { if (!signalId && signals.data?.items[0]) setSignalId(signals.data.items[0].id); }, [signalId, signals.data]);
  const selected = patterns.data?.items.find((item) => item.id === selectedId);
  const timeline = useQuery({ queryKey: ["governance", projectId, "pattern-timeline", selectedId], queryFn: () => listPatternTimeline(projectId, selectedId!), enabled: Boolean(selectedId) });
  const monitors = useQuery({ queryKey: ["governance", projectId, "pattern-monitors", selectedId], queryFn: () => listPatternMonitors(projectId, selectedId!), enabled: Boolean(selectedId) });
  const invalidate = async () => {
    await queryClient.invalidateQueries({ queryKey: ["governance", projectId, "patterns"] });
    await queryClient.invalidateQueries({ queryKey: ["governance", projectId, "pattern-timeline", selectedId] });
    await queryClient.invalidateQueries({ queryKey: ["governance", projectId, "pattern-monitors", selectedId] });
  };
  const createPattern = useMutation({
    mutationFn: () => projectAction<FailurePattern>(projectId, "/failure-patterns", { title: title.trim(), description: "", severity: selectedSignal(signals.data?.items, signalId)?.severity ?? "high", priority: 10, owner: owner.trim() || null, signal_ids: [signalId], matcher: {}, created_by: actor.trim() }),
    onSuccess: async (value) => { setSelectedId(value.id); setTitle(""); setNotice("Failure Pattern candidate 已创建，等待 membership review。"); await invalidate(); },
  });
  const reviewMemberships = useMutation({
    mutationFn: () => projectAction(projectId, `/failure-patterns/${encodeURIComponent(selectedId!)}/memberships:review`, { reviewer_id: actor.trim(), decisions: (selected?.memberships ?? []).filter((item) => item.status === "candidate").map((item) => ({ signal_id: item.signal_id, decision: "confirmed", explanation: "Representative evidence reviewed in the governance console." })) }),
    onSuccess: async () => { setNotice("候选 membership 已人工确认。"); await invalidate(); },
  });
  const transition = useMutation({
    mutationFn: () => projectAction(projectId, `/failure-patterns/${encodeURIComponent(selectedId!)}:transition`, { target_status: targetStatus, actor: actor.trim(), reason: reason.trim(), resolved_by_run_id: targetStatus === "resolved" ? resolvedRunId.trim() : null, ignored_until: null }),
    onSuccess: async () => { setReason(""); setNotice(`Pattern 已迁移为 ${targetStatus}。`); await invalidate(); },
  });
  const monitor = useMutation({
    mutationFn: () => projectAction(projectId, `/failure-patterns/${encodeURIComponent(selectedId!)}/monitors`, { environment: null, shadow_mode: true, webhook: null }),
    onSuccess: async () => { setNotice("复发 Monitor 已以 shadow mode 启用。"); await invalidate(); },
  });
  const critical = patterns.data?.items.filter((item) => ["critical", "high"].includes(item.severity)).length ?? 0;
  const regressed = patterns.data?.items.filter((item) => item.status === "regressed").length ?? 0;
  return <>
    <MetricStrip items={[["Failure Signals", signals.data?.total ?? "—", "原子、不可变失败事实"], ["Patterns", patterns.data?.total ?? "—", "人工确认的治理对象"], ["Critical / High", critical, "可绑定 Release Gate"], ["Regressed", regressed, "复发会链接原修复证据"]]} />
    {notice ? <Notice>{notice}</Notice> : null}
    {[patterns.error, signals.error, timeline.error, monitors.error, createPattern.error, reviewMemberships.error, transition.error, monitor.error].filter(Boolean).map((error, index) => <ErrorNotice key={index} value={error} />)}
    <div className={styles.failureGrid}>
      <Panel className={styles.signalPanel} eyebrow="原子失败事实" title="Signal Inbox"><div className={styles.signalList}>{(signals.data?.items ?? []).map((signal) => <button className={signalId === signal.id ? styles.selectedSignal : ""} key={signal.id} onClick={() => { setSignalId(signal.id); if (!title) setTitle(signal.summary.slice(0, 120)); }} type="button"><StatusBadge value={signal.severity} /><span><strong>{signal.summary}</strong><small>{signal.category} · {formatDate(signal.occurred_at)}</small></span></button>)}{!signals.isLoading && !signals.data?.items.length ? <Empty icon={Siren} title="尚无 Failure Signal">评测、人工或生产 trace detector 产生后会显示。</Empty> : null}</div><form className={styles.compactForm} onSubmit={(event) => { event.preventDefault(); createPattern.mutate(); }}><label>Pattern 标题<input onChange={(event) => setTitle(event.target.value)} value={title} /></label><label>Owner<input onChange={(event) => setOwner(event.target.value)} value={owner} /></label><Button disabled={!signalId || !title.trim() || !actor.trim() || createPattern.isPending} type="submit" variant="primary">从选中 Signal 建立候选</Button></form></Panel>
      <Panel className={styles.patternPanel} eyebrow="治理对象" title="Failure Patterns" actions={<Button icon={<RefreshCcw />} onClick={() => void patterns.refetch()} size="sm">刷新</Button>}><div className={styles.masterList}>{(patterns.data?.items ?? []).map((item) => <MasterButton active={selectedId === item.id} key={item.id} meta={`${item.category} · ${item.owner ?? "未分配"}`} onClick={() => setSelectedId(item.id)} status={item.status} title={item.title} />)}{!patterns.isLoading && !patterns.data?.items.length ? <Empty icon={GitBranch} title="尚无 Pattern">Signal 经过人工归并后成为治理对象。</Empty> : null}</div></Panel>
      <section className={styles.detailPanel}>{selected ? <><header className={styles.detailHeader}><div><span className="eyebrow">Failure Pattern</span><h2>{selected.title}</h2><code>{selected.signature}</code></div><StatusBadge value={selected.status} /></header><div className={styles.detailScroll}><div className={styles.factGrid}><Fact label="Severity" value={selected.severity} /><Fact label="Owner" value={selected.owner ?? "unassigned"} /><Fact label="Definition" value={`v${selected.definition_version}`} /><Fact label="Last seen" value={formatDate(selected.last_seen_at)} /></div><section className={styles.memberships}><header><span className="eyebrow">Membership review</span><h3>{selected.memberships.length} 条候选关联</h3></header>{selected.memberships.map((item) => <article key={item.signal_id}><code>{shortId(item.signal_id)}</code><span>{item.explanation}</span><StatusBadge value={item.status} /></article>)}<Button disabled={!selected.memberships.some((item) => item.status === "candidate") || !actor.trim() || reviewMemberships.isPending} onClick={() => reviewMemberships.mutate()} size="sm">确认全部候选关联</Button></section><section className={styles.timelineSection}><header><div><span className="eyebrow">Audit timeline</span><h3>定义、状态与复发</h3></div><Badge>{timeline.data?.length ?? 0}</Badge></header><div className={styles.patternTimeline}>{(timeline.data ?? []).map((event) => <article key={event.id}><span><i /></span><div><header><strong>{event.event_type}</strong><time>{formatDate(event.created_at)}</time></header><p>{event.actor}</p><pre>{pretty(event.details)}</pre></div></article>)}</div></section><section className={styles.actionForm}><header><div><span className="eyebrow">Human transition</span><h3>状态迁移与复发监控</h3></div><ShieldCheck size={16} /></header><label>操作人<input onChange={(event) => setActor(event.target.value)} value={actor} /></label><div className={styles.formPair}><label>目标状态<select onChange={(event) => setTargetStatus(event.target.value)} value={targetStatus}>{["new", "escalating", "ongoing", "resolved", "ignored"].map((value) => <option key={value} value={value}>{value}</option>)}</select></label>{targetStatus === "resolved" ? <label>Verified Run ID<input onChange={(event) => setResolvedRunId(event.target.value)} value={resolvedRunId} /></label> : <label>Monitor<span className={styles.readonlyField}>{monitors.data?.length ?? 0} active/history</span></label>}</div><label>理由<textarea onChange={(event) => setReason(event.target.value)} value={reason} /></label><footer><Button disabled={!reason.trim() || !actor.trim() || (targetStatus === "resolved" && !resolvedRunId.trim()) || transition.isPending} onClick={() => transition.mutate()} variant="primary">提交人工迁移</Button><Button disabled={monitor.isPending || Boolean(monitors.data?.length)} onClick={() => monitor.mutate()}>启用 shadow monitor</Button></footer></section></div></> : <Empty icon={GitBranch} title="选择 Failure Pattern">查看 membership、状态历史、修复证据和复发 Monitor。</Empty>}</section>
    </div>
  </>;
}

function JobWorkspace({ projectId }: { projectId: string }) {
  const queryClient = useQueryClient();
  const jobs = useQuery({ queryKey: ["governance", projectId, "jobs"], queryFn: () => listExecutionJobs(projectId), refetchInterval: 5_000 });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => { const items = jobs.data?.items ?? []; if (!selectedId || !items.some((item) => item.id === selectedId)) setSelectedId(items[0]?.id ?? null); }, [jobs.data, selectedId]);
  const selected = jobs.data?.items.find((item) => item.id === selectedId);
  const attempts = useQuery({ queryKey: ["governance", projectId, "attempts", selectedId], queryFn: () => listExecutionAttempts(projectId, selectedId!), enabled: Boolean(selectedId), refetchInterval: selected && ["leased", "running"].includes(selected.status) ? 3_000 : false });
  const cancel = useMutation({ mutationFn: () => projectAction<ExecutionJob>(projectId, `/execution-jobs/${encodeURIComponent(selectedId!)}:cancel`), onSuccess: async () => { setNotice("取消请求已持久化；Worker 会在安全边界停止。"); await queryClient.invalidateQueries({ queryKey: ["governance", projectId, "jobs"] }); } });
  const active = jobs.data?.items.filter((item) => ["queued", "leased", "running"].includes(item.status)).length ?? 0;
  const dead = jobs.data?.items.filter((item) => item.status === "dead").length ?? 0;
  const sideEffects = jobs.data?.items.filter((item) => item.external_side_effect).length ?? 0;
  return <>
    <MetricStrip items={[["Durable Jobs", jobs.data?.total ?? "—", "数据库是权威队列"], ["Active", active, "queued / leased / running"], ["Dead", dead, "不会静默重复副作用"], ["External Side Effect", sideEffects, "过期租约进入人工处置"]]} />
    {notice ? <Notice>{notice}</Notice> : null}
    {[jobs.error, attempts.error, cancel.error].filter(Boolean).map((error, index) => <ErrorNotice key={index} value={error} />)}
    <div className={styles.workbench}><Panel className={styles.masterPanel} eyebrow="Lease-protected queue" title="Execution Jobs" actions={<Button icon={<RefreshCcw />} onClick={() => void jobs.refetch()} size="sm">刷新</Button>}><div className={styles.masterList}>{(jobs.data?.items ?? []).map((job) => <MasterButton active={selectedId === job.id} key={job.id} meta={`Run ${shortId(job.run_id)} · attempt ${job.attempt}/${job.max_attempts}`} onClick={() => setSelectedId(job.id)} status={job.status} title={shortId(job.case_run_id)} />)}{!jobs.isLoading && !jobs.data?.items.length ? <Empty icon={Clock3} title="没有 Durable Job">启用 durable scheduler 后，新 CaseRun 会入数据库队列。</Empty> : null}</div></Panel><section className={styles.detailPanel}>{selected ? <><header className={styles.detailHeader}><div><span className="eyebrow">Execution Job</span><h2>{shortId(selected.case_run_id)}</h2><code>{selected.id}</code></div><StatusBadge value={selected.status} /></header><div className={styles.detailScroll}><div className={styles.factGrid}><Fact label="Run" value={selected.run_id} /><Fact label="Priority" value={String(selected.priority)} /><Fact label="Lease owner" value={selected.lease_owner ?? "none"} /><Fact label="Lease expires" value={selected.lease_expires_at ? formatDate(selected.lease_expires_at) : "none"} /></div>{selected.external_side_effect ? <Notice tone="warning">该 Job 已记录外部副作用；租约过期时不会自动重放。</Notice> : null}<section className={styles.attemptList}><header><span className="eyebrow">Append-only attempts</span><h3>{attempts.data?.length ?? 0} 次执行尝试</h3></header>{(attempts.data ?? []).map((attempt) => <article key={attempt.id}><span>{String(attempt.attempt).padStart(2, "0")}</span><div><header><strong>{attempt.lease_owner}</strong><StatusBadge value={attempt.status} /></header><p>{formatDate(attempt.started_at)} → {attempt.finished_at ? formatDate(attempt.finished_at) : "运行中"}</p><small>{attempt.error_code ?? "no error"}{attempt.external_side_effect ? " · external side effect" : ""}</small></div></article>)}</section><footer className={styles.detailActions}><p>Cancel 写入持久状态；不会删除 Job 或历史 Attempt。</p><Button disabled={!['queued', 'leased', 'running'].includes(selected.status) || cancel.isPending} onClick={() => cancel.mutate()} variant="danger">请求取消</Button></footer></div></> : <Empty icon={Clock3} title="选择 Durable Job">查看租约、attempt、取消请求和副作用保护。</Empty>}</section></div>
  </>;
}

function Panel({ title, eyebrow, actions, children, className = "" }: { title: string; eyebrow: string; actions?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`${styles.panel} ${className}`}><header><div><span className="eyebrow">{eyebrow}</span><h2>{title}</h2></div>{actions ? <div>{actions}</div> : null}</header>{children}</section>;
}

function MetricStrip({ items }: { items: Array<[string, ReactNode, string]> }) {
  return <div className={styles.metricStrip}>{items.map(([label, value, meta]) => <div key={label}><span>{label}</span><strong>{value}</strong><small>{meta}</small></div>)}</div>;
}

function MasterButton({ active, title, meta, status, onClick }: { active: boolean; title: string; meta: string; status: string; onClick: () => void }) {
  return <button className={active ? styles.activeMaster : ""} onClick={onClick} type="button"><span><strong>{title}</strong><small>{meta}</small></span><StatusBadge value={status} /><ChevronRight size={13} /></button>;
}

function SpanEvent({ span, index }: { span: ProductionSpan; index: number }) {
  const payload = { model_call: span.model_call, tool_call: span.tool_call, tool_result: span.tool_result, permission: span.permission, memory_operation: span.memory_operation, artifact_refs: span.artifact_refs, attributes: span.attributes, events: span.events };
  return <details><summary><span>{String(index + 1).padStart(2, "0")}</span><div><strong>{span.name}</strong><small>{span.span_kind} · {span.agent_path.join(" / ") || "root"}</small></div><StatusBadge value={span.status} /><ChevronRight size={13} /></summary><div><EvidenceHashes values={[["Span", span.content_hash], ["External ID", span.external_span_id]]} /><pre>{pretty(payload)}</pre></div></details>;
}

function EvidenceHashes({ values }: { values: Array<[string, string]> }) {
  return <div className={styles.hashList}>{values.map(([label, value]) => <div key={label}><span>{label}</span><code>{value}</code></div>)}</div>;
}

function Fact({ label, value }: { label: string; value: string }) {
  return <div><span>{label}</span><strong title={value}>{value}</strong></div>;
}

function Empty({ icon: Icon, title, children }: { icon: LucideIcon; title: string; children: ReactNode }) {
  return <div className={styles.empty}><Icon size={21} /><strong>{title}</strong><p>{children}</p></div>;
}

function ErrorNotice({ value }: { value: unknown }) {
  return <Notice tone="danger"><CircleAlert size={14} />{errorMessage(value)}</Notice>;
}

function Notice({ children, tone = "success" }: { children: ReactNode; tone?: "success" | "warning" | "danger" }) {
  return <div className={styles.notice} data-tone={tone}>{tone === "success" ? <CheckCircle2 size={14} /> : <CircleAlert size={14} />}<span>{children}</span></div>;
}

function StatusBadge({ value }: { value: string }) {
  return <Badge tone={statusTone(value)}>{value.replaceAll("_", " ")}</Badge>;
}

function selectedSignal(items: FailureSignal[] | undefined, id: string): FailureSignal | undefined {
  return items?.find((item) => item.id === id);
}

function sectionTitle(section: GovernanceSection): string {
  return { production: "生产证据", reviews: "人工审核与 Judge 对齐", failures: "Failure Pattern 与复发监控", jobs: "耐久执行" }[section];
}

function sectionDescription(section: GovernanceSection): string {
  return {
    production: "受控接入 OTLP 事实，审阅脱敏 Trace，并通过不可变 lineage 创建回归草稿。",
    reviews: "CaseRun 与 Production 事实进入同一队列；Annotation 追加式、GoldLabel 需要独立审核。",
    failures: "Signal 保持原子，Pattern 经过人工确认后绑定回归证据、发布门禁与复发 Monitor。",
    jobs: "数据库租约、心跳与 append-only Attempt 让重启恢复不依赖进程内任务。",
  }[section];
}

function subjectLabel(value: ReviewItem["subject_kind"]): string {
  return { case_run: "CaseRun", production_trace: "Production Trace", production_span: "Production Span" }[value];
}

function statusTone(value: string): "neutral" | "accent" | "success" | "warning" | "danger" {
  if (["completed", "passed", "pass", "resolved", "approved", "active", "healthy", "confirmed"].includes(value)) return "success";
  if (["failed", "fail", "blocked", "critical", "dead", "regressed", "rejected", "evaluation_error"].includes(value)) return "danger";
  if (["queued", "running", "leased", "in_review", "adjudication", "high", "candidate", "inconclusive"].includes(value)) return "warning";
  if (["open", "new", "ongoing", "escalating"].includes(value)) return "accent";
  return "neutral";
}

function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function shortId(value: string): string {
  return value.length > 24 ? `${value.slice(0, 12)}…${value.slice(-7)}` : value;
}

function formatDate(value: string): string {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : date.toLocaleString("zh-CN", { hour12: false });
}

function errorMessage(value: unknown): string {
  if (value instanceof Error) return value.message;
  return typeof value === "string" ? value : "请求失败，请检查 Project 权限与服务状态。";
}
