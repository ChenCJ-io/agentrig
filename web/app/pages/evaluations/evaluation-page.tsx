import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowLeft,
  CheckCircle2,
  ChevronRight,
  CircleDashed,
  Clock3,
  FileText,
  FlaskConical,
  Gavel,
  Layers3,
  RefreshCw,
  RotateCcw,
  Square,
  XCircle,
} from "lucide-react";
import { useMemo, useState, type FormEvent } from "react";
import { Link, useLocation, useNavigate } from "react-router";

import { toEvaluationCell, toPlanPreview, toRunListItem } from "~/adapters/evaluation-adapter";
import {
  cancelRun,
  evaluateReleaseGate,
  getDefaultReleasePolicy,
  getOne,
  getQualityReport,
  getRunReport,
  getRunCell,
  getRunSummary,
  getPage,
  listRunCells,
  previewRunCases,
  retryRunCells,
  submitRunCases,
  type ExecutionProfile,
  type Page,
  type Run,
  type RunCell,
  type Target,
  type TestCase,
} from "~/api/v1";
import { ErrorState, LoadingState, PartialDataNotice } from "~/components/states/query-state";
import { Badge } from "~/components/ui/badge";
import { Button } from "~/components/ui/button";
import { CopyableId } from "~/components/ui/copyable-id";
import { PageHeader } from "~/components/ui/page-header";
import { Panel } from "~/components/ui/panel";
import type { UiStatus } from "~/view-models/evaluation";

import styles from "./evaluation-page.module.css";

type EvaluationRoute =
  | { page: "runs" }
  | { page: "run"; runId: string }
  | { page: "cell"; runId: string; cellId: string }
  | { page: "report"; runId: string }
  | { page: "wizard"; step: "info" | "scope" | "review" }
  | { page: "fallback" };

export function EvaluationPage({ targetId }: { targetId: string }) {
  const { pathname } = useLocation();
  const route = matchRoute(pathname, targetId);
  if (route.page === "wizard") return <RunWizardPage targetId={targetId} step={route.step} />;
  if (route.page === "run") return <RunDetailPage targetId={targetId} runId={route.runId} />;
  if (route.page === "cell") return <CellDetailPage targetId={targetId} runId={route.runId} cellId={route.cellId} />;
  if (route.page === "report") return <RunReportPage targetId={targetId} runId={route.runId} />;
  return <RunListPage targetId={targetId} />;
}

interface WizardDraft {
  goal: string;
  caseIds: string[];
  profileId: string;
  repeatCount: number;
}

