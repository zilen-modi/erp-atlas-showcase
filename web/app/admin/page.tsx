import { redirect } from "next/navigation";
import AdminPanel from "@/components/account/AdminPanel";
import KnowledgeAdmin from "@/components/knowledge/KnowledgeAdmin";
import QualityAdmin from "@/components/quality/QualityAdmin";
import { PageHeader } from "@/components/ui";
import { api } from "@/lib/api";

export default async function AdminPage() {
  const me: any = await api("/api/auth/me").catch(() => null);
  if (me?.user?.role !== "admin") redirect("/");
  return (
    <>
      <PageHeader title="Admin" desc="Who can use Atlas, what they've asked Claude, what they've changed, and what Atlas has written down." />
      <AdminPanel meId={me.user.id} />
      <div style={{ marginTop: 16 }}><QualityAdmin /></div>
      <div style={{ marginTop: 16 }}><KnowledgeAdmin /></div>
    </>
  );
}
