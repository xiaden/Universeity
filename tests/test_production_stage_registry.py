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
from types import SimpleNamespace
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
    # Repoint the structural-analysis seam at the DISPATCH seam (Plan L P3-S2):
    # the worker threads the dispatched result into STRUCTURAL_ANALYSIS instead
    # of re-normalizing raw bytes via _parsed_text, so drive the stage through
    # the dispatch seam with a route="text" result (source_store is otherwise
    # absent -> the real _dispatch_text would return None and record no evidence).
    composer._dispatch_text = lambda _src: SimpleNamespace(  # type: ignore[method-assign]
        route="text",
        text="Alice and Bob spoke together.",
        parser="txt",
        parser_version="umd-txt@1",
        decoder_version="umd-stdlib-decode@1",
        config_digest="umd-dispatch@1",
        non_text=False,
        warnings=[],
    )
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


# ---------------------------------------------------------------------------
# Plan M P3-S3: STRUCTURAL_ANALYSIS runs deterministic-only AND optional hybrid
# (provider configured-but-unavailable) with IDENTICAL deterministic
# observations — DAG topology and completion semantics unchanged.
# ---------------------------------------------------------------------------


def test_structural_analysis_deterministic_and_hybrid_modes_identical(
    umd_db: sa.Engine,
) -> None:
    """The existing structural-analysis stage must run in BOTH the default
    deterministic-only mode and the optional hybrid mode (a provider configured
    but unavailable/disabled) while producing IDENTICAL deterministic
    observations, without changing DAG topology or completion semantics.

    This proves the provider path is additive and honest: configuring a semantic
    provider that cannot resolve does NOT disturb the deterministic baseline and
    does NOT fabricate provider observations — it only surfaces a truthful
    unavailable-provider warning.
    """
    import json

    from umd.config import SemanticSettings, Settings
    from umd.domain.evidence import EvidenceBatch

    production = importlib.import_module("umd.jobs.production")
    ensure_source(umd_db)

    dispatch_double = SimpleNamespace(
        route="text",
        text=(
            "Alice and the White Rabbit talked together.\n"
            '"Hello," said Alice. "Where are you going?"\n'
            "The White Rabbit hurried away."
        ),
        parser="txt",
        parser_version="umd-txt@1",
        decoder_version="umd-stdlib-decode@1",
        config_digest="umd-dispatch@1",
        non_text=False,
        warnings=[],
    )

    def _run(settings: Settings | None) -> tuple[list[Evidence], Any]:
        captured: list[Evidence] = []

        class _Capture:
            def record(self, batch: EvidenceBatch):  # type: ignore[no-untyped-def]
                captured.extend(batch.records)
                return object()

        composer = production._Composer(  # noqa: SLF001
            umd_db,
            production.ProductionRuntime(engine=umd_db, settings=settings),
        )
        composer._evidence = _Capture()  # noqa: SLF001
        composer._dispatch_text = lambda _src: dispatch_double  # noqa: SLF001
        manifest = make_manifest("STRUCTURAL_ANALYSIS")
        outcome = composer._structural_analysis(manifest)  # noqa: SLF001
        return captured, outcome

    def _norm(evs: list[Evidence]) -> list[tuple[Any, ...]]:
        # Deterministic evidence identity minus the random row uuid: identical
        # observations in both modes must serialize identically.
        return sorted(
            (
                ev.evidence_kind,
                ev.locator,
                ev.extraction_stage,
                tuple(sorted(ev.tool_versions.items())),
                ev.config_digest,
                ev.confidence,
                json.dumps(ev.quality, sort_keys=True, default=str),
            )
            for ev in evs
        )

    # Mode A: default deterministic-only (no semantic provider configured).
    det_evidence, det_out = _run(None)
    # Mode B: optional hybrid — provider configured but unavailable (no registry)
    # -> honest degradation to the deterministic baseline.
    hybrid_evidence, hybrid_out = _run(
        Settings(semantic=SemanticSettings(provider="ollama", model="qwen"))
    )

    assert det_evidence, "deterministic mode recorded no evidence"
    # IDENTICAL deterministic observations in both modes.
    assert _norm(det_evidence) == _norm(hybrid_evidence), (
        "configured-but-unavailable provider must not disturb the deterministic "
        "baseline observations"
    )
    # Honest difference: hybrid surfaces the unavailable-provider warning.
    assert det_out.warnings == []
    assert any(
        any(w in word for w in ("unavailable", "unsupported", "disabled"))
        for word in hybrid_out.warnings
    ), hybrid_out.warnings

    # DAG topology unchanged: STRUCTURAL_ANALYSIS stays a canonical stage.
    assert "STRUCTURAL_ANALYSIS" in STAGE_ORDER
    # Completion semantics unchanged: identical, non-empty artifact/evidence refs.
    assert det_out.artifact_refs == hybrid_out.artifact_refs
    assert det_out.evidence_refs == hybrid_out.evidence_refs
    assert det_out.artifact_refs, "structural analysis must produce durable refs"


