"use client";

import {
  Plus,
  MessageSquare,
  Star,
  Database,
  ChevronRight,
} from "lucide-react";
import { ENTITIES, HISTORY, SAVED_QUERIES } from "@/lib/mock";

export function Sidebar({
  open,
  onNewChat,
  onPick,
}: {
  open: boolean;
  onNewChat: () => void;
  onPick: (q: string) => void;
}) {
  return (
    <aside
      className={`${
        open ? "flex" : "hidden"
      } w-64 shrink-0 flex-col border-e border-[color:var(--border)] bg-[color:var(--surface)] md:flex`}
    >
      <div className="p-3">
        <button
          onClick={onNewChat}
          className="flex w-full items-center justify-center gap-2 rounded-xl bg-[color:var(--accent)] px-3 py-2.5 text-sm font-medium text-[color:var(--accent-contrast)] transition-colors hover:bg-[color:var(--accent-hover)]"
        >
          <Plus size={16} />
          New chat
        </button>
      </div>

      <div className="flex-1 space-y-5 overflow-y-auto px-3 pb-4">
        <Section icon={<MessageSquare size={13} />} title="Recent">
          {HISTORY.map((h) => (
            <Item key={h} onClick={() => onPick(h)}>
              {h}
            </Item>
          ))}
        </Section>

        <Section icon={<Star size={13} />} title="Saved queries">
          {SAVED_QUERIES.map((s) => (
            <Item key={s} onClick={() => onPick(s)}>
              {s}
            </Item>
          ))}
        </Section>

        <Section icon={<Database size={13} />} title="Entities">
          {ENTITIES.map((e) => (
            <button
              key={e.form}
              onClick={() => onPick(`Show me ${e.label.toLowerCase()}`)}
              className="group flex w-full items-center justify-between gap-2 rounded-lg px-2.5 py-1.5 text-start text-sm text-[color:var(--muted)] hover:bg-[color:var(--surface-2)] hover:text-[color:var(--text)]"
            >
              <span className="truncate">
                {e.label}
                <span className="ms-1 font-mono text-[10px] text-[color:var(--faint)]">
                  {e.form}
                </span>
              </span>
              <span className="shrink-0 text-xs text-[color:var(--faint)]">
                {e.count}
              </span>
            </button>
          ))}
        </Section>
      </div>

      <div className="border-t border-[color:var(--border)] p-3">
        <button className="flex w-full items-center justify-between rounded-lg px-2.5 py-2 text-sm text-[color:var(--muted)] hover:bg-[color:var(--surface-2)]">
          <span className="flex items-center gap-2">
            <span className="grid h-6 w-6 place-items-center rounded-full bg-[color:var(--accent-soft)] text-xs font-semibold text-[color:var(--accent)]">
              PG
            </span>
            Priority Guru
          </span>
          <ChevronRight size={14} className="rtl:rotate-180" />
        </button>
      </div>
    </aside>
  );
}

function Section({
  icon,
  title,
  children,
}: {
  icon: React.ReactNode;
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div>
      <div className="mb-1.5 flex items-center gap-1.5 px-2.5 text-xs font-semibold uppercase tracking-wide text-[color:var(--faint)]">
        {icon}
        {title}
      </div>
      <div className="space-y-0.5">{children}</div>
    </div>
  );
}

function Item({
  children,
  onClick,
}: {
  children: React.ReactNode;
  onClick: () => void;
}) {
  return (
    <button
      onClick={onClick}
      className="w-full truncate rounded-lg px-2.5 py-1.5 text-start text-sm text-[color:var(--muted)] hover:bg-[color:var(--surface-2)] hover:text-[color:var(--text)]"
    >
      {children}
    </button>
  );
}
