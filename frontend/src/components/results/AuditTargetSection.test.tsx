import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import AuditTargetSection from "@/components/results/AuditTargetSection";
import { tEn } from "@/test/i18nEn";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: tEn }),
}));

const buildProps = (overrides: Record<string, unknown> = {}) => {
  const { auditForm: auditFormRaw, ...restOverrides } = overrides;
  const auditFormOverrides = (auditFormRaw ?? {}) as Record<string, any>;
  const auditForm = {
    setFormValue: vi.fn(),
    formErrors: {},
    isPreScanning: false,
    isPreflightChecking: false,
    runUrlAutoDetection: vi.fn(),
    preScanResult: null,
    preflightError: "",
    preflightVerifiedUrl: "",
    preScanError: "",
    ...auditFormOverrides,
    form: {
      auditTargetType: "website",
      url: "",
      targetUrl: "",
      targetName: "",
      tier: "fast",
      ...(auditFormOverrides.form ?? {}),
    },
  };
  return {
    auditForm,
    isStartDisabled: false,
    resolvedTargetUrl: "",
    cleanAuditError: (raw: string | null | undefined) => raw ?? "",
    ...restOverrides,
  };
};

describe("AuditTargetSection", () => {
  it("is the approved Target section: heading, its sentence, and all three fields", () => {
    render(<AuditTargetSection {...buildProps()} />);

    expect(screen.getByRole("heading", { name: "Target" })).toBeInTheDocument();
    expect(screen.getByText("What this audit measures.")).toBeInTheDocument();
    expect(screen.getByLabelText("URL")).toBeInTheDocument();
    expect(screen.getByLabelText("Name on the report")).toBeInTheDocument();
    expect(screen.getByText("How the target is labelled in the audit output.")).toBeInTheDocument();
  });

  it("has no Analyze control, which the approved design does not carry", () => {
    render(<AuditTargetSection {...buildProps()} />);

    expect(screen.queryByRole("button", { name: /analyze/i })).not.toBeInTheDocument();
  });

  it("explains each target type under the segmented control", () => {
    const { unmount } = render(<AuditTargetSection {...buildProps()} />);
    expect(screen.getByText("You have a web address you want checked.")).toBeInTheDocument();
    unmount();

    render(
      <AuditTargetSection {...buildProps({ auditForm: { form: { auditTargetType: "brand" } } })} />
    );
    expect(
      screen.getByText("You want the brand checked wherever it shows up online.")
    ).toBeInTheDocument();
  });

  it("switches the target type via the segmented control", () => {
    const props = buildProps();
    render(<AuditTargetSection {...props} />);

    expect(screen.getByRole("button", { name: "Website" })).toHaveAttribute("aria-pressed", "true");
    fireEvent.click(screen.getByRole("button", { name: "Brand" }));
    expect(props.auditForm.setFormValue).toHaveBeenCalledWith("auditTargetType", "brand");
  });

  it("keeps the name field on both target types", () => {
    render(
      <AuditTargetSection {...buildProps({ auditForm: { form: { auditTargetType: "brand" } } })} />
    );

    expect(screen.getByLabelText("Name on the report")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Brand" })).toHaveAttribute("aria-pressed", "true");
  });

  it("writes the address into both url fields", () => {
    const props = buildProps();
    render(<AuditTargetSection {...props} />);

    fireEvent.change(screen.getByLabelText("URL"), {
      target: { value: "https://example.com" },
    });
    expect(props.auditForm.setFormValue).toHaveBeenCalledWith("url", "https://example.com");
    expect(props.auditForm.setFormValue).toHaveBeenCalledWith("targetUrl", "https://example.com");
  });

  it("confirms reachability only for the address the preflight actually resolved", () => {
    const { unmount } = render(
      <AuditTargetSection
        {...buildProps({
          resolvedTargetUrl: "https://example.com",
          auditForm: {
            preflightVerifiedUrl: "https://example.com",
            form: { url: "https://example.com", targetUrl: "https://example.com" },
          },
        })}
      />
    );
    expect(screen.getByText("Address resolved - site is reachable.")).toBeInTheDocument();
    unmount();

    // The address moved on since the preflight: the claim is withdrawn.
    render(
      <AuditTargetSection
        {...buildProps({
          resolvedTargetUrl: "https://moved.example",
          auditForm: {
            preflightVerifiedUrl: "https://example.com",
            form: { url: "https://moved.example", targetUrl: "https://moved.example" },
          },
        })}
      />
    );
    expect(screen.queryByText("Address resolved - site is reachable.")).not.toBeInTheDocument();
  });

  it("reports an address that could not be resolved", () => {
    render(
      <AuditTargetSection
        {...buildProps({
          resolvedTargetUrl: "https://nope.example",
          auditForm: {
            preflightError: "URL preflight failed.",
            form: { url: "https://nope.example", targetUrl: "https://nope.example" },
          },
        })}
      />
    );

    expect(
      screen.getByText("Could not resolve that address - check it and try again.")
    ).toBeInTheDocument();
  });

  it("says it is checking while the preflight runs", () => {
    render(
      <AuditTargetSection
        {...buildProps({
          resolvedTargetUrl: "https://example.com",
          auditForm: {
            isPreflightChecking: true,
            form: { url: "https://example.com", targetUrl: "https://example.com" },
          },
        })}
      />
    );

    expect(screen.getByText("Checking the address...")).toBeInTheDocument();
  });

  it("shows the validation message in plain words", () => {
    render(
      <AuditTargetSection
        {...buildProps({
          auditForm: {
            formErrors: {
              url: { message: "Please enter a valid URL (e.g. https://example.com)." },
            },
          },
        })}
      />
    );

    expect(
      screen.getByText("Please enter a valid URL (e.g. https://example.com).")
    ).toBeInTheDocument();
  });

  /* SIGV2-1171: the unreadable-target block used to be a hand-rolled div with
     no role at all, its body in `--t-3` at 12px, so a screen reader never
     announced it and a sighted reader had to go looking for it. */
  it("announces an unreadable target as an alert", () => {
    render(
      <AuditTargetSection
        {...buildProps({
          resolvedTargetUrl: "https://nope.example",
          auditForm: {
            preflightError: "The site refused the connection.",
            form: { url: "https://nope.example", targetUrl: "https://nope.example" },
          },
        })}
      />
    );

    const alerts = screen.getAllByRole("alert");
    const block = alerts.find((node) => node.textContent?.includes("We could not read the site"));
    expect(block).toBeDefined();
    expect(block).toHaveTextContent("The site refused the connection.");
  });

  it("announces the field-level address failure too, in the tone's own colour", () => {
    render(
      <AuditTargetSection
        {...buildProps({
          resolvedTargetUrl: "https://nope.example",
          auditForm: {
            preflightError: "URL preflight failed.",
            form: { url: "https://nope.example", targetUrl: "https://nope.example" },
          },
        })}
      />
    );

    const note = screen.getByText("Could not resolve that address - check it and try again.")
      .parentElement as HTMLElement;
    expect(note).toHaveAttribute("data-signal-inline-note", "danger");
    expect(note).toHaveAttribute("role", "alert");
  });

  it("disables the fields while a run is in flight", () => {
    render(<AuditTargetSection {...buildProps({ isStartDisabled: true })} />);

    expect(screen.getByLabelText("URL")).toBeDisabled();
    expect(screen.getByLabelText("Name on the report")).toBeDisabled();
  });

  it("keeps the depth and plan detail out of the Target section", () => {
    render(<AuditTargetSection {...buildProps()} />);

    expect(screen.queryByText("How thorough")).not.toBeInTheDocument();
  });
});
