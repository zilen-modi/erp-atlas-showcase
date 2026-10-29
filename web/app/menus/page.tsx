import Link from "next/link";
import { Card, EmptyState, ErrorBox, PageHeader, Pager, ProgramLink, Toolbar, UsageBar } from "@/components/ui";
import { api, enc, fmtNum } from "@/lib/api";

export const dynamic = "force-dynamic";
const PAGE = 100;

export default async function MenusPage({ searchParams }: { searchParams: { q?: string; page?: string } }) {
  const q = searchParams.q ?? "";
  const page = Math.max(0, parseInt(searchParams.page ?? "0", 10) || 0);
  let d: any, all: any;
  try {
    [d, all] = await Promise.all([api(`/api/menus?q=${enc(q)}&limit=${PAGE}&offset=${page * PAGE}`), api("/api/menus?limit=1")]);
  } catch (e) {
    return <ErrorBox error={e} />;
  }
  const top = all.menus[0]?.used || 1;
  const pages = Math.ceil(d.total / PAGE);
  const qs = (p: number) => `/menus?${new URLSearchParams({ ...(q ? { q } : {}), page: String(p) })}`;
  return (
    <>
      <PageHeader
        eyebrow="Browse"
        title="Menus"
        desc={<>Every menu item ranked by real launches (MENU-ITEMS <code>#USED</code>): {fmtNum(all.launches)} launches across {fmtNum(all.total)} menus. Start from the top.</>}
      />
      <Card>
        <Toolbar action="/menus" q={q} placeholder="Filter by menu code or command, e.g. M44 or XFR" />
        {d.menus.length === 0 ? <EmptyState title="No menus match">Try a shorter code, like M44.</EmptyState> : (
          <div className="table-wrap tall">
            <table>
              <thead>
                <tr>
                  <th className="w-min">#</th><th>Menu</th><th>Runs</th><th className="num">Launches</th>
                  <th style={{ width: "18%" }}>Share</th><th className="nowrap">Last used</th><th className="w-min" />
                </tr>
              </thead>
              <tbody>
                {d.menus.map((m: any, i: number) => (
                  <tr key={m.code}>
                    <td className="rank">{page * PAGE + i + 1}</td>
                    <td className="nowrap"><Link href={`/menu/${enc(m.code)}`} className="mono" style={{ fontWeight: 600 }}>{m.code}</Link></td>
                    <td className="trunc">{m.program ? <ProgramLink name={m.program} /> : <code className="sub">{m.exec}</code>}</td>
                    <td className="num">{fmtNum(m.used)}</td>
                    <td><UsageBar value={m.used} max={top} /></td>
                    <td className="nowrap sub">{m.last_used ?? "—"}</td>
                    <td className="w-min">{m.program && <Link href={`/flow/${enc(m.code)}`} className="btn sm ghost">Flow</Link>}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pager page={page} pages={pages} total={d.total} noun={q ? "matching menus" : "menus"} href={qs} />
      </Card>
    </>
  );
}
