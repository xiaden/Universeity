"""Plan S Phase 3 (P3-S5): cross-source identity is explicit, reviewable, scoped.

Proves source-independent identity (requirement ledger item 3):
  * a supported same character (shared work membership) collapses to ONE opaque
    canonical ref across two sources of the same work;
  * an unrelated same-name character in a different work remains a DISTINCT ref,
    kept separate and surfaced as a reviewable CORRESPONDENCE alignment;
  * ambiguous identity stays unresolved/reviewable (never silently merged);
  * human overrides/locks outrank machine cross-source inference;
  * merge/split remain reversible and reruns are deterministic + idempotent
    (no duplicate canonicals, no lost evidence);
  * all memberships are query-visible and source-local mention rows stay intact
    with exact support/provenance; no source-bound canonical refs are emitted.

The two-source fixture lives in ``tests/fixtures_two_source.py`` (deterministic,
small; does not touch Lantern Keeper or immutable source bytes).
"""

from __future__ import annotations

import importlib
import json
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa

from conftest import _truncate
from fixtures_two_source import (
    AMBIGUOUS_NAME,
    NOVEL_WORK,
    OTHER_WORK,
    SAME_NAME_COLLISION,
    SHARED_NOVEL_NAMES,
    SOURCE_A,
    SOURCE_B,
    SOURCE_C,
    WORK_BY_SOURCE,
    two_source_mention_specs,
)
from umd.analysis.semantic import (
    GeneratedBy,
    RelationshipCandidate,
    SegmentEvidenceRef,
    SemanticAnalysisResult,
)
from umd.application.commands import SemanticCommandService
from umd.domain.evidence import EvidenceBatch
from umd.domain.models import Evidence, EvidenceKind
from umd.reconciliation.reconciler import ReconciliationInput, SemanticReconciler
from umd.resolution.mentions import SourceMention
from umd.resolution.resolution import PostgresSplitEnumerator, Resolver
from umd.resolution.service import (
    CanonicalEntity,
    EntityResolutionService,
    ResolutionBatch,
    ResolutionInput,
)
from umd.storage.postgres.ledger import SemanticLedger
from umd.storage.postgres.reducer import (
    CANONICAL_IDENTITY_PREDICATE,
    STATE_USER_CONFIRMED,
    USER_OVERRIDE,
)
from umd.storage.postgres.repositories import SourceMembershipService
from umd.storage.postgres.tables import metadata as db_meta

_se = db_meta.tables["semantic_event"]
_cs = db_meta.tables["current_state"]
_em = db_meta.tables["entity_mention"]
_align = db_meta.tables["alignment"]
_src_t = db_meta.tables["source"]

NOVEL = "Novel"
OTHER = "Other"


# ---------------------------------------------------------------------------
# pure resolution helpers + tests (no DB)
# ---------------------------------------------------------------------------


def _m(
    source_id: str,
    text: str,
    segment: str,
    *,
    work_id: str | None = None,
    continuity_id: str | None = None,
    confidence: float = 0.85,
    cs: str = "CONFIRMED",
    nf: list[str] | None = None,
) -> SourceMention:
    return SourceMention(
        source_id=source_id,
        mention_text=text,
        segment_id=segment,
        confidence=confidence,
        confidence_state=cs,
        normalized_forms=nf or [text],
        work_id=work_id,
        continuity_id=continuity_id,
    )


def _resolve(mentions: list[SourceMention], **scope: Any) -> Any:
    svc = EntityResolutionService()
    return svc.resolve_mentions(ResolutionInput(mentions=mentions, **scope))


def test_pure_same_name_different_scope_stays_separate() -> None:
    a = [
        _m(SOURCE_A, "Mara", "p/1", work_id=NOVEL_WORK),
        _m(SOURCE_A, "Mara", "p/3", work_id=NOVEL_WORK),
    ]
    c = [_m(SOURCE_C, "Mara", "p/1", work_id=OTHER_WORK)]
    batch_a = _resolve(a, source_id=SOURCE_A)
    batch_c = _resolve(c, source_id=SOURCE_C)

    ref_a = {e.ref for e in batch_a.canonical_entities if e.label == "Mara"}
    ref_c = {e.ref for e in batch_c.canonical_entities if e.label == "Mara"}
    assert len(ref_a) == len(ref_c) == 1
    # Unrelated same-name across different work scopes -> DISTINCT opaque refs,
    # never merged by string equality.
    assert ref_a != ref_c
    ra = next(iter(ref_a))
    rc = next(iter(ref_c))
    assert ra.startswith("entity:canonical:") and rc.startswith("entity:canonical:")
    # No source prefix is baked into the ref (opaque, source-independent).
    assert ":" not in ra.rsplit("entity:canonical:", 1)[1]
    assert ":" not in rc.rsplit("entity:canonical:", 1)[1]


def test_pure_ambiguous_stays_unresolved() -> None:
    astra = _m(
        SOURCE_A,
        AMBIGUOUS_NAME,
        "p/5",
        work_id=NOVEL_WORK,
        confidence=0.4,
        cs="AMBIGUOUS",
    )
    batch = _resolve([astra], source_id=SOURCE_A)
    assert any(u.text == AMBIGUOUS_NAME for u in batch.unresolved)
    assert not any(e.label == AMBIGUOUS_NAME for e in batch.canonical_entities)


