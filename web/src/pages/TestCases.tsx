import { useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button, Card, Pill, StatusBadge } from "../components/ui";
import { Dots, Plus, Search, Upload } from "../components/icons";
import { useI18n } from "../i18n";
import { getCases } from "../lib/api";
import { mockCases } from "../lib/mock";
import type { LastResult, TestCase } from "../lib/types";

export default function TestCases() {
  const { t } = useI18n();
  const nav = useNavigate();
  const [cases, setCases] = useState<TestCase[]>(mockCases);
  const [tab, setTab] = useState<"all" | "attention" | "drafts" | "recent">("all");
  const [q, setQ] = useState("");

  useEffect(() => {
    getCases()
      .then(setCases)
      .catch(() => setCases(mockCases));
  }, []);

  const counts = useMemo(
    () => ({
      all: cases.length,
      attention: cases.filter((c) => c.last_result === "failed" || c.last_result === "review").length,
      drafts: cases.filter((c) => c.last_result === "draft").length,
      recent: cases.length,
    }),
    [cases],
  );

  const filtered = cases.filter((c) => {
    if (tab === "attention" && c.last_result !== "failed" && c.last_result !== "review") return false;
    if (tab === "drafts" && c.last_result !== "draft") return false;
    if (q) {
      const s = q.toLowerCase();
      return (
        c.name.toLowerCase().includes(s) ||
        c.id.toLowerCase().includes(s) ||
        c.tags.some((tag) => tag.toLowerCase().includes(s)) ||
        c.expected_tools.some((tool) => tool.toLowerCase().includes(s))
      );
    }
    return true;
  });

  const tabs: { key: typeof tab; label: string; n: number }[] = [
    { key: "all", label: t("cases.tab.all"), n: counts.all },
    { key: "attention", label: t("cases.tab.attention"), n: counts.attention },
    { key: "drafts", label: t("cases.tab.drafts"), n: counts.drafts },
    { key: "recent", label: t("cases.tab.recent"), n: counts.recent },
  ];

  return (
    <div className="p-8 max-w-6xl">
      {/* Header */}
      <div className="flex items-start justify-between mb-6">
        <div>
          <h1 className="text-2xl font-semibold">{t("cases.title")}</h1>
          <p className="text-sm text-ink-mute mt-1">
            {counts.all} {t("cases.subtitle")}
          </p>
        </div>
        <div className="flex gap-2">
          <Button variant="outline">
            <Upload width={14} height={14} />
            {t("action.import")}
          </Button>
          <Button variant="primary" onClick={() => nav("/cases/new")}>
            <Plus width={14} height={14} />
            {t("action.newCase")}
          </Button>
        </div>
      </div>

      <Card className="overflow-hidden">
        {/* Tabs */}
        <div className="flex items-center gap-5 px-5 border-b border-line">
          {tabs.map((tb) => (
            <button
              key={tb.key}
              onClick={() => setTab(tb.key)}
              className={`py-3 text-xs font-medium border-b-2 -mb-px transition-colors ${
                tab === tb.key ? "border-accent text-ink" : "border-transparent text-ink-mute hover:text-ink"
              }`}
            >
              {tb.label} <span className="text-ink-faint">{tb.n}</span>
            </button>
          ))}
        </div>

        {/* Filter bar */}
        <div className="flex items-center gap-2 px-5 py-3 border-b border-line bg-canvas/50">
          <div className="flex-1 relative">
            <Search width={15} height={15} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-ink-faint" />
            <input
              value={q}
              onChange={(e) => setQ(e.target.value)}
              placeholder={t("cases.search")}
              className="w-full h-8 pl-8 pr-3 rounded-lg border border-line bg-white text-xs focus:outline-none focus:border-accent"
            />
          </div>
          <Button variant="outline">{t("cases.col.tags")}</Button>
          <Button variant="outline">{t("cases.col.judge")}</Button>
        </div>

        {/* Table */}
        <table className="w-full text-xs">
          <thead>
            <tr className="text-ink-faint text-left border-b border-line bg-canvas/30">
              <th className="py-2.5 pl-5 w-8"><input type="checkbox" className="accent-accent" /></th>
              <th className="py-2.5 font-medium">{t("cases.col.case")}</th>
              <th className="py-2.5 font-medium">{t("cases.col.tags")}</th>
              <th className="py-2.5 font-medium">{t("cases.col.toolFlow")}</th>
              <th className="py-2.5 font-medium">{t("cases.col.judge")}</th>
              <th className="py-2.5 font-medium">{t("cases.col.lastResult")}</th>
              <th className="py-2.5 font-medium">{t("cases.col.updated")}</th>
              <th className="py-2.5 pr-5 w-8"></th>
            </tr>
          </thead>
          <tbody>
            {filtered.map((c) => (
              <tr
                key={c.id}
                onClick={() => nav(`/cases/${c.id}`)}
                className="border-b border-line/60 hover:bg-canvas cursor-pointer"
              >
                <td className="py-3 pl-5" onClick={(e) => e.stopPropagation()}>
                  <input type="checkbox" className="accent-accent" />
                </td>
                <td className="py-3">
                  <p className="font-medium text-ink">{c.name}</p>
                  <p className="font-mono text-ink-faint">{c.id}</p>
                </td>
                <td className="py-3">
                  <div className="flex gap-1 flex-wrap">
                    {c.tags.slice(0, 3).map((tag) => (
                      <Pill key={tag}>{tag}</Pill>
                    ))}
                  </div>
                </td>
                <td className="py-3 text-ink-soft font-mono">{c.expected_tools.join(" → ") || "—"}</td>
                <td className="py-3 text-ink-soft">{c.judge_mode}</td>
                <td className="py-3">
                  <StatusBadge status={(c.last_result ?? "draft") as LastResult} />
                </td>
                <td className="py-3 text-ink-mute">{c.updated_ago ?? "—"}</td>
                <td className="py-3 pr-5 text-ink-faint">
                  <Dots width={16} height={16} />
                </td>
              </tr>
            ))}
          </tbody>
        </table>

        {filtered.length === 0 && (
          <div className="py-16 text-center text-sm text-ink-mute">{t("cases.empty")}</div>
        )}

        {/* Pagination */}
        <div className="flex items-center justify-between px-5 py-3 border-t border-line text-xs text-ink-mute">
          <span>0 {t("action.runSelected").toLowerCase()}</span>
          <div className="flex items-center gap-1">
            {[1, 2, 3, 4].map((p) => (
              <span
                key={p}
                className={`w-7 h-7 inline-flex items-center justify-center rounded ${
                  p === 1 ? "bg-accent text-white" : "hover:bg-canvas"
                }`}
              >
                {p}
              </span>
            ))}
          </div>
        </div>
      </Card>
    </div>
  );
}
