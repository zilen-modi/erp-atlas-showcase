import Link from "next/link";
import ReportActions from "@/components/ReportActions";
import { EmptyState, PageHeader } from "@/components/ui";
import { ago, api } from "@/lib/api";

export default async function ReportsPage() {
  const rows: any[] = await api("/api/reports").catch(() => []);
  return (
    <>
      <PageHeader title="Reports" desc="PDF exports of Atlas pages. Use Export in the top bar on any page to add one; share the link or the file." />
      {rows.length === 0 ? (
        <EmptyState title="No reports yet">Open any page (a program, a flow, a compare run, a chat) and choose Export → PDF report of this page.</EmptyState>
      ) : (
        <section className="card">
          <div className="table-wrap">
            <table>
              <thead><tr><th>Report</th><th>Page</th><th className="num">Pages</th><th>Source</th><th>Created</th><th className="w-min" /></tr></thead>
              <tbody>
                {rows.map((r) => (
                  <tr key={r.id}>
                    <td style={{ fontWeight: 600 }}><Link href={`/reports/${r.id}`}>{r.title}</Link></td>
                    <td className="mono sub"><Link href={r.page}>{r.page}</Link></td>
                    <td className="num">{r.pages}</td>
                    <td className="mono sub">git {r.git_sha || "—"} · {r.environment}</td>
                    <td className="sub nowrap">{ago(r.created_at)}</td>
                    <td className="w-min"><ReportActions id={r.id} compact /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}
    </>
  );
}
