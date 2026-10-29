"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { CheckIcon, CopyIcon, DownloadIcon, SparkIcon } from "@/components/Icons";
import { errorText, toast } from "@/components/Toaster";
import ExportButton from "@/components/ExportButton";
import JobProgress from "@/components/JobProgress";
import { type Job, pollJob, reportJob, startJob } from "@/lib/jobs";

type Field = { pos: number; uv: string; heading: string; conv: string; aliases: string[]; model: string; sm: "S" | "M"; format: string; source: "rules" | "ai" | "user";
  data?: { sm?: "S" | "M"; format?: string; required?: boolean } };
type Model = { table_name: string; description: string; description_source: string; fields: Field[] };
const FORMATS = ["string", "date", "time", "number", "decimal"];
const SOURCE: Record<string, [string, string]> = { rules: ["suggested", ""], ai: ["AI", "violet"], user: ["edited", "blue"] };

function toJson(m: Model) {
  return JSON.stringify({
    table_name: m.table_name, description: m.description,
    fields: m.fields.map((f) => ({ pos: f.pos, uv: f.uv, model: f.model, sm: f.sm, format: f.format })),
  }, null, 2);
}

// The file's dictionary as the new system's model: pos / uv / model / sm / format, editable, exportable.
export default function DictModelEditor({ file }: { file: string }) {
  const [saved, setSaved] = useState<Model | null>(null);
  const [m, setM] = useState<Model | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [showJson, setShowJson] = useState(false);
  const [copied, setCopied] = useState(false);
  const url = `/api/dict/${encodeURIComponent(file)}/model`;

  const load = useCallback(async () => {
    const r = await fetch(url).catch(() => null);
    if (!r?.ok) { if (r?.status !== 404) toast.error("Couldn't load the dictionary model", await errorText(r)); return; }
    const d = await r.json();
    setSaved(d); setM(d);
  }, [url]);
  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!job || job.state !== "running") return;
    const t = setInterval(async () => {
      const j = await pollJob(job.id);
      if (!j) return;
      setJob(j);
      if (j.state !== "running") { reportJob(j, "Field naming", "Field names suggested"); load(); }
    }, 1500);
    return () => clearInterval(t);
  }, [job, load]);

  const dirty = useMemo(() => !!m && !!saved && toJson(m) !== toJson(saved), [m, saved]);
  if (!m) return null;

  const set = (pos: number, patch: Partial<Field>) =>
    setM({ ...m, fields: m.fields.map((f) => (f.pos === pos ? { ...f, ...patch, source: "user" } : f)) });
  // where the latest data profile disagrees with the DICT
  const fixes = m.fields.filter((f) => (f.data?.sm && f.data.sm !== f.sm) || (f.data?.format && f.data.format !== f.format));
  const applyFixes = () => setM({ ...m, fields: m.fields.map((f) => fixes.includes(f)
    ? { ...f, sm: f.data?.sm ?? f.sm, format: f.data?.format ?? f.format, source: "user" as const } : f) });
  const dupes = new Set(m.fields.map((f) => f.model).filter((x, i, a) => x && a.indexOf(x) !== i));

  async function save() {
    if (!m || !saved) return;
    const changed = m.fields.filter((f) => {
      const o = saved.fields.find((x) => x.pos === f.pos);
      return o && (o.model !== f.model || o.sm !== f.sm || o.format !== f.format);
    }).map((f) => ({ pos: f.pos, model: f.model, sm: f.sm, format: f.format }));
    const body: any = { fields: changed };
    if (m.description !== saved.description) body.description = m.description;
    const r = await fetch(url, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).catch(() => null);
    if (!r?.ok) { toast.error("Couldn't save", await errorText(r)); return; }
    const d = await r.json();
    setSaved(d); setM(d);
    toast.success("Model names saved", `${changed.length} field${changed.length === 1 ? "" : "s"} updated`);
  }
  async function reset() {
    if (!window.confirm("Drop every edited and AI name for this file and go back to the suggested names?")) return;
    const r = await fetch(url, { method: "DELETE" }).catch(() => null);
    if (!r?.ok) { toast.error("Couldn't reset", await errorText(r)); return; }
    const d = await r.json();
    setSaved(d); setM(d);
    toast.info("Back to suggested names");
  }
  async function copy() {
    try { await navigator.clipboard.writeText(toJson(m!)); setCopied(true); setTimeout(() => setCopied(false), 1500); toast.success("JSON copied", `${m!.fields.length} fields`); }
    catch { toast.error("Couldn't copy", "The browser blocked clipboard access."); }
  }
  function download() {
    const blob = new Blob([toJson(m!) + "\n"], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `${m!.table_name}.json`;
    a.click();
    URL.revokeObjectURL(a.href);
  }
  const running = job?.state === "running";

  return (
    <section className="card" id="model" data-section="model-export">
      <div className="card-head">
        <h2>Model export</h2>
        <span className="sub">DICT → new system field names · {m.fields.length} fields</span>
        <span className="spacer" />
        {running ? null : (
          <button className="sm" onClick={async () => { const j = await startJob("/api/jobs/dict-names", { pick_file: file }, "Field naming"); if (j) setJob(j); }}
            disabled={dirty} title={dirty ? "Save or discard your edits first" : "Claude Code reads the dictionary and how the code uses each attribute, then names every field. Your edits are kept."}>
            <SparkIcon size={14} /> Suggest names with AI
          </button>
        )}
        <button className="sm" onClick={copy}>{copied ? <CheckIcon size={14} /> : <CopyIcon size={14} />} Copy JSON</button>
        <button className="sm" onClick={download}><DownloadIcon size={14} /> Download</button>
        <ExportButton section="model-export" sectionTitle="Model export" />
      </div>
      {running && job && (
        <div className="card-body" style={{ paddingBottom: 0 }}>
          <JobProgress job={job} title={`Claude is naming the fields of ${file}`} expectedKind="dict-names"
            hint="Reads the dictionary and how the code uses each field. Usually about a minute; uses your Claude Code plan. Your edited names are kept." />
        </div>
      )}
      {fixes.length > 0 && (
        <div className="card-body dm-fixes">
          <span>The data profile disagrees with the DICT on <b>{fixes.length}</b> field{fixes.length === 1 ? "" : "s"} (e.g. single-valued in the DICT but multivalued in the data).</span>
          <span className="spacer" />
          <a href={`/files/${encodeURIComponent(file)}/profile`} className="btn sm ghost">See profile</a>
          <button className="sm" onClick={applyFixes}>Apply data fixes</button>
        </div>
      )}
      <div className="card-body dm-desc">
        <label>
          <span>
            Description
            {m.description_source !== "rules" && <span className={`badge ${SOURCE[m.description_source]?.[1] ?? ""}`}>{SOURCE[m.description_source]?.[0]}</span>}
          </span>
          <input value={m.description} onChange={(e) => setM({ ...m, description: e.target.value, description_source: "user" })} placeholder="What this file holds" />
        </label>
      </div>
      <div className="table-wrap tall">
        <table className="dm-table">
          <thead><tr><th className="num w-min">Pos</th><th>UV (DICT)</th><th>Model</th><th className="w-min">S/M</th><th className="w-min">Format</th><th className="w-min" /></tr></thead>
          <tbody>
            {m.fields.map((f) => (
              <tr key={f.pos}>
                <td className="num w-min mono">{f.pos}</td>
                <td>
                  <span className="mono" style={{ fontWeight: 600 }}>{f.uv}</span>
                  {(f.heading || f.conv || f.aliases.length > 0) && (
                    <div className="sub dm-meta">
                      {f.heading && <span title="Column heading">“{f.heading}”</span>}
                      {f.conv && <span title="Conversion code" className="mono">{f.conv}</span>}
                      {f.aliases.length > 0 && <span title={`Also named: ${f.aliases.join(", ")}`}>+{f.aliases.length} alias{f.aliases.length === 1 ? "" : "es"}</span>}
                    </div>
                  )}
                </td>
                <td>
                  <input className={`mono dm-input ${dupes.has(f.model) ? "dm-dupe" : ""}`} value={f.model} spellCheck={false}
                    onChange={(e) => set(f.pos, { model: e.target.value.replace(/[^A-Za-z0-9_]/g, "") })}
                    title={dupes.has(f.model) ? "Another field has this name" : undefined} />
                </td>
                <td className="w-min nowrap">
                  <select value={f.sm} onChange={(e) => set(f.pos, { sm: e.target.value as "S" | "M" })}>
                    <option value="S">S</option><option value="M">M</option>
                  </select>
                  {f.data?.sm && f.data.sm !== f.sm && <span className="dm-hint" title="The data profile found several values in this field">data: {f.data.sm}</span>}
                </td>
                <td className="w-min nowrap">
                  <select className="dm-format" value={f.format} onChange={(e) => set(f.pos, { format: e.target.value })}>
                    {FORMATS.map((x) => <option key={x} value={x}>{x}</option>)}
                  </select>
                  {f.data?.format && f.data.format !== f.format && <span className="dm-hint" title="What the sampled values look like">data: {f.data.format}</span>}
                  {f.data?.required && <span className="dm-hint ok" title="Filled in every sampled record">required</span>}
                </td>
                <td className="w-min">{f.source !== "rules" && <span className={`badge ${SOURCE[f.source][1]}`}>{SOURCE[f.source][0]}</span>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {showJson && <pre className="dm-json">{toJson(m)}</pre>}
      <div className="card-foot">
        <button className="ghost sm" onClick={() => setShowJson((v) => !v)}>{showJson ? "Hide" : "Show"} JSON</button>
        <span className="sub">S/M and format come from the DICT (depth and conversion). Names are suggested from the DICT name and heading until you edit them or ask the AI.</span>
        <span className="spacer" />
        <button className="ghost sm" onClick={reset}>Reset names</button>
        {dirty && <button className="sm" onClick={() => setM(saved)}>Discard</button>}
        <button className="primary sm" onClick={save} disabled={!dirty || dupes.size > 0}>Save</button>
      </div>
    </section>
  );
}
