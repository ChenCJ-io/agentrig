import {
  useMutation,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import {
  Ban,
  Check,
  ChevronRight,
  CircleStop,
  FileJson,
  Play,
  Plus,
  RefreshCcw,
  Save,
  SearchCheck,
  Trash2,
} from "lucide-react";
import {
  useEffect,
  useState,
  type ReactNode,
} from "react";
import { useNavigate } from "react-router";

import {
  createOne,
  deleteOne,
  getOne,
  getPage,
  patchOne,
  postAction,
  putOne,
  type CaseRun,
  type ExecutionProfile,
  type Run,
  type Sample,
  type Target,
  type TestCase,
} from "~/api/v1";
import { Badge } from "~/components/ui/badge";
import { Button } from "~/components/ui/button";
import { PageHeader } from "~/components/ui/page-header";
import { Panel } from "~/components/ui/panel";
import { StatCard } from "~/components/ui/stat-card";

import styles from "./v1-console-page.module.css";

type Asset = TestCase | Target | ExecutionProfile | Sample;
type Tone = "neutral" | "accent" | "success" | "warning" | "danger";

const CASE_DRAFT = {
  name: "新测试用例",
  description: "",
  tags: [],
  supported_versions: [],
  primary_evaluator: "external_controller",
  initial_state: {},
  case_assertions: [],
  case_rubric: null,
  turns: [{ position: 1, user_message: "请输入用户消息", fixtures: [], assertions: [] }],
};

const TARGET_DRAFT = {
  name: "本地 Agent",
  driver_type: "http_sse",
  endpoint: "http://127.0.0.1:9000",
  secret_ref: null,
  options: {},
  versions: [],
};

const PROFILE_DRAFT = {
  name: "Core",
  description: "确定性的 Fixture / Sample 执行方案",
  config: {
    tool_mode: "controlled",
    provider_chain: [{ name: "fixture" }, { name: "sample" }],
    primary_evaluator: "external_controller",
    concurrency: 4,
    case_timeout_seconds: 300,
    component_timeouts: { driver: 120, real_tool: 60, curator: 30, judge: 60 },
    repeat_count: 1,
    curator_model: null,
    judge_model: null,
  },
};

const SAMPLE_DRAFT = {
  name: "工具结果样本",
  tool_name: "namespace__tool",
  sample_kind: "single",
  content: {},
  match_arguments: {},
  ignored_argument_paths: [],
  supported_versions: [],
};

interface AssetConfig<T extends Asset> {
  kind: string;
  title: string;
  description: string;
  endpoint: string;
  draft: object;
  detail: (item: T) => string;
  status?: (item: T) => string;
  clean: (item: Record<string, unknown>) => Record<string, unknown>;
  immutable?: (item: T) => boolean;
}

const CASE_CONFIG: AssetConfig<TestCase> = {
  kind: "test-cases",
  title: "测试用例",
  description: "多轮输入、Fixture、断言与评判要求。approved 用例保持不可变。",
  endpoint: "/api/test-cases",
  draft: CASE_DRAFT,
  detail: (item) => `${item.turns.length} 轮 · ${item.primary_evaluator}`,
  status: (item) => item.review_status,
  immutable: (item) => item.review_status === "approved",
  clean: (item) => omit(item, ["review_status", "created_at", "updated_at"]),
};

const TARGET_CONFIG: AssetConfig<Target> = {
  kind: "targets",
  title: "Targets",
  description: "保存被测 Agent 的 Driver、默认地址和版本覆盖；密钥只保存 env: 引用。",
  endpoint: "/api/targets",
  draft: TARGET_DRAFT,
  detail: (item) => `${item.driver_type} · ${item.versions.length} 个版本`,
  clean: (item) => omit(item, ["created_at", "updated_at"]),
};

const PROFILE_CONFIG: AssetConfig<ExecutionProfile> = {
  kind: "execution-profiles",
  title: "Execution Profiles",
  description: "复用工具控制方式、Provider 顺序、主评判器、并发与超时。",
  endpoint: "/api/execution-profiles",
  draft: PROFILE_DRAFT,
  detail: (item) =>
    `${item.config.tool_mode} · ${item.config.provider_chain.map((entry) => entry.name).join(" → ")}`,
  clean: (item) => omit(item, ["created_at", "updated_at"]),
};

const SAMPLE_CONFIG: AssetConfig<Sample> = {
  kind: "samples",
  title: "工具结果 Samples",
  description: "共享的单次或序列结果。只有人工审核通过的 Sample 会参与匹配。",
  endpoint: "/api/samples",
  draft: SAMPLE_DRAFT,
  detail: (item) => `${item.tool_name ?? "sequence"} · ${item.source_type}`,
  status: (item) => item.status,
  immutable: (item) => item.status !== "draft",
  clean: (item) =>
    omit(item, [
      "status",
      "source_type",
      "source_tool_call_id",
      "created_at",
      "updated_at",
    ]),
};

export function V1ConsolePage({ pathname }: { pathname: string }) {
  if (pathname === "/evaluation/overview") return <OverviewPage />;
  if (pathname === "/evaluation/test-cases") {
    return <AssetPage config={CASE_CONFIG} />;
  }
  if (pathname === "/evaluation/cases/review") {
    return <AssetPage config={CASE_CONFIG} reviewOnly />;
  }
  if (pathname === "/evaluation/targets") {
    return <AssetPage config={TARGET_CONFIG} />;
  }
  if (pathname === "/evaluation/profiles") {
    return <AssetPage config={PROFILE_CONFIG} />;
  }
  if (pathname === "/evaluation/samples") {
    return <AssetPage config={SAMPLE_CONFIG} />;
  }
  if (
    pathname === "/evaluation/batches" ||
    /^\/evaluation\/batches\/[^/]+$/.test(pathname)
  ) {
    return <RunsPage pathname={pathname} />;
  }
  return <OverviewPage />;
}

function OverviewPage() {
  const cases = useQuery({
    queryKey: ["v1", "cases", "overview"],
    queryFn: () => getPage<TestCase>("/api/test-cases?limit=1"),
  });
  const runs = useQuery({
    queryKey: ["v1", "runs", "overview"],
    queryFn: () => getPage<Run>("/api/runs?limit=8"),
    refetchInterval: 5_000,
  });
  const targets = useQuery({
    queryKey: ["v1", "targets", "overview"],
    queryFn: () => getPage<Target>("/api/targets?limit=1"),
  });
  const samples = useQuery({
    queryKey: ["v1", "samples", "overview"],
    queryFn: () => getPage<Sample>("/api/samples?limit=1"),
  });
  const active = runs.data?.items.filter((item) =>
    ["queued", "running"].includes(item.status),
  ).length ?? 0;

  return (
    <Workspace>
      <PageHeader
        eyebrow="AGENTRIG / V1"
        title="评测控制台"
        description="外部编码 Agent 和人工界面共享同一套用例、运行与证据。"
      />
      <div className={styles.stats}>
        <StatCard label="测试用例" value={cases.data?.total ?? "—"} meta="draft + approved" accent="blue" />
        <StatCard label="运行中" value={active} meta="queued / running" accent="amber" />
        <StatCard label="Targets" value={targets.data?.total ?? "—"} meta="Driver 接入" accent="green" />
        <StatCard label="Samples" value={samples.data?.total ?? "—"} meta="all review states" accent="coral" />
      </div>
      <Panel title="最近运行" eyebrow="ASYNCHRONOUS RUNS">
        <RunTable
          runs={runs.data?.items ?? []}
          empty="尚无运行记录。可从“运行记录”提交单用例、批量或 A/B 请求。"
        />
      </Panel>
    </Workspace>
  );
}

function AssetPage<T extends Asset>({
  config,
  reviewOnly = false,
}: {
  config: AssetConfig<T>;
  reviewOnly?: boolean;
}) {
  const queryClient = useQueryClient();
  const queryPath =
    reviewOnly && config.kind === "test-cases"
      ? `${config.endpoint}?review_status=draft&limit=200`
      : `${config.endpoint}?limit=200`;
  const query = useQuery({
    queryKey: ["v1", config.kind, reviewOnly],
    queryFn: () => getPage<T>(queryPath),
  });
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [editor, setEditor] = useState(pretty(config.draft));
  const [notice, setNotice] = useState<string | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const selected = query.data?.items.find((item) => item.id === selectedId) ?? null;
  const locked = selected ? Boolean(config.immutable?.(selected)) : false;

  useEffect(() => {
    if (!selectedId && query.data?.items[0]) {
      const first = query.data.items[0];
      setSelectedId(first.id);
      setEditor(pretty(config.clean(first)));
    }
  }, [config, query.data, selectedId]);

  const refresh = async () => {
    await queryClient.invalidateQueries({ queryKey: ["v1", config.kind] });
  };
  const mutation = useMutation({
    mutationFn: async () => {
      setParseError(null);
      let parsed: Record<string, unknown>;
      try {
        parsed = JSON.parse(editor);
      } catch (error) {
        throw new Error(`JSON 无法解析：${String(error)}`);
      }
      if (selected) {
        const payload = omit(parsed, ["id"]);
        return patchOne<T>(
          `${config.endpoint}/${encodeURIComponent(selected.id)}`,
          payload,
        );
      }
      return createOne<T>(config.endpoint, parsed);
    },
    onSuccess: async (item) => {
      setSelectedId(item.id);
      setEditor(pretty(config.clean(item)));
      setNotice(selected ? "修改已保存。" : "草稿已创建。");
      await refresh();
    },
    onError: (error) => setParseError(error instanceof Error ? error.message : String(error)),
  });

  const remove = async () => {
    if (!selected || !window.confirm(`确认删除 ${selected.name}？`)) return;
    try {
      await deleteOne(`${config.endpoint}/${encodeURIComponent(selected.id)}`);
      setSelectedId(null);
      setEditor(pretty(config.draft));
      setNotice("已删除。");
      await refresh();
    } catch (error) {
      setParseError(error instanceof Error ? error.message : String(error));
    }
  };

  const review = async (status: string) => {
    if (!selected) return;
    const parameter =
      config.kind === "test-cases" ? "review_status" : "sample_status";
    try {
      await postAction(
        `${config.endpoint}/${encodeURIComponent(selected.id)}/review?${parameter}=${status}`,
      );
      setNotice(`审核状态已更新为 ${status}。`);
      if (reviewOnly) {
        setSelectedId(null);
        setEditor(pretty(config.draft));
      }
      await refresh();
    } catch (error) {
      setParseError(error instanceof Error ? error.message : String(error));
    }
  };

  const checkTarget = async () => {
    if (!selected || config.kind !== "targets") return;
    try {
      const result = await postAction<Record<string, unknown>>(
        `/api/targets/${encodeURIComponent(selected.id)}/check`,
      );
      setNotice(String(result.message ?? "检查完成"));
    } catch (error) {
      setParseError(error instanceof Error ? error.message : String(error));
    }
  };

  return (
    <Workspace>
      <PageHeader
        eyebrow={`ASSETS / ${config.kind.toUpperCase()}`}
        title={reviewOnly ? "用例审核" : config.title}
        description={config.description}
        actions={
          <Button
            icon={<Plus />}
            variant="primary"
            onClick={() => {
              setSelectedId(null);
              setEditor(pretty(config.draft));
              setNotice(null);
              setParseError(null);
            }}
          >
            新建
          </Button>
        }
      />
      {notice ? <Notice>{notice}</Notice> : null}
      {parseError ? <Notice tone="danger">{parseError}</Notice> : null}
      <div className={styles.assetGrid}>
        <Panel
          title={`${query.data?.total ?? 0} 项`}
          eyebrow={reviewOnly ? "AWAITING HUMAN REVIEW" : "LIBRARY"}
          actions={
            <Button icon={<RefreshCcw />} size="sm" onClick={() => query.refetch()}>
              刷新
            </Button>
          }
        >
          <div className={styles.assetList}>
            {query.isLoading ? <Empty>正在读取…</Empty> : null}
            {query.error ? <Empty>{String(query.error)}</Empty> : null}
            {query.data?.items.map((item) => (
              <button
                className={`${styles.assetRow} ${item.id === selectedId ? styles.selected : ""}`}
                key={item.id}
                type="button"
                onClick={() => {
                  setSelectedId(item.id);
                  setEditor(pretty(config.clean(item)));
                  setNotice(null);
                  setParseError(null);
                }}
              >
                <span>
                  <strong>{item.name}</strong>
                  <small>{config.detail(item)}</small>
                </span>
                <span>
                  {config.status ? (
                    <Badge tone={toneForStatus(config.status(item))}>
                      {config.status(item)}
                    </Badge>
                  ) : null}
                  <ChevronRight size={14} />
                </span>
              </button>
            ))}
            {!query.isLoading && !query.data?.items.length ? <Empty>暂无数据</Empty> : null}
          </div>
        </Panel>
        <Panel
          title={selected ? selected.name : "新建草稿"}
          eyebrow={selected?.id ?? "UNSAVED"}
          actions={
            <>
              {config.kind === "targets" && selected ? (
                <Button icon={<SearchCheck />} size="sm" onClick={checkTarget}>
                  检查
                </Button>
              ) : null}
              {config.kind === "test-cases" && selected ? (
                <>
                  <Button icon={<Check />} size="sm" onClick={() => review("approved")}>
                    通过
                  </Button>
                  <Button icon={<Ban />} size="sm" onClick={() => review("rejected")}>
                    驳回
                  </Button>
                </>
              ) : null}
              {config.kind === "samples" && selected ? (
                <>
                  <Button icon={<Check />} size="sm" onClick={() => review("approved")}>
                    通过
                  </Button>
                  <Button icon={<Ban />} size="sm" onClick={() => review("disabled")}>
                    停用
                  </Button>
                </>
              ) : null}
            </>
          }
        >
          <div className={styles.editor}>
            {locked ? (
              <Notice>当前记录已通过审核或停用，内容只读；历史运行仍使用自己的快照。</Notice>
            ) : null}
            <textarea
              aria-label={`${config.title} JSON 编辑器`}
              value={editor}
              readOnly={locked}
              spellCheck={false}
              onChange={(event) => setEditor(event.target.value)}
            />
            <div className={styles.editorFooter}>
              <span>JSON 会由后端 Pydantic Schema 再校验。</span>
              <div>
                {selected ? (
                  <Button
                    icon={<Trash2 />}
                    variant="danger"
                    disabled={locked}
                    onClick={remove}
                  >
                    删除
                  </Button>
                ) : null}
                <Button
                  icon={<Save />}
                  variant="primary"
                  disabled={locked || mutation.isPending}
                  onClick={() => mutation.mutate()}
                >
                  {selected ? "保存" : "创建"}
                </Button>
              </div>
            </div>
          </div>
        </Panel>
      </div>
    </Workspace>
  );
}

function RunsPage({ pathname }: { pathname: string }) {
  const navigate = useNavigate();
  const queryClient = useQueryClient();
  const pathRunId = pathname.match(/^\/evaluation\/batches\/([^/]+)$/)?.[1];
  const selectedRunId = pathRunId ? decodeURIComponent(pathRunId) : null;
  const runs = useQuery({
    queryKey: ["v1", "runs"],
    queryFn: () => getPage<Run>("/api/runs?limit=100"),
    refetchInterval: 4_000,
  });
  const run = useQuery({
    queryKey: ["v1", "run", selectedRunId],
    queryFn: () => getOne<Run>(`/api/runs/${encodeURIComponent(selectedRunId!)}`),
    enabled: Boolean(selectedRunId),
    refetchInterval: (query) =>
      ["queued", "running"].includes(query.state.data?.status ?? "") ? 2_000 : false,
  });
  const caseRuns = useQuery({
    queryKey: ["v1", "case-runs", selectedRunId],
    queryFn: () =>
      getPage<CaseRun>(
        `/api/runs/${encodeURIComponent(selectedRunId!)}/case-runs?limit=200`,
      ),
    enabled: Boolean(selectedRunId),
    refetchInterval: ["queued", "running"].includes(run.data?.status ?? "") ? 2_000 : false,
  });
  const [createOpen, setCreateOpen] = useState(!selectedRunId && !runs.data?.items.length);
  const [draft, setDraft] = useState(
    pretty({
      case_ids: ["case_id"],
      targets: [{ role: "candidate", target_id: "target_id" }],
      profile_id: null,
      overrides: {},
    }),
  );
  const [selectedCaseRunId, setSelectedCaseRunId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const caseRun = useQuery({
    queryKey: ["v1", "case-run", selectedCaseRunId],
    queryFn: () =>
      getOne<CaseRun>(`/api/case-runs/${encodeURIComponent(selectedCaseRunId!)}`),
    enabled: Boolean(selectedCaseRunId),
  });
  const create = useMutation({
    mutationFn: () => createOne<{ run_id: string }>("/api/runs", JSON.parse(draft)),
    onSuccess: async (result) => {
      setCreateOpen(false);
      await queryClient.invalidateQueries({ queryKey: ["v1", "runs"] });
      navigate(`/evaluation/batches/${encodeURIComponent(result.run_id)}`);
    },
    onError: (value) => setError(value instanceof Error ? value.message : String(value)),
  });

  useEffect(() => {
    if (!selectedCaseRunId && caseRuns.data?.items[0]) {
      setSelectedCaseRunId(caseRuns.data.items[0].id);
    }
  }, [caseRuns.data, selectedCaseRunId]);

  const cancel = async () => {
    if (!selectedRunId) return;
    await postAction(`/api/runs/${encodeURIComponent(selectedRunId)}/cancel`);
    await run.refetch();
  };

  return (
    <Workspace>
      <PageHeader
        eyebrow="EXECUTION / RUNS"
        title={selectedRunId ? `Run ${shortId(selectedRunId)}` : "运行记录"}
        description="单用例、批量、多版本、重复和 A/B 都使用同一异步入口。"
        actions={
          <>
            {selectedRunId ? (
              <Button onClick={() => navigate("/evaluation/batches")}>返回列表</Button>
            ) : null}
            {run.data && ["queued", "running"].includes(run.data.status) ? (
              <Button icon={<CircleStop />} variant="danger" onClick={cancel}>
                取消
              </Button>
            ) : null}
            <Button icon={<Play />} variant="primary" onClick={() => setCreateOpen(true)}>
              提交运行
            </Button>
          </>
        }
      />
      {error ? <Notice tone="danger">{error}</Notice> : null}
      {createOpen ? (
        <Panel title="run_cases 请求" eyebrow="ASYNC SUBMISSION">
          <div className={styles.editor}>
            <textarea value={draft} spellCheck={false} onChange={(event) => setDraft(event.target.value)} />
            <div className={styles.editorFooter}>
              <span>提交后立即返回 Run ID；版本留空时按用例支持版本展开。</span>
              <div>
                <Button onClick={() => setCreateOpen(false)}>关闭</Button>
                <Button variant="primary" icon={<Play />} onClick={() => create.mutate()}>
                  提交
                </Button>
              </div>
            </div>
          </div>
        </Panel>
      ) : null}
      {!selectedRunId ? (
        <Panel title={`${runs.data?.total ?? 0} 个 Run`} eyebrow="HISTORY">
          <RunTable
            runs={runs.data?.items ?? []}
            empty="尚无运行记录。"
            onSelect={(item) =>
              navigate(`/evaluation/batches/${encodeURIComponent(item.id)}`)
            }
          />
        </Panel>
      ) : (
        <>
          <RunSummary run={run.data} />
          <div className={styles.runGrid}>
            <Panel title={`${caseRuns.data?.total ?? 0} 个 CaseRun`} eyebrow="ATOMIC RESULTS">
              <div className={styles.assetList}>
                {caseRuns.data?.items.map((item) => (
                  <button
                    type="button"
                    key={item.id}
                    className={`${styles.assetRow} ${selectedCaseRunId === item.id ? styles.selected : ""}`}
                    onClick={() => setSelectedCaseRunId(item.id)}
                  >
                    <span>
                      <strong>{item.case_id}</strong>
                      <small>
                        {item.version ?? "default"} · repeat {item.repeat_index}
                        {item.comparison_role ? ` · ${item.comparison_role}` : ""}
                      </small>
                    </span>
                    <span>
                      <Badge tone={toneForStatus(item.evaluation_state)}>
                        {item.evaluation_state}
                      </Badge>
                      <ChevronRight size={14} />
                    </span>
                  </button>
                ))}
              </div>
            </Panel>
            <CaseRunDetailPanel
              value={caseRun.data}
              onVerdict={async (payload) => {
                if (!selectedCaseRunId) return;
                await putOne(
                  `/api/case-runs/${encodeURIComponent(selectedCaseRunId)}/external-verdict`,
                  payload,
                );
                await caseRun.refetch();
                await caseRuns.refetch();
              }}
            />
          </div>
        </>
      )}
    </Workspace>
  );
}

function RunSummary({ run }: { run?: Run }) {
  if (!run) return <Panel><Empty>正在读取 Run…</Empty></Panel>;
  return (
    <div className={styles.stats}>
      <StatCard
        label="调度状态"
        value={run.status}
        meta={run.failed_count ? `${run.failed_count} execution failed` : shortId(run.id)}
        accent={run.failed_count ? "coral" : "blue"}
      />
      <StatCard label="已完成" value={run.completed_count} meta={`共 ${run.total_count}`} accent="green" />
      <StatCard label="失败" value={run.failed_count} meta="execution failed" accent="coral" />
      <StatCard label="跳过" value={run.skipped_count} meta={`${run.cancelled_count} cancelled`} accent="amber" />
    </div>
  );
}

function CaseRunDetailPanel({
  value,
  onVerdict,
}: {
  value?: CaseRun;
  onVerdict: (payload: Record<string, unknown>) => Promise<void>;
}) {
  const [verdict, setVerdict] = useState("pass");
  const [summary, setSummary] = useState("");
  const [evidenceRefs, setEvidenceRefs] = useState("");
  const [saving, setSaving] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);
  if (!value) {
    return <Panel title="CaseRun 证据"><Empty>选择一个 CaseRun。</Empty></Panel>;
  }
  const canSubmitExternal = !["queued", "running"].includes(value.status);
  return (
    <Panel
      title={`${value.case_id} · ${value.evaluation_state}`}
      eyebrow={value.id}
      actions={<Badge tone={toneForStatus(value.status)}>{value.status}</Badge>}
    >
      <div className={styles.caseRunDetail}>
        {value.error_message ? <Notice tone="danger">{value.error_code}: {value.error_message}</Notice> : null}
        <section>
          <h3>事件流</h3>
          <div className={styles.timeline}>
            {value.events?.map((event) => (
              <details key={event.id}>
                <summary>
                  <span>{String(event.seq).padStart(2, "0")}</span>
                  <strong>{event.event_type}</strong>
                  <small>{shortId(event.id)}</small>
                </summary>
                <pre>{pretty(event.payload)}</pre>
              </details>
            ))}
          </div>
        </section>
        <section>
          <h3>评判器输出</h3>
          {value.evaluations?.length ? (
            value.evaluations.map((evaluation, index) => (
              <pre className={styles.evaluation} key={String(evaluation.id ?? index)}>
                {pretty(evaluation)}
              </pre>
            ))
          ) : (
            <Empty>尚无评判记录。</Empty>
          )}
        </section>
        {canSubmitExternal ? (
          <section className={styles.verdictForm}>
            <h3>外部控制方判定</h3>
            <p>
              当前主评判器为 <code>{value.primary_evaluator}</code>。提交后会保存或重写
              External 记录，并以该外部结果作为当前结论。
            </p>
            <select value={verdict} onChange={(event) => setVerdict(event.target.value)}>
              <option value="pass">pass</option>
              <option value="fail">fail</option>
              <option value="inconclusive">inconclusive</option>
            </select>
            <textarea
              value={summary}
              placeholder="根据上方事件填写判定依据"
              onChange={(event) => setSummary(event.target.value)}
            />
            <textarea
              value={evidenceRefs}
              placeholder="可选：引用的事件 ID，一行一个或用逗号分隔"
              onChange={(event) => setEvidenceRefs(event.target.value)}
            />
            {formError ? <Notice tone="danger">{formError}</Notice> : null}
            <Button
              variant="primary"
              icon={<Save />}
              disabled={saving || !summary.trim()}
              onClick={async () => {
                setSaving(true);
                setFormError(null);
                try {
                  await onVerdict({
                    verdict,
                    summary,
                    evidence_refs: evidenceRefs
                      .split(/[\s,]+/)
                      .map((item) => item.trim())
                      .filter(Boolean),
                    submitted_by: "agentrig.web",
                  });
                } catch (error) {
                  setFormError(error instanceof Error ? error.message : String(error));
                } finally {
                  setSaving(false);
                }
              }}
            >
              回写判定
            </Button>
          </section>
        ) : null}
      </div>
    </Panel>
  );
}

function RunTable({
  runs,
  empty,
  onSelect,
}: {
  runs: Run[];
  empty: string;
  onSelect?: (run: Run) => void;
}) {
  const navigate = useNavigate();
  if (!runs.length) return <Empty>{empty}</Empty>;
  return (
    <div className={styles.tableWrap}>
      <table className={styles.table}>
        <thead>
          <tr>
            <th>Run</th>
            <th>状态</th>
            <th>用例</th>
            <th>进度</th>
            <th>创建时间</th>
            <th />
          </tr>
        </thead>
        <tbody>
          {runs.map((item) => (
            <tr key={item.id}>
              <td><code>{shortId(item.id)}</code></td>
              <td>
                <Badge tone={toneForRun(item)}>
                  {item.status}
                  {item.failed_count ? ` · ${item.failed_count} failed` : ""}
                </Badge>
              </td>
              <td>{item.resolved_case_ids.length}</td>
              <td>{item.completed_count + item.failed_count + item.skipped_count + item.cancelled_count} / {item.total_count}</td>
              <td>{formatDate(item.created_at)}</td>
              <td>
                <Button
                  size="sm"
                  onClick={() =>
                    onSelect
                      ? onSelect(item)
                      : navigate(`/evaluation/batches/${encodeURIComponent(item.id)}`)
                  }
                >
                  查看
                </Button>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function Workspace({ children }: { children: ReactNode }) {
  return <div className={`workspace workspace--centered ${styles.workspace}`}>{children}</div>;
}

function Notice({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: "neutral" | "danger";
}) {
  return <div className={`${styles.notice} ${tone === "danger" ? styles.noticeDanger : ""}`}>{children}</div>;
}

function Empty({ children }: { children: ReactNode }) {
  return <div className={styles.empty}><FileJson size={18} /> <span>{children}</span></div>;
}

function omit(
  value: Record<string, unknown>,
  keys: string[],
): Record<string, unknown> {
  return Object.fromEntries(Object.entries(value).filter(([key]) => !keys.includes(key)));
}

function pretty(value: unknown): string {
  return JSON.stringify(value, null, 2);
}

function shortId(value: string): string {
  const parts = value.split("_");
  return parts.length > 1 ? `${parts[0]}_${parts[1]?.slice(0, 8)}` : value.slice(0, 12);
}

function formatDate(value: string): string {
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function toneForStatus(status: string): Tone {
  if (["approved", "pass", "completed", "reachable"].includes(status)) return "success";
  if (["failed", "fail", "rejected", "disabled", "cancelled", "evaluation_error"].includes(status)) return "danger";
  if (["running", "queued", "draft", "awaiting_verdict", "inconclusive"].includes(status)) return "warning";
  return "neutral";
}

function toneForRun(run: Run): Tone {
  if (run.failed_count) return "danger";
  return toneForStatus(run.status);
}
