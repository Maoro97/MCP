import { Sparkles, User } from "lucide-react";
import type { ChatMessage } from "@/lib/types";
import { renderInline } from "@/lib/markdown";
import { WidgetRenderer } from "@/components/widgets/WidgetRenderer";
import { SourceChip } from "@/components/widgets/SourceChip";
import { ToolIndicator } from "./ToolIndicator";

export function MessageBubble({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";

  if (isUser) {
    return (
      <div className="fade-up flex justify-end gap-3">
        <div className="max-w-[80%] rounded-2xl rounded-tr-sm bg-[color:var(--accent)] px-4 py-2.5 text-[color:var(--accent-contrast)]">
          <p className="whitespace-pre-wrap text-sm leading-relaxed">
            {message.text}
          </p>
        </div>
        <div className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[color:var(--surface-2)] text-[color:var(--muted)]">
          <User size={16} />
        </div>
      </div>
    );
  }

  return (
    <div className="fade-up flex gap-3">
      <div className="mt-0.5 grid h-8 w-8 shrink-0 place-items-center rounded-full bg-[color:var(--accent-soft)] text-[color:var(--accent)]">
        <Sparkles size={16} />
      </div>
      <div className="min-w-0 flex-1 space-y-3">
        {message.toolLabel && (message.streaming || !message.text) && (
          <ToolIndicator label={message.toolLabel + "…"} />
        )}

        {message.text && (
          <div
            className={`text-sm leading-relaxed text-[color:var(--text)] ${
              message.streaming ? "caret" : ""
            }`}
          >
            {renderInline(message.text)}
          </div>
        )}

        {message.widget && !message.streaming && (
          <div className="fade-up">
            <WidgetRenderer widget={message.widget} />
          </div>
        )}

        {message.source && !message.streaming && (
          <SourceChip source={message.source} />
        )}
      </div>
    </div>
  );
}
