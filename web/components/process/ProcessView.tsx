"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import AskButton from "@/components/AskButton";
import { errorText } from "@/components/Toaster";
import { programHref } from "@/lib/api";
import { readParam, writeParams } from "@/lib/urlstate";

type Step = {
  program: string; line: number; to: string; from: string | null; code: string;
  saved_to: string | null; saved_at: number | null; also_sets: number[];
};
type Prog = {
  program: string; launches: number | null; domain: string | null; writes: string[]; reads: string[];
  menus: { menu: string; used: number; path: string[] }[];
};
type Chosen = { program: string; line: number; code: string; kind: string; text?: string; screen?: { form: string; control: string; line: number } };
type Flow = {
  process: { key: string; title: string; blurb: string | null; file: string; attr: number; field: string | null };
  states: { code: string; label: string | null }[];
  steps: Step[]; chosen: Chosen[]; programs: Record<string, Prog>; fields: Record<string, string>; domains: Record<string, string>;
  leave: { program: string; line: number; launches: number | null; domain: string | null; archives_to: string[] }[];
};
type Catalog = { key: string; title: string; file: string; attr: number; blurb: string; states: Record<string, string> }[];

const HUE: Record<string, number> = { "1": 135, "2": 42, "3": 12, "4": 208, "5": 262, "6": 322, "7": 172, "8": 70, "9": 228, shared: 30, off: 215 };
const STAGE = ["#3b5bfd", "#d97706", "#7c3aed", "#059669", "#0891b2", "#db2777"];
const compact = (n: number | null | undefined) =>
  n == null ? null : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : String(n);

/** One program's part in one stage: every line where it moves the record into that state. */
type Mover = { p: Prog; steps: Step[]; from: Set<string>; savedTo: Set<string>; also: Set<number> };

