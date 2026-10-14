"use client";

import { asset } from "@/lib/basePath";
import { useCallback, useEffect, useRef } from "react";

/**
 * Sends a browser Notification when the document is hidden (tab backgrounded).
 *
 * - Lazily requests permission on the first `notify()` call while the tab is
 *   visible so the browser prompt is not intrusive.
 * - If the user has denied permission, `notify()` is a no-op.
 * - Clicking the notification focuses the originating tab and optionally
 *   navigates via the provided `onClick` callback.
 */
export function useAuditNotification() {
  const permissionRef = useRef<NotificationPermission>(
    typeof Notification !== "undefined" ? Notification.permission : "denied"
  );

  useEffect(() => {
    if (typeof Notification !== "undefined") {
      permissionRef.current = Notification.permission;
    }
  }, []);

  const requestPermission = useCallback(async () => {
    if (typeof Notification === "undefined") return "denied" as const;
    if (permissionRef.current === "granted") return "granted" as const;
    if (permissionRef.current === "denied") return "denied" as const;

    try {
      const result = await Notification.requestPermission();
      permissionRef.current = result;
      return result;
    } catch {
      return "denied" as const;
    }
  }, []);

  const notify = useCallback(
    async ({ title, body, onClick }: { title: string; body?: string; onClick?: () => void }) => {
      if (typeof Notification === "undefined") return;
      if (typeof document !== "undefined" && document.visibilityState === "visible") return;

      if (permissionRef.current === "default") {
        await requestPermission();
      }
      if (permissionRef.current !== "granted") return;

      try {
        const n = new Notification(title, {
          body,
          icon: asset("/icon-192.png"),
          tag: "audit-complete",
        });

        n.onclick = () => {
          window.focus();
          n.close();
          onClick?.();
        };
      } catch {
        // Notification constructor may throw in some environments
      }
    },
    [requestPermission]
  );

  return { notify, requestPermission };
}
