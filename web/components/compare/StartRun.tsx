"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import Finder from "@/components/compare/Finder";
import { SearchIcon } from "@/components/Icons";
import { toast } from "@/components/Toaster";

// Start a run of a flow: the key of the record created in each system.
export default function StartRun({ flowId, mainFile = "" }: { flowId: string; mainFile?: string }) {
  const router = useRouter();
  const [oldKey, setOldKey] = useState("");
  const [newKey, setNewKey] = useState("");
  const [name, setName] = useState("");
  const [finding, setFinding] = useState(false);
  async function start(e: React.FormEvent) {
    e.preventDefault();
    const r = await fetch("/api/compare/runs", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ flow_id: flowId, legacy_key: oldKey, new_key: newKey, name }),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) { toast.error("Couldn't start the run", d.detail ?? `HTTP ${r.status}`); return; }
    router.push(`/compare/runs/${d.id}`);
  }
  return (
    <>
    <form onSubmit={start}>
      <div className="card-body form-grid three">
        <label><span>Old system key</span><input className="mono" value={oldKey} onChange={(e) => setOldKey(e.target.value)} placeholder="record made in the green screen" /></label>
        <label><span>New system key</span><input className="mono" value={newKey} onChange={(e) => setNewKey(e.target.value)} placeholder="record made in ERP Next" /></label>
        <label><span>Name <span className="faint">(optional)</span></span><input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. 2 lines, ship complete" /></label>
      </div>
      <div className="card-foot">
        <span>Make the same record in both systems with the same inputs, then start a run.</span>
        <span className="spacer" />
        <button type="button" onClick={() => setFinding((v) => !v)}><SearchIcon size={14} /> {finding ? "Hide finder" : "Find test data"}</button>
        <button className="primary" type="submit">Start run</button>
      </div>
    </form>
    {/* outside the form: the finder's own buttons must not submit "Start run" */}
    {finding && (
      <div className="card-body" style={{ borderTop: "1px solid var(--border)" }}>
        <Finder initialFile={mainFile} flowId={flowId} onPick={(side, key) => {
          if (side === "legacy") setOldKey(key); else setNewKey(key);
          toast.success(`${side === "legacy" ? "Old" : "New"} system key set`, key);
        }} />
      </div>
    )}
    </>
  );
}
