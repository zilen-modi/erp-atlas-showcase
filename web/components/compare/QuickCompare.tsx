"use client";

import { useState } from "react";
import DiffTable, { type Row } from "@/components/compare/DiffTable";
import FileInput from "@/components/compare/FileInput";
import { CompareIcon } from "@/components/Icons";
import { errorText, toast } from "@/components/Toaster";

// Compare any two records of one file right now, without setting up a flow.
export default function QuickCompare() {
  const [file, setFile] = useState("");
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<any>(null);
  const [onlyDiff, setOnlyDiff] = useState(true);

  async function run(e: React.FormEvent) {
    e.preventDefault();
    setBusy(true);
    const r = await fetch("/api/compare/quick", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pick_file: file, old_key: a, new_key: b }),
    }).catch(() => null);
    setBusy(false);
    if (!r?.ok) { toast.error("Quick compare failed", await errorText(r)); return; }
    setRes(await r.json());
  }

  return (
    <section className="card">
      <div className="card-head">
        <h2>Quick compare</h2>
        <span className="sub">Two records of any file, read from TEST now</span>
      </div>
      <form className="quick-form" onSubmit={run}>
        <label><span>File</span><FileInput value={file} onChange={setFile} /></label>
        <label><span>Old system key</span><input value={a} onChange={(e) => setA(e.target.value)} placeholder="e.g. 3456789" /></label>
        <label><span>New system key</span><input value={b} onChange={(e) => setB(e.target.value)} placeholder="e.g. 3456790" /></label>
        <button className="primary" type="submit" disabled={busy || !file.trim() || (!a.trim() && !b.trim())}>
          {busy ? <><span className="spinner" style={{ borderTopColor: "#fff" }} /> Reading…</> : <><CompareIcon size={14} /> Compare</>}
        </button>
      </form>
      {res && (
        <>
          <div className="toolbar">
            <b className="mono">{res.pick_file}</b>
            <span className="sub">old <code>{res.old.key || "—"}</code>{res.old.typed && res.old.key !== res.old.typed && <span className="faint"> (found as this, not {res.old.typed})</span>}{res.old.error && <span className="st-note"> · {res.old.error}</span>}</span>
            <span className="sub">new <code>{res.new.key || "—"}</code>{res.new.typed && res.new.key !== res.new.typed && <span className="faint"> (found as this, not {res.new.typed})</span>}{res.new.error && <span className="st-note"> · {res.new.error}</span>}</span>
            <span className="spacer" />
            <span className={`badge ${res.differences ? "red" : "green"}`}>{res.differences} difference{res.differences === 1 ? "" : "s"}</span>
            <label className="row sub" style={{ gap: 6, cursor: "pointer" }}>
              <input type="checkbox" checked={onlyDiff} onChange={(e) => setOnlyDiff(e.target.checked)} style={{ width: "auto", height: "auto" }} />
              Differences only
            </label>
          </div>
          <DiffTable rows={res.rows as Row[]} pickFile={res.pick_file} onlyDiff={onlyDiff} />
        </>
      )}
    </section>
  );
}
