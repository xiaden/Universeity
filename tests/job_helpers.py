"""Shared doubles + wiring for Phase-B job tests (not collected by pytest)."""

from __future__ import annotations

import uuid as _uuid
from types import SimpleNamespace
from typing import Any

import sqlalchemy as sa

from umd.application.commands import SemanticCommandService
from umd.jobs.stage_execution import (
    DurableStageExecutor,
    NoWaitBackoff,
    RetryPolicy,
    StageManifest,
    StageOutcome,
    StageWork,
)
from umd.storage.postgres.ledger import SemanticLedger
from umd.storage.postgres.repositories import PostgresQuarantine
from umd.storage.postgres.stage_repository import JobRunAudit, StageRunRepository

#: A stable, valid UUID used as the seed source for durable executor tests.
SOURCE_ID = "b3f98f72-0000-0000-0000-000000000000"

#: A stable, valid UUID carrying the same source for ledger-payload resolution.
_job_source = SOURCE_ID


def build_executor(
    engine: sa.Engine,
    *,
    retry: RetryPolicy | None = None,
) -> tuple[DurableStageExecutor, SemanticLedger]:
    """Wire a real durable executor + ledger over a migrated Postgres engine."""
    ledger = SemanticLedger(engine)
    executor = DurableStageExecutor(
        engine=engine,
        commands=SemanticCommandService(ledger),
        ledger=ledger,
        stage_repo=StageRunRepository(engine),
        audit=JobRunAudit(engine),
        quarantine=PostgresQuarantine(engine),
        retry=retry,
        backoff=NoWaitBackoff(),
    )
    return executor, ledger


def ensure_source(engine: sa.Engine, source_id: str = _job_source) -> None:
    """Insert a source row so stage_run FK + StageCompleted payload resolve."""
    from umd.storage.postgres.tables import metadata as _meta

    src_t = _meta.tables["source"]
    with engine.begin() as conn:
        conn.execute(
            src_t.insert().values(
                id=_uuid.UUID(source_id),
                ocfl_ref=f"urn:ocfl:{source_id}",
                sha512="d" * 128,
                size_bytes=42,
                media_kind="text",
                original_name="seed.txt",
            )
        )


def make_manifest(
    stage: str, *, job_id: str = "job-id", dag_universe: str | None = None
) -> StageManifest:
    return StageManifest(
        job_id=job_id,
        stage_name=stage,
        source_id=SOURCE_ID,
        dag_universe=dag_universe,
        evidence_refs=[],
        input_manifest={"source_id": SOURCE_ID},
    )


class FakeExecutor:
    """Executor double for runner/JobService unit tests (no DB).

    Marks every stage ``complete`` immediately and records how many times each
    stage's work was invoked so rework-vs-dedupe assertions stay meaningful.
    """

    def __init__(self) -> None:
        self.calls: list[str] = []

    def run(self, manifest: StageManifest, work: StageWork) -> Any:
        self.calls.append(manifest.stage_name)
        outcome = work(manifest)
        state = getattr(outcome, "state", "complete")
        replayed = getattr(outcome, "replayed", False)
        return SimpleNamespace(
            state=state,
            claim=SimpleNamespace(idempotency_key=f"k-{manifest.stage_name}"),
            attempts=1,
            replayed=replayed,
        )


def ok(_manifest: StageManifest) -> Any:
    """A stage-work that always succeeds."""
    return StageOutcome(artifact_refs=[], evidence_refs=[])
