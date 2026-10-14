import React from "react";
import { cx } from "@/components/ui/utils";

export type SectionHeaderProps = {
  icon: React.ReactNode;
  iconColorClass?: string;
  iconContainerClassName?: string;
  title: React.ReactNode;
  description?: React.ReactNode;
  badge?: React.ReactNode;
  className?: string;
  titleClassName?: string;
};

const SectionHeader: React.FC<SectionHeaderProps> = ({
  icon,
  iconColorClass,
  iconContainerClassName = "flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border",
  title,
  description,
  badge,
  className,
  titleClassName = "text-lg font-bold tracking-tight text-white",
}) => (
  <div className={cx("flex items-start justify-between gap-4", className)}>
    <div className="flex items-start gap-3.5">
      <div className={cx(iconContainerClassName, iconColorClass)}>{icon}</div>
      <div className="min-w-0">
        {typeof title === "string" ? <h3 className={titleClassName}>{title}</h3> : title}
        {description &&
          (typeof description === "string" ? (
            <p className="mt-0.5 text-sm text-slate-400">{description}</p>
          ) : (
            description
          ))}
      </div>
    </div>
    {badge}
  </div>
);

export default SectionHeader;