// A business process as a board: one column per state of the record, the programs that move it there,
// and what else each of them touches. Read from the code; every card links to its lines.
export default function ProcessView() {
  const [catalog, setCatalog] = useState<Catalog | null>(null);
  const [key, setKey] = useState<string | null>(null);
  const [flow, setFlow] = useState<Flow | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [batch, setBatch] = useState(false);
  const [open, setOpen] = useState<string | null>(null);

  useEffect(() => {
    fetch("/api/processes").then(async (r) => {
      if (!r.ok) throw new Error(r.status === 404 ? "This Atlas API doesn't have processes yet: restart it with `uv run atlas serve`." : await errorText(r));
      const c: Catalog = await r.json();
      setCatalog(c);
      setKey(readParam("p") ?? c[0]?.key ?? null);
    }).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    if (!key) return;
    writeParams({ p: key });
    setFlow(null);
    fetch(`/api/process/${encodeURIComponent(key)}`).then(async (r) => {
      if (!r.ok) throw new Error(await errorText(r));
      setFlow(await r.json());
    }).catch((e) => setError(e instanceof Error ? e.message : String(e)));
  }, [key]);

  const board = useMemo(() => {
    if (!flow) return null;
    const cols = flow.states.map((s) => {
      const by = new Map<string, Mover>();
      for (const st of flow.steps) {
        if (st.to !== s.code) continue;
        const p = flow.programs[st.program];
        const m = by.get(st.program) ?? { p, steps: [], from: new Set<string>(), savedTo: new Set<string>(), also: new Set<number>() };
        m.steps.push(st);
        m.from.add(st.from ?? "new");
        if (st.saved_to) m.savedTo.add(st.saved_to);
        st.also_sets.forEach((a) => m.also.add(a));
        by.set(st.program, m);
      }
      const movers = [...by.values()].sort((a, b) => (b.p.launches ?? -1) - (a.p.launches ?? -1) || a.p.program.localeCompare(b.p.program));
      const onMenu = movers.filter((m) => m.p.menus.length > 0);
      const files = (pick: (p: Prog) => string[]) => {
        const n = new Map<string, number>();
        for (const m of onMenu.length ? onMenu : movers) for (const f of pick(m.p)) n.set(f, (n.get(f) ?? 0) + 1);
        return [...n].sort((a, b) => b[1] - a[1]).slice(0, 8);
      };
      const from = new Set(movers.flatMap((m) => [...m.from]));
      // where records in this state go next, when the code says so (IF XF<2> = "B" THEN XF<2> = "O")
      const next = flow.steps.filter((x) => x.from === s.code && x.to !== s.code);
      return { s, movers, onMenu, batch: movers.length - onMenu.length, writes: files((p) => p.writes), reads: files((p) => p.reads), from, next };
    });
    const menus = new Set(Object.values(flow.programs).flatMap((p) => p.menus.map((m) => m.menu)));
    return { cols, menus: menus.size, programs: Object.keys(flow.programs).length };
  }, [flow]);

  const fieldName = (a: number) => (flow?.fields[String(a)] ? `${flow.fields[String(a)]}` : "");

  return (
    <div className="pr">
      <header className="pr-head">
        <div>
          <div className="tr-eyebrow">Business process</div>
          <h1>{flow?.process.title ?? "Processes"}</h1>
          {flow?.process.blurb && <p className="pr-blurb">{flow.process.blurb}</p>}
          {flow && board && (
            <div className="pr-facts">
              <span>The life of a <Link className="mono" href={`/files/${encodeURIComponent(flow.process.file)}`}>{flow.process.file}</Link> record, told by its status
                field <Link className="mono" href={`/trace?file=${encodeURIComponent(flow.process.file)}&attr=${flow.process.attr}`}>{flow.process.file}&lt;{flow.process.attr}&gt;</Link>
                {flow.process.field ? <> ({flow.process.field})</> : null}</span>
              <span className="pr-dot" /><span><b>{board.programs}</b> programs move it</span>
              <span className="pr-dot" /><span>reached from <b>{board.menus}</b> menus</span>
            </div>
          )}
        </div>
        <div className="pr-tools">
          {catalog && catalog.length > 1 && (
            <select value={key ?? ""} onChange={(e) => setKey(e.target.value)}>
              {catalog.map((c) => <option key={c.key} value={c.key}>{c.title}</option>)}
            </select>
          )}
          <label className="pr-toggle"><input type="checkbox" checked={batch} onChange={(e) => setBatch(e.target.checked)} /> Show batch &amp; one-off code</label>
          {flow && <AskButton question={`Walk me through the ${flow.process.title.toLowerCase()} process: how a ${flow.process.file} record moves through ${flow.states.map((s) => s.code).join(", ")}, which programs do each step, and what else they update.`} />}
        </div>
      </header>

      {error && <div className="tr-error">{error}</div>}
      {!flow && !error && <div className="tr-loading">Reading the process from the code…</div>}

      {flow && flow.chosen.length > 0 && (
        <div className="pr-chosen">
          <div className="pr-chosen-h"><b>Set on screen</b><span>these programs set the status to whatever the user picks, so they can move a {flow.process.file.toLowerCase()} into any state</span></div>
          {flow.chosen.map((c) => {
            const p = flow.programs[c.program];
            return (
              <div key={`${c.program}:${c.line}`} className="pr-chosen-row">
                <Link className="mono strong" href={programHref(c.program, c.line)}>{c.program}:{c.line}</Link>
                {c.screen ? <span className="tr-tag screen"><i />Screen <b>{c.screen.form} › {c.screen.control}</b> <Link className="mono" href={programHref(c.program, c.screen.line)}>:{c.screen.line}</Link></span>
                  : <span className="tr-tag computed"><i /><span className="mono">{c.text}</span></span>}
                {p?.menus[0] && <span className="tr-sub">menu <b className="mono">{p.menus[0].menu}</b>{p.menus[0].path.length > 1 ? <> · via {p.menus[0].path.slice(0, -1).join(" › ")}</> : null}</span>}
                {p?.launches ? <span className="tr-pill">{compact(p.launches)}</span> : null}
              </div>
            );
          })}
        </div>
      )}

      {flow && board && (
        <div className="pr-scroll">
          <div className="pr-board" style={{ gridTemplateColumns: `repeat(${board.cols.length + 1}, minmax(250px, 1fr))` }}>
            {board.cols.map((c, i) => (
                <section key={c.s.code} className="pr-col" style={{ ["--stage" as string]: STAGE[i % STAGE.length] }}>
                  <div className="pr-stage">
                    <div className="pr-code">{c.s.code}</div>
                    <div className="pr-stage-t">
                      <b>{c.s.label ?? `State ${c.s.code}`}</b>
                      <span>{c.movers.length} program{c.movers.length === 1 ? "" : "s"} set it{c.batch && !batch ? ` · ${c.onMenu.length} on a menu` : ""}</span>
                    </div>
                    <div className="pr-arrow" aria-hidden />
                  </div>
                  <div className="pr-from">
                    {[...c.from].map((f) => (
                      <span key={f} className={`pr-chip ${f === "new" ? "new" : ""}`}>{f === "new" ? "from a new or any record" : `from ${f} · ${flow.states.find((s) => s.code === f)?.label ?? f}`}</span>
                    ))}
                  </div>
                  <div className="pr-cards">
                    {(batch ? c.movers : c.onMenu).map((m) => {
                      const id = `${c.s.code}:${m.p.program}`, on = open === id;
                      const hist = [...m.savedTo].filter((f) => f !== flow.process.file);
                      return (
                        <div key={m.p.program} className={`pr-card${on ? " open" : ""}`} style={{ ["--hue" as string]: HUE[m.p.domain ?? "off"] ?? 215 }}>
                          <button className="pr-card-h" onClick={() => setOpen(on ? null : id)}>
                            <span className="pr-name mono">{m.p.program}</span>
                            {m.p.launches ? <span className="tr-pill">{compact(m.p.launches)}</span> : <span className="tr-pill dim">batch</span>}
                          </button>
                          <div className="tr-sub">{m.p.menus[0] ? <>menu <b className="mono">{m.p.menus[0].menu}</b>{m.p.menus[0].path.length > 1 ? <> · via {m.p.menus[0].path.slice(0, -1).join(" › ")}</> : null}</> : "no menu reaches it"}</div>
                          {hist.length > 0 && <div className="pr-note">saved to <b className="mono">{hist.join(", ")}</b> (history), not the live record</div>}
                          {on && (
                            <div className="pr-more">
                              <div className="pr-sec">Where</div>
                              {m.steps.map((s) => (
                                <Link key={s.line} className="pr-line" href={programHref(s.program, s.line)}>
                                  <span className="mono">:{s.line}</span><code>{s.code}</code>
                                </Link>
                              ))}
                              {m.also.size > 0 && <>
                                <div className="pr-sec">Also sets on the {flow.process.file}</div>
                                <div className="pr-chips">
                                  {[...m.also].sort((a, b) => a - b).map((a) => (
                                    <Link key={a} className="pr-chip field" href={`/trace?file=${encodeURIComponent(flow.process.file)}&attr=${a}`} title="Trace this field">
                                      <span className="mono">&lt;{a}&gt;</span>{fieldName(a) && <span>{fieldName(a)}</span>}
                                    </Link>
                                  ))}
                                </div>
                              </>}
                              {m.p.writes.length > 0 && <><div className="pr-sec">Writes</div><Files list={m.p.writes} kind="w" /></>}
                              {m.p.reads.length > 0 && <><div className="pr-sec">Reads</div><Files list={m.p.reads} kind="r" /></>}
                            </div>
                          )}
                        </div>
                      );
                    })}
                    {!batch && c.batch > 0 && <button className="pr-batch" onClick={() => setBatch(true)}>+ {c.batch} batch or one-off program{c.batch === 1 ? "" : "s"}</button>}
                    {c.movers.length === 0 && <div className="tr-none">No program sets it to a fixed {c.s.code} here{flow.chosen.length ? "; the screen above can" : ""}.</div>}
                  </div>
                  {c.next.length > 0 && (
                    <div className="pr-next">
                      <div className="pr-sec">Moves on to</div>
                      {c.next.map((x) => (
                        <Link key={`${x.program}:${x.line}`} className="pr-next-row" href={programHref(x.program, x.line)}>
                          <span className="pr-next-to">→ {x.to}</span><span>{flow.states.find((s) => s.code === x.to)?.label ?? ""}</span>
                          <span className="mono tr-sub">{x.program}:{x.line}</span>
                        </Link>
                      ))}
                    </div>
                  )}
                  {(c.writes.length > 0 || c.reads.length > 0) && (
                    <div className="pr-touch">
                      <div className="pr-sec">This step also writes</div>
                      <Files list={c.writes.map(([f]) => f)} kind="w" counts={new Map(c.writes)} />
                      <div className="pr-sec">and reads</div>
                      <Files list={c.reads.map(([f]) => f)} kind="r" counts={new Map(c.reads)} />
                    </div>
                  )}
                </section>
            ))}

            <section className="pr-col" style={{ ["--stage" as string]: "#475569" }}>
              <div className="pr-stage">
                <div className="pr-code">✕</div>
                <div className="pr-stage-t"><b>Leaves {flow.process.file}</b><span>{flow.leave.length} program{flow.leave.length === 1 ? "" : "s"} delete records</span></div>
              </div>
              <div className="pr-from"><span className="pr-chip new">archived, then deleted from the live file</span></div>
              <div className="pr-cards">
                {flow.leave.filter((l) => batch || l.launches).map((l) => (
                  <div key={l.program} className="pr-card" style={{ ["--hue" as string]: HUE[l.domain ?? "off"] ?? 215 }}>
                    <div className="pr-card-h static">
                      <Link className="pr-name mono" href={programHref(l.program, l.line)}>{l.program}</Link>
                      {l.launches ? <span className="tr-pill">{compact(l.launches)}</span> : <span className="tr-pill dim">batch</span>}
                    </div>
                    {l.archives_to.length > 0 ? <><div className="pr-sec">Keeps a copy in</div><Files list={l.archives_to} kind="w" /></> : <div className="tr-sub">deletes without keeping a copy</div>}
                  </div>
                ))}
                {!batch && flow.leave.some((l) => !l.launches) && (
                  <button className="pr-batch" onClick={() => setBatch(true)}>+ {flow.leave.filter((l) => !l.launches).length} batch or one-off</button>
                )}
              </div>
            </section>
          </div>
        </div>
      )}
      {flow && <p className="pr-foot">Each state is a literal the code assigns to {flow.process.file}&lt;{flow.process.attr}&gt;; &ldquo;from&rdquo; is the condition on that line or just above it. A step saved to a history file records a leg of the journey rather than changing the live record.</p>}
    </div>
  );
}

function Files({ list, kind, counts }: { list: string[]; kind: "w" | "r"; counts?: Map<string, number> }) {
  if (!list.length) return <div className="tr-sub">none</div>;
  return (
    <div className="pr-chips">
      {list.map((f) => (
        <Link key={f} className={`pr-chip file ${kind}`} href={`/files/${encodeURIComponent(f)}`}>
          <span className="mono">{f}</span>{counts && (counts.get(f) ?? 0) > 1 ? <span className="n">×{counts.get(f)}</span> : null}
        </Link>
      ))}
    </div>
  );
}
