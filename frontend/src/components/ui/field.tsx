import React from "react";
import HelperText from "./HelperText";
import Label from "./Label";
import { MICRO_LABEL_CLASS } from "./typographyTokens";
import { cx } from "./utils";

const Field = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} data-slot="field" className={cx("w-full space-y-2", className)} {...props} />
  )
);
Field.displayName = "Field";

const FieldLabel = React.forwardRef<HTMLLabelElement, React.LabelHTMLAttributes<HTMLLabelElement>>(
  ({ className, ...props }, ref) => (
    <Label
      ref={ref}
      data-slot="field-label"
      className={cx(MICRO_LABEL_CLASS, "leading-[normal]", className)}
      {...props}
    />
  )
);
FieldLabel.displayName = "FieldLabel";

const FieldDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <HelperText
    ref={ref}
    data-slot="field-description"
    className={cx("pl-0.5", className)}
    {...props}
  />
));
FieldDescription.displayName = "FieldDescription";

const FieldError = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <HelperText
    ref={ref}
    data-slot="field-error"
    tone="error"
    className={cx("pl-0.5", className)}
    {...props}
  />
));
FieldError.displayName = "FieldError";

export { Field, FieldLabel, FieldDescription, FieldError };
