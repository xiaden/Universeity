"""Pure unit tests for the deterministic semantic reconciler (Plan O P1-S2/S4).

These test the :mod:`umd.reconciliation.reconciler` contract (CONTRACTS.md:78)
with NO database: given the same typed observations + resolved mappings the
reconciler yields the same ordered assertions; strong facts promote to
CONFIRMED, medium to PROBABLE, weak stay candidate/evidence (UNKNOWN),
ambiguous/conflicting observations keep AMBIGUOUS/CONFLICTING, support refs are
the source evidence (distinct from machine interpretation), unknown relationship
predicates are never invented, and re-running is idempotent.
"""

from __future__ import annotations

from umd.analysis.semantic import (
    ConfidenceState,
    ContextObservation,
    DescriptiveTrait,
    EmotionObservation,
    EntityMention,
    GeneratedBy,
    NormalizedAlias,
    Presence,
    RelationshipCandidate,
    SceneBoundary,
    SegmentEvidenceRef,
    SemanticAnalysisResult,
    StateObservation,
    Utterance,
)
from umd.reconciliation.reconciler import (
    ReconciliationInput,
    SemanticReconciler,
    _promote,
)
from umd.resolution.service import (
    AliasMapping,
    CanonicalEntity,
    Contradiction,
    ResolutionBatch,
)


def _gb() -> GeneratedBy:
    return GeneratedBy(path="deterministic", config_digest="cfg@1")


def _seg(locator: str = "source://s/1", evidence_ref: str = "ev:1") -> SegmentEvidenceRef:
    return SegmentEvidenceRef(locator=locator, evidence_ref=evidence_ref)


def _analysis(**kwargs: object) -> SemanticAnalysisResult:
    base: dict[str, list[object]] = {
        "scene_boundaries": [],
        "entity_mentions": [],
        "aliases": [],
        "presence": [],
        "utterances": [],
        "speaker_candidates": [],
        "traits": [],
        "relationships": [],
        "emotions": [],
        "states": [],
        "context": [],
    }
    base.update(kwargs)
    return SemanticAnalysisResult(source_id="s1", generated_by=_gb(), **base)


def _events(input_: ReconciliationInput) -> list[dict[str, object]]:
    return [e.payload for e in SemanticReconciler().reconcile(input_)]


def _by_predicate(events: list[dict[str, object]]) -> dict[str, list[dict[str, object]]]:
    out: dict[str, list[dict[str, object]]] = {}
    for e in events:
        out.setdefault(str(e["predicate_code"]), []).append(e)
    return out


# ---------------------------------------------------------------------------
# deterministic promotion (P1-S4)
# ---------------------------------------------------------------------------


def test_promote_thresholds() -> None:
    assert _promote(0.9, ConfidenceState.PROBABLE) == "CONFIRMED"
    assert _promote(0.6, ConfidenceState.PROBABLE) == "PROBABLE"
    assert _promote(0.3, ConfidenceState.PROBABLE) == "UNKNOWN"  # weak -> candidate


def test_promote_ambiguous_and_conflicting_kept() -> None:
    assert _promote(0.9, ConfidenceState.AMBIGUOUS) == "AMBIGUOUS"
    assert _promote(0.9, ConfidenceState.CONFLICTING) == "CONFLICTING"


def test_machine_never_emits_user_confirmed() -> None:
    # Machine reconcile must not fabricate a user-confirmed authority.
    events = _events(
        ReconciliationInput(
            source_id="s1",
            analysis=_analysis(
                utterances=[
                    Utterance(
                        utterance_text="hi",
                        speaker="Alice",
                        confidence=1.0,
                        segment=_seg(),
                        generated_by=_gb(),
                    )
                ]
            ),
        )
    )
    assert all(e["state"] != "USER_CONFIRMED" for e in events)
    assert all(e["authority"] == "machine" for e in events)


# ---------------------------------------------------------------------------
# observation mapping
# ---------------------------------------------------------------------------


