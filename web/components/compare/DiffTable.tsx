"use client";

import Link from "next/link";
import { Fragment, useState } from "react";
import { NoteIcon, TrashIcon } from "@/components/Icons";
import { toast } from "@/components/Toaster";

export type Cell = { raw: string; display: string; values: number; date: string | null; list?: string[][] };
export type Note = { id: string; verdict: string; text: string; author: string; scope: "flow" | "run"; created_at: string };
export type Row = { attr: number; names: string[]; status: string; old: Cell; new: Cell; notes: Note[] };

export const STATUS: Record<string, [string, string]> = {
  same: ["Same", "green"], different: ["Different", "red"], "old-only": ["Only old", "violet"], "new-only": ["Only new", "blue"],
};
export const VERDICT: Record<string, [string, string]> = {
  expected: ["Expected", "green"], bug: ["Bug", "red"], question: ["Question", "amber"], fixed: ["Fixed", "blue"],
};

export function readName(): string {
  try { return localStorage.getItem("atlas.reviewer") ?? ""; } catch { return ""; }
}
export function saveName(n: string) {
  try { localStorage.setItem("atlas.reviewer", n); } catch { /* private mode */ }
}

export function Value({ c, other }: { c: Cell; other?: Cell }) {
  if (!c.raw) return <span className="faint">—</span>;
  const changed = other && other.raw !== c.raw;
  const list = c.list ?? [];
  if (list.length > 1) {
    // a multivalued attribute: one row per value, numbered like Pick (<attr,1>, <attr,2>, ...)
    const theirs = other?.list ?? [];
    return (
      <div className="val">
        <ol className="mv">
          {list.map((sv, i) => {
            const mine = sv.join("\u00fc");
            const diff = other && (theirs[i] ?? [""]).join("\u00fc") !== mine;
            return (
              <li key={i} className={diff ? "mv-diff" : ""}>
                <span className="mv-i">{i + 1}</span>
                {mine === "" ? <span className="mv-empty">empty</span>
                  : sv.length > 1 ? <span className="mono">{sv.map((x, j) => <span key={j} className="mv-sv">{x || <span className="mv-empty">empty</span>}</span>)}</span>
                  : <span className="mono">{sv[0]}</span>}
              </li>
            );
          })}
        </ol>
        {c.date && <div className="val-hint"><span>{c.date}</span></div>}
      </div>
    );
  }
  return (
    <div className="val">
      <span className={`mono ${changed ? "val-changed" : ""}`} title={c.display}>{c.display}</span>
      {c.date && <div className="val-hint"><span>{c.date}</span></div>}
    </div>
  );
}

function NoteEditor({ onSave, onCancel }: {
  onSave: (verdict: string, text: string, remember: boolean) => Promise<string | null>; onCancel: () => void;
}) {
  const [verdict, setVerdict] = useState("question");
  const [text, setText] = useState("");
  const [remember, setRemember] = useState(true);
  const [busy, setBusy] = useState(false);
  return (
    <form className="note-editor" onSubmit={async (e) => {
      e.preventDefault();
      setBusy(true);
      const problem = await onSave(verdict, text, remember);
      setBusy(false);
      if (problem) toast.error("Couldn't save the note", problem);
    }}>
      <div className="seg">
        {Object.entries(VERDICT).map(([k, [label]]) => (
          <a key={k} href="#" className={verdict === k ? "active" : ""} onClick={(e) => { e.preventDefault(); setVerdict(k); }}>{label}</a>
        ))}
      </div>
      <textarea autoFocus rows={2} value={text} onChange={(e) => setText(e.target.value)}
        placeholder="What did you notice? e.g. new system leaves this blank until ship; legacy fills it at create" />
      <div className="row">
        <label className="row sub" style={{ gap: 6, cursor: "pointer" }}>
          <input type="checkbox" checked={remember} onChange={(e) => setRemember(e.target.checked)} style={{ width: "auto", height: "auto" }} />
          Remember for every run of this flow
        </label>
        <span className="spacer" />
        <button type="button" className="ghost sm" onClick={onCancel}>Cancel</button>
        <button type="submit" className="primary sm" disabled={busy || !text.trim()}>Save note</button>
      </div>
    </form>
  );
}