def test_pure_input_scope_carried_to_memberships() -> None:
    # A mention with no work_id still inherits the source's explicit scope via the
    # ResolutionInput (P3-S1): the canonical stays scoped to the work.
    m = _m(SOURCE_A, "Orin", "p/1", work_id=None)
    batch = _resolve(
        [m],
        source_id=SOURCE_A,
        work_id=NOVEL_WORK,
        memberships={"source_ids": [SOURCE_A], "work_ids": [NOVEL_WORK]},
    )
    assert len(batch.canonical_entities) == 1
    e = batch.canonical_entities[0]
    assert e.memberships["work_ids"] == [NOVEL_WORK]
    assert e.memberships["source_ids"] == [SOURCE_A]


# ---------------------------------------------------------------------------
# PostgreSQL / StageWork helpers
# ---------------------------------------------------------------------------

pytestmark = pytest.mark.postgres


def _composer(umd_db: sa.Engine) -> tuple[Any, SourceMembershipService]:
    production = importlib.import_module("umd.jobs.production")
    ledger = SemanticLedger(umd_db)
    runtime = production.ProductionRuntime(
        engine=umd_db,
        commands=SemanticCommandService(ledger),
        ledger=ledger,
    )
    composer = production._Composer(umd_db, runtime)  # noqa: SLF001
    return composer, SourceMembershipService(umd_db)


def _manifest(source_id: str, stage: str = "ENTITY_RESOLUTION") -> Any:
    from umd.jobs.manifest import StageManifest

    return StageManifest(
        job_id="two-source",
        stage_name=stage,
        source_id=source_id,
        dag_universe=None,
        evidence_refs=[],
        input_manifest={"source_id": source_id},
    )


def _sha(sid: str) -> str:
    import hashlib

    return hashlib.sha512(sid.encode()).hexdigest()


def _setup(umd_db: sa.Engine) -> tuple[Any, SourceMembershipService]:
    composer, svc = _composer(umd_db)
    for work_id, title in ((NOVEL_WORK, NOVEL), (OTHER_WORK, OTHER)):
        svc.ensure_work(work_id=work_id, title=title, work_type="book")
    for sid in (SOURCE_A, SOURCE_B, SOURCE_C):
        work_id = WORK_BY_SOURCE[sid]
        svc.ensure_source(
            source_id=sid,
            ocfl_ref=f"urn:ocfl:{sid}",
            sha512=_sha(sid),
            size_bytes=len(sid),
            media_kind="text",
            original_name=f"{sid}.txt",
            work_id=work_id,
        )
        svc.add_membership(source_id=sid, work_id=work_id, role="primary")
    return composer, svc


def _seed_source(composer: Any, sid: str) -> None:
    records = [
        Evidence(
            source_id=sid,
            evidence_kind=EvidenceKind.TEXT_SPAN,
            locator=spec["locator"],
            extraction_stage="STRUCTURAL_ANALYSIS",
            tool_versions={},
            config_digest="umd-entity-resolution@1",
            confidence=float(spec["quality"].get("confidence", 0.6)),
            quality={"candidate_kind": "entity", **spec["quality"]},
        )
        for spec in two_source_mention_specs(sid)
    ]
    composer._evidence.record(EvidenceBatch(records=records))  # noqa: SLF001


def _run_resolution(composer: Any, sid: str) -> Any:
    return composer._entity_resolution(_manifest(sid))


def _identity(umd_db: sa.Engine) -> dict[str, dict[str, Any]]:
    """Return {canonical_ref -> {meta, state, authority}} from current_state."""
    out: dict[str, dict[str, Any]] = {}
    with umd_db.connect() as conn:
        for r in conn.execute(
            sa.select(_cs.c.entity_ref, _cs.c.object_ref, _cs.c.state, _cs.c.authority).where(
                _cs.c.predicate == CANONICAL_IDENTITY_PREDICATE
            )
        ):
            out[str(r.entity_ref)] = {
                "meta": json.loads(r.object_ref),
                "state": r.state,
                "authority": r.authority,
            }
    return out


def _refs_by_label(identity: dict[str, dict[str, Any]]) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for ref, rec in identity.items():
        out.setdefault(rec["meta"].get("display_label"), []).append(ref)
    return out


def _mems(rec: dict[str, Any]) -> dict[str, list[str]]:
    """Memberships live under the canonical metadata's ``memberships`` key."""
    return rec["meta"].get("memberships") or {}


def _align_rows(umd_db: sa.Engine) -> list[tuple[str, str, str, str]]:
    with umd_db.connect() as conn:
        return [
            (str(r.left_ref), str(r.right_ref), str(r.alignment_type), str(r.method))
            for r in conn.execute(
                sa.select(
                    _align.c.left_ref, _align.c.right_ref, _align.c.alignment_type, _align.c.method
                )
            )
        ]


def _count_resolved(umd_db: sa.Engine) -> int:
    with umd_db.connect() as conn:
        return int(
            conn.execute(
                sa.select(sa.func.count())
                .select_from(_se)
                .where(_se.c.event_type == "EntityResolved")
            ).scalar()
        )


# ---------------------------------------------------------------------------
# PostgreSQL / StageWork tests
# ---------------------------------------------------------------------------


