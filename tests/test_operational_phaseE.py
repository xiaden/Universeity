"""Phase E / P1-S4: OPERATIONAL tests over live Postgres.

These exercise the operational SLOs against the real services — never fabricating
an active external dependency:

* worker/sandbox crash -> late-stage resume (effective-once completion)
* duplicate stage submissions -> single execution
* transient retry backoff -> retry count matches attempts (no amplification)
* projection rebuild via ProjectionController (write-through builder only)
* authority-poison pause alerts + no auto-resume
* queue bursts -> reindex concurrency cadence (bounded + min interval)
* token-wait backoff -> bounded 503, never stale
* per-source decomposition report (P1-S2)

Every failure mode is exercised at the real boundary the DD names.
"""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from job_helpers import SOURCE_ID, build_executor, ensure_source, make_manifest
from test_projection_phase2 import SearchProjectionBuilder, _mention, _override
from umd.jobs.stage_execution import (
    MalformedInputError,
    RetryPolicy,
    StageOutcome,
    StageQuarantinedError,
)
from umd.operations.controller import ProjectionController, ReindexCoordinator
from umd.operations.reports import SourceReportBuilder
from umd.projections.base import ReplayDriver
from umd.projections.checkpoint import ProjectionCheckpointStore
from umd.projections.vector import EmbeddingProjectionBuilder
from umd.storage.postgres.ledger import SemanticLedger
from umd.storage.postgres.stage_repository import StageRunManifest, StageRunRepository
from umd.storage.postgres.tables import metadata as db_meta

pytestmark = pytest.mark.postgres

_job_t = db_meta.tables["job"]


