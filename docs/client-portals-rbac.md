# Client Portals & Advanced RBAC

## Scope

This document defines the implementation for `TASK-01-STX-02-client-portals-advanced-rbac`.

Goals:
- add a workspace-scoped `CLIENT_READONLY` role
- restrict client users to explicitly assigned projects
- expose a dedicated read-only portal surface with white-label branding
- keep agency dashboard, billing, audit execution, and internal settings inaccessible to client users

Non-goals for the first slice:
- full Jira workflow state sync from Atlassian
- multi-workspace portal switching UX beyond a deterministic default workspace

## Decisions

### 1. Role model

`WorkspaceRole` gains `CLIENT_READONLY`.

This role is:
- read-only
- project-scoped
- blocked from the existing agency dashboard and sensitive APIs
- allowed only through dedicated `/portal/*` endpoints and routes

### 2. Project scoping model

Use a normalized junction table:

`workspace_user_project_access`
- `id`
- `workspace_user_id -> workspace_users.id`
- `project_id -> projects.id`
- `created_at`

Why this over JSON on `workspace_users`:
- enforces referential integrity
- supports indexed filtering by project and member
- keeps future RBAC expansion possible for more scoped roles
- avoids full-row JSON rewrites on every project assignment change

### 3. Jira task visibility model

Portal task views require backend persistence. Existing Jira export state is tracked only in frontend local storage, which is not portable or safe for client portals.

Add:

`project_jira_exports`
- `id`
- `project_id -> projects.id`
- `audit_id -> audits.id` nullable
- `created_by_user_id -> users.id`
- `jira_project_key`
- `issue_id`
- `issue_key`
- `issue_url`
- `title`
- `issue_type`
- `status_name` default `"Exported"`
- `created_at`

This stores the last known exported state. Live Jira workflow sync is optional later.

### 4. Auth context model

Access tokens gain lightweight portal claims:
- `portal_only: bool`
- `portal_workspace_id: int | null`

These claims are derived from DB memberships when tokens are minted:
- `portal_only = true` only when the user owns no workspace and all workspace memberships are `CLIENT_READONLY`
- `portal_workspace_id` is populated when there is exactly one client workspace, otherwise `null`

These claims are used only for frontend/middleware routing. Backend enforcement still resolves membership state from the database on every protected request.

## Data model

```text
users
  1 ───< workspace_users >─── 1 workspaces
            |
            | 1
            v
  workspace_user_project_access
            ^
            | many
            |
         projects
            |
            | 1
            v
    project_jira_exports
```

Rules:
- only `CLIENT_READONLY` memberships may have rows in `workspace_user_project_access`
- every assigned project must belong to the same workspace as the membership
- project access is deny-by-default for client users

## Security boundary map

### Agency-only surfaces

Blocked for `CLIENT_READONLY`:
- `/dashboard/**`
- `/api/v1/workspaces/**`
- `/api/v1/projects/**`
- `/api/v1/billing/**`
- `/api/v1/users/me`
- `/api/v1/users/me/profile`
- `/api/v1/integrations/jira/**`
- audit creation / mutation endpoints
- workspace member endpoints
- workspace OAuth and settings endpoints

### Portal-only surfaces

Allowed for `CLIENT_READONLY`:
- `/portal`
- `/portal/projects/[projectId]`
- `/api/v1/portal/branding`
- `/api/v1/portal/projects`
- `/api/v1/portal/projects/{id}/dashboard`
- `/api/v1/portal/projects/{id}/tasks`

### Routing enforcement

Frontend:
- Next middleware decodes JWT payload from the auth cookie
- `portal_only=true` users are redirected away from `/dashboard/**` to `/portal`
- non-portal authenticated users are redirected away from `/portal/**` to `/dashboard`

Backend:
- default workspace/project access helpers reject `CLIENT_READONLY`
- portal router uses explicit allow-list helpers that also enforce project assignment
- sensitive user/billing endpoints reject `portal_only` users even if they bypass the frontend

## API contract

### Invitation

`POST /api/v1/workspaces/{workspace_id}/invite-client`

Request:

```json
{
  "email": "client@example.com",
  "name": "Acme Stakeholder",
  "project_ids": [12, 13]
}
```

