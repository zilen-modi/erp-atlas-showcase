"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import JobProgress from "@/components/JobProgress";
import { CloseIcon, SyncIcon } from "@/components/Icons";
import { errorText, toast } from "@/components/Toaster";
import { type Job, pollJob, reportJob, startJob } from "@/lib/jobs";
import { readParam, writeParams } from "@/lib/urlstate";
import type { Branch, Lane, Pick, Transfer } from "./scene";

type Snapshot = {
  at: string; days: number; branches: Branch[]; lanes: Lane[]; transit: Transfer[]; open_count: number;
  kpis: Record<string, number>; seconds: number; organisation?: string;
};

function ago(iso: string) {
  const m = Math.round((Date.now() - new Date(iso).getTime()) / 60000);
  return m < 1 ? "just now" : m < 60 ? `${m} min ago` : m < 1440 ? `${Math.round(m / 60)} h ago` : `${Math.round(m / 1440)} d ago`;
}
function fmt(d?: string | null) {
  if (!d) return "—";
  const x = new Date(d + "T00:00:00");
  return x.toLocaleDateString("en-GB", { day: "numeric", month: "short", year: x.getFullYear() === new Date().getFullYear() ? undefined : "2-digit" });
}

// The branch network on TEST: towers per branch, arcs per lane, a pulse per transfer in transit.
export default function NetworkView() {
  const host = useRef<HTMLDivElement>(null);
  const sceneRef = useRef<any>(null);
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [empty, setEmpty] = useState(false);
  const [job, setJob] = useState<Job | null>(null);
  const [days, setDays] = useState(30);
  const [showOpen, setShowOpen] = useState(true);
  const [pick, setPick] = useState<Pick>(null);
  const [hover, setHover] = useState<string | null>(null);
  // details are tagged with the selection they belong to: a panel never reads another selection's data
  const [loaded, setLoaded] = useState<{ key: string; data: any } | null>(null);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [sceneReady, setSceneReady] = useState(false);

  const names = useMemo(() => new Map((snap?.branches ?? []).map((b) => [b.id, b])), [snap]);
  const label = (id: string) => { const b = names.get(id); return b ? `${b.city || "Branch"} #${id}` : `#${id}`; };

  const load = useCallback(async (d = days) => {
    const r = await fetch(`/api/network?days=${d}`).catch(() => null);
    if (!r?.ok) { toast.error("Couldn't load the network", await errorText(r)); return; }
    const v = await r.json();
    if (v.empty) { setEmpty(true); setSnap(null); } else { setEmpty(false); setSnap(v); }
  }, [days]);

  const refresh = useCallback(async (d = days) => {
    const j = await startJob("/api/jobs/network", { days: d }, "Network refresh");
    if (j) setJob(j);
  }, [days]);

  useEffect(() => {
    const d = Number(readParam("days")) || 30;
    setDays(d);
    const sel = readParam("branch");
    if (sel) setPick({ kind: "branch", id: sel });
    load(d);
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => { if (empty && !job) refresh(); }, [empty]);  // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!job || job.state !== "running") return;
    const t = setInterval(async () => {
      const j = await pollJob(job.id);
      if (!j) return;
      setJob(j);
      if (j.state !== "running") { reportJob(j, "Network refresh", "Network refreshed from TEST"); load(); }
    }, 1500);
    return () => clearInterval(t);
  }, [job, load]);

  // the 3D scene (three.js is loaded only on this page)
  useEffect(() => {
    let disposed = false, onResize: (() => void) | null = null;
    import("./scene").then(({ NetworkScene }) => {
      if (disposed || !host.current) return;
      const s = new NetworkScene(host.current);
      s.onPick = (p) => setPick(p);
      s.onHover = (id) => setHover(id);
      sceneRef.current = s;
      onResize = () => s.resize();
      window.addEventListener("resize", onResize);
      setSceneReady(true);              // the data may have arrived first: the build effect below runs now
    });
    return () => { disposed = true; if (onResize) window.removeEventListener("resize", onResize); sceneRef.current?.dispose(); sceneRef.current = null; };
  }, []);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    if (snap && sceneReady && sceneRef.current) {
      sceneRef.current.build(snap.branches, snap.lanes, snap.transit, { maxLanes: 160, showOpen, organisation: snap.organisation });
      sceneRef.current.select(pick);
    }
  }, [snap, showOpen, sceneReady]);  // eslint-disable-line react-hooks/exhaustive-deps

  // selection: highlight in the scene, keep it in the URL, fetch live details
  useEffect(() => {
    sceneRef.current?.select(pick);
    writeParams({ branch: pick?.kind === "branch" ? pick.id : null, days: days !== 30 ? String(days) : null });
    if (!pick || pick.kind === "lane") return;
    let stale = false;
    setLoadingDetail(true);
    const url = pick.kind === "branch" ? `/api/network/branch/${pick.id}?days=${days}` : `/api/network/transfer/${encodeURIComponent(pick.id)}`;
    const key = `${pick.kind}:${pick.id}`;
    fetch(url).then(async (r) => {
      if (stale) return;
      if (!r.ok) { toast.error("Couldn't load details", await errorText(r)); return; }
      setLoaded({ key, data: await r.json() });
    }).catch(() => {}).finally(() => { if (!stale) setLoadingDetail(false); });
    return () => { stale = true; };
  }, [pick, days]);

  const k = snap?.kpis;
  const detail = pick && pick.kind !== "lane" && loaded?.key === `${pick.kind}:${pick.id}` ? loaded.data : null;
  const running = job?.state === "running";
  const selectedLane = pick?.kind === "lane" ? snap?.lanes.find((l) => l.from === pick.from && l.to === pick.to) : null;
  const hoverB = hover ? names.get(hover) : null;

  return (
    <div className="net">
      <div className="net-canvas" ref={host} />

      <header className="net-top">
        <div className="net-title">
          <h1>Branch network</h1>
          <div className="sub">
            {snap ? <>TEST · transfers ordered in the last {snap.days} days · refreshed {ago(snap.at)}</> : "Reading TEST…"}
          </div>
        </div>
        {k && (
          <div className="net-kpis">
            <Kpi label="Branches" value={k.branches} note={`${k.hubs} hubs · ${k.cds} CD`} />
            <Kpi label="In transit" value={k.in_transit} tone="ok" note="shipped, not received" />
            <Kpi label="Open" value={k.open} note={`${k.ordered_today} ordered today`} />
            <Kpi label="Past required date" value={k.overdue} tone="bad" note="open or in transit" />
            <Kpi label="Active lanes" value={k.lanes} note="branch → branch" />
          </div>
        )}
        <div className="net-actions">
          <select value={days} onChange={(e) => { const d = Number(e.target.value); setDays(d); load(d).then(() => refresh(d)); }} title="Open transfers ordered in the last…">
            {[7, 30, 90].map((d) => <option key={d} value={d}>{d} days</option>)}
          </select>
          <button className="sm" onClick={() => refresh()} disabled={running}><SyncIcon size={14} /> Refresh</button>
        </div>
      </header>

      {running && job && (
        <div className="net-job"><JobProgress job={job} title="Reading the network from TEST" expectedKind="network"
          hint="Branches, transfers in transit and open transfers, read-only through the python layer. About 30 seconds." /></div>
      )}
      {!snap && !running && empty && <div className="net-empty">No network snapshot yet. <button className="sm primary" onClick={() => refresh()}>Read it from TEST</button></div>}

      {snap && (
        <aside className="net-left">
          <section className="net-card">
            <div className="net-card-h"><b>Busiest lanes</b><span className="sub">open + in transit</span></div>
            <div className="net-list">
              {snap.lanes.slice(0, 10).map((l) => (
                <button key={l.from + ">" + l.to} className={`net-row ${selectedLane === l ? "on" : ""}`} onClick={() => setPick({ kind: "lane", from: l.from, to: l.to })}>
                  <span className="net-lane"><span>{label(l.from)}</span><span className="faint">→</span><span>{label(l.to)}</span></span>
                  <span className="net-nums">
                    <b>{l.open + l.transit}</b>
                    {l.overdue > 0 && <span className="net-bad" title="past required date">{l.overdue}</span>}
                  </span>
                </button>
              ))}
            </div>
          </section>
          <section className="net-card">
            <div className="net-card-h"><b>In transit</b><span className="sub">{snap.transit.length} transfers</span></div>
            <div className="net-list tall">
              {snap.transit.slice(0, 80).map((t) => (
                <button key={t.id} className={`net-row ${pick?.kind === "transfer" && pick.id === t.id ? "on" : ""}`} onClick={() => setPick({ kind: "transfer", id: t.id })}>
                  <span className={`net-dot ${t.overdue ? "bad" : "ok"}`} />
                  <span className="net-lane"><span className="mono">{t.id}</span><span className="sub">{label(t.from)} → {label(t.to)}</span></span>
                  <span className="sub nowrap">{t.required ? `due ${fmt(t.required)}` : ""}</span>
                </button>
              ))}
            </div>
          </section>
        </aside>
      )}

      {pick && (
        <aside className="net-right">
          <section className="net-card">
            <button className="ghost icon-btn sm net-close" aria-label="Close" onClick={() => setPick(null)}><CloseIcon size={14} /></button>
            {pick.kind === "branch" && <BranchPanel b={names.get(pick.id)} detail={detail} loading={loadingDetail} label={label} onPick={setPick} />}
            {pick.kind === "lane" && selectedLane && <LanePanel l={selectedLane} label={label} transit={snap?.transit ?? []} onPick={setPick} />}
            {pick.kind === "transfer" && <TransferPanel id={pick.id} t={snap?.transit.find((x) => x.id === pick.id)} detail={detail} loading={loadingDetail} label={label} onPick={setPick} />}
          </section>
        </aside>
      )}

      {hoverB && (!pick || pick.kind !== "branch" || pick.id !== hoverB.id) && (
        <div className="net-hover">
          <b>{hoverB.city || "Branch"}</b> <span className="mono">#{hoverB.id}</span> · {hoverB.state}{hoverB.cd ? " · CD" : hoverB.hub ? ` · hub for ${hoverB.children}` : ""}
          <div className="sub">out {hoverB.out_open + hoverB.out_transit} · in {hoverB.in_open + hoverB.in_transit}{hoverB.overdue_in ? ` · ${hoverB.overdue_in} late inbound` : ""}</div>
        </div>
      )}

      <footer className="net-legend">
        <span><i className="sw cd" /> Central Distribution</span>
        <span><i className="sw hub" /> Regional hub</span>
        <span><i className="sw br" /> Branch</span>
        <span><i className="sw truck" /> Truck in transit</span>
        <span><i className="sw late" /> Past its required date</span>
        <span><i className="pinmark" /> Most late inbound</span>
        <span className="sub">Bigger warehouse = more activity · pallets = work waiting to ship</span>
        <label className="row" style={{ gap: 6, cursor: "pointer" }}>
          <input type="checkbox" checked={showOpen} onChange={(e) => setShowOpen(e.target.checked)} style={{ width: "auto", height: "auto" }} /> Open lanes
        </label>
      </footer>
      <div className="net-cam">
        <button className="sm" onClick={() => sceneRef.current?.zoom(0.8)} aria-label="Zoom in">+</button>
        <button className="sm" onClick={() => sceneRef.current?.zoom(1.25)} aria-label="Zoom out">−</button>
        <button className="sm" onClick={() => { setPick(null); sceneRef.current?.home(); }} aria-label="Reset view" title="Reset view">⌂</button>
      </div>
    </div>
  );
}

