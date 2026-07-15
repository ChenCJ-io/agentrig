import type { ButtonHTMLAttributes, ReactNode } from "react";
import type { LastResult } from "../lib/types";
import { useI18n } from "../i18n";

export function Card({ className = "", children }: { className?: string; children: ReactNode }) {
  return (
    <div className={`bg-card border border-line rounded-xl ${className}`}>{children}</div>
  );
}

export function SectionTitle({
  title,
  subtitle,
  right,
}: {
  title: string;
  subtitle?: string;
  right?: ReactNode;
}) {
  return (
    <div className="flex items-start justify-between mb-3">
      <div>
        <h3 className="text-sm font-semibold text-ink">{title}</h3>
        {subtitle && <p className="text-xs text-ink-mute mt-0.5">{subtitle}</p>}
      </div>
      {right}
    </div>
  );
}

type BtnVariant = "primary" | "outline" | "ghost" | "danger";
export function Button({
  variant = "outline",
  className = "",
  children,
  ...rest
}: { variant?: BtnVariant; children: ReactNode } & ButtonHTMLAttributes<HTMLButtonElement>) {
  const styles: Record<BtnVariant, string> = {
    primary: "bg-accent text-white hover:bg-accent-hover border border-accent",
    outline: "bg-white text-ink border border-line hover:bg-canvas",
    ghost: "text-ink-mute hover:text-ink hover:bg-canvas border border-transparent",
    danger: "bg-fail text-white hover:opacity-90 border border-fail",
  };
  return (
    <button
      className={`inline-flex items-center gap-1.5 px-3 h-8 rounded-lg text-xs font-medium transition-colors ${styles[variant]} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

const verdictStyle: Record<LastResult, string> = {
  passed: "bg-accent-soft text-pass border-accent-border",
  failed: "bg-red-50 text-fail border-red-200",
  review: "bg-amber-50 text-review border-amber-200",
  draft: "bg-gray-100 text-draft border-gray-200",
};

export function StatusBadge({ status }: { status: LastResult }) {
  const { t } = useI18n();
  return (
    <span
      className={`inline-flex items-center gap-1 px-2 h-5 rounded-full text-[11px] font-medium border ${verdictStyle[status]}`}
    >
      <span className="w-1.5 h-1.5 rounded-full bg-current opacity-70" />
      {t(`verdict.${status}`)}
    </span>
  );
}

export function Pill({ children }: { children: ReactNode }) {
  return (
    <span className="inline-flex items-center px-2 h-5 rounded-md bg-canvas text-ink-mute text-[11px] border border-line">
      {children}
    </span>
  );
}

export function ProgressBar({ done, total }: { done: number; total: number }) {
  const pct = total ? Math.round((done / total) * 100) : 0;
  return (
    <div className="h-1.5 rounded-full bg-line overflow-hidden">
      <div className="h-full bg-accent transition-all" style={{ width: `${pct}%` }} />
    </div>
  );
}

export function MetricCard({
  label,
  value,
  delta,
  deltaTone = "neutral",
}: {
  label: string;
  value: ReactNode;
  delta?: string;
  deltaTone?: "up" | "down" | "warn" | "neutral";
}) {
  const tone =
    deltaTone === "up"
      ? "text-pass"
      : deltaTone === "down"
        ? "text-fail"
        : deltaTone === "warn"
          ? "text-review"
          : "text-ink-mute";
  return (
    <Card className="p-4">
      <p className="text-xs text-ink-mute">{label}</p>
      <p className="text-2xl font-semibold text-ink mt-1">{value}</p>
      {delta && <p className={`text-xs mt-1 ${tone}`}>{delta}</p>}
    </Card>
  );
}
