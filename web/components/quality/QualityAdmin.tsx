"use client";

import { useEffect, useState } from "react";
import { errorText, toast } from "@/components/Toaster";
import { ago } from "@/lib/api";
import { cancelJob, type Job, pollJob, reportJob, startJob } from "@/lib/jobs";

type Case = { id: string; status: string; q: string; expected: string; must_cite: string[]; reviewed_by?: string };
type Res = { id: string; status: string; q: string; score: number; error?: string | null; missing_cites?: string[];
  citations?: { cites: number; problems: { cite: string; why: string }[] };
  verdict?: { score: number; missing: string[]; contradicted: string[] } | null };
type Run = { run: string; at: string; model: string; cases: number; cost_usd: number;
  verified: { n: number; score: number | null }; draft: { n: number; score: number | null }; results?: Res[] };
type Cand = { answer_id: string; question: string; correction: string; user: string; created_at: string };

const pct = (x: number | null | undefined) => (x == null ? "—" : `${Math.round(x * 100)}%`);

// Is Ask Atlas getting better or worse? The golden questions, asked and scored; and the cases to grow it from.
export default function QualityAdmin() {
  const [d, setD] = useState<{ cases: Case[]; runs: Run[]; candidates: Cand[] } | null>(null);
  const [job, setJob] = useState<Job | null>(null);
  const [open, setOpen] = useState<string | null>(null);
  const load = () => fetch("/api/eval").then((r) => (r.ok ? r.json() : null)).then(setD).catch(() => null);
  useEffect(() => { load(); }, []);
  useEffect(() => {
    if (!job || job.state !== "running") return;
    const t = setInterval(async () => {
      const j = await pollJob(job.id);
      if (!j) return;
      setJob(j);
      if (j.state !== "running") { reportJob(j, "Answer-quality run"); load(); }
    }, 3000);
    return () => clearInterval(t);
  }, [job]);   // eslint-disable-line react-hooks/exhaustive-deps

  async function post(path: string, body: unknown, ok: string) {
    const r = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }).catch(() => null);
    if (!r?.ok) { toast.error("Couldn't save", await errorText(r)); return; }
    toast.success(ok);
    load();
  }
  function verify(c: Case) {
    const expected = window.prompt(`The correct answer to “${c.q}” (it's what answers are graded against):`, c.expected);
    if (expected === null) return;
    post(`/api/eval/cases/${c.id}/verify`, { expected }, `${c.id} verified: it now counts toward the score`);
  }
  async function run() {
    if (!window.confirm(`Ask all ${d?.cases.length} golden questions on your Claude and score the answers? Each is a full Ask Atlas answer, so this uses a fair share of your plan.`)) return;
    const j = await startJob("/api/jobs/ask-eval", {}, "Answer-quality run");
    if (j) setJob(j);
  }

  if (!d) return null;
  const last = d.runs[0];
  const prev = d.runs[1];
  const byId = new Map((last?.results ?? []).map((r) => [r.id, r]));
  const busy = job?.state === "running";
  const verified = d.cases.filter((c) => c.status === "verified").length;
  const trend = last && prev && last.verified.score != null && prev.verified.score != null ? last.verified.score - prev.verified.score : null;
  return (
    <section className="card" id="quality">
      <div className="card-head"><h2>Answer quality</h2><span className="sub">Golden questions asked and scored, so a change that makes answers worse shows up</span></div>
      <div className="card-body stack">
        <div className="kn-stats">
          <div><span className="faint">Verified cases</span><strong>{pct(last?.verified.score)}</strong>
            <small className="faint">{verified} of {d.cases.length} verified{trend != null ? ` · ${trend >= 0 ? "+" : ""}${Math.round(trend * 100)} since last run` : ""}</small></div>
          <div><span className="faint">Draft cases</span><strong>{pct(last?.draft.score)}</strong><small className="faint">not counted until verified</small></div>
          <div><span className="faint">Last run</span><strong>{last ? ago(last.at) : "never"}</strong><small className="faint">{last ? `${last.model} · $${last.cost_usd.toFixed(2)}` : "Run it to get a baseline"}</small></div>
        </div>
        <p className="sub">Each case scores: does the answer cite the programs it must, do all its citations check out against git, and (where the case has a correct answer) does it say the same thing, graded by Claude. Contradicting the correct answer caps a case at 30%. Verify a case once the expected answer is right: only verified cases count.</p>
        <div className="kn-run">
          {busy ? <button className="sm" onClick={() => job && cancelJob(job.id)}>Stop after this question</button>
            : <button className="primary" onClick={run}>Run all {d.cases.length} questions</button>}
        </div>
        {job && <pre className="kn-log">{job.log.filter((l) => !l.startsWith("Thinking")).slice(-6).join("\n") || "Starting…"}</pre>}

        <div className="table-wrap mid">
          <table className="acct-table">
            <thead><tr><th>Case</th><th>Question</th><th className="num">Last score</th><th>Issues</th><th /></tr></thead>
            <tbody>
              {d.cases.map((c) => {
                const r = byId.get(c.id);
                const issues = r ? [
                  r.error && "didn't answer",
                  r.missing_cites?.length ? `didn't cite ${r.missing_cites.join(", ")}` : "",
                  r.citations?.problems.length ? `${r.citations.problems.length} citation${r.citations.problems.length === 1 ? "" : "s"} don't check out` : "",
                  r.verdict?.contradicted.length ? `contradicts: ${r.verdict.contradicted[0]}` : "",
                  r.verdict?.missing.length ? `misses: ${r.verdict.missing[0]}` : "",
                ].filter(Boolean) : [];
                return (
                  <tr key={c.id}>
                    <td className="nowrap"><span className="mono">{c.id}</span> {c.status === "verified"
                      ? <span className="badge green" title={c.reviewed_by ? `verified by ${c.reviewed_by}` : undefined}>verified</span>
                      : <span className="badge">draft</span>}</td>
                    <td className="en-what">{c.q}{!c.expected && <div className="faint">no correct answer written yet</div>}</td>
                    <td className="num">{r ? <span className={`badge ${r.score >= 0.8 ? "green" : r.score >= 0.5 ? "amber" : "red"}`}>{pct(r.score)}</span> : "—"}</td>
                    <td className="en-what">
                      {issues.length === 0 ? <span className="faint">{r ? "none" : "not run yet"}</span> : (
                        <button className="ghost sm" onClick={() => setOpen(open === c.id ? null : c.id)}>{issues[0]}{issues.length > 1 ? ` +${issues.length - 1}` : ""}</button>
                      )}
                      {open === c.id && <ul className="q-issues">{issues.map((x, i) => <li key={i}>{x}</li>)}</ul>}
                    </td>
                    <td className="acct-actions">{c.status !== "verified" && <button className="sm ghost" onClick={() => verify(c)}>Verify…</button>}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>

        {d.candidates.length > 0 && (
          <div className="stack">
            <h3 className="q-h3">From thumbs-down answers</h3>
            <p className="sub">People marked these answers wrong and said what's right. Add one as a case so the same mistake is caught next time.</p>
            {d.candidates.map((c) => (
              <div key={c.answer_id} className="q-cand">
                <div><b>{c.question}</b><div className="sub">Correction from {c.user.split(" <")[0]}, {ago(c.created_at)}: {c.correction}</div></div>
                <button className="sm" onClick={() => post("/api/eval/cases", { answer_id: c.answer_id }, "Added as a draft case")}>Add as case</button>
              </div>
            ))}
          </div>
        )}
      </div>
    </section>
  );
}