def test_reconcile_maps_all_observation_categories() -> None:
    seg = _seg()
    analysis = _analysis(
        scene_boundaries=[
            SceneBoundary(
                scene_ref="scene:1",
                boundary="start",
                confidence=0.5,
                segment=seg,
                generated_by=_gb(),
            )
        ],
        entity_mentions=[
            EntityMention(
                mention="Alice",
                entity_type="character",
                confidence=0.3,
                segment=seg,
                generated_by=_gb(),
            )
        ],
        presence=[
            Presence(
                entity="Alice",
                present_in="scene:1",
                confidence=0.3,
                segment=seg,
                generated_by=_gb(),
            )
        ],
        utterances=[
            Utterance(
                utterance_text="hello",
                speaker="Alice",
                confidence=0.9,
                segment=seg,
                generated_by=_gb(),
            )
        ],
        traits=[
            DescriptiveTrait(
                entity="Alice", trait="brave", confidence=0.6, segment=seg, generated_by=_gb()
            )
        ],
        relationships=[
            RelationshipCandidate(
                subject_ref="Alice",
                predicate="CO_OCCURS",
                object_ref="Bob",
                confidence=0.2,
                segment=seg,
                generated_by=_gb(),
            )
        ],
        emotions=[
            EmotionObservation(
                entity="Alice", emotion="happy", confidence=0.55, segment=seg, generated_by=_gb()
            )
        ],
        states=[
            StateObservation(
                entity="Alice",
                observed_state="asleep",
                confidence=0.55,
                segment=seg,
                generated_by=_gb(),
            )
        ],
        context=[
            ContextObservation(
                context_type="location",
                value="forest",
                confidence=0.5,
                segment=seg,
                generated_by=_gb(),
            )
        ],
    )
    res = ResolutionBatch(
        source_id="s1",
        canonical_entities=[
            CanonicalEntity(
                ref="entity:canonical:s1:aaa",
                label="Alice",
                source_id="s1",
                confidence=0.9,
                state="CONFIRMED",
            )
        ],
    )
    events = _by_predicate(
        _events(ReconciliationInput(source_id="s1", analysis=analysis, resolution=res))
    )
    assert {
        "STARTS_AT",
        "MENTIONED_IN",
        "PRESENT_IN",
        "SPEAKS",
        "UTTERED_IN",
        "HAS_TRAIT",
        "CO_OCCURS",
        "HAS_EMOTION",
        "IN_STATE",
        "HAS_CONTEXT",
    } <= set(events)
    # Entity surface resolves to the deterministic canonical ref.
    assert events["MENTIONED_IN"][0]["subject_ref"] == "entity:canonical:s1:aaa"
    assert events["SPEAKS"][0]["subject_ref"] == "entity:canonical:s1:aaa"


def test_support_refs_are_source_evidence_distinct_from_interpretation() -> None:
    seg = _seg(evidence_ref="ev:9")
    analysis = _analysis(
        entity_mentions=[
            EntityMention(mention="Alice", confidence=0.6, segment=seg, generated_by=_gb())
        ]
    )
    events = _events(
        ReconciliationInput(
            source_id="s1",
            analysis=analysis,
            generated_by={
                "stage": "SEMANTIC_RECONCILIATION",
                "reconciler": "umd-semantic-reconciler@1",
            },
        )
    )
    mentioned = [e for e in events if e["predicate_code"] == "MENTIONED_IN"][0]
    # support_refs carry the exact source evidence ref, never machine output.
    assert mentioned["support_refs"] == ["ev:9"]
    # generated_by preserves the observation provenance (path + analyzer + config).
    gb = mentioned["generated_by"]
    assert gb["path"] == "deterministic"
    assert gb["config_digest"] == "cfg@1"
    # reconciliation provenance is merged in too.
    assert gb["reconciler"] == "umd-semantic-reconciler@1"
    assert gb["stage"] == "SEMANTIC_RECONCILIATION"


def test_weak_observations_stay_candidate_never_promoted() -> None:
    analysis = _analysis(
        entity_mentions=[
            EntityMention(mention="Ghost", confidence=0.3, segment=_seg(), generated_by=_gb())
        ]
    )
    events = [
        e
        for e in _events(ReconciliationInput(source_id="s1", analysis=analysis))
        if e["predicate_code"] == "MENTIONED_IN"
    ]
    assert events and all(e["state"] == "UNKNOWN" for e in events)


def test_ambiguous_observation_promotes_to_ambiguous() -> None:
    seg = _seg()
    analysis = _analysis(
        presence=[
            Presence(
                entity="Alice",
                present_in="scene:2",
                confidence=0.9,
                state=ConfidenceState.AMBIGUOUS,
                segment=seg,
                generated_by=_gb(),
            )
        ]
    )
    events = [
        e
        for e in _events(ReconciliationInput(source_id="s1", analysis=analysis))
        if e["predicate_code"] == "PRESENT_IN"
    ]
    assert events and all(e["state"] == "AMBIGUOUS" for e in events)


