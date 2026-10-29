import Link from "next/link";
import AskButton from "@/components/AskButton";
import { Badge, Card, EmptyState, ErrorBox, LineLink, PageHeader, ProgramLink } from "@/components/ui";
import { api, enc, fmtNum } from "@/lib/api";

export const dynamic = "force-dynamic";

function lines(list: number[], program: string, max = 8) {
  return (
    <span className="mono">
      {list.slice(0, max).map((l, i) => <span key={`${l}-${i}`}>{i > 0 && ", "}<LineLink program={program} line={l} /></span>)}
      {list.length > max && <span className="faint"> +{list.length - max}</span>}
    </span>
  );
}

function Sites({ data, write }: { data: any; write: boolean }) {
  if (data.programs.length === 0) return <EmptyState title={write ? "No writers found" : "No readers found"} />;
  return (
    <div className="table-wrap tall">
      <table>
        <thead>
          <tr><th>Program</th><th className="num">Launches</th><th>Lines</th>{write && <th>Saved at</th>}</tr>
        </thead>
        <tbody>
          {data.programs.map((p: any) => (
            <tr key={p.program}>
              <td className="nowrap"><ProgramLink name={p.program} strong /></td>
              <td className="num">{fmtNum(p.reached_launches)}</td>
              <td>{lines(p.sites.map((s: any) => s.line), p.program)}</td>
              {write && <td>{(p.persisted_by_write_at ?? []).length ? lines(p.persisted_by_write_at, p.program, 5) : <span className="faint">—</span>}</td>}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export default async function FieldPage({ params }: { params: { file: string; attr: string } }) {
  const file = decodeURIComponent(params.file).toUpperCase();
  const attr = parseInt(params.attr, 10);
  let d: any;
  try {
    d = await api(`/api/field/${enc(file)}/${attr}?track=true`);
  } catch (e) {
    return <ErrorBox error={e} />;
  }
  const w = d.writes;
  const r = d.reads;
  return (
    <>
      <PageHeader
        eyebrow={<Link href={`/files/${enc(file)}`}>Field of {file}</Link>}
        title={`${file}<${attr}>`}
        mono
        meta={<>
          {w.dict_names.length > 0
            ? w.dict_names.map((n: string) => <span key={n} className="chip">{n}</span>)
            : <Badge kind="amber">Not named in DICT {file}</Badge>}
          <span>·</span><span>{w.programs.length} writer{w.programs.length === 1 ? "" : "s"}</span>
          <span>·</span><span>{r.programs.length} reader{r.programs.length === 1 ? "" : "s"}</span>
        </>}
        actions={<>
          <div className="seg">
            {attr > 1 && <Link href={`/field/${enc(file)}/${attr - 1}`}>‹ &lt;{attr - 1}&gt;</Link>}
            <Link href={`/field/${enc(file)}/${attr + 1}`}>&lt;{attr + 1}&gt; ›</Link>
          </div>
          <Link className="btn sm primary" href={`/trace?file=${enc(file)}&attr=${attr}`}>See its journey</Link>
          <AskButton question={`What does ${file}<${attr}> hold, how is it set (by whom and under what conditions), and who relies on it?`} />
        </>}
      />
      <div className="stack">
        <Card title="Written by" sub={<>Assignments like <code>REC&lt;{attr}&gt; = …</code> change the record in memory; <b>Saved at</b> is where the program writes it back to {file}.</>}>
          <Sites data={w} write />
        </Card>
        <Card title="Read by">
          <Sites data={r} write={false} />
        </Card>
      </div>
    </>
  );
}
