"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import {
  Bot,
  Loader2,
  MessageCircleQuestion,
  Minus,
  SendHorizontal,
  Sparkles,
  User,
  X,
} from "lucide-react";
import { toast } from "sonner";
import { cx } from "@/components/ui/utils";

type ChatRole = "user" | "assistant";

type ChatMessage = {
  id: string;
  role: ChatRole;
  content: string;
};

type SupportChatResponse = {
  agent_name: string;
  reply: string;
  source: "openai" | "google" | "fallback";
  model: string | null;
  suggestions: string[];
};

const STARTER_SUGGESTIONS = [
  "How do I run my first Smart audit?",
  "What are the plan options and pricing?",
  "Where can I find my invoices?",
  "How do I enable MFA for my account?",
];

const buildId = () => `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`;

const INITIAL_MESSAGE =
  "Hi, I'm Qiko. Ask me about audits (Guest, Fast, Smart, High Confidence), plans, billing, plans, reports, integrations, projects, API, account settings, and MFA.";
const CHAT_PANEL_ID = "ask-qiko-support-panel";

/**
 * Ask Qiko is switched off, and no page or layout mounts this component, so
 * nothing in the running app renders it today: the launcher below is only
 * reachable from this file's tests. The flag governs what happens when the
 * widget *is* rendered (a disabled "SOON" launcher that cannot be opened).
 *
 * Re-enabling it is not a one-line change any more. Since SIGV2-1148 the
 * backend route it calls, `POST /api/v1/ai/support-chat`, requires an
 * authenticated session, so the widget may only be mounted behind a signed-in
 * surface; on an anonymous page every send would come back 401. A prospect
 * assistant would need its own deliberately public endpoint, built on the
 * guest-audit pattern.
 */
const ASK_QIKO_ENABLED = false;

type Props = {
  /** Overrides {@link ASK_QIKO_ENABLED}. Only used by tests today. */
  enabled?: boolean;
};

