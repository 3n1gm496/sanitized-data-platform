import { type PropsWithChildren } from "react";

type ExplainPanelProps = PropsWithChildren<{
  title: string;
  tone?: "default" | "warning";
}>;

export function ExplainPanel({ title, tone = "default", children }: ExplainPanelProps) {
  return (
    <aside className={`explain-panel explain-panel--${tone}`}>
      <h3>{title}</h3>
      <div>{children}</div>
    </aside>
  );
}