export default function DiffTable({ rows, pickFile, runId, onChanged, onlyDiff }: {
  rows: Row[]; pickFile: string; runId?: string; onChanged?: () => void; onlyDiff: boolean;
}) {
  const [editing, setEditing] = useState<number | null>(null);
  const shown = rows.filter((r) => !onlyDiff || r.status !== "same" || r.notes.length > 0);

  async function save(attr: number, verdict: string, text: string, remember: boolean) {
    const author = readName();  // only used when sign-in is off; otherwise notes carry the signed-in name
    const r = await fetch("/api/compare/notes", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ run_id: runId, pick_file: pickFile, attr, verdict, text, author, remember }),
    });
    if (!r.ok) return (await r.json().catch(() => ({}))).detail ?? `HTTP ${r.status}`;
    setEditing(null);
    onChanged?.();
    return null;
  }

  async function setVerdict(id: string, verdict: string) {
    await fetch(`/api/compare/notes/${id}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ verdict }) });
    onChanged?.();
  }

  async function remove(id: string) {
    if (!window.confirm("Delete this note?")) return;
    await fetch(`/api/compare/notes/${id}`, { method: "DELETE" });
    onChanged?.();
  }

  if (shown.length === 0) {
    return <div className="empty">{rows.length === 0 ? "Nothing captured yet." : "No differences. Every attribute matches."}</div>;
  }
  return (
    <div className="table-wrap">
      <table className="diff-table">
        <thead>
          <tr>
            <th className="w-min num">Attr</th><th>Name</th><th style={{ width: "30%" }}>Old system</th><th style={{ width: "30%" }}>New system</th>
            <th className="w-min">Result</th>{runId && <th style={{ width: "22%" }}>Notes</th>}
          </tr>
        </thead>
        <tbody>
          {shown.map((r) => (
            <Fragment key={r.attr}>
              <tr className={`st-${r.status}`}>
                <td className="num w-min">
                  <Link href={`/field/${encodeURIComponent(pickFile)}/${r.attr}`} className="mono" style={{ fontWeight: 600 }}>&lt;{r.attr}&gt;</Link>
                </td>
                <td className="nowrap sub mono" title={r.names.join(", ")}>{r.names.slice(0, 2).join(", ") || <span className="faint">—</span>}</td>
                <td><Value c={r.old} other={r.new} /></td>
                <td><Value c={r.new} other={r.old} /></td>
                <td className="w-min"><span className={`badge ${STATUS[r.status]?.[1] ?? ""}`}>{STATUS[r.status]?.[0] ?? r.status}</span></td>
                {runId && (
                  <td>
                    <div className="notes-cell">
                      {r.notes.map((n) => (
                        <div key={n.id} className="note-chip">
                          <select value={n.verdict} onChange={(e) => setVerdict(n.id, e.target.value)} className={`verdict v-${n.verdict}`}
                            title="Change verdict">
                            {Object.entries(VERDICT).map(([k, [label]]) => <option key={k} value={k}>{label}</option>)}
                          </select>
                          <span className="note-text" title={`${n.author}${n.scope === "flow" ? " · remembered for this flow" : " · this run only"}`}>{n.text}</span>
                          <button className="ghost icon-btn sm" onClick={() => remove(n.id)} aria-label="Delete note"><TrashIcon size={12} /></button>
                        </div>
                      ))}
                      {editing !== r.attr && (
                        <button className="ghost sm" onClick={() => setEditing(r.attr)}><NoteIcon size={13} /> Note</button>
                      )}
                    </div>
                  </td>
                )}
              </tr>
              {editing === r.attr && (
                <tr className="edit-row">
                  <td colSpan={6}><NoteEditor onCancel={() => setEditing(null)} onSave={(v, t, m) => save(r.attr, v, t, m)} /></td>
                </tr>
              )}
            </Fragment>
          ))}
        </tbody>
      </table>
    </div>
  );
}
