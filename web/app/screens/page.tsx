import Link from "next/link";
import { Card, EmptyState, ErrorBox, PageHeader, Toolbar } from "@/components/ui";
import { api, enc, fmtNum } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ScreensPage({ searchParams }: { searchParams: { q?: string } }) {
  const q = searchParams.q ?? "";
  let d: any;
  try {
    d = await api(`/api/screens?q=${enc(q)}&limit=300`);
  } catch (e) {
    return <ErrorBox error={e} />;
  }
  return (
    <>
      <PageHeader eyebrow="Browse" title="Screens"
        desc="Every AccuTerm GUI screen in src/TEMPLATES, drawn from its definition and wired to the code: which handler each button runs, which files it writes, and which field each box shows." />
      <Card>
        <Toolbar action="/screens" q={q} placeholder="Filter by screen, program, control or caption, e.g. Ship Via" />
        {d.screens.length === 0 ? <EmptyState title="No screens match" /> : (
          <div className="table-wrap tall">
            <table>
              <thead><tr><th>Screen</th><th>Program</th><th className="num">Forms</th><th className="num">Controls</th><th className="num">Menu launches</th><th>Saved in designer</th></tr></thead>
              <tbody>
                {d.screens.map((s: any) => (
                  <tr key={s.project}>
                    <td><Link href={`/screen/${enc(s.project)}`} className="mono" style={{ fontWeight: 600 }}>{s.project}</Link>
                      <div className="sub ellipsis" style={{ maxWidth: 420 }}>{s.form_list[0]?.title}</div></td>
                    <td className="mono sub">{s.program}</td>
                    <td className="num">{s.forms}</td>
                    <td className="num">{fmtNum(s.controls)}</td>
                    <td className="num">{s.launches ? fmtNum(s.launches) : <span className="faint">—</span>}</td>
                    <td className="sub nowrap">{s.saved_at ?? "—"}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="card-foot"><span className="sub">{fmtNum(d.total)} screens{q ? ` matching “${q}”` : ""}, most-used first.</span></div>
      </Card>
    </>
  );
}
