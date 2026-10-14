import React from "react";
import { cva } from "class-variance-authority";
import { cx } from "./utils";

type BadgeSize = "sm" | "md";
type BadgeColor = "default" | "success" | "warning" | "danger" | "info" | "teal" | "violet";

type BadgeProps = {
  children: React.ReactNode;
  size?: BadgeSize;
  color?: BadgeColor;
  className?: string;
};

const badgeVariants = cva("inline-flex items-center rounded-full border font-semibold capitalize", {
  variants: {
    size: {
      sm: "px-2.5 py-1 text-xs",
      md: "px-3.5 py-1.5 text-sm",
    },
    color: {
      default: "border-(--border) bg-(--surface-subtle) text-(--text-soft)",
      success: "border-success/20 bg-success/10 text-success",
      warning: "border-warning/20 bg-warning/10 text-warning",
      danger: "border-danger/20 bg-danger/10 text-danger",
      info: "border-info/20 bg-info/10 text-info",
      teal: "border-accent/20 bg-accent/10 text-accent",
      violet: "border-violet-500/20 bg-violet-500/10 text-violet-400",
    },
  },
  defaultVariants: {
    size: "sm",
    color: "default",
  },
});

export default function Badge({ children, size = "sm", color = "default", className }: BadgeProps) {
  return <span className={cx(badgeVariants({ size, color }), className)}>{children}</span>;
}
