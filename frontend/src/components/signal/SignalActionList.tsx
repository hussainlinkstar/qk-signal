import { cx } from "@/components/ui/utils";

export type SignalAction = {
  id: string;
  /** Point uplift when known. When omitted a priority rank is shown instead. */
  points?: number;
  title: string;
  description: string;
  category?: string;
  effort?: "Low" | "Medium" | "High";
  status?: string;
};

export type SignalActionListProps = {
  actions: SignalAction[];
  /** Accent for the points + category chip. */
  accent?: "blue" | "gradient";
  emptyLabel?: string;
  /** When provided, each fix shows an action button (e.g. "Fix with AI"). */
  onAction?: (action: SignalAction) => void;
  actionLabel?: string;
};

/**
 * Matches signal-MVP's `.act` fix cards: points badge (`.pts`) + body
 * (`.ab`: h3/p/meta chips). Ranked by points-per-effort. (signal.css 65-78)
 */
export default function SignalActionList({
  actions,
  accent = "blue",
  emptyLabel = "No recommended actions right now — you're at target.",
  onAction,
  actionLabel = "Fix with AI",
}: SignalActionListProps) {
  if (actions.length === 0) {
    return (
      <div className="rounded-[16px] border border-(--line) bg-(--panel) p-8 text-center text-[13px] text-(--t-3)">
        {emptyLabel}
      </div>
    );
  }
  return (
    <div className="rounded-[16px] border border-(--line) bg-(--panel)">
      {actions.map((a, i) => (
        <div
          key={a.id}
          className={cx("flex gap-4 p-[18px_20px]", i > 0 && "border-t border-(--line)")}
        >
          <div className="flex-none text-center">
            <b
              className={cx(
                "block font-(family-name:--disp) text-[22px] font-black leading-none",
                accent === "gradient" ? "text-(--purple)" : "text-(--blue)"
              )}
            >
              {a.points !== undefined ? `+${a.points}` : `#${i + 1}`}
            </b>
            <small className="font-(family-name:--mono) text-[9px] tracking-[0.08em] text-(--t-3)">
              {a.points !== undefined ? "PTS" : "PRIORITY"}
            </small>
          </div>
          <div className="min-w-0 flex-1">
            <h3 className="text-[14.5px] font-bold text-(--t-1)">{a.title}</h3>
            <p className="mt-1 text-[13px] leading-normal text-(--t-2)">{a.description}</p>
            <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
              {a.category && (
                <span
                  className={cx(
                    "rounded-full px-2.5 py-1 font-(family-name:--mono) text-[10.5px] tracking-[0.04em]",
                    accent === "gradient"
                      ? "bg-(--purple-s) text-(--purple)"
                      : "bg-(--blue-s) text-(--blue)"
                  )}
                >
                  {a.category}
                </span>
              )}
              {a.effort && (
                <span className="rounded-full border border-(--line) px-2.5 py-1 font-(family-name:--mono) text-[10.5px] tracking-[0.04em] text-(--t-3)">
                  Effort: {a.effort}
                </span>
              )}
              {a.status && (
                <span className="rounded-full bg-(--good-s) px-2.5 py-1 font-(family-name:--mono) text-[10.5px] tracking-[0.04em] text-(--good)">
                  {a.status}
                </span>
              )}
            </div>
          </div>
          {onAction && (
            <button
              type="button"
              onClick={() => onAction(a)}
              className={cx(
                "flex-none self-start rounded-full px-3 py-1.5 font-(family-name:--mono) text-[11px] font-semibold tracking-[0.04em] text-white transition-opacity hover:opacity-90",
                accent === "gradient" ? "bg-(image:--grad)" : "bg-(--blue)"
              )}
            >
              {actionLabel}
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
