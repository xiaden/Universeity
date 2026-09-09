"""Plan U Phase 1 (P1-S1..S5): accepted correspondence is authoritative, durable input.

Spec-first tests for the semantic identity / relationship boundary-correctness pass.
They prove the existing ENTITY_RESOLUTION authority hydrates accepted explicit
correspondence/alignment AND human support into the pure ``ResolutionInputBuilder``
(never inferred from same-name/work/continuity/locator/fuzzy similarity), and that an
accepted correspondence recorded AFTER a resolution is persisted as authoritative input
for a SUBSEQUENT resolution generation — idempotent, replayable, with provenance, and
NEVER silently resolved in SEMANTIC_RECONCILIATION.

These tests were written BEFORE the production wiring existed (spec-first); they fail
until src/umd/jobs/production.py hydrates correspondence/human_support.

Rules preserved:
  * one ENTITY_RESOLUTION authority (no second resolution batch in reconciliation);
  * same-name/work/continuity/locator/fuzzy similarity is candidate narrowing only;
  * identical-content co-reference and differing-content John separation stay green
    (Plan T content-derived separation);
  * append-only ledger + alignment registry; no fabricated entity rows / IDs;
  * nullable UUID FKs for non-UUID canonical refs (never a second identity store).
"""

from __future__ import annotations

import json
import uuid
from typing import Any
from unittest import mock

import pytest
import sqlalchemy as sa

from fixtures_two_source import NOVEL_WORK, OTHER_WORK, SOURCE_A, SOURCE_B, SOURCE_C
from test_phase3_cross_source_identity import (
    _align_rows,
    _count_resolved,
    _identity,
    _manifest,
    _mems,
    _run_resolution,
    _seed_named,
    _setup,
)
from umd.storage.postgres.reducer import (
    CANONICAL_IDENTITY_PREDICATE,
    STATE_USER_CONFIRMED,
    USER_OVERRIDE,
)

pytestmark = pytest.mark.postgres


def _record_equiv(composer: Any, left_ref: str, right_ref: str) -> None:
    """Record an accepted (positive) explicit correspondence via the alignment authority."""
    composer._opt("commands").record_alignment(  # noqa: SLF001
        left_ref=left_ref,
        right_ref=right_ref,
        alignment_type="EQUIVALENT",
        method="api",
        confidence=1.0,
        correlation_id=uuid.uuid5(uuid.NAMESPACE_URL, "plan-u"),
        idempotency_key=uuid.uuid5(uuid.NAMESPACE_URL, f"plan-u-equiv:{left_ref}:{right_ref}"),
    )


def _mara_refs(umd_db: sa.Engine) -> dict[str, str]:
    """Return {source_id -> Mara canonical ref} from committed identity current_state."""
    identity = _identity(umd_db)
    out: dict[str, str] = {}
    for ref, rec in identity.items():
        if rec["meta"].get("display_label") != "Mara":
            continue
        for sid in _mems(rec).get("source_ids") or []:
            out.setdefault(str(sid), ref)
    return out


# ---------------------------------------------------------------------------
# P1-S1: _entity_resolution supplies committed + accepted-correspondence + human support
# ---------------------------------------------------------------------------


