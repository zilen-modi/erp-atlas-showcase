import Link from "next/link";
import FlowEditor from "@/components/compare/FlowEditor";
import SuggestFlows from "@/components/compare/SuggestFlows";
import { PageHeader } from "@/components/ui";

export default function NewFlowPage({ searchParams }: { searchParams: { draft?: string; topic?: string; program?: string } }) {
  const fromDraft = searchParams.draft === "1";
  const initial = searchParams.program ?? searchParams.topic ?? "";
  return (
    <>
      <PageHeader
        eyebrow={<Link href="/compare">Compare</Link>}
        title="New flow"
        desc={fromDraft
          ? "Review the suggested flow, adjust anything, then create it."
          : "Start from a suggestion, or name what you're testing, list the checkpoints, and add every file the flow touches."}
      />
      <div className="stack">
        {!fromDraft && <SuggestFlows initial={initial} />}
        <FlowEditor />
      </div>
    </>
  );
}