# ---------------------------------------------------------------------------
# Plan N P3-S3: the production ENTITY_RESOLUTION stage emits MORE THAN ONE
# canonical entity from a realistic multi-chapter book input and NEVER emits
# the old source-level canonical placeholder ``entity:canonical:<source_id>``.
# ---------------------------------------------------------------------------


def test_entity_resolution_stage_live_command_path_option_b(umd_db: sa.Engine) -> None:
    """P4-S6: the REAL command path over live PostgreSQL — Option B shape.

    Drives the production ``ENTITY_RESOLUTION`` binding (no ``_apply_resolution``
    stub) over committed multi-chapter candidate evidence: three distinct
    characters with aliases and one ambiguous alias. Proves a live run commits
    the expected mention/alias events, leaves text-resolution mention FK values
    NULL, exposes canonical decisions through current-state/query/search seams,
    never emits the old source-level placeholder, and keeps the ambiguous alias
    unresolved/reviewable.
    """
    from umd.application.commands import SemanticCommandService
    from umd.domain.evidence import EvidenceBatch
    from umd.domain.models import Evidence, EvidenceKind
    from umd.projections.base import ReplayDriver
    from umd.projections.checkpoint import ProjectionCheckpointStore
    from umd.projections.query import QueryService, StructuredQuery
    from umd.projections.search import SearchProjectionBuilder
    from umd.storage.postgres.ledger import SemanticLedger
    from umd.storage.postgres.tables import metadata as db_meta

    production = importlib.import_module("umd.jobs.production")
    ensure_source(umd_db)

    _se = db_meta.tables["semantic_event"]
    _cs = db_meta.tables["current_state"]
    _em = db_meta.tables["entity_mention"]

    ledger = SemanticLedger(umd_db)
    runtime = production.ProductionRuntime(
        engine=umd_db,
        commands=SemanticCommandService(ledger),
        ledger=ledger,
    )
    composer = production._Composer(umd_db, runtime)  # noqa: SLF001
    src = composer._require_source(make_manifest("ENTITY_RESOLUTION"))  # noqa: SLF001
    sid = src["id"]

    # Realistic cast: 3 characters x repeated chapters + an alias each + one
    # genuinely ambiguous alias. Co-occurrence + entity_type + alias normalized
    # forms let the deterministic service cluster aliases onto their character
    # (the amendment's segment-context/co-occurrence/type inputs).
    _c = {"entity_type": "character", "confidence": 0.6}
    mentions = [
        ("Alice", "chapter/1/paragraph/2", {**_c, "co_occurring": ["Robert"]}),
        ("Alice", "chapter/2/paragraph/1", {**_c, "co_occurring": ["Robert"]}),
        (
            "Al",
            "chapter/1/paragraph/1",
            {**_c, "co_occurring": ["Robert"], "normalized_forms": ["alice"]},
        ),
        ("Robert", "chapter/1/paragraph/3", {**_c, "co_occurring": ["Alice"]}),
        ("Robert", "chapter/2/paragraph/2", {**_c, "co_occurring": ["Alice"]}),
        (
            "Bob",
            "chapter/1/paragraph/5",
            {**_c, "co_occurring": ["Alice"], "normalized_forms": ["robert"]},
        ),
        ("Carol", "chapter/1/paragraph/4", {**_c, "co_occurring": ["Dan"]}),
        ("Carol", "chapter/2/paragraph/3", {**_c, "co_occurring": ["Dan"]}),
        (
            "Caro",
            "chapter/1/paragraph/6",
            {**_c, "co_occurring": ["Dan"], "normalized_forms": ["carol"]},
        ),
        ("Astra", "chapter/1/paragraph/7", {**_c, "confidence_state": "AMBIGUOUS"}),
    ]
    records = [
        Evidence(
            source_id=sid,
            evidence_kind=EvidenceKind.TEXT_SPAN,
            locator=locator,
            extraction_stage="STRUCTURAL_ANALYSIS",
            tool_versions={"analyzer": "umd-text-structural@2"},
            config_digest="umd-entity-resolution@1",
            confidence=0.6,
            quality={"candidate_kind": "entity", "mention_text": text, **quality},
        )
        for text, locator, quality in mentions
    ]
    composer._evidence.record(EvidenceBatch(records=records))  # noqa: SLF001
    read_back = composer._evidence.get_by_source(sid)  # noqa: SLF001
    assert sum(1 for e in read_back if (e.quality or {}).get("candidate_kind") == "entity") == 10

    # The REAL command path runs end-to-end (no stub) over live Postgres.
    outcome = composer._entity_resolution(make_manifest("ENTITY_RESOLUTION"))  # noqa: SLF001

    # More than one distinct canonical entity, no collapse.
    canonical_refs = sorted(r for r in outcome.artifact_refs if r.startswith("entity:canonical:"))
    assert len(canonical_refs) == 3, canonical_refs
    assert len(set(canonical_refs)) == 3
    assert f"resolved_entities:{sid}" in outcome.artifact_refs
    assert outcome.artifact_refs == outcome.evidence_refs
    # The old source-level placeholder (exact source id, no digest suffix) is
    # never emitted anywhere in the stage output.
    old_placeholder = f"entity:canonical:{sid}"
    assert old_placeholder not in outcome.artifact_refs
    assert all(ref != old_placeholder for ref in canonical_refs)

    # The mention/alias events were committed by the command path.
    with umd_db.connect() as conn:
        mention_ev = int(
            conn.execute(
                sa.select(sa.func.count())
                .select_from(_se)
                .where(_se.c.event_type == "EntityMentioned")
            ).scalar()
        )
        alias_ev = int(
            conn.execute(
                sa.select(sa.func.count())
                .select_from(_se)
                .where(_se.c.event_type == "EntityResolved")
            ).scalar()
        )
        # 9 resolved members get MENTION events; explicit ALIAS commands are
        # emitted for every alias mention that is not the cluster's primary
        # member (>= 2 of our 3 aliases), all resolved to a canonical.
        assert mention_ev == 9, f"expected 9 EntityMentioned, got {mention_ev}"
        assert alias_ev >= 2, f"expected >=2 EntityResolved(ALIAS), got {alias_ev}"

        # Option B: text-resolution mention rows keep entity_id NULL.
        # (9 resolved + 1 unresolved reviewable = 10 rows; all NULL).
        fk_rows = conn.execute(sa.select(_em.c.entity_id).where(_em.c.source_id == sid)).fetchall()
        assert len(fk_rows) == 10
        assert all(r.entity_id is None for r in fk_rows), (
            "text-resolution mention FK must stay NULL (no string into SAUuid bind)"
        )

        # Each resolved mention's EntityMentioned event carries the resolved
        # STRING canonical ref + generated_by provenance. Group alias surfaces
        # onto their canonical cluster to prove aliases resolve (no collapse).
        mention_rows = conn.execute(
            sa.select(_se.c.payload, _se.c.generated_by).where(
                _se.c.event_type == "EntityMentioned"
            )
        ).fetchall()
        clusters: dict[str, set[str]] = {}
        for payload, gb in mention_rows:
            p = payload or {}
            ref = str(p.get("entity_id", ""))
            assert ref.startswith("entity:canonical:"), f"string canonical ref required: {ref}"
            assert (gb or {}).get("config_digest") == "umd-entity-resolution@1"
            clusters.setdefault(ref, set()).add(str(p.get("mention_text", "")))
        assert len(clusters) == 3, f"characters collapsed into {len(clusters)} canonicals"
        # Alice's cluster contains the "Al" alias, Robert's "Bob", Carol's "Caro"
        # — each alias lands in its own character's cluster (never cross-mapped).
        surfaces = {frozenset(v) for v in clusters.values()}
        assert any({"Alice", "Al"} <= s for s in surfaces)
        assert any({"Robert", "Bob"} <= s for s in surfaces)
        assert any({"Carol", "Caro"} <= s for s in surfaces)

        # Canonical decisions exposed through the reducer-backed current_state:
        # one CANONICAL_ENTITY row per resolved alias mention id.
        cs_rows = conn.execute(
            sa.select(_cs.c.entity_ref, _cs.c.object_ref).where(
                _cs.c.predicate == "CANONICAL_ENTITY"
            )
        ).fetchall()
        assert len(cs_rows) == alias_ev
        assert all(str(r.object_ref) in clusters for r in cs_rows)

    # Query seam: unresolved_aliases excludes resolved mentions, retains Astra.
    page = QueryService(umd_db).structured(
        StructuredQuery(kind="UNRESOLVED_ALIASES", filters={"source_id": sid})
    )
    texts = [h.value for h in page.results]
    assert texts == ["Astra"], f"expected only the ambiguous alias unresolved, got {texts}"

    # Search seam: replay keeps canonical/alias docs discoverable and never
    # labels the unresolved mention canonical.
    store = ProjectionCheckpointStore(umd_db)
    ReplayDriver(umd_db, store).run(SearchProjectionBuilder(), wipe=True)
    from umd.projections.tables import search_document_in

    sd = search_document_in("public")
    with umd_db.connect() as conn:
        kinds = {str(k) for k in conn.execute(sa.select(sd.c.kind).distinct()).scalars()}
        canon_refs = {
            str(r)
            for r in conn.execute(
                sa.select(sd.c.ref).where(sd.c.kind == "CANONICAL_ENTITY")
            ).scalars()
        }
        astra_row = conn.execute(
            sa.select(sd.c.id).where((sd.c.kind == "SOURCE_EVIDENCE") & (sd.c.text == "Astra"))
        ).first()
        canon_astra = conn.execute(
            sa.select(sd.c.id).where((sd.c.kind == "CANONICAL_ENTITY") & (sd.c.text == "Astra"))
        ).first()
    assert "CANONICAL_ENTITY" in kinds
    assert canon_refs, "search projection must index canonical docs from current_state"
    # The unresolved mention must never be labeled canonical (its reviewable
    # surface is the UNRESOLVED_ALIASES query seam, not the search index).
    assert canon_astra is None, "the unresolved mention must not appear as a canonical doc"
    assert astra_row is None, (
        "unresolved mentions are surfaced via the query seam, not canonical search"
    )


