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
from umd.resolution.service import EntityResolutionService, ResolutionInputBuilder

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


def test_accepted_canonicals_carry_full_identity_metadata():
    """Plan S P1-S1/P1-S6: accepted canonicals carry the full first-class identity.

    Opaque non-source-bound ref, type, display label, active aliases, exact
    support refs, confidence/state, generated-by provenance, and
    work/source/continuity memberships — with no synthetic alias entity.
    """
    batch = EntityResolutionService(resolve_floor=0.4).resolve_mentions(_book_mentions())
    assert len(batch.canonical_entities) == 3
    for e in batch.canonical_entities:
        # Opaque ref: no source-bound prefix, no filename, deterministic hex tail.
        tail = e.ref[len("entity:canonical:") :]
        assert ":" not in tail, e.ref
        assert "chapter" not in tail and "paragraph" not in tail, e.ref
        assert e.entity_type == "character"
        assert e.state in {ConfidenceState.PROBABLE.value, ConfidenceState.CONFIRMED.value}
        assert e.generated_by.get("generator") == "EntityResolutionService"
        assert e.generated_by.get("config_digest") == "umd-entity-resolution@1"
        # Exact support/evidence refs == the member mention refs.
        assert set(e.support_refs) == set(e.member_mention_ids)
        # Work/source membership context (source_local; work/continuity empty here).
        assert e.memberships["source_ids"] == ["src-book"]
        assert e.memberships["work_ids"] == []
        assert e.memberships["continuity_ids"] == []
    # Active aliases are the distinct non-label surfaces; no synthetic alias entity.
    by_label = {e.label: e for e in batch.canonical_entities}
    assert by_label["Alice"].aliases == ["Al"]
    assert by_label["Robert"].aliases == ["Bob"]
    assert by_label["Carol"].aliases == ["Caro"]
    # ESTABLISH commands route canonical-establishment identity metadata.
    establish = [c for c in batch.commands if c.kind == "ESTABLISH"]
    assert len(establish) == 3
    for cmd in establish:
        assert cmd.metadata["display_label"] in by_label
        assert cmd.metadata["canonical_type"] == "character"
        assert cmd.metadata["support_refs"]
        assert set(cmd.metadata["memberships"].keys()) == {
            "source_ids",
            "work_ids",
            "continuity_ids",
        }
        assert cmd.metadata["aliases"] == by_label[cmd.metadata["display_label"]].aliases


# ---------------------------------------------------------------------------
# Plan T P1-S5: semantic identity boundary hardening (pure resolution domain)
# ---------------------------------------------------------------------------
NOVEL = "11111111-1111-1111-1111-111111111111"


def _m2(
    *,
    text: str,
    mid: str,
    source: str,
    segment: str,
    work_id: str | None = NOVEL,
    entity_id: str | None = None,
    conf: float = 0.85,
    state: str = ConfidenceState.CONFIRMED.value,
    context: str | None = None,
) -> SourceMention:
    """A mention with content-derived evidence (segment) and an optional work scope.

    ``context`` is the normalized paragraph/context text (Plan T P1-S2): when
    present its content digest participates in the evidence anchor, so
    coincident-structural same-name mentions with different surrounding text
    resolve to DISTINCT opaque refs.
    """
    return SourceMention(
        id=uuid.UUID(mid),
        source_id=source,
        entity_id=entity_id,
        segment_id=segment,
        mention_text=text,
        normalized_forms=[normalize_name(text)],
        confidence_state=state,
        confidence=conf,
        provenance={"locator": f"chapter/1/{segment}"},
        metadata_={"entity_type": "character"},
        work_id=work_id,
        context_text=context,
    )


def _single(batch) -> list[SourceMention]:
    """The member mentions of a one-character canonical cluster."""
    assert len(batch.canonical_entities) == 1
    return batch.canonical_entities[0]


