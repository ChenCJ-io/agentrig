import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Activity,
  ArrowRight,
  BarChart3,
  Bot,
  Boxes,
  Check,
  CheckCircle2,
  ChevronRight,
  CircleAlert,
  CircleDot,
  ClipboardCheck,
  Clock3,
  Code2,
  Database,
  Download,
  ExternalLink,
  FileJson,
  FileSearch,
  Gauge,
  GitCompareArrows,
  History,
  Layers3,
  ListChecks,
  MessageSquare,
  Network,
  Play,
  Plus,
  RefreshCcw,
  Search,
  Settings2,
  ShieldCheck,
  Sparkles,
  TestTube2,
  TriangleAlert,
  UserRoundCheck,
  UsersRound,
  Waypoints,
  Wrench,
  X,
  XCircle,
  type LucideIcon,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState, type ChangeEvent, type ReactNode } from "react";
import { Link, useNavigate } from "react-router";

import {
  createOne,
  getOne,
  getPage,
  postAction,
  type CaseRun,
  type ExecutionProfile,
  type Run,
  type Sample,
  type Target,
  type TargetCheck,
  type TestCase,
} from "~/api/v1";
import {
  closeTargetChat,
  createDraftCaseFromTargetChat,
  createDraftSampleFromTargetChat,
  createTargetChat,
  getAgentInvocation,
  getAgentTeamsHealth,
  getTargetChat,
  listAllAgentInvocations,
  listTargetChats,
  sendTargetChatMessage,
  type AgentInvocation,
  type AgentTeamsHealth,
  type TargetChatEvent,
} from "~/api/v2";
import { Badge } from "~/components/ui/badge";
import { Button } from "~/components/ui/button";
import { AssistantPage } from "~/pages/v2/assistant-page";

import { CaseEditorDrawer, ProfileEditorDrawer, SampleEditorDrawer, TargetEditorDrawer } from "./resource-drawers";

import styles from "./product-page.module.css";

type Tone = "neutral" | "accent" | "success" | "warning" | "danger";

interface TargetRoute {
  targetId: string;
  suffix: string;
}

function parseTargetRoute(pathname: string): TargetRoute | null {
  const match = pathname.match(/^\/targets\/([^/]+)(\/.*)?$/);
  return match
    ? { targetId: decodeURIComponent(match[1]!), suffix: match[2] || "/overview" }
    : null;
}

export function ProductPage({ pathname }: { pathname: string }) {
  if (pathname === "/targets") return <TargetDirectoryPage />;
  if (pathname.startsWith("/evaluator-teams")) return <EvaluatorTeamsPage />;
  if (pathname.startsWith("/audit")) return <AuditPage />;
  if (pathname.startsWith("/settings")) return <SettingsPage />;
  const route = parseTargetRoute(pathname);
  if (!route) return <TargetDirectoryPage />;
  if (route.suffix === "/assistant") return <AssistantPage />;
  if (route.suffix === "/conversation") return <ConversationPage targetId={route.targetId} />;
  if (route.suffix === "/overview") return <OverviewPage targetId={route.targetId} />;
  if (route.suffix === "/assets") return <AssetsOverviewPage targetId={route.targetId} />;
  if (route.suffix === "/assets/tool-results") return <ToolResultsPage targetId={route.targetId} />;
  if (route.suffix === "/assets/profiles") return <ProfilesPage targetId={route.targetId} />;
  if (route.suffix === "/evaluation/test-cases") return <TestCasesPage targetId={route.targetId} />;
  if (route.suffix === "/evaluation/case-review") return <CaseReviewPage targetId={route.targetId} />;
  if (route.suffix === "/evaluation/comparisons") return <ComparisonsPage targetId={route.targetId} />;
  if (route.suffix === "/evaluation/reports") return <ReportsPage targetId={route.targetId} />;
  if (route.suffix === "/observability") return <ObservabilityPage targetId={route.targetId} />;
  if (route.suffix === "/observability/metrics") return <MetricsPage targetId={route.targetId} />;
  if (route.suffix === "/observability/problems") return <ProblemsPage targetId={route.targetId} />;
  if (route.suffix === "/observability/export") return <ExportPage targetId={route.targetId} />;
  if (route.suffix.startsWith("/evaluation/runs")) {
    const runId = route.suffix.match(/^\/evaluation\/runs\/([^/]+)$/)?.[1];
    return <RunsPage runId={runId ? decodeURIComponent(runId) : null} targetId={route.targetId} />;
  }
  return <OverviewPage targetId={route.targetId} />;
}

function PageIntro({
  eyebrow,
  title,
  description,
  actions,
}: {
  eyebrow: string;
  title: string;
  description: string;
  actions?: ReactNode;
}) {
  return (
    <header className={styles.pageIntro}>
      <div>
        <span className="eyebrow">{eyebrow}</span>
        <h1>{title}</h1>
        <p>{description}</p>
      </div>
      {actions ? <div className={styles.pageActions}>{actions}</div> : null}
    </header>
  );
}

function Surface({
  title,
  eyebrow,
  actions,
  children,
  className = "",
}: {
  title?: string;
  eyebrow?: string;
  actions?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`${styles.surface} ${className}`}>
      {title || eyebrow || actions ? (
        <header className={styles.surfaceHeader}>
          <div>{eyebrow ? <span className="eyebrow">{eyebrow}</span> : null}{title ? <h2>{title}</h2> : null}</div>
          {actions ? <div className={styles.surfaceActions}>{actions}</div> : null}
        </header>
      ) : null}
      {children}
    </section>
  );
}

function Status({ value, label }: { value: string; label?: string }) {
  return <span className={`${styles.status} ${styles[`status${toneFor(value)}`]}`}><i />{label ?? labelFor(value)}</span>;
}

function EmptyState({ icon: Icon = FileSearch, title, children }: { icon?: LucideIcon; title: string; children: ReactNode }) {
  return <div className={styles.emptyState}><Icon size={20} /><strong>{title}</strong><p>{children}</p></div>;
}

function QueryFailure({ value }: { value: unknown }) {
  return <div className={styles.queryFailure}><CircleAlert size={15} /><span>{errorMessage(value)}</span></div>;
}

function MetricStrip({ items }: { items: Array<{ label: string; value: ReactNode; meta: string; tone?: Tone }> }) {
  return (
    <div className={styles.metricStrip}>
      {items.map((item) => (
        <div key={item.label} data-tone={item.tone ?? "neutral"}>
          <span>{item.label}</span><strong>{item.value}</strong><small>{item.meta}</small>
        </div>
      ))}
    </div>
  );
}

function TargetDirectoryPage() {
  const [searchQuery, setSearchQuery] = useState("");
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingTarget, setEditingTarget] = useState<Target | null>(null);
  const targets = useQuery({ queryKey: ["product", "targets"], queryFn: () => getPage<Target>("/api/targets?limit=100") });
  const cases = useQuery({ queryKey: ["product", "cases", "count"], queryFn: () => getPage<TestCase>("/api/test-cases?limit=1") });
  const samples = useQuery({ queryKey: ["product", "samples", "count"], queryFn: () => getPage<Sample>("/api/samples?limit=1") });
  const runs = useQuery({ queryKey: ["product", "runs", "directory"], queryFn: () => getPage<Run>("/api/runs?limit=100"), refetchInterval: 5_000 });
  const health = useQuery({ queryKey: ["product", "agentteams", "health"], queryFn: getAgentTeamsHealth, refetchInterval: 15_000 });
  const online = targets.data?.items.length ?? 0;
  const visibleTargets = (targets.data?.items ?? []).filter((target) => {
    const needle = searchQuery.trim().toLocaleLowerCase();
    return !needle || [target.name, target.id, target.driver_type].some((value) => value.toLocaleLowerCase().includes(needle));
  });
  return (
    <ProductWorkspace>
      <PageIntro
        eyebrow="平台控制台 · 接入目录"
        title="被测 Agent"
        description="管理接入 AgentRig 的评测对象，并从统一工作区进入对话、评测、资产与观测。"
        actions={<Button icon={<Plus />} onClick={() => { setEditingTarget(null); setEditorOpen(true); }} variant="primary">接入被测 Agent</Button>}
      />
      <MetricStrip items={[
        { label: "被测 Agent", value: targets.data?.total ?? "—", meta: `${online} 个已接入`, tone: "accent" },
        { label: "测试用例", value: cases.data?.total ?? "—", meta: "包含草稿与已审核用例" },
        { label: "工具结果资产", value: samples.data?.total ?? "—", meta: "覆盖全部审核状态" },
        { label: "评测运行时", value: health.data?.matrix_reachable ? "就绪" : "待检查", meta: health.data?.enabled ? "AgentTeams 已启用" : "仅核心模式", tone: health.data?.matrix_reachable ? "success" : "warning" },
      ]} />
      <div className={styles.directoryGrid}>
        <Surface title="被测 Agent 目录" eyebrow="接入与状态" className={styles.targetDirectory} actions={<label className={styles.searchBox}><Search size={14} /><input aria-label="搜索被测 Agent" placeholder="搜索名称、ID 或驱动" value={searchQuery} onChange={(event) => setSearchQuery(event.target.value)} /></label>}>
          {targets.isLoading ? <EmptyState title="正在读取被测 Agent">正在连接本地 AgentRig 数据库。</EmptyState> : null}
          {targets.error ? <QueryFailure value={targets.error} /> : null}
          <div className={styles.targetGrid}>
            {visibleTargets.map((target) => {
              const latest = runs.data?.items.find((run) => run.target_snapshots.some((snapshot) => snapshot.id === target.id));
              return <TargetDirectoryCard key={target.id} target={target} latest={latest} caseCount={cases.data?.total} onEdit={() => { setEditingTarget(target); setEditorOpen(true); }} sampleCount={samples.data?.total} />;
            })}
          </div>
          {!targets.isLoading && !targets.data?.items.length ? <EmptyState icon={Waypoints} title="尚未接入被测 Agent">完成接入后即可进入完整评测工作区。</EmptyState> : null}
          {!targets.isLoading && Boolean(targets.data?.items.length) && !visibleTargets.length ? <EmptyState icon={Search} title="没有匹配的被测 Agent">尝试按名称、ID 或驱动类型搜索。</EmptyState> : null}
        </Surface>
        <aside className={styles.directoryRail}>
          <Surface title="评测运行时" eyebrow="AgentTeams">
            <div className={styles.runtimePanel}>
              <span className={styles.runtimeIcon}><UsersRound size={18} /></span>
              <div><strong>{health.data?.matrix_reachable ? "运行环境就绪" : "运行环境待检查"}</strong><p>{health.data?.matrix_reachable ? "Matrix 与三角色评测协作正常" : "正在检查 AgentTeams 运行状态"}</p></div>
            </div>
            <div className={styles.compactRows}>
              <div><span>Matrix</span><Status value={health.data?.matrix_reachable ? "ready" : "unavailable"} /></div>
              <div><span>评测主控</span><Status value={health.data?.enabled ? "ready" : "disabled"} /></div>
              <div><span>专业 Worker</span><strong>已配置 2 个</strong></div>
            </div>
            <Link className={styles.panelLink} to="/evaluator-teams">查看评测团队 <ChevronRight size={13} /></Link>
          </Surface>
          <Surface title="最近平台活动" eyebrow="运行动态">
            <div className={styles.activityList}>
              {(runs.data?.items ?? []).slice(0, 5).map((run) => (
                <Link to={run.target_snapshots[0]?.id ? `/targets/${encodeURIComponent(run.target_snapshots[0].id)}/evaluation/runs/${run.id}` : "/targets"} key={run.id}>
                  <Status value={run.status} />
                  <span><strong>Run {shortId(run.id)}</strong><small>{formatDate(run.created_at)}</small></span>
                  <ChevronRight size={12} />
                </Link>
              ))}
              {!runs.data?.items.length ? <p className={styles.mutedText}>尚无运行活动。</p> : null}
            </div>
          </Surface>
        </aside>
      </div>
      {editorOpen ? <TargetEditorDrawer initial={editingTarget} onClose={() => setEditorOpen(false)} onSaved={() => setEditorOpen(false)} /> : null}
    </ProductWorkspace>
  );
}

function TargetDirectoryCard({ target, latest, caseCount, sampleCount, onEdit }: { target: Target; latest?: Run; caseCount?: number; sampleCount?: number; onEdit: () => void }) {
  const version = target.versions[0]?.version;
  const check = useQuery({
    queryKey: ["product", "target-check", target.id, version ?? null],
    queryFn: () => postAction<TargetCheck>(`/api/targets/${encodeURIComponent(target.id)}/check${version ? `?version=${encodeURIComponent(version)}` : ""}`),
    staleTime: 60_000,
    retry: false,
  });
  const base = `/targets/${encodeURIComponent(target.id)}`;
  const healthStatus = check.isPending ? "running" : check.data?.reachable ? "ready" : "unavailable";
  const healthLabel = check.isPending ? "检测中" : check.data?.reachable ? "可连接" : "连接失败";
  return (
    <article className={styles.targetCard}>
      <header>
        <span className={styles.targetMark}><Bot size={20} /></span>
        <div><h2>{target.name}</h2><p title={check.data?.message ?? errorMessage(check.error)}>被测智能体 · {check.isPending ? "正在执行连接检查" : check.data?.reachable ? "HTTP 连通性检查通过" : "连接检查未通过"}</p></div>
        <Status value={healthStatus} label={healthLabel} />
      </header>
      <div className={styles.targetProtocol}>
        <span><Waypoints size={13} />{target.driver_type}</span>
        <span><Network size={13} />{check.data?.endpoint ? "端点已探测" : "驱动探测"}</span>
        <span><Layers3 size={13} />{target.versions.length || 1} 个版本</span>
      </div>
      <dl className={styles.targetStats}>
        <div><dt>测试用例</dt><dd>{caseCount ?? "—"}</dd></div>
        <div><dt>结果资产</dt><dd>{sampleCount ?? "—"}</dd></div>
        <div><dt>最近运行</dt><dd>{latest ? labelFor(latest.status) : "暂无"}</dd></div>
      </dl>
      <footer>
        <Link className="button button--primary" to={`${base}/overview`}>进入工作区 <ArrowRight size={13} /></Link>
        <Link className="button" to={`${base}/conversation`}>对话验证</Link>
        <Button onClick={onEdit} size="sm" variant="quiet"><Settings2 size={12} /> 配置</Button>
        <Link className={styles.inlineLink} to={`${base}/assistant`}>智能评测 <Sparkles size={12} /></Link>
      </footer>
    </article>
  );
}

function useTargetData(targetId: string) {
  const target = useQuery({ queryKey: ["product", "target", targetId], queryFn: () => getOne<Target>(`/api/targets/${encodeURIComponent(targetId)}`) });
  const cases = useQuery({ queryKey: ["product", "cases"], queryFn: () => getPage<TestCase>("/api/test-cases?limit=200") });
  const runs = useQuery({ queryKey: ["product", "runs", targetId], queryFn: () => getPage<Run>(`/api/runs?target_id=${encodeURIComponent(targetId)}&limit=100`), refetchInterval: 5_000 });
  const samples = useQuery({ queryKey: ["product", "samples"], queryFn: () => getPage<Sample>("/api/samples?limit=200") });
  const profiles = useQuery({ queryKey: ["product", "profiles"], queryFn: () => getPage<ExecutionProfile>("/api/execution-profiles?limit=100") });
  return { target, cases, runs, samples, profiles };
}

