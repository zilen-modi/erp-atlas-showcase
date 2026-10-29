"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { errorText, toast } from "@/components/Toaster";
import { STATUS_LABEL } from "@/lib/parity";

// Migration status of a legacy job or report: what replaces it in ERP Next, if anything.
export default function ParityEditor({ kind, name, parity, statuses }: {
  kind: "job" | "report"; name: string; parity: { status: string; target: string; note: string; updated_at?: string }; statuses: string[];
}) {
  const router = useRouter();
  const [status, setStatus] = useState(parity.status);
  const [target, setTarget] = useState(parity.target ?? "");
  const [note, setNote] = useState(parity.note ?? "");
  const [busy, setBusy] = useState(false);
  const dirty = status !== parity.status || target !== (parity.target ?? "") || note !== (parity.note ?? "");
  async function save() {
    setBusy(true);
    const r = await fetch(`/api/parity/${kind}/${encodeURIComponent(name)}`, {
      method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ status, target, note }),
    }).catch(() => null);
    setBusy(false);
    if (!r?.ok) { toast.error("Couldn't save", await errorText(r)); return; }
    toast.success("Migration status saved", STATUS_LABEL[status]?.[0]);
    router.refresh();
  }
  return (
    <section className="card">
      <div className="card-head"><h2>In ERP Next</h2>{parity.updated_at && <span className="sub">updated {parity.updated_at.slice(0, 10)}</span>}</div>
      <div className="card-body parity">
        <label><span>Status</span>
          <select value={status} onChange={(e) => setStatus(e.target.value)}>
            {statuses.map((s) => <option key={s} value={s}>{STATUS_LABEL[s]?.[0] ?? s}</option>)}
          </select>
        </label>
        <label><span>{kind === "job" ? "ERP Next job / doctype" : "ERP Next report"}</span>
          <input value={target} onChange={(e) => setTarget(e.target.value)} placeholder={kind === "job" ? "e.g. scheduler: reorder_suggestions (daily)" : "e.g. Stock Ledger report"} />
        </label>
        <label className="wide"><span>Note</span>
          <textarea rows={2} value={note} onChange={(e) => setNote(e.target.value)} placeholder="Why, who owns it, what's different…" />
        </label>
      </div>
      <div className="card-foot"><span className="spacer" /><button className="primary sm" disabled={!dirty || busy} onClick={save}>{busy ? "Saving…" : "Save"}</button></div>
    </section>
  );
}
