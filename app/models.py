"""
SQLModel table definitions for the Regulatory Watch platform.
Core models: Domain, Url, FetchRun, FetchAttempt, RawDocument.
Versioning models: SourceVersion (immutable history), ChangeEvent (diffs).
"""

from sqlmodel import SQLModel, Field, Relationship, Column
from sqlalchemy import JSON, Text, String, CheckConstraint, UniqueConstraint, Date, ARRAY
from pgvector.sqlalchemy import Vector
from typing import Optional
from uuid import UUID, uuid4
from datetime import datetime, date, timezone


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ═════════════════════════════════════════════════════════════════════════════
# Domain — a regulatory website to monitor
# ═════════════════════════════════════════════════════════════════════════════
class Domain(SQLModel, table=True):
    __tablename__ = "domains"
    __table_args__ = (
        CheckConstraint("status IN ('active','paused','archived')", name="ck_domain_status"),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    domain: str = Field(index=True, unique=True, max_length=255)
    seed_urls: list[str] = Field(default=[], sa_column=Column(JSON, nullable=False, server_default="[]"))
    status: str = Field(default="active", max_length=20)
    rate_limit_rps: float = Field(default=1.0, description="Max requests per second to this domain")

    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    # Relationships
    urls: list["Url"] = Relationship(back_populates="domain")
    fetch_runs: list["FetchRun"] = Relationship(back_populates="domain")


# ═════════════════════════════════════════════════════════════════════════════
# Url — a specific page being monitored within a domain
# ═════════════════════════════════════════════════════════════════════════════
class Url(SQLModel, table=True):
    __tablename__ = "urls"
    __table_args__ = (
        CheckConstraint(
            "state IN ('discovered','queued','fetched','failed','ignored','blocked')",
            name="ck_url_state",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    domain_id: UUID = Field(foreign_key="domains.id", index=True)
    url: str = Field(sa_column=Column(Text, unique=True, nullable=False))

    # State machine
    state: str = Field(default="discovered", max_length=20, index=True)

    # Scoring
    priority: float = Field(default=0.5)
    relevance_score: float = Field(default=0.5)
    hub_score: float = Field(default=0.0)
    trap_score: float = Field(default=0.0)

    # Fetch tracking
    last_fetch_at: Optional[datetime] = Field(default=None)
    last_status_code: Optional[int] = Field(default=None)
    last_content_hash: Optional[str] = Field(default=None, max_length=128)
    last_etag: Optional[str] = Field(default=None, max_length=256)

    # Scheduling
    next_fetch_at: datetime = Field(default_factory=utcnow, index=True)
    fetch_interval_hours: int = Field(default=168)  # weekly

    # Error handling
    error_streak: int = Field(default=0)
    cooldown_until: Optional[datetime] = Field(default=None)

    # Discovery
    discovered_from_url_id: Optional[UUID] = Field(default=None, foreign_key="urls.id")
    first_seen_at: datetime = Field(default_factory=utcnow)

    # Relationships
    domain: Optional[Domain] = Relationship(back_populates="urls")
    attempts: list["FetchAttempt"] = Relationship(back_populates="url")


# ═════════════════════════════════════════════════════════════════════════════
# FetchRun — a batch crawl execution
# ═════════════════════════════════════════════════════════════════════════════
class FetchRun(SQLModel, table=True):
    __tablename__ = "fetch_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running','completed','failed','cancelled')",
            name="ck_fetchrun_status",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    domain_id: UUID = Field(foreign_key="domains.id", index=True)
    status: str = Field(default="running", max_length=20)

    # Metrics
    planned_count: int = Field(default=0)
    fetched_count: int = Field(default=0)
    changed_count: int = Field(default=0)
    alert_count: int = Field(default=0)

    started_at: datetime = Field(default_factory=utcnow)
    finished_at: Optional[datetime] = Field(default=None)

    # Relationships
    domain: Optional[Domain] = Relationship(back_populates="fetch_runs")
    attempts: list["FetchAttempt"] = Relationship(back_populates="run")


# ═════════════════════════════════════════════════════════════════════════════
# FetchAttempt — one URL fetch within a run
# ═════════════════════════════════════════════════════════════════════════════
class FetchAttempt(SQLModel, table=True):
    __tablename__ = "fetch_attempts"

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    url_id: UUID = Field(foreign_key="urls.id", index=True)
    run_id: UUID = Field(foreign_key="fetch_runs.id", index=True)

    status_code: Optional[int] = Field(default=None)
    content_hash: Optional[str] = Field(default=None, max_length=128)
    diff_status: Optional[str] = Field(default=None, max_length=20)

    # Artifact locations (S3 URIs)
    raw_html_uri: Optional[str] = Field(default=None, max_length=512)
    extracted_text_uri: Optional[str] = Field(default=None, max_length=512)

    fetched_at: datetime = Field(default_factory=utcnow)
    duration_ms: Optional[int] = Field(default=None)

    error_message: Optional[str] = Field(default=None, sa_column=Column(Text))

    # Relationships
    url: Optional[Url] = Relationship(back_populates="attempts")
    run: Optional[FetchRun] = Relationship(back_populates="attempts")


# ═════════════════════════════════════════════════════════════════════════════
# RawDocument — a single ingested regulatory document from any source
# ═════════════════════════════════════════════════════════════════════════════
class RawDocument(SQLModel, table=True):
    __tablename__ = "raw_documents"
    __table_args__ = (
        UniqueConstraint("content_hash", name="uq_raw_document_content_hash"),
        CheckConstraint(
            "source_type IN ('web','pdf','rss','xml','email')",
            name="ck_raw_document_source_type",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    # Source metadata
    source_url: str = Field(sa_column=Column(Text, nullable=False))
    source_type: str = Field(max_length=20)  # web | pdf | rss | xml | email

    # Extracted content
    raw_text: Optional[str] = Field(default=None, sa_column=Column(Text))
    title: Optional[str] = Field(default=None, sa_column=Column(Text))
    language: Optional[str] = Field(default=None, max_length=10)  # ISO 639-1 e.g. "en"

    # Deduplication — SHA-256 hex of raw_text; UNIQUE in DB
    content_hash: str = Field(sa_column=Column(String(64), nullable=False))

    # Structure — populated for multi-part documents (currently: PDFs).
    # `page_count` is the number of pages; `pages` is a JSON list of
    # {"n": int, "start": int, "end": int} giving character offsets into
    # `raw_text` for each page, so consumers can slice a specific page
    # without storing 1 row per page.
    page_count: Optional[int] = Field(default=None)
    pages: Optional[list] = Field(default=None, sa_column=Column(JSON, nullable=True))

    # Cold-storage pointer — S3 (or other object-store) URI where the
    # extracted text was archived. NULL when AWS_S3_BUCKET is not configured.
    artifact_uri: Optional[str] = Field(default=None, max_length=512)

    # Timestamps
    fetched_at: datetime = Field(default_factory=utcnow)
    last_seen_at: datetime = Field(default_factory=utcnow)


# ═════════════════════════════════════════════════════════════════════════════
# SourceVersion — immutable history row per unique (source_url, content_hash).
# Every time an ingested document's content_hash changes for a given URL we
# append a new SourceVersion. last_seen_at is bumped when the same hash is
# observed again, so we can tell "this version was still live on date X".
# ═════════════════════════════════════════════════════════════════════════════
class SourceVersion(SQLModel, table=True):
    __tablename__ = "source_versions"
    __table_args__ = (
        UniqueConstraint(
            "source_url", "content_hash",
            name="uq_source_version_url_hash",
        ),
        CheckConstraint(
            "source_type IN ('web','pdf','rss','xml','email')",
            name="ck_source_version_source_type",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)

    source_url: str = Field(sa_column=Column(Text, nullable=False))
    source_type: str = Field(max_length=20)
    content_hash: str = Field(sa_column=Column(String(64), nullable=False))

    # Full canonical text of this version (so future diffs / re-processing
    # don't require re-fetching from the origin).
    raw_text: Optional[str] = Field(default=None, sa_column=Column(Text))
    title: Optional[str] = Field(default=None, sa_column=Column(Text))
    language: Optional[str] = Field(default=None, max_length=10)

    # PDF / multi-part structure carried forward from RawDocument.
    page_count: Optional[int] = Field(default=None)
    pages: Optional[list] = Field(default=None, sa_column=Column(JSON, nullable=True))

    # Cold-storage pointer — mirrors raw_documents.artifact_uri.
    artifact_uri: Optional[str] = Field(default=None, max_length=512)

    first_seen_at: datetime = Field(default_factory=utcnow)
    last_seen_at: datetime = Field(default_factory=utcnow)


# ═════════════════════════════════════════════════════════════════════════════
# ChangeEvent — one row per detected transition between SourceVersions.
#   diff_kind = 'created'   → first time we've ever seen this URL
#              'modified'   → content_hash changed vs. the previous version
# For 'modified' events we persist a unified diff (truncated) + char deltas
# so the UI / alerting layer can render "what changed" without recomputing.
# `summary` is reserved for a later LLM-produced natural-language summary.
# ═════════════════════════════════════════════════════════════════════════════
class ChangeEvent(SQLModel, table=True):
    __tablename__ = "change_events"
    __table_args__ = (
        CheckConstraint(
            "diff_kind IN ('created','modified')",
            name="ck_change_event_diff_kind",
        ),
        CheckConstraint(
            "significance_score IS NULL OR "
            "(significance_score >= 0.0 AND significance_score <= 1.0)",
            name="ck_change_event_significance_score_range",
        ),
        CheckConstraint(
            "change_type IS NULL OR change_type IN ("
            "'typo_or_cosmetic','minor_wording','clarification',"
            "'substantive','critical')",
            name="ck_change_event_change_type",
        ),
        CheckConstraint(
            "topic IS NULL OR topic IN ("
            "'customs_trade','financial_services','data_privacy',"
            "'environmental','healthcare_pharma','sanctions_export_control',"
            "'labor_employment','tax_accounting','consumer_protection',"
            "'corporate_governance','other')",
            name="ck_change_event_topic",
        ),
        CheckConstraint(
            "trade_flow_direction IS NULL OR trade_flow_direction IN ("
            "'inbound','outbound','bilateral','global')",
            name="ck_change_event_trade_flow_direction",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    source_url: str = Field(sa_column=Column(Text, nullable=False, index=True))

    new_version_id: UUID = Field(foreign_key="source_versions.id", index=True)
    prev_version_id: Optional[UUID] = Field(default=None, foreign_key="source_versions.id")

    diff_kind: str = Field(max_length=20)
    added_chars: int = Field(default=0)
    removed_chars: int = Field(default=0)

    # Truncated unified diff (see change_detection.MAX_DIFF_CHARS)
    unified_diff: Optional[str] = Field(default=None, sa_column=Column(Text))

    # ── Layer-3 LLM-produced fields (significance scorer) ─────────────
    # Populated asynchronously by `app.services.significance.score_event`.
    # All nullable: an event is created unscored and scoring may fail
    # (missing API key, transient LLM error, etc.) without blocking
    # ingestion or downstream alerting.
    significance_score: Optional[float] = Field(default=None)
    change_type: Optional[str] = Field(default=None, max_length=30)
    # Regulatory taxonomy topic (customs_trade, financial_services, ...)
    # Drives M5 alert subscriptions and dashboards. See migration 007.
    topic: Optional[str] = Field(default=None, max_length=40, index=True)
    affected_entities: Optional[list] = Field(
        default=None, sa_column=Column(JSON, nullable=True),
    )
    deadline_changes: Optional[list] = Field(
        default=None, sa_column=Column(JSON, nullable=True),
    )
    # `summary` is the LLM-produced plain-English compliance summary
    # ("what changed and what do I need to do about it").
    summary: Optional[str] = Field(default=None, sa_column=Column(Text))
    llm_model: Optional[str] = Field(default=None, max_length=50)
    llm_error: Optional[str] = Field(default=None, sa_column=Column(Text))
    scored_at: Optional[datetime] = Field(default=None)

    # Set when obligation extraction (M4 phase 3) has attempted this
    # event. NULL = never tried. Non-NULL with zero rows in
    # `obligations` = tried, nothing to extract.
    obligations_extracted_at: Optional[datetime] = Field(default=None)

    # ── M5 prelude: trade-flow / country filters (migration 010) ─────
    # `origin_countries` : LLM-extracted ISO-2 codes for the country of
    #     origin of goods / transactions the rule applies to.
    # `destination_countries` : jurisdictions the regulator governs,
    #     auto-filled from the source URL (see app.services.geo).
    # `trade_flow_direction` : inbound / outbound / bilateral / global.
    origin_countries: Optional[list[str]] = Field(
        default=None, sa_column=Column(ARRAY(String(length=8)), nullable=True),
    )
    destination_countries: Optional[list[str]] = Field(
        default=None, sa_column=Column(ARRAY(String(length=8)), nullable=True),
    )
    trade_flow_direction: Optional[str] = Field(
        default=None, max_length=12,
    )

    # Semantic embedding of (topic + entities + summary) — populated after
    # L3 scoring. Used by M5 matching for cosine similarity against
    # subscription embeddings. NULL on old/unscored events.
    embedding: Optional[list] = Field(
        default=None, sa_column=Column(Vector(1536), nullable=True),
    )

    detected_at: datetime = Field(default_factory=utcnow, index=True)


# ═════════════════════════════════════════════════════════════════════════════
# Entity / ChangeEventEntity — M4 queryable entity index
# ═════════════════════════════════════════════════════════════════════════════
# The LLM emits `affected_entities` as a JSON list of strings on each
# ChangeEvent. Those are great for display but useless for cross-event
# analytics ("show me every critical change mentioning FCA in Q2").
# These two tables promote that blob into a proper many-to-many index
# keyed on a normalized canonical form. See app.services.entity_index.
class Entity(SQLModel, table=True):
    __tablename__ = "entities"
    __table_args__ = (
        UniqueConstraint("canonical_key", name="uq_entities_canonical_key"),
        CheckConstraint(
            "entity_type IN ("
            "'agency','regulation','program','code','industry','other')",
            name="ck_entities_type",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    canonical_key: str = Field(max_length=255, index=True)
    display_name: str = Field(max_length=255)
    entity_type: str = Field(default="other", max_length=20, index=True)
    mention_count: int = Field(default=0)
    first_seen_at: datetime = Field(default_factory=utcnow)
    last_seen_at: datetime = Field(default_factory=utcnow, index=True)


class ChangeEventEntity(SQLModel, table=True):
    __tablename__ = "change_event_entities"

    change_event_id: UUID = Field(
        foreign_key="change_events.id", primary_key=True,
    )
    entity_id: UUID = Field(
        foreign_key="entities.id", primary_key=True, index=True,
    )
    # Exact surface form the LLM emitted, pre-normalization.
    mention_text: str = Field(max_length=255)
    created_at: datetime = Field(default_factory=utcnow)


# ═════════════════════════════════════════════════════════════════════════════
# Obligation — M4 phase 3: structured actionable obligations
# ═════════════════════════════════════════════════════════════════════════════
# Extracted by `app.services.obligations.extract_obligations` from events
# with significance_score >= 0.6 only (gating keeps LLM cost bounded).
# Each row is one discrete compliance action. An event can produce zero
# or many obligations.
class Obligation(SQLModel, table=True):
    __tablename__ = "obligations"
    __table_args__ = (
        CheckConstraint(
            "obligation_type IN ("
            "'reporting','prohibition','threshold','disclosure',"
            "'registration','penalty','other')",
            name="ck_obligations_type",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    change_event_id: UUID = Field(foreign_key="change_events.id", index=True)

    actor: str = Field(max_length=255)
    action: str = Field(sa_column=Column(Text, nullable=False))
    condition: Optional[str] = Field(default=None, sa_column=Column(Text))
    deadline_text: Optional[str] = Field(default=None, max_length=255)
    deadline_date: Optional[date] = Field(default=None, sa_column=Column(Date))
    penalty: Optional[str] = Field(default=None, sa_column=Column(Text))
    obligation_type: str = Field(default="other", max_length=30)

    llm_model: Optional[str] = Field(default=None, max_length=50)
    extracted_at: datetime = Field(default_factory=utcnow)


# ═════════════════════════════════════════════════════════════════════════════
# UserSubscription — M5: user alerting profiles
# ═════════════════════════════════════════════════════════════════════════════
# Each row represents one subscription "rule" a user has configured.
# The M5 matching engine evaluates every active subscription against each
# newly scored ChangeEvent using a combination of structured metadata
# pre-filters and PostgreSQL full-text search (TSVector/TSQuery).
# A user can have multiple subscriptions (e.g. "My China Sanctions Watch",
# "EU Environmental Alerts").
class UserSubscription(SQLModel, table=True):
    __tablename__ = "user_subscriptions"
    __table_args__ = (
        CheckConstraint(
            "min_significance >= 0.0 AND min_significance <= 1.0",
            name="ck_user_subscriptions_min_significance",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    user_email: str = Field(max_length=255, index=True)
    label: str = Field(max_length=255, default="Default Subscription")

    # ── Keyword list + semantic embedding ────────────────────────────
    # `keywords` stores the raw list for display and post-match XAI.
    # `embedding` is the single vector for the concatenated keyword
    # string, computed once at create/update via text-embedding-3-small.
    # NULL embedding → subscription is skipped at match time.
    keywords: list[str] = Field(
        default=[], sa_column=Column(JSON, nullable=False, server_default="[]"),
    )
    embedding: Optional[list] = Field(
        default=None, sa_column=Column(Vector(1536), nullable=True),
    )
    # Cosine similarity threshold [0, 1]. A higher value means stricter
    # matching (fewer, more precise alerts).
    similarity_threshold: float = Field(default=0.72)

    min_significance: float = Field(default=0.6)
    is_active: bool = Field(default=True, index=True)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)


# ═════════════════════════════════════════════════════════════════════════════
# Alert — M5: generated notifications linking users to matching events
# ═════════════════════════════════════════════════════════════════════════════
# One row per (subscription, change_event) match. The unique constraint
# prevents duplicate alerts if the matching task is retried.
class Alert(SQLModel, table=True):
    __tablename__ = "alerts"
    __table_args__ = (
        UniqueConstraint(
            "subscription_id", "change_event_id",
            name="uq_alerts_subscription_event",
        ),
        CheckConstraint(
            "status IN ('unread','read','dismissed')",
            name="ck_alerts_status",
        ),
    )

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    subscription_id: UUID = Field(
        foreign_key="user_subscriptions.id", index=True,
    )
    change_event_id: UUID = Field(
        foreign_key="change_events.id", index=True,
    )

    # XAI — store exactly which keywords triggered the alert so the
    # UI can highlight them for the compliance officer.
    matched_keywords: Optional[list] = Field(
        default=None, sa_column=Column(JSON, nullable=True),
    )

    status: str = Field(default="unread", max_length=20)
    created_at: datetime = Field(default_factory=utcnow)
