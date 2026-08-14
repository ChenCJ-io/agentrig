import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowRight,
  Boxes,
  CheckCircle2,
  ChevronRight,
  Code2,
  Database,
  FileCheck2,
  FilePenLine,
  Plus,
  Search,
  Settings2,
  ShieldCheck,
  TestTube2,
  X,
  XCircle,
} from "lucide-react";
import { useEffect, useMemo, useState, type FormEvent, type ReactNode } from "react";
import { Link, useLocation } from "react-router";

import {
  createOne,
  getPage,
  patchOne,
  postAction,
  type ExecutionProfile,
  type Sample,
  type TestCase,
} from "~/api/v1";
import { EmptyState, ErrorState, LoadingState, PartialDataNotice } from "~/components/states/query-state";
import { Badge } from "~/components/ui/badge";
import { Button } from "~/components/ui/button";
import { CopyableId } from "~/components/ui/copyable-id";
import { PageHeader } from "~/components/ui/page-header";
import { Panel } from "~/components/ui/panel";
import { formatChinaDateTime } from "~/utils/date-time";

import styles from "./assets-page.module.css";

type AssetRoute = "overview" | "cases" | "review" | "samples" | "profiles";

export function AssetsPage({ targetId, pathname }: { targetId: string; pathname: string }) {
  const route: AssetRoute = pathname.endsWith("/evaluation/test-cases")
    ? "cases"
    : pathname.endsWith("/evaluation/case-review")
      ? "review"
      : pathname.endsWith("/assets/tool-results")
        ? "samples"
        : pathname.endsWith("/assets/profiles")
          ? "profiles"
          : "overview";
  if (route === "cases") return <CasesWorkbench targetId={targetId} />;
  if (route === "review") return <CaseReviewWorkbench targetId={targetId} />;
  if (route === "samples") return <SamplesWorkbench targetId={targetId} />;
  if (route === "profiles") return <ProfilesWorkbench targetId={targetId} />;
  return <AssetsOverview targetId={targetId} />;
}

function useAssets() {
  const cases = useQuery({ queryKey: ["assets-v2", "cases"], queryFn: () => getPage<TestCase>("/api/test-cases?limit=200") });
  const samples = useQuery({ queryKey: ["assets-v2", "samples"], queryFn: () => getPage<Sample>("/api/samples?limit=200") });
  const profiles = useQuery({ queryKey: ["assets-v2", "profiles"], queryFn: () => getPage<ExecutionProfile>("/api/execution-profiles?limit=200") });
  return { cases, samples, profiles };
}

function AssetsOverview({ targetId }: { targetId: string }) {
  const { cases, samples, profiles } = useAssets();
  const base = `/targets/${encodeURIComponent(targetId)}`;
  const approvedCases = cases.data?.items.filter((item) => item.review_status === "approved").length ?? 0;
  const approvedSamples = samples.data?.items.filter((item) => item.status === "approved").length ?? 0;
  return (
    <Page>
      <PageHeader eyebrow="Evaluation Assets" title="评测资产" description="用例定义验证目标，工具结果控制资源消耗，执行配置冻结运行策略。" />
      <section className={styles.assetSummary}>
        <AssetMetric icon={<TestTube2 />} label="测试用例" value={cases.data?.total ?? "—"} help={`${approvedCases} 个已批准`} />
        <AssetMetric icon={<FileCheck2 />} label="待审核" value={cases.data?.items.filter((item) => item.review_status === "draft").length ?? "—"} help="人工确认后进入正式评测" />
        <AssetMetric icon={<Database />} label="工具结果" value={samples.data?.total ?? "—"} help={`${approvedSamples} 个已批准`} />
        <AssetMetric icon={<Settings2 />} label="执行配置" value={profiles.data?.total ?? "—"} help="Provider、Evaluator 与并发" />
      </section>
      <div className={styles.assetCards}>
        <AssetCard href={`${base}/evaluation/test-cases`} icon={<TestTube2 />} title="测试用例" description="多轮对话、Fixture、断言与 Rubric；已批准用例不可原地修改。" meta={`${approvedCases} 个正式用例`} />
        <AssetCard href={`${base}/evaluation/case-review`} icon={<ShieldCheck />} title="用例审核" description="人工批准或驳回 Draft，阻止未经审核的生成内容进入正式 Run。" meta={`${cases.data?.items.filter((item) => item.review_status === "draft").length ?? 0} 个待处理`} />
        <AssetCard href={`${base}/assets/tool-results`} icon={<Database />} title="工具结果资产" description="Fixture/Sample 复用真实结果，减少重复工具调用带来的资源消耗。" meta={`${approvedSamples} 个可用结果`} />
        <AssetCard href={`${base}/assets/profiles`} icon={<Settings2 />} title="执行配置" description="固定 Tool Mode、Provider Chain、Evaluator、Timeout 与并发。" meta={`${profiles.data?.total ?? 0} 个 Profile`} />
      </div>
    </Page>
  );
}

