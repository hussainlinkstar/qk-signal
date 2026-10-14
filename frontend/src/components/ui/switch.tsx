"use client";

import React from "react";
import * as SwitchPrimitive from "@radix-ui/react-switch";
import { cx } from "./utils";

const Switch = React.forwardRef<
  React.ComponentRef<typeof SwitchPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof SwitchPrimitive.Root>
>(({ className, ...props }, ref) => (
  <SwitchPrimitive.Root
    ref={ref}
    type="button"
    data-slot="switch"
    className={cx(
      "relative inline-flex h-6 w-[42px] shrink-0 items-center rounded-full border-none transition-colors duration-normal focus-visible:outline-hidden focus-visible:ring-[3px] focus-visible:ring-(--ring)",
      "data-[state=checked]:bg-(--good)",
      "data-[state=unchecked]:bg-(--line)",
      className
    )}
    {...props}
  />
));
Switch.displayName = "Switch";

const SwitchThumb = React.forwardRef<
  React.ComponentRef<typeof SwitchPrimitive.Thumb>,
  React.ComponentPropsWithoutRef<typeof SwitchPrimitive.Thumb>
>(({ className, ...props }, ref) => (
  <SwitchPrimitive.Thumb
    ref={ref}
    data-slot="switch-thumb"
    className={cx(
      "pointer-events-none inline-block h-[18px] w-[18px] rounded-full bg-white shadow-sm ring-0 transition-transform duration-normal",
      "data-[state=checked]:translate-x-[21px] data-[state=unchecked]:translate-x-[3px]",
      className
    )}
    {...props}
  />
));
SwitchThumb.displayName = "SwitchThumb";

export { Switch, SwitchThumb };
