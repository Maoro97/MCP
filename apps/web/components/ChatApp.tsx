"use client";

import { useEffect, useRef, useState } from "react";
import type { ChatMessage } from "@/lib/types";
import { runMockEngine } from "@/lib/mock";
import { TopBar } from "./TopBar";
import { Sidebar } from "./Sidebar";
import { EmptyState } from "./chat/EmptyState";
import { Composer } from "./chat/Composer";
import { MessageBubble } from "./chat/MessageBubble";

let idSeq = 0;
const nextId = () => `m${++idSeq}`;

export function ChatApp() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [dark, setDark] = useState(false);
  const [rtl, setRtl] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const scrollRef = useRef<HTMLDivElement>(null);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  // Apply theme + direction to the document.
  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);
  useEffect(() => {
    document.documentElement.dir = rtl ? "rtl" : "ltr";
    document.documentElement.lang = rtl ? "he" : "en";
  }, [rtl]);

  // Auto-scroll to the latest message.
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  // Clean up any pending timers on unmount.
  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  const patch = (id: string, updates: Partial<ChatMessage>) =>
    setMessages((prev) =>
      prev.map((m) => (m.id === id ? { ...m, ...updates } : m))
    );

  const send = (text: string) => {
    if (busy) return;
    setBusy(true);

    const userMsg: ChatMessage = { id: nextId(), role: "user", text };
    const aId = nextId();
    const { toolLabel, answer } = runMockEngine(text);

    const assistantMsg: ChatMessage = {
      id: aId,
      role: "assistant",
      text: "",
      streaming: true,
      toolLabel,
    };
    setMessages((prev) => [...prev, userMsg, assistantMsg]);

    // 1) Simulate the tool call, then 2) stream the prose word-by-word.
    const words = answer.text.split(" ");
    timers.current.push(
      setTimeout(() => {
        let i = 0;
        const step = () => {
          i++;
          patch(aId, { text: words.slice(0, i).join(" ") });
          if (i < words.length) {
            timers.current.push(setTimeout(step, 24 + Math.random() * 30));
          } else {
            // Reveal widget + source, end streaming.
            patch(aId, {
              streaming: false,
              widget: answer.widget,
              source: answer.source,
            });
            setBusy(false);
          }
        };
        step();
      }, 750)
    );
  };

  const newChat = () => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
    setBusy(false);
    setMessages([]);
  };

  return (
    <div className="flex h-dvh overflow-hidden bg-[color:var(--bg)] text-[color:var(--text)]">
      <Sidebar open={sidebarOpen} onNewChat={newChat} onPick={send} />

      <div className="flex min-w-0 flex-1 flex-col">
        <TopBar
          dark={dark}
          onToggleDark={() => setDark((v) => !v)}
          rtl={rtl}
          onToggleRtl={() => setRtl((v) => !v)}
          onToggleSidebar={() => setSidebarOpen((v) => !v)}
        />

        <div ref={scrollRef} className="flex-1 overflow-y-auto">
          {messages.length === 0 ? (
            <EmptyState onPick={send} />
          ) : (
            <div className="mx-auto max-w-3xl space-y-6 px-4 py-6">
              {messages.map((m) => (
                <MessageBubble key={m.id} message={m} />
              ))}
            </div>
          )}
        </div>

        <Composer onSend={send} disabled={busy} rtl={rtl} />
      </div>
    </div>
  );
}
