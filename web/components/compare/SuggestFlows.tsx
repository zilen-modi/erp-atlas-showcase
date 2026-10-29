"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState } from "react";
import { ArrowIcon, SearchIcon, SparkIcon, SyncIcon } from "@/components/Icons";
import { ago } from "@/lib/api";
import JobProgress from "@/components/JobProgress";
import { type Job, pollJob, reportJob, startJob } from "@/lib/jobs";

type SFile = { pick_file: string; key_template: string; why: string };
type SFlow = { name: string; description: string; program: string; steps: string[]; files: SFile[]; evidence: string[]; source: string };

const TOPICS = ["Transfer", "Order", "Purchase order", "Receiving", "Invoice", "Product"];
const CITE = /^([A-Z][A-Z0-9._$%]+):(\d+)$/;

export function toDraft(flow: SFlow) {
  return {
    name: flow.name,
    description: flow.description,
    steps: flow.steps.map((name) => ({ name })),
    files: flow.files.map((f) => ({ pick_file: f.pick_file, key_template: f.key_template || "{key}", note: f.why })),
  };
}

function FlowCard({ f, onUse }: { f: SFlow; onUse: () => void }) {
  return (
    <div className="sugg">
      <div className="sugg-head">
        <div style={{ minWidth: 0 }}>
          <div className="sugg-name">{f.name}</div>
          <div className="sub">{f.description}</div>
        </div>
        <button className="primary sm" onClick={onUse}>Use this flow <ArrowIcon size={13} /></button>
      </div>
      <div className="sugg-row">
        <span className="sugg-label">Steps</span>
        <div className="step-line">
          {f.steps.map((s, i) => <span key={s + i} className="step-pill sm"><span className="step-num">{i + 1}</span>{s}</span>)}
        </div>
      </div>
      <div className="sugg-row">
        <span className="sugg-label">Files</span>
        <div className="chips">
          {f.files.map((x) => (
            <span key={x.pick_file} className="chip" title={x.why}>
              {x.pick_file}{x.key_template !== "{key}" && <span className="faint"> {x.key_template}</span>}
            </span>
          ))}
        </div>
      </div>
      {f.evidence.length > 0 && (
        <div className="sugg-row">
          <span className="sugg-label">From</span>
          <div className="chips">
            {f.evidence.slice(0, 5).map((e) => {
              const m = e.match(CITE);
              return m
                ? <Link key={e} href={`/program/${encodeURIComponent(m[1])}/source?line=${m[2]}`} className="chip">{e}</Link>
                : <span key={e} className="chip" title={e}>{e.replace(/^GUI\.[^.]+\./, "")}</span>;
            })}
          </div>
        </div>
      )}
    </div>
  );
}

// "What are you testing?" -> suggested Compare flows, from the code and (on request) named by Claude.
export default function SuggestFlows({ initial = "", compact = false }: { initial?: string; compact?: boolean }) {
  const router = useRouter();
  const [q, setQ] = useState(initial);
  const [term, setTerm] = useState(initial);
  const [data, setData] = useState<any>(null);
  const [loading, setLoading] = useState(false);
  const [job, setJob] = useState<Job | null>(null);

  const isProgram = /^[A-Z0-9.$%_]+$/.test(term) && /[0-9]|^W4|^W5/.test(term) && term.length > 4;
  const params = useCallback((): Record<string, string> => {
    const t = term.trim();
    return isProgram ? { program: t.toUpperCase() } : { topic: t };
  }, [term, isProgram]);

  const load = useCallback(async () => {
    if (term.trim().length < 3) { setData(null); return; }
    setLoading(true);
    const r = await fetch(`/api/compare/suggest?${new URLSearchParams(params())}`).catch(() => null);
    setLoading(false);
    if (r?.ok) setData(await r.json());
  }, [term, params]);

  useEffect(() => { const t = setTimeout(() => setTerm(q.trim()), 400); return () => clearTimeout(t); }, [q]);
  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!job || job.state !== "running") return;
    const t = setInterval(async () => {
      const j = await pollJob(job.id);
      if (!j) return;
      setJob(j);
      if (j.state !== "running") { reportJob(j, "Naming flows", "Named flows are ready"); load(); }
    }, 2000);
    return () => clearInterval(t);
  }, [job, load]);

  async function askClaude() {
    const j = await startJob("/api/jobs/suggest", params(), "Naming flows");
    if (j) setJob(j);
  }

  function use(f: SFlow) {
    try { sessionStorage.setItem("atlas.flowDraft", JSON.stringify(toDraft(f))); } catch { /* ignore */ }
    router.push("/compare/flows/new?draft=1");
  }

  const running = job?.state === "running";
  const ai: SFlow[] = data?.ai?.flows ?? [];
  const code: SFlow[] = data?.quick?.flows ?? [];

  return (
    <section className="card">
      <div className="card-head">
        <SparkIcon size={16} />
        <h2>Suggested flows</h2>
        <span className="sub">Type what you're testing, or a program, and Atlas suggests flows from the code</span>
      </div>
      <div className="card-body" style={{ paddingBottom: 8 }}>
        <div className="sugg-search">
          <SearchIcon size={16} />
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. transfer, order, purchase order, LG.PO.MAINT"
            autoFocus={!compact} />
          {loading && <span className="spinner" />}
        </div>
        <div className="chips" style={{ marginTop: 10 }}>
          {TOPICS.map((t) => <button key={t} className="chip" style={{ fontFamily: "var(--sans)" }} onClick={() => setQ(t)}>{t}</button>)}
        </div>
      </div>

      {data?.quick && (
        <>
          <div className="toolbar" style={{ borderTop: "1px solid var(--border)" }}>
            <span className="sub">Programs found:</span>
            {data.quick.programs.length === 0 && <span className="sub">none. Try another word or a program name.</span>}
            {data.quick.programs.map((p: string) => (
              <Link key={p} href={`/program/${encodeURIComponent(p)}`} className="chip">{p}</Link>
            ))}
            <span className="spacer" />
            {data.quick.programs.length > 0 && (
              <button className={ai.length ? "" : "primary"} onClick={askClaude} disabled={running}>
                {running ? <><span className="spinner" /> Claude is reading the code…</>
                  : ai.length ? <><SyncIcon size={14} /> Refresh named flows</> : <><SparkIcon size={14} /> Name the flows with Claude</>}
              </button>
            )}
          </div>
          {running && job && (
            <div style={{ padding: "0 20px 14px" }}>
              <JobProgress job={job} title="Claude is reading the code and naming flows" expectedKind="suggest"
                hint="Usually about a minute; uses your Claude Code plan." />
            </div>
          )}

          {ai.length > 0 && (
            <div className="sugg-list">
              <div className="sugg-section">
                Named by Claude from the code
                <span className="faint"> · {data.ai.created_at ? ago(data.ai.created_at) : ""}</span>
              </div>
              {ai.map((f, i) => <FlowCard key={f.name + i} f={f} onUse={() => use(f)} />)}
            </div>
          )}

          {code.length > 0 && (
            <div className="sugg-list">
              <div className="sugg-section">
                {ai.length ? "Or everything a program writes" : "From the code right now"}
                {!ai.length && <span className="faint"> · press “Name the flows with Claude” to get flows like “Create transfer” or “Ship using serial numbers”</span>}
              </div>
              {code.map((f, i) => <FlowCard key={f.name + i} f={f} onUse={() => use(f)} />)}
            </div>
          )}
        </>
      )}
    </section>
  );
}