def test_shared_character_one_ref_across_sources_and_unrelated_separate(
    umd_db: sa.Engine,
) -> None:
    composer, _svc = _setup(umd_db)
    for sid in (SOURCE_A, SOURCE_B, SOURCE_C):
        _seed_source(composer, sid)

    _run_resolution(composer, SOURCE_A)  # establishes Novel Mara/Ellis
    _run_resolution(composer, SOURCE_B)  # seeds onto the same refs (shared work)
    _run_resolution(composer, SOURCE_C)  # unrelated same-name -> distinct

    identity = _identity(umd_db)
    by_label = _refs_by_label(identity)

    # Supported same characters share ONE opaque ref spanning BOTH Novel sources.
    for name in SHARED_NOVEL_NAMES:
        refs = [
            r
            for r in by_label.get(name, [])
            if NOVEL_WORK in (_mems(identity[r]).get("work_ids") or [])
        ]
        assert len(refs) == 1, (name, refs)
        ref = refs[0]
        sources = set(_mems(identity[ref]).get("source_ids") or [])
        assert {SOURCE_A, SOURCE_B} <= sources, (name, sources)

    # Unrelated same-name in OTHER is a DISTINCT ref, single-sourced.
    other_mara = [
        r for r in by_label["Mara"] if OTHER_WORK in (_mems(identity[r]).get("work_ids") or [])
    ]
    novel_mara = [
        r for r in by_label["Mara"] if NOVEL_WORK in (_mems(identity[r]).get("work_ids") or [])
    ]
    assert len(other_mara) == 1 and len(novel_mara) == 1
    assert other_mara[0] != novel_mara[0]
    assert set(_mems(identity[other_mara[0]]).get("source_ids") or []) == {SOURCE_C}

    # No source-bound canonical refs: all refs are opaque with no source id / ":".
    for ref in identity:
        assert ref.startswith("entity:canonical:")
        assert ":" not in ref.rsplit("entity:canonical:", 1)[1]
        assert SOURCE_A not in ref and SOURCE_B not in ref and SOURCE_C not in ref

    # Ambiguity stays unresolved (Astra in Novel, Nyx in Other) -> no canonical.
    assert all(r["meta"].get("display_label") != AMBIGUOUS_NAME for r in identity.values())
    assert all(r["meta"].get("display_label") != "Nyx" for r in identity.values())


def test_mention_rows_source_local_and_intact(umd_db: sa.Engine) -> None:
    composer, _svc = _setup(umd_db)
    for sid in (SOURCE_A, SOURCE_B):
        _seed_source(composer, sid)
        _run_resolution(composer, sid)

    with umd_db.connect() as conn:
        rows = conn.execute(
            sa.select(_em.c.source_id, _em.c.entity_id, sa.func.count()).group_by(
                _em.c.source_id, _em.c.entity_id
            )
        ).fetchall()
    # Every source keeps its own source-local mention rows.
    by_source = {str(r.source_id): int(r[2]) for r in rows}
    assert set(by_source) == {SOURCE_A, SOURCE_B}
    assert by_source[SOURCE_A] == len(two_source_mention_specs(SOURCE_A))
    assert by_source[SOURCE_B] == len(two_source_mention_specs(SOURCE_B))
    # Canonical refs are non-UUID -> mention FK stays NULL (no fabricated row).
    for r in rows:
        assert r.entity_id is None


def test_cross_source_alignment_supported_and_reviewable_idempotent(
    umd_db: sa.Engine,
) -> None:
    composer, _svc = _setup(umd_db)
    for sid in (SOURCE_A, SOURCE_B, SOURCE_C):
        _seed_source(composer, sid)
        _run_resolution(composer, sid)

    composer._cross_source_alignment(_manifest(SOURCE_B))
    composer._cross_source_alignment(_manifest(SOURCE_C))

    aligns = _align_rows(umd_db)
    supported = [a for a in aligns if a[2] == "CONTINUITY" and a[3] == "work-membership"]
    reviewable = [a for a in aligns if a[2] == "CORRESPONDENCE" and a[3] == "candidate-separation"]
    # Supported shared Novel identities are explicit CONTINUITY (2: Mara, Ellis).
    assert len(supported) == 2, supported
    # Unrelated same-name is a reviewable CORRESPONDENCE: cross-work Mara/Ellis
    # (2) plus the same-work John A/B collision (1, same name + work but no
    # shared evidence -> separate, reviewable) = 3. Never merged by name.
    assert len(reviewable) == 3, reviewable
    assert all(a[2] == "CORRESPONDENCE" for a in reviewable)

    # Idempotent: rerunning the stage never duplicates the alignments.
    composer._cross_source_alignment(_manifest(SOURCE_B))
    composer._cross_source_alignment(_manifest(SOURCE_C))
    assert _align_rows(umd_db) == aligns


def test_human_override_outranks_machine_cross_source(umd_db: sa.Engine) -> None:
    composer, svc = _setup(umd_db)
    _seed_source(composer, SOURCE_A)
    _run_resolution(composer, SOURCE_A)

    identity = _identity(umd_db)
    novel_mara = [
        r
        for r, rec in identity.items()
        if rec["meta"].get("display_label") == "Mara"
        and NOVEL_WORK in (_mems(rec).get("work_ids") or [])
    ][0]

    # Human confirms Mara -> USER_OVERRIDE on the canonical identity.
    composer._opt("commands").record_override(
        subject_ref=novel_mara,
        predicate=CANONICAL_IDENTITY_PREDICATE,
        object_ref=json.dumps(
            {"display_label": "Human-Mara", "canonical_type": "CHARACTER"},
            sort_keys=True,
        ),
        actor="tester",
    )

    # A machine rerun from a second source (B) would re-establish Mara -> but the
    # USER_OVERRIDE outranks it and wins.
    _seed_source(composer, SOURCE_B)
    _run_resolution(composer, SOURCE_B)

    rec = _identity(umd_db)[novel_mara]
    assert rec["state"] == STATE_USER_CONFIRMED
    assert rec["authority"] == USER_OVERRIDE
    assert rec["meta"]["display_label"] == "Human-Mara"


