"use client";

import PasswordForm from "@/components/account/PasswordForm";

// Shown in place of every page until someone signed in with a one-time password chooses their own.
export default function FirstPassword({ name }: { name: string }) {
  return (
    <div className="auth-wrap">
      <div className="auth-card">
        <h1>Welcome, {name.split(" ")[0]}</h1>
        <p className="sub">Choose your own password to finish setting up your account.</p>
        <PasswordForm first onDone={() => window.location.assign("/account?welcome=1")} />
      </div>
    </div>
  );
}
