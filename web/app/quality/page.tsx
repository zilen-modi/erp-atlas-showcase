import Link from "next/link";
import QualityStart from "@/components/QualityStart";
import { Card, EmptyState, ErrorBox, PageHeader } from "@/components/ui";
import { ago, api, enc, fmtNum } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function QualityPage() {
  let rows: any[];
  try {
    rows = await api("/api/profiles");
  } catch (e) {
    return <ErrorBox error={e} />;
  }
  return (
    <>
      <PageHeader title="Data quality"
        desc="What the Pick files really hold on TEST, before anything is migrated: values that break the DICT, attributes the DICT doesn't know about, and values that point to records that don't exist." />
      <div className="stack">
        <QualityStart />
        <Card title="Profiled files" sub={rows.length ? `${rows.length} file${rows.length === 1 ? "" : "s"}, worst first` : undefined}>
          {rows.length === 0 ? <EmptyState title="Nothing profiled yet">Pick a file above, e.g. TRANSFER, ORDER or PRODUCT.</EmptyState> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>File</th><th className="num">Records sampled</th><th className="num">Errors</th><th className="num">Warnings</th><th>Profiled</th></tr></thead>
                <tbody>
                  {rows.map((r) => (
                    <tr key={r.id}>
                      <td><Link href={`/files/${enc(r.pick_file)}/profile`} className="mono" style={{ fontWeight: 600 }}>{r.pick_file}</Link></td>
                      <td className="num">{fmtNum(r.records)}</td>
                      <td className="num">{r.errors ? <span className="badge red">{r.errors}</span> : <span className="faint">0</span>}</td>
                      <td className="num">{r.warnings ? <span className="badge amber">{r.warnings}</span> : <span className="faint">0</span>}</td>
                      <td className="sub">{ago(r.finished_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