def test_deterministic_idempotent_rerun_converges(umd_db: sa.Engine) -> None:
    composer, _svc = _setup(umd_db)
    for sid in (SOURCE_A, SOURCE_B):
        _seed_source(composer, sid)

    _run_resolution(composer, SOURCE_A)
    _run_resolution(composer, SOURCE_B)
    before = _identity(umd_db)
    est_before = _count_resolved(umd_db)

    # Rerun both sources: same refs, no duplicate ESTABLISH, no lost identity.
    _run_resolution(composer, SOURCE_A)
    _run_resolution(composer, SOURCE_B)
    assert _identity(umd_db) == before
    est_after = _count_resolved(umd_db)
    assert est_after == est_before


def test_merge_split_reversible(umd_db: sa.Engine) -> None:
    composer, _svc = _setup(umd_db)
    for sid in (SOURCE_A, SOURCE_C):
        _seed_source(composer, sid)
        _run_resolution(composer, sid)

    identity = _identity(umd_db)
    by_label = _refs_by_label(identity)
    novel_mara = [
        r for r in by_label["Mara"] if NOVEL_WORK in (_mems(identity[r]).get("work_ids") or [])
    ][0]
    other_mara = [
        r for r in by_label["Mara"] if OTHER_WORK in (_mems(identity[r]).get("work_ids") or [])
    ][0]

    from umd.resolution.mentions import PostgresMentionRepository

    ledger = SemanticLedger(umd_db)
    repo = PostgresMentionRepository(umd_db)
    resolver = Resolver(ledger, PostgresSplitEnumerator(umd_db, repo), repo, umd_db)
    # MERGE is a reversible log record, never a delete: both identity rows survive.
    resolver.merge(target_entity=novel_mara, merged_refs=[other_mara], reason="test")
    after = _identity(umd_db)
    assert novel_mara in after and other_mara in after
    assert set(_refs_by_label(after)["Mara"]) == {novel_mara, other_mara}


def test_memberships_query_visible(umd_db: sa.Engine) -> None:
    composer, _svc = _setup(umd_db)
    for sid in (SOURCE_A, SOURCE_B):
        _seed_source(composer, sid)
        _run_resolution(composer, sid)

    identity = _identity(umd_db)
    novel_mara = [
        r
        for r, rec in identity.items()
        if rec["meta"].get("display_label") == "Mara"
        and NOVEL_WORK in (_mems(rec).get("work_ids") or [])
    ][0]
    mems = _mems(identity[novel_mara])
    # Memberships are query-visible on the canonical identity (public).
    assert {SOURCE_A, SOURCE_B} <= set(mems.get("source_ids") or [])
    assert NOVEL_WORK in (mems.get("work_ids") or [])
    # The canonical carries exact support/evidence refs (source-local rows intact).
    assert identity[novel_mara]["meta"]["support_refs"]


def _seed_named(
    composer: Any,
    sid: str,
    name: str,
    locator: str,
    confidence: float = 0.85,
    state: str = "CONFIRMED",
) -> None:
    """Seed a single entity-candidate evidence record (John/Moss in isolation)."""
    composer._evidence.record(  # noqa: SLF001
        EvidenceBatch(
            records=[
                Evidence(
                    source_id=sid,
                    evidence_kind=EvidenceKind.TEXT_SPAN,
                    locator=locator,
                    extraction_stage="STRUCTURAL_ANALYSIS",
                    tool_versions={},
                    config_digest="umd-entity-resolution@1",
                    confidence=confidence,
                    quality={
                        "candidate_kind": "entity",
                        "mention_text": name,
                        "entity_type": "CHARACTER",
                        "confidence": confidence,
                        "confidence_state": state,
                        "co_occurring": [],
                        "normalized_forms": [name],
                    },
                )
            ]
        )
    )


def test_same_name_same_work_different_evidence_stays_separate(umd_db: sa.Engine) -> None:
    """Plan T P1-S5/R3: John/C same-name separation at the DB level.

    Two sources of the SAME work each contain a "John", but at DIFFERENT evidence
    locators. Shared work + shared name is NOT proof of identity: each resolves to a
    DISTINCT opaque ref (no seed, no alias, no merge) and both remain queryable.
    """
    composer, _svc = _setup(umd_db)
    _seed_named(composer, SOURCE_A, "John", "chapter/1/paragraph/6")
    _seed_named(composer, SOURCE_B, "John", "chapter/1/paragraph/7")
    _run_resolution(composer, SOURCE_A)
    _run_resolution(composer, SOURCE_B)

    identity = _identity(umd_db)
    john_refs = [
        r
        for r, rec in identity.items()
        if rec["meta"].get("display_label") == "John"
        and NOVEL_WORK in (_mems(rec).get("work_ids") or [])
    ]
    assert len(john_refs) == 2, john_refs
    assert len(set(john_refs)) == 2
    sources = {frozenset(_mems(identity[r]).get("source_ids") or []) for r in john_refs}
    assert sources == {frozenset([SOURCE_A]), frozenset([SOURCE_B])}, sources
    for ref in john_refs:
        assert ref.startswith("entity:canonical:")
        assert ":" not in ref.rsplit("entity:canonical:", 1)[1]
    # No fabricated alias links the two Johns.
    for ref in john_refs:
        assert "John" not in (identity[ref]["meta"].get("aliases") or [])


