"""P1-S1: spec-first production stage-registry composition (Phase 2).

These tests are SPEC-FIRST — they FAIL until Phase 2 creates
``umd.jobs.production`` with a ``StageWorkRegistryFactory.build(runtime)`` that
composes every canonical ``STAGE_ORDER`` stage into a
:class:`umd.jobs.runner.StageWorkRegistry` of real executable work
(CONTRACTS.md "Production execution remediation contracts":60).

The module is imported lazily via :func:`importlib.import_module` so the tests
resolve the planned symbol at runtime (raising ``ImportError`` today) instead of
tripping the static type gate before the module exists.

Assertions pinned here (the binding contract):
  * every stage in ``STAGE_ORDER`` resolves to callable work through the factory;
  * a build that omits a canonical stage is a *configuration failure* (raises),
    never a silent "pending"/successful completion;
  * stage completion is impossible before durable segment/evidence/ledger output
    exists — the production work completes only through the
    :class:`DurableStageExecutor` + ``SemanticLedger.complete_and_append`` atomic
    path (mirrors ``test_stage_execution.py`` atomic-completion pattern);
  * a duplicate/restart submission does not repeat committed expensive work
    (executor replay semantics through the production registry).
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest
import sqlalchemy as sa

from job_helpers import SOURCE_ID, build_executor, ensure_source, make_manifest
from umd.domain.models import Evidence, EvidenceKind
from umd.jobs.dag import STAGE_ORDER

pytestmark = pytest.mark.postgres


def _production_module() -> Any:
    """Import the planned production composition module (created in Phase 2).

    ``umd.jobs.production`` does not exist until Phase 2; importing it here is
    exactly what makes these tests fail for the intended spec-first reason.
    """
    return importlib.import_module("umd.jobs.production")


def _build_registry(umd_db: sa.Engine, **runtime: Any) -> Any:
    """Build the production ``StageWorkRegistry`` via the factory (Phase 2)."""
    mod = _production_module()
    factory = mod.StageWorkRegistryFactory
    return factory.build({"engine": umd_db, **runtime})


def _completed_events(engine: sa.Engine) -> int:
    with engine.connect() as conn:
        return conn.execute(
            sa.text("SELECT count(*) FROM semantic_event WHERE event_type='StageCompleted'")
        ).scalar()


def test_every_stage_in_stage_order_resolves_to_work(umd_db: sa.Engine) -> None:
    """Every canonical stage is present and callable in the production registry."""
    ensure_source(umd_db)
    registry = _build_registry(umd_db)
    for stage in STAGE_ORDER:
        assert stage in registry, f"production registry is missing stage {stage}"
        assert callable(registry[stage]), f"stage {stage} work is not callable"


def test_absent_stage_is_configuration_failure_never_success(umd_db: sa.Engine) -> None:
    """A build omitting a canonical stage must raise, never silently succeed.

    ``StageWorkRegistryFactory.build`` composes *every* stage in ``STAGE_ORDER``;
    an absent stage is a configuration failure (CONTRACTS.md:60). Driving the
    failure via a ``stages`` runtime filter is an interpretation of that contract
    until Phase 2 fixes the exact ``build(runtime)`` shape.
    """
    ensure_source(umd_db)
    mod = _production_module()
    # The full build must cover every canonical stage exactly.
    full = mod.StageWorkRegistryFactory.build({"engine": umd_db})
    assert set(full) == set(STAGE_ORDER)
    # Omitting INGEST is a configuration failure -> build must raise.
    with pytest.raises(Exception, match="INGEST"):
        mod.StageWorkRegistryFactory.build(
            {"engine": umd_db, "stages": [s for s in STAGE_ORDER if s != "INGEST"]}
        )


def test_completion_requires_durable_output_via_ledger(umd_db: sa.Engine) -> None:
    """Stage completion is impossible before durable artifact/evidence/ledger
    output exists — the production work completes atomically through the
    DurableStageExecutor + SemanticLedger (mirrors test_stage_execution.py)."""
    ensure_source(umd_db)
    registry = _build_registry(umd_db)
    executor, _ledger = build_executor(umd_db)
    manifest = make_manifest("INGEST", job_id="prod-atomic")
    record = executor.run(manifest, registry["INGEST"])
    assert record.state == "complete"

    # Completion committed durable output: artifact/evidence refs on the stage_run
    # row AND one StageCompleted semantic event, atomically. A completion is
    # impossible without both.
    with umd_db.connect() as conn:
        row = conn.execute(
            sa.text("SELECT artifact_refs, evidence_refs FROM stage_run WHERE idempotency_key=:k"),
            {"k": manifest.idempotency_key()},
        ).first()
    assert row is not None and row.artifact_refs, "no durable artifact output on completion"
    # The production INGEST binding commits durable evidence refs
    # (``source_bytes:<ocfl_ref>``) into the same atomically-completed run row.
    assert isinstance(row.evidence_refs, list) and row.evidence_refs, (
        "INGEST should produce durable evidence_refs on completion"
    )
    assert _completed_events(umd_db) == 1, "no StageCompleted ledger append on completion"


def test_restart_submission_does_not_repeat_committed_work(umd_db: sa.Engine) -> None:
    """A duplicate/restart submission replays the committed run without re-running
    the expensive production stage work (executor replay semantics)."""
    ensure_source(umd_db)
    registry = _build_registry(umd_db)
    executor, _ledger = build_executor(umd_db)
    calls: list[str] = []
    original = registry["FORMAT_ANALYSIS"]

    def counting(manifest: Any) -> Any:
        calls.append(manifest.stage_name)
        return original(manifest)

    manifest = make_manifest("FORMAT_ANALYSIS", job_id="prod-restart")
    first = executor.run(manifest, counting)
    second = executor.run(manifest, counting)  # identical dedup key -> replayed
    assert first.state == "complete"
    assert second.replayed is True
    assert calls == ["FORMAT_ANALYSIS"], "committed production work ran more than once"
    assert _completed_events(umd_db) == 1, "duplicate submission appended a second StageCompleted"


def test_production_evidence_recorders_set_config_digest(umd_db: sa.Engine) -> None:
    """(QA R1 F4) Every Evidence the production recorders emit carries a stable
    config_digest, so ``uq_evidence_identity`` ``(source_id, locator, evidence_kind,
    config_digest)`` dedups identical re-records on a re-run instead of NULL-vs-NULL
    treating them as distinct and duplicating rows (CONTRACTS.md:12 evidence batches
    carry a configuration digest)."""
    production = importlib.import_module("umd.jobs.production")
    from umd.domain.evidence import EvidenceBatch
    from umd.storage.postgres.repositories import PostgresEvidenceRepository

    src = {
        "id": SOURCE_ID,
        "media_kind": "txt",
        "format": None,
    }

    # 1. Every recorder-produced Evidence is tagged with a non-null config_digest.
    captured: list[Evidence] = []

    class _Capture:
        def record(self, batch: EvidenceBatch):
            captured.extend(batch.records)
            return object()

    composer = production._Composer(  # noqa: SLF001 - registry-internal, test-only
        umd_db, production.ProductionRuntime(engine=umd_db)
    )
    composer._evidence = _Capture()  # noqa: SLF001 - swap repo for a capture double
    composer._record_format_evidence(src, "hello world")  # noqa: SLF001
    composer._span_evidence(  # noqa: SLF001
        src,
        "00000000-0000-0000-0000-000000000001",
        "document/1",
        0.9,
        "hello world",
        stage="LOW_LEVEL_EXTRACTION",
    )
    composer._record_media_format_evidence(src)  # noqa: SLF001
    assert captured, "recorders produced no evidence"
    for ev in captured:
        assert ev.config_digest, (
            f"recorder evidence {ev.evidence_kind}@{ev.locator} missing config_digest"
        )

    # 2. Dedup intent with the digest set: re-recording identical evidence through
    # the real repo is reported as ``existing`` (never re-inserted) against the
    # uq_evidence_identity unique index.
    ensure_source(umd_db)
    repo = PostgresEvidenceRepository(umd_db)
    record = Evidence(
        source_id=SOURCE_ID,
        evidence_kind=EvidenceKind.METADATA,
        locator="format_analysis:dedup-probe",
        extraction_stage="FORMAT_ANALYSIS",
        tool_versions={"format_analyzer": "umd-txt@1"},
        config_digest=production._TEXT_EVIDENCE_CONFIG_DIGEST,  # noqa: SLF001
        confidence=0.99,
        quality={},
    )
    first = repo.record(EvidenceBatch(records=[record]))
    second = repo.record(EvidenceBatch(records=[record]))  # identical -> dedup
    assert first.total == 1 and len(first.created) == 1
    assert second.total == 1 and len(second.created) == 0
    assert len(second.existing) == 1, "identical re-record should dedup not re-insert"
    with umd_db.connect() as conn:
        count = conn.execute(
            sa.text("SELECT count(*) FROM evidence WHERE locator=:loc AND config_digest=:d"),
            {"loc": record.locator, "d": record.config_digest},
        ).scalar()
    assert count == 1, "uq_evidence_identity did not dedup identical digest-bearing rows"


def test_structural_analysis_evidence_has_non_null_config_digest_and_dedups(
    umd_db: sa.Engine,
) -> None:
    """(QA R2 M2) The STRUCTURAL_ANALYSIS evidence path passes a stable
    config_digest into ``analyze_text`` (never NULL), so its text-span evidence
    rows dedup via ``uq_evidence_identity`` on a crash-retry re-record instead of
    NULL-vs-NULL duplicating. Extends F4's recorder check to the one remaining
    evidence path that previously passed ``config_digest=None``.
    """
    import importlib

    from umd.domain.evidence import EvidenceBatch
    from umd.storage.postgres.repositories import PostgresEvidenceRepository

    production = importlib.import_module("umd.jobs.production")
    ensure_source(umd_db)

    # 1. Drive the REAL structural binding and capture every Evidence it emits.
    captured: list[Evidence] = []

    class _Capture:
        def record(self, batch: EvidenceBatch):
            captured.extend(batch.records)
            return object()

    composer = production._Composer(  # noqa: SLF001 - registry-internal, test-only
        umd_db, production.ProductionRuntime(engine=umd_db)
    )
    composer._evidence = _Capture()  # noqa: SLF001
    # Provide parser-visible text so the structural path actually runs analyze_text
    # (source_store is otherwise absent -> no evidence recorded).
    composer._parsed_text = lambda _src: (b"x", "Alice and Bob spoke together.")  # type: ignore[method-assign]
    manifest = make_manifest("STRUCTURAL_ANALYSIS")  # source_id=SOURCE_ID (media_kind=text)
    composer._structural_analysis(manifest)  # noqa: SLF001
    assert captured, "structural analysis recorded no evidence"
    for ev in captured:
        assert ev.config_digest, (
            f"structural evidence {ev.locator} missing config_digest (NULL would "
            "bypass uq_evidence_identity dedup)"
        )

    # 2. Dedup proof with the digest set: re-recording the identical structural
    # evidence through the real repo reports ``existing`` (created=0) and the DB
    # count for each locator+digest stays 1.
    # Note: analyze_text may emit multiple evidence rows at the SAME locator
    # (dialogue/narration span + candidate findings), so collapse by identity key
    # (source_id, locator, evidence_kind, config_digest) — the exact columns
    # uq_evidence_identity dedups on — before the re-record proof.
    repo = PostgresEvidenceRepository(umd_db)
    unique: list[Evidence] = []
    seen: set[tuple[str, str, str, str]] = set()
    for ev in captured:
        key = (str(ev.source_id), ev.locator, str(ev.evidence_kind), ev.config_digest or "")
        if key in seen:
            continue
        seen.add(key)
        unique.append(ev)
    assert unique, "no distinct structural evidence identity to dedup"
    for ev in unique:
        first = repo.record(EvidenceBatch(records=[ev]))
        second = repo.record(EvidenceBatch(records=[ev]))  # identical -> dedup
        assert first.total == 1 and len(first.created) == 1
        assert second.total == 1 and len(second.created) == 0
        assert len(second.existing) == 1
        with umd_db.connect() as conn:
            count = conn.execute(
                sa.text(
                    "SELECT count(*) FROM evidence "
                    "WHERE locator=:l AND config_digest=:d AND source_id=:s"
                ),
                {"l": ev.locator, "d": ev.config_digest, "s": SOURCE_ID},
            ).scalar()
        assert count == 1, f"uq_evidence_identity did not dedup structural evidence {ev.locator}"
