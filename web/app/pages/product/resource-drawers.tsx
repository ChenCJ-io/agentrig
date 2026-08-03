import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CircleAlert, Plus, Save, Trash2, X } from "lucide-react";
import { useEffect, useState, type FormEvent, type ReactNode } from "react";

import {
  createOne,
  deleteOne,
  getOne,
  patchOne,
  type ExecutionProfile,
  type Sample,
  type Target,
  type TestCase,
} from "~/api/v1";
import { Button } from "~/components/ui/button";

import styles from "./product-page.module.css";

type ResourceKind = "被测 Agent" | "测试用例" | "结果样本" | "执行配置";

interface DrawerShellProps {
  children: ReactNode;
  error: string | null;
  eyebrow: string;
  isEditing: boolean;
  isPending: boolean;
  kind: ResourceKind;
  onClose: () => void;
  onDelete?: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}

function DrawerShell({ children, error, eyebrow, isEditing, isPending, kind, onClose, onDelete, onSubmit }: DrawerShellProps) {
  const [confirmDelete, setConfirmDelete] = useState(false);
  return (
    <div className={styles.drawerBackdrop} role="presentation">
      <form className={styles.runDrawer} onSubmit={onSubmit}>
        <header><div><span className="eyebrow">{eyebrow}</span><h2>{isEditing ? `编辑${kind}` : `新建${kind}`}</h2></div><button aria-label="关闭" onClick={onClose} type="button"><X size={15} /></button></header>
        <div className={styles.drawerBody}>
          {children}
          {error ? <div className={styles.queryFailure}><CircleAlert size={14} /><span>{error}</span></div> : null}
          {confirmDelete ? <div className={styles.deleteConfirm}><p>删除后该资源无法恢复。确认删除？</p><div><Button disabled={isPending} onClick={() => setConfirmDelete(false)}>取消</Button><Button disabled={isPending} icon={<Trash2 />} onClick={onDelete} variant="danger">确认删除</Button></div></div> : null}
        </div>
        <footer>
          {isEditing && onDelete && !confirmDelete ? <Button className={styles.deleteButton} disabled={isPending} icon={<Trash2 />} onClick={() => setConfirmDelete(true)} variant="quiet">删除</Button> : null}
          <Button disabled={isPending} onClick={onClose}>取消</Button>
          <Button disabled={isPending} icon={isEditing ? <Save /> : <Plus />} type="submit" variant="primary">{isEditing ? "保存修改" : "创建草稿"}</Button>
        </footer>
      </form>
    </div>
  );
}

function JsonField({ label, hint, value, onChange }: { label: string; hint?: string; value: string; onChange: (value: string) => void }) {
  return <label>{label}{hint ? <small>{hint}</small> : null}<textarea className={styles.jsonEditor} onChange={(event) => onChange(event.target.value)} spellCheck={false} value={value} /></label>;
}

function parseJson<T>(value: string, label: string): T {
  try {
    return JSON.parse(value) as T;
  } catch (error) {
    throw new Error(`${label} 不是合法 JSON：${error instanceof Error ? error.message : String(error)}`);
  }
}

function message(error: unknown) {
  return error instanceof Error ? error.message : String(error);
}

