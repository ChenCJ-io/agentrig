import { BrainCircuit, ChevronRight, ShieldCheck } from "lucide-react";
import { Link, useLocation } from "react-router";

import type { DecisionQualityMetrics, DecisionRecord } from "~/api/v2";
import { Badge } from "~/components/ui/badge";

import styles from "./assistant-page.module.css";
import {
  decisionActionLabel,
  decisionKindLabel,
  evidenceKindLabel,
  policyLabel,
  shortId,
  statusLabel,
  tone,
} from "./assistant-presenters";
import { evidenceSourcePath } from "./evidence-links";

export function DecisionCard({ decision }: { decision: DecisionRecord }) {
  const location = useLocation();
  const known = decision.observation_summary.known.slice(0, 3);
  return (
    <article className={styles.decisionCard}>
      <header>
        <span><BrainCircuit size={15} /></span>
        <div>
          <small>{decisionKindLabel(decision.decision_kind)}</small>
          <strong>{decisionActionLabel(decision.selected_action.action_type)}</strong>
        </div>
        <Badge tone={tone(decision.status)}>{statusLabel(decision.status)}</Badge>
      </header>
      <p>{decision.rationale_summary.summary}</p>
      {known.length ? <ul>{known.map((item) => <li key={item}>{item}</li>)}</ul> : null}
      <footer>
        <span><ShieldCheck size={12} /> {policyLabel(decision.policy_verdict.verdict)}</span>
        <code>{shortId(decision.id)}</code>
      </footer>
      <details>
        <summary>查看决策依据与取舍 <ChevronRight size={12} /></summary>
        <div className={styles.decisionEvidence}>
          {decision.evidence_refs.map((item) => (
            <Link
              key={`${item.kind}:${item.resource_id}`}
              title={`打开${evidenceKindLabel(item.kind)}：${item.resource_id}`}
              to={evidenceSourcePath(item, decision, location.pathname)}
            >
              <span>
                <small>{evidenceKindLabel(item.kind)}</small>
                <code>{shortId(item.resource_id)}</code>
              </span>
              <ChevronRight size={12} />
            </Link>
          ))}
        </div>
        {decision.rationale_summary.tradeoffs.length ? (
          <p className={styles.tradeoffs}>取舍：{decision.rationale_summary.tradeoffs.join(" · ")}</p>
        ) : null}
      </details>
    </article>
  );
}

export function DecisionSummary({
  decision,
  metrics,
}: {
  decision: DecisionRecord;
  metrics?: DecisionQualityMetrics;
}) {
  return (
    <div className={styles.decisionSummary}>
      <div>
        <Badge tone={tone(decision.status)}>{statusLabel(decision.status)}</Badge>
        <code>{shortId(decision.id)}</code>
      </div>
      <strong>{decisionActionLabel(decision.selected_action.action_type)}</strong>
      <p>{decision.objective}</p>
      <dl>
        <div><dt>策略裁定</dt><dd>{policyLabel(decision.policy_verdict.verdict)}</dd></div>
        <div><dt>证据引用</dt><dd>{decision.evidence_refs.length}</dd></div>
        <div><dt>置信度</dt><dd>{decision.confidence == null ? "—" : `${Math.round(decision.confidence * 100)}%`}</dd></div>
      </dl>
      {metrics ? (
        <div className={styles.decisionQuality}>
          <span><small>决策成功率</small><strong>{metricRate(metrics.success_rate)}</strong></span>
          <span><small>事实引用</small><strong>{metrics.evidence_reference_count}</strong></span>
          <span><small>结果可追溯</small><strong>{metricRate(metrics.provenance_link_rate)}</strong></span>
        </div>
      ) : null}
      {decision.action_ref_id ? (
        <footer><span>业务结果</span><code title={decision.action_ref_id}>{shortId(decision.action_ref_id)}</code></footer>
      ) : null}
    </div>
  );
}

function metricRate(value: number | null) {
  return value == null ? "—" : `${Math.round(value * 100)}%`;
}
