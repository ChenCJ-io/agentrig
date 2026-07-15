import { useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { Button, Card, Pill, SectionTitle, StatusBadge } from "../components/ui";
import { Check, Play, Plus } from "../components/icons";
import { useI18n } from "../i18n";
import { getCase, runCase, upsertCase } from "../lib/api";
import { mockCases } from "../lib/mock";
import type { Expectation, JudgeMode, TestCase } from "../lib/types";

const empty: TestCase = {
  id: "",
  name: "",
  user_message: "",
  expected_tools: [],
  expectations: [],
  mock: {},
  tags: [],
  judge_mode: "rule",
};

function safeParse(s: string): Record<string, unknown> {
  try {
    const v = JSON.parse(s);
    return v && typeof v === "object" ? (v as Record<string, unknown>) : {};
  } catch {
    return {};
  }
}

function expSummary(e: Expectation): string {
  if (e.kind === "expected_tools") return (e.tools ?? []).join(", ");
  if (e.kind === "tool_call_order") return (e.tools ?? []).join(" → ");
  if (e.kind === "text_contains") return String(e.needle ?? "");
  if (e.kind === "not_called") return (e.tools ?? []).join(", ");
  return JSON.stringify(e);
}

export default function CaseEditor() {
  const { id } = useParams();
  const nav = useNavigate();
  const { t } = useI18n();
  const [c, setC] = useState<TestCase>(empty);
  const [tab, setTab] = useState<"definition" | "mocks" | "history">("definition");
  const [saved, setSaved] = useState(false);
  const [mockText, setMockText] = useState("{}");

  useEffect(() => {
    if (!id) {
      setC(empty);
      setMockText("{}");
      return;
    }
    const fallback = mockCases.find((x) => x.id === id);
    getCase(id)
      .then(setC)
      .catch(() => fallback && setC(fallback));
  }, [id]);

  useEffect(() => {
    setMockText(JSON.stringify(c.mock, null, 2));
  }, [c.mock]);

  const set = (patch: Partial<TestCase>) => setC((p) => ({ ...p, ...patch }));

  const save = async () => {
    const patched: TestCase = { ...c, mock: safeParse(mockText) };
    try {
      const r = await upsertCase(patched);
      setC(r);
    } catch {
      /* 离线：保留本地 */
    }
    setSaved(true);
    setTimeout(() => setSaved(false), 1500);
  };

  const saveRun = async () => {
    const patched: TestCase = { ...c, mock: safeParse(mockText) };
    const savedCase = await upsertCase(patched).catch(() => patched);
    const run = await runCase(savedCase.id).catch(() => null);
    nav(`/cases/${savedCase.id}/run`, {
      state: { run, caseName: savedCase.name },
    });
  };

  const addAssertion = () =>
    set({ expectations: [...c.expectations, { kind: "expected_tools", tools: [] }] });
  const delAssertion = (i: number) =>
    set({ expectations: c.expectations.filter((_, idx) => idx !== i) });

  const toolsMocked = Object.keys(safeParse(mockText));
  const mockCover = c.expected_tools.length
    ? c.expected_tools.every((x) => toolsMocked.includes(x))
    : toolsMocked.length > 0;

  return (
    <div className="p-8 max-w-6xl">
      {/* Header */}
      <div className="mb-5">
        <p className="text-xs text-ink-mute mb-2">
          <button onClick={() => nav("/cases")} className="hover:text-ink">
            {t("nav.cases")}
          </button>{" "}
          / <span className="font-mono">{c.id || "new"}</span>
        </p>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold">{c.name || t("action.newCase")}</h1>
            {c.last_result && <StatusBadge status={c.last_result} />}
          </div>
          <div className="flex gap-2">
            <Button variant="ghost" onClick={() => nav(-1)}>
              {t("action.discard")}
            </Button>
            <Button variant="outline" onClick={save}>
              {saved ? <Check width={14} height={14} /> : null}
              {saved ? t("common.saveOk") : t("action.save")}
            </Button>
            <Button variant="primary" onClick={saveRun}>
              <Play width={14} height={14} />
              {t("action.saveRun")}
            </Button>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="flex items-center gap-5 border-b border-line mb-5">
        {(["definition", "mocks", "history"] as const).map((tb) => (
          <button
            key={tb}
            onClick={() => setTab(tb)}
            className={`pb-2.5 text-xs font-medium border-b-2 -mb-px ${
              tab === tb ? "border-accent text-ink" : "border-transparent text-ink-mute"
            }`}
          >
            {t(`editor.tab.${tb}`)}
          </button>
        ))}
      </div>

      <div className="grid grid-cols-3 gap-5">
        {/* 左：表单 */}
        <div className="col-span-2 space-y-5">
          {tab === "definition" && (
            <>
              <Card className="p-5">
                <SectionTitle title={t("editor.scenario")} subtitle={t("editor.scenarioHint")} />
                <div className="grid grid-cols-2 gap-3">
                  <Field label={t("editor.caseId")}>
                    <input
                      value={c.id}
                      onChange={(e) => set({ id: e.target.value })}
                      className={inputCls}
                    />
                  </Field>
                  <Field label={t("editor.name")}>
                    <input
                      value={c.name}
                      onChange={(e) => set({ name: e.target.value })}
                      className={inputCls}
                    />
                  </Field>
                  <Field label={t("editor.tagsField")}>
                    <input
                      value={c.tags.join(", ")}
                      onChange={(e) =>
                        set({ tags: e.target.value.split(",").map((s) => s.trim()).filter(Boolean) })
                      }
                      className={inputCls}
                    />
                  </Field>
                  <Field label={t("editor.judgeMode")}>
                    <select
                      value={c.judge_mode}
                      onChange={(e) => set({ judge_mode: e.target.value as JudgeMode })}
                      className={inputCls}
                    >
                      <option value="rule">Rule judge</option>
                      <option value="ai">AI judge</option>
                      <option value="off">Off</option>
                    </select>
                  </Field>
                </div>
                <div className="mt-3">
                  <Field label={t("editor.userMessage")}>
                    <textarea
                      value={c.user_message}
                      onChange={(e) => set({ user_message: e.target.value })}
                      rows={3}
                      className={`${inputCls} font-sans`}
                    />
                  </Field>
                </div>
              </Card>

              <Card className="p-5">
                <SectionTitle
                  title={t("editor.expectations")}
                  subtitle={t("editor.expectationsHint")}
                  right={
                    <Button variant="primary" onClick={addAssertion}>
                      <Plus width={14} height={14} />
                      {t("action.addAssertion")}
                    </Button>
                  }
                />
                <div className="space-y-2">
                  {c.expectations.map((e, i) => (
                    <div
                      key={i}
                      className="flex items-center gap-3 p-3 rounded-lg border border-line bg-canvas/40"
                    >
                      <input type="checkbox" defaultChecked className="accent-accent" />
                      <select
                        value={e.kind}
                        onChange={(ev) =>
                          set({
                            expectations: c.expectations.map((x, idx) =>
                              idx === i ? { ...x, kind: ev.target.value } : x,
                            ),
                          })
                        }
                        className={`${inputCls} w-40`}
                      >
                        <option value="expected_tools">expected_tools</option>
                        <option value="tool_call_order">tool_call_order</option>
                        <option value="text_contains">text_contains</option>
                        <option value="not_called">not_called</option>
                      </select>
                      <input
                        value={expSummary(e)}
                        onChange={(ev) =>
                          set({
                            expectations: c.expectations.map((x, idx) =>
                              idx === i
                                ? e.kind === "text_contains"
                                  ? { ...x, needle: ev.target.value }
                                  : { ...x, tools: ev.target.value.split(/[,\s]+/).filter(Boolean) }
                                : x,
                            ),
                          })
                        }
                        className={`${inputCls} flex-1 font-mono`}
                      />
                      <button
                        onClick={() => delAssertion(i)}
                        className="text-ink-faint hover:text-fail text-xs px-2"
                      >
                        ✕
                      </button>
                    </div>
                  ))}
                  {c.expectations.length === 0 && (
                    <p className="text-xs text-ink-mute py-4 text-center">{t("cases.empty")}</p>
                  )}
                </div>
              </Card>
            </>
          )}

          {tab === "mocks" && (
            <Card className="p-5">
              <SectionTitle title={t("editor.mock")} subtitle={t("editor.mockHint")} />
              <textarea
                value={mockText}
                onChange={(e) => setMockText(e.target.value)}
                rows={18}
                className="w-full p-3 rounded-lg border border-line bg-[#1a1d23] text-[#e5e7eb] font-mono text-xs focus:outline-none focus:border-accent"
                spellCheck={false}
              />
            </Card>
          )}

          {tab === "history" && (
            <Card className="p-8 text-center text-sm text-ink-mute">🚧 Run history — coming soon.</Card>
          )}
        </div>

        {/* 右：Run target / Latest / Mock coverage */}
        <div className="space-y-5">
          <Card className="p-5">
            <SectionTitle title={t("editor.runTarget")} />
            <div className="space-y-2 text-xs">
              <Row label="Endpoint" value="127.0.0.1:9000/chat" />
              <Row label="Branch" value="main · 9d2e7f1" />
              <Row label="Proxy" value={<span className="text-pass">/proxy · connected</span>} />
            </div>
          </Card>

          <Card className="p-5">
            <SectionTitle title={t("editor.latestResult")} />
            {c.last_result === "passed" ? (
              <div className="text-xs">
                <p className="flex items-center gap-1.5 text-pass font-medium">
                  <Check width={14} height={14} /> {t("verdict.passed")}
                </p>
                <p className="text-ink-mute mt-1">6.1s · real transport</p>
                <p className="font-mono text-ink-soft mt-2">
                  {c.expected_tools.join(" → ") || "—"}
                </p>
              </div>
            ) : (
              <p className="text-xs text-ink-mute">{t("run.noRun")}</p>
            )}
          </Card>

          <Card className="p-5">
            <SectionTitle
              title={t("editor.mockCoverage")}
              right={
                <span
                  className={`px-2 h-5 inline-flex items-center rounded text-[11px] font-semibold border ${
                    mockCover
                      ? "bg-accent-soft text-pass border-accent-border"
                      : "bg-amber-50 text-review border-amber-200"
                  }`}
                >
                  {mockCover ? "READY" : "GAP"}
                </span>
              }
            />
            <div className="space-y-1.5 text-xs">
              {toolsMocked.map((tool) => (
                <div key={tool} className="flex items-center justify-between">
                  <span className="font-mono text-ink">{tool}</span>
                  <span className="text-ink-mute">L0 inline</span>
                </div>
              ))}
              {toolsMocked.length === 0 && <p className="text-ink-mute">{t("common.none")}</p>}
            </div>
          </Card>

          <div className="flex flex-wrap gap-1">
            {c.tags.map((tag) => (
              <Pill key={tag}>{tag}</Pill>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

const inputCls =
  "w-full h-8 px-2.5 rounded-lg border border-line bg-white text-xs focus:outline-none focus:border-accent";

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="text-[11px] text-ink-mute">{label}</span>
      <div className="mt-1">{children}</div>
    </label>
  );
}

function Row({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between">
      <span className="text-ink-mute">{label}</span>
      <span className="text-ink font-mono">{value}</span>
    </div>
  );
}
