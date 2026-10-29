import Link from "next/link";
import { StatusBadge } from "@/lib/parity";
import { Card, EmptyState, ErrorBox, PageHeader, Stat, Toolbar } from "@/components/ui";
import { ReportIcon } from "@/components/Icons";
import { api, enc, fmtNum } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function LegacyReports({ searchParams }: { searchParams: { q?: string; kind?: string; status?: string; screens?: string } }) {
  const q = searchParams.q ?? "", kind = searchParams.kind ?? "", status = searchParams.status ?? "";
  const screens = searchParams.screens === "1";
  let d: any;
  try {
    d = await api(`/api/legacy-reports?${new URLSearchParams({ q, kind, status, ...(screens ? { screens: "true" } : {}) })}`);
  } catch (e) {
    return <ErrorBox error={e} />;
  }
  const link = (p: Record<string, string>) => `/legacy-reports?${new URLSearchParams({ ...(q ? { q } : {}), ...(kind ? { kind } : {}), ...(status ? { status } : {}), ...(screens ? { screens: "1" } : {}), ...p })}`;
  return (
    <>
      <PageHeader eyebrow="Browse" title="Report catalogue"
        desc="Every report the old system produces: PROC reports (SORT/LIST with a heading) and programs launched from a menu or job that print or export to Excel. Mark each one built, replaced by a standard ERP Next report, or not needed." />
      <div className="grid cols-4" style={{ marginBottom: 16 }}>
        <Stat icon={<ReportIcon size={18} />} label="Reports" value={fmtNum(d.total)} note={`${d.screen_exports} screen exports ${screens ? "included" : "hidden"}`} />
        <Stat icon={<ReportIcon size={18} />} label="Decided" value={fmtNum(d.decided)} note="built, standard or not needed" />
        <Stat icon={<ReportIcon size={18} />} label="Decided, weighted by use" value={`${d.decided_by_use_pct}%`} note="share of menu launches covered" />
        <Stat icon={<ReportIcon size={18} />} label="To do" value={fmtNum(d.total - d.decided)} note="most-used first below" />
      </div>
      <Card>
        <Toolbar action="/legacy-reports" q={q} placeholder="Filter by name, title or file, e.g. STOCK or TRANSFER">
          {kind && <input type="hidden" name="kind" value={kind} />}
          {status && <input type="hidden" name="status" value={status} />}
          {screens && <input type="hidden" name="screens" value="1" />}
          <div className="seg">
            <Link href={link({ kind: "" })} className={!kind ? "active" : ""}>All</Link>
            <Link href={link({ kind: "program" })} className={kind === "program" ? "active" : ""}>Programs</Link>
            <Link href={link({ kind: "proc" })} className={kind === "proc" ? "active" : ""}>PROC reports</Link>
          </div>
          <div className="seg">
            <Link href={link({ status: "" })} className={!status ? "active" : ""}>Any status</Link>
            <Link href={link({ status: "todo" })} className={status === "todo" ? "active" : ""}>To do</Link>
          </div>
          <Link href={screens ? link({ screens: "" }).replace(/&?screens=1/, "") : link({ screens: "1" })} className="btn ghost sm">{screens ? "Hide" : "Show"} screen exports</Link>
        </Toolbar>
        {d.reports.length === 0 ? <EmptyState title="No reports match" /> : (
          <div className="table-wrap tall">
            <table>
              <thead><tr><th>Report</th><th>Output</th><th className="num">Launches</th><th>Reads</th><th>Menu</th><th>ERP Next</th></tr></thead>
              <tbody>
                {d.reports.map((r: any) => (
                  <tr key={r.kind + r.name}>
                    <td style={{ minWidth: 0 }}>
                      <Link href={`/legacy-reports/${enc(r.name)}`} style={{ fontWeight: 600 }}>{r.title}</Link>
                      <div className="sub mono">{r.name} <span className="faint">· {r.kind === "proc" ? "PROC" : r.type === "screen export" ? "screen export" : "program"}</span></div>
                    </td>
                    <td className="nowrap sub">{r.output}</td>
                    <td className="num">{r.launches ? fmtNum(r.launches) : <span className="faint">—</span>}</td>
                    <td className="sub trunc" title={r.files.join(", ")}><span className="mono">{r.files.slice(0, 3).join(", ") || "—"}</span></td>
                    <td className="sub nowrap">{r.menus.slice(0, 2).map((m: string, i: number) => <span key={m}>{i > 0 && ", "}<Link href={`/menu/${enc(m)}`} className="mono">{m}</Link></span>)}</td>
                    <td><StatusBadge status={r.status} />{r.target && <div className="sub ellipsis" style={{ maxWidth: 180 }}>{r.target}</div>}</td>
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
