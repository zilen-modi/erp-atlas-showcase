import Link from "next/link";
import {
  AlertIcon, ArrowIcon, ChatIcon, CompareIcon, FactIcon, GitIcon, NoteIcon, PlusIcon, ProgramIcon, ReportIcon, SearchIcon,
  SparkIcon,
} from "@/components/Icons";
import JobButton from "@/components/JobButton";
import MeaningBox from "@/components/overview/MeaningBox";
import { Card, EmptyState, ErrorBox, PageHeader, Stat } from "@/components/ui";
import { ago, api, enc, fmtNum, fmtTime } from "@/lib/api";

export const dynamic = "force-dynamic";

// compact launch counts: 10,232,634 -> 10.2M
function short(n: number | null | undefined) {
  if (!n) return null;
  if (n >= 1e6) return `${(n / 1e6).toFixed(n >= 1e7 ? 0 : 1)}M`;
  if (n >= 1e3) return `${Math.round(n / 1e3)}k`;
  return String(n);
}

export default async function Overview() {
  let d: any;
  let admin = false;
  try {
    d = await api("/api/dashboard");
    admin = (await api("/api/auth/me").catch(() => null))?.user?.role === "admin";
  } catch (e) {
    return <ErrorBox error={e} />;
  }
  const s = d.stats;

  return (
    <>
      <PageHeader
        title="Overview"
        desc="What needs you, what changed in the legacy code that matters to you, and your work in progress."
        actions={
          <>
            <Link href="/ask" className="btn"><ChatIcon size={14} /> Ask Atlas</Link>
            <Link href="/compare/flows/new" className="btn"><PlusIcon size={14} /> New compare flow</Link>
            {admin && <JobButton endpoint="/api/jobs/sync" body={{ live: false }} label="Sync with git" primary />}
          </>
        }
      />

      {d.needs_you.length > 0 && (
        <section className="card ny-card">
          <div className="card-head"><h2>Needs you</h2><span className="sub">{d.needs_you.length} thing{d.needs_you.length === 1 ? "" : "s"}</span></div>
          <ul className="ny-list">
            {d.needs_you.map((n: any) => (
              <li key={n.title} className={`ny ${n.level}`}>
                <span className="ny-dot" aria-hidden="true" />
                <div className="ny-body">
                  <div className="ny-title">{n.title}</div>
                  <div className="sub">{n.detail}</div>
                </div>
                {n.action === "sync" && admin
                  ? <JobButton endpoint="/api/jobs/sync" body={{ live: false }} label="Sync now" />
                  : <Link href={n.href} className="btn sm">{n.level === "high" ? "Fix" : "Open"} <ArrowIcon size={13} /></Link>}
              </li>
            ))}
          </ul>
        </section>
      )}

      <MeaningBox />

      <div className="grid cols-4" style={{ marginBottom: 16 }}>
        <Stat icon={<CompareIcon size={18} />} label="Compare runs" value={fmtNum(s.runs)}
          note={`${fmtNum(s.flows)} flow${s.flows === 1 ? "" : "s"}`} href="/compare" />
        <Stat icon={<NoteIcon size={18} />} label="Open issues" value={<span style={s.open_issues ? { color: "var(--bad)" } : undefined}>{fmtNum(s.open_issues)}</span>}
          note="Compare notes marked bug or question" href="#issues" />
        <Stat icon={<AlertIcon size={18} />} label="TEST runs a different version"
          value={<span style={s.test_differs ? { color: "var(--warn)" } : undefined}>{fmtNum(s.test_differs)}</span>}
          note={`of ${fmtNum(s.test_checked)} programs checked`} href="/drift?state=drift" />
        <Stat icon={<FactIcon size={18} />} label="Confirmed facts" value={fmtNum(s.facts_confirmed)}
          note={s.facts_open ? `${fmtNum(s.facts_open)} waiting for review` : "nothing waiting for review"} href="/facts" />
      </div>

      <div className="grid side">
        <div className="stack">
          <Card title="Changed since you last looked"
            sub={d.changed.since ? `${d.changed.total} commit${d.changed.total === 1 ? "" : "s"} since ${fmtTime(d.changed.since)}` : `${d.changed.total}${d.changed.total >= 40 ? "+" : ""} commit${d.changed.total === 1 ? "" : "s"} in the last two weeks`}
            actions={<Link href="/drift" className="btn sm ghost">TEST vs git <ArrowIcon size={13} /></Link>}>
            {d.changed.yours.length > 0 && (
              <div className="cs-yours">
                <div className="cs-label">Touches your work</div>
                {d.changed.yours.map((y: any) => (
                  <Link key={y.program} href={`/program/${enc(y.program)}`} className="cs-item">
                    <span className="mono cs-name">{y.program}</span>
                    <span className="cs-body">
                      {y.summary && <span className="cs-summary">{y.summary}</span>}
                      <span className="sub">{y.why} · changed in “{y.commit}” by {y.author}, {y.date}</span>
                    </span>
                  </Link>
                ))}
              </div>
            )}
            {d.changed.yours.length === 0 && d.changed.total > 0 && (
              <div className="sub cs-none">{d.changed.tracking > 0
                ? "None of these touch programs you've looked at or fields your saved scenarios use."
                : "Open programs and save Test data scenarios, and changes to them are picked out here."}</div>
            )}
            {d.changed.commits.length === 0 && <div className="empty">No commits to the legacy code since then.</div>}
            {d.changed.commits.map((c: any) => (
              <div key={c.sha} className="feed-item">
                <span className={`feed-dot ${c.impact >= 1e6 ? "hot" : ""}`} />
                <div style={{ minWidth: 0, flex: 1 }}>
                  <div className="row" style={{ gap: 8 }}>
                    <b style={{ minWidth: 0 }} className="ellipsis">{c.summary}</b>
                    {c.impact >= 1e6 && <span className="badge red" title="A changed program is reached by over a million menu launches">high impact</span>}
                  </div>
                  <div className="sub">{c.author} · {c.date} · <code>{c.sha.slice(0, 9)}</code> · {c.changed} file{c.changed === 1 ? "" : "s"}</div>
                  <div className="chips" style={{ marginTop: 6 }}>
                    {c.files.map((f: any) => (
                      <Link key={f.name} href={`/program/${enc(f.name)}`} className="chip"
                        title={[f.launches ? `${fmtNum(f.launches)} menu launches reach it` : "no recorded menu launches", f.test_differs ? "TEST runs a different version" : ""].filter(Boolean).join(" · ")}>
                        <span className="mono">{f.name}</span>
                        {short(f.launches) && <span className="chip-meta">{short(f.launches)}</span>}
                        {f.test_differs && <span className="chip-warn">TEST differs</span>}
                      </Link>
                    ))}
                    {c.changed > c.files.length && <span className="sub">+{c.changed - c.files.length} more</span>}
                  </div>
                </div>
              </div>
            ))}
            {d.changed.total > d.changed.commits.length && <div className="card-foot">Showing the latest {d.changed.commits.length} of {d.changed.total}.</div>}
          </Card>

          <Card title="Continue where you left off" sub="Latest compare runs"
            actions={<Link href="/compare" className="btn sm ghost">All flows <ArrowIcon size={13} /></Link>}>
            {d.runs.length === 0 ? (
              <EmptyState title="No compare runs yet" icon={<CompareIcon size={20} />}>
                Pick a flow such as “Create transfer”, make the same record in both systems, and compare them field by field.{" "}
                <Link href="/compare/flows/new">Start a flow</Link>
              </EmptyState>
            ) : (
              <div className="table-wrap">
                <table>
                  <thead><tr><th>Run</th><th>Progress</th><th className="num">To review</th></tr></thead>
                  <tbody>
                    {d.runs.map((r: any) => (
                      <tr key={r.id}>
                        <td style={{ minWidth: 0 }}>
                          <Link href={`/compare/runs/${r.id}`} style={{ fontWeight: 600 }}>{r.name}</Link>
                          <span className="faint" style={{ fontSize: 12, marginLeft: 8 }}>{ago(r.updated_at)}</span>
                          <div className="sub ellipsis" style={{ maxWidth: 340 }} title={r.flow}>{r.flow}</div>
                        </td>
                        <td style={{ minWidth: 0 }}>
                          <div className="progress" title={`${r.captured_steps} of ${r.steps} steps captured`}>
                            {Array.from({ length: r.steps }, (_, i) => <span key={i} className={i < r.captured_steps ? "on" : ""} />)}
                          </div>
                          <div className="sub ellipsis" style={{ maxWidth: 200 }} title={r.step ?? undefined}>
                            {r.captured_steps}/{r.steps} · {r.step ? r.step.replace(/\s*\(.*$/, "") : "nothing captured"}
                          </div>
                        </td>
                        <td className="num nowrap">
                          {r.differences == null ? <span className="faint">—</span> : (
                            <span className={`badge ${r.differences - r.explained > 0 ? "red" : "green"}`}
                              title={`${r.differences} differences at the latest step, ${r.explained} explained by notes`}>
                              {r.differences - r.explained > 0 ? `${r.differences - r.explained} fields` : "all explained"}
                            </span>
                          )}
                          {r.bugs > 0 && <> <span className="badge red">{r.bugs} bug{r.bugs === 1 ? "" : "s"}</span></>}
                          {r.questions > 0 && <> <span className="badge amber">{r.questions} ?</span></>}
                          {r.files_not_found > 0 && <div className="sub" title="Files with no record on either side at the latest step">{r.files_not_found} not found</div>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>

          <section id="issues">
            <Card title="Open issues" sub={d.issues.total ? `${d.issues.total} marked bug or question in Compare` : "From Compare notes"}>
              {d.issues.items.length === 0 ? (
                <div className="empty">No open issues. Mark a field difference as <b>Bug</b> or <b>Question</b> in a compare run and it shows here until it's marked expected or fixed.</div>
              ) : (
                <div className="issue-list">
                  {d.issues.items.map((n: any) => (
                    <Link key={n.id} href={n.href} className="issue">
                      <span className={`badge ${n.verdict === "bug" ? "red" : "amber"}`}>{n.verdict === "bug" ? "Bug" : "Question"}</span>
                      <div style={{ minWidth: 0, flex: 1 }}>
                        <div className="issue-field mono">{n.pick_file}&lt;{n.attr}&gt;{n.names.length > 0 && <span className="sub"> {n.names.join(", ")}</span>}</div>
                        <div className="issue-text">{n.text || <span className="faint">No text</span>}</div>
                        <div className="sub">{n.run ?? "every run"} · {n.flow} · {ago(n.at)}</div>
                      </div>
                    </Link>
                  ))}
                </div>
              )}
            </Card>
          </section>

        </div>

        <div className="stack">
          <Card title="Recently viewed">
            {d.recent.length === 0 ? <div className="empty">Programs, files and fields you open show here.</div> : (
              <div className="mini-list">
                {d.recent.map((r: any) => (
                  <Link key={`${r.kind}-${r.key}`} href={r.href} className="mini">
                    <span className="badge">{r.label}</span>
                    <span className="mono ellipsis" style={{ flex: 1 }}>{r.key}</span>
                    <span className="sub nowrap">{ago(r.at)}</span>
                  </Link>
                ))}
              </div>
            )}
          </Card>


          <Card title="Your work">
            <div className="yw">
              <div className="yw-head"><SearchIcon size={14} /> Saved scenarios <Link href="/test-data?tab=saved" className="sub">all</Link></div>
              {d.work.scenarios.length === 0 ? <div className="sub yw-empty">None yet. <Link href="/test-data">Find test data</Link> and save the search.</div> : d.work.scenarios.map((x: any) => (
                <Link key={x.id} href={`/test-data?scenario=${x.id}`} className="mini">
                  <span className="ellipsis" style={{ flex: 1 }} title={x.name}>{x.name}</span>
                  <span className="mono sub">{x.pick_file}</span>
                  {x.last_count == null ? <span className="sub nowrap">not run</span>
                    : <span className={`badge ${x.last_count === 0 ? "red" : "green"}`}>{x.last_count === 0 ? "none" : x.last_count}</span>}
                </Link>
              ))}
              <div className="yw-head"><ChatIcon size={14} /> Your questions <Link href="/ask" className="sub">ask</Link></div>
              {d.work.chats.length === 0 ? <div className="sub yw-empty">Ask anything about the old system: a flow, a field, a rule.</div> : d.work.chats.map((q: any) => (
                <Link key={q.chat_id} href={`/ask?chat=${q.chat_id}`} className="mini">
                  <span className="ellipsis" style={{ flex: 1 }} title={q.question}>{q.question}</span>
                  <span className="sub nowrap">{ago(q.at)}</span>
                </Link>
              ))}
              <div className="yw-head"><ReportIcon size={14} /> Your PDFs <Link href="/reports" className="sub">all</Link></div>
              {d.work.reports.length === 0 ? <div className="sub yw-empty">Use <b>Export</b> in the top bar on any page.</div> : d.work.reports.map((r: any) => (
                <Link key={r.id} href={`/reports/${r.id}`} className="mini">
                  <span className="ellipsis" style={{ flex: 1 }} title={r.title}>{r.title}</span>
                  <span className="sub nowrap">{r.pages} p · {ago(r.created_at)}</span>
                </Link>
              ))}
            </div>
          </Card>

          {d.ideas.length > 0 && (
            <Card title="Worth understanding next" sub="Heavily used, not asked about yet">
              {d.ideas.map((i: any) => (
                <div key={i.title} className="idea">
                  <span className="idea-ico"><SparkIcon size={15} /></span>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <Link href={i.href} className="idea-title">{i.title}</Link>
                    <div className="sub ellipsis">{i.why}</div>
                  </div>
                  <Link className="btn sm" href={`/ask?q=${enc(i.question)}`}>Ask</Link>
                </div>
              ))}
            </Card>
          )}

          <Card title="Data quality" sub="Latest profiles on TEST"
            actions={<Link href="/quality" className="btn sm ghost">All <ArrowIcon size={13} /></Link>}>
            {d.quality.length === 0 ? <div className="empty">Profile a file to see what it really holds before migrating it. <Link href="/quality">Start</Link></div> : (
              <div className="mini-list">
                {d.quality.map((q: any) => (
                  <Link key={q.id} href={`/files/${enc(q.pick_file)}/profile`} className="mini">
                    <span className="mono ellipsis" style={{ flex: 1, fontWeight: 600 }}>{q.pick_file}</span>
                    {q.errors > 0 && <span className="badge red">{q.errors} err</span>}
                    {q.warnings > 0 && <span className="badge amber">{q.warnings} warn</span>}
                    {!q.errors && !q.warnings && <span className="badge green">clean</span>}
                    <span className="sub nowrap">{ago(q.finished_at)}</span>
                  </Link>
                ))}
              </div>
            )}
          </Card>

          <Card title="Codebase" sub="git main">
            <div className="card-body mini-stats">
              <Link href="/programs"><ProgramIcon size={15} /> <b>{fmtNum(s.programs)}</b> programs</Link>
              <Link href="/drift"><GitIcon size={15} /> <b>{fmtNum(s.test_checked)}</b> compared with TEST</Link>
              <Link href="/ask"><ChatIcon size={15} /> <b>{fmtNum(s.answers)}</b> questions answered</Link>
            </div>
          </Card>
        </div>
      </div>
    </>
  );
}
