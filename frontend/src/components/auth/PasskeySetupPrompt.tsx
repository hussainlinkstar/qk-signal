"use client";

import React, { useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { Fingerprint, X } from "lucide-react";

import { useAuth } from "@/contexts/AuthContext";
import { useCookieConsent } from "@/contexts/CookieConsentContext";
import { listPasskeys, registerPasskey } from "@/services/passkey.service";
import Modal from "@/components/ui/Modal";
import Button from "@/components/ui/Button";

const STORAGE_KEY = "passkey_prompt_dismissed_at";
const DISMISS_COOLDOWN_DAYS = 30;

function isDismissed(): boolean {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) return false;
    const dismissed = new Date(raw);
    const elapsed = Date.now() - dismissed.getTime();
    return elapsed < DISMISS_COOLDOWN_DAYS * 24 * 60 * 60 * 1000;
  } catch {
    return false;
  }
}

function markDismissed(): void {
  try {
    localStorage.setItem(STORAGE_KEY, new Date().toISOString());
  } catch {
    /* storage unavailable */
  }
}

export default function PasskeySetupPrompt() {
  const { user, getToken } = useAuth();
  const { hasAnswered, isSettingsOpen } = useCookieConsent();
  const [open, setOpen] = useState(false);
  const [registering, setRegistering] = useState(false);

  useEffect(() => {
    if (!user || isDismissed() || !hasAnswered || isSettingsOpen) return;

    let cancelled = false;
    (async () => {
      try {
        const token = await getToken();
        if (!token || cancelled) return;
        const passkeys = await listPasskeys(token);
        if (!cancelled && passkeys.length === 0) {
          setOpen(true);
        }
      } catch {
        // Silently ignore, the prompt is not critical
      }
    })();

    return () => {
      cancelled = true;
    };
  }, [user, getToken, hasAnswered, isSettingsOpen]);

  const handleDismiss = useCallback(() => {
    markDismissed();
    setOpen(false);
  }, []);

  const handleRegister = useCallback(async () => {
    setRegistering(true);
    try {
      const token = await getToken();
      if (!token) throw new Error("Not authenticated");
      await registerPasskey(token, "My Passkey");
      toast.success("Passkey registered successfully.");
      markDismissed();
      setOpen(false);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Passkey registration failed.";
      if (
        message.includes("cancelled") ||
        message.includes("AbortError") ||
        message.includes("NotAllowedError")
      ) {
        return;
      }
      toast.error(message);
    } finally {
      setRegistering(false);
    }
  }, [getToken]);

  return (
    <Modal
      open={open && hasAnswered && !isSettingsOpen}
      onClose={handleDismiss}
      title="Set up a passkey"
      ariaDescribedby="passkey-prompt-description"
      className="bg-[color-mix(in_srgb,var(--ink)_42%,transparent)]! backdrop-blur-[3px]! animate-none!"
      panelClassName="w-[420px] max-w-[calc(100vw-32px)] rounded-[20px]! border-(--line)! bg-(--panel)! p-0! animate-none!"
    >
      <div
        data-signal-theme
        className="relative rounded-[20px] bg-(--panel) p-6 font-(family-name:--body-font) text-(--t-1) [--auth-gradient:var(--grad)] sm:p-7"
      >
        <button
          aria-label="Dismiss"
          className="absolute end-3 top-3 flex h-9 w-9 items-center justify-center rounded-(--r-sm) text-(--t-3) transition-colors duration-150 hover:bg-(--line-2) hover:text-(--t-1) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--brand)"
          onClick={handleDismiss}
          type="button"
        >
          <X className="h-4 w-4" aria-hidden="true" />
        </button>

        <div className="mb-[18px] flex h-[46px] w-[46px] items-center justify-center rounded-[13px] bg-(--purple-s) text-(--purple)">
          <Fingerprint className="h-[23px] w-[23px]" strokeWidth={1.9} aria-hidden="true" />
        </div>
        <h2
          aria-hidden="true"
          className="font-(family-name:--disp) text-[23px] font-extrabold leading-[1.3] tracking-[-0.02em]"
        >
          Set up a passkey
        </h2>
        <p
          id="passkey-prompt-description"
          className="mt-2 text-[13.5px] leading-[1.5] text-(--t-2)"
        >
          Sign in faster and more securely with a passkey. Passkeys use your device&apos;s
          biometrics or screen lock, no password needed.
        </p>

        <div className="mt-6 flex flex-col gap-2.5">
          <Button
            className="w-full"
            loading={registering}
            loadingText="Setting up passkey..."
            size="md"
            variant="auth"
            onClick={handleRegister}
          >
            <Fingerprint className="h-4 w-4" aria-hidden="true" />
            Set up passkey
          </Button>
          <button
            className="inline-flex min-h-11 w-full items-center justify-center rounded-full border-0 bg-white px-[15px] text-[13.5px] font-semibold text-(--t-2) transition-colors duration-150 hover:bg-[#E8ECF3] hover:bg-(--paper) focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-(--brand) disabled:cursor-not-allowed disabled:opacity-45"
            disabled={registering}
            type="button"
            onClick={handleDismiss}
          >
            Maybe later
          </button>
        </div>
      </div>
    </Modal>
  );
}