function RunWizardPage({ targetId, step }: { targetId: string; step: "info" | "scope" | "review" }) {
  const navigate = useNavigate();
  const target = useTarget(targetId);
  const cases = useQuery({
    queryKey: ["test-cases", "wizard"],
    queryFn: () => getPage<TestCase>("/api/test-cases?limit=200"),
  });
  const profiles = useQuery({
    queryKey: ["profiles", "wizard"],
    queryFn: () => getPage<ExecutionProfile>("/api/execution-profiles?limit=200"),
  });
  const [draft, setDraft] = useState<WizardDraft>(() => readWizardDraft(targetId));
  const [notice, setNotice] = useState<string | null>(null);
  const request = useMemo(() => ({
    case_ids: draft.caseIds,
    targets: [{ role: "candidate" as const, target_id: targetId }],
    profile_id: draft.profileId || undefined,
    repeat_count: draft.repeatCount,
  }), [draft.caseIds, draft.profileId, draft.repeatCount, targetId]);
  const preview = useQuery({
    queryKey: ["run-preview", targetId, request],
    queryFn: () => previewRunCases(request),
    enabled: step === "review" && draft.caseIds.length > 0,
  });
  const submit = useMutation({
    mutationFn: () => submitRunCases({
      ...request,
      expected_manifest_hash: preview.data!.manifest_hash,
    }),
    onSuccess: (result) => {
      window.sessionStorage.removeItem(wizardKey(targetId));
      navigate(`/targets/${encodeURIComponent(targetId)}/evaluation/runs/${encodeURIComponent(result.run_id)}`);
    },
    onError: (error) => setNotice(message(error)),
  });
  const previewVm = preview.data ? toPlanPreview(preview.data, target.data) : null;

  function update(next: WizardDraft) {
    setDraft(next);
    window.sessionStorage.setItem(wizardKey(targetId), JSON.stringify(next));
  }

  function nextFromInfo(event: FormEvent) {
    event.preventDefault();
    if (!draft.goal.trim()) return;
    navigate(wizardPath(targetId, "scope"));
  }

  function nextFromScope(event: FormEvent) {
    event.preventDefault();
    if (!draft.caseIds.length) {
      setNotice("至少选择一个测试用例。当前不会自动扩大评测范围。");
      return;
    }
    navigate(wizardPath(targetId, "review"));
  }

  return (
    <div className={styles.page}>
      <Link className={styles.backLink} to={`/targets/${encodeURIComponent(targetId)}/evaluation/runs`}><ArrowLeft size={13} /> 退出新建评测</Link>
      <PageHeader
        eyebrow="New Evaluation Run"
        title="新建评测"
        description="先明确目标，再选择真实资产，最后确认展开后的 Manifest。"
      />
      <nav className={styles.wizardSteps} aria-label="新建评测步骤">
        {(["info", "scope", "review"] as const).map((value, index) => (
          <Link aria-current={step === value ? "step" : undefined} data-active={step === value} key={value} to={wizardPath(targetId, value)}>
            <em>{index + 1}</em><span><strong>{["目标", "范围", "确认"][index]}</strong><small>{["说明要验证什么", "选择 Case 与配置", "核对 Cell 与副作用"][index]}</small></span>
          </Link>
        ))}
      </nav>
      {notice ? <PartialDataNotice>{notice}</PartialDataNotice> : null}
      {step === "info" ? (
        <Panel eyebrow="Step 1 · Info" title="评测目标与 Target">
          <form className={styles.wizardForm} onSubmit={nextFromInfo}>
            <label><span>当前被测 Agent</span><div className={styles.selectedAsset}><FlaskConical size={15} /><strong>{target.data?.name ?? targetId}</strong><small>{target.data?.driver_type ?? "正在读取"}</small></div></label>
            <label><span>这次希望验证什么</span><textarea autoFocus onChange={(event) => update({ ...draft, goal: event.target.value })} placeholder="例如：验证图片编辑 Agent 在需要二次确认时不会提前执行工具，并保留失败证据。" rows={5} value={draft.goal} /><small>目标只用于帮助用户核对范围，不会作为隐藏评判标准注入被测 Agent。</small></label>
            <footer><span /><Button disabled={!draft.goal.trim()} type="submit" variant="primary">下一步：选择范围 <ChevronRight size={13} /></Button></footer>
          </form>
        </Panel>
      ) : null}
      {step === "scope" ? (
        <Panel eyebrow="Step 2 · Scope" title="测试用例与执行配置">
          <form className={styles.wizardForm} onSubmit={nextFromScope}>
            <fieldset><legend>测试用例</legend>{cases.isPending ? <LoadingState title="正在读取测试用例" /> : <div className={styles.assetChoices}>{(cases.data?.items ?? []).map((item) => <label key={item.id} data-selected={draft.caseIds.includes(item.id)}><input checked={draft.caseIds.includes(item.id)} onChange={(event) => update({ ...draft, caseIds: event.target.checked ? [...draft.caseIds, item.id] : draft.caseIds.filter((id) => id !== item.id) })} type="checkbox" /><span><strong>{item.name}</strong><small>{item.id} · {item.review_status === "approved" ? "已批准" : item.review_status}</small></span></label>)}</div>}</fieldset>
            <div className={styles.scopeGrid}><label><span>执行配置</span><select onChange={(event) => update({ ...draft, profileId: event.target.value })} value={draft.profileId}><option value="">使用部署默认配置</option>{profiles.data?.items.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><label><span>每个 Cell 的 Attempt 数</span><input max={20} min={1} onChange={(event) => update({ ...draft, repeatCount: Math.max(1, Number(event.target.value) || 1) })} type="number" value={draft.repeatCount} /></label></div>
            <footer><Link className="button button--secondary button--md" to={wizardPath(targetId, "info")}>上一步</Link><Button disabled={!draft.caseIds.length} type="submit" variant="primary">下一步：预览 Manifest <ChevronRight size={13} /></Button></footer>
          </form>
        </Panel>
      ) : null}
      {step === "review" ? (
        <Panel eyebrow="Step 3 · Review" title="确认真实执行边界">
          {preview.isPending ? <LoadingState title="正在展开 Canonical Manifest" description="此操作不会创建 Run，也不会调用被测 Agent。" /> : null}
          {preview.error ? <ErrorState description={message(preview.error)} onRetry={() => void preview.refetch()} /> : null}
          {previewVm ? <div className={styles.review}><section className={styles.reviewMetrics}><SummaryMetric label="Cell" value={previewVm.cellCount} icon={<Layers3 />} /><SummaryMetric label="Attempt" value={previewVm.attemptCount} icon={<Activity />} /><SummaryMetric label="跳过" value={previewVm.skippedCount} icon={<AlertTriangle />} tone={previewVm.skippedCount ? "danger" : undefined} /></section><dl><div><dt>评测目标</dt><dd>{draft.goal}</dd></div><div><dt>结果提供链</dt><dd>{previewVm.providers.join(" → ") || "部署默认"}</dd></div><div><dt>评判器</dt><dd>{previewVm.evaluators.join(", ") || "部署默认"}</dd></div><div><dt>Manifest Hash</dt><dd><CopyableId label="Manifest Hash" value={previewVm.manifestHash} /></dd></div></dl>{previewVm.rejected.length ? <PartialDataNotice>{previewVm.rejected.map((item) => `${item.id}: ${item.reason}`).join("；")}</PartialDataNotice> : null}<div className={styles.manifestCells}>{preview.data?.manifest.cells.map((cell) => <article key={cell.cell_key}><span><strong>{cell.case_id}</strong><small>{cell.target_role} · {cell.version ?? "默认版本"}</small></span><Badge tone={cell.disposition === "run" ? "success" : "warning"}>{cell.disposition === "run" ? `${cell.attempts.length} Attempts` : "跳过"}</Badge></article>)}</div><footer><Link className="button button--secondary button--md" to={wizardPath(targetId, "scope")}>返回修改</Link><Button disabled={submit.isPending} icon={<FlaskConical />} onClick={() => submit.mutate()} variant="primary">{submit.isPending ? "正在提交" : "确认 Manifest 并运行"}</Button></footer></div> : null}
        </Panel>
      ) : null}
    </div>
  );
}

function RunListPage({ targetId }: { targetId: string }) {
  const target = useTarget(targetId);
  const runs = useQuery({
    queryKey: ["runs", "default", targetId],
    queryFn: () => getPage<Run>(`/api/runs?target_id=${encodeURIComponent(targetId)}&limit=200`),
    refetchInterval: 5_000,
  });
  const items = useMemo(
    () => (runs.data?.items ?? []).map((run) => toRunListItem(run, target.data)),
    [runs.data, target.data],
  );
  const active = items.filter((item) => ["queued", "running"].includes(item.status)).length;
  const failed = items.filter((item) => ["failed", "partial"].includes(item.status)).length;

  return (
    <div className={styles.page}>
      <PageHeader
        eyebrow="Evaluation · Run Registry"
        title="评测运行"
        description="一个 Run 固化一份 Manifest；Cell 表示评测组合，Attempt 表示独立重复执行。"
        actions={<div className={styles.headerActions}><Link className="button button--secondary button--md" to={`/targets/${encodeURIComponent(targetId)}/assistant`}>用评测助手发起</Link><Link className="button button--primary button--md" to={wizardPath(targetId, "info")}>新建评测</Link></div>}
      />
      <section className={styles.summaryBand}>
        <SummaryMetric label="运行总数" value={runs.data?.total ?? "—"} icon={<Layers3 />} />
        <SummaryMetric label="执行中" value={active} icon={<Activity />} tone="accent" />
        <SummaryMetric label="需关注" value={failed} icon={<AlertTriangle />} tone="danger" />
        <SummaryMetric label="当前 Target" value={target.data?.name ?? targetId} icon={<FlaskConical />} compact />
      </section>
      <Panel
        eyebrow="真实运行数据"
        title="最近 Run"
        actions={<Button icon={<RefreshCw />} onClick={() => void runs.refetch()} size="sm">刷新</Button>}
      >
        {runs.isPending ? <LoadingState title="正在读取评测运行" /> : null}
        {runs.error ? <ErrorState description={message(runs.error)} onRetry={() => void runs.refetch()} /> : null}
        {runs.data && !items.length ? (
          <div className={styles.emptyRun}>
            <CircleDashed size={24} />
            <strong>这个 Target 还没有评测运行</strong>
            <p>可以在智能评测助手中用自然语言生成计划，确认后执行。</p>
          </div>
        ) : null}
        {items.length ? (
          <div className={styles.runTable} role="table" aria-label="评测运行">
            <div className={styles.runTableHeader} role="row">
              <span>Run / 创建时间</span><span>状态</span><span>进度</span><span>Cell / Attempt</span><span>失败</span><span />
            </div>
            {items.map((item) => (
              <Link className={styles.runRow} key={item.id} role="row" to={`/targets/${encodeURIComponent(targetId)}/evaluation/runs/${encodeURIComponent(item.id)}`}>
                <span><strong>{item.shortId}</strong><small>{item.createdAt}</small>{item.recoveryOfRunId ? <em>Recovery</em> : null}</span>
                <span><StatusBadge status={item.status} /></span>
                <span><Progress value={item.progress.percent} /><small>{item.progress.completed} / {item.progress.total}</small></span>
                <span><strong>{item.cellCount}</strong><small>{item.attemptCount} Attempts</small></span>
                <span><strong data-danger={item.failedCount > 0}>{item.failedCount}</strong></span>
                <ChevronRight size={14} />
              </Link>
            ))}
          </div>
        ) : null}
      </Panel>
    </div>
  );
}

function RunDetailPage({ targetId, runId }: { targetId: string; runId: string }) {
  const queryClient = useQueryClient();
  const run = useQuery({
    queryKey: ["run", "default", targetId, runId],
    queryFn: () => getOne<Run>(`/api/runs/${encodeURIComponent(runId)}`),
    refetchInterval: (query) => terminal(query.state.data?.status) ? false : 2_000,
  });
  const summary = useQuery({
    queryKey: ["run-summary", "default", targetId, runId],
    queryFn: () => getRunSummary(runId),
    refetchInterval: (query) => query.state.data?.terminal ? false : 2_000,
  });
  const cells = useQuery({
    queryKey: ["run-cells", "default", targetId, runId],
    queryFn: () => listRunCells(runId),
    refetchInterval: summary.data?.terminal ? false : 2_000,
  });
  const stop = useMutation({
    mutationFn: () => cancelRun(runId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ["run"] });
      await queryClient.invalidateQueries({ queryKey: ["run-summary"] });
    },
  });
  const progress = summary.data?.attempt_count
    ? Math.round((summary.data.finished_attempt_count / summary.data.attempt_count) * 100)
    : 0;

  if (run.isPending) return <div className={styles.page}><LoadingState title="正在读取 Run" /></div>;
  if (run.error || !run.data) return <div className={styles.page}><ErrorState description={message(run.error)} onRetry={() => void run.refetch()} /></div>;

  return (
    <div className={styles.page}>
      <Link className={styles.backLink} to={`/targets/${encodeURIComponent(targetId)}/evaluation/runs`}><ArrowLeft size={13} /> 返回运行记录</Link>
      <PageHeader
        eyebrow={run.data.recovery_of_run_id ? "Recovery Run" : "Evaluation Run"}
        title={`运行 ${runId.slice(0, 18)}`}
        description="主视图只展示 Cell 摘要；每个 Attempt 的消息、工具调用和评判证据在 Cell 详情中查看。"
        actions={<div className={styles.headerActions}>{terminal(run.data.status) ? <Link className="button button--primary button--md" to={`/targets/${encodeURIComponent(targetId)}/evaluation/runs/${encodeURIComponent(runId)}/report`}>查看验收报告</Link> : <Button icon={<Square />} onClick={() => stop.mutate()} variant="danger">取消运行</Button>}</div>}
      />
      {run.data.recovery_of_run_id ? (
        <PartialDataNotice>这是 Recovery Run，来源 <Link to={`/targets/${encodeURIComponent(targetId)}/evaluation/runs/${encodeURIComponent(run.data.recovery_of_run_id)}`}>{run.data.recovery_of_run_id}</Link>；原始证据未被覆盖。</PartialDataNotice>
      ) : null}
      <section className={styles.runHero}>
        <div><small>运行状态</small><StatusBadge status={toRunListItem(run.data).status} /><CopyableId label="Run ID" value={run.data.id} /></div>
        <div className={styles.heroProgress}><span><strong>{progress}%</strong><small>{summary.data?.finished_attempt_count ?? 0} / {summary.data?.attempt_count ?? run.data.attempt_count} Attempts</small></span><Progress value={progress} /></div>
        <div><small>Manifest</small>{run.data.manifest_hash ? <CopyableId label="Manifest Hash" value={run.data.manifest_hash} /> : <strong>旧 Run 不可用</strong>}</div>
        <div><small>Cell / Attempt</small><strong>{run.data.cell_count} / {run.data.attempt_count}</strong></div>
      </section>
      {summary.error || cells.error ? <PartialDataNotice>部分增量数据暂时不可用：{message(summary.error ?? cells.error)}</PartialDataNotice> : null}
      <Panel eyebrow="Cell Matrix" title="评测组合与结论">
        {cells.isPending ? <LoadingState title="正在读取 Cell" /> : null}
        <div className={styles.cellGrid}>
          {(cells.data?.items ?? []).map((raw) => {
            const cell = toEvaluationCell(raw);
            return (
              <Link className={styles.cellCard} key={cell.id} to={`/targets/${encodeURIComponent(targetId)}/evaluation/runs/${encodeURIComponent(runId)}/cells/${encodeURIComponent(cell.id)}`}>
                <header><span><strong>{cell.caseIdentity.label}</strong><small>{cell.targetIdentity.label} · {cell.targetIdentity.version ?? "默认版本"}</small></span><StatusBadge status={cell.verdict} /></header>
                <dl><div><dt>Attempt</dt><dd>{cell.finishedAttemptCount}/{cell.attemptCount}</dd></div><div><dt>执行</dt><dd>{statusLabel(cell.status)}</dd></div><div><dt>失败分类</dt><dd>{failureLabel(cell.failureClass)}</dd></div></dl>
                <footer><CopyableId label="Cell ID" value={cell.id} /><ChevronRight size={14} /></footer>
              </Link>
            );
          })}
        </div>
      </Panel>
    </div>
  );
}

