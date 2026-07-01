import React from "react";

/*
 * Minimal inline markdown renderer for assistant prose.
 * Supports **bold** and *italic* only — enough for the demo answers without
 * pulling a full markdown dependency. Text is otherwise rendered verbatim.
 */
export function renderInline(text: string): React.ReactNode[] {
  const nodes: React.ReactNode[] = [];
  // Split on **bold** or *italic* while keeping the delimiters.
  const parts = text.split(/(\*\*[^*]+\*\*|\*[^*]+\*)/g);
  parts.forEach((part, i) => {
    if (!part) return;
    if (part.startsWith("**") && part.endsWith("**")) {
      nodes.push(
        <strong key={i} className="font-semibold text-[color:var(--text)]">
          {part.slice(2, -2)}
        </strong>
      );
    } else if (part.startsWith("*") && part.endsWith("*")) {
      nodes.push(
        <em key={i} className="italic">
          {part.slice(1, -1)}
        </em>
      );
    } else {
      nodes.push(<React.Fragment key={i}>{part}</React.Fragment>);
    }
  });
  return nodes;
}