function CasesWorkbench({ targetId }: { targetId: string }) {
  const location = useLocation();
  const queryClient = useQueryClient();
  const { cases } = useAssets();
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("all");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editor, setEditor] = useState<{ item: TestCase | null } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const items = useMemo(() => (cases.data?.items ?? []).filter((item) => {
    const haystack = `${item.id} ${item.name} ${item.description} ${item.tags.join(" ")}`.toLowerCase();
    return haystack.includes(query.toLowerCase()) && (status === "all" || item.review_status === status);
  }), [cases.data, query, status]);
  useEffect(() => {
    const requested = new URLSearchParams(location.search).get("case_id");
    if (requested && cases.data?.items.some((item) => item.id === requested)) setSelectedId(requested);
    else if (!selectedId && items[0]) setSelectedId(items[0].id);
  }, [cases.data, items, location.search, selectedId]);
  const selected = cases.data?.items.find((item) => item.id === selectedId) ?? null;
  const save = useMutation({
    mutationFn: async (payload: Record<string, unknown>) => editor?.item
      ? patchOne<TestCase>(`/api/test-cases/${encodeURIComponent(editor.item.id)}`, payload)
      : createOne<TestCase>("/api/test-cases", payload),
    onSuccess: async (item) => { setEditor(null); setSelectedId(item.id); setNotice("用例草稿已保存。"); await queryClient.invalidateQueries({ queryKey: ["assets-v2", "cases"] }); },
    onError: (error) => setNotice(errorMessage(error)),
  });
  return (
    <Page>
      <PageHeader eyebrow="Case Catalog" title="测试用例" description="结构化定义输入、工具边界和评判标准；只有明确的 Draft 才允许编辑。" actions={<Button icon={<Plus />} onClick={() => setEditor({ item: null })} variant="primary">新建用例</Button>} />
      {notice ? <PartialDataNotice>{notice}</PartialDataNotice> : null}
      <CatalogLayout
        rail={<FilterRail counts={{ all: cases.data?.total ?? 0, approved: countBy(cases.data?.items, "review_status", "approved"), draft: countBy(cases.data?.items, "review_status", "draft"), rejected: countBy(cases.data?.items, "review_status", "rejected") }} onChange={setStatus} value={status} />}
        list={<CatalogList loading={cases.isPending} error={cases.error} query={query} onQuery={setQuery} count={items.length}>{items.map((item) => <CatalogButton active={item.id === selectedId} key={item.id} onClick={() => setSelectedId(item.id)} title={item.name} subtitle={`${item.turns.length} 轮 · ${item.primary_evaluator}`} status={item.review_status} />)}</CatalogList>}
        detail={selected ? <CaseDetail item={selected} onEdit={selected.review_status === "approved" ? undefined : () => setEditor({ item: selected })} targetId={targetId} /> : <EmptyDetail icon={<TestTube2 />} title="选择一个测试用例" />}
      />
      {editor ? <JsonEditorDialog title={editor.item ? "编辑用例草稿" : "新建用例草稿"} description="高级 Fixture、Assertion 和 Rubric 使用同一服务端 Schema 校验。" initial={editor.item ? casePayload(editor.item) : newCasePayload()} saving={save.isPending} onClose={() => setEditor(null)} onSave={(value) => save.mutate(value)} /> : null}
    </Page>
  );
}

