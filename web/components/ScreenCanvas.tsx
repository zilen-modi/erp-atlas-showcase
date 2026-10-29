"use client";

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";
import ExportButton from "@/components/ExportButton";
import { errorText, toast } from "@/components/Toaster";
import { programHref } from "@/lib/api";
import { readParam, writeParams } from "@/lib/urlstate";

// Character cells -> pixels (Arial 9 in AccuTerm is roughly 8 x 20 per cell)
const CX = 8, CY = 20, TAB_HEAD = 26;

type Node = {
  name: string; kind: string; type: number; left: number; top: number; width: number; height: number;
  caption?: string; title?: string; tip?: string; items?: { value: string; label: string }[];
  columns?: { heading: string; width: number }[]; children?: Node[];
};
type Handler = { event: string; label: string; line: number; writes: string[]; calls: string[] };
type Binding = { file: string; attr: number; how: string; lines: number[] };
type Wire = { handlers: Handler[]; bindings: Binding[] };

const plain = (s?: string) => (s ?? "").replace(/&(?!&)/g, "");

function fieldLabel(b: Binding) {
  return b.attr === 0 ? `${b.file} key` : `${b.file}<${b.attr}>`;
}

// One W4 form drawn from its template, every control clickable to show what it's wired to.
export default function ScreenCanvas({ project, form, program }: { project: string; form: string; program: string }) {
  const [d, setD] = useState<any>(null);
  const [sel, setSel] = useState<string | null>(null);
  const [showFields, setShowFields] = useState(() => readParam("fields") !== "off");
  const [showNames, setShowNames] = useState(() => readParam("names") === "on");
  const [tabSel, setTabSel] = useState<Record<string, string>>({});
  const [fit, setFit] = useState(() => readParam("fit") !== "off");
  useEffect(() => {
    writeParams({ fields: showFields ? null : "off", names: showNames ? "on" : null, fit: fit ? null : "off" });
  }, [showFields, showNames, fit]);
  const [boxW, setBoxW] = useState(0);
  const scrollRef = useCallback((el: HTMLDivElement | null) => {
    if (!el) return;
    const ro = new ResizeObserver(() => setBoxW(el.clientWidth - 40));
    ro.observe(el);
    setBoxW(el.clientWidth - 40);
  }, []);

  const load = useCallback(async () => {
    setD(null); setSel(null);
    const r = await fetch(`/api/screens/${encodeURIComponent(project)}/${encodeURIComponent(form)}`).catch(() => null);
    if (!r?.ok) { toast.error("Couldn't load this form", await errorText(r)); return; }
    setD(await r.json());
  }, [project, form]);
  useEffect(() => { load(); }, [load]);

  const wiring: Record<string, Wire> = d?.wiring ?? {};
  const menus = useMemo(() => {
    const out: Node[] = [];
    const walk = (ns: Node[]) => ns.forEach((n) => { if (n.kind === "menu") out.push(n); if (n.children) walk(n.children); });
    if (d) walk(d.form.controls);
    return out;
  }, [d]);

  if (!d) return <div className="card empty" data-report-busy><span className="spinner" style={{ display: "inline-block" }} /></div>;

  const f = d.form;
  const selNode = sel ? find(f.controls, sel) : null;

  function render(n: Node, parentKind?: string): React.ReactNode {
    if (n.kind === "menu" || n.kind === "timer") return null;
    const w = wiring[n.name];
    const style: React.CSSProperties = { left: n.left * CX, top: n.top * CY + (parentKind === "tab" ? 0 : 0), width: Math.max(n.width * CX, 6), height: Math.max(n.height * CY, 6) };
    const cls = `sc-ctl sc-${n.kind} ${w ? "wired" : ""} ${sel === n.name ? "sel" : ""}`;
    const pick = (e: React.MouseEvent) => { e.stopPropagation(); setSel(n.name); };
    const bound = showFields && w?.bindings[0] ? <span className="sc-field">{fieldLabel(w.bindings[0])}</span> : null;
    const nameTag = showNames ? <span className="sc-name">{n.name}</span> : null;
    const title = `${n.name}${w?.bindings[0] ? ` · ${fieldLabel(w.bindings[0])}` : ""}${n.tip ? ` · ${n.tip}` : ""}${w ? ` · ${w.handlers.length} handler${w.handlers.length === 1 ? "" : "s"}` : ""}`;

    if (n.kind === "tabs") {
      const tabs = (n.children ?? []).filter((c) => c.kind === "tab");
      const cur = tabSel[n.name] ?? tabs[0]?.name;
      const active = tabs.find((t) => t.name === cur);
      return (
        <div key={n.name} className={cls} style={style} title={title}>
          <div className="sc-tabhead">
            {tabs.map((t) => (
              <button key={t.name} type="button" className={`sc-tab ${t.name === cur ? "on" : ""} ${wiring[t.name] ? "wired" : ""}`}
                onClick={(e) => { e.stopPropagation(); setTabSel((s) => ({ ...s, [n.name]: t.name })); setSel(t.name); }}>
                {plain(t.title) || t.name}
              </button>
            ))}
          </div>
          <div className="sc-tabbody" style={{ top: TAB_HEAD }}>{active?.children?.map((c) => render(c, "tab"))}</div>
          {nameTag}
        </div>
      );
    }
    if (n.kind === "frame") {
      return (
        <fieldset key={n.name} className={cls} style={style} onClick={pick} title={title}>
          {(n.title || n.caption) && <legend>{plain(n.title || n.caption)}</legend>}
          {n.children?.map((c) => render(c, "frame"))}
          {nameTag}
        </fieldset>
      );
    }
    let inner: React.ReactNode = null;
    switch (n.kind) {
      case "label": inner = n.caption ? <span className="sc-cap">{plain(n.caption)}</span> : <span className="sc-data" />; break;
      case "button": inner = <span className="sc-cap">{plain(n.caption) || n.name.replace(/^BTN|^CMD/, "")}</span>; break;
      case "checkbox": inner = <><span className="sc-box" /><span className="sc-cap">{plain(n.caption)}</span></>; break;
      case "combo": case "dropdown":
        inner = <><span className="sc-cap">{n.items?.[0]?.label ?? ""}</span><span className="sc-caret">▾</span></>; break;
      case "radio":
        inner = <>
          {n.title && <span className="sc-rtitle">{plain(n.title)}</span>}
          <span className="sc-ritems">{(n.items ?? []).map((it) => <span key={it.value + it.label}><span className="sc-dot" />{plain(it.label)}</span>)}</span>
        </>; break;
      case "grid":
        inner = <table className="sc-grid"><thead><tr>{(n.columns ?? []).map((c, i) => <th key={i} style={{ width: c.width * CX }}>{c.heading}</th>)}</tr></thead>
          <tbody>{[0, 1, 2].map((r) => <tr key={r}>{(n.columns ?? []).map((_c, i) => <td key={i} />)}</tr>)}</tbody></table>; break;
      case "list": inner = <span className="sc-listitems">{(n.items ?? []).slice(0, 8).map((it) => <span key={it.value + it.label}>{plain(it.label)}</span>)}</span>; break;
      case "progress": inner = <span className="sc-prog" />; break;
      case "picture": inner = <span className="sc-cap faint">image</span>; break;
      default: inner = null;
    }
    return <div key={n.name} className={cls} style={style} onClick={pick} title={title}>{inner}{bound}{nameTag}</div>;
  }

  const wiredCount = Object.keys(wiring).length;
  return (
    <div className="sc-layout">
      <section className="card sc-stage" data-section={`form-${f.name}`} id={`sec-form-${f.name}`}>
        <div className="card-head">
          <h2 className="mono">{f.name}</h2>
          <span className="sub ellipsis">{plain(f.title)}</span>
          <span className="spacer" />
          <label className="row sub" style={{ gap: 6, cursor: "pointer" }}>
            <input type="checkbox" checked={fit} onChange={(e) => setFit(e.target.checked)} style={{ width: "auto", height: "auto" }} /> Fit
          </label>
          <label className="row sub" style={{ gap: 6, cursor: "pointer" }}>
            <input type="checkbox" checked={showFields} onChange={(e) => setShowFields(e.target.checked)} style={{ width: "auto", height: "auto" }} /> Fields
          </label>
          <label className="row sub" style={{ gap: 6, cursor: "pointer" }}>
            <input type="checkbox" checked={showNames} onChange={(e) => setShowNames(e.target.checked)} style={{ width: "auto", height: "auto" }} /> Control names
          </label>
          <ExportButton section={`form-${f.name}`} sectionTitle={`Form ${f.name}`} />
        </div>
        <div className="sc-scroll" ref={scrollRef} onClick={() => setSel(null)}>
          {(() => {
            const natural = f.width * CX + 2;
            const scale = fit && boxW > 0 && natural > boxW ? boxW / natural : 1;
            return (
          <div className="sc-fit" style={{ width: natural * scale, height: (f.height * CY + 28) * scale }}>
          <div className="sc-window" style={{ width: natural, transform: scale < 1 ? `scale(${scale})` : undefined, transformOrigin: "0 0" }}>
            <div className="sc-titlebar"><span>{plain(f.title) || f.name}</span><span className="sc-winbtns">▁ ▢ ✕</span></div>
            <div className="sc-body" style={{ width: f.width * CX, height: f.height * CY }}>
              {f.controls.map((c: Node) => render(c))}
            </div>
          </div>
          </div>
            );
          })()}
        </div>
        <div className="card-foot">
          <span className="sub"><span className="sc-legend wired" /> wired to code ({wiredCount}) · click any control · blue tags show the field a box reads or writes</span>
        </div>
      </section>

      <aside className="card sc-side">
        {selNode ? <Detail n={selNode} w={wiring[selNode.name]} program={program} onClose={() => setSel(null)} /> : (
          <FormSummary d={d} program={program} menus={menus} onPick={setSel} />
        )}
      </aside>
    </div>
  );
}

