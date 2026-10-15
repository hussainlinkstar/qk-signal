"use client";

import React, { useEffect, useState, useCallback } from "react";
import { Bell } from "lucide-react";
import Link from "next/link";
import { useAuth } from "@/components/auth/custom-auth";

export function AdminAlertBell() {
  const { getToken, isSignedIn } = useAuth();
  const [count, setCount] = useState(0);

  const checkAlerts = useCallback(async () => {
    if (!isSignedIn) return;
    try {
      const token = await getToken();
      const res = await fetch("/api/admin/alerts/events?status=active", {
        headers: { Authorization: `Bearer ${token}` },
      });
      if (res.ok) {
        const data = await res.json();
        setCount(data.length || 0);
      }
    } catch (err) {
      // Ignore for the bell widget
    }
  }, [getToken, isSignedIn]);

  useEffect(() => {
    checkAlerts();
    // Poll every 60 seconds
    const interval = setInterval(checkAlerts, 60000);
    return () => clearInterval(interval);
  }, [checkAlerts]);

  return (
    <Link
      href="/admin/alerts"
      className="relative inline-flex h-9 w-9 items-center justify-center rounded-(--r-md) border-0 bg-white text-(--t-2) transition-colors hover:bg-(--paper) hover:text-(--t-1)"
      title="System Alerts"
    >
      <Bell size={16} />
      {count > 0 && (
        <span className="absolute -top-1.5 -right-1.5 flex h-4 min-w-4 items-center justify-center rounded-full bg-(--bad) px-1 font-(family-name:--mono) text-[9px] text-white">
          {count > 99 ? "99+" : count}
        </span>
      )}
    </Link>
  );
}
