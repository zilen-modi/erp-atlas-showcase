import Link from "next/link";
import { SCHED_CLS, StatusBadge } from "@/lib/parity";
import { Card, EmptyState, ErrorBox, PageHeader, Toolbar } from "@/components/ui";
import { api, enc, fmtNum } from "@/lib/api";

export const dynamic = "force-dynamic";

const SCHEDULES: [string, string][] = [["", "All"], ["nightly", "Nightly"], ["daily", "Daily"], ["weekly", "Weekly"],
  ["month-end", "Month-end"], ["year-end", "Year-end"], ["on demand", "On demand"]];

export default async function JobsPage({ searchParams }: { searchParams: { schedule?: string; q?: string } }) {
  const schedule = searchParams.schedule ?? "";
  const q = searchParams.q ?? "";
  let d: any, all: any;
  try {
    [d, all] = await Promise.all([api(`/api/bg-jobs?schedule=${enc(schedule)}&q=${enc(q)}`), api(`/api/bg-jobs?q=${enc(q)}`)]);
  } catch (e) {
    return <ErrorBox error={e} />;
  }
  const qs = (s: string) => `/jobs?${new URLSearchParams({ ...(s ? { schedule: s } : {}), ...(q ? { q } : {}) })}`;
  return (
    <>
      <PageHeader eyebrow="Browse" title="Background jobs"
        desc="The PROC scripts in src/PROK: nightly, month-end and year-end processing, and the procs menus launch. What each runs, what it changes, and what replaces it in ERP Next." />
      <nav className="tabs">
        {SCHEDULES.map(([k, label]) => (
          <Link key={k} href={qs(k)} className={schedule === k ? "active" : ""}>
            {label} <span className="faint">{k ? all.by_schedule[k] ?? 0 : all.total}</span>
          </Link>
        ))}
      </nav>
      <Card>
        <Toolbar action="/jobs" q={q} placeholder="Filter by name or description, e.g. EOM or cash">
          {schedule && <input type="hidden" name="schedule" value={schedule} />}
        </Toolbar>
        {d.jobs.length === 0 ? <EmptyState title="No jobs match" /> : (
          <div className="table-wrap tall">
            <table>
              <thead><tr><th>Job</th><th>When</th><th className="num">Programs</th><th className="num">Reports</th><th>Launched by</th><th>ERP Next</th></tr></thead>
              <tbody>
                {d.jobs.slice(0, 400).map((j: any) => (
                  <tr key={j.name}>
                    <td style={{ minWidth: 0 }}>
                      <Link href={`/jobs/${enc(j.name)}`} className="mono" style={{ fontWeight: 600 }}>{j.name}</Link>
                      {j.destructive > 0 && <span className="badge red" style={{ marginLeft: 6 }} title="Runs CLEAR-FILE or DELETE">clears data</span>}
                      <div className="sub ellipsis" style={{ maxWidth: 480 }}>{j.title}</div>
                    </td>
                    <td><span className={`badge ${SCHED_CLS[j.schedule] ?? ""}`}>{j.schedule}</span></td>
                    <td className="num">{j.programs || <span className="faint">—</span>}</td>
                    <td className="num">{j.reports || <span className="faint">—</span>}</td>
                    <td className="sub nowrap">
                      {j.menus.length > 0 ? j.menus.map((m: string, i: number) => <span key={m}>{i > 0 && ", "}<Link href={`/menu/${enc(m)}`} className="mono">{m}</Link></span>)
                        : j.called_by ? `${j.called_by} other proc${j.called_by === 1 ? "" : "s"}` : <span className="faint">—</span>}
                      {j.launches > 0 && <div className="faint">{fmtNum(j.launches)} launches</div>}
                    </td>
                    <td><StatusBadge status={j.status} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="card-foot"><span className="sub">{fmtNum(d.total)} jobs{d.total > 400 ? " (first 400 shown: filter to narrow)" : ""}. When a job runs is inferred from its name, its text and SLEEP commands; check the job page for the evidence.</span></div>
      </Card>
    </>
  );
}