function Kpi({ label, value, note, tone }: { label: string; value: number; note?: string; tone?: "ok" | "bad" }) {
  return (
    <div className={`net-kpi ${tone ?? ""}`}>
      <div className="l">{label}</div>
      <div className="v">{value.toLocaleString()}</div>
      {note && <div className="n">{note}</div>}
    </div>
  );
}

function TList({ title, rows, label, onPick, empty }: { title: string; rows: Transfer[]; label: (id: string) => string; onPick: (p: Pick) => void; empty: string }) {
  return (
    <div className="net-sec">
      <div className="net-sec-h">{title} <span className="faint">{rows.length}</span></div>
      {rows.length === 0 ? <div className="sub">{empty}</div> : (
        <div className="net-list">
          {rows.slice(0, 8).map((t) => (
            <button key={t.id} className="net-row" onClick={() => onPick({ kind: "transfer", id: t.id })}>
              <span className={`net-dot ${t.overdue ? "bad" : t.mode === "S" ? "ok" : ""}`} />
              <span className="net-lane"><span className="mono">{t.id}</span><span className="sub">{label(t.from)} → {label(t.to)}</span></span>
              <span className="sub nowrap">{t.required ? fmt(t.required) : ""}</span>
            </button>
          ))}
          {rows.length > 8 && <div className="sub" style={{ padding: "4px 8px" }}>+{rows.length - 8} more</div>}
        </div>
      )}
    </div>
  );
}

