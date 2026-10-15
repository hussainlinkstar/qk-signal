"use client";

import React, { useMemo, useState } from "react";
import { Check, Mail, MessagesSquare } from "lucide-react";
import Button, { buttonClasses } from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";
import TextField from "@/components/ui/TextField";
import { BILLING_EMAIL } from "@/lib/contact";

const SALES_SUPPORT_BULLETS = [
  "Volume audit commitments with negotiated commercial terms",
  "Custom invoicing, purchase orders, and procurement support",
  "Dedicated onboarding and implementation planning",
  "Priority support expectations and operating cadence",
];

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
      <div className="relative mx-auto max-w-5xl overflow-hidden rounded-[22px] border-0 bg-white p-6">
        <div className="flex flex-col gap-6">
          <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
            <div className="max-w-2xl">
              <p className="text-xs font-medium uppercase tracking-wide text-(--t-3)">
                Enterprise Billing
              </p>
              <h2 className="mt-2 text-[22px] font-extrabold text-(--t-1)">Need a custom plan?</h2>
              <p className="mt-3 text-sm text-(--t-2)">
                Share your expected volume and billing requirements, then we will prepare the right
                commercial path for procurement-heavy or high-usage teams.
              </p>
            </div>
          </div>

          <div className="grid gap-3 md:grid-cols-2">
            {SALES_SUPPORT_BULLETS.map((item) => (
              <div key={item} className="flex items-start gap-2 text-sm text-(--t-2)">
                <Check className="mt-0.5 h-4 w-4 shrink-0 text-emerald-400" />
                <span>{item}</span>
              </div>
            ))}
          </div>

          <div className="flex flex-wrap gap-3">
            <Button onClick={() => setIsOpen(true)} variant="inverse" size="md">
              <MessagesSquare className="h-4 w-4" />
              Contact Sales
            </Button>
            <a
              href={`mailto:${BILLING_EMAIL}`}
              className={buttonClasses({ variant: "ghost", size: "md" })}
            >
              <Mail className="h-4 w-4" />
              Email Billing
            </a>
          </div>
        </div>
      </div>

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
            <a href={mailtoHref} className={buttonClasses({ variant: "primary", size: "md" })}>
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