function find(ns: Node[], name: string): Node | null {
  for (const n of ns) {
    if (n.name === name) return n;
    const k = n.children ? find(n.children, name) : null;
    if (k) return k;
  }
  return null;
}

function Handlers({ hs, program }: { hs: Handler[]; program: string }) {
  if (!hs.length) return <div className="sub">No event handler in {program} for this control.</div>;
  return (
    <div className="sc-handlers">
      {hs.map((h) => (
        <div key={h.label} className="sc-handler">
          <div className="row" style={{ gap: 8 }}>
            <span className="badge blue">{h.event}</span>
            <Link href={programHref(program, h.line)} className="mono sub">line {h.line}</Link>
          </div>
          <div className="mono faint sc-lbl" title={h.label}>{h.label}</div>
          {h.writes.length > 0 && <div className="chips" style={{ marginTop: 4 }}>{h.writes.map((w) => <Link key={w} href={`/files/${encodeURIComponent(w)}`} className="chip mono">writes {w}</Link>)}</div>}
          {h.calls.length > 0 && <div className="sub" style={{ marginTop: 4 }}>calls {h.calls.slice(0, 6).map((c, i) => <span key={c}>{i > 0 && ", "}<Link href={`/program/${encodeURIComponent(c)}`} className="mono">{c}</Link></span>)}</div>}
        </div>
      ))}
    </div>
  );
}

