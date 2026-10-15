"use client";

import React from "react";
import { Loader2, MessageSquare, Send, Sparkles } from "lucide-react";
import { toast } from "sonner";

import { useAuth } from "@/components/auth/custom-auth";
import { cx } from "@/components/ui/utils";
import GatedSection from "@/components/results/GatedSection";
import { minimumPlanForCapability, requiredPlanLabelForCapability } from "@/lib/planCapabilities";
import {
  fetchAdvisorChatHistory,
  sendAdvisorChat,
  type AdvisorChatMessage,
} from "@/services/advisorChatService";

// The Advisor is the `has_advisor_recommendations` entitlement, so the plan
// this upsell names comes from that capability (SIGV2-1221).
const ADVISOR_REQUIRED_PLAN = minimumPlanForCapability("has_advisor_recommendations") ?? "";
const ADVISOR_REQUIRED_PLAN_LABEL =
  requiredPlanLabelForCapability("has_advisor_recommendations") ?? "a higher plan";

type AdvisorChatProps = {
  /**
   * The audit being discussed. The chat is grounded strictly on this audit's
   * evidence. When absent, the panel renders nothing (no audit to ground on).
   */
  auditId?: string | number | null;
  /**
   * When `true`, the chat is blurred behind a `GatedSection` upsell. Defaults
   * to `true` (fail-safe LOCKED) so the chat stays gated when the capability is
   * unknown — callers pass `isLocked={!canSeeAdvisor}`.
   */
  isLocked?: boolean;
  /** Forwarded to the gated upsell CTA for guest audits. */
  guestAuditToken?: string;
  className?: string;
};

/** A rendered transcript turn — assistant turns may carry citation ids. */
type ChatTurn = {
  role: AdvisorChatMessage["role"];
  content: string;
  citations?: string[];
};

type AdvisorChatBodyProps = {
  auditId: string | number;
  /** When `true`, the input + send are inert (used inside the blurred preview). */
  disabled?: boolean;
};

