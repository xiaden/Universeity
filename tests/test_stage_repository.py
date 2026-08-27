"""P3-S3: StageRunRepository.claim idempotency + JobRunAudit separation (postgres)."""

from __future__ import annotations

import uuid

import pytest
import sqlalchemy as sa

from umd.storage.postgres.stage_repository import (
    JobAuditAttempt,
    JobRunAudit,
    StageRunManifest,
    StageRunRepository,
)

pytestmark = pytest.mark.postgres


def test_stage_claim_is_authoritative_and_idempotent(umd_db: sa.Engine) -> None:
    repo = StageRunRepository(umd_db)
    key = str(uuid.uuid4())
    manifest = StageRunManifest(
        job_id="job-1",
        stage_name="FORMAT_ANALYSIS",
        input_manifest={"source": "s1"},
        config_digest="abc",
    )
    first = repo.claim(key, manifest)
    assert first.won is True
    assert first.status == "claimed"

    # A concurrent duplicate submission of the SAME idempotency_key claims nothing new.
    second = repo.claim(key, manifest)
    assert second.won is False
    assert second.status == "already_exists"
    assert second.id == first.id

    with umd_db.connect() as conn:
        n = conn.execute(
            sa.text("SELECT count(*) FROM stage_run WHERE idempotency_key=:k"), {"k": key}
        ).scalar()
    assert n == 1  # UNIQUE(idempotency_key) => single authoritative completion


def test_job_run_audit_records_are_separate_operational_stream(umd_db: sa.Engine) -> None:
    audit = JobRunAudit(umd_db)
    rec = audit.record(
        JobAuditAttempt(
            job_id="job-7",
            stage_name="ASR",
            action="complete",
            attempt=3,
            details={"decoder": "faster-whisper"},
        )
    )
    assert rec.id
    assert rec.action == "complete"
    assert rec.attempt == 3

    # The operational audit stream is a distinct table from the semantic ledger.
    with umd_db.connect() as conn:
        job_rows = conn.execute(sa.text("SELECT count(*) FROM job_run_audit")).scalar()
        event_rows = conn.execute(sa.text("SELECT count(*) FROM semantic_event")).scalar()
    assert job_rows == 1
    assert event_rows == 0  # JobRunAudit record() never writes a semantic event
