import RunView from "@/components/compare/RunView";

export const dynamic = "force-dynamic";

export default function RunPage({ params }: { params: { id: string } }) {
  return <RunView runId={params.id} />;
}
