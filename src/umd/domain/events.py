"""Append-only semantic-event modeling, versioning, validation, and upcasting (P3-S1).

This module is the pure, I/O-free authority for what a *semantic event is*: its
envelope, its versioned payload schemas under ``schemas/events/<type>/v<n>.json``,
the validation of a payload against the published JSON schema for a ``(type, version)``,
and the pure upcaster chain that widens an old payload into the latest version.

Design rules (carried forward from the DD / CONTRACTS.md):
  * payloads are immutable once appended; a historical row is NEVER mutated;
  * a breaking change ADDS a new version + a pure upcaster — it never edits a
    retained ``v<n>.json``;
  * upcasters are pure functions of ``(payload)`` with no I/O, so replay is
    deterministic and testable without a database;
  * validation uses ``jsonschema`` against the published ``v<n>.json`` file, so
    the schema files are the single canonical contract, not duplicated logic.

``JobRunAudit`` is modelled as an event type (it is an auditable record) but is
handled *explicitly* by projector/reducer policy and is excluded from semantic
Tier-0 replay — the concrete operational stream lives in ``job_run_audit``
(see ``umd.storage.postgres.stage_repository``).
"""

from __future__ import annotations

import json
import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from functools import cache
from pathlib import Path
from typing import Any

import jsonschema
from jsonschema import Draft202012Validator
from pydantic import BaseModel, Field

#: All versioned semantic event types (the DD's appendix list).
EVENT_TYPES: tuple[str, ...] = (
    "SourceIngested",
    "SourceAliased",
    "FormatAnalyzed",
    "SegmentCreated",
    "StageCompleted",
    "JobRunAudit",
    "EntityMentioned",
    "EntityResolved",
    "ReferenceRebound",
    "Aligned",
    "SemanticAsserted",
    "ContradictionRecorded",
    "OverrideApplied",
    "CorrectionApplied",
    "Locked",
    "Unlocked",
    "Invalidated",
    "LocatorRebased",
    "HallucinationFiltered",
)

#: Event types that are auditable records but are deliberately EXCLUDED from
#: semantic Tier-0 replay (DD: job-run audit is committed but excluded from
#: semantic-state replay to avoid sequence inflation; handled by projector policy).
NON_SEMANTIC_EVENT_TYPES: frozenset[str] = frozenset({"JobRunAudit"})


class EventType(StrEnum):
    """Typed enum of the versioned semantic event types."""

    SOURCE_INGESTED = "SourceIngested"
    SOURCE_ALIASED = "SourceAliased"
    FORMAT_ANALYZED = "FormatAnalyzed"
    SEGMENT_CREATED = "SegmentCreated"
    STAGE_COMPLETED = "StageCompleted"
    JOB_RUN_AUDIT = "JobRunAudit"
    ENTITY_MENTIONED = "EntityMentioned"
    ENTITY_RESOLVED = "EntityResolved"
    REFERENCE_REBOUND = "ReferenceRebound"
    ALIGNED = "Aligned"
    SEMANTIC_ASSERTED = "SemanticAsserted"
    CONTRADICTION_RECORDED = "ContradictionRecorded"
    OVERRIDE_APPLIED = "OverrideApplied"
    CORRECTION_APPLIED = "CorrectionApplied"
    LOCKED = "Locked"
    UNLOCKED = "Unlocked"
    INVALIDATED = "Invalidated"
    LOCATOR_REBASED = "LocatorRebased"
    HALLUCINATION_FILTERED = "HallucinationFiltered"


class EventSchemaError(ValueError):
    """Raised when a payload fails validation against its published JSON schema."""


class EventVersionError(ValueError):
    """Raised when a (type, version) has no retained schema or upcaster."""


# A pure upcaster: ``payload_old -> payload_new`` (version N -> N+1). No I/O.
type Upcaster = Callable[[dict[str, Any]], dict[str, Any]]


# ---------------------------------------------------------------------------
# Schema discovery / loading
# ---------------------------------------------------------------------------


