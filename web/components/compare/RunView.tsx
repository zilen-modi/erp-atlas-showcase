"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import DiffTable, { STATUS, type Row, Value } from "@/components/compare/DiffTable";
import { CheckIcon, ChevronIcon, CompareIcon, CopyIcon, EditIcon, SyncIcon, TrashIcon } from "@/components/Icons";
import { ago } from "@/lib/api";
import { isPrint } from "@/lib/print";
import { readParam, writeParams } from "@/lib/urlstate";
import ExportButton from "@/components/ExportButton";
import { cancelJob, type Job, pollJob, reportJob, startJob } from "@/lib/jobs";
import { errorText, toast } from "@/components/Toaster";


const CHANGE: Record<string, [string, string]> = {
  both: ["Both changed it the same way", "green"],
  "both-differently": ["Both changed it, differently", "red"],
  "old-only": ["Only the old system changed it", "violet"],
  "new-only": ["Only the new system changed it", "blue"],
};

function CaptureState({ c }: { c: any }) {
  const sides = ["legacy", "new"].filter((s) => c?.[s]);
  if (sides.length === 0) return <span className="cap-dot none" title="Not captured" />;
  return <span className={`cap-dot ${sides.length === 2 ? "both" : "half"}`} title={sides.length === 2 ? "Both captured" : "One side captured"} />;
}

