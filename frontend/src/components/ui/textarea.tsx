import React from "react";
import { cn } from "./utils";
import { fieldControlClasses, type FieldVariant } from "./fieldPrimitives";

export type TextareaProps = React.TextareaHTMLAttributes<HTMLTextAreaElement> & {
  variant?: FieldVariant;
  error?: boolean;
};

const Textarea = React.forwardRef<HTMLTextAreaElement, TextareaProps>(
  ({ className, variant = "default", error = false, ...props }, ref) => (
    <textarea
      ref={ref}
      data-slot="textarea"
      className={cn(
        fieldControlClasses({ variant, error, multiline: true }),
        "resize-y",
        className
      )}
      {...props}
    />
  )
);

Textarea.displayName = "Textarea";

export { Textarea };