def test_builder_is_single_pure_bounded_input_authority():
    """Plan T P1-S1/R1: the builder deterministically assembles a bounded input.

    Routing the same mentions through ``ResolutionInputBuilder.build`` yields the
    identical ``ResolutionBatch`` as resolving the mentions directly — there is ONE
    bounded input/batch builder and ONE domain decision per execution generation.
    The builder is pure (writes nothing) and sorts mentions by mention id.
    """
    mentions = [
        _m2(text="Mara", mid="10000000-0000-0000-0000-000000000001", source="A", segment="p/1"),
        _m2(text="Mara", mid="10000000-0000-0000-0000-000000000003", source="A", segment="p/3"),
    ]
    direct = EntityResolutionService(resolve_floor=0.4).resolve_mentions(mentions)
    built = EntityResolutionService(resolve_floor=0.4).resolve_mentions(
        ResolutionInputBuilder().build(
            source={"source_id": "A", "work_id": NOVEL},
            evidence=mentions,
            memberships={"source_ids": ["A"], "work_ids": [NOVEL], "continuity_ids": []},
        )
    )
    assert [e.ref for e in built.canonical_entities] == [e.ref for e in direct.canonical_entities]
    # One ESTABLISH decision (plus per-member MENTION commands) — a single
    # authoritative resolution per generation, no duplicate establishment.
    assert sum(1 for c in built.commands if c.kind == "ESTABLISH") == 1
    # Bounded: the built input carries exactly the source scope and no topology.
    assert built.assignments == direct.assignments
    assert not built.contradictions


def test_same_work_same_evidence_unifies_same_canonical_across_sources():
    """Plan T P1-S5: Mara A<->B equality — same canonical when evidence supports it.

    Two sources of the SAME work, with the SAME content-derived evidence (segments),
    unify onto ONE canonical ref — evidence (not display-name-only) authorizes the
    join. The ref is source-independent (no source prefix) and opaque.
    """
    a = [
        _m2(text="Mara", mid="10000000-0000-0000-0000-000000000001", source="A", segment="p/1"),
        _m2(text="Mara", mid="10000000-0000-0000-0000-000000000003", source="A", segment="p/3"),
    ]
    b = [
        _m2(text="Mara", mid="20000000-0000-0000-0000-000000000001", source="B", segment="p/1"),
        _m2(text="Mara", mid="20000000-0000-0000-0000-000000000003", source="B", segment="p/3"),
    ]
    ref_a = _single(EntityResolutionService(resolve_floor=0.4).resolve_mentions(a)).ref
    ref_b = _single(EntityResolutionService(resolve_floor=0.4).resolve_mentions(b)).ref
    assert ref_a == ref_b, "same work + same evidence must unify onto one canonical"
    assert ref_a.startswith("entity:canonical:")
    assert ":" not in ref_a[len("entity:canonical:") :]


def test_same_name_same_work_different_evidence_stays_separate():
    """Plan T P1-S5/R3: John/C same-name separation — evidence disambiguates.

    Same name AND same work is NOT proof of identity. Two "John" characters at
    DIFFERENT evidence segments in the same work stay SEPARATE (distinct refs) and
    never get a fabricated alias linking them. Each source is resolved independently
    (as ENTITY_RESOLUTION does per source), then the resulting refs are compared —
    identical names never collapse across sources without accepted evidence.
    """
    service = EntityResolutionService(resolve_floor=0.4)
    john_a = service.resolve_mentions(
        [_m2(text="John", mid="30000000-0000-0000-0000-000000000006", source="A", segment="p/6")]
    )
    john_b = service.resolve_mentions(
        [_m2(text="John", mid="40000000-0000-0000-0000-000000000007", source="B", segment="p/7")]
    )
    ref_a = _single(john_a).ref
    ref_b = _single(john_b).ref
    assert ref_a != ref_b, "same name + same work but different evidence must stay separate"
    assert not john_a.alias_mappings and not john_b.alias_mappings
    assert _single(john_a).classification == "probable"
    assert _single(john_b).classification == "probable"


