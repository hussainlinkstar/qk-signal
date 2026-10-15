"use client";

import React from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { cx } from "./utils";
import { RADIUS_CONTROL_CLASS, RADIUS_OVERLAY_CLASS } from "./radiusTokens";

const TooltipProvider = TooltipPrimitive.Provider;
const TooltipRoot = TooltipPrimitive.Root;
const TooltipTrigger = TooltipPrimitive.Trigger;

const TooltipContent = React.forwardRef<
  React.ComponentRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 12, ...props }, ref) => (
  <TooltipPrimitive.Portal>
    <TooltipPrimitive.Content
      ref={ref}
      data-slot="tooltip-content"
      sideOffset={sideOffset}
      className={cx(
        "pointer-events-none z-100 w-max max-w-64 border-0 bg-(--chart-tooltip-bg) px-3 py-2 text-xs text-(--foreground) shadow-lg animate-in fade-in-0 zoom-in-95",
        RADIUS_OVERLAY_CLASS,
        className
      )}
      {...props}
    />
  </TooltipPrimitive.Portal>
));
TooltipContent.displayName = "TooltipContent";

export { TooltipProvider, TooltipRoot, TooltipTrigger, TooltipContent };

type TooltipProps = {
  content: React.ReactNode;
  children: React.ReactNode;
  className?: string;
  panelClassName?: string;
  triggerClassName?: string;
  triggerAriaLabel?: string;
  side?: "top" | "bottom" | "left" | "right";
};

export default function Tooltip({
  content,
  children,
  className = "",
  panelClassName = "",
  triggerClassName = "",
  triggerAriaLabel,
  side = "top",
}: TooltipProps) {
  return (
    <TooltipProvider delayDuration={0}>
      <TooltipRoot>
        <span className={`group/tooltip relative inline-flex ${className}`.trim()}>
          <TooltipTrigger asChild>
            <span
              tabIndex={0}
              aria-label={triggerAriaLabel}
              className={cx(
                "peer inline-flex focus-visible:outline-hidden focus-visible:ring-2 focus-visible:ring-ring/70",
                RADIUS_CONTROL_CLASS,
                triggerClassName
              )}
            >
              {children}
            </span>
          </TooltipTrigger>
        </span>
        <TooltipContent side={side} className={panelClassName}>
          {content}
        </TooltipContent>
      </TooltipRoot>
    </TooltipProvider>
  );
}