function Detail({ n, w, program, onClose }: { n: Node; w?: Wire; program: string; onClose: () => void }) {
  return (
    <>
      <div className="card-head">
        <h2 className="mono ellipsis">{n.name}</h2>
        <span className="badge">{n.kind}</span>
        <span className="spacer" />
        <button className="ghost icon-btn sm" onClick={onClose} aria-label="Close">×</button>
      </div>
      <div className="card-body stack" style={{ gap: 14 }}>
        {(n.caption || n.title || n.tip) && (
          <div className="sub">{n.caption && <>Caption <b>“{plain(n.caption)}”</b> </>}{n.title && <>Title <b>“{plain(n.title)}”</b> </>}{n.tip && <div>Tip: {n.tip}</div>}</div>
        )}
        <div>
          <div className="sc-h">Field</div>
          {w?.bindings.length ? w.bindings.map((b) => (
            <div key={`${b.file}${b.attr}`} className="sc-bind">
              {b.attr === 0 ? <Link href={`/files/${encodeURIComponent(b.file)}`} className="mono">{b.file} key (@ID)</Link>
                : <Link href={`/field/${encodeURIComponent(b.file)}/${b.attr}`} className="mono">{b.file}&lt;{b.attr}&gt;</Link>}
              <span className="sub"> {b.how} · lines {b.lines.map((l, i) => <span key={l}>{i > 0 && ", "}<Link href={programHref(program, l)}>{l}</Link></span>)}</span>
            </div>
          )) : <div className="sub">No field found. The code doesn't read or set this control's value from a record field.</div>}
        </div>
        {n.items && n.items.length > 0 && (
          <div>
            <div className="sc-h">Items ({n.items.length})</div>
            <div className="sc-items">{n.items.map((it) => <div key={it.value + it.label}><code>{it.value}</code> {it.label !== it.value && it.label}</div>)}</div>
          </div>
        )}
        {n.columns && n.columns.length > 0 && (
          <div>
            <div className="sc-h">Columns</div>
            <div className="sc-items">{n.columns.map((c, i) => <div key={i}><span className="faint">{i + 1}</span> {c.heading || <i className="faint">no heading</i>}</div>)}</div>
          </div>
        )}
        <div>
          <div className="sc-h">Handlers</div>
          <Handlers hs={w?.handlers ?? []} program={program} />
        </div>
        <div className="sub faint">Position {n.left}, {n.top} · size {n.width} × {n.height} (character cells)</div>
      </div>
    </>
  );
}

