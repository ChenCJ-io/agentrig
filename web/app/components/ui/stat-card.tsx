import type { ReactNode } from "react";

export function StatCard({
  label,
  value,
  meta,
  accent,
}: {
  label: string;
  value: ReactNode;
  meta?: ReactNode;
  accent?: "blue" | "green" | "amber" | "coral";
}) {
  return (
    <article className={`stat-card ${accent ? `stat-card--${accent}` : ""}`.trim()}>
      <div className="stat-card__rail" aria-hidden="true" />
      <p>{label}</p>
      <strong>{value}</strong>
      {meta ? <div className="stat-card__meta">{meta}</div> : null}
    </article>
  );
}