function CaseReviewWorkbench({ targetId }: { targetId: string }) {
  const queryClient = useQueryClient();
  const cases = useQuery({ queryKey: ["assets-v2", "cases", "review"], queryFn: () => getPage<TestCase>("/api/test-cases?review_status=draft&limit=200") });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => { if (!selectedId && cases.data?.items[0]) setSelectedId(cases.data.items[0].id); }, [cases.data, selectedId]);
  const selected = cases.data?.items.find((item) => item.id === selectedId) ?? null;
  const review = useMutation({
    mutationFn: (value: "approved" | "rejected") => postAction<TestCase>(`/api/test-cases/${encodeURIComponent(selected!.id)}/review?review_status=${value}`),
    onSuccess: async (_, value) => { setNotice(value === "approved" ? "用例已批准并冻结。" : "用例已驳回。"); setSelectedId(null); await queryClient.invalidateQueries({ queryKey: ["assets-v2", "cases"] }); },
    onError: (error) => setNotice(errorMessage(error)),
  });
  return (
    <Page>
      <PageHeader eyebrow="Human Review" title="用例审核" description="人工审核是正式资产边界；批准后不可原地改写，只能创建新草稿。" />
      {notice ? <PartialDataNotice>{notice}</PartialDataNotice> : null}
      <div className={styles.reviewLayout}>
        <Panel eyebrow={`${cases.data?.total ?? 0} Drafts`} title="待审核队列">
          {cases.isPending ? <LoadingState title="正在读取待审核用例" /> : null}
          <div className={styles.reviewQueue}>{cases.data?.items.map((item) => <CatalogButton active={item.id === selectedId} key={item.id} onClick={() => setSelectedId(item.id)} title={item.name} subtitle={`${item.turns.length} 轮 · ${item.primary_evaluator}`} status="draft" />)}</div>
          {cases.data && !cases.data.items.length ? <EmptyState title="没有待审核用例" description="所有 Draft 均已处理。" /> : null}
        </Panel>
        {selected ? <section className={styles.reviewDetail}><CaseDetail item={selected} targetId={targetId} /><footer><Button disabled={review.isPending} icon={<XCircle />} onClick={() => review.mutate("rejected")} variant="danger">驳回</Button><Button disabled={review.isPending} icon={<CheckCircle2 />} onClick={() => review.mutate("approved")} variant="primary">批准并冻结</Button></footer></section> : <EmptyDetail icon={<FileCheck2 />} title="选择一个 Draft 进行审核" />}
      </div>
    </Page>
  );
}

