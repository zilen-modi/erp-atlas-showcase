import Link from "next/link";
import { Card, EmptyState, ErrorBox, PageHeader, Toolbar } from "@/components/ui";
import { api, enc, fmtNum } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function FilesPage({ searchParams }: { searchParams: { q?: string; all?: string } }) {
  const q = searchParams.q ?? "";
  let d: any;
  try {
    d = await api(`/api/files?q=${enc(q)}`);
  } catch (e) {
    return <ErrorBox error={e} />;
  }
  const limited = !searchParams.all && !q;
  const shown = limited ? d.files.filter((f: any) => f.programs_opening > 0).slice(0, 300) : d.files;
  const max = d.files[0]?.programs_opening || 1;
  return (
    <>
      <PageHeader
        eyebrow="Browse"
        title="Files & fields"
        desc="The data layer. Each Pick file opens a data dictionary with every attribute, its DICT names, and which programs write and read it."
        actions={<a href="/api/dict-export.zip" className="btn" title="One JSON per file: pos, uv, model, sm, format (edited and AI names included)">Export all dictionaries (JSON)</a>}
      />
      <Card>
        <Toolbar action="/files" q={q} placeholder="Filter files, e.g. TRANSFER or ORDER" />
        {shown.length === 0 ? <EmptyState title="No files match" /> : (
          <div className="table-wrap tall">
            <table>
              <thead>
                <tr><th>File</th><th className="num">Programs opening</th><th style={{ width: "18%" }} /><th className="num">Programs writing</th><th className="num">DICT attributes</th></tr>
              </thead>
              <tbody>
                {shown.map((f: any) => (
                  <tr key={f.file}>
                    <td className="trunc"><Link href={`/files/${enc(f.file)}`} className="mono" style={{ fontWeight: 600 }}>{f.file}</Link></td>
                    <td className="num">{fmtNum(f.programs_opening)}</td>
                    <td><div className="bar"><span style={{ width: `${Math.max(2, (f.programs_opening / max) * 100)}%` }} /></div></td>
                    <td className="num">{fmtNum(f.programs_writing)}</td>
                    <td className="num">{fmtNum(f.dict_attrs)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
        <div className="pager">
          <span>{limited ? `Showing the 300 most-used of ${fmtNum(d.total)} files` : `${fmtNum(shown.length)} files`}</span>
          <span className="spacer" />
          {limited && <Link href="/files?all=1" className="btn sm">Show all</Link>}
        </div>
      </Card>
    </>
  );
}
