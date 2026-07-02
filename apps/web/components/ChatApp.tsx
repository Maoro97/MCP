"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Loader2 } from "lucide-react";
import type { AssistantAnswer, ChatMessage } from "@/lib/types";
import { runMockEngine } from "@/lib/mock";
import { TopBar } from "./TopBar";
import { Sidebar } from "./Sidebar";
import { EmptyState } from "./chat/EmptyState";
import { Composer } from "./chat/Composer";
import { MessageBubble } from "./chat/MessageBubble";
import { ConnectPriority } from "./ConnectPriority";

type Mode = "loading" | "demo" | "connect" | "live";

let idSeq = 0;
const nextId = () => `m${++idSeq}`;

export function ChatApp() {
  const [mode, setMode] = useState<Mode>("loading");
  const [userName, setUserName] = useState<string | undefined>();
  const [canOAuth, setCanOAuth] = useState(false);
  const [authError, setAuthError] = useState<string | undefined>();

  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const [dark, setDark] = useState(false);
  const [rtl, setRtl] = useState(false);
  const [sidebarOpen, setSidebarOpen] = useState(true);

  const scrollRef = useRef<HTMLDivElement>(null);
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);

  // Determine run mode (demo / connect / live) and surface OAuth callback status.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const err = params.get("auth_error");
    if (err) setAuthError(err);
    if (params.has("connected") || err) {
      window.history.replaceState({}, "", window.location.pathname);
    }
    fetch("/api/auth/status")
      .then((r) => r.json())
      .then((d) => {
        setMode(d.mode);
        setUserName(d.name);
        setCanOAuth(Boolean(d.canOAuth));
      })
      .catch(() => setMode("demo"));
  }, []);

  useEffect(() => {
    document.documentElement.classList.toggle("dark", dark);
  }, [dark]);
  useEffect(() => {
    document.documentElement.dir = rtl ? "rtl" : "ltr";
    document.documentElement.lang = rtl ? "he" : "en";
  }, [rtl]);
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages]);
  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  const patch = useCallback((id: string, updates: Partial<ChatMessage>) => {
    setMessages((prev) => prev.map((m) => (m.id === id ? { ...m, ...updates } : m)));
  }, []);

  // Stream an answer's prose word-by-word, then reveal the widget + source.
  const streamAnswer = useCallback(
    (id: string, answer: AssistantAnswer) => {
      const words = answer.text.split(" ");
      let i = 0;
      const step = () => {
        i++;
        patch(id, { text: words.slice(0, i).join(" ") });
        if (i < words.length) {
          timers.current.push(setTimeout(step, 22 + Math.random() * 26));
        } else {
          patch(id, { streaming: false, widget: answer.widget, source: answer.source });
          setBusy(false);
        }
      };
      step();
    },
    [patch]
  );

  // Fetch a live answer from Priority, or fall back to the mock engine in demo mode.
  const resolveAnswer = useCallback(
    async (text: string): Promise<{ toolLabel: string; answer: AssistantAnswer }> => {
      if (mode !== "live") {
        const r = runMockEngine(text);
        return r;
      }
      try {
        const res = await fetch("/api/query", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ text }),
        });
        if (res.status === 401) {
          setMode("connect");
          return {
            toolLabel: "Priority",
            answer: { text: "Your Priority session expired — please reconnect." },
          };
        }
        const data = await res.json();
        return {
          toolLabel: "Querying Priority",
          answer: (data.answer as AssistantAnswer) ?? { text: data.error ?? "No response." },
        };
      } catch {
        return { toolLabel: "Priority", answer: { text: "⚠️ Could not reach the server." } };
      }
    },
    [mode]
  );

  const send = useCallback(
    (text: string) => {
      if (busy || mode === "connect" || mode === "loading") return;
      setBusy(true);

      const userMsg: ChatMessage = { id: nextId(), role: "user", text };
      const aId = nextId();
      setMessages((prev) => [
        ...prev,
        userMsg,
        { id: aId, role: "assistant", text: "", streaming: true, toolLabel: "Querying Priority" },
      ]);

      // Small pause so the tool indicator reads naturally, then resolve + stream.
      timers.current.push(
        setTimeout(async () => {
          const { toolLabel, answer } = await resolveAnswer(text);
          patch(aId, { toolLabel });
          streamAnswer(aId, answer);
        }, mode === "live" ? 150 : 600)
      );
    },
    [busy, mode, patch, resolveAnswer, streamAnswer]
  );

  const newChat = () => {
    timers.current.forEach(clearTimeout);
    timers.current = [];
    setBusy(false);
    setMessages([]);
  };

  const disconnect = async () => {
    await fetch("/api/auth/logout", { method: "POST" }).catch(() => {});
    setMessages([]);
    setMode("connect");
  };

  const modeLabel =
    mode === "live"
      ? userName
        ? `Live · ${userName}`
        : "Live · Priority"
      : mode === "demo"
        ? "Demo data"
        : "Priority";

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
          modeLabel={modeLabel}
          onDisconnect={mode === "live" && userName !== "Static token" ? disconnect : undefined}
        />

        {mode === "loading" ? (
          <div className="flex flex-1 items-center justify-center text-[color:var(--muted)]">
            <Loader2 className="animate-spin" />
          </div>
        ) : mode === "connect" ? (
          <ConnectPriority canOAuth={canOAuth} error={authError} />
        ) : (
          <>
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
          </>
        )}
      </div>
    </div>
  );
}