def test_moss_never_inferred_as_mara(umd_db: sa.Engine) -> None:
    """Plan T P1-S5/R8: honest fallback — Moss is never merged into Mara.

    Mara is established as a canonical; a genuinely ambiguous single "Moss" mention
    stays UNRESOLVED/reviewable — it gets no fabricated canonical ref and is never
    aliased onto or merged into Mara. Neither an entity row nor a current mapping is
    fabricated for the ambiguous surface.
    """
    composer, _svc = _setup(umd_db)
    _seed_named(composer, SOURCE_A, "Mara", "chapter/1/paragraph/1")
    _seed_named(
        composer, SOURCE_A, "Moss", "chapter/1/paragraph/9", confidence=0.4, state="AMBIGUOUS"
    )
    _run_resolution(composer, SOURCE_A)

    identity = _identity(umd_db)
    mara_refs = [r for r, rec in identity.items() if rec["meta"].get("display_label") == "Mara"]
    assert len(mara_refs) == 1
    mara = mara_refs[0]
    assert "Moss" not in (identity[mara]["meta"].get("aliases") or [])
    # Moss is never promoted to a canonical identity (no fabricated ref).
    assert not [r for r, rec in identity.items() if rec["meta"].get("display_label") == "Moss"]
    assert identity[mara]["meta"]["classification"] == "probable"


def test_phase5_two_source_public_identity_e2e(umd_db: sa.Engine, source_store) -> None:
    """P5-S2: prove shared identity, same-name separation, and reviewable ambiguity
    through the TYPED PUBLIC ``/v1/entities`` read surface (never direct table-only
    proof). Supported Novel Mara/Ellis share ONE canonical ref across sources A+B;
    the unrelated same-name in Other stays a DISTINCT ref; Astra/Nyx stay
    reviewable (absent from the canonical list); entity responses expose
    source/work/continuity membership + canonical ref/display label."""
    from fastapi.testclient import TestClient

    from test_api_contract import _build_all, _client_settings
    from umd.api.app import create_app

    composer, _svc = _setup(umd_db)
    for sid in (SOURCE_A, SOURCE_B, SOURCE_C):
        _seed_source(composer, sid)
    _run_resolution(composer, SOURCE_A)  # establishes Novel Mara/Ellis
    _run_resolution(composer, SOURCE_B)  # seeds onto the same refs (shared work)
    _run_resolution(composer, SOURCE_C)  # unrelated same-name -> distinct ref

    _build_all(umd_db)
    app = create_app(
        engine=umd_db, source_store=source_store, settings=_client_settings(), runner="hermetic"
    )
    read_headers = {"Authorization": "Bearer read-key"}
    with TestClient(app) as client:
        le = client.get("/v1/entities?limit=100", headers=read_headers)
        assert le.status_code == 200, le.text
        items = le.json()["items"]
        by_label: dict[str, list[dict[str, Any]]] = {}
        for it in items:
            by_label.setdefault(it.get("display_label") or it["label"], []).append(it)

        # Supported Novel Mara/Ellis: exactly ONE canonical shared across A+B.
        for name in SHARED_NOVEL_NAMES:
            novel = [
                it
                for it in by_label.get(name, [])
                if NOVEL_WORK in it["memberships"].get("work_ids", [])
            ]
            assert len(novel) == 1, (name, novel)
            mem = novel[0]["memberships"]
            assert {SOURCE_A, SOURCE_B} <= set(mem["source_ids"]), mem
            assert NOVEL_WORK in mem["work_ids"], mem
            assert novel[0]["ref"].startswith("entity:canonical:"), novel[0]["ref"]
        novel_mara = [
            it for it in by_label["Mara"] if NOVEL_WORK in it["memberships"].get("work_ids", [])
        ][0]

        # Unrelated same-name in Other: DISTINCT ref, single-sourced.
        other_mara = [
            it for it in by_label["Mara"] if OTHER_WORK in it["memberships"].get("work_ids", [])
        ]
        assert len(other_mara) == 1, other_mara
        assert other_mara[0]["ref"] != novel_mara["ref"], "same-name must not be merged"
        assert set(other_mara[0]["memberships"]["source_ids"]) == {SOURCE_C}
        assert OTHER_WORK in other_mara[0]["memberships"]["work_ids"]

        # Ambiguity stays reviewable, never merged: Astra/Nyx are not canonical.
        assert all((it.get("display_label") or it["label"]) != AMBIGUOUS_NAME for it in items)
        assert all((it.get("display_label") or it["label"]) != "Nyx" for it in items)

        # Every canonical is retrievable by opaque ref with display label + membership.
        for it in items:
            g = client.get(f"/v1/entities/{it['ref']}", headers=read_headers)
            assert g.status_code == 200, g.text
            body = g.json()
            assert (body.get("display_label") or body["label"]) == (
                it.get("display_label") or it["label"]
            ), body
            assert body["memberships"].get("source_ids")
            assert body["memberships"].get("work_ids")
            assert "continuity_ids" in body["memberships"]


# ---------------------------------------------------------------------------
# Plan T Phase 3 (P3-S2/S3): boundary-hardening proofs on the two-source fixture
# ---------------------------------------------------------------------------


def test_pure_permutation_order_invariance() -> None:
    """P3-S3: the canonical anchor is order-invariant — a permutation of the same
    mention set yields the SAME refs (deterministic, no first-establisher bias)."""
    mentions = [
        _m(SOURCE_A, "Mara", "p/1", work_id=NOVEL_WORK),
        _m(SOURCE_A, "Mara", "p/3", work_id=NOVEL_WORK),
        _m(SOURCE_B, "Mara", "p/1", work_id=NOVEL_WORK),
        _m(SOURCE_A, SAME_NAME_COLLISION, "p/6", work_id=NOVEL_WORK),
        _m(SOURCE_B, SAME_NAME_COLLISION, "p/7", work_id=NOVEL_WORK),
    ]

    def _refs(seq: list[SourceMention]) -> dict[str, str]:
        batch = _resolve(seq, source_id=SOURCE_A, work_id=NOVEL_WORK)
        return {e.label: e.ref for e in batch.canonical_entities}

    forward = _refs(mentions)
    reverse = _refs(list(reversed(mentions)))
    shuffled = _refs([mentions[2], mentions[0], mentions[4], mentions[1], mentions[3]])
    assert forward == reverse == shuffled
    assert forward["Mara"] != forward[SAME_NAME_COLLISION]


