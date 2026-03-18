type StatusChipProps = {
  tone: "neutral" | "success" | "warning" | "danger" | "info";
  children: string;
};

export function toneForStatus(status: string | null | undefined): StatusChipProps["tone"] {
  if (!status) return "neutral";
  const value = status.toLowerCase();
  if (["completed", "passed", "active", "available", "eligible", "ready"].includes(value)) {
    return "success";
  }
  if (["failed", "error", "deleted", "expired", "blocking"].includes(value)) {
    return "danger";
  }
  if (["warning", "pending", "queued", "running", "refreshing", "publishing"].includes(value)) {
    return "warning";
  }
  return "info";
}

export function StatusChip({ tone, children }: StatusChipProps) {
  return <span className={`status-chip status-chip--${tone}`}>{children}</span>;
}