function CellDetailPage({ targetId, runId, cellId }: { targetId: string; runId: string; cellId: string }) {
  const navigate = useNavigate();
  const [notice, setNotice] = useState<string | null>(null);
  const cell = useQuery({
    queryKey: ["cell", "default", targetId, runId, cellId],
    queryFn: () => getRunCell(runId, cellId),
  });
  const retry = useMutation({
    mutationFn: () => retryRunCells(runId, {
      cell_ids: [cellId],
      reason: "从 Cell 证据页人工发起恢复",
    }),
    onSuccess: (result) => navigate(`/targets/${encodeURIComponent(targetId)}/evaluation/runs/${encodeURIComponent(result.run_id)}`),
    onError: (error) => setNotice(message(error)),
  });
  if (cell.isPending) return <div className={styles.page}><LoadingState title="正在读取 Cell 证据" /></div>;
  if (cell.error || !cell.data) return <div className={styles.page}><ErrorState description={message(cell.error)} onRetry={() => void cell.refetch()} /></div>;
  const view = toEvaluationCell(cell.data);
  const canRetry = retryableFailure(cell.data.failure_class);
  const capability = [...(cell.data.attempt_details ?? []), ...cell.data.attempts]
    .find((attempt) => attempt.capability_snapshot)?.capability_snapshot;
  const enabledFeatureCount = capability
    ? Object.values(capability.features).filter((feature) => feature.value === true).length
    : 0;

  return (
    <div className={styles.page}>
      <Link className={styles.backLink} to={`/targets/${encodeURIComponent(targetId)}/evaluation/runs/${encodeURIComponent(runId)}`}><ArrowLeft size={13} /> 返回 Run</Link>
      <PageHeader
        eyebrow="Cell · Attempt Evidence"
        title={view.caseIdentity.label}
        description={`${view.targetIdentity.label} · ${view.targetIdentity.version ?? "默认版本"} · ${view.attemptCount} 个独立 Attempt`}
        actions={canRetry ? <Button disabled={retry.isPending} icon={<RotateCcw />} onClick={() => retry.mutate()}>{retry.isPending ? "正在创建恢复" : "重跑此 Cell"}</Button> : undefined}
      />
      {notice ? <PartialDataNotice>{notice}</PartialDataNotice> : null}
      <section className={styles.cellHero}>
        <div><small>Cell 结论</small><StatusBadge status={view.verdict} /></div>
        <div><small>失败分类</small><strong>{failureLabel(view.failureClass)}</strong></div>
        <div><small>完成 Attempt</small><strong>{view.finishedAttemptCount} / {view.attemptCount}</strong></div>
        <div><small>Cell ID</small><CopyableId value={view.id} /></div>
      </section>
      <Panel eyebrow="Capability Snapshot" title="运行环境快照">
        {capability ? (
          <>
            <dl className={styles.qualityGrid}>
              <div><dt>采集状态</dt><dd>{capabilityStatusLabel(capability.collection_status)}</dd></div>
              <div><dt>Runtime / 协议</dt><dd>{snapshotValue(capability.runtime.framework)} / {snapshotValue(capability.runtime.protocol)}</dd></div>
              <div><dt>工具权限模式</dt><dd>{snapshotValue(capability.permissions?.mode)}</dd></div>
              <div><dt>已声明能力</dt><dd>{enabledFeatureCount}</dd></div>
              <div><dt>缺失字段</dt><dd>{capability.missing_fields.length}</dd></div>
              <div><dt>Snapshot Hash</dt><dd><CopyableId label="Capability Snapshot Hash" value={capability.snapshot_hash} /></dd></div>
            </dl>
            {capability.limitations.length ? <PartialDataNotice>能力快照限制：{capability.limitations.join("；")}</PartialDataNotice> : null}
          </>
        ) : <PartialDataNotice>该 Attempt 没有能力快照；不能据此判断 Runtime、工具或权限环境是否漂移。</PartialDataNotice>}
      </Panel>
      <Panel eyebrow="Evidence Timeline" title="执行与评判证据">
        <div className={styles.attemptRail}>
          {view.attempts.map((attempt) => <span key={attempt.id}><em>{attempt.repeatIndex}</em><StatusBadge status={attempt.verdict} /><CopyableId value={attempt.id} label="Attempt ID" /></span>)}
        </div>
        <div className={styles.timeline}>
          {view.timeline.map((item) => (
            <article className={styles.timelineItem} data-kind={item.kind} key={item.id}>
              <span className={styles.timelineIcon}>{timelineIcon(item.kind)}</span>
              <div>
                <header><span><strong>{item.title}</strong><small>{item.actor} · Attempt {item.attemptIndex}</small></span><time>{item.occurredAt}</time></header>
                {item.summary ? <p>{item.summary}</p> : null}
                <details><summary>查看原始证据</summary><pre>{JSON.stringify(item.payload, null, 2)}</pre><footer>{item.evidenceRefs.map((ref) => <CopyableId key={ref} label="Evidence ID" value={ref} />)}</footer></details>
              </div>
            </article>
          ))}
          {!view.timeline.length ? <div className={styles.emptyRun}>当前 Cell 没有可显示的 Timeline 事件。</div> : null}
        </div>
      </Panel>
    </div>
  );
}

