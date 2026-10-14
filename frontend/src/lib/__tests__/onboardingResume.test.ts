import { afterEach, beforeEach, describe, expect, it } from "vitest";

import {
  ONBOARDING_RESUME_KEY,
  ONBOARDING_RESUME_TTL_MS,
  clearOnboardingResume,
  readOnboardingResume,
  recordOnboardingResume,
} from "@/lib/onboardingResume";

const write = (value: unknown) =>
  window.sessionStorage.setItem(ONBOARDING_RESUME_KEY, JSON.stringify(value));

describe("onboarding resume context", () => {
  beforeEach(() => {
    window.sessionStorage.clear();
  });

  afterEach(() => {
    window.sessionStorage.clear();
  });

  it("round-trips the workspace, project and step the wizard was on", () => {
    recordOnboardingResume({ workspaceId: 11, projectId: 42, step: 4 });

    expect(readOnboardingResume()).toEqual(
      expect.objectContaining({ workspaceId: 11, projectId: 42, step: 4 })
    );
  });

  it("returns null when nothing was recorded", () => {
    expect(readOnboardingResume()).toBeNull();
  });

  it("is consumed by clearing, so a later visit does not reopen the wizard", () => {
    recordOnboardingResume({ workspaceId: 11, projectId: 42, step: 4 });
    clearOnboardingResume();

    expect(readOnboardingResume()).toBeNull();
  });

  it("refuses a context recorded for a different workspace", () => {
    // SIGV2-1207's rule applied to the resume: a project belongs to the
    // workspace it was created in, so a context from another workspace is
    // dropped rather than resumed against whatever is active now.
    recordOnboardingResume({ workspaceId: 11, projectId: 42, step: 4 });

    expect(readOnboardingResume({ activeWorkspaceId: 9 })).toBeNull();
    expect(readOnboardingResume({ activeWorkspaceId: 11 })).not.toBeNull();
  });

  it("accepts any active workspace for a context recorded without one", () => {
    recordOnboardingResume({ workspaceId: null, projectId: 42, step: 4 });

    expect(readOnboardingResume({ activeWorkspaceId: 9 })).not.toBeNull();
  });

  it("expires a stale context instead of resuming an abandoned setup", () => {
    recordOnboardingResume({ workspaceId: 11, projectId: 42, step: 4 });

    expect(readOnboardingResume({ now: Date.now() + ONBOARDING_RESUME_TTL_MS + 1 })).toBeNull();
    // Dropped on the way out, so it cannot be read again.
    expect(window.sessionStorage.getItem(ONBOARDING_RESUME_KEY)).toBeNull();
  });

  it("refuses a context stamped in the future", () => {
    write({ workspaceId: 11, projectId: 42, step: 4, createdAt: Date.now() + 60_000 });

    expect(readOnboardingResume()).toBeNull();
  });

  it.each([
    ["unparseable", "not json"],
    ["a non-object", JSON.stringify(7)],
  ])("drops %s record", (_label, raw) => {
    window.sessionStorage.setItem(ONBOARDING_RESUME_KEY, raw);

    expect(readOnboardingResume()).toBeNull();
    expect(window.sessionStorage.getItem(ONBOARDING_RESUME_KEY)).toBeNull();
  });

  it.each([0, -1, 6, 2.5, Number.NaN, "4"])("drops the record for step %s", (step) => {
    write({ workspaceId: 11, projectId: 42, step, createdAt: Date.now() });

    expect(readOnboardingResume()).toBeNull();
  });

  it.each([0, -3, 1.5, "42"])("drops the record for project id %s", (projectId) => {
    write({ workspaceId: 11, projectId, step: 4, createdAt: Date.now() });

    expect(readOnboardingResume()).toBeNull();
  });

  it("keeps a context that names no project yet", () => {
    // Step 1 and 2 run before the project exists; a reload there still
    // resumes at the right step.
    recordOnboardingResume({ workspaceId: 11, projectId: null, step: 2 });

    expect(readOnboardingResume()).toEqual(expect.objectContaining({ projectId: null, step: 2 }));
  });

  it("records nothing for a step outside the wizard", () => {
    recordOnboardingResume({ workspaceId: 11, projectId: 42, step: 9 });

    expect(window.sessionStorage.getItem(ONBOARDING_RESUME_KEY)).toBeNull();
  });
});
