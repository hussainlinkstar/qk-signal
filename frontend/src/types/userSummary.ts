import type { TrialStatus } from "@/types/billing";

/**
 * Shape of `GET /api/users/me`. The dashboard shell needs the payload
 * (it reads the signed-in user's email), so the type lives here instead.
 */
export type UserSummary = {
  id: number;
  email: string;
  role: string;
  scans_used?: number;
  scans_remaining?: number | null;
  reset_at?: string | null;
  subscription: {
    plan_type: string;
    status: string;
    current_period_end: string | null;
    cancel_at_period_end: boolean;
  } | null;
  trial?: TrialStatus | null;
};
