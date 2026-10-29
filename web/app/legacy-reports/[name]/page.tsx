import Link from "next/link";
import AskButton from "@/components/AskButton";
import ParityEditor from "@/components/ParityEditor";
import { Card, ErrorBox, PageHeader } from "@/components/ui";
import { api, enc, fmtNum } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function LegacyReport({ params }: { params: { name: string } }) {
  const name = decodeURIComponent(params.name);
  let r: any;
  try {
    r = await api(`/api/legacy-reports/${enc(name)}?track=true`);
  } catch (e) {
    return <ErrorBox error={e} />;
  }
  return (
    <>
      <PageHeader eyebrow={<Link href="/legacy-reports">Report catalogue</Link>} title={r.title}
        meta={<>
          <span className="mono">{r.name}</span><span>·</span><span>{r.kind === "proc" ? "PROC report" : "program"}</span><span>·</span>
          <span>{r.output}</span>
          {r.launches ? <><span>·</span><span>{fmtNum(r.launches)} launches</span></> : null}
          {r.menus.length > 0 && <><span>·</span><span>{r.menus.map((m: string, i: number) => <span key={m}>{i > 0 && ", "}<Link href={`/menu/${enc(m)}`} className="mono">{m}</Link></span>)}</span></>}
        </>}
        actions={<>
          {r.kind === "program" ? <Link href={`/program/${enc(r.name)}`} className="btn">Program</Link> : <Link href={`/jobs/${enc(r.name)}`} className="btn">PROC</Link>}
          <AskButton question={`Describe the legacy report ${r.name} (${r.title}): who uses it, what it selects, which columns it shows and from which fields, and what an ERP Next equivalent would need.`} />
        </>}
      />
      <div className="grid side">
        <div className="stack">
          <Card title="Reads" sub="Pick files, most-read first">
            <div className="chips card-body">{r.files.length ? r.files.map((f: string) => <Link key={f} href={`/files/${enc(f)}`} className="chip mono">{f}</Link>) : <span className="sub">None found.</span>}</div>
          </Card>
          {r.columns.length > 0 && (
            <Card title="Columns" sub="DICT names the report lists">
              <div className="chips card-body">{r.columns.map((c: string) => <span key={c} className="chip mono">{c}</span>)}</div>
            </Card>
          )}
          {r.criteria && <Card title="Selection"><div className="card-body"><code>{r.criteria}</code></div></Card>}
          {r.via?.length > 0 && <Card title="Output through"><div className="chips card-body">{r.via.map((v: string) => <Link key={v} href={`/program/${enc(v)}`} className="chip mono">{v}</Link>)}</div></Card>}
          {r.job && (
            <Card title="In the PROC" sub={`${r.job.reports.length} report command${r.job.reports.length === 1 ? "" : "s"}`}>
              <div className="card-body stack" style={{ gap: 8 }}>
                {r.job.reports.map((c: any, i: number) => (
                  <div key={i}><b className="mono">{c.target}</b>{c.heading && <> · “{c.heading}”</>}<div className="mono sub job-cmd">{c.text}</div></div>
                ))}
              </div>
            </Card>
          )}
        </div>
        <div className="stack">
          <ParityEditor kind="report" name={r.name} parity={r.parity} statuses={r.statuses} />
        </div>
      </div>
    </>
  );
}
