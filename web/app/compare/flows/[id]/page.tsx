import Link from "next/link";
import FlowEditor from "@/components/compare/FlowEditor";
import StartRun from "@/components/compare/StartRun";
import { Badge, Card, EmptyState, ErrorBox, PageHeader } from "@/components/ui";
import { ago, api, enc } from "@/lib/api";

export const dynamic = "force-dynamic";

const VERDICT: Record<string, [string, string]> = {
  expected: ["Expected", "green"], bug: ["Bug", "red"], question: ["Question", "amber"], fixed: ["Fixed", "blue"],
};

export default async function FlowPage({ params, searchParams }: { params: { id: string }; searchParams: { edit?: string } }) {
  let f: any;
  try {
    f = await api(`/api/compare/flows/${enc(params.id)}`);
  } catch (e) {
    return <ErrorBox error={e} />;
  }
  const editing = searchParams.edit === "1";
  const counts: Record<string, number> = {};
  for (const n of f.all_notes) counts[n.verdict] = (counts[n.verdict] ?? 0) + 1;

  if (editing) {
    return (
      <>
        <PageHeader eyebrow={<Link href={`/compare/flows/${f.id}`}>{f.name}</Link>} title="Edit flow" />
        <FlowEditor flow={f} />
      </>
    );
  }

  return (
    <>
      <PageHeader
        eyebrow={<Link href="/compare">Compare</Link>}
        title={f.name}
        desc={f.description || undefined}
        meta={<>
          <span>{f.steps.length} step{f.steps.length === 1 ? "" : "s"}</span><span>·</span>
          <span>{f.files.length} file{f.files.length === 1 ? "" : "s"}</span><span>·</span>
          <span>{f.runs.length} run{f.runs.length === 1 ? "" : "s"}</span>
        </>}
        actions={<Link href={`/compare/flows/${f.id}?edit=1`} className="btn">Edit flow</Link>}
      />

      <div className="grid cols-2" style={{ alignItems: "start", marginBottom: 16 }}>
        <Card title="Steps">
          <div className="card-body">
            <div className="step-line">
              {f.steps.map((s: any, i: number) => (
                <span key={s.id} className="step-pill"><span className="step-num">{i + 1}</span>{s.name}</span>
              ))}
            </div>
          </div>
        </Card>
        <Card title="Files it touches">
          <table>
            <tbody>
              {f.files.map((x: any) => (
                <tr key={x.id}>
                  <td className="nowrap"><Link href={`/files/${enc(x.pick_file)}`} className="mono" style={{ fontWeight: 600 }}>{x.pick_file}</Link></td>
                  <td className="mono sub nowrap">{x.key_template}</td>
                  <td className="trunc sub"><span>{x.note}</span></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Card>
      </div>

      <div className="stack">
        <section className="card" id="start">
          <div className="card-head"><h2>Start a run</h2></div>
          <StartRun flowId={f.id} mainFile={f.files[0]?.pick_file ?? ""} />
        </section>

        <Card title="Runs">
          {f.runs.length === 0 ? <EmptyState title="No runs yet">Start one above with the keys of the two records.</EmptyState> : (
            <div className="table-wrap">
              <table>
                <thead><tr><th>Run</th><th>Old key</th><th>New key</th><th className="nowrap">Started</th><th className="nowrap">Updated</th></tr></thead>
                <tbody>
                  {f.runs.map((r: any) => (
                    <tr key={r.id}>
                      <td className="trunc"><span><Link href={`/compare/runs/${r.id}`} style={{ fontWeight: 600 }}>{r.name}</Link></span></td>
                      <td className="mono nowrap">{r.legacy_key || "—"}</td>
                      <td className="mono nowrap">{r.new_key || "—"}</td>
                      <td className="nowrap sub">{ago(r.created_at)}</td>
                      <td className="nowrap sub">{ago(r.updated_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>

        <Card title="Notes on this flow" sub={Object.entries(counts).map(([k, n]) => `${n} ${VERDICT[k]?.[0].toLowerCase() ?? k}`).join(" · ") || undefined}>
          {f.all_notes.length === 0 ? <EmptyState title="No notes yet">Add notes on a field from any run; the ones you remember show up here and on every run.</EmptyState> : (
            <div className="table-wrap mid">
              <table>
                <thead><tr><th>Field</th><th>Verdict</th><th>Note</th><th>By</th><th className="nowrap">When</th></tr></thead>
                <tbody>
                  {f.all_notes.map((n: any) => (
                    <tr key={n.id}>
                      <td className="nowrap"><Link href={`/field/${enc(n.pick_file)}/${n.attr}`} className="mono">{n.pick_file}&lt;{n.attr}&gt;</Link></td>
                      <td><Badge kind={VERDICT[n.verdict]?.[1] ?? ""}>{VERDICT[n.verdict]?.[0] ?? n.verdict}</Badge></td>
                      <td>{n.text}{n.run_id && <span className="faint"> · this run only</span>}</td>
                      <td className="nowrap sub">{n.author}</td>
                      <td className="nowrap sub">{ago(n.created_at)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
