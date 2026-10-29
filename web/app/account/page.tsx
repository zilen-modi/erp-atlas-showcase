import AccountPanel from "@/components/account/AccountPanel";
import { PageHeader } from "@/components/ui";

export default function AccountPage({ searchParams }: { searchParams: { welcome?: string } }) {
  return (
    <>
      <PageHeader title="Your account" desc="Your password, and the Claude account Ask Atlas and “Describe the record you need” run on." />
      <AccountPanel welcome={searchParams.welcome === "1"} />
    </>
  );
}
