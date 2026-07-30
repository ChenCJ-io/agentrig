import type { HTMLAttributes, ReactNode } from "react";

interface PanelProps extends HTMLAttributes<HTMLElement> {
  title?: string;
  eyebrow?: string;
  actions?: ReactNode;
  children: ReactNode;
}

export function Panel({ title, eyebrow, actions, children, className = "", ...props }: PanelProps) {
  return (
    <section className={`panel ${className}`.trim()} {...props}>
      {title || eyebrow || actions ? (
        <div className="panel__header">
          <div>
            {eyebrow ? <p className="eyebrow">{eyebrow}</p> : null}
            {title ? <h2>{title}</h2> : null}
          </div>
          {actions ? <div className="panel__actions">{actions}</div> : null}
        </div>
      ) : null}
      {children}
    </section>
  );
}
