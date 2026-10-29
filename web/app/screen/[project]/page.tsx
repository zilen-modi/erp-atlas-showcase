import Link from "next/link";
import ScreenCanvas from "@/components/ScreenCanvas";
import AskButton from "@/components/AskButton";
import { ErrorBox, PageHeader, ProgramLink } from "@/components/ui";
import { api, enc, fmtNum } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function ScreenPage({ params, searchParams }: { params: { project: string }; searchParams: { form?: string } }) {
  const project = decodeURIComponent(params.project);
  let s: any;
  try {
    s = await api(`/api/screens/${enc(project)}?track=true`);
  } catch (e) {
    return <ErrorBox error={e} />;
  }
  const form = (searchParams.form ?? s.forms[0]?.name ?? "").toUpperCase();
  return (
    <>
      <PageHeader eyebrow={<Link href="/screens">Screens</Link>} title={s.project} mono
        meta={<>
          <span>driven by <ProgramLink name={s.program} strong /></span><span>·</span>
          <span>{s.forms.length} form{s.forms.length === 1 ? "" : "s"}, {fmtNum(s.controls)} controls</span>
          {s.launches ? <><span>·</span><span>{fmtNum(s.launches)} menu launches</span></> : null}
          {s.menus.length > 0 && <><span>·</span><span>{s.menus.slice(0, 3).map((m: any, i: number) => <span key={m.code}>{i > 0 && ", "}<Link href={`/menu/${enc(m.code)}`} className="mono">{m.code}</Link></span>)}</span></>}
        </>}
        desc={<>Drawn from the git copy of <code>src/TEMPLATES/{s.project}</code>, last saved in the AccuTerm designer {s.saved_at ?? "at an unknown time"}. The live template can differ from git.</>}
        actions={<AskButton question={`Walk me through the ${s.project} screen (form ${form}): what each main control does, which handlers run, and which files and fields they write.`} />}
      />
      <nav className="tabs form-tabs">
        {s.forms.map((f: any) => (
          <Link key={f.name} href={`/screen/${enc(s.project)}?form=${enc(f.name)}`} className={f.name === form ? "active" : ""}
            title={f.title}>
            {f.name} <span className="faint">{f.controls}</span>
          </Link>
        ))}
      </nav>
      <ScreenCanvas project={s.project} form={form} program={s.program} />
    </>
  );
}