export function TargetEditorDrawer({ initial, onClose, onSaved }: { initial?: Target | null; onClose: () => void; onSaved: (target?: Target) => void }) {
  const queryClient = useQueryClient();
  const drivers = useQuery({ queryKey: ["product", "driver-types"], queryFn: () => getOne<Array<{ driver_type: string; deployment_ready: boolean }>>("/api/driver-types") });
  const [id, setId] = useState("");
  const [name, setName] = useState("");
  const [driverType, setDriverType] = useState("pixcake_http_sse");
  const [endpoint, setEndpoint] = useState("");
  const [secretRef, setSecretRef] = useState("");
  const [versions, setVersions] = useState("[]");
  const [options, setOptions] = useState("{}");
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    setId(initial?.id ?? ""); setName(initial?.name ?? ""); setDriverType(initial?.driver_type ?? "pixcake_http_sse"); setEndpoint(initial?.endpoint ?? ""); setSecretRef(typeof initial?.secret_ref === "string" ? initial.secret_ref : ""); setVersions(JSON.stringify(initial?.versions ?? [], null, 2)); setOptions(JSON.stringify(initial?.options ?? {}, null, 2)); setError(null);
  }, [initial]);
  const save = useMutation({
    mutationFn: async () => {
      const value = { name: name.trim(), driver_type: driverType, endpoint: endpoint.trim() || null, secret_ref: secretRef.trim() || null, versions: parseJson<unknown[]>(versions, "版本定义"), options: parseJson<Record<string, unknown>>(options, "驱动参数") };
      return initial ? patchOne<Target>(`/api/targets/${encodeURIComponent(initial.id)}`, value) : createOne<Target>("/api/targets", { ...value, id: id.trim() || null });
    },
    onSuccess: async (target) => { await queryClient.invalidateQueries({ queryKey: ["product", "targets"] }); onSaved(target); },
    onError: (value) => setError(message(value)),
  });
  const remove = useMutation({ mutationFn: () => deleteOne(`/api/targets/${encodeURIComponent(initial!.id)}`), onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ["product", "targets"] }); onSaved(); }, onError: (value) => setError(message(value)) });
  return <DrawerShell error={error} eyebrow="被测对象 · 连接配置" isEditing={Boolean(initial)} isPending={save.isPending || remove.isPending} kind="被测 Agent" onClose={onClose} onDelete={initial ? () => remove.mutate() : undefined} onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
    <div className={styles.formGrid}>{!initial ? <label>被测对象 ID（Target ID，可选）<input onChange={(event) => setId(event.target.value)} placeholder="target_lassist" value={id} /></label> : <label>被测对象 ID<input readOnly value={initial.id} /></label>}<label>显示名称<input onChange={(event) => setName(event.target.value)} required value={name} /></label></div>
    <label>接入驱动（Driver）<select onChange={(event) => setDriverType(event.target.value)} value={driverType}>{(drivers.data ?? [{ driver_type: driverType, deployment_ready: true }]).map((driver) => <option disabled={!driver.deployment_ready} key={driver.driver_type} value={driver.driver_type}>{driver.driver_type}{driver.deployment_ready ? "" : " · 当前不可部署"}</option>)}</select></label>
    <label>服务地址（Endpoint，可选）<input onChange={(event) => setEndpoint(event.target.value)} placeholder="http://127.0.0.1:8008" value={endpoint} /></label>
    <label>密钥引用（Secret Reference，可选）<input onChange={(event) => setSecretRef(event.target.value)} placeholder="env:TARGET_API_KEY" value={secretRef} /><small>只允许 env:VARIABLE_NAME，不保存明文密钥。</small></label>
    <JsonField hint='例如 [{"version":"v1"}]' label="版本定义（Versions）" onChange={setVersions} value={versions} />
    <JsonField hint="驱动专用参数；保存前由服务端校验" label="驱动参数（Options）" onChange={setOptions} value={options} />
  </DrawerShell>;
}

