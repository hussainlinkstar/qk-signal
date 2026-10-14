import React from "react";
import { cx } from "./utils";
import { Switch, SwitchThumb } from "./switch";

type ToggleSwitchProps = {
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
  label?: string;
  description?: string;
  className?: string;
  "aria-label"?: string;
};

const ToggleSwitch: React.FC<ToggleSwitchProps> = ({
  checked,
  onChange,
  disabled = false,
  label,
  description,
  className,
  "aria-label": ariaLabel,
}) => (
  <label
    className={cx(
      "group inline-flex items-center gap-3 select-none",
      disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer",
      className
    )}
  >
    <Switch
      checked={checked}
      onCheckedChange={onChange}
      disabled={disabled}
      aria-label={ariaLabel ?? label}
    >
      <SwitchThumb />
    </Switch>
    {(label || description) && (
      <span className="flex flex-col">
        {label && <span className="text-sm font-medium text-(--foreground)">{label}</span>}
        {description && <span className="mt-0.5 text-xs text-(--text-muted)">{description}</span>}
      </span>
    )}
  </label>
);

export default ToggleSwitch;
