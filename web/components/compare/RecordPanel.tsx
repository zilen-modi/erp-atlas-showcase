"use client";

import Link from "next/link";
import { useEffect, useMemo, useState } from "react";
import { CloseIcon, CopyIcon } from "@/components/Icons";
import { errorText, toast } from "@/components/Toaster";

type Attr = { attr: number; names: string[]; conv: string; raw: string; values: string[] };
type Rec = { table: string; key: string; fetched_at: string; fields: Attr[]; related: { file: string; key: string; exists: boolean; fields: Attr[] }[] };

export async function copy(text: string, what: string) {
  try { await navigator.clipboard.writeText(text); toast.success(`${what} copied`, text.length > 90 ? `${text.slice(0, 90)}…` : text); }
  catch { toast.info(what, text); }
}

/** A LIST command for the terminal: these keys, these columns. */
export function listCommand(file: string, keys: string[], cols: string[]) {
  return `LIST ${file} ${keys.map((k) => `"${k}"`).join(" ")}${cols.length ? ` ${cols.join(" ")}` : ""}`;
}

// One TEST record in full: every attribute under its DICT names, converted, with the scenario's related records.
export default function RecordPanel({ file, recordKey, related, columns, onClose }: {
  file: string; recordKey: string; related: { file: string; key: string }[]; columns: string[]; onClose: () => void;
}) {
  const [rec, setRec] = useState<Rec | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState("");
  const [empty, setEmpty] = useState(false);

  const rel = JSON.stringify(related);         // by value: a new array with the same checks isn't a new read
  useEffect(() => {
    setRec(null); setError(null);
    let live = true;
    fetch("/api/finder/record", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pick_file: file, key: recordKey, related: JSON.parse(rel) }),
    }).then(async (r) => { if (!r.ok) throw new Error(await errorText(r)); return r.json(); })
      .then((x) => { if (live) setRec(x); })
      .catch((e) => { if (live) setError(e instanceof Error ? e.message : String(e)); });
    return () => { live = false; };
  }, [file, recordKey, rel]);

  useEffect(() => {
    const esc = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onClose]);

  const filled = rec?.fields.filter((f) => f.raw !== "").length ?? 0;

  return (
    <div className="rp-veil" onClick={onClose}>
      <aside className="rp" onClick={(e) => e.stopPropagation()} aria-label={`${file} ${recordKey}`}>
        <header className="rp-head">
          <div>
            <div className="tr-eyebrow">Record on TEST</div>
            <h2 className="mono">{file} <span>{recordKey}</span></h2>
            {rec && <div className="sub">{filled} of {rec.fields.length} attributes filled · read {new Date(rec.fetched_at).toLocaleTimeString()}</div>}
          </div>
          <div className="rp-actions">
            <button type="button" className="sm" onClick={() => copy(recordKey, "Key")}><CopyIcon size={13} /> Key</button>
            <button type="button" className="sm" onClick={() => copy(listCommand(file, [recordKey], columns), "LIST command")}><CopyIcon size={13} /> LIST</button>
            <button type="button" className="ghost icon-btn sm" aria-label="Close" onClick={onClose}><CloseIcon size={15} /></button>
          </div>
        </header>
        {error && <div className="tr-error">{error}</div>}
        {!rec && !error && <div className="tr-loading">Reading {file} {recordKey} from TEST…</div>}
        {rec && (
          <>
            <div className="rp-tools">
              <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filter by name, number or value…" />
              <label className="pr-toggle"><input type="checkbox" checked={empty} onChange={(e) => setEmpty(e.target.checked)} /> Show empty</label>
            </div>
            <Attrs file={file} fields={rec.fields} filter={filter} empty={empty} />
            {rec.related.map((r) => (
              <section key={r.file + r.key} className="rp-rel">
                <div className="rp-rel-h">
                  <b className="mono">{r.file} {r.key}</b>
                  {r.exists ? <span className="ok-text">exists</span> : <span className="faint">not on TEST</span>}
                </div>
                {r.exists && <Attrs file={r.file} fields={r.fields} filter={filter} empty={false} compact />}
              </section>
            ))}
          </>
        )}
      </aside>
    </div>
  );
}

function Attrs({ file, fields, filter, empty, compact = false }: { file: string; fields: Attr[]; filter: string; empty: boolean; compact?: boolean }) {
  const shown = useMemo(() => {
    const t = filter.trim().toUpperCase();
    return fields.filter((f) => (empty || f.raw !== "") && (!t || String(f.attr) === t || f.names.some((n) => n.includes(t))
      || f.values.some((v) => v.toUpperCase().includes(t))));
  }, [fields, filter, empty]);
  if (!shown.length) return <div className="tr-none">No attributes match.</div>;
  return (
    <div className={`rp-attrs${compact ? " compact" : ""}`}>
      {shown.map((f) => (
        <div key={f.attr} className="rp-attr">
          <Link className="rp-pos mono" href={`/field/${encodeURIComponent(file)}/${f.attr}`} title="Who reads and writes this field">&lt;{f.attr}&gt;</Link>
          <div className="rp-names">
            {f.names.length ? (
              <><Link href={`/trace?file=${encodeURIComponent(file)}&attr=${f.attr}`} title="Trace this field" className="rp-name">{f.names[0]}</Link>
                {f.names.length > 1 && <span className="faint"> {f.names.slice(1, 3).join(", ")}{f.names.length > 3 ? "…" : ""}</span>}</>
            ) : <span className="faint">unnamed</span>}
          </div>
          <div className="rp-vals" title={f.raw !== f.values.join("ý") ? `stored as ${f.raw.replace(/ý/g, " ] ").replace(/ü/g, " \\ ")}` : undefined}>
            {f.values.length === 0 ? <span className="faint">—</span>
              : f.values.length === 1 ? <span className="mono">{f.values[0]}</span>
              : <>{f.values.slice(0, 12).map((v, i) => <span key={i} className="rp-mv mono"><i>{i + 1}</i>{v || "·"}</span>)}{f.values.length > 12 && <span className="faint">+{f.values.length - 12} more</span>}</>}
          </div>
        </div>
      ))}
    </div>
  );
}
