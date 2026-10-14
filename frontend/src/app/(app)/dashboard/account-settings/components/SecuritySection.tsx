"use client";

import React, { useCallback, useEffect, useState } from "react";
import Image from "next/image";
import { useAccountSettings } from "../useAccountSettings";
import { useAuth } from "@/contexts/AuthContext";
import { cx } from "@/components/ui/utils";
import {
  registerPasskey,
  listPasskeys,
  renamePasskey,
  deletePasskey,
  type PasskeyListItem,
} from "@/services/passkey.service";
import {
  listLinkedIdentities,
  startIdentityLink,
  type LinkedIdentityStatus,
} from "@/services/linkedIdentity.service";
import { resolveBackendAuthUrl } from "@/lib/backendAuthUrl";

const LINK_RETURN_MESSAGES: Record<string, string> = {
  identity_already_linked:
    "That Microsoft account is already connected to another Qiko Signal account.",
  provider_profile_missing: "Microsoft did not return an account to connect. Please try again.",
  link_session_invalid: "The link request expired. Start again from this page.",
  oauth_failed: "Microsoft sign-in did not complete. Please try again.",
};

type SecuritySectionProps = {
  settings: ReturnType<typeof useAccountSettings>;
};

/* -------------------------------------------------------------------------- */
/*  Passkey list item                                                         */
/* -------------------------------------------------------------------------- */
const PasskeyRow: React.FC<{
  pk: PasskeyListItem;
  onRename: (id: number, name: string) => Promise<void>;
  onDelete: (id: number) => Promise<void>;
}> = ({ pk, onRename, onDelete }) => {
  const [editing, setEditing] = useState(false);
  const [draft, setDraft] = useState(pk.name);
  const [busy, setBusy] = useState(false);

  const save = async () => {
    if (!draft.trim()) return;
    setBusy(true);
    try {
      await onRename(pk.id, draft.trim());
      setEditing(false);
    } finally {
      setBusy(false);
    }
  };

  const remove = async () => {
    setBusy(true);
    try {
      await onDelete(pk.id);
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex items-center justify-between gap-4 border-t border-t-(--line-2) py-3.5 first:border-t-0 max-md:flex-wrap max-md:items-start max-md:[&>div]:min-w-0">
      <div className="min-w-0">
        {editing ? (
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <input
              aria-label="Passkey name"
              className="field-focus-ring h-[34px] w-[200px] max-w-full rounded-[10px] border border-(--line) bg-(--paper) px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#C7CDD6] disabled:bg-(--line-2) disabled:text-(--t-3)"
              value={draft}
              onChange={(e) => setDraft(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && save()}
              autoFocus
            />
            <button
              type="button"
              className="inline-flex h-[34px] cursor-pointer items-center gap-2 rounded-[10px] border border-(--line) bg-(--panel) px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:border-[#D7DAE0]"
              onClick={save}
              disabled={busy}
            >
              Save
            </button>
            <button
              type="button"
              className="inline-flex h-[34px] cursor-pointer items-center gap-2 rounded-[10px] border border-(--line) bg-(--panel) px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:border-[#D7DAE0]"
              onClick={() => {
                setDraft(pk.name);
                setEditing(false);
              }}
            >
              Cancel
            </button>
          </div>
        ) : (
          <div className="text-[13.5px] font-semibold">{pk.name}</div>
        )}
        <div className="mt-0.5 max-w-[560px] text-[12px] leading-[1.45] text-(--t-3)">
          Added {pk.created_at ? new Date(pk.created_at).toLocaleDateString() : "N/A"}
          {pk.last_used_at && <> · Last used {new Date(pk.last_used_at).toLocaleDateString()}</>}
          {pk.backed_up && <> · Synced</>}
        </div>
      </div>

      {!editing && (
        <div className="flex flex-wrap items-center gap-2 sm:flex-none">
          <button
            type="button"
            className="inline-flex h-[34px] cursor-pointer items-center gap-2 rounded-[10px] border border-(--line) bg-(--panel) px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:border-[#D7DAE0]"
            onClick={() => setEditing(true)}
          >
            Rename
          </button>
          <button
            type="button"
            className="inline-flex h-[34px] cursor-pointer items-center gap-2 rounded-[10px] border border-(--line) bg-(--panel) px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:border-[#D7DAE0] border-[rgba(229,72,77,0.4)] text-(--bad)"
            onClick={remove}
            disabled={busy}
          >
            Delete
          </button>
        </div>
      )}
    </div>
  );
};

/* -------------------------------------------------------------------------- */
/*  Main SecuritySection                                                      */
/* -------------------------------------------------------------------------- */
const SecuritySection: React.FC<SecuritySectionProps> = ({ settings }) => {
  const {
    isSignedIn,
    isBootLoading,
    currentPassword,
    setCurrentPassword,
    newPassword,
    setNewPassword,
    confirmPassword,
    setConfirmPassword,
    securityMessage,
    securityError,
    isSavingPassword,
    handleChangePassword,
    mfaEnabled,
    mfaSetup,
    mfaCode,
    setMfaCode,
    mfaMessage,
    mfaError,
    isPreparingMfa,
    isSubmittingMfa,
    handleGenerateMfaSetup,
    handleEnableMfa,
    handleDisableMfa,
  } = settings;

  const { getToken } = useAuth();

  // ---- Passkey state ----
  const [passkeys, setPasskeys] = useState<PasskeyListItem[]>([]);
  const [isLoadingPasskeys, setIsLoadingPasskeys] = useState(false);
  const [isAddingPasskey, setIsAddingPasskey] = useState(false);
  const [passkeyName, setPasskeyName] = useState("");
  const [showAddForm, setShowAddForm] = useState(false);
  const [passkeyMessage, setPasskeyMessage] = useState("");
  const [passkeyError, setPasskeyError] = useState("");

  const fetchPasskeys = useCallback(async () => {
    if (!isSignedIn) return;
    setIsLoadingPasskeys(true);
    try {
      const token = await getToken();
      if (!token) return;
      const list = await listPasskeys(token);
      setPasskeys(list);
    } catch {
      // silent
    } finally {
      setIsLoadingPasskeys(false);
    }
  }, [getToken, isSignedIn]);

  useEffect(() => {
    void fetchPasskeys();
  }, [fetchPasskeys]);

  const handleAddPasskey = async () => {
    setPasskeyMessage("");
    setPasskeyError("");
    setIsAddingPasskey(true);
    try {
      const token = await getToken();
      if (!token) throw new Error("Not authenticated");
      await registerPasskey(token, passkeyName.trim() || "My Passkey");
      setPasskeyMessage("Passkey registered successfully.");
      setPasskeyName("");
      setShowAddForm(false);
      await fetchPasskeys();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to register passkey.";
      if (
        msg.includes("cancelled") ||
        msg.includes("AbortError") ||
        msg.includes("NotAllowedError")
      ) {
        setPasskeyError("Passkey registration was cancelled.");
      } else {
        setPasskeyError(msg);
      }
    } finally {
      setIsAddingPasskey(false);
    }
  };

  const handleRenamePasskey = async (id: number, name: string) => {
    const token = await getToken();
    if (!token) return;
    await renamePasskey(token, id, name);
    await fetchPasskeys();
  };

  const handleDeletePasskey = async (id: number) => {
    const token = await getToken();
    if (!token) return;
    await deletePasskey(token, id);
    setPasskeys((prev) => prev.filter((p) => p.id !== id));
  };

  // ---- Linked sign-in identities (SIGV2-1257) ----
  const [microsoftIdentity, setMicrosoftIdentity] = useState<LinkedIdentityStatus | null>(null);
  const [showLinkForm, setShowLinkForm] = useState(false);
  const [linkPassword, setLinkPassword] = useState("");
  const [linkConfirmed, setLinkConfirmed] = useState(false);
  const [isLinking, setIsLinking] = useState(false);
  const [linkMessage, setLinkMessage] = useState("");
  const [linkError, setLinkError] = useState("");

  const fetchLinkedIdentities = useCallback(async () => {
    if (!isSignedIn) return;
    try {
      const token = await getToken();
      if (!token) return;
      const identities = await listLinkedIdentities(token);
      setMicrosoftIdentity(identities.find((entry) => entry.provider === "microsoft") ?? null);
    } catch {
      // Silent: a deployment without the provider configured, or an older
      // backend, simply offers no linking row rather than an error.
    }
  }, [getToken, isSignedIn]);

  useEffect(() => {
    void fetchLinkedIdentities();
  }, [fetchLinkedIdentities]);

  // The provider leg returns to this page, so the outcome is read from the
  // query string the backend set, not from the request that started it.
  useEffect(() => {
    const params = new URLSearchParams(window.location.search);
    const linked = params.get("linked");
    const failed = params.get("link_error");
    if (linked === "microsoft") {
      setLinkMessage("Microsoft sign-in is now connected to this account.");
    } else if (failed) {
      setLinkError(LINK_RETURN_MESSAGES[failed] ?? "Microsoft could not be connected.");
    }
  }, []);

  const handleStartMicrosoftLink = async () => {
    setLinkMessage("");
    setLinkError("");
    if (!linkConfirmed) {
      setLinkError("Confirm that you want to connect this Microsoft account.");
      return;
    }
    setIsLinking(true);
    try {
      const token = await getToken();
      if (!token) throw new Error("You must be signed in to connect a sign-in provider.");
      const { link_token, authorize_path } = await startIdentityLink(
        token,
        "microsoft",
        linkPassword
      );
      setLinkPassword("");
      // The provider leg is a full navigation to the backend origin, the same
      // route Microsoft sign-in already uses.
      window.location.assign(
        resolveBackendAuthUrl(`${authorize_path}?link_token=${encodeURIComponent(link_token)}`)
      );
    } catch (err) {
      setLinkError(err instanceof Error ? err.message : "Unable to connect Microsoft.");
    } finally {
      setIsLinking(false);
    }
  };

  // ---- Computed ----
  const mfaOrPasskeyEnabled = mfaEnabled || passkeys.length > 0;

  return (
    <div className="flex flex-col gap-4">
      {/* ── Change Password ── */}
      <div className="rounded-(--r) border border-(--line) bg-(--panel) px-[22px] py-[18px]">
        <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
          Change Password
        </h3>
        <p className="m-0 mb-[18px] text-[12.5px] leading-[1.5] text-(--t-3)">
          Update your account password. Use a strong, unique passphrase.
        </p>
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <div className="mb-4 last:mb-0">
            <label
              className="mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)"
              htmlFor="current-password"
            >
              Current password
            </label>
            <input
              id="current-password"
              className="field-focus-ring h-11 w-full rounded-[10px] border border-(--line) bg-(--paper) px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#C7CDD6] disabled:bg-(--line-2) disabled:text-(--t-3)"
              type="password"
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              placeholder="••••••••"
            />
          </div>
          <div className="mb-4 last:mb-0">
            <label
              className="mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)"
              htmlFor="new-password"
            >
              New password
            </label>
            <input
              id="new-password"
              className="field-focus-ring h-11 w-full rounded-[10px] border border-(--line) bg-(--paper) px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#C7CDD6] disabled:bg-(--line-2) disabled:text-(--t-3)"
              type="password"
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              placeholder="Minimum 8 characters"
            />
          </div>
          <div className="mb-4 last:mb-0">
            <label
              className="mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)"
              htmlFor="confirm-password"
            >
              Confirm new password
            </label>
            <input
              id="confirm-password"
              className="field-focus-ring h-11 w-full rounded-[10px] border border-(--line) bg-(--paper) px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#C7CDD6] disabled:bg-(--line-2) disabled:text-(--t-3)"
              type="password"
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              placeholder="Repeat new password"
            />
          </div>
        </div>
        <div className="mt-4 flex flex-wrap items-center justify-end gap-3">
          {securityMessage && (
            <span className="text-[13px] font-semibold text-(--good)">{securityMessage}</span>
          )}
          {securityError && (
            <span className="text-[13px] font-semibold text-(--bad)">{securityError}</span>
          )}
          <button
            type="button"
            className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-[10px] border border-(--ink) bg-(--ink) px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black"
            onClick={handleChangePassword}
            disabled={!isSignedIn || isBootLoading || isSavingPassword}
          >
            {isSavingPassword ? "Updating…" : "Update password"}
          </button>
        </div>
      </div>

      {/* ── Advanced Security ── */}
      <div className="rounded-(--r) border border-(--line) bg-(--panel) px-[22px] py-[18px]">
        <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
          Advanced Security
        </h3>
        <p className="m-0 mb-[18px] text-[12.5px] leading-[1.5] text-(--t-3)">
          Protect your account with TOTP and passkeys.{" "}
          {mfaOrPasskeyEnabled ? (
            <span className="rounded-[6px] bg-(--good-s) px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em] text-(--good)">
              Protected
            </span>
          ) : (
            <span className="rounded-[6px] bg-(--line-2) px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em] text-(--t-2)">
              Not configured
            </span>
          )}
        </p>

        {/* -- TOTP MFA -- */}
        <div className="flex items-center justify-between gap-4 border-t border-t-(--line-2) py-3.5 first:border-t-0 max-md:flex-wrap max-md:items-start max-md:[&>div]:min-w-0">
          <div>
            <div className="text-[13.5px] font-semibold">Authenticator app (TOTP)</div>
            <div className="mt-0.5 max-w-[560px] text-[12px] leading-[1.45] text-(--t-3)">
              Google Authenticator, 1Password, Authy
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3 sm:flex-none">
            <span
              className={cx(
                "rounded-[6px] px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]",
                mfaEnabled ? "bg-(--good-s) text-(--good)" : "bg-(--line-2) text-(--t-2)"
              )}
            >
              {mfaEnabled ? "On" : "Off"}
            </span>
            {!mfaEnabled && !mfaSetup && (
              <button
                type="button"
                className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-[10px] border border-(--line) bg-(--panel) px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:border-[#D7DAE0]"
                onClick={handleGenerateMfaSetup}
                disabled={!isSignedIn || isPreparingMfa}
              >
                {isPreparingMfa ? "Generating…" : "Set up authenticator"}
              </button>
            )}
          </div>
        </div>

        {/* MFA setup / disable expanded content */}
        {!mfaEnabled && mfaSetup && (
          <div className="grid min-w-0 grid-cols-1 gap-5 py-1 pb-2 md:grid-cols-[220px_minmax(0,1fr)]">
            <div className="flex items-center justify-center rounded-[12px] border border-(--line) bg-(--paper) p-3">
              <Image
                src={mfaSetup.qr_code_url}
                alt="MFA QR code"
                width={196}
                height={196}
                unoptimized
                className="h-[196px] w-[196px] rounded-lg bg-white p-2"
              />
            </div>
            <div className="flex flex-col gap-3">
              <p className="m-0 text-[12.5px] leading-[1.5] text-(--t-3)">
                Account: <b>{mfaSetup.account_name}</b>
              </p>
              <div className="mb-0">
                <label
                  className="mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)"
                  htmlFor="mfa-manual-setup-key"
                >
                  Manual setup key
                </label>
                <input
                  id="mfa-manual-setup-key"
                  className="field-focus-ring h-11 w-full rounded-[10px] border border-(--line) bg-(--paper) px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#C7CDD6] disabled:bg-(--line-2) disabled:text-(--t-3)"
                  value={mfaSetup.secret}
                  readOnly
                />
              </div>
              <div className="mb-0">
                <label
                  className="mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)"
                  htmlFor="mfa-authenticator-code"
                >
                  Authenticator code
                </label>
                <input
                  id="mfa-authenticator-code"
                  className="field-focus-ring h-11 w-full rounded-[10px] border border-(--line) bg-(--paper) px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#C7CDD6] disabled:bg-(--line-2) disabled:text-(--t-3)"
                  value={mfaCode}
                  onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                  placeholder="123456"
                  inputMode="numeric"
                  maxLength={6}
                />
              </div>
              <div className="flex flex-wrap gap-3">
                <button
                  type="button"
                  className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-[10px] border border-(--ink) bg-(--ink) px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black"
                  onClick={handleEnableMfa}
                  disabled={isSubmittingMfa}
                >
                  {isSubmittingMfa ? "Verifying…" : "Enable MFA"}
                </button>
                <button
                  type="button"
                  className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-[10px] border border-(--line) bg-(--panel) px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:border-[#D7DAE0]"
                  onClick={handleGenerateMfaSetup}
                  disabled={isPreparingMfa || isSubmittingMfa}
                >
                  Regenerate secret
                </button>
              </div>
            </div>
          </div>
        )}

        {mfaEnabled && (
          <div className="flex flex-wrap items-end gap-3">
            <div className="mb-0 min-w-[220px] flex-1">
              <label
                className="mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)"
                htmlFor="mfa-disable-code"
              >
                Authenticator code to disable
              </label>
              <input
                id="mfa-disable-code"
                className="field-focus-ring h-11 w-full rounded-[10px] border border-(--line) bg-(--paper) px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#C7CDD6] disabled:bg-(--line-2) disabled:text-(--t-3)"
                value={mfaCode}
                onChange={(e) => setMfaCode(e.target.value.replace(/\D/g, "").slice(0, 6))}
                placeholder="123456"
                inputMode="numeric"
                maxLength={6}
              />
            </div>
            <button
              type="button"
              className="inline-flex h-[38px] flex-none cursor-pointer items-center gap-2 rounded-[10px] border border-[rgba(229,72,77,0.4)] bg-(--panel) px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--bad) hover:border-[#D7DAE0]"
              onClick={handleDisableMfa}
              disabled={isSubmittingMfa}
            >
              {isSubmittingMfa ? "Disabling…" : "Disable MFA"}
            </button>
          </div>
        )}

        {mfaMessage && (
          <p className="mt-2 mb-0 text-[12.5px] leading-[1.5] text-(--good)">{mfaMessage}</p>
        )}
        {mfaError && (
          <p className="mt-2 mb-0 text-[12.5px] leading-[1.5] text-(--bad)">{mfaError}</p>
        )}

        {/* -- Passkeys -- */}
        <div className="flex items-center justify-between gap-4 border-t border-t-(--line-2) py-3.5 first:border-t-0 max-md:flex-wrap max-md:items-start max-md:[&>div]:min-w-0">
          <div>
            <div className="text-[13.5px] font-semibold">Passkeys</div>
            <div className="mt-0.5 max-w-[560px] text-[12px] leading-[1.45] text-(--t-3)">
              Touch ID, Face ID, Windows Hello, Security Keys.
              {passkeys.length === 0 &&
                " No passkeys registered yet. Add one to enable passwordless sign-in."}
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-3 sm:flex-none">
            {passkeys.length > 0 && (
              <span className="rounded-[6px] bg-(--good-s) px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em] text-(--good)">
                {passkeys.length} registered
              </span>
            )}
            {!showAddForm && (
              <button
                type="button"
                className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-[10px] border border-(--line) bg-(--panel) px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:border-[#D7DAE0]"
                onClick={() => setShowAddForm(true)}
                disabled={!isSignedIn}
              >
                Add Passkey
              </button>
            )}
          </div>
        </div>

        {/* Passkey list */}
        {isLoadingPasskeys ? (
          <p className="mt-1 mb-0 text-[12.5px] leading-[1.5] text-(--t-3)">Loading passkeys…</p>
        ) : (
          passkeys.length > 0 && (
            <div>
              {passkeys.map((pk) => (
                <PasskeyRow
                  key={pk.id}
                  pk={pk}
                  onRename={handleRenamePasskey}
                  onDelete={handleDeletePasskey}
                />
              ))}
            </div>
          )
        )}

        {/* Add passkey form */}
        {showAddForm && (
          <div className="mt-3 flex flex-wrap items-end gap-3">
            <div className="mb-0 min-w-[200px] flex-1">
              <label
                className="mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)"
                htmlFor="new-passkey-name"
              >
                Passkey name
              </label>
              <input
                id="new-passkey-name"
                className="field-focus-ring h-11 w-full rounded-[10px] border border-(--line) bg-(--paper) px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#C7CDD6] disabled:bg-(--line-2) disabled:text-(--t-3)"
                value={passkeyName}
                onChange={(e) => setPasskeyName(e.target.value)}
                placeholder="e.g. MacBook TouchID"
              />
            </div>
            <button
              type="button"
              className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-[10px] border border-(--ink) bg-(--ink) px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black"
              onClick={handleAddPasskey}
              disabled={isAddingPasskey}
            >
              {isAddingPasskey ? "Registering…" : "Register Passkey"}
            </button>
            <button
              type="button"
              className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-[10px] border border-(--line) bg-(--panel) px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:border-[#D7DAE0]"
              onClick={() => {
                setShowAddForm(false);
                setPasskeyName("");
                setPasskeyError("");
              }}
              disabled={isAddingPasskey}
            >
              Cancel
            </button>
          </div>
        )}

        {passkeyMessage && (
          <p className="mt-2 mb-0 text-[12.5px] leading-[1.5] text-(--good)">{passkeyMessage}</p>
        )}
        {passkeyError && (
          <p className="mt-2 mb-0 text-[12.5px] leading-[1.5] text-(--bad)">{passkeyError}</p>
        )}

        {/* -- Microsoft sign-in (SIGV2-1257). Only offered where the provider
             is actually configured, so a deployment without Microsoft SSO
             shows nothing rather than a dead affordance. -- */}
        {microsoftIdentity?.configured && (
          <>
            <div className="flex items-center justify-between gap-4 border-t border-t-(--line-2) py-3.5 first:border-t-0 max-md:flex-wrap max-md:items-start max-md:[&>div]:min-w-0">
              <div>
                <div className="text-[13.5px] font-semibold">Microsoft sign-in</div>
                <div className="mt-0.5 max-w-[560px] text-[12px] leading-[1.45] text-(--t-3)">
                  {microsoftIdentity.linked
                    ? "Connected. You can sign in to this account with Microsoft."
                    : "Connect your Microsoft account so you can sign in with it. You confirm your password first."}
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-3 sm:flex-none">
                <span
                  className={cx(
                    "rounded-[6px] px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]",
                    microsoftIdentity.linked
                      ? "bg-(--good-s) text-(--good)"
                      : "bg-(--line-2) text-(--t-2)"
                  )}
                >
                  {microsoftIdentity.linked ? "Connected" : "Not connected"}
                </span>
                {!microsoftIdentity.linked && !showLinkForm && (
                  <button
                    type="button"
                    className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-[10px] border border-(--line) bg-(--panel) px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:border-[#D7DAE0]"
                    onClick={() => setShowLinkForm(true)}
                    disabled={!isSignedIn}
                  >
                    Connect Microsoft
                  </button>
                )}
              </div>
            </div>

            {showLinkForm && !microsoftIdentity.linked && (
              <div className="flex flex-col gap-3 pb-2">
                <div className="mb-0 max-w-[360px]">
                  <label
                    className="mb-2 block font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.08em] text-(--t-3)"
                    htmlFor="microsoft-link-password"
                  >
                    Account password
                  </label>
                  <input
                    id="microsoft-link-password"
                    className="field-focus-ring h-11 w-full rounded-[10px] border border-(--line) bg-(--paper) px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] text-(--t-1) outline-none placeholder:text-(--t-3) focus:border-[#C7CDD6] disabled:bg-(--line-2) disabled:text-(--t-3)"
                    type="password"
                    value={linkPassword}
                    onChange={(e) => setLinkPassword(e.target.value)}
                    placeholder="••••••••"
                  />
                </div>
                <label className="flex max-w-[560px] items-start gap-2 text-[12.5px] leading-[1.5] text-(--t-3)">
                  <input
                    type="checkbox"
                    className="mt-0.5"
                    checked={linkConfirmed}
                    onChange={(e) => setLinkConfirmed(e.target.checked)}
                  />
                  <span>
                    I understand that whoever controls the Microsoft account I sign in with next
                    will be able to sign in to this Qiko Signal account.
                  </span>
                </label>
                <div className="flex flex-wrap gap-3">
                  <button
                    type="button"
                    className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-[10px] border border-(--ink) bg-(--ink) px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black"
                    onClick={handleStartMicrosoftLink}
                    disabled={isLinking || !linkPassword || !linkConfirmed}
                  >
                    {isLinking ? "Confirming…" : "Confirm and continue"}
                  </button>
                  <button
                    type="button"
                    className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-[10px] border border-(--line) bg-(--panel) px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:border-[#D7DAE0]"
                    onClick={() => {
                      setShowLinkForm(false);
                      setLinkPassword("");
                      setLinkConfirmed(false);
                      setLinkError("");
                    }}
                    disabled={isLinking}
                  >
                    Cancel
                  </button>
                </div>
              </div>
            )}
          </>
        )}

        {linkMessage && (
          <p className="mt-2 mb-0 text-[12.5px] leading-[1.5] text-(--good)">{linkMessage}</p>
        )}
        {linkError && (
          <p className="mt-2 mb-0 text-[12.5px] leading-[1.5] text-(--bad)">{linkError}</p>
        )}
      </div>
    </div>
  );
};

export default SecuritySection;
