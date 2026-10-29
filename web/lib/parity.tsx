// Shared by server and client components (no "use client").
export const STATUS_LABEL: Record<string, [string, string]> = {
  todo: ["To do", ""], built: ["Built in ERP Next", "green"], standard: ["Standard ERP Next report", "green"],
  scheduled: ["Scheduled job in ERP Next", "green"], "not needed": ["Not needed", "violet"],
};

export const SCHED_CLS: Record<string, string> = {
  nightly: "violet", daily: "blue", weekly: "blue", "month-end": "amber", "year-end": "red", "on demand": "",
};

export function StatusBadge({ status }: { status: string }) {
  const [label, cls] = STATUS_LABEL[status] ?? [status, ""];
  return <span className={`badge ${cls}`}>{label}</span>;
}