def test_resolution_contradiction_marks_assertions_conflicting() -> None:
    seg = _seg()
    analysis = _analysis(
        presence=[
            Presence(
                entity="Alice",
                present_in="scene:3",
                confidence=0.9,
                segment=seg,
                generated_by=_gb(),
            )
        ]
    )
    res = ResolutionBatch(
        source_id="s1",
        canonical_entities=[
            CanonicalEntity(
                ref="entity:canonical:s1:aaa",
                label="Alice",
                source_id="s1",
                confidence=0.9,
                state="CONFIRMED",
            )
        ],
        contradictions=[
            Contradiction(
                subject_ref="entity:canonical:s1:aaa", contradicting_ref="entity:canonical:s1:bbb"
            )
        ],
    )
    events = [
        e
        for e in _events(ReconciliationInput(source_id="s1", analysis=analysis, resolution=res))
        if e["predicate_code"] == "PRESENT_IN"
    ]
    assert events and all(e["state"] == "CONFLICTING" for e in events)


# ---------------------------------------------------------------------------
# identity / alias (resolution-driven)
# ---------------------------------------------------------------------------


def test_resolution_alias_emits_alias_of_and_known_as() -> None:
    res = ResolutionBatch(
        source_id="s1",
        canonical_entities=[
            CanonicalEntity(
                ref="entity:canonical:s1:aaa",
                label="Alice",
                source_id="s1",
                confidence=0.9,
                state="CONFIRMED",
            )
        ],
        alias_mappings=[
            AliasMapping(
                alias_ref="m:9",
                canonical_ref="entity:canonical:s1:aaa",
                alias_text="Ally",
                canonical_text="Alice",
                confidence=0.7,
            )
        ],
    )
    events = _events(ReconciliationInput(source_id="s1", analysis=_analysis(), resolution=res))
    by = _by_predicate(events)
    assert by["ALIAS_OF"][0]["subject_ref"] == "m:9"
    assert by["ALIAS_OF"][0]["object_ref"] == "entity:canonical:s1:aaa"
    assert by["KNOWN_AS"][0]["subject_ref"] == "entity:canonical:s1:aaa"
    assert by["KNOWN_AS"][0]["object_ref"] == "Ally"


def test_reconciliation_consumes_committed_batch_no_topology() -> None:
    """Plan T P1-S1/R1: SEMANTIC_RECONCILIATION consumes the COMMITTED result.

    ``ResolutionBatch.from_committed`` surfaces the accepted canonicals and aliases
    that ENTITY_RESOLUTION committed (from current_state) as a READ-ONLY batch with
    NO commands / assignments — no second resolution, no re-derivation. The
    reconciler maps observation surfaces to those committed refs and enriches
    observations only; it never establishes/aliases/merges/invents canonical
    identity, and unknown surfaces fall back to the honest deterministic ref.
    """
    committed = [
        (
            "entity:canonical:aaa",
            {
                "display_label": "Mara",
                "aliases": ["Ma"],
                "canonical_type": "CHARACTER",
                "state": "CONFIRMED",
                "confidence": 0.9,
                "classification": "accepted",
                "support_refs": ["m:1", "m:2"],
                "memberships": {"source_ids": ["A"], "work_ids": ["w"], "continuity_ids": []},
            },
        ),
        (
            "entity:canonical:bbb",
            {
                "display_label": "Ellis",
                "aliases": [],
                "canonical_type": "CHARACTER",
                "state": "PROBABLE",
                "confidence": 0.7,
                "classification": "probable",
                "support_refs": ["m:3"],
                "memberships": {"source_ids": ["A"], "work_ids": ["w"], "continuity_ids": []},
            },
        ),
    ]
    res = ResolutionBatch.from_committed(committed, source_id="A")
    # Read-only committed batch: no topology-changing commands/assignments.
    assert res.commands == []
    assert res.assignments == {}
    assert len(res.canonical_entities) == 2
    assert res.canonical_entities[0].ref == "entity:canonical:aaa"
    assert res.canonical_entities[0].classification == "accepted"
    assert res.canonical_entities[1].classification == "probable"
    assert res.canonical_entities[0].memberships["work_ids"] == ["w"]

    # A mention naming Mara maps to the COMMITTED ref (not a re-derived fallback).
    analysis = _analysis(
        entity_mentions=[
            EntityMention(
                mention="Mara",
                confidence=0.9,
                segment=_seg(),
                generated_by=_gb(),
            )
        ]
    )
    events = _events(ReconciliationInput(source_id="A", analysis=analysis, resolution=res))
    # The committed canonical ref surfaces in the emitted observations (the reconciler
    # enriches observations against the accepted identity — it does not re-derive or
    # invent a fresh ref for a surface it already maps).
    assert any(
        "entity:canonical:aaa" in str(e.get("subject_ref", ""))
        or "entity:canonical:aaa" in str(e.get("object_ref", ""))
        for e in events
    ), events


