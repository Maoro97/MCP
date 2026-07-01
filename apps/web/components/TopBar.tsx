"use client";

import { Moon, Sun, Languages, PanelLeft, Sparkles } from "lucide-react";

export function TopBar({
  dark,
  onToggleDark,
  rtl,
  onToggleRtl,
  onToggleSidebar,
}: {
  dark: boolean;
  onToggleDark: () => void;
  rtl: boolean;
  onToggleRtl: () => void;
  onToggleSidebar: () => void;
}) {
  return (
    <header className="flex h-14 shrink-0 items-center justify-between border-b border-[color:var(--border)] bg-[color:var(--surface)] px-3">
      <div className="flex items-center gap-2">
        <button
          onClick={onToggleSidebar}
          aria-label="Toggle sidebar"
          className="grid h-8 w-8 place-items-center rounded-lg text-[color:var(--muted)] hover:bg-[color:var(--surface-2)] md:hidden"
        >
          <PanelLeft size={18} />
        </button>
        <div className="flex items-center gap-2">
          <div className="grid h-7 w-7 place-items-center rounded-lg bg-[color:var(--accent)] text-[color:var(--accent-contrast)]">
            <Sparkles size={15} />
          </div>
          <div className="leading-tight">
            <div className="text-sm font-semibold">Priority Chat</div>
            <div className="text-[10px] text-[color:var(--faint)]">
              ERP assistant · read-only
            </div>
          </div>
        </div>
      </div>

      <div className="flex items-center gap-1.5">
        <span className="hidden rounded-full border border-[color:var(--border)] bg-[color:var(--surface-2)] px-2.5 py-1 text-xs text-[color:var(--muted)] sm:inline">
          Claude · Sonnet
        </span>
        <button
          onClick={onToggleRtl}
          aria-label="Toggle direction"
          className={`grid h-8 w-8 place-items-center rounded-lg hover:bg-[color:var(--surface-2)] ${
            rtl ? "text-[color:var(--accent)]" : "text-[color:var(--muted)]"
          }`}
          title={rtl ? "Switch to LTR" : "עברית / RTL"}
        >
          <Languages size={17} />
        </button>
        <button
          onClick={onToggleDark}
          aria-label="Toggle theme"
          className="grid h-8 w-8 place-items-center rounded-lg text-[color:var(--muted)] hover:bg-[color:var(--surface-2)]"
        >
          {dark ? <Sun size={17} /> : <Moon size={17} />}
        </button>
      </div>
    </header>
  );
}