function SamplesWorkbench({ targetId: _targetId }: { targetId: string }) {
  const queryClient = useQueryClient();
  const { samples } = useAssets();
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editor, setEditor] = useState<{ item: Sample | null } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const items = useMemo(() => (samples.data?.items ?? []).filter((item) => `${item.id} ${item.name} ${item.tool_name ?? ""}`.toLowerCase().includes(query.toLowerCase())), [query, samples.data]);
  useEffect(() => { if (!selectedId && items[0]) setSelectedId(items[0].id); }, [items, selectedId]);
  const selected = samples.data?.items.find((item) => item.id === selectedId) ?? null;
  const save = useMutation({ mutationFn: (payload: Record<string, unknown>) => editor?.item ? patchOne<Sample>(`/api/samples/${encodeURIComponent(editor.item.id)}`, payload) : createOne<Sample>("/api/samples", payload), onSuccess: async (item) => { setEditor(null); setSelectedId(item.id); setNotice("工具结果资产已保存为 Draft。"); await queryClient.invalidateQueries({ queryKey: ["assets-v2", "samples"] }); }, onError: (error) => setNotice(errorMessage(error)) });
  const review = useMutation({ mutationFn: (value: "approved" | "disabled") => postAction<Sample>(`/api/samples/${encodeURIComponent(selected!.id)}/review?sample_status=${value}`), onSuccess: async () => { setNotice("工具结果状态已更新。"); await queryClient.invalidateQueries({ queryKey: ["assets-v2", "samples"] }); }, onError: (error) => setNotice(errorMessage(error)) });
  return (
    <Page>
      <PageHeader eyebrow="Tool Result Assets" title="工具结果资产" description="复用 Fixture/Sample 可以验证工具协议与 Agent 行为，同时避免重复消耗真实工具资源。" actions={<Button icon={<Plus />} onClick={() => setEditor({ item: null })} variant="primary">新建结果资产</Button>} />
      {notice ? <PartialDataNotice>{notice}</PartialDataNotice> : null}
      <CatalogLayout rail={<FilterRail counts={{ all: samples.data?.total ?? 0, approved: countBy(samples.data?.items, "status", "approved"), draft: countBy(samples.data?.items, "status", "draft"), disabled: countBy(samples.data?.items, "status", "disabled") }} onChange={() => undefined} value="all" />} list={<CatalogList loading={samples.isPending} error={samples.error} query={query} onQuery={setQuery} count={items.length}>{items.map((item) => <CatalogButton active={item.id === selectedId} key={item.id} onClick={() => setSelectedId(item.id)} title={item.name} subtitle={`${item.tool_name ?? "sequence"} · ${sampleSourceLabel(item.source_type)}`} status={item.status} />)}</CatalogList>} detail={selected ? <GenericDetail eyebrow="Result Asset" title={selected.name} id={selected.id} status={selected.status} body={<><Definition label="工具 / 类型" value={`${selected.tool_name ?? "sequence"} · ${selected.sample_kind}`} /><Definition label="来源" value={sampleSourceLabel(selected.source_type)} /><Raw value={selected} /></>} actions={<><Button icon={<FilePenLine />} onClick={() => setEditor({ item: selected })}>编辑</Button>{selected.status === "draft" ? <Button onClick={() => review.mutate("approved")} variant="primary">批准</Button> : <Button onClick={() => review.mutate("disabled")} variant="danger">停用</Button>}</>} /> : <EmptyDetail icon={<Database />} title="选择一个工具结果资产" />} />
      {editor ? <JsonEditorDialog title={editor.item ? "编辑工具结果" : "新建工具结果"} description="内容会经过明文 Secret 扫描和 Sample Schema 校验。" initial={editor.item ? samplePayload(editor.item) : newSamplePayload()} saving={save.isPending} onClose={() => setEditor(null)} onSave={(value) => save.mutate(value)} /> : null}
    </Page>
  );
}

