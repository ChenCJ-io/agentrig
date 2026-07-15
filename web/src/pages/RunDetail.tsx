import { useEffect, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";
import { Button, Card, SectionTitle } from "../components/ui";
import { ArrowRight, Check, Play } from "../components/icons";
import { useI18n } from "../i18n";
import { getCase, runCase } from "../lib/api";
import { mockCases } from "../lib/mock";
import type { RunResult, TestCase } from "../lib/types";

export default function RunDetail() {
  const { id } = useParams();
  const loc = useLocation();
  const nav = useNavigate();
  const { t } = useI18n();
  const st = loc.state as { run?: RunResult; caseName?: string } | null;
  const [run, setRun] = useState<RunResult | null>(st?.run ?? null);
  const [caseName, setCaseName] = useState(st?.caseName ?? id ?? "");
  const [tc, setTc] = useState<TestCase | null>(null);
  const [loading, setLoading] = useState(false);

  // 进入只加载用例（不自动 run——避免意外触发真实 agent 调用 / token 消耗）
  useEffect(() => {
    if (!id) return;
    getCase(id)
      .then((c) => {
        setTc(c);
        setCaseName(c.name);
      })
      .catch(() => setTc(mockCases.find((x) => x.id === id) ?? null));
  }, [id]);

  const runNow = async () => {
    if (!id) return;
    setLoading(true);
    try {
      const r = await runCase(id).catch(() => null);
      if (r) setRun(r);
    } finally {
      setLoading(false);
    }
  };

  // 工具时间线：name 列表 + 对应 mock result（来自 case.mock）
  const tools = run?.tool_calls ?? [];
  const toolResult = (name: string) => tc?.mock[name];

  return (
    <div className="p-8 max-w-4xl">
      {/* Header */}
      <div className="mb-6">
        <p className="text-xs text-ink-mute mb-2">
          <button onClick={() => nav("/cases")} className="hover:text-ink">
            {t("nav.cases")}
          </button>{" "}
          / <button onClick={() => nav(`/cases/${id}`)} className="hover:text-ink">{id}</button> /{" "}
          {t("nav.runs")}
        </p>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-3">
            <h1 className="text-2xl font-semibold">{caseName}</h1>
            {run && (
              <span
                className={`px-2.5 h-6 inline-flex items-center rounded-full text-xs font-semibold border ${
                  run.passed
                    ? "bg-accent-soft text-pass border-accent-border"
                    : "bg-red-50 text-fail border-red-200"
                }`}
              >
                {run.passed ? t("verdict.passed") : t("verdict.failed")}
              </span>
            )}
          </div>
          <Button variant="primary" onClick={runNow}>
            <Play width={14} height={14} />
            {t("run.runNow")}
          </Button>
        </div>
        {run && (
          <p className="text-xs text-ink-mute mt-2">
            #{id} · {run.transport} transport · {run.tool_results_count} results · {run.judge_mode}
          </p>
        )}
      </div>

      {loading && <p className="text-sm text-ink-mute">{t("common.loading")}</p>}

      {run?.error && (
        <Card className="p-4 mb-4 border-red-200 bg-red-50">
          <p className="text-xs font-semibold text-fail">{t("run.error")}</p>
          <p className="text-xs text-fail/80 mt-1 font-mono">{run.error}</p>
        </Card>
      )}

      {/* Tool calls timeline */}
      <Card className="p-5 mb-4">
        <SectionTitle title={t("run.toolCalls")} subtitle={`${tools.length} calls`} />
        {tools.length === 0 ? (
          <p className="text-xs text-ink-mute">{t("common.none")}</p>
        ) : (
          <div className="flex items-stretch gap-2 overflow-x-auto pb-2">
            {tools.map((name, i) => (
              <div key={i} className="flex items-center gap-2">
                <div className="min-w-[160px] p-3 rounded-lg border border-line bg-canvas/50">
                  <p className="font-mono text-sm font-medium text-ink">{name}</p>
                  <pre className="text-[11px] text-ink-mute mt-1 whitespace-pre-wrap break-all max-h-24 overflow-auto">
                    {JSON.stringify(toolResult(name) ?? "—", null, 2)}
                  </pre>
                </div>
                {i < tools.length - 1 && (
                  <ArrowRight width={16} height={16} className="text-ink-faint shrink-0" />
                )}
              </div>
            ))}
          </div>
        )}
      </Card>

      {/* Assistant text */}
      {run?.assistant_text && (
        <Card className="p-5 mb-4">
          <SectionTitle title={t("run.assistantText")} />
          <p className="text-sm text-ink-soft bg-canvas/50 rounded-lg p-3">{run.assistant_text}</p>
        </Card>
      )}

      {/* Reasons */}
      {run && (
        <Card className="p-5">
          <SectionTitle title={t("run.reasons")} />
          {run.reasons.length === 0 ? (
            <p className="flex items-center gap-1.5 text-xs text-pass">
              <Check width={14} height={14} /> {t("verdict.passed")}
            </p>
          ) : (
            <ul className="space-y-1.5">
              {run.reasons.map((r, i) => (
                <li key={i} className="text-xs text-ink-soft font-mono bg-canvas/50 rounded px-3 py-1.5">
                  {r}
                </li>
              ))}
            </ul>
          )}
          {run.missing_expected_tools.length > 0 && (
            <p className="text-xs text-fail mt-3">
              missing: {run.missing_expected_tools.join(", ")}
            </p>
          )}
        </Card>
      )}
    </div>
  );
}
