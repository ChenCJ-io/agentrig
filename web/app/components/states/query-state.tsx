import { AlertTriangle, Inbox, LoaderCircle, RefreshCw } from "lucide-react";
import type { ReactNode } from "react";

import { Button } from "~/components/ui/button";

import styles from "./query-state.module.css";

interface StateProps {
  title: string;
  description?: string;
  action?: ReactNode;
}

function StateFrame({ icon, title, description, action }: StateProps & { icon: ReactNode }) {
  return (
    <section className={styles.state} role="status">
      <span className={styles.icon} aria-hidden="true">{icon}</span>
      <strong>{title}</strong>
      {description ? <p>{description}</p> : null}
      {action ? <div>{action}</div> : null}
    </section>
  );
}

export function LoadingState({ title = "正在加载", description }: Partial<StateProps>) {
  return <StateFrame icon={<LoaderCircle className={styles.spin} />} title={title} description={description} />;
}

export function EmptyState({ title, description, action }: StateProps) {
  return <StateFrame icon={<Inbox />} title={title} description={description} action={action} />;
}

export function ErrorState({
  title = "数据加载失败",
  description,
  onRetry,
}: Partial<StateProps> & { onRetry?: () => void }) {
  return (
    <StateFrame
      icon={<AlertTriangle />}
      title={title}
      description={description}
      action={onRetry ? <Button icon={<RefreshCw />} onClick={onRetry}>重试</Button> : undefined}
    />
  );
}

export function PartialDataNotice({ children }: { children: ReactNode }) {
  return (
    <div className={styles.partial} role="status">
      <AlertTriangle aria-hidden="true" size={14} />
      <span>{children}</span>
    </div>
  );
}