def _schemas_root() -> Path:
    """Locate ``schemas/events`` for the installed package or repository checkout.

    Resolution order (first hit wins, fail closed — never silently degrade):
      1. ``UMD_EVENT_SCHEMAS_ROOT`` env override (the image sets this to the
         baked-in ``/app/schemas/events``). If set but not a directory, raise.
      2. ancestor walk from the installed module (repo checkout / editable).
      3. ``Path.cwd() / "schemas" / "events"`` fallback for non-image runs
         without the env var (e.g. tests run from the repo root).
    """
    override = os.environ.get("UMD_EVENT_SCHEMAS_ROOT")
    if override:
        override_path = Path(override)
        if override_path.is_dir():
            return override_path
        raise FileNotFoundError(
            f"UMD_EVENT_SCHEMAS_ROOT is set to {override!r} but is not a directory"
        )
    here = Path(__file__).resolve()
    for parent in here.parents:
        candidate = parent / "schemas" / "events"
        if candidate.is_dir():
            return candidate
    cwd_candidate = Path.cwd() / "schemas" / "events"
    if cwd_candidate.is_dir():
        return cwd_candidate
    raise FileNotFoundError(
        "schemas/events not found (set UMD_EVENT_SCHEMAS_ROOT to the schemas/events directory)"
    )


@cache
def schemas_root() -> Path:
    """Absolute path to the retained event-schema root (``schemas/events``)."""
    return _schemas_root()


def load_schema(event_type: str, version: int) -> dict[str, Any]:
    """Load and cache a retained payload JSON schema for ``(type, version)``."""
    path = _schemas_root() / event_type / f"v{version}.json"
    if not path.is_file():
        raise EventVersionError(f"no retained schema for {event_type} v{version}: {path}")
    with path.open(encoding="utf-8") as fh:
        data: dict[str, Any] = json.load(fh)
        return data


@cache
def latest_version(event_type: str) -> int:
    """The highest retained schema version for an event type."""
    root = _schemas_root() / event_type
    versions = [
        int(p.name[1:].split(".")[0]) for p in root.glob("v*.json") if p.name.startswith("v")
    ]
    if not versions:
        raise EventVersionError(f"no retained schemas for event type {event_type!r}")
    return max(versions)


@cache
def _validator(event_type: str, version: int) -> Draft202012Validator:
    return Draft202012Validator(load_schema(event_type, version))


def schema_url(event_type: str, version: int) -> str:
    """Canonical ``schema_url`` stored on the semantic_event envelope row."""
    return f"schemas/events/{event_type}/v{version}.json"


# ---------------------------------------------------------------------------
# Pure upcaster chain
# ---------------------------------------------------------------------------
# A breaking change to an event payload registers a new v<n> schema AND a pure
# upcaster here from the old version to the new one. Historical retained rows
# replay through this chain deterministically; nothing is ever edited in place.


def _upcast_semantic_asserted_1_to_2(payload: dict[str, Any]) -> dict[str, Any]:
    """v1 -> v2: v2 added a required ``scope`` discriminator; the pure upcaster
    supplies the pre-2.0 default (GLOBAL) so retained v1 rows replay as v2."""
    widened = dict(payload)
    widened.setdefault("scope", "GLOBAL")
    return widened


def _upcast_entity_resolved_1_to_2(payload: dict[str, Any]) -> dict[str, Any]:
    """v1 -> v2: v2 adds additive canonical-identity metadata fields (Plan S
    P1-S3). The pure upcaster supplies neutral defaults so retained v1 rows
    (MERGE/SPLIT/ALIAS) replay unchanged as v2; nothing historical is mutated."""
    widened = dict(payload)
    widened.setdefault("canonical_type", None)
    widened.setdefault("display_label", None)
    widened.setdefault("aliases", [])
    widened.setdefault("support_refs", [])
    widened.setdefault("memberships", {})
    widened.setdefault("state", None)
    widened.setdefault("confidence", None)
    return widened


UPCASTERS: dict[tuple[str, int], Upcaster] = {
    # SemanticAsserted v1 -> v2 (pure upcaster, no I/O).
    ("SemanticAsserted", 1): _upcast_semantic_asserted_1_to_2,
    # EntityResolved v1 -> v2 (Plan S P1-S3): additive canonical-identity metadata.
    ("EntityResolved", 1): _upcast_entity_resolved_1_to_2,
}


