"use client";

import React from "react";
import Card from "@/components/ui/Card";
import TextField from "@/components/ui/TextField";
import { cx } from "@/components/ui/utils";

export const GlassCard = ({
  children,
  className,
  glow = false,
  glowColor = "primary",
  ...props
}: React.HTMLAttributes<HTMLDivElement> & {
  glow?: boolean;
  glowColor?: "primary" | "indigo" | "slate" | "amber";
}) => (
  <Card
    {...props}
    variant="glass"
    glow={glow}
    className={cx("relative overflow-hidden", className)}
    data-glow-color={glowColor}
  >
    {children}
  </Card>
);

export const CyberField = ({ label, ...props }: React.ComponentProps<typeof TextField>) => (
  <TextField {...props} label={label} className={cx("h-11", props.className)} />
);
