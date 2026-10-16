"use client";

import React, { useMemo, useState } from "react";
import {
  Building2,
  Check,
  ClipboardList,
  Headphones,
  Mail,
  MessagesSquare,
  Receipt,
} from "lucide-react";
import Button, { buttonClasses } from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";
import TextField from "@/components/ui/TextField";
import { BILLING_EMAIL } from "@/lib/contact";
import { cx } from "@/components/ui/utils";

const SALES_SUPPORT_ITEMS = [
  {
    title: "Volume commitments",
    description: "Negotiated audit volume and commercial terms for high-usage teams.",
    icon: Building2,
  },
  {
    title: "Procurement ready",
    description: "Custom invoicing, purchase orders, and procurement support.",
    icon: Receipt,
  },
  {
    title: "Dedicated onboarding",
    description: "Implementation planning so your team is productive from day one.",
    icon: ClipboardList,
  },
  {
    title: "Priority support",
    description: "Clear operating cadence and faster response for enterprise accounts.",
    icon: Headphones,
  },
] as const;

const buildMailtoLink = (params: {
  companyName: string;
  monthlyAudits: string;
  requirements: string;
}) => {
  const subject = params.companyName
    ? `Custom billing inquiry - ${params.companyName}`
    : "Custom billing inquiry";
  const body = [
    "Hi billing team,",
    "",
    `Company: ${params.companyName || "Not provided"}`,
    `Estimated monthly audits: ${params.monthlyAudits || "Not provided"}`,
    "",
    "What we need:",
    params.requirements || "Please contact us to discuss custom pricing and billing options.",
  ].join("\n");

  return `mailto:${BILLING_EMAIL}?subject=${encodeURIComponent(subject)}&body=${encodeURIComponent(body)}`;
};