# ---------------------------------------------------------------------------
# P3-S1: real StageWorkRegistryFactory-built registry over the book fixture
# ("The Lantern Keeper") through the nine-stage universe — durable evidence,
# semantic events, replay projections, idempotent repeat with deterministic
# identity material.
# ---------------------------------------------------------------------------


def _commit_book_source(umd_db: sa.Engine, source_store: Any, fmt: str = "txt") -> tuple[str, str]:
    import io
    import uuid

    from fixtures import BOOK_TITLE, semantic_book_bytes
    from umd.storage.ocfl import SourceDescriptor
    from umd.storage.postgres.repositories import SourceMembershipService

    memberships = SourceMembershipService(umd_db)
    work_id = uuid.uuid4().hex
    memberships.ensure_work(work_id=work_id, title=BOOK_TITLE, work_type="book")
    man = source_store.put_immutable(
        io.BytesIO(semantic_book_bytes(fmt)),
        SourceDescriptor(logical_name=f"lantern.{fmt}"),
    )
    sid = uuid.uuid4().hex
    memberships.ensure_source(
        source_id=sid,
        ocfl_ref=man.object_id,
        sha512=man.sha512,
        size_bytes=man.size_bytes,
        media_kind="text",
        original_name=f"lantern.{fmt}",
        work_id=work_id,
    )
    return sid, work_id


