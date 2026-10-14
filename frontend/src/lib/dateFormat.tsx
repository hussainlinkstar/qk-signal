"use client";

import React, { useEffect, useState } from "react";
import {
  formatDate,
  formatDateLong,
  formatDateTime,
  type DateDisplayFormat,
} from "./dateFormatShared";

export {
  formatDate,
  formatDateLong,
  formatDateTime,
  formatDateForFilename,
  formatISO,
  formatRelativeTime,
} from "./dateFormatShared";

/**
 * Client-safe Date component to avoid hydration mismatches.
 */
export function ClientSafeDate({
  date,
  format = "datetime",
}: {
  date: string | Date;
  format?: DateDisplayFormat;
}) {
  const [mounted, setMounted] = useState(false);

  useEffect(() => {
    setMounted(true);
  }, []);

  if (!mounted) {
    // Return a predictable skeleton to avoid layout shift and hydration error
    return <span className="opacity-0">Pending...</span>;
  }

  let text = "\u2014";
  if (format === "date") text = formatDate(date);
  else if (format === "long") text = formatDateLong(date);
  else text = formatDateTime(date);

  return <span>{text}</span>;
}
