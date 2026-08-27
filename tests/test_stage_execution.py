"""P1-S2/P1-S5: durable stage execution over live Postgres (claim-before-side-effect,
effective-once completion, quarantine, bounded retry, crash/resume)."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from job_helpers import build_executor, ensure_source, make_manifest
from umd.jobs.stage_execution import (
    MalformedInputError,
    StageOutcome,
    StageQuarantinedError,
)
from umd.storage.postgres.stage_repository import StageRunManifest, StageRunRepository

pytestmark = pytest.mark.postgres


def _stage_run_status(engine: sa.Engine, key: str) -> str:
    with engine.connect() as conn:
        return conn.execute(
            sa.text("SELECT status FROM stage_run WHERE idempotency_key=:k"), {"k": key}
        ).scalar()


def _completed_events(engine: sa.Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(
            sa.text("SELECT count(*) FROM semantic_event WHERE event_type='StageCompleted'")
        ).scalar()


def test_no_repeated_successful_stage_work(umd_db: sa.Engine) -> None:
    ensure_source(umd_db)
    executor, _ledger = build_executor(umd_db)
    calls: list[str] = []

    def work(m):
        calls.append(m.stage_name)
        return StageOutcome(artifact_refs=["art:1"], evidence_refs=["ev:9"])

    manifest = make_manifest("FORMAT_ANALYSIS")
    first = executor.run(manifest, work)
    second = executor.run(manifest, work)  # identical dedup key -> must NOT re-run work
    assert first.state == "complete"
    assert second.replayed is True
    assert calls == ["FORMAT_ANALYSIS"]  # work ran exactly once
    assert _completed_events(umd_db) == 1  # one StageCompleted, not two


def test_claim_before_side_effect_and_atomic_completion(umd_db: sa.Engine) -> None:
    ensure_source(umd_db)
    executor, _ledger = build_executor(umd_db)

    def work(_m):
        return StageOutcome(artifact_refs=["art:42"], evidence_refs=["ev:7"])

    manifest = make_manifest("INGEST", job_id="job-atomic")
    rec = executor.run(manifest, work)
    assert rec.state == "complete"
    assert rec.claim.won is True

    # The stage_run row committed both artifact refs and completion in one txn.
    with umd_db.connect() as conn:
        row = conn.execute(
            sa.text("SELECT status, artifact_refs FROM stage_run WHERE idempotency_key=:k"),
            {"k": manifest.idempotency_key()},
        ).first()
    assert row.status == "complete"
    assert "art:42" in row.artifact_refs
    # One StageCompleted semantic event committed atomically with the artifacts.
    assert _completed_events(umd_db) == 1


def test_deterministic_malformed_input_is_quarantined_not_retried(umd_db: sa.Engine) -> None:
    ensure_source(umd_db)
    # Even with max_attempts=5 the deterministic failure must not retry (quarantine).
    executor, _ledger = build_executor(umd_db, retry=_retry(5))
    calls: list[int] = []

    def bad_work(_m):
        calls.append(1)
        raise MalformedInputError("corrupt structure", "locator://bad")

    manifest = make_manifest("BASIC_SEGMENTATION")
    with pytest.raises(StageQuarantinedError):
        executor.run(manifest, bad_work)
    assert len(calls) == 1  # no retry storm
    assert _stage_run_status(umd_db, manifest.idempotency_key()) == "quarantined"
    with umd_db.connect() as conn:
        n = conn.execute(sa.text("SELECT count(*) FROM quarantine")).scalar()
    assert n == 1


def test_transient_failure_retries_with_backoff_then_completes(umd_db: sa.Engine) -> None:
    ensure_source(umd_db)
    executor, _ledger = build_executor(umd_db, retry=_retry(3))
    attempts: list[int] = []

    def flaky(_m):
        attempts.append(1)
        if len(attempts) < 3:
            raise RuntimeError("transient network hiccup")
        return StageOutcome(artifact_refs=["art:3"], evidence_refs=[])

    manifest = make_manifest("LOW_LEVEL_EXTRACTION")
    rec = executor.run(manifest, flaky)
    assert rec.state == "complete"
    assert rec.attempts == 3
    assert len(attempts) == 3
    with umd_db.connect() as conn:
        actions = [
            r[0]
            for r in conn.execute(
                sa.text(
                    "SELECT action FROM job_run_audit WHERE stage_name='LOW_LEVEL_EXTRACTION'"
                    " ORDER BY created_at"
                )
            ).fetchall()
        ]
    # start + retry(retry) + complete
    assert "retry" in actions and actions[0] == "start" and actions[-1] == "complete"


def test_crash_after_artifact_write_then_restart_resume(umd_db: sa.Engine) -> None:
    ensure_source(umd_db)
    # Simulate a worker that writes artifacts, then dies before committing the
    # completion (a plain out-of-band side-effect + left-claimed stage row).
    artifacts_written: list[str] = []
    key = make_manifest("ENTITY_RESOLUTION").idempotency_key()
    manifest_row = StageRunManifest(
        stage_name="ENTITY_RESOLUTION", job_id="job-crash", input_manifest={}
    )
    claim = StageRunRepository(umd_db).claim(key, manifest_row)
    assert claim.won
    artifacts_written.append("art:crash-partial")  # artifact persisted, then CRASH

    # Stage run is still 'claimed' (in-flight) and NO completion was committed.
    assert _stage_run_status(umd_db, key) == "claimed"
    assert _completed_events(umd_db) == 0

    # Restart: a fresh process re-drives the SAME manifest. The executor resumes
    # the crashed stage (already_exists + status=claimed) and completes it.
    executor2, _ledger = build_executor(umd_db)

    def resume_work(_m):
        artifacts_written.append("art:resumed")
        return StageOutcome(artifact_refs=list(artifacts_written), evidence_refs=["ev:r"])

    rec = executor2.run(make_manifest("ENTITY_RESOLUTION"), resume_work)
    assert rec.state == "complete"
    assert _stage_run_status(umd_db, key) == "complete"
    assert _completed_events(umd_db) == 1


def test_job_run_audit_is_operational_stream_not_semantic(umd_db: sa.Engine) -> None:
    ensure_source(umd_db)
    executor, _ledger = build_executor(umd_db)
    executor.run(make_manifest("CROSS_SOURCE_ALIGNMENT", job_id="job-ops"), ok_work())
    with umd_db.connect() as conn:
        audits = conn.execute(
            sa.text("SELECT action FROM job_run_audit WHERE job_id='job-ops'")
        ).fetchall()
        stage_completions = conn.execute(
            sa.text("SELECT count(*) FROM semantic_event WHERE event_type='StageCompleted'")
        ).scalar()
    assert {a[0] for a in audits} == {"start", "complete"}  # separate operational stream
    assert stage_completions == 1


def ok_work():
    def _w(_m):
        return StageOutcome(artifact_refs=["a"], evidence_refs=[])

    return _w


def _retry(max_attempts: int):
    from umd.jobs.stage_execution import RetryPolicy

    return RetryPolicy(max_attempts=max_attempts)
