"use client";

import { useEffect, useRef, useState } from "react";

// ============================================================
// TEMPORARY / MOCK DATA — REMOVE WHEN BACKEND IS WIRED UP
// Search for "STATIC_GREETING" to locate and delete later.
// ============================================================
const STATIC_GREETING = {
  id: "static-greeting-remove-me",
  role: "assistant" as const,
  content:
    "Good morning, Doctor. I'm LUNA, your clinical decision support assistant. You can ask me about a specific patient's history, run population-level queries across the database, or request a diagnostic report for a patient. How can I help you today?",
};
// ============================================================

type Message = {
  id: string;
  role: "assistant" | "user";
  content: string;
};

export default function ChatInterface() {
  const [messages, setMessages] = useState<Message[]>([STATIC_GREETING]);
  const [input, setInput] = useState("");
  const scrollRef = useRef<HTMLDivElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  // Auto-scroll to bottom on new message
  useEffect(() => {
    scrollRef.current?.scrollTo({
      top: scrollRef.current.scrollHeight,
      behavior: "smooth",
    });
  }, [messages]);

  // Auto-resize textarea
  useEffect(() => {
    const ta = textareaRef.current;
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = `${Math.min(ta.scrollHeight, 200)}px`;
  }, [input]);

  const handleSend = () => {
    const trimmed = input.trim();
    if (!trimmed) return;

    const userMsg: Message = {
      id: crypto.randomUUID(),
      role: "user",
      content: trimmed,
    };
    setMessages((prev) => [...prev, userMsg]);
    setInput("");

    // TODO: replace with real API call to backend (RAG / LLM endpoint).
    // For now, stub an assistant echo so the UI feels alive.
    setTimeout(() => {
      setMessages((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          role: "assistant",
          content:
            "(stubbed response — backend not yet connected) I received your query. Once the RAG pipeline is wired up, I'll respond with citation-backed information.",
        },
      ]);
    }, 600);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSend();
    }
  };

  return (
    <div className="flex h-full flex-col">
      {/* Messages area */}
      <div
        ref={scrollRef}
        className="flex-1 overflow-y-auto px-4 py-6"
      >
        <div className="mx-auto flex max-w-3xl flex-col gap-6">
          {messages.map((m) => (
            <MessageBubble key={m.id} message={m} />
          ))}
        </div>
      </div>

      {/* Composer */}
      <div className="shrink-0 border-t border-steel/40 bg-midnight/40 px-4 py-4 backdrop-blur-xl">
        <div className="mx-auto max-w-3xl">
          <div className="flex items-end gap-2 rounded-xl border border-steel bg-deepnavy/80 p-2 transition focus-within:border-cyan/60 focus-within:shadow-glow-cyan">
            <textarea
              ref={textareaRef}
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={handleKeyDown}
              placeholder="Ask LUNA about a patient, request a diagnostic report…"
              rows={1}
              className="flex-1 resize-none bg-transparent px-3 py-2 font-sans text-sm text-ice placeholder-mist/70 outline-none"
            />
            <button
              onClick={handleSend}
              disabled={!input.trim()}
              aria-label="Send message"
              className="flex h-9 w-9 shrink-0 items-center justify-center rounded-lg border border-cyan/50 bg-cyan/10 text-cyan transition hover:bg-cyan/20 hover:shadow-glow-cyan disabled:cursor-not-allowed disabled:border-steel disabled:bg-transparent disabled:text-mist/40 disabled:shadow-none"
            >
              <svg
                className="h-4 w-4"
                fill="none"
                stroke="currentColor"
                viewBox="0 0 24 24"
              >
                <path
                  strokeLinecap="round"
                  strokeLinejoin="round"
                  strokeWidth={2}
                  d="M5 12h14m0 0l-6-6m6 6l-6 6"
                />
              </svg>
            </button>
          </div>

          <p className="mt-2 px-2 text-center font-display text-[9px] tracking-[0.2em] text-mist/70">
            LUNA MAY PRODUCE INACCURATE INFORMATION · ALWAYS VERIFY WITH CLINICAL JUDGMENT
          </p>
        </div>
      </div>
    </div>
  );
}

function MessageBubble({ message }: { message: Message }) {
  const isUser = message.role === "user";

  return (
    <div className={`flex gap-3 ${isUser ? "flex-row-reverse" : "flex-row"}`}>
      {/* Avatar */}
      <div
        className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full font-display text-[10px] font-bold ${
          isUser
            ? "bg-slate text-ice"
            : "bg-cyan/20 text-cyan"
        }`}
      >
        {isUser ? "DR" : "L"}
      </div>

      {/* Bubble */}
      <div
        className={`max-w-[80%] rounded-2xl px-4 py-3 font-sans text-sm leading-relaxed ${
          isUser
            ? "bg-slate/70 text-ice"
            : "border border-steel/50 bg-midnight/60 text-ice"
        }`}
      >
        {message.content}
      </div>
    </div>
  );
}
