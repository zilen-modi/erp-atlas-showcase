import Link from "next/link";
import { ArrowIcon, BridgeIcon, ProgramIcon } from "@/components/Icons";
import JobButton from "@/components/JobButton";
import { Card, EmptyState, ErrorBox, PageHeader, Stat } from "@/components/ui";
import { api, enc, fmtNum } from "@/lib/api";

export const dynamic = "force-dynamic";

const short = (n: number | null | undefined) => !n ? null : n >= 1e6 ? `${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)}M` : n >= 1e3 ? `${Math.round(n / 1e3)}k` : String(n);

function Prog({ name }: { name: string }) {
  return <Link href={`/program/${enc(name)}`} className="chip"><span className="mono">{name}</span></Link>;
}

export default async function ErpNextPage({ searchParams }: { searchParams: { depth?: string } }) {
  let d: any, me: any;
  try {
    [d, me] = await Promise.all([api("/api/erpnext"), api("/api/auth/me").catch(() => null)]);
  } catch (e) {
    return <ErrorBox error={e} />;
  }
  const admin = me?.user?.role === "admin";
  const t = d.totals;
  const showAll = searchParams.depth === "all";
  const deps = showAll ? d.depends_on : d.depends_on.filter((x: any) => x.depth === 1);
  const missing = d.helpers.filter((h: any) => !h.summary).map((h: any) => h.program);

  return (
    <>
      <PageHeader
        eyebrow="Migration"
        title="ERP Next"
        desc="The BASIC subroutines the new ERP Next API calls (src/next in the ERP repo), and the old programs and Pick files they still lean on. An old program on this page can't be retired until its logic is rebuilt on the new side."
        actions={admin && missing.length > 0 ? (
          <JobButton endpoint="/api/jobs/summaries" body={{ programs: missing, model: "claude-sonnet-5-5" }}
            label={`Summarise the ${missing.length} helper${missing.length === 1 ? "" : "s"}`}
            confirm={`Write summaries for ${missing.length} ERP Next helpers on your Claude (Sonnet)? They're small: a few calls.`} />
        ) : undefined}
      />

      <div className="grid cols-4" style={{ marginBottom: 16 }}>
        <Stat icon={<BridgeIcon size={18} />} label="Helpers the API calls" value={fmtNum(t.helpers)} note={`${t.summarised} summarised`} />
        <Stat icon={<ProgramIcon size={18} />} label="Old programs it calls directly" value={fmtNum(t.direct)} note="business logic reused as is" href="#depends" />
        <Stat icon={<ProgramIcon size={18} />} label="Old programs it needs in all" value={fmtNum(t.old_programs)} note={`following calls ${d.depth} levels down`} href="/erpnext?depth=all#depends" />
        <Stat icon={<ProgramIcon size={18} />} label="Pick files it touches" value={fmtNum(t.files)} note={`${d.files.filter((f: any) => f.writes.length).length} written`} href="#files" />
      </div>

      {d.helpers.length === 0 ? (
        <Card><EmptyState title="No ERP Next helpers indexed" icon={<BridgeIcon size={20} />}>Run a sync: Atlas reads src/next/api-helpers and src/next/utilities from the ERP repo.</EmptyState></Card>
      ) : (
        <div className="stack">
          <Card title="Helpers" sub="What each one does, and the old code and files it uses">
            <div className="table-wrap">
              <table className="en-table">
                <thead><tr><th>Helper</th><th>What it does</th><th>Calls into the old ERP</th><th>Pick files</th></tr></thead>
                <tbody>
                  {d.helpers.map((h: any) => (
                    <tr key={h.program}>
                      <td className="nowrap">
                        <Link href={`/program/${enc(h.program)}`} className="mono" style={{ fontWeight: 600 }}>{h.program}</Link>
                        <div className="sub">{h.folder.replace("ERP Next ", "")} · {fmtNum(h.lines)} lines</div>
                      </td>
                      <td className="en-what">
                        {h.summary ? <>{h.summary.title}{h.summary.stale && <> <span className="badge amber">out of date</span></>}</>
                          : <span className="faint">No summary yet</span>}
                      </td>
                      <td><div className="chips">{h.calls.map((c: string) => <Prog key={c} name={c} />)}
                        {h.uses_helpers.map((c: string) => <Link key={c} href={`/program/${enc(c)}`} className="chip en-helper"><span className="mono">{c}</span></Link>)}
                        {h.calls.length + h.uses_helpers.length === 0 && <span className="faint">none</span>}</div></td>
                      <td><div className="chips">{h.files.map((f: string) => <Link key={f} href={`/files/${enc(f)}`} className="file-chip">{f}</Link>)}</div></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <section id="depends">
            <Card title="Old programs the new system still needs"
              sub={showAll ? `All ${d.depends_on.length}, up to ${d.depth} calls away` : `${deps.length} called directly by a helper`}
              actions={<Link href={showAll ? "/erpnext#depends" : "/erpnext?depth=all#depends"} className="btn sm ghost">
                {showAll ? "Only direct calls" : `Show all ${d.depends_on.length}`} <ArrowIcon size={13} /></Link>}>
              <div className="table-wrap tall">
                <table className="en-table">
                  <thead><tr><th>Program</th><th>What it does</th><th>Needed by</th><th className="num">Menu launches</th></tr></thead>
                  <tbody>
                    {deps.map((x: any) => (
                      <tr key={x.program}>
                        <td className="nowrap">
                          {x.indexed ? <Link href={`/program/${enc(x.program)}`} className="mono" style={{ fontWeight: 600 }}>{x.program}</Link>
                            : <span className="mono faint" title="Called, but not in the git index (a catalogued routine kept elsewhere)">{x.program}</span>}
                          <div className="sub">{x.depth === 1 ? "called directly" : `${x.depth} calls away`}{x.lines ? ` · ${fmtNum(x.lines)} lines` : ""}
                            {x.test_differs && <> · <span className="chip-warn">TEST differs</span></>}</div>
                        </td>
                        <td className="en-what">{x.summary ? x.summary.title : <span className="faint">No summary yet</span>}</td>
                        <td><div className="chips">{x.via.slice(0, 4).map((v: string) => <Link key={v} href={`/program/${enc(v)}`} className="chip en-helper"><span className="mono">{v}</span></Link>)}
                          {x.via.length > 4 && <span className="sub">+{x.via.length - 4}</span>}</div></td>
                        <td className="num nowrap">{short(x.launches) ?? <span className="faint">—</span>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </section>

          <section id="files">
            <Card title="Pick files the helpers read and write" sub="Their own I/O, written files first">
              <div className="table-wrap">
                <table className="en-table">
                  <thead><tr><th>File</th><th>Written by</th><th>Read by</th></tr></thead>
                  <tbody>
                    {d.files.map((f: any) => (
                      <tr key={f.file}>
                        <td className="nowrap"><Link href={`/files/${enc(f.file)}`} className="mono" style={{ fontWeight: 600 }}>{f.file}</Link></td>
                        <td><div className="chips">{f.writes.length ? f.writes.map((p: string) => <Prog key={p} name={p} />) : <span className="faint">—</span>}</div></td>
                        <td><div className="chips">{f.reads.map((p: string) => <Prog key={p} name={p} />)}</div></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
          </section>
        </div>
      )}
    </>
  );
}
