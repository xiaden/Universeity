"""Semantic command handlers: build versioned events and append them (P3-S3).

Every mutation here goes through :class:`SemanticLedger.append` — the semantic
ledger is the ONLY semantic write authority. Handlers never write projections;
they construct a typed :class:`SemanticEvent`, let the ledger validate/upcast it,
and return the commit (``read_your_writes_token``).

Covered commands (CONTRACTS.md / DD):
  assertions, overrides, corrections, locks, aliases, alignments, contradictions,
  invalidation, locator rebasing, and stage completion.
"""

from __future__ import annotations

import uuid
from typing import Any

import sqlalchemy as sa

from umd.domain.events import EventType, SemanticEvent
from umd.storage.postgres.ledger import CommitResult, SemanticLedger
from umd.storage.postgres.tables import metadata as db_meta

_alignment_t = db_meta.tables["alignment"]


class SemanticCommandService:
    """Typed facade over the append-only semantic ledger."""

    def __init__(self, ledger: SemanticLedger) -> None:
        self._ledger = ledger

    # -- ingestion lifecycle events ---------------------------------------

    def record_source_ingested(
        self,
        *,
        source_id: str,
        sha512: str,
        ocfl_ref: str,
        size_bytes: int,
        media_kind: str,
        work_id: str | None = None,
        original_name: str | None = None,
        idempotency_key: str | uuid.UUID | None = None,
        created_by: str | None = None,
        correlation_id: Any | None = None,
    ) -> CommitResult:
        return self._ledger.append(
            [
                SemanticEvent(
                    event_type=EventType.SOURCE_INGESTED,
                    payload={
                        "source_id": source_id,
                        "sha512": sha512,
                        "ocfl_ref": ocfl_ref,
                        "size_bytes": size_bytes,
                        "media_kind": media_kind,
                        "work_id": work_id,
                        "original_name": original_name,
                    },
                    created_by=created_by,
                    correlation_id=correlation_id,
                )
            ],
            idempotency_key=idempotency_key,
        )

    # -- semantic assertions & edits --------------------------------------

    def assert_semantic(
        self,
        *,
        predicate_code: str,
        subject_ref: str,
        object_ref: str | None = None,
        confidence: float | None = None,
        state: str = "PROBABLE",
        authority: str = "machine",
        scope: str = "GLOBAL",
        support_refs: list[str] | None = None,
        contradiction_refs: list[str] | None = None,
        derived_from: list[str] | None = None,
        subject_entity_id: Any | None = None,
        object_entity_id: Any | None = None,
        continuity_id: Any | None = None,
        narrative_time: dict[str, Any] | None = None,
        spatial: dict[str, Any] | None = None,
        generated_by: dict[str, Any] | None = None,
        actor: str | None = None,
        correlation_id: Any | None = None,
        causation_id: int | None = None,
    ) -> CommitResult:
        payload: dict[str, Any] = {
            "predicate_code": predicate_code,
            "subject_ref": subject_ref,
            "object_ref": object_ref,
            "subject_entity_id": subject_entity_id,
            "object_entity_id": object_entity_id,
            "authority": authority,
            "confidence": confidence,
            "state": state,
            "scope": scope,
            "continuity_id": continuity_id,
            "support_refs": support_refs or [],
            "contradiction_refs": contradiction_refs or [],
            "derived_from": derived_from or [],
            "generated_by": generated_by or {},
        }
        # narrative_time/spatial are object-typed (not nullable) in the schema —
        # only include them when actually provided.
        if narrative_time is not None:
            payload["narrative_time"] = narrative_time
        if spatial is not None:
            payload["spatial"] = spatial
        return self._ledger.append(
            [
                SemanticEvent(
                    event_type=EventType.SEMANTIC_ASSERTED,
                    payload=payload,
                    authority=authority,
                    confidence=confidence,
                    generated_by=generated_by or {},
                    created_by=actor,
                    correlation_id=correlation_id,
                    causation_id=causation_id,
                )
            ]
        )

    def record_override(
        self,
        *,
        subject_ref: str,
        predicate: str,
        object_ref: str | None,
        confidence: float | None = None,
        actor: str,
        evidence: list[str] | None = None,
        reason: str | None = None,
        correlation_id: Any | None = None,
    ) -> CommitResult:
        return self._ledger.append(
            [
                SemanticEvent(
                    event_type=EventType.OVERRIDE_APPLIED,
                    payload={
                        "subject_ref": subject_ref,
                        "predicate": predicate,
                        "object_ref": object_ref,
                        "authority": "USER_OVERRIDE",
                        "confidence": confidence,
                        "evidence": evidence or [],
                        "actor": actor,
                        "reason": reason,
                    },
                    authority="USER_OVERRIDE",
                    confidence=confidence,
                    created_by=actor,
                    correlation_id=correlation_id,
                )
            ]
        )

    def record_correction(
        self,
        *,
        subject_ref: str,
        predicate: str,
        object_ref: str | None,
        prior_ref: str | None = None,
        actor: str,
        reason: str | None = None,
        evidence: list[str] | None = None,
        correlation_id: Any | None = None,
    ) -> CommitResult:
        return self._ledger.append(
            [
                SemanticEvent(
                    event_type=EventType.CORRECTION_APPLIED,
                    payload={
                        "subject_ref": subject_ref,
                        "predicate": predicate,
                        "object_ref": object_ref,
                        "prior_ref": prior_ref,
                        "actor": actor,
                        "reason": reason,
                        "evidence": evidence or [],
                    },
                    authority="USER_OVERRIDE",
                    created_by=actor,
                    correlation_id=correlation_id,
                )
            ]
        )

    # -- locks ------------------------------------------------------------

    def lock(
        self,
        *,
        entity_ref: str,
        predicate: str | None = None,
        actor: str,
        reason: str | None = None,
        correlation_id: Any | None = None,
    ) -> CommitResult:
        return self._ledger.append(
            [
                SemanticEvent(
                    event_type=EventType.LOCKED,
                    payload={
                        "entity_ref": entity_ref,
                        "predicate": predicate,
                        "actor": actor,
                        "reason": reason,
                    },
                    created_by=actor,
                    correlation_id=correlation_id,
                )
            ]
        )

    def unlock(
        self,
        *,
        entity_ref: str,
        predicate: str | None = None,
        actor: str,
        reason: str | None = None,
        correlation_id: Any | None = None,
    ) -> CommitResult:
        return self._ledger.append(
            [
                SemanticEvent(
                    event_type=EventType.UNLOCKED,
                    payload={
                        "entity_ref": entity_ref,
                        "predicate": predicate,
                        "actor": actor,
                        "reason": reason,
                    },
                    created_by=actor,
                    correlation_id=correlation_id,
                )
            ]
        )

    # -- contradictions / invalidation -------------------------------------

    def record_contradiction(
        self,
        *,
        subject_ref: str,
        predicate: str,
        contradicting_ref: str | None = None,
        refs: list[str] | None = None,
        reason: str | None = None,
        correlation_id: Any | None = None,
    ) -> CommitResult:
        return self._ledger.append(
            [
                SemanticEvent(
                    event_type=EventType.CONTRADICTION_RECORDED,
                    payload={
                        "subject_ref": subject_ref,
                        "predicate": predicate,
                        "contradicting_ref": contradicting_ref,
                        "refs": refs or [],
                        "reason": reason,
                    },
                    correlation_id=correlation_id,
                )
            ]
        )

    def invalidate(
        self,
        *,
        subject_ref: str,
        predicate: str | None = None,
        cause: str | None = None,
        scope: str = "GLOBAL",
        stage: str | None = None,
        refs: list[str] | None = None,
        correlation_id: Any | None = None,
    ) -> CommitResult:
        return self._ledger.append(
            [
                SemanticEvent(
                    event_type=EventType.INVALIDATED,
                    payload={
                        "subject_ref": subject_ref,
                        "predicate": predicate,
                        "cause": cause,
                        "scope": scope,
                        "stage": stage,
                        "refs": refs or [],
                    },
                    correlation_id=correlation_id,
                )
            ]
        )

    # -- aliases / alignment / locator rebase ------------------------------

    def alias_source(
        self,
        *,
        source_id: str,
        work_id: str,
        role: str = "alias",
        canonical_id: str | None = None,
        reason: str | None = None,
        correlation_id: Any | None = None,
    ) -> CommitResult:
        return self._ledger.append(
            [
                SemanticEvent(
                    event_type=EventType.SOURCE_ALIASED,
                    payload={
                        "source_id": source_id,
                        "work_id": work_id,
                        "role": role,
                        "canonical_id": canonical_id,
                        "reason": reason,
                    },
                    correlation_id=correlation_id,
                )
            ]
        )

    def record_alignment(
        self,
        *,
        left_ref: str,
        right_ref: str,
        alignment_type: str,
        method: str | None = None,
        assumptions: dict[str, Any] | None = None,
        confidence: float | None = None,
        correlation_id: Any | None = None,
    ) -> CommitResult:
        alignment_id = uuid.uuid4()

        def record_row(conn: sa.Connection) -> None:
            conn.execute(
                _alignment_t.insert().values(
                    id=alignment_id,
                    left_ref=left_ref,
                    right_ref=right_ref,
                    alignment_type=alignment_type,
                    method=method,
                    assumptions=assumptions or {},
                    source_events={},
                    confidence=confidence,
                )
            )

        return self._ledger.complete_and_append(
            events=[
                SemanticEvent(
                    event_type=EventType.ALIGNED,
                    payload={
                        "left_ref": left_ref,
                        "right_ref": right_ref,
                        "alignment_type": alignment_type,
                        "method": method,
                        "assumptions": assumptions or {},
                        "source_events": {},
                        "confidence": confidence,
                    },
                    confidence=confidence,
                    correlation_id=correlation_id,
                )
            ],
            side_effects=record_row,
        )

    def rebase_locator(
        self,
        *,
        old_locator: str,
        new_locator: str,
        reason: str | None = None,
        affected_refs: list[str] | None = None,
        correlation_id: Any | None = None,
    ) -> CommitResult:
        return self._ledger.append(
            [
                SemanticEvent(
                    event_type=EventType.LOCATOR_REBASED,
                    payload={
                        "old_locator": old_locator,
                        "new_locator": new_locator,
                        "reason": reason,
                        "affected_refs": affected_refs or [],
                    },
                    correlation_id=correlation_id,
                )
            ]
        )

    # -- stage completion --------------------------------------------------

    def stage_completed(
        self,
        *,
        source_id: str,
        stage: str,
        status: str = "complete",
        artifact_refs: list[str] | None = None,
        evidence_refs: list[str] | None = None,
        generated_by: dict[str, Any] | None = None,
        job_id: str | None = None,
        correlation_id: Any | None = None,
    ) -> CommitResult:
        return self._ledger.append(
            [
                SemanticEvent(
                    event_type=EventType.STAGE_COMPLETED,
                    payload={
                        "source_id": source_id,
                        "stage": stage,
                        "status": status,
                        "artifact_refs": artifact_refs or [],
                        "evidence_refs": evidence_refs or [],
                        "generated_by": generated_by or {},
                        "job_id": job_id,
                    },
                    generated_by=generated_by or {},
                    correlation_id=correlation_id,
                )
            ]
        )

    # -- entity resolution (MERGE/SPLIT/ALIAS) -----------------------------

    def entity_resolve(
        self,
        *,
        kind: str,
        entity_id: str,
        target_entity_id: str | None = None,
        refs: list[str] | None = None,
        assignments: dict[str, Any] | None = None,
        reason: str | None = None,
        correlation_id: Any | None = None,
    ) -> CommitResult:
        if kind not in ("MERGE", "SPLIT", "ALIAS"):
            raise ValueError(f"invalid EntityResolved kind {kind!r}")
        return self._ledger.append(
            [
                SemanticEvent(
                    event_type=EventType.ENTITY_RESOLVED,
                    payload={
                        "kind": kind,
                        "entity_id": entity_id,
                        "target_entity_id": target_entity_id,
                        "refs": refs or [],
                        "assignments": assignments or {},
                        "reason": reason,
                    },
                    correlation_id=correlation_id,
                )
            ]
        )

    def append(self, events: list[SemanticEvent], **kwargs: Any) -> CommitResult:
        """Raw append passthrough (e.g. StageCompleted / custom batches)."""
        return self._ledger.append(events, **kwargs)


# Re-export for callers that need the ledger directly.
__all__ = ["SemanticCommandService", "CommitResult", "SemanticLedger"]
