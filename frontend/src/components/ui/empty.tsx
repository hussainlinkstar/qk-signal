import React from "react";
import { cx } from "./utils";

const Empty = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} data-slot="empty" className={cx("p-8 text-center", className)} {...props} />
  )
);
Empty.displayName = "Empty";

const EmptyMedia = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div
      ref={ref}
      data-slot="empty-icon"
      className={cx(
        "mx-auto mb-4 inline-flex h-12 w-12 items-center justify-center rounded-full border-0 bg-(--surface-subtle)",
        className
      )}
      {...props}
    />
  )
);
EmptyMedia.displayName = "EmptyMedia";

const EmptyTitle = React.forwardRef<HTMLHeadingElement, React.HTMLAttributes<HTMLHeadingElement>>(
  ({ className, ...props }, ref) => (
    <h3
      ref={ref}
      data-slot="empty-title"
      className={cx("text-lg font-semibold text-(--foreground)", className)}
      {...props}
    />
  )
);
EmptyTitle.displayName = "EmptyTitle";

const EmptyDescription = React.forwardRef<
  HTMLParagraphElement,
  React.HTMLAttributes<HTMLParagraphElement>
>(({ className, ...props }, ref) => (
  <p
    ref={ref}
    data-slot="empty-description"
    className={cx("mt-2 text-sm text-(--text-muted)", className)}
    {...props}
  />
));
EmptyDescription.displayName = "EmptyDescription";

const EmptyContent = React.forwardRef<HTMLDivElement, React.HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <div ref={ref} data-slot="empty-content" className={cx("mt-4", className)} {...props} />
  )
);
EmptyContent.displayName = "EmptyContent";

export { Empty, EmptyMedia, EmptyTitle, EmptyDescription, EmptyContent };
