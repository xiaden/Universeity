"""Evidence batch value types (Phase B, P2-S2).

Implements the binding contract ``EvidenceRepository.record(batch) ->
EvidenceBatch`` (CONTRACTS.md §Core and storage). An ``EvidenceBatch`` is a set of
:class:`Evidence` rows (already defined in ``umd.domain.models``) plus an invariant
summary, and a :class:`RecordedEvidence` projection with idempotent-accepted
tracking.

Every evidence row carries: source id, exact locator, evidence kind, language,
track, raw/normalized/artifact references, extraction stage, tool versions,
configuration digest and confidence — per the DD §Typed relational core.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from umd.domain.models import Evidence


@dataclass
class EvidenceBatch:
    """A batch of :class:`Evidence` rows to record (``record(batch)`` input)."""

    records: list[Evidence] = field(default_factory=list)


@dataclass
class RecordedEvidence:
    """One persisted evidence row with idempotency confirmation."""

    id: str
    source_id: str
    segment_id: str | None = None
    evidence_kind: str = "text_span"
    locator: str | None = None
    is_new: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_id": self.source_id,
            "segment_id": self.segment_id,
            "evidence_kind": self.evidence_kind,
            "locator": self.locator,
            "is_new": self.is_new,
        }


@dataclass
class RecordedEvidenceBatch:
    """Result of :meth:`EvidenceRepository.record`.

    ``created`` are newly inserted records; ``existing`` are idempotent
    duplicates of an identical evidence row (same source + locator + kind +
    config digest); ``total`` counts all accepted input records.

    Idempotency is in-batch (via ``record``'s local ``seen`` set) AND DB-authoritative:
    the ``evidence`` table carries a UNIQUE index ``uq_evidence_identity`` on
    ``(source_id, locator, evidence_kind, config_digest)`` and inserts use
    ``ON CONFLICT DO NOTHING``, so a re-record of identical evidence across
    separate calls is reported as ``existing`` (never re-inserted).
    """

    created: list[RecordedEvidence] = field(default_factory=list)
    existing: list[RecordedEvidence] = field(default_factory=list)
    total: int = 0
