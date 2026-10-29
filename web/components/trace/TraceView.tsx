"use client";

import Link from "next/link";
import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import AskButton from "@/components/AskButton";
import { SearchIcon } from "@/components/Icons";
import { errorText } from "@/components/Toaster";
import { programHref } from "@/lib/api";
import { readParam, writeParams } from "@/lib/urlstate";

type Field = { file: string; attr: number };
type SetSite = {
  line: number; kind: "screen" | "system" | "clear" | "copy" | "computed" | "direct"; text?: string; code?: string;
  converted?: boolean; screen?: { form: string; control: string; line: number }; from?: Field & { var: string };
};
type Source = {
  program: string; launches: number | null; domain: string | null; no_menu: boolean; saved: number[]; sets: SetSite[];
  menus: { menu: string; used: number; path: string[] }[];
};
type Reader = {
  program: string; launches: number | null; domain: string | null; lines: number[];
  copies: { line: number; code: string; to: Field & { var: string } }[]; shown: { line: number; form: string; control: string }[];
};
type Journey = {
  field: Field & { names: string[]; facts: { id: string; status: string; text: string }[] };
  sources: Source[]; readers: Reader[]; counts: { writers: number; readers: number; readers_shown: number };
  domains: Record<string, string>;
};

const HUE: Record<string, number> = { "1": 135, "2": 42, "3": 12, "4": 208, "5": 262, "6": 322, "7": 172, "8": 70, "9": 228, shared: 30, off: 215 };
const key = (f: Field) => `${f.file}<${f.attr}>`;
const compact = (n: number | null | undefined) =>
  n == null ? null : n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : String(n);

type Node = { id: string; lane: 0 | 1 | 2 | 3 | 4 };
type Edge = { from: string; to: string; kind: "enter" | "set" | "read" | "copy" };

// A field's journey: how users get to the code that sets it, where the value comes from, where it is saved,
// who reads it, and where it is copied on to. Every step links to its line.
export default function TraceView() {
  const [field, setField] = useState<Field | null>(null);
  const [data, setData] = useState<Journey | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [allReaders, setAllReaders] = useState(false);

  // each field you walk to is a step in the browser history, so Back retraces the chain
  const fromUrl = useRef(true);
  useEffect(() => {
    const read = () => {
      const f = readParam("file"), a = Number(readParam("attr"));
      fromUrl.current = true;
      setField(f && a > 0 ? { file: f.toUpperCase(), attr: a } : null);
    };
    read();
    window.addEventListener("popstate", read);
    return () => window.removeEventListener("popstate", read);
  }, []);

  useEffect(() => {
    if (!field) return;
    if (fromUrl.current) { fromUrl.current = false; writeParams({ file: field.file, attr: String(field.attr) }); }
    else window.history.pushState(window.history.state, "", `${window.location.pathname}?file=${encodeURIComponent(field.file)}&attr=${field.attr}`);
    setLoading(true); setError(null); setAllReaders(false);
    let live = true;
    fetch(`/api/trace/field/${encodeURIComponent(field.file)}/${field.attr}?track=true`)
      .then(async (r) => { if (!r.ok) throw new Error(r.status === 404 ? "This Atlas API doesn't have Trace yet: restart it with `uv run atlas serve`." : await errorText(r)); return r.json(); })
      .then((j) => { if (live) setData(j); })
      .catch((e) => { if (live) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (live) setLoading(false); });
    return () => { live = false; };
  }, [field]);

  if (!field) return <Start onPick={setField} />;
  return (
    <div className="tr">
      <header className="tr-head">
        <div className="tr-title">
          <div className="tr-eyebrow">Field journey</div>
          <h1 className="mono">{key(field)}</h1>
          {data && (
            <div className="tr-names">
              {data.field.names.length ? data.field.names.map((n) => <span key={n} className="tr-name">{n}</span>) : <span className="tr-name dim">not named in DICT</span>}
            </div>
          )}
        </div>
        <div className="tr-tools">
          <Picker onPick={setField} compact />
          <Link className="btn sm" href={`/field/${encodeURIComponent(field.file)}/${field.attr}`}>Table view</Link>
          <AskButton question={`Walk me through ${key(field)}: where users enter it, how each program sets it, where it is saved, and who depends on it.`} />
        </div>
      </header>

      {error && <div className="tr-error">{error}</div>}
      {loading && !data && <div className="tr-loading">Following {key(field)} through the code…</div>}
      {data && key(data.field) === key(field) && (
        <Board data={data} loading={loading} allReaders={allReaders} onAllReaders={() => setAllReaders(true)} onTrace={setField} />
      )}
    </div>
  );
}

