import { useEffect, useState } from "react";
import { Button, Card, MetricCard, ProgressBar, SectionTitle } from "../components/ui";
import { ArrowRight, Play } from "../components/icons";
import { useI18n } from "../i18n";
import { getOverview } from "../lib/api";
import { mockOverview } from "../lib/mock";
import type { Overview as OV } from "../lib/types";

export default function Overview() {
  const { t } = useI18n();
  const [ov, setOv] = useState<OV>(mockOverview);

  useEffect(() => {
    getOverview()
      .then(setOv)
      .catch(() => setOv(mockOverview));
  }, []);

  return (
    <div className="p-8 max-w-6xl">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold text-ink">{t("overview.title")}</h1>
          <p className="text-sm text-ink-mute mt-1">{t("overview.subtitle")}</p>
        </div>
        <div className="flex items-center gap-2">
          <span className="inline-flex items-center gap-1.5 px-2.5 h-8 rounded-lg border border-line bg-white text-xs text-ink-mute">
            main · local
          </span>
          <Button variant="primary">
            <Play width={14} height={14} />
            {t("action.runRegression")}
          </Button>
        </div>
      </div>

      {/* Release gate */}
      <Card className="p-5 mb-6">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2">
            <span className="px-2 h-5 inline-flex items-center rounded text-[11px] font-semibold bg-amber-100 text-review border border-amber-200">
              {t("overview.releaseGate")}
            </span>
            <span className="text-sm font-medium text-ink">
              {ov.failed > 0 ? `${ov.failed} failing` : "All green"}
            </span>
          </div>
          <span className="text-xs text-ink-mute">
            {t("overview.coverage")} · {ov.coverage_done}/{ov.coverage_total}
          </span>
        </div>
        <ProgressBar done={ov.coverage_done} total={ov.coverage_total} />
        <div className="flex items-center gap-5 mt-3 text-xs">
          <span className="text-pass font-medium">{t("overview.passed")} {ov.passed}</span>
          <span className="text-fail font-medium">{t("overview.failed")} {ov.failed}</span>
          <span className="text-ink-mute">{t("overview.skipped")} {ov.skipped}</span>
        </div>
      </Card>

      {/* Metrics */}
      <div className="grid grid-cols-4 gap-4 mb-6">
        <MetricCard label={t("overview.totalCases")} value={ov.total_cases} delta="+5 this week" deltaTone="up" />
        <MetricCard label={t("overview.passRate")} value={`${ov.pass_rate}%`} delta="+3.4%" deltaTone="up" />
        <MetricCard label={t("overview.medianRun")} value={ov.median_run} delta="-0.8s" deltaTone="up" />
        <MetricCard label={t("overview.changedTools")} value={ov.changed_tools} delta="needs review" deltaTone="warn" />
      </div>

      {/* Recent runs + Suite growth */}
      <div className="grid grid-cols-3 gap-4">
        <Card className="col-span-2 p-5">
          <SectionTitle
            title={t("overview.recentRuns")}
            right={<button className="text-xs text-accent hover:underline">{t("action.viewAll")}</button>}
          />
          <table className="w-full text-xs">
            <thead>
              <tr className="text-ink-faint text-left border-b border-line">
                <th className="py-2 font-medium">RUN</th>
                <th className="py-2 font-medium">COMMIT</th>
                <th className="py-2 font-medium">SCOPE</th>
                <th className="py-2 font-medium">RESULT</th>
                <th className="py-2 font-medium">DURATION</th>
                <th className="py-2 font-medium">WHEN</th>
              </tr>
            </thead>
            <tbody>
              {ov.recent_runs.map((r) => (
                <tr key={r.id} className="border-b border-line/60 hover:bg-canvas">
                  <td className="py-2.5 font-medium text-ink">#{r.id}</td>
                  <td className="py-2.5 font-mono text-ink-mute">{r.commit}</td>
                  <td className="py-2.5 text-ink-soft">{r.scope}</td>
                  <td className="py-2.5">
                    <span className="text-pass">{r.passed} passed</span>
                    {r.failed > 0 && <span className="text-fail"> · {r.failed} failed</span>}
                  </td>
                  <td className="py-2.5 text-ink-mute">{r.duration}</td>
                  <td className="py-2.5 text-ink-mute">{r.when}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>

        <Card className="p-5">
          <SectionTitle title={t("overview.suiteGrowth")} />
          <ul className="space-y-2.5">
            {ov.suite_growth.map((g) => (
              <li key={g.name} className="flex items-center justify-between text-xs">
                <div>
                  <p className="font-mono text-ink">{g.name}</p>
                  <p className="text-ink-faint">{g.when}</p>
                </div>
                <span className="text-pass font-medium">+{g.delta}</span>
              </li>
            ))}
          </ul>
        </Card>
      </div>
    </div>
  );
}
