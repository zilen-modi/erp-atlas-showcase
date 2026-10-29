import { redirect } from "next/navigation";
import FactsReview from "@/components/facts/FactsReview";
import { PageHeader } from "@/components/ui";
import { api, enc } from "@/lib/api";

export const dynamic = "force-dynamic";

// The review queue for what Atlas has learned. Old links such as /facts?q=F-0005 (from chat answers) still
// jump to the page the fact is about.
export default async function FactsPage({ searchParams }: { searchParams: { q?: string; tab?: string } }) {
  const id = (searchParams.q ?? "").trim().toUpperCase();
  if (/^F-\d{4}$/.test(id)) {
    const f: any = await api(`/api/facts/${enc(id)}`).catch(() => null);
    if (f?.home) redirect(`${f.home}#${id}`);
    redirect(`/facts?tab=${f?.status === "accepted" ? "accepted" : f?.status === "stale" ? "stale" : "proposed"}#${id}`);
  }
  const me: any = await api("/api/auth/me").catch(() => null);
  const tab = (["stale", "proposed", "accepted"].includes(searchParams.tab ?? "") ? searchParams.tab : "stale") as "stale" | "proposed" | "accepted";
  return (
    <>
      <PageHeader title="Facts" desc="What Atlas has learned about the legacy code, each tied to the lines it cites. A named person confirms each one; Ask Atlas only states confirmed facts without a caveat." />
      <FactsReview admin={me?.user?.role === "admin"} initial={tab} />
    </>
  );
}
