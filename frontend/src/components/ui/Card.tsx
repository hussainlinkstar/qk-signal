import React from "react";
import { cva } from "class-variance-authority";
import { cn } from "./utils";
import { CARD_RADIUS_OUTER_CLASS } from "./cardStyleTokens";

export type CardVariant = "surface" | "glass" | "accent";

type CardProps<T extends React.ElementType> = {
  as?: T;
  variant?: CardVariant;
  glow?: boolean;
  className?: string;
} & Omit<React.ComponentPropsWithoutRef<T>, "as" | "className">;

const cardVariants = cva("relative overflow-hidden", {
  variants: {
    variant: {
      surface: "surface-card",
      glass: "glass-surface hover:shadow-lg",
      accent: "glass-accent hover:shadow-lg",
    },
  },
  defaultVariants: {
    variant: "surface",
  },
});

const Card = <T extends React.ElementType = "div">({
  as,
  variant = "surface",
  glow = false,
  className,
  ...props
}: CardProps<T>) => {
  const Component = as ?? "div";

  return (
    <Component
      data-signal-card
      className={cn(
        CARD_RADIUS_OUTER_CLASS,
        cardVariants({ variant }),
        glow && "shadow-primary/20 shadow-lg border-primary/30",
        className
      )}
      {...props}
    />
  );
};

export default Card;
