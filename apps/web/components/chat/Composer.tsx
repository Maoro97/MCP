"use client";

import { useRef, useState } from "react";
import { ArrowUp, Lock } from "lucide-react";

/** Chat input. Enter to send, Shift+Enter for newline. */
export function Composer({
  onSend,
  disabled,
  rtl,
}: {
  onSend: (text: string) => void;
  disabled?: boolean;
  rtl?: boolean;
}) {
  const [value, setValue] = useState("");
  const ref = useRef<HTMLTextAreaElement>(null);

  const submit = () => {
    const t = value.trim();
    if (!t || disabled) return;
    onSend(t);
    setValue("");
    if (ref.current) ref.current.style.height = "auto";
  };

  return (
    <div className="mx-auto w-full max-w-3xl px-4 pb-4">
      <div className="flex items-end gap-2 rounded-2xl border border-[color:var(--border)] bg-[color:var(--surface)] p-2 shadow-[var(--shadow)] focus-within:border-[color:var(--accent)]">
        <textarea
          ref={ref}
          value={value}
          rows={1}
          dir={rtl ? "rtl" : "ltr"}
          placeholder={
            rtl ? "שאלו על הזמנות, לקוחות, חשבוניות…" : "Ask about orders, customers, invoices, inventory…"
          }
          onChange={(e) => {
            setValue(e.target.value);
            e.target.style.height = "auto";
            e.target.style.height = Math.min(e.target.scrollHeight, 160) + "px";
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter" && !e.shiftKey) {
              e.preventDefault();
              submit();
            }
          }}
          className="max-h-40 flex-1 resize-none bg-transparent px-2 py-1.5 text-sm outline-none placeholder:text-[color:var(--faint)]"
        />
        <button
          onClick={submit}
          disabled={disabled || !value.trim()}
          aria-label="Send"
          className="grid h-9 w-9 shrink-0 place-items-center rounded-xl bg-[color:var(--accent)] text-[color:var(--accent-contrast)] transition-opacity hover:bg-[color:var(--accent-hover)] disabled:opacity-40"
        >
          <ArrowUp size={18} />
        </button>
      </div>
      <div className="mt-2 flex items-center justify-center gap-1.5 text-xs text-[color:var(--faint)]">
        <Lock size={11} />
        <span>Read-only · connected to Priority ERP (demo data)</span>
      </div>
    </div>
  );
}
