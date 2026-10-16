"use client";

import React from "react";
import { useAccountSettings } from "../useAccountSettings";
import { cx } from "@/components/ui/utils";
import { formatInvoiceAmount, formatInvoiceDate } from "../utils";

type ProfileSectionProps = {
  settings: ReturnType<typeof useAccountSettings>;
};

const ProfileSection: React.FC<ProfileSectionProps> = ({ settings }) => {
  const {
    authLoading,
    isSignedIn,
    isBootLoading,
    profileName,
    setProfileName,
    profileEmail,
    profileRole,
    companyLegalName,
    setCompanyLegalName,
    companyRegistrationNumber,
    setCompanyRegistrationNumber,
    companyVatNumber,
    setCompanyVatNumber,
    billingEmail,
    setBillingEmail,
    billingPhone,
    setBillingPhone,
    billingAddressLine1,
    setBillingAddressLine1,
    billingAddressLine2,
    setBillingAddressLine2,
    billingCity,
    setBillingCity,
    billingState,
    setBillingState,
    billingPostalCode,
    setBillingPostalCode,
    billingCountry,
    setBillingCountry,
    billingWebsiteUrl,
    setBillingWebsiteUrl,
    billingTaxExempt,
    setBillingTaxExempt,
    stripeCustomerId,
    profileMessage,
    profileError,
    isSavingProfile,
    handleSaveProfile,
    recentInvoices,
    billingInfoError,
    isLoadingInvoices,
    loadInvoices,
  } = settings;

  const invoicesRefreshing = isBootLoading || isLoadingInvoices;

  const fieldLabelCls =
    "mb-2 block text-[11px] font-semibold uppercase tracking-[0.06em] text-(--t-3)";
  const fieldInputCls =
    "field-focus-ring h-11 w-full rounded-[14px] border-0 bg-[#EEF1F6] px-[13px] py-0 font-(family-name:--body-font) text-[13.5px] leading-none text-(--t-1) outline-none placeholder:text-(--t-3) focus:bg-white disabled:bg-(--line-2) disabled:text-(--t-3)";
  const cardCls = "rounded-[22px] border-0 bg-white px-6 py-6";
  const cardTitleCls =
    "m-0 mb-1 font-(family-name:--disp) text-[15px] font-bold tracking-[-0.01em]";
  const cardSubCls = "m-0 mb-6 text-[12.5px] leading-[1.5] text-(--t-3)";

  return (
    <div className="flex flex-col gap-5">
      {/* ── Identity ── */}
      <div className={cardCls}>
        <h3 className={cardTitleCls}>Identity</h3>
        <p className={cardSubCls}>Your account credentials and display name.</p>
        <div className="grid grid-cols-1 gap-x-6 gap-y-5 md:grid-cols-3">
          <div>
            <label className={fieldLabelCls} htmlFor="profile-display-name">
              Display name
            </label>
            <input
              id="profile-display-name"
              className={fieldInputCls}
              type="text"
              value={profileName}
              onChange={(e) => setProfileName(e.target.value)}
              placeholder="Your name or company"
            />
          </div>
          <div>
            <label className={fieldLabelCls} htmlFor="profile-email">
              Email
            </label>
            <input
              id="profile-email"
              className={fieldInputCls}
              type="text"
              value={profileEmail}
              readOnly
              disabled
            />
          </div>
          <div>
            <label className={fieldLabelCls} htmlFor="profile-role">
              Role
            </label>
            <input
              id="profile-role"
              className={fieldInputCls}
              type="text"
              value={profileRole}
              readOnly
              disabled
            />
          </div>
        </div>
      </div>

      {/* ── Company ── */}
      <div className={cardCls}>
        <h3 className={cardTitleCls}>Company</h3>
        <p className={cardSubCls}>Legal entity details for invoicing and compliance.</p>
        <div className="mb-5 grid grid-cols-1 gap-x-6 gap-y-5 md:grid-cols-2">
          <div>
            <label className={fieldLabelCls} htmlFor="company-legal-name">
              Legal company name
            </label>
            <input
              id="company-legal-name"
              className={fieldInputCls}
              type="text"
              value={companyLegalName}
              onChange={(e) => setCompanyLegalName(e.target.value)}
              placeholder="Acme Holdings SRL"
            />
          </div>
          <div>
            <label className={fieldLabelCls} htmlFor="company-registration-number">
              Registration number
            </label>
            <input
              id="company-registration-number"
              className={fieldInputCls}
              type="text"
              value={companyRegistrationNumber}
              onChange={(e) => setCompanyRegistrationNumber(e.target.value)}
              placeholder="J22/1234/2020"
            />
          </div>
        </div>
        <div className="mb-2 grid grid-cols-1 gap-x-6 gap-y-5 md:grid-cols-2">
          <div>
            <label className={fieldLabelCls} htmlFor="company-vat-number">
              VAT / tax number
            </label>
            <input
              id="company-vat-number"
              className={fieldInputCls}
              type="text"
              value={companyVatNumber}
              onChange={(e) => setCompanyVatNumber(e.target.value)}
              placeholder="RO12345678"
            />
          </div>
          <div>
            <label className={fieldLabelCls} htmlFor="stripe-customer-id">
              Stripe customer ID
            </label>
            <input
              id="stripe-customer-id"
              className={fieldInputCls}
              type="text"
              value={stripeCustomerId ?? "Not linked yet"}
              readOnly
              disabled
            />
          </div>
        </div>
        <div className="flex items-center justify-between gap-4 border-t border-t-(--line-2) py-3.5 first:border-t-0 max-md:flex-wrap max-md:items-start max-md:[&>div]:min-w-0">
          <div>
            <div id="billing-tax-exempt-label" className="text-[13.5px] font-semibold">
              Tax exempt
            </div>
            <div className="mt-0.5 max-w-[560px] text-[12px] leading-[1.45] text-(--t-3)">
              Mark this company as tax exempt for Stripe invoicing.
            </div>
          </div>
          <button
            type="button"
            role="switch"
            aria-labelledby="billing-tax-exempt-label"
            aria-label="Tax exempt"
            aria-checked={billingTaxExempt}
            className={cx(
              "relative h-6 w-[42px] flex-none cursor-pointer rounded-[999px]! border-none border-current",
              billingTaxExempt ? "bg-(--good)" : "bg-(--line)"
            )}
            onClick={() => setBillingTaxExempt(!billingTaxExempt)}
          >
            <i
              className={cx(
                "absolute top-[3px] h-[18px] w-[18px] rounded-[50%] bg-white transition-[left]",
                billingTaxExempt ? "left-[21px]" : "left-[3px]"
              )}
            />
          </button>
        </div>
      </div>

      {/* ── Billing Details ── */}
      <div className={cardCls}>
        <h3 className={cardTitleCls}>Billing Details</h3>
        <p className={cardSubCls}>Contact information and mailing address for invoices.</p>
        <div className="mb-5 grid grid-cols-1 gap-x-6 gap-y-5 md:grid-cols-3">
          <div>
            <label className={fieldLabelCls} htmlFor="billing-email">
              Billing email
            </label>
            <input
              id="billing-email"
              className={fieldInputCls}
              type="text"
              value={billingEmail}
              onChange={(e) => setBillingEmail(e.target.value)}
              placeholder="billing@company.com"
            />
          </div>
          <div>
            <label className={fieldLabelCls} htmlFor="billing-phone">
              Phone
            </label>
            <input
              id="billing-phone"
              className={fieldInputCls}
              type="text"
              value={billingPhone}
              onChange={(e) => setBillingPhone(e.target.value)}
              placeholder="+40 712 345 678"
            />
          </div>
          <div>
            <label className={fieldLabelCls} htmlFor="billing-website">
              Website
            </label>
            <input
              id="billing-website"
              className={fieldInputCls}
              type="text"
              value={billingWebsiteUrl}
              onChange={(e) => setBillingWebsiteUrl(e.target.value)}
              placeholder="https://company.example"
            />
          </div>
        </div>
        <div className="mb-5">
          <label className={fieldLabelCls} htmlFor="billing-address-line-1">
            Address line 1
          </label>
          <input
            id="billing-address-line-1"
            className={fieldInputCls}
            type="text"
            value={billingAddressLine1}
            onChange={(e) => setBillingAddressLine1(e.target.value)}
            placeholder="Street, number, suite"
          />
        </div>
        <div className="mb-5 grid grid-cols-1 gap-x-6 gap-y-5 md:grid-cols-2">
          <div>
            <label className={fieldLabelCls} htmlFor="billing-address-line-2">
              Address line 2
            </label>
            <input
              id="billing-address-line-2"
              className={fieldInputCls}
              type="text"
              value={billingAddressLine2}
              onChange={(e) => setBillingAddressLine2(e.target.value)}
              placeholder="Building, floor, department"
            />
          </div>
          <div>
            <label className={fieldLabelCls} htmlFor="billing-city">
              City
            </label>
            <input
              id="billing-city"
              className={fieldInputCls}
              type="text"
              value={billingCity}
              onChange={(e) => setBillingCity(e.target.value)}
              placeholder="Iasi"
            />
          </div>
        </div>
        <div className="grid grid-cols-1 gap-x-6 gap-y-5 md:grid-cols-3">
          <div>
            <label className={fieldLabelCls} htmlFor="billing-state">
              State / county
            </label>
            <input
              id="billing-state"
              className={fieldInputCls}
              type="text"
              value={billingState}
              onChange={(e) => setBillingState(e.target.value)}
              placeholder="Iasi"
            />
          </div>
          <div>
            <label className={fieldLabelCls} htmlFor="billing-postal-code">
              Postal code
            </label>
            <input
              id="billing-postal-code"
              className={fieldInputCls}
              type="text"
              value={billingPostalCode}
              onChange={(e) => setBillingPostalCode(e.target.value)}
              placeholder="700001"
            />
          </div>
          <div>
            <label className={fieldLabelCls} htmlFor="billing-country">
              Country (ISO2)
            </label>
            <input
              id="billing-country"
              className={fieldInputCls}
              type="text"
              value={billingCountry}
              onChange={(e) => setBillingCountry(e.target.value.toUpperCase())}
              placeholder="RO"
              maxLength={2}
            />
          </div>
        </div>
      </div>

      {/* ── Recent Invoices ── */}
      <div className="rounded-[22px] border-0 bg-white">
        <div className="flex flex-col items-stretch justify-between gap-4 px-6 pt-6 pb-4 sm:flex-row sm:items-center">
          <div>
            <h3 className={cardTitleCls}>Recent Invoices</h3>
            <p className="m-0 text-[12.5px] leading-[1.5] text-(--t-3)">
              Latest invoices synced from your Stripe billing profile.
            </p>
          </div>
          <button
            type="button"
            className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#EEF1F6] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-(--t-1) hover:bg-[#E8ECF3]"
            onClick={() => void loadInvoices()}
            disabled={invoicesRefreshing}
          >
            Refresh
          </button>
        </div>

        {billingInfoError && <p className="mx-6 my-0 text-(--bad)">{billingInfoError}</p>}

        <div
          className="max-md:max-w-full max-md:overflow-x-auto max-md:overscroll-x-contain max-md:[&>table]:min-w-[620px]"
          role="region"
          aria-label="Recent invoices"
          tabIndex={0}
        >
          {isLoadingInvoices ? (
            <table className="w-full border-collapse">
              <tbody>
                <tr>
                  <td className="px-4 py-[13px] text-center align-middle text-[13px] text-(--t-3)">
                    Loading invoices…
                  </td>
                </tr>
              </tbody>
            </table>
          ) : recentInvoices.length ? (
            <table className="w-full border-collapse">
              <thead>
                <tr>
                  <th className="border-b border-b-(--line) px-4 py-[11px] text-left font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)">
                    Date
                  </th>
                  <th className="border-b border-b-(--line) px-4 py-[11px] text-left font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)">
                    Status
                  </th>
                  <th className="border-b border-b-(--line) px-4 py-[11px] text-left font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)">
                    Paid
                  </th>
                  <th className="border-b border-b-(--line) px-4 py-[11px] text-left font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)">
                    Due
                  </th>
                  <th className="border-b border-b-(--line) px-4 py-[11px] text-left font-(family-name:--mono) text-[10px] font-normal uppercase tracking-[0.06em] text-(--t-3)">
                    Invoice
                  </th>
                </tr>
              </thead>
              <tbody className="[&>tr:last-child>td]:border-b-0">
                {recentInvoices.map((invoice, index) => (
                  <tr key={`${invoice.date}-${index}`}>
                    <td className="border-b border-b-(--line-2) px-4 py-[13px] align-middle text-[13px]">
                      {formatInvoiceDate(invoice.date)}
                    </td>
                    <td className="border-b border-b-(--line-2) px-4 py-[13px] align-middle text-[13px]">
                      <span
                        className={cx(
                          "rounded-[6px] px-2 py-[3px] font-(family-name:--mono) text-[10.5px] uppercase tracking-[0.04em]",
                          invoice.status === "paid"
                            ? "bg-(--good-s) text-(--good)"
                            : invoice.status === "open"
                              ? "bg-(--warn-s) text-(--warn)"
                              : "bg-(--line-2) text-(--t-2)"
                        )}
                      >
                        {invoice.status}
                      </span>
                    </td>
                    <td className="border-b border-b-(--line-2) px-4 py-[13px] align-middle text-[13px]">
                      {formatInvoiceAmount(invoice.amounts.amount_paid, invoice.currency)}
                    </td>
                    <td className="border-b border-b-(--line-2) px-4 py-[13px] align-middle text-[13px]">
                      {formatInvoiceAmount(invoice.amounts.amount_due, invoice.currency)}
                    </td>
                    <td className="border-b border-b-(--line-2) px-4 py-[13px] align-middle text-[13px]">
                      {invoice.hosted_invoice_url ? (
                        <a
                          href={invoice.hosted_invoice_url}
                          target="_blank"
                          rel="noreferrer"
                          className="font-semibold text-(--purple)"
                        >
                          View
                        </a>
                      ) : invoice.invoice_pdf ? (
                        <a
                          href={invoice.invoice_pdf}
                          target="_blank"
                          rel="noreferrer"
                          className="font-semibold text-(--purple)"
                        >
                          PDF
                        </a>
                      ) : (
                        <span className="text-(--t-3)">N/A</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          ) : billingInfoError ? null : (
            <table className="w-full border-collapse">
              <tbody>
                <tr>
                  <td className="px-4 py-[13px] text-center align-middle text-[13px] text-(--t-3)">
                    No invoices yet. Once billing is active, they will appear here.
                  </td>
                </tr>
              </tbody>
            </table>
          )}
        </div>
      </div>

      {/* ── Save ── */}
      <div className="flex flex-wrap items-center justify-end gap-3">
        {profileMessage && (
          <span className="text-[13px] font-semibold text-(--good)">{profileMessage}</span>
        )}
        {profileError && (
          <span className="text-[13px] font-semibold text-(--bad)">{profileError}</span>
        )}
        <button
          type="button"
          className="inline-flex h-[38px] cursor-pointer items-center gap-2 rounded-full border-0 bg-[#111827] px-[15px] py-0 font-(family-name:--body-font) text-[13.5px] font-semibold text-white hover:bg-black"
          onClick={handleSaveProfile}
          disabled={authLoading || !isSignedIn || isBootLoading || isSavingProfile}
        >
          {isSavingProfile ? "Saving…" : "Save profile"}
        </button>
      </div>
    </div>
  );
};

export default ProfileSection;