function RunReportPage({ targetId, runId }: { targetId: string; runId: string }) {
  const report = useQuery({
    queryKey: ["run-report", runId],
    queryFn: () => getRunReport(runId),
  });
  const quality = useQuery({
    queryKey: ["quality-report", runId],
    queryFn: () => getQualityReport(runId),
  });
  const cells = useQuery({
    queryKey: ["run-cells", "report", runId],
    queryFn: () => listRunCells(runId),
  });
  const policy = useQuery({
    queryKey: ["release-policy", "default"],
    queryFn: getDefaultReleasePolicy,
  });
  const gate = useQuery({
    queryKey: ["release-gate", runId, policy.data?.policy_version],
    queryFn: () => evaluateReleaseGate(runId, policy.data!),
    enabled: Boolean(policy.data && report.data && report.data.targets.length > 1),
  });
  const attemptToCell = useMemo(() => {
    const result = new Map<string, string>();
    for (const item of cells.data?.items ?? []) {
      for (const attempt of item.attempts) result.set(attempt.id, item.cell_id);
    }
    return result;
  }, [cells.data]);

  if (report.isPending) {
    return <div className={styles.page}><LoadingState title="正在生成验收报告" /></div>;
  }
  if (report.error || !report.data) {
    return <div className={styles.page}><ErrorState description={message(report.error)} onRetry={() => void report.refetch()} /></div>;
  }
  const data = report.data;
  const comparisonRun = data.targets.length > 1;
  const directVerdict = directRunVerdict(data);
  const verdict = comparisonRun ? (gate.data?.verdict ?? "inconclusive") : directVerdict;

  return (
    <div className={styles.page}>
      <Link className={styles.backLink} to={`/targets/${encodeURIComponent(targetId)}/evaluation/runs/${encodeURIComponent(runId)}`}><ArrowLeft size={13} /> 返回 Run 证据</Link>
      <PageHeader
        eyebrow="Acceptance Report"
        title="评测验收结论"
        description="报告使用真实评判证据；执行终态不等同于业务通过，Recovery 也不会覆盖原始 Attempt。"
        actions={<CopyableId label="Run ID" value={runId} />}
      />
      {data.recovery ? (
        <PartialDataNotice>本报告以 <strong>{data.recovery.source_run_id}</strong> 为原始 Run，并应用 {data.recovery.applied_recovery_run_ids.length} 个 Recovery Run；替换 {data.recovery.replaced_attempt_count} 个失败 Attempt，原始证据仍可追溯。</PartialDataNotice>
      ) : null}
      {quality.error || (comparisonRun && gate.error) ? <PartialDataNotice>部分质量或发布门禁数据暂时不可用：{message(quality.error ?? gate.error)}</PartialDataNotice> : null}
      <section className={styles.reportHero}>
        <article data-verdict={verdict}>
          <span><Gavel size={18} /></span>
          <div><small>验收结论</small><strong>{gateVerdictLabel(verdict)}</strong><em>{comparisonRun ? (gate.data ? `${gate.data.policy_name} · ${gate.data.policy_version}` : "正在执行默认 A/B 发布门禁") : "单目标 Run · 业务评判与证据完整性"}</em></div>
        </article>
        <SummaryMetric label="业务通过" value={data.outcomes.pass_count} icon={<CheckCircle2 />} tone="success" />
        <SummaryMetric label="业务失败" value={data.outcomes.fail_count} icon={<XCircle />} tone="danger" />
        <SummaryMetric label="证据不足/待判定" value={data.outcomes.inconclusive_count + data.outcomes.awaiting_verdict_count} icon={<AlertTriangle />} tone="warning" />
      </section>
      <div className={styles.reportColumns}>
        <Panel eyebrow="Release Gate" title="质量门禁检查">
          <div className={styles.gateChecks}>
            {comparisonRun ? (gate.data?.checks ?? []).map((check) => (
              <article data-outcome={check.outcome} key={check.name}>
                <span>{check.outcome === "pass" ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}</span>
                <div><strong>{check.name}</strong><p>{check.message}</p><small>实际 {check.actual ?? "不可用"} · 阈值 {check.operator} {check.threshold}</small></div>
              </article>
            )) : (
              <article data-outcome="pass">
                <span><CheckCircle2 size={14} /></span>
                <div><strong>单目标 Run 无需 A/B 发布门禁</strong><p>本次验收结论直接来自业务评判结果；A/B 回归 Run 才执行基线差异门禁。</p><small>没有额外调用被测 Agent，也没有新增资源消耗</small></div>
              </article>
            )}
            {comparisonRun && gate.isPending ? <LoadingState title="正在执行质量门禁" /> : null}
          </div>
        </Panel>
        <Panel eyebrow="Evidence Quality" title="证据与可靠性">
          {quality.data ? (
            <dl className={styles.qualityGrid}>
              <div><dt>证据引用有效率</dt><dd>{percent(quality.data.evidence_quality.reference_validity_rate)}</dd></div>
              <div><dt>Recovery 成功率</dt><dd>{percent(quality.data.reliability.recovery_success_rate)}</dd></div>
              <div><dt>Provider 错误</dt><dd>{quality.data.reliability.provider_error_count}</dd></div>
              <div><dt>P95 用例耗时</dt><dd>{duration(quality.data.latency.case_run.p95_ms)}</dd></div>
              <div><dt>总 Token</dt><dd>{quality.data.usage.total_tokens ?? "不可用"}</dd></div>
              <div><dt>脱敏状态</dt><dd>{quality.data.evidence_quality.redaction_status === "applied" ? "已应用" : "未知"}</dd></div>
            </dl>
          ) : <LoadingState title="正在汇总质量证据" />}
        </Panel>
      </div>
      <Panel eyebrow="Failure Analysis" title="失败与证据入口">
        {data.failures.length ? (
          <div className={styles.failureList}>
            {data.failures.map((failure) => {
              const cellId = attemptToCell.get(failure.id);
              return (
                <article key={failure.id}>
                  <div><strong>{failure.case_id}</strong><small>Attempt {failure.repeat_index + 1} · {failure.error_code ?? failure.evaluation_state}</small><p>{failure.evaluation_summary ?? failure.error_message ?? "该 Attempt 未提供可展示的失败摘要。"}</p></div>
                  {cellId ? <Link to={`/targets/${encodeURIComponent(targetId)}/evaluation/runs/${encodeURIComponent(runId)}/cells/${encodeURIComponent(cellId)}`}>查看 Cell 证据 <ChevronRight size={13} /></Link> : <CopyableId label="Attempt ID" value={failure.id} />}
                </article>
              );
            })}
          </div>
        ) : <div className={styles.emptyRun}><CheckCircle2 size={24} /><strong>没有业务失败项</strong><p>仍请结合质量门禁和证据完整性判断是否可以验收。</p></div>}
      </Panel>
    </div>
  );
}