def test_entity_resolution_supplies_committed_correspondence_human_support(
    umd_db: sa.Engine,
) -> None:
    """The single authority feeds ALL THREE authoritative inputs to the pure builder:
    committed assignments, accepted explicit correspondence, and human-confirmed
    support. Same-name/work alone never seeds a cross-source join."""
    composer, _svc = _setup(umd_db)
    _seed_named(
        composer,
        SOURCE_A,
        "Mara",
        "chapter/1/paragraph/1",
        context_text="The apprentice Mara lit the lantern.",
    )
    _seed_named(
        composer,
        SOURCE_C,
        "Mara",
        "chapter/1/paragraph/1",
        context_text="The sailor Mara knew the harbor.",
    )
    _run_resolution(composer, SOURCE_A)
    _run_resolution(composer, SOURCE_C)

    by_source = _mara_refs(umd_db)
    a_ref = by_source[SOURCE_A]
    c_ref = by_source[SOURCE_C]
    assert a_ref != c_ref  # distinct works + distinct content, no correspondence yet

    # Accepted correspondence A <-> C (durable alignment ledger record).
    _record_equiv(composer, a_ref, c_ref)
    # Human-confirm A's Mara (override with FULL metadata so support_refs survive).
    identity = _identity(umd_db)
    composer._opt("commands").record_override(  # noqa: SLF001
        subject_ref=a_ref,
        predicate=CANONICAL_IDENTITY_PREDICATE,
        object_ref=json.dumps(dict(identity[a_ref]["meta"]), sort_keys=True),
        actor="tester",
    )

    from umd.resolution.service import ResolutionInputBuilder

    captured: dict[str, Any] = {}
    real_build = ResolutionInputBuilder.build

    def _spy(self: Any, **kwargs: Any) -> Any:
        captured.update(kwargs)
        return real_build(self, **kwargs)

    with mock.patch.object(ResolutionInputBuilder, "build", _spy):
        _run_resolution(composer, SOURCE_A)

    committed = captured["committed_observations"]
    correspondence = captured["correspondence"]
    human_support = captured["human_support"]
    assert committed, "committed assignment must be supplied"
    assert correspondence, "accepted correspondence must be supplied"
    assert human_support, "human-confirmed support must be supplied"

    mid = next(iter(committed))
    assert committed[mid] == a_ref  # existing canonical assignment preserved
    assert human_support[mid] == a_ref  # human-confirmed ref locked/overridden
    assert correspondence[mid] in {a_ref, c_ref}  # authoritative ref of the accepted component
    # Same-name/work never joins by itself: the mention's entity_id comes ONLY from the
    # authoritative inputs, never from string equality with the other work's Mara.
    assert set(committed) == set(correspondence) == set(human_support)


# ---------------------------------------------------------------------------
# P1-S4: regression fixtures — unify ONLY with explicit evidence / accepted correspondence
# ---------------------------------------------------------------------------


def test_different_text_locators_unify_only_with_correspondence(umd_db: sa.Engine) -> None:
    """Same work, different text AND different locators: distinct canonicals until an
    accepted correspondence is recorded; re-resolving BOTH sources converges them onto
    ONE authoritative canonical spanning both sources."""
    composer, _svc = _setup(umd_db)
    _seed_named(
        composer,
        SOURCE_A,
        "Mara",
        "chapter/1/paragraph/1",
        context_text="The apprentice Mara lit the lantern.",
    )
    _seed_named(
        composer,
        SOURCE_B,
        "Mara",
        "chapter/9/paragraph/12",
        context_text="The sailor Mara knew the harbor.",
    )
    _run_resolution(composer, SOURCE_A)
    _run_resolution(composer, SOURCE_B)

    by_source = _mara_refs(umd_db)
    assert by_source[SOURCE_A] != by_source[SOURCE_B]  # no correspondence -> distinct

    _record_equiv(composer, by_source[SOURCE_A], by_source[SOURCE_B])
    _run_resolution(composer, SOURCE_A)
    _run_resolution(composer, SOURCE_B)

    identity = _identity(umd_db)
    spanning = [
        r
        for r, rec in identity.items()
        if rec["meta"].get("display_label") == "Mara"
        and {SOURCE_A, SOURCE_B} <= set(_mems(rec).get("source_ids") or [])
    ]
    assert len(spanning) == 1, spanning
    ref = spanning[0]
    assert ref.startswith("entity:canonical:")
    assert ":" not in ref.rsplit("entity:canonical:", 1)[1]