def _evidence_identity(engine: sa.Engine, source_id: str) -> list[tuple[str, str, str]]:
    with engine.connect() as c:
        rows = c.execute(
            sa.text(
                "SELECT evidence_kind, locator, config_digest FROM evidence "
                "WHERE source_id=:s ORDER BY locator, evidence_kind"
            ),
            {"s": source_id},
        ).fetchall()
    return [(str(r[0]), str(r[1]), str(r[2])) for r in rows]


def _stage_run_counts(engine: sa.Engine, job_id: str) -> dict[str, int]:
    with engine.connect() as c:
        rows = c.execute(
            sa.text(
                "SELECT stage_name, count(*) AS n FROM stage_run "
                "WHERE job_id=:j GROUP BY stage_name"
            ),
            {"j": job_id},
        ).fetchall()
    return {str(r[0]): int(r[1]) for r in rows}


def test_book_fixture_full_dag_durable_evidence_idempotent_and_deterministic(
    umd_db: sa.Engine, source_store: Any
) -> None:
    """Run the REAL StageWorkRegistryFactory-built registry over 'The Lantern
    Keeper' book fixture through all nine stages, then REPEAT the run to prove
    idempotency (stage_run claim dedup) and deterministic output identity."""
    from fixtures import BOOK_EVIDENCE_CONFIG_DIGEST
    from umd.api.app import build_context
    from umd.config import AuthSettings, ConsistencySettings, RateLimitSettings, Settings

    settings = Settings(
        auth=AuthSettings(api_keys=["write-key", "read-key"], write_keys=["write-key"]),
        rate_limit=RateLimitSettings(
            enabled=False, requests_per_window=0, window_seconds=60.0, burst=0
        ),
        consistency=ConsistencySettings(lag_wait_multiplier=1, max_waiters=16),
        lag_budget_seconds=0.05,
    )
    # build_context wires the SAME runtime object into the stage registry that the
    # HTTP API uses (settings, source_store, segmenters, providers, builders), so
    # the registry here is the real production registry, not a bare fake.
    ctx = build_context(
        settings=settings, engine=umd_db, source_store=source_store, runner="hermetic"
    )
    registry = ctx.extra["work_registry"]
    assert set(registry) == set(STAGE_ORDER)  # nine-stage universe fully composed

    sid, _work_id = _commit_book_source(umd_db, source_store, "txt")
    ctx.jobs.submit(
        job_id="book-run", source_id=sid, dag_universe="v1-dag:base", work_registry=registry
    )
    assert ctx.jobs.status("book-run") == "complete"

    # --- durable evidence: every row carries a config_digest; structural analysis
    #     evidence uses the fixture's dispatch config digest as its leading part.
    with umd_db.connect() as c:
        null_digests = c.execute(
            sa.text("SELECT count(*) FROM evidence WHERE config_digest IS NULL")
        ).scalar()
    assert null_digests == 0
    identity = _evidence_identity(umd_db, sid)
    assert identity, "book run produced no durable evidence"
    assert any(d.startswith(BOOK_EVIDENCE_CONFIG_DIGEST) for _, _, d in identity), (
        "dispatch-derived structural evidence must carry the fixture's dispatch config digest"
    )

    # --- semantic events: all nine StageCompleted + reconciliation assertions.
    with umd_db.connect() as c:
        completed = c.execute(
            sa.text("SELECT count(*) FROM semantic_event WHERE event_type='StageCompleted'")
        ).scalar()
        asserted = c.execute(
            sa.text("SELECT count(*) FROM semantic_event WHERE event_type='SemanticAsserted'")
        ).scalar()
    assert completed >= 9
    assert asserted >= 1

    # --- segments persisted for the book.
    with umd_db.connect() as c:
        nseg = c.execute(
            sa.text("SELECT count(*) FROM segment WHERE source_id=:s"), {"s": sid}
        ).scalar()
    assert nseg >= 1

    # --- replay projections consistent: scenes + relationship edges readable.
    from umd.projections.base import ReplayDriver
    from umd.projections.checkpoint import ProjectionCheckpointStore
    from umd.projections.current import CurrentTierOneBuilder
    from umd.projections.edges import ActiveSemanticEdgeProjectionBuilder
    from umd.projections.query import QueryService

    pstore = ProjectionCheckpointStore(umd_db)
    ReplayDriver(umd_db, pstore).run(CurrentTierOneBuilder(), wipe=True)
    ReplayDriver(umd_db, pstore).run(ActiveSemanticEdgeProjectionBuilder(), wipe=True)
    query = QueryService(umd_db)
    scenes = query.structured({"kind": "SCENE", "filters": {"source_id": sid}, "limit": 20})
    assert scenes.total >= 3  # 2 chapters + >=2 sections for txt
    edges = query.structured({"kind": "RELATIONSHIP_EDGES", "limit": 100})
    assert edges.total >= 1

    # --- idempotent repeat: resubmitting the same job schedules nothing new and
    #     produces byte-identical evidence identity material (deduped, never
    #     churned; determinism keys on (source_id, locator, evidence_kind,
    #     config_digest), NOT random evidence UUIDs).
    counts_before = _stage_run_counts(umd_db, "book-run")
    ctx.jobs.submit(
        job_id="book-run", source_id=sid, dag_universe="v1-dag:base", work_registry=registry
    )
    assert ctx.jobs.status("book-run") == "complete"
    counts_after = _stage_run_counts(umd_db, "book-run")
    assert counts_after == counts_before
    assert set(counts_after) == set(STAGE_ORDER) and all(n == 1 for n in counts_after.values())
    assert _evidence_identity(umd_db, sid) == identity


