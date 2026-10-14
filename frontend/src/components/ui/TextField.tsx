import React, { useId } from "react";
import { Input } from "./input";
import { FieldShell, type FieldVariant, joinDescribedBy } from "./fieldPrimitives";

export type TextFieldProps = React.InputHTMLAttributes<HTMLInputElement> & {
  label?: string;
  error?: string;
  helperText?: string;
  variant?: FieldVariant;
};

const TextField = React.forwardRef<HTMLInputElement, TextFieldProps>(
  (
    {
      className,
      label,
      error,
      helperText,
      id: externalId,
      variant = "default",
      "aria-describedby": ariaDescribedBy,
      "aria-invalid": ariaInvalid,
      ...props
    },
    ref
  ) => {
    const autoId = useId();
    const id = externalId ?? autoId;
    const messageId = error || helperText ? `${id}-message` : undefined;

    return (
      <FieldShell
        id={id}
        label={label}
        error={error}
        helperText={helperText}
        variant={variant}
        messageId={messageId}
      >
        <Input
          ref={ref}
          id={id}
          variant={variant}
          error={Boolean(error)}
          aria-describedby={joinDescribedBy(ariaDescribedBy, messageId)}
          aria-invalid={ariaInvalid ?? (error ? true : undefined)}
          className={className}
          {...props}
        />
      </FieldShell>
    );
  }
);

TextField.displayName = "TextField";

export default TextField;