# ---------------------------------------------------------------------------
# safety + determinism
# ---------------------------------------------------------------------------


def test_unknown_relationship_predicate_is_never_invented() -> None:
    seg = _seg()
    analysis = _analysis(
        relationships=[
            RelationshipCandidate(
                subject_ref="Alice",
                predicate="QUX_LINK",
                object_ref="Bob",
                confidence=0.9,
                segment=seg,
                generated_by=_gb(),
            )
        ]
    )
    events = _events(ReconciliationInput(source_id="s1", analysis=analysis))
    assert all(e["predicate_code"] != "QUX_LINK" for e in events)


def test_reconcile_is_deterministic_and_dedups() -> None:
    seg = _seg()
    analysis = _analysis(
        entity_mentions=[
            EntityMention(mention="Alice", confidence=0.6, segment=seg, generated_by=_gb()),
            EntityMention(mention="Alice", confidence=0.6, segment=seg, generated_by=_gb()),
        ],
        presence=[
            Presence(
                entity="Alice",
                present_in="scene:1",
                confidence=0.3,
                segment=seg,
                generated_by=_gb(),
            ),
        ],
    )
    r = SemanticReconciler()
    a = [e.payload for e in r.reconcile(ReconciliationInput(source_id="s1", analysis=analysis))]
    b = [e.payload for e in r.reconcile(ReconciliationInput(source_id="s1", analysis=analysis))]
    assert a == b
    # duplicate mention collapsed to one MENTIONED_IN.
    assert len([e for e in a if e["predicate_code"] == "MENTIONED_IN"]) == 1


def test_unresolved_entity_uses_deterministic_fallback_ref() -> None:
    analysis = _analysis(
        presence=[
            Presence(
                entity="Nobody",
                present_in="scene:1",
                confidence=0.3,
                segment=_seg(),
                generated_by=_gb(),
            )
        ]
    )
    events = [
        e
        for e in _events(ReconciliationInput(source_id="s1", analysis=analysis))
        if e["predicate_code"] == "PRESENT_IN"
    ]
    assert events
    ref = events[0]["subject_ref"]
    assert ref.startswith("entity:s1:")
    # Same surface -> same fallback ref across runs (stable, no random uuid).
    again = [
        e
        for e in _events(ReconciliationInput(source_id="s1", analysis=analysis))
        if e["predicate_code"] == "PRESENT_IN"
    ]
    assert again[0]["subject_ref"] == ref


# ---------------------------------------------------------------------------
# P3-S1: full row-matrix provenance (identity..context) + promotion ladder
# ---------------------------------------------------------------------------


def _full_analysis() -> SemanticAnalysisResult:
    """One typed observation per reconciliation category (identity..context)."""
    seg = _seg()
    return _analysis(
        scene_boundaries=[
            SceneBoundary(
                scene_ref="scene:1",
                boundary="start",
                confidence=0.85,
                segment=seg,
                generated_by=_gb(),
            )
        ],
        aliases=[
            NormalizedAlias(
                canonical_name="Alice",
                alias="Ally",
                entity_ref="entity:canonical:s1:aaa",
                confidence=0.7,
                segment=seg,
                generated_by=_gb(),
            )
        ],
        entity_mentions=[
            EntityMention(
                mention="Alice",
                entity_type="character",
                confidence=0.6,
                segment=seg,
                generated_by=_gb(),
            )
        ],
        presence=[
            Presence(
                entity="Alice",
                present_in="scene:1",
                confidence=0.6,
                segment=seg,
                generated_by=_gb(),
            )
        ],
        utterances=[
            Utterance(
                utterance_text="hello",
                speaker="Alice",
                confidence=0.9,
                segment=seg,
                generated_by=_gb(),
            )
        ],
        traits=[
            DescriptiveTrait(
                entity="Alice", trait="brave", confidence=0.6, segment=seg, generated_by=_gb()
            )
        ],
        relationships=[
            RelationshipCandidate(
                subject_ref="Alice",
                predicate="CO_OCCURS",
                object_ref="Bob",
                confidence=0.55,
                segment=seg,
                generated_by=_gb(),
            )
        ],
        emotions=[
            EmotionObservation(
                entity="Alice", emotion="happy", confidence=0.55, segment=seg, generated_by=_gb()
            )
        ],
        states=[
            StateObservation(
                entity="Alice",
                observed_state="asleep",
                confidence=0.55,
                segment=seg,
                generated_by=_gb(),
            )
        ],
        context=[
            ContextObservation(
                context_type="location",
                value="forest",
                confidence=0.5,
                segment=seg,
                generated_by=_gb(),
            )
        ],
    )


