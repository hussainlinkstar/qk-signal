"use client";

import React from "react";

import MonitoringSummaryCard from "@/components/settings/MonitoringSummaryCard";

/** Section 5. The card owns its own copy and its own "coming soon" treatment. */
export default function MonitoringSection() {
  return (
    <div id="monitoring">
      <MonitoringSummaryCard />
    </div>
  );
}
