import Link from "next/link";
import QuickCompare from "@/components/compare/QuickCompare";
import SuggestFlows from "@/components/compare/SuggestFlows";
import { CompareIcon, PlusIcon } from "@/components/Icons";
import { Card, EmptyState, ErrorBox, PageHeader } from "@/components/ui";
import { ago, api, enc } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ComparePage() {
  let flows: any, runs: any;
  try {
    [flows, runs] = await Promise.all([api("/api/compare/flows"), api("/api/compare/runs?limit=10")]);
  } catch (e) {
    return <ErrorBox error={e} />;
  }
  return (
    <>
      <PageHeader
        title="Compare"
        desc="Do the same thing in the old system and in ERP Next, then compare every file it touches, field by field, at each step: after create, after ship, and so on. Notes you add are kept for the next run."
        actions={<>
          <Link href="/test-data" className="btn">Find test data</Link>
          <Link href="/compare/flows/new" className="btn primary"><PlusIcon size={14} /> New flow</Link>
        </>}
      />

      <div className="stack">
        <SuggestFlows compact />

        <Card title="Flows" sub="Reusable test definitions: steps and the files they touch">
          {flows.flows.length === 0 ? (
            <EmptyState title="No flows yet" icon={<CompareIcon size={20} />}>
              Create one for something you test repeatedly, e.g. “Order entry” with steps After create → After ship → After invoice,
              touching ORDER, ORDER-LOG and OLD-INVOICES. <Link href="/compare/flows/new">Create a flow</Link>
            </EmptyState>
          ) : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Flow</th><th className="num">Steps</th><th className="num">Files</th><th className="num">Runs</th><th className="nowrap">Last run</th><th className="w-min" /></tr></thead>
                <tbody>
                  {flows.flows.map((f: any) => (
                    <tr key={f.id}>
                      <td className="trunc">
                        <span>
                          <Link href={`/compare/flows/${f.id}`} style={{ fontWeight: 600 }}>{f.name}</Link>
                          {f.description && <span className="sub"> · {f.description}</span>}
                        </span>
                      </td>
                      <td className="num">{f.steps}</td>
                      <td className="num">{f.files}</td>
                      <td className="num">{f.runs}</td>
                      <td className="nowrap sub">{f.last_run ? ago(f.last_run) : "never"}</td>
                      <td className="w-min"><Link href={`/compare/flows/${f.id}#start`} className="btn sm">New run</Link></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        {runs.runs.length > 0 && (
          <Card title="Recent runs">
            <div className="table-wrap">
              <table>
                <thead><tr><th>Run</th><th>Flow</th><th>Old key</th><th>New key</th><th className="nowrap">Updated</th></tr></thead>
                <tbody>
                  {runs.runs.map((r: any) => (
                    <tr key={r.id}>
                      <td className="trunc"><span><Link href={`/compare/runs/${r.id}`} style={{ fontWeight: 600 }}>{r.name}</Link></span></td>
                      <td className="nowrap"><Link href={`/compare/flows/${enc(r.flow_id)}`}>{r.flow_name}</Link></td>
                      <td className="mono nowrap">{r.legacy_key || "—"}</td>
                      <td className="mono nowrap">{r.new_key || "—"}</td>
                      <td className="nowrap sub">{ago(r.updated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>
        )}

        <QuickCompare />
      </div>
    </>
  );
}
