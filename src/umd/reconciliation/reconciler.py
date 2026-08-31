"""Deterministic semantic reconciler (Plan O P1-S2).

Implements the binding contract ``SemanticReconciler.reconcile(input) ->
list[SemanticEvent]`` (CONTRACTS.md:78):

    rich typed semantic assertions through the ledger — identity/alias, mention,
    presence, utterance/speech, trait, relationship, emotion/state/context and
    scene-structure assertions — each carrying exact support refs (source
    evidence, distinct from machine interpretation), confidence, authority,
    state, scope, contradiction refs, and ``generated_by`` provenance.

The reconciler is a *pure, deterministic, testable* function: it writes nothing
and touches no database. Given the same typed observations
(:class:`~umd.analysis.semantic.SemanticAnalysisResult`) and resolved
entity/mention mappings (:class:`~umd.resolution.service.ResolutionBatch`) it
always produces the identical ordered list of :class:`SemanticEvent` ledger
commands (idempotent rerun convergence). Weak facts remain candidate/evidence
(never promoted); unsupported facts are omitted entirely. The caller routes
every returned event through ``SemanticCommandService.assert_semantic`` — the
reconciler never appends.

Deterministic promotion (P1-S4)
-------------------------------
Strong observations (``confidence >= 0.8``) -> ``CONFIRMED``; medium (``>= 0.5``)
-> ``PROBABLE``; weak (``< 0.5``) stay candidate/evidence (``UNKNOWN``, never
promoted); observations whose own semantic state is ``AMBIGUOUS``/``CONFLICTING``,
or that resolve to a contradicting canonical, -> ``AMBIGUOUS``/``CONFLICTING``.
User-confirmed and locked values are never weakened here: the reconciler emits
only ``machine``-authority events and the shared reducer's USER_OVERRIDE/lock
semantics win (``reducer.py`` is unchanged).
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from umd.analysis.semantic import ConfidenceState, GeneratedBy, SemanticAnalysisResult
from umd.domain.events import EventType, SemanticEvent
from umd.domain.models import is_known_predicate
from umd.resolution.service import ResolutionBatch

#: Reconciliation binding config digest (provenance).
RECONCILER_DIGEST = "umd-semantic-reconciliation@1"


class ReconciliationInput(BaseModel):
    """The typed ``input`` to :meth:`SemanticReconciler.reconcile`.

    ``analysis`` carries the validated typed observations; ``resolution`` the
    deterministic resolved entity/mention mappings (may be absent when no
    candidates were resolved). ``generated_by`` supplies the reconciliation
    provenance merged onto every assertion; ``scope``/``authority`` seed the
    assertion defaults.
    """

    source_id: str = Field(min_length=1)
    analysis: SemanticAnalysisResult
    resolution: ResolutionBatch | None = None
    generated_by: dict[str, Any] = Field(default_factory=dict)
    authority: str = "machine"
    scope: str = "SOURCE"
    config_digest: str = RECONCILER_DIGEST


@dataclass
class _Emit:
    """One pending assertion (predicate + refs + provenance) before state/de-dup."""

    predicate: str
    subject_ref: str
    object_ref: str | None
    confidence: float
    obs_state: ConfidenceState
    support_refs: list[str]
    obs_generated_by: GeneratedBy | None
    contradiction_refs: list[str] = field(default_factory=list)
    relationship_type: str | None = None


_REL_TYPE_RE = re.compile(r"[A-Z][A-Z0-9_]{0,63}")

#: Recognized semantic relationship types that are NOT registered predicates but are
#: valid to promote to a typed ``RELATED_TO`` (Plan T P2-S4 / R7). The DD names a
#: valid unanticipated ``MENTOR_OF``; arbitrary well-formed but unknown predicates
#: (e.g. ``QUX_LINK``) are NOT in this set and stay evidence-only — the trusted
#: vocabulary is never invented by input.
_SEMANTIC_RELATIONSHIP_TYPES = frozenset({"MENTOR_OF"})


def _normalize_relationship_type(value: str | None) -> str | None:
    """Validate + normalize a relationship type (Plan T P2-S4 / R7).

    Strips, upper-cases and enforces the same syntax gate as predicate codes. An
    empty / malformed value returns ``None`` so the caller can treat it as
    type-invalid (evidence-only, never an assertion).
    """
    if value is None:
        return None
    norm = value.strip().upper()
    if not norm or _REL_TYPE_RE.fullmatch(norm) is None:
        return None
    return norm


def _relationship_target(rel: Any) -> tuple[str, str | None] | None:
    """Resolve a relationship observation's predicate + validated relationship type.

    Plan T (P2-S4 / R7) — the generic relationship fallback that keeps the trusted
    predicate vocabulary immutable:

    * ``RELATED_TO`` with a valid normalized ``relationship_type`` -> emit as
      ``RELATED_TO`` carrying that type.
    * a registered predicate (e.g. the Lantern Keeper ``SIBLING_OF``) -> emit as
      itself, its own predicate preserved (no relationship_type).
    * a valid unanticipated relationship predicate (e.g. ``MENTOR_OF``) -> emit as
      a typed ``RELATED_TO`` preserving the semantic predicate as its
      ``relationship_type``.
    * malformed sibling-of (a registered sibling carrying a conflicting type),
      unregistered / type-invalid input -> ``None`` (evidence-only, never an
      assertion).
    """
    predicate = (rel.predicate or "").strip().upper()
    rt = _normalize_relationship_type(getattr(rel, "relationship_type", None))
    if predicate == "RELATED_TO":
        # generic typed relationship: a validated relationship_type is REQUIRED
        return ("RELATED_TO", rt) if rt is not None else None
    if predicate == "SIBLING_OF":
        # registered sibling stays its own predicate. A sibling-of that attempts to
        # subtype itself (a conflicting relationship_type) is malformed -> evidence.
        if rt is not None and rt != "SIBLING_OF":
            return None
        if is_known_predicate("SIBLING_OF"):
            return ("SIBLING_OF", None)
        return None  # unregistered sibling-of -> evidence-only
    if is_known_predicate(predicate):
        # any other registered predicate (e.g. HAS_EMOTION) -> as-is, no type
        return (predicate, None)
    # An unregistered but recognized semantic relationship type (e.g. MENTOR_OF)
    # becomes a typed RELATED_TO preserving the semantic predicate. An explicit
    # valid relationship_type wins; otherwise the recognized predicate is the type.
    if rt is not None:
        return ("RELATED_TO", rt)
    if predicate in _SEMANTIC_RELATIONSHIP_TYPES:
        return ("RELATED_TO", predicate)
    return None  # unregistered / type-invalid -> evidence-only


def _promote(confidence: float, obs_state: ConfidenceState) -> str:
    """Deterministic promotion (P1-S4).

    Strong -> CONFIRMED, medium -> PROBABLE, weak -> UNKNOWN (candidate/evidence,
    never promoted). An observation already carrying AMBIGUOUS/CONFLICTING keeps
    that state. Machine reconcile never emits USER_CONFIRMED.
    """
    if obs_state == ConfidenceState.AMBIGUOUS:
        return ConfidenceState.AMBIGUOUS.value
    if obs_state == ConfidenceState.CONFLICTING:
        return ConfidenceState.CONFLICTING.value
    if confidence >= 0.8:
        return ConfidenceState.CONFIRMED.value
    if confidence >= 0.5:
        return ConfidenceState.PROBABLE.value
    return ConfidenceState.UNKNOWN.value


def _deterministic_ref(source_id: str, kind: str, value: str) -> str:
    """Deterministic candidate ref for an unresolved surface/utterance.

    Stable across reruns so weak observations always reference the same ref and
    the ledger materialization dedups (never a random uuid).
    """
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]
    return f"{kind}:{source_id}:{digest}"


def _support_refs(segment: Any) -> list[str]:
    """Exact source evidence refs for an observation (never machine output)."""
    if getattr(segment, "evidence_ref", None):
        return [str(segment.evidence_ref)]
    return [str(segment.locator)]


def _provenance(input_gb: dict[str, Any], obs_gb: GeneratedBy | None) -> dict[str, Any]:
    """Merge reconciliation provenance with the observation's provenance.

    The observation's deterministic/provider path metadata (path, analyzer,
    provider, model, config digest) is preserved so no assertion loses how it
    was derived (source evidence stays distinct from machine interpretation).
    The observation's own ``config_digest`` wins over the reconciliation default;
    the reconciliation digest is only a fallback when the observation carries
    none.
    """
    out: dict[str, Any] = dict(input_gb)
    if obs_gb is not None:
        out.setdefault("path", obs_gb.path.value)
        for key in ("analyzer", "provider", "model", "model_version", "prompt_version"):
            value = getattr(obs_gb, key, None)
            if value is not None:
                out.setdefault(key, value)
        if obs_gb.config_digest:
            out["config_digest"] = obs_gb.config_digest
    out.setdefault("config_digest", RECONCILER_DIGEST)
    return out


class SemanticReconciler:
    """Pure mapper from typed observations + resolved mappings to assertions.

    ``reconcile`` is deterministic and self-contained per call (the resolution
    maps are rebuilt on every invocation), so the same ``input`` always yields
    the same ordered events.
    """

    def __init__(self) -> None:
        self._surface_to_ref: dict[str, str] = {}
        self._conflicted: set[str] = set()
        self._source_id: str = ""

    def reconcile(self, input: ReconciliationInput) -> list[SemanticEvent]:
        """Map ``input`` into an ordered, de-duplicated list of assertions.

        Pure and deterministic: the same ``input`` always yields the same events.
        """
        self._surface_to_ref = self._build_surface_map(input)
        self._conflicted = self._build_conflicted(input)
        self._source_id = input.source_id

        pending: list[_Emit] = []
        pending.extend(self._emit_resolution(input))
        pending.extend(self._emit_observations(input))

        seen: set[tuple[str, str, str | None]] = set()
        events: list[SemanticEvent] = []
        for e in pending:
            state = self._state_for(e)
            key = (e.predicate, e.subject_ref, e.object_ref)
            if key in seen:
                continue
            seen.add(key)
            events.append(
                SemanticEvent(
                    event_type=EventType.SEMANTIC_ASSERTED,
                    payload={
                        "predicate_code": e.predicate,
                        "subject_ref": e.subject_ref,
                        "object_ref": e.object_ref,
                        "authority": input.authority,
                        "confidence": e.confidence,
                        "state": state,
                        "scope": input.scope,
                        "support_refs": list(e.support_refs),
                        "contradiction_refs": list(e.contradiction_refs),
                        "derived_from": [],
                        "relationship_type": e.relationship_type,
                        "generated_by": _provenance(input.generated_by, e.obs_generated_by),
                    },
                    authority=input.authority,
                    confidence=e.confidence,
                    generated_by=_provenance(input.generated_by, e.obs_generated_by),
                )
            )
        return events

    # -- entity/mention reference resolution -------------------------------

    @staticmethod
    def _build_surface_map(input: ReconciliationInput) -> dict[str, str]:
        """Map surface labels/aliases to deterministic canonical refs."""
        surface_to_ref: dict[str, str] = {}
        resolution = input.resolution
        if resolution is None:
            return surface_to_ref
        for ce in resolution.canonical_entities:
            if ce.label:
                surface_to_ref.setdefault(ce.label, ce.ref)
        for am in resolution.alias_mappings:
            if am.alias_text:
                surface_to_ref.setdefault(am.alias_text, am.canonical_ref)
        return surface_to_ref

    @staticmethod
    def _build_conflicted(input: ReconciliationInput) -> set[str]:
        """Canonical refs surfaced as identity contradictions."""
        resolution = input.resolution
        if resolution is None:
            return set()
        conflicted: set[str] = set()
        for c in resolution.contradictions:
            conflicted.add(c.subject_ref)
            conflicted.add(c.contradicting_ref)
        return conflicted

    def _resolve(self, surface: str | None) -> str | None:
        """Resolve a surface form to a canonical ref (or a deterministic fallback)."""
        if not surface:
            return None
        hit = self._surface_to_ref.get(surface)
        if hit:
            return hit
        return _deterministic_ref(self._source_id, "entity", surface)

    def _state_for(self, e: _Emit) -> str:
        state = _promote(e.confidence, e.obs_state)
        if e.subject_ref in self._conflicted and state not in (
            ConfidenceState.AMBIGUOUS.value,
            ConfidenceState.CONFLICTING.value,
        ):
            return ConfidenceState.CONFLICTING.value
        return state

    # -- assertion emission (resolution-driven identity) -------------------

    def _emit_resolution(self, input: ReconciliationInput) -> list[_Emit]:
        resolution = input.resolution
        if resolution is None:
            return []
        out: list[_Emit] = []
        for am in resolution.alias_mappings:
            conf = am.confidence if am.confidence else 0.0
            out.append(
                _Emit(
                    predicate="ALIAS_OF",
                    subject_ref=am.alias_ref,
                    object_ref=am.canonical_ref,
                    confidence=conf,
                    obs_state=ConfidenceState.PROBABLE,
                    support_refs=[am.alias_ref],
                    obs_generated_by=None,
                )
            )
            if am.alias_text:
                out.append(
                    _Emit(
                        predicate="KNOWN_AS",
                        subject_ref=am.canonical_ref,
                        object_ref=am.alias_text,
                        confidence=conf,
                        obs_state=ConfidenceState.PROBABLE,
                        support_refs=[am.alias_ref],
                        obs_generated_by=None,
                    )
                )
        return out

    # -- assertion emission (typed observations) ---------------------------

    def _emit_observations(self, input: ReconciliationInput) -> list[_Emit]:
        result = input.analysis
        out: list[_Emit] = []

        for sb in result.scene_boundaries:
            if sb.boundary == "start":
                out.append(
                    _Emit(
                        "STARTS_AT",
                        sb.scene_ref,
                        sb.segment.locator,
                        sb.confidence,
                        sb.state,
                        _support_refs(sb.segment),
                        sb.generated_by,
                    )
                )

        for al in result.aliases:
            canonical = al.entity_ref or self._resolve(al.canonical_name)
            alias_ref = self._resolve(al.alias) or _deterministic_ref(
                input.source_id, "entity", al.alias
            )
            if canonical:
                out.append(
                    _Emit(
                        "ALIAS_OF",
                        alias_ref,
                        canonical,
                        al.confidence,
                        al.state,
                        _support_refs(al.segment),
                        al.generated_by,
                    )
                )
                out.append(
                    _Emit(
                        "KNOWN_AS",
                        canonical,
                        al.alias,
                        al.confidence,
                        al.state,
                        _support_refs(al.segment),
                        al.generated_by,
                    )
                )

        for em in result.entity_mentions:
            subject = self._resolve(em.mention)
            if subject is None:
                continue
            out.append(
                _Emit(
                    "MENTIONED_IN",
                    subject,
                    em.segment.locator,
                    em.confidence,
                    em.state,
                    _support_refs(em.segment),
                    em.generated_by,
                )
            )

        for pr in result.presence:
            subject = self._resolve(pr.entity)
            if subject is None:
                continue
            out.append(
                _Emit(
                    "PRESENT_IN",
                    subject,
                    pr.present_in,
                    pr.confidence,
                    pr.state,
                    _support_refs(pr.segment),
                    pr.generated_by,
                )
            )

        for obs in result.utterances:
            utterance_ref = _deterministic_ref(input.source_id, "utterance", obs.segment.locator)
            speaker = self._resolve(obs.speaker)
            if speaker:
                out.append(
                    _Emit(
                        "SPEAKS",
                        speaker,
                        utterance_ref,
                        obs.confidence,
                        obs.state,
                        _support_refs(obs.segment),
                        obs.generated_by,
                    )
                )
            out.append(
                _Emit(
                    "UTTERED_IN",
                    utterance_ref,
                    obs.segment.locator,
                    obs.confidence,
                    obs.state,
                    _support_refs(obs.segment),
                    obs.generated_by,
                )
            )

        for tr in result.traits:
            subject = self._resolve(tr.entity)
            if subject is None:
                continue
            out.append(
                _Emit(
                    "HAS_TRAIT",
                    subject,
                    tr.trait,
                    tr.confidence,
                    tr.state,
                    _support_refs(tr.segment),
                    tr.generated_by,
                )
            )

        for rel in result.relationships:
            # Plan T (P2-S4 / R7): resolve the relationship to a registered
            # predicate + validated relationship type. Unknown / type-invalid /
            # malformed sibling-of input yields None -> evidence-only, never an
            # assertion (the trusted predicate vocabulary is never mutated by input).
            target = _relationship_target(rel)
            if target is None:
                continue
            predicate, rel_type = target
            subject = self._resolve(rel.subject_ref)
            obj = self._resolve(rel.object_ref)
            if subject is None or obj is None:
                continue
            out.append(
                _Emit(
                    predicate,
                    subject,
                    obj,
                    rel.confidence,
                    rel.state,
                    _support_refs(rel.segment),
                    rel.generated_by,
                    relationship_type=rel_type,
                )
            )

        for emo in result.emotions:
            subject = self._resolve(emo.entity)
            if subject is None:
                continue
            out.append(
                _Emit(
                    "HAS_EMOTION",
                    subject,
                    emo.emotion,
                    emo.confidence,
                    emo.state,
                    _support_refs(emo.segment),
                    emo.generated_by,
                )
            )

        for st in result.states:
            subject = self._resolve(st.entity)
            if subject is None:
                continue
            out.append(
                _Emit(
                    "IN_STATE",
                    subject,
                    st.observed_state,
                    st.confidence,
                    st.state,
                    _support_refs(st.segment),
                    st.generated_by,
                )
            )

        for ctx in result.context:
            out.append(
                _Emit(
                    "HAS_CONTEXT",
                    ctx.segment.locator,
                    ctx.value,
                    ctx.confidence,
                    ctx.state,
                    _support_refs(ctx.segment),
                    ctx.generated_by,
                )
            )

        return out


__all__ = ["ReconciliationInput", "SemanticReconciler", "RECONCILER_DIGEST", "_promote"]
