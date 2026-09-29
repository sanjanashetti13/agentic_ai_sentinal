import type { ReactNode } from "react";

type EmptyStateProps = {
  title: string;
  children?: ReactNode;
  action?: {
    label: string;
    onClick: () => void;
  };
};

export function EmptyState({ title, children, action }: EmptyStateProps) {
  return (
    <div className="empty">
      <strong>{title}</strong>
      {children ? <p className="muted">{children}</p> : null}
      {action ? (
        <div className="actions">
          <button className="primary" type="button" onClick={action.onClick}>
            {action.label}
          </button>
        </div>
      ) : null}
    </div>
  );
}
