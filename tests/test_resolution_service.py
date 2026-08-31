"""P3-S1 spec-first resolution-stage tests.

These drive the *production resolution path* exactly as the ENTITY_RESOLUTION
stage does: typed :class:`SourceMention` records (from semantic observations or
committed evidence) are fed into ``EntityResolutionService.resolve_mentions``
and the resulting :class:`ResolutionBatch` is asserted.

Proven acceptance behaviour (the multi-entity-resolution contract):

  * three distinct characters with repeated mentions across chapters/scenes
    resolve to **three distinct canonical entities** — never collapsed;
  * aliases map to their canonical character;
  * ONE ambiguous alias remains **unresolved / reviewable** until a human
    confirmation — the resolver never guesses a target.

These are pure unit tests (no DB): the service is a projection and writes
nothing, matching CONTRACTS.md:76.
"""

from __future__ import annotations

import uuid

from umd.domain.models import ConfidenceState
from umd.resolution.candidates import normalize_name
from umd.resolution.mentions import SourceMention
from umd.resolution.service import EntityResolutionService

# Fixed mention ids so the deterministic member ordering (sorted by mention id)
# is stable across runs and the alias-member is never accidentally the cluster
# "first" member (which would suppress its AliasMapping).
# Canonical surfaces are chosen LONGEST so the service's ``_canonical_label``
# (longest distinct surface) picks the canonical name, keeping the alias mention
# (shorter) the AliasMapping subject — deterministic, not data-dependent.
ALICE = "10000000-0000-0000-0000-000000000000"
ALICE_2 = "20000000-0000-0000-0000-000000000000"
ALIAS_AL = "30000000-0000-0000-0000-000000000000"
ROBERT = "40000000-0000-0000-0000-000000000000"
ROBERT_2 = "50000000-0000-0000-0000-000000000000"
ALIAS_BOB = "60000000-0000-0000-0000-000000000000"
CAROL = "70000000-0000-0000-0000-000000000000"
CAROL_2 = "80000000-0000-0000-0000-000000000000"
ALIAS_CARO = "90000000-0000-0000-0000-000000000000"
ASTRA = "a0000000-0000-0000-0000-000000000000"


def _m(
    *,
    text: str,
    mid: str,
    entity_id: str | None = None,
    forms: list[str] | None = None,
    state: str = ConfidenceState.PROBABLE.value,
    conf: float = 0.6,
    entity_type: str = "character",
    co_occurring: list[str] | None = None,
) -> SourceMention:
    meta: dict[str, object] = {"entity_type": entity_type}
    if co_occurring:
        meta["co_occurring"] = co_occurring
    return SourceMention(
        id=uuid.UUID(mid),
        source_id="src-book",
        entity_id=entity_id,
        mention_text=text,
        normalized_forms=forms or [normalize_name(text)],
        confidence_state=state,
        confidence=conf,
        metadata_=meta,
    )


def _book_mentions() -> list[SourceMention]:
    """A realistic multi-chapter cast: 3 characters + aliases + one ambiguous alias.

    Repeated mentions (distinct source ids) model the same character appearing
    across chapters/scenes; the alias mentions carry the canonical normalized
    form plus a shared co-occurrence context so they resolve deterministically.
    """
    return [
        _m(text="Alice", mid=ALICE, co_occurring=["Robert"]),
        _m(text="Alice", mid=ALICE_2, co_occurring=["Robert"]),
        _m(text="Al", mid=ALIAS_AL, forms=["alice"], co_occurring=["Robert"]),
        _m(text="Robert", mid=ROBERT, co_occurring=["Alice"]),
        _m(text="Robert", mid=ROBERT_2, co_occurring=["Alice"]),
        _m(text="Bob", mid=ALIAS_BOB, forms=["robert"], co_occurring=["Alice"]),
        _m(text="Carol", mid=CAROL, co_occurring=["Dan"]),
        _m(text="Carol", mid=CAROL_2, co_occurring=["Dan"]),
        _m(text="Caro", mid=ALIAS_CARO, forms=["carol"], co_occurring=["Dan"]),
        # Ambiguous alias: deliberately left reviewable (never a guessed target).
        _m(text="Astra", mid=ASTRA, state=ConfidenceState.AMBIGUOUS.value),
    ]


def _ref_of(entities, member_id: str) -> str:
    return next(e.ref for e in entities if member_id in e.member_mention_ids)


def test_three_characters_resolve_to_three_distinct_canonical_entities():
    """>=3 distinct characters with repeated mentions never collapse."""
    batch = EntityResolutionService(resolve_floor=0.4).resolve_mentions(_book_mentions())

    assert len(batch.canonical_entities) == 3
    refs = [e.ref for e in batch.canonical_entities]
    assert len(set(refs)) == 3, f"characters collapsed into {len(set(refs))} canonicals"
    # Repeated mentions across chapters/scenes group under one character.
    for ent in batch.canonical_entities:
        assert len(ent.member_mention_ids) >= 2
    # Distinct surface labels (no destructive collapse into one name).
    assert len({e.label for e in batch.canonical_entities}) == 3
    # No cross-character assignment leaks.
    assert set(batch.assignments.values()) == set(refs)


def test_aliases_map_to_their_canonical_character():
    """>=2 aliases resolve to the correct canonical (never merged or mis-mapped)."""
    batch = EntityResolutionService(resolve_floor=0.4).resolve_mentions(_book_mentions())
    ents = batch.canonical_entities

    alice_ref = _ref_of(ents, ALICE)
    robert_ref = _ref_of(ents, ROBERT)
    carol_ref = _ref_of(ents, CAROL)

    assert batch.assignments[ALIAS_AL] == alice_ref
    assert batch.assignments[ALIAS_BOB] == robert_ref
    assert batch.assignments[ALIAS_CARO] == carol_ref

    # Explicit AliasMapping records for each alias mention (alias_ref = mention id).
    alias_refs = {a.alias_ref for a in batch.alias_mappings}
    assert alias_refs == {ALIAS_AL, ALIAS_BOB, ALIAS_CARO}


def test_ambiguous_alias_stays_unresolved_and_reviewable():
    """An ambiguous alias is kept unresolved/reviewable with no guessed target."""
    batch = EntityResolutionService(resolve_floor=0.4).resolve_mentions(_book_mentions())

    assert len(batch.unresolved) == 1
    u = batch.unresolved[0]
    assert u.text == "Astra"
    assert u.reason == "ambiguous"
    assert ASTRA not in batch.assignments  # no guessed target
    assert all(ASTRA not in e.member_mention_ids for e in batch.canonical_entities)
    assert ASTRA not in {a.alias_ref for a in batch.alias_mappings}
    # A batch with an unresolved mention is surfaced as AMBIGUOUS, not confirmed.
    assert batch.state == ConfidenceState.AMBIGUOUS.value
