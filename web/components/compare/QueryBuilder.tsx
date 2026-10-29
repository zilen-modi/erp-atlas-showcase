"use client";

import { useEffect, useMemo, useState } from "react";
import { PlusIcon, TrashIcon } from "@/components/Icons";

export type FieldValue = { value: string; label: string | null; count: number | null; source: string };
export type Field = { name: string; attr: number; conv: string; multi: boolean; kind: string; filled_pct: number | null; values: FieldValue[] };
type Op = "=" | "#" | "GE" | "LE" | "GT" | "LT" | "LIKE" | "EMPTY" | "FILLED";
type Row = { join: "AND" | "OR"; field: string; op: Op; value: string };

const OPS: { op: Op; label: string; kinds?: string[] }[] = [
  { op: "=", label: "is" }, { op: "#", label: "is not" },
  { op: "GE", label: "on or after", kinds: ["date"] }, { op: "LE", label: "on or before", kinds: ["date"] },
  { op: "GE", label: "at least", kinds: ["number", "integer"] }, { op: "LE", label: "at most", kinds: ["number", "integer"] },
  { op: "GT", label: "after / more than" }, { op: "LT", label: "before / less than" },
  { op: "LIKE", label: "starts with", kinds: ["text", "code", "key"] },
  { op: "FILLED", label: "has a value" }, { op: "EMPTY", label: "is empty" },
];

const toPick = (iso: string) => { const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso); return m ? `${m[2]}/${m[3]}/${m[1]}` : iso; };
const fromPick = (s: string) => { const m = /^(\d{2})\/(\d{2})\/(\d{4})$/.exec(s); return m ? `${m[3]}-${m[1]}-${m[2]}` : s; };

/** Rows -> a RetrieVe selection the finder accepts. */
export function toQuery(rows: Row[], kinds: Map<string, string>): string {
  // a row joins the query once it's complete: a blank value isn't "is empty" (that's its own condition)
  return rows.filter((r) => r.field.trim() && (r.op === "EMPTY" || r.op === "FILLED" || r.value !== "")).map((r, i) => {
    const f = r.field.trim().toUpperCase(), date = kinds.get(f) === "date";
    const v = date ? toPick(r.value) : r.value;
    const cond = r.op === "EMPTY" ? `WITH ${f} = ""` : r.op === "FILLED" ? `WITH ${f} # ""`
      : r.op === "LIKE" ? `WITH ${f} LIKE "${v}..."` : `WITH ${f} ${r.op} "${v}"`;
    return (i ? `${r.join} ` : "") + cond;
  }).join(" ");
}

