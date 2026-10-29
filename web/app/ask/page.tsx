import AskClient from "@/components/AskClient";

export const dynamic = "force-dynamic";

export default function AskPage({ searchParams }: { searchParams: { chat?: string; q?: string } }) {
  return <AskClient initialChat={searchParams.chat} initialQ={searchParams.q} />;
}