function OverviewPage({ targetId }: { targetId: string }) {
  const { target, cases, runs, samples, profiles } = useTargetData(targetId);
  const latest = runs.data?.items[0];
  const caseRuns = useQuery({
    queryKey: ["product", "case-runs", latest?.id],
    queryFn: () => getPage<CaseRun>(`/api/runs/${encodeURIComponent(latest!.id)}/case-runs?limit=200`),
    enabled: Boolean(latest?.id),
    refetchInterval: latest && ["queued", "running"].includes(latest.status) ? 2_000 : false,
  });
  const outcomes = summarizeOutcomes(caseRuns.data?.items ?? []);
  const approvedCases = cases.data?.items.filter((item) => item.review_status === "approved").length ?? 0;
  const pendingCases = cases.data?.items.filter((item) => item.review_status === "draft").length ?? 0;
  const approvedSamples = samples.data?.items.filter((item) => item.status === "approved").length ?? 0;
  const capabilityRows = capabilityCoverage(cases.data?.items ?? []);
  const base = `/targets/${encodeURIComponent(targetId)}`;
  return (
    <ProductWorkspace>
      <PageIntro
        eyebrow="工作区 · 评测概况"
        title={`${target.data?.name ?? "被测 Agent"} 评测总览`}
        description="从真实运行、评测资产和 AgentTeams 协作状态汇总当前质量。"
        actions={<><Link className="button" to={`${base}/conversation`}><MessageSquare size={13} /> 对话验证</Link><Link className="button button--primary" to={`${base}/assistant`}><Sparkles size={13} /> 发起智能评测</Link></>}
      />
      <MetricStrip items={[
        { label: "已评测", value: outcomes.total || "—", meta: latest ? `最近运行 ${shortId(latest.id)}` : "暂无已完成运行", tone: "accent" },
        { label: "评测通过", value: outcomes.pass, meta: outcomes.total ? `通过率 ${percentage(outcomes.pass, outcomes.total)}` : "暂无评测结论", tone: "success" },
        { label: "评测未通过", value: outcomes.fail, meta: `${outcomes.inconclusive} 个证据不足`, tone: outcomes.fail ? "danger" : "neutral" },
        { label: "已审核用例", value: approvedCases, meta: `${pendingCases} 个等待审核` },
        { label: "已审核结果资产", value: approvedSamples, meta: `共 ${samples.data?.total ?? 0} 项资产` },
      ]} />
      <div className={styles.overviewGrid}>
        <Surface title="最近一次评测" eyebrow="运行摘要" className={styles.latestRun} actions={latest ? <Status value={latest.status} /> : null}>
          {latest ? (
            <div className={styles.latestRunBody}>
              <div className={styles.runIdentity}>
                <span>运行编号</span><code>{shortId(latest.id)}</code><p>{latest.resolved_case_ids.length} 个用例 · {formatDate(latest.created_at)}</p>
              </div>
              <div className={styles.outcomeBand}>
                <div data-tone="success"><strong>{outcomes.pass}</strong><span>通过</span></div>
                <div data-tone="danger"><strong>{outcomes.fail}</strong><span>未通过</span></div>
                <div data-tone="warning"><strong>{outcomes.inconclusive}</strong><span>证据不足</span></div>
                <div><strong>{latest.failed_count}</strong><span>执行错误</span></div>
              </div>
              <div className={styles.progressTrack}><i style={{ width: `${percentage(latest.completed_count + latest.failed_count + latest.skipped_count + latest.cancelled_count, Math.max(latest.total_count, 1))}` }} /></div>
              <footer><span>{latest.completed_count + latest.failed_count + latest.skipped_count + latest.cancelled_count} / {latest.total_count} 个用例运行</span><Link to={`${base}/evaluation/runs/${latest.id}`}>查看运行证据 <ArrowRight size={13} /></Link></footer>
            </div>
          ) : <EmptyState icon={Play} title="尚无评测运行">从智能评测助手或运行记录提交第一次真实评测。</EmptyState>}
        </Surface>
        <Surface title="质量门禁" eyebrow="验收状态">
          <div className={styles.gateList}>
            <Gate label="执行完整性" pass={!latest || latest.failed_count === 0} meta={latest ? `${latest.failed_count} 个执行错误` : "等待首次运行"} />
            <Gate label="权威裁决" pass={outcomes.inconclusive === 0} meta={`${outcomes.inconclusive} 个证据不足`} />
            <Gate label="回归结果" pass={outcomes.fail === 0} meta={`${outcomes.fail} 个未通过用例`} />
            <Gate label="资产审核" pass={pendingCases === 0} meta={`${pendingCases} 个用例草稿`} />
          </div>
        </Surface>
        <Surface title="能力覆盖" eyebrow="用例标签">
          <div className={styles.coverageList}>
            {capabilityRows.slice(0, 6).map((row) => <div key={row.label}><span>{row.label}</span><div><i style={{ width: `${Math.min(100, row.count * 16)}%` }} /></div><strong>{row.count}</strong></div>)}
            {!capabilityRows.length ? <p className={styles.mutedText}>当前用例还没有能力标签。</p> : null}
          </div>
        </Surface>
        <Surface title="待处理事项" eyebrow="行动队列">
          <div className={styles.actionQueue}>
            <Link to={`${base}/evaluation/case-review`}><FileSearch size={14} /><span><strong>{pendingCases} 个待审核用例</strong><small>人工审核后进入正式用例库</small></span><ChevronRight size={13} /></Link>
            <Link to={`${base}/assets/tool-results`}><Database size={14} /><span><strong>{(samples.data?.total ?? 0) - approvedSamples} 个结果样本草稿</strong><small>检查来源、数据结构与匹配规则</small></span><ChevronRight size={13} /></Link>
            <Link to={`${base}/evaluation/runs`}><TriangleAlert size={14} /><span><strong>{outcomes.fail + (latest?.failed_count ?? 0)} 个最近异常</strong><small>区分行为失败与执行错误</small></span><ChevronRight size={13} /></Link>
          </div>
        </Surface>
      </div>
      <Surface title="最近运行" eyebrow="运行历史" actions={<Link className={styles.inlineLink} to={`${base}/evaluation/runs`}>全部运行 <ArrowRight size={12} /></Link>}>
        <RunRows runs={(runs.data?.items ?? []).slice(0, 7)} targetId={targetId} />
      </Surface>
    </ProductWorkspace>
  );
}

function Gate({ label, pass, meta }: { label: string; pass: boolean; meta: string }) {
  return <div><span className={pass ? styles.gatePass : styles.gateFail}>{pass ? <Check size={13} /> : <X size={13} />}</span><p><strong>{label}</strong><small>{meta}</small></p><Status value={pass ? "pass" : "fail"} /></div>;
}

function AssetsOverviewPage({ targetId }: { targetId: string }) {
  const { cases, samples, profiles } = useTargetData(targetId);
  const base = `/targets/${encodeURIComponent(targetId)}`;
  const approvedCases = cases.data?.items.filter((item) => item.review_status === "approved").length ?? 0;
  const approvedSamples = samples.data?.items.filter((item) => item.status === "approved").length ?? 0;
  const toolNames = new Set(samples.data?.items.map((item) => item.tool_name).filter(Boolean));
  return (
    <ProductWorkspace>
      <PageIntro eyebrow="资产中心 · 可复现评测" title="评测资产" description="统一管理测试用例、工具结果资产和可复用执行策略。" />
      <MetricStrip items={[
        { label: "测试用例", value: cases.data?.total ?? "—", meta: `${approvedCases} 个已审核`, tone: "accent" },
        { label: "工具结果资产", value: samples.data?.total ?? "—", meta: `${approvedSamples} 个可用于回放`, tone: "success" },
        { label: "覆盖工具", value: toolNames.size, meta: "来自工具结果目录" },
        { label: "执行配置", value: profiles.data?.total ?? "—", meta: "可复用的执行策略" },
      ]} />
      <div className={styles.assetOverviewGrid}>
        <AssetDomain icon={TestTube2} title="测试用例" code="用例库" value={cases.data?.total ?? 0} description="多轮输入、夹具、断言与语义评判规则。" href={`${base}/evaluation/test-cases`} meta={`${(cases.data?.total ?? 0) - approvedCases} 个草稿`} />
        <AssetDomain icon={Database} title="工具结果资产" code="结果目录" value={samples.data?.total ?? 0} description="可审核的结果样本、候选结果与结果提供链命中规则。" href={`${base}/assets/tool-results`} meta={`${toolNames.size} 个工具`} />
        <AssetDomain icon={Settings2} title="执行配置" code="策略模板" value={profiles.data?.total ?? 0} description="工具模式、结果提供链、评判器与超时策略。" href={`${base}/assets/profiles`} meta="每次运行自动冻结快照" />
      </div>
      <Surface title="资产治理状态" eyebrow="审核与覆盖">
        <div className={styles.governanceRows}>
          <div><span>已审核用例</span><strong>{approvedCases}</strong><small>{(cases.data?.total ?? 0) - approvedCases} 个待审核</small></div>
          <div><span>已审核结果资产</span><strong>{approvedSamples}</strong><small>{(samples.data?.total ?? 0) - approvedSamples} 个草稿或停用项</small></div>
          <div><span>能力覆盖</span><strong>{capabilityCoverage(cases.data?.items ?? []).length}</strong><small>基于 cap.* 标签统计</small></div>
          <div><span>快照策略</span><strong>已启用</strong><small>每次 Run 冻结全部资产</small></div>
        </div>
      </Surface>
    </ProductWorkspace>
  );
}

function AssetDomain({ icon: Icon, title, code, value, description, href, meta }: { icon: LucideIcon; title: string; code: string; value: number; description: string; href: string; meta: string }) {
  return <Link className={styles.assetDomain} to={href}><header><span><Icon size={17} /></span><small>{code}</small><ChevronRight size={14} /></header><strong>{value}</strong><h2>{title}</h2><p>{description}</p><footer>{meta}</footer></Link>;
}

function ProductWorkspace({ children }: { children: ReactNode }) {
  return <div className={styles.workspace}>{children}</div>;
}

function RunRows({ runs, targetId }: { runs: Run[]; targetId: string }) {
  if (!runs.length) return <EmptyState icon={ListChecks} title="没有运行记录">提交评测后，Run 会显示在这里。</EmptyState>;
  return <div className={styles.dataTable}><div className={styles.tableHeader}><span>运行编号</span><span>执行状态</span><span>用例数</span><span>进度</span><span>创建时间</span><span /></div>{runs.map((run) => <Link className={styles.tableRow} key={run.id} to={`/targets/${encodeURIComponent(targetId)}/evaluation/runs/${run.id}`}><code>{shortId(run.id)}</code><Status value={run.status} /><span>{run.resolved_case_ids.length}</span><span>{run.completed_count + run.failed_count + run.skipped_count + run.cancelled_count} / {run.total_count}</span><time>{formatDate(run.created_at)}</time><ChevronRight size={13} /></Link>)}</div>;
}

function capabilityCoverage(cases: TestCase[]) {
  const counts = new Map<string, number>();
  cases.flatMap((item) => item.tags).filter((tag) => tag.startsWith("cap.")).forEach((tag) => counts.set(tag, (counts.get(tag) ?? 0) + 1));
  return [...counts.entries()].map(([label, count]) => ({ label: label.replace(/^cap\./, ""), count })).sort((a, b) => b.count - a.count);
}

function summarizeOutcomes(items: CaseRun[]) {
  const values = { pass: 0, fail: 0, inconclusive: 0, total: 0 };
  items.forEach((item) => {
    if (item.evaluation_state === "pass") values.pass += 1;
    else if (item.evaluation_state === "fail") values.fail += 1;
    else if (item.evaluation_state === "inconclusive") values.inconclusive += 1;
  });
  values.total = values.pass + values.fail + values.inconclusive;
  return values;
}

function shortId(value: string) {
  const [prefix, body] = value.split("_", 2);
  return body ? `${prefix}_${body.slice(0, 8)}` : value.slice(0, 12);
}

