import React from "react";
import { cn } from "./utils";
import { fieldControlClasses, type FieldVariant } from "./fieldPrimitives";

export type InputProps = React.InputHTMLAttributes<HTMLInputElement> & {
  variant?: FieldVariant;
  error?: boolean;
};

const Input = React.forwardRef<HTMLInputElement, InputProps>(
  ({ className, variant = "default", error = false, ...props }, ref) => (
    <input
      ref={ref}
      data-slot="input"
      className={cn(fieldControlClasses({ variant, error }), className)}
      {...props}
    />
  )
);

Input.displayName = "Input";

export { Input };