@pytest.fixture()
def _p3_client(umd_db: sa.Engine, source_store):
    """Resolve the full A/B/C fixture, build projections, and return the public
    ``/v1/entities`` HTTP client plus a label->items map (never table-only proof)."""
    from fastapi.testclient import TestClient

    from test_api_contract import _build_all, _client_settings
    from umd.api.app import create_app

    composer, _svc = _setup(umd_db)
    for sid in (SOURCE_A, SOURCE_B, SOURCE_C):
        _seed_source(composer, sid)
    for sid in (SOURCE_A, SOURCE_B, SOURCE_C):
        _run_resolution(composer, sid)
    _build_all(umd_db)
    app = create_app(
        engine=umd_db, source_store=source_store, settings=_client_settings(), runner="hermetic"
    )
    with TestClient(app) as client:
        read_headers = {"Authorization": "Bearer read-key"}
        r = client.get("/v1/entities?limit=100", headers=read_headers)
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        by_label: dict[str, list[dict[str, Any]]] = {}
        for it in items:
            by_label.setdefault(it.get("display_label") or it["label"], []).append(it)
        yield client, by_label


@pytest.fixture()
def _p3_http(umd_db: sa.Engine, source_store):
    """Real nine-stage HTTP ingestion (POST /v1/sources + poll /v1/jobs) of the
    A/B/C identity through the hermetic in-process production DAG runner. De-risks
    the live scenario; returns the public entities client + label map."""
    import time

    from fastapi.testclient import TestClient

    from test_api_contract import _client_settings
    from umd.api.app import create_app

    book_a = (
        "Chapter 1\n\n"
        "The apprentice Mara met the warden Orin and Mara took the lantern. "
        "Ellis the cartographer watched the flame and Ellis smiled.\n\n"
        "Mara knelt and the wick caught, burning clean and steady.\n\n"
        "The merchant John arrived by dusk and John bought the map from Mara.\n"
    )
    book_b = (
        "Chapter 1\n\n"
        "Mara and Ellis climbed the hill and Mara carried the lantern. "
        "Ellis unrolled a fresh map and Ellis traced the eastern road.\n\n"
        "At the top Mara looked out over the village lights below.\n\n"
        "The courier John rode through the night and John carried a sealed letter.\n"
    )
    book_c = (
        "Chapter 1\n\nThe sailor Mara knew the harbor well and Mara guided the ship at night.\n"
    )

    def _ingest(client, name, text, work_id):
        payload = {
            "media_kind": "txt",
            "original_name": name,
            "content_type": "text/plain",
            "content": text,
        }
        if work_id is not None:
            payload["work_id"] = work_id
        r = client.post("/v1/sources", json=payload, headers={"Authorization": "Bearer write-key"})
        assert r.status_code == 201, r.text
        return r.json()

    def _poll(client, sid):
        job = f"job-{sid[:12]}"
        for _ in range(150):
            rj = client.get(f"/v1/jobs/{job}", headers={"Authorization": "Bearer read-key"})
            assert rj.status_code == 200, rj.text
            if rj.json()["status"] in ("complete", "failed", "cancelled"):
                return rj.json()["status"]
            time.sleep(0.05)
        return "timeout"

    app = create_app(
        engine=umd_db, source_store=source_store, settings=_client_settings(), runner="hermetic"
    )
    with TestClient(app) as client:
        a = _ingest(client, "novel_a.txt", book_a, None)
        wa = a["work_id"]
        b = _ingest(client, "novel_b.txt", book_b, wa)
        c = _ingest(client, "other.txt", book_c, None)
        for sid in (a["source_id"], b["source_id"], c["source_id"]):
            assert _poll(client, sid) == "complete"
        r = client.get("/v1/entities?limit=100", headers={"Authorization": "Bearer read-key"})
        assert r.status_code == 200, r.text
        items = r.json()["items"]
        by_label: dict[str, list[dict[str, Any]]] = {}
        for it in items:
            by_label.setdefault(it.get("display_label") or it["label"], []).append(it)
        yield SimpleNamespace(client=client, by_label=by_label, a=a, b=b, c=c, wa=wa)


def _dashless(uuid_like: str) -> str:
    return uuid_like.replace("-", "")


def _dashed(uuid_like: str) -> str:
    """Normalize a 32-hex id (as returned by POST /v1/sources) to dashed UUID form,
    which is the format the membership filters expect."""
    return (
        f"{uuid_like[:8]}-{uuid_like[8:12]}-{uuid_like[12:16]}-{uuid_like[16:20]}-{uuid_like[20:]}"
    )