function formatDate(value?: string | null) {
  if (!value) return "—";
  return new Intl.DateTimeFormat("zh-CN", { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
}

function percentage(value: number, total: number) {
  return total ? `${Math.round((value / total) * 100)}%` : "0%";
}

function toneFor(value: string): Tone {
  if (["ready", "pass", "approved", "completed", "submitted", "reachable"].includes(value)) return "success";
  if (["fail", "failed", "rejected", "disabled", "cancelled", "timed_out", "unavailable", "error"].includes(value)) return "danger";
  if (["running", "dispatched", "confirmed"].includes(value)) return "accent";
  if (["draft", "queued", "created", "pending", "inconclusive", "check", "degraded"].includes(value)) return "warning";
  return "neutral";
}

function labelFor(value: string) {
  const labels: Record<string, string> = {
    approved: "已审核",
    cancelled: "已取消",
    check: "待检查",
    closed: "已结束",
    completed: "已完成",
    confirmed: "已确认",
    created: "已创建",
    degraded: "状态异常",
    delivered: "已送达",
    disabled: "已停用",
    dispatched: "已派发",
    draft: "草稿",
    error: "错误",
    fail: "未通过",
    failed: "执行失败",
    inconclusive: "证据不足",
    interrupted: "已中断",
    open: "进行中",
    pass: "通过",
    pending: "待处理",
    queued: "排队中",
    reachable: "可连接",
    ready: "就绪",
    rejected: "已驳回",
    running: "运行中",
    submitted: "已提交",
    timed_out: "已超时",
    unavailable: "不可用",
  };
  return labels[value] ?? value.replaceAll("_", " ");
}

function evaluatorLabel(value: string) {
  const labels: Record<string, string> = {
    evidence_judge: "证据裁决 Judge",
    evaluator: "评判器",
    external_controller: "外部评测控制器",
    rule: "规则评判器",
  };
  return labels[value] ?? value;
}

function errorMessage(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

// The remaining route implementations are kept below so every management view
// shares the same data, status and evidence semantics.

function TestCasesPage({ targetId }: { targetId: string }) {
  const { cases } = useTargetData(targetId);
  const queryClient = useQueryClient();
  const importInput = useRef<HTMLInputElement>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingCase, setEditingCase] = useState<TestCase | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const items = useMemo(() => (cases.data?.items ?? []).filter((item) => {
    const text = `${item.id} ${item.name} ${item.description} ${item.tags.join(" ")}`.toLowerCase();
    return text.includes(query.toLowerCase()) && (status === "all" || item.review_status === status);
  }), [cases.data, query, status]);
  useEffect(() => { if (!selectedId && items[0]) setSelectedId(items[0].id); }, [items, selectedId]);
  const selected = items.find((item) => item.id === selectedId) ?? cases.data?.items.find((item) => item.id === selectedId) ?? null;
  const approved = cases.data?.items.filter((item) => item.review_status === "approved").length ?? 0;
  async function importCases(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file) return;
    try {
      const parsed = JSON.parse(await file.text()) as unknown;
      const records = Array.isArray(parsed) ? parsed : [parsed];
      for (const record of records) {
        if (!record || typeof record !== "object") throw new Error("导入文件必须是用例对象或对象数组。");
        const { review_status: _reviewStatus, created_at: _createdAt, updated_at: _updatedAt, ...payload } = record as Record<string, unknown>;
        await createOne<TestCase>("/api/test-cases", payload);
      }
      await queryClient.invalidateQueries({ queryKey: ["product", "cases"] });
      setNotice(`已导入 ${records.length} 个 Draft 用例。`);
    } catch (error) { setNotice(errorMessage(error)); }
  }
  return (
    <ProductWorkspace>
      <PageIntro eyebrow="评测管理 · 用例库" title="测试用例" description="用结构化多轮脚本、确定性断言和语义评判规则定义评测目标。" actions={<><input accept="application/json,.json" className={styles.hiddenInput} onChange={(event) => void importCases(event)} ref={importInput} type="file" /><Button icon={<Download />} onClick={() => importInput.current?.click()}>导入 JSON</Button><Button icon={<Plus />} onClick={() => { setEditingCase(null); setEditorOpen(true); }} variant="primary">新建用例</Button></>} />
      {notice ? <div className={styles.noticeBar}><CircleAlert size={14} />{notice}<button onClick={() => setNotice(null)} type="button"><X size={12} /></button></div> : null}
      <MetricStrip items={[
        { label: "全部用例", value: cases.data?.total ?? "—", meta: "共享用例库，运行时按版本筛选", tone: "accent" },
        { label: "已审核", value: approved, meta: "内容不可变，可直接执行", tone: "success" },
        { label: "草稿", value: (cases.data?.total ?? 0) - approved, meta: "等待人工审核", tone: "warning" },
        { label: "能力标签", value: capabilityCoverage(cases.data?.items ?? []).length, meta: "按 cap.* 标签统计" },
      ]} />
      <div className={styles.assetWorkbench}>
        <aside className={styles.catalogRail}>
          <header><span className="eyebrow">用例目录</span><strong>能力与状态</strong></header>
          <button className={status === "all" ? styles.activeCatalog : ""} onClick={() => setStatus("all")} type="button"><span>全部用例</span><strong>{cases.data?.total ?? 0}</strong></button>
          <button className={status === "approved" ? styles.activeCatalog : ""} onClick={() => setStatus("approved")} type="button"><span>已审核</span><strong>{approved}</strong></button>
          <button className={status === "draft" ? styles.activeCatalog : ""} onClick={() => setStatus("draft")} type="button"><span>草稿</span><strong>{cases.data?.items.filter((item) => item.review_status === "draft").length ?? 0}</strong></button>
          <div className={styles.catalogDivider}>能力标签</div>
          {capabilityCoverage(cases.data?.items ?? []).slice(0, 8).map((row) => <button key={row.label} onClick={() => setQuery(`cap.${row.label}`)} type="button"><span>{row.label}</span><strong>{row.count}</strong></button>)}
        </aside>
        <section className={styles.assetListPane}>
          <header><label><Search size={14} /><input aria-label="搜索测试用例" onChange={(event) => setQuery(event.target.value)} placeholder="搜索名称、ID 或标签" value={query} /></label><span>{items.length} 条结果</span></header>
          <div className={styles.columnLabels}><span>测试用例</span><span>轮次</span><span>评判器</span><span>状态</span></div>
          <div className={styles.masterList}>
            {items.map((item) => <button className={selectedId === item.id ? styles.selectedMaster : ""} key={item.id} onClick={() => setSelectedId(item.id)} type="button"><span><strong>{item.name}</strong><small>{shortId(item.id)} · {item.tags.slice(0, 3).join(" · ") || "无标签"}</small></span><b>{item.turns.length}</b><em>{item.primary_evaluator.replace("evidence_", "")}</em><Status value={item.review_status} /></button>)}
            {!items.length ? <EmptyState icon={TestTube2} title="没有匹配用例">调整搜索或审核状态筛选。</EmptyState> : null}
          </div>
        </section>
        <CaseDetail caseItem={selected} onEdit={() => { setEditingCase(selected); setEditorOpen(true); }} targetId={targetId} />
      </div>
      {editorOpen ? <CaseEditorDrawer initial={editingCase} onClose={() => setEditorOpen(false)} onSaved={(item) => { setEditorOpen(false); if (item) setSelectedId(item.id); else setSelectedId(null); }} /> : null}
    </ProductWorkspace>
  );
}

function CaseDetail({ caseItem, targetId, onEdit }: { caseItem: TestCase | null; targetId: string; onEdit: () => void }) {
  const [tab, setTab] = useState<"definition" | "raw">("definition");
  if (!caseItem) return <section className={styles.detailPane}><EmptyState icon={TestTube2} title="选择一个测试用例">查看 Turn、Fixture、Assertion 和 Rubric。</EmptyState></section>;
  const assertions = Array.isArray(caseItem.case_assertions) ? caseItem.case_assertions as Array<Record<string, unknown>> : [];
  const rubric = typeof caseItem.case_rubric === "string" ? caseItem.case_rubric : null;
  return (
    <section className={styles.detailPane}>
      <header className={styles.detailHeader}><div><span className="eyebrow">用例详情</span><h2>{caseItem.name}</h2><code>{caseItem.id}</code></div><Status value={caseItem.review_status} /></header>
      <div className={styles.detailTabs}><button className={tab === "definition" ? styles.activeTab : ""} onClick={() => setTab("definition")} type="button">用例定义</button><button className={tab === "raw" ? styles.activeTab : ""} onClick={() => setTab("raw")} type="button"><Code2 size={12} /> 原始定义</button></div>
      {tab === "raw" ? <pre className={styles.rawPanel}>{pretty(caseItem)}</pre> : <div className={styles.detailScroll}>
        <section className={styles.definitionBlock}><header><span>用例说明</span><small>{caseItem.updated_at ? formatDate(caseItem.updated_at) : "—"}</small></header><p>{caseItem.description || "暂无说明。"}</p><div className={styles.tagRow}>{caseItem.tags.map((tag) => <Badge key={tag}>{tag}</Badge>)}</div></section>
        <section className={styles.definitionBlock}><header><span>初始状态</span><small>已脱敏 JSON</small></header><pre>{pretty(caseItem.initial_state ?? {})}</pre></section>
        <section className={styles.turnTimeline}><header><span>对话脚本</span><small>{caseItem.turns.length} 轮</small></header>{caseItem.turns.map((turn, index) => <TurnBlock key={String(turn.position ?? index)} index={index + 1} turn={turn} />)}</section>
        <section className={styles.definitionBlock}><header><span>用例评判</span><small>{caseItem.primary_evaluator}</small></header><div className={styles.visibilityNote}><ShieldCheck size={13} /><span>评判规则对 Judge 可见，对 Curator 与被测 Agent 不可见。</span></div><p>{rubric || "当前用例没有语义评判规则。"}</p><small>{assertions.length} 条用例级断言</small></section>
      </div>}
      <footer className={styles.detailFooter}><span>{caseItem.review_status === "approved" ? "已审核用例不可原地修改" : "草稿可修改并提交审核"}</span><div>{caseItem.review_status !== "approved" ? <Button icon={<Settings2 />} onClick={onEdit}>编辑</Button> : null}<Link className="button button--primary" to={`/targets/${encodeURIComponent(targetId)}/evaluation/runs`}>运行用例 <Play size={13} /></Link></div></footer>
    </section>
  );
}

function TurnBlock({ index, turn }: { index: number; turn: Record<string, unknown> }) {
  const fixtures = Array.isArray(turn.fixtures) ? turn.fixtures : [];
  const assertions = Array.isArray(turn.assertions) ? turn.assertions : [];
  return <article className={styles.turnBlock}><span className={styles.turnIndex}>{String(index).padStart(2, "0")}</span><div><small>用户消息</small><p>{String(turn.user_message ?? "")}</p><div className={styles.turnMeta}><span><Database size={11} />{fixtures.length} 个夹具</span><span><CheckCircle2 size={11} />{assertions.length} 条断言</span><span><ShieldCheck size={11} />{turn.rubric ? "本轮评判规则" : "无本轮规则"}</span></div></div></article>;
}

function CaseReviewPage({ targetId }: { targetId: string }) {
  const queryClient = useQueryClient();
  const cases = useQuery({ queryKey: ["product", "cases", "review"], queryFn: () => getPage<TestCase>("/api/test-cases?review_status=draft&limit=200") });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => { if (!selectedId && cases.data?.items[0]) setSelectedId(cases.data.items[0].id); }, [cases.data, selectedId]);
  const selected = cases.data?.items.find((item) => item.id === selectedId) ?? null;
  const review = useMutation({
    mutationFn: (status: "approved" | "rejected") => postAction(`/api/test-cases/${encodeURIComponent(selected!.id)}/review?review_status=${status}`),
    onSuccess: async (_, status) => { setNotice(status === "approved" ? "用例已通过人工审核。" : "用例已驳回。"); setSelectedId(null); await queryClient.invalidateQueries({ queryKey: ["product", "cases"] }); },
    onError: (error) => setNotice(errorMessage(error)),
  });
  return <ProductWorkspace>
    <PageIntro eyebrow="评测管理 · 人工审核" title="用例审核" description="AI 和自动化只能创建草稿；只有人工审核通过后才能进入正式用例库。" />
    {notice ? <div className={styles.noticeBar}><CircleAlert size={14} />{notice}<button onClick={() => setNotice(null)} type="button"><X size={12} /></button></div> : null}
    <div className={styles.reviewWorkbench}>
      <Surface title="待审核队列" eyebrow={`${cases.data?.total ?? 0} 个用例草稿`} className={styles.reviewQueue}>
        <div className={styles.masterList}>{cases.data?.items.map((item) => <button className={selectedId === item.id ? styles.selectedMaster : ""} key={item.id} onClick={() => setSelectedId(item.id)} type="button"><span><strong>{item.name}</strong><small>{shortId(item.id)} · {item.turns.length} turns</small></span><Status value={item.review_status} /></button>)}{!cases.data?.items.length ? <EmptyState icon={UserRoundCheck} title="审核队列已清空">当前没有 Draft 用例。</EmptyState> : null}</div>
      </Surface>
      <section className={styles.reviewSurface}>
        {selected ? <><header><div><span className="eyebrow">待审核用例</span><h2>{selected.name}</h2><code>{selected.id}</code></div><Status value={selected.review_status} /></header><div className={styles.reviewBody}><div className={styles.reviewContent}><p>{selected.description || "暂无说明。"}</p>{selected.turns.map((turn, index) => <TurnBlock key={index} index={index + 1} turn={turn} />)}<div className={styles.visibilityNote}><ShieldCheck size={13} />评判规则只提供给 Judge，不进入 Curator 上下文。</div></div><aside className={styles.reviewChecks}><h3>字段检查</h3><ReviewCheck pass={Boolean(selected.name)} label="名称明确" /><ReviewCheck pass={selected.turns.length > 0} label="至少一个 Turn" /><ReviewCheck pass={Boolean(selected.primary_evaluator)} label="评判器已定义" /><ReviewCheck pass={selected.tags.length > 0} label="能力或优先级标签" /><ReviewCheck pass={Boolean(selected.case_rubric) || Boolean(selected.case_assertions && (selected.case_assertions as unknown[]).length)} label="存在可执行评判" /></aside></div><footer><span><ShieldCheck size={13} />审核结果写入权威状态</span><div><Button disabled={review.isPending} icon={<XCircle />} onClick={() => review.mutate("rejected")} variant="danger">驳回</Button><Button disabled={review.isPending} icon={<Check />} onClick={() => review.mutate("approved")} variant="primary">通过审核</Button></div></footer></> : <EmptyState icon={UserRoundCheck} title="选择候选用例">审核内容、评判机制和可见性边界。</EmptyState>}
      </section>
    </div>
  </ProductWorkspace>;
}

function ReviewCheck({ pass, label }: { pass: boolean; label: string }) { return <div className={styles.reviewCheck} data-pass={pass}><span>{pass ? <Check size={12} /> : <CircleAlert size={12} />}</span><p>{label}</p><small>{pass ? "通过" : "需检查"}</small></div>; }

function ToolResultsPage({ targetId: _targetId }: { targetId: string }) {
  const samples = useQuery({ queryKey: ["product", "samples", "workbench"], queryFn: () => getPage<Sample>("/api/samples?limit=200") });
  const queryClient = useQueryClient();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [notice, setNotice] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingSample, setEditingSample] = useState<Sample | null>(null);
  const items = (samples.data?.items ?? []).filter((item) => (filter === "all" || item.status === filter) && `${item.name} ${item.id} ${item.tool_name}`.toLowerCase().includes(query.toLowerCase()));
  useEffect(() => { if (!selectedId && items[0]) setSelectedId(items[0].id); }, [items, selectedId]);
  const selected = samples.data?.items.find((item) => item.id === selectedId) ?? null;
  const review = useMutation({ mutationFn: (status: "approved" | "disabled") => postAction(`/api/samples/${encodeURIComponent(selected!.id)}/review?sample_status=${status}`), onSuccess: async (_, status) => { setNotice(`结果样本已更新为${labelFor(status)}。`); await queryClient.invalidateQueries({ queryKey: ["product", "samples"] }); }, onError: (error) => setNotice(errorMessage(error)) });
  const toolCounts = useMemo(() => { const counts = new Map<string, number>(); (samples.data?.items ?? []).forEach((item) => counts.set(item.tool_name ?? "sequence", (counts.get(item.tool_name ?? "sequence") ?? 0) + 1)); return [...counts.entries()].sort((a, b) => b[1] - a[1]); }, [samples.data]);
  return <ProductWorkspace>
    <PageIntro eyebrow="资产管理 · 工具结果" title="工具结果资产" description="管理可审核的结果样本，并解释结果提供链为什么命中或回退。" actions={<Button icon={<Plus />} onClick={() => { setEditingSample(null); setEditorOpen(true); }} variant="primary">创建结果样本</Button>} />
    <MetricStrip items={[
      { label: "全部结果样本", value: samples.data?.total ?? "—", meta: "单次结果与结果序列", tone: "accent" },
      { label: "已审核", value: samples.data?.items.filter((item) => item.status === "approved").length ?? 0, meta: "可参与确定性回放", tone: "success" },
      { label: "草稿", value: samples.data?.items.filter((item) => item.status === "draft").length ?? 0, meta: "等待人工审核", tone: "warning" },
      { label: "覆盖工具", value: toolCounts.length, meta: "来自结果样本目录" },
    ]} />
    {notice ? <div className={styles.noticeBar}><CircleAlert size={14} />{notice}<button onClick={() => setNotice(null)} type="button"><X size={12} /></button></div> : null}
    <div className={styles.assetWorkbench}>
      <aside className={styles.catalogRail}><header><span className="eyebrow">工具目录</span><strong>覆盖范围</strong></header><button className={filter === "all" ? styles.activeCatalog : ""} onClick={() => setFilter("all")} type="button"><span>全部结果样本</span><strong>{samples.data?.total ?? 0}</strong></button><button className={filter === "approved" ? styles.activeCatalog : ""} onClick={() => setFilter("approved")} type="button"><span>已审核</span><strong>{samples.data?.items.filter((item) => item.status === "approved").length ?? 0}</strong></button><button className={filter === "draft" ? styles.activeCatalog : ""} onClick={() => setFilter("draft")} type="button"><span>待审核</span><strong>{samples.data?.items.filter((item) => item.status === "draft").length ?? 0}</strong></button><div className={styles.catalogDivider}>工具名称</div>{toolCounts.slice(0, 10).map(([tool, count]) => <button key={tool} onClick={() => setQuery(tool)} type="button"><span>{tool}</span><strong>{count}</strong></button>)}</aside>
      <section className={styles.assetListPane}><header><label><Search size={14} /><input aria-label="搜索结果样本" onChange={(event) => setQuery(event.target.value)} placeholder="搜索工具、名称或 ID" value={query} /></label><span>{items.length} 条结果</span></header><div className={styles.columnLabels}><span>结果样本</span><span>类型</span><span>来源</span><span>状态</span></div><div className={styles.masterList}>{items.map((item) => <button className={selectedId === item.id ? styles.selectedMaster : ""} key={item.id} onClick={() => setSelectedId(item.id)} type="button"><span><strong>{item.name}</strong><small>{item.tool_name ?? "结果序列"} · {shortId(item.id)}</small></span><b>{item.sample_kind}</b><em>{item.source_type}</em><Status value={item.status} /></button>)}</div></section>
      <section className={styles.detailPane}>{selected ? <><header className={styles.detailHeader}><div><span className="eyebrow">结果样本详情</span><h2>{selected.name}</h2><code>{selected.id}</code></div><Status value={selected.status} /></header><div className={styles.detailScroll}><section className={styles.sampleIdentity}><div><span>工具</span><strong>{selected.tool_name ?? "结果序列"}</strong></div><div><span>样本类型</span><strong>{selected.sample_kind}</strong></div><div><span>数据来源</span><strong>{selected.source_type}</strong></div></section><DefinitionJson label="参数匹配条件" value={selected.match_arguments ?? {}} /><DefinitionJson label="忽略字段路径" value={selected.ignored_argument_paths ?? []} /><DefinitionJson label="工具执行结果" value={selected.content ?? null} /><section className={styles.definitionBlock}><header><span>来源信息</span><small>不可变来源记录</small></header><div className={styles.visibilityNote}><ShieldCheck size={13} />{selected.source_tool_call_id ? `来源 ToolCall：${selected.source_tool_call_id}` : "手工创建的结果样本草稿"}</div></section></div><footer className={styles.detailFooter}><span>{selected.status === "draft" ? "批准前检查数据结构、敏感信息和匹配冲突" : "非草稿内容不可原地修改"}</span><div>{selected.status === "draft" ? <Button icon={<Settings2 />} onClick={() => { setEditingSample(selected); setEditorOpen(true); }}>编辑</Button> : null}{selected.status !== "disabled" ? <Button disabled={review.isPending} onClick={() => review.mutate("disabled")} variant="danger">停用</Button> : null}{selected.status === "draft" ? <Button disabled={review.isPending} icon={<Check />} onClick={() => review.mutate("approved")} variant="primary">通过审核</Button> : null}</div></footer></> : <EmptyState icon={Database} title="选择结果样本">查看匹配条件、结果和来源证据。</EmptyState>}</section>
    </div>
    {editorOpen ? <SampleEditorDrawer initial={editingSample} onClose={() => setEditorOpen(false)} onSaved={(item) => { setEditorOpen(false); if (item) setSelectedId(item.id); else setSelectedId(null); }} /> : null}
  </ProductWorkspace>;
}