def test_moss_never_inferred_as_mara():
    """Plan T P1-S5/R8: honest fallback — Moss is never merged into Mara.

    Without evidence linking them, Moss and Mara keep distinct refs; Moss is NOT an
    alias of Mara and no canonical identity is fabricated for it beyond its own
    probable cluster.
    """
    moss = _m2(text="Moss", mid="50000000-0000-0000-0000-000000000009", source="A", segment="p/9")
    mara = [
        _m2(text="Mara", mid="10000000-0000-0000-0000-000000000001", source="A", segment="p/1"),
        _m2(text="Mara", mid="10000000-0000-0000-0000-000000000003", source="A", segment="p/3"),
    ]
    batch = EntityResolutionService(resolve_floor=0.4).resolve_mentions([moss, *mara])
    assert len(batch.canonical_entities) == 2
    mara_e = next(e for e in batch.canonical_entities if e.label == "Mara")
    moss_e = next(e for e in batch.canonical_entities if e.label == "Moss")
    assert mara_e.ref != moss_e.ref
    assert "Moss" not in mara_e.aliases and "moss" not in mara_e.aliases
    assert moss_e.ref not in mara_e.aliases
    assert moss_e.classification == "probable"
    assert moss_e.state == ConfidenceState.PROBABLE.value


def test_classification_accepted_probable_ambiguous():
    """Plan T P1-S3: resolution distinguishes accepted/probable/unresolved/ambiguous.

    A cluster seeded from an existing committed assignment is ACCEPTED; a fresh
    machine-inferred canonical is PROBABLE; a genuinely ambiguous mention stays
    UNRESOLVED with an AMBIGUOUS batch classification — no fabricated ref or alias.
    """
    # Fresh (no existing assignment) -> probable.
    fresh = [
        _m2(text="Mara", mid="10000000-0000-0000-0000-000000000001", source="A", segment="p/1"),
        _m2(text="Mara", mid="10000000-0000-0000-0000-000000000003", source="A", segment="p/3"),
    ]
    fresh_batch = EntityResolutionService(resolve_floor=0.4).resolve_mentions(fresh)
    assert fresh_batch.classification == "probable"
    assert fresh_batch.canonical_entities[0].classification == "probable"

    # Ambiguous singleton -> unresolved, batch AMBIGUOUS.
    ambiguous = _m2(
        text="Moss",
        mid="50000000-0000-0000-0000-000000000099",
        source="A",
        segment="p/9",
        state=ConfidenceState.AMBIGUOUS.value,
        conf=0.4,
    )
    amb_batch = EntityResolutionService(resolve_floor=0.4).resolve_mentions([ambiguous])
    assert amb_batch.classification == "ambiguous"
    assert amb_batch.unresolved and amb_batch.unresolved[0].classification == "ambiguous"
    assert amb_batch.state == ConfidenceState.AMBIGUOUS.value


def test_human_support_build_narrowing_seeds_accepted():
    """Plan T P1-S5/R2: human_support candidate narrowing reuses a committed ref.

    A human-confirmed ref passed to the builder seeds the mention, producing an
    ACCEPTED canonical that reuses the confirmed ref (no duplicate derivation) —
    human confirmation is a legitimate join that outranks a fresh machine guess.
    """
    human_ref = "entity:canonical:beef000000000001"
    m = _m2(text="Mara", mid="10000000-0000-0000-0000-000000000001", source="A", segment="p/1")
    built = ResolutionInputBuilder().build(
        source={"source_id": "A", "work_id": NOVEL},
        evidence=[m],
        human_support={m.mention_id: human_ref},
    )
    assert built.mentions[0].entity_id == human_ref
    batch = EntityResolutionService(resolve_floor=0.4).resolve_mentions(built)
    assert len(batch.canonical_entities) == 1
    ent = batch.canonical_entities[0]
    assert ent.ref == human_ref
    assert ent.classification == "accepted"
    assert ent.state == ConfidenceState.CONFIRMED.value


def test_coincident_locator_different_content_stays_separate():
    """Plan T P1-S2/P1-S5/R3: coincident structure + different content => distinct.

    Two same-work same-name mentions at the SAME structural locator whose
    surrounding paragraph/context text differs are TWO distinct characters: they
    must NOT be merged by name/work/locator alone. Content disambiguates them
    into distinct opaque refs (the content digest is part of the anchor).
    """
    service = EntityResolutionService(resolve_floor=0.4)
    batch = service.resolve_mentions(
        [
            _m2(
                text="John",
                mid="30000000-0000-0000-0000-000000000010",
                source="A",
                segment="p/6",
                context="The merchant John arrived at the fair",
            ),
            _m2(
                text="John",
                mid="40000000-0000-0000-0000-000000000011",
                source="B",
                segment="p/6",
                context="The courier John rode through the night",
            ),
        ]
    )
    # Coincident structural position + differing content -> distinct canonicals,
    # never one merged character, and never a fabricated alias link between them.
    assert len(batch.canonical_entities) == 2
    refs = [e.ref for e in batch.canonical_entities]
    assert len(set(refs)) == 2, "coincident structure + different content must not merge"
    assert not batch.alias_mappings
    for e in batch.canonical_entities:
        assert e.ref.startswith("entity:canonical:")
        tail = e.ref[len("entity:canonical:") :]
        assert ":" not in tail, e.ref  # opaque, no structural token leaks into the ref


