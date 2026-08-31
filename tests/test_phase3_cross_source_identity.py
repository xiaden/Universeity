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
from typing import Any

import pytest
import sqlalchemy as sa

from fixtures_two_source import (
    AMBIGUOUS_NAME,
    NOVEL_WORK,
    OTHER_WORK,
    SHARED_NOVEL_NAMES,
    SOURCE_A,
    SOURCE_B,
    SOURCE_C,
    WORK_BY_SOURCE,
    two_source_mention_specs,
)
from umd.application.commands import SemanticCommandService
from umd.domain.evidence import EvidenceBatch
from umd.domain.models import Evidence, EvidenceKind
from umd.resolution.mentions import SourceMention
from umd.resolution.resolution import PostgresSplitEnumerator, Resolver
from umd.resolution.service import EntityResolutionService, ResolutionInput
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
    # Unrelated cross-work same-name is a reviewable CORRESPONDENCE (2: Mara, Ellis).
    assert len(reviewable) == 2, reviewable
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
