"""Configuration loading for the Universal Media Decomposer.

Environment-driven configuration via ``pydantic-settings``. All settings are
overridable with environment variables prefixed ``UMD_`` and/or a ``.env``
file. Secrets are never embedded in source; production uses the environment.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

# Default filesystem layout extension for OCFL 1.1 storage roots. Configurable,
# but pinned to a well-understood layout for reproducibility. The adapter treats
# the underlying filesystem/MinIO-compatible substrate as replaceable.
DEFAULT_OCFL_LAYOUT = "0003-hash-and-id-n-tuple-storage-layout"


class PostgresSettings(BaseSettings):
    """PostgreSQL transactional-authority connection settings."""

    dsn: str = "postgresql+psycopg://umd:umd@127.0.0.1:5432/umd"
    pool_size: int = 10
    max_overflow: int = 20


class OcflSettings(BaseSettings):
    """OCFL object-store substrate settings."""

    root: Path = Field(default=Path("./.ocfl-root"))
    layout: str = DEFAULT_OCFL_LAYOUT


class LimitsSettings(BaseSettings):
    """Security and resource bounds shared across retrieval/ingestion."""

    max_upload_bytes: int = 1024 * 1024 * 1024
    max_range_bytes: int = 1024 * 1024
    max_read_buffer_bytes: int = 1024 * 1024


class ApiSettings(BaseSettings):
    """Versioned REST API surface settings (Phase 3)."""

    #: API version prefix served by the router (versioned surface).
    version: str = "v1"
    #: Human-readable service/contract version reported by /version.
    contract_version: str = "1.0.0"
    #: Optional CORS allow-origins (empty = same-origin only).
    cors_allow_origins: list[str] = Field(default_factory=list)


class AuthSettings(BaseSettings):
    """API authentication/authorization (API key + bearer) settings."""

    #: Enabled API keys. A request authenticates with ``Authorization: Bearer <key>``
    #: OR ``X-API-Key: <key>``. Empty disables bearer auth (tests inject keys).
    api_keys: list[str] = Field(default_factory=list)
    #: Authorization check for mutating routes: the authenticated key must be in this
    #: set to perform writes. Empty = any valid key may write.
    write_keys: list[str] = Field(default_factory=list)


class RateLimitSettings(BaseSettings):
    """Per-key / per-IP in-process token-bucket rate limiting (real, not a stub)."""

    enabled: bool = True
    #: Max requests per window per (authenticated key / client IP) bucket.
    requests_per_window: int = 1000
    #: Window length in seconds over which the token bucket refills.
    window_seconds: float = 60.0
    #: Burst capacity above the sustained rate.
    burst: int = 50


class QueryCostSettings(BaseSettings):
    """Bounded query-cost limits (structured/semantic/search)."""

    #: Hard cap on result page size for any query/search collection.
    max_limit: int = 200
    default_limit: int = 20
    #: Bounded traversal depth cap (hard ceiling; v1 has no arbitrary-depth graphs).
    max_depth: int = 4
    #: Confidence floor applied when a query omits it.
    min_confidence: float = 0.0


class ConsistencySettings(BaseSettings):
    """Read-your-writes token waiter / consistency behavior (Phase 3)."""

    #: Bounded Tier-1 waiter concurrency (token-bearing reads wait behind this semaphore).
    max_waiters: int = 16
    #: Multiplier of the configured lag budget a token-bearing read may wait before 503.
    #: DD: bounded waiter waits up to ~2x the (default <=1s) lag budget.
    lag_wait_multiplier: int = 2
    #: Retry-After (seconds) for transient-lag 503s.
    transient_retry_after: float = 1.0
    #: Retry-After (seconds) for rebuild-in-progress 503s (>=30s per DD).
    rebuild_retry_after: float = 30.0


class RebuildSettings(BaseSettings):
    """Projection rebuild budget + reindex coordination (P1-S3)."""

    #: Rebuild budget: max events a single rebuild may replay before it is flagged.
    max_events: int = 1_000_000
    #: Rebuild budget: max wall seconds a single rebuild may take before it is flagged.
    max_seconds: float = 3600.0
    #: Concurrent reindex cap (DD: projection writes remain single-writer per builder).
    concurrent_rebuilds: int = 1
    #: Minimum wall-clock interval between two rebuilds of the same projection.
    min_interval_seconds: float = 1.0


class RasterSettings(BaseSettings):
    """Raster OCR provider selection (wired identically to the audio ASR pattern).

    ``reference`` is the deterministic default; ``tesseract`` (and other gated
    providers) activate only when explicitly configured AND the runtime gate
    passes. The :meth:`umd.jobs.production._Composer._ocr_provider` reads this so
    production can select tesseract when it is available; unavailable providers
    degrade honestly with a gated warning (never a fabricated active OCR claim).
    """

    ocr_provider: str = "reference"


class SemanticSettings(BaseSettings):
    """Semantic text-analysis provider selection (Plan M P2).

    ``reference`` is the deterministic default; a configured provider/model
    activates the optional provider-backed semantic-analysis path. An
    unavailable/unsupported/disabled/gated provider degrades honestly to the
    deterministic/reference baseline with a warning — never a fabricated active
    provider result (the analyzer boundary, :mod:`umd.analysis.semantic_analyzer`,
    mirrors the OCR/ASR gate pattern).
    """

    provider: str = "reference"
    model: str | None = None


class ProjectionSettings(BaseSettings):
    """Tier-1 projection / blue-green / search / vector knobs (Phase 2)."""

    #: Grace period a retired generation schema is retained before being dropped.
    grace_period_seconds: float = 300.0
    #: Default page size for exact/fuzzy/hybrid search reads.
    search_default_limit: int = 20
    #: Minimum confidence threshold a search/query result must meet.
    min_confidence: float = 0.0
    #: pgvector HNSW is a build gate: it only activates when the extension version is
    #: >= this minimum (DD: at least 0.8.2).
    vector_hnsw_min_version: str = "0.8.2"
    #: Hybrid ranking fuses exact + cosine scores with this vector weight (1-weight exact).
    hybrid_vector_weight: float = 0.5


class Settings(BaseSettings):
    """Top-level application settings."""

    model_config = SettingsConfigDict(
        env_prefix="UMD_",
        env_nested_delimiter="__",
        env_file=".env",
        extra="ignore",
    )

    log_level: str = Field(default="INFO")
    postgres: PostgresSettings = Field(default_factory=PostgresSettings)
    ocfl: OcflSettings = Field(default_factory=OcflSettings)
    limits: LimitsSettings = Field(default_factory=LimitsSettings)
    raster: RasterSettings = Field(default_factory=RasterSettings)
    semantic: SemanticSettings = Field(default_factory=SemanticSettings)
    projection: ProjectionSettings = Field(default_factory=ProjectionSettings)
    rebuild: RebuildSettings = Field(default_factory=RebuildSettings)
    api: ApiSettings = Field(default_factory=ApiSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    rate_limit: RateLimitSettings = Field(default_factory=RateLimitSettings)
    query_cost: QueryCostSettings = Field(default_factory=QueryCostSettings)
    consistency: ConsistencySettings = Field(default_factory=ConsistencySettings)
    lag_budget_seconds: float = Field(default=1.0)
    digest_algorithm: str = Field(default="sha512")

    @field_validator("lag_budget_seconds")
    @classmethod
    def _lag_budget_cap(cls, v: float) -> float:
        # Per the DD, the bounded lag budget cap is <= 1 second.
        if v > 1.0:
            raise ValueError("lag_budget_seconds must be <= 1.0")
        return v

    @field_validator("digest_algorithm")
    @classmethod
    def _supported_digest(cls, v: str) -> str:
        if v != "sha512":
            raise ValueError("Phase 1 supports only the sha512 content-addressing digest")
        return v


def get_settings(**overrides: Any) -> Settings:
    """Build a :class:`Settings`, applying ``overrides`` last (used by tests)."""
    return Settings(**overrides)