function DefinitionJson({ label, value }: { label: string; value: unknown }) { return <section className={styles.definitionBlock}><header><span>{label}</span><small>JSON</small></header><pre>{pretty(value)}</pre></section>; }

function ProfilesPage({ targetId }: { targetId: string }) {
  const { profiles, target } = useTargetData(targetId);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [editingProfile, setEditingProfile] = useState<ExecutionProfile | null>(null);
  useEffect(() => { if (!selectedId && profiles.data?.items[0]) setSelectedId(profiles.data.items[0].id); }, [profiles.data, selectedId]);
  const selected = profiles.data?.items.find((item) => item.id === selectedId) ?? null;
  return <ProductWorkspace>
    <PageIntro eyebrow="资产管理 · 执行策略" title="执行配置" description="复用工具模式、结果提供链、评判器、模型、并发和超时策略。" actions={<Button icon={<Plus />} onClick={() => { setEditingProfile(null); setEditorOpen(true); }} variant="primary">新建执行配置</Button>} />
    <div className={styles.profileGrid}><section className={styles.profileList}><header><span className="eyebrow">执行配置库</span><strong>{profiles.data?.total ?? 0} 个可复用策略</strong></header>{profiles.data?.items.map((item, index) => <button className={selectedId === item.id ? styles.selectedProfile : ""} key={item.id} onClick={() => setSelectedId(item.id)} type="button"><span className={styles.profileNumber}>{String(index + 1).padStart(2, "0")}</span><div><strong>{item.name}</strong><p>{item.description || "可复用的执行配置"}</p><small>{item.config.provider_chain.map((entry) => entry.name).join(" → ") || "仅观测"}</small></div><Status value={item.config.tool_mode === "observe_only" ? "check" : "ready"} label={toolModeLabel(item.config.tool_mode)} /></button>)}</section><section className={styles.profileDetail}>{selected ? <><header><div><span className="eyebrow">执行配置详情</span><h2>{selected.name}</h2><code>{selected.id}</code></div><Badge tone="accent">运行时冻结快照</Badge></header><div className={styles.profileDetailBody}><section className={styles.modeHero}><span><Settings2 size={18} /></span><div><small>工具模式</small><strong>{toolModeLabel(selected.config.tool_mode)}</strong><p>{toolModeDescription(selected.config.tool_mode)}</p></div></section><section><h3>结果提供链</h3><div className={styles.providerChain}>{selected.config.provider_chain.length ? selected.config.provider_chain.map((provider, index) => <div key={provider.name}><span>{String(index + 1).padStart(2, "0")}</span><strong>{provider.name}</strong><small>{provider.name === "simulation_curator" ? "AgentTeams 专业协作角色" : "确定性结果提供器"}</small></div>) : <p className={styles.mutedText}>仅观测模式不注入工具结果。</p>}</div></section><section><h3>评判与兼容性</h3><div className={styles.configGrid}><div><span>主要评判器</span><strong>{evaluatorLabel(selected.config.primary_evaluator ?? "") || "继承用例配置"}</strong></div><div><span>并发数</span><strong>{selected.config.concurrency}</strong></div><div><span>被测 Agent</span><strong>{target.data?.name ?? targetId}</strong></div><div><span>兼容性</span><strong className={styles.successText}>就绪</strong></div></div></section><DefinitionJson label="冻结配置预览" value={selected.config} /></div><footer><span>执行配置修改只影响未来运行；历史运行继续使用冻结快照。</span><div><Button icon={<Settings2 />} onClick={() => { setEditingProfile(selected); setEditorOpen(true); }}>编辑</Button><Link className="button button--primary" to={`/targets/${encodeURIComponent(targetId)}/evaluation/runs`}><Play size={13} /> 使用此配置评测</Link></div></footer></> : <EmptyState icon={Settings2} title="选择执行配置">查看工具控制和评判策略。</EmptyState>}</section></div>
    {editorOpen ? <ProfileEditorDrawer initial={editingProfile} onClose={() => setEditorOpen(false)} onSaved={(item) => { setEditorOpen(false); if (item) setSelectedId(item.id); else setSelectedId(null); }} /> : null}
  </ProductWorkspace>;
}

function toolModeDescription(value: string) { if (value === "controlled") return "AgentRig 观测工具调用，通过结果提供链生成并注入工具返回。"; if (value === "proxy") return "被测 Agent 通过限定用例运行范围的工具代理执行。"; return "被测 Agent 自行处理工具，AgentRig 只记录并评判证据。"; }
function toolModeLabel(value: string) { if (value === "controlled") return "受控注入"; if (value === "proxy") return "工具代理"; return "仅观测"; }

function RunsPage({ targetId, runId }: { targetId: string; runId: string | null }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { runs, cases, profiles } = useTargetData(targetId);
  const [createOpen, setCreateOpen] = useState(false);
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [selectedProfileId, setSelectedProfileId] = useState("");
  const [createError, setCreateError] = useState<string | null>(null);
  useEffect(() => { if (!selectedCaseId && cases.data?.items[0]) setSelectedCaseId(cases.data.items[0].id); }, [cases.data, selectedCaseId]);
  useEffect(() => { if (!selectedProfileId && profiles.data?.items[0]) setSelectedProfileId(profiles.data.items[0].id); }, [profiles.data, selectedProfileId]);
  const create = useMutation({
    mutationFn: () => createOne<{ run_id: string }>("/api/runs", { case_ids: [selectedCaseId], targets: [{ role: "candidate", target_id: targetId }], profile_id: selectedProfileId || null, overrides: {} }),
    onSuccess: async (result) => { await queryClient.invalidateQueries({ queryKey: ["product", "runs"] }); navigate(`/targets/${encodeURIComponent(targetId)}/evaluation/runs/${result.run_id}`); },
    onError: (error) => setCreateError(errorMessage(error)),
  });
  if (runId) return <RunDetailPage runId={runId} targetId={targetId} />;
  const active = runs.data?.items.filter((item) => ["queued", "running"].includes(item.status)).length ?? 0;
  const completed = runs.data?.items.filter((item) => item.status === "completed").length ?? 0;
  const executionErrors = runs.data?.items.reduce((total, item) => total + item.failed_count, 0) ?? 0;
  return <ProductWorkspace>
    <PageIntro eyebrow="评测管理 · 运行历史" title="运行记录" description="单用例、批量、版本展开和 A/B 对比共享同一异步执行链。" actions={<Button icon={<Play />} onClick={() => setCreateOpen(true)} variant="primary">发起评测</Button>} />
    <MetricStrip items={[
      { label: "全部运行", value: runs.data?.total ?? "—", meta: "完整执行历史", tone: "accent" },
      { label: "执行中", value: active, meta: "排队中与运行中", tone: active ? "warning" : "neutral" },
      { label: "已完成", value: completed, meta: "执行链路已结束", tone: "success" },
      { label: "执行错误", value: executionErrors, meta: "与评测未通过分开统计", tone: executionErrors ? "danger" : "neutral" },
    ]} />
    {createOpen ? <div className={styles.drawerBackdrop}><section className={styles.runDrawer}><header><div><span className="eyebrow">新建评测</span><h2>发起单用例评测</h2></div><button aria-label="关闭" onClick={() => setCreateOpen(false)} type="button"><X size={15} /></button></header><div className={styles.drawerBody}><label>被测 Agent<input readOnly value={targetId} /></label><label>测试用例<select onChange={(event) => setSelectedCaseId(event.target.value)} value={selectedCaseId}>{cases.data?.items.map((item) => <option key={item.id} value={item.id}>{item.name} · {labelFor(item.review_status)}</option>)}</select></label><label>执行配置<select onChange={(event) => setSelectedProfileId(event.target.value)} value={selectedProfileId}>{profiles.data?.items.map((item) => <option key={item.id} value={item.id}>{item.name} · {toolModeLabel(item.config.tool_mode)}</option>)}</select></label><div className={styles.runPreview}><span>计划生成的用例运行</span><strong>01</strong><p>提交后会冻结测试用例、被测 Agent 和执行配置快照。</p></div>{createError ? <QueryFailure value={createError} /> : null}</div><footer><Button onClick={() => setCreateOpen(false)}>取消</Button><Button disabled={!selectedCaseId || create.isPending} icon={<Play />} onClick={() => create.mutate()} variant="primary">确认并运行</Button></footer></section></div> : null}
    <Surface title="全部运行" eyebrow="执行历史" actions={<Button icon={<RefreshCcw />} onClick={() => runs.refetch()} size="sm">刷新</Button>}>
      {runs.error ? <QueryFailure value={runs.error} /> : <RunRows runs={runs.data?.items ?? []} targetId={targetId} />}
    </Surface>
  </ProductWorkspace>;
}

function RunDetailPage({ runId, targetId }: { runId: string; targetId: string }) {
  const run = useQuery({ queryKey: ["product", "run", runId], queryFn: () => getOne<Run>(`/api/runs/${encodeURIComponent(runId)}`), refetchInterval: (query) => ["queued", "running"].includes(query.state.data?.status ?? "") ? 2_000 : false });
  const caseRuns = useQuery({ queryKey: ["product", "run", runId, "case-runs"], queryFn: () => getPage<CaseRun>(`/api/runs/${encodeURIComponent(runId)}/case-runs?limit=200`), refetchInterval: ["queued", "running"].includes(run.data?.status ?? "") ? 2_000 : false });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [eventFilter, setEventFilter] = useState("all");
  useEffect(() => { if (!selectedId && caseRuns.data?.items[0]) setSelectedId(caseRuns.data.items[0].id); }, [caseRuns.data, selectedId]);
  const detail = useQuery({ queryKey: ["product", "case-run", selectedId], queryFn: () => getOne<CaseRun>(`/api/case-runs/${encodeURIComponent(selectedId!)}`), enabled: Boolean(selectedId), refetchInterval: ["queued", "running"].includes(caseRuns.data?.items.find((item) => item.id === selectedId)?.status ?? "") ? 2_000 : false });
  const outcomes = summarizeOutcomes(caseRuns.data?.items ?? []);
  const invocationIds = useMemo(() => {
    const ids = new Set<string>();
    detail.data?.evaluations?.forEach((item) => {
      const meta = item.model_metadata as Record<string, unknown> | undefined;
      const single = meta?.agent_invocation_id;
      const many = meta?.agent_invocation_ids;
      if (typeof single === "string") ids.add(single);
      if (Array.isArray(many)) many.forEach((id) => typeof id === "string" && ids.add(id));
    });
    return [...ids];
  }, [detail.data]);
  const filteredEvents = (detail.data?.events ?? []).filter((event) => eventFilter === "all" || event.event_type === eventFilter);
  return <ProductWorkspace>
    <PageIntro eyebrow="运行详情 · 完整证据" title={`Run ${shortId(runId)}`} description="执行状态、评测结论、AgentTeams 与冻结配置保持可审计关联。" actions={<><Link className="button" to={`/targets/${encodeURIComponent(targetId)}/evaluation/runs`}>返回列表</Link><Button icon={<RefreshCcw />} onClick={() => { void run.refetch(); void caseRuns.refetch(); }}>刷新</Button></>} />
    <MetricStrip items={[
      { label: "运行状态", value: run.data ? labelFor(run.data.status) : "—", meta: "异步执行生命周期", tone: run.data ? toneFor(run.data.status) : "neutral" },
      { label: "评测通过", value: outcomes.pass, meta: `占已评测项 ${percentage(outcomes.pass, outcomes.total)}`, tone: "success" },
      { label: "评测未通过", value: outcomes.fail, meta: "权威评测结论", tone: outcomes.fail ? "danger" : "neutral" },
      { label: "证据不足", value: outcomes.inconclusive, meta: "无法形成可靠结论", tone: outcomes.inconclusive ? "warning" : "neutral" },
      { label: "执行错误", value: run.data?.failed_count ?? "—", meta: "平台或被测 Agent 错误", tone: run.data?.failed_count ? "danger" : "neutral" },
    ]} />
    <div className={styles.evidenceWorkbench}>
      <aside className={styles.caseRunRail}><header><div><span className="eyebrow">用例运行</span><strong>{caseRuns.data?.total ?? 0} 个原子结果</strong></div><Status value={run.data?.status ?? "queued"} /></header><div className={styles.caseRunList}>{caseRuns.data?.items.map((item) => <button className={selectedId === item.id ? styles.selectedCaseRun : ""} key={item.id} onClick={() => setSelectedId(item.id)} type="button"><span><strong>{item.case_id}</strong><small>{item.version ?? "默认版本"} · 第 {item.repeat_index} 次{item.comparison_role ? ` · ${comparisonRoleLabel(item.comparison_role)}` : ""}</small></span><Status value={item.evaluation_state} /></button>)}</div><footer><span>配置快照</span><small>测试用例、被测 Agent 与执行配置均已冻结</small></footer></aside>
      <main className={styles.evidenceTimeline}><header><div><span className="eyebrow">运行证据时间线</span><h2>{detail.data?.case_id ?? "选择用例运行"}</h2><code>{detail.data?.id ?? "—"}</code></div><div className={styles.eventFilters}><button className={eventFilter === "all" ? styles.activeEventFilter : ""} onClick={() => setEventFilter("all")} type="button">全部</button>{["tool_call", "provider_attempt", "tool_result", "validation", "error"].map((value) => <button className={eventFilter === value ? styles.activeEventFilter : ""} key={value} onClick={() => setEventFilter(value)} type="button">{eventTypeLabel(value)}</button>)}</div></header>
        {detail.isLoading ? <EmptyState icon={Clock3} title="正在读取证据">加载完整 CaseRun、Event 和 Evaluation。</EmptyState> : null}
        {detail.error ? <QueryFailure value={detail.error} /> : null}
        <div className={styles.eventTimeline}>{filteredEvents.map((event) => <EvidenceEvent event={event} key={event.id} />)}{detail.data && !filteredEvents.length ? <EmptyState icon={FileSearch} title="没有匹配事件">调整事件类型筛选。</EmptyState> : null}</div>
      </main>
      <aside className={styles.verdictRail}><header><span className="eyebrow">权威评测结论</span><Status value={detail.data?.evaluation_state ?? "pending"} /></header>{detail.data ? <><section className={styles.verdictHero}><small>最终结论</small><strong data-tone={toneFor(detail.data.evaluation_state)}>{labelFor(detail.data.evaluation_state)}</strong><p>主要评判器 · {evaluatorLabel(detail.data.primary_evaluator)}</p></section><section className={styles.verdictSection}><h3>评判记录</h3>{detail.data.evaluations?.map((evaluation, index) => <EvaluationCard key={String(evaluation.id ?? index)} value={evaluation} />)}{!detail.data.evaluations?.length ? <p className={styles.mutedText}>尚无评判记录。</p> : null}</section><section className={styles.verdictSection}><h3>AgentTeams 协作调用</h3>{invocationIds.map((id) => <Link className={styles.resourceLink} key={id} to={`/evaluator-teams?invocation=${encodeURIComponent(id)}`}><ShieldCheck size={12} /><code>{shortId(id)}</code><ChevronRight size={12} /></Link>)}{!invocationIds.length ? <p className={styles.mutedText}>当前评测没有专业角色调用引用。</p> : null}</section><details className={styles.snapshotDetails}><summary>冻结快照 <ChevronRight size={12} /></summary><DefinitionJson label="被测 Agent" value={detail.data.target_snapshot ?? {}} /><DefinitionJson label="执行配置" value={detail.data.profile_snapshot ?? {}} /></details></> : <EmptyState icon={ClipboardCheck} title="选择用例运行">查看事件、裁决与冻结快照。</EmptyState>}</aside>
    </div>
  </ProductWorkspace>;
}

