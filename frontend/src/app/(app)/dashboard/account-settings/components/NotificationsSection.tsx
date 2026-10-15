"use client";

import React from "react";
import { useAccountSettings } from "../useAccountSettings";
import { cx } from "@/components/ui/utils";

type NotificationsSectionProps = {
  settings: ReturnType<typeof useAccountSettings>;
};

const NotificationsSection: React.FC<NotificationsSectionProps> = ({ settings }) => {
  const {
    isSignedIn,
    isBootLoading,
    notificationsEnabled,
    setNotificationsEnabled,
    notifyProductUpdates,
    setNotifyProductUpdates,
    notifyAuditAlerts,
    setNotifyAuditAlerts,
    notifyBilling,
    setNotifyBilling,
    notificationMessage,
    notificationError,
    isSavingNotifications,
    handleSaveNotifications,
  } = settings;

  const controlsDisabled = isSavingNotifications || isBootLoading;
  const categoryDisabled = controlsDisabled || !notificationsEnabled;

  return (
    <div className="flex flex-col gap-4">
      <div className="rounded-[22px] border-0 bg-white px-[22px] py-[18px]">
        <h3 className="m-0 mb-[3px] font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]">
          Notifications
        </h3>
        <p className="m-0 mb-[18px] text-[12.5px] leading-[1.5] text-(--t-3)">
          Control how you receive product updates and audit signals.
        </p>

        <div className="flex items-center justify-between gap-4 border-t border-t-(--line-2) py-3.5 first:border-t-0 max-md:flex-wrap max-md:items-start max-md:[&>div]:min-w-0">
          <div>
            <div className="text-[13.5px] font-semibold">Email notifications</div>
            <div className="mt-0.5 max-w-[560px] text-[12px] leading-[1.45] text-(--t-3)">
              Master toggle for all non-transactional email notifications.
            </div>
          </div>
          <button
            type="button"
            className={cx(
              "relative h-6 w-[42px] flex-none cursor-pointer rounded-[999px]! border-none border-current",
              notificationsEnabled ? "bg-(--good)" : "bg-(--line)"
            )}
            onClick={() => setNotificationsEnabled(!notificationsEnabled)}
            disabled={controlsDisabled}
            aria-pressed={notificationsEnabled}
          >
            <i
              className={cx(
                "absolute top-[3px] h-[18px] w-[18px] rounded-[50%] bg-white transition-[left]",
                notificationsEnabled ? "left-[21px]" : "left-[3px]"
              )}
            />
          </button>
        </div>

        <div className="flex items-center justify-between gap-4 border-t border-t-(--line-2) py-3.5 first:border-t-0 max-md:flex-wrap max-md:items-start max-md:[&>div]:min-w-0">
          <div>
            <div className="text-[13.5px] font-semibold">Product updates</div>
            <div className="mt-0.5 max-w-[560px] text-[12px] leading-[1.45] text-(--t-3)">
              Release notes, report delivery, and account notices.
            </div>
          </div>
          <button
            type="button"
            className={cx(
              "relative h-6 w-[42px] flex-none cursor-pointer rounded-[999px]! border-none border-current",
              notifyProductUpdates ? "bg-(--good)" : "bg-(--line)"
            )}
            onClick={() => setNotifyProductUpdates(!notifyProductUpdates)}
            disabled={categoryDisabled}
            aria-pressed={notifyProductUpdates}
          >
            <i
              className={cx(
                "absolute top-[3px] h-[18px] w-[18px] rounded-[50%] bg-white transition-[left]",
                notifyProductUpdates ? "left-[21px]" : "left-[3px]"
              )}
            />
          </button>
        </div>

        <div className="flex items-center justify-between gap-4 border-t border-t-(--line-2) py-3.5 first:border-t-0 max-md:flex-wrap max-md:items-start max-md:[&>div]:min-w-0">
          <div>
            <div className="text-[13.5px] font-semibold">Audit &amp; monitoring alerts</div>
            <div className="mt-0.5 max-w-[560px] text-[12px] leading-[1.45] text-(--t-3)">
              Audit completion, visibility drops, and alert-rule triggers.
            </div>
          </div>
          <button
            type="button"
            className={cx(
              "relative h-6 w-[42px] flex-none cursor-pointer rounded-[999px]! border-none border-current",
              notifyAuditAlerts ? "bg-(--good)" : "bg-(--line)"
            )}
            onClick={() => setNotifyAuditAlerts(!notifyAuditAlerts)}
            disabled={categoryDisabled}
            aria-pressed={notifyAuditAlerts}
          >
            <i
              className={cx(
                "absolute top-[3px] h-[18px] w-[18px] rounded-[50%] bg-white transition-[left]",
                notifyAuditAlerts ? "left-[21px]" : "left-[3px]"
              )}
            />
          </button>
        </div>

        <div className="flex items-center justify-between gap-4 border-t border-t-(--line-2) py-3.5 first:border-t-0 max-md:flex-wrap max-md:items-start max-md:[&>div]:min-w-0">
          <div>
            <div className="text-[13.5px] font-semibold">Billing</div>
            <div className="mt-0.5 max-w-[560px] text-[12px] leading-[1.45] text-(--t-3)">
              Plan renewal notices, usage warnings, and invoice emails.
            </div>
          </div>
          <button
            type="button"
            className={cx(
              "relative h-6 w-[42px] flex-none cursor-pointer rounded-[999px]! border-none border-current",
              notifyBilling ? "bg-(--good)" : "bg-(--line)"
            )}
            onClick={() => setNotifyBilling(!notifyBilling)}
            disabled={categoryDisabled}
            aria-pressed={notifyBilling}
          >
            <i
              className={cx(
                "absolute top-[3px] h-[18px] w-[18px] rounded-[50%] bg-white transition-[left]",
                notifyBilling ? "left-[21px]" : "left-[3px]"
              )}
            />
          </button>
        </div>

        <div className="mt-[18px] flex items-center justify-end gap-3">
          {notificationMessage && (
            <span className="text-[13px] font-semibold text-(--good)">{notificationMessage}</span>
          )}
          {notificationError && (
            <span className="text-[13px] font-semibold text-(--bad)">{notificationError}</span>
          )}
          <button
            type="button"
            className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black"
            onClick={handleSaveNotifications}
            disabled={!isSignedIn || isBootLoading || isSavingNotifications}
          >
            {isSavingNotifications ? "Saving…" : "Save preferences"}
          </button>
        </div>
      </div>
    </div>
  );
};

export default NotificationsSection;
