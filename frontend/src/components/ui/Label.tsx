"use client";

import React from "react";
import * as LabelPrimitive from "@radix-ui/react-label";
import { LABEL_CLASS } from "./typographyTokens";
import { cn } from "./utils";

const Label = React.forwardRef<
  React.ComponentRef<typeof LabelPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof LabelPrimitive.Root>
>(({ className, ...props }, ref) => (
  <LabelPrimitive.Root ref={ref} className={cn("block", LABEL_CLASS, className)} {...props} />
));

Label.displayName = "Label";

export { Label };

export default Label;
