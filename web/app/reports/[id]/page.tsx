import Link from "next/link";
import ReportActions from "@/components/ReportActions";
import { ErrorBox, PageHeader } from "@/components/ui";
import { api } from "@/lib/api";

export default async function ReportPage({ params }: { params: { id: string } }) {
  const r: any = await api(`/api/reports/${params.id}`).catch(() => null);
  if (!r) return <ErrorBox error="Report not found. It may have been deleted." />;
  const when = new Date(r.created_at).toLocaleString("en-GB", { dateStyle: "medium", timeStyle: "short" });
  return (
    <>
      <PageHeader eyebrow={<Link href="/reports">Reports</Link>} title={r.title}
        desc={<>From <Link href={r.page} className="mono">{r.page}</Link> · {r.pages} page{r.pages === 1 ? "" : "s"} · created {when} · git main {r.git_sha || "—"} · {r.environment}</>}
        actions={<ReportActions id={r.id} />} />
      <section className="card report-frame">
        <iframe src={`/api/reports/${r.id}/pdf`} title={r.title} />
      </section>
    </>
  );
}
