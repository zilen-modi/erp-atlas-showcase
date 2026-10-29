"use client";

import { useEffect, useRef, useState } from "react";
import { CheckIcon } from "@/components/Icons";
import { cancelJob, type Job } from "@/lib/jobs";

// A running job as a live checklist: every step it has logged, the current one spinning,
// the time so far, and Cancel.
export default function JobProgress({ job, title, hint, expectedKind }: {
  job: Job; title: string; hint?: string; expectedKind?: string;
}) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => { const t = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(t); }, []);
  const list = useRef<HTMLOListElement>(null);
  const steps = job.log.filter((l) => !l.startsWith("WARNING:"));
  useEffect(() => { list.current?.scrollTo({ top: list.current.scrollHeight }); }, [steps.length]);

  const secs = Math.max(0, Math.round((now - new Date(job.started_at).getTime()) / 1000));
  const elapsed = secs >= 60 ? `${Math.floor(secs / 60)}m ${String(secs % 60).padStart(2, "0")}s` : `${secs}s`;
  const other = expectedKind && job.kind !== expectedKind;

  return (
    <div className="jobprog" role="status" aria-live="polite">
      <div className="jobprog-head">
        <span className="spinner" />
        <b>{other ? `Waiting for another job (${job.kind}) to finish` : title}</b>
        <span className="sub">{elapsed}</span>
        <span className="spacer" />
        <button className="sm" onClick={() => cancelJob(job.id)}>Cancel</button>
      </div>
      <ol className="jobprog-steps" ref={list}>
        {steps.length === 0 && <li className="current"><span className="jp-ico"><span className="dotpulse" /></span>Starting…</li>}
        {steps.map((s, i) => {
          const last = i === steps.length - 1;
          const thinking = s.startsWith("Thinking: ");
          return (
            <li key={i} className={`${last ? "current" : "done"} ${thinking ? "thinking" : ""}`}>
              <span className="jp-ico">{last ? <span className="dotpulse" /> : <CheckIcon size={12} />}</span>
              <span>{thinking ? <i>{s.slice(10)}</i> : s}</span>
            </li>
          );
        })}
      </ol>
      {hint && <div className="jobprog-hint sub">{hint}</div>}
    </div>
  );
}
