"use client";

import { useEffect, useState } from "react";
import { UsageBar } from "@/components/ui";
import { cancelJob, type Job, pollJob, reportJob, startJob } from "@/lib/jobs";

type K = { programs: number; summarised: number; stale: number; sections: number; cost_usd: number;
  top_used: { of: number; done: number }; index: { entries: number; model: string; available: boolean };
  models: { id: string; label: string }[] };

const SIZES = [10, 25, 50, 100, 250];

// Admins write summaries in batches, most-used programs first, on their own Claude.
export default function KnowledgeAdmin() {
  const [k, setK] = useState<K | null>(null);
  const [limit, setLimit] = useState(25);
  const [model, setModel] = useState("claude-sonnet-5-5");
  const [job, setJob] = useState<Job | null>(null);
  const [est, setEst] = useState<{ programs: number; calls: number; lines: number; first: { name: string; lines: number }[] } | null>(null);
  useEffect(() => {
    setEst(null);
    fetch(`/api/knowledge/estimate?limit=${limit}`).then((r) => (r.ok ? r.json() : null)).then(setEst).catch(() => null);
  }, [limit, k?.summarised]);
  const load = () => fetch("/api/knowledge").then((r) => (r.ok ? r.json() : null)).then(setK).catch(() => null);
  useEffect(() => { load(); }, []);

  useEffect(() => {
    if (!job || job.state !== "running") return;
    const t = setInterval(async () => {
      const j = await pollJob(job.id);
      if (!j) return;
      setJob(j);
      load();
      if (j.state !== "running") reportJob(j, job.kind === "embed" ? "Meaning index" : "Summaries");
    }, 2500);
    return () => clearInterval(t);
  }, [job]);   // eslint-disable-line react-hooks/exhaustive-deps

  async function start(kind: "summaries" | "embed") {
    const j = await startJob(`/api/jobs/${kind}`, kind === "summaries" ? { limit, model } : {},
      kind === "summaries" ? "Summaries" : "Meaning index");
    if (j) setJob(j);
  }

  if (!k) return null;
  const busy = job?.state === "running";
  const log = job ? job.log.slice(-6) : [];
  return (
    <section className="card" id="knowledge">
      <div className="card-head"><h2>Knowledge</h2><span className="sub">Plain-English summaries and search by meaning</span></div>
      <div className="card-body stack">
        <div className="kn-stats">
          <div><span className="faint">Most-used 100 programs</span><strong>{k.top_used.done} / {k.top_used.of}</strong><UsageBar value={k.top_used.done} max={k.top_used.of || 1} /></div>
          <div><span className="faint">All programs</span><strong>{k.summarised.toLocaleString("en-US")} / {k.programs.toLocaleString("en-US")}</strong><UsageBar value={k.summarised} max={k.programs || 1} /></div>
          <div><span className="faint">Out of date</span><strong>{k.stale}</strong><small className="faint">code changed since</small></div>
          <div><span className="faint">Searchable entries</span><strong>{k.index.entries.toLocaleString("en-US")}</strong><small className="faint">{k.sections} sections of long programs</small></div>
          <div><span className="faint">Claude cost so far</span><strong>${k.cost_usd.toFixed(2)}</strong><small className="faint">as reported by Claude Code</small></div>
        </div>
        <p className="sub">Claude reads each program from git and writes what it does, most-used first, then out-of-date ones. Small programs go several to a call; long ones are read section by section. It runs on <strong>your</strong> Claude, beside other jobs. Sonnet is a good balance for this; Haiku is the lightest on your plan.</p>
        <div className="kn-run">
          <label>Next
            <select value={limit} onChange={(e) => setLimit(Number(e.target.value))} disabled={busy}>
              {SIZES.map((n) => <option key={n} value={n}>{n} programs</option>)}
            </select>
          </label>
          <label>with
            <select value={model} onChange={(e) => setModel(e.target.value)} disabled={busy}>
              {k.models.map((m) => <option key={m.id} value={m.id}>{m.label.split(" · ")[0]}</option>)}
            </select>
          </label>
          {busy ? <button className="sm" onClick={() => job && cancelJob(job.id)}>Stop after this call</button>
            : <button className="primary" onClick={() => start("summaries")}>Write summaries</button>}
          <span className="spacer" />
          <button className="sm ghost" disabled={busy} onClick={() => start("embed")}
            title="Re-embed new or changed summaries and facts (runs on this machine, no Claude)">Update search index</button>
        </div>
        {est && !busy && (
          <div className="faint kn-est">
            {est.programs === 0 ? "Every program has a current summary." : <>
              About {est.calls} Claude call{est.calls === 1 ? "" : "s"} for {est.lines.toLocaleString("en-US")} lines. Next up: {est.first.map((f, i) => (
                <span key={f.name}>{i > 0 && ", "}<code>{f.name}</code>{f.lines > 3000 ? ` (${f.lines.toLocaleString("en-US")} lines)` : ""}</span>))}
              {est.programs > est.first.length && " …"}
            </>}
          </div>
        )}
        {job && <pre className="kn-log">{log.join("\n") || "Starting…"}</pre>}
      </div>
    </section>
  );
}