def test_coincident_locator_identical_content_is_co_reference():
    """Plan T P1-S2: coincident structure + identical content is ONE character.

    Guard against the opposite regression: two mentions of the SAME character at
    a coincident structural position with identical surrounding content must
    still union into ONE canonical (not be spuriously split).
    """
    batch = EntityResolutionService(resolve_floor=0.4).resolve_mentions(
        [
            _m2(
                text="John",
                mid="30000000-0000-0000-0000-000000000012",
                source="A",
                segment="p/6",
                context="The merchant John arrived at the fair",
            ),
            _m2(
                text="John",
                mid="30000000-0000-0000-0000-000000000013",
                source="A",
                segment="p/6",
                context="The merchant John arrived at the fair",
            ),
        ]
    )
    assert len(batch.canonical_entities) == 1
    ent = batch.canonical_entities[0]
    assert len(ent.member_mention_ids) == 2
    assert ent.ref.startswith("entity:canonical:")


def test_coincident_locator_no_content_is_ambiguous_no_establish():
    """Plan T P1-S2/P1-S5/R3: no-content coincidence collision is AMBIGUOUS.

    Two same-work same-name mentions at a coincident structural locator with NO
    content evidence cannot be proven distinct OR identical -> they must be
    classified AMBIGUOUS/reviewable and NEVER established. No canonical ref is
    fabricated and no ESTABLISH command is emitted (the resolver never merges by
    name/work/locator alone).
    """
    batch = EntityResolutionService(resolve_floor=0.4).resolve_mentions(
        [
            _m2(text="John", mid="30000000-0000-0000-0000-000000000014", source="A", segment="p/6"),
            _m2(text="John", mid="40000000-0000-0000-0000-000000000015", source="B", segment="p/6"),
        ]
    )
    # No canonical established, both mentions AMBIGUOUS/reviewable, no ESTABLISH.
    assert len(batch.canonical_entities) == 0
    assert batch.classification == "ambiguous"
    assert batch.state == ConfidenceState.AMBIGUOUS.value
    assert len(batch.unresolved) == 2
    assert all(u.reason == "ambiguous" for u in batch.unresolved)
    assert not any(c.kind == "ESTABLISH" for c in batch.commands)
    assert not batch.assignments


def test_accepted_join_still_requires_explicit_evidence():
    """Plan T P1-S5: accepted joins still require explicit correspondence/evidence.

    A seeded (already-committed) canonical ref is reused ONLY when the builder
    supplies the explicit correspondence; without it, name+work strings alone
    never join two mentions into one accepted canonical.
    """
    service = EntityResolutionService(resolve_floor=0.4)
    john_a = _m2(text="John", mid="30000000-0000-0000-0000-000000000016", source="A", segment="p/6")
    john_b = _m2(text="John", mid="40000000-0000-0000-0000-000000000017", source="B", segment="p/6")
    # No explicit correspondence -> the two mentions stay separate (probable) and
    # neither is an ACCEPTED join.
    plain = service.resolve_mentions([john_a, john_b])
    assert len(plain.canonical_entities) == 0  # coincident no-content -> ambiguous
    assert plain.classification == "ambiguous"

    # Explicit human confirmation/lock IS a legitimate accepted join that reuses
    # the confirmed ref (never a name+work guess).
    human_ref = "entity:canonical:beef000000000002"
    built = ResolutionInputBuilder().build(
        source={"source_id": "B", "work_id": NOVEL},
        evidence=[john_b],
        human_support={john_b.mention_id: human_ref},
    )
    accepted = service.resolve_mentions(built)
    assert len(accepted.canonical_entities) == 1
    assert accepted.canonical_entities[0].ref == human_ref
    assert accepted.canonical_entities[0].classification == "accepted"
