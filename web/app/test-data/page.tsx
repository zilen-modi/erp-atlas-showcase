import Finder from "@/components/compare/Finder";
import { PageHeader } from "@/components/ui";

export default function FindPage({ searchParams }: { searchParams: { file?: string } }) {
  return (
    <>
      <PageHeader title="Test data"
        desc="Describe the record you need and Atlas finds matching records on TEST (read-only), so you don't have to hunt for keys. Save a search as a scenario to reuse it." />
      <section className="card"><div className="card-body"><Finder initialFile={(searchParams.file ?? "").toUpperCase()} library /></div></section>
    </>
  );
}
