import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  ArrowRight,
  Boxes,
  CheckCircle2,
  FlaskConical,
  MessageSquare,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { Link } from "react-router";

import { toRunListItem } from "~/adapters/evaluation-adapter";
import {
  getOne,
  getPage,
  getRunSummary,
  postAction,
  type ExecutionProfile,
  type Run,
  type Sample,
  type Target,
  type TargetCheck,
  type TestCase,
} from "~/api/v1";
import { ErrorState, LoadingState, PartialDataNotice } from "~/components/states/query-state";
import { Badge } from "~/components/ui/badge";
import { PageHeader } from "~/components/ui/page-header";
import { Panel } from "~/components/ui/panel";

import styles from "./target-overview-page.module.css";

export function TargetOverviewPage({ targetId }: { targetId: string }) {
  const base = `/targets/${encodeURIComponent(targetId)}`;
  const target = useQuery({
    queryKey: ["target-overview", "target", targetId],
    queryFn: () => getOne<Target>(`/api/targets/${encodeURIComponent(targetId)}`),
  });
  const runs = useQuery({
    queryKey: ["target-overview", "runs", targetId],
    queryFn: () => getPage<Run>(`/api/runs?target_id=${encodeURIComponent(targetId)}&limit=20`),
    refetchInterval: 5_000,
  });
  const cases = useQuery({
    queryKey: ["target-overview", "cases"],
    queryFn: () => getPage<TestCase>("/api/test-cases?limit=200"),
  });
  const samples = useQuery({
    queryKey: ["target-overview", "samples"],
    queryFn: () => getPage<Sample>("/api/samples?limit=200"),
  });
  const profiles = useQuery({
    queryKey: ["target-overview", "profiles"],
    queryFn: () => getPage<ExecutionProfile>("/api/execution-profiles?limit=200"),
  });
  const check = useQuery({
    queryKey: ["target-overview", "check", targetId],
    queryFn: () => postAction<TargetCheck>(`/api/targets/${encodeURIComponent(targetId)}/check`),
    retry: false,
    refetchInterval: 30_000,
  });
  const latest = runs.data?.items[0];
  const latestSummary = useQuery({
    queryKey: ["target-overview", "summary", latest?.id],
    queryFn: () => getRunSummary(latest!.id),
    enabled: Boolean(latest?.id),
    refetchInterval: latest && ["queued", "running"].includes(latest.status) ? 2_000 : false,
  });

  if (target.isPending) return <div className={styles.page}><LoadingState title="正在读取被测 Agent" /></div>;
  if (target.error || !target.data) return <div className={styles.page}><ErrorState description={errorMessage(target.error)} onRetry={() => void target.refetch()} /></div>;
  const approvedCases = cases.data?.items.filter((item) => item.review_status === "approved").length ?? 0;
  const draftCases = cases.data?.items.filter((item) => item.review_status === "draft").length ?? 0;
  const approvedSamples = samples.data?.items.filter((item) => item.status === "approved").length ?? 0;
  const latestVm = latest ? toRunListItem(latest, target.data) : null;
  const failedClasses = Object.entries(latestSummary.data?.failure_classes ?? {}).filter(([, count]) => count > 0);

  return (
    <div className={styles.page}>
      <PageHeader
        eyebrow="Target Workspace"
        title={`${target.data.name} 评测总览`}
        description="从连接状态、正式资产和真实运行证据汇总当前可评测性。"
        actions={<div className={styles.actions}><Link className="button button--secondary button--md" to={`${base}/conversation`}><MessageSquare size={13} /> 对话验证</Link><Link className="button button--primary button--md" to={`${base}/assistant`}><Sparkles size={13} /> 智能评测</Link></div>}
      />
      {check.error ? <PartialDataNotice>连接检查失败：{errorMessage(check.error)}。这不会被替换为演示数据。</PartialDataNotice> : null}
      <section className={styles.summary}>
        <Metric icon={<Activity />} label="连接状态" value={check.isPending ? "检查中" : check.data?.reachable ? "可达" : "不可达"} tone={check.data?.reachable ? "success" : check.isPending ? "accent" : "danger"} help={check.data?.message ?? target.data.driver_type} />
        <Metric icon={<FlaskConical />} label="真实 Run" value={runs.data?.total ?? "—"} help={latestVm ? `最近 ${latestVm.createdAt}` : "尚未执行评测"} />
        <Metric icon={<CheckCircle2 />} label="已批准用例" value={approvedCases} tone="success" help={`${draftCases} 个草稿待审核`} />
        <Metric icon={<Boxes />} label="结果资产 / Profile" value={`${approvedSamples} / ${profiles.data?.total ?? 0}`} help="可复用的工具结果与执行配置" />
      </section>
      <div className={styles.workspaceGrid}>
        <Panel eyebrow="Latest Run" title="最近一次评测">
          {latestVm ? (
            <div className={styles.latestRun}>
              <header><span><strong>{latestVm.shortId}</strong><small>{latestVm.createdAt}</small></span><Badge tone={runTone(latestVm.status)}>{runLabel(latestVm.status)}</Badge></header>
              <div className={styles.progress}><i style={{ width: `${latestVm.progress.percent}%` }} /></div>
              <dl><div><dt>进度</dt><dd>{latestVm.progress.completed}/{latestVm.progress.total}</dd></div><div><dt>Cell</dt><dd>{latestVm.cellCount}</dd></div><div><dt>Attempt</dt><dd>{latestVm.attemptCount}</dd></div><div><dt>失败</dt><dd data-danger={latestVm.failedCount > 0}>{latestVm.failedCount}</dd></div></dl>
              <footer><span>{latestVm.manifestHash ? "Canonical Manifest 已冻结" : "旧 Run 无 Manifest"}</span><Link to={`${base}/evaluation/runs/${encodeURIComponent(latestVm.id)}`}>查看运行证据 <ArrowRight size={13} /></Link></footer>
            </div>
          ) : <EmptyRun href={`${base}/evaluation/runs/new/info`} />}
        </Panel>
        <Panel eyebrow="Quality Boundary" title="当前风险与门禁">
          <div className={styles.gates}>
            <Gate label="Target 连接" pass={check.data?.reachable === true} detail={check.data?.reachable ? "连接检查已通过" : "需要修复接入或运行服务"} />
            <Gate label="正式用例" pass={approvedCases > 0} detail={approvedCases ? `${approvedCases} 个已批准用例` : "没有可用于正式评测的用例"} />
            <Gate label="执行完整性" pass={!latestVm || latestVm.failedCount === 0} detail={latestVm ? `${latestVm.failedCount} 个失败 Attempt` : "等待首次运行"} />
            <Gate label="证据结论" pass={!latestSummary.data || (latestSummary.data.evaluation_outcomes.fail ?? 0) === 0} detail={failedClasses.length ? failedClasses.map(([name, count]) => `${failureLabel(name)} ${count}`).join(" · ") : "未发现失败分类"} />
          </div>
        </Panel>
      </div>
      <Panel eyebrow="Recent Runs" title="运行历史" actions={<Link className={styles.inlineLink} to={`${base}/evaluation/runs`}>全部运行 <ArrowRight size={12} /></Link>}>
        <div className={styles.runRows}>
          {(runs.data?.items ?? []).slice(0, 6).map((item) => {
            const run = toRunListItem(item, target.data);
            return <Link key={run.id} to={`${base}/evaluation/runs/${encodeURIComponent(run.id)}`}><span><strong>{run.shortId}</strong><small>{run.createdAt}</small></span><Badge tone={runTone(run.status)}>{runLabel(run.status)}</Badge><span>{run.cellCount} Cells · {run.attemptCount} Attempts</span><span data-danger={run.failedCount > 0}>{run.failedCount} 失败</span><ArrowRight size={13} /></Link>;
          })}
          {runs.data && !runs.data.items.length ? <EmptyRun href={`${base}/evaluation/runs/new/info`} /> : null}
          {runs.isPending ? <LoadingState title="正在读取运行历史" /> : null}
        </div>
      </Panel>
    </div>
  );
}