function ProfilesWorkbench({ targetId }: { targetId: string }) {
  const queryClient = useQueryClient();
  const { profiles } = useAssets();
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editor, setEditor] = useState<{ item: ExecutionProfile | null } | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  useEffect(() => { if (!selectedId && profiles.data?.items[0]) setSelectedId(profiles.data.items[0].id); }, [profiles.data, selectedId]);
  const selected = profiles.data?.items.find((item) => item.id === selectedId) ?? null;
  const save = useMutation({ mutationFn: (payload: Record<string, unknown>) => editor?.item ? patchOne<ExecutionProfile>(`/api/execution-profiles/${encodeURIComponent(editor.item.id)}`, payload) : createOne<ExecutionProfile>("/api/execution-profiles", payload), onSuccess: async (item) => { setEditor(null); setSelectedId(item.id); setNotice("执行配置已保存。"); await queryClient.invalidateQueries({ queryKey: ["assets-v2", "profiles"] }); }, onError: (error) => setNotice(errorMessage(error)) });
  return (
    <Page>
      <PageHeader eyebrow="Execution Profiles" title="执行配置" description="Profile 冻结 Provider Chain、工具模式、Evaluator、超时、定价快照与并发边界。" actions={<Button icon={<Plus />} onClick={() => setEditor({ item: null })} variant="primary">新建 Profile</Button>} />
      {notice ? <PartialDataNotice>{notice}</PartialDataNotice> : null}
      <CatalogLayout rail={<aside className={styles.profileGuide}><Settings2 size={20} /><strong>可复用执行策略</strong><p>Run 会保存 Profile Snapshot；后续修改不会污染历史证据。</p><Link to={`/targets/${encodeURIComponent(targetId)}/evaluation/runs/new/scope`}>用于新评测 <ArrowRight size={12} /></Link></aside>} list={<div className={styles.profileList}>{profiles.isPending ? <LoadingState title="正在读取 Profile" /> : null}{profiles.data?.items.map((item) => <CatalogButton active={item.id === selectedId} key={item.id} onClick={() => setSelectedId(item.id)} title={item.name} subtitle={`${item.config.tool_mode} · ${item.config.provider_chain.map((provider) => provider.name).join(" → ")}`} />)}</div>} detail={selected ? <GenericDetail eyebrow="Execution Profile" title={selected.name} id={selected.id} body={<><Definition label="工具模式" value={selected.config.tool_mode} /><Definition label="结果提供链" value={selected.config.provider_chain.map((item) => item.name).join(" → ")} /><Definition label="评判器 / 并发" value={`${selected.config.primary_evaluator ?? "用例默认"} · ${selected.config.concurrency}`} /><Raw value={selected.config} /></>} actions={<Button icon={<FilePenLine />} onClick={() => setEditor({ item: selected })}>编辑配置</Button>} /> : <EmptyDetail icon={<Settings2 />} title="选择一个执行配置" />} />
      {editor ? <JsonEditorDialog title={editor.item ? "编辑执行配置" : "新建执行配置"} description="模型凭据只允许使用 env:VARIABLE secret_ref。" initial={editor.item ? profilePayload(editor.item) : newProfilePayload()} saving={save.isPending} onClose={() => setEditor(null)} onSave={(value) => save.mutate(value)} /> : null}
    </Page>
  );
}

