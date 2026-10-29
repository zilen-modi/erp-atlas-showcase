import Link from "next/link";
import { Card, EmptyState, ErrorBox, PageHeader, Pager, ProgramLink, Toolbar } from "@/components/ui";
import { api, enc, fmtNum } from "@/lib/api";

export const dynamic = "force-dynamic";
const PAGE = 100;

export default async function ProgramsPage({ searchParams }: { searchParams: { q?: string; sort?: string; page?: string } }) {
  const q = searchParams.q ?? "";
  const sort = ["usage", "lines", "name"].includes(searchParams.sort ?? "") ? searchParams.sort! : "usage";
  const page = Math.max(0, parseInt(searchParams.page ?? "0", 10) || 0);
  let d: any;
  try {
    d = await api(`/api/programs?q=${enc(q)}&sort=${sort}&limit=${PAGE}&offset=${page * PAGE}`);
  } catch (e) {
    return <ErrorBox error={e} />;
  }
  const qs = (p: number, s = sort) => `/programs?${new URLSearchParams({ ...(q ? { q } : {}), sort: s, page: String(p) })}`;
  const pages = Math.ceil(d.total / PAGE);
  const sortLink = (s: string, label: string) => (
    <Link href={qs(0, s)} className={sort === s ? "active" : ""}>{label}</Link>
  );
  return (
    <>
      <PageHeader
        eyebrow="Browse"
        title="Programs"
        desc="All BP programs. By default they're ranked by the menu launches that reach them (their own menus, or the menus of the programs that call them), which is how much real use they see."
      />
      <Card>
        <Toolbar action="/programs" q={q} placeholder="Filter by name, e.g. XFR or W4SUBORD">
          <input type="hidden" name="sort" value={sort} />
        </Toolbar>
        <div className="toolbar" style={{ paddingTop: 10, paddingBottom: 10 }}>
          <span className="sub">Sort by</span>
          <div className="seg">{sortLink("usage", "Most used")}{sortLink("lines", "Largest")}{sortLink("name", "Name")}</div>
        </div>
        {d.programs.length === 0 ? <EmptyState title="No programs match">Try part of the name, e.g. XFR.</EmptyState> : (
          <div className="table-wrap tall">
            <table>
              <thead>
                <tr><th className="w-min">#</th><th>Program</th><th>Kind</th><th className="num">Lines</th><th className="num">Launches reaching it</th><th className="w-min" /></tr>
              </thead>
              <tbody>
                {d.programs.map((p: any, i: number) => (
                  <tr key={p.name}>
                    <td className="rank">{page * PAGE + i + 1}</td>
                    <td className="trunc"><span><ProgramLink name={p.name} strong /></span></td>
                    <td className="nowrap sub">{p.kind === "NONE" ? "Program" : p.kind.charAt(0) + p.kind.slice(1).toLowerCase()}</td>
                    <td className="num">{fmtNum(p.line_count)}</td>
                    <td className="num">{fmtNum(p.reached_launches)}</td>
                    <td className="w-min"><Link href={`/flow/${enc(p.name)}`} className="btn sm ghost">Flow</Link></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <Pager page={page} pages={pages} total={d.total} noun={q ? "matching programs" : "programs"} href={(p) => qs(p)} />
      </Card>
    </>
  );
}
