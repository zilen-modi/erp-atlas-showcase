"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { SyncIcon } from "@/components/Icons";
import { cancelJob, type Job, pollJob, reportJob, startJob } from "@/lib/jobs";

// Starts a background job on `atlas serve`, polls it, shows its progress, and
// refreshes the page's server data when it finishes. Outcomes arrive as toasts.
export default function JobButton({
  endpoint,
  body,
  label,
  confirm,
  primary = false,
}: {
  endpoint: string;
  body?: unknown;
  label: string;
  confirm?: string;
  primary?: boolean;
}) {
  const router = useRouter();
  const [job, setJob] = useState<Job | null>(null);
  const [dismissed, setDismissed] = useState(false);

  useEffect(() => {
    if (!job || job.state !== "running") return;
    const t = setInterval(async () => {
      const j = await pollJob(job.id);
      if (!j) return;
      setJob(j);
      if (j.state !== "running") {
        reportJob(j, label);
        router.refresh();
      }
    }, 1500);
    return () => clearInterval(t);
  }, [job, router, label]);

  async function start() {
    if (confirm && !window.confirm(confirm)) return;
    setDismissed(false);
    const j = await startJob(endpoint, body, label);
    if (j) setJob(j);
  }

  const running = job?.state === "running";
  return (
    <div className="job">
      <button className={primary ? "primary" : ""} onClick={running ? () => setDismissed(false) : start}
        title={running ? "Show progress" : undefined}>
        {running ? <><span className="spinner" /> Working…</> : <><SyncIcon size={14} /> {label}</>}
      </button>
      {job && !dismissed && running && (
        <div className="job-panel">
          <div className="row">
            <b style={{ fontSize: 13 }}>{job.kind === "capture" ? "Capture" : label}</b>
            <span className="badge blue">running</span>
            <span className="spacer" />
            <button className="sm" onClick={() => cancelJob(job.id)}>Cancel</button>
            <button className="ghost icon-btn sm" aria-label="Hide progress" onClick={() => setDismissed(true)}>×</button>
          </div>
          {job.log.length > 0 && <div className="log" style={{ marginTop: 8 }}>{job.log.slice(-40).join("\n")}</div>}
        </div>
      )}
    </div>
  );
}
