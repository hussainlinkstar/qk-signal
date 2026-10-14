import React, { type ReactNode } from "react";

import { cx } from "@/components/ui/utils";

type ProjectPageFrameProps = {
  title: string;
  accent?: string;
  description?: ReactNode;
  children: ReactNode;
  className?: string;
  introClassName?: string;
  titleClassName?: string;
  descriptionClassName?: string;
  accentClassName?: string;
};

export default function ProjectPageFrame({
  title,
  accent,
  description,
  children,
  className,
  introClassName,
  titleClassName,
  descriptionClassName,
  accentClassName = "font-medium text-(--t-3)",
}: ProjectPageFrameProps) {
  return (
    <div
      className={cx("space-y-6 animate-in fade-in slide-in-from-bottom-4 duration-500", className)}
    >
      <div className={cx("flex flex-col gap-1", introClassName)}>
        <h1
          className={cx(
            "font-(family-name:--disp) text-[24px] font-extrabold tracking-[-0.02em] text-(--t-1)",
            titleClassName
          )}
        >
          {title}
          {accent ? (
            <>
              {" "}
              <span className={accentClassName}>{accent}</span>
            </>
          ) : null}
        </h1>

        {description ? (
          <p
            className={cx(
              "max-w-3xl text-sm font-medium leading-relaxed text-(--t-2)",
              descriptionClassName
            )}
          >
            {description}
          </p>
        ) : null}
      </div>

      {children}
    </div>
  );
}
