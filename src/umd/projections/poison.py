"""Projection poison classification (P2-S1).

Per the DD / CONTRACTS, a projection may SKIP only non-authoritative machine noise
AFTER it has been quarantined, and must PAUSE (with a reason) on authority-relevant
events such as ``USER_OVERRIDE``, ``MERGE``/``SPLIT``/``ALIAS``, locks, corrections and
invalidations — it must never silently continue with stale state.

The classification is pure and I/O-free: it returns a decision from the event payload
plus the set of refs known to be quarantined.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from umd.domain.events import SemanticEvent

#: Event types that are authority-relevant poison: the projection must pause rather
#: than eagerly refresh from possibly-stale machine-inferred semantics.
AUTHORITY_PAUSE_EVENTS: frozenset[str] = frozenset(
    {
        "OverrideApplied",
        "CorrectionApplied",
        "EntityResolved",  # MERGE / SPLIT / ALIAS
        "Locked",
        "Unlocked",
        "Invalidated",
        "ReferenceRebound",
    }
)

#: Authority-typed predicates (DD §Reversible entity resolution / jobs projection-pause).
AUTHORITY_PREDICATES: frozenset[str] = frozenset(
    {"speaker", "entity", "character", "canonical_entity", "pronunciation"}
)


class PoisonDecision(StrEnum):
    APPLY = "APPLY"
    SKIP = "SKIP"
    PAUSE = "PAUSE"


@dataclass(frozen=True)
class PoisonOutcome:
    decision: PoisonDecision
    reason: str = ""


# ---------------------------------------------------------------------------
# Event-reference extraction (for quarantine anchoring)
# ---------------------------------------------------------------------------


def event_refs(event: SemanticEvent) -> list[str]:
    """Every reference an event is anchored to (used for quarantine detection)."""
    payload = event.payload or {}
    keys = (
        "subject_ref",
        "object_ref",
        "subject_entity_id",
        "object_entity_id",
        "source_id",
        "segment_id",
        "entity_id",
        "mention_id",
        "reference",
        "evidence_ref",
    )
    refs: list[str] = []
    for key in keys:
        val = payload.get(key)
        if isinstance(val, str) and val:
            refs.append(val)
    for key in ("support_refs", "contradiction_refs", "refs", "source_refs"):
        vals = payload.get(key)
        if isinstance(vals, list):
            refs.extend(str(v) for v in vals if isinstance(v, str) and v)
    generated_by = payload.get("generated_by")
    if isinstance(generated_by, dict):
        for key in ("evidence_refs", "input_refs", "source_refs"):
            vals = generated_by.get(key)
            if isinstance(vals, list):
                refs.extend(str(v) for v in vals if isinstance(v, str) and v)
            elif isinstance(vals, str) and vals:
                refs.append(vals)
    return refs


def references_quarantine(event: SemanticEvent, quarantined: set[str]) -> bool:
    """True when ANY ref the event is anchored to is a known quarantined locator."""
    return any(r in quarantined for r in event_refs(event))


def is_authority_pause(event: SemanticEvent) -> bool:
    """True when the event is authority-relevant and must pause a projection."""
    if event.event_type in AUTHORITY_PAUSE_EVENTS:
        return True
    # A SemanticAsserted carrying an explicit USER_OVERRIDE is authority-relevant.
    authority = event.authority or event.payload.get("authority")
    if authority == "USER_OVERRIDE":
        return True
    predicate = event.payload.get("predicate") or event.payload.get("predicate_code")
    # Authority-relevant when the override touches an authority (or any) predicate.
    return authority == "USER_OVERRIDE" and (
        predicate is None or str(predicate).lower() in AUTHORITY_PREDICATES
    )


def classify(event: SemanticEvent, *, quarantined: set[str] | None = None) -> PoisonOutcome:
    """Decide APPLY / SKIP / PAUSE for a replayed semantic event.

    * PAUSE — authority-relevant event (override/merge/split/lock/correction/
      invalidation). Never skipped, never silently applied to a disposable projection.
    * SKIP — non-authoritative machine noise anchored to a quarantined locator.
    * APPLY — everything else.
    """
    if is_authority_pause(event):
        subject = (
            event.payload.get("subject_ref")
            or event.payload.get("entity_ref")
            or event.payload.get("entity_id")
            or "?"
        )
        return PoisonOutcome(
            PoisonDecision.PAUSE,
            f"authority-relevant {event.event_type} on {subject}; "
            "projection paused until reconciled state settles",
        )
    if quarantined and references_quarantine(event, quarantined):
        return PoisonOutcome(
            PoisonDecision.SKIP,
            f"non-authoritative machine noise {event.event_type} anchored to a "
            "quarantined locator; skipped",
        )
    return PoisonOutcome(PoisonDecision.APPLY)


def apply_decision_default() -> PoisonOutcome:
    """A default APPLY outcome (for builders that never poison)."""
    return PoisonOutcome(PoisonDecision.APPLY)


__all__ = [
    "PoisonDecision",
    "PoisonOutcome",
    "classify",
    "event_refs",
    "references_quarantine",
    "is_authority_pause",
    "AUTHORITY_PAUSE_EVENTS",
    "AUTHORITY_PREDICATES",
]
