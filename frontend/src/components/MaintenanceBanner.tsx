"use client";

import React, { useEffect, useState } from "react";
import { motion, AnimatePresence } from "motion/react";
import SignalAlert from "@/components/signal/SignalAlert";

export const MaintenanceBanner = () => {
  const [scheduleStart, setScheduleStart] = useState<Date | null>(null);
  const [message, setMessage] = useState<string>("");

  useEffect(() => {
    // Scheduled maintenance notice for any authenticated user. The admin
    // endpoint (/api/admin/maintenance) is not usable here: it 403s for every
    // non-admin, which the browser logs as a console error on every page load.
    fetch("/api/maintenance-notice")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data?.maintenance?.scheduled_start) {
          const start = new Date(data.maintenance.scheduled_start);
          // Only show banner if maintenance is within the next 24 hours
          const now = new Date();
          const hoursUntil = (start.getTime() - now.getTime()) / (1000 * 60 * 60);

          if (hoursUntil > 0 && hoursUntil <= 24) {
            setScheduleStart(start);
            setMessage(data.maintenance.message || "Scheduled maintenance will start soon.");
          }
        }
      })
      .catch(() => {});
  }, []);

  if (!scheduleStart) return null;

  const formattedTime = new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    hour: "numeric",
    minute: "2-digit",
    timeZoneName: "short",
  }).format(scheduleStart);

  return (
    <AnimatePresence>
      <motion.div
        initial={{ height: 0, opacity: 0 }}
        animate={{ height: "auto", opacity: 1 }}
        exit={{ height: 0, opacity: 0 }}
        className="px-4 py-2"
      >
        <SignalAlert
          tone="warning"
          title="Scheduled System Maintenance"
          className="mx-auto max-w-7xl"
        >
          <p>Scheduled System Maintenance on {formattedTime}.</p>
          <p>{message}</p>
        </SignalAlert>
      </motion.div>
    </AnimatePresence>
  );
};