def upcast_payload(
    event_type: str, from_version: int, payload: dict[str, Any]
) -> tuple[int, dict[str, Any]]:
    """Replay a payload through the pure upcaster chain to its latest version.

    Returns ``(latest_version, upcast_payload)``. Deterministic and I/O-free;
    the input payload is never mutated.
    """
    version = int(from_version)
    out = dict(payload)
    while (event_type, version) in UPCASTERS:
        out = UPCASTERS[(event_type, version)](out)
        version += 1
    return version, out


# ---------------------------------------------------------------------------
# Envelope + builder
# ---------------------------------------------------------------------------


class SemanticEvent(BaseModel):
    """An event to append to the semantic ledger, or a replayed retained row.

    Construction path (P3-S5 "event-construction vs replay" conformance): callers
    build a :class:`SemanticEvent`, then :meth:`prepare` validates the payload
    against the published schema and upcasts it to the latest version — this is
    the *construction* path. Replay reads retained rows back and folds them
    through :func:`reduce_current_state` with the already-upcast payload.
    """

    event_type: str
    payload: dict[str, Any] = Field(default_factory=dict)
    #: Explicit retained version of ``payload``. ``None`` => use the latest
    #: retained schema (normal for freshly-constructed events).
    payload_version: int | None = None
    valid_time: datetime | None = None
    authority: str | None = None
    confidence: float | None = None
    generated_by: dict[str, Any] = Field(default_factory=dict)
    correlation_id: Any | None = None
    causation_id: int | None = None
    created_by: str | None = None
    # -- populated at insert / on load from the ledger --
    seq: int | None = None
    tx_time: datetime | None = None

    @property
    def is_semantic(self) -> bool:
        """True when this event type participates in Tier-0 semantic replay."""
        return self.event_type not in NON_SEMANTIC_EVENT_TYPES

    def prepare(self) -> PreparedEvent:
        """Validate + upcast; produce the immutable insertable form.

        Raises :class:`EventSchemaError` if ``payload`` does not conform to the
        retained schema for the event's (type, version).
        """
        declared = (
            self.payload_version
            if self.payload_version is not None
            else latest_version(self.event_type)
        )
        validate_payload(self.event_type, declared, self.payload)
        version, upcast = upcast_payload(self.event_type, declared, self.payload)
        # A freshly upcast payload must itself conform to the latest schema.
        validate_payload(self.event_type, version, upcast)
        return PreparedEvent(
            event_type=self.event_type,
            event_version=version,
            schema_url=schema_url(self.event_type, version),
            payload=upcast,
            valid_time=self.valid_time,
            authority=self.authority,
            confidence=self.confidence,
            generated_by=self.generated_by,
            correlation_id=self.correlation_id,
            causation_id=self.causation_id,
            created_by=self.created_by,
        )


class PreparedEvent(BaseModel):
    """Immutable, validated, upcast event ready for ledger insertion."""

    event_type: str
    event_version: int
    schema_url: str
    payload: dict[str, Any]
    valid_time: datetime | None = None
    authority: str | None = None
    confidence: float | None = None
    generated_by: dict[str, Any] = Field(default_factory=dict)
    correlation_id: Any | None = None
    causation_id: int | None = None
    created_by: str | None = None


@dataclass(frozen=True)
class EventSchemaRef:
    """A retained (type, version) schema reference for fixtures/replay."""

    event_type: str
    version: int

    @property
    def url(self) -> str:
        return schema_url(self.event_type, self.version)


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------


def validate_payload(event_type: str, version: int, payload: dict[str, Any]) -> None:
    """Validate ``payload`` against the retained ``v<version>.json`` schema.

    Raises :class:`EventSchemaError` on any non-conformance.
    """
    try:
        _validator(event_type, version).validate(payload)
    except jsonschema.ValidationError as exc:
        raise EventSchemaError(
            f"payload for {event_type} v{version} failed validation: {exc.message}"
        ) from exc


def retained_event_references() -> list[EventSchemaRef]:
    """Every retained ``(type, version)`` schema, for CI replay fixtures."""
    refs: list[EventSchemaRef] = []
    for event_type in EVENT_TYPES:
        root = _schemas_root() / event_type
        versions = sorted(
            int(p.name[1:].split(".")[0]) for p in root.glob("v*.json") if p.name.startswith("v")
        )
        for ver in versions:
            refs.append(EventSchemaRef(event_type=event_type, version=ver))
    return refs
