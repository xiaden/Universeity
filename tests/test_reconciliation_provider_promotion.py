"""Plan R P2 — provider observation reconciliation promotion (spec-first).

Phase 1 added the ``_reconciliation_input`` seam to
``umd.jobs.production`` that unions the deterministic baseline with the
already-validated, committed ``semantic_observations`` evidence the provider-aware
STRUCTURAL_ANALYSIS recorded. These tests drive the REAL production seam (never a
mock of the seam under test) over the 'The Lantern Keeper' book fixture and the
real :class:`~umd.reconciliation.reconciler.SemanticReconciler`, proving the
promotion rules in Plan R P2:

* P2-S1 — provider aliases / traits / scene boundaries / presence / utterances +
  speaker / supported relationships become the existing SemanticReconciler events;
  unsupported relationship predicates and unresolved/ambiguous surfaces stay
  evidence-only and are never fabricated into events.
* P2-S2 — every provider-derived event retains exact segment support refs,
  confidence, state and provider ``generated_by`` metadata, with the
  reconciliation-stage metadata MERGED (not replacing) observation provenance;
  deterministic observations remain in the same event stream.
* P2-S3 — the deterministic+provider union loses nothing and duplicates nothing.
* P2-S4 — malformed / unknown-category / unsupported-predicate / missing-model /
  unregistered-provider / invalid-support / invalid-confidence / invalid-state /
  stale-evidence inputs degrade to the deterministic baseline with warnings and
  never promote rejected model output.
* P2-S5 — repeated reconciliation of the same committed evidence converges to one
  deterministic event set; provider invocation count does not increase during
  reconciliation; the seam itself writes no projection/table rows.
* P2-S6 — correction/invalidation/lock/USER_OVERRIDE authority and immutable
  history hold over provider-derived machine events.

Every test drives the production seam through real committed OCFL bytes and the
real evidence-commit path — no provider is re-invoked except via the single
structural-analysis invocation.
"""

from __future__ import annotations

import io
import uuid
from typing import Any

import pytest
import sqlalchemy as sa

from fixtures import BOOK_TITLE, semantic_book_bytes
from umd.application.commands import SemanticCommandService
from umd.config import SemanticSettings, Settings
from umd.domain.evidence import EvidenceBatch
from umd.domain.models import Evidence, EvidenceKind
from umd.jobs.stage_execution import StageManifest
from umd.models.provider import (
    ModelMode,
    ModelProvider,
    ModelRequest,
    StructuredModelResult,
)
from umd.models.registry import ProviderRegistry
from umd.reconciliation.reconciler import SemanticReconciler
from umd.storage.ocfl import SourceDescriptor
from umd.storage.postgres.ledger import SemanticLedger
from umd.storage.postgres.repositories import SourceMembershipService

pytestmark = pytest.mark.postgres

_STRUCTURAL = "STRUCTURAL_ANALYSIS"
_RECONCILIATION = "SEMANTIC_RECONCILIATION"

#: A paragraph locator that deterministically exists in the Lantern Keeper txt
#: dispatch (chapter/1 carries an extra heading paragraph -> paragraph/1 exists).
_VALID_LOCATOR = "chapter/1/section/1/paragraph/1"
#: A locator that is never part of the Lantern Keeper input (stale support).
_STALE_LOCATOR = "chapter/9/section/9/paragraph/99"


def _manifest(sid: str, stage: str, job: str | None = None) -> StageManifest:
    return StageManifest(
        job_id=job or f"r2-{stage.lower()}-{uuid.uuid4().hex[:8]}",
        stage_name=stage,
        source_id=sid,
        dag_universe="v1-dag:base",
        evidence_refs=[],
        input_manifest={"source_id": sid},
    )


def _provider_gb() -> dict[str, Any]:
    """A valid provider ``GeneratedBy`` serialization for crafted observations."""
    return {
        "path": "provider",
        "analyzer": "umd-text-structural@2",
        "provider": "lantern_semantic",
        "model": "lantern-qwen",
        "model_version": "2.0.0",
        "prompt_version": "semantic-v1",
        "config_digest": "provider-test@1",
    }


