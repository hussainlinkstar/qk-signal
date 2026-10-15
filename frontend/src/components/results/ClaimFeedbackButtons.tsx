"use client";

import React, { useState } from "react";
import { ThumbsUp, ThumbsDown, CheckCircle2, MessageSquare, X } from "lucide-react";
import { cx } from "@/components/ui/utils";
import type { FeedbackType } from "@/hooks/useClaimFeedback";

type Props = {
  claimKey: string;
  currentFeedback?: FeedbackType | null;
  summary?: { agree: number; disagree: number; fixed: number } | null;
  onSubmit: (type: FeedbackType, text?: string) => void;
  onRemove?: () => void;
  compact?: boolean;
};

const BUTTONS: {
  type: FeedbackType;
  icon: typeof ThumbsUp;
  label: string;
  activeColor: string;
  hoverColor: string;
}[] = [
  {
    type: "agree",
    icon: ThumbsUp,
    label: "Agree",
    activeColor: "text-emerald-400 bg-emerald-500/15 border-emerald-500/30",
    hoverColor: "hover:text-emerald-400 hover:bg-emerald-500/10",
  },
  {
    type: "disagree",
    icon: ThumbsDown,
    label: "Disagree",
    activeColor: "text-rose-400 bg-rose-500/15 border-rose-500/30",
    hoverColor: "hover:text-rose-400 hover:bg-rose-500/10",
  },
  {
    type: "fixed",
    icon: CheckCircle2,
    label: "Fixed",
    activeColor: "text-sky-400 bg-sky-500/15 border-sky-500/30",
    hoverColor: "hover:text-sky-400 hover:bg-sky-500/10",
  },
];

export default function ClaimFeedbackButtons({
  claimKey: _claimKey,
  currentFeedback,
  summary,
  onSubmit,
  onRemove,
  compact = false,
}: Props) {
  const [showTextInput, setShowTextInput] = useState(false);
  const [feedbackText, setFeedbackText] = useState("");
  const [pendingType, setPendingType] = useState<FeedbackType | null>(null);

  const handleClick = (type: FeedbackType) => {
    if (currentFeedback === type) {
      onRemove?.();
      return;
    }
    if (type === "disagree") {
      setPendingType(type);
      setShowTextInput(true);
      return;
    }
    onSubmit(type);
  };

  const handleSubmitWithText = () => {
    if (pendingType) {
      onSubmit(pendingType, feedbackText || undefined);
      setShowTextInput(false);
      setFeedbackText("");
      setPendingType(null);
    }
  };

  const _totalVotes = summary ? summary.agree + summary.disagree + summary.fixed : 0;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        {BUTTONS.map(({ type, icon: Icon, label, activeColor, hoverColor }) => {
          const isActive = currentFeedback === type;
          const count = summary?.[type] || 0;

          return (
            <button
              key={type}
              type="button"
              onClick={() => handleClick(type)}
              aria-label={`${label} this finding`}
              aria-pressed={isActive}
              className={cx(
                "group/fb flex items-center gap-1.5 rounded-lg border px-2.5 py-1.5 text-[10px] font-bold uppercase tracking-widest transition-all",
                isActive
                  ? activeColor
                  : "text-(--t-3) border-(--line) bg-transparent " + hoverColor,
                compact && "px-2 py-1"
              )}
            >
              <Icon className={cx("w-3.5 h-3.5", compact && "w-3 h-3")} />
              {!compact && label}
              {count > 0 && (
                <span
                  className={cx(
                    "ml-0.5 text-[9px] tabular-nums",
                    isActive ? "opacity-90" : "opacity-50"
                  )}
                >
                  {count}
                </span>
              )}
            </button>
          );
        })}

        {currentFeedback === "disagree" && !showTextInput && (
          <button
            type="button"
            onClick={() => {
              setPendingType("disagree");
              setShowTextInput(true);
            }}
            aria-label="Add context to disagreement"
            className="flex items-center gap-1 rounded-[14px] border-0 bg-[#EEF1F6] px-2 py-1.5 text-[10px] text-(--t-3) hover:text-(--t-2) transition-colors"
          >
            <MessageSquare className="w-3 h-3" />
          </button>
        )}
      </div>

      {showTextInput && (
        <div className="flex items-center gap-2 mt-1">
          <input
            type="text"
            value={feedbackText}
            onChange={(e) => setFeedbackText(e.target.value)}
            placeholder="Why do you disagree? (optional)"
            className="flex-1 rounded-[14px] border-0 bg-[#EEF1F6] bg-black/30 px-3 py-1.5 text-xs text-(--t-1) placeholder:text-(--t-3) focus:outline-hidden focus:border-rose-500/40"
            onKeyDown={(e) => {
              if (e.key === "Enter") handleSubmitWithText();
              if (e.key === "Escape") {
                setShowTextInput(false);
                setFeedbackText("");
                setPendingType(null);
              }
            }}
            autoFocus
          />
          <button
            type="button"
            onClick={handleSubmitWithText}
            className="rounded-lg border-0 bg-rose-500/10 px-3 py-1.5 text-[10px] font-bold uppercase tracking-widest text-rose-400 hover:bg-rose-500/20 transition-colors"
          >
            Submit
          </button>
          <button
            type="button"
            onClick={() => {
              setShowTextInput(false);
              setFeedbackText("");
              setPendingType(null);
            }}
            aria-label="Cancel"
            className="p-1 text-(--t-3) hover:text-(--t-2) transition-colors"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      )}
    </div>
  );
}