function EvidenceEvent({ event }: { event: NonNullable<CaseRun["events"]>[number] }) {
  const Icon = eventIcon(event.event_type);
  const tone = toneFor(event.event_type === "error" ? "error" : event.event_type === "validation" && event.payload.valid === false ? "fail" : "neutral");
  return <details className={styles.evidenceEvent} data-tone={tone}><summary><span className={styles.eventSeq}>{String(event.seq).padStart(2, "0")}</span><span className={styles.eventIcon}><Icon size={13} /></span><div><strong>{eventTypeLabel(event.event_type)}</strong><small>{eventSummary(event)}</small></div><code>{shortId(event.id)}</code><ChevronRight size={13} /></summary><div className={styles.eventPayload}><div><span>事件 ID</span><code>{event.id}</code></div><pre>{pretty(event.payload)}</pre></div></details>;
}

function EvaluationCard({ value }: { value: Record<string, unknown> }) {
  const criteria = Array.isArray(value.criteria) ? value.criteria as Array<Record<string, unknown>> : [];
  return <article className={styles.evaluationCard}><header><div><strong>{evaluatorLabel(String(value.evaluator_type ?? "evaluator"))}</strong><small>{String(value.evaluator_source ?? "")}</small></div><Status value={String(value.verdict ?? value.status ?? "pending")} /></header><p>{String(value.summary ?? "暂无评判摘要。")}</p>{criteria.map((criterion, index) => <div className={styles.criterion} key={index}><span>{criterion.verdict === "pass" ? <Check size={11} /> : <X size={11} />}</span><p>{String(criterion.criterion ?? "评判条件")}</p><small>{Array.isArray(criterion.evidence_refs) ? `${criterion.evidence_refs.length} 条证据引用` : "无证据引用"}</small></div>)}</article>;
}

function eventIcon(value: string): LucideIcon { const icons: Record<string, LucideIcon> = { user_message: UserRoundCheck, assistant_text: MessageSquare, assistant_message: MessageSquare, tool_call: Wrench, provider_attempt: Layers3, tool_result: Database, validation: ShieldCheck, usage: BarChart3, error: TriangleAlert, driver_request: Network, driver_session: CircleDot }; return icons[value] ?? CircleDot; }
function eventSummary(event: NonNullable<CaseRun["events"]>[number]) { const payload = event.payload; if (event.event_type === "tool_call") return String(payload.tool_name ?? "工具调用"); if (event.event_type === "provider_attempt") return `${String(payload.provider ?? "结果提供器")} · ${labelFor(String(payload.status ?? "尝试调用"))}`; if (event.event_type === "tool_result") return `${String(payload.tool_name ?? "工具")} · ${String(payload.source ?? "返回结果")}`; if (event.event_type === "assistant_text" || event.event_type === "assistant_message") return String(payload.text ?? "Agent 回复").slice(0, 80); if (event.event_type === "user_message") return String(payload.text ?? "用户输入").slice(0, 80); if (event.event_type === "error") return String(payload.message ?? payload.error ?? "执行错误"); return formatDate(event.created_at); }

function ConversationPage({ targetId }: { targetId: string }) {
  const queryClient = useQueryClient();
  const { target, profiles } = useTargetData(targetId);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [newSession, setNewSession] = useState(false);
  const [profileId, setProfileId] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [evidenceFilter, setEvidenceFilter] = useState("all");
  useEffect(() => { if (!profileId && profiles.data?.items[0]) setProfileId(profiles.data.items[0].id); }, [profileId, profiles.data]);
  const history = useQuery({ queryKey: ["product", "target-chats", targetId], queryFn: () => listTargetChats(targetId), refetchInterval: 5_000 });
  useEffect(() => { if (!sessionId && !newSession && history.data?.items[0]) setSessionId(history.data.items[0].id); }, [history.data, newSession, sessionId]);
  const session = useQuery({ queryKey: ["product", "target-chat", sessionId], queryFn: () => getTargetChat(sessionId!), enabled: Boolean(sessionId), refetchInterval: sessionId ? 2_000 : false });
  const send = useMutation({
    mutationFn: async (content: string) => {
      const active = sessionId && session.data?.status === "open" ? await getTargetChat(sessionId) : await createTargetChat(targetId, profileId || null);
      if (active.id !== sessionId) setSessionId(active.id);
      return sendTargetChatMessage(active.id, content);
    },
    onSuccess: async (value) => { setSessionId(value.id); setNewSession(false); setMessage(""); setError(null); await queryClient.invalidateQueries({ queryKey: ["product", "target-chats", targetId] }); },
    onError: (value) => setError(errorMessage(value)),
  });
  const close = useMutation({ mutationFn: () => closeTargetChat(sessionId!), onSuccess: async () => { setNotice("会话已结束，历史证据已持久化。"); await queryClient.invalidateQueries({ queryKey: ["product", "target-chats", targetId] }); await session.refetch(); }, onError: (value) => setError(errorMessage(value)) });
  const draftCase = useMutation({ mutationFn: () => createDraftCaseFromTargetChat(sessionId!), onSuccess: async (item) => { setNotice(`已生成用例草稿：${item.name}`); await queryClient.invalidateQueries({ queryKey: ["product", "cases"] }); }, onError: (value) => setError(errorMessage(value)) });
  const draftSample = useMutation({ mutationFn: (toolCallId: string) => createDraftSampleFromTargetChat(sessionId!, toolCallId), onSuccess: async (item) => { setNotice(`已生成结果样本草稿：${item.name}`); await queryClient.invalidateQueries({ queryKey: ["product", "samples"] }); }, onError: (value) => setError(errorMessage(value)) });
  const events = session.data?.events ?? [];
  const evidence = events.filter((event) => !["user_message", "assistant_message", "assistant_text"].includes(event.event_type) && (evidenceFilter === "all" || event.event_type === evidenceFilter));
  return <div className={styles.conversationWorkspace}>
    <aside className={styles.chatSessions}><header><div><span className="eyebrow">验证会话</span><strong>对话历史</strong></div><MessageSquare size={15} /></header><button className={styles.newChat} onClick={() => { setSessionId(null); setNewSession(true); setError(null); setNotice(null); }} type="button"><Plus size={13} /> 新建验证会话</button><div className={styles.chatSessionList}>{history.data?.items.map((item) => { const first = item.events.find((event) => event.event_type === "user_message"); return <button className={sessionId === item.id ? styles.activeChat : ""} key={item.id} onClick={() => { setSessionId(item.id); setNewSession(false); setError(null); }} type="button"><span><MessageSquare size={12} /><strong>{String(first?.payload.content ?? "未命名验证会话")}</strong></span><small>{shortId(item.id)} · {item.events.length} 个事件 · {labelFor(item.status)}</small></button>; })}{!history.data?.items.length ? <p>发送第一条消息后创建真实会话。</p> : null}</div><footer><span><i />{target.data?.name ?? targetId}</span><small>{target.data?.driver_type ?? "正在读取驱动"}</small></footer></aside>
    <main className={styles.targetChat}><header><div><span className={styles.targetMark}><Bot size={17} /></span><div><span className="eyebrow">直接连接被测 Agent</span><h1>{target.data?.name ?? "lassist"}</h1></div></div><div>{sessionId && events.some((event) => event.event_type === "user_message") ? <Button disabled={draftCase.isPending} icon={<TestTube2 />} onClick={() => draftCase.mutate()} size="sm">生成用例草稿</Button> : null}<select aria-label="对话执行配置" onChange={(event) => setProfileId(event.target.value)} value={profileId}>{profiles.data?.items.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select><Status value={session.data?.status === "open" || !session.data ? "ready" : session.data.status} label={session.data?.status === "open" || !session.data ? "被测 Agent 就绪" : undefined} /></div></header>
      {error ? <div className={styles.noticeBar}><CircleAlert size={14} />{error}<button onClick={() => setError(null)} type="button"><X size={12} /></button></div> : null}
      {notice ? <div className={styles.noticeBar}><CheckCircle2 size={14} />{notice}<button onClick={() => setNotice(null)} type="button"><X size={12} /></button></div> : null}
      <div className={styles.chatMessages}>{events.filter((event) => ["user_message", "assistant_message"].includes(event.event_type)).map((event) => <TargetChatMessage event={event} key={event.seq} />)}{!events.length ? <div className={styles.chatWelcome}><span><Bot size={24} /></span><small>LASSIST · 实时连接</small><h2>直接验证被测 Agent</h2><p>这里的消息会真实发送给 lassist；工具调用与结果提供证据显示在右侧。</p><div>{["帮我分析一下如何让照片主体更突出", "我想对一张人像照片进行自然美化", "解释你可以使用哪些修图能力"].map((prompt) => <button key={prompt} onClick={() => setMessage(prompt)} type="button">{prompt}<ChevronRight size={12} /></button>)}</div></div> : null}{send.isPending ? <div className={styles.targetTyping}><span><Bot size={13} /></span><p><strong>lassist</strong><small>正在处理消息和工具调用…</small></p></div> : null}</div>
      <form className={styles.chatComposer} onSubmit={(event) => { event.preventDefault(); const value = message.trim(); if (value) send.mutate(value); }}><textarea disabled={send.isPending} onChange={(event) => setMessage(event.target.value)} onKeyDown={(event) => { if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); event.currentTarget.form?.requestSubmit(); } }} placeholder={session.data && session.data.status !== "open" ? "输入消息会自动创建新的验证会话…" : "向 lassist 发送真实测试消息…"} value={message} /><footer><span>当前执行配置 · {profiles.data?.items.find((item) => item.id === profileId)?.name ?? "默认配置"}</span><div>{sessionId && session.data?.status === "open" ? <button disabled={close.isPending} onClick={() => close.mutate()} type="button">结束会话</button> : null}<Button disabled={!message.trim() || send.isPending} variant="primary">发送 <ArrowRight size={13} /></Button></div></footer></form>
    </main>
    <aside className={styles.chatEvidence}><header><div><span className="eyebrow">实时运行证据</span><strong>工具与协议</strong></div><Badge tone={evidence.length ? "accent" : "neutral"}>{evidence.length}</Badge></header><div className={styles.evidenceTabs}><button className={evidenceFilter === "all" ? styles.activeTab : ""} onClick={() => setEvidenceFilter("all")} type="button">全部</button><button className={evidenceFilter === "tool_call" ? styles.activeTab : ""} onClick={() => setEvidenceFilter("tool_call")} type="button">工具调用</button><button className={evidenceFilter === "provider_attempt" ? styles.activeTab : ""} onClick={() => setEvidenceFilter("provider_attempt")} type="button">结果提供</button></div><div className={styles.chatEvidenceList}>{evidence.map((event) => { const toolCallId = event.event_type === "tool_call" ? String(event.payload.tool_call_id ?? "") : ""; const hasResult = toolCallId && events.some((candidate) => candidate.event_type === "tool_result" && candidate.payload.tool_call_id === toolCallId); return <details key={event.seq}><summary><span><Wrench size={12} /></span><p><strong>{eventTypeLabel(event.event_type)}</strong><small>{targetChatSummary(event)}</small></p><ChevronRight size={12} /></summary><pre>{pretty(event.payload)}</pre>{hasResult ? <div className={styles.evidenceAction}><Button disabled={draftSample.isPending} icon={<Database />} onClick={() => draftSample.mutate(toolCallId)} size="sm">生成结果样本草稿</Button></div> : null}</details>; })}{!evidence.length ? <EmptyState icon={Wrench} title="等待运行证据">发送消息后，这里展示协议、工具调用、结果提供尝试和工具返回。</EmptyState> : null}</div><footer><ShieldCheck size={12} /><span>历史会话与脱敏证据已持久化</span></footer></aside>
  </div>;
}

function TargetChatMessage({ event }: { event: TargetChatEvent }) {
  const user = event.event_type === "user_message";
  return <article className={`${styles.targetMessage} ${user ? styles.targetUserMessage : styles.targetAssistantMessage}`}><span>{user ? <UserRoundCheck size={13} /> : <Bot size={13} />}</span><div><small>{user ? "你" : "LASSIST"}</small><p>{String(event.payload.content ?? event.payload.text ?? "")}</p><footer>#{event.seq} · {new Date(event.created_at).toLocaleTimeString("zh-CN")}</footer></div></article>;
}

