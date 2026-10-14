import React from "react";
import Card from "./Card";
import { EmptyContent, EmptyDescription, EmptyMedia, EmptyTitle } from "./empty";
import { cx } from "./utils";
import type { LucideIcon } from "lucide-react";

type EmptyStateProps = {
  icon?: LucideIcon;
  title: string;
  description?: string;
  action?: React.ReactNode;
  className?: string;
};

export default function EmptyState({
  icon: Icon,
  title,
  description,
  action,
  className,
}: EmptyStateProps) {
  return (
    <Card className={cx("p-8 text-center", className)} variant="surface">
      {Icon && (
        <EmptyMedia>
          <Icon className="h-6 w-6 text-primary" />
        </EmptyMedia>
      )}
      <EmptyTitle>{title}</EmptyTitle>
      {description && <EmptyDescription>{description}</EmptyDescription>}
      {action && <EmptyContent>{action}</EmptyContent>}
    </Card>
  );
}