def test_cross_work_mara_unifies_only_with_accepted_correspondence(
    umd_db: sa.Engine,
) -> None:
    """Book One / Book Two Mara: cross-work same-name does NOT unify by name or shared
    structural position — only an ACCEPTED correspondence converges the two realizations
    onto ONE authoritative canonical spanning both works."""
    composer, _svc = _setup(umd_db)
    _seed_named(
        composer,
        SOURCE_A,
        "Mara",
        "chapter/1/paragraph/1",
        context_text="The apprentice Mara lit the lantern.",
    )
    _seed_named(
        composer,
        SOURCE_C,
        "Mara",
        "chapter/1/paragraph/1",
        context_text="The sailor Mara knew the harbor.",
    )
    _run_resolution(composer, SOURCE_A)
    _run_resolution(composer, SOURCE_C)

    by_source = _mara_refs(umd_db)
    assert by_source[SOURCE_A] != by_source[SOURCE_C]  # cross-work same-name stays distinct

    # The alignment stage surfaces them as a REVIEWABLE CORRESPONDENCE — never a merge.
    composer._cross_source_alignment(_manifest(SOURCE_C))
    aligns = _align_rows(umd_db)
    assert any(a[2] == "CORRESPONDENCE" and a[3] == "candidate-separation" for a in aligns)
    assert _mara_refs(umd_db)[SOURCE_A] != _mara_refs(umd_db)[SOURCE_C]  # still distinct

    # Only an ACCEPTED (EQUIVALENT) correspondence + re-resolution converges them.
    _record_equiv(composer, by_source[SOURCE_A], by_source[SOURCE_C])
    _run_resolution(composer, SOURCE_A)
    _run_resolution(composer, SOURCE_C)

    identity = _identity(umd_db)
    spanning = [
        r
        for r, rec in identity.items()
        if rec["meta"].get("display_label") == "Mara"
        and {SOURCE_A, SOURCE_C} <= set(_mems(rec).get("source_ids") or [])
    ]
    assert len(spanning) == 1, spanning
    mems = _mems(identity[spanning[0]])
    assert NOVEL_WORK in (mems.get("work_ids") or [])
    assert OTHER_WORK in (mems.get("work_ids") or [])


def test_cross_work_same_name_without_correspondence_stays_distinct(
    umd_db: sa.Engine,
) -> None:
    """Same cross-work names WITHOUT accepted correspondence remain distinct AND
    reviewable across subsequent resolution generations — never silently merged."""
    composer, _svc = _setup(umd_db)
    _seed_named(
        composer,
        SOURCE_A,
        "Mara",
        "chapter/1/paragraph/1",
        context_text="The apprentice Mara lit the lantern.",
    )
    _seed_named(
        composer,
        SOURCE_C,
        "Mara",
        "chapter/1/paragraph/1",
        context_text="The sailor Mara knew the harbor.",
    )
    _run_resolution(composer, SOURCE_A)
    _run_resolution(composer, SOURCE_C)

    # A subsequent generation (no correspondence recorded) keeps them distinct.
    _run_resolution(composer, SOURCE_C)
    assert _mara_refs(umd_db)[SOURCE_A] != _mara_refs(umd_db)[SOURCE_C]

    # The alignment stage records the reviewable separation, still no merge.
    composer._cross_source_alignment(_manifest(SOURCE_C))
    aligns = _align_rows(umd_db)
    assert any(a[2] == "CORRESPONDENCE" for a in aligns)
    assert _mara_refs(umd_db)[SOURCE_A] != _mara_refs(umd_db)[SOURCE_C]


