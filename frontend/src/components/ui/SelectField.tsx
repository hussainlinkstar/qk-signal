import React, { useId } from "react";
import { NativeSelect } from "./native-select";
import { FieldShell, type FieldVariant, joinDescribedBy } from "./fieldPrimitives";

export type SelectFieldProps = React.SelectHTMLAttributes<HTMLSelectElement> & {
  label?: string;
  error?: string;
  helperText?: string;
  variant?: FieldVariant;
};

const SelectField = React.forwardRef<HTMLSelectElement, SelectFieldProps>(
  (
    {
      className,
      label,
      error,
      helperText,
      id: externalId,
      variant = "default",
      children,
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
        <NativeSelect
          ref={ref}
          id={id}
          variant={variant}
          error={Boolean(error)}
          aria-describedby={joinDescribedBy(ariaDescribedBy, messageId)}
          aria-invalid={ariaInvalid ?? (error ? true : undefined)}
          className={className}
          {...props}
        >
          {children}
        </NativeSelect>
      </FieldShell>
    );
  }
);

SelectField.displayName = "SelectField";

export default SelectField;
