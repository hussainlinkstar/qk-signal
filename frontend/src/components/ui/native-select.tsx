import React from "react";
import { cn } from "./utils";
import { fieldControlClasses, type FieldVariant } from "./fieldPrimitives";

export type NativeSelectProps = React.SelectHTMLAttributes<HTMLSelectElement> & {
  variant?: FieldVariant;
  error?: boolean;
};

const NativeSelect = React.forwardRef<HTMLSelectElement, NativeSelectProps>(
  ({ className, variant = "default", error = false, children, ...props }, ref) => (
    <select
      ref={ref}
      data-slot="native-select"
      className={cn(
        fieldControlClasses({ variant, error }),
        "select-chevron pr-10 [&_option]:bg-(--surface) [&_option]:text-(--foreground) [&_optgroup]:bg-(--surface) [&_optgroup]:text-(--foreground)",
        className
      )}
      {...props}
    >
      {children}
    </select>
  )
);

NativeSelect.displayName = "NativeSelect";

const NativeSelectOption = (props: React.OptionHTMLAttributes<HTMLOptionElement>) => (
  <option data-slot="native-select-option" {...props} />
);

const NativeSelectOptGroup = (props: React.OptgroupHTMLAttributes<HTMLOptGroupElement>) => (
  <optgroup data-slot="native-select-optgroup" {...props} />
);

export { NativeSelect, NativeSelectOption, NativeSelectOptGroup };
