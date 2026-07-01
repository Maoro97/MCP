"use client";

import { useState } from "react";
import { ArrowUpDown } from "lucide-react";
import type { TableWidget } from "@/lib/types";
import { StatusPill } from "./StatusPill";

/** Sortable data table for lists of orders / invoices / parts. */
export function DataTable({ widget }: { widget: TableWidget }) {
  const [sortKey, setSortKey] = useState<string | null>(null);
  const [asc, setAsc] = useState(true);

  const rows = [...widget.rows];
  if (sortKey) {
    rows.sort((a, b) => {
      const av = a.cells[sortKey];
      const bv = b.cells[sortKey];
      const an = typeof av === "number" ? av : parseFloat(String(av).replace(/[^\d.-]/g, ""));
      const bn = typeof bv === "number" ? bv : parseFloat(String(bv).replace(/[^\d.-]/g, ""));
      let cmp: number;
      if (!isNaN(an) && !isNaN(bn)) cmp = an - bn;
      else cmp = String(av).localeCompare(String(bv));
      return asc ? cmp : -cmp;
    });
  }

  const toggle = (key: string) => {
    if (sortKey === key) setAsc((v) => !v);
    else {
      setSortKey(key);
      setAsc(true);
    }
  };

  const hasStatus = widget.rows.some((r) => r.status);

  return (
    <div className="overflow-hidden rounded-[var(--radius-app)] border border-[color:var(--border)] bg-[color:var(--surface)]">
      <div className="border-b border-[color:var(--border)] px-4 py-2.5 text-sm font-semibold">
        {widget.title}
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-[color:var(--muted)]">
              {widget.columns.map((c) => (
                <th
                  key={c.key}
                  onClick={() => toggle(c.key)}
                  className={`cursor-pointer select-none whitespace-nowrap px-4 py-2 font-medium hover:text-[color:var(--text)] ${
                    c.numeric ? "text-end" : "text-start"
                  }`}
                >
                  <span className="inline-flex items-center gap-1">
                    {c.label}
                    <ArrowUpDown
                      size={12}
                      className={sortKey === c.key ? "text-[color:var(--accent)]" : "opacity-30"}
                    />
                  </span>
                </th>
              ))}
              {hasStatus && (
                <th className="px-4 py-2 text-start font-medium">Status</th>
              )}
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr
                key={i}
                className="border-t border-[color:var(--border)] transition-colors hover:bg-[color:var(--surface-2)]"
              >
                {widget.columns.map((c) => (
                  <td
                    key={c.key}
                    className={`whitespace-nowrap px-4 py-2.5 ${
                      c.numeric ? "text-end tabular-nums" : "text-start"
                    }`}
                  >
                    {r.cells[c.key]}
                  </td>
                ))}
                {hasStatus && (
                  <td className="px-4 py-2.5">
                    {r.status && (
                      <StatusPill label={r.status.label} tone={r.status.tone} />
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {widget.footnote && (
        <div className="border-t border-[color:var(--border)] px-4 py-2 text-xs text-[color:var(--muted)]">
          {widget.footnote}
        </div>
      )}
    </div>
  );
}
