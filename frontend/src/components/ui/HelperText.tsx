import React from "react";
import { CAPTION_CLASS } from "./typographyTokens";
import { cx } from "./utils";

type HelperTone = "default" | "error" | "info";

type HelperTextProps = React.HTMLAttributes<HTMLParagraphElement> & {
  tone?: HelperTone;
};

const toneClasses: Record<HelperTone, string> = {
  default: "text-(--text-muted)",
  error: "text-danger",
  info: "text-info",
};

const HelperText = React.forwardRef<HTMLParagraphElement, HelperTextProps>(
  ({ tone = "default", className, ...props }, ref) => (
    <p ref={ref} className={cx(CAPTION_CLASS, toneClasses[tone], className)} {...props} />
  )
);

HelperText.displayName = "HelperText";

export default HelperText;