Behavior:
- requires workspace write access
- validates projects belong to the target workspace
- if user does not exist, creates a local user with a random password hash
- creates or updates `workspace_users` with `CLIENT_READONLY`
- replaces project assignments in `workspace_user_project_access`
- sends an invitation email with a password-set/reset link

Response:

```json
{
  "user_id": 42,
  "email": "client@example.com",
  "role": "CLIENT_READONLY",
  "project_ids": [12, 13],
  "invited": true
}
```

### Portal branding

`GET /api/v1/portal/branding`

Response:

```json
{
  "workspace_id": 3,
  "workspace_name": "Acme Workspace",
  "agency_name": "Pixel Artisan",
  "custom_logo_url": "https://...",
  "primary_color": "#0EA5A4",
  "secondary_color": "#1D4ED8"
}
```

### Portal project list

`GET /api/v1/portal/projects`

Response:

```json
[
  {
    "id": 12,
    "workspace_id": 3,
    "name": "Acme EU",
    "domain_url": "https://acme.example",
    "latest_seo_score": 72,
    "latest_geo_score": 68,
    "latest_aeo_score": 70,
    "last_audit_at": "2026-03-02T12:00:00Z"
  }
]
```

### Portal project dashboard

`GET /api/v1/portal/projects/{project_id}/dashboard`

Response:

```json
{
  "project": {
    "id": 12,
    "name": "Acme EU",
    "domain_url": "https://acme.example"
  },
  "latest_audit": {
    "id": 991,
    "created_at": "2026-03-02T12:00:00Z",
    "status": "completed",
    "seo_score": 72,
    "geo_score": 68,
    "aeo_score": 70,
    "summary": "..."
  },
  "trends": [
    {
      "created_at": "2026-02-02T12:00:00Z",
      "seo_score": 64,
      "geo_score": 58,
      "aeo_score": 60
    }
  ],
  "recommendations": [
    {
      "title": "Improve FAQ coverage",
      "description": "..."
    }
  ]
}
```

Excluded by design:
- credit data
- audit configuration
- model selection
- raw internal notes
- workspace membership

### Portal tasks

`GET /api/v1/portal/projects/{project_id}/tasks`

Response:

```json
[
  {
    "id": 11,
    "issue_key": "SYN-7",
    "issue_url": "https://example.atlassian.net/browse/SYN-7",
    "title": "Improve FAQ coverage",
    "issue_type": "Task",
    "status_name": "Exported",
    "created_at": "2026-03-02T12:05:00Z"
  }
]
```

## Frontend route plan

Add a dedicated route group:

```text
src/app/(portal)/portal/layout.tsx
src/app/(portal)/portal/page.tsx
src/app/(portal)/portal/projects/[projectId]/page.tsx
```

Behavior:
- agency users manage portal invitations from `src/app/(app)/dashboard/settings/page.tsx`
- if outbound mail is disabled, the settings UI shows the generated onboarding link for manual sharing
- portal layout fetches branding and project list
- minimal navigation: branding header, assigned projects, sign out
- project page shows:
  - SEO/GEO/AEO score cards
  - trend timeline/chart
  - latest recommendations
  - Jira exported tasks

No portal page may render:
- billing links
- credit counters
- plan badges
- audit run actions
- workspace settings
- member management

## Backend enforcement plan

1. extend `WorkspaceRole`
2. add project access + Jira export persistence tables
3. change default workspace/project resolvers to deny `CLIENT_READONLY`
4. add explicit portal resolvers that enforce assignment rows
5. persist Jira export rows at export time
6. reject `portal_only` users from billing and sensitive user summary endpoints
7. expose invitation + portal endpoints

## Testing plan

Backend:
- invite new client user into selected projects
- invite existing user and replace project assignments
- client user denied from current workspace/project endpoints
- client user denied from billing endpoints
- portal endpoints return only assigned projects
- portal endpoints reject non-assigned project IDs
- Jira export persistence is created when exporting a project recommendation

Frontend:
- middleware redirects `portal_only` users from `/dashboard` to `/portal`
- middleware redirects agency users away from `/portal`
- portal page renders branding + assigned projects only