# ---------------------------------------------------------------------------
# P3-S1: provider-enabled full nine-stage DAG — provider observations promote
# through the UNCHANGED canonical registry via the command/ledger path (never
# written directly to the edge/search projections).
# ---------------------------------------------------------------------------


def test_book_fixture_full_dag_provider_promotion_via_ledger_not_projections(
    umd_db: sa.Engine, source_store: Any
) -> None:
    """Register a model provider into the real production runtime and run the full
    nine-stage DAG. The provider-derived aliases / traits / scene boundaries /
    presence / utterances+speakers / supported relationships must be committed
    through ``commands.assert_semantic`` (append-only ledger + semantic_assertion
    mirror) and must NOT be written directly to the edge/search projections (those
    require the sanctioned replay builders)."""
    from test_reconciliation_provider_promotion import _LanternProvider
    from umd.api.app import build_context
    from umd.config import AuthSettings, ConsistencySettings, RateLimitSettings, Settings

    settings = Settings(
        auth=AuthSettings(api_keys=["write-key", "read-key"], write_keys=["write-key"]),
        rate_limit=RateLimitSettings(
            enabled=False, requests_per_window=0, window_seconds=60.0, burst=0
        ),
        consistency=ConsistencySettings(lag_wait_multiplier=1, max_waiters=16),
        lag_budget_seconds=0.05,
    )
    ctx = build_context(
        settings=settings, engine=umd_db, source_store=source_store, runner="hermetic"
    )
    registry = ctx.extra["work_registry"]
    # Canonical nine-stage DAG is UNCHANGED by the provider.
    assert set(registry) == set(STAGE_ORDER)

    # Register the provider into the SAME runtime the stage registry uses.
    composer = registry["STRUCTURAL_ANALYSIS"].__self__
    provider = _LanternProvider()
    composer._runtime.providers.register(provider)
    ctx.settings.semantic.provider = provider.name
    ctx.settings.semantic.model = "lantern-qwen"

    sid, _work_id = _commit_book_source(umd_db, source_store, "txt")
    ctx.jobs.submit(
        job_id="book-prov", source_id=sid, dag_universe="v1-dag:base", work_registry=registry
    )
    assert ctx.jobs.status("book-prov") == "complete"

    # Provider invoked exactly once via the REAL structural-analysis invocation.
    assert len(provider.calls) == 1, "provider must be invoked exactly once by structural analysis"

    # --- committed through the command/ledger path (assert_semantic) ---------
    with umd_db.connect() as c:
        rows = c.execute(
            sa.text(
                "SELECT predicate_code AS p, subject_ref AS s, object_ref AS o "
                "FROM semantic_assertion"
            )
        ).fetchall()
        prov_events = c.execute(
            sa.text(
                "SELECT count(*) FROM semantic_event WHERE event_type='SemanticAsserted' "
                "AND payload->'generated_by'->>'provider'='lantern_semantic'"
            )
        ).scalar()
    by_obj: dict[str, set[str]] = {}
    by_subj: dict[str, set[str]] = {}
    for r in rows:
        pred, subj, obj = str(r[0]), str(r[1]), str(r[2])
        by_obj.setdefault(pred, set()).add(obj)
        by_subj.setdefault(pred, set()).add(subj)

    # Provider aliases -> KNOWN_AS; traits -> HAS_TRAIT; scene -> STARTS_AT;
    # presence -> PRESENT_IN; utterance+speaker -> SPEAKS/UTTERED_IN;
    # supported relationship -> CO_OCCURS.
    assert "the apprentice" in by_obj.get("KNOWN_AS", set())
    assert "the cartographer" in by_obj.get("KNOWN_AS", set())
    assert "the warden" in by_obj.get("KNOWN_AS", set())
    assert "moss-green eyes" in by_obj.get("HAS_TRAIT", set())
    assert "grey beard" in by_obj.get("HAS_TRAIT", set())
    assert "scene:lantern-1" in by_subj.get("STARTS_AT", set())
    assert "PRESENT_IN" in by_obj
    assert "SPEAKS" in by_obj and "UTTERED_IN" in by_obj
    assert "CO_OCCURS" in by_obj
    # Plan S Phase 4 (P4-S1): SIBLING_OF is now a registered controlled-vocabulary
    # relationship, so the provider's Mara->Ellis sibling observation is promoted
    # through the ledger (it is no longer an unsupported evidence-only predicate).
    assert "SIBLING_OF" in by_obj

    # Ledger carries the provider provenance on the appended SemanticAsserted events.
    assert prov_events and int(prov_events) > 0, "provider assertions missing from the ledger"

    # --- NOT written directly to projections ---------------------------------
    # After the full DAG only the sanctioned CURRENT_SEARCH_PROJECTION replay built
    # current_state; the edge/search projections are NOT part of the DAG and must be
    # empty (they need explicit replay builders). Reconciliation only appended to the
    # ledger — it never wrote active_semantic_edge / search_document directly.
    with umd_db.connect() as c:
        edges = c.execute(sa.text("SELECT count(*) FROM active_semantic_edge")).scalar()
        sdocs = c.execute(sa.text("SELECT count(*) FROM search_document")).scalar()
        cs = c.execute(sa.text("SELECT count(*) FROM current_state")).scalar()
    assert int(edges) == 0, "reconciliation must not write the edge projection directly"
    assert int(sdocs) == 0, "reconciliation must not write the search projection directly"
    assert int(cs) > 0, "current_state should be built by the sanctioned replay stage"
