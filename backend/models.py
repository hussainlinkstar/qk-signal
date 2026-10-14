from enum import Enum as PyEnum

from sqlalchemy import (
    Column,
    Integer,
    BigInteger,
    String,
    Table,
    ForeignKey,
    DateTime,
    JSON,
    Float,
    Boolean,
    Text,
    Index,
    Date,
    UniqueConstraint,
    Enum,
    CheckConstraint,
    Numeric,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import relationship, validates
from sqlalchemy.sql import func

from app.config.plans import (
    CANONICAL_PLAN_TYPES,
    resolve_entitled_subscription_plan,
    resolve_plan_alias,
)
from core.encrypted_types import EncryptedText
from database import Base


site_competitors = Table(
    "site_competitors",
    Base.metadata,
    Column("site_id", Integer, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False),
    Column(
        "competitor_site_id",
        Integer,
        ForeignKey("sites.id", ondelete="CASCADE"),
        nullable=False,
    ),
    UniqueConstraint("site_id", "competitor_site_id", name="uq_site_competitors_pair"),
    Index("ix_site_competitors_site_id", "site_id"),
    Index("ix_site_competitors_competitor_site_id", "competitor_site_id"),
)


admin_alert_rule_channels = Table(
    "admin_alert_rule_channels",
    Base.metadata,
    Column(
        "rule_id",
        Integer,
        ForeignKey("admin_alert_rules.id", ondelete="CASCADE"),
        nullable=False,
    ),
    Column(
        "channel_id",
        Integer,
        ForeignKey("admin_notification_channels.id", ondelete="CASCADE"),
        nullable=False,
    ),
    UniqueConstraint("rule_id", "channel_id", name="uq_admin_alert_rule_channels_rule_channel"),
    Index("ix_admin_alert_rule_channels_rule_id", "rule_id"),
    Index("ix_admin_alert_rule_channels_channel_id", "channel_id"),
)


# SQLite is used heavily in tests; use JSON arrays there while keeping PostgreSQL ARRAY in production.
StringArrayType = ARRAY(String()).with_variant(JSON(), "sqlite")


class WorkspaceRole(str, PyEnum):
    ADMIN = "ADMIN"
    MANAGER = "MANAGER"
    EDITOR = "EDITOR"
    VIEWER = "VIEWER"
    CLIENT_READONLY = "CLIENT_READONLY"


class OAuthProvider(str, PyEnum):
    GOOGLE = "google"
    BING = "bing"
    JIRA = "jira"
    SLACK = "slack"


class AuditType(str, PyEnum):
    FAST = "FAST"
    SMART = "SMART"
    STANDARD = "STANDARD"
    DEEP = "DEEP"


class AuditTargetType(str, PyEnum):
    WEBSITE = "website"
    BRAND = "brand"


# SIGV2-1117: whose target an audit measures, relative to ``Audit.project_id``.
#
# A competitor benchmark is stored under the customer's own ``project_id`` so the
# work stays attributable and billable to that project. That linkage alone cannot
# tell a project's own measurement apart from a competitor's, and inferring the
# difference from a competitor snapshot fails open: an audit with no snapshot, or
# whose snapshot was removed with the competitor, reads back as the project's own.
#
# ``Audit.project_scope`` records the distinction on the audit row itself so a
# project's own history is selected positively. A row that is not proven to be
# the project's own is not counted as the project's.
AUDIT_PROJECT_SCOPE_OWN = "project"
AUDIT_PROJECT_SCOPE_COMPETITOR = "competitor"
AUDIT_PROJECT_SCOPES = (AUDIT_PROJECT_SCOPE_OWN, AUDIT_PROJECT_SCOPE_COMPETITOR)


# SIGV2-1129: who the scan belongs to, for the customer-facing scan allowance.
#
# The allowance is counted over ``audit_jobs`` at acceptance, before the
# ``audits`` row the worker will write exists, so ``Audit.project_scope`` is not
# reachable from the row being counted. The job carries its own declaration, in
# the same positive shape (SIGV2-1121): the allowance bills what is declared to
# be the customer's scan, and a job that declares nothing is not billed.
#
# This answers a different question from ``project_scope``, which is about score
# attribution. A competitor lite audit a customer asks for through the API is
# ``competitor`` for attribution and ``customer`` for billing: they launched it,
# so it is one of their scans. Keying billing on ``competitor`` alone would let
# any Specialist caller mark every audit as a competitor lite audit through the
# client-supplied ``category`` and never consume a scan.
SCAN_ORIGIN_CUSTOMER = "customer"
SCAN_ORIGIN_COMPETITOR_REFRESH = "competitor_refresh"
SCAN_ORIGINS = (SCAN_ORIGIN_CUSTOMER, SCAN_ORIGIN_COMPETITOR_REFRESH)


class ScheduledAuditFrequency(str, PyEnum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ScheduledAuditPauseReason(str, PyEnum):
    INSUFFICIENT_CREDITS = "insufficient_credits"
    BUDGET_EXCEEDED = "budget_exceeded"
    PLAN_RESTRICTED = "plan_restricted"
    MANUAL = "manual"


class ScheduledAuditRunStatus(str, PyEnum):
    QUEUED = "queued"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    PAUSED = "paused"


class ProjectDataSourceType(str, PyEnum):
    GOOGLE_SEARCH_CONSOLE = "google_search_console"
    GOOGLE_ANALYTICS_4 = "google_analytics_4"
    BING_WEBMASTER = "bing_webmaster"


class BotLogIngestionSourceType(str, PyEnum):
    MANUAL_UPLOAD = "manual_upload"
    CLOUDFLARE_LOGPUSH = "cloudflare_logpush"
    AWS_S3 = "aws_s3"
    GCP_CLOUD_STORAGE = "gcp_cloud_storage"


class ProjectDataSourceBindingMode(str, PyEnum):
    WORKSPACE = "workspace"
    CLIENT_MAGIC_LINK = "client_magic_link"
    AI_ESTIMATE = "ai_estimate"


class CompetitiveDigestFrequency(str, PyEnum):
    OFF = "off"
    WEEKLY = "weekly"
    MONTHLY = "monthly"


class ProjectTaskStatus(str, PyEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    DONE = "done"


class ProjectTaskPriority(str, PyEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ProjectTaskOrigin(str, PyEnum):
    MANUAL = "manual"
    AUDIT_RECOMMENDATION = "audit_recommendation"


class ProjectTaskResolutionSource(str, PyEnum):
    MANUAL = "manual"
    AUDIT_VALIDATED = "audit_validated"


class AnnotationVisibility(str, PyEnum):
    INTERNAL = "internal"
    CLIENT_VISIBLE = "client_visible"


class RecommendationApprovalStatus(str, PyEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    DEFERRED = "deferred"


class ClientDigestFrequency(str, PyEnum):
    DAILY = "daily"
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    NONE = "none"


class ProjectStatus(str, PyEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    external_id = Column(String, unique=True, index=True, nullable=True)
    auth_provider = Column(String, nullable=False, server_default="local")
    provider_subject = Column(String, unique=True, index=True, nullable=True)
    email = Column(String, unique=True, index=True, nullable=False)
    hashed_password = Column(String, nullable=False)
    email_verified = Column(Boolean, default=False, nullable=False, server_default="false")
    mfa_secret = Column(String, nullable=True)
    role = Column(String, default="user", nullable=False)
    credits = Column(Integer, default=5, nullable=False)
    notifications_enabled = Column(Boolean, default=True, nullable=False)
    notify_product_updates = Column(Boolean, default=True, nullable=False, server_default="true")
    notify_audit_alerts = Column(Boolean, default=True, nullable=False, server_default="true")
    notify_billing = Column(Boolean, default=True, nullable=False, server_default="true")
    unsubscribe_token = Column(String, unique=True, index=True, nullable=True)
    custom_logo_url = Column(String, nullable=True)
    company_name = Column(String, nullable=True)
    company_legal_name = Column(String, nullable=True)
    company_registration_number = Column(String, nullable=True)
    company_vat_number = Column(String, nullable=True)
    billing_email = Column(String, nullable=True)
    billing_phone = Column(String, nullable=True)
    billing_address_line1 = Column(String, nullable=True)
    billing_address_line2 = Column(String, nullable=True)
    billing_city = Column(String, nullable=True)
    billing_state = Column(String, nullable=True)
    billing_postal_code = Column(String, nullable=True)
    billing_country = Column(String, nullable=True)
    billing_website_url = Column(String, nullable=True)
    billing_tax_exempt = Column(Boolean, default=False, nullable=False)
    primary_color = Column(String, nullable=True)
    secondary_color = Column(String, nullable=True)
    anonymized_at = Column(DateTime(timezone=True), nullable=True)
    onboarding_state = Column(JSON, nullable=True)
    avatar_url = Column(String, nullable=True)

    # Trial fields
    trial_started_at = Column(DateTime(timezone=True), nullable=True)
    trial_ends_at = Column(DateTime(timezone=True), nullable=True)
    trial_plan = Column(
        String, nullable=True
    )  # "plan_agency_trial" when active, "plan_starter" after transition
    trial_audits_used = Column(Integer, default=0, nullable=False, server_default="0")
    trial_max_audits = Column(Integer, default=5, nullable=False, server_default="5")
    trial_initial_credits = Column(Integer, default=100, nullable=False, server_default="100")
    trial_concierge_completed = Column(
        Boolean, default=False, nullable=False, server_default="false"
    )
    explorer_credits_refreshed_at = Column(DateTime(timezone=True), nullable=True)
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    audits = relationship("Audit", back_populates="user")
    sites = relationship("Site", back_populates="user")
    owned_workspaces = relationship(
        "Workspace",
        back_populates="owner",
        foreign_keys="Workspace.owner_id",
        cascade="all, delete-orphan",
    )
    workspace_memberships = relationship(
        "WorkspaceUser",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    subscription = relationship("Subscription", back_populates="user", uselist=False)
    base_checkout_attempts = relationship(
        "BaseCheckoutAttempt",
        back_populates="user",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    billing_payments = relationship("BillingPayment", back_populates="user")
    email_outbox_entries = relationship("EmailOutbox", back_populates="user")
    credit_adjustments = relationship(
        "UserCreditAdjustment",
        back_populates="user",
        foreign_keys="UserCreditAdjustment.user_id",
    )
    plan_credit_grants = relationship(
        "PlanCreditGrant",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    # Internal records of a retired flow: no customer top-up route exists any
    # more (SIGV2-1102 settled credits as an internal unit), so this is kept
    # only to read historical rows and must not be used to build a new one.
    credit_top_up_orders = relationship(
        "CreditTopUpOrder",
        back_populates="user",
    )
    credit_holds = relationship(
        "CreditHold",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    admin_action_logs = relationship("AdminActionLog", back_populates="admin_user")
    auth_audit_logs = relationship(
        "AuthAuditLog", back_populates="user", cascade="all, delete-orphan"
    )
    api_keys = relationship("ApiKey", back_populates="user", cascade="all, delete-orphan")
    embed_api_keys = relationship(
        "EmbedApiKey", back_populates="user", cascade="all, delete-orphan"
    )
    scheduled_audits = relationship(
        "ScheduledAudit",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    jira_exports = relationship(
        "ProjectJiraExport",
        back_populates="created_by_user",
        cascade="all, delete-orphan",
    )
    assigned_project_tasks = relationship(
        "ProjectTask",
        back_populates="assigned_to_user",
        foreign_keys="ProjectTask.assigned_to_user_id",
    )
    created_project_tasks = relationship(
        "ProjectTask",
        back_populates="created_by_user",
        foreign_keys="ProjectTask.created_by_user_id",
    )
    authored_report_annotations = relationship(
        "ReportAnnotation",
        back_populates="author",
        foreign_keys="ReportAnnotation.user_id",
    )
    reviewed_claim_decisions = relationship(
        "ClaimReviewDecision",
        back_populates="reviewed_by",
        foreign_keys="ClaimReviewDecision.reviewed_by_id",
    )
    created_workflows = relationship(
        "Workflow",
        back_populates="created_by_user",
        foreign_keys="Workflow.created_by_user_id",
    )
    initiated_cms_deployments = relationship(
        "CMSDeploymentLog",
        back_populates="initiated_by_user",
        foreign_keys="CMSDeploymentLog.initiated_by",
    )
    sitemap_crawl_jobs = relationship(
        "SitemapCrawlJob",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    credit_commitment = relationship("CreditCommitment", back_populates="user", uselist=False)
    commitment_usage_cycles = relationship("CommitmentUsageCycle", back_populates="user")
    passkey_credentials = relationship(
        "PasskeyCredential",
        back_populates="user",
        cascade="all, delete-orphan",
    )
    security_events = relationship(
        "SecurityEvent", back_populates="user", cascade="all, delete-orphan"
    )
    sessions = relationship("UserSession", back_populates="user", cascade="all, delete-orphan")
    linked_identities = relationship(
        "UserLinkedIdentity",
        back_populates="user",
        cascade="all, delete-orphan",
    )

    def to_dict(self):
        role_value = str(self.role or "user").strip().lower()
        resolved_permissions = getattr(self, "resolved_permissions", None)
        if isinstance(resolved_permissions, list):
            permissions = [str(permission) for permission in resolved_permissions]
        else:
            default_permissions_map = {
                "admin": ["*"],
                "moderator": [
                    "audit:run",
                    "audit:read",
                    "profile:read",
                    "profile:update",
                    "admin:panel",
                    "admin:trials",
                    "admin:content",
                    "admin:operations",
                    "admin:monitoring",
                    "admin:overview",
                ],
                "user": ["audit:run", "audit:read", "profile:read", "profile:update"],
            }
            permissions = default_permissions_map.get(role_value, [])

        created_at_value = getattr(self, "created_at", None)
        if hasattr(created_at_value, "isoformat"):
            created_at = created_at_value.isoformat()
        elif isinstance(created_at_value, str):
            created_at = created_at_value
        else:
            created_at = None

        portal_only = bool(getattr(self, "resolved_portal_only", False))
        portal_workspace_id = getattr(self, "resolved_portal_workspace_id", None)
        subscription_plan = resolve_plan_alias(resolve_entitled_subscription_plan(self))
        trial_plan = resolve_plan_alias(getattr(self, "trial_plan", None))
        effective_plan = subscription_plan or trial_plan or "plan_starter"

        return {
            "id": str(self.id),
            "email": self.email,
            "name": self.company_name,
            "role": role_value,
            "permissions": permissions,
            "subscription_plan": effective_plan,
            "email_verified": bool(self.email_verified),
            "created_at": created_at,
            "portal_only": portal_only,
            "portal_workspace_id": portal_workspace_id,
            "avatar_url": self.avatar_url,
            "auth_provider": self.auth_provider,
        }


class Workspace(Base):
    __tablename__ = "workspaces"
    __table_args__ = (Index("ix_workspaces_owner_id_created_at", "owner_id", "created_at"),)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    owner_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    custom_logo_url = Column(String, nullable=True)
    company_name = Column(String, nullable=True)
    primary_color = Column(String, nullable=True)
    secondary_color = Column(String, nullable=True)
    custom_favicon_url = Column(String, nullable=True)
    custom_page_title = Column(String, nullable=True)
    custom_meta_description = Column(Text, nullable=True)
    hide_powered_by = Column(Boolean, default=False, nullable=False, server_default="false")
    email_sender_name = Column(String, nullable=True)
    email_reply_to = Column(String, nullable=True)
    social_facebook_url = Column(String, nullable=True)
    social_x_url = Column(String, nullable=True)
    social_instagram_url = Column(String, nullable=True)
    social_linkedin_url = Column(String, nullable=True)
    social_youtube_url = Column(String, nullable=True)
    social_tiktok_url = Column(String, nullable=True)
    company_address = Column(Text, nullable=True)
    company_legal_name = Column(String, nullable=True)
    company_trademark_text = Column(String, nullable=True)
    footer_about_url = Column(String, nullable=True)
    footer_blog_url = Column(String, nullable=True)
    footer_support_url = Column(String, nullable=True)
    footer_legal_url = Column(String, nullable=True)
    footer_preferences_url = Column(String, nullable=True)
    footer_privacy_url = Column(String, nullable=True)
    role_mode = Column(String(32), nullable=True)
    credit_budget = Column(Integer, nullable=True)
    credit_usage_current_cycle = Column(Integer, nullable=False, default=0, server_default="0")
    credit_cycle_start = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    owner = relationship("User", back_populates="owned_workspaces", foreign_keys=[owner_id])
    members = relationship(
        "WorkspaceUser", back_populates="workspace", cascade="all, delete-orphan"
    )
    projects = relationship("Project", back_populates="workspace", cascade="all, delete-orphan")
    oauth_connections = relationship(
        "OAuthConnection",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    slack_connection = relationship(
        "SlackConnection",
        back_populates="workspace",
        uselist=False,
        cascade="all, delete-orphan",
    )
    teams_connection = relationship(
        "TeamsConnection",
        back_populates="workspace",
        uselist=False,
        cascade="all, delete-orphan",
    )
    embed_api_keys = relationship(
        "EmbedApiKey",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    leads = relationship(
        "Lead",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    cms_connections = relationship(
        "CMSConnection",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    workflows = relationship(
        "Workflow",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )
    custom_domains = relationship(
        "CustomDomain",
        back_populates="workspace",
        cascade="all, delete-orphan",
    )


class CustomDomain(Base):
    __tablename__ = "custom_domains"
    __table_args__ = (
        UniqueConstraint("domain", name="uq_custom_domains_domain"),
        Index("ix_custom_domains_workspace_created_at", "workspace_id", "created_at"),
        Index("ix_custom_domains_domain_verified", "domain", "verified"),
    )

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    domain = Column(String, nullable=False)
    dns_target = Column(String, nullable=False)
    verified = Column(Boolean, default=False, nullable=False, server_default="false")
    ssl_status = Column(
        String,
        nullable=False,
        default="pending_verification",
        server_default="pending_verification",
    )
    verification_error = Column(Text, nullable=True)
    verification_checked_at = Column(DateTime(timezone=True), nullable=True)
    activated_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    workspace = relationship("Workspace", back_populates="custom_domains")


class WorkspaceUser(Base):
    __tablename__ = "workspace_users"
    __table_args__ = (
        UniqueConstraint("workspace_id", "user_id", name="uq_workspace_users_workspace_user"),
        Index("ix_workspace_users_workspace_role", "workspace_id", "role"),
    )

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role = Column(
        Enum(WorkspaceRole, name="workspace_user_role", native_enum=False),
        nullable=False,
        default=WorkspaceRole.ADMIN,
        server_default=WorkspaceRole.ADMIN.value,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    # Client notification preferences (portal users)
    email_digest_frequency = Column(
        Enum(ClientDigestFrequency, name="client_digest_frequency", native_enum=False),
        nullable=True,
    )
    notify_on_new_audit = Column(Boolean, nullable=True)

    workspace = relationship("Workspace", back_populates="members")
    user = relationship("User", back_populates="workspace_memberships")
    project_access_assignments = relationship(
        "WorkspaceUserProjectAccess",
        back_populates="workspace_user",
        cascade="all, delete-orphan",
    )


class Project(Base):
    __tablename__ = "projects"
    __table_args__ = (
        Index("ix_projects_workspace_id_created_at", "workspace_id", "created_at"),
        Index("ix_projects_workspace_domain_url", "workspace_id", "domain_url"),
    )

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = Column(String, nullable=False)
    domain_url = Column(String, nullable=True)
    target_country = Column(String, nullable=True)
    language = Column(String, nullable=False, default="en", server_default="en")
    icp_roles = Column(StringArrayType, nullable=False, default=list)
    pain_points = Column(Text, nullable=True)
    usp = Column(Text, nullable=True)
    competitors_json = Column("competitors", JSON, nullable=False, default=list)
    auto_competitor_audits_enabled = Column(
        Boolean,
        nullable=False,
        default=True,
        server_default="true",
    )
    competitive_digest_frequency = Column(
        Enum(CompetitiveDigestFrequency, name="competitive_digest_frequency", native_enum=False),
        nullable=False,
        default=CompetitiveDigestFrequency.WEEKLY,
        server_default=CompetitiveDigestFrequency.WEEKLY.name,
    )
    priority_pulse_tags = Column(StringArrayType, nullable=False, default=list)
    sme_profiles = Column(StringArrayType, nullable=False, default=list)
    tags = Column(JSON, nullable=False, default=list)
    status = Column(
        Enum(
            ProjectStatus,
            name="project_status",
            native_enum=False,
            values_callable=lambda x: [e.value for e in x],
        ),
        nullable=False,
        default=ProjectStatus.ACTIVE,
        server_default="active",
    )
    archived_at = Column(DateTime(timezone=True), nullable=True)
    aio_score_target = Column(Integer, nullable=True)
    seo_score_target = Column(Integer, nullable=True)
    cloned_from_id = Column(Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    workspace = relationship("Workspace", back_populates="projects")
    audits = relationship("Audit", back_populates="project")
    data_sources = relationship(
        "ProjectDataSource",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    magic_links = relationship("MagicLink", back_populates="project", cascade="all, delete-orphan")
    oauth_connections = relationship(
        "ProjectOAuthConnection",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    connection_audit_logs = relationship(
        "ProjectConnectionAuditLog",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    ga4_config = relationship(
        "ProjectGA4Config", back_populates="project", uselist=False, cascade="all, delete-orphan"
    )
    llm_traffic_snapshots = relationship(
        "LLMTrafficSnapshot", back_populates="project", cascade="all, delete-orphan"
    )
    bot_log_sources = relationship(
        "ProjectBotLogSource", back_populates="project", cascade="all, delete-orphan"
    )
    bot_log_uploads = relationship(
        "ProjectBotLogUpload", back_populates="project", cascade="all, delete-orphan"
    )
    bot_log_aggregates = relationship(
        "ProjectBotLogAggregate", back_populates="project", cascade="all, delete-orphan"
    )
    bot_log_daily_summaries = relationship(
        "ProjectBotLogDailySummary", back_populates="project", cascade="all, delete-orphan"
    )
    off_page_mentions = relationship(
        "ProjectOffPageMention", back_populates="project", cascade="all, delete-orphan"
    )
    off_page_mention_daily_summaries = relationship(
        "ProjectOffPageMentionDailySummary",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    target_keywords = relationship(
        "TargetKeyword", back_populates="project", cascade="all, delete-orphan"
    )
    visibility_queries = relationship(
        "ProjectVisibilityQuery",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectVisibilityQuery.created_at.asc()",
    )
    visibility_run_batches = relationship(
        "VisibilityRunBatch",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    serp_snapshots = relationship(
        "SERPTrackingSnapshot", back_populates="project", cascade="all, delete-orphan"
    )
    scheduled_audits = relationship(
        "ScheduledAudit",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    budget = relationship(
        "ProjectBudget",
        back_populates="project",
        uselist=False,
        cascade="all, delete-orphan",
    )
    budget_usage_periods = relationship(
        "ProjectBudgetUsagePeriod",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    progress_reports = relationship(
        "ProjectProgressReport",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    competitors = relationship(
        "ProjectCompetitor",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectCompetitor.created_at.asc()",
    )
    brand_facts = relationship(
        "ProjectBrandFact",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectBrandFact.created_at.asc()",
    )
    competitor_snapshots = relationship(
        "ProjectCompetitorSnapshot",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    competitive_digest_logs = relationship(
        "ProjectCompetitiveDigestLog",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    client_access_assignments = relationship(
        "WorkspaceUserProjectAccess",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    jira_exports = relationship(
        "ProjectJiraExport",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    tasks = relationship(
        "ProjectTask",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ProjectTask.sort_order.asc()",
    )
    cms_connections = relationship(
        "CMSConnection",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    report_annotations = relationship(
        "ReportAnnotation",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ReportAnnotation.created_at.asc()",
    )
    claim_review_decisions = relationship(
        "ClaimReviewDecision",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="ClaimReviewDecision.reviewed_at.desc()",
    )
    entity_authority_snapshots = relationship(
        "EntityAuthoritySnapshot",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="EntityAuthoritySnapshot.computed_at.desc()",
    )
    workflows = relationship(
        "Workflow",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    signal_audit_snapshots = relationship(
        "SignalAuditSnapshot",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    signal_debate_agent_facts = relationship(
        "SignalDebateAgentFact",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    signal_claim_disposition_facts = relationship(
        "SignalClaimDispositionFact",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    signal_citation_events = relationship(
        "SignalCitationEvent",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    signal_entity_observations = relationship(
        "SignalEntityObservation",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    signal_remediation_outcomes = relationship(
        "SignalRemediationOutcome",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    proprietary_scores = relationship(
        "ProprietaryScore",
        back_populates="project",
        cascade="all, delete-orphan",
    )
    sitemap_crawl_jobs = relationship(
        "SitemapCrawlJob",
        back_populates="project",
        cascade="all, delete-orphan",
        order_by="SitemapCrawlJob.created_at.desc()",
    )


class OAuthConnection(Base):
    __tablename__ = "oauth_connections"
    __table_args__ = (
        UniqueConstraint(
            "workspace_id", "provider", name="uq_oauth_connections_workspace_provider"
        ),
        Index("ix_oauth_connections_workspace_provider", "workspace_id", "provider"),
    )

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    provider = Column(
        Enum(OAuthProvider, name="oauth_provider", native_enum=False),
        nullable=False,
    )
    access_token = Column(EncryptedText(), nullable=False)
    refresh_token = Column(EncryptedText(), nullable=True)
    token_type = Column(String, nullable=True)
    scope = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    workspace = relationship("Workspace", back_populates="oauth_connections")


class JiraConnection(Base):
    __tablename__ = "jira_connections"
    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_jira_connections_workspace"),
        Index("ix_jira_connections_workspace_id", "workspace_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    access_token = Column(EncryptedText(), nullable=False)
    refresh_token = Column(EncryptedText(), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    cloud_id = Column(String, nullable=True)  # Atlassian Site ID
    site_name = Column(String, nullable=True)  # Atlassian Site Name
    site_url = Column(String, nullable=True)  # Atlassian Site URL
    default_jira_project_key = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    workspace = relationship("Workspace", backref="jira_connection", uselist=False)


class SlackConnection(Base):
    __tablename__ = "slack_connections"
    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_slack_connections_workspace"),
        Index("ix_slack_connections_workspace_id", "workspace_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    access_token = Column(EncryptedText(), nullable=False)
    incoming_webhook_url = Column(EncryptedText(), nullable=True)
    team_id = Column(String, nullable=False)
    team_name = Column(String, nullable=True)
    bot_user_id = Column(String, nullable=True)
    default_channel_id = Column(String, nullable=True)
    default_channel_name = Column(String, nullable=True)
    scope = Column(Text, nullable=True)
    schema_version = Column(String, nullable=False, server_default="1")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    workspace = relationship("Workspace", back_populates="slack_connection")


class TeamsConnection(Base):
    __tablename__ = "teams_connections"
    __table_args__ = (
        UniqueConstraint("workspace_id", name="uq_teams_connections_workspace"),
        Index("ix_teams_connections_workspace_id", "workspace_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    webhook_url = Column(EncryptedText(), nullable=False)
    channel_name = Column(String, nullable=True)
    schema_version = Column(String, nullable=False, server_default="1")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    workspace = relationship("Workspace", back_populates="teams_connection")


class CMSConnection(Base):
    __tablename__ = "cms_connections"
    __table_args__ = (
        UniqueConstraint("project_id", "cms_type", name="uq_cms_connections_project_type"),
        Index("ix_cms_connections_project_type", "project_id", "cms_type"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cms_type = Column(String, nullable=False)
    site_url = Column(String, nullable=False)
    credentials_json = Column(EncryptedText(), nullable=False)
    status = Column(String, nullable=False, default="pending", server_default="pending")
    last_verified_at = Column(DateTime(timezone=True), nullable=True)
    schema_version = Column(String, nullable=False, default="1", server_default="1")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    project = relationship("Project", back_populates="cms_connections")
    workspace = relationship("Workspace", back_populates="cms_connections")
    deployment_logs = relationship(
        "CMSDeploymentLog",
        back_populates="cms_connection",
    )


class CMSDeploymentLog(Base):
    __tablename__ = "cms_deployment_logs"
    __table_args__ = (
        Index("ix_cms_deployment_logs_task_created", "project_task_id", "created_at"),
        Index("ix_cms_deployment_logs_connection_created", "cms_connection_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_task_id = Column(
        Integer,
        ForeignKey("project_tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    cms_connection_id = Column(
        Integer,
        ForeignKey("cms_connections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    initiated_by = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    page_url = Column(String, nullable=False)
    field_changed = Column(String, nullable=False)
    value_before = Column(Text, nullable=True)
    value_after = Column(Text, nullable=False)
    cms_revision_id = Column(String, nullable=True)
    status = Column(String, nullable=False)
    pushed_at = Column(DateTime(timezone=True), nullable=True)
    rolled_back_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    schema_version = Column(String, nullable=False, default="1", server_default="1")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    project_task = relationship("ProjectTask", back_populates="cms_deployment_logs")
    cms_connection = relationship("CMSConnection", back_populates="deployment_logs")
    initiated_by_user = relationship("User", back_populates="initiated_cms_deployments")


class Workflow(Base):
    __tablename__ = "workflows"
    __table_args__ = (
        Index("ix_workflows_workspace_project_active", "workspace_id", "project_id", "is_active"),
    )

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    created_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    trigger_config = Column(JSON, nullable=False, default=dict)
    actions_config = Column(JSON, nullable=False, default=list)
    cooldown_minutes = Column(Integer, nullable=False, server_default="1440", default=1440)
    is_active = Column(Boolean, nullable=False, server_default="true", default=True)
    last_triggered_at = Column(DateTime(timezone=True), nullable=True)
    schema_version = Column(String, nullable=False, server_default="1")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    workspace = relationship("Workspace", back_populates="workflows")
    project = relationship("Project", back_populates="workflows")
    created_by_user = relationship("User", back_populates="created_workflows")
    runs = relationship(
        "WorkflowRun",
        back_populates="workflow",
        cascade="all, delete-orphan",
        order_by="WorkflowRun.triggered_at.desc()",
    )


class WorkflowRun(Base):
    __tablename__ = "workflow_runs"
    __table_args__ = (
        Index("ix_workflow_runs_workflow_triggered_at", "workflow_id", "triggered_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    workflow_id = Column(
        Integer, ForeignKey("workflows.id", ondelete="CASCADE"), nullable=False, index=True
    )
    triggered_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    trigger_event = Column(String, nullable=False)
    trigger_context = Column(JSON, nullable=False, default=dict)
    status = Column(String, nullable=False, server_default="running", default="running")
    action_results = Column(JSON, nullable=False, default=list)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    schema_version = Column(String, nullable=False, server_default="1")

    workflow = relationship("Workflow", back_populates="runs")


class WorkspaceUserProjectAccess(Base):
    __tablename__ = "workspace_user_project_access"
    __table_args__ = (
        UniqueConstraint(
            "workspace_user_id",
            "project_id",
            name="uq_workspace_user_project_access_member_project",
        ),
        Index("ix_workspace_user_project_access_member", "workspace_user_id"),
        Index("ix_workspace_user_project_access_project", "project_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    workspace_user_id = Column(
        Integer,
        ForeignKey("workspace_users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    role_override = Column(
        Enum(WorkspaceRole, name="project_role_override", native_enum=False),
        nullable=True,
    )

    workspace_user = relationship("WorkspaceUser", back_populates="project_access_assignments")
    project = relationship("Project", back_populates="client_access_assignments")


class RecommendationApproval(Base):
    __tablename__ = "recommendation_approvals"
    __table_args__ = (
        UniqueConstraint(
            "audit_id",
            "source_recommendation_key",
            name="uq_recommendation_approvals_audit_key",
        ),
        Index("ix_recommendation_approvals_audit_id", "audit_id"),
        Index("ix_recommendation_approvals_decided_by", "decided_by_user_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    audit_id = Column(
        Integer,
        ForeignKey("audits.id", ondelete="CASCADE"),
        nullable=False,
    )
    section_path = Column(String, nullable=True)
    source_recommendation_key = Column(String, nullable=False)
    status = Column(
        Enum(
            RecommendationApprovalStatus, name="recommendation_approval_status", native_enum=False
        ),
        nullable=False,
    )
    decided_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    decided_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    note = Column(Text, nullable=True)
    schema_version = Column(String, nullable=False, default="1", server_default="1")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    audit = relationship("Audit", backref="recommendation_approvals")
    decided_by = relationship("User", backref="recommendation_approvals")


class InvitationStatus(str, PyEnum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    EXPIRED = "expired"
    REVOKED = "revoked"


class WorkspaceInvitation(Base):
    __tablename__ = "workspace_invitations"
    __table_args__ = (
        Index("ix_workspace_invitations_workspace_id", "workspace_id"),
        Index("ix_workspace_invitations_token", "token", unique=True),
    )

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    invited_email = Column(String, nullable=False)
    invited_name = Column(String, nullable=True)
    invited_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    role = Column(
        Enum(WorkspaceRole, name="invitation_role", native_enum=False, create_constraint=False),
        nullable=False,
        default=WorkspaceRole.VIEWER,
    )
    project_ids = Column(JSON, nullable=False, default=list)
    status = Column(
        Enum(
            InvitationStatus, name="invitation_status", native_enum=False, create_constraint=False
        ),
        nullable=False,
        default=InvitationStatus.PENDING,
    )
    token = Column(String, unique=True, nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    accepted_at = Column(DateTime(timezone=True), nullable=True)
    schema_version = Column(String, nullable=False, default="1", server_default="1")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    workspace = relationship("Workspace", backref="invitations")
    invited_by = relationship("User", backref="sent_invitations")


class WorkspaceActivityLog(Base):
    __tablename__ = "workspace_activity_log"
    __table_args__ = (
        Index("ix_workspace_activity_log_workspace_id_created_at", "workspace_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False)
    actor_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    action = Column(String, nullable=False)
    target_type = Column(String, nullable=True)
    target_id = Column(Integer, nullable=True)
    metadata_json = Column(JSON, nullable=True)
    schema_version = Column(String, nullable=False, default="1", server_default="1")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    workspace = relationship("Workspace", backref="activity_logs")
    actor = relationship("User", backref="workspace_activity_logs")


class ProjectBudget(Base):
    __tablename__ = "project_budgets"
    __table_args__ = (
        UniqueConstraint("project_id", name="uq_project_budgets_project_id"),
        CheckConstraint(
            "monthly_limit_credits >= 0", name="ck_project_budgets_monthly_limit_non_negative"
        ),
        CheckConstraint(
            "monthly_limit_scans >= 0", name="ck_project_budgets_monthly_limit_scans_non_negative"
        ),
        CheckConstraint(
            "cycle_anchor_day >= 1 AND cycle_anchor_day <= 28",
            name="ck_project_budgets_cycle_anchor_day",
        ),
        Index("ix_project_budgets_project_id", "project_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, unique=True
    )
    monthly_limit_credits = Column(Integer, nullable=True)
    monthly_limit_scans = Column(Integer, nullable=True)
    cycle_anchor_day = Column(Integer, nullable=False, server_default="1", default=1)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    project = relationship("Project", back_populates="budget")


class ProjectBudgetUsagePeriod(Base):
    __tablename__ = "project_budget_usage_periods"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "period_start", name="uq_project_budget_usage_project_period"
        ),
        CheckConstraint(
            "consumed_credits >= 0", name="ck_project_budget_usage_consumed_non_negative"
        ),
        CheckConstraint(
            "consumed_scans >= 0", name="ck_project_budget_usage_consumed_scans_non_negative"
        ),
        Index("ix_project_budget_usage_project_period", "project_id", "period_start"),
        Index("ix_project_budget_usage_period_start", "period_start"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    cycle_anchor_day = Column(Integer, nullable=False, server_default="1", default=1)
    budget_limit_credits = Column(Integer, nullable=True)
    consumed_credits = Column(Integer, nullable=False, server_default="0", default=0)
    budget_limit_scans = Column(Integer, nullable=True)
    consumed_scans = Column(Integer, nullable=False, server_default="0", default=0)
    warning_threshold_sent_at = Column(DateTime(timezone=True), nullable=True)
    limit_reached_sent_at = Column(DateTime(timezone=True), nullable=True)
    last_consumed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    project = relationship("Project", back_populates="budget_usage_periods")


class ProjectProgressReport(Base):
    __tablename__ = "project_progress_reports"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "report_month", name="uq_project_progress_reports_project_month"
        ),
        Index("ix_project_progress_reports_project_month", "project_id", "report_month"),
        Index("ix_project_progress_reports_workspace_month", "workspace_id", "report_month"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    report_month = Column(Date, nullable=False)
    period_start = Column(Date, nullable=False)
    period_end = Column(Date, nullable=False)
    generated_by = Column(String, nullable=False, server_default="manual")
    snapshot_json = Column("snapshot", JSON, nullable=False, default=dict)
    recipient_count = Column(Integer, nullable=False, server_default="0", default=0)
    email_sent_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    project = relationship("Project", back_populates="progress_reports")
    workspace = relationship("Workspace")


class ProjectCompetitor(Base):
    __tablename__ = "project_competitors"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "normalized_domain", name="uq_project_competitors_project_domain"
        ),
        Index("ix_project_competitors_project_created", "project_id", "created_at"),
        Index("ix_project_competitors_normalized_domain", "normalized_domain"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    target_url = Column(String, nullable=False)
    normalized_domain = Column(String, nullable=False)
    display_name = Column(String, nullable=False)
    auto_audit_enabled = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    project = relationship("Project", back_populates="competitors")
    snapshots = relationship(
        "ProjectCompetitorSnapshot",
        back_populates="competitor",
        cascade="all, delete-orphan",
    )


class ProjectBrandFact(Base):
    """Per-project brand fact / allowed-or-forbidden claim (guardrails input).

    These structured statements feed the audit's evidence/grounding context so
    the engine respects brand truth. Gated by ``has_brand_integrity_guardrails``.
    """

    __tablename__ = "project_brand_facts"
    __table_args__ = (Index("ix_project_brand_facts_project_created", "project_id", "created_at"),)

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    kind = Column(String(32), nullable=False, default="fact", server_default="fact")
    statement = Column(Text, nullable=False)
    is_forbidden = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    project = relationship("Project", back_populates="brand_facts")


class RecommendationDecision(Base):
    """User accept/dismiss decision for an Advisor recommendation (learnings loop).

    Task 7.1/7.2 of the Qiko Signal learnings phase. Each row records a user's
    decision (``accepted`` / ``dismissed``) for a specific recommendation,
    identified by a stable ``action_fingerprint`` (sha256 of the action text).
    Dismissed fingerprints are suppressed from the Advisor plan on future audits;
    the full history feeds a user-facing Learnings view and the data moat.
    """

    __tablename__ = "recommendation_decisions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "action_fingerprint",
            name="uq_recommendation_decisions_project_fingerprint",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    action_fingerprint = Column(String(64), nullable=False)
    action_label = Column(Text, nullable=True)
    decision = Column(String(16), nullable=False)
    note = Column(Text, nullable=True)
    decided_by = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    project = relationship("Project")


class AdvisorChatMessage(Base):
    """One persisted turn of the audit-grounded Advisor chat (multi-turn history).

    Phase 8 follow-up (F3). Each row is a single ``user`` or ``assistant`` turn
    scoped to a (``audit_id``, ``user_id``) pair so follow-up questions carry
    prior-turn context. Assistant turns also store the validated ``citations``
    the reply was grounded on.

    This is PRIOR-TURN CONTEXT ONLY: history is replayed to the model as
    delimited user/assistant data, never merged into the system prompt, so the
    closed-world / grounding / abstention guarantees are unchanged. Stored
    ``content`` is RAW-sanitized (control chars stripped, length-capped) — never
    HTML-escaped (React escapes at render).
    """

    __tablename__ = "advisor_chat_messages"
    __table_args__ = (
        Index(
            "ix_advisor_chat_messages_audit_user_created",
            "audit_id",
            "user_id",
            "created_at",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    audit_id = Column(
        Integer,
        ForeignKey("audits.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    role = Column(String(16), nullable=False)
    content = Column(Text, nullable=False)
    citations = Column(JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    schema_version = Column(String, nullable=False, default="1", server_default="1")


class AdvisorPlanSnapshot(Base):
    """One persisted snapshot of the deterministic Advisor plan per audit (R12).

    The Advisor plan ("what to fix, in order") is computed at response-time and
    attached at ``metadata.advisor``; it is never used to mutate the canonical
    contract. This table records exactly one point-in-time copy per completed
    audit so plan progress / trend can later be shown over time (Executive tier).

    ``advisor_plan`` stores the full response-time plan shape verbatim (reused,
    not recomputed differently). ``plan_summary`` denormalizes the action counts
    (``total_actions`` + ``high_impact`` / ``medium_impact`` / ``low_impact``)
    for cheap trend queries. Persistence only — no auto-execution, no UI.
    """

    __tablename__ = "advisor_plan_snapshots"
    __table_args__ = (
        UniqueConstraint("audit_id", name="uq_advisor_plan_snapshots_audit"),
        Index("ix_advisor_plan_snapshots_project_created", "project_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    audit_id = Column(
        Integer,
        ForeignKey("audits.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    advisor_plan = Column(JSON, nullable=False)
    plan_summary = Column(JSON, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    schema_version = Column(String, nullable=False, default="1", server_default="1")


class ProjectCompetitorSnapshot(Base):
    __tablename__ = "project_competitor_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "competitor_id",
            "source_audit_id",
            name="uq_project_competitor_snapshots_source_competitor",
        ),
        Index("ix_project_competitor_snapshots_project_created", "project_id", "created_at"),
        Index("ix_project_competitor_snapshots_source_audit", "source_audit_id"),
        Index("ix_project_competitor_snapshots_competitor", "competitor_id"),
        Index("ix_project_competitor_snapshots_status", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    competitor_id = Column(
        Integer,
        ForeignKey("project_competitors.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_audit_id = Column(
        Integer,
        ForeignKey("audits.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    competitor_audit_id = Column(
        Integer,
        ForeignKey("audits.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(String, nullable=False, default="pending", server_default="pending")
    failure_reason = Column(Text, nullable=True)
    geo_score = Column(Float, nullable=True)
    seo_score = Column(Float, nullable=True)
    aeo_score = Column(Float, nullable=True)
    captured_at = Column(DateTime(timezone=True), nullable=True)
    metadata_json = Column("metadata", JSON, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    project = relationship("Project", back_populates="competitor_snapshots")
    competitor = relationship("ProjectCompetitor", back_populates="snapshots")
    source_audit = relationship("Audit", foreign_keys=[source_audit_id])
    competitor_audit = relationship("Audit", foreign_keys=[competitor_audit_id])


class ProjectCompetitiveDigestLog(Base):
    __tablename__ = "project_competitive_digest_logs"
    __table_args__ = (
        UniqueConstraint("source_audit_id", name="uq_project_competitive_digest_logs_source_audit"),
        Index("ix_project_competitive_digest_logs_project_created", "project_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_audit_id = Column(
        Integer,
        ForeignKey("audits.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    frequency = Column(String, nullable=False, default="weekly", server_default="weekly")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    project = relationship("Project", back_populates="competitive_digest_logs")
    source_audit = relationship("Audit", foreign_keys=[source_audit_id])


class ProjectJiraExport(Base):
    __tablename__ = "project_jira_exports"
    __table_args__ = (
        Index("ix_project_jira_exports_project_created", "project_id", "created_at"),
        Index("ix_project_jira_exports_issue_key", "issue_key"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    audit_id = Column(
        Integer, ForeignKey("audits.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    jira_project_key = Column(String, nullable=True)
    issue_id = Column(String, nullable=False, index=True)
    issue_key = Column(String, nullable=False)
    issue_url = Column(String, nullable=False)
    title = Column(String, nullable=False)
    issue_type = Column(String, nullable=False, server_default="Task")
    status_name = Column(String, nullable=False, server_default="Exported")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    project = relationship("Project", back_populates="jira_exports")
    audit = relationship("Audit", back_populates="jira_exports")
    created_by_user = relationship("User", back_populates="jira_exports")


class ProjectDataSource(Base):
    __tablename__ = "project_data_sources"
    __table_args__ = (
        UniqueConstraint("project_id", "source_type", name="uq_project_data_sources_project_type"),
        Index("ix_project_data_sources_project_provider", "project_id", "provider"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    oauth_connection_id = Column(
        Integer,
        ForeignKey("oauth_connections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    project_oauth_connection_id = Column(
        Integer,
        ForeignKey("project_oauth_connections.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider = Column(
        Enum(OAuthProvider, name="oauth_provider", native_enum=False),
        nullable=False,
    )
    source_type = Column(
        Enum(ProjectDataSourceType, name="project_data_source_type", native_enum=False),
        nullable=False,
    )
    binding_mode = Column(
        Enum(
            ProjectDataSourceBindingMode, name="project_data_source_binding_mode", native_enum=False
        ),
        nullable=False,
        default=ProjectDataSourceBindingMode.WORKSPACE,
        server_default=ProjectDataSourceBindingMode.WORKSPACE.name,
    )
    source_id = Column(String, nullable=True)
    source_label = Column(String, nullable=True)
    metadata_json = Column("metadata", JSON, nullable=False, default=dict)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    last_status = Column(String, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    project = relationship("Project", back_populates="data_sources")
    oauth_connection = relationship("OAuthConnection")
    project_oauth_connection = relationship("ProjectOAuthConnection", back_populates="data_sources")


class MagicLink(Base):
    __tablename__ = "magic_links"
    __table_args__ = (Index("ix_magic_links_project_id_expires_at", "project_id", "expires_at"),)

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    unique_token = Column(String, nullable=False, unique=True, index=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    is_used = Column(Boolean, nullable=False, default=False, server_default="false")
    used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    project = relationship("Project", back_populates="magic_links")
    oauth_connections = relationship("ProjectOAuthConnection", back_populates="magic_link")
    audit_logs = relationship("ProjectConnectionAuditLog", back_populates="magic_link")


class ProjectOAuthConnection(Base):
    __tablename__ = "project_oauth_connections"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "provider", name="uq_project_oauth_connections_project_provider"
        ),
        Index("ix_project_oauth_connections_project_provider", "project_id", "provider"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    magic_link_id = Column(
        Integer,
        ForeignKey("magic_links.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider = Column(
        Enum(OAuthProvider, name="oauth_provider", native_enum=False),
        nullable=False,
    )
    access_token = Column(EncryptedText(), nullable=False)
    refresh_token = Column(EncryptedText(), nullable=True)
    token_type = Column(String, nullable=True)
    scope = Column(Text, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    connected_by_email = Column(String, nullable=True)
    external_subject = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    project = relationship("Project", back_populates="oauth_connections")
    magic_link = relationship("MagicLink", back_populates="oauth_connections")
    data_sources = relationship("ProjectDataSource", back_populates="project_oauth_connection")


class ProjectConnectionAuditLog(Base):
    __tablename__ = "project_connection_audit_logs"
    __table_args__ = (
        Index("ix_project_connection_audit_logs_project_created", "project_id", "created_at"),
        Index("ix_project_connection_audit_logs_event_type", "event_type"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    magic_link_id = Column(
        Integer,
        ForeignKey("magic_links.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    provider = Column(
        Enum(OAuthProvider, name="oauth_provider", native_enum=False),
        nullable=True,
    )
    event_type = Column(String, nullable=False)
    metadata_json = Column("metadata", JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    project = relationship("Project", back_populates="connection_audit_logs")
    magic_link = relationship("MagicLink", back_populates="audit_logs")


class ProjectGA4Config(Base):
    __tablename__ = "project_ga4_configs"
    __table_args__ = (UniqueConstraint("project_id", name="uq_project_ga4_configs_project"),)

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        unique=True,
        index=True,
    )
    ga4_property_id = Column(String, nullable=False)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    last_synced_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    project = relationship("Project", back_populates="ga4_config")


class ProjectBotLogSource(Base):
    __tablename__ = "project_bot_log_sources"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "source_type", name="uq_project_bot_log_sources_project_source"
        ),
        Index("ix_project_bot_log_sources_project_active", "project_id", "is_active"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type = Column(
        Enum(BotLogIngestionSourceType, name="bot_log_ingestion_source_type", native_enum=False),
        nullable=False,
    )
    display_name = Column(String, nullable=True)
    config_json = Column("config", JSON, nullable=False, default=dict, server_default="{}")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    last_sync_at = Column(DateTime(timezone=True), nullable=True)
    last_status = Column(String, nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    project = relationship("Project", back_populates="bot_log_sources")
    uploads = relationship("ProjectBotLogUpload", back_populates="source")


class ProjectGSCPageMetric(Base):
    """Daily Search Console page metrics (SIGV2-1025).

    Grain per contract section 8: property, page, date, clicks, impressions,
    position, completeness flag. Deliberately shaped for the Pages table, not
    the dropped ``project_gsc_snapshots`` ROI-simulator table.
    """

    __tablename__ = "project_gsc_page_metrics"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "property",
            "page",
            "date",
            name="uq_project_gsc_page_metrics_grain",
        ),
        Index("ix_project_gsc_page_metrics_project_date", "project_id", "date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    property = Column(String, nullable=False)
    page = Column(String, nullable=False)
    date = Column(Date, nullable=False)
    clicks = Column(Float, nullable=False, default=0.0, server_default="0")
    impressions = Column(Float, nullable=False, default=0.0, server_default="0")
    position = Column(Float, nullable=True)
    is_incomplete = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    project = relationship("Project")


class ProjectBingMetric(Base):
    """Daily Bing Webmaster metrics (SIGV2-1082).

    A deliberately separate dataset from ``project_gsc_page_metrics``: Bing
    numbers are never merged into or presented as Search Console numbers.
    ``dimension_type`` is one of site / query / page; ``dimension`` is empty
    for site rows, the query text, or the page URL. Position is stored only as
    the raw provider integers because Microsoft types them ``int`` without
    documenting the scale; consumers report position as unavailable.
    """

    __tablename__ = "project_bing_metrics"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "site_url",
            "dimension_type",
            "dimension",
            "date",
            name="uq_project_bing_metrics_grain",
        ),
        Index("ix_project_bing_metrics_project_date", "project_id", "date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    site_url = Column(String, nullable=False)
    dimension_type = Column(String, nullable=False)
    dimension = Column(String, nullable=False, default="", server_default="")
    date = Column(Date, nullable=False)
    clicks = Column(Float, nullable=False, default=0.0, server_default="0")
    impressions = Column(Float, nullable=False, default=0.0, server_default="0")
    avg_click_position_raw = Column(Integer, nullable=True)
    avg_impression_position_raw = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    project = relationship("Project")


class ProjectBotLogUpload(Base):
    __tablename__ = "project_bot_log_uploads"
    __table_args__ = (
        Index("ix_project_bot_log_uploads_project_uploaded", "project_id", "uploaded_at"),
        Index("ix_project_bot_log_uploads_project_status", "project_id", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_id = Column(
        Integer,
        ForeignKey("project_bot_log_sources.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_type = Column(
        Enum(BotLogIngestionSourceType, name="bot_log_ingestion_source_type", native_enum=False),
        nullable=False,
        default=BotLogIngestionSourceType.MANUAL_UPLOAD,
        server_default=BotLogIngestionSourceType.MANUAL_UPLOAD.name,
    )
    filename = Column(String, nullable=False)
    status = Column(String, nullable=False, default="processing", server_default="processing")
    bytes_processed = Column(BigInteger, nullable=False, default=0, server_default="0")
    lines_processed = Column(Integer, nullable=False, default=0, server_default="0")
    bot_hits = Column(Integer, nullable=False, default=0, server_default="0")
    skipped_lines = Column(Integer, nullable=False, default=0, server_default="0")
    metadata_json = Column("metadata", JSON, nullable=False, default=dict, server_default="{}")
    started_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    uploaded_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    error_message = Column(Text, nullable=True)
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    project = relationship("Project", back_populates="bot_log_uploads")
    source = relationship("ProjectBotLogSource", back_populates="uploads")
    aggregates = relationship(
        "ProjectBotLogAggregate", back_populates="upload", cascade="all, delete-orphan"
    )


class ProjectBotLogAggregate(Base):
    __tablename__ = "project_bot_log_aggregates"
    __table_args__ = (
        UniqueConstraint(
            "upload_id",
            "snapshot_date",
            "bot_name",
            "section",
            "status_class",
            "is_verified",
            name="uq_project_bot_log_aggregates_upload_dimension",
        ),
        Index("ix_project_bot_log_aggregates_project_date", "project_id", "snapshot_date"),
        Index("ix_project_bot_log_aggregates_project_bot", "project_id", "bot_name"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    upload_id = Column(
        Integer,
        ForeignKey("project_bot_log_uploads.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type = Column(
        Enum(BotLogIngestionSourceType, name="bot_log_ingestion_source_type", native_enum=False),
        nullable=False,
        default=BotLogIngestionSourceType.MANUAL_UPLOAD,
        server_default=BotLogIngestionSourceType.MANUAL_UPLOAD.name,
    )
    snapshot_date = Column(Date, nullable=False)
    bot_name = Column(String, nullable=False)
    section = Column(String, nullable=False)
    status_class = Column(String, nullable=False)
    is_verified = Column(Boolean, nullable=False, default=False, server_default="false")
    hits = Column(Integer, nullable=False, default=0, server_default="0")
    distinct_ips = Column(Integer, nullable=False, default=0, server_default="0")
    metadata_json = Column("metadata", JSON, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    project = relationship("Project", back_populates="bot_log_aggregates")
    upload = relationship("ProjectBotLogUpload", back_populates="aggregates")


class ProjectBotLogDailySummary(Base):
    __tablename__ = "project_bot_log_daily_summaries"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "source_type",
            "snapshot_date",
            "bot_name",
            "section",
            "status_class",
            "is_verified",
            name="uq_project_bot_log_daily_summaries_dimension",
        ),
        Index("ix_project_bot_log_daily_summaries_project_date", "project_id", "snapshot_date"),
        Index("ix_project_bot_log_daily_summaries_project_bot", "project_id", "bot_name"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type = Column(
        Enum(BotLogIngestionSourceType, name="bot_log_ingestion_source_type", native_enum=False),
        nullable=False,
        default=BotLogIngestionSourceType.MANUAL_UPLOAD,
        server_default=BotLogIngestionSourceType.MANUAL_UPLOAD.name,
    )
    snapshot_date = Column(Date, nullable=False)
    bot_name = Column(String, nullable=False)
    section = Column(String, nullable=False)
    status_class = Column(String, nullable=False)
    is_verified = Column(Boolean, nullable=False, default=False, server_default="false")
    hits = Column(Integer, nullable=False, default=0, server_default="0")
    distinct_ips = Column(Integer, nullable=False, default=0, server_default="0")
    computed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    project = relationship("Project", back_populates="bot_log_daily_summaries")


class ProjectOffPageMention(Base):
    __tablename__ = "project_off_page_mentions"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "fingerprint_hash",
            name="uq_project_off_page_mentions_project_fingerprint",
        ),
        Index("ix_project_off_page_mentions_project_published", "project_id", "published_at"),
        Index("ix_project_off_page_mentions_project_sentiment", "project_id", "sentiment_label"),
        Index("ix_project_off_page_mentions_project_domain", "project_id", "source_domain"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_type = Column(
        String, nullable=False, default="manual_import", server_default="manual_import"
    )
    source_domain = Column(String, nullable=True)
    mention_url = Column(String, nullable=True)
    external_id = Column(String, nullable=True, index=True)
    title = Column(String, nullable=True)
    snippet = Column(Text, nullable=False)
    fingerprint_hash = Column(String, nullable=False)
    published_at = Column(DateTime(timezone=True), nullable=True)
    discovered_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    sentiment_label = Column(String, nullable=False, default="unknown", server_default="unknown")
    sentiment_score = Column(Float, nullable=True)
    linked_keywords_json = Column(
        "linked_keywords", JSON, nullable=False, default=list, server_default="[]"
    )
    entities_json = Column("entities", JSON, nullable=False, default=list, server_default="[]")
    authority_score = Column(Float, nullable=False, default=0.0, server_default="0")
    action_recommendation = Column(Text, nullable=True)
    analysis_status = Column(String, nullable=False, default="pending", server_default="pending")
    analysis_error = Column(Text, nullable=True)
    metadata_json = Column("metadata", JSON, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    updated_at = Column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
    # Verified outbound-link-to-target state (SIGV2-1008). "unknown" covers
    # never-checked, fetch-failed and restricted pages; only "unlinked" is a
    # reclaimable opportunity.
    link_state = Column(String, nullable=False, default="unknown", server_default="unknown")
    link_checked_at = Column(DateTime(timezone=True), nullable=True)
    link_evidence_json = Column("link_evidence", JSON, nullable=True)
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    project = relationship("Project", back_populates="off_page_mentions")


class ProjectOffPageMentionDailySummary(Base):
    __tablename__ = "project_off_page_mention_daily_summaries"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "snapshot_date",
            name="uq_project_off_page_mention_daily_summaries_project_date",
        ),
        Index(
            "ix_project_off_page_mention_daily_summaries_project_date",
            "project_id",
            "snapshot_date",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_date = Column(Date, nullable=False)
    total_mentions = Column(Integer, nullable=False, default=0, server_default="0")
    positive_mentions = Column(Integer, nullable=False, default=0, server_default="0")
    neutral_mentions = Column(Integer, nullable=False, default=0, server_default="0")
    negative_mentions = Column(Integer, nullable=False, default=0, server_default="0")
    unique_domains = Column(Integer, nullable=False, default=0, server_default="0")
    avg_authority_score = Column(Float, nullable=False, default=0.0, server_default="0")
    off_page_aeo_score = Column(Float, nullable=False, default=0.0, server_default="0")
    degraded = Column(Boolean, nullable=False, default=False, server_default="false")
    degraded_reasons_json = Column(
        "degraded_reasons", JSON, nullable=False, default=list, server_default="[]"
    )
    computed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    project = relationship("Project", back_populates="off_page_mention_daily_summaries")


class LLMTrafficSnapshot(Base):
    __tablename__ = "llm_traffic_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "source",
            "snapshot_date",
            name="uq_llm_traffic_snapshots_project_source_date",
        ),
        Index("ix_llm_traffic_snapshots_project_date", "project_id", "snapshot_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source = Column(String, nullable=False)
    snapshot_date = Column(Date, nullable=False)
    sessions = Column(Integer, nullable=False, default=0, server_default="0")
    users = Column(Integer, nullable=True)
    page_views = Column(Integer, nullable=True)
    avg_session_duration_seconds = Column(Float, nullable=True)
    bounce_rate = Column(Float, nullable=True)
    metadata_json = Column("metadata", JSON, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    project = relationship("Project", back_populates="llm_traffic_snapshots")


class TargetKeyword(Base):
    __tablename__ = "target_keywords"
    __table_args__ = (
        UniqueConstraint("project_id", "keyword", name="uq_target_keywords_project_keyword"),
        Index("ix_target_keywords_project_active", "project_id", "is_active"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    keyword = Column(String, nullable=False)
    search_engine = Column(String, nullable=False, default="google", server_default="google")
    language_code = Column(String, nullable=False, default="en", server_default="en")
    location_code = Column(Integer, nullable=True)
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    project = relationship("Project", back_populates="target_keywords")
    serp_snapshots = relationship(
        "SERPTrackingSnapshot", back_populates="keyword", cascade="all, delete-orphan"
    )


class SERPTrackingSnapshot(Base):
    __tablename__ = "serp_tracking_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "keyword_id", "snapshot_date", name="uq_serp_tracking_snapshots_keyword_date"
        ),
        Index("ix_serp_tracking_snapshots_keyword_date", "keyword_id", "snapshot_date"),
        Index("ix_serp_tracking_snapshots_project_date", "project_id", "snapshot_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    keyword_id = Column(
        Integer, ForeignKey("target_keywords.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_date = Column(Date, nullable=False)
    owns_featured_snippet = Column(Boolean, nullable=False, default=False, server_default="false")
    featured_snippet_url = Column(String, nullable=True)
    featured_snippet_content = Column(Text, nullable=True)
    paa_appearances = Column(JSON, nullable=False, default=list, server_default="[]")
    organic_position = Column(Integer, nullable=True)
    serp_features_present = Column(JSON, nullable=False, default=list, server_default="[]")
    ai_overview_detected = Column(Boolean, nullable=False, default=False, server_default="false")
    ai_overview_cites_target = Column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    ai_overview_source_urls = Column(JSON, nullable=True)
    ai_overview_text = Column(Text, nullable=True)
    raw_response_hash = Column(String, nullable=True)
    metadata_json = Column("metadata", JSON, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    keyword = relationship("TargetKeyword", back_populates="serp_snapshots")
    project = relationship("Project", back_populates="serp_snapshots")


class AuthAuditLog(Base):
    __tablename__ = "auth_audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True)
    event_type = Column(
        String, nullable=False, index=True
    )  # e.g., login_success, login_failed, mfa_enabled
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    user = relationship("User", back_populates="auth_audit_logs")


class SecurityEvent(Base):
    __tablename__ = "security_events"

    id = Column(Integer, primary_key=True, index=True)
    event_type = Column(String, nullable=False, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    metadata_json = Column(JSON, nullable=True)
    severity = Column(String, nullable=False, server_default="info")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    user = relationship("User", back_populates="security_events")


class UserSession(Base):
    __tablename__ = "user_sessions"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    token_jti = Column(String, unique=True, index=True)
    ip_address = Column(String, nullable=True)
    user_agent = Column(String, nullable=True)
    device_name = Column(String, nullable=True)
    is_active = Column(Boolean, nullable=False, server_default="true")
    last_activity_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    user = relationship("User", back_populates="sessions")


class MetricsSnapshot(Base):
    __tablename__ = "metrics_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    snapshot_at = Column(DateTime(timezone=True), nullable=False, index=True)

    requests_total = Column(Integer, nullable=False, server_default="0")
    requests_2xx = Column(Integer, nullable=False, server_default="0")
    requests_4xx = Column(Integer, nullable=False, server_default="0")
    requests_5xx = Column(Integer, nullable=False, server_default="0")

    latency_p50_ms = Column(Float, nullable=True)
    latency_p95_ms = Column(Float, nullable=True)
    latency_p99_ms = Column(Float, nullable=True)
    latency_avg_ms = Column(Float, nullable=True)

    audit_jobs_completed = Column(Integer, nullable=True)
    audit_jobs_failed = Column(Integer, nullable=True)
    audit_avg_duration_seconds = Column(Float, nullable=True)

    slow_endpoints = Column(JSON, nullable=True)
    schema_version = Column(String, nullable=False, default="1", server_default="1")


class ApiKey(Base):
    __tablename__ = "api_keys"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name = Column(String, nullable=False)
    key_hash = Column(String, nullable=False, unique=True, index=True)
    key_prefix = Column(String, nullable=True)
    key_last_four = Column(String, nullable=True)
    scopes = Column(JSON, nullable=False, default=list, server_default="[]")
    is_active = Column(Boolean, nullable=False, default=True)
    revoked_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="api_keys")
    audit_jobs = relationship("AuditJob", back_populates="api_key")


class EmbedApiKey(Base):
    __tablename__ = "embed_api_keys"
    __table_args__ = (Index("ix_embed_api_keys_workspace_active", "workspace_id", "is_active"),)

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    label = Column(String, nullable=False)
    key_hash = Column(String, nullable=False, unique=True, index=True)
    key_prefix = Column(String, nullable=False, default="stx_embed_", server_default="stx_embed_")
    key_last_four = Column(String, nullable=True)
    allowed_origins = Column(StringArrayType, nullable=False, default=list)
    daily_limit = Column(Integer, nullable=False, default=100, server_default="100")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    workspace = relationship("Workspace", back_populates="embed_api_keys")
    user = relationship("User", back_populates="embed_api_keys")
    leads = relationship("Lead", back_populates="embed_key")
    audit_jobs = relationship("AuditJob", back_populates="embed_api_key")


class Lead(Base):
    __tablename__ = "leads"
    __table_args__ = (
        Index("ix_leads_workspace_status_created", "workspace_id", "status", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    embed_key_id = Column(
        Integer, ForeignKey("embed_api_keys.id", ondelete="SET NULL"), nullable=True, index=True
    )
    email = Column(String, nullable=False, index=True)
    url = Column(String, nullable=False)
    entity = Column(String, nullable=True)
    audit_job_id = Column(
        String, ForeignKey("audit_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    scores_json = Column(JSON, nullable=True)
    source = Column(String, nullable=False, default="widget", server_default="widget")
    status = Column(String, nullable=False, default="pending", server_default="pending", index=True)
    ip_address = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    workspace = relationship("Workspace", back_populates="leads")
    embed_key = relationship("EmbedApiKey", back_populates="leads")
    audit_job = relationship("AuditJob", back_populates="leads")


class SitemapCrawlJob(Base):
    __tablename__ = "sitemap_crawl_jobs"
    __table_args__ = (
        Index("ix_sitemap_crawl_jobs_project_status_created", "project_id", "status", "created_at"),
    )

    id = Column(String, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    sitemap_url = Column(String, nullable=False)
    status = Column(String, nullable=False, default="parsing", server_default="parsing", index=True)
    total_urls = Column(Integer, nullable=True)
    completed_urls = Column(Integer, nullable=False, default=0, server_default="0")
    failed_urls = Column(Integer, nullable=False, default=0, server_default="0")
    aggregated_scores_json = Column(JSON, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    credits_consumed = Column(Integer, nullable=False, default=0, server_default="0")
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    project = relationship("Project", back_populates="sitemap_crawl_jobs")
    user = relationship("User", back_populates="sitemap_crawl_jobs")
    audit_jobs = relationship("AuditJob", back_populates="sitemap_crawl_job")


class UserCreditAdjustment(Base):
    __tablename__ = "user_credit_adjustments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    admin_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    delta = Column(Integer, nullable=False)
    reason = Column(Text, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    user = relationship("User", foreign_keys=[user_id], back_populates="credit_adjustments")
    admin_user = relationship("User", foreign_keys=[admin_user_id])


class CreditTopUpOrder(Base):
    """Internal record of the retired customer credit top-up flow.

    Credits are the internal cost unit (SIGV2-1102) and no customer top-up
    route exists any more (`POST /billing/top-up` is gone). The table may still
    hold historical rows, so the model stays for reads and migrations, but it
    must not be used to build a new top-up flow.
    """

    __tablename__ = "credit_top_up_orders"
    __table_args__ = (
        CheckConstraint(
            "expected_credits >= 100 AND expected_credits <= 10000",
            name="ck_credit_top_up_orders_expected_credits",
        ),
        CheckConstraint(
            "expected_amount_cents > 0",
            name="ck_credit_top_up_orders_expected_amount_positive",
        ),
        CheckConstraint(
            "currency = 'usd'",
            name="ck_credit_top_up_orders_currency_usd",
        ),
        CheckConstraint(
            "stripe_mode IN ('test', 'live')",
            name="ck_credit_top_up_orders_stripe_mode",
        ),
        CheckConstraint(
            "status IN ('pending', 'checkout_created', 'validation_failed', 'fulfilled', 'canceled')",
            name="ck_credit_top_up_orders_status",
        ),
        CheckConstraint(
            "(status = 'fulfilled' AND stripe_customer_id IS NOT NULL "
            "AND stripe_session_id IS NOT NULL AND fulfilled_at IS NOT NULL "
            "AND credit_adjustment_id IS NOT NULL) OR "
            "(status != 'fulfilled' AND fulfilled_at IS NULL AND credit_adjustment_id IS NULL)",
            name="ck_credit_top_up_orders_fulfilled_fields",
        ),
        CheckConstraint(
            "status != 'pending' OR stripe_session_id IS NULL",
            name="ck_credit_top_up_orders_pending_fields",
        ),
        CheckConstraint(
            "status != 'checkout_created' OR "
            "(stripe_customer_id IS NOT NULL AND stripe_session_id IS NOT NULL)",
            name="ck_credit_top_up_orders_checkout_fields",
        ),
        UniqueConstraint(
            "stripe_session_id",
            name="uq_credit_top_up_orders_stripe_session_id",
        ),
        UniqueConstraint(
            "user_id",
            "intent_key_hash",
            name="uq_credit_top_up_orders_user_intent_key_hash",
        ),
        UniqueConstraint(
            "credit_adjustment_id",
            name="uq_credit_top_up_orders_credit_adjustment_id",
        ),
        Index("ix_credit_top_up_orders_user_id", "user_id"),
        Index("ix_credit_top_up_orders_status", "status"),
        Index("ix_credit_top_up_orders_stripe_customer_id", "stripe_customer_id"),
        Index("ix_credit_top_up_orders_stripe_session_id", "stripe_session_id"),
        Index("ix_credit_top_up_orders_user_status", "user_id", "status"),
    )

    id = Column(String(64), primary_key=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False)
    intent_key_hash = Column(String(64), nullable=False)
    expected_credits = Column(Integer, nullable=False)
    expected_amount_cents = Column(Integer, nullable=False)
    currency = Column(String(3), nullable=False, default="usd", server_default="usd")
    stripe_mode = Column(String(8), nullable=False)
    status = Column(String(32), nullable=False, default="pending", server_default="pending")
    stripe_customer_id = Column(String(255), nullable=True)
    stripe_session_id = Column(String(255), nullable=True)
    credit_adjustment_id = Column(
        Integer,
        ForeignKey(
            "user_credit_adjustments.id",
            name="fk_credit_top_up_orders_credit_adjustment_id",
        ),
        nullable=True,
    )
    last_error_code = Column(String(64), nullable=True)
    last_error_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    fulfilled_at = Column(DateTime(timezone=True), nullable=True)
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    user = relationship("User", back_populates="credit_top_up_orders")


class PlanCreditGrant(Base):
    __tablename__ = "plan_credit_grants"
    __table_args__ = (
        CheckConstraint(
            "stripe_mode IN ('legacy', 'test', 'live')",
            name="ck_plan_credit_grants_stripe_mode",
        ),
        CheckConstraint(
            "period_start >= 0 AND period_end >= period_start",
            name="ck_plan_credit_grants_period",
        ),
        UniqueConstraint(
            "stripe_invoice_id",
            name="uq_plan_credit_grants_stripe_invoice_id",
        ),
        UniqueConstraint(
            "entitlement_key",
            name="uq_plan_credit_grants_entitlement_key",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    stripe_invoice_id = Column(String, nullable=False)
    entitlement_key = Column(String(512), nullable=False)
    stripe_mode = Column(String(8), nullable=False)
    stripe_price_id = Column(String(255), nullable=False)
    period_start = Column(Integer, nullable=False)
    period_end = Column(Integer, nullable=False)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    plan_type = Column(String, nullable=False)
    credits = Column(Integer, nullable=False)
    interval = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    user = relationship("User", back_populates="plan_credit_grants")


class CreditHold(Base):
    __tablename__ = "credit_holds"
    __table_args__ = (
        Index("ix_credit_holds_user_status", "user_id", "status"),
        Index("ix_credit_holds_status_expires", "status", "expires_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    request_id = Column(String(128), nullable=False, unique=True, index=True)
    hold_amount = Column(Integer, nullable=False)
    final_amount = Column(Integer, nullable=True)
    refunded_amount = Column(Integer, nullable=False, default=0, server_default="0")
    status = Column(
        String(20), nullable=False, default="pending", server_default="pending", index=True
    )
    reason_code = Column(String(100), nullable=False)
    feature_key = Column(String(100), nullable=False)
    tier_class = Column(String(20), nullable=False, default="fast", server_default="fast")
    policy_version = Column(String(10), nullable=False, default="v1", server_default="v1")
    workspace_id = Column(
        Integer,
        ForeignKey("workspaces.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    project_id = Column(
        Integer,
        ForeignKey("projects.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    payload_json = Column("payload", JSON, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    settled_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False, index=True)
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    user = relationship("User", back_populates="credit_holds")
    workspace = relationship("Workspace")
    project = relationship("Project")


class AIEconomicsLedgerEntry(Base):
    __tablename__ = "ai_economics_ledger_entries"
    __table_args__ = (
        Index("ix_ai_econ_ledger_feature_created", "feature_key", "created_at"),
        Index("ix_ai_econ_ledger_workspace_created", "workspace_id", "created_at"),
        Index("ix_ai_econ_ledger_project_created", "project_id", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    policy_version = Column(String, nullable=False, default="v1", server_default="v1")
    feature_key = Column(String, nullable=False, index=True)
    tier_class = Column(String, nullable=False, default="fast", server_default="fast")
    routing_profile = Column(String, nullable=True)
    provider = Column(String, nullable=True, index=True)
    model = Column(String, nullable=True)
    fallback_level = Column(Integer, nullable=False, default=0, server_default="0")
    input_tokens = Column(Integer, nullable=False, default=0, server_default="0")
    output_tokens = Column(Integer, nullable=False, default=0, server_default="0")
    total_tokens = Column(Integer, nullable=False, default=0, server_default="0")
    token_cost_usd = Column(Numeric(12, 6), nullable=False, default=0, server_default="0")
    infra_alloc_usd = Column(Numeric(12, 6), nullable=False, default=0, server_default="0")
    orchestration_usd = Column(Numeric(12, 6), nullable=False, default=0, server_default="0")
    retry_risk_usd = Column(Numeric(12, 6), nullable=False, default=0, server_default="0")
    real_cost_usd = Column(Numeric(12, 6), nullable=False, default=0, server_default="0")
    credits_charged = Column(Integer, nullable=False, default=0, server_default="0")
    credit_unit_value_usd = Column(Numeric(12, 6), nullable=False, default=0, server_default="0")
    implied_revenue_usd = Column(Numeric(12, 6), nullable=False, default=0, server_default="0")
    margin_usd = Column(Numeric(12, 6), nullable=False, default=0, server_default="0")
    margin_pct = Column(Numeric(8, 6), nullable=True)
    request_id = Column(String, nullable=True, index=True)
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="SET NULL"), nullable=True, index=True
    )
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    shadow_policy_version = Column(String, nullable=True)
    shadow_credits_charged = Column(Integer, nullable=True)
    payload_json = Column("payload", JSON, nullable=False, default=dict, server_default="{}")
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    workspace = relationship("Workspace")
    project = relationship("Project")
    user = relationship("User")


class AlertRule(Base):
    __tablename__ = "alert_rules"
    __table_args__ = (Index("ix_alert_rules_project_id", "project_id"),)

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False)
    metric = Column(String, nullable=False)  # geo_score, seo_score, etc.
    condition = Column(String, nullable=False)  # below, drops_by
    threshold = Column(Float, nullable=False)
    email_to = Column(String, nullable=False)
    is_active = Column(Boolean, default=True, server_default="true", nullable=False)
    last_triggered_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    project = relationship("Project", backref="alert_rules")
    logs = relationship("AlertLog", back_populates="rule", cascade="all, delete-orphan")


class AlertLog(Base):
    __tablename__ = "alert_logs"

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(
        Integer, ForeignKey("alert_rules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    triggered_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    metric_value = Column(Float, nullable=False)
    message = Column(String, nullable=False)

    rule = relationship("AlertRule", back_populates="logs")


class AdminActionLog(Base):
    __tablename__ = "admin_action_logs"

    id = Column(Integer, primary_key=True, index=True)
    admin_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action = Column(String, nullable=False, index=True)
    target_type = Column(String, nullable=False, index=True)
    target_id = Column(String, nullable=True, index=True)
    metadata_json = Column("metadata", JSON, nullable=False, default=dict)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    admin_user = relationship("User", back_populates="admin_action_logs")


class AdminNotificationChannel(Base):
    __tablename__ = "admin_notification_channels"
    __table_args__ = (
        Index("ix_admin_notification_channels_type_active", "channel_type", "is_active"),
    )

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    channel_type = Column(String, nullable=False, index=True)
    config_json = Column("config", JSON, nullable=False, default=dict, server_default="{}")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true", index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    rules = relationship(
        "AdminAlertRule",
        secondary=admin_alert_rule_channels,
        back_populates="channels",
    )


class AdminAlertRule(Base):
    __tablename__ = "admin_alert_rules"
    __table_args__ = (Index("ix_admin_alert_rules_metric_active", "metric_key", "is_active"),)

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    metric_key = Column(String, nullable=False, index=True)
    condition = Column(String, nullable=False)
    threshold_value = Column(Float, nullable=False)
    time_window_minutes = Column(Integer, nullable=False, default=5, server_default="5")
    cooldown_minutes = Column(Integer, nullable=False, default=60, server_default="60")
    severity = Column(String, nullable=False, default="warning", server_default="warning")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    notify_email = Column(Boolean, nullable=False, default=True, server_default="true")
    notify_slack = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    channels = relationship(
        "AdminNotificationChannel",
        secondary=admin_alert_rule_channels,
        back_populates="rules",
    )
    events = relationship(
        "AdminAlertEvent",
        back_populates="rule",
        cascade="all, delete-orphan",
        order_by="AdminAlertEvent.triggered_at.desc()",
    )


class AdminAlertEvent(Base):
    __tablename__ = "admin_alert_events"
    __table_args__ = (
        Index("ix_admin_alert_events_status_triggered", "status", "triggered_at"),
        Index("ix_admin_alert_events_rule_triggered", "rule_id", "triggered_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(
        Integer, ForeignKey("admin_alert_rules.id", ondelete="SET NULL"), nullable=True, index=True
    )
    metric_key = Column(String, nullable=False, index=True)
    current_value = Column(Float, nullable=False)
    threshold_value = Column(Float, nullable=True)
    severity = Column(String, nullable=False, default="warning", server_default="warning")
    message = Column(Text, nullable=True)
    context_info = Column(JSON, nullable=False, default=dict, server_default="{}")
    status = Column(String, nullable=False, default="active", server_default="active", index=True)
    triggered_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_by = Column(String, nullable=True)
    notes = Column(Text, nullable=True)
    notifications_sent = Column(JSON, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    rule = relationship("AdminAlertRule", back_populates="events")


class Audit(Base):
    __tablename__ = "audits"
    __table_args__ = (
        Index("ix_audits_user_id_created_at", "user_id", "created_at"),
        Index("ix_audits_site_id_created_at", "site_id", "created_at"),
        Index("ix_audits_project_id_created_at", "project_id", "created_at"),
        Index("ix_audits_target_type_created_at", "audit_target_type", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    # Legacy linkage retained for backwards compatibility during migration to workspace/project model.
    user_id = Column(Integer, ForeignKey("users.id"), index=True)
    site_id = Column(Integer, ForeignKey("sites.id"), index=True, nullable=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="SET NULL"), index=True, nullable=True
    )
    # SIGV2-1117: "project" when this audit measures the linked project's own
    # target, "competitor" when it measures a competitor benchmarked for that
    # project. NULL means unclassified and is never read as the project's own.
    # SIGV2-1121: deliberately no default and no server_default. A write path
    # declares the scope (services.project_audit_scope.declare_audit_project_scope);
    # one that declares nothing writes NULL and is excluded from the project's
    # scores, instead of silently passing as the project's own.
    project_scope = Column(String, nullable=True)
    audit_type = Column(
        "type",
        Enum(AuditType, name="audit_type", native_enum=False),
        nullable=False,
        default=AuditType.FAST,
        server_default=AuditType.FAST.value,
    )
    audit_target_type = Column(
        Enum(AuditTargetType, name="audit_target_type", native_enum=False),
        nullable=False,
        default=AuditTargetType.WEBSITE,
        server_default=AuditTargetType.WEBSITE.name,
        index=True,
    )
    target_name = Column(String, nullable=True)
    target_url = Column(String, nullable=True)
    target_metadata = Column(JSON, nullable=False, default=dict, server_default="{}")
    url = Column(String, nullable=True)
    geo_score = Column(Float, nullable=False)
    seo_score = Column(Float, nullable=True)
    aeo_score = Column(Float, nullable=True)
    full_report = Column(JSON, nullable=True)
    request_id = Column(String, nullable=True, index=True)
    intent = Column(String, nullable=True, index=True)
    query_type = Column(String, nullable=True, index=True)
    query_category = Column(String, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), index=True)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=True
    )
    sanitized_at = Column(DateTime(timezone=True), nullable=True)
    report_archive_uri = Column(String, nullable=True)
    report_archived_at = Column(DateTime(timezone=True), nullable=True)
    is_pinned = Column(Boolean, nullable=False, default=False, server_default="false")
    share_token = Column(String, nullable=True, unique=True, index=True)
    # NULL means "no expiry recorded": a share token minted before SIGV2-1250,
    # which stays valid until it is rotated. Tokens minted since carry their
    # own deadline.
    share_token_expires_at = Column(DateTime(timezone=True), nullable=True)
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    user = relationship("User", back_populates="audits")
    site = relationship("Site", back_populates="audits")
    project = relationship("Project", back_populates="audits")
    entity_facts = relationship(
        "SiteEntityFact", back_populates="audit", cascade="all, delete-orphan"
    )
    jira_exports = relationship("ProjectJiraExport", back_populates="audit")
    sourced_project_tasks = relationship(
        "ProjectTask",
        back_populates="source_audit",
        foreign_keys="ProjectTask.source_audit_id",
    )
    verified_project_tasks = relationship(
        "ProjectTask",
        back_populates="verification_audit",
        foreign_keys="ProjectTask.verification_audit_id",
    )
    annotations = relationship(
        "ReportAnnotation",
        back_populates="audit",
        cascade="all, delete-orphan",
        order_by="ReportAnnotation.created_at.asc()",
    )
    claim_review_decisions = relationship(
        "ClaimReviewDecision",
        back_populates="audit",
        cascade="all, delete-orphan",
        order_by="ClaimReviewDecision.reviewed_at.desc()",
    )
    debate_traces = relationship(
        "DebateTrace",
        back_populates="audit",
        cascade="all, delete-orphan",
        order_by="DebateTrace.created_at.asc()",
    )
    signal_audit_snapshots = relationship(
        "SignalAuditSnapshot",
        back_populates="audit",
        cascade="all, delete-orphan",
    )
    signal_debate_agent_facts = relationship(
        "SignalDebateAgentFact",
        back_populates="audit",
        cascade="all, delete-orphan",
    )
    signal_claim_disposition_facts = relationship(
        "SignalClaimDispositionFact",
        back_populates="audit",
        cascade="all, delete-orphan",
    )
    signal_entity_observations = relationship(
        "SignalEntityObservation",
        back_populates="audit",
        cascade="all, delete-orphan",
    )
    remediation_before_outcomes = relationship(
        "SignalRemediationOutcome",
        foreign_keys="SignalRemediationOutcome.audit_before_id",
        back_populates="audit_before",
    )
    remediation_after_outcomes = relationship(
        "SignalRemediationOutcome",
        foreign_keys="SignalRemediationOutcome.audit_after_id",
        back_populates="audit_after",
    )


class ReportAnnotation(Base):
    __tablename__ = "report_annotations"
    __table_args__ = (
        Index("ix_report_annotations_audit_created", "audit_id", "created_at"),
        Index("ix_report_annotations_project_visibility", "project_id", "visibility"),
        Index("ix_report_annotations_parent_id", "parent_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    audit_id = Column(
        Integer, ForeignKey("audits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    parent_id = Column(
        Integer,
        ForeignKey("report_annotations.id", ondelete="CASCADE"),
        nullable=True,
    )
    section_path = Column(String, nullable=True)
    source_recommendation_key = Column(String, nullable=True)
    content = Column(Text, nullable=False)
    visibility = Column(
        Enum(AnnotationVisibility, name="annotation_visibility", native_enum=False),
        nullable=False,
        default=AnnotationVisibility.INTERNAL,
        server_default=AnnotationVisibility.INTERNAL.name,
    )
    is_deleted = Column(Boolean, nullable=False, default=False, server_default="false")
    schema_version = Column(String, nullable=False, default="1", server_default="1")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    audit = relationship("Audit", back_populates="annotations")
    project = relationship("Project", back_populates="report_annotations")
    author = relationship(
        "User",
        back_populates="authored_report_annotations",
        foreign_keys=[user_id],
    )
    parent = relationship(
        "ReportAnnotation",
        remote_side=[id],
        back_populates="replies",
        foreign_keys=[parent_id],
    )
    replies = relationship(
        "ReportAnnotation",
        back_populates="parent",
        cascade="all, delete-orphan",
        order_by="ReportAnnotation.created_at.asc()",
    )


class ClaimReviewDecision(Base):
    __tablename__ = "claim_review_decisions"
    __table_args__ = (
        UniqueConstraint("audit_id", "claim_id", name="uq_claim_review_audit_claim"),
        Index("ix_claim_review_project_audit", "project_id", "audit_id"),
        Index("ix_claim_review_reviewer_id", "reviewed_by_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    audit_id = Column(
        Integer, ForeignKey("audits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    claim_id = Column(String(64), nullable=False)
    claim_domain = Column(String(16), nullable=False)
    claim_text = Column(Text, nullable=False)
    original_disposition = Column(String(32), nullable=False)
    review_disposition = Column(String(32), nullable=False)
    review_note = Column(Text, nullable=True)
    reviewed_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    reviewed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    audit = relationship("Audit", back_populates="claim_review_decisions")
    project = relationship("Project", back_populates="claim_review_decisions")
    reviewed_by = relationship(
        "User",
        back_populates="reviewed_claim_decisions",
        foreign_keys=[reviewed_by_id],
    )


class DebateTrace(Base):
    __tablename__ = "debate_traces"
    __table_args__ = (
        Index("ix_debate_trace_audit_layer", "audit_id", "agent_layer"),
        Index("ix_debate_trace_audit_role", "audit_id", "agent_role"),
    )

    id = Column(Integer, primary_key=True, index=True)
    audit_id = Column(
        Integer, ForeignKey("audits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    agent_role = Column(String(64), nullable=False)
    agent_layer = Column(Integer, nullable=False, default=0, server_default="0")
    pipeline_type = Column(String(32), nullable=False)
    provider = Column(String(32), nullable=False)
    model = Column(String(128), nullable=False)
    input_payload_hash = Column(String(64), nullable=False)
    input_payload_chars = Column(Integer, nullable=False, default=0, server_default="0")
    input_summary = Column(Text, nullable=True)
    input_payload_raw = Column(EncryptedText(), nullable=False)
    output_raw = Column(EncryptedText(), nullable=False)
    output_claim_ledger = Column(JSON, nullable=True)
    latency_ms = Column(Integer, nullable=False, default=0, server_default="0")
    cost_usd = Column(Float, nullable=True)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    status = Column(String(16), nullable=False, default="completed", server_default="completed")
    error_message = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    audit = relationship("Audit", back_populates="debate_traces")


class ProjectTask(Base):
    __tablename__ = "project_tasks"
    __table_args__ = (
        Index("ix_project_tasks_project_status_sort", "project_id", "status", "sort_order"),
        Index("ix_project_tasks_project_created", "project_id", "created_at"),
        Index("ix_project_tasks_source_key", "project_id", "source_recommendation_key"),
        Index("ix_project_tasks_assigned_to", "assigned_to_user_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    source_audit_id = Column(
        Integer,
        ForeignKey("audits.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    verification_audit_id = Column(
        Integer,
        ForeignKey("audits.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    assigned_to_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title = Column(String, nullable=False)
    description = Column(Text, nullable=True)
    status = Column(
        Enum(ProjectTaskStatus, name="project_task_status", native_enum=False),
        nullable=False,
        default=ProjectTaskStatus.TODO,
        server_default=ProjectTaskStatus.TODO.name,
    )
    priority = Column(
        Enum(ProjectTaskPriority, name="project_task_priority", native_enum=False),
        nullable=False,
        default=ProjectTaskPriority.MEDIUM,
        server_default=ProjectTaskPriority.MEDIUM.name,
    )
    origin = Column(
        Enum(ProjectTaskOrigin, name="project_task_origin", native_enum=False),
        nullable=False,
        default=ProjectTaskOrigin.MANUAL,
        server_default=ProjectTaskOrigin.MANUAL.name,
    )
    resolution_source = Column(
        Enum(ProjectTaskResolutionSource, name="project_task_resolution_source", native_enum=False),
        nullable=True,
    )
    category = Column(String, nullable=False, default="General", server_default="General")
    source_recommendation_key = Column(String, nullable=True)
    due_date = Column(Date, nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    verified_at = Column(DateTime(timezone=True), nullable=True)
    sort_order = Column(Integer, nullable=False, default=0, server_default="0")
    schema_version = Column(String, nullable=False, default="1", server_default="1")
    metadata_json = Column("metadata", JSON, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    project = relationship("Project", back_populates="tasks")
    source_audit = relationship(
        "Audit",
        back_populates="sourced_project_tasks",
        foreign_keys=[source_audit_id],
    )
    verification_audit = relationship(
        "Audit",
        back_populates="verified_project_tasks",
        foreign_keys=[verification_audit_id],
    )
    assigned_to_user = relationship(
        "User",
        back_populates="assigned_project_tasks",
        foreign_keys=[assigned_to_user_id],
    )
    created_by_user = relationship(
        "User",
        back_populates="created_project_tasks",
        foreign_keys=[created_by_user_id],
    )
    signal_remediation_outcomes = relationship(
        "SignalRemediationOutcome",
        back_populates="project_task",
        cascade="all, delete-orphan",
    )
    cms_deployment_logs = relationship(
        "CMSDeploymentLog",
        back_populates="project_task",
    )


class ScheduledAudit(Base):
    __tablename__ = "scheduled_audits"
    __table_args__ = (
        CheckConstraint(
            "(project_id IS NOT NULL) OR (site_id IS NOT NULL)",
            name="ck_scheduled_audits_target",
        ),
        Index("ix_scheduled_audits_user_id_is_active", "user_id", "is_active"),
        Index("ix_scheduled_audits_is_active_next_run", "is_active", "next_run_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), index=True, nullable=True
    )
    site_id = Column(Integer, ForeignKey("sites.id", ondelete="CASCADE"), index=True, nullable=True)
    audit_type = Column(
        "type",
        Enum(AuditType, name="audit_type", native_enum=False),
        nullable=False,
        default=AuditType.STANDARD,
        server_default=AuditType.STANDARD.value,
    )
    url = Column(String, nullable=True)
    frequency = Column(
        Enum(
            ScheduledAuditFrequency,
            name="scheduled_audit_frequency",
            native_enum=False,
        ),
        nullable=False,
        default=ScheduledAuditFrequency.WEEKLY,
        server_default=ScheduledAuditFrequency.WEEKLY.name,
    )
    audit_params = Column(JSON, nullable=False, default=dict, server_default="{}")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    next_run_at = Column(DateTime(timezone=True), nullable=False, index=True)
    last_run_at = Column(DateTime(timezone=True), nullable=True)
    paused_reason = Column(
        Enum(
            ScheduledAuditPauseReason,
            name="scheduled_audit_pause_reason",
            native_enum=False,
        ),
        nullable=True,
    )
    last_run_status = Column(
        Enum(
            ScheduledAuditRunStatus,
            name="scheduled_audit_run_status",
            native_enum=False,
        ),
        nullable=True,
    )
    last_job_id = Column(String, nullable=True, index=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    user = relationship("User", back_populates="scheduled_audits")
    project = relationship("Project", back_populates="scheduled_audits")
    site = relationship("Site", back_populates="scheduled_audits")


class Site(Base):
    __tablename__ = "sites"
    __table_args__ = (UniqueConstraint("user_id", "domain", name="uq_sites_user_domain"),)

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    domain = Column(String, nullable=False, index=True)
    display_name = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    user = relationship("User", back_populates="sites")
    audits = relationship("Audit", back_populates="site")
    entity_facts = relationship(
        "SiteEntityFact", back_populates="site", cascade="all, delete-orphan"
    )
    competitors = relationship(
        "Site",
        secondary=site_competitors,
        primaryjoin=id == site_competitors.c.site_id,
        secondaryjoin=id == site_competitors.c.competitor_site_id,
        back_populates="competing_against",
        lazy="selectin",
    )
    competing_against = relationship(
        "Site",
        secondary=site_competitors,
        primaryjoin=id == site_competitors.c.competitor_site_id,
        secondaryjoin=id == site_competitors.c.site_id,
        back_populates="competitors",
        lazy="selectin",
    )
    scheduled_audits = relationship(
        "ScheduledAudit",
        back_populates="site",
        cascade="all, delete-orphan",
    )


class Subscription(Base):
    __tablename__ = "subscriptions"
    __table_args__ = (
        CheckConstraint(
            f"plan_type IN ({', '.join(repr(plan) for plan in CANONICAL_PLAN_TYPES)})",
            name="ck_subscriptions_plan_type_canonical",
        ),
        CheckConstraint(
            "stripe_mode IS NULL OR stripe_mode IN ('test', 'live')",
            name="ck_subscriptions_stripe_mode",
        ),
        CheckConstraint(
            "(stripe_schedule_id IS NULL AND pending_plan_type IS NULL "
            "AND pending_billing_interval IS NULL "
            "AND pending_change_effective_at IS NULL) OR "
            "(stripe_schedule_id IS NOT NULL AND pending_plan_type IS NOT NULL "
            "AND pending_billing_interval IS NOT NULL "
            "AND pending_change_effective_at IS NOT NULL)",
            name="ck_subscriptions_pending_change_complete_set",
        ),
        CheckConstraint(
            "pending_plan_type IS NULL OR pending_plan_type IN "
            "('plan_starter', 'plan_standard', 'plan_specialist', 'plan_executive')",
            name="ck_subscriptions_pending_plan_type",
        ),
        CheckConstraint(
            "pending_billing_interval IS NULL OR " "pending_billing_interval IN ('month', 'year')",
            name="ck_subscriptions_pending_billing_interval",
        ),
        UniqueConstraint("user_id", name="uq_subscriptions_user_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"))
    stripe_customer_id = Column(String, unique=True, index=True, nullable=False)
    stripe_subscription_id = Column(String, unique=True, index=True, nullable=True)
    stripe_mode = Column(String(8), nullable=True)
    stripe_schedule_id = Column(String(255), nullable=True)
    managed_plan_change_schedule_id = Column(String(255), nullable=True)
    pending_plan_type = Column(String, nullable=True)
    pending_billing_interval = Column(String(8), nullable=True)
    pending_change_effective_at = Column(DateTime(timezone=True), nullable=True)
    plan_state_event_created_at = Column(DateTime(timezone=True), nullable=True)
    current_period_end = Column(DateTime(timezone=True), nullable=True)
    cancel_at_period_end = Column(Boolean, default=False, nullable=False)
    plan_type = Column(
        String, nullable=False
    )  # normalized: plan_standard/plan_specialist/plan_executive
    status = Column(String, nullable=False)  # active, canceled, etc.
    billing_interval = Column(
        String, nullable=False, default="month", server_default="month"
    )  # month or year
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    user = relationship("User", back_populates="subscription")

    @validates("plan_type")
    def _validate_plan_type(self, _key: str, value: object) -> str:
        if not isinstance(value, str) or value not in CANONICAL_PLAN_TYPES:
            raise ValueError("Subscription plan_type must be an exact canonical plan ID.")
        return value


class BaseCheckoutAttempt(Base):
    __tablename__ = "base_checkout_attempts"
    __table_args__ = (
        CheckConstraint(
            "stripe_mode IN ('test', 'live')",
            name="ck_base_checkout_attempts_stripe_mode",
        ),
        CheckConstraint(
            "target_plan IN ('plan_starter', 'plan_standard', 'plan_specialist', "
            "'plan_executive')",
            name="ck_base_checkout_attempts_target_plan",
        ),
        CheckConstraint(
            "billing_interval IN ('month', 'year')",
            name="ck_base_checkout_attempts_billing_interval",
        ),
        CheckConstraint(
            "status IN ('pending', 'customer_created', 'session_created', "
            "'completed', 'expired', 'failed', 'canceled')",
            name="ck_base_checkout_attempts_status",
        ),
        CheckConstraint(
            "(status = 'pending' AND stripe_customer_id IS NULL "
            "AND stripe_session_id IS NULL AND completed_at IS NULL) OR "
            "(status = 'customer_created' AND stripe_customer_id IS NOT NULL "
            "AND stripe_session_id IS NULL AND completed_at IS NULL) OR "
            "(status = 'session_created' AND stripe_customer_id IS NOT NULL "
            "AND stripe_session_id IS NOT NULL AND completed_at IS NULL) OR "
            "(status = 'completed' AND stripe_customer_id IS NOT NULL "
            "AND stripe_session_id IS NOT NULL AND completed_at IS NOT NULL) OR "
            "(status IN ('expired', 'failed', 'canceled') AND completed_at IS NULL)",
            name="ck_base_checkout_attempts_state_consistency",
        ),
        Index(
            "uq_base_checkout_attempts_active_user_mode",
            "user_id",
            "stripe_mode",
            unique=True,
            postgresql_where=text("status IN ('pending', 'customer_created', 'session_created')"),
            sqlite_where=text("status IN ('pending', 'customer_created', 'session_created')"),
        ),
        Index(
            "ix_base_checkout_attempts_user_mode_status",
            "user_id",
            "stripe_mode",
            "status",
        ),
        Index("ix_base_checkout_attempts_status_expires_at", "status", "expires_at"),
    )

    id = Column(String(64), primary_key=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    stripe_mode = Column(String(8), nullable=False)
    target_plan = Column(String, nullable=False)
    billing_interval = Column(String(8), nullable=False)
    status = Column(String(32), nullable=False, default="pending", server_default="pending")
    stripe_customer_id = Column(String(255), nullable=True)
    stripe_session_id = Column(String(255), unique=True, nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    user = relationship("User", back_populates="base_checkout_attempts")


class CreditCommitment(Base):
    __tablename__ = "credit_commitments"
    __table_args__ = (
        CheckConstraint(
            "stripe_mode IS NULL OR stripe_mode IN ('test', 'live')",
            name="ck_credit_commitments_stripe_mode",
        ),
        Index("ix_credit_commitments_user_status", "user_id", "status"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    tier = Column(String, nullable=False, index=True)
    committed_credits = Column(Integer, nullable=False)
    rate_per_credit = Column(Numeric(10, 4), nullable=False)
    # monthly_fee_usd and pending_monthly_fee_usd hold major units of
    # billing.config.BILLING_CURRENCY, which is USD. The _usd suffix is
    # accurate: Stripe charges these amounts on USD prices. Do not render
    # either column with a currency other than USD (SIGV2-1133).
    monthly_fee_usd = Column(Numeric(10, 2), nullable=False)
    overage_rate = Column(Numeric(10, 4), nullable=False, default="0.0100", server_default="0.0100")
    stripe_subscription_id = Column(String, unique=True, index=True, nullable=False)
    stripe_mode = Column(String(8), nullable=True)
    stripe_commitment_subscription_item_id = Column(String, nullable=True)
    stripe_overage_subscription_item_id = Column(String, nullable=True)
    status = Column(String, nullable=False, default="active", server_default="active", index=True)
    cancel_at_period_end = Column(Boolean, nullable=False, default=False, server_default="false")
    current_cycle_start = Column(DateTime(timezone=True), nullable=True)
    current_cycle_end = Column(DateTime(timezone=True), nullable=True)
    pending_tier = Column(String, nullable=True)
    pending_committed_credits = Column(Integer, nullable=True)
    pending_rate_per_credit = Column(Numeric(10, 4), nullable=True)
    pending_monthly_fee_usd = Column(Numeric(10, 2), nullable=True)
    pending_change_effective_at = Column(DateTime(timezone=True), nullable=True)
    canceled_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    user = relationship("User", back_populates="credit_commitment")
    usage_cycles = relationship(
        "CommitmentUsageCycle",
        back_populates="commitment",
        cascade="all, delete-orphan",
        order_by="CommitmentUsageCycle.cycle_start.desc()",
    )


class CommitmentUsageCycle(Base):
    __tablename__ = "commitment_usage_cycles"
    __table_args__ = (
        Index("ix_commitment_cycles_active", "commitment_id", "status"),
        UniqueConstraint("commitment_id", "cycle_start", name="uq_commitment_cycle_start"),
    )

    id = Column(Integer, primary_key=True, index=True)
    commitment_id = Column(
        Integer,
        ForeignKey("credit_commitments.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    cycle_start = Column(DateTime(timezone=True), nullable=False)
    cycle_end = Column(DateTime(timezone=True), nullable=False)
    committed_credits = Column(Integer, nullable=False)
    credits_used = Column(Integer, nullable=False, default=0, server_default="0")
    overage_credits = Column(Integer, nullable=False, default=0, server_default="0")
    overage_reported = Column(Boolean, nullable=False, default=False, server_default="false")
    warning_sent_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String, nullable=False, default="active", server_default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    commitment = relationship("CreditCommitment", back_populates="usage_cycles")
    user = relationship("User", back_populates="commitment_usage_cycles")


class OperationalSetting(Base):
    __tablename__ = "operational_settings"

    id = Column(Integer, primary_key=True, index=True)
    fallback_model_enabled = Column(Boolean, default=False, nullable=False)
    pricing_v2_enabled = Column(Boolean, default=True, nullable=False, server_default="true")
    credit_engine_v2_enabled = Column(Boolean, default=True, nullable=False, server_default="true")
    pricing_v2_shadow_mode = Column(Boolean, default=False, nullable=False, server_default="false")
    pricing_v3_shadow_mode = Column(Boolean, default=False, nullable=False, server_default="false")
    report_retention_days = Column(Integer, nullable=False, default=30, server_default="30")
    cache_refresh_requested_at = Column(DateTime(timezone=True), nullable=True)
    admin_settings_payload = Column(JSON, nullable=True)

    # Maintenance mode flags
    maintenance_mode = Column(Boolean, default=False, nullable=False, server_default="false")
    maintenance_message = Column(Text, nullable=True)
    maintenance_allowed_ips = Column(JSON, nullable=True)
    maintenance_scheduled_start = Column(DateTime(timezone=True), nullable=True)
    maintenance_scheduled_end = Column(DateTime(timezone=True), nullable=True)


class StripeEventLog(Base):
    __tablename__ = "stripe_event_log"
    __table_args__ = (
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_stripe_event_log_attempt_count_nonnegative",
        ),
        CheckConstraint(
            "processing_status IN ('pending', 'processing', 'failed', 'processed', 'dead_letter')",
            name="ck_stripe_event_log_processing_status",
        ),
        CheckConstraint(
            "(processing_status = 'pending' AND claim_token IS NULL AND claimed_at IS NULL "
            "AND next_attempt_at IS NULL AND processed_at IS NULL AND dead_lettered_at IS NULL) OR "
            "(processing_status = 'failed' AND claim_token IS NULL AND claimed_at IS NULL "
            "AND next_attempt_at IS NOT NULL AND processed_at IS NULL AND dead_lettered_at IS NULL) OR "
            "(processing_status = 'processing' AND claim_token IS NOT NULL "
            "AND claimed_at IS NOT NULL AND next_attempt_at IS NULL "
            "AND processed_at IS NULL AND dead_lettered_at IS NULL) OR "
            "(processing_status = 'processed' AND claim_token IS NULL AND claimed_at IS NULL "
            "AND next_attempt_at IS NULL AND processed_at IS NOT NULL AND dead_lettered_at IS NULL) OR "
            "(processing_status = 'dead_letter' AND claim_token IS NULL AND claimed_at IS NULL "
            "AND next_attempt_at IS NULL AND processed_at IS NULL AND dead_lettered_at IS NOT NULL)",
            name="ck_stripe_event_log_state_consistency",
        ),
        Index(
            "ix_stripe_event_log_status_next_attempt",
            "processing_status",
            "next_attempt_at",
        ),
        Index(
            "ix_stripe_event_log_status_claimed_at",
            "processing_status",
            "claimed_at",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    event_id = Column(String, unique=True, index=True, nullable=False)
    event_type = Column(String, nullable=False)
    event_created_at = Column(DateTime(timezone=True), nullable=False)
    payload = Column(JSON, nullable=False)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    processing_status = Column(String, nullable=False, server_default="pending")
    last_error = Column(Text, nullable=True)
    claim_token = Column(String(64), nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    next_attempt_at = Column(DateTime(timezone=True), nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    dead_lettered_at = Column(DateTime(timezone=True), nullable=True)


class StripeCommandOutbox(Base):
    __tablename__ = "stripe_command_outbox"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending', 'processing', 'failed', 'succeeded', 'dead_letter')",
            name="ck_stripe_command_outbox_status",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_stripe_command_outbox_attempt_count_nonnegative",
        ),
        CheckConstraint(
            "stripe_mode IN ('test', 'live')",
            name="ck_stripe_command_outbox_stripe_mode",
        ),
        CheckConstraint(
            "(status = 'pending' AND claim_token IS NULL AND claimed_at IS NULL "
            "AND next_attempt_at IS NULL AND processed_at IS NULL AND dead_lettered_at IS NULL) OR "
            "(status = 'processing' AND claim_token IS NOT NULL AND claimed_at IS NOT NULL "
            "AND next_attempt_at IS NULL AND processed_at IS NULL AND dead_lettered_at IS NULL) OR "
            "(status = 'failed' AND claim_token IS NULL AND claimed_at IS NULL "
            "AND next_attempt_at IS NOT NULL AND processed_at IS NULL AND dead_lettered_at IS NULL) OR "
            "(status = 'succeeded' AND claim_token IS NULL AND claimed_at IS NULL "
            "AND next_attempt_at IS NULL AND processed_at IS NOT NULL AND dead_lettered_at IS NULL) OR "
            "(status = 'dead_letter' AND claim_token IS NULL AND claimed_at IS NULL "
            "AND next_attempt_at IS NULL AND processed_at IS NULL AND dead_lettered_at IS NOT NULL)",
            name="ck_stripe_command_outbox_state_consistency",
        ),
        UniqueConstraint(
            "idempotency_key",
            name="uq_stripe_command_outbox_idempotency_key",
        ),
        Index(
            "ix_stripe_command_outbox_status_next_attempt",
            "status",
            "next_attempt_at",
        ),
    )

    id = Column(Integer, primary_key=True)
    idempotency_key = Column(String(255), nullable=False)
    command_type = Column(String(64), nullable=False)
    stripe_mode = Column(String(8), nullable=False)
    payload = Column(JSON, nullable=False)
    status = Column(String(32), nullable=False, default="pending", server_default="pending")
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    claim_token = Column(String(64), nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    next_attempt_at = Column(DateTime(timezone=True), nullable=True)
    processed_at = Column(DateTime(timezone=True), nullable=True)
    dead_lettered_at = Column(DateTime(timezone=True), nullable=True)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class BillingPayment(Base):
    """An issued invoice. A statutory tax record, not account data (SIGV2-1144).

    `user_id` is nullable because the row has to outlive the account. On
    account deletion it is set to NULL and the account id is kept in
    `former_user_id`, a plain integer with no relationship, so the invoice
    stays complete and readable without pointing at a living customer
    identity. See app/services/billing_retention.py for the retention clock
    and the law it implements.
    """

    __tablename__ = "billing_payments"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    stripe_invoice_id = Column(String, unique=True, index=True, nullable=False)
    stripe_customer_id = Column(String, nullable=False, index=True)
    stripe_subscription_id = Column(String, nullable=True, index=True)
    amount_paid = Column(Integer, nullable=True)
    amount_due = Column(Integer, nullable=True)
    currency = Column(String, nullable=True)
    status = Column(String, nullable=True)
    hosted_invoice_url = Column(String, nullable=True)
    invoice_pdf = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), nullable=False)
    # Retained after the account is gone: the account id as a bare reference,
    # and the recipient identity the tax invoice itself carries.
    former_user_id = Column(Integer, nullable=True, index=True)
    invoice_customer_name = Column(String, nullable=True)
    invoice_customer_email = Column(String, nullable=True)
    # The statutory clock, per row, measured from the end of the Tax Period the
    # invoice relates to. `retention_hold` keeps the row beyond that date while
    # an audit, a dispute or a Voluntary Disclosure is open.
    retention_until = Column(DateTime(timezone=True), nullable=True, index=True)
    retention_hold = Column(Boolean, nullable=True, default=False, server_default="false")
    retention_hold_reason = Column(String, nullable=True)
    anonymized_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="billing_payments")


class AccountDeletionReceipt(Base):
    """Evidence that an account deletion request was honoured (SIGV2-1144).

    Deliberately holds no foreign key to `users`: it exists precisely because
    the user row is gone, and the account settings copy promises the customer
    "a record that the deletion happened, so we can show we honoured your
    request". The subject is identified by a SHA-256 fingerprint of the
    normalised email address rather than the address itself, so the receipt can
    confirm a specific request without retaining the personal data that the
    request asked us to erase.
    """

    __tablename__ = "account_deletion_receipts"
    __table_args__ = (
        UniqueConstraint("reference", name="uq_account_deletion_receipts_reference"),
        CheckConstraint(
            "initiated_by IN ('self_service', 'admin')",
            name="ck_account_deletion_receipts_initiated_by",
        ),
        Index(
            "ix_account_deletion_receipts_fingerprint",
            "subject_email_fingerprint",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    reference = Column(String(64), nullable=False)
    former_user_id = Column(Integer, nullable=False, index=True)
    subject_email_fingerprint = Column(String(64), nullable=False)
    requested_at = Column(DateTime(timezone=True), nullable=False)
    completed_at = Column(DateTime(timezone=True), nullable=False)
    initiated_by = Column(String(32), nullable=False)
    initiated_by_admin_user_id = Column(Integer, nullable=True)
    erased_record_counts = Column(JSON, nullable=False, default=dict, server_default="{}")
    retained_billing_payment_count = Column(Integer, nullable=False, default=0, server_default="0")
    retained_until = Column(DateTime(timezone=True), nullable=True)
    retention_basis = Column(String, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class EmailOutbox(Base):
    __tablename__ = "email_outbox"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=True, index=True)
    to_email = Column(String, nullable=False)
    from_name = Column(String, nullable=True)
    reply_to = Column(String, nullable=True)
    subject = Column(String, nullable=False)
    html_body = Column(Text, nullable=True)
    text_body = Column(Text, nullable=True)
    category = Column(String, nullable=True, index=True)
    template_key = Column(String, nullable=True, index=True)
    correlation_id = Column(String, nullable=True, index=True)
    status = Column(String, nullable=False, index=True, default="pending")
    provider = Column(String, nullable=True)
    attempts = Column(Integer, nullable=False, default=0)
    last_error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    sent_at = Column(DateTime(timezone=True), nullable=True)

    user = relationship("User", back_populates="email_outbox_entries")


class SiteEntityFact(Base):
    __tablename__ = "site_entity_facts"
    __table_args__ = (
        Index("ix_site_entity_facts_site_id_entity_key", "site_id", "entity_key"),
        Index("ix_site_entity_facts_site_id_created_at", "site_id", "created_at"),
        Index(
            "ix_site_entity_facts_site_id_category_created_at",
            "site_id",
            "entity_category",
            "created_at",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    site_id = Column(
        Integer, ForeignKey("sites.id", ondelete="CASCADE"), nullable=False, index=True
    )
    audit_id = Column(
        Integer, ForeignKey("audits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    entity_name = Column(String, nullable=False)
    entity_key = Column(String, nullable=False)
    entity_category = Column(String, nullable=False, server_default="Unknown")
    relevance_score = Column(Float, nullable=True)
    ai_importance = Column(Float, nullable=True)
    source = Column(String, nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )

    site = relationship("Site", back_populates="entity_facts")
    audit = relationship("Audit", back_populates="entity_facts")


class ComplexReportJob(Base):
    __tablename__ = "complex_report_jobs"

    id = Column(String, primary_key=True, index=True)
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    status = Column(String, nullable=False, default="queued", index=True)
    file_path = Column(String, nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    last_heartbeat = Column(DateTime(timezone=True), nullable=True)
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    max_attempts = Column(Integer, nullable=False, default=3, server_default="3")
    export_manifest = Column(JSON, nullable=True)
    # Report library columns. `name` is resolved once at enqueue and frozen:
    # deriving it on read would silently rewrite the name of every historical
    # report the day the naming format changes. `period_start`/`period_end`
    # record the interval the customer actually asked for, both NULL meaning
    # "all time" (never inferred from the selected audits, which would be a
    # different claim). `file_size_bytes` is written by the PDF worker from the
    # artifact it uploaded, so the library never sizes files on read.
    name = Column(String, nullable=True)
    period_start = Column(DateTime(timezone=True), nullable=True)
    period_end = Column(DateTime(timezone=True), nullable=True)
    file_size_bytes = Column(Integer, nullable=True)

    user = relationship("User")


class AuditJob(Base):
    __tablename__ = "audit_jobs"

    id = Column(String, primary_key=True, index=True)  # UUID string
    user_id = Column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    api_key_id = Column(
        Integer, ForeignKey("api_keys.id", ondelete="SET NULL"), nullable=True, index=True
    )
    embed_api_key_id = Column(
        Integer,
        ForeignKey("embed_api_keys.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="SET NULL"), nullable=True, index=True
    )
    sitemap_crawl_job_id = Column(
        String,
        ForeignKey("sitemap_crawl_jobs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    status = Column(String, nullable=False, default="queued", index=True)
    source = Column(
        String, nullable=False, default="internal", server_default="internal", index=True
    )
    url = Column(String, nullable=False)
    audit_target_type = Column(
        Enum(AuditTargetType, name="audit_target_type", native_enum=False),
        nullable=False,
        default=AuditTargetType.WEBSITE,
        server_default=AuditTargetType.WEBSITE.name,
        index=True,
    )
    target_name = Column(String, nullable=True)
    target_url = Column(String, nullable=True)
    target_metadata = Column(JSON, nullable=False, default=dict, server_default="{}")
    provider = Column(String, nullable=True)
    tier = Column(String, nullable=True)
    estimated_credit_cost = Column(Integer, nullable=True)
    consumed_credit_cost = Column(Integer, nullable=True)
    idempotency_key_hash = Column(String, nullable=True, index=True)
    webhook_url = Column(String, nullable=True)
    webhook_secret = Column(EncryptedText, nullable=True)
    webhook_status = Column(String, nullable=True)
    webhook_attempts = Column(Integer, nullable=False, default=0, server_default="0")
    webhook_last_error = Column(Text, nullable=True)
    webhook_delivered_at = Column(DateTime(timezone=True), nullable=True)
    error = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    last_heartbeat = Column(DateTime(timezone=True), nullable=True)
    request_id = Column(String, nullable=True, index=True)
    # SIGV2-1129: "customer" when the customer launched this scan, which is what
    # the scan allowance bills; "competitor_refresh" when Signal launched it to
    # populate the competitor comparison the customer's plan already includes,
    # which is never one of their scans.
    #
    # Deliberately no default and no server_default, matching Audit.project_scope
    # (SIGV2-1121). NULL means the write path declared nothing, so the job is
    # not proven to be the customer's own scan and is not billed. That
    # under-counts rather than billing a customer for work they did not ask for,
    # and scan_allowance_service logs every unclassified row it meets.
    #
    # Not indexed: the allowance count is already selective on the indexed
    # (user_id, created_at) pair and this column only narrows that window.
    scan_origin = Column(String, nullable=True)

    user = relationship("User")
    api_key = relationship("ApiKey", back_populates="audit_jobs")
    embed_api_key = relationship("EmbedApiKey", back_populates="audit_jobs")
    project = relationship("Project")
    sitemap_crawl_job = relationship("SitemapCrawlJob", back_populates="audit_jobs")
    leads = relationship("Lead", back_populates="audit_job")


class AuditTierDurationStat(Base):
    """One row per selectable depth, holding the measured duration aggregate.

    SIGV2-1177. The figures the product states per depth are derived here from
    completed ``audit_jobs`` runs instead of being held as a constant. The
    statistic, the exclusions and the thresholds are documented in
    ``services/tier_duration_stats_service.py``; this table only stores what
    that service computed, plus enough provenance for a reader to decide
    whether it may be published:

    * ``sample_size`` is recorded even when it is below ``min_sample_size``, so
      an operator can see how far a tier is from publishable.
    * ``p25_seconds`` / ``p50_seconds`` / ``p75_seconds`` are **NULL** until the
      sample clears the threshold. Storing the sample size without the
      quartiles is what stops a figure derived from three runs ever reaching a
      customer-facing surface by accident.
    * ``computed_at`` is what expires a row: the aggregate is recomputed by the
      hourly cron sweep, so a stale row is a broken sweep, and a stale figure
      is not served.

    One row per tier, enforced by the unique constraint: the sweep upserts
    rather than appending, because nothing reads a history of the aggregate and
    an append-only shape would need a "latest row" rule in every reader.
    """

    __tablename__ = "audit_tier_duration_stats"

    id = Column(Integer, primary_key=True, index=True)
    tier = Column(String, nullable=False, unique=True, index=True)

    sample_size = Column(Integer, nullable=False, default=0, server_default="0")
    window_days = Column(Integer, nullable=False, default=90, server_default="90")
    min_sample_size = Column(Integer, nullable=False, default=20, server_default="20")

    p25_seconds = Column(Float, nullable=True)
    p50_seconds = Column(Float, nullable=True)
    p75_seconds = Column(Float, nullable=True)

    computed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    schema_version = Column(String, nullable=False, default="1", server_default="1")


class VisibilityRunBatch(Base):
    __tablename__ = "visibility_run_batches"
    __table_args__ = (
        Index(
            "ix_visibility_run_batches_topic_provider_created", "topic", "provider", "created_at"
        ),
        Index(
            "ix_visibility_run_batches_project_target_created",
            "project_id",
            "target_domain",
            "created_at",
        ),
        Index(
            "ix_visibility_run_batches_project_topic_provider_created",
            "project_id",
            "topic",
            "provider",
            "created_at",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=True, index=True
    )
    topic = Column(String, nullable=False, index=True)
    provider = Column(String, nullable=False, index=True)
    target_domain = Column(String, nullable=True, index=True)
    schedule_key = Column(String, nullable=False, index=True)
    audit_job_id = Column(
        String, ForeignKey("audit_jobs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    status = Column(String, nullable=False, default="queued", index=True)
    score = Column(Float, nullable=True)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    project = relationship("Project", back_populates="visibility_run_batches")
    runs = relationship("VisibilityRun", back_populates="batch", cascade="all, delete-orphan")
    signal_citation_events = relationship(
        "SignalCitationEvent",
        back_populates="batch",
        cascade="all, delete-orphan",
    )
    daily_seed_query_runs = relationship(
        "DailySeedQueryRun",
        back_populates="batch",
        cascade="all, delete-orphan",
    )


class VisibilityRun(Base):
    __tablename__ = "visibility_runs"
    __table_args__ = (
        Index("ix_visibility_runs_batch_created", "batch_id", "created_at"),
        Index("ix_visibility_runs_topic_provider_created", "topic", "provider", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(
        Integer, ForeignKey("visibility_run_batches.id", ondelete="CASCADE"), nullable=False
    )
    topic = Column(String, nullable=False, index=True)
    provider = Column(String, nullable=False, index=True)
    target_domain = Column(String, nullable=True, index=True)
    prompt_template = Column(String, nullable=False)
    prompt = Column(Text, nullable=False)
    raw_response = Column(JSON, nullable=True)
    parsed_citations = Column(JSON, nullable=False, default=list)
    valid_citations = Column(JSON, nullable=False, default=list)
    score = Column(Float, nullable=True)
    status = Column(String, nullable=False, default="queued", index=True)
    error = Column(Text, nullable=True)
    started_at = Column(DateTime(timezone=True), nullable=True)
    completed_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    batch = relationship("VisibilityRunBatch", back_populates="runs")
    signal_citation_event = relationship(
        "SignalCitationEvent",
        back_populates="run",
        uselist=False,
        cascade="all, delete-orphan",
    )
    daily_seed_query_runs = relationship(
        "DailySeedQueryRun",
        back_populates="run",
        cascade="all, delete-orphan",
    )


class ProjectVisibilityQuery(Base):
    __tablename__ = "project_visibility_queries"
    __table_args__ = (
        UniqueConstraint(
            "project_id", "query_text", name="uq_project_visibility_queries_project_query"
        ),
        Index("ix_project_visibility_queries_project_active", "project_id", "is_active"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    query_text = Column(String, nullable=False)
    query_type = Column(String, nullable=False, default="aeo", server_default="aeo")
    # SIGV2-1186: the prompt's own customer-facing search type (one of
    # services.query_taxonomy.CANONICAL_SEARCH_TYPES). This is the value every
    # scoring path reads; the text-based classifier only pre-fills it.
    # Deliberately nullable with no default: a prompt written before this column
    # existed keeps NULL and falls back to the old inference
    # (query_taxonomy.resolve_search_type), rather than having a guess written
    # into the database as though the customer had chosen it.
    search_type = Column(String, nullable=True)
    # SIGV2-1186: "customer" for a prompt the customer wrote, "generated" for
    # one Signal generated as part of the project's base set, so a generated
    # prompt is attributable and the customer can tell it from their own.
    # NULL is read as the customer's own, which is the safe direction: nothing
    # of theirs is ever labelled as ours.
    origin = Column(String, nullable=True)
    providers = Column(JSON, nullable=False, default=list, server_default="[]")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    schema_version = Column(Integer, nullable=False, default=1, server_default="1")

    project = relationship("Project", back_populates="visibility_queries")


class GlobalVolatilitySeedQuery(Base):
    __tablename__ = "global_volatility_seed_queries"
    __table_args__ = (
        UniqueConstraint(
            "normalized_query",
            "industry",
            name="uq_global_volatility_seed_queries_query_industry",
        ),
        Index(
            "ix_global_volatility_seed_queries_active_industry",
            "is_active",
            "industry",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    query_text = Column(String, nullable=False)
    normalized_query = Column(String, nullable=False, index=True)
    industry = Column(String, nullable=False, default="general", server_default="general")
    priority_weight = Column(Float, nullable=False, default=1.0, server_default="1")
    is_active = Column(Boolean, nullable=False, default=True, server_default="true")
    source = Column(
        String, nullable=False, default="default_catalog", server_default="default_catalog"
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    daily_runs = relationship(
        "DailySeedQueryRun",
        back_populates="seed_query",
        cascade="all, delete-orphan",
    )


class DailySeedQueryRun(Base):
    __tablename__ = "daily_seed_query_runs"
    __table_args__ = (
        UniqueConstraint(
            "seed_query_id",
            "provider",
            "run_date",
            name="uq_daily_seed_query_runs_seed_provider_date",
        ),
        Index(
            "ix_daily_seed_query_runs_provider_date",
            "provider",
            "run_date",
        ),
        Index(
            "ix_daily_seed_query_runs_seed_date",
            "seed_query_id",
            "run_date",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    seed_query_id = Column(
        Integer,
        ForeignKey("global_volatility_seed_queries.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider = Column(String, nullable=False, index=True)
    run_date = Column(Date, nullable=False, index=True)
    visibility_run_batch_id = Column(
        Integer,
        ForeignKey("visibility_run_batches.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    visibility_run_id = Column(
        Integer,
        ForeignKey("visibility_runs.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    answer_text = Column(Text, nullable=True)
    answer_text_hash = Column(String, nullable=True, index=True)
    citations_hash = Column(String, nullable=True, index=True)
    citation_domains_json = Column(
        "citation_domains", JSON, nullable=False, default=list, server_default="[]"
    )
    citations_count = Column(Integer, nullable=False, default=0, server_default="0")
    answer_format = Column(String, nullable=False, default="unknown", server_default="unknown")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    seed_query = relationship("GlobalVolatilitySeedQuery", back_populates="daily_runs")
    batch = relationship("VisibilityRunBatch", back_populates="daily_seed_query_runs")
    run = relationship("VisibilityRun", back_populates="daily_seed_query_runs")


class GlobalVolatilitySnapshot(Base):
    __tablename__ = "global_volatility_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "snapshot_date",
            "provider",
            "industry",
            name="uq_global_volatility_snapshots_date_provider_industry",
        ),
        Index(
            "ix_global_volatility_snapshots_provider_date",
            "provider",
            "snapshot_date",
        ),
        Index(
            "ix_global_volatility_snapshots_industry_date",
            "industry",
            "snapshot_date",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    snapshot_date = Column(Date, nullable=False, index=True)
    provider = Column(String, nullable=False, index=True)
    industry = Column(String, nullable=False, default="all", server_default="all", index=True)
    volatility_score = Column(Float, nullable=True)
    compared_queries = Column(Integer, nullable=False, default=0, server_default="0")
    changed_query_count = Column(Integer, nullable=False, default=0, server_default="0")
    changed_ratio = Column(Float, nullable=True)
    avg_text_similarity = Column(Float, nullable=True)
    avg_citation_jaccard = Column(Float, nullable=True)
    citation_churn_rate = Column(Float, nullable=True)
    format_change_rate = Column(Float, nullable=True)
    top_winners_json = Column(
        "top_winners", JSON, nullable=False, default=list, server_default="[]"
    )
    top_losers_json = Column("top_losers", JSON, nullable=False, default=list, server_default="[]")
    changes_json = Column("changes", JSON, nullable=False, default=dict, server_default="{}")
    computed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    schema_version = Column(String, nullable=False, default="1", server_default="1")


class EntityAuthoritySnapshot(Base):
    __tablename__ = "entity_authority_snapshots"
    __table_args__ = (
        Index("ix_entity_authority_snapshots_project_computed_at", "project_id", "computed_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    computed_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    authority_score = Column(Float, nullable=False)
    coverage_score = Column(Float, nullable=False, default=0.0, server_default="0")
    depth_score = Column(Float, nullable=False, default=0.0, server_default="0")
    consistency_score = Column(Float, nullable=False, default=0.0, server_default="0")
    uniqueness_score = Column(Float, nullable=False, default=0.0, server_default="0")
    target_entity_count = Column(Integer, nullable=False, default=0, server_default="0")
    detected_entity_count = Column(Integer, nullable=False, default=0, server_default="0")
    gap_count = Column(Integer, nullable=False, default=0, server_default="0")
    computation_version = Column(String, nullable=False, default="v1", server_default="v1")
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    project = relationship("Project", back_populates="entity_authority_snapshots")


class SignalAuditSnapshot(Base):
    __tablename__ = "signal_audit_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "audit_id",
            "score_dimension",
            name="uq_signal_audit_snapshots_audit_dimension",
        ),
        Index("ix_signal_audit_snapshots_project_date", "project_id", "snapshot_date"),
        Index("ix_signal_audit_snapshots_workspace_date", "workspace_id", "snapshot_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    audit_id = Column(
        Integer, ForeignKey("audits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    workspace_id = Column(
        Integer, ForeignKey("workspaces.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_date = Column(Date, nullable=False, index=True)
    score_dimension = Column(String, nullable=False)
    score_value = Column(Float, nullable=False)
    provider = Column(String, nullable=True)
    tier_class = Column(String, nullable=True)
    routing_mode = Column(String, nullable=True)
    pipeline_type = Column(String, nullable=True)
    agent_count = Column(Integer, nullable=True)
    parallel_layers = Column(Integer, nullable=True)
    total_debate_cost_usd = Column(Float, nullable=True)
    total_debate_latency_ms = Column(Integer, nullable=True)
    evidence_anchor_json = Column("evidence_anchor", JSON, nullable=True)
    ingested_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    audit = relationship("Audit", back_populates="signal_audit_snapshots")
    project = relationship("Project", back_populates="signal_audit_snapshots")


class SignalDebateAgentFact(Base):
    __tablename__ = "signal_debate_agent_facts"
    __table_args__ = (
        UniqueConstraint(
            "audit_id",
            "agent_role",
            name="uq_signal_debate_agent_audit_role",
        ),
        Index("ix_signal_debate_agent_project_date", "project_id", "snapshot_date"),
        Index("ix_signal_debate_agent_provider_date", "provider", "snapshot_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    audit_id = Column(
        Integer, ForeignKey("audits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_date = Column(Date, nullable=False, index=True)
    pipeline_type = Column(String(32), nullable=False)
    agent_role = Column(String(64), nullable=False)
    agent_layer = Column(Integer, nullable=False, default=0, server_default="0")
    provider = Column(String(32), nullable=False)
    model = Column(String(128), nullable=False)
    latency_ms = Column(Integer, nullable=True)
    cost_usd = Column(Float, nullable=True)
    prompt_tokens = Column(Integer, nullable=True)
    completion_tokens = Column(Integer, nullable=True)
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    audit = relationship("Audit", back_populates="signal_debate_agent_facts")
    project = relationship("Project", back_populates="signal_debate_agent_facts")


class SignalClaimDispositionFact(Base):
    __tablename__ = "signal_claim_disposition_facts"
    __table_args__ = (
        UniqueConstraint(
            "audit_id",
            "domain",
            name="uq_signal_claim_disp_audit_domain",
        ),
        Index("ix_signal_claim_disp_project_date", "project_id", "snapshot_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    audit_id = Column(
        Integer, ForeignKey("audits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_date = Column(Date, nullable=False, index=True)
    pipeline_type = Column(String(32), nullable=False)
    domain = Column(String(16), nullable=False)
    claims_generated = Column(Integer, nullable=False, default=0, server_default="0")
    claims_accepted = Column(Integer, nullable=False, default=0, server_default="0")
    claims_downgraded = Column(Integer, nullable=False, default=0, server_default="0")
    claims_rejected = Column(Integer, nullable=False, default=0, server_default="0")
    claims_needs_manual_review = Column(Integer, nullable=False, default=0, server_default="0")
    claims_deduplicated = Column(Integer, nullable=False, default=0, server_default="0")
    claims_manually_approved = Column(Integer, nullable=False, default=0, server_default="0")
    claims_manually_refused = Column(Integer, nullable=False, default=0, server_default="0")
    debate_confidence_score = Column(Float, nullable=True)
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    audit = relationship("Audit", back_populates="signal_claim_disposition_facts")
    project = relationship("Project", back_populates="signal_claim_disposition_facts")


class SignalCitationEvent(Base):
    __tablename__ = "signal_citation_events"
    __table_args__ = (
        UniqueConstraint(
            "visibility_run_id",
            name="uq_signal_citation_events_visibility_run",
        ),
        Index("ix_signal_citation_events_project_date", "project_id", "snapshot_date"),
        Index(
            "ix_signal_citation_events_project_provider_date",
            "project_id",
            "provider",
            "snapshot_date",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    visibility_run_batch_id = Column(
        Integer,
        ForeignKey("visibility_run_batches.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    visibility_run_id = Column(
        Integer,
        ForeignKey("visibility_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_date = Column(Date, nullable=False, index=True)
    provider = Column(String, nullable=False)
    query_hash = Column(String, nullable=False, index=True)
    domain_cited = Column(String, nullable=True)
    citation_present = Column(Boolean, nullable=False, default=False, server_default="false")
    answer_changed = Column(Boolean, nullable=False, default=False, server_default="false")
    citations_hash = Column(String, nullable=True)
    text_similarity_score = Column(Float, nullable=True)
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    batch = relationship("VisibilityRunBatch", back_populates="signal_citation_events")
    run = relationship("VisibilityRun", back_populates="signal_citation_event")
    project = relationship("Project", back_populates="signal_citation_events")


class SignalEntityObservation(Base):
    __tablename__ = "signal_entity_observations"
    __table_args__ = (
        UniqueConstraint(
            "audit_id",
            "entity_key",
            name="uq_signal_entity_observations_audit_entity",
        ),
        Index("ix_signal_entity_observations_project_date", "project_id", "snapshot_date"),
        Index("ix_signal_entity_observations_entity_key", "entity_key"),
    )

    id = Column(Integer, primary_key=True, index=True)
    audit_id = Column(
        Integer, ForeignKey("audits.id", ondelete="CASCADE"), nullable=False, index=True
    )
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    snapshot_date = Column(Date, nullable=False, index=True)
    entity_key = Column(String, nullable=False)
    entity_category = Column(String, nullable=False, server_default="Unknown")
    relevance_score = Column(Float, nullable=True)
    mention_frequency = Column(Integer, nullable=False, default=1, server_default="1")
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    audit = relationship("Audit", back_populates="signal_entity_observations")
    project = relationship("Project", back_populates="signal_entity_observations")


class SignalRemediationOutcome(Base):
    __tablename__ = "signal_remediation_outcomes"
    __table_args__ = (
        UniqueConstraint(
            "project_task_id",
            "audit_after_id",
            name="uq_signal_remediation_outcomes_task_after_audit",
        ),
        Index(
            "ix_signal_remediation_outcomes_project_completed",
            "project_id",
            "completed_at",
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_task_id = Column(
        Integer,
        ForeignKey("project_tasks.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)
    recommendation_category = Column(String, nullable=True)
    before_score_geo = Column(Float, nullable=True)
    after_score_geo = Column(Float, nullable=True)
    score_delta_geo = Column(Float, nullable=True)
    before_score_aeo = Column(Float, nullable=True)
    after_score_aeo = Column(Float, nullable=True)
    score_delta_aeo = Column(Float, nullable=True)
    days_to_impact = Column(Integer, nullable=True)
    audit_before_id = Column(
        Integer,
        ForeignKey("audits.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    audit_after_id = Column(
        Integer,
        ForeignKey("audits.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    project_task = relationship("ProjectTask", back_populates="signal_remediation_outcomes")
    project = relationship("Project", back_populates="signal_remediation_outcomes")
    audit_before = relationship(
        "Audit",
        foreign_keys=[audit_before_id],
        back_populates="remediation_before_outcomes",
    )
    audit_after = relationship(
        "Audit",
        foreign_keys=[audit_after_id],
        back_populates="remediation_after_outcomes",
    )


class BenchmarkCohortAggregate(Base):
    __tablename__ = "benchmark_cohort_aggregates"
    __table_args__ = (
        UniqueConstraint(
            "cohort_key",
            "metric",
            "period_date",
            name="uq_benchmark_cohort_aggregates_key_metric_period",
        ),
        Index("ix_benchmark_cohort_aggregates_period_metric", "period_date", "metric"),
    )

    id = Column(Integer, primary_key=True, index=True)
    cohort_key = Column(String, nullable=False, index=True)
    metric = Column(String, nullable=False, index=True)
    period_date = Column(Date, nullable=False, index=True)
    cohort_size = Column(Integer, nullable=False, default=0, server_default="0")
    p10 = Column(Float, nullable=True)
    p25 = Column(Float, nullable=True)
    p50 = Column(Float, nullable=True)
    p75 = Column(Float, nullable=True)
    p90 = Column(Float, nullable=True)
    mean = Column(Float, nullable=True)
    stddev = Column(Float, nullable=True)
    suppressed = Column(Boolean, nullable=False, default=False, server_default="false")
    computed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    schema_version = Column(String, nullable=False, default="1", server_default="1")


class ProprietaryScore(Base):
    __tablename__ = "proprietary_scores"
    __table_args__ = (
        UniqueConstraint(
            "project_id",
            "score_type",
            "score_version",
            name="uq_proprietary_scores_project_type_version",
        ),
        Index("ix_proprietary_scores_project_computed", "project_id", "computed_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    project_id = Column(
        Integer, ForeignKey("projects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    score_type = Column(String, nullable=False, index=True)
    score_version = Column(String, nullable=False, default="v1", server_default="v1")
    value = Column(Float, nullable=True)
    components_json = Column("components", JSON, nullable=False, default=dict, server_default="{}")
    weights_json = Column("weights", JSON, nullable=False, default=dict, server_default="{}")
    confidence = Column(
        String, nullable=False, default="insufficient", server_default="insufficient"
    )
    data_points_used = Column(Integer, nullable=False, default=0, server_default="0")
    computed_at = Column(DateTime(timezone=True), nullable=False, server_default=func.now())
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    project = relationship("Project", back_populates="proprietary_scores")


class IntentCorpusEntry(Base):
    __tablename__ = "intent_corpus_entries"
    __table_args__ = (Index("ix_intent_corpus_entries_created_at", "created_at"),)

    id = Column(Integer, primary_key=True, index=True)
    question = Column(Text, nullable=False)
    context = Column(Text, nullable=True)
    metadata_json = Column("metadata", JSON, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class IntentQueryTelemetry(Base):
    __tablename__ = "intent_query_telemetry"
    __table_args__ = (
        Index("ix_intent_query_telemetry_created_at", "created_at"),
        Index("ix_intent_query_telemetry_provider_created", "provider", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    query = Column(Text, nullable=False)
    top_k = Column(Integer, nullable=False)
    provider = Column(String, nullable=False, default="local")
    latency_ms = Column(Float, nullable=False)
    response_payload = Column(JSON, nullable=False, default=list)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)


class AeoQueryTrackerEntry(Base):
    __tablename__ = "aeo_query_tracker_entries"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "context_key",
            "query",
            name="uq_aeo_query_tracker_user_context_query",
        ),
        Index("ix_aeo_query_tracker_user_context", "user_id", "context_key"),
        Index("ix_aeo_query_tracker_context", "context_key"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    context_key = Column(String, nullable=False, index=True)
    query = Column(Text, nullable=False)
    citation_hits = Column(Integer, nullable=False, default=0)
    tracked_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class GeoPromptTrackerEntry(Base):
    __tablename__ = "geo_prompt_tracker_entries"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "context_key",
            "prompt",
            name="uq_geo_prompt_tracker_user_context_prompt",
        ),
        Index("ix_geo_prompt_tracker_user_context", "user_id", "context_key"),
        Index("ix_geo_prompt_tracker_context", "context_key"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    context_key = Column(String, nullable=False, index=True)
    prompt = Column(Text, nullable=False)
    citation_hits = Column(Integer, nullable=False, default=0)
    tracked_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


class PerformanceSnapshot(Base):
    __tablename__ = "performance_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "normalized_url", "snapshot_date", name="uq_performance_snapshots_url_date"
        ),
        Index("ix_performance_snapshots_url_date", "normalized_url", "snapshot_date"),
        Index("ix_performance_snapshots_snapshot_date", "snapshot_date"),
    )

    id = Column(Integer, primary_key=True, index=True)
    normalized_url = Column(String, nullable=False, index=True)
    snapshot_date = Column(Date, nullable=False)
    metrics_payload = Column(JSON, nullable=False, default=dict)
    source_status = Column(String, nullable=False, default="success")
    error_message = Column(Text, nullable=True)
    fetched_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )


# ---------------------------------------------------------------------------
# Plan override & feature flag tables (TASK_ADMIN-06)
# ---------------------------------------------------------------------------


class WorkspaceCapabilityOverride(Base):
    __tablename__ = "workspace_capability_overrides"
    __table_args__ = (
        Index(
            "ix_wco_workspace_capability",
            "workspace_id",
            "capability_key",
            unique=True,
        ),
    )

    id = Column(Integer, primary_key=True, index=True)
    workspace_id = Column(
        Integer,
        ForeignKey("workspaces.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    capability_key = Column(String, nullable=False)
    override_value = Column(JSON, nullable=False)
    reason = Column(Text, nullable=True)
    created_by_user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    expires_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    workspace = relationship("Workspace", backref="capability_overrides")
    created_by_user = relationship("User", foreign_keys=[created_by_user_id])


class FeatureFlag(Base):
    __tablename__ = "feature_flags"

    id = Column(Integer, primary_key=True, index=True)
    key = Column(String, unique=True, nullable=False, index=True)
    description = Column(Text, nullable=True)
    is_enabled = Column(Boolean, nullable=False, default=False, server_default="false")
    rollout_percentage = Column(Integer, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    schema_version = Column(String, nullable=False, default="1", server_default="1")


class PasskeyCredential(Base):
    """WebAuthn / FIDO2 passkey credential bound to a user."""

    __tablename__ = "passkey_credentials"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    credential_id = Column(String, unique=True, nullable=False, index=True)
    public_key = Column(Text, nullable=False)
    sign_count = Column(Integer, nullable=False, default=0)
    name = Column(String, nullable=False, default="My Passkey")
    transports = Column(JSON, nullable=True)
    backed_up = Column(Boolean, nullable=False, default=False, server_default="false")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    last_used_at = Column(DateTime(timezone=True), nullable=True)
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    user = relationship("User", back_populates="passkey_credentials")


class UserLinkedIdentity(Base):
    """An OAuth provider identity attached to an account the user already owns.

    Deliberately not stored in ``User.auth_provider`` / ``User.provider_subject``:
    until SIGV2-1268, ``auth/token_verifier.py`` rewrote both of those columns
    to the access token's subject on every authenticated request, so a link
    written there was erased by the user's next API call. The rewriting is gone,
    but this table remains the right place for a link: a provider identity is a
    fact about an external account, not about the local user row, and a row
    here also leaves the account's own password credentials intact, so linking
    adds a way in rather than converting the account to SSO-only.
    """

    __tablename__ = "user_linked_identities"

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    provider = Column(String, nullable=False)
    subject = Column(String, nullable=False)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    __table_args__ = (
        UniqueConstraint("provider", "subject", name="uq_user_linked_identity_provider_subject"),
        UniqueConstraint("user_id", "provider", name="uq_user_linked_identity_user_provider"),
    )

    user = relationship("User", back_populates="linked_identities")


class TrialInvitation(Base):
    """Tracks admin-issued trial invitations and their redemption status."""

    __tablename__ = "trial_invitations"
    __table_args__ = (Index("ix_trial_invitations_status", "status"),)

    id = Column(Integer, primary_key=True, index=True)
    email = Column(String, nullable=False, index=True)
    contact_name = Column(String, nullable=True)
    token = Column(String, unique=True, nullable=False, index=True)
    status = Column(
        String, nullable=False, default="pending", server_default="pending"
    )  # pending, redeemed, expired, revoked
    invited_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    redeemed_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    redeemed_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    invited_by = relationship(
        "User", foreign_keys=[invited_by_user_id], backref="sent_trial_invitations"
    )
    redeemed_by = relationship(
        "User", foreign_keys=[redeemed_by_user_id], backref="redeemed_trial_invitation"
    )


class TrialFeedbackRequest(Base):
    """Tracks tokenized post-trial feedback requests and submitted responses."""

    __tablename__ = "trial_feedback_requests"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "trial_started_at_snapshot",
            name="uq_trial_feedback_requests_user_trial_start",
        ),
        Index("ix_trial_feedback_requests_status", "status"),
        Index("ix_trial_feedback_requests_requested_at", "requested_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    user_id = Column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    trial_invitation_id = Column(
        Integer,
        ForeignKey("trial_invitations.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    requested_by_user_id = Column(
        Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    token = Column(String, unique=True, nullable=False, index=True)
    status = Column(
        String, nullable=False, default="pending", server_default="pending"
    )  # pending, submitted, expired
    trigger_reason = Column(
        String, nullable=False, default="trial_expired", server_default="trial_expired"
    )
    trial_started_at_snapshot = Column(DateTime(timezone=True), nullable=False)
    trial_ended_at_snapshot = Column(DateTime(timezone=True), nullable=True)
    overall_rating = Column(Integer, nullable=True)
    would_recommend = Column(String, nullable=True)
    what_worked_well = Column(Text, nullable=True)
    what_was_missing = Column(Text, nullable=True)
    improvement_suggestions = Column(Text, nullable=True)
    requested_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    submitted_at = Column(DateTime(timezone=True), nullable=True)
    expires_at = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    user = relationship("User", foreign_keys=[user_id], backref="trial_feedback_requests")
    trial_invitation = relationship("TrialInvitation", backref="feedback_requests")
    requested_by = relationship(
        "User",
        foreign_keys=[requested_by_user_id],
        backref="requested_trial_feedback_requests",
    )


# ── Model Lifecycle Monitoring ──────────────────────────────────────


class ModelLifecycleSnapshot(Base):
    __tablename__ = "model_lifecycle_snapshots"
    __table_args__ = (
        Index("ix_model_lifecycle_snapshots_provider_source", "provider", "source_url"),
        Index("ix_model_lifecycle_snapshots_fetched", "fetched_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String, nullable=False, index=True)
    source_url = Column(String, nullable=False)
    page_type = Column(String, nullable=False, default="deprecations")
    content_hash = Column(String, nullable=False)
    extracted_models = Column(JSON, nullable=True)
    raw_text_excerpt = Column(Text, nullable=True)
    fetched_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    schema_version = Column(String, nullable=False, default="1", server_default="1")


class ModelLifecycleAlert(Base):
    __tablename__ = "model_lifecycle_alerts"
    __table_args__ = (
        Index("ix_model_lifecycle_alerts_status_created", "status", "created_at"),
        Index("ix_model_lifecycle_alerts_provider", "provider"),
    )

    id = Column(Integer, primary_key=True, index=True)
    provider = Column(String, nullable=False)
    alert_type = Column(String, nullable=False)
    severity = Column(String, nullable=False, default="warning", server_default="warning")
    title = Column(String, nullable=False)
    description = Column(Text, nullable=False)
    affected_models = Column(JSON, nullable=True)
    details = Column(JSON, nullable=True)
    source_url = Column(String, nullable=True)
    status = Column(String, nullable=False, default="active", server_default="active", index=True)
    acknowledged_by_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    schema_version = Column(String, nullable=False, default="1", server_default="1")

    acknowledged_by = relationship("User", foreign_keys=[acknowledged_by_id])


# ── Claim Feedback Loop ─────────────────────────────────────────────


class ClaimFeedbackType(str, PyEnum):
    AGREE = "agree"
    DISAGREE = "disagree"
    FIXED = "fixed"


class ClaimFeedback(Base):
    __tablename__ = "claim_feedback"
    __table_args__ = (
        UniqueConstraint("audit_id", "claim_key", "user_id", name="uq_claim_feedback_per_user"),
        Index("ix_claim_feedback_audit_id", "audit_id"),
        Index("ix_claim_feedback_claim_key", "claim_key"),
        Index("ix_claim_feedback_user_id", "user_id"),
    )

    id = Column(Integer, primary_key=True, index=True)
    audit_id = Column(Integer, ForeignKey("audits.id", ondelete="CASCADE"), nullable=False)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    claim_key = Column(String, nullable=False)
    claim_text = Column(Text, nullable=False)
    claim_category = Column(String, nullable=True)
    feedback_type = Column(
        Enum(ClaimFeedbackType, name="claim_feedback_type", native_enum=False),
        nullable=False,
    )
    feedback_text = Column(Text, nullable=True)
    schema_version = Column(String, nullable=False, default="1", server_default="1")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    audit = relationship("Audit", backref="claim_feedback")
    user = relationship("User", backref="claim_feedback")


# ---------------------------------------------------------------------------
# Guest Audit Record (lightweight, no user FK, persists unauthenticated audits)
# ---------------------------------------------------------------------------


class GuestAuditRecord(Base):
    __tablename__ = "guest_audit_records"
    __table_args__ = (
        Index("ix_guest_audit_records_ip_hash", "ip_hash"),
        Index("ix_guest_audit_records_claim_token", "claim_token"),
        Index("ix_guest_audit_records_created_at", "created_at"),
    )

    id = Column(Integer, primary_key=True, index=True)
    ip_hash = Column(String, nullable=False)
    target_url = Column(String, nullable=True)
    target_name = Column(String, nullable=True)
    audit_target_type = Column(String, nullable=False, default="website", server_default="website")
    seo_score = Column(Float, nullable=True)
    geo_score = Column(Float, nullable=True)
    aeo_score = Column(Float, nullable=True)
    overall_score = Column(Float, nullable=True)
    findings_summary = Column(JSON, nullable=True)
    entity_count = Column(Integer, nullable=False, default=0, server_default="0")
    competitor_count = Column(Integer, nullable=False, default=0, server_default="0")
    claim_token = Column(String, unique=True, nullable=False)
    claimed_by_user_id = Column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    claimed_at = Column(DateTime(timezone=True), nullable=True)
    email = Column(String, nullable=True)
    referrer = Column(String, nullable=True)
    user_agent_hash = Column(String, nullable=True)
    request_id = Column(String, nullable=True, index=True)
    schema_version = Column(String, nullable=False, default="1", server_default="1")
    created_at = Column(DateTime(timezone=True), server_default=func.now(), nullable=False)

    claimed_by = relationship("User", backref="guest_audit_records")