function BranchPanel({ b, detail, loading, label, onPick }: { b?: Branch; detail: any; loading: boolean; label: (id: string) => string; onPick: (p: Pick) => void }) {
  if (!b) return <div className="sub">Unknown branch.</div>;
  const role = b.cd ? "Central Distribution" : b.hub ? `Regional hub · ${b.children} branches report here` : "Branch";
  return (
    <>
      <div className="net-eyebrow">{role}</div>
      <h2 className="net-h2">{b.city || "Branch"} <span className="mono faint">#{b.id}</span></h2>
      <div className="sub">{b.state}{b.mother !== b.id && <> · reports to <button className="link" onClick={() => onPick({ kind: "branch", id: b.mother })}>{label(b.mother)}</button></>}</div>
      <div className="net-stats">
        <div><span>Outbound</span><b>{b.out_open + b.out_transit}</b><em>{b.out_transit} in transit</em></div>
        <div><span>Inbound</span><b>{b.in_open + b.in_transit}</b><em>{b.in_transit} in transit</em></div>
        <div className={b.overdue_in ? "bad" : ""}><span>Late inbound</span><b>{b.overdue_in}</b><em>past required date</em></div>
      </div>
      {loading && !detail && <div className="sub"><span className="spinner" style={{ display: "inline-block" }} /> Reading this branch's transfers from TEST…</div>}
      {detail && (
        <>
          <TList title="Arriving (in transit)" rows={detail.inbound?.transit ?? []} label={label} onPick={onPick} empty="Nothing on the way." />
          <TList title="To ship (open, outbound)" rows={detail.outbound?.open ?? []} label={label} onPick={onPick} empty="Nothing waiting to ship." />
          <TList title="Ordered from other branches (open, inbound)" rows={detail.inbound?.open ?? []} label={label} onPick={onPick} empty="None." />
          {(detail.lanes ?? []).length > 0 && (
            <div className="net-sec">
              <div className="net-sec-h">Lanes</div>
              <div className="net-list">
                {detail.lanes.slice(0, 6).map((l: Lane) => (
                  <button key={l.from + l.to} className="net-row" onClick={() => onPick({ kind: "lane", from: l.from, to: l.to })}>
                    <span className="net-lane"><span>{label(l.from)} → {label(l.to)}</span><span className="sub">{l.vias.join(", ")}</span></span>
                    <span className="net-nums"><b>{l.open + l.transit}</b>{l.overdue > 0 && <span className="net-bad">{l.overdue}</span>}</span>
                  </button>
                ))}
              </div>
            </div>
          )}
        </>
      )}
      <div className="net-links"><Link href={`/test-data?file=TRANSFER`}>Find test transfers</Link><Link href="/files/BRANCH">BRANCH file</Link></div>
    </>
  );
}

function LanePanel({ l, label, transit, onPick }: { l: Lane; label: (id: string) => string; transit: Transfer[]; onPick: (p: Pick) => void }) {
  const moving = transit.filter((t) => t.from === l.from && t.to === l.to);
  return (
    <>
      <div className="net-eyebrow">Lane</div>
      <h2 className="net-h2">{label(l.from)} <span className="faint">→</span> {label(l.to)}</h2>
      <div className="sub">{l.vias.length ? `Usually ${l.vias.join(", ")}` : "No ship-via recorded"}</div>
      <div className="net-stats">
        <div><span>Open</span><b>{l.open}</b><em>ordered, not shipped</em></div>
        <div><span>In transit</span><b>{l.transit}</b><em>shipped</em></div>
        <div className={l.overdue ? "bad" : ""}><span>Past due</span><b>{l.overdue}</b><em>required date passed</em></div>
      </div>
      <TList title="In transit on this lane" rows={moving} label={label} onPick={onPick} empty="Nothing in transit right now." />
      <div className="net-links">
        <button className="link" onClick={() => onPick({ kind: "branch", id: l.from })}>{label(l.from)}</button>
        <button className="link" onClick={() => onPick({ kind: "branch", id: l.to })}>{label(l.to)}</button>
      </div>
    </>
  );
}

function TransferPanel({ id, t, detail, loading, label, onPick }: { id: string; t?: Transfer; detail: any; loading: boolean; label: (id: string) => string; onPick: (p: Pick) => void }) {
  const d = detail ?? {};
  const from = d.from ?? t?.from, to = d.to ?? t?.to;
  const today = new Date().toISOString().slice(0, 10);
  const steps = [
    { name: "Ordered", date: d.ordered ?? t?.ordered, done: true },
    { name: "Required", date: d.required ?? t?.required, done: !!(d.required ?? t?.required) && (d.required ?? t?.required) <= today, due: true },
    { name: "Shipped", date: d.shipped, done: (d.mode ?? t?.mode) === "S" || (d.mode ?? t?.mode) === "R" },
    { name: "Received", date: d.received, done: (d.mode ?? t?.mode) === "R" },
  ];
  return (
    <>
      <div className="net-eyebrow">Transfer · {(d.mode ?? t?.mode) === "S" ? "in transit" : (d.mode ?? t?.mode) === "O" ? "open" : d.mode ?? t?.mode ?? ""}</div>
      <h2 className="net-h2 mono">{id}</h2>
      {from && to && <div className="sub"><button className="link" onClick={() => onPick({ kind: "branch", id: from })}>{label(from)}</button> → <button className="link" onClick={() => onPick({ kind: "branch", id: to })}>{label(to)}</button>{(d.via ?? t?.via) && ` · ${d.via ?? t?.via}`}</div>}
      <ol className="net-journey">
        {steps.map((s) => (
          <li key={s.name} className={`${s.done ? "done" : ""} ${s.due && t?.overdue ? "late" : ""}`}>
            <span className="pin" /><b>{s.name}</b><span className="sub">{fmt(s.date)}</span>
          </li>
        ))}
      </ol>
      {loading && !detail && <div className="sub"><span className="spinner" style={{ display: "inline-block" }} /> Reading the transfer and its log…</div>}
      {detail && (
        <>
          <div className="sub" style={{ marginBottom: 6 }}>{d.lines} product line{d.lines === 1 ? "" : "s"}{d.writer && ` · written by ${d.writer}`}</div>
          {(d.events ?? []).length > 0 && (
            <div className="net-sec">
              <div className="net-sec-h">History <span className="faint">TRANSFER-LOG</span></div>
              <div className="net-events">
                {d.events.map((e: any, i: number) => (
                  <div key={i}><span className="mono">{fmt(e.date)} {e.time}</span><b>{e.reason || "—"}</b><span className="sub">{e.mode && `mode ${e.mode} · `}{e.user}{e.program && ` · ${e.program}`}</span></div>
                ))}
              </div>
            </div>
          )}
        </>
      )}
      <div className="net-links">
        <Link href={`/compare`}>Compare this transfer</Link>
        <Link href={`/screen/LG.XFER.MAINT`}>Transfer screen</Link>
      </div>
    </>
  );
}
