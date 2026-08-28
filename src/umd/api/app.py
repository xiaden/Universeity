"""FastAPI application factory for the versioned REST boundary (Phase 3).

Assembles the :class:`AppContext` (services over the Phase 1/2 building blocks),
installs RFC 7807 error handlers, a request correlation-id middleware, real
per-key/IP rate limiting, and mounts the versioned routers. OpenAPI is generated
automatically and served at ``/openapi.json``.

Production execution (P3-S1/P3-S4/P3-S5): :func:`build_context` wires the
*durable* execution path — :class:`PostgresJobRepository` +
:class:`DurableDAGRunner` over the composed production stage registry
(:mod:`umd.jobs.production`). ``InMemoryJobStore`` and ``SynchronousRunner`` are
NEVER instantiated here (they remain test-only doubles importable from
:mod:`umd.api.runner` / :mod:`umd.jobs.job`).

Execution mechanism: submission drives the durable runner synchronously through
the public route — the executor's atomic ``StageCompleted`` commits ARE the
worker callbacks, so a job never reports completion without real durable stage
output. This is an interim execution path ONLY: Hatchet (Plan I) remains the sole
production scheduler behind the same ``DAGRunner`` seam. The production stage
work performs NO in-process decoder/model invocation (pure-Python text ops run
in-process; modality decoders route through the sandbox dispatch seam).
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa
from fastapi import FastAPI, Request

from umd.api.consistency import ConsistencyGuard, ProjectionFreshness
from umd.api.deps import AppContext
from umd.api.errors import register_error_handlers
from umd.api.ratelimit import RateLimitGuard, TokenBucketRateLimiter
from umd.api.routers import (
    alignment,
    audit,
    claims,
    entities,
    jobs,
    query,
    search,
    segments,
    sources,
    system,
)
from umd.application.commands import SemanticCommandService
from umd.application.jobs import JobService
from umd.audit.service import AuditService
from umd.config import Settings, get_settings
from umd.jobs.production import StageWorkRegistryFactory, build_runtime
from umd.jobs.runner import DurableDAGRunner
from umd.jobs.stage_execution import DurableStageExecutor, RealBackoff, RetryPolicy
from umd.models.registry import ProviderRegistry
from umd.observability.logging import StructuredLogger
from umd.projections.base import ReplayDriver
from umd.projections.checkpoint import ProjectionCheckpointStore
from umd.projections.current import CurrentTierOneBuilder
from umd.projections.query import QueryService
from umd.projections.question import QuestionService
from umd.projections.search import SearchProjectionBuilder, SearchService
from umd.resolution.mentions import PostgresMentionRepository
from umd.resolution.resolution import PostgresSplitEnumerator, Resolver
from umd.security.capabilities import capability_report
from umd.security.sandbox import SubprocessSandboxRunner
from umd.segmentation.segmenters import segment_txt
from umd.storage.postgres.artifacts import PostgresArtifactStore
from umd.storage.postgres.job_repository import PostgresJobRepository
from umd.storage.postgres.ledger import SemanticLedger
from umd.storage.postgres.repositories import (
    PostgresEvidenceRepository,
    PostgresQuarantine,
    PostgresSegmentStore,
    PostgresSourceRepository,
    SourceMembershipService,
)
from umd.storage.postgres.stage_repository import JobRunAudit, StageRunRepository

_PROJECTION_QUERY = "current_tier1"
_PROJECTION_SEARCH = "search"


def engine_from_settings(settings: Settings) -> sa.Engine:
    """Build a SQLAlchemy engine from the configured Postgres DSN."""
    return sa.create_engine(
        settings.postgres.dsn,
        pool_pre_ping=True,
        pool_size=settings.postgres.pool_size,
        max_overflow=settings.postgres.max_overflow,
    )


def build_context(*, settings: Settings, engine: sa.Engine, source_store: Any) -> AppContext:
    """Construct the :class:`AppContext` bundle of services (testable standalone).

    Phase 3 wires the *production* execution path, never the test-only doubles:
    ``PostgresJobRepository`` + ``DurableDAGRunner`` over the composed production
    stage registry (:mod:`umd.jobs.production`). ``InMemoryJobStore`` and
    ``SynchronousRunner`` are never instantiated here.
    """
    ledger = SemanticLedger(engine)
    commands = SemanticCommandService(ledger)
    memberships = SourceMembershipService(engine)
    sources = PostgresSourceRepository(engine)
    segments = PostgresSegmentStore(engine)
    evidence = PostgresEvidenceRepository(engine)
    query = QueryService(engine)
    search = SearchService(engine)
    question = QuestionService(query, search)
    audit = AuditService(engine)

    # Phase-1 reversible entity resolver. This is the SAME resolution authority used
    # by the service layer (ledger append + mention rebind + quarantine); it is NOT a
    # second semantic authority and never writes projection stores (builders only).
    mentions = PostgresMentionRepository(engine)
    resolver = Resolver(
        ledger=ledger,
        enumerator=PostgresSplitEnumerator(engine, mentions),
        mentions=mentions,
        engine=engine,
        quarantine=PostgresQuarantine(engine).record,
    )

    # -- production execution wiring (P3-S1) --------------------------------
    # Build the composed production stage registry once from the production
    # runtime (never an empty ``{}``), then wire the durable runner + durable job
    # store. The executor's atomic StageCompleted commits are the worker
    # callbacks, so a job queued through the public route reaches completion only
    # via real committed stage output.
    checkpoint_store = ProjectionCheckpointStore(engine)
    replay = ReplayDriver(engine, checkpoint_store)
    providers = ProviderRegistry()
    runtime = build_runtime(
        engine=engine,
        settings=settings,
        source_store=source_store,
        commands=commands,
        ledger=ledger,
        segmenters={"txt": segment_txt},
        segments=segments,
        evidence=evidence,
        replay=replay,
        builders={
            "current_tier1": CurrentTierOneBuilder(),
            "search": SearchProjectionBuilder(),
        },
        providers=providers,
        sandbox=SubprocessSandboxRunner(),
        artifacts=PostgresArtifactStore(engine),
        observability=StructuredLogger("umd-api"),
        capabilities=capability_report(),
    )
    work_registry = StageWorkRegistryFactory.build(runtime)

    job_store = PostgresJobRepository(engine)
    executor = DurableStageExecutor(
        engine=engine,
        commands=commands,
        ledger=ledger,
        stage_repo=StageRunRepository(engine),
        audit=JobRunAudit(engine),
        quarantine=PostgresQuarantine(engine),
        retry=RetryPolicy(),
        backoff=RealBackoff(RetryPolicy()),
    )
    runner = DurableDAGRunner(executor=executor, store=job_store)
    jobs = JobService(store=job_store, runner=runner, commands=commands)

    query_guard = ConsistencyGuard(ProjectionFreshness(engine, _PROJECTION_QUERY), settings)
    search_guard = ConsistencyGuard(ProjectionFreshness(engine, _PROJECTION_SEARCH), settings)

    limiter = TokenBucketRateLimiter(settings.rate_limit)
    rate_guard = RateLimitGuard(limiter)

    ctx = AppContext(
        settings=settings,
        engine=engine,
        commands=commands,
        ledger=ledger,
        query=query,
        search=search,
        question=question,
        audit=audit,
        jobs=jobs,
        segments=segments,
        evidence=evidence,
        sources=sources,
        memberships=memberships,
        source_store=source_store,
        resolver=resolver,
        consistency=query_guard,
        freshness=query_guard.freshness,
        work_registry=work_registry,
    )
    ctx.extra["query_guard"] = query_guard
    ctx.extra["search_guard"] = search_guard
    ctx.extra["rate_guard"] = rate_guard
    ctx.extra["job_store"] = job_store
    ctx.extra["work_registry"] = work_registry
    return ctx


def create_app(
    *,
    engine: sa.Engine,
    source_store: Any,
    settings: Settings | None = None,
) -> FastAPI:
    """Create the FastAPI application bound to ``engine`` and ``source_store``."""
    settings = settings or get_settings()
    ctx = build_context(settings=settings, engine=engine, source_store=source_store)

    app = FastAPI(
        title="Universeity UMD REST API",
        version=settings.api.contract_version,
        description=(
            "Versioned structured/semantic query and complete REST boundary over "
            "the Universal Media Decomposer. Tier-0 ledger is the semantic "
            "authority; projections are never authoritative."
        ),
        openapi_tags=[
            {"name": "sources", "description": "Source descriptors, segments, locators, evidence"},
            {"name": "entities", "description": "Entity descriptors, merge/split/lock/unlock"},
            {"name": "claims", "description": "Claims, override, invalidate, provenance"},
            {"name": "segments", "description": "Segment edits (edit/split/merge/rerun)"},
            {"name": "alignment", "description": "Cross-source alignment"},
            {"name": "jobs", "description": "Job lifecycle"},
            {"name": "query", "description": "Structured + semantic query"},
            {"name": "search", "description": "Exact/fuzzy/hybrid search"},
            {"name": "audit", "description": "Audit / provenance"},
            {"name": "system", "description": "Health, readiness, capabilities, version"},
        ],
    )
    app.state.ctx = ctx
    register_error_handlers(app)

    if settings.api.cors_allow_origins:
        from fastapi.middleware.cors import CORSMiddleware

        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.api.cors_allow_origins,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def correlation_middleware(request: Request, call_next: Any) -> Any:
        request.state.correlation_id = request.headers.get("x-request-id") or uuid.uuid4().hex
        response = await call_next(request)
        response.headers["x-correlation-id"] = str(request.state.correlation_id)
        return response

    for r in (
        sources.router,
        entities.router,
        claims.router,
        segments.router,
        alignment.router,
        jobs.router,
        query.router,
        search.router,
        audit.router,
        system.router,
    ):
        app.include_router(r)

    return app


__all__ = [
    "create_app",
    "build_context",
    "engine_from_settings",
    "AppContext",
]