const AdvisorChatBody = ({ auditId, disabled = false }: AdvisorChatBodyProps) => {
  const { getToken } = useAuth();
  const [turns, setTurns] = React.useState<ChatTurn[]>([]);
  const [draft, setDraft] = React.useState("");
  const [sending, setSending] = React.useState(false);

  // Hydrate the transcript from the server-persisted history on mount so
  // multi-turn context survives a reload. The blurred (disabled) preview does
  // not hydrate — it never reaches the gated endpoint. Failures are silent: an
  // empty transcript is a safe default and the user can still start fresh.
  React.useEffect(() => {
    if (disabled) {
      return;
    }
    let cancelled = false;
    void (async () => {
      try {
        const token = await getToken();
        const headers: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {};
        const { messages } = await fetchAdvisorChatHistory(auditId, headers);
        if (cancelled || messages.length === 0) {
          return;
        }
        setTurns(
          messages.map((message) => ({
            role: message.role,
            content: message.content,
            citations: message.citations.length > 0 ? message.citations : undefined,
          }))
        );
      } catch {
        // Non-fatal: start with an empty transcript.
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [auditId, disabled, getToken]);

  const handleSend = React.useCallback(
    async (event: React.FormEvent) => {
      event.preventDefault();
      const message = draft.trim();
      if (!message || sending || disabled) {
        return;
      }

      const history: AdvisorChatMessage[] = turns.map((turn) => ({
        role: turn.role,
        content: turn.content,
      }));

      setTurns((current) => [...current, { role: "user", content: message }]);
      setDraft("");
      setSending(true);
      try {
        const token = await getToken();
        const headers: HeadersInit = token ? { Authorization: `Bearer ${token}` } : {};
        const result = await sendAdvisorChat(auditId, { message, history }, headers);
        setTurns((current) => [
          ...current,
          { role: "assistant", content: result.reply, citations: result.citations },
        ]);
      } catch (chatError) {
        toast.error(
          chatError instanceof Error ? chatError.message : "Unable to reach the audit advisor."
        );
      } finally {
        setSending(false);
      }
    },
    [auditId, disabled, draft, getToken, sending, turns]
  );

  return (
    <div className="space-y-6" data-testid="advisor-chat">
      <div className="space-y-1">
        <h3 className="flex items-center gap-3 text-sm font-black uppercase tracking-[0.2em] text-(--t-1)">
          <MessageSquare className="h-4 w-4 text-primary" />
          Ask the advisor
        </h3>
        <p className="pl-7 text-xs font-medium text-(--t-3)">
          Grounded answers about this audit, citing the findings behind them
        </p>
      </div>

      <div
        className="max-h-80 space-y-3 overflow-y-auto rounded border-0 bg-(--line-2) p-4 shadow-inner"
        data-testid="advisor-chat-transcript"
      >
        {turns.length === 0 ? (
          <p className="text-xs leading-relaxed text-(--t-3)">
            Try: &ldquo;Why am I losing the comparison queries?&rdquo;
          </p>
        ) : (
          turns.map((turn, index) => (
            <div
              key={`${turn.role}-${index}`}
              className={cx("flex", turn.role === "user" ? "justify-end" : "justify-start")}
            >
              <div
                className={cx(
                  "max-w-[85%] space-y-2 rounded px-3 py-2 text-xs leading-relaxed",
                  turn.role === "user"
                    ? "border border-primary/20 bg-primary/[0.08] text-(--t-1)"
                    : "border-0 bg-(--line-2) text-(--t-2)"
                )}
                data-testid={`advisor-chat-message-${turn.role}`}
              >
                <p className="whitespace-pre-wrap">{turn.content}</p>
                {turn.citations && turn.citations.length > 0 && (
                  <div className="flex flex-wrap items-center gap-1.5 pt-1">
                    {turn.citations.map((citation) => (
                      <span
                        key={citation}
                        data-testid="advisor-chat-citation"
                        className="inline-flex items-center gap-1 rounded-full border border-emerald-500/30 bg-emerald-500/10 px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider text-emerald-300"
                      >
                        <Sparkles className="h-2.5 w-2.5" />
                        {citation}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            </div>
          ))
        )}
        {sending && (
          <div className="flex justify-start" aria-live="polite">
            <span className="inline-flex items-center gap-2 rounded border-0 bg-(--line-2) px-3 py-2 text-xs text-(--t-2)">
              <Loader2 className="h-3 w-3 animate-spin" />
              Thinking…
            </span>
          </div>
        )}
      </div>

      <form onSubmit={handleSend} className="flex items-center gap-2">
        <input
          type="text"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          disabled={disabled || sending}
          aria-label="Ask the advisor a question about this audit"
          placeholder="Ask a question about this audit…"
          data-testid="advisor-chat-input"
          className="flex-1 rounded border-0 bg-(--line-2) px-3 py-2 text-xs text-(--t-1) placeholder:text-(--t-3) focus:border-primary/40 focus:outline-hidden disabled:cursor-not-allowed disabled:opacity-50"
        />
        <button
          type="submit"
          disabled={disabled || sending || draft.trim().length === 0}
          aria-label="Send question to the advisor"
          data-testid="advisor-chat-send"
          className="inline-flex items-center gap-1.5 rounded border border-primary/30 bg-primary/[0.08] px-3 py-2 text-xs font-bold uppercase tracking-wider text-primary transition-colors hover:bg-primary/15 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {sending ? <Loader2 className="h-3 w-3 animate-spin" /> : <Send className="h-3 w-3" />}
          Send
        </button>
      </form>
    </div>
  );
};

/**
 * Conversational, audit-grounded advisor chat panel.
 *
 * Lets the user ask grounded questions about a single audit and renders the
 * reply plus citation chips (finding ids). Answers come from the backend's
 * audit-grounded advisor (`POST /api/audits/{id}/advisor-chat`), which gates on
 * `has_advisor_recommendations`. When `isLocked` is `true` (i.e.
 * `!canSeeAdvisor`) the panel is blurred behind a `GatedSection` upsell.
 *
 * Renders nothing without an `auditId` (no audit to ground the conversation on).
 */
export default function AdvisorChat({
  auditId,
  isLocked = true,
  guestAuditToken,
  className,
}: AdvisorChatProps) {
  if (auditId === null || auditId === undefined || auditId === "") {
    return null;
  }

  if (isLocked) {
    return (
      <div className={className}>
        <GatedSection
          title="Ask the advisor"
          teaser="Chat with an advisor grounded in your audit: ask why you're losing queries and get answers cited to your findings."
          requiredPlan={ADVISOR_REQUIRED_PLAN}
          requiredPlanLabel={ADVISOR_REQUIRED_PLAN_LABEL}
          guestAuditToken={guestAuditToken}
          blurredPreview={<AdvisorChatBody auditId={auditId} disabled />}
        />
      </div>
    );
  }

  return (
    <div className={className}>
      <AdvisorChatBody auditId={auditId} />
    </div>
  );
}
