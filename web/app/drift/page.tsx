import Link from "next/link";
import JobButton from "@/components/JobButton";
import { Badge, Card, EmptyState, ErrorBox, PageHeader, ProgramLink } from "@/components/ui";
import { ago, api, enc, fmtNum } from "@/lib/api";

export const dynamic = "force-dynamic";

const STATE_LABEL: Record<string, [string, string]> = {
  drift: ["Different", "amber"], cosmetic: ["Cosmetic only", ""], identical: ["Same as git", "green"],
};

export default async function DeploymentPage({ searchParams }: { searchParams: { state?: string } }) {
  let d: any;
  try {
    d = await api("/api/drift");
  } catch (e) {
    return <ErrorBox error={e} />;
  }
  const state = searchParams.state;
  const rows = (d.programs as any[]).filter((r) => !state || r.state === state);
  return (
    <>
      <PageHeader
        eyebrow="Deployment check"
        title="TEST vs git"
        desc="Git main is the source of truth. This page only shows which of the checked programs the TEST server runs a different version of, so a deployment can bring it back in line."
        actions={<JobButton endpoint="/api/jobs/sync" body={{ live: true, budget: 10 }} label="Check 10 more"
          confirm="Compare 10 more of the most-used programs with the TEST server? Needs VPN." />}
      />
      <Card>
        <div className="toolbar">
          <div className="seg">
            <Link href="/drift" className={!state ? "active" : ""}>All · {d.programs.length}</Link>
            {["drift", "cosmetic", "identical"].map((s) => (
              <Link key={s} href={`/drift?state=${s}`} className={state === s ? "active" : ""}>{STATE_LABEL[s][0]} · {d.totals[s] ?? 0}</Link>
            ))}
          </div>
        </div>
        {rows.length === 0 ? <EmptyState title="Nothing checked yet">Use “Check 10 more” to compare programs with TEST.</EmptyState> : (
          <div className="table-wrap tall">
            <table>
              <thead>
                <tr><th>Program</th><th>On TEST</th><th className="num">Differences</th><th>TEST matches git</th><th className="num">Launches</th><th className="nowrap">Checked</th></tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.program}>
                    <td className="nowrap"><ProgramLink name={r.program} strong /></td>
                    <td><Badge kind={STATE_LABEL[r.state]?.[1] ?? ""}>{STATE_LABEL[r.state]?.[0] ?? r.state}</Badge></td>
                    <td className="num">{r.real_hunks ? <Link href={`/drift/${enc(r.program)}`}>{r.real_hunks}</Link> : <span className="faint">—</span>}</td>
                    <td className="sub nowrap">
                      {r.test_version ? <><code>{r.test_version.sha.slice(0, 9)}</code> {r.test_version.date}{r.test_version.behind > 0 && ` · ${r.test_version.behind} behind`}</> : "—"}
                    </td>
                    <td className="num">{fmtNum(r.reached_launches)}</td>
                    <td className="nowrap sub">{ago(r.live_fetched_at)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </Card>
    </>
  );
}
