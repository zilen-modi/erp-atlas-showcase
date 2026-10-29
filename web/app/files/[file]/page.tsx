import Link from "next/link";
import AskButton from "@/components/AskButton";
import DictModelEditor from "@/components/DictModelEditor";
import { Badge, Card, EmptyState, ErrorBox, PageHeader, ProgramLink } from "@/components/ui";
import { api, enc, fmtNum } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function FileDetail({ params, searchParams }: {
  params: { file: string }; searchParams: { only?: string };
}) {
  const file = decodeURIComponent(params.file).toUpperCase();
  let d: any, jobs: any[] = [];
  try {
    [d, jobs] = await Promise.all([api(`/api/files/${enc(file)}?track=true`), api(`/api/files/${enc(file)}/jobs`).catch(() => [])]);
  } catch (e) {
    return <ErrorBox error={e} />;
  }
  const onlyUndoc = searchParams.only === "undocumented";
  const attrs = (d.attributes as any[]).filter((a) => !onlyUndoc || a.dict_names.length === 0);
  const base = `/files/${enc(file)}`;
  return (
    <>
      <PageHeader
        eyebrow="Pick file"
        title={file}
        mono
        meta={<>
          <span>{d.attributes.length} attributes</span><span>·</span>
          <span>{d.undocumented.length} not named in DICT</span><span>·</span>
          <span>used by {fmtNum(d.program_count)} programs</span>
        </>}
        actions={<><Link href={`/files/${enc(file)}/profile`} className="btn">Data profile</Link><a href="#model" className="btn">Model export</a><AskButton question={`Explain the ${file} file: what it holds, its key format, the most important attributes, and which programs create and update records.`} /></>}
      />

      <div className="grid cols-2" style={{ alignItems: "start" }}>
        <Card title="Attributes"
          actions={<div className="seg">
            <Link href={base} className={!onlyUndoc ? "active" : ""}>All</Link>
            <Link href={`${base}?only=undocumented`} className={onlyUndoc ? "active" : ""}>Not in DICT</Link>
          </div>}>
          {attrs.length === 0 ? <EmptyState title="Nothing here" /> : (
            <div className="table-wrap tall">
              <table>
                <thead><tr><th className="num w-min">Attr</th><th>DICT name</th><th className="num">Writers</th><th className="num">Readers</th></tr></thead>
                <tbody>
                  {attrs.map((a) => (
                    <tr key={a.attr}>
                      <td className="num w-min"><Link href={`/field/${enc(file)}/${a.attr}`} className="mono" style={{ fontWeight: 600 }}>&lt;{a.attr}&gt;</Link></td>
                      <td className="trunc">
                        {a.dict_names.length
                          ? <span className="mono" title={a.dict_names.join(", ")}>{a.dict_names.slice(0, 3).join(", ")}{a.dict_names.length > 3 ? ` +${a.dict_names.length - 3}` : ""}</span>
                          : <span><Badge kind="amber">not in DICT</Badge></span>}
                      </td>
                      <td className="num">{a.writers || <span className="faint">—</span>}</td>
                      <td className="num">{a.readers || <span className="faint">—</span>}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card title="Programs using this file" sub={`${fmtNum(d.program_count)} total, most used first`}>
          <div className="table-wrap tall">
            <table>
              <thead><tr><th>Program</th><th>Access</th><th className="num">Launches</th></tr></thead>
              <tbody>
                {d.programs.slice(0, 200).map((p: any) => (
                  <tr key={p.program}>
                    <td className="trunc"><span><ProgramLink name={p.program} /></span></td>
                    <td className="nowrap">
                      <span className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                        {p.access.includes("write") && <Badge kind="red">writes</Badge>}
                        {p.access.includes("read") && <Badge kind="green">reads</Badge>}
                        {p.access.length === 0 && <span className="sub">opens</span>}
                      </span>
                    </td>
                    <td className="num">{fmtNum(p.reached_launches)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {d.program_count > 200 && <div className="card-foot">Showing 200 of {fmtNum(d.program_count)}</div>}
        </Card>
      </div>
      {jobs.length > 0 && (
        <div style={{ marginTop: 16 }}>
          <Card title="Background jobs that change this file" sub={`${jobs.length} PROC${jobs.length === 1 ? "" : "s"} run programs that write ${file}`}>
            <div className="mini-list">
              {jobs.slice(0, 30).map((j: any) => (
                <Link key={j.name} href={`/jobs/${enc(j.name)}`} className="mini">
                  <span className="badge">{j.schedule}</span>
                  <span className="mono" style={{ fontWeight: 600 }}>{j.name}</span>
                  <span className="sub ellipsis" style={{ flex: 1 }}>via {j.via.join(", ")}</span>
                </Link>
              ))}
            </div>
          </Card>
        </div>
      )}
      <div style={{ marginTop: 16 }}><DictModelEditor file={file} /></div>
    </>
  );
}