def test_false_friend_remains_separate_despite_human_confirm(umd_db: sa.Engine) -> None:
    """A human-confirmed canonical never drags a DIFFERENT realization (false friend)
    into it: coincident-structure same-name John with differing content stays a separate,
    reviewable canonical even after one John is USER_CONFIRMED. Plan T content-derived
    separation remains green."""
    composer, _svc = _setup(umd_db)
    _seed_named(
        composer,
        SOURCE_A,
        "John",
        "chapter/1/paragraph/6",
        context_text="The merchant John arrived by dusk and John bought the map.",
    )
    _seed_named(
        composer,
        SOURCE_B,
        "John",
        "chapter/1/paragraph/6",
        context_text="The courier John rode through the night and John carried a letter.",
    )
    _run_resolution(composer, SOURCE_A)
    _run_resolution(composer, SOURCE_B)

    identity = _identity(umd_db)
    john_refs = [r for r, rec in identity.items() if rec["meta"].get("display_label") == "John"]
    assert len(john_refs) == 2, john_refs  # content-derived separation (Plan T)

    a_john = [r for r in john_refs if SOURCE_A in set(_mems(identity[r]).get("source_ids"))][0]
    composer._opt("commands").record_override(  # noqa: SLF001
        subject_ref=a_john,
        predicate=CANONICAL_IDENTITY_PREDICATE,
        object_ref=json.dumps(dict(identity[a_john]["meta"]), sort_keys=True),
        actor="tester",
    )

    # A subsequent resolution of B must NOT merge B's John into the confirmed John.
    _run_resolution(composer, SOURCE_B)
    identity2 = _identity(umd_db)
    confirmed = [
        r
        for r, rec in identity2.items()
        if rec["meta"].get("display_label") == "John"
        and (rec["state"] == STATE_USER_CONFIRMED or rec["authority"] == USER_OVERRIDE)
    ]
    assert len(confirmed) == 1, confirmed
    assert set(_mems(identity2[confirmed[0]]).get("source_ids") or []) == {SOURCE_A}
    # Both John canonicals still exist and are distinct (false friend not merged).
    john2 = [r for r, rec in identity2.items() if rec["meta"].get("display_label") == "John"]
    assert len(john2) == 2


# ---------------------------------------------------------------------------
# P1-S5: durable rerun / idempotency + reconciliation stays read-only
# ---------------------------------------------------------------------------


def test_correspondence_convergence_idempotent_and_reconciliation_readonly(
    umd_db: sa.Engine,
) -> None:
    """Correspondence-driven convergence is durable, idempotent, and replayable: the
    SECOND rerun after convergence establishes no additional resolution events, and
    SEMANTIC_RECONCILIATION consumes the committed result WITHOUT resolving another
    batch (no new EntityResolved events, no new canonical identity)."""
    composer, _svc = _setup(umd_db)
    _seed_named(
        composer,
        SOURCE_A,
        "Mara",
        "chapter/1/paragraph/1",
        context_text="The apprentice Mara lit the lantern.",
    )
    _seed_named(
        composer,
        SOURCE_C,
        "Mara",
        "chapter/1/paragraph/1",
        context_text="The sailor Mara knew the harbor.",
    )
    _run_resolution(composer, SOURCE_A)
    _run_resolution(composer, SOURCE_C)

    by_source = _mara_refs(umd_db)
    _record_equiv(composer, by_source[SOURCE_A], by_source[SOURCE_C])
    _run_resolution(composer, SOURCE_A)
    _run_resolution(composer, SOURCE_C)
    est_after_first = _count_resolved(umd_db)
    # The convergence is now durable in the ledger; a subsequent generation converges
    # onto the SAME authoritative ref without establishing duplicates.
    _run_resolution(composer, SOURCE_C)
    assert _count_resolved(umd_db) == est_after_first, "rerun must not add resolution events"

    spanning_before = [
        r
        for r, rec in _identity(umd_db).items()
        if rec["meta"].get("display_label") == "Mara"
        and {SOURCE_A, SOURCE_C} <= set(_mems(rec).get("source_ids") or [])
    ]
    assert len(spanning_before) == 1

    # Reconciliation consumes the committed batch read-only: no new resolution events,
    # and no new canonical identity is fabricated by the reconciler.
    composer._semantic_reconciliation(_manifest(SOURCE_C))
    assert _count_resolved(umd_db) == est_after_first, "reconciliation must not resolve"
    spanning_after = [
        r
        for r, rec in _identity(umd_db).items()
        if rec["meta"].get("display_label") == "Mara"
        and {SOURCE_A, SOURCE_C} <= set(_mems(rec).get("source_ids") or [])
    ]
    assert len(spanning_after) == 1
    assert {r for r in spanning_after} == {r for r in spanning_before}
