import NavSettings from "@/components/NavSettings";
import SettingsForm from "@/components/SettingsForm";
import { PageHeader } from "@/components/ui";

export default function SettingsPage() {
  return (
    <>
      <PageHeader title="Settings" desc="Where Atlas reads TEST from, and which tabs the sidebar shows. Changes apply straight away, for everyone using this Atlas." />
      <SettingsForm />
      <NavSettings />
    </>
  );
}