/** A selection -> rows, if it's made only of simple conditions; null when it needs the text box. */
export function fromQuery(q: string, kinds: Map<string, string>): Row[] | null {
  const t = q.trim();
  if (!t) return [];
  const parts = t.split(/\s+(AND|OR)\s+(?=WITH\b)/i);
  const rows: Row[] = [];
  for (let i = 0; i < parts.length; i += 2) {
    const m = /^WITH\s+(\S+)\s+(=|#|EQ|NE|GE|LE|GT|LT|LIKE)\s+"([^"]*)"$/i.exec(parts[i].trim());
    if (!m) return null;
    const field = m[1].toUpperCase();
    let op = m[2].toUpperCase().replace("EQ", "=").replace("NE", "#") as Op;
    let value = m[3];
    if (op === "=" && value === "") op = "EMPTY";
    else if (op === "#" && value === "") op = "FILLED";
    else if (op === "LIKE") value = value.replace(/\.\.\.$/, "");
    if (kinds.get(field) === "date") value = fromPick(value);
    rows.push({ join: (i ? parts[i - 1].toUpperCase() : "AND") as "AND" | "OR", field, op, value });
  }
  return rows;
}

// Build a RetrieVe selection from field / condition / value rows; the text box stays the source of truth.
export default function QueryBuilder({ file, query, onChange, onFields }: {
  file: string; query: string; onChange: (q: string) => void; onFields?: (f: Field[]) => void;
}) {
  const [fields, setFields] = useState<Field[]>([]);
  useEffect(() => {
    const f = file.trim().toUpperCase();
    if (!f) { setFields([]); return; }
    let live = true;
    fetch(`/api/finder/fields/${encodeURIComponent(f)}`).then((r) => (r.ok ? r.json() : [])).then((x: Field[]) => {
      if (!live) return;
      setFields(x); onFields?.(x);
    }).catch(() => undefined);
    return () => { live = false; };
  }, [file, onFields]);

  const byName = useMemo(() => new Map(fields.map((f) => [f.name, f])), [fields]);
  const kinds = useMemo(() => new Map(fields.map((f) => [f.name, f.kind])), [fields]);
  // the rows are their own state (a half-filled row isn't in the query yet), kept in step with the text:
  // re-read when the text changes from outside, or when the fields arrive (dates need their kind)
  const [rows, setRows] = useState<Row[] | null>(() => fromQuery(query, kinds));
  useEffect(() => { setRows(fromQuery(query, kinds)); }, [kinds]);  // eslint-disable-line react-hooks/exhaustive-deps
  useEffect(() => {
    setRows((cur) => (cur && toQuery(cur, kinds) === query.trim() ? cur : fromQuery(query, kinds)));
  }, [query]);  // eslint-disable-line react-hooks/exhaustive-deps
  // the most useful fields first: those with known values, then the most often filled
  const ranked = useMemo(() => [...fields].filter((f) => f.attr > 0 || f.name === "@ID")
    .sort((a, b) => Number(b.values.length > 0) - Number(a.values.length > 0) || (b.filled_pct ?? -1) - (a.filled_pct ?? -1)), [fields]);

  const set = (next: Row[]) => { setRows(next); onChange(toQuery(next, kinds)); };
  const edit = (i: number, patch: Partial<Row>) => rows && set(rows.map((r, j) => (j === i ? { ...r, ...patch } : r)));

  if (!file.trim()) return <div className="qb-empty">Pick a file to build a selection from its fields.</div>;
  if (rows === null) {
    return <div className="qb-empty">This selection uses more than simple conditions, so edit it as text below (or <button type="button" className="linklike" onClick={() => onChange("")}>start over</button>).</div>;
  }
  const listId = `qb-fields-${file}`;
  return (
    <div className="qb">
      <datalist id={listId}>
        {ranked.map((f) => <option key={f.name} value={f.name}>{`<${f.attr}> ${f.kind}${f.filled_pct != null ? ` · ${Math.round(f.filled_pct)}% filled` : ""}`}</option>)}
      </datalist>
      {rows.map((r, i) => {
        const f = byName.get(r.field.toUpperCase());
        const kind = f?.kind ?? "text";
        const ops = OPS.filter((o) => !o.kinds || o.kinds.includes(kind));
        const needsValue = r.op !== "EMPTY" && r.op !== "FILLED";
        return (
          <div key={i} className="qb-row">
            {i === 0 ? <span className="qb-join first">Where</span> : (
              <select className="qb-join" value={r.join} onChange={(e) => edit(i, { join: e.target.value as "AND" | "OR" })}>
                <option value="AND">and</option><option value="OR">or</option>
              </select>
            )}
            <div className="qb-field">
              <input className="mono" list={listId} value={r.field} placeholder="field" spellCheck={false}
                onChange={(e) => edit(i, { field: e.target.value.toUpperCase() })} />
              {f && <span className="qb-meta">&lt;{f.attr}&gt; {kind}</span>}
            </div>
            <select value={ops.some((o) => o.op === r.op) ? r.op : "="} onChange={(e) => edit(i, { op: e.target.value as Op })}>
              {ops.map((o) => <option key={o.label} value={o.op}>{o.label}</option>)}
            </select>
            {!needsValue ? <span className="qb-novalue" /> : kind === "date" ? (
              <input type="date" value={r.value} onChange={(e) => edit(i, { value: e.target.value })} />
            ) : f && f.values.length > 0 && (r.op === "=" || r.op === "#") ? (
              <select className="mono" value={f.values.some((v) => v.value === r.value) ? r.value : "__other"}
                onChange={(e) => edit(i, { value: e.target.value === "__other" ? "" : e.target.value })}>
                {!f.values.some((v) => v.value === r.value) && <option value="__other">{r.value ? `“${r.value}”` : "choose…"}</option>}
                {f.values.map((v) => (
                  <option key={v.value} value={v.value}>{v.value}{v.label ? ` — ${v.label}` : ""}{v.count != null ? ` (${v.count})` : ""}</option>
                ))}
              </select>
            ) : (
              <input className="mono" value={r.value} onChange={(e) => edit(i, { value: e.target.value })} placeholder="value" />
            )}
            <button type="button" className="ghost icon-btn sm" aria-label="Remove condition" onClick={() => set(rows.filter((_x, j) => j !== i))}><TrashIcon size={13} /></button>
          </div>
        );
      })}
      <div className="qb-add">
        <button type="button" className="ghost sm" onClick={() => set([...rows, { join: "AND", field: "", op: "=", value: "" }])}><PlusIcon size={13} /> Add condition</button>
        {rows.length === 0 && ranked.filter((f) => f.values.length > 0).slice(0, 4).map((f) => (
          <button key={f.name} type="button" className="chip qb-suggest" onClick={() => set([{ join: "AND", field: f.name, op: "=", value: f.values[0].value }])}>
            {f.name}
          </button>
        ))}
      </div>
    </div>
  );
}