def test_every_observation_row_carries_complete_provenance_matrix() -> None:
    """Identity/alias/presence/mention/speech/utterance/scene/trait/relationship/
    emotion/state/context rows each carry support refs, confidence, authority,
    generated-by, state, and scope (P3-S1)."""
    res = ResolutionBatch(
        source_id="s1",
        canonical_entities=[
            CanonicalEntity(
                ref="entity:canonical:s1:aaa",
                label="Alice",
                source_id="s1",
                confidence=0.9,
                state="CONFIRMED",
            )
        ],
    )
    events = _events(
        ReconciliationInput(
            source_id="s1",
            analysis=_full_analysis(),
            resolution=res,
            scope="SOURCE",
            generated_by={"stage": "SEMANTIC_RECONCILIATION", "reconciler": "r@1"},
        )
    )
    assert events, "expected reconciled assertions from the full matrix"

    expected_predicates = {
        "ALIAS_OF",
        "KNOWN_AS",
        "STARTS_AT",
        "MENTIONED_IN",
        "PRESENT_IN",
        "SPEAKS",
        "UTTERED_IN",
        "HAS_TRAIT",
        "CO_OCCURS",
        "HAS_EMOTION",
        "IN_STATE",
        "HAS_CONTEXT",
    }
    by = _by_predicate(events)
    assert expected_predicates <= set(by)

    for rows in by.values():
        for e in rows:
            assert e["authority"] == "machine"
            assert e["scope"] == "SOURCE"
            assert isinstance(e["confidence"], float) and 0.0 <= e["confidence"] <= 1.0
            assert e["state"] in {
                "CONFIRMED",
                "PROBABLE",
                "UNKNOWN",
                "AMBIGUOUS",
                "CONFLICTING",
            }
            # support_refs are the exact source evidence (never machine output).
            assert e["support_refs"] == ["ev:1"]
            # generated_by carries the observation provenance (path + analyzer +
            # config digest) merged with the reconciliation provenance.
            gb = e["generated_by"]
            assert gb["path"] == "deterministic"
            assert gb["config_digest"] == "cfg@1"
            assert gb["reconciler"] == "r@1"
            assert gb["stage"] == "SEMANTIC_RECONCILIATION"
            # source evidence is distinct from machine interpretation: support_refs
            # point at evidence, generated_by describes the producing path.
            assert all(s.startswith("ev:") for s in e["support_refs"])


def test_promotion_ladder_full_matrix_at_event_level() -> None:
    """P3-S1: strong -> CONFIRMED, medium -> PROBABLE, weak stays candidate/evidence,
    ambiguous/conflicting preserved — verified per category through the reconciler."""
    seg = _seg()

    def presence_with(confidence: float, state: ConfidenceState = ConfidenceState.PROBABLE) -> str:
        analysis = _analysis(
            presence=[
                Presence(
                    entity="Alice",
                    present_in="scene:1",
                    confidence=confidence,
                    state=state,
                    segment=seg,
                    generated_by=_gb(),
                )
            ]
        )
        rows = [
            e
            for e in _events(ReconciliationInput(source_id="s1", analysis=analysis))
            if e["predicate_code"] == "PRESENT_IN"
        ]
        assert rows
        return rows[0]["state"]

    assert presence_with(0.9) == "CONFIRMED"  # strong
    assert presence_with(0.6) == "PROBABLE"  # medium
    assert presence_with(0.3) == "UNKNOWN"  # weak stays candidate/evidence
    assert presence_with(0.9, ConfidenceState.AMBIGUOUS) == "AMBIGUOUS"
    assert presence_with(0.9, ConfidenceState.CONFLICTING) == "CONFLICTING"

    # Every category promotes deterministically (spot-check the non-presence rows).
    strong = _full_analysis()
    strong.scene_boundaries[0].confidence = 0.9
    strong.traits[0].confidence = 0.9
    strong.emotions[0].confidence = 0.9
    strong.states[0].confidence = 0.9
    events = _events(ReconciliationInput(source_id="s1", analysis=strong))
    for pred in ("STARTS_AT", "HAS_TRAIT", "HAS_EMOTION", "IN_STATE"):
        rows = [e for e in events if e["predicate_code"] == pred]
        assert rows and all(e["state"] == "CONFIRMED" for e in rows)

    # Machine reconcile never fabricates a user-confirmed authority.
    assert all(e["state"] != "USER_CONFIRMED" for e in events)