export default function RunView({ runId }: { runId: string }) {
  const router = useRouter();
  const [run, setRun] = useState<any>(null);
  const [step, setStep] = useState<string | null>(() => readParam("step"));
  const [view, setView] = useState<"diff" | "changes">(() => (readParam("view") === "changes" ? "changes" : "diff"));
  const [data, setData] = useState<any>(null);
  const [onlyDiff, setOnlyDiff] = useState(() => readParam("rows") !== "all");
  const [job, setJob] = useState<Job | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [editKeys, setEditKeys] = useState(false);
  const [copied, setCopied] = useState(false);
  // accordion state per file; unset = default (open when there is something to look at)
  const [open, setOpen] = useState<Record<string, boolean>>({});
  useEffect(() => setOpen({}), [step, view]);
  // keep what's on screen in the address, so Export and shared links show this step and view
  useEffect(() => {
    if (step) writeParams({ step, view: view === "changes" ? "changes" : null, rows: onlyDiff ? null : "all" });
  }, [step, view, onlyDiff]);

  const loadRun = useCallback(async () => {
    const r = await fetch(`/api/compare/runs/${runId}`);
    if (!r.ok) { const m = await errorText(r); setErr(m); toast.error("Couldn't load this run", m); return; }
    const d = await r.json();
    setRun(d);
    setStep((s) => (s && d.steps.some((x: any) => x.id === s) ? s : null)
      ?? d.steps.find((x: any) => Object.keys(x.captured).length)?.id ?? d.steps[0]?.id ?? null);
  }, [runId]);

  const stepIdx = run?.steps.findIndex((s: any) => s.id === step) ?? -1;
  const prevStep = stepIdx > 0 ? run.steps[stepIdx - 1] : null;

  const loadData = useCallback(async () => {
    if (!step) return;
    const url = view === "changes" && prevStep
      ? `/api/compare/runs/${runId}/changes?from_step=${prevStep.id}&to_step=${step}`
      : `/api/compare/runs/${runId}/diff?step_id=${step}`;
    const r = await fetch(url);
    if (r.ok) setData({ view: view === "changes" && prevStep ? "changes" : "diff", ...(await r.json()) });
  }, [runId, step, view, prevStep]);

  useEffect(() => { loadRun(); }, [loadRun]);
  useEffect(() => { loadData(); }, [loadData]);

  useEffect(() => {
    if (!job || job.state !== "running") return;
    const t = setInterval(async () => {
      const j = await pollJob(job.id);
      if (!j) return;
      setJob(j);
      if (j.state !== "running") {
        reportJob(j, "Capture", `Captured ${j.log.filter((l) => l.startsWith("[")).length} records`);
        loadRun(); loadData();
      }
    }, 1200);
    return () => clearInterval(t);
  }, [job, loadRun, loadData]);

  async function capture(sides: string[]) {
    const j = await startJob(`/api/jobs/capture/${runId}`, { step_id: step, sides }, "Capture");
    if (j) setJob(j);
  }

  async function copyReport() {
    const r = await fetch(`/api/compare/runs/${runId}/report`);
    if (!r.ok) return;
    try { await navigator.clipboard.writeText((await r.json()).markdown); setCopied(true); setTimeout(() => setCopied(false), 1500); } catch { /* ignore */ }
  }

  async function removeRun() {
    if (!window.confirm("Delete this run and its captures? Notes remembered for the flow are kept.")) return;
    await fetch(`/api/compare/runs/${runId}`, { method: "DELETE" });
    router.push(`/compare/flows/${run.flow.id}`);
  }

  if (err && !run) return <div className="card empty">This run couldn't be loaded.</div>;
  if (!run) return <div className="card empty" data-report-busy><span className="spinner" style={{ display: "inline-block" }} /></div>;
  const cur = run.steps[stepIdx];
  const running = job?.state === "running";
  const totalDiffs = data?.view === "diff" ? data.files.reduce((n: number, f: any) => n + f.differences, 0) : null;

  return (
    <>
      {!data && !err && <span hidden data-report-busy />}
      <div className="page-head">
        <div style={{ minWidth: 0 }}>
          <div className="eyebrow"><Link href={`/compare/flows/${run.flow.id}`}>{run.flow.name}</Link></div>
          <h1>{run.name}</h1>
          <div className="meta">
            <span className="side-tag old">Old</span><code>{run.legacy_key || "—"}</code>
            <span className="side-tag new">New</span><code>{run.new_key || "—"}</code>
            <button className="ghost sm" onClick={() => setEditKeys((v) => !v)}><EditIcon size={13} /> Keys</button>
          </div>
        </div>
        <div className="actions">
          <button onClick={copyReport}>{copied ? <CheckIcon size={14} /> : <CopyIcon size={14} />} {copied ? "Copied" : "Copy report"}</button>
          <button className="ghost" onClick={removeRun} aria-label="Delete run"><TrashIcon size={14} /></button>
        </div>
      </div>

      {editKeys && <KeysEditor run={run} onSaved={() => { setEditKeys(false); loadRun(); loadData(); }} />}

      <nav className="tabs step-tabs">
        {run.steps.map((s: any, i: number) => (
          <a key={s.id} href="#" className={s.id === step ? "active" : ""} onClick={(e) => { e.preventDefault(); setStep(s.id); }}>
            <CaptureState c={s.captured} /> <span className="faint">{i + 1}</span> {s.name}
          </a>
        ))}
      </nav>

      <section className="card" style={{ marginBottom: 16 }}>
        <div className="toolbar" style={{ borderBottom: 0 }}>
          <b>{cur?.name}</b>
          <span className="sub">
            {cur?.captured?.legacy ? <>old captured {ago(cur.captured.legacy.at)}</> : "old not captured"}
            {" · "}
            {cur?.captured?.new ? <>new captured {ago(cur.captured.new.at)}</> : "new not captured"}
          </span>
          <span className="spacer" />
          <button className="primary" disabled={running} onClick={() => capture(["legacy", "new"])}>
            {running ? <><span className="spinner" style={{ borderTopColor: "#fff" }} /> Capturing…</> : <><SyncIcon size={14} /> Capture both</>}
          </button>
          <button disabled={running} onClick={() => capture(["legacy"])}>Old only</button>
          <button disabled={running} onClick={() => capture(["new"])}>New only</button>
        </div>
        {job && job.state === "running" && (
          <div style={{ padding: "0 16px 14px" }}>
            <div className="row" style={{ marginBottom: 6 }}>
              <span className="spinner" />
              <span className="sub">{job.kind === "capture" ? "Reading records from TEST…" : `Waiting for another job (${job.kind}) to finish…`}</span>
              <span className="spacer" />
              <button className="sm" onClick={() => cancelJob(job.id)}>Cancel</button>
            </div>
            {job.log.length > 0 && <div className="log">{job.log.slice(-20).join("\n")}</div>}
          </div>
        )}
        <div className="card-foot" style={{ justifyContent: "flex-start" }}>
          <div className="seg">
            <a href="#" className={view === "diff" ? "active" : ""} onClick={(e) => { e.preventDefault(); setView("diff"); }}>
              <CompareIcon size={13} /> &nbsp;Old vs new
            </a>
            <a href="#" className={view === "changes" ? "active" : ""} title={prevStep ? `Compared with “${prevStep.name}”` : "Needs an earlier step"}
              onClick={(e) => { e.preventDefault(); if (prevStep) setView("changes"); }} style={!prevStep ? { opacity: 0.45, cursor: "not-allowed" } : {}}>
              What this step changed
            </a>
          </div>
          {data?.view === "diff" && (
            <label className="row sub" style={{ gap: 6, cursor: "pointer" }}>
              <input type="checkbox" checked={onlyDiff} onChange={(e) => setOnlyDiff(e.target.checked)} style={{ width: "auto", height: "auto" }} />
              Differences only
            </label>
          )}
          <span className="spacer" />
          {data?.files.length > 1 && (
            <>
              <button className="ghost sm" onClick={() => setOpen(Object.fromEntries(data.files.map((f: any) => [f.file_id, true])))}>Expand all</button>
              <button className="ghost sm" onClick={() => setOpen(Object.fromEntries(data.files.map((f: any) => [f.file_id, false])))}>Collapse all</button>
            </>
          )}
          {totalDiffs != null && <span className={`badge ${totalDiffs ? "red" : "green"}`}>{totalDiffs} difference{totalDiffs === 1 ? "" : "s"} in this step</span>}
        </div>
      </section>

      <div className="stack">
        {data?.files.map((f: any) => data.view === "diff" ? (
          <Fold key={f.file_id} sectionId={`file-${f.file_id}`} title={f.pick_file} open={open[f.file_id] ?? hasData(f, "diff")} onToggle={(v) => setOpen((o) => ({ ...o, [f.file_id]: v }))}
            head={<>
              <h2 className="mono">{f.pick_file}</h2>
              <SideInfo label="Old" s={f.old} />
              <SideInfo label="New" s={f.new} />
              <span className="spacer" />
              {f.explained > 0 && <span className="badge green">{f.explained} explained</span>}
              {(f.old?.found || f.new?.found) && (
                <span className={`badge ${f.differences ? "red" : "green"}`}>{f.differences ? `${f.differences} different` : "all match"}</span>
              )}
              {!f.old && !f.new && <span className="badge">not captured</span>}
              {(f.old || f.new) && !f.old?.found && !f.new?.found && <span className="badge amber">not found</span>}
            </>}>
            {!f.old && !f.new ? <div className="empty">Not captured yet for this step.</div>
              : !f.old?.found && !f.new?.found ? <div className="empty">The record wasn't found in either system at this step. Check the keys.</div> : (
                <DiffTable rows={f.rows as Row[]} pickFile={f.pick_file} runId={runId} onChanged={loadData} onlyDiff={onlyDiff} />
              )}
          </Fold>
        ) : (
          <Fold key={f.file_id} sectionId={`file-${f.file_id}`} title={`${f.pick_file} changes`} open={open[f.file_id] ?? hasData(f, "changes")} onToggle={(v) => setOpen((o) => ({ ...o, [f.file_id]: v }))}
            head={<>
              <h2 className="mono">{f.pick_file}</h2>
              <span className="sub">changes from “{prevStep?.name}” to “{cur?.name}”</span>
              <span className="spacer" />
              <span className="badge">{f.rows.length} attribute{f.rows.length === 1 ? "" : "s"} changed</span>
            </>}>
            {f.rows.length === 0 ? <div className="empty">Neither system changed this file in this step{!f.captured.legacy_to && !f.captured.new_to ? " (not captured yet)" : ""}.</div> : (
              <div className="table-wrap">
                <table className="diff-table">
                  <thead><tr><th className="num w-min">Attr</th><th>Name</th><th>Old system: before → after</th><th>New system: before → after</th><th className="w-min">Result</th></tr></thead>
                  <tbody>
                    {f.rows.map((r: any) => (
                      <tr key={r.attr} className={r.change === "both" ? "" : "st-different"}>
                        <td className="num w-min mono" style={{ fontWeight: 600 }}>&lt;{r.attr}&gt;</td>
                        <td className="nowrap sub mono">{r.names.slice(0, 2).join(", ") || "—"}</td>
                        <td><div className="before-after"><Value c={r.old_before} /><span className="arrow">→</span><Value c={r.old_after} other={r.old_before} /></div></td>
                        <td><div className="before-after"><Value c={r.new_before} /><span className="arrow">→</span><Value c={r.new_after} other={r.new_before} /></div></td>
                        <td className="w-min"><span className={`badge ${CHANGE[r.change][1]}`}>{CHANGE[r.change][0]}</span></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Fold>
        ))}
      </div>
      <p className="sub" style={{ marginTop: 12 }}>
        {Object.entries(STATUS).map(([k, [label, cls]]) => <span key={k} style={{ marginRight: 10 }}><span className={`badge ${cls}`}>{label}</span></span>)}
        Records are read from the TEST server. Notes marked “Remember” appear on every run of this flow.
      </p>
    </>
  );
}

// open by default only when there is something to read: a record found on at least one side,
// or (for "what this step changed") at least one changed attribute
function hasData(f: any, view: "diff" | "changes") {
  return view === "diff" ? !!(f.old?.found || f.new?.found) : f.rows.length > 0;
}

function Fold({ open: shown, onToggle, head, children, sectionId, title }: {
  open: boolean; onToggle: (v: boolean) => void; head: React.ReactNode; children: React.ReactNode; sectionId: string; title: string;
}) {
  const open = shown || isPrint();       // a report shows every file
  return (
    <section className={`card fold ${open ? "open" : ""}`} data-section={sectionId} id={`sec-${sectionId}`}>
      <div className="card-head fold-head" role="button" tabIndex={0} aria-expanded={open}
        onClick={(e) => { if (!(e.target as HTMLElement).closest("a,button,input,.export")) onToggle(!open); }}
        onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); onToggle(!open); } }}>
        <ChevronIcon size={15} className="fold-chev" />
        {head}
        <ExportButton section={sectionId} sectionTitle={title} />
      </div>
      {open && children}
    </section>
  );
}

