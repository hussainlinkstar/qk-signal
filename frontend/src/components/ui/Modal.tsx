"use client";

import React, { useEffect, useRef, useState } from "react";
import { cn, cx } from "./utils";
import { RADIUS_PANEL_CLASS } from "./radiusTokens";
import { Dialog, DialogPortal, DialogOverlay, DialogContent, DialogTitle } from "./dialog";

type ModalProps = {
  open: boolean;
  onClose: () => void;
  children: React.ReactNode;
  /** Additional classes on the backdrop */
  className?: string;
  /** Additional classes on the panel */
  panelClassName?: string;
  /** Whether clicking the backdrop closes the modal (default true) */
  closeOnBackdrop?: boolean;
  /** Whether pressing Escape closes the modal (default true) */
  closeOnEscape?: boolean;
  /** When true, modal goes full-screen below md breakpoint */
  fullscreenOnMobile?: boolean;
  /**
   * Focus the dialog panel itself on open instead of the first control. Use
   * for dialogs whose first control is a consequential action (e.g. purchase)
   * so mounting never lands the user on it unannounced.
   */
  initialFocusPanel?: boolean;
  /** Keep background interactive (no focus trap, no scroll lock) */
  nonModal?: boolean;
  /** Vertical placement: centered (default) or anchored near the viewport top */
  panelPosition?: "center" | "top";
  /** Accessible name rendered visually hidden when the design has no heading */
  title?: string;
  ariaLabelledby?: string;
  ariaDescribedby?: string;
};

// CSS scope hooks that portalled dialogs must re-apply on their wrapper.
const PORTAL_SCOPE_HOOKS = ["app-shell"];

// `.sg` scopes always sit inside [data-signal-theme] and carried the signal
// base styles (text colour, body font, smoothing) that children inherit. The
// class rules are gone with signal-mvp.css, so themed portals re-apply them
// as utilities on the wrapper.
const SG_PORTAL_CLASSES = "text-(--t-1) font-(family-name:--body-font) antialiased";

const FOCUSABLE_SELECTOR =
  'button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])';

export default function Modal({
  open,
  onClose,
  children,
  className,
  panelClassName,
  closeOnBackdrop = true,
  closeOnEscape = true,
  fullscreenOnMobile = false,
  initialFocusPanel = false,
  nonModal = false,
  panelPosition = "center",
  title = "Dialog",
  ariaLabelledby,
  ariaDescribedby,
}: ModalProps) {
  const anchorRef = useRef<HTMLSpanElement>(null);
  const panelRef = useRef<HTMLDivElement>(null);
  const restoreFocusRef = useRef<HTMLElement | null>(null);
  const [portalScope, setPortalScope] = useState<{ themed: boolean; classes: string[] }>({
    themed: false,
    classes: [],
  });

  useEffect(() => {
    // The portal escapes the page's stacking contexts, and with them every
    // CSS scope the caller was inside: [data-signal-theme] tokens, the signal
    // base styles and the `.app-shell` palette. Re-apply each hook found on
    // the caller's ancestors so the dialog keeps the styling it had inline.
    const classes = new Set<string>();
    let themed = false;
    for (let el = anchorRef.current?.parentElement ?? null; el; el = el.parentElement) {
      if (el.hasAttribute("data-signal-theme")) themed = true;
      for (const hook of PORTAL_SCOPE_HOOKS) {
        if (el.classList.contains(hook)) classes.add(hook);
      }
    }
    setPortalScope({ themed, classes: [...classes] });
  }, []);

  const focusFirstControl = () => {
    const panel = panelRef.current;
    if (initialFocusPanel) {
      panel?.focus();
      return;
    }
    const firstControl = panel?.querySelector<HTMLElement>(FOCUSABLE_SELECTOR);
    (firstControl ?? panel)?.focus();
  };

  // Restore focus to whatever was focused before the dialog opened. Radix's
  // own restore is unreliable once the content has unmounted, so keep ours.
  useEffect(() => {
    if (!open) return;
    restoreFocusRef.current =
      document.activeElement instanceof HTMLElement ? document.activeElement : null;
    return () => {
      restoreFocusRef.current?.focus();
      restoreFocusRef.current = null;
    };
  }, [open]);

  return (
    <>
      <span ref={anchorRef} hidden />
      <Dialog open={open} modal={!nonModal} onOpenChange={(next) => !next && onClose()}>
        <DialogPortal>
          <div className={cx("contents", ...portalScope.classes)}>
            <div
              data-signal-theme={portalScope.themed ? "" : undefined}
              className={cx("contents", portalScope.themed && SG_PORTAL_CLASSES)}
            >
              <DialogOverlay
                className={cn(
                  portalScope.themed ? "backdrop-blur-[3px]" : "animate-in fade-in duration-150",
                  className
                )}
              />
              <div
                className={cx(
                  "fixed inset-0 z-modal flex justify-center",
                  panelPosition === "top" ? "items-start pt-[15vh]" : "items-center"
                )}
              >
                <DialogContent
                  ref={panelRef}
                  tabIndex={initialFocusPanel ? -1 : undefined}
                  aria-modal={!nonModal || undefined}
                  {...(ariaLabelledby ? { "aria-labelledby": ariaLabelledby } : {})}
                  aria-describedby={ariaDescribedby}
                  onInteractOutside={(e) => {
                    if (!closeOnBackdrop) e.preventDefault();
                  }}
                  onEscapeKeyDown={(e) => {
                    if (!closeOnEscape) e.preventDefault();
                  }}
                  onOpenAutoFocus={(e) => {
                    e.preventDefault();
                    focusFirstControl();
                  }}
                  className={cn(
                    "relative mx-4 max-h-[90vh] overflow-y-auto",
                    portalScope.themed
                      ? "w-[560px] max-w-[calc(100vw-32px)] rounded-[20px] border-(--line) bg-(--panel) px-[30px] pt-7 pb-[26px] leading-[normal] shadow-(--modal-shadow)"
                      : `p-6 animate-in zoom-in-95 fade-in duration-200 ${RADIUS_PANEL_CLASS}`,
                    fullscreenOnMobile &&
                      "mx-0 h-full max-h-full w-full rounded-none md:mx-4 md:h-auto md:max-h-[90vh] md:w-auto md:rounded-(--r-lg)",
                    panelClassName
                  )}
                >
                  {!ariaLabelledby && <DialogTitle className="sr-only">{title}</DialogTitle>}
                  {children}
                </DialogContent>
              </div>
            </div>
          </div>
        </DialogPortal>
      </Dialog>
    </>
  );
}
