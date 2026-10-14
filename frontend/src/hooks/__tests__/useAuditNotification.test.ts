import { renderHook, act } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";

import { useAuditNotification } from "@/hooks/useAuditNotification";

describe("useAuditNotification", () => {
  const originalNotification = globalThis.Notification;
  let notificationInstances: Array<{
    title: string;
    options?: NotificationOptions;
    onclick: ((ev: Event) => void) | null;
    close: ReturnType<typeof vi.fn>;
  }>;

  beforeEach(() => {
    notificationInstances = [];

    const FakeNotification = vi.fn(function (
      this: any,
      title: string,
      options?: NotificationOptions
    ) {
      this.title = title;
      this.options = options;
      this.onclick = null;
      this.close = vi.fn();
      notificationInstances.push(this);
      return this;
    }) as any;

    FakeNotification.permission = "granted";
    FakeNotification.requestPermission = vi.fn(async () => "granted");

    globalThis.Notification = FakeNotification;
  });

  afterEach(() => {
    globalThis.Notification = originalNotification;
  });

  it("does not fire a notification when the tab is visible", async () => {
    Object.defineProperty(document, "visibilityState", {
      value: "visible",
      writable: true,
      configurable: true,
    });

    const { result } = renderHook(() => useAuditNotification());

    await act(async () => {
      await result.current.notify({ title: "Test", body: "body" });
    });

    expect(notificationInstances).toHaveLength(0);
  });

  it("fires a notification when the tab is hidden and permission is granted", async () => {
    Object.defineProperty(document, "visibilityState", {
      value: "hidden",
      writable: true,
      configurable: true,
    });

    const { result } = renderHook(() => useAuditNotification());

    await act(async () => {
      await result.current.notify({ title: "Audit Complete", body: "Score: 85" });
    });

    expect(notificationInstances).toHaveLength(1);
    expect(notificationInstances[0].title).toBe("Audit Complete");
    expect(notificationInstances[0].options?.body).toBe("Score: 85");
  });

  it("calls onClick and focuses window when notification is clicked", async () => {
    Object.defineProperty(document, "visibilityState", {
      value: "hidden",
      writable: true,
      configurable: true,
    });

    const focusSpy = vi.spyOn(window, "focus").mockImplementation(() => {});
    const onClickMock = vi.fn();

    const { result } = renderHook(() => useAuditNotification());

    await act(async () => {
      await result.current.notify({ title: "Done", onClick: onClickMock });
    });

    expect(notificationInstances).toHaveLength(1);

    // Simulate click
    act(() => {
      notificationInstances[0].onclick?.(new Event("click"));
    });

    expect(focusSpy).toHaveBeenCalled();
    expect(onClickMock).toHaveBeenCalled();
    expect(notificationInstances[0].close).toHaveBeenCalled();

    focusSpy.mockRestore();
  });

  it("requests permission when permission is default", async () => {
    (globalThis.Notification as any).permission = "default";
    Object.defineProperty(document, "visibilityState", {
      value: "hidden",
      writable: true,
      configurable: true,
    });

    const { result } = renderHook(() => useAuditNotification());

    await act(async () => {
      await result.current.notify({ title: "Test" });
    });

    expect(Notification.requestPermission).toHaveBeenCalled();
  });

  it("does not fire a notification when permission is denied", async () => {
    (globalThis.Notification as any).permission = "denied";
    Object.defineProperty(document, "visibilityState", {
      value: "hidden",
      writable: true,
      configurable: true,
    });

    const { result } = renderHook(() => useAuditNotification());

    await act(async () => {
      await result.current.notify({ title: "Test" });
    });

    expect(notificationInstances).toHaveLength(0);
  });
});