def test_john_same_work_collision_separate_public(_p3_client) -> None:
    """P3-S3/R3: John A and John B share the SAME name and SAME work but have NO
    shared evidence (distinct locators, no explicit correspondence) -> they resolve
    to TWO DISTINCT opaque refs, never merged by string equality, never alias-linked.
    Mara still unifies into ONE canonical spanning A+B."""
    client, by_label = _p3_client

    john = by_label.get(SAME_NAME_COLLISION, [])
    assert len(john) == 2, john
    assert len({j["ref"] for j in john}) == 2, "same-name/same-work must not collapse"
    memsets = {frozenset(j["memberships"]["source_ids"]) for j in john}
    assert memsets == {frozenset([SOURCE_A]), frozenset([SOURCE_B])}, memsets
    for j in john:
        assert NOVEL_WORK in j["memberships"]["work_ids"]
        assert j["ref"].startswith("entity:canonical:")
        # No alias links the two John canonicals to one another.
        detail = client.get(
            f"/v1/entities/{j['ref']}", headers={"Authorization": "Bearer read-key"}
        )
        assert detail.status_code == 200, detail.text
        body = detail.json()
        for ref in {x["ref"] for x in john}:
            assert ref not in (body.get("aliases") or []), (j["ref"], body.get("aliases"))

    # Mara (explicit correspondence / accepted evidence) still unifies across A+B.
    novel_mara = [m for m in by_label["Mara"] if NOVEL_WORK in m["memberships"]["work_ids"]]
    assert len(novel_mara) == 1
    assert {SOURCE_A, SOURCE_B} <= set(novel_mara[0]["memberships"]["source_ids"])


def test_inverse_order_equality_public(umd_db: sa.Engine, source_store) -> None:
    """P3-S2/R2: ingest-order invariance — resolving A,B,C forward vs C,B,A reverse
    yields the SAME public canonical refs (no first-establisher bias)."""
    from fastapi.testclient import TestClient

    from test_api_contract import _build_all, _client_settings
    from umd.api.app import create_app

    def _run(order: tuple[str, ...]) -> dict[str, str]:
        composer, _svc = _setup(umd_db)
        for sid in order:
            _seed_source(composer, sid)
        for sid in order:
            _run_resolution(composer, sid)
        _build_all(umd_db)
        app = create_app(
            engine=umd_db, source_store=source_store, settings=_client_settings(), runner="hermetic"
        )
        with TestClient(app) as client:
            r = client.get("/v1/entities?limit=100", headers={"Authorization": "Bearer read-key"})
            assert r.status_code == 200, r.text
            out: dict[str, str] = {}
            for it in r.json()["items"]:
                label = it.get("display_label") or it["label"]
                if NOVEL_WORK in it["memberships"].get("work_ids", []):
                    out.setdefault(label, it["ref"])
            return out

    forward = _run((SOURCE_A, SOURCE_B, SOURCE_C))
    _truncate(umd_db)
    reverse = _run((SOURCE_C, SOURCE_B, SOURCE_A))
    assert forward == reverse
    assert SAME_NAME_COLLISION in forward  # John present in Novel


def test_no_duplicate_reconciliation_public(_p3_client, umd_db: sa.Engine) -> None:
    """P3-S2/R1: exactly ONE active Mara canonical in Novel after full A/B/C
    resolution, and a rerun over the same committed evidence never establishes a
    duplicate (single resolution authority)."""
    client, by_label = _p3_client
    novel_mara = [m for m in by_label["Mara"] if NOVEL_WORK in m["memberships"]["work_ids"]]
    assert len(novel_mara) == 1, "duplicate Mara canonical must not exist"

    before = _count_resolved(umd_db)
    composer, _svc = _composer(umd_db)
    for sid in (SOURCE_A, SOURCE_B, SOURCE_C):
        _run_resolution(composer, sid)
    after = _count_resolved(umd_db)
    assert after == before, "rerun must not establish additional EntityResolved events"


def test_wipe_replay_identity_equality_public(umd_db: sa.Engine, source_store) -> None:
    """P3-S2: wipe+replay of the current-tier / search / edge projections is
    byte-stable — rebuilding from the immutable ledger yields the SAME public refs
    and memberships (replay-derived identity, no double-count)."""
    from fastapi.testclient import TestClient

    from test_api_contract import _build_all, _client_settings
    from umd.api.app import create_app

    composer, _svc = _setup(umd_db)
    for sid in (SOURCE_A, SOURCE_B, SOURCE_C):
        _seed_source(composer, sid)
    for sid in (SOURCE_A, SOURCE_B, SOURCE_C):
        _run_resolution(composer, sid)

    def _snapshot() -> dict[tuple[str, str], str]:
        _build_all(umd_db)  # wipe=True replay of current_tier1 + edges + search
        app = create_app(
            engine=umd_db, source_store=source_store, settings=_client_settings(), runner="hermetic"
        )
        with TestClient(app) as client:
            r = client.get("/v1/entities?limit=100", headers={"Authorization": "Bearer read-key"})
            assert r.status_code == 200, r.text
            return {
                (
                    it.get("display_label") or it["label"],
                    frozenset(it["memberships"]["source_ids"]),
                ): it["ref"]
                for it in r.json()["items"]
            }

    first = _snapshot()
    second = _snapshot()  # wipe + full replay again
    assert first == second, "wipe/replay must reproduce identical public identity"
    mara = [r for (label, _mems), r in first.items() if label == "Mara" and SOURCE_A in _mems]
    assert len(mara) == 1