function FormSummary({ d, program, menus, onPick }: { d: any; program: string; menus: Node[]; onPick: (n: string) => void }) {
  return (
    <>
      <div className="card-head"><h2>This form</h2></div>
      <div className="card-body stack" style={{ gap: 14 }}>
        <div>
          <div className="sc-h">Writes ({d.writes.length} files)</div>
          {d.writes.length ? <div className="chips">{d.writes.map((w: string) => <Link key={w} href={`/files/${encodeURIComponent(w)}`} className="chip mono">{w}</Link>)}</div>
            : <div className="sub">No handler on this form writes a Pick file.</div>}
        </div>
        {d.form_events.length > 0 && (
          <div>
            <div className="sc-h">Form events</div>
            <Handlers hs={d.form_events} program={program} />
          </div>
        )}
        {menus.length > 0 && (
          <div>
            <div className="sc-h">Right-click menus</div>
            {menus.map((m) => (
              <div key={m.name} className="sc-menu">
                <button className="ghost sm mono" onClick={() => onPick(m.name)}>{m.name}</button>
                <div className="sub">{(m.items ?? []).map((i) => plain(i.label)).filter(Boolean).join(" · ")}</div>
              </div>
            ))}
          </div>
        )}
        {d.orphan_handlers.length > 0 && (
          <div>
            <div className="sc-h">Handlers with no control <span className="badge amber">{d.orphan_handlers.length}</span></div>
            <div className="sub" style={{ marginBottom: 6 }}>The code handles events for these controls, but they aren't on this form in the template, so the code can't run from here.</div>
            {d.orphan_handlers.map((o: any) => (
              <div key={o.control} className="sub mono">{o.control}: {o.handlers.map((h: Handler) => <Link key={h.label} href={programHref(program, h.line)} style={{ marginRight: 6 }}>{h.event}</Link>)}</div>
            ))}
          </div>
        )}
        {d.buttons_without_handler.length > 0 && (
          <div>
            <div className="sc-h">Buttons with no handler <span className="badge amber">{d.buttons_without_handler.length}</span></div>
            <div className="chips">{d.buttons_without_handler.map((b: string) => <button key={b} className="chip mono" onClick={() => onPick(b)}>{b}</button>)}</div>
          </div>
        )}
      </div>
    </>
  );
}
