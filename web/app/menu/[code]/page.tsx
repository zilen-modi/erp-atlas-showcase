import Link from "next/link";
import AskButton from "@/components/AskButton";
import { FlowIcon } from "@/components/Icons";
import { Card, ErrorBox, PageHeader, ProgramLink } from "@/components/ui";
import { api, enc, fmtNum } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function MenuPage({ params }: { params: { code: string } }) {
  const code = decodeURIComponent(params.code).toUpperCase();
  let m: any;
  try {
    m = await api(`/api/menu/${enc(code)}?track=true`);
  } catch (e) {
    return <ErrorBox error={e} />;
  }
  if (m.error) return <ErrorBox error={m.error} />;
  const p = m.program_overview;
  const calls = p && !p.error ? Object.keys(p.calls).map((k) => k.split(" ")[1]) : [];

  return (
    <>
      <PageHeader
        eyebrow={<Link href="/menus">Menu</Link>}
        title={m.code}
        mono
        meta={<>
          <code>{m.exec}</code><span>·</span><span>{fmtNum(m.used)} launches</span><span>·</span><span>last used {m.last_used ?? "—"}</span>
        </>}
        actions={<>
          {m.program && <Link className="btn" href={`/flow/${enc(m.code)}`}><FlowIcon size={14} /> See the flow</Link>}
          <AskButton primary question={`Walk me through menu ${m.code}${m.program ? ` (${m.program})` : ""} end to end: what the user does, the main steps, and which files are read and written.`} label="Explain this menu" />
        </>}
      />
      <div className="grid cols-2" style={{ alignItems: "start" }}>
        <Card title="Runs" pad>
          {m.program ? (
            <>
              <div className="row" style={{ marginBottom: 8 }}>
                <ProgramLink name={m.program} strong />
                {p && !p.error && <span className="sub">{fmtNum(p.lines)} lines · {p.kind === "NONE" ? "program" : p.kind.toLowerCase()}</span>}
              </div>
              <Link href={`/program/${enc(m.program)}`} className="btn sm">Open program</Link>
            </>
          ) : <span className="sub">This menu doesn't run a BP program: <code>{m.exec}</code></span>}
        </Card>
        <Card title="Which calls" sub={`${calls.length} program${calls.length === 1 ? "" : "s"}`} pad>
          {calls.length === 0 ? <span className="sub">No calls to other programs.</span> : (
            <div className="chips">
              {calls.map((t) => <Link key={t} className="chip" href={`/program/${enc(t)}`}>{t}</Link>)}
            </div>
          )}
        </Card>
      </div>
    </>
  );
}