export default function BillingSalesContactCard() {
  const [isOpen, setIsOpen] = useState(false);
  const [companyName, setCompanyName] = useState("");
  const [monthlyAudits, setMonthlyAudits] = useState("");
  const [requirements, setRequirements] = useState("");

  const mailtoHref = useMemo(
    () => buildMailtoLink({ companyName, monthlyAudits, requirements }),
    [companyName, monthlyAudits, requirements]
  );

  return (
    <>
      <section className="w-full overflow-hidden rounded-[22px] border-0 bg-white shadow-[0_4px_24px_rgba(12,15,22,0.05)]">
        <div className="grid w-full lg:grid-cols-[minmax(0,0.95fr)_minmax(0,1.05fr)]">
          {/* CTA panel */}
          <div className="relative flex flex-col justify-between gap-8 bg-(--ink) px-6 py-8 text-white sm:px-9 sm:py-9">
            <div className="max-w-md">
              <div className="inline-flex items-center gap-2 rounded-full bg-white/10 px-3 py-1 text-[11px] font-semibold uppercase tracking-[0.08em] text-white/80">
                <span className="h-1.5 w-1.5 rounded-full bg-(--good)" aria-hidden="true" />
                Enterprise Billing
              </div>
              <h2 className="mt-4 font-(family-name:--disp) text-[28px] font-extrabold leading-[1.15] tracking-[-0.02em] text-white sm:text-[30px]">
                Need a custom plan?
              </h2>
              <p className="mt-3 text-[14.5px] leading-[1.55] text-white/75">
                Share your expected volume and billing requirements. We will prepare a commercial
                path for procurement-heavy or high-usage teams.
              </p>
              <p className="mt-4 text-[12.5px] text-white/55">Typical reply within 1–2 business days</p>
            </div>

            <div className="flex flex-wrap items-center gap-3">
              <Button
                onClick={() => setIsOpen(true)}
                variant="ghost"
                size="md"
                className="border-0 bg-white text-(--ink) hover:border-0 hover:bg-[#F3F4F6] hover:text-(--ink)"
              >
                <MessagesSquare className="h-4 w-4" />
                Contact Sales
              </Button>
              <a
                href={`mailto:${BILLING_EMAIL}`}
                className={cx(
                  buttonClasses({ variant: "ghost", size: "md" }),
                  "border border-white/25 bg-transparent text-white hover:border-white/40 hover:bg-white/10 hover:text-white"
                )}
              >
                <Mail className="h-4 w-4" />
                Email Billing
              </a>
            </div>
          </div>

          {/* Benefits */}
          <div className="bg-[#F7F8FA] px-6 py-8 sm:px-8 sm:py-9">
            <div className="mb-5 flex items-end justify-between gap-3">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.08em] text-(--t-3)">
                  What you get
                </p>
                <p className="mt-1 text-[13px] text-(--t-2)">Built for agencies and larger teams</p>
              </div>
            </div>
            <ul className="grid gap-3 sm:grid-cols-2">
              {SALES_SUPPORT_ITEMS.map((item) => {
                const Icon = item.icon;
                return (
                  <li
                    key={item.title}
                    className="flex h-full flex-col gap-3 rounded-[16px] border-0 bg-white p-4 transition-transform duration-150 hover:-translate-y-0.5"
                  >
                    <span className="flex h-9 w-9 items-center justify-center rounded-[10px] bg-[#EEF1F6] text-(--ink)">
                      <Icon className="h-4 w-4" strokeWidth={1.9} aria-hidden="true" />
                    </span>
                    <div>
                      <div className="flex items-center gap-2">
                        <Check
                          className="h-3.5 w-3.5 flex-none text-(--good)"
                          strokeWidth={2.5}
                          aria-hidden="true"
                        />
                        <p className="text-[13.5px] font-semibold text-(--t-1)">{item.title}</p>
                      </div>
                      <p className="mt-1.5 text-[12.5px] leading-[1.45] text-(--t-2)">
                        {item.description}
                      </p>
                    </div>
                  </li>
                );
              })}
            </ul>
          </div>
        </div>
      </section>

      <Modal
        open={isOpen}
        onClose={() => setIsOpen(false)}
        panelClassName="w-full max-w-2xl p-0"
        ariaLabelledby="sales-intake-heading"
      >
        <div className="border-b border-(--line) px-6 py-5">
          <p className="text-xs font-medium uppercase tracking-wide text-(--t-3)">Sales Intake</p>
          <h3 id="sales-intake-heading" className="mt-2 text-xl font-semibold text-(--t-1)">
            Tell us what you need
          </h3>
          <p className="mt-2 text-sm text-(--t-2)">
            We will open a pre-filled billing conversation with the details your team provides here.
          </p>
        </div>

        <div className="space-y-5 px-6 py-6">
          <div className="grid gap-4 md:grid-cols-2">
            <TextField
              id="company-name"
              label="Company name"
              placeholder="Example Agency"
              value={companyName}
              onChange={(event) => setCompanyName(event.target.value)}
            />
            <TextField
              id="monthly-audits"
              label="Monthly audits target"
              placeholder="500"
              inputMode="numeric"
              value={monthlyAudits}
              onChange={(event) => setMonthlyAudits(event.target.value)}
            />
          </div>

          <div className="space-y-1.5">
            <label
              htmlFor="billing-requirements"
              className="block text-sm font-medium text-(--t-2)"
            >
              Billing requirements
            </label>
            <textarea
              id="billing-requirements"
              rows={5}
              value={requirements}
              onChange={(event) => setRequirements(event.target.value)}
              placeholder="Describe procurement needs, invoice rules, onboarding expectations, or delivery constraints."
              className="w-full rounded-md border-0 bg-[#EEF1F6] px-4 py-3 text-sm text-(--t-1) placeholder:text-(--t-3) focus-visible:border-primary focus-visible:outline-hidden focus-visible:ring-1 focus-visible:ring-primary"
            />
          </div>

          <div className="rounded-md border-0 bg-[#EEF1F6] px-4 py-4 text-sm text-(--t-2)">
            The message draft will be sent to{" "}
            <span className="font-medium text-(--t-2)">{BILLING_EMAIL}</span>.
          </div>

          <div className="flex flex-wrap gap-3">
            <a href={mailtoHref} className={buttonClasses({ variant: "inverse", size: "md" })}>
              Open Email Draft
            </a>
            <Button variant="ghost" size="md" onClick={() => setIsOpen(false)}>
              Close
            </Button>
          </div>
        </div>
      </Modal>
    </>
  );
}
