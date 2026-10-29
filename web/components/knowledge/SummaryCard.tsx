"use client";

import { useEffect, useState } from "react";
import { SparkIcon } from "@/components/Icons";
import { LineLink } from "@/components/ui";
import { ago } from "@/lib/api";
import { type Job, pollJob, reportJob, startJob } from "@/lib/jobs";

type Highlight = { line: number; note: string };
type S = { start: number; end: number; title: string; summary: string; terms: string[]; highlights: Highlight[];
  model: string | null; by: string | null; created_at: string; stale: boolean };
type Data = { program: string; indexed: boolean; lines: number | null; summary: S | null; sections: S[] };

const enc = encodeURIComponent;

// "What it does", in plain English: written by Claude from the git code, marked stale when the code changes.
export default function SummaryCard({ program }: { program: string }) {
  const [d, setD] = useState<Data | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [open, setOpen] = useState(false);
  const load = () => fetch(`/api/program/${enc(program)}/summary`).then((r) => (r.ok ? r.json() : null)).then(setD).catch(() => null);
  useEffect(() => { load(); }, [program]);   // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!job || job.state !== "running") return;
    const t = setInterval(async () => {
      const j = await pollJob(job.id);
      if (!j) return;
      setJob(j);
      if (j.state !== "running") { reportJob(j, "Summary", `Summary of ${program} written`); load(); }
    }, 2000);
    return () => clearInterval(t);
  }, [job]);   // eslint-disable-line react-hooks/exhaustive-deps

  async function write() {
    const j = await startJob(`/api/program/${enc(program)}/summarize`, {}, "Summary");
    if (j) setJob(j);
  }

  if (!d || !d.indexed) return null;
  const s = d.summary;
  const busy = job?.state === "running";
  const last = busy ? job.log.filter((l) => !l.startsWith(" ")).at(-1) : null;
  return (
    <section className="card ks-card">
      <div className="card-head">
        <h2><SparkIcon size={15} /> What it does</h2>
        {s && <span className={`badge ${s.stale ? "amber" : "violet"}`} title={s.stale ? "The code has changed since this was written" : undefined}>
          {s.stale ? "out of date" : "machine-written"}</span>}
        <span className="spacer" />
        <button className="sm ghost" onClick={write} disabled={busy}
          title={s ? "Write it again from the current code, on your Claude" : "Claude reads the code and writes a summary, on your Claude"}>
          {busy ? "Writing…" : s ? (s.stale ? "Update" : "Rewrite") : "Write a summary"}
        </button>
      </div>
      <div className="card-body stack">
        {busy && <div className="sub ks-progress">{last ?? "Starting…"}{(d.lines ?? 0) > 3000 && " · a long program is read section by section, so this takes a few minutes"}</div>}
        {!s && !busy && <p className="sub">No summary yet. Claude can read the {d.lines?.toLocaleString("en-US")} lines and explain what this program does in plain English, with the lines that matter.</p>}
        {s && <>
          <p className="ks-title">{s.title}</p>
          <p className="ks-text">{s.summary}</p>
          {s.highlights.length > 0 && (
            <ul className="ks-lines">
              {s.highlights.map((h) => <li key={h.line}><LineLink program={program} line={h.line} /> {h.note}</li>)}
            </ul>
          )}
          {s.terms.length > 0 && <div className="ks-terms">{s.terms.map((t) => <span key={t} className="chip">{t}</span>)}</div>}
          {d.sections.length > 0 && (
            <div>
              <button className="sm ghost" onClick={() => setOpen(!open)} aria-expanded={open}>
                {open ? "Hide" : "Show"} the {d.sections.length} sections
              </button>
              {open && (
                <ol className="ks-sections">
                  {d.sections.map((x) => (
                    <li key={x.start}>
                      <div><LineLink program={program} line={x.start} /><span className="faint">–{x.end}</span> <strong>{x.title}</strong></div>
                      <div className="sub">{x.summary}</div>
                    </li>
                  ))}
                </ol>
              )}
            </div>
          )}
          <div className="faint ks-foot">
            Written by Claude ({s.model ?? "unknown model"}) from the git code {ago(s.created_at)}{s.by ? ` for ${s.by.split(" <")[0]}` : ""}.
            It tells you where to look; the code is the answer.
          </div>
        </>}
      </div>
    </section>
  );
}
