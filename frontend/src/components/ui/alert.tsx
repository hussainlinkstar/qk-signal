import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";

import { cn } from "@/components/ui/utils";

// Canonical shadcn Alert anatomy, driven by the Signal tokens so it renders
// correctly on both themes. The grid icon column collapses to zero when the
// alert has no direct <svg> child.
const alertVariants = cva(
  "relative grid w-full grid-cols-[0_1fr] items-start gap-x-3 gap-y-0.5 rounded-(--r-md) border px-4 py-3 font-(family-name:--body-font) text-[13px] leading-[1.5] text-(--t-1) has-[>svg]:grid-cols-[calc(var(--spacing)*4)_1fr] [&>svg]:size-4 [&>svg]:translate-y-0.5 [&>svg]:text-current",
  {
    variants: {
      variant: {
        default: "border-(--line) bg-(--panel)",
        brand:
          "border-(--line) bg-(--panel) [&>svg]:text-(--brand) [&_[data-slot=alert-title]]:text-(--brand)",
        // SIGV2-1222: the three status variants no longer name their own fill
        // or border. Both come from the `[data-signal-alert="<tone>"]` rules
        // in globals.css, the same rules SignalAlert uses, so the animated
        // gradient edge is one implementation rather than two that drift.
        warning: "[&>svg]:text-(--warn)",
        destructive: "[&>svg]:text-(--bad)",
        success: "[&>svg]:text-(--good)",
      },
    },
    defaultVariants: { variant: "default" },
  }
);

/* Which variants are a status, and therefore take the animated gradient edge.
   `default` and `brand` are neutral panels - a promotional or structural
   notice is not a status, and giving it a moving edge would spend the
   customer's attention on something that is not telling them anything
   happened. */
const EDGE_TONES = {
  warning: "warning",
  destructive: "danger",
  success: "success",
} as const;

function Alert({
  className,
  variant,
  ...props
}: React.ComponentProps<"div"> & VariantProps<typeof alertVariants>) {
  const tone = variant ? EDGE_TONES[variant as keyof typeof EDGE_TONES] : undefined;
  return (
    <div
      data-slot="alert"
      role="alert"
      data-signal-alert={tone}
      className={cn(alertVariants({ variant }), className)}
      {...props}
    />
  );
}

function AlertTitle({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-title"
      className={cn("col-start-2 line-clamp-1 min-h-4 font-medium tracking-tight", className)}
      {...props}
    />
  );
}

function AlertDescription({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="alert-description"
      className={cn(
        "col-start-2 grid justify-items-start gap-1 text-sm text-(--t-2) [&_p]:leading-relaxed",
        className
      )}
      {...props}
    />
  );
}

export { Alert, AlertTitle, AlertDescription };