function SideInfo({ label, s }: { label: string; s: any }) {
  if (!s) return <span className="sub"><span className={`side-tag ${label === "Old" ? "old" : "new"}`}>{label}</span> not captured</span>;
  return (
    <span className="sub" title={s.at ? `captured ${ago(s.at)}` : undefined}>
      <span className={`side-tag ${label === "Old" ? "old" : "new"}`}>{label}</span>
      <code>{s.key}</code>
      {!s.found && <span style={{ color: "var(--bad)" }}> · {s.error ?? "not found"}</span>}
    </span>
  );
}

function KeysEditor({ run, onSaved }: { run: any; onSaved: () => void }) {
  const [oldKey, setOldKey] = useState<string>(run.legacy_key);
  const [newKey, setNewKey] = useState<string>(run.new_key);
  const [name, setName] = useState<string>(run.name);
  const [over, setOver] = useState<Record<string, string>>(() => {
    const o: Record<string, string> = {};
    for (const f of run.files) for (const s of f.overridden) o[`${f.id}|${s}`] = f.keys[s];
    return o;
  });
  async function save() {
    const overrides = run.files.flatMap((f: any) => ["legacy", "new"].map((side) => ({ file_id: f.id, side, key: over[`${f.id}|${side}`] ?? "" })));
    await fetch(`/api/compare/runs/${run.id}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, legacy_key: oldKey, new_key: newKey, overrides }),
    });
    onSaved();
  }
  return (
    <section className="card" style={{ marginBottom: 16 }}>
      <div className="card-head"><h2>Run keys</h2><span className="sub">Leave a file's key empty to use its pattern. <code>{"{num}"}</code> = key without its letter prefix</span></div>
      <div className="card-body form-grid three">
        <label><span>Run name</span><input value={name} onChange={(e) => setName(e.target.value)} /></label>
        <label><span>Old system key</span><input className="mono" value={oldKey} onChange={(e) => setOldKey(e.target.value)} /></label>
        <label><span>New system key</span><input className="mono" value={newKey} onChange={(e) => setNewKey(e.target.value)} /></label>
      </div>
      <div className="table-wrap">
        <table>
          <thead><tr><th>File</th><th>Pattern</th><th>Old system record</th><th>New system record</th></tr></thead>
          <tbody>
            {run.files.map((f: any) => (
              <tr key={f.id}>
                <td className="mono" style={{ fontWeight: 600 }}>{f.pick_file}</td>
                <td className="mono sub">{f.key_template}</td>
                {["legacy", "new"].map((side) => (
                  <td key={side}>
                    <input className="mono" value={over[`${f.id}|${side}`] ?? ""} placeholder={f.keys[side] || "—"}
                      onChange={(e) => setOver((o) => ({ ...o, [`${f.id}|${side}`]: e.target.value }))} />
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="card-foot"><span className="spacer" /><button className="primary" onClick={save}>Save keys</button></div>
    </section>
  );
}
