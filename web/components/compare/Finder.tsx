"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import FileInput from "@/components/compare/FileInput";
import QueryBuilder, { type Field } from "@/components/compare/QueryBuilder";
import RecordPanel, { copy, listCommand } from "@/components/compare/RecordPanel";
import JobProgress from "@/components/JobProgress";
import { CopyIcon, DownloadIcon, EditIcon, LinkIcon, PlusIcon, SearchIcon, SparkIcon, TrashIcon } from "@/components/Icons";
import { errorText, toast } from "@/components/Toaster";
import { type Job, pollJob, reportJob, startJob } from "@/lib/jobs";
import { readParam, writeParams } from "@/lib/urlstate";

type Related = { file: string; key: string; exists: boolean; why?: string };
type Criteria = { query: string; columns: string[]; related: Related[] };
type Match = { key: string; values: Record<string, string>; lists?: Record<string, string[]>; related: Record<string, boolean> };
type Scenario = {
  id: string; name: string; description: string; pick_file: string; criteria: Criteria; flow_id: string | null;
  last_count: number | null; last_run: string | null; updated_at: string;
  shared: boolean; owner: string | null; mine: boolean;   // yours, or shared with the team by `owner`
};

const EMPTY: Criteria = { query: "", columns: [], related: [] };

// Find records on TEST that fit a scenario ("a shipped transfer with serial numbers") instead of hunting for keys.
export default function Finder({ initialFile = "", flowId, onPick, library = false }: {
  initialFile?: string; flowId?: string; onPick?: (side: "legacy" | "new", key: string) => void;
  /** the stand-alone page: Search and Saved scenarios as tabs, instead of a row of chips */
  library?: boolean;
}) {
  const [file, setFile] = useState(initialFile);
  const [desc, setDesc] = useState("");
  const [crit, setCrit] = useState<Criteria>(EMPTY);
  const [explain, setExplain] = useState("");
  const [name, setName] = useState("");
  const [job, setJob] = useState<Job | null>(null);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<any>(null);
  const [scen, setScen] = useState<Scenario[]>([]);
  const [scenId, setScenId] = useState<string | null>(null);
  const [shared, setShared] = useState(false);
  const [fields, setFields] = useState<Field[]>([]);
  const [opened, setOpened] = useState<string | null>(null);
  const [tab, setTab] = useState<"search" | "saved">("search");
  const [scenLoaded, setScenLoaded] = useState(false);

  const loadScen = useCallback(async () => {
    const q = new URLSearchParams();
    if (flowId) q.set("flow_id", flowId);
    if (file.trim() && !library) q.set("pick_file", file.trim());   // the library shows every file's scenarios
    const r = await fetch(`/api/finder/scenarios?${q}`).catch(() => null);
    if (r?.ok) { setScen(await r.json()); setScenLoaded(true); }
  }, [flowId, file, library]);
  useEffect(() => { loadScen(); }, [loadScen]);

  // a shared link (?scenario=…) opens that scenario and runs it; ?tab=saved opens the library
  const [linked, setLinked] = useState(false);
  useEffect(() => {
    if (!library || linked || !scenLoaded) return;
    const id = readParam("scenario"), s = id ? scen.find((x) => x.id === id) : undefined;
    const t = readParam("tab"), q = readParam("q"), f = readParam("file");
    if (s) open(s);
    else if (q != null && f) {
      // a search handed over in the link (Ask Atlas: "See received transfers on TEST"): fill it in, maybe run it
      const c: Criteria = { query: q, columns: (readParam("cols") ?? "").split(",").filter(Boolean), related: [] };
      setFile(f.toUpperCase()); setCrit(c); setTab("search");
      if (readParam("run") === "1") find(c, null, f.toUpperCase());
      writeParams({ q: null, cols: null, run: null });
    } else if (t === "saved") setTab(t);
    setLinked(true);
  }, [library, scen, scenLoaded, linked]); // eslint-disable-line react-hooks/exhaustive-deps
  // the address bar follows along once the link we were opened with has been read
  useEffect(() => {
    if (library && linked) writeParams({ tab: tab === "search" ? null : tab, scenario: tab === "search" ? scenId : null });
  }, [library, linked, tab, scenId]);

  useEffect(() => {
    if (!job || job.state !== "running") return;
    const t = setInterval(async () => {
      const j = await pollJob(job.id);
      if (!j) return;
      setJob(j);
      if (j.state !== "running") {
        reportJob(j, "Writing criteria", "Criteria ready: check them, then Find");
        if (j.state === "done" && j.result) {
          setCrit(j.result.criteria); setExplain(j.result.explanation); if (!name) setName(j.result.name);
        }
      }
    }, 1500);
    return () => clearInterval(t);
  }, [job, name]);

  async function find(c = crit, sid = scenId, f = file) {
    if (!f.trim()) { toast.error("Pick a file first", "e.g. TRANSFER"); return; }
    setBusy(true);
    const r = await fetch("/api/finder/run", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pick_file: f.trim(), criteria: c, limit: 25, scenario_id: sid }),
    }).catch(() => null);
    setBusy(false);
    if (!r?.ok) { toast.error("Search failed", await errorText(r)); return; }
    const d = await r.json();
    setRes(d);
    setCrit({ ...c, ...d.criteria });
    if (sid) loadScen();
  }
  async function save() {
    if (!name.trim()) { toast.error("Name the scenario", "e.g. Shipped transfer with serial numbers"); return; }
    const body = { pick_file: file.trim(), name: name.trim(), description: desc, criteria: crit, flow_id: flowId ?? null, shared };
    const r = await fetch(scenId ? `/api/finder/scenarios/${scenId}` : "/api/finder/scenarios", {
      method: scenId ? "PUT" : "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
    }).catch(() => null);
    if (!r?.ok) { toast.error("Couldn't save the scenario", await errorText(r)); return; }
    const s = await r.json();
    setScenId(s.id);
    toast.success("Scenario saved", shared ? "Shared: everyone on the team can run it." : "Only you can see it. Share it to let the team reuse it.");
    loadScen();
  }
  async function remove(id: string) {
    const r = await fetch(`/api/finder/scenarios/${id}`, { method: "DELETE" }).catch(() => null);
    if (!r?.ok) { toast.error("Couldn't delete the scenario", await errorText(r)); return; }
    if (scenId === id) setScenId(null);
    loadScen();
  }
  async function share(s: Scenario, on: boolean) {
    const r = await fetch(`/api/finder/scenarios/${s.id}`, {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pick_file: s.pick_file, name: s.name, description: s.description, criteria: s.criteria, flow_id: s.flow_id, shared: on }),
    }).catch(() => null);
    if (!r?.ok) { toast.error("Couldn't change sharing", await errorText(r)); return; }
    toast.success(on ? "Shared with the team" : "Now only you can see it");
    if (scenId === s.id) setShared(on);
    loadScen();
  }
  /** Load a scenario into the search; run it unless we're only editing it. */
  function open(s: Scenario, run = true) {
    // someone else's shared scenario runs as it is; changing it makes your own copy
    const copyOf = !run && !s.mine;
    setScenId(copyOf ? null : s.id); setName(copyOf ? `${s.name} (copy)` : s.name); setShared(copyOf ? false : s.shared);
    setDesc(s.description); setFile(s.pick_file); setCrit(s.criteria); setExplain("");
    setRes(null); setOpened(null); setTab("search");
    if (run) find(s.criteria, s.id, s.pick_file);      // the file too: setFile hasn't landed yet
  }
  function startNew() {
    setScenId(null); setShared(false); setName(""); setDesc(""); setCrit(EMPTY); setExplain(""); setRes(null); setTab("search");
  }
  const running = job?.state === "running";
  const cols = res?.criteria?.columns ?? crit.columns;

  return (
    <div className="finder">
      {library && (
        <div className="finder-tabs" role="tablist">
          <button type="button" role="tab" aria-selected={tab === "search"} className={tab === "search" ? "on" : ""} onClick={() => setTab("search")}>
            <SearchIcon size={14} /> Search{scenId && name ? <span className="finder-tab-sub">· {name}</span> : null}
          </button>
          <button type="button" role="tab" aria-selected={tab === "saved"} className={tab === "saved" ? "on" : ""} onClick={() => setTab("saved")}>
            Saved scenarios <span className="finder-count">{scen.length}</span>
          </button>
          {tab === "search" && scenId && <button type="button" className="ghost sm finder-new" onClick={startNew}><PlusIcon size={13} /> New search</button>}
        </div>
      )}

      {library && tab === "saved" && (
        <ScenarioLibrary scenarios={scen} current={scenId} onRun={(s) => open(s)} onEdit={(s) => open(s, false)} onDelete={remove} onShare={share} onNew={startNew} />
      )}

      {!library && scen.length > 0 && (
        <div className="finder-scen">
          <span className="sub">Saved scenarios:</span>
          {scen.map((s) => (
            <span key={s.id} className={`chip finder-chip ${s.id === scenId ? "on" : ""}`}>
              <button type="button" className="ghost sm" onClick={() => open(s)} title={s.criteria.query || "no selection"}>
                {s.name}{s.last_count != null && <span className="chip-meta">{s.last_count}</span>}
              </button>
              <button type="button" className="ghost icon-btn sm" aria-label={`Delete ${s.name}`} onClick={() => remove(s.id)}><TrashIcon size={12} /></button>
            </span>
          ))}
        </div>
      )}

      {(!library || tab === "search") && (<>
        <div className="finder-grid">
          <label><span>File</span><FileInput value={file} onChange={setFile} /></label>
          <label className="finder-desc"><span>Describe the record you need</span>
            <input value={desc} onChange={(e) => setDesc(e.target.value)} placeholder="e.g. a transfer with serial-numbered lines, already shipped, ordered this month"
              onKeyDown={(e) => { if (e.key === "Enter" && desc.trim() && file.trim()) (document.getElementById("finder-ai") as HTMLButtonElement)?.click(); }} />
          </label>
          <button type="button" id="finder-ai" disabled={running || !desc.trim() || !file.trim()} onClick={async () => {
            const j = await startJob("/api/jobs/finder-suggest", { pick_file: file.trim(), description: desc }, "Writing criteria");
            if (j) setJob(j);
          }}><SparkIcon size={14} /> Write criteria</button>
        </div>
        {running && job && <JobProgress job={job} title="Claude is turning your description into search criteria" expectedKind="finder"
          hint="Uses the DICT, the screen's dropdown values and the data profile. Usually under a minute." />}

        <div className="finder-crit">
          <div>
            <span className="finder-lbl">Conditions</span>
            <QueryBuilder file={file} query={crit.query} onChange={(q) => setCrit((c) => ({ ...c, query: q }))} onFields={setFields} />
          </div>
          <label><span>Selection (RetrieVe, read-only) · the conditions above, as text</span>
            <input className="mono" value={crit.query} onChange={(e) => setCrit({ ...crit, query: e.target.value })}
              placeholder={'WITH MODE = "S" AND WITH DATE-ORD GE "09/01/2026"'} spellCheck={false} />
          </label>
          <div>
            <span className="finder-lbl">Related records</span>
            {crit.related.map((r, i) => (
              <div key={i} className="finder-rel">
                <select value={r.exists ? "1" : "0"} onChange={(e) => setCrit({ ...crit, related: crit.related.map((x, j) => j === i ? { ...x, exists: e.target.value === "1" } : x) })}>
                  <option value="1">must exist</option><option value="0">must not exist</option>
                </select>
                <input className="mono" value={r.file} onChange={(e) => setCrit({ ...crit, related: crit.related.map((x, j) => j === i ? { ...x, file: e.target.value.toUpperCase() } : x) })} placeholder="TRANSFER-HIST" />
                <input className="mono" value={r.key} onChange={(e) => setCrit({ ...crit, related: crit.related.map((x, j) => j === i ? { ...x, key: e.target.value } : x) })} placeholder="{key}-1" />
                <button type="button" className="ghost icon-btn sm" aria-label="Remove" onClick={() => setCrit({ ...crit, related: crit.related.filter((_x, j) => j !== i) })}><TrashIcon size={13} /></button>
                {r.why && <span className="sub finder-why">{r.why}</span>}
              </div>
            ))}
            <button type="button" className="ghost sm" onClick={() => setCrit({ ...crit, related: [...crit.related, { file: "", key: "{key}-1", exists: true }] })}><PlusIcon size={13} /> Add related record</button>
          </div>
          <div>
            <span className="finder-lbl">Columns to show</span>
            <div className="finder-cols">
              {crit.columns.map((c) => (
                <span key={c} className="chip finder-col mono">{c}
                  <button type="button" className="ghost icon-btn sm" aria-label={`Remove ${c}`} onClick={() => setCrit({ ...crit, columns: crit.columns.filter((x) => x !== c) })}>×</button>
                </span>
              ))}
              {crit.columns.length < 8 && (
                <select value="" aria-label="Add a column" onChange={(e) => e.target.value && setCrit({ ...crit, columns: [...crit.columns, e.target.value] })}>
                  <option value="">+ add column</option>
                  {fields.filter((f) => f.attr > 0 && !crit.columns.includes(f.name)).map((f) => (
                    <option key={f.name} value={f.name}>{f.name} &lt;{f.attr}&gt;{f.filled_pct != null ? ` · ${Math.round(f.filled_pct)}%` : ""}</option>
                  ))}
                </select>
              )}
            </div>
          </div>
          {explain && <div className="finder-explain sub"><SparkIcon size={13} /> {explain}</div>}
          <div className="row" style={{ gap: 8 }}>
            <button type="button" className="primary" onClick={() => find()} disabled={busy || !file.trim()}>
              {busy ? <><span className="spinner" style={{ borderTopColor: "#fff" }} /> Searching TEST…</> : <><SearchIcon size={14} /> Find</>}
            </button>
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="Scenario name" style={{ maxWidth: 260 }} />
            <label className="finder-share" title="Shared scenarios appear in everyone's Saved tab">
              <input type="checkbox" checked={shared} onChange={(e) => setShared(e.target.checked)} /> Share with team
            </label>
            <button type="button" onClick={save} disabled={!file.trim()}>{scenId ? "Update scenario" : "Save scenario"}</button>
          </div>
        </div>

        {res && (
          <div className="finder-res">
            <div className="toolbar">
              <b>{res.total_matches} match{res.total_matches === 1 ? "" : "es"}</b>
              <span className="sub">
                {res.selected} selected by the query{res.criteria.related.length > 0 && `, ${res.total_matches} passed the related-record checks`}
                {res.capped && " (selection capped: narrow the query to see more)"}
              </span>
              {res.matches.length > 0 && (
                <span className="finder-out">
                  <button type="button" className="ghost sm" onClick={() => copy(res.matches.map((m: Match) => m.key).join("\n"), "Keys")}><CopyIcon size={13} /> Keys</button>
                  <button type="button" className="ghost sm" onClick={() => copy(listCommand(res.table, res.matches.map((m: Match) => m.key), cols), "LIST command")}><CopyIcon size={13} /> LIST command</button>
                  <button type="button" className="ghost sm" onClick={() => downloadCsv(res, cols)}><DownloadIcon size={13} /> CSV</button>
                </span>
              )}
            </div>
            {res.matches.length === 0 ? (
              <div className="empty">{res.selected > 0 ? "Records matched the selection, but none passed the related-record checks. Loosen or remove a check." : "No records on TEST match. Loosen the selection."}</div>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Key</th>{cols.map((c: string) => <th key={c}>{c}</th>)}{res.criteria.related.map((r: Related) => <th key={r.file + r.key} className="nowrap">{r.file} {r.key}</th>)}<th className="w-min" /></tr></thead>
                  <tbody>
                    {res.matches.map((m: Match) => (
                      <tr key={m.key} className={`finder-row${opened === m.key ? " on" : ""}`} title="Open the whole record"
                        onClick={(e) => { if (!(e.target as HTMLElement).closest("button, a")) setOpened(m.key); }}>
                        <td className="mono" style={{ fontWeight: 600 }}>{m.key}</td>
                        {cols.map((c: string) => <td key={c} className="mono sub" title={m.values[c]}><Vals list={m.lists?.[c]} flat={m.values[c]} /></td>)}
                        {res.criteria.related.map((r: Related) => {
                          const v = m.related[`${r.file} ${r.key}`];
                          return <td key={r.file + r.key}>{v ? <span className="ok-text">exists</span> : <span className="faint">none</span>}</td>;
                        })}
                        <td className="w-min nowrap">
                          {onPick ? (
                            <>
                              <button type="button" className="sm" onClick={() => onPick("legacy", m.key)}>Use as old</button>{" "}
                              <button type="button" className="sm" onClick={() => onPick("new", m.key)}>Use as new</button>
                            </>
                          ) : (
                            <button type="button" className="ghost sm" onClick={async () => { try { await navigator.clipboard.writeText(m.key); toast.success("Key copied", m.key); } catch { toast.info("Key", m.key); } }}>
                              <CopyIcon size={13} /> Copy key
                            </button>
                          )}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </div>
        )}
        {opened && res && (
          <RecordPanel file={res.table} recordKey={opened} related={res.criteria.related.map((r: Related) => ({ file: r.file, key: r.key }))}
            columns={cols} onClose={() => setOpened(null)} />
        )}
      </>)}
    </div>
  );
}

/** A column's values: one chip per value when the field holds several. */
function Vals({ list, flat }: { list?: string[]; flat: string }) {
  const v = list ?? (flat ? [flat] : []);
  if (!v.length) return <span className="faint">—</span>;
  if (v.length === 1) return <span className="finder-one">{v[0]}</span>;
  return <span className="finder-mv">{v.slice(0, 3).map((x, i) => <span key={i}>{x}</span>)}{v.length > 3 && <em>+{v.length - 3}</em>}</span>;
}

function downloadCsv(res: { table: string; matches: Match[]; criteria: Criteria }, cols: string[]) {
  const esc = (s: string) => (/[",\n]/.test(s) ? `"${s.replace(/"/g, '""')}"` : s);
  const rel = res.criteria.related.map((r) => `${r.file} ${r.key}`);
  const lines = [["KEY", ...cols, ...rel].map(esc).join(","),
    ...res.matches.map((m) => [m.key, ...cols.map((c) => (m.lists?.[c] ?? [m.values[c] ?? ""]).join(" | ")),
      ...rel.map((k) => (m.related[k] ? "exists" : "none"))].map(esc).join(","))];
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([lines.join("\n")], { type: "text/csv" }));
  a.download = `${res.table.toLowerCase()}-test-data.csv`;
  a.click();
  URL.revokeObjectURL(a.href);
}

function ago(iso: string | null) {
  if (!iso) return null;
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`;
}

// Every saved scenario as a card: what it finds, how, and how it did last time; run, edit, share or delete it.
function ScenarioLibrary({ scenarios, current, onRun, onEdit, onDelete, onShare, onNew }: {
  scenarios: Scenario[]; current: string | null; onRun: (s: Scenario) => void; onEdit: (s: Scenario) => void;
  onDelete: (id: string) => void; onShare: (s: Scenario, on: boolean) => void; onNew: () => void;
}) {
  const [q, setQ] = useState("");
  const [file, setFile] = useState<string | null>(null);
  const [whose, setWhose] = useState<"all" | "mine" | "team">("all");
  const files = useMemo(() => {
    const n = new Map<string, number>();
    scenarios.forEach((s) => n.set(s.pick_file, (n.get(s.pick_file) ?? 0) + 1));
    return [...n].sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0]));
  }, [scenarios]);
  const shown = scenarios.filter((s) => (!file || s.pick_file === file)
    && (whose === "all" || (whose === "mine" ? s.mine : !s.mine)) && (!q.trim()
    || `${s.name} ${s.description} ${s.criteria.query} ${s.pick_file}`.toUpperCase().includes(q.trim().toUpperCase())));

  if (!scenarios.length) {
    return (
      <div className="lib-empty">
        <b>No saved scenarios yet</b>
        <span>Build a search, give it a name and press Save scenario. Only you see it, unless you tick Share with team.</span>
        <button type="button" className="primary sm" onClick={onNew}><PlusIcon size={13} /> New search</button>
      </div>
    );
  }
  return (
    <div className="lib">
      <div className="lib-tools">
        <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Filter by name, description or query…" />
        <div className="lib-files">
          <span className="seg lib-whose" role="radiogroup" aria-label="Whose scenarios">
            {([["all", "All"], ["mine", "Mine"], ["team", "From the team"]] as const).map(([k, label]) => (
              <button key={k} type="button" role="radio" aria-checked={whose === k} className={whose === k ? "on" : ""} onClick={() => setWhose(k)}>{label}</button>
            ))}
          </span>
          <button type="button" className={`chip ${!file ? "on" : ""}`} onClick={() => setFile(null)}>All <span className="chip-meta">{scenarios.length}</span></button>
          {files.map(([f, n]) => (
            <button key={f} type="button" className={`chip mono ${file === f ? "on" : ""}`} onClick={() => setFile(file === f ? null : f)}>{f} <span className="chip-meta">{n}</span></button>
          ))}
        </div>
      </div>
      {shown.length === 0 && <div className="empty">No scenario matches.</div>}
      <div className="lib-grid">
        {shown.map((s) => {
          const ran = ago(s.last_run);
          return (
            <article key={s.id} className={`lib-card${s.id === current ? " on" : ""}`}>
              <div className="lib-card-h">
                <span className="chip mono lib-file">{s.pick_file}</span>
                {s.last_count != null
                  ? <span className={`lib-count ${s.last_count === 0 ? "none" : ""}`} title={ran ? `last run ${ran}` : undefined}>{s.last_count === 0 ? "found nothing" : `${s.last_count} match${s.last_count === 1 ? "" : "es"}`}</span>
                  : <span className="lib-count dim">not run yet</span>}
              </div>
              <h3>{s.name}</h3>
              <div className="lib-who">
                {s.mine
                  ? <button type="button" className={`lib-share ${s.shared ? "on" : ""}`} onClick={() => onShare(s, !s.shared)}
                      title={s.shared ? "Everyone on the team sees this. Click to make it yours only." : "Only you see this. Click to share it with the team."}>
                      {s.shared ? "Shared with team" : "Only you"}
                    </button>
                  : <span className="lib-share team">{s.owner ? `Shared by ${s.owner}` : "Team scenario"}</span>}
              </div>
              {s.description && <p className="lib-desc">{s.description}</p>}
              <code className="lib-query" title={s.criteria.query}>{s.criteria.query || "(every record)"}</code>
              <div className="lib-meta">
                {s.criteria.related.map((r) => (
                  <span key={r.file + r.key} className={`lib-rel ${r.exists ? "" : "not"}`} title={r.why || undefined}>{r.exists ? "has" : "no"} <b className="mono">{r.file} {r.key}</b></span>
                ))}
                {s.criteria.columns.length > 0 && <span className="lib-cols">shows {s.criteria.columns.slice(0, 4).join(", ")}{s.criteria.columns.length > 4 ? ` +${s.criteria.columns.length - 4}` : ""}</span>}
              </div>
              <div className="lib-foot">
                <span className="sub">{ran ? `ran ${ran}` : `saved ${ago(s.updated_at) ?? ""}`}</span>
                <span className="lib-actions">
                  <button type="button" className="primary sm" onClick={() => onRun(s)}><SearchIcon size={13} /> Run</button>
                  <button type="button" className="sm" onClick={() => onEdit(s)} title={s.mine ? undefined : "Make your own copy to change"}>
                    {s.mine ? <><EditIcon size={13} /> Edit</> : <><CopyIcon size={13} /> Copy</>}</button>
                  <button type="button" className="ghost icon-btn sm" aria-label="Copy a link to this scenario"
                    title={s.shared || !s.mine ? "Copy a link that runs it" : "Copy a link that runs it (teammates can open it once you share it)"}
                    onClick={() => copy(`${window.location.origin}/test-data?scenario=${s.id}`, "Link")}><LinkIcon size={13} /></button>
                  {s.mine && <button type="button" className="ghost icon-btn sm" aria-label={`Delete ${s.name}`} title="Delete"
                    onClick={() => { if (window.confirm(`Delete the scenario “${s.name}”?${s.shared ? " It's shared, so it goes for the whole team." : ""}`)) onDelete(s.id); }}><TrashIcon size={13} /></button>}
                </span>
              </div>
            </article>
          );
        })}
      </div>
    </div>
  );
}