export function CaseEditorDrawer({ initial, onClose, onSaved }: { initial?: TestCase | null; onClose: () => void; onSaved: (item?: TestCase) => void }) {
  const queryClient = useQueryClient();
  const [id, setId] = useState(""); const [name, setName] = useState(""); const [description, setDescription] = useState(""); const [tags, setTags] = useState(""); const [versions, setVersions] = useState(""); const [evaluator, setEvaluator] = useState("rule"); const [rubric, setRubric] = useState(""); const [initialState, setInitialState] = useState("{}"); const [caseAssertions, setCaseAssertions] = useState("[]"); const [turns, setTurns] = useState("[]"); const [error, setError] = useState<string | null>(null);
  useEffect(() => { setId(initial?.id ?? ""); setName(initial?.name ?? ""); setDescription(initial?.description ?? ""); setTags(initial?.tags.join(", ") ?? ""); setVersions(initial?.supported_versions.join(", ") ?? ""); setEvaluator(initial?.primary_evaluator ?? "rule"); setRubric(typeof initial?.case_rubric === "string" ? initial.case_rubric : ""); setInitialState(JSON.stringify(initial?.initial_state ?? {}, null, 2)); setCaseAssertions(JSON.stringify(initial?.case_assertions ?? [], null, 2)); setTurns(JSON.stringify(initial?.turns ?? [{ position: 1, user_message: "", fixtures: [], assertions: [{ kind: "no_execution_error" }] }], null, 2)); setError(null); }, [initial]);
  const save = useMutation({ mutationFn: async () => { const value = { name: name.trim(), description, tags: splitList(tags), supported_versions: splitList(versions), primary_evaluator: evaluator, initial_state: parseJson<Record<string, unknown>>(initialState, "初始状态"), case_assertions: parseJson<unknown[]>(caseAssertions, "用例断言"), case_rubric: rubric.trim() || null, turns: parseJson<unknown[]>(turns, "对话轮次") }; return initial ? patchOne<TestCase>(`/api/test-cases/${encodeURIComponent(initial.id)}`, value) : createOne<TestCase>("/api/test-cases", { ...value, id: id.trim() || null }); }, onSuccess: async (item) => { await queryClient.invalidateQueries({ queryKey: ["product", "cases"] }); onSaved(item); }, onError: (value) => setError(message(value)) });
  const remove = useMutation({ mutationFn: () => deleteOne(`/api/test-cases/${encodeURIComponent(initial!.id)}`), onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ["product", "cases"] }); onSaved(); }, onError: (value) => setError(message(value)) });
  return <DrawerShell error={error} eyebrow="测试用例 · 结构化定义" isEditing={Boolean(initial)} isPending={save.isPending || remove.isPending} kind="测试用例" onClose={onClose} onDelete={initial && initial.review_status !== "approved" ? () => remove.mutate() : undefined} onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
    <div className={styles.formGrid}>{!initial ? <label>用例 ID（Case ID，可选）<input onChange={(event) => setId(event.target.value)} value={id} /></label> : <label>用例 ID<input readOnly value={initial.id} /></label>}<label>名称<input onChange={(event) => setName(event.target.value)} required value={name} /></label></div>
    <label>说明<textarea className={styles.textEditor} onChange={(event) => setDescription(event.target.value)} value={description} /></label>
    <div className={styles.formGrid}><label>标签（逗号分隔）<input onChange={(event) => setTags(event.target.value)} placeholder="cap.edit, priority.p0" value={tags} /></label><label>支持版本（逗号分隔）<input onChange={(event) => setVersions(event.target.value)} placeholder="v1, v2" value={versions} /></label></div>
    <label>主要评判器（Primary Evaluator）<select onChange={(event) => setEvaluator(event.target.value)} value={evaluator}><option value="rule">规则评判器（rule）</option><option value="evidence_judge">证据裁决（evidence_judge）</option><option value="external_controller">外部控制器（external_controller）</option></select></label>
    <JsonField label="初始状态（Initial State）" onChange={setInitialState} value={initialState} /><JsonField label="用例断言（Case Assertions）" onChange={setCaseAssertions} value={caseAssertions} />
    <label>评判标准（Case Rubric）<textarea className={styles.textEditor} onChange={(event) => setRubric(event.target.value)} value={rubric} /></label>
    <JsonField hint="必须包含连续 position 和非空 user_message" label="对话轮次（Conversation Turns）" onChange={setTurns} value={turns} />
  </DrawerShell>;
}