function eventTypeLabel(value: string) { const labels: Record<string, string> = { session_started: "会话开始", driver_request: "驱动请求", driver_session: "驱动会话", user_message: "用户消息", assistant_text: "Agent 文本", assistant_message: "Agent 消息", tool_call: "工具调用", provider_attempt: "结果提供尝试", validation: "结构校验", tool_result: "工具返回", usage: "用量记录", error: "运行错误" }; return labels[value] ?? value.replaceAll("_", " "); }

function targetChatSummary(event: TargetChatEvent) { if (event.event_type === "tool_call") return String(event.payload.tool_name ?? "工具调用"); if (event.event_type === "provider_attempt") return `${String(event.payload.provider ?? "结果提供器")} · ${labelFor(String(event.payload.status ?? "尝试调用"))}`; if (event.event_type === "tool_result") return `${String(event.payload.tool_name ?? "工具")} · 返回结果`; if (event.event_type === "error") return String(event.payload.message ?? "运行错误"); return `事件 #${event.seq}`; }

function ComparisonsPage({ targetId }: { targetId: string }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const { target, runs, cases, profiles } = useTargetData(targetId);
  const [createOpen, setCreateOpen] = useState(false);
  const [baseline, setBaseline] = useState("");
  const [candidate, setCandidate] = useState("");
  const [profileId, setProfileId] = useState("");
  const [caseIds, setCaseIds] = useState<string[]>([]);
  const [createError, setCreateError] = useState<string | null>(null);
  useEffect(() => { const versions = target.data?.versions ?? []; if (!baseline && versions[0]) setBaseline(versions[0].version); if (!candidate && versions[1]) setCandidate(versions[1].version); }, [baseline, candidate, target.data]);
  useEffect(() => { if (!profileId && profiles.data?.items[0]) setProfileId(profiles.data.items[0].id); }, [profileId, profiles.data]);
  useEffect(() => { if (!caseIds.length && cases.data?.items.length) { const approved = cases.data.items.filter((item) => item.review_status === "approved").map((item) => item.id); setCaseIds(approved.length ? approved : cases.data.items.map((item) => item.id)); } }, [caseIds.length, cases.data]);
  const create = useMutation({ mutationFn: () => createOne<{ run_id: string }>("/api/runs", { case_ids: caseIds, targets: [{ role: "baseline", target_id: targetId, version: baseline }, { role: "candidate", target_id: targetId, version: candidate }], profile_id: profileId || null, overrides: {} }), onSuccess: async (result) => { await queryClient.invalidateQueries({ queryKey: ["product", "runs", targetId] }); navigate(`/targets/${encodeURIComponent(targetId)}/evaluation/runs/${result.run_id}`); }, onError: (error) => setCreateError(errorMessage(error)) });
  const runDetails = useQuery({
    queryKey: ["product", "comparison-candidates", runs.data?.items.map((item) => item.id)],
    enabled: Boolean(runs.data?.items.length),
    queryFn: async () => {
      const values = await Promise.all((runs.data?.items ?? []).slice(0, 20).map(async (run) => ({ run, page: await getPage<CaseRun>(`/api/runs/${encodeURIComponent(run.id)}/case-runs?limit=200`) })));
      return values.filter(({ page }) => page.items.some((item) => item.comparison_role));
    },
  });
  const latest = runDetails.data?.[0];
  const pairs = useMemo(() => comparisonPairs(latest?.page.items ?? []), [latest]);
  const counts = pairs.reduce((value, item) => ({ ...value, [item.change]: (value[item.change] ?? 0) + 1 }), {} as Record<string, number>);
  return <ProductWorkspace>
    <PageIntro eyebrow="评测管理 · 基线与候选版本" title="版本对比" description="使用相同用例与执行配置对齐基线版本和候选版本，定位真实回归。" actions={<Button icon={<GitCompareArrows />} onClick={() => setCreateOpen(true)} variant="primary">新建版本对比</Button>} />
    {createOpen ? <div className={styles.drawerBackdrop}><section className={styles.runDrawer}><header><div><span className="eyebrow">新建 A/B 评测</span><h2>创建版本对比</h2></div><button aria-label="关闭" onClick={() => setCreateOpen(false)} type="button"><X size={15} /></button></header><div className={styles.drawerBody}><label>被测 Agent<input readOnly value={target.data?.name ?? targetId} /></label><div className={styles.formGrid}><label>基线版本<select onChange={(event) => setBaseline(event.target.value)} value={baseline}>{target.data?.versions.map((item) => <option key={item.version} value={item.version}>{item.version}</option>)}</select></label><label>候选版本<select onChange={(event) => setCandidate(event.target.value)} value={candidate}>{target.data?.versions.map((item) => <option key={item.version} value={item.version}>{item.version}</option>)}</select></label></div><label>执行配置<select onChange={(event) => setProfileId(event.target.value)} value={profileId}>{profiles.data?.items.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label><fieldset className={styles.casePicker}><legend>测试用例 · 已选择 {caseIds.length} 个</legend>{cases.data?.items.map((item) => <label key={item.id}><input checked={caseIds.includes(item.id)} onChange={(event) => setCaseIds((current) => event.target.checked ? [...current, item.id] : current.filter((id) => id !== item.id))} type="checkbox" /><span><strong>{item.name}</strong><small>{labelFor(item.review_status)} · {item.supported_versions.join(", ") || "全部版本"}</small></span></label>)}</fieldset><div className={styles.runPreview}><span>计划生成的用例运行</span><strong>{String(caseIds.length * 2).padStart(2, "0")}</strong><p>每个用例生成一组通过对比组 ID 关联的基线与候选运行。</p></div>{target.data && target.data.versions.length < 2 ? <QueryFailure value="当前被测 Agent 至少需要两个版本才能执行对比。" /> : null}{createError ? <QueryFailure value={createError} /> : null}</div><footer><Button onClick={() => setCreateOpen(false)}>取消</Button><Button disabled={create.isPending || !caseIds.length || !baseline || !candidate || baseline === candidate || !profileId} icon={<GitCompareArrows />} onClick={() => create.mutate()} variant="primary">确认并运行</Button></footer></section></div> : null}
    <div className={styles.comparisonHero}><div><span className="eyebrow">基线版本</span><strong>{target.data?.versions?.[0]?.version ?? "未选择"}</strong><small>{target.data?.name ?? targetId}</small></div><span className={styles.compareArrow}><ArrowRight size={17} /></span><div><span className="eyebrow">候选版本</span><strong>{target.data?.versions?.[1]?.version ?? "未选择"}</strong><small>{target.data?.name ?? targetId}</small></div><div className={styles.compareVerdict}><span>对比结论</span><Status value={(counts.regressed ?? 0) > 0 ? "fail" : pairs.length ? "pass" : "check"} label={(counts.regressed ?? 0) > 0 ? "发现回归" : pairs.length ? "未发现回归" : "等待对比运行"} /></div></div>
    <MetricStrip items={[
      { label: "可对比用例", value: pairs.length, meta: latest ? shortId(latest.run.id) : "暂无版本对比运行", tone: "accent" },
      { label: "效果提升", value: counts.improved ?? 0, meta: "未通过 → 通过", tone: "success" },
      { label: "效果回归", value: counts.regressed ?? 0, meta: "通过 → 未通过或证据不足", tone: counts.regressed ? "danger" : "neutral" },
      { label: "保持不变", value: (counts.unchanged ?? 0), meta: "两侧权威结论一致" },
    ]} />
    <Surface title="用例对比矩阵" eyebrow="成对用例运行">
      {pairs.length ? <div className={styles.comparisonTable}><div className={styles.comparisonHeader}><span>测试用例</span><span>基线结论</span><span>候选结论</span><span>变化</span><span /></div>{pairs.map((pair) => <div key={pair.key}><span><strong>{pair.baseline?.case_id ?? pair.candidate?.case_id}</strong><small>{pair.key}</small></span><Status value={pair.baseline?.evaluation_state ?? "missing"} /><Status value={pair.candidate?.evaluation_state ?? "missing"} /><Badge tone={pair.change === "regressed" ? "danger" : pair.change === "improved" ? "success" : "neutral"}>{comparisonChangeLabel(pair.change)}</Badge><Link to={latest ? `/targets/${encodeURIComponent(targetId)}/evaluation/runs/${latest.run.id}` : "#"}>证据 <ChevronRight size={12} /></Link></div>)}</div> : <EmptyState icon={GitCompareArrows} title="尚无 A/B 版本对比">创建包含基线和候选版本的运行后，这里会按对比组 ID 自动配对。</EmptyState>}
    </Surface>
  </ProductWorkspace>;
}

function comparisonPairs(items: CaseRun[]) {
  const grouped = new Map<string, { key: string; baseline?: CaseRun; candidate?: CaseRun }>();
  items.forEach((item) => { if (!item.comparison_pair_id || !item.comparison_role) return; const value = grouped.get(item.comparison_pair_id) ?? { key: item.comparison_pair_id }; value[item.comparison_role as "baseline" | "candidate"] = item; grouped.set(item.comparison_pair_id, value); });
  return [...grouped.values()].map((item) => { const left = item.baseline?.evaluation_state; const right = item.candidate?.evaluation_state; let change = "unchanged"; if (!left || !right) change = "not_comparable"; else if (left === "pass" && right !== "pass") change = "regressed"; else if (left !== "pass" && right === "pass") change = "improved"; else if (left !== right) change = "needs_review"; return { ...item, change }; });
}

function comparisonChangeLabel(value: string) { const labels: Record<string, string> = { improved: "提升", regressed: "回归", unchanged: "不变", not_comparable: "不可对比", needs_review: "需要复核" }; return labels[value] ?? value; }
function comparisonRoleLabel(value: string) { return value === "baseline" ? "基线版本" : value === "candidate" ? "候选版本" : value; }

function ReportsPage({ targetId }: { targetId: string }) {
  const { runs, target } = useTargetData(targetId);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  useEffect(() => { if (!selectedId && runs.data?.items[0]) setSelectedId(runs.data.items[0].id); }, [runs.data, selectedId]);
  const selected = runs.data?.items.find((item) => item.id === selectedId) ?? null;
  const caseRuns = useQuery({ queryKey: ["product", "report", selectedId], queryFn: () => getPage<CaseRun>(`/api/runs/${encodeURIComponent(selectedId!)}/case-runs?limit=200`), enabled: Boolean(selectedId) });
  const outcomes = summarizeOutcomes(caseRuns.data?.items ?? []);
  function downloadReport() {
    if (!selected) return;
    const targetName = target.data?.name ?? targetId;
    const failures = (caseRuns.data?.items ?? []).filter((item) => item.evaluation_state === "fail" || item.error_code);
    const markdown = [`# ${targetName} 评测报告`, "", `- 运行编号：\`${selected.id}\``, `- 执行状态：${labelFor(selected.status)}`, `- 生成时间：${new Date().toISOString()}`, `- 通过率：${percentage(outcomes.pass, outcomes.total)}`, `- 通过 / 未通过 / 证据不足：${outcomes.pass} / ${outcomes.fail} / ${outcomes.inconclusive}`, `- 执行错误：${selected.failed_count}`, "", "## 执行范围", "", ...selected.resolved_case_ids.map((id) => `- \`${id}\``), "", "## 主要失败", "", ...(failures.length ? failures.map((item) => `- **${item.case_id}** — ${item.error_message || String(item.summary?.evaluation_summary ?? labelFor(item.evaluation_state))}`) : ["无失败或执行错误。"]), "", `> 根据 AgentRig 不可变运行事实生成。被测 Agent：\`${targetId}\`。`].join("\n");
    downloadText(`agentrig-${targetId}-${selected.id}.md`, markdown, "text/markdown;charset=utf-8");
  }
  return <ProductWorkspace>
    <PageIntro eyebrow="评测管理 · 冻结报告" title="评测报告" description="把一次真实运行的范围、结果、失败与证据组织为可验收结论。" actions={<Button disabled={!selected || caseRuns.isLoading} icon={<Download />} onClick={downloadReport}>导出 Markdown</Button>} />
    <div className={styles.reportWorkspace}><Surface title="报告目录" eyebrow={`${runs.data?.total ?? 0} 份运行报告`} className={styles.reportList}><div className={styles.masterList}>{runs.data?.items.map((run) => <button className={selectedId === run.id ? styles.selectedMaster : ""} key={run.id} onClick={() => setSelectedId(run.id)} type="button"><span><strong>Run {shortId(run.id)}</strong><small>{formatDate(run.created_at)} · {run.resolved_case_ids.length} 个用例</small></span><Status value={run.status} /></button>)}</div></Surface><article className={styles.reportDocument}>{selected ? <><header><div><span className="eyebrow">AgentRig 评测验收报告</span><h1>{target.data?.name ?? targetId} 评测验收报告</h1><p>Run {selected.id}</p></div><Status value={outcomes.fail ? "fail" : outcomes.total ? "pass" : selected.status} /></header><section className={styles.reportSummary}><div><small>执行状态</small><strong>{labelFor(selected.status)}</strong><span>{formatDate(selected.finished_at ?? selected.created_at)}</span></div><div><small>已评测</small><strong>{outcomes.total}</strong><span>计划 {selected.total_count} 个 CaseRun</span></div><div><small>通过率</small><strong>{percentage(outcomes.pass, outcomes.total)}</strong><span>{outcomes.pass} 个通过 · {outcomes.fail} 个未通过</span></div><div><small>证据不足</small><strong>{outcomes.inconclusive}</strong><span>无法形成可靠结论</span></div></section><ReportSection number="01" title="执行范围"><div className={styles.reportScope}><div><span>被测 Agent</span><strong>{target.data?.name ?? targetId}</strong></div><div><span>测试用例</span><strong>{selected.resolved_case_ids.length}</strong></div><div><span>运行编号</span><code>{selected.id}</code></div><div><span>资产快照</span><strong>已冻结</strong></div></div></ReportSection><ReportSection number="02" title="结果分布"><div className={styles.outcomeBand}><div data-tone="success"><strong>{outcomes.pass}</strong><span>通过</span></div><div data-tone="danger"><strong>{outcomes.fail}</strong><span>未通过</span></div><div data-tone="warning"><strong>{outcomes.inconclusive}</strong><span>证据不足</span></div><div><strong>{selected.failed_count}</strong><span>执行错误</span></div></div></ReportSection><ReportSection number="03" title="主要失败">{caseRuns.data?.items.filter((item) => item.evaluation_state === "fail" || item.error_code).map((item) => <Link className={styles.reportFailure} key={item.id} to={`/targets/${encodeURIComponent(targetId)}/evaluation/runs/${selected.id}`}><span><XCircle size={13} /></span><div><strong>{item.case_id}</strong><p>{item.error_message || String(item.summary?.evaluation_summary ?? "权威评判结果为未通过")}</p></div><ChevronRight size={13} /></Link>)}{!caseRuns.data?.items.some((item) => item.evaluation_state === "fail" || item.error_code) ? <p className={styles.reportPositive}><CheckCircle2 size={14} /> 当前报告没有失败或执行错误。</p> : null}</ReportSection><footer><span>由不可变运行事实生成</span><Link to={`/targets/${encodeURIComponent(targetId)}/evaluation/runs/${selected.id}`}>打开完整证据 <ExternalLink size={12} /></Link></footer></> : <EmptyState icon={ClipboardCheck} title="选择一份运行报告">报告根据真实 Run 和 CaseRun 动态生成。</EmptyState>}</article></div>
  </ProductWorkspace>;
}

function ReportSection({ number, title, children }: { number: string; title: string; children: ReactNode }) { return <section className={styles.reportSection}><header><span>{number}</span><h2>{title}</h2></header>{children}</section>; }

function useLatestCaseRuns(targetId: string) {
  const { runs } = useTargetData(targetId);
  return useQuery({ queryKey: ["product", "latest-case-runs", runs.data?.items.slice(0, 8).map((item) => item.id)], enabled: Boolean(runs.data?.items.length), queryFn: async () => { const pages = await Promise.all((runs.data?.items ?? []).slice(0, 8).map(async (run) => ({ run, page: await getPage<CaseRun>(`/api/runs/${encodeURIComponent(run.id)}/case-runs?limit=200`) }))); return pages; } });
}

function ObservabilityPage({ targetId }: { targetId: string }) {
  const { runs, cases, samples } = useTargetData(targetId);
  const history = useLatestCaseRuns(targetId);
  const all = history.data?.flatMap((entry) => entry.page.items) ?? [];
  const outcomes = summarizeOutcomes(all);
  const flaky = flakyCases(all);
  const providerErrors = all.filter((item) => item.error_code === "provider_exhausted").length;
  const points = (history.data ?? []).slice().reverse().map((entry) => ({ id: entry.run.id, outcomes: summarizeOutcomes(entry.page.items), date: formatDate(entry.run.created_at) }));
  return <ProductWorkspace>
    <PageIntro eyebrow="观测与分析 · 评测数据" title="观测总览" description="从真实评测事实观察质量、执行可靠性、Provider 和资产健康度。" actions={<div className={styles.dataSource}><i />评测数据已连接</div>} />
    <MetricStrip items={[
      { label: "评测通过率", value: percentage(outcomes.pass, outcomes.total), meta: `最近 ${outcomes.total} 个评测结论`, tone: "success" },
      { label: "结果不稳定用例", value: flaky.length, meta: "重复运行出现不同结论", tone: flaky.length ? "warning" : "neutral" },
      { label: "Provider 耗尽", value: providerErrors, meta: "执行基础设施错误", tone: providerErrors ? "danger" : "neutral" },
      { label: "待审核资产", value: (cases.data?.items.filter((item) => item.review_status === "draft").length ?? 0) + (samples.data?.items.filter((item) => item.status === "draft").length ?? 0), meta: "用例草稿与结果样本草稿" },
    ]} />
    <div className={styles.observabilityGrid}><Surface title="评测结果趋势" eyebrow="最近 8 次运行" className={styles.trendPanel}><div className={styles.trendChart}>{points.map((point) => { const total = Math.max(point.outcomes.total, 1); return <div key={point.id} title={`${point.date} · ${point.outcomes.total} 个评测结论`}><span><i data-tone="success" style={{ height: percentage(point.outcomes.pass, total) }} /><i data-tone="danger" style={{ height: percentage(point.outcomes.fail, total) }} /><i data-tone="warning" style={{ height: percentage(point.outcomes.inconclusive, total) }} /></span><small>{shortId(point.id).split("_")[1]}</small></div>; })}{!points.length ? <EmptyState icon={BarChart3} title="暂无趋势数据">完成多个运行后显示真实结论分布。</EmptyState> : null}</div><footer><span><i data-tone="success" />通过</span><span><i data-tone="danger" />未通过</span><span><i data-tone="warning" />证据不足</span></footer></Surface><Surface title="运行可靠性" eyebrow="执行基础设施"><div className={styles.reliabilityList}><Reliability label="运行完成率" value={`${runs.data?.items.filter((item) => item.status === "completed").length ?? 0}/${runs.data?.total ?? 0}`} tone="success" /><Reliability label="执行错误" value={String(runs.data?.items.reduce((total, item) => total + item.failed_count, 0) ?? 0)} tone="danger" /><Reliability label="Provider 耗尽" value={String(providerErrors)} tone="warning" /><Reliability label="生产遥测" value="未配置" tone="neutral" /></div></Surface><Surface title="高频问题" eyebrow="由证据归并"><div className={styles.problemPreview}>{problemRows(all).slice(0, 6).map((problem) => <Link key={problem.key} to={`/targets/${encodeURIComponent(targetId)}/observability/problems`}><span><TriangleAlert size={13} /></span><p><strong>{problem.label}</strong><small>{problem.source === "Evaluation" ? "评测结论" : "执行错误"}</small></p><b>{problem.count}</b><ChevronRight size={12} /></Link>)}{!problemRows(all).length ? <p className={styles.reportPositive}><CheckCircle2 size={14} /> 最近运行没有可归并的问题。</p> : null}</div></Surface><Surface title="资产健康" eyebrow="覆盖范围"><div className={styles.governanceRows}><div><span>测试用例</span><strong>{cases.data?.total ?? 0}</strong><small>{capabilityCoverage(cases.data?.items ?? []).length} 个能力标签</small></div><div><span>结果样本</span><strong>{samples.data?.total ?? 0}</strong><small>{new Set(samples.data?.items.map((item) => item.tool_name)).size} 个工具</small></div><div><span>不稳定用例</span><strong>{flaky.length}</strong><small>需要重复验证</small></div></div></Surface></div>
  </ProductWorkspace>;
}

function Reliability({ label, value, tone }: { label: string; value: string; tone: Tone }) { return <div><span>{label}</span><strong data-tone={tone}>{value}</strong></div>; }

const METRIC_DEFINITIONS = [
  { id: "eval.pass_rate", group: "评测质量", name: "评测通过率", formula: "通过 /（通过 + 未通过 + 证据不足）", source: "Evaluation", dimensions: "被测 Agent · 版本 · 执行配置 · 能力" },
  { id: "eval.inconclusive_rate", group: "评测质量", name: "证据不足率", formula: "证据不足 / 已评测项", source: "Evaluation", dimensions: "被测 Agent · 评判器 · 版本" },
  { id: "run.execution_error_rate", group: "执行可靠性", name: "执行错误率", formula: "执行失败的 CaseRun / 计划 CaseRun", source: "CaseRun", dimensions: "被测 Agent · 驱动 · 执行配置" },
  { id: "provider.exhausted_rate", group: "工具结果", name: "Provider 耗尽率", formula: "Provider 耗尽次数 / 工具结果解析次数", source: "RunEvent", dimensions: "工具 · 执行配置 · 版本" },
  { id: "asset.case_approval", group: "资产健康", name: "用例审核覆盖率", formula: "已审核用例 / 全部用例", source: "TestCase", dimensions: "能力 · 来源" },
  { id: "agent.invocation_success", group: "AgentTeams", name: "Worker 调用成功率", formula: "已完成调用 / 已结束调用", source: "AgentInvocation", dimensions: "角色 · 模型 · Prompt 版本" },
] as const;

function MetricsPage({ targetId: _targetId }: { targetId: string }) {
  const [selectedId, setSelectedId] = useState<string>(METRIC_DEFINITIONS[0].id);
  const selected = METRIC_DEFINITIONS.find((item) => item.id === selectedId)!;
  return <ProductWorkspace><PageIntro eyebrow="观测与分析 · 指标口径" title="指标目录" description="每个指标公开公式、事实来源、统计口径和支持维度。" /><div className={styles.metricCatalog}><aside><header><span className="eyebrow">指标分组</span><strong>共 6 个指标定义</strong></header>{[...new Set(METRIC_DEFINITIONS.map((item) => item.group))].map((group) => <button key={group} type="button"><span>{group}</span><strong>{METRIC_DEFINITIONS.filter((item) => item.group === group).length}</strong></button>)}</aside><section><header><span>指标名称</span><span>事实来源</span></header>{METRIC_DEFINITIONS.map((item) => <button className={selectedId === item.id ? styles.selectedMetric : ""} key={item.id} onClick={() => setSelectedId(item.id)} type="button"><span><strong>{item.name}</strong><code>{item.id}</code></span><em>{item.source}</em><ChevronRight size={12} /></button>)}</section><article><header><span className="eyebrow">指标定义</span><h2>{selected.name}</h2><code>{selected.id}</code></header><dl><div><dt>指标分组</dt><dd>{selected.group}</dd></div><div><dt>事实来源</dt><dd>{selected.source}</dd></div><div><dt>计算公式</dt><dd>{selected.formula}</dd></div><div><dt>统计维度</dt><dd>{selected.dimensions}</dd></div><div><dt>排除范围</dt><dd>已跳过、已取消和遥测缺失项</dd></div><div><dt>数据时效</dt><dd>根据当前本地数据库实时派生</dd></div></dl><div className={styles.visibilityNote}><ShieldCheck size={13} />未采集数据返回“未知”，不会用 0 替代。</div></article></div></ProductWorkspace>;
}

function ProblemsPage({ targetId }: { targetId: string }) {
  const history = useLatestCaseRuns(targetId);
  const all = history.data?.flatMap((entry) => entry.page.items) ?? [];
  const problems = problemRows(all);
  const [query, setQuery] = useState("");
  const [selectedKey, setSelectedKey] = useState<string | null>(null);
  const filtered = problems.filter((problem) => `${problem.label} ${problem.key} ${problem.source} ${problem.items.map((item) => item.case_id).join(" ")}`.toLowerCase().includes(query.toLowerCase()));
  useEffect(() => { if (filtered[0] && !filtered.some((item) => item.key === selectedKey)) setSelectedKey(filtered[0].key); if (!filtered.length && selectedKey) setSelectedKey(null); }, [filtered, selectedKey]);
  const selected = filtered.find((item) => item.key === selectedKey) ?? null;
  return <ProductWorkspace><PageIntro eyebrow="观测与分析 · 问题归并" title="问题中心" description="按确定性错误来源归并重复失败，并下钻到真实用例运行与证据。" /><MetricStrip items={[
    { label: "待处理问题", value: problems.length, meta: "由运行证据生成的问题指纹", tone: problems.length ? "warning" : "success" },
    { label: "出现次数", value: problems.reduce((total, item) => total + item.count, 0), meta: "来自最近用例运行" },
    { label: "Agent 行为问题", value: problems.filter((item) => item.source === "Evaluation").length, meta: "未通过或证据不足" },
    { label: "基础设施问题", value: problems.filter((item) => item.source === "Execution").length, meta: "按错误码归并", tone: problems.some((item) => item.source === "Execution") ? "danger" : "neutral" },
  ]} /><div className={styles.problemWorkspace}><section className={styles.problemList}><header><label><Search size={14} /><input onChange={(event) => setQuery(event.target.value)} placeholder="搜索用例、错误码或证据" value={query} /></label><span>{filtered.length} 个问题指纹</span></header>{filtered.map((problem) => <button className={selectedKey === problem.key ? styles.selectedProblem : ""} key={problem.key} onClick={() => setSelectedKey(problem.key)} type="button"><span className={problem.source === "Execution" ? styles.problemDanger : styles.problemWarning}><TriangleAlert size={13} /></span><p><strong>{problem.label}</strong><small>{problem.source === "Execution" ? "执行错误" : "评测结论"} · {problem.key}</small></p><b>{problem.count}</b><Status value="check" label="待处理" /></button>)}{!filtered.length ? <EmptyState icon={problems.length ? Search : CheckCircle2} title={problems.length ? "没有匹配问题" : "没有重复问题"}>{problems.length ? "尝试搜索用例 ID、错误码或来源。" : "最近评测没有失败或执行错误。"}</EmptyState> : null}</section><article className={styles.problemDetail}>{selected ? <><header><div><span className="eyebrow">问题指纹</span><h2>{selected.label}</h2><code>{selected.key}</code></div><Status value="check" label="待处理" /></header><div className={styles.problemSummary}><div><span>出现次数</span><strong>{selected.count}</strong></div><div><span>问题来源</span><strong>{selected.source === "Execution" ? "执行错误" : "评测结论"}</strong></div><div><span>严重程度</span><strong>{selected.source === "Execution" ? "高" : "中"}</strong></div></div><section><h3>关联用例运行</h3>{selected.items.map((item) => <Link className={styles.problemOccurrence} key={item.id} to={`/targets/${encodeURIComponent(targetId)}/evaluation/runs/${item.run_id}`}><span><Status value={item.evaluation_state} /></span><p><strong>{item.case_id}</strong><small>{shortId(item.id)} · {item.version ?? "默认版本"}</small></p><ChevronRight size={13} /></Link>)}</section><section><h3>处理建议</h3><div className={styles.actionQueue}><Link to={`/targets/${encodeURIComponent(targetId)}/assistant`}><Sparkles size={14} /><span><strong>交给助手分析</strong><small>传入真实资源 ID 与当前问题指纹</small></span><ChevronRight size={13} /></Link><Link to={`/targets/${encodeURIComponent(targetId)}/evaluation/test-cases`}><TestTube2 size={14} /><span><strong>创建验证用例</strong><small>所有生成内容先进入草稿</small></span><ChevronRight size={13} /></Link></div></section></> : <EmptyState icon={FileSearch} title="选择问题">查看出现记录和证据。</EmptyState>}</article></div></ProductWorkspace>;
}

function ExportPage({ targetId }: { targetId: string }) {
  const { runs, cases, samples } = useTargetData(targetId);
  const [format, setFormat] = useState("json");
  const [notice, setNotice] = useState<string | null>(null);
  const recordCount = (runs.data?.total ?? 0) + (cases.data?.total ?? 0) + (samples.data?.total ?? 0);
  function downloadExport() {
    const payload = { schema_version: "agentrig.export.v1", target_id: targetId, generated_at: new Date().toISOString(), scope: { runs: runs.data?.items ?? [], cases: cases.data?.items ?? [], samples: samples.data?.items ?? [] }, redaction: "保留密钥配置引用，排除解析后的密钥值" };
    if (format === "markdown") {
      const markdown = [`# AgentRig 证据导出`, "", `- 被测 Agent：\`${targetId}\``, `- 生成时间：${payload.generated_at}`, `- 运行：${payload.scope.runs.length}`, `- 测试用例：${payload.scope.cases.length}`, `- 结果样本：${payload.scope.samples.length}`, `- 脱敏策略：${payload.redaction}`, "", "## 评测运行", "", ...payload.scope.runs.map((run) => `- \`${run.id}\` · ${labelFor(run.status)} · ${run.resolved_case_ids.length} 个用例`), "", "## 测试用例", "", ...payload.scope.cases.map((item) => `- \`${item.id}\` · ${item.name} · ${labelFor(item.review_status)}`), "", "## 结果样本", "", ...payload.scope.samples.map((item) => `- \`${item.id}\` · ${item.name} · ${labelFor(item.status)}`)].join("\n");
      downloadText(`agentrig-${targetId}-export.md`, markdown, "text/markdown;charset=utf-8");
    } else if (format === "html") {
      const body = `<h1>AgentRig 证据导出</h1><dl><dt>被测 Agent</dt><dd>${escapeHtml(targetId)}</dd><dt>生成时间</dt><dd>${escapeHtml(payload.generated_at)}</dd><dt>记录数量</dt><dd>${recordCount}</dd></dl><h2>评测运行</h2><ul>${payload.scope.runs.map((run) => `<li><code>${escapeHtml(run.id)}</code> · ${escapeHtml(labelFor(run.status))}</li>`).join("")}</ul><h2>测试用例</h2><ul>${payload.scope.cases.map((item) => `<li><code>${escapeHtml(item.id)}</code> · ${escapeHtml(item.name)}</li>`).join("")}</ul><h2>结果样本</h2><ul>${payload.scope.samples.map((item) => `<li><code>${escapeHtml(item.id)}</code> · ${escapeHtml(item.name)}</li>`).join("")}</ul><p>${escapeHtml(payload.redaction)}</p>`;
      downloadText(`agentrig-${targetId}-export.html`, `<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>AgentRig 证据导出</title><style>body{max-width:960px;margin:40px auto;font:14px system-ui;color:#1b1d1c}code{background:#f1f3f2;padding:2px 4px}dt{font-weight:700}dd{margin:0 0 8px}</style><body>${body}</body></html>`, "text/html;charset=utf-8");
    } else {
      downloadText(`agentrig-${targetId}-export.json`, JSON.stringify(payload, null, 2), "application/json");
    }
    setNotice(`已生成脱敏 ${format.toUpperCase()} 导出文件。`);
  }
  return <ProductWorkspace><PageIntro eyebrow="观测与分析 · 安全导出" title="数据导出" description="先预览数据范围和脱敏策略，再生成可审计的数据包。" /><div className={styles.exportGrid}><Surface title="导出配置" eyebrow="范围与格式"><div className={styles.exportForm}><label>被测 Agent<input readOnly value={targetId} /></label><label>数据范围<select><option>运行、用例与结果样本</option></select></label><label>导出格式<select onChange={(event) => setFormat(event.target.value)} value={format}><option value="json">JSON 证据包</option><option value="markdown">Markdown 评测报告</option><option value="html">独立 HTML 评测报告</option></select></label><label>脱敏策略<select><option>默认安全脱敏策略</option></select></label></div></Surface><Surface title="导出预览" eyebrow="数据估算"><div className={styles.exportPreview}><div><span>记录数量</span><strong>{recordCount}</strong><small>当前本地数据库可见记录</small></div><div><span>文件格式</span><strong>{format.toUpperCase()}</strong><small>可移植导出文件</small></div><div><span>明文密钥</span><strong className={styles.successText}>已排除</strong><small>只保留 env: 配置引用</small></div></div><div className={styles.redactionList}><p><Check size={12} />移除 Authorization 请求头</p><p><Check size={12} />不解析 Secret Reference</p><p><Check size={12} />不导出 Matrix Access Token</p><p><Check size={12} />保留 Evidence ID 与 Hash</p></div>{notice ? <div className={styles.noticeBar}><CheckCircle2 size={13} />{notice}</div> : null}<Button icon={<Download />} onClick={downloadExport} variant="primary">生成并下载</Button></Surface></div></ProductWorkspace>;
}

function EvaluatorTeamsPage() {
  const health = useQuery({ queryKey: ["product", "teams", "health"], queryFn: getAgentTeamsHealth, refetchInterval: 10_000 });
  const invocations = useAllInvocations();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  useEffect(() => { if (!selectedId && invocations.data?.[0]) setSelectedId(invocations.data[0].id); }, [invocations.data, selectedId]);
  const detail = useQuery({ queryKey: ["product", "invocation", selectedId], queryFn: () => getAgentInvocation(selectedId!), enabled: Boolean(selectedId) });
  const curator = invocations.data?.filter((item) => item.agent_role === "simulation_curator") ?? [];
  const judge = invocations.data?.filter((item) => item.agent_role === "evidence_judge") ?? [];
  return <ProductWorkspace><PageIntro eyebrow="平台管理 · AgentTeams 运行时" title="评测团队" description="AgentRig 定义评测角色和权限，AgentTeams 提供身份、Matrix 与协作运行环境。" actions={<Button icon={<RefreshCcw />} onClick={() => { void health.refetch(); void invocations.refetch(); }}>检查运行环境</Button>} /><MetricStrip items={[
    { label: "团队状态", value: health.data?.matrix_reachable ? "就绪" : "待检查", meta: health.data?.matrix_reachable ? "Matrix 与协作角色运行正常" : "正在检查协作运行时", tone: health.data?.matrix_reachable ? "success" : "warning" },
    { label: "Matrix 连接", value: health.data?.matrix_reachable ? "可连接" : "不可用", meta: "AgentTeams 协作传输通道", tone: health.data?.matrix_reachable ? "success" : "danger" },
    { label: "Worker 调用", value: invocations.data?.length ?? 0, meta: "已持久化的协作任务", tone: "accent" },
    { label: "失败或超时", value: invocations.data?.filter((item) => ["failed", "timed_out"].includes(item.status)).length ?? 0, meta: "已结束的 Worker 错误", tone: invocations.data?.some((item) => ["failed", "timed_out"].includes(item.status)) ? "danger" : "neutral" },
  ]} /><Surface title="默认评测团队" eyebrow="固定角色拓扑"><div className={styles.teamTopology}><RoleCard icon={Bot} title="评测主控 Manager" subtitle="面向用户的评测编排角色" status={health.data?.enabled ? "ready" : "disabled"} metrics={["规划 · 确认 · 提交", "仅访问 Manager MCP"]} /><span className={styles.teamConnector}><ArrowRight size={15} /></span><div className={styles.workerStack}><RoleCard icon={GitCompareArrows} title="结果模拟 Curator" subtitle="生成符合 Schema 的工具结果" status={roleStatus(curator)} metrics={[`${curator.length} 次调用`, "不可访问评判规则"]} /><RoleCard icon={ShieldCheck} title="证据裁决 Judge" subtitle="基于证据独立形成结论" status={roleStatus(judge)} metrics={[`${judge.length} 次调用`, "必须引用证据"]} /></div></div></Surface><div className={styles.invocationWorkspace}><Surface title="Worker 调用记录" eyebrow="可审计任务" className={styles.invocationList}><div className={styles.masterList}>{invocations.data?.map((item) => <button className={selectedId === item.id ? styles.selectedMaster : ""} key={item.id} onClick={() => setSelectedId(item.id)} type="button"><span><strong>{item.agent_role === "simulation_curator" ? "结果模拟 Curator" : "证据裁决 Judge"}</strong><small>{shortId(item.id)} · {formatDate(item.created_at)}</small></span><Status value={item.status} /></button>)}{!invocations.data?.length ? <EmptyState icon={UsersRound} title="尚无 Worker 调用">执行包含 Curator 或 Judge 的评测后会显示在这里。</EmptyState> : null}</div></Surface><article className={styles.invocationDetail}>{detail.data ? <><header><div><span className="eyebrow">调用详情</span><h2>{detail.data.agent_role === "simulation_curator" ? "结果模拟 Curator" : "证据裁决 Judge"}</h2><code>{detail.data.id}</code></div><Status value={detail.data.status} /></header><div className={styles.invocationMeta}><div><span>运行编号</span><code>{shortId(detail.data.run_id)}</code></div><div><span>CaseRun</span><code>{shortId(detail.data.case_run_id)}</code></div><div><span>尝试次数</span><strong>{detail.data.attempt ?? 1}</strong></div><div><span>执行 Agent</span><strong>{detail.data.assigned_agent ?? "待分配"}</strong></div></div><section className={styles.hashGrid}><div><span>输入 Hash</span><code>{detail.data.input_hash}</code></div><div><span>结果 Hash</span><code>{detail.data.result_hash ?? "待生成"}</code></div><div><span>请求事件</span><code>{detail.data.request_event_id ?? "待生成"}</code></div><div><span>响应事件</span><code>{detail.data.response_event_id ?? "待生成"}</code></div></section><div className={styles.visibilityNote}><ShieldCheck size={13} />{detail.data.agent_role === "simulation_curator" ? "Curator 输入不包含评判规则、预期答案和最终分数。" : "Judge 只能引用本 CaseRun 冻结证据中存在的事件 ID。"}</div><details className={styles.snapshotDetails} open><summary>冻结输入快照 <ChevronRight size={12} /></summary><pre>{pretty(detail.data.input_snapshot ?? {})}</pre></details><details className={styles.snapshotDetails}><summary>已校验结果 <ChevronRight size={12} /></summary><pre>{pretty(detail.data.result_payload ?? {})}</pre></details></> : <EmptyState icon={ShieldCheck} title="选择一条 Worker 调用">查看冻结输入、Hash、Matrix 与结构化结果。</EmptyState>}</article></div></ProductWorkspace>;
}

function useAllInvocations() {
  return useQuery({ queryKey: ["product", "all-invocations"], queryFn: async () => (await listAllAgentInvocations()).items, refetchInterval: 5_000 });
}

function RoleCard({ icon: Icon, title, subtitle, status, metrics }: { icon: LucideIcon; title: string; subtitle: string; status: string; metrics: string[] }) { return <article className={styles.roleCard}><header><span><Icon size={17} /></span><Status value={status} /></header><h3>{title}</h3><p>{subtitle}</p><footer>{metrics.map((metric) => <small key={metric}>{metric}</small>)}</footer></article>; }
function roleStatus(items: AgentInvocation[]) { const current = items[0]?.status; if (["failed", "timed_out"].includes(current ?? "")) return "degraded"; return items.length ? "ready" : "check"; }

function AuditPage() {
  const targets = useQuery({ queryKey: ["product", "targets"], queryFn: () => getPage<Target>("/api/targets?limit=100") });
  const runs = useQuery({ queryKey: ["product", "runs", "audit"], queryFn: () => getPage<Run>("/api/runs?limit=100") });
  const invocations = useAllInvocations();
  const events = useMemo(() => [
    ...(invocations.data ?? []).map((item) => ({ id: item.id, time: item.created_at, actor: item.agent_role, action: "agent.invocation", resource: item.case_run_id, outcome: item.status })),
    ...(runs.data?.items ?? []).map((item) => ({ id: item.id, time: item.created_at, actor: "system / user", action: "run.submitted", resource: `${item.resolved_case_ids.length} cases`, outcome: item.status })),
    ...(targets.data?.items ?? []).map((item) => ({ id: item.id, time: item.updated_at, actor: "platform", action: "target.configured", resource: item.name, outcome: "completed" })),
  ].sort((a, b) => b.time.localeCompare(a.time)), [invocations.data, runs.data, targets.data]);
  return <ProductWorkspace><PageIntro eyebrow="平台管理 · 操作治理" title="审计日志" description="统一展示用户、Manager、Worker、API 和系统对权威资源的操作。" /><MetricStrip items={[
    { label: "审计事件", value: events.length, meta: "当前权威资源投影", tone: "accent" },
    { label: "用户与系统操作", value: (runs.data?.total ?? 0) + (targets.data?.total ?? 0), meta: "运行与 Target 配置操作" },
    { label: "Agent 操作", value: invocations.data?.length ?? 0, meta: "已持久化的 Worker 调用" },
    { label: "异常结果", value: events.filter((item) => ["failed", "timed_out", "cancelled"].includes(item.outcome)).length, meta: "需要关注的事件", tone: events.some((item) => ["failed", "timed_out"].includes(item.outcome)) ? "danger" : "neutral" },
  ]} /><Surface title="平台活动" eyebrow="操作者 · 操作 · 资源"><div className={styles.auditTable}><div><span>时间</span><span>操作者</span><span>操作</span><span>资源</span><span>结果</span></div>{events.map((event) => <article key={`${event.action}-${event.id}`}><time>{formatDate(event.time)}</time><span>{event.actor}</span><code>{event.action}</code><span title={event.resource}>{shortId(event.resource)}</span><Status value={event.outcome} /></article>)}</div><footer className={styles.auditNotice}><ShieldCheck size={13} />当前页面已投影权威资源；完整的只追加 AuditEvent 表属于后续治理增强。</footer></Surface></ProductWorkspace>;
}

function SettingsPage() {
  const health = useQuery({ queryKey: ["product", "settings", "health"], queryFn: getAgentTeamsHealth });
  return <ProductWorkspace><PageIntro eyebrow="平台管理 · 运行配置" title="系统设置" description="运行时、模型密钥和访问控制只展示配置引用与健康状态。" actions={<Button disabled={health.isFetching} icon={<RefreshCcw />} onClick={() => health.refetch()}>重新检测</Button>} />{health.error ? <QueryFailure value={health.error} /> : null}<div className={styles.settingsGrid}><Surface title="本地运行环境" eyebrow="运行时"><SettingsRow icon={Database} label="本地数据库" value="SQLite" status="ready" /><SettingsRow icon={Network} label="AgentRig API" value="同源 Web API" status="ready" /><SettingsRow icon={UsersRound} label="AgentTeams" value={health.data?.matrix_reachable ? "Matrix 与协作角色运行正常" : "等待运行时连接"} status={health.data?.matrix_reachable ? "ready" : "check"} /></Surface><Surface title="模型与密钥" eyebrow="安全配置"><SettingsRow icon={Bot} label="评测模型" value="deepseek-v4-flash" status="ready" /><SettingsRow icon={ShieldCheck} label="模型密钥" value="env:DEEPSEEK_API_KEY" status="ready" /><div className={styles.visibilityNote}><ShieldCheck size={13} />密钥真实值不会返回浏览器、数据库快照、运行证据或导出文件。</div></Surface><Surface title="访问与接口" eyebrow="权限隔离"><SettingsRow icon={ShieldCheck} label="Web API" value="Bearer Token" status="ready" /><SettingsRow icon={Waypoints} label="评测主控 Manager MCP" value="角色隔离凭据" status={health.data?.configured ? "ready" : "check"} /><SettingsRow icon={Waypoints} label="专业 Worker MCP" value="Curator / Judge 独立访问凭据" status={health.data?.configured ? "ready" : "check"} /></Surface></div></ProductWorkspace>;
}

function SettingsRow({ icon: Icon, label, value, status }: { icon: LucideIcon; label: string; value: string; status: string }) { return <div className={styles.settingsRow}><span><Icon size={14} /></span><p><strong>{label}</strong><small>{value}</small></p><Status value={status} /></div>; }

function flakyCases(items: CaseRun[]) { const values = new Map<string, Set<string>>(); items.forEach((item) => { const current = values.get(item.case_id) ?? new Set<string>(); if (["pass", "fail", "inconclusive"].includes(item.evaluation_state)) current.add(item.evaluation_state); values.set(item.case_id, current); }); return [...values.entries()].filter(([, outcomes]) => outcomes.size > 1).map(([caseId]) => caseId); }

function problemRows(items: CaseRun[]) {
  const grouped = new Map<string, { key: string; label: string; source: string; count: number; items: CaseRun[] }>();
  items.forEach((item) => { let key: string | null = null; let label = ""; let source = "Evaluation"; if (item.error_code) { key = `error:${item.error_code}`; label = `执行错误 · ${item.error_code}`; source = "Execution"; } else if (["fail", "inconclusive"].includes(item.evaluation_state)) { key = `outcome:${item.case_id}:${item.evaluation_state}`; label = `${item.case_id} · ${labelFor(item.evaluation_state)}`; } if (!key) return; const current = grouped.get(key) ?? { key, label, source, count: 0, items: [] }; current.count += 1; current.items.push(item); grouped.set(key, current); });
  return [...grouped.values()].sort((a, b) => b.count - a.count);
}

function downloadText(filename: string, content: string, type: string) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  URL.revokeObjectURL(url);
}

function escapeHtml(value: string) {
  return value.replaceAll("&", "&amp;").replaceAll("<", "&lt;").replaceAll(">", "&gt;").replaceAll('"', "&quot;").replaceAll("'", "&#039;");
}

function pretty(value: unknown) { return JSON.stringify(value, null, 2); }