function Metric({ icon, label, value, help, tone }: { icon: React.ReactNode; label: string; value: string | number; help: string; tone?: string }) {
  return <article data-tone={tone}><span>{icon}</span><div><small>{label}</small><strong>{value}</strong><em>{help}</em></div></article>;
}
function Gate({ label, pass, detail }: { label: string; pass: boolean; detail: string }) {
  return <article><span data-pass={pass}>{pass ? <CheckCircle2 size={14} /> : <AlertTriangle size={14} />}</span><div><strong>{label}</strong><small>{detail}</small></div><Badge tone={pass ? "success" : "warning"}>{pass ? "通过" : "需处理"}</Badge></article>;
}
function EmptyRun({ href }: { href: string }) { return <div className={styles.empty}><ShieldCheck size={24} /><strong>还没有真实评测运行</strong><p>从明确目标和已批准资产开始，先预览 Manifest 再提交。</p><Link className="button button--primary button--md" to={href}>新建评测</Link></div>; }
function errorMessage(value: unknown) { return value instanceof Error ? value.message : value ? String(value) : "未知错误"; }
function runLabel(value: string) { return ({ passed: "通过", failed: "失败", partial: "部分完成", queued: "排队中", running: "执行中", cancelled: "已取消", interrupted: "已中断", unknown: "未知" } as Record<string, string>)[value] ?? value; }
function runTone(value: string): "neutral" | "accent" | "success" | "warning" | "danger" { if (value === "passed") return "success"; if (value === "failed") return "danger"; if (["queued", "running"].includes(value)) return "accent"; if (["partial", "interrupted"].includes(value)) return "warning"; return "neutral"; }
function failureLabel(value: string) { return ({ behavior_regression: "行为回归", target_unreachable: "Target 不可达", tool_result_unavailable: "工具结果不可用", contract_incompatible: "契约不兼容", timeout: "超时", evaluation_error: "评判异常", policy_denied: "策略拒绝", internal_error: "内部错误" } as Record<string, string>)[value] ?? value; }
