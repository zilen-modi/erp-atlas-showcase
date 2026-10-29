import { redirect } from "next/navigation";

// moved to its own section
export default function FindPage({ searchParams }: { searchParams: { file?: string } }) {
  redirect(`/test-data${searchParams.file ? `?file=${encodeURIComponent(searchParams.file)}` : ""}`);
}
