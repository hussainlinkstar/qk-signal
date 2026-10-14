import React from "react";

type PlanWordmark = "Starter" | "Standard" | "Specialist" | "Executive";

type PlanWordmarkConfig = {
  lead: string;
  tail: string;
  width: number;
};

const PLAN_WORDMARKS: Record<PlanWordmark, PlanWordmarkConfig> = {
  Starter: {
    lead: "Starter",
    tail: "",
    width: 360,
  },
  Standard: {
    lead: "Standard",
    tail: "",
    width: 420,
  },
  Specialist: {
    lead: "Specialist",
    tail: "",
    width: 460,
  },
  Executive: {
    lead: "Executive",
    tail: "",
    width: 460,
  },
};

interface PlanTypeWordmarkProps {
  planName: string;
  className?: string;
}

export default function PlanTypeWordmark({ planName, className = "" }: PlanTypeWordmarkProps) {
  const config = PLAN_WORDMARKS[planName as PlanWordmark];

  if (!config) {
    return <span className={className}>{planName}</span>;
  }

  return (
    <svg
      aria-hidden="true"
      className={className}
      role="presentation"
      viewBox={`0 0 ${config.width} 100`}
      xmlns="http://www.w3.org/2000/svg"
    >
      <text
        x="50%"
        y="68"
        fill="currentColor"
        fontFamily="Manrope, ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, Helvetica, Arial"
        fontSize="56"
        letterSpacing="0.01em"
        textAnchor="middle"
      >
        <tspan fontWeight="900">{config.lead}</tspan>
        <tspan dx="4" fontWeight="300">
          {config.tail}
        </tspan>
      </text>
    </svg>
  );
}
