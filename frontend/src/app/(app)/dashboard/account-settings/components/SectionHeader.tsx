import React from "react";
import { cx } from "@/components/ui/utils";

type SectionHeaderProps = {
  icon: React.ReactNode;
  iconColorClass: string;
  title: string;
  description: string;
  badge?: React.ReactNode;
};

const SectionHeader: React.FC<SectionHeaderProps> = ({
  icon,
  iconColorClass,
  title,
  description,
  badge,
}) => (
  <div className="flex items-start justify-between gap-4">
    <div className="flex items-start gap-3.5">
      <div
        className={cx(
          "flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border",
          iconColorClass
        )}
      >
        {icon}
      </div>
      <div className="min-w-0">
        <h3 className="text-lg font-bold tracking-tight text-(--t-1)">{title}</h3>
        <p className="mt-0.5 text-sm text-(--t-2)">{description}</p>
      </div>
    </div>
    {badge}
  </div>
);

export default SectionHeader;