class _LanternProvider:
    """A model provider emitting the FULL validated observation range anchored to
    the exact input segment locators (so every candidate passes exact support).

    Emits the FULL validated observation range anchored to the exact input
    segment locators (so every candidate passes exact support): supported
    speaker/relationship events that become SemanticReconciler events, an
    ambiguous entity surface that must never be fabricated into a canonical
    assertion, and unsupported relationship predicates that stay evidence-only.
    ``SIBLING_OF`` is now registered in the controlled vocabulary (Plan S P4-S1),
    so this provider's SIBLING_OF Mara->Ellis relationship is materialized as a
    real semantic event rather than remaining evidence-only.
    """

    name = "lantern_semantic"

    def __init__(self, entity_locators: dict[str, str] | None = None) -> None:
        self._entity_locators = entity_locators or {}
        self.calls: list[ModelRequest] = []

    def _loc(self, entity: str, fallback: str) -> str:
        return self._entity_locators.get(entity) or fallback

    def invoke(self, request: ModelRequest) -> StructuredModelResult:
        self.calls.append(request)
        refs = list(request.input_refs or [])
        loc_a = refs[0] if refs else _VALID_LOCATOR
        loc_b = refs[-1] if refs else loc_a
        loc_c = refs[len(refs) // 2] if len(refs) > 1 else loc_a

        def seg(locator: str) -> dict[str, str]:
            return {"locator": locator}

        presence_a = self._loc("Mara", loc_a)
        presence_b = self._loc("Ellis", loc_a)
        presence_c = self._loc("Orin", loc_b)
        output: dict[str, Any] = {
            "entities": [
                {
                    "mention": "Mara",
                    "entity_type": "character",
                    "confidence": 0.92,
                    "segment": seg(loc_a),
                },
                {
                    "mention": "Ellis",
                    "entity_type": "character",
                    "confidence": 0.91,
                    "segment": seg(loc_a),
                },
                {
                    "mention": "Orin",
                    "entity_type": "character",
                    "confidence": 0.90,
                    "segment": seg(loc_b),
                },
                {
                    "mention": "??",
                    "entity_type": "character",
                    "confidence": 0.55,
                    "state": "AMBIGUOUS",
                    "segment": seg(loc_c),
                },
            ],
            "aliases": [
                {
                    "canonical_name": "Mara",
                    "alias": "Moss",
                    "confidence": 0.9,
                    "segment": seg(loc_a),
                },
                {
                    "canonical_name": "Mara",
                    "alias": "the apprentice",
                    "confidence": 0.85,
                    "segment": seg(loc_a),
                },
                {
                    "canonical_name": "Ellis",
                    "alias": "the cartographer",
                    "confidence": 0.9,
                    "segment": seg(loc_a),
                },
                {
                    "canonical_name": "Orin",
                    "alias": "the warden",
                    "confidence": 0.9,
                    "segment": seg(loc_b),
                },
            ],
            "traits": [
                {
                    "entity": "Mara",
                    "trait": "moss-green eyes",
                    "confidence": 0.9,
                    "segment": seg(loc_a),
                },
                {"entity": "Orin", "trait": "grey beard", "confidence": 0.9, "segment": seg(loc_b)},
            ],
            "presence": [
                {
                    "entity": "Mara",
                    "present_in": presence_a,
                    "confidence": 0.8,
                    "segment": seg(presence_a),
                },
                {
                    "entity": "Ellis",
                    "present_in": presence_b,
                    "confidence": 0.8,
                    "segment": seg(presence_b),
                },
                {
                    "entity": "Orin",
                    "present_in": presence_c,
                    "confidence": 0.8,
                    "segment": seg(presence_c),
                },
                {"entity": "Mara", "present_in": loc_c, "confidence": 0.7, "segment": seg(loc_c)},
            ],
            "scenes": [
                {
                    "scene_ref": "scene:lantern-1",
                    "boundary": "start",
                    "confidence": 0.85,
                    "segment": seg(loc_a),
                },
            ],
            "utterances": [
                {
                    "utterance_text": "The flame keeps slipping.",
                    "speaker": "Mara",
                    "confidence": 0.9,
                    "segment": seg(loc_c),
                },
            ],
            "speakers": [
                {
                    "speaker_label": "Mara",
                    "utterance_ref": "utter:lantern-1",
                    "confidence": 0.85,
                    "segment": seg(loc_c),
                },
            ],
            "relationships": [
                {
                    "subject_ref": "Mara",
                    "predicate": "CO_OCCURS",
                    "object_ref": "Ellis",
                    "confidence": 0.7,
                    "segment": seg(loc_a),
                },
                {
                    "subject_ref": "Mara",
                    "predicate": "SIBLING_OF",
                    "object_ref": "Ellis",
                    "confidence": 0.7,
                    "segment": seg(loc_a),
                },
            ],
            "emotions": [
                {"entity": "Mara", "emotion": "resolute", "confidence": 0.6, "segment": seg(loc_a)},
            ],
            "states": [
                {
                    "entity": "Mara",
                    "observed_state": "kneeling",
                    "confidence": 0.6,
                    "segment": seg(loc_a),
                },
            ],
            "context": [
                {
                    "context_type": "location",
                    "value": "the village edge",
                    "confidence": 0.6,
                    "segment": seg(loc_a),
                },
            ],
        }
        return StructuredModelResult(
            mode=ModelMode.COMPLETION,
            model=request.model,
            model_version="2.0.0",
            provider=self.name,
            prompt_version=request.prompt_version,
            output=output,
            confidence=0.9,
            input_refs=request.input_refs,
            stage=request.stage,
        )


def _commit_source(umd_db: sa.Engine, source_store: Any) -> str:
    memberships = SourceMembershipService(umd_db)
    work_id = uuid.uuid4().hex
    memberships.ensure_work(work_id=work_id, title=BOOK_TITLE, work_type="book")
    man = source_store.put_immutable(
        io.BytesIO(semantic_book_bytes("txt")),
        SourceDescriptor(logical_name="lantern.txt"),
    )
    sid = uuid.uuid4().hex
    memberships.ensure_source(
        source_id=sid,
        ocfl_ref=man.object_id,
        sha512=man.sha512,
        size_bytes=man.size_bytes,
        media_kind="text",
        original_name="lantern.txt",
        work_id=work_id,
    )
    return sid


def _build_composer(
    umd_db: sa.Engine,
    source_store: Any,
    *,
    provider: ModelProvider | None,
    provider_name: str | None,
    model: str | None,
) -> Any:
    from umd.jobs import production

    settings = (
        Settings(semantic=SemanticSettings(provider=provider_name, model=model))
        if provider_name
        else None
    )
    registry = ProviderRegistry([provider]) if provider is not None else None
    ledger = SemanticLedger(umd_db)
    runtime = production.ProductionRuntime(
        engine=umd_db,
        settings=settings,
        source_store=source_store,
        providers=registry,
        commands=SemanticCommandService(ledger),
        ledger=ledger,
    )
    return production._Composer(umd_db, runtime)  # noqa: SLF001 - registry-internal, test-only


class _Seam:
    """A committed Lantern Keeper source + a composer wired to the real runtime."""

    def __init__(self, composer: Any, sid: str, provider: ModelProvider | None) -> None:
        self.composer = composer
        self.sid = sid
        self.provider = provider


def _seam(
    umd_db: sa.Engine,
    source_store: Any,
    *,
    provider: ModelProvider | None = None,
    provider_name: str | None = None,
    model: str | None = None,
    sid: str | None = None,
    run_structural: bool = True,
) -> _Seam:
    sid = sid or _commit_source(umd_db, source_store)
    composer = _build_composer(
        umd_db, source_store, provider=provider, provider_name=provider_name, model=model
    )
    seam = _Seam(composer, sid, provider)
    if run_structural:
        _structural(seam)
    return seam


def _structural(seam: _Seam) -> Any:
    return seam.composer._structural_analysis(_manifest(seam.sid, _STRUCTURAL))  # noqa: SLF001


def _recon_input(seam: _Seam) -> Any:
    src = seam.composer._require_source(_manifest(seam.sid, _RECONCILIATION))  # noqa: SLF001
    return seam.composer._reconciliation_input(src)  # noqa: SLF001


def _recon_events(seam: _Seam) -> list[dict[str, Any]]:
    inp = _recon_input(seam)
    assert inp is not None, "reconciliation input is None (dispatch/segments failed)"
    return [e.payload for e in SemanticReconciler().reconcile(inp)]


def _events_by_predicate(events: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for p in events:
        out.setdefault(str(p["predicate_code"]), []).append(p)
    return out


def _fetch(engine: sa.Engine, sql: str, **params: Any) -> list[sa.Row]:
    with engine.connect() as c:
        return c.execute(sa.text(sql), params).fetchall()


def _count(engine: sa.Engine, sql: str, **params: Any) -> int:
    rows = _fetch(engine, sql, **params)
    return int(rows[0][0]) if rows else 0


def _event_keys(events: list[dict[str, Any]]) -> set[tuple[str, str, str | None]]:
    return {(str(p["predicate_code"]), str(p["subject_ref"]), p["object_ref"]) for p in events}


def _materialize(seam: _Seam) -> Any:
    return seam.composer._semantic_reconciliation(_manifest(seam.sid, _RECONCILIATION))  # noqa: SLF001


# ---------------------------------------------------------------------------
# P2-S1 — provider observations promote to the existing reconciler events;
# unsupported predicates / unresolved surfaces stay evidence-only.
# ---------------------------------------------------------------------------


def test_p2s1_provider_categories_promote_to_reconciler_events(
    umd_db: sa.Engine, source_store: Any
) -> None:
    provider = _LanternProvider()
    seam = _seam(
        umd_db, source_store, provider=provider, provider_name=provider.name, model="lantern-qwen"
    )
    assert provider.calls, "provider was not invoked by the real structural-analysis seam"
    events = _recon_events(seam)
    by_pred = _events_by_predicate(events)
    preds = set(by_pred)

    # Provider aliases -> ALIAS_OF / KNOWN_AS (deterministic leaves aliases absent).
    known = {p["object_ref"] for p in by_pred.get("KNOWN_AS", [])}
    assert "Moss" in known, "provider alias 'Moss' did not become a KNOWN_AS event"
    assert "ALIAS_OF" in preds

    # Provider traits -> HAS_TRAIT (deterministic leaves traits absent).
    traits = {p["object_ref"] for p in by_pred.get("HAS_TRAIT", [])}
    assert "moss-green eyes" in traits and "grey beard" in traits

    # Provider scene boundary -> STARTS_AT with the provider scene ref (subject).
    starts = {p["subject_ref"] for p in by_pred.get("STARTS_AT", [])}
    assert "scene:lantern-1" in starts, "provider scene boundary did not become a STARTS_AT event"

    # Provider presence -> PRESENT_IN.
    assert "PRESENT_IN" in preds

    # Provider utterance + speaker -> SPEAKS / UTTERED_IN.
    assert "SPEAKS" in preds and "UTTERED_IN" in preds

    # Provider emotions / states / context -> their reconciler events.
    assert "HAS_EMOTION" in preds and "IN_STATE" in preds and "HAS_CONTEXT" in preds

    # Supported relationship predicates -> the predicate is emitted directly.
    # Plan S Phase 4 (P4-S1): SIBLING_OF is now a registered controlled-vocabulary
    # relationship, so the provider's Mara->Ellis sibling observation is promoted.
    assert "CO_OCCURS" in preds, "supported relationship predicate must emit an event"
    assert "SIBLING_OF" in preds, "registered SIBLING_OF predicate must emit an event"

    # No fabricated predicate: every emitted predicate is a known reconciler output.
    known_predicates = {
        "ALIAS_OF",
        "KNOWN_AS",
        "STARTS_AT",
        "MENTIONED_IN",
        "PRESENT_IN",
        "SPEAKS",
        "UTTERED_IN",
        "HAS_TRAIT",
        "CO_OCCURS",
        "SIBLING_OF",
        "HAS_EMOTION",
        "IN_STATE",
        "HAS_CONTEXT",
    }
    assert preds <= known_predicates, f"unknown predicates fabricated: {preds - known_predicates}"


def test_p2s1_unsupported_and_ambiguous_stay_evidence_only_never_fabricated(
    umd_db: sa.Engine, source_store: Any
) -> None:
    provider = _LanternProvider()
    seam = _seam(
        umd_db, source_store, provider=provider, provider_name=provider.name, model="lantern-qwen"
    )
    events = _recon_events(seam)
    by_pred = _events_by_predicate(events)

    # SIBLING_OF is a registered controlled-vocabulary predicate (Plan S P4-S1), so
    # the provider's sibling observation is now a valid reconciler event. The
    # "unsupported stays evidence-only" guarantee is exercised with genuinely
    # unregistered/malformed predicates in test_p2s4_unsupported_predicate_evidence...
    # and in the Phase-4 sibling tests below.
    assert "SIBLING_OF" in by_pred, "registered SIBLING_OF must now be emitted"

    # Speaker candidates produce no standalone predicate (SPEAKS/UTTERED_IN only
    # ever come from typed utterance observations, never from a bare speaker label).
    assert not any(p["predicate_code"] in {"SPEAKER_OF", "SPEAKER_CANDIDATE"} for p in events)

    # The ambiguous entity surface ("??") never fabricates a canonical identity:
    # it yields at most a deterministic fallback mention ref, never a guessed
    # canonical entity or a made-up relationship. Its fallback ref is the stable
    # reconciler deterministic ref, not a fabricated UUID/human-readable ref.
    for p in events:
        if p["predicate_code"] == "MENTIONED_IN" and p["generated_by"].get("provider"):
            assert not str(p["subject_ref"]).startswith("urn:") or "canonical" in str(
                p["subject_ref"]
            )


# ---------------------------------------------------------------------------
# P2-S2 — provider-derived events retain support refs, confidence, state and
# provider provenance; reconciliation metadata MERGED not replaced.
# ---------------------------------------------------------------------------


def test_p2s2_provider_events_retain_support_confidence_state_and_provenance(
    umd_db: sa.Engine, source_store: Any
) -> None:
    model = "lantern-qwen"
    provider = _LanternProvider()
    seam = _seam(umd_db, source_store, provider=provider, provider_name=provider.name, model=model)
    events = _recon_events(seam)

    # Identify the provider-derived trait (deterministic leaves traits absent, so
    # HAS_TRAIT for "moss-green eyes" is guaranteed to originate from the provider).
    trait = next(
        p
        for p in events
        if p["predicate_code"] == "HAS_TRAIT" and p["object_ref"] == "moss-green eyes"
    )

    # Exact segment/evidence support ref: provider observations carry no evidence_ref,
    # so the reconciler emits the exact segment locator (never a fabricated ref).
    assert trait["support_refs"], "provider-derived event lost its support refs"
    assert all(str(r).startswith("chapter/") for r in trait["support_refs"]), trait["support_refs"]

    # Confidence / semantic state retained from the provider observation (0.9 with
    # a PROBABLE observation state -> promoted to CONFIRMED).
    assert trait["confidence"] == 0.9
    assert trait["state"] == "CONFIRMED"

    # Reconciliation-stage metadata MERGED, not replaced: the event keeps BOTH the
    # reconciliation stage identity AND the provider observation provenance.
    gb = trait["generated_by"]
    assert gb["stage"] == "SEMANTIC_RECONCILIATION"  # reconciliation metadata retained
    assert gb.get("reconciler") == "umd-semantic-reconciler@1"
    assert gb.get("provider") == provider.name  # observation provenance retained
    assert gb.get("model") == model
    assert gb.get("model_version") == "2.0.0"
    assert gb.get("config_digest"), "provider config_digest must be carried through"

    # Every provider-provenance event carries provider metadata.
    provider_events = [p for p in events if p["generated_by"].get("provider")]
    assert provider_events, "expected provider-derived events in the stream"
    for p in provider_events:
        gb = p["generated_by"]
        assert gb.get("model") == model
        assert gb.get("stage") == "SEMANTIC_RECONCILIATION"
        assert 0.0 < float(p["confidence"]) <= 1.0
        # Semantic state is RETAINED from the provider observation: it may be
        # CONFIRMED/PROBABLE, or AMBIGUOUS/CONFLICTING when the observation
        # explicitly carries an ambiguous/conflicting state or the subject is
        # part of a contradiction set. It must always be a valid ConfidenceState.
        assert p["state"] in {"CONFIRMED", "PROBABLE", "UNKNOWN", "AMBIGUOUS", "CONFLICTING"}
        assert p["support_refs"], "provider-derived event lost support refs"

    # Deterministic observations remain present in the SAME stream: at least the
    # deterministic scene/1 STARTS_AT carries no provider provenance.
    det = [p for p in events if not p["generated_by"].get("provider")]
    assert det, "deterministic observations vanished from the union stream"
    det_scene = [
        p for p in det if p["predicate_code"] == "STARTS_AT" and p["subject_ref"] == "scene/1"
    ]
    assert det_scene, "deterministic scene/1 boundary was dropped from the stream"


# ---------------------------------------------------------------------------
# P2-S3 — deterministic+provider union has no loss and no duplication.
# ---------------------------------------------------------------------------


def test_p2s3_provider_union_no_loss_no_dup(umd_db: sa.Engine, source_store: Any) -> None:
    sid = _commit_source(umd_db, source_store)

    # Baseline-only: deterministic analyzer over the SAME source (no provider).
    base_seam = _seam(umd_db, source_store, provider=None, provider_name=None, model=None, sid=sid)
    base_events = _recon_events(base_seam)
    base_keys = _event_keys(base_events)

    # Provider-enabled over the SAME source id (so canonical refs are comparable).
    provider = _LanternProvider()
    prov_seam = _seam(
        umd_db,
        source_store,
        provider=provider,
        provider_name=provider.name,
        model="lantern-qwen",
        sid=sid,
    )
    prov_events = _recon_events(prov_seam)
    prov_keys = _event_keys(prov_events)

    # NO LOSS: every deterministic event survives the union. Canonical/entity
    # refs differ between the two runs because the provider adds entity/alias
    # mentions that change resolution clustering, so exact (pred, subj, obj) keys
    # are not comparable. Instead compare event CONTENT by (predicate, object_ref)
    # for every object-stable predicate (object is a locator/utterance-ref/alias
    # that is resolution-independent). CO_OCCURS's object is an entity ref that
    # differs with resolution, so it is compared by count only.
    def stable_pairs(keys: set[tuple[str, str, str]]) -> set[tuple[str, str]]:
        return {(p, o) for (p, _s, o) in keys if p != "CO_OCCURS"}

    base_pairs = stable_pairs(base_keys)
    prov_pairs = stable_pairs(prov_keys)
    missing = base_pairs - prov_pairs
    assert not missing, f"provider union lost deterministic event content: {missing}"

    # Resolution-dependent predicate CO_OCCURS: no deterministic co-occurrence
    # event was dropped (provider union has at least as many).
    base_co = sum(1 for (p, _s, _o) in base_keys if p == "CO_OCCURS")
    prov_co = sum(1 for (p, _s, _o) in prov_keys if p == "CO_OCCURS")
    assert prov_co >= base_co, "provider union dropped deterministic CO_OCCURS events"

    # No duplication: within the provider-enabled run every event key is unique
    # (reconciler dedups by predicate/subject/object).
    assert len(prov_keys) == len(prov_events), "provider union duplicated an event key"

    # Provider is additive: the union has strictly more distinct events.
    assert len(prov_keys) > len(base_keys), "provider observations added nothing to the union"

    # Provider-only categories were added (aliases/traits/emotions/states/context
    # are left ABSENT by the deterministic baseline).
    prov_preds = {p["predicate_code"] for p in prov_events}
    for extra in ("ALIAS_OF", "KNOWN_AS", "HAS_TRAIT", "HAS_EMOTION", "IN_STATE", "HAS_CONTEXT"):
        assert extra in prov_preds, f"provider-only category {extra} missing from union"


def test_p2s3_deterministic_unsupported_categories_unchanged_without_provider(
    umd_db: sa.Engine, source_store: Any
) -> None:
    seam = _seam(umd_db, source_store, provider=None, provider_name=None, model=None)
    events = _recon_events(seam)
    by_pred = _events_by_predicate(events)
    # The deterministic baseline leaves aliases/traits/emotions/states/context ABSENT.
    for absent in ("ALIAS_OF", "KNOWN_AS", "HAS_TRAIT", "HAS_EMOTION", "IN_STATE", "HAS_CONTEXT"):
        assert absent not in by_pred, f"deterministic baseline unexpectedly emitted {absent}"
    # Deterministic structural baseline still emits its chapter scene boundaries.
    starts = {p["subject_ref"] for p in by_pred.get("STARTS_AT", [])}
    assert {"scene/1", "scene/2"} <= starts, starts


# ---------------------------------------------------------------------------
# P2-S4 — rejected/degraded provider inputs never become semantic assertions.
# ---------------------------------------------------------------------------


def _record_observations(seam: _Seam, observations: list[dict[str, Any]]) -> None:
    ev = Evidence(
        source_id=seam.sid,
        evidence_kind=EvidenceKind.TEXT_SPAN,
        locator=f"semantic_analysis:{seam.sid}:test",
        extraction_stage="STRUCTURAL_ANALYSIS",
        tool_versions={"provider": "lantern_semantic", "model": "lantern-qwen"},
        config_digest="provider-test@1",
        confidence=0.9,
        quality={"kind": "semantic_observations", "observations": observations},
    )
    seam.composer._evidence.record(EvidenceBatch(records=[ev]))  # noqa: SLF001


def test_p2s4_rejected_observations_degrade_to_baseline_with_warnings(
    umd_db: sa.Engine, source_store: Any
) -> None:
    # Commit the source WITHOUT running structural analysis; craft a committed
    # semantic_observations evidence row with only rejected/malformed payloads.
    provider = _LanternProvider()
    seam = _seam(
        umd_db,
        source_store,
        provider=provider,
        provider_name=provider.name,
        model="lantern-qwen",
        run_structural=False,
    )
    gb = _provider_gb()
    bad = [
        # malformed: missing required 'entity'
        {"trait": "invented-trait", "generated_by": gb},
        # unknown category: no dispatch key present
        {"fabricated_kind": "fabricated", "entity": "Mara", "generated_by": gb},
        # invalid/stale support: locator not in the analyzed input (valid confidence)
        {
            "trait": "stale-trait",
            "entity": "Mara",
            "confidence": 0.9,
            "segment": {"locator": _STALE_LOCATOR},
            "generated_by": gb,
        },
        # invalid confidence: out of [0,1]
        {
            "trait": "conf-trait",
            "entity": "Mara",
            "confidence": 1.5,
            "segment": {"locator": _VALID_LOCATOR},
            "generated_by": gb,
        },
        # invalid semantic state (valid confidence, isolated failure)
        {
            "trait": "state-trait",
            "entity": "Mara",
            "confidence": 0.9,
            "state": "BOGUS",
            "segment": {"locator": _VALID_LOCATOR},
            "generated_by": gb,
        },
    ]
    _record_observations(seam, bad)

    inp = _recon_input(seam)
    warnings = "\n".join(inp.analysis.warnings)
    for marker in (
        "unknown or ambiguous category",
        "lacks exact input-segment support",
        "malformed",
    ):
        assert marker in warnings, f"expected rejection warning {marker!r}; got: {warnings}"

    events = [e.payload for e in SemanticReconciler().reconcile(inp)]
    by_pred = _events_by_predicate(events)
    traits = {p["object_ref"] for p in by_pred.get("HAS_TRAIT", [])}
    for rejected in ("invented-trait", "stale-trait", "conf-trait", "state-trait"):
        assert rejected not in traits, (
            f"rejected observation {rejected!r} was promoted to an assertion"
        )


def test_p2s4_unsupported_predicate_evidence_stays_evidence_only(
    umd_db: sa.Engine, source_store: Any
) -> None:
    provider = _LanternProvider()
    seam = _seam(
        umd_db,
        source_store,
        provider=provider,
        provider_name=provider.name,
        model="lantern-qwen",
        run_structural=False,
    )
    gb = _provider_gb()
    # Plan S Phase 4 (P4-S1) lockstep: SIBLING_OF is now a registered controlled
    # vocabulary predicate, so it is no longer the "unsupported" example. The
    # malformed/arbitrary-model-predicate rejection MUST remain strict, so this
    # test now proves that a well-formed-but-unregistered predicate AND a malformed
    # arbitrary string stay evidence-only at reconciliation (never fabricated).
    _record_observations(
        seam,
        [
            # Well-formed but NOT in the controlled vocabulary -> rejected.
            {
                "subject_ref": "Mara",
                "predicate": "TRANSMUTATION_OF",
                "object_ref": "Ellis",
                "segment": {"locator": _VALID_LOCATOR},
                "generated_by": gb,
            },
            # Malformed arbitrary model predicate (hyphen) -> rejected.
            {
                "subject_ref": "Mara",
                "predicate": "sibling-of",
                "object_ref": "Ellis",
                "segment": {"locator": _VALID_LOCATOR},
                "generated_by": gb,
            },
        ],
    )
    events = _recon_events(seam)
    preds = {p["predicate_code"] for p in events}
    assert "TRANSMUTATION_OF" not in preds, (
        "unregistered predicate must stay evidence-only, never an assertion"
    )
    assert "SIBLING-OF" not in preds, "malformed arbitrary predicate must stay evidence-only"


def test_p2s4_missing_model_degrades_with_honest_warning(
    umd_db: sa.Engine, source_store: Any
) -> None:
    provider = _LanternProvider()
    seam = _seam(
        umd_db,
        source_store,
        provider=provider,
        provider_name=provider.name,
        model=None,  # provider configured but no model -> honest gate
    )
    outcome = _structural(seam)
    assert any("no model" in w for w in outcome.warnings), outcome.warnings
    assert provider.calls == [], "provider must not be invoked when model is None"

    inp = _recon_input(seam)
    assert any("no committed semantic-observation evidence" in w for w in inp.analysis.warnings)
    events = [e.payload for e in SemanticReconciler().reconcile(inp)]
    assert not any(p["generated_by"].get("provider") for p in events), (
        "missing-model must not promote provider events"
    )


def test_p2s4_unregistered_provider_degrades_with_honest_warning(
    umd_db: sa.Engine, source_store: Any
) -> None:
    provider = _LanternProvider()
    seam = _seam(
        umd_db,
        source_store,
        provider=provider,
        provider_name="ghost",  # not registered under this name
        model="lantern-qwen",
    )
    outcome = _structural(seam)
    assert any(
        w in " ".join(outcome.warnings) for w in ("unavailable", "unsupported", "disabled")
    ), outcome.warnings
    assert provider.calls == [], "unregistered provider must not be invoked"

    inp = _recon_input(seam)
    assert any("no committed semantic-observation evidence" in w for w in inp.analysis.warnings)
    events = [e.payload for e in SemanticReconciler().reconcile(inp)]
    assert not any(p["generated_by"].get("provider") for p in events)


# ---------------------------------------------------------------------------
# P2-S5 — repeated reconciliation converges; provider not re-invoked; the seam
# writes no projection/table rows.
# ---------------------------------------------------------------------------


def test_p2s5_reconciliation_is_idempotent_and_never_reinvokes_provider(
    umd_db: sa.Engine, source_store: Any
) -> None:
    provider = _LanternProvider()
    seam = _seam(
        umd_db, source_store, provider=provider, provider_name=provider.name, model="lantern-qwen"
    )
    assert len(provider.calls) == 1, "structural analysis must invoke the provider exactly once"

    # Pure seam: deterministic + hydrated provider events, computed twice.
    events_1 = _recon_events(seam)
    events_2 = _recon_events(seam)
    assert _event_keys(events_1) == _event_keys(events_2)
    assert len(events_1) == len(events_2)
    # Recomputing the input + reconciling writes nothing to projection/authority.
    assert _count(umd_db, "SELECT count(*) FROM current_state") == 0
    assert _count(umd_db, "SELECT count(*) FROM semantic_assertion") == 0
    assert _count(umd_db, "SELECT count(*) FROM search_document") == 0

    # Provider is NEVER re-invoked by the reconciliation seam.
    assert len(provider.calls) == 1

    # Command-path materialization is idempotent: two reconciliation runs commit
    # the same distinct fact set (no duplication, no erasure).
    n = len(events_1)
    first = _materialize(seam)
    assert first.metrics["assertion_count"] == n
    assert _count(umd_db, "SELECT count(*) FROM semantic_assertion") == n
    assert _count(umd_db, "SELECT count(*) FROM current_state") > 0
    second = _materialize(seam)
    assert second.metrics["assertion_count"] == n
    assert _count(umd_db, "SELECT count(*) FROM semantic_assertion") == n, (
        "rerun duplicated assertions"
    )
    # Provider invocation count did not increase during reconciliation.
    assert len(provider.calls) == 1


# ---------------------------------------------------------------------------
# P2-S6 — user authority and immutable history hold over provider-derived events.
# ---------------------------------------------------------------------------


def test_p2s6_user_override_wins_over_provider_machine_and_survives_rerun(
    umd_db: sa.Engine, source_store: Any
) -> None:
    provider = _LanternProvider()
    seam = _seam(
        umd_db, source_store, provider=provider, provider_name=provider.name, model="lantern-qwen"
    )
    _materialize(seam)
    events = _recon_events(seam)

    trait = next(
        p
        for p in events
        if p["predicate_code"] == "HAS_TRAIT" and p["generated_by"].get("provider")
    )
    subj, obj = trait["subject_ref"], trait["object_ref"]

    # The provider-derived machine assertion is materialized as authority=machine.
    _cs_sql = (
        "SELECT object_ref, authority FROM current_state "
        "WHERE entity_ref=:s AND predicate='HAS_TRAIT'"
    )
    rows = _fetch(umd_db, _cs_sql, s=subj)
    assert rows, "provider-derived machine assertion was not materialized"
    assert rows[0][0] == obj and rows[0][1] == "machine"

    _ev_sql = (
        "SELECT count(*) FROM semantic_event WHERE payload->>'subject_ref'=:s "
        "AND payload->>'predicate_code'='HAS_TRAIT'"
    )
    history_before = _count(umd_db, _ev_sql, s=subj)

    # User correction overrides the machine fact.
    svc = SemanticCommandService(SemanticLedger(umd_db))
    svc.record_override(
        subject_ref=subj,
        predicate="HAS_TRAIT",
        object_ref="user-corrected-trait",
        confidence=1.0,
        actor="human",
        reason="correction",
    )

    # Machine rerun cannot downgrade the override.
    _materialize(seam)
    _cs_sql = (
        "SELECT object_ref, authority FROM current_state "
        "WHERE entity_ref=:s AND predicate='HAS_TRAIT'"
    )
    rows = _fetch(umd_db, _cs_sql, s=subj)
    assert rows[0][0] == "user-corrected-trait" and rows[0][1] == "USER_OVERRIDE"

    # Immutable history retained: the machine event is still present (not erased),
    # and the override appended more history.
    history_after = _count(umd_db, _ev_sql, s=subj)
    assert history_after > history_before, "immutable ledger history was lost or not appended"
    assert history_before >= 1, "machine assertion event missing from history"


def test_p2s6_lock_blocks_provider_machine_and_selective_rerun_preserves_unrelated(
    umd_db: sa.Engine, source_store: Any
) -> None:
    provider = _LanternProvider()
    seam = _seam(
        umd_db, source_store, provider=provider, provider_name=provider.name, model="lantern-qwen"
    )
    events = _recon_events(seam)

    emotion = next(
        p
        for p in events
        if p["predicate_code"] == "HAS_EMOTION" and p["generated_by"].get("provider")
    )
    locked_subj = emotion["subject_ref"]

    # Lock the entity BEFORE materialization: machine events for it are blocked.
    svc = SemanticCommandService(SemanticLedger(umd_db))
    svc.lock(entity_ref=locked_subj, actor="human", reason="reviewing")

    _materialize(seam)

    # Lock blocks machine materialization for the locked entity. The lock
    # itself writes a `*LOCK*` marker row into current_state, so count only
    # non-lock machine assertion rows for the locked entity.
    locked_rows = _fetch(
        umd_db,
        "SELECT count(*) FROM current_state WHERE entity_ref=:s AND predicate <> '*LOCK*'",
        s=locked_subj,
    )
    assert locked_rows[0][0] == 0, "machine must not materialize current_state for a locked entity"

    # Unrelated provider-derived facts materialize normally.
    total_first = _count(umd_db, "SELECT count(*) FROM semantic_assertion")
    assert total_first > 0, "unrelated provider-derived facts were not materialized"

    # Selective rerun neither duplicates nor erases unrelated assertions.
    _materialize(seam)
    total_second = _count(umd_db, "SELECT count(*) FROM semantic_assertion")
    assert total_second == total_first, "selective rerun duplicated or erased unrelated assertions"
    locked_rows = _fetch(
        umd_db,
        "SELECT count(*) FROM current_state WHERE entity_ref=:s AND predicate <> '*LOCK*'",
        s=locked_subj,
    )
    assert locked_rows[0][0] == 0, "lock released after a rerun"


# ---------------------------------------------------------------------------
# P3-S2: replay rebuild exposes provider-derived assertions through the
# reducer-owned scalar ``current_state`` and the replay-only
# ``active_semantic_edge`` with ORIGINAL confidence / semantic state /
# authority / scope / support refs / fact identity / ledger seq / provider
# provenance; wipe/replay and rerun produce identical active results.
# ---------------------------------------------------------------------------


def _active_edge_snapshot(umd_db: sa.Engine) -> list[tuple[Any, ...]]:
    import json

    rows = _fetch(
        umd_db,
        "SELECT fact_id, predicate, subject_ref, object_ref, confidence, state, authority, "
        "scope, ledger_seq FROM active_semantic_edge WHERE active ORDER BY fact_id",
    )

    def norm(x: Any) -> Any:
        if isinstance(x, (list, dict)):
            return json.dumps(x, sort_keys=True)
        return str(x) if not isinstance(x, (int, float)) else x

    return [tuple(norm(c) for c in r) for r in rows]


def test_p3s2_replay_exposes_provider_assertions_with_full_provenance(
    umd_db: sa.Engine, source_store: Any
) -> None:
    from umd.projections.base import ReplayDriver
    from umd.projections.checkpoint import ProjectionCheckpointStore
    from umd.projections.current import CurrentTierOneBuilder
    from umd.projections.edges import ActiveSemanticEdgeProjectionBuilder

    provider = _LanternProvider()
    seam = _seam(
        umd_db, source_store, provider=provider, provider_name=provider.name, model="lantern-qwen"
    )
    events = _recon_events(seam)
    trait = next(
        p
        for p in events
        if p["predicate_code"] == "HAS_TRAIT" and p["object_ref"] == "moss-green eyes"
    )
    subj = trait["subject_ref"]
    orig_conf = trait["confidence"]
    orig_state = trait["state"]

    # Command path materializes the provider assertions into the ledger.
    _materialize(seam)
    assert _count(umd_db, "SELECT count(*) FROM semantic_assertion") > 0

    # --- reducer-owned scalar current_state (wipe-and-replay) -----------------
    pstore = ProjectionCheckpointStore(umd_db)
    ReplayDriver(umd_db, pstore).run(CurrentTierOneBuilder(), wipe=True)
    cs = _fetch(
        umd_db,
        "SELECT entity_ref, predicate, object_ref, confidence, authority, state, seq "
        "FROM current_state WHERE entity_ref=:s AND predicate='HAS_TRAIT'",
        s=subj,
    )
    assert cs, "provider HAS_TRAIT missing from replayed current_state"
    row = cs[0]
    assert str(row[1]) == "HAS_TRAIT"
    assert str(row[2]) == "moss-green eyes"
    assert float(row[3]) == orig_conf, "original confidence lost in current_state replay"
    assert str(row[4]) == "machine", "original authority lost in current_state replay"
    assert str(row[5]) == orig_state, "original semantic state lost in current_state replay"
    assert int(row[6]) > 0, "seq not set by current_state replay"

    # --- replay-only active_semantic_edge with full provenance ----------------
    ReplayDriver(umd_db, pstore).run(ActiveSemanticEdgeProjectionBuilder(), wipe=True)
    edges = _fetch(
        umd_db,
        "SELECT fact_id, predicate, subject_ref, object_ref, confidence, state, authority, "
        "scope, support_refs, ledger_seq, derivation FROM active_semantic_edge "
        "WHERE subject_ref=:s AND predicate='HAS_TRAIT' AND active",
        s=subj,
    )
    assert edges, "provider HAS_TRAIT missing from replayed active_semantic_edge"
    e = edges[0]
    assert str(e[2]) == subj and str(e[3]) == "moss-green eyes"
    assert float(e[4]) == orig_conf, "original confidence lost in edge replay"
    assert str(e[5]) == orig_state, "original semantic state lost in edge replay"
    assert str(e[6]) == "machine", "original authority lost in edge replay"
    assert e[7] in ("SOURCE", "GLOBAL"), f"scope lost in edge replay: {e[7]}"
    support = list(e[8] or [])
    assert support, "support refs lost in edge replay"
    assert all(str(r).startswith("chapter/") for r in support), support
    assert int(e[9]) > 0, "ledger_seq not set by edge replay"
    der = e[10] or {}
    gb = der.get("generated_by") or {}
    assert gb.get("provider") == provider.name
    assert gb.get("model") == "lantern-qwen"
    assert gb.get("model_version") == "2.0.0"
    assert gb.get("stage") == "SEMANTIC_RECONCILIATION"

    # fact identity is the real content-addressable semantic_assertion id.
    assert_id = _fetch(
        umd_db,
        "SELECT id FROM semantic_assertion WHERE predicate_code='HAS_TRAIT' "
        "AND subject_ref=:s AND object_ref='moss-green eyes'",
        s=subj,
    )
    assert assert_id, "assertion id not found in semantic_assertion mirror"
    assert str(e[0]) == str(assert_id[0][0]), "edge fact_id != semantic_assertion id"

    # --- wipe/replay and rerun produce identical active results ----------------
    snap1 = _active_edge_snapshot(umd_db)
    ReplayDriver(umd_db, pstore).run(ActiveSemanticEdgeProjectionBuilder(), wipe=True)
    snap2 = _active_edge_snapshot(umd_db)
    assert snap1 and snap2, "active edge snapshot empty"
    assert snap1 == snap2, "wipe/replay changed the active edge result set"

    # Replay must never re-invoke the provider.
    assert len(provider.calls) == 1, "replay must never re-invoke the provider"
