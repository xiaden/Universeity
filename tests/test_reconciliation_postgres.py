"""Materialization + promotion tests for reconciled assertions (Plan O P1-S3/S4).

Spec-first postgres tests for:

  * every ``SemanticAsserted`` event appended through the command path is
    materialized into ``semantic_assertion`` in the SAME transaction as the
    event append (P1-S3), with the full subject/object refs, authority,
    confidence, state, support_refs, contradiction_refs, schema_ref and
    provenance in ``derivation``;
  * the FK-safe ``predicate`` row is auto-seeded from the registered vocabulary
    (data, not a migration);
  * materialization is idempotent — a rerun of the same fact yields ONE row
    (deterministic content-addressable id + on-conflict update), the latest
    assertion for a fact updates that row, and distinct facts get distinct rows;
  * P1-S4 — a machine reconciliation never overwrites a user override and never
    mutates a locked entity (the shared reducer's USER_OVERRIDE/lock semantics
    win; they are not weakened here).
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa

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
from umd.application.commands import SemanticCommandService
from umd.reconciliation.reconciler import ReconciliationInput, SemanticReconciler
from umd.resolution.service import CanonicalEntity, ResolutionBatch
from umd.storage.postgres.ledger import SemanticLedger

pytestmark = pytest.mark.postgres


def _svc(umd_db: sa.Engine) -> tuple[SemanticLedger, SemanticCommandService]:
    ledger = SemanticLedger(umd_db)
    return ledger, SemanticCommandService(ledger)


def _fetch(umd_db: sa.Engine, sql: str) -> list:
    with umd_db.connect() as c:
        return c.execute(sa.text(sql)).fetchall()


# ---------------------------------------------------------------------------
# P1-S3 materialization
# ---------------------------------------------------------------------------


def test_assert_semantic_materializes_full_row(umd_db: sa.Engine) -> None:
    _, svc = _svc(umd_db)
    svc.assert_semantic(
        predicate_code="SPEAKS",
        subject_ref="e:1",
        object_ref="utter:1",
        confidence=0.7,
        state="CONFIRMED",
        scope="CONTINUITY",
        support_refs=["ev:1"],
        contradiction_refs=["ev:2"],
        derived_from=["ev:0"],
        generated_by={"path": "deterministic", "config_digest": "cfg@1"},
    )
    rows = _fetch(umd_db, "SELECT * FROM semantic_assertion")
    assert len(rows) == 1
    r = rows[0]
    assert r.predicate_code == "SPEAKS"
    assert r.subject_ref == "e:1"
    assert r.object_ref == "utter:1"
    assert r.authority == "machine"
    assert r.confidence == 0.7
    assert r.state == "CONFIRMED"
    assert r.support_refs == ["ev:1"]
    assert r.contradiction_refs == ["ev:2"]
    assert r.schema_ref.endswith("v2.json")
    assert r.derivation["generated_by"] == {"path": "deterministic", "config_digest": "cfg@1"}
    assert r.derivation["scope"] == "CONTINUITY"
    assert r.derivation["derived_from"] == ["ev:0"]
    assert r.derivation["source_seq"] == 1
    # FK-safe predicate row auto-seeded (data, not a migration).
    preds = _fetch(umd_db, "SELECT code FROM predicate")
    assert ("SPEAKS",) in preds


def test_materialization_is_idempotent_on_rerun(umd_db: sa.Engine) -> None:
    _, svc = _svc(umd_db)

    def assert_once() -> None:
        svc.assert_semantic(
            predicate_code="SPEAKS",
            subject_ref="e:1",
            object_ref="utter:1",
            confidence=0.7,
            state="CONFIRMED",
            scope="CONTINUITY",
            support_refs=["ev:1"],
        )

    assert_once()
    assert_once()  # rerun asserts the same semantic fact
    n_assert = _fetch(umd_db, "SELECT count(*) FROM semantic_assertion")[0][0]
    n_event = _fetch(umd_db, "SELECT count(*) FROM semantic_event")[0][0]
    # Both events are in the append-only ledger, but the fact materializes ONCE.
    assert n_assert == 1
    assert n_event == 2


def test_latest_assertion_updates_the_fact_row(umd_db: sa.Engine) -> None:
    _, svc = _svc(umd_db)
    for state, conf in (("PROBABLE", 0.6), ("CONFIRMED", 0.9)):
        svc.assert_semantic(
            predicate_code="SPEAKS",
            subject_ref="e:1",
            object_ref="utter:1",
            confidence=conf,
            state=state,
            scope="CONTINUITY",
            support_refs=["ev:1"],
        )
    rows = _fetch(umd_db, "SELECT state, confidence, derivation FROM semantic_assertion")
    assert len(rows) == 1
    # The row reflects the LATEST assertion for the same semantic fact.
    assert rows[0].state == "CONFIRMED"
    assert rows[0].confidence == 0.9
    assert rows[0].derivation["source_seq"] == 2


def test_distinct_facts_get_distinct_rows(umd_db: sa.Engine) -> None:
    _, svc = _svc(umd_db)
    svc.assert_semantic(
        predicate_code="SPEAKS",
        subject_ref="e:1",
        object_ref="utter:1",
        confidence=0.7,
        state="CONFIRMED",
        scope="CONTINUITY",
        support_refs=["ev:1"],
    )
    svc.assert_semantic(
        predicate_code="PRESENT_IN",
        subject_ref="e:1",
        object_ref="scene:1",
        confidence=0.5,
        state="PROBABLE",
        scope="SOURCE",
        support_refs=["ev:2"],
    )
    rows = _fetch(umd_db, "SELECT predicate_code, subject_ref, object_ref FROM semantic_assertion")
    assert len(rows) == 2
    assert {r.predicate_code for r in rows} == {"SPEAKS", "PRESENT_IN"}


def test_reconciliation_predicate_vocabulary_is_registered(umd_db: sa.Engine) -> None:
    """P1-S1: the reconciled vocabulary predicates materialize FK-safely."""
    _, svc = _svc(umd_db)
    codes = [
        "MENTIONED_IN",
        "UTTERED_IN",
        "HAS_TRAIT",
        "CO_OCCURS",
        "HAS_EMOTION",
        "IN_STATE",
        "HAS_CONTEXT",
        "STARTS_AT",
    ]
    for i, code in enumerate(codes):
        svc.assert_semantic(
            predicate_code=code,
            subject_ref=f"e:{i}",
            object_ref=f"o:{i}",
            confidence=0.5,
            state="PROBABLE",
            scope="SOURCE",
            support_refs=[f"ev:{i}"],
        )
    preds = _fetch(umd_db, "SELECT code FROM predicate")
    assert all((c,) in preds for c in codes)


# ---------------------------------------------------------------------------
# P1-S4 promotion precedence — user/locked always win (reducer unchanged)
# ---------------------------------------------------------------------------


def test_user_override_wins_over_machine_reconcile(umd_db: sa.Engine) -> None:
    _, svc = _svc(umd_db)
    # Machine reconciliation asserts one value.
    svc.assert_semantic(
        predicate_code="SPEAKS",
        subject_ref="e:1",
        object_ref="utter:machine",
        confidence=0.9,
        state="CONFIRMED",
        scope="CONTINUITY",
        support_refs=["ev:1"],
    )
    # A later human override must always win over a machine rerun.
    svc.record_override(
        subject_ref="e:1",
        predicate="SPEAKS",
        object_ref="utter:human",
        confidence=1.0,
        actor="human",
        reason="correction",
    )
    row = _fetch(
        umd_db,
        "SELECT object_ref, authority, state FROM current_state "
        "WHERE entity_ref='e:1' AND predicate='SPEAKS'",
    )[0]
    assert row.object_ref == "utter:human"
    assert row.authority == "USER_OVERRIDE"


def test_lock_blocks_machine_reconcile(umd_db: sa.Engine) -> None:
    _, svc = _svc(umd_db)
    svc.lock(entity_ref="e:1", actor="human", reason="reviewing")
    # Machine reconciliation must NOT mutate a locked entity.
    svc.assert_semantic(
        predicate_code="SPEAKS",
        subject_ref="e:1",
        object_ref="utter:machine",
        confidence=0.9,
        state="CONFIRMED",
        scope="CONTINUITY",
        support_refs=["ev:1"],
    )
    rows = _fetch(
        umd_db,
        "SELECT count(*) FROM current_state WHERE entity_ref='e:1' AND predicate='SPEAKS'",
    )
    assert rows[0][0] == 0, "machine assertion must not write a locked entity"


# ---------------------------------------------------------------------------
# P3-S1: reconciler path through the ledger materializes the full typed matrix
# ---------------------------------------------------------------------------


def _gb() -> GeneratedBy:
    return GeneratedBy(path="deterministic", config_digest="cfg@1")


def _seg() -> SegmentEvidenceRef:
    return SegmentEvidenceRef(locator="source://s/1", evidence_ref="ev:1")


def _full_analysis() -> SemanticAnalysisResult:
    seg = _seg()
    return SemanticAnalysisResult(
        source_id="s1",
        generated_by=_gb(),
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
            EntityMention(mention="Alice", confidence=0.6, segment=seg, generated_by=_gb())
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


def _append_reconciled(umd_db: sa.Engine, **input_kw: object) -> list[str]:
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
    events = SemanticReconciler().reconcile(
        ReconciliationInput(source_id="s1", analysis=_full_analysis(), resolution=res, **input_kw)
    )
    SemanticLedger(umd_db).append(events)
    rows = _fetch(
        umd_db,
        "SELECT predicate_code, support_refs, confidence, authority, state, "
        "derivation->>'scope' AS scope, derivation "
        "FROM semantic_assertion",
    )
    return [str(r.predicate_code) for r in rows], rows


def test_reconciler_events_materialize_full_typed_row_matrix(umd_db: sa.Engine) -> None:
    """P3-S1: every reconciler category materializes a typed ``semantic_assertion``
    row in the same transaction, carrying support refs, confidence, authority,
    state, scope and provenance in ``derivation``."""
    preds, rows = _append_reconciled(umd_db)
    assert {
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
    } <= set(preds)

    for r in rows:
        assert r.authority == "machine"
        assert r.support_refs == ["ev:1"]  # source evidence, distinct from interpretation
        assert 0.0 <= r.confidence <= 1.0
        assert r.state in {"CONFIRMED", "PROBABLE", "UNKNOWN", "AMBIGUOUS", "CONFLICTING"}
        assert r.scope == "SOURCE"
        gb = r.derivation["generated_by"]
        assert gb["path"] == "deterministic"
        assert gb["config_digest"] == "cfg@1"
        assert r.derivation["scope"] == "SOURCE"


def test_reconciler_promotion_ladder_materialized(umd_db: sa.Engine) -> None:
    """P3-S1: the deterministic promotion ladder is reflected in the materialized
    semantic_assertion rows (strong->CONFIRMED, medium->PROBABLE, weak->UNKNOWN,
    ambiguous/conflicting preserved)."""

    def state_for(confidence: float, obs_state: ConfidenceState = ConfidenceState.PROBABLE) -> str:
        res = ResolutionBatch(source_id="s1")
        seg = _seg()
        analysis = SemanticAnalysisResult(
            source_id="s1",
            generated_by=_gb(),
            presence=[
                Presence(
                    entity="Alice",
                    present_in="scene:1",
                    confidence=confidence,
                    state=obs_state,
                    segment=seg,
                    generated_by=_gb(),
                )
            ],
        )
        events = SemanticReconciler().reconcile(
            ReconciliationInput(source_id="s1", analysis=analysis, resolution=res)
        )
        SemanticLedger(umd_db).append(events)
        row = _fetch(
            umd_db,
            "SELECT state FROM semantic_assertion "
            "WHERE predicate_code='PRESENT_IN' ORDER BY id DESC LIMIT 1",
        )[0]
        return str(row.state)

    assert state_for(0.9) == "CONFIRMED"
    assert state_for(0.6) == "PROBABLE"
    assert state_for(0.3) == "UNKNOWN"  # weak stays candidate/evidence
    assert state_for(0.9, ConfidenceState.AMBIGUOUS) == "AMBIGUOUS"
    assert state_for(0.9, ConfidenceState.CONFLICTING) == "CONFLICTING"


def test_reconciler_machine_never_overwrites_user_override_or_lock(umd_db: sa.Engine) -> None:
    """P3-S1: user-confirmed and locked values always win over a later machine
    reconcile at the scalar current_state level (reducer semantics unchanged)."""
    _, svc = _svc(umd_db)
    svc.record_override(
        subject_ref="e:1",
        predicate="SPEAKS",
        object_ref="utter:human",
        confidence=1.0,
        actor="human",
        reason="correction",
    )
    # A machine reconcile of the same fact must not flip the winner.
    svc.assert_semantic(
        predicate_code="SPEAKS",
        subject_ref="e:1",
        object_ref="utter:machine",
        confidence=0.95,
        state="CONFIRMED",
        scope="CONTINUITY",
        support_refs=["ev:1"],
    )
    row = _fetch(
        umd_db,
        "SELECT object_ref, authority FROM current_state "
        "WHERE entity_ref='e:1' AND predicate='SPEAKS'",
    )[0]
    assert row.object_ref == "utter:human"
    assert row.authority == "USER_OVERRIDE"


# ---------------------------------------------------------------------------
# P4-S3: materialization mirror precedence (semantic_assertion)
# ---------------------------------------------------------------------------


def test_materialization_preserves_user_override_row_on_machine_reassert(
    umd_db: sa.Engine,
) -> None:
    """P4-S3: a machine reassertion must NOT downgrade a USER_OVERRIDE mirror row.

    The ``semantic_assertion`` mirror materializes the same deterministic fact identity
    (content-addressable ``fact_id``) regardless of authority. After a USER_OVERRIDE
    mirror row exists, a later machine assertion of the SAME fact must leave the mirror
    authority at USER_OVERRIDE (previously the authority-agnostic LWW overwrote it back
    to ``machine``, diverging from the reduced winner).
    """
    _, svc = _svc(umd_db)
    # Establish a USER_OVERRIDE mirror row for the fact (predicate/subject/object/scope).
    svc.assert_semantic(
        predicate_code="SPEAKS",
        subject_ref="e:1",
        object_ref="utter:human",
        confidence=1.0,
        state="CONFIRMED",
        scope="CONTINUITY",
        authority="USER_OVERRIDE",
    )
    # A later machine reassertion of the SAME fact must not downgrade the mirror.
    svc.assert_semantic(
        predicate_code="SPEAKS",
        subject_ref="e:1",
        object_ref="utter:human",
        confidence=0.95,
        state="CONFIRMED",
        scope="CONTINUITY",
        authority="machine",
    )
    rows = _fetch(
        umd_db,
        "SELECT authority FROM semantic_assertion "
        "WHERE subject_ref='e:1' AND predicate_code='SPEAKS'",
    )
    assert len(rows) == 1, "one mirror row per deterministic fact identity"
    assert rows[0].authority == "USER_OVERRIDE"


def test_materialization_skips_locked_entity_machine_assert(umd_db: sa.Engine) -> None:
    """P4-S3: a machine assertion on a locked entity never materializes to the mirror.

    The reducer already skips folding a machine assertion for a locked entity (no
    ``current_state`` row); the mirror must not diverge by writing a row for it.
    """
    _, svc = _svc(umd_db)
    svc.lock(entity_ref="e:1", actor="human", reason="reviewing")
    svc.assert_semantic(
        predicate_code="SPEAKS",
        subject_ref="e:1",
        object_ref="utter:machine",
        confidence=0.95,
        state="CONFIRMED",
        scope="CONTINUITY",
    )
    rows = _fetch(
        umd_db,
        "SELECT count(*) FROM semantic_assertion "
        "WHERE subject_ref='e:1' AND predicate_code='SPEAKS'",
    )
    assert rows[0][0] == 0, "locked-entity machine assertion must not write the mirror"
