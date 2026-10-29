"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import FileInput from "@/components/compare/FileInput";
import { PlusIcon, TrashIcon } from "@/components/Icons";
import { toast } from "@/components/Toaster";

type Step = { id?: string; name: string };
type File = { id?: string; pick_file: string; key_template: string; note: string };

const STEP_IDEAS = ["After create", "After update", "After ship", "After receive", "After invoice", "After cancel", "After delete"];

function move<T>(list: T[], i: number, d: number): T[] {
  const j = i + d;
  if (j < 0 || j >= list.length) return list;
  const out = [...list];
  [out[i], out[j]] = [out[j], out[i]];
  return out;
}

// Create or edit a flow: its steps (checkpoints) and the files it touches.
export default function FlowEditor({ flow }: { flow?: any }) {
  const router = useRouter();
  const [name, setName] = useState<string>(flow?.name ?? "");
  const [description, setDescription] = useState<string>(flow?.description ?? "");
  const [steps, setSteps] = useState<Step[]>(flow?.steps ?? [{ name: "After create" }]);
  const [files, setFiles] = useState<File[]>(flow?.files ?? [{ pick_file: "", key_template: "{key}", note: "" }]);
  const [busy, setBusy] = useState(false);
  const [fromSuggestion, setFromSuggestion] = useState(false);

  // "Use this flow" from Suggested flows hands over a draft to review before saving
  useEffect(() => {
    if (flow || !window.location.search.includes("draft=1")) return;
    try {
      const d = JSON.parse(sessionStorage.getItem("atlas.flowDraft") ?? "null");
      if (!d) return;
      setName(d.name ?? "");
      setDescription(d.description ?? "");
      if (d.steps?.length) setSteps(d.steps);
      if (d.files?.length) setFiles(d.files);
      setFromSuggestion(true);
      sessionStorage.removeItem("atlas.flowDraft");
    } catch { /* ignore a bad draft */ }
  }, [flow]);

  async function save() {
    setBusy(true);
    const r = await fetch(flow ? `/api/compare/flows/${flow.id}` : "/api/compare/flows", {
      method: flow ? "PUT" : "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name, description, steps, files }),
    });
    const d = await r.json().catch(() => ({}));
    setBusy(false);
    if (!r.ok) { toast.error("Couldn't save the flow", d.detail ?? `HTTP ${r.status}`); return; }
    toast.success(flow ? "Flow saved" : "Flow created");
    router.push(`/compare/flows/${d.id}`);
    router.refresh();
  }

  async function remove() {
    if (!flow || !window.confirm(`Delete “${flow.name}” with all its runs, captures and notes?`)) return;
    await fetch(`/api/compare/flows/${flow.id}`, { method: "DELETE" });
    router.push("/compare");
    router.refresh();
  }

  const addStep = (n = "") => setSteps((s) => [...s, { name: n }]);
  const unused = STEP_IDEAS.filter((i) => !steps.some((s) => s.name.toLowerCase() === i.toLowerCase()));

  return (
    <div className="stack">
      {fromSuggestion && (
        <div className="notice">Filled in from a suggestion. Check the steps, files and key patterns, then press Create flow.</div>
      )}
      <section className="card">
        <div className="card-head"><h2>Flow</h2><span className="sub">What you're testing, e.g. “Branch transfer” or “Order entry”</span></div>
        <div className="card-body form-grid">
          <label><span>Name</span><input value={name} onChange={(e) => setName(e.target.value)} placeholder="Order entry" autoFocus={!flow} /></label>
          <label><span>Description</span><input value={description} onChange={(e) => setDescription(e.target.value)} placeholder="Optional: what the test covers" /></label>
        </div>
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Steps</h2>
          <span className="sub">Checkpoints where you capture both systems</span>
          <span className="spacer" />
          <button className="sm" onClick={() => addStep()}><PlusIcon size={13} /> Add step</button>
        </div>
        <div className="card-body">
          <div className="edit-list">
            {steps.map((s, i) => (
              <div key={s.id ?? `new-${i}`} className="edit-item">
                <span className="step-num">{i + 1}</span>
                <input value={s.name} onChange={(e) => setSteps((all) => all.map((x, j) => (j === i ? { ...x, name: e.target.value } : x)))}
                  placeholder="After ship" />
                <button className="ghost icon-btn sm" onClick={() => setSteps((l) => move(l, i, -1))} disabled={i === 0} aria-label="Move up">↑</button>
                <button className="ghost icon-btn sm" onClick={() => setSteps((l) => move(l, i, 1))} disabled={i === steps.length - 1} aria-label="Move down">↓</button>
                <button className="ghost icon-btn sm" onClick={() => setSteps((l) => l.filter((_, j) => j !== i))} aria-label="Remove step"><TrashIcon size={13} /></button>
              </div>
            ))}
          </div>
          {unused.length > 0 && (
            <div className="chips" style={{ marginTop: 10 }}>
              <span className="sub">Add:</span>
              {unused.map((u) => <button key={u} className="chip" onClick={() => addStep(u)}>+ {u}</button>)}
            </div>
          )}
        </div>
      </section>

      <section className="card">
        <div className="card-head">
          <h2>Files it touches</h2>
          <span className="sub">Every file to compare at each step</span>
          <span className="spacer" />
          <button className="sm" onClick={() => setFiles((f) => [...f, { pick_file: "", key_template: "{key}", note: "" }])}><PlusIcon size={13} /> Add file</button>
        </div>
        <div className="table-wrap">
          <table>
            <thead><tr><th style={{ width: "28%" }}>Pick file</th><th style={{ width: "22%" }}>Record key</th><th>Note</th><th className="w-min" /></tr></thead>
            <tbody>
              {files.map((f, i) => (
                <tr key={f.id ?? `new-${i}`}>
                  <td><FileInput value={f.pick_file} onChange={(v) => setFiles((all) => all.map((x, j) => (j === i ? { ...x, pick_file: v } : x)))} /></td>
                  <td><input className="mono" value={f.key_template}
                    onChange={(e) => setFiles((all) => all.map((x, j) => (j === i ? { ...x, key_template: e.target.value } : x)))} /></td>
                  <td><input value={f.note} placeholder="Optional, e.g. one record per shipment leg"
                    onChange={(e) => setFiles((all) => all.map((x, j) => (j === i ? { ...x, note: e.target.value } : x)))} /></td>
                  <td className="w-min"><button className="ghost icon-btn sm" onClick={() => setFiles((l) => l.filter((_, j) => j !== i))} aria-label="Remove file"><TrashIcon size={13} /></button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="card-foot">
          <code>{"{key}"}</code> is the run's key as typed; <code>{"{num}"}</code> is the same key without its letter prefix
          (T11027 → 11027). Files of one flow often key the document differently, e.g. <code>{"{num}"}</code>, <code>{"T{num}"}</code>,
          <code>{"{key}-1"}</code>. If a record isn't under its pattern, capture tries those variants and keeps the one that works.
          You can also override a single key on the run page.
        </div>
      </section>

      <div className="row">
        <button className="primary" onClick={save} disabled={busy}>{busy ? "Saving…" : flow ? "Save changes" : "Create flow"}</button>
        <button className="ghost" onClick={() => router.back()}>Cancel</button>
        <span className="spacer" />
        {flow && <button className="ghost" onClick={remove} style={{ color: "var(--bad)" }}><TrashIcon size={14} /> Delete flow</button>}
      </div>
    </div>
  );
}
