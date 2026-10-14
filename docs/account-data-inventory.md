# Account Data Inventory — Export and Deletion (SIGV2-1013)

Scope: `GET /api/v1/users/me/data-export` and `DELETE /api/v1/users/me`
(`backend/routers/api_router.py`). This document records what each category
contains, what export covers, what deletion does, and where the two do not
match. It is the basis for the retention decision that follows; it does not
claim regulatory compliance.

## Deletion policy (current)

Deletion is immediate inside a single database transaction; any failure rolls
back and the request can be retried. There is no scheduled deletion, grace
period or cancellation flow, and no surface promises one.

- **Owned workspace with other members:** deletion is refused with HTTP 409 and
  `code = "workspace_ownership_transfer_required"`. Nothing is deleted.
  `workspaces.owner_id` is `ON DELETE CASCADE`, so without this check deleting
  an owner would destroy every other member's workspace data.
- **Owned workspace, sole member:** proceeds; the workspace and its dependents
  are removed by cascade.
- **Workspaces where the user is a member but not owner:** only their
  `WorkspaceUser` row is removed. Other members' data is not touched.
- **Active subscription:** refused with HTTP 409 and
  `code = "active_subscription_cancellation_required"` while a subscription is
  `active`, `trialing`, `past_due` or `unpaid` and not already set to cancel at
  period end. This prevents silently abandoning a paying subscription.

## Inventory by category

| Category | Export covers | Deletion does today | Mismatch / risk |
|---|---|---|---|
| **User record** (`users`): email, role, credits, notification flag, company/billing profile fields | Yes: identity fields plus `company_profile` block | Row deleted | None |
| **User-only records**: `Audit` rows (with normalized `full_report`), `EmailOutbox`, `UserCreditAdjustment`, `AdminActionLog` | Yes | Hard-deleted (`Audit`, `EmailOutbox`, own `UserCreditAdjustment`); `admin_user_id` anonymized to `NULL` on logs where the user was the acting admin | Audit artifacts live only as `audits.full_report` JSON; report files in S3 (`report_archive_uri`) are not exported or enumerated |
| **Owned workspaces** (`workspaces` + ~18 dependent tables: projects, memberships, data sources, OAuth/Slack/Teams/Jira/CMS connections, embed keys, leads, workflows, custom domains, credit budget) | Summary only (`workspaces[]`: id, name, role, is_owner) | Sole-member: full cascade deletion. Shared: refused until ownership is resolved | Export lists workspaces but not their contents (projects, audits inside shared workspaces belong to the workspace, not the user) |
| **Memberships in others' workspaces** (`workspace_users`) | `workspaces[]` entries with `is_owner: false` | Membership row removed; rest of workspace untouched | None |
| **Audit and report artifacts** | `audits[]` with full report | User-scoped `Audit` rows deleted; workspace-scoped audit history in shared workspaces is not | Report PDFs/archives in object storage are outside both export and deletion |
| **Connected authorizations**: `OAuthConnection` (workspace-scoped), `ProjectOAuthConnection` (per-project, `connected_by_email`), `JiraConnection`, `SlackConnection`, `TeamsConnection`, `CMSConnection`, `MagicLink` | Not enumerated | `OAuthConnection` is left untouched on shared workspaces and cascade-deleted only with sole-member owned workspaces; `ProjectOAuthConnection` is deleted where `connected_by_email` matches, degrading its data source via `ON DELETE SET NULL` | **Open item — `OAuthConnection` has no attribution.** The table is `UniqueConstraint(workspace_id, provider)`: one shared row per provider holding an access and a refresh token, with no `user_id`/`created_by`. When a member leaves we cannot remove their credentials without destroying the workspace's only integration for that provider. Consequence: a departing member's provider tokens remain inside the workspace connection until an owner reconnects or disconnects it. Closing this needs a `created_by` on the table plus a per-user reconnect flow — a follow-up ticket. Jira/Slack/Teams/CMS credentials are likewise workspace-owned and un-attributable |
| **Sessions and tokens**: `UserSession` (refresh/session JTI), `ApiKey`, `EmbedApiKey`, password reset / magic links | Not enumerated | `user_sessions` and `api_keys` cascade with the user; each session JTI is also added to the Redis revocation denylist (`session:revoked:`) so in-flight access tokens stop working immediately | Redis revocation is best-effort; an outage logs an error and still returns success (user and session rows are gone, refresh is dead) |
| **Subscription state** (`subscriptions`) | `subscription` block incl. Stripe ids | Row deleted — but refused while a blocking (non-cancelling) active status exists | No Stripe API call is made; an already `cancel_at_period_end` subscription is left for Stripe to terminate |
| **Accounting records** (`billing_payments`) | Yes: invoice ids, amounts, hosted URLs, PDF links | **Hard-deleted.** Preserved deliberately per the ticket's dependency: changing this to retention (dangling `user_id` or `SET NULL`) requires the approved retention policy and record-of-truth classification first. Risk: payment and invoice history for the account is destroyed rather than retained, which financial-record obligations may not permit. Flagged for the retention decision, unchanged for now | ⚠ **Retention risk — decision pending** |

## Export authorization and minimisation

- Both endpoints require `get_current_user` and operate only on the
  authenticated user's own rows; there is no user-id parameter.
- Export returns only records keyed to `user_id`/`admin_user_id` plus the
  workspace summaries listed above. Stripe identifiers are included because
  they identify the user's own customer/subscription records.
- `audits[].full_report` passes through `build_normalized_audit_report` with
  the caller's current plan, matching what the app itself exposes.

## Known residual items (not covered by either endpoint)

- Redis-cached audit/job data keyed by user — expires on its own TTL.
- S3/object-storage report archives (`report_archive_uri`) — lifecycle policy.
- `AdminActionLog` entries where the user is the *target* rather than the actor.
- Workspace-level data in shared workspaces the user left (activity logs,
  invitations, API-key usage records attributed by workspace).