function Page({ children }: { children: ReactNode }) { return <div className={styles.page}>{children}</div>; }
function AssetMetric({ icon, label, value, help }: { icon: ReactNode; label: string; value: string | number; help: string }) { return <article><span>{icon}</span><div><small>{label}</small><strong>{value}</strong><em>{help}</em></div></article>; }
function AssetCard({ href, icon, title, description, meta }: { href: string; icon: ReactNode; title: string; description: string; meta: string }) { return <Link to={href}><span>{icon}</span><div><strong>{title}</strong><p>{description}</p><small>{meta}</small></div><ChevronRight size={15} /></Link>; }
function CatalogLayout({ rail, list, detail }: { rail: ReactNode; list: ReactNode; detail: ReactNode }) { return <div className={styles.catalog}>{rail}<section className={styles.catalogList}>{list}</section><section className={styles.detail}>{detail}</section></div>; }
function CatalogList({ loading, error, query, onQuery, count, children }: { loading: boolean; error: unknown; query: string; onQuery: (value: string) => void; count: number; children: ReactNode }) { return <><header><label><Search size={13} /><input aria-label="搜索资产" onChange={(event) => onQuery(event.target.value)} placeholder="搜索名称、ID 或标签" value={query} /></label><small>{count} 条</small></header>{loading ? <LoadingState title="正在读取资产" /> : null}{error ? <ErrorState description={errorMessage(error)} /> : null}<div className={styles.catalogItems}>{children}{!loading && !count ? <EmptyState title="没有匹配资产" description="调整搜索或状态筛选。" /> : null}</div></>; }
function FilterRail({ counts, value, onChange }: { counts: Record<string, number>; value: string; onChange: (value: string) => void }) { return <aside className={styles.filterRail}><span className="eyebrow">资产状态</span><strong>目录</strong>{Object.entries(counts).map(([key, count]) => <button data-active={value === key} key={key} onClick={() => onChange(key)} type="button"><span>{statusLabel(key)}</span><b>{count}</b></button>)}</aside>; }
function CatalogButton({ active, title, subtitle, status, onClick }: { active: boolean; title: string; subtitle: string; status?: string; onClick: () => void }) { return <button data-active={active} onClick={onClick} type="button"><span><strong>{title}</strong><small>{subtitle}</small></span>{status ? <Badge tone={statusTone(status)}>{statusLabel(status)}</Badge> : <ChevronRight size={13} />}</button>; }
function CaseDetail({ item, targetId, onEdit }: { item: TestCase; targetId: string; onEdit?: () => void }) { return <GenericDetail eyebrow="Test Case" title={item.name} id={item.id} status={item.review_status} body={<><p className={styles.description}>{item.description || "暂无用例说明。"}</p><div className={styles.tags}>{item.tags.map((tag) => <Badge key={tag}>{tag}</Badge>)}</div><Definition label="评判器 / 版本" value={`${item.primary_evaluator} · ${item.supported_versions.join(", ") || "全部"}`} /><div className={styles.turns}>{item.turns.map((turn, index) => <article key={String(turn.position ?? index)}><em>{index + 1}</em><div><small>用户消息</small><p>{String(turn.user_message ?? "")}</p><span>{Array.isArray(turn.fixtures) ? turn.fixtures.length : 0} Fixtures · {Array.isArray(turn.assertions) ? turn.assertions.length : 0} Assertions</span></div></article>)}</div><Raw value={item} /></>} actions={<>{onEdit ? <Button icon={<FilePenLine />} onClick={onEdit}>编辑 Draft</Button> : null}<Link className="button button--primary button--md" to={`/targets/${encodeURIComponent(targetId)}/evaluation/runs/new/scope`}>用于评测</Link></>} />; }
function GenericDetail({ eyebrow, title, id, status, body, actions }: { eyebrow: string; title: string; id: string; status?: string; body: ReactNode; actions: ReactNode }) { return <div className={styles.genericDetail}><header><div><span className="eyebrow">{eyebrow}</span><h2>{title}</h2><CopyableId value={id} /></div>{status ? <Badge tone={statusTone(status)}>{statusLabel(status)}</Badge> : null}</header><div className={styles.detailBody}>{body}</div><footer><small>更新操作会由服务端 Schema 与不可变规则校验。</small><div>{actions}</div></footer></div>; }
function Definition({ label, value }: { label: string; value: string }) { return <dl className={styles.definition}><dt>{label}</dt><dd>{value}</dd></dl>; }
function Raw({ value }: { value: unknown }) { return <details className={styles.raw}><summary><Code2 size={12} /> 查看完整 JSON</summary><pre>{JSON.stringify(value, null, 2)}</pre></details>; }
function EmptyDetail({ icon, title }: { icon: ReactNode; title: string }) { return <div className={styles.emptyDetail}><span>{icon}</span><strong>{title}</strong><p>从左侧列表选择资产后查看版本、状态和完整定义。</p></div>; }

