import { cx } from "@/components/ui/utils";

export type SignalSectionHeaderProps = {
  title: string;
  /** Right-aligned note (`.mini`, e.g. "ranked by points per effort"). */
  note?: string;
  /** Google Analytics source label with the GA conic-gradient chip. */
  gaSource?: string;
  /** Optional right-aligned action (e.g. an "Add keyword" button). */
  action?: React.ReactNode;
  /** The detail pages' approved <style> blocks override .sec h2 to 14px/700. */
  titleClassName?: string;
  /** Detail pages override `.mini` to mono 11px/.05em; default is 12.5px body. */
  monoNote?: boolean;
  className?: string;
};

/**
 * Matches signal-MVP's `.sec`: a plain inline row — display `<h2>`, the 1px
 * vertical `.ln` divider, the `.mini` note, then a spacer pushing any action
 * right. The divider is a `w-px h-4` chip, NOT a flex-1 hairline, and `.mini`
 * is 12.5px body text, not mono. (signal.css `.sec`, `.ln`, `.mini`)
 */
export default function SignalSectionHeader({
  title,
  note,
  gaSource,
  action,
  titleClassName,
  monoNote = false,
  className,
}: SignalSectionHeaderProps) {
  return (
    <div className={cx("mb-3.5 flex min-w-0 flex-wrap items-center gap-3", className)}>
      <h2
        className={cx(
          "min-w-0 font-(family-name:--disp) text-[17px] font-extrabold tracking-[-0.01em] text-(--t-1)",
          titleClassName
        )}
      >
        {title}
      </h2>
      <span className="h-4 w-px flex-none bg-(--line-2)" />
      {gaSource && (
        <span className="inline-flex min-w-0 items-center gap-1.5 text-[12.5px] text-(--t-3)">
          <span className="h-[13px] w-[13px] rounded-[3px] bg-[conic-gradient(#F9AB00_0_25%,#E37400_0_50%,#34A853_0_75%,#4285F4_0)]" />
          {gaSource}
        </span>
      )}
      {note && (
        <span
          className={cx(
            "min-w-0 text-(--t-3)",
            monoNote ? "font-mono text-[11px] tracking-[0.05em]" : "text-[12.5px]"
          )}
        >
          {note}
        </span>
      )}
      <div className="flex-1" />
      {action}
    </div>
  );
}
