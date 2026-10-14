"use client";

import { useState } from "react";
import { BASE_PATH } from "@/lib/basePath";

const EMAIL_RE = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;

type Status = "idle" | "loading" | "success" | "error";

export default function WaitlistForm() {
  const [status, setStatus] = useState<Status>("idle");
  const [error, setError] = useState<string | null>(null);
  const [fields, setFields] = useState({
    fname: "",
    company: "",
    email: "",
    website: "",
    hp: "",
  });

  const update = (key: keyof typeof fields) => (e: React.ChangeEvent<HTMLInputElement>) =>
    setFields((f) => ({ ...f, [key]: e.target.value }));

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    if (!fields.fname.trim()) {
      setError("Please enter your name.");
      return;
    }
    if (!EMAIL_RE.test(fields.email.trim())) {
      setError("Please enter a valid email address.");
      return;
    }
    if (!fields.website.trim()) {
      setError("Please enter your website or brand.");
      return;
    }
    setStatus("loading");
    try {
      const res = await fetch(`${BASE_PATH}/api/waitlist`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(fields),
      });
      if (!res.ok) {
        const data = (await res.json().catch(() => ({}))) as { error?: string };
        setError(data.error || "Something went wrong. Please try again.");
        setStatus("error");
        return;
      }
      setStatus("success");
    } catch {
      setError("Network error. Please check your connection and try again.");
      setStatus("error");
    }
  }

  if (status === "success") {
    return (
      <div className="px-0 pb-1 pt-5 text-center">
        <div className="mx-auto mb-[18px] grid h-14 w-14 place-items-center rounded-[50%] border border-[#1f4d3a] bg-[rgba(52,211,153,0.12)]">
          <svg width="26" height="26" viewBox="0 0 24 24" fill="none">
            <path
              d="M5 12.5l4 4 10-11"
              stroke="#34d399"
              strokeWidth="2.4"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </div>
        <h3 className="mb-2.5 text-2xl font-bold tracking-[-0.02em]">You are on the list.</h3>
        <p className="mx-auto max-w-[40ch] text-[15.5px] leading-[1.6] text-(--muted)">
          Thanks for your interest in Signal. We will be in touch at{" "}
          <span>{fields.email.trim()}</span> the moment it goes live.
        </p>
      </div>
    );
  }

  return (
    <div id="wl-form-view">
      <span className="font-(family-name:--mono) text-[12.5px] font-semibold uppercase tracking-[0.18em] text-(--eye)">
        Join the waitlist
      </span>
      <h2 className="my-3.5 text-[clamp(28px,3.6vw,42px)] font-bold leading-[1.08] tracking-[-0.025em]">
        Be first in when Signal goes live.
      </h2>
      <p className="mx-auto mb-[30px] max-w-[46ch] text-[17px] leading-[1.6] text-(--muted)">
        Leave your details and we will let you know the moment Signal is ready. Early sign-ups get
        first access.
      </p>
      <form className="flex flex-col gap-[14px] text-left" onSubmit={onSubmit} noValidate>
        <div className="grid grid-cols-2 gap-[14px] max-[780px]:grid-cols-1">
          <div>
            <label
              className="mb-2 block font-(family-name:--mono) text-[11px] uppercase tracking-[0.1em] text-(--muted-3)"
              htmlFor="wl-name"
            >
              Name
            </label>
            <input
              className="w-full rounded-[10px]! border! border-(--line)! bg-[#0c1626]! px-3.5! py-[13px]! text-[14.5px]! leading-[1.5]! text-(--ink)! outline-none transition-[border-color] placeholder:text-[#54627a] focus:border-(--blue)!"
              id="wl-name"
              name="name"
              type="text"
              placeholder="Jane Doe"
              autoComplete="name"
              required
              value={fields.fname}
              onChange={update("fname")}
            />
          </div>
          <div>
            <label
              className="mb-2 block font-(family-name:--mono) text-[11px] uppercase tracking-[0.1em] text-(--muted-3)"
              htmlFor="wl-company"
            >
              Company
            </label>
            <input
              className="w-full rounded-[10px]! border! border-(--line)! bg-[#0c1626]! px-3.5! py-[13px]! text-[14.5px]! leading-[1.5]! text-(--ink)! outline-none transition-[border-color] placeholder:text-[#54627a] focus:border-(--blue)!"
              id="wl-company"
              name="company"
              type="text"
              placeholder="Acme Inc."
              autoComplete="organization"
              value={fields.company}
              onChange={update("company")}
            />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-[14px] max-[780px]:grid-cols-1">
          <div>
            <label
              className="mb-2 block font-(family-name:--mono) text-[11px] uppercase tracking-[0.1em] text-(--muted-3)"
              htmlFor="wl-email"
            >
              Work email
            </label>
            <input
              className="w-full rounded-[10px]! border! border-(--line)! bg-[#0c1626]! px-3.5! py-[13px]! text-[14.5px]! leading-[1.5]! text-(--ink)! outline-none transition-[border-color] placeholder:text-[#54627a] focus:border-(--blue)!"
              id="wl-email"
              name="email"
              type="email"
              placeholder="you@company.com"
              autoComplete="email"
              required
              aria-invalid={Boolean(error)}
              value={fields.email}
              onChange={update("email")}
            />
          </div>
          <div>
            <label
              className="mb-2 block font-(family-name:--mono) text-[11px] uppercase tracking-[0.1em] text-(--muted-3)"
              htmlFor="wl-site"
            >
              Website or brand
            </label>
            <input
              className="w-full rounded-[10px]! border! border-(--line)! bg-[#0c1626]! px-3.5! py-[13px]! text-[14.5px]! leading-[1.5]! text-(--ink)! outline-none transition-[border-color] placeholder:text-[#54627a] focus:border-(--blue)!"
              id="wl-site"
              name="site"
              type="text"
              placeholder="signal-example.com"
              required
              value={fields.website}
              onChange={update("website")}
            />
          </div>
        </div>

        {/* Honeypot: hidden from users; bots that fill it are dropped server-side. */}
        <div className="absolute -left-[5000px] h-px w-px overflow-hidden" aria-hidden="true">
          <input
            className="p-0!"
            type="text"
            name="b_hp"
            tabIndex={-1}
            autoComplete="off"
            value={fields.hp}
            onChange={update("hp")}
          />
        </div>

        <button
          type="submit"
          className="inline-flex cursor-pointer items-center gap-2 whitespace-nowrap rounded-full rounded-[999px]! px-[26px] py-[15px] text-[15.5px] font-bold transition-[transform,box-shadow,background] focus-visible:outline-2 focus-visible:outline-offset-[3px] focus-visible:outline-(--cyan) text-white bg-(image:--grad) shadow-[0_14px_38px_-12px_rgba(79,143,247,0.75)] hover:-translate-y-px hover:shadow-[0_18px_44px_-12px_rgba(79,143,247,0.85)] mt-1.5 w-full justify-center border-none border-current"
          disabled={status === "loading"}
        >
          {status === "loading" ? "Joining…" : "Join the waitlist"}{" "}
          <span aria-hidden="true">→</span>
        </button>
        {error ? (
          <div className="mt-1 text-center text-[13px] text-[#fb7185]" role="alert">
            {error}
          </div>
        ) : null}
        <div className="mt-1 text-center text-[12.5px] text-(--faint)">
          We will only email you about Signal. No spam.
        </div>
      </form>
    </div>
  );
}