function useTarget(targetId: string) {
  return useQuery({ queryKey: ["targets", targetId], queryFn: () => getOne<Target>(`/api/targets/${encodeURIComponent(targetId)}`) });
}

function matchRoute(pathname: string, targetId: string): EvaluationRoute {
  const base = `/targets/${encodeURIComponent(targetId)}/evaluation/runs`;
  const wizard = pathname.match(new RegExp(`^${escapeRegex(base)}/new/(info|scope|review)$`));
  if (wizard?.[1]) return { page: "wizard", step: wizard[1] as "info" | "scope" | "review" };
  const cell = pathname.match(new RegExp(`^${escapeRegex(base)}/([^/]+)/cells/([^/]+)$`));
  if (cell?.[1] && cell[2]) return { page: "cell", runId: decodeURIComponent(cell[1]), cellId: decodeURIComponent(cell[2]) };
  const report = pathname.match(new RegExp(`^${escapeRegex(base)}/([^/]+)/report$`));
  if (report?.[1]) return { page: "report", runId: decodeURIComponent(report[1]) };
  const run = pathname.match(new RegExp(`^${escapeRegex(base)}/([^/]+)$`));
  if (run?.[1]) return { page: "run", runId: decodeURIComponent(run[1]) };
  if (pathname === base) return { page: "runs" };
  return { page: "fallback" };
}