def _completed(engine: sa.Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(
            sa.text("SELECT count(*) FROM semantic_event WHERE event_type='StageCompleted'")
        ).scalar()


def _insert_job(engine: sa.Engine, job_id: str, status: str) -> None:
    with engine.begin() as conn:
        conn.execute(
            _job_t.insert().values(
                id=job_id, source_id=uuid.UUID(SOURCE_ID), dag_universe="base", status=status
            )
        )


# ---------------------------------------------------------------------------
# worker/sandbox crash -> late-stage resume (restart-resume + crash runbooks)
# ---------------------------------------------------------------------------


def test_worker_crash_then_restart_resumes_without_double_commit(umd_db: sa.Engine) -> None:
    ensure_source(umd_db)
    key = make_manifest("ENTITY_RESOLUTION").idempotency_key()
    # a worker claims the stage, writes an artifact, then crashes pre-commit
    claim = StageRunRepository(umd_db).claim(
        key, StageRunManifest(stage_name="ENTITY_RESOLUTION", job_id="job-crash", input_manifest={})
    )
    assert claim.won
    assert _completed(umd_db) == 0

    # restart: a fresh executor re-drives the same deterministic manifest.
    executor2, _ledger = build_executor(umd_db)
    calls = []

    def resume_work(_m):
        calls.append(1)
        return StageOutcome(artifact_refs=["art:resumed"], evidence_refs=["ev:r"])

    rec = executor2.run(make_manifest("ENTITY_RESOLUTION"), resume_work)
    assert rec.state == "complete"
    assert len(calls) == 1
    assert _completed(umd_db) == 1  # exactly one StageCompleted, not two


# ---------------------------------------------------------------------------
# duplicate stage submissions -> single execution
# ---------------------------------------------------------------------------


def test_duplicate_stage_submission_runs_work_once(umd_db: sa.Engine) -> None:
    ensure_source(umd_db)
    executor, _ledger = build_executor(umd_db)
    calls = []

    def work(_m):
        calls.append(1)
        return StageOutcome(artifact_refs=["a:1"], evidence_refs=[])

    manifest = make_manifest("FORMAT_ANALYSIS")
    first = executor.run(manifest, work)
    second = executor.run(manifest, work)  # identical key -> duplicate
    assert first.state == "complete"
    assert second.replayed is True
    assert len(calls) == 1
    assert _completed(umd_db) == 1


# ---------------------------------------------------------------------------
# transient retry backoff without retry amplification
# ---------------------------------------------------------------------------


def test_transient_backoff_retries_once_per_attempt(umd_db: sa.Engine) -> None:
    ensure_source(umd_db)
    executor, _ledger = build_executor(umd_db, retry=RetryPolicy(max_attempts=3))
    attempts: list[int] = []

    def flaky(_m):
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("transient hiccup")
        return StageOutcome(artifact_refs=["a"], evidence_refs=[])

    rec = executor.run(make_manifest("LOW_LEVEL_EXTRACTION"), flaky)
    assert rec.attempts == 3 and rec.state == "complete"
    with umd_db.connect() as conn:
        retries = conn.execute(
            sa.text(
                "SELECT count(*) FROM job_run_audit "
                "WHERE stage_name='LOW_LEVEL_EXTRACTION' AND action='retry'"
            )
        ).scalar()
    # exactly one retry per failed attempt up to max_attempts — no amplification
    assert retries == 2


def test_token_wait_bounded_503_never_stale(umd_db: sa.Engine) -> None:
    from umd.api.consistency import ConsistencyGuard, ProjectionFreshness
    from umd.api.errors import ConsistencyLagError
    from umd.config import Settings

    ledger = SemanticLedger(umd_db)
    ledger.append([_mention(SOURCE_ID, "token-wait-source")])
    with umd_db.connect() as conn:
        tail = int(conn.execute(sa.text("SELECT max(seq) FROM semantic_event")).scalar() or 0)

    store = ProjectionCheckpointStore(umd_db)
    r = ReplayDriver(umd_db, store).run(EmbeddingProjectionBuilder(), wipe=True)
    assert r.applied_seq == tail  # caught up

    guard = ConsistencyGuard(
        ProjectionFreshness(umd_db, "vector"), Settings(lag_budget_seconds=0.05)
    )
    snap = guard.ensure_read(token=tail)
    assert snap.applied_seq == tail
    with pytest.raises(ConsistencyLagError) as ei:
        guard.ensure_read(token=tail + 1)  # beyond applied -> bounded 503, never stale
    assert ei.value.code == "consistency_transient_lag"


# ---------------------------------------------------------------------------
# projection rebuild via the controller (write-through builder only)
# ---------------------------------------------------------------------------


def test_projection_rebuild_catches_up_through_builder(umd_db: sa.Engine) -> None:
    ledger = SemanticLedger(umd_db)
    ledger.append([_mention("s:1", "FirstMention")])
    controller = ProjectionController(umd_db, store=ProjectionCheckpointStore(umd_db))
    r1 = controller.rebuild(EmbeddingProjectionBuilder(), wipe=True)
    assert r1["started"] is True
    assert r1["report"]["ledger_tail"] == r1["report"]["applied_seq"]  # caught up
    assert r1["budget"]["within_budget"] is True
    assert controller.checkpoint("vector")["status"] == "fresh"

    # new ledger events -> stale, then a rebuild catches up again
    ledger.append([_mention("s:2", "SecondMention")])
    assert controller.checkpoint("vector")["status"] == "stale"
    r2 = controller.rebuild(EmbeddingProjectionBuilder(), wipe=False)
    assert r2["started"] is True
    assert controller.checkpoint("vector")["status"] == "fresh"


# ---------------------------------------------------------------------------
# authority-poison pause: alerts surface, no auto-resume
# ---------------------------------------------------------------------------


def test_authority_poison_pause_alerts_and_no_auto_resume(umd_db: sa.Engine) -> None:
    ledger = SemanticLedger(umd_db)
    ledger.append([_mention("s:1", "Sherlock")])
    ledger.append([_override("e:9", "speaker", "canonical speaker")])

    controller = ProjectionController(umd_db, store=ProjectionCheckpointStore(umd_db))
    r = controller.rebuild(SearchProjectionBuilder(), wipe=True)
    assert r["started"] is True
    assert r["report"]["paused"] is True
    assert r["report"]["pause_reason"] and "authority" in r["report"]["pause_reason"]

    assert controller.pause_alerts()  # the alert surfaces (real data)
    # a second (non-force) run stays paused — never silently continues stale
    r2 = controller.rebuild(SearchProjectionBuilder(), wipe=False)
    assert r2["report"]["paused"] is True


# ---------------------------------------------------------------------------
# queue bursts -> reindex concurrency cadence (bounded, min-interval)
# ---------------------------------------------------------------------------


def test_reindex_coordinator_absorbs_queue_burst() -> None:
    coord = ReindexCoordinator()
    assert coord.concurrent_cap == 1
    assert coord.acquire("p1") is True
    assert coord.acquire("p2") is False  # concurrency cap honoured (burst serializes)
    assert coord.active_rebuilds() == ["p1"]
    coord.release("p1")
    assert coord.acquire("p2") is True
    # immediate re-acquire of the same projection is refused (cap reaches 1)
    assert coord.acquire("p2") is False
    coord.release("p2")


# ---------------------------------------------------------------------------
# per-source decomposition report (P1-S2)
# ---------------------------------------------------------------------------


def test_source_report_covers_stages_retries_and_quarantine(umd_db: sa.Engine) -> None:
    ensure_source(umd_db)
    _insert_job(umd_db, "job-ok", "COMPLETE")

    executor, _ledger = build_executor(umd_db, retry=RetryPolicy(max_attempts=3))
    attempts: list[int] = []

    def flaky(_m):
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("transient")
        return StageOutcome(artifact_refs=["art:ok"], evidence_refs=["ev:ok"])

    executor.run(make_manifest("BASIC_SEGMENTATION", job_id="job-ok"), flaky)

    bad_job = SOURCE_ID[:12]
    _insert_job(umd_db, bad_job, "FAILED")
    bad_executor, _ledger2 = build_executor(umd_db)
    locator = f"source://{SOURCE_ID}/bad"

    def bad(_m):
        raise MalformedInputError("corrupt", locator)

    with pytest.raises(StageQuarantinedError):
        bad_executor.run(make_manifest("FORMAT_ANALYSIS", job_id=bad_job), bad)

    report = SourceReportBuilder(umd_db).build(SOURCE_ID)
    stages = [s for j in report.jobs for s in j.stages]
    ok_stage = next((s for s in stages if s.stage_name == "BASIC_SEGMENTATION"), None)
    assert ok_stage is not None and ok_stage.retries == 2
    assert any(q["locator"] == locator for q in report.quarantine)
    # rerun causation: the failed job's incomplete branch is surfaced
    failed = next(j for j in report.jobs if j.job_id == bad_job)
    assert failed.incomplete_branches  # the quarantined stage is reported incomplete