export default function ThothChatWidget({ enabled = ASK_QIKO_ENABLED }: Props = {}) {
  const pathname = usePathname();
  const [isOpen, setIsOpen] = useState(false);
  const [isTriggerReady, setIsTriggerReady] = useState(pathname !== "/");
  const [messages, setMessages] = useState<ChatMessage[]>([
    {
      id: buildId(),
      role: "assistant",
      content: INITIAL_MESSAGE,
    },
  ]);
  const [input, setInput] = useState("");
  const [isSending, setIsSending] = useState(false);
  const [dynamicSuggestions, setDynamicSuggestions] = useState<string[]>([]);
  const scrollContainerRef = useRef<HTMLDivElement | null>(null);
  const launcherRef = useRef<HTMLButtonElement | null>(null);

  const suggestions = dynamicSuggestions.length ? dynamicSuggestions : STARTER_SUGGESTIONS;

  const closeChat = () => {
    setIsOpen(false);
    launcherRef.current?.focus();
  };

  useEffect(() => {
    if (!isOpen) return;
    const node = scrollContainerRef.current;
    if (!node) return;
    node.scrollTop = node.scrollHeight;
  }, [messages, isSending, isOpen]);

  useEffect(() => {
    if (!isOpen) return;
    const handleEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setIsOpen(false);
        launcherRef.current?.focus();
      }
    };
    document.addEventListener("keydown", handleEscape);
    return () => document.removeEventListener("keydown", handleEscape);
  }, [isOpen]);

  useEffect(() => {
    if (pathname !== "/") {
      setIsTriggerReady(true);
      return;
    }

    if (isOpen) {
      setIsTriggerReady(true);
      return;
    }

    setIsTriggerReady(false);

    const revealTrigger = () => setIsTriggerReady(true);
    const handleScroll = () => {
      if (window.scrollY > 180) {
        revealTrigger();
      }
    };

    const timeoutId = window.setTimeout(revealTrigger, 9000);

    window.addEventListener("scroll", handleScroll, { passive: true });
    window.addEventListener("pointerdown", revealTrigger);
    window.addEventListener("keydown", revealTrigger);

    return () => {
      window.clearTimeout(timeoutId);
      window.removeEventListener("scroll", handleScroll);
      window.removeEventListener("pointerdown", revealTrigger);
      window.removeEventListener("keydown", revealTrigger);
    };
  }, [isOpen, pathname]);

  const sendMessage = async (rawText: string) => {
    const text = rawText.trim();
    if (!text || isSending) return;

    const nextUserMessage: ChatMessage = {
      id: buildId(),
      role: "user",
      content: text,
    };
    const nextMessages = [...messages, nextUserMessage];
    setMessages(nextMessages);
    setInput("");
    setIsSending(true);
    setIsOpen(true);

    try {
      const response = await fetch("/api/ai/support-chat", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          locale: "en",
          messages: nextMessages.map((message) => ({
            role: message.role,
            content: message.content,
          })),
        }),
      });

      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as { detail?: string } | null;
        throw new Error(payload?.detail || "Support chat is temporarily unavailable.");
      }

      const payload = (await response.json()) as SupportChatResponse;
      if (Array.isArray(payload.suggestions) && payload.suggestions.length > 0) {
        setDynamicSuggestions(payload.suggestions.slice(0, 4));
      }

      setMessages((current) => [
        ...current,
        {
          id: buildId(),
          role: "assistant",
          content: payload.reply,
        },
      ]);
    } catch (error) {
      toast.error(error instanceof Error ? error.message : "Unable to send message.");
      setMessages((current) => current.slice(0, -1));
      setInput(text);
    } finally {
      setIsSending(false);
    }
  };

  const handleSubmit = async (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    await sendMessage(input);
  };

  return (
    <div
      className={cx(
        "fixed bottom-[max(1.25rem,env(safe-area-inset-bottom))] right-[max(1.25rem,env(safe-area-inset-right))] z-widget flex flex-col items-end gap-3 transition-all duration-300",
        !isOpen && !isTriggerReady && "pointer-events-none translate-y-4 opacity-0"
      )}
    >
      {enabled && isOpen ? (
        <section
          id={CHAT_PANEL_ID}
          className="flex h-[min(72dvh,560px)] w-[min(92vw,380px)] flex-col overflow-hidden rounded border border-white/15 bg-[#050A16]/95 shadow-[0_30px_90px_rgba(0,0,0,0.55)]"
        >
          <header className="px-4 py-3 border-b border-white/10 bg-linear-to-r from-thoth-brass/20 via-thoth-logic/15 to-transparent">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-3">
                <div className="w-9 h-9 rounded-xl bg-thoth-brass/20 border border-thoth-brass/35 flex items-center justify-center shadow-[0_0_20px_rgba(6,182,212,0.35)]">
                  <Bot className="w-4.5 h-4.5 text-thoth-brass" />
                </div>
                <div>
                  <h3 className="text-sm font-black text-white">Qiko</h3>
                  <p className="text-[10px] uppercase tracking-[0.14em] text-slate-300">
                    Customer Support
                  </p>
                </div>
              </div>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={closeChat}
                  className="flex min-h-11 min-w-11 items-center justify-center rounded-lg border border-white/15 bg-white/5 text-slate-300 transition-colors hover:bg-white/10 hover:text-white"
                  aria-label="Minimize Ask Qiko chat"
                >
                  <Minus className="w-4 h-4" />
                </button>
                <button
                  type="button"
                  onClick={closeChat}
                  className="flex min-h-11 min-w-11 items-center justify-center rounded-lg border border-white/15 bg-white/5 text-slate-300 transition-colors hover:bg-white/10 hover:text-white"
                  aria-label="Close Ask Qiko chat"
                >
                  <X className="w-4 h-4" />
                </button>
              </div>
            </div>
          </header>

          <div ref={scrollContainerRef} className="flex-1 overflow-y-auto px-3 py-3 space-y-3">
            {messages.map((message) => {
              const isUser = message.role === "user";
              return (
                <div
                  key={message.id}
                  className={`flex ${isUser ? "justify-end" : "justify-start"}`}
                >
                  <div
                    className={`max-w-[88%] rounded px-3 py-2.5 border text-sm leading-relaxed ${
                      isUser
                        ? "bg-thoth-logic/20 border-thoth-logic/35 text-blue-100"
                        : "bg-white/5 border-white/10 text-slate-200"
                    }`}
                  >
                    <div className="mb-1.5 flex items-center gap-1.5 text-[10px] uppercase tracking-[0.12em] text-slate-400">
                      {isUser ? <User className="w-3 h-3" /> : <Sparkles className="w-3 h-3" />}
                      {isUser ? "You" : "Qiko"}
                    </div>
                    <p className="whitespace-pre-wrap">{message.content}</p>
                  </div>
                </div>
              );
            })}

            {isSending ? (
              <div className="flex justify-start">
                <div className="rounded px-3 py-2 border border-white/10 bg-white/5 text-slate-300 text-xs inline-flex items-center gap-2">
                  <Loader2 className="w-3.5 h-3.5 animate-spin text-thoth-brass" />
                  Qiko is thinking...
                </div>
              </div>
            ) : null}
          </div>

          <div className="px-3 pb-3 pt-2 border-t border-white/10 space-y-2.5">
            <div className="flex flex-wrap gap-1.5">
              {suggestions.slice(0, 3).map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  onClick={() => void sendMessage(suggestion)}
                  disabled={isSending}
                  className="rounded-full border border-white/15 bg-white/5 px-2.5 py-1 text-[10px] font-semibold uppercase tracking-[0.08em] text-slate-300 hover:bg-white/10 hover:text-white transition-colors disabled:opacity-50"
                >
                  {suggestion}
                </button>
              ))}
            </div>

            <form onSubmit={handleSubmit} className="flex items-center gap-2">
              <input
                value={input}
                onChange={(event) => setInput(event.target.value)}
                placeholder="Ask Qiko..."
                className="flex-1 rounded-xl border border-white/10 bg-black/45 px-3 py-2.5 text-sm text-white placeholder:text-slate-500 focus:border-thoth-brass/45 focus:outline-hidden"
                disabled={isSending}
                maxLength={1200}
              />
              <button
                type="submit"
                disabled={isSending || !input.trim()}
                className="w-10 h-10 rounded-xl bg-white text-(--background) disabled:opacity-50 hover:scale-[1.03] transition-transform flex items-center justify-center"
                aria-label="Send message to Qiko"
              >
                <SendHorizontal className="w-4 h-4" />
              </button>
            </form>
          </div>
        </section>
      ) : null}

      <button
        ref={launcherRef}
        type="button"
        disabled={!enabled}
        onClick={enabled ? () => setIsOpen((current) => !current) : undefined}
        className={cx(
          "group relative h-12 w-12 overflow-hidden rounded-full border   p-0 shadow-[0_18px_34px_rgba(0,0,0,0.42)] transition-all md:h-auto md:w-auto md:px-3.5 md:py-2.5",
          enabled ? "hover:border-thoth-brass/35 hover:bg-[#0b172b]" : "cursor-not-allowed"
        )}
        aria-label={enabled ? "Open Ask Qiko support chat" : "Ask Qiko is coming soon"}
        title={enabled ? undefined : "Ask Qiko is coming soon"}
        aria-expanded={enabled ? isOpen : undefined}
        aria-controls={enabled ? CHAT_PANEL_ID : undefined}
      >
        <span
          className={cx(
            "absolute inset-0 bg-linear-to-r  via-thoth-logic/10 to-transparent transition-opacity",
            enabled ? "opacity-50 group-hover:opacity-75" : "opacity-30"
          )}
        />
        <span className="relative flex items-center justify-center gap-2">
          <span
            className={cx(
              "flex h-9 w-9 items-center justify-center rounded-full border border-thoth-brass/25 ",
              enabled ? null : "opacity-60"
            )}
          >
            <MessageCircleQuestion className="h-4.5 w-4.5 text-thoth-brass" />
          </span>
          <span
            className={cx(
              "hidden text-[11px] font-semibold uppercase tracking-[0.12em] md:inline md:text-xs",
              enabled ? "text-white" : "text-white/70"
            )}
          >
            Ask Qiko
          </span>
          {!enabled ? (
            <em className="hidden rounded-[5px] border border-white/40 px-1.5 py-px font-(family-name:--mono) text-[10px] not-italic tracking-[0.08em] text-white md:inline">
              SOON
            </em>
          ) : null}
        </span>
      </button>
    </div>
  );
}