function escapeRegex(value: string) { return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"); }
function wizardPath(targetId: string, step: "info" | "scope" | "review") { return `/targets/${encodeURIComponent(targetId)}/evaluation/runs/new/${step}`; }
function wizardKey(targetId: string) { return `agentrig:evaluation-draft:${targetId}`; }
function readWizardDraft(targetId: string): WizardDraft { try { const value = JSON.parse(window.sessionStorage.getItem(wizardKey(targetId)) ?? "null") as Partial<WizardDraft> | null; return { goal: typeof value?.goal === "string" ? value.goal : "", caseIds: Array.isArray(value?.caseIds) ? value.caseIds.filter((item): item is string => typeof item === "string") : [], profileId: typeof value?.profileId === "string" ? value.profileId : "", repeatCount: typeof value?.repeatCount === "number" && value.repeatCount > 0 ? value.repeatCount : 1 }; } catch { return { goal: "", caseIds: [], profileId: "", repeatCount: 1 }; } }
function terminal(value?: string) { return ["completed", "failed", "cancelled", "interrupted"].includes(value ?? ""); }
function message(value: unknown) { return value instanceof Error ? value.message : value ? String(value) : "未知错误"; }
function retryableFailure(value: RunCell["failure_class"]) { return ["target_unreachable", "tool_result_unavailable", "timeout", "evaluation_error", "cancelled", "interrupted", "internal_error", "unknown"].includes(value ?? ""); }

function SummaryMetric({ label, value, icon, tone, compact }: { label: string; value: string | number; icon: React.ReactNode; tone?: string; compact?: boolean }) {
  return <article data-tone={tone} className={compact ? styles.compactMetric : ""}><span>{icon}</span><div><small>{label}</small><strong>{value}</strong></div></article>;
}
function Progress({ value }: { value: number }) { return <span className={styles.progress}><i style={{ width: `${Math.max(0, Math.min(100, value))}%` }} /></span>; }
function StatusBadge({ status }: { status: UiStatus }) { return <Badge tone={statusTone(status)}>{statusLabel(status)}</Badge>; }
function statusTone(status: UiStatus): "neutral" | "accent" | "success" | "warning" | "danger" { if (status === "passed") return "success"; if (status === "failed") return "danger"; if (["running", "queued"].includes(status)) return "accent"; if (["partial", "pending", "interrupted"].includes(status)) return "warning"; return "neutral"; }
function statusLabel(status: UiStatus) { return ({ draft: "草稿", pending: "待处理", queued: "排队中", running: "执行中", passed: "通过", failed: "失败", partial: "部分完成", cancelled: "已取消", interrupted: "已中断", unknown: "未知" } as const)[status]; }
function failureLabel(value?: string | null) { return ({ behavior_regression: "行为回归", target_unreachable: "Target 不可达", tool_result_unavailable: "工具结果不可用", contract_incompatible: "契约不兼容", timeout: "执行超时", evaluation_error: "评判异常", policy_denied: "策略拒绝", cancelled: "已取消", interrupted: "已中断", internal_error: "内部错误", unknown: "未知异常" } as Record<string, string>)[value ?? ""] ?? "无"; }
function timelineIcon(kind: string) { if (kind === "evaluation") return <CheckCircle2 size={14} />; if (kind === "error") return <XCircle size={14} />; if (kind === "tool_call" || kind === "tool_result") return <FlaskConical size={14} />; if (kind === "input") return <FileText size={14} />; return <Clock3 size={14} />; }
function gateVerdictLabel(value?: "pass" | "warn" | "fail" | "inconclusive") { return ({ pass: "通过", warn: "有条件通过", fail: "不通过", inconclusive: "证据不足" } as const)[value ?? "inconclusive"]; }
function capabilityStatusLabel(value: "complete" | "partial" | "unavailable" | "invalid" | "legacy_unavailable") { return ({ complete: "完整", partial: "部分采集", unavailable: "不可用", invalid: "无效", legacy_unavailable: "历史 Run 不可用" } as const)[value]; }
function snapshotValue(value: unknown) { return typeof value === "string" && value.trim() ? value : "未观测"; }
function directRunVerdict(report: import("~/api/v1").RunReport): "pass" | "fail" | "inconclusive" {
  if (report.outcomes.fail_count > 0 || report.outcomes.evaluation_error_count > 0) return "fail";
  if (report.outcomes.evaluated > 0 && report.outcomes.pass_count === report.outcomes.evaluated) return "pass";
  return "inconclusive";
}
function percent(value: number | null) { return value === null ? "不可用" : `${Math.round(value * 100)}%`; }
function duration(value: number | null) { return value === null ? "不可用" : value >= 1000 ? `${(value / 1000).toFixed(2)} s` : `${Math.round(value)} ms`; }
