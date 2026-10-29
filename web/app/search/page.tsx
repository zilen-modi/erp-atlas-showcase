import Link from "next/link";
import { redirect } from "next/navigation";
import AskButton from "@/components/AskButton";
import { ArrowIcon, CodeIcon, DictIcon, FieldIcon, MenuIcon, ProgramIcon, SparkIcon } from "@/components/Icons";
import { Highlight } from "@/components/SearchBox";
import { Card, EmptyState, ErrorBox, PageHeader } from "@/components/ui";
import { api, enc, fmtNum, programHref } from "@/lib/api";

export const dynamic = "force-dynamic";

type Tab = "all" | "meaning" | "programs" | "menus" | "fields" | "code";

export default async function Search({ searchParams }: { searchParams: { q?: string; type?: string } }) {
  const q = (searchParams.q ?? "").trim();
  const tab = (["all", "meaning", "programs", "menus", "fields", "code"].includes(searchParams.type ?? "")
    ? searchParams.type : "all") as Tab;
  if (!q) redirect("/");
  let r: any, code: any, meaning: any;
  try {
    [r, code, meaning] = await Promise.all([
      api(`/api/search?q=${enc(q)}&limit=50&track=${tab === "all"}`),
      api(`/api/code?q=${enc(q)}&limit=80`),
      api(`/api/meaning?q=${enc(q)}&limit=${tab === "meaning" ? 25 : 6}`).catch(() => ({ results: [] })),
    ]);
  } catch (e) {
    return <ErrorBox error={e} />;
  }
  const up = q.toUpperCase();
  if (tab === "all") {
    // an exact name goes straight to its page
    if (r.fields.length === 1 && !r.programs.some((p: any) => p.name === up)) redirect(`/field/${enc(r.fields[0].file)}/${r.fields[0].attr}`);
    if (r.programs[0]?.name === up && !r.menus.some((m: any) => m.code === up)) redirect(`/program/${enc(up)}`);
    if (r.menus[0]?.code === up) redirect(`/menu/${enc(up)}`);
  }

  const byProgram = new Map<string, any[]>();
  for (const h of code.hits) byProgram.set(h.program, [...(byProgram.get(h.program) ?? []), h]);
  const fields = [...r.fields.map((f: any) => ({ file: f.file, attr: f.attr, name: f.dict_names.join(", ") || "not named in DICT" })),
    ...r.dict_names.map((d: any) => ({ file: d.pick_file, attr: d.attr, name: d.name }))];
  const counts: Record<Tab, number> = { all: 0, meaning: meaning.results.length, programs: r.programs.length, menus: r.menus.length, fields: fields.length, code: byProgram.size };
  counts.all = counts.meaning + counts.programs + counts.menus + counts.fields + counts.code;
  const show = (t: Tab) => tab === "all" || tab === t;
  const cap = (n: number) => (tab === "all" ? n : 1000);
  const tabHref = (t: Tab) => `/search?${new URLSearchParams({ q, ...(t === "all" ? {} : { type: t }) })}`;
  const more = (t: Tab, n: number, noun: string) =>
    tab === "all" && n > 0 ? <Link href={tabHref(t)} className="btn sm ghost">All {n} {noun} <ArrowIcon size={13} /></Link> : undefined;
  const TABS: [Tab, string][] = [["all", "All"], ["meaning", "By meaning"], ["programs", "Programs"], ["menus", "Menus"], ["fields", "Fields"], ["code", "In code"]];

  return (
    <>
      <PageHeader
        eyebrow="Search"
        title={<>Results for “{q}”</>}
        meta={<span>{counts.all === 0 ? "No matches" : `${fmtNum(counts.all)} matches`}</span>}
        actions={<AskButton question={q.includes(" ") ? q : `What is ${q} in the legacy ERP, and where is it used?`} label="Ask Atlas instead" />}
      />

      <nav className="tabs">
        {TABS.map(([t, label]) => (
          <Link key={t} href={tabHref(t)} className={tab === t ? "active" : ""}>
            {label} <span className="tab-count">{counts[t]}{t === "code" && code.truncated ? "+" : ""}</span>
          </Link>
        ))}
      </nav>

      {counts.all === 0 && (
        <Card>
          <EmptyState title={`Nothing matched “${q}”`}>
            Try a program (<code>LG.XFER.MAINT</code>), a menu (<code>M4401</code>), a field (<code>TRANSFER&lt;10&gt;</code>),
            a DICT name (<code>DATEREQD</code>), or ask the question in plain English.
          </EmptyState>
        </Card>
      )}

      <div className="results">
        {show("meaning") && meaning.results.length > 0 && (
          <Card className="wide" title={<span className="row" style={{ gap: 6 }}><SparkIcon size={15} /> By meaning</span>}
            sub="Programs whose summaries match what you described"
            actions={meaning.results.length >= 6 ? more("meaning", meaning.results.length, "matches") : undefined}>
            {meaning.results.map((m: any, i: number) => m.kind === "fact" ? (
              <Link key={`f${m.id}`} href={`/facts?q=${enc(m.id)}`} className="result meaning-hit">
                <span className="mono result-title">{m.id}</span>
                <span className="sub">{m.text}</span>
                <span className="spacer" />
                <span className={`badge ${m.status === "accepted" ? "green" : ""}`}>{m.status}</span>
              </Link>
            ) : (
              <Link key={`${m.program}${m.start ?? ""}${i}`} href={m.start ? programHref(m.program, m.start) : `/program/${enc(m.program)}`} className="result meaning-hit">
                <span className="mono result-title">{m.program}{m.start ? <span className="faint">:{m.start}–{m.end}</span> : null}</span>
                <span className="meaning-text"><strong>{m.title}</strong> <span className="sub">{m.summary}</span></span>
                {m.stale && <span className="badge amber" title="The code has changed since this summary was written">out of date</span>}
              </Link>
            ))}
          </Card>
        )}
        {tab === "meaning" && meaning.results.length === 0 && (
          <Card>
            <EmptyState title="Nothing close in meaning">
              {meaning.ready === false ? "There are no summaries to search yet: an admin writes them on the People page, under Knowledge."
                : "No summary is close to that description. Summaries are written most-used programs first, so the program may not have one yet."}
            </EmptyState>
          </Card>
        )}
        {show("programs") && r.programs.length > 0 && (
          <Card title={<span className="row" style={{ gap: 6 }}><ProgramIcon size={15} /> Programs</span>} actions={r.programs.length > 8 ? more("programs", r.programs.length, "programs") : undefined}>
            {r.programs.slice(0, cap(8)).map((p: any) => (
              <Link key={p.name} href={`/program/${enc(p.name)}`} className="result">
                <span className="mono result-title"><Highlight text={p.name} q={q} /></span>
                <span className="spacer" />
                <span className="sub">{p.reached_launches ? `${fmtNum(p.reached_launches)} launches` : "no recorded launches"}</span>
              </Link>
            ))}
          </Card>
        )}

        {show("menus") && r.menus.length > 0 && (
          <Card title={<span className="row" style={{ gap: 6 }}><MenuIcon size={15} /> Menus</span>} actions={r.menus.length > 6 ? more("menus", r.menus.length, "menus") : undefined}>
            {r.menus.slice(0, cap(6)).map((m: any) => (
              <Link key={m.code} href={`/menu/${enc(m.code)}`} className="result">
                <span className="mono result-title"><Highlight text={m.code} q={q} /></span>
                <span className="sub mono"><Highlight text={m.program ?? m.exec} q={q} /></span>
                <span className="spacer" />
                <span className="sub nowrap">{fmtNum(m.used)} launches</span>
              </Link>
            ))}
          </Card>
        )}

        {show("fields") && fields.length > 0 && (
          <Card title={<span className="row" style={{ gap: 6 }}><FieldIcon size={15} /> Fields</span>} actions={fields.length > 8 ? more("fields", fields.length, "fields") : undefined}>
            {fields.slice(0, cap(8)).map((f: any, i: number) => (
              <Link key={`${f.file}-${f.attr}-${i}`} href={`/field/${enc(f.file)}/${f.attr}`} className="result">
                <span className="mono result-title">{f.file}&lt;{f.attr}&gt;</span>
                <span className="sub row" style={{ gap: 4 }}><DictIcon size={12} /> <Highlight text={f.name} q={q} /></span>
              </Link>
            ))}
          </Card>
        )}

        {show("code") && byProgram.size > 0 && (
          <Card className="wide" title={<span className="row" style={{ gap: 6 }}><CodeIcon size={15} /> In the code</span>}
            sub={`${fmtNum(code.hits.length)}${code.truncated ? "+" : ""} lines in ${byProgram.size} programs`}
            actions={byProgram.size > 6 ? more("code", byProgram.size, "programs") : undefined}>
            {[...byProgram.entries()].slice(0, cap(6)).map(([prog, hits]) => (
              <div key={prog} className="code-hit">
                <div className="row" style={{ marginBottom: 6 }}>
                  <Link href={`/program/${enc(prog)}`} className="mono result-title">{prog}</Link>
                  <span className="sub">{hits.length} line{hits.length === 1 ? "" : "s"}</span>
                </div>
                <div className="code">
                  {hits.slice(0, tab === "code" ? 12 : 3).map((h: any) => (
                    <div key={h.line} className="ln">
                      <span className="no"><Link href={`/program/${enc(prog)}/source?line=${h.line}`}>{h.line}</Link></span>
                      <span className="tx"><Highlight text={h.text} q={q} /></span>
                    </div>
                  ))}
                </div>
              </div>
            ))}
            {code.truncated && tab === "code" && <div className="card-foot">Showing the first {code.hits.length} matching lines. Narrow the search to see more.</div>}
          </Card>
        )}
      </div>
    </>
  );
}