function JsonEditorDialog({ title, description, initial, saving, onClose, onSave }: { title: string; description: string; initial: Record<string, unknown>; saving: boolean; onClose: () => void; onSave: (value: Record<string, unknown>) => void }) {
  const [text, setText] = useState(() => JSON.stringify(initial, null, 2));
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !saving) onClose();
    };
    window.addEventListener("keydown", handleKey);
    return () => window.removeEventListener("keydown", handleKey);
  }, [onClose, saving]);
  function submit(event: FormEvent) { event.preventDefault(); try { const value = JSON.parse(text) as unknown; if (!value || Array.isArray(value) || typeof value !== "object") throw new Error("根节点必须是 JSON 对象"); setError(null); onSave(value as Record<string, unknown>); } catch (reason) { setError(errorMessage(reason)); } }
  return <div className={styles.dialogBackdrop} role="presentation"><section aria-labelledby="asset-editor-title" aria-modal="true" className={styles.dialog} role="dialog"><header><div><span className="eyebrow">Schema-bound Editor</span><h2 id="asset-editor-title">{title}</h2><p>{description}</p></div><button aria-label="关闭编辑器" onClick={onClose} type="button"><X size={16} /></button></header><form onSubmit={submit}>{error ? <PartialDataNotice>{error}</PartialDataNotice> : null}<label><span>资产 JSON</span><textarea autoFocus onChange={(event) => setText(event.target.value)} spellCheck={false} value={text} /></label><footer><Button disabled={saving} onClick={onClose}>取消</Button><Button disabled={saving} type="submit" variant="primary">{saving ? "正在保存" : "保存并校验"}</Button></footer></form></section></div>;
}

function casePayload(item: TestCase) { const { name, description, tags, supported_versions, primary_evaluator, turns } = item; return { name, description, tags, supported_versions, primary_evaluator, initial_state: item.initial_state ?? {}, case_assertions: item.case_assertions ?? [], case_rubric: item.case_rubric ?? null, turns }; }
function newCasePayload() { return { name: "新的评测用例", description: "", tags: [], supported_versions: [], primary_evaluator: "rule", initial_state: {}, case_assertions: [], case_rubric: null, turns: [{ position: 1, user_message: "请填写用户消息", fixtures: [], assertions: [], rubric: null }] }; }
function samplePayload(item: Sample) { return { name: item.name, tool_name: item.tool_name, sample_kind: item.sample_kind, content: item.content ?? null, match_arguments: item.match_arguments ?? {}, ignored_argument_paths: item.ignored_argument_paths ?? [], supported_versions: item.supported_versions }; }
function sampleSourceLabel(value: string) { return value === "real_tool" ? "真实 MCP 工具调用" : value === "manual" ? "手工录入" : value; }
function newSamplePayload() { return { name: "新的工具结果", tool_name: "tool_name", sample_kind: "single", content: {}, match_arguments: {}, ignored_argument_paths: [], supported_versions: [] }; }
function profilePayload(item: ExecutionProfile) { return { name: item.name, description: item.description, config: item.config }; }
function newProfilePayload() { return { name: "新的执行配置", description: "", config: { tool_mode: "controlled", provider_chain: [{ name: "fixture", config: {} }, { name: "sample", config: {} }], primary_evaluator: "rule", concurrency: 1, case_timeout_seconds: 300, component_timeouts: { driver: 120, real_tool: 60, curator: 30, judge: 60 }, repeat_count: 1 } }; }
function countBy<T>(items: T[] | undefined, key: keyof T, value: unknown) { return items?.filter((item) => item[key] === value).length ?? 0; }
function statusLabel(value: string) { return ({ all: "全部", approved: "已批准", draft: "草稿", rejected: "已驳回", disabled: "已停用" } as Record<string, string>)[value] ?? value; }
function statusTone(value: string): "neutral" | "accent" | "success" | "warning" | "danger" { if (value === "approved") return "success"; if (value === "draft") return "warning"; if (value === "rejected" || value === "disabled") return "danger"; return "neutral"; }
function errorMessage(value: unknown) { return value instanceof Error ? value.message : value ? String(value) : "未知错误"; }
