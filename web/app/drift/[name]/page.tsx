import Link from "next/link";
import JobButton from "@/components/JobButton";
import ProgramHeader from "@/components/ProgramHeader";
import { Badge, Card, Code, DRIFT_HELP, EmptyState, ErrorBox } from "@/components/ui";
import { ago, api, enc, programHref } from "@/lib/api";

export const dynamic = "force-dynamic";

const ORDER = ["logic", "git-only", "live-only", "label", "comment", "whitespace"];
const REAL = new Set(["logic", "git-only", "live-only"]);
const LABEL: Record<string, string> = {
  logic: "Changed", "git-only": "Only in git", "live-only": "Only on TEST", label: "Label", comment: "Comment", whitespace: "Spacing",
};

export default async function DriftPage({
  params,
  searchParams,
}: {
  params: { name: string };
  searchParams: { class?: string; all?: string };
}) {
  const name = decodeURIComponent(params.name);
  const showAll = searchParams.all === "1";
  let p: any, d: any;
  try {
    [p, d] = await Promise.all([
      api(`/api/program/${enc(name)}`),
      api(`/api/drift/${enc(name)}${showAll ? "?all=true" : ""}`),
    ]);
  } catch (e) {
    return <ErrorBox error={e} />;
  }
  if (p.error) return <ErrorBox error={p.error} />;
  const base = `/drift/${enc(name)}`;
  const refresh = (
    <JobButton endpoint={`/api/jobs/drift/${enc(name)}`} label="Re-check TEST"
      confirm={`Fetch ${name} from the TEST server now? Large programs take minutes. Needs VPN.`} />
  );

  if (typeof d.drift === "string") {
    return (
      <>
        <ProgramHeader p={p} tab="drift" />
        <Card title="TEST deployment" actions={refresh}>
          <EmptyState title={d.drift === "identical to git" ? "TEST runs the same version as git" : "Not checked against TEST yet"} />
        </Card>
      </>
    );
  }

  const filter = searchParams.class;
  const hunks = (d.hunks as any[]).filter((h) => !filter || h.class === filter);
  const v = d.live_matches_git_version;
  const chipHref = (k?: string) => {
    if (!k) return showAll ? `${base}?all=1` : base;
    return `${base}?${new URLSearchParams({ ...(showAll || !REAL.has(k) ? { all: "1" } : {}), class: k })}`;
  };

  return (
    <>
      <ProgramHeader p={p} tab="drift" />
      <div className="grid cols-2" style={{ marginBottom: 16, alignItems: "start" }}>
        <Card title="Which version is TEST running?" pad>
          {v ? (
            <>
              <p style={{ fontSize: 14.5, marginBottom: 6 }}>
                TEST {v.real_hunks === 0 ? "matches exactly" : <>is closest to</>} git <code>{v.sha.slice(0, 9)}</code>
                {v.real_hunks > 0 && <span className="sub"> ({v.real_hunks} differences remain)</span>}
              </p>
              <p className="sub">{v.date} · {v.author} · “{v.summary}”</p>
              <p className="sub" style={{ margin: 0 }}>
                {v.behind === 0 ? "That is the newest commit for this file." : <>git main has <b>{v.behind}</b> newer commit{v.behind === 1 ? "" : "s"} for this file that TEST doesn't have.</>}
              </p>
            </>
          ) : <span className="sub">Not computed.</span>}
        </Card>
        <Card title="Differences" sub={`checked ${ago(d.computed_at)}`} actions={refresh}>
          <div className="card-body">
            <div className="seg" style={{ flexWrap: "wrap" }}>
              <Link href={chipHref()} className={!filter ? "active" : ""}>All</Link>
              {ORDER.filter((k) => d.summary[k]).map((k) => (
                <Link key={k} href={chipHref(k)} title={DRIFT_HELP[k]} className={filter === k ? "active" : ""}>
                  {LABEL[k]} · {d.summary[k]}
                </Link>
              ))}
            </div>
            <p className="sub" style={{ marginTop: 10, marginBottom: 0 }}>
              {showAll ? <Link href={base}>Hide cosmetic differences</Link> : <Link href={`${base}?all=1`}>Include cosmetic differences</Link>}
              {" · "}<span style={{ color: "var(--bad)" }}>red</span> = git, <span style={{ color: "var(--ok)" }}>green</span> = TEST
            </p>
          </div>
        </Card>
      </div>

      {hunks.length === 0 && <Card><EmptyState title="No differences in this view" /></Card>}
      {hunks.map((h) => (
        <div key={h.hunk} className="hunk">
          <div className="hunk-head">
            <b>#{h.hunk}</b>
            <Badge kind={h.class}>{LABEL[h.class] ?? h.class}</Badge>
            <span className="sub">{DRIFT_HELP[h.class]}</span>
            <span className="spacer" />
            {h.git[0] > 0 && <Link href={programHref(name, h.git[0])} className="btn sm ghost mono">git {h.git[0]}–{h.git[1]}</Link>}
            {h.live[0] > 0 && <Link href={programHref(name, h.live[0], "live")} className="btn sm ghost mono">TEST {h.live[0]}–{h.live[1]}</Link>}
          </div>
          {h.git_commits?.map((c: any) => (
            <div key={c.sha} className="commit">
              {c.role === "removed-in-git" ? "Removed from git in " : "Git line from "}
              <code>{c.sha.slice(0, 9)}</code> · {c.date} · {c.author} · {c.summary}
            </div>
          ))}
          {h.git_text && <Code lines={h.git_text.split("\n")} start={h.git[0]} mark="del" />}
          {h.live_text && <Code lines={h.live_text.split("\n")} start={h.live[0]} mark="add" />}
        </div>
      ))}
    </>
  );
}