function Summary({ data, menus, downstream }: { data: Journey; menus: number; downstream: number }) {
  const batch = data.sources.filter((s) => s.no_menu).length;
  return (
    <p className="tr-summary">
      Set by <b>{data.counts.writers}</b> program{data.counts.writers === 1 ? "" : "s"}
      {menus > 0 && <> reached from <b>{menus}</b> menu{menus === 1 ? "" : "s"}</>}
      {batch > 0 && <>, <b>{batch}</b> with no menu at all</>}. Read by <b>{data.counts.readers}</b>
      {downstream > 0 && <>, and copied on into <b>{downstream}</b> other field{downstream === 1 ? "" : "s"}</>}.
    </p>
  );
}

function Board({ data, loading, allReaders, onAllReaders, onTrace }: {
  data: Journey; loading: boolean; allReaders: boolean; onAllReaders: () => void; onTrace: (f: Field) => void;
}) {
  const board = useRef<HTMLDivElement>(null);
  const els = useRef(new Map<string, HTMLElement>());
  const [paths, setPaths] = useState<{ d: string; e: Edge }[]>([]);
  const [hover, setHover] = useState<string | null>(null);

  const g = useMemo(() => {
    const writers = [...data.sources].sort((a, b) => (b.launches ?? -1) - (a.launches ?? -1) || a.program.localeCompare(b.program));
    const menus = new Map<string, { code: string; used: number; top: string }>();
    const upstream = new Map<string, { f: Field; by: Set<string> }>();
    const edges: Edge[] = [];
    let batch = 0;
    for (const s of writers) {
      for (const m of s.menus) {
        if (!menus.has(m.menu)) menus.set(m.menu, { code: m.menu, used: m.used, top: m.path[0] });
        edges.push({ from: `m:${m.menu}`, to: `w:${s.program}`, kind: "enter" });
      }
      if (s.no_menu) { batch++; edges.push({ from: "batch", to: `w:${s.program}`, kind: "enter" }); }
      for (const x of s.sets) if (x.kind === "copy" && x.from) {
        const k = key(x.from);
        const u = upstream.get(k) ?? { f: x.from, by: new Set<string>() };
        u.by.add(s.program); upstream.set(k, u);
        edges.push({ from: `u:${k}`, to: `w:${s.program}`, kind: "enter" });
      }
      edges.push({ from: `w:${s.program}`, to: "f", kind: "set" });
    }
    const readersAll = [...data.readers].sort((a, b) =>
      Number(b.copies.length + b.shown.length > 0) - Number(a.copies.length + a.shown.length > 0) || (b.launches ?? -1) - (a.launches ?? -1));
    const readers = allReaders ? readersAll : readersAll.slice(0, 12);
    const downstream = new Map<string, { f: Field; by: Set<string> }>();
    for (const r of data.readers) for (const c of r.copies) {
      const k = key(c.to);
      const d = downstream.get(k) ?? { f: c.to, by: new Set<string>() };
      d.by.add(r.program); downstream.set(k, d);
    }
    for (const r of readers) {
      edges.push({ from: "f", to: `r:${r.program}`, kind: "read" });
      for (const c of r.copies) edges.push({ from: `r:${r.program}`, to: `d:${key(c.to)}`, kind: "copy" });
    }
    const menuList = [...menus.values()].sort((a, b) => b.used - a.used);
    return { writers, menuList, batch, upstream: [...upstream.values()], readers, readersAll, downstream: [...downstream.values()], edges: dedupe(edges) };
  }, [data, allReaders]);

  // which cards a hovered card is on a route with: back to where users start, on to where it ends up
  const lit = useMemo(() => {
    if (!hover) return null;
    const on = new Set<string>([hover]);
    if (hover === "f") return null;
    const walk = (dir: "fwd" | "back") => {
      const q = [hover];
      while (q.length) {
        const n = q.pop()!;
        for (const e of g.edges) {
          const [a, b] = dir === "fwd" ? [e.from, e.to] : [e.to, e.from];
          if (a !== n || on.has(b)) continue;
          on.add(b);
          if (b !== "f") q.push(b);
        }
      }
    };
    walk("fwd"); walk("back");
    return on;
  }, [hover, g.edges]);

  const reg = useCallback((id: string) => (el: HTMLElement | null) => { if (el) els.current.set(id, el); else els.current.delete(id); }, []);

  const layoutPaths = useCallback(() => {
    const b = board.current;
    if (!b) return;
    const br = b.getBoundingClientRect();
    const out: { d: string; e: Edge }[] = [];
    for (const e of g.edges) {
      const a = els.current.get(e.from), c = els.current.get(e.to);
      if (!a || !c) continue;
      const ar = a.getBoundingClientRect(), cr = c.getBoundingClientRect();
      const x1 = ar.right - br.left, y1 = ar.top + ar.height / 2 - br.top;
      const x2 = cr.left - br.left, y2 = cr.top + Math.min(cr.height / 2, 28) - br.top;
      const mx = (x1 + x2) / 2;
      out.push({ d: `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`, e });
    }
    setPaths(out);
  }, [g.edges]);

  useLayoutEffect(() => {
    layoutPaths();
    const ro = new ResizeObserver(layoutPaths);
    if (board.current) ro.observe(board.current);
    return () => ro.disconnect();
  }, [layoutPaths]);

  const dim = (id: string) => (lit && !lit.has(id) ? " dim" : "");
  const hov = (id: string) => ({ onMouseEnter: () => setHover(id), onMouseLeave: () => setHover((h) => (h === id ? null : h)) });

  return (
    <>
      <Summary data={data} menus={g.menuList.length} downstream={g.downstream.length} />
      <div className={`tr-scroll${loading ? " busy" : ""}`}>
        <div className="tr-board" ref={board}>
          <svg className="tr-wires" aria-hidden>
            {paths.map(({ d, e }, i) => {
              const on = !lit || (lit.has(e.from) && lit.has(e.to));
              return <path key={i} d={d} className={`w-${e.kind}${on ? (lit ? " on" : "") : " off"}`} />;
            })}
          </svg>

          <Lane n={1} title="How users get there" sub="menus that lead to the code that sets it">
            {g.menuList.map((m) => (
              <div key={m.code} ref={reg(`m:${m.code}`)} className={`tr-card entry${dim(`m:${m.code}`)}`} {...hov(`m:${m.code}`)}>
                <div className="tr-row"><Link href={`/menu/${encodeURIComponent(m.code)}`} className="tr-menu mono">{m.code}</Link><span className="tr-pill">{compact(m.used)} runs</span></div>
                <div className="tr-sub mono">{m.top}</div>
              </div>
            ))}
            {g.upstream.map((u) => (
              <button key={key(u.f)} ref={reg(`u:${key(u.f)}`)} className={`tr-card field-in${dim(`u:${key(u.f)}`)}`} {...hov(`u:${key(u.f)}`)} onClick={() => onTrace(u.f)} title="Trace this field">
                <div className="tr-row"><span className="mono strong">{key(u.f)}</span><span className="tr-go">trace ›</span></div>
                <div className="tr-sub">copied in by {[...u.by].join(", ")}</div>
              </button>
            ))}
            {g.batch > 0 && (
              <div ref={reg("batch")} className={`tr-card batch${dim("batch")}`} {...hov("batch")}>
                <div className="tr-row"><span className="strong">No menu</span><span className="tr-pill dim">{g.batch}</span></div>
                <div className="tr-sub">batch jobs and utilities: nothing on a menu calls them</div>
              </div>
            )}
          </Lane>

          <Lane n={2} title="Where it's set" sub="each assignment, and where its value comes from">
            {g.writers.map((s) => (
              <div key={s.program} ref={reg(`w:${s.program}`)} className={`tr-card prog${dim(`w:${s.program}`)}`} {...hov(`w:${s.program}`)}
                style={{ ["--hue" as string]: HUE[s.domain ?? "off"] ?? 215 }}>
                <div className="tr-row"><Link className="mono strong" href={programHref(s.program)}>{s.program}</Link>{s.launches ? <span className="tr-pill">{compact(s.launches)}</span> : null}</div>
                {s.menus[0] && s.menus[0].path.length > 1 && <div className="tr-sub mono">via {s.menus[0].path.slice(0, -1).join(" › ")}</div>}
                <div className="tr-sets">
                  {s.sets.slice(0, 5).map((x, i) => <Origin key={i} x={x} program={s.program} onTrace={onTrace} />)}
                  {s.sets.length > 5 && <span className="tr-more">+{s.sets.length - 5} more</span>}
                </div>
                {s.saved.length > 0 && (
                  <div className="tr-saved">saved at {s.saved.slice(0, 3).map((l) => <Link key={l} className="mono" href={programHref(s.program, l)}>:{l}</Link>)}{s.saved.length > 3 && <span> +{s.saved.length - 3}</span>}</div>
                )}
              </div>
            ))}
          </Lane>

          <Lane n={3} title="Saved in" sub="the field on file">
            <div ref={reg("f")} className={`tr-card hero${dim("f")}`} {...hov("f")}>
              <div className="tr-hero-file mono">{data.field.file}</div>
              <div className="tr-hero-attr mono">&lt;{data.field.attr}&gt;</div>
              <div className="tr-hero-names">{data.field.names.slice(0, 3).join(" · ") || "unnamed"}</div>
              <div className="tr-hero-stats">
                <div><b>{data.counts.writers}</b><span>set it</span></div>
                <div><b>{data.counts.readers}</b><span>read it</span></div>
              </div>
              {data.field.facts.length > 0 && <div className="tr-sub">{data.field.facts.length} fact{data.field.facts.length === 1 ? "" : "s"} about it</div>}
            </div>
          </Lane>

          <Lane n={4} title="Who reads it" sub="busiest first; those passing it on at the top">
            {g.readers.map((r) => (
              <div key={r.program} ref={reg(`r:${r.program}`)} className={`tr-card prog${dim(`r:${r.program}`)}`} {...hov(`r:${r.program}`)}
                style={{ ["--hue" as string]: HUE[r.domain ?? "off"] ?? 215 }}>
                <div className="tr-row"><Link className="mono strong" href={programHref(r.program, r.lines[0])}>{r.program}</Link>{r.launches ? <span className="tr-pill">{compact(r.launches)}</span> : null}</div>
                <div className="tr-sub">{data.domains[r.domain ?? "off"] ?? ""} · reads at {r.lines.slice(0, 3).map((l) => <Link key={l} className="mono" href={programHref(r.program, l)}>:{l} </Link>)}{r.lines.length > 3 && `+${r.lines.length - 3}`}</div>
                {(r.shown.length > 0 || r.copies.length > 0) && (
                  <div className="tr-sets">
                    {r.shown.slice(0, 2).map((x, i) => <span key={`s${i}`} className="tr-tag screen"><i />Shown on <b>{x.form} › {x.control}</b> <Link className="mono" href={programHref(r.program, x.line)}>:{x.line}</Link></span>)}
                    {r.copies.slice(0, 3).map((c, i) => <button key={`c${i}`} className="tr-tag copy" onClick={() => onTrace(c.to)} title="Trace that field"><i />Copies into <b className="mono">{key(c.to)}</b> <span className="mono">:{c.line}</span></button>)}
                  </div>
                )}
              </div>
            ))}
            {!allReaders && g.readersAll.length > g.readers.length && (
              <button className="tr-showall" onClick={onAllReaders}>Show all {g.readersAll.length} readers</button>
            )}
            {data.counts.readers > data.counts.readers_shown && allReaders && (
              <Link className="tr-showall" href={`/field/${encodeURIComponent(data.field.file)}/${data.field.attr}`}>{data.counts.readers - data.counts.readers_shown} more in the table view</Link>
            )}
          </Lane>

          <Lane n={5} title="Where it goes next" sub="other fields it's copied into">
            {g.downstream.length === 0 && <div className="tr-none">Not copied into another file's field (as far as the code shows).</div>}
            {g.downstream.map((d) => (
              <button key={key(d.f)} ref={reg(`d:${key(d.f)}`)} className={`tr-card field-out${dim(`d:${key(d.f)}`)}`} {...hov(`d:${key(d.f)}`)} onClick={() => onTrace(d.f)} title="Trace this field">
                <div className="tr-row"><span className="mono strong">{key(d.f)}</span><span className="tr-go">trace ›</span></div>
                <div className="tr-sub">by {[...d.by].slice(0, 3).join(", ")}{d.by.size > 3 ? ` +${d.by.size - 3}` : ""}</div>
              </button>
            ))}
            {g.downstream.length > 0 && <div className="tr-note">A copy is "possibly" the same value: it may be converted on the way. Check the line.</div>}
          </Lane>
        </div>
      </div>
    </>
  );
}

function dedupe(edges: Edge[]) {
  const seen = new Set<string>();
  return edges.filter((e) => { const k = `${e.from}>${e.to}`; if (seen.has(k)) return false; seen.add(k); return true; });
}

function Lane({ n, title, sub, children }: { n: number; title: string; sub: string; children: React.ReactNode }) {
  return (
    <section className="tr-lane">
      <div className="tr-lane-h"><span className="tr-step">{n}</span><div><b>{title}</b><span>{sub}</span></div></div>
      <div className="tr-lane-body">{children}</div>
    </section>
  );
}

function Origin({ x, program, onTrace }: { x: SetSite; program: string; onTrace: (f: Field) => void }) {
  const at = <Link className="mono" href={programHref(program, x.line)}>:{x.line}</Link>;
  switch (x.kind) {
    case "screen":
      return <span className="tr-tag screen" title={x.code}><i />Screen <b>{x.screen!.form} › {x.screen!.control}</b>{x.converted ? " (converted)" : ""} {at}</span>;
    case "system":
      return <span className="tr-tag system" title={x.code}><i />Today&apos;s date {at}</span>;
    case "clear":
      return <span className="tr-tag clear" title={x.code}><i />Cleared {at}</span>;
    case "copy":
      return <button className="tr-tag copy" title={x.code} onClick={() => onTrace(x.from!)}><i />From <b className="mono">{key(x.from!)}</b> {at}</button>;
    case "direct":
      return <span className="tr-tag computed" title={x.text}><i />WRITEV straight to file {at}</span>;
    default:
      return <span className="tr-tag computed" title={x.code}><i /><span className="mono trunc">{x.text}</span> {at}</span>;
  }
}

/** Find a field by FILE<n> or by its DICT name. */
function Picker({ onPick, compact: small = false }: { onPick: (f: Field) => void; compact?: boolean }) {
  const [q, setQ] = useState("");
  const [hits, setHits] = useState<{ f: Field; name?: string }[]>([]);
  useEffect(() => {
    const t = q.trim();
    const direct = /^([\w.\-]+)\s*<\s*(\d+)\s*>$/i.exec(t);
    if (direct) { setHits([{ f: { file: direct[1].toUpperCase(), attr: Number(direct[2]) } }]); return; }
    if (t.length < 2) { setHits([]); return; }
    const id = setTimeout(async () => {
      const r = await fetch(`/api/search?q=${encodeURIComponent(t)}`).catch(() => null);
      if (!r?.ok) return;
      const j = await r.json();
      const out: { f: Field; name?: string }[] = [
        ...(j.fields ?? []).map((x: { file: string; attr: number; dict_names: string[] }) => ({ f: { file: x.file, attr: x.attr }, name: x.dict_names?.[0] })),
        ...(j.dict_names ?? []).map((x: { pick_file: string; attr: number; name: string }) => ({ f: { file: x.pick_file, attr: x.attr }, name: x.name })),
      ];
      setHits(out.slice(0, 10));
    }, 180);
    return () => clearTimeout(id);
  }, [q]);
  const go = (f: Field) => { onPick(f); setQ(""); setHits([]); };
  return (
    <div className={`tr-picker${small ? " small" : ""}`}>
      <SearchIcon size={small ? 14 : 18} />
      <input value={q} onChange={(e) => setQ(e.target.value)} placeholder={small ? "Trace another field…" : "TRANSFER<10>, or a DICT name like REQUIRED"}
        onKeyDown={(e) => { if (e.key === "Enter" && hits[0]) go(hits[0].f); if (e.key === "Escape") setQ(""); }} aria-label="Find a field" />
      {hits.length > 0 && (
        <div className="tr-hits">
          {hits.map((h) => (
            <button key={`${key(h.f)}${h.name ?? ""}`} onClick={() => go(h.f)}>
              <span className="mono strong">{key(h.f)}</span>{h.name && <span className="tr-sub">{h.name}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function Start({ onPick }: { onPick: (f: Field) => void }) {
  return (
    <div className="tr-start">
      <div className="tr-eyebrow">Trace</div>
      <h1>Where does a value come from, and where does it go?</h1>
      <p>Pick a field and Atlas follows it through the legacy code: the menus users start from, the screen or
        calculation that sets it, the WRITE that saves it, every program that reads it, and the other files it is copied into.</p>
      <Picker onPick={onPick} />
      <div className="tr-examples">
        <span>Try</span>
        <button onClick={() => onPick({ file: "TRANSFER", attr: 10 })}><span className="mono">TRANSFER&lt;10&gt;</span> required date</button>
        <button onClick={() => onPick({ file: "TRANSFER", attr: 15 })}><span className="mono">TRANSFER&lt;15&gt;</span> ship via</button>
      </div>
      <div className="tr-steps">
        {["How users get there", "Where it's set", "Saved in", "Who reads it", "Where it goes next"].map((t, i) => (
          <div key={t}><span className="tr-step">{i + 1}</span>{t}</div>
        ))}
      </div>
    </div>
  );
}
