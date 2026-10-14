"use client";

import { useCallback, useRef, type FocusEvent, type ReactNode } from "react";

/**
 * SIGV2-1226: lets keyboard focus leave a live toast.
 *
 * Sonner's toaster list keeps two refs. On focus entering the list it records
 * `event.relatedTarget`, the element focus arrived from; on focus leaving the
 * list it calls `.focus()` on that recorded element. The intent is to restore
 * focus after someone deliberately visits a notification, but it does not
 * distinguish that case from a Tab that is simply passing through, so every
 * attempt to Tab out of a toast is answered by putting focus back where it
 * came from. For the four seconds a toast is alive, a keyboard user cannot get
 * past it. Paired with SIGV2-1217, which just gave 628 controls a visible
 * focus ring, the effect is a clearly drawn ring that will not move.
 *
 * There is no prop for this: `ToasterProps` in sonner 1.7.4 exposes no focus
 * option, so it cannot be configured away, and forking the library is out.
 * What is left is intercepting the events it listens to. Both handlers are
 * React props on the toaster's own `<ol>`, so a capture-phase handler on an
 * ancestor runs first in React's dispatch queue and `stopPropagation()` keeps
 * the event from ever reaching them. The bookkeeping never happens, so the
 * restore it drives never happens either, and focus moves on normally.
 *
 * Stopping the event is deliberately narrow. It suppresses sonner's record and
 * restore and nothing else: the toast `<li>` keeps its `tabIndex={0}`, the
 * close button stays a real button, and the alt+T hotkey still focuses the
 * stack. The toast stays reachable on purpose, which matters, because a
 * dismissible notification a keyboard user cannot reach is its own failure.
 * Only the involuntary return trip is gone.
 *
 * The one behaviour given up is sonner's focus restore after a toast is
 * dismissed from the keyboard. That is replaced below, but narrowed to the
 * case it was meant for: focus is returned only when the element holding it
 * has left the document, never when the user chose to Tab away.
 *
 * The wrapper is `display: contents`, so it adds no box and cannot affect the
 * fixed-position toast stack or any screenshot.
 */
export default function ToastFocusRelease({ children }: { children: ReactNode }) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);
  // Where focus was before it entered the toaster, so a toast that disappears
  // under the user does not strand them on <body>.
  const returnTargetRef = useRef<HTMLElement | null>(null);

  const isInsideToaster = useCallback(
    (node: EventTarget | null): boolean =>
      node instanceof Node && !!wrapperRef.current?.contains(node),
    []
  );

  const handleFocusCapture = useCallback(
    (event: FocusEvent<HTMLDivElement>) => {
      // Sonner's record step. Stop it here and the restore step has nothing
      // to act on.
      event.stopPropagation();

      if (isInsideToaster(event.relatedTarget)) return;
      returnTargetRef.current =
        event.relatedTarget instanceof HTMLElement ? event.relatedTarget : null;
    },
    [isInsideToaster]
  );

  const handleBlurCapture = useCallback(
    (event: FocusEvent<HTMLDivElement>) => {
      // Sonner's restore step.
      event.stopPropagation();

      const departed = event.target as HTMLElement;

      if (event.relatedTarget !== null) {
        // Focus has a destination, so the move was deliberate. If it left the
        // toaster the user chose to go; forget where they came from rather
        // than dragging them back. This is the Tab the ticket is about.
        if (!isInsideToaster(event.relatedTarget)) returnTargetRef.current = null;
        return;
      }

      // No destination: focus fell to <body>. If the element that held it is
      // gone, the toast was dismissed or expired while focused, and the
      // keyboard user would otherwise restart from the top of the document.
      const returnTarget = returnTargetRef.current;
      returnTargetRef.current = null;
      queueMicrotask(() => {
        if (departed.isConnected) return;
        if (!returnTarget?.isConnected) return;
        if (document.activeElement !== document.body) return;
        returnTarget.focus({ preventScroll: true });
      });
    },
    [isInsideToaster]
  );

  return (
    <div
      ref={wrapperRef}
      style={{ display: "contents" }}
      onFocusCapture={handleFocusCapture}
      onBlurCapture={handleBlurCapture}
    >
      {children}
    </div>
  );
}
