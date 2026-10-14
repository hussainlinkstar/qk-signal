import React, { type ReactNode } from "react";
import { AlertTriangle, CheckCircle2, Info, XCircle } from "lucide-react";

import { cn } from "@/components/ui/utils";
import type { SignalAlertTone } from "@/components/signal/SignalAlert";

type Props = {
  children: ReactNode;
  tone?: SignalAlertTone;
  icon?: ReactNode;
  className?: string;
  role?: "alert" | "status" | "note";
  id?: string;
};

/* Same four glyphs as the alert tier, so one shape means one thing wherever it
   appears. */
const icons = {
  info: Info,
  warning: AlertTriangle,
  danger: XCircle,
  success: CheckCircle2,
};

const toneText: Record<SignalAlertTone, string> = {
  info: "text-(--blue)",
  warning: "text-(--warn)",
  danger: "text-(--bad)",
  success: "text-(--good)",
};

const defaultRoles: Record<SignalAlertTone, "alert" | "status"> = {
  info: "status",
  success: "status",
  warning: "alert",
  danger: "alert",
};

/**
 * The approved inline tier (mockup: Signal Components.html `#sec-notify`,
 * `QNotify.inline`; signal.css `.note-inline`): feedback attached to the
 * control that caused it. Anatomy is the design's, exactly - 15px glyph, 8px
 * gap, 12.5px/500 text in the tone's own colour, 7px above.
 *
 * Use it for one field or one control. A failure that belongs to a whole
 * action, or that the customer has to be able to find again, is the alert tier
 * (`SignalAlert`), not this.
 *
 * Contrast on the surfaces this sits on, with the `[data-signal-theme]` status
 * tokens: `--bad` #b4232a 6.53:1 on `--panel` #ffffff and 6.09:1 on `--paper`
 * #f6f7f9, `--warn` #8a5a00 5.93:1 on `--panel`, `--good` #116149 7.42:1,
 * `--blue` #2563eb 5.17:1. All above WCAG AA 4.5.
 */
export default function SignalInlineNote({
  children,
  tone = "info",
  icon,
  className,
  role,
  id,
}: Props) {
  const Icon = icons[tone];
  return (
    <p
      id={id}
      role={role ?? defaultRoles[tone]}
      data-signal-inline-note={tone}
      className={cn(
        "m-0 mt-[7px] flex items-center gap-2 font-(family-name:--body-font) text-[12.5px] font-medium leading-[1.5]",
        toneText[tone],
        className
      )}
    >
      <span aria-hidden="true" className="flex-none [&_svg]:h-[15px] [&_svg]:w-[15px]">
        {icon ?? <Icon strokeWidth={2} />}
      </span>
      <span className="min-w-0">{children}</span>
    </p>
  );
}