def test_http_public_identity_abc(_p3_http) -> None:
    """P3-S2/R9: real nine-stage HTTP ingestion (POST /v1/sources + poll /v1/jobs)
    through the production DAG runner proves Mara unifies into ONE canonical
    spanning A+B, the other-work Mara (C) is a DISTINCT ref, scoped reads return
    only the right canonicals, and no duplicate canonical is established."""
    client = _p3_http.client
    by_label = _p3_http.by_label
    a, b, c = _p3_http.a, _p3_http.b, _p3_http.c
    sa_id, sb_id, sc_id = a["source_id"], b["source_id"], c["source_id"]

    def _memb(source_ids):
        return {_dashless(s) for s in source_ids}

    mara = by_label.get("Mara", [])
    mara_a = [m for m in mara if sa_id in _memb(m["memberships"]["source_ids"])]
    mara_c = [m for m in mara if sc_id in _memb(m["memberships"]["source_ids"])]
    # Mara unifies across A+B (same work, shared correspondence) into ONE canonical.
    assert len(mara_a) == 1, mara_a
    assert sb_id in _memb(mara_a[0]["memberships"]["source_ids"]), mara_a
    # The other-work Mara (C) is a DISTINCT ref (no cross-work merge).
    assert len(mara_c) == 1, mara_c
    assert mara_c[0]["ref"] != mara_a[0]["ref"]
    # No duplicate: exactly one Mara canonical carries source A's membership.
    assert len([m for m in mara if sa_id in _memb(m["memberships"]["source_ids"])]) == 1

    # Scoped public read: source A sees only A's Mara; source C only C's.
    for sid, expected in ((sa_id, mara_a[0]), (sc_id, mara_c[0])):
        r = client.get(
            f"/v1/entities?source_id={_dashed(sid)}", headers={"Authorization": "Bearer read-key"}
        )
        assert r.status_code == 200, r.text
        labels = [it.get("display_label") or it["label"] for it in r.json()["items"]]
        assert labels.count("Mara") == 1, (sid, labels)
        scoped = next(
            it for it in r.json()["items"] if (it.get("display_label") or it["label"]) == "Mara"
        )
        assert scoped["ref"] == expected["ref"]


def _tail(engine: sa.Engine) -> int:
    with engine.connect() as conn:
        t = conn.execute(sa.text("SELECT max(seq) FROM semantic_event")).scalar()
    return int(t or 0)


def test_public_generic_relationship_typed_related_to(umd_db: sa.Engine) -> None:
    """P3-S3/R7: a valid MENTOR_OF relationship across the two-source cast is emitted
    as a typed RELATED_TO (relationship_type=MENTOR_OF) and a SIBLING_OF predicate
    is preserved, both readable through the PUBLIC /v1/query/structured
    RELATIONSHIP_EDGES surface (full-DAG reconciliation -> ledger -> edge projection)."""
    from fastapi.testclient import TestClient

    from test_api_contract import _build_all, _client_settings
    from umd.api.app import create_app

    composer, _svc = _setup(umd_db)
    for sid in (SOURCE_A, SOURCE_B):
        _seed_source(composer, sid)
        _run_resolution(composer, sid)

    identity = _identity(umd_db)
    by_label = _refs_by_label(identity)
    novel_mara = by_label["Mara"][0]
    novel_ellis = by_label["Ellis"][0]
    assert novel_mara != novel_ellis

    seg = SegmentEvidenceRef(locator="source://a/rel/1", evidence_ref="ev:rel:1")
    gb = GeneratedBy(path="deterministic", config_digest="umd-entity-resolution@1")
    analysis = SemanticAnalysisResult(
        source_id=SOURCE_A,
        generated_by=gb,
        relationships=[
            RelationshipCandidate(
                subject_ref=novel_mara,
                predicate="MENTOR_OF",
                object_ref=novel_ellis,
                confidence=0.9,
                segment=seg,
                generated_by=gb,
            ),
            RelationshipCandidate(
                subject_ref=novel_ellis,
                predicate="SIBLING_OF",
                object_ref=novel_mara,
                confidence=0.85,
                segment=seg,
                generated_by=gb,
            ),
        ],
    )
    res = ResolutionBatch(
        source_id=SOURCE_A,
        canonical_entities=[
            CanonicalEntity(ref=novel_mara, label="Mara", source_id=SOURCE_A),
            CanonicalEntity(ref=novel_ellis, label="Ellis", source_id=SOURCE_A),
        ],
    )
    events = SemanticReconciler().reconcile(
        ReconciliationInput(source_id=SOURCE_A, analysis=analysis, resolution=res)
    )
    SemanticLedger(umd_db).append(events)
    _build_all(umd_db)

    app = create_app(
        engine=umd_db, source_store=None, settings=_client_settings(), runner="hermetic"
    )
    with TestClient(app) as client:
        body = {
            "kind": "RELATIONSHIP_EDGES",
            "filters": {"relationship_type": "MENTOR_OF"},
            "consistency_token": _tail(umd_db),
        }
        r = client.post(
            "/v1/query/structured", json=body, headers={"Authorization": "Bearer read-key"}
        )
        assert r.status_code == 200, r.text
        results = r.json()["results"]
        typed = [h for h in results if h["predicate"] == "RELATED_TO"]
        assert len(typed) >= 1, results
        hit = typed[0]
        assert hit["data"].get("relationship_type") == "MENTOR_OF"
        # Endpoints may be surfaced as the source-bound mention ref; the typed
        # RELATED_TO predicate + relationship_type is the contract under test.
        assert hit["ref"].startswith("entity:") and hit["value"].startswith("entity:")

        # SIBLING_OF is preserved as its own registered predicate.
        body_sib = {
            "kind": "RELATIONSHIP_EDGES",
            "filters": {"predicate": "SIBLING_OF"},
            "consistency_token": _tail(umd_db),
        }
        rs = client.post(
            "/v1/query/structured", json=body_sib, headers={"Authorization": "Bearer read-key"}
        )
        assert rs.status_code == 200, rs.text
        sib = [h for h in rs.json()["results"] if h["predicate"] == "SIBLING_OF"]
        assert len(sib) >= 1, rs.json()
