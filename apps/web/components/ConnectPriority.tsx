"use client";

import { Database, ArrowRight, ShieldCheck, AlertTriangle } from "lucide-react";

/** Shown when Priority is configured but the user hasn't logged in yet. */
export function ConnectPriority({
  canOAuth,
  error,
}: {
  canOAuth: boolean;
  error?: string;
}) {
  return (
    <div className="mx-auto flex max-w-md flex-col items-center px-4 py-16 text-center">
      <div className="mb-4 grid h-14 w-14 place-items-center rounded-2xl bg-[color:var(--accent-soft)] text-[color:var(--accent)]">
        <Database size={26} />
      </div>
      <h1 className="text-2xl font-semibold tracking-tight">Connect to Priority</h1>
      <p className="mt-2 text-sm text-[color:var(--muted)]">
        Sign in with your Priority account to query live data. Access is
        <span className="font-medium text-[color:var(--text)]"> read-only</span> and
        respects your own Priority permissions.
      </p>

      {error && (
        <div className="mt-4 flex items-start gap-2 rounded-xl border border-[color:var(--neg)]/30 bg-[color:var(--neg)]/10 px-3 py-2 text-start text-sm text-[color:var(--neg)]">
          <AlertTriangle size={16} className="mt-0.5 shrink-0" />
          <span>Sign-in failed: {error}</span>
        </div>
      )}

      {canOAuth ? (
        <a
          href="/api/auth/login"
          className="mt-6 inline-flex items-center gap-2 rounded-xl bg-[color:var(--accent)] px-5 py-3 text-sm font-medium text-[color:var(--accent-contrast)] transition-colors hover:bg-[color:var(--accent-hover)]"
        >
          Sign in with Priority
          <ArrowRight size={16} className="rtl:rotate-180" />
        </a>
      ) : (
        <div className="mt-6 rounded-xl border border-[color:var(--border)] bg-[color:var(--surface-2)] px-4 py-3 text-start text-sm text-[color:var(--muted)]">
          OAuth isn&apos;t fully configured yet. Set{" "}
          <code className="font-mono text-xs">PRIORITY_OIDC_ISSUER</code>,{" "}
          <code className="font-mono text-xs">PRIORITY_OAUTH_CLIENT_ID</code> and{" "}
          <code className="font-mono text-xs">SESSION_SECRET</code> in{" "}
          <code className="font-mono text-xs">.env.local</code>, or set{" "}
          <code className="font-mono text-xs">PRIORITY_ACCESS_TOKEN</code> for a quick test.
        </div>
      )}

      <div className="mt-8 flex items-center gap-1.5 text-xs text-[color:var(--faint)]">
        <ShieldCheck size={13} />
        <span>Credentials stay on the server · never shown in the browser</span>
      </div>
    </div>
  );
}
