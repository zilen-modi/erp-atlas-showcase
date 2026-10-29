import Link from "next/link";
import ProgramHeader from "@/components/ProgramHeader";
import SummaryCard from "@/components/knowledge/SummaryCard";
import { Badge, Card, EmptyState, ErrorBox, LineLink, ProgramLink } from "@/components/ui";
import { api, enc, fmtNum } from "@/lib/api";

export const dynamic = "force-dynamic";

function Lines({ program, list, max = 6 }: { program: string; list: number[]; max?: number }) {
  return (
    <span className="mono sub">
      {list.slice(0, max).map((l, i) => <span key={l}>{i > 0 && ", "}<LineLink program={program} line={l} /></span>)}
      {list.length > max && ` +${list.length - max}`}
    </span>
  );
}

const provenanceIsGit = (p: any) => (p.provenance ?? "git") === "git";

export default async function ProgramPage({ params }: { params: { name: string } }) {
  const name = decodeURIComponent(params.name);
  let p: any, callers: any;
  try {
    [p, callers] = await Promise.all([api(`/api/program/${enc(name)}?track=true`), api(`/api/callers/${enc(name)}`)]);
  } catch (e) {
    return <ErrorBox error={e} />;
  }
  if (p.error) return <ErrorBox error={p.error} />;

  const calls = Object.entries(p.calls as Record<string, number[]>);
  const byFile: Record<string, { op: string; n: number; first: number }[]> = {};
  for (const r of p.io as any[]) (byFile[r.pick_file ?? "(unresolved file variable)"] ??= []).push(r);
  const callerRows: Record<string, { kind: string; lines: number[] }> = {};
  for (const s of callers.sites as any[]) {
    const c = (callerRows[s.program] ??= { kind: s.kind, lines: [] });
    c.lines.push(s.line);
  }

  return (
    <>
      <ProgramHeader p={p} tab="overview" />
      {provenanceIsGit(p) && <SummaryCard program={p.program} />}
      <div className="grid cols-2" style={{ alignItems: "start" }}>
        <div className="stack">
          <Card title="Launched from" sub={p.menus.length ? `${p.menus.length} menu${p.menus.length === 1 ? "" : "s"}` : undefined}>
            {p.menus.length === 0 ? <div className="empty">Not launched directly from a menu.</div> : (
              <table>
                <thead><tr><th>Menu</th><th className="num">Launches</th><th className="nowrap">Last used</th></tr></thead>
                <tbody>
                  {p.menus.map((m: any) => (
                    <tr key={m.code}>
                      <td><Link href={`/menu/${enc(m.code)}`} className="mono" style={{ fontWeight: 600 }}>{m.code}</Link></td>
                      <td className="num">{fmtNum(m.used)}</td>
                      <td className="nowrap sub">{m.last_used ?? "—"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </Card>

          <Card title="Called by" sub={`${callers.programs} program${callers.programs === 1 ? "" : "s"}`}>
            {callers.programs === 0 ? <div className="empty">Nothing in the index calls this program.</div> : (
              <div className="table-wrap mid">
                <table>
                  <thead><tr><th>Program</th><th>How</th><th>At lines</th></tr></thead>
                  <tbody>
                    {Object.entries(callerRows).map(([prog, c]) => (
                      <tr key={prog}>
                        <td className="nowrap"><ProgramLink name={prog} strong /></td>
                        <td className="sub nowrap">{c.kind.toLowerCase()}</td>
                        <td><Lines program={prog} list={c.lines} /></td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <Card title="Calls" sub={`${calls.length} programs · plus ${fmtNum(p.gui_calls)} GUI calls and ${fmtNum(p.gosub_calls)} GOSUBs`}>
            {calls.length === 0 ? <div className="empty">No calls to other programs.</div> : (
              <div className="table-wrap mid">
                <table>
                  <thead><tr><th>Program</th><th>How</th><th>At lines</th></tr></thead>
                  <tbody>
                    {calls.map(([k, lines]) => {
                      const [kind, target] = k.split(" ");
                      return (
                        <tr key={k}>
                          <td className="nowrap"><ProgramLink name={target} strong /></td>
                          <td className="sub nowrap">{kind.toLowerCase()}</td>
                          <td><Lines program={p.program} list={lines} /></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>

        <Card title="Data it reads and writes" sub={`${Object.keys(byFile).length} Pick files`}>
          {Object.keys(byFile).length === 0 ? <EmptyState title="No file I/O found" /> : (
            <div className="table-wrap" style={{ maxHeight: 900 }}>
              <table>
                <thead><tr><th>File</th><th>Operations</th></tr></thead>
                <tbody>
                  {Object.entries(byFile).map(([f, ops]) => {
                    const writes = ops.some((o) => /WRITE|DELETE/.test(o.op));
                    return (
                      <tr key={f}>
                        <td className="nowrap">
                          {f.startsWith("(") ? <span className="sub">{f}</span>
                            : <Link href={`/files/${enc(f)}`} className="mono" style={{ fontWeight: 600 }}>{f}</Link>}
                          {" "}{writes && <Badge kind="red">writes</Badge>}
                        </td>
                        <td>
                          <div className="chips">
                            {ops.map((o) => (
                              <Link key={o.op} className="chip" href={`/program/${enc(p.program)}/source?line=${o.first}`} title={`first at line ${o.first}`}>
                                {o.op.toLowerCase()} ×{o.n}
                              </Link>
                            ))}
                          </div>
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
          <div className="card-foot">IOREADU / IORELEASE calls are counted as reads, writes and deletes.</div>
        </Card>
      </div>
    </>
  );
}