export function SampleEditorDrawer({ initial, onClose, onSaved }: { initial?: Sample | null; onClose: () => void; onSaved: (item?: Sample) => void }) {
  const queryClient = useQueryClient();
  const [id, setId] = useState(""); const [name, setName] = useState(""); const [toolName, setToolName] = useState(""); const [kind, setKind] = useState("single"); const [versions, setVersions] = useState(""); const [matchArguments, setMatchArguments] = useState("{}"); const [ignoredPaths, setIgnoredPaths] = useState(""); const [content, setContent] = useState("{}"); const [error, setError] = useState<string | null>(null);
  useEffect(() => { setId(initial?.id ?? ""); setName(initial?.name ?? ""); setToolName(initial?.tool_name ?? ""); setKind(initial?.sample_kind ?? "single"); setVersions(initial?.supported_versions.join(", ") ?? ""); setMatchArguments(JSON.stringify(initial?.match_arguments ?? {}, null, 2)); setIgnoredPaths(Array.isArray(initial?.ignored_argument_paths) ? initial.ignored_argument_paths.join(", ") : ""); setContent(JSON.stringify(initial?.content ?? {}, null, 2)); setError(null); }, [initial]);
  const save = useMutation({ mutationFn: async () => { const value = { name: name.trim(), tool_name: kind === "single" ? toolName.trim() : null, sample_kind: kind, content: parseJson<unknown>(content, "工具返回内容"), match_arguments: parseJson<Record<string, unknown>>(matchArguments, "参数匹配规则"), ignored_argument_paths: splitList(ignoredPaths), supported_versions: splitList(versions) }; return initial ? patchOne<Sample>(`/api/samples/${encodeURIComponent(initial.id)}`, value) : createOne<Sample>("/api/samples", { ...value, id: id.trim() || null }); }, onSuccess: async (item) => { await queryClient.invalidateQueries({ queryKey: ["product", "samples"] }); onSaved(item); }, onError: (value) => setError(message(value)) });
  const remove = useMutation({ mutationFn: () => deleteOne(`/api/samples/${encodeURIComponent(initial!.id)}`), onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ["product", "samples"] }); onSaved(); }, onError: (value) => setError(message(value)) });
  return <DrawerShell error={error} eyebrow="结果样本 · 工具返回" isEditing={Boolean(initial)} isPending={save.isPending || remove.isPending} kind="结果样本" onClose={onClose} onDelete={initial && initial.status === "draft" ? () => remove.mutate() : undefined} onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
    <div className={styles.formGrid}>{!initial ? <label>样本 ID（Sample ID，可选）<input onChange={(event) => setId(event.target.value)} value={id} /></label> : <label>样本 ID<input readOnly value={initial.id} /></label>}<label>名称<input onChange={(event) => setName(event.target.value)} required value={name} /></label></div>
    <div className={styles.formGrid}><label>样本类型<select onChange={(event) => setKind(event.target.value)} value={kind}><option value="single">单次结果（single）</option><option value="sequence">结果序列（sequence）</option></select></label><label>工具名称（Tool Name）<input disabled={kind !== "single"} onChange={(event) => setToolName(event.target.value)} required={kind === "single"} value={toolName} /></label></div>
    <label>支持版本（逗号分隔）<input onChange={(event) => setVersions(event.target.value)} value={versions} /></label><JsonField label="参数匹配规则（Match Arguments）" onChange={setMatchArguments} value={matchArguments} /><label>忽略参数路径（逗号分隔）<input onChange={(event) => setIgnoredPaths(event.target.value)} value={ignoredPaths} /></label><JsonField hint={kind === "sequence" ? "结果序列需要非空 SampleStep 数组" : "被测 Agent 收到的工具结果"} label="工具返回内容（Tool Result）" onChange={setContent} value={content} />
  </DrawerShell>;
}

