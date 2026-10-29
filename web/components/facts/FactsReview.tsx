"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { errorText, toast } from "@/components/Toaster";
import { ago, programHref } from "@/lib/api";

type Cite = { src: string; ref: string; line: number; line_text: string | null; now_text: string | null; changed: boolean; note: string };
type Fact = { id: string; text: string; kind: string; scope: string | null; status: string; rationale: string | null;
  proposed_by: string; accepted_by: string | null; stale_reason: string | null; created_at: string; updated_at: string;
  cites: Cite[]; home: string | null };
type Tab = "stale" | "proposed" | "accepted";

const TABS: [Tab, string, string][] = [
  ["stale", "Went stale", "The code these cite has changed since they were written. Check the line: if the fact still holds, re-cite it (it goes back for review); if not, retire it."],
  ["proposed", "Waiting for review", "Proposed by Ask Atlas or a person. Read the cited lines; accept what's true, retire what isn't. Accepted facts are stated by Ask Atlas without caveats."],
  ["accepted", "Confirmed", "Reviewed by a named person. They go stale by themselves if the code they cite changes."],
];

// The facts review queue: what Atlas has learned, waiting for a named person to confirm.
export default function FactsReview({ admin, initial }: { admin: boolean; initial: Tab }) {
  const [tab, setTab] = useState<Tab>(initial);
  const [data, setData] = useState<Record<Tab, Fact[]> | null>(null);
  const [busy, setBusy] = useState("");

  async function load() {
    const [r, a] = await Promise.all([fetch("/api/facts/review"), fetch("/api/facts?status=accepted")]);
    if (!r.ok) { toast.error("Couldn't load facts", await errorText(r)); return; }
    const d = await r.json();
    const acc = a.ok ? (await a.json()).facts : [];
    setData({ stale: d.stale, proposed: d.proposed, accepted: acc });
  }
  useEffect(() => { load(); }, []);
  useEffect(() => {
    try { const u = new URL(window.location.href); u.searchParams.set("tab", tab); window.history.replaceState(null, "", u); } catch { /* fine */ }
  }, [tab]);

  async function act(f: Fact, action: "accept" | "recite" | "retire") {
    let reason = "";
    if (action === "retire") {
      reason = window.prompt(`Why retire ${f.id}? (e.g. "no longer true since the change in LG.XFER.MAINT")`)?.trim() ?? "";
      if (!reason) return;
    }
    setBusy(f.id + action);
    const r = await fetch(`/api/facts/${f.id}/${action}`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ reason }),
    }).catch(() => null);
    setBusy("");
    if (!r?.ok) { toast.error(`Couldn't ${action} ${f.id}`, await errorText(r)); return; }
    toast.success({ accept: `${f.id} confirmed`, recite: `${f.id} re-cited: it's back in review`, retire: `${f.id} retired` }[action]);
    load();
  }

  if (!data) return <section className="card"><div className="card-body sub">Loading…</div></section>;
  const list = data[tab];
  const help = TABS.find((t) => t[0] === tab)![2];
  return (
    <div className="stack">
      <nav className="tabs">
        {TABS.map(([t, label]) => (
          <button key={t} type="button" className={`tab-btn ${tab === t ? "active" : ""}`} onClick={() => setTab(t)}>
            {label} <span className="tab-count">{data[t].length}</span>
          </button>
        ))}
      </nav>
      <p className="sub">{help}{!admin && tab !== "accepted" && " Only admins confirm or retire facts."}</p>
      {list.length === 0 && <section className="card"><div className="card-body empty">Nothing here.</div></section>}
      {list.map((f) => (
        <article key={f.id} className="card fr-card" id={f.id}>
          <div className="card-head">
            <span className="mono fr-id">{f.id}</span>
            <span className="badge">{f.kind}</span>
            {f.scope && (f.home ? <Link href={f.home} className="sub mono">{f.scope}</Link> : <span className="sub mono">{f.scope}</span>)}
            <span className="spacer" />
            <span className="sub">{f.status === "accepted" ? `confirmed by ${(f.accepted_by ?? "").split(" <")[0]}` : `proposed by ${f.proposed_by.split(" <")[0]}`} · {ago(f.updated_at)}</span>
          </div>
          <div className="card-body stack">
            <p className="fr-text">{f.text}</p>
            {f.rationale && <p className="sub">Why: {f.rationale}</p>}
            <div className="fr-cites">
              {f.cites.map((c, i) => (
                <div key={i} className={`fr-cite ${c.changed ? "changed" : ""}`}>
                  <Link className="mono fr-ref" href={c.src === "git" ? programHref(c.ref, c.line) : programHref(c.ref, c.line, c.src)}>
                    {c.src !== "git" && <span className="badge amber">{c.src}</span>} {c.ref}:{c.line}
                  </Link>
                  {c.changed ? (
                    <div className="fr-diff">
                      <code className="fr-was" title="As cited">− {c.line_text?.trim()}</code>
                      <code className="fr-now" title="In git now">+ {c.now_text?.trim()}</code>
                    </div>
                  ) : <code className="fr-line">{c.line_text?.trim()}</code>}
                </div>
              ))}
            </div>
            {admin && f.status !== "accepted" && (
              <div className="fr-actions">
                {f.status === "stale"
                  ? <button className="primary sm" disabled={!!busy} onClick={() => act(f, "recite")} title="It still holds: point it at the lines as they read now and send it back for review">Still true: re-cite</button>
                  : <button className="primary sm" disabled={!!busy} onClick={() => act(f, "accept")} title="Confirm it under your name">Confirm</button>}
                <button className="sm ghost" disabled={!!busy} onClick={() => act(f, "retire")}>Retire</button>
              </div>
            )}
          </div>
        </article>
      ))}
    </div>
  );
}
