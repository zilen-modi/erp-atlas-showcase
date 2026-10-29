"use client";

import { toast } from "@/components/Toaster";

export type Job = {
  id: string; kind: string; state: "running" | "done" | "failed" | "cancelled";
  log: string[]; error: string | null; started_at: string; result?: any;
};

// Start a background job. If one is already running, attach to it instead of failing:
// the caller then shows that job's progress (and can cancel it).
export async function startJob(endpoint: string, body: unknown, label: string): Promise<Job | null> {
  const r = await fetch(endpoint, {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body ?? {}),
  }).catch(() => null);
  if (!r) { toast.error(`${label} didn't start`, "Atlas API is not reachable. Start it with: uv run atlas serve"); return null; }
  const d = await r.json().catch(() => ({}));
  if (r.ok) return d as Job;
  if (r.status === 409 && d.detail?.job) {
    toast.info("Another job is still running", `${d.detail.message} Showing its progress.`);
    return d.detail.job as Job;
  }
  toast.error(`${label} didn't start`, typeof d.detail === "string" ? d.detail : d.detail?.message ?? `HTTP ${r.status}`);
  return null;
}

export async function cancelJob(id: string) {
  await fetch(`/api/jobs/${id}/cancel`, { method: "POST" }).catch(() => null);
  toast.info("Cancelling…", "The job stops after its current step.");
}

// Toast the outcome once a job leaves "running", including any WARNING lines it logged.
export function reportJob(j: Job, label: string, done?: string) {
  for (const w of j.log.filter((l) => l.startsWith("WARNING:"))) toast.info("Check this", w.replace(/^WARNING:\s*/, ""));
  if (j.state === "failed") toast.error(`${label} failed`, j.error ?? undefined);
  else if (j.state === "cancelled") toast.info(`${label} cancelled`);
  else if (j.state === "done") toast.success(done ?? `${label} finished`);
}

export async function pollJob(id: string): Promise<Job | null> {
  const r = await fetch(`/api/jobs/${id}`).catch(() => null);
  return r?.ok ? ((await r.json()) as Job) : null;
}