export function ProfileEditorDrawer({ initial, onClose, onSaved }: { initial?: ExecutionProfile | null; onClose: () => void; onSaved: (item?: ExecutionProfile) => void }) {
  const queryClient = useQueryClient();
  const [id, setId] = useState(""); const [name, setName] = useState(""); const [description, setDescription] = useState(""); const [toolMode, setToolMode] = useState("controlled"); const [providers, setProviders] = useState("fixture, sample"); const [evaluator, setEvaluator] = useState("rule"); const [concurrency, setConcurrency] = useState(4); const [timeout, setTimeoutValue] = useState(300); const [repeatCount, setRepeatCount] = useState(1); const [error, setError] = useState<string | null>(null);
  useEffect(() => { setId(initial?.id ?? ""); setName(initial?.name ?? ""); setDescription(initial?.description ?? ""); setToolMode(initial?.config.tool_mode ?? "controlled"); setProviders(initial?.config.provider_chain.map((entry) => entry.name).join(", ") ?? "fixture, sample"); setEvaluator(initial?.config.primary_evaluator ?? "rule"); setConcurrency(initial?.config.concurrency ?? 4); setTimeoutValue(typeof initial?.config.case_timeout_seconds === "number" ? initial.config.case_timeout_seconds : 300); setRepeatCount(typeof initial?.config.repeat_count === "number" ? initial.config.repeat_count : 1); setError(null); }, [initial]);
  const save = useMutation({ mutationFn: async () => { const config = { ...(initial?.config ?? {}), tool_mode: toolMode, provider_chain: toolMode === "observe_only" ? [] : splitList(providers).map((provider) => ({ name: provider })), primary_evaluator: evaluator || null, concurrency, case_timeout_seconds: timeout, repeat_count: repeatCount }; const value = { name: name.trim(), description, config }; return initial ? patchOne<ExecutionProfile>(`/api/execution-profiles/${encodeURIComponent(initial.id)}`, value) : createOne<ExecutionProfile>("/api/execution-profiles", { ...value, id: id.trim() || null }); }, onSuccess: async (item) => { await queryClient.invalidateQueries({ queryKey: ["product", "profiles"] }); onSaved(item); }, onError: (value) => setError(message(value)) });
  const remove = useMutation({ mutationFn: () => deleteOne(`/api/execution-profiles/${encodeURIComponent(initial!.id)}`), onSuccess: async () => { await queryClient.invalidateQueries({ queryKey: ["product", "profiles"] }); onSaved(); }, onError: (value) => setError(message(value)) });
  return <DrawerShell error={error} eyebrow="执行配置 · 运行策略" isEditing={Boolean(initial)} isPending={save.isPending || remove.isPending} kind="执行配置" onClose={onClose} onDelete={initial ? () => remove.mutate() : undefined} onSubmit={(event) => { event.preventDefault(); save.mutate(); }}>
    <div className={styles.formGrid}>{!initial ? <label>配置 ID（Profile ID，可选）<input onChange={(event) => setId(event.target.value)} value={id} /></label> : <label>配置 ID<input readOnly value={initial.id} /></label>}<label>名称<input onChange={(event) => setName(event.target.value)} required value={name} /></label></div><label>说明<textarea className={styles.textEditor} onChange={(event) => setDescription(event.target.value)} value={description} /></label>
    <div className={styles.formGrid}><label>工具模式（Tool Mode）<select onChange={(event) => setToolMode(event.target.value)} value={toolMode}><option value="controlled">受控返回（controlled）</option><option value="proxy">代理调用（proxy）</option><option value="observe_only">仅观测（observe_only）</option></select></label><label>主要评判器<select onChange={(event) => setEvaluator(event.target.value)} value={evaluator}><option value="rule">规则评判器（rule）</option><option value="evidence_judge">证据裁决（evidence_judge）</option><option value="external_controller">外部控制器（external_controller）</option></select></label></div>
    <label>结果提供链（Provider Chain，逗号分隔）<input disabled={toolMode === "observe_only"} onChange={(event) => setProviders(event.target.value)} placeholder="fixture, sample, simulation_curator" value={toolMode === "observe_only" ? "" : providers} /></label>
    <div className={styles.formGrid}><label>并发数<input min={1} onChange={(event) => setConcurrency(Number(event.target.value))} type="number" value={concurrency} /></label><label>用例超时（秒）<input min={1} onChange={(event) => setTimeoutValue(Number(event.target.value))} type="number" value={timeout} /></label></div><label>重复执行次数<input min={1} onChange={(event) => setRepeatCount(Number(event.target.value))} type="number" value={repeatCount} /></label>
  </DrawerShell>;
}

function splitList(value: string) {
  return [...new Set(value.split(",").map((item) => item.trim()).filter(Boolean))];
}
