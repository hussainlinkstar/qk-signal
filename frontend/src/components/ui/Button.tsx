import React from "react";
import { Loader2 } from "lucide-react";
import { cva } from "class-variance-authority";
import { cn, cx } from "./utils";
import { RADIUS_CONTROL_CLASS } from "./radiusTokens";

export type OfficialButtonVariant = "primary" | "inverse" | "ghost" | "danger" | "accent";
export type ButtonVariant = OfficialButtonVariant | "outline" | "auth" | "cta";
export type ButtonSize = "sm" | "md" | "lg";
export const BUTTON_ICON_CLASS = "button-icon";

type ButtonStyleOptions = {
  variant?: ButtonVariant;
  size?: ButtonSize;
  className?: string;
};

const legacyVariantMap: Record<ButtonVariant, OfficialButtonVariant> = {
  primary: "primary",
  inverse: "inverse",
  outline: "ghost",
  ghost: "ghost",
  danger: "danger",
  auth: "primary",
  cta: "accent",
  accent: "accent",
};

/**
 * Every variant is token-driven, because this button renders on both themes: the
 * dark marketing/auth pages and the light signal dashboard, where
 * `[data-signal-theme]` re-points these same tokens.
 *
 * The previous values were dark-theme literals, which made `ghost` (and
 * `outline`, which aliases to it) a 3% white fill inside a 5% white border, i.e.
 * an invisible button on the light dashboard, and `inverse` turned white on
 * hover while its label stayed `--background`, so the label vanished.
 *
 * `bg-(--surface-subtle)` for ghost and `bg-primary` for primary are the
 * contract asserted by ui/__tests__/foundation-primitives.test.tsx, which the
 * implementation had drifted away from.
 */
const buttonVariants = cva(
  cx(
    "signal-button inline-flex min-w-0 cursor-pointer items-center justify-center gap-2 whitespace-nowrap border font-(family-name:--body-font) font-semibold leading-[normal] transition-colors duration-150 focus-visible:outline-hidden focus-visible:ring-[3px] focus-visible:ring-(--ring) disabled:cursor-not-allowed disabled:opacity-45 motion-reduce:transition-none",
    RADIUS_CONTROL_CLASS
  ),
  {
    variants: {
      variant: {
        primary:
          "signal-button-primary border-transparent bg-primary text-(--primary-foreground) hover:bg-(--primary-hover)",
        inverse: "border-(--foreground) bg-(--foreground) text-(--background) hover:opacity-90",
        ghost:
          "signal-button-ghost border-(--border) bg-(--surface-subtle) text-(--foreground) hover:border-(--border-hover) hover:bg-(--muted)",
        danger: "border-danger bg-danger text-white hover:border-danger hover:bg-danger/90",
        accent: "border-transparent bg-(--accent) text-(--accent-foreground) hover:opacity-90",
      },
      size: {
        sm: "h-[30px] rounded-(--r-sm) px-[11px] text-[12px] max-md:min-h-11",
        md: "h-[38px] px-[15px] text-[13.5px] max-md:min-h-11",
        lg: "h-11 px-5 text-[14.5px]",
      },
    },
    defaultVariants: {
      variant: "primary",
      size: "md",
    },
  }
);

const legacyVariantClasses: Partial<Record<ButtonVariant, string>> = {
  outline: "signal-button-outline",
  cta: "tracking-normal",
};

export const buttonClasses = ({
  variant = "primary",
  size = "md",
  className,
}: ButtonStyleOptions = {}) =>
  variant === "auth"
    ? cn(
        "inline-flex min-h-11 min-w-0 cursor-pointer items-center justify-center gap-1.5 rounded-full border border-transparent bg-[color:var(--auth-primary,var(--blue))] bg-(image:--auth-gradient) px-[15px] py-2.5 font-(family-name:--body-font) text-[13.5px] font-semibold leading-[1.5] tracking-normal text-(--panel) transition-[filter,box-shadow] duration-150 hover:brightness-[1.06] focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--brand) disabled:cursor-not-allowed disabled:opacity-45",
        className
      )
    : cn(
        buttonVariants({ variant: legacyVariantMap[variant], size }),
        legacyVariantClasses[variant],
        className
      );

export type ButtonProps = React.ButtonHTMLAttributes<HTMLButtonElement> &
  ButtonStyleOptions & {
    loading?: boolean;
    loadingText?: string;
  };

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  (
    {
      variant = "primary",
      size = "md",
      className,
      type = "button",
      loading,
      loadingText,
      children,
      disabled,
      ...props
    },
    ref
  ) => (
    <button
      ref={ref}
      type={type}
      className={buttonClasses({ variant, size, className })}
      disabled={disabled || loading}
      {...props}
    >
      {loading ? (
        <>
          <Loader2 className="h-4 w-4 animate-spin" />
          {loadingText ?? children}
        </>
      ) : (
        children
      )}
    </button>
  )
);

Button.displayName = "Button";

export { buttonVariants };

export default Button;
