import Link from "next/link";
import AskButton from "@/components/AskButton";
import ParityEditor from "@/components/ParityEditor";
import { SCHED_CLS } from "@/lib/parity";
import { Card, ErrorBox, PageHeader } from "@/components/ui";
import { api, enc, fmtNum } from "@/lib/api";

export const dynamic = "force-dynamic";

const STEP: Record<string, [string, string]> = {
  run: ["runs", "blue"], proc: ["calls proc", "violet"], report: ["report", "green"], select: ["selects", ""],
  destructive: ["CLEARS", "red"], sleep: ["waits", "amber"], spool: ["printer", ""], tcl: ["TCL", ""], call: ["runs", ""],
};

export default async function JobPage({ params }: { params: { name: string } }) {
  const name = decodeURIComponent(params.name);
  let j: any;
  try {
    j = await api(`/api/bg-jobs/${enc(name)}?track=true`);
  } catch (e) {
    return <ErrorBox error={e} />;
  }
  const steps = (j.commands as any[]).filter((c) => c.kind !== "spool" && !(c.kind === "tcl" && /^(ECHO|TERM|CLEARCOMMON|TIME|WHO)/i.test(c.text)));
  return (
    <>
      <PageHeader eyebrow={<Link href="/jobs">Background jobs</Link>} title={j.name} mono
        meta={<>
          <span className={`badge ${SCHED_CLS[j.schedule] ?? ""}`}>{j.schedule}</span><span>·</span>
          <span>{j.kind === "menu" ? "PROC menu" : "PROC"} · {fmtNum(j.lines)} lines</span>
          {j.menus.length > 0 && <><span>·</span><span>launched from {j.menus.map((m: any, i: number) => <span key={m.code}>{i > 0 && ", "}<Link href={`/menu/${enc(m.code)}`} className="mono">{m.code}</Link>{m.used ? ` (${fmtNum(m.used)})` : ""}</span>)}</span></>}
          {j.called_by.length > 0 && <><span>·</span><span>called by {j.called_by.slice(0, 5).map((c: string, i: number) => <span key={c}>{i > 0 && ", "}<Link href={`/jobs/${enc(c)}`} className="mono">{c}</Link></span>)}{j.called_by.length > 5 && ` +${j.called_by.length - 5}`}</span></>}
        </>}
        desc={j.title !== j.description ? <>{j.title}{j.description && <div className="sub" style={{ marginTop: 4 }}>{j.description}</div>}</> : j.title}
        actions={<AskButton question={`Explain the ${j.name} PROC in src/PROK: when it runs, what it does step by step, which files it changes, and what would need to replace it in ERP Next.`} />}
      />
      {j.destructive.length > 0 && (
        <div className="notice bad" style={{ marginBottom: 16 }}>
          This job clears or deletes data: {j.destructive.map((d: any) => <code key={d.line} style={{ marginRight: 8 }}>{d.text}</code>)}
        </div>
      )}
      <div className="grid side">
        <div className="stack">
          <Card title="What it does, in order" sub={`${steps.length} steps`}>
            <ol className="job-steps">
              {steps.map((c: any, i: number) => {
                const [label, cls] = STEP[c.kind] ?? [c.kind, ""];
                return (
                  <li key={i}>
                    <span className={`badge ${cls}`}>{label}</span>
                    <div style={{ minWidth: 0 }}>
                      {c.kind === "run" || c.kind === "call" ? <Link href={`/program/${enc(c.target)}`} className="mono" style={{ fontWeight: 600 }}>{c.target}</Link>
                        : c.kind === "proc" ? <Link href={`/jobs/${enc(c.target)}`} className="mono" style={{ fontWeight: 600 }}>{c.target}</Link>
                          : c.kind === "report" || c.kind === "select" ? <><Link href={`/files/${enc(c.target)}`} className="mono" style={{ fontWeight: 600 }}>{c.target}</Link>{c.heading && <span> · “{c.heading}”</span>}{c.printed && <span className="badge" style={{ marginLeft: 6 }}>printed</span>}</>
                            : null}
                      <div className="mono sub job-cmd" title={c.text}>{c.text}</div>
                      {c.columns?.length > 0 && <div className="sub">columns: {c.columns.slice(0, 14).join(", ")}</div>}
                    </div>
                  </li>
                );
              })}
            </ol>
            {j.menu_items.length > 0 && (
              <div className="card-body">
                <div className="sc-h">Menu items</div>
                {j.menu_items.map((m: any, i: number) => <div key={i} className="sub"><b>{m.caption}</b> {m.command && <code>{m.command}</code>}</div>)}
              </div>
            )}
          </Card>
        </div>
        <div className="stack">
          <ParityEditor kind="job" name={j.name} parity={j.parity} statuses={j.statuses} />
          <Card title="Changes" sub={`${j.writes.length} files`}>
            <div className="card-body stack" style={{ gap: 12 }}>
              {j.writes.length ? <div className="chips">{j.writes.map((w: string) => <Link key={w} href={`/files/${enc(w)}`} className="chip mono">{w}</Link>)}</div>
                : <div className="sub">The programs it runs don't write any Pick file directly (reports only, or work done by procs it calls).</div>}
              {j.counters.length > 0 && <div><div className="sc-h">Control counters</div><div className="chips">{j.counters.map((c: string) => <span key={c} className="chip mono" title="CONTROL record incremented by the programs it runs">{c}</span>)}</div></div>}
            </div>
          </Card>
          {j.programs.length > 0 && (
            <Card title="Programs it runs">
              <div className="mini-list">
                {j.programs.map((p: any) => (
                  <Link key={p.name} href={`/program/${enc(p.name)}`} className="mini">
                    <span className="mono" style={{ fontWeight: 600 }}>{p.name}</span>
                    <span className="sub ellipsis" style={{ flex: 1 }}>{p.writes.length ? `writes ${p.writes.slice(0, 4).join(", ")}${p.writes.length > 4 ? "…" : ""}` : "no direct writes"}</span>
                  </Link>
                ))}
              </div>
            </Card>
          )}
          {j.calls.length > 0 && (
            <Card title="Procs it calls">
              <div className="chips card-body">{j.calls.map((c: string) => <Link key={c} href={`/jobs/${enc(c)}`} className="chip mono">{c}</Link>)}</div>
            </Card>
          )}
        </div>
      </div>
    </>
  );
}
