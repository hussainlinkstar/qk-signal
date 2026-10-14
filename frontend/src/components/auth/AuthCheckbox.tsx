import React from "react";
import { Check } from "lucide-react";

import HelperText from "@/components/ui/HelperText";
import { cx } from "@/components/ui/utils";

type AuthCheckboxProps = Omit<React.InputHTMLAttributes<HTMLInputElement>, "type"> & {
  label: React.ReactNode;
  description?: React.ReactNode;
  error?: string;
};

const AuthCheckbox = React.forwardRef<HTMLInputElement, AuthCheckboxProps>(
  ({ className, label, description: _description, error, id, ...props }, ref) => (
    <div className={cx("space-y-2", className)}>
      <label
        className={cx(
          "group relative flex min-h-6 cursor-pointer select-none items-start gap-2.5",
          className
        )}
      >
        <span className="relative mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center">
          <input {...props} ref={ref} id={id} type="checkbox" className="peer sr-only" />
          <span className="h-4 w-4 rounded-[4px] border border-(--t-3) bg-(--panel) transition-colors duration-150 group-hover:border-(--brand) peer-checked:border-(--brand) peer-checked:bg-(--brand) peer-focus-visible:ring-[3px] peer-focus-visible:ring-(--ring)" />
          <Check
            aria-hidden="true"
            className="pointer-events-none absolute h-3 w-3 text-(--panel) opacity-0 peer-checked:opacity-100"
            strokeWidth={3}
          />
        </span>
        {label ? <span className="text-[13px] leading-[1.5] text-(--t-2)">{label}</span> : null}
      </label>
      {error ? (
        <HelperText tone="error" className="pl-8">
          {error}
        </HelperText>
      ) : null}
    </div>
  )
);

AuthCheckbox.displayName = "AuthCheckbox";

export default AuthCheckbox;
