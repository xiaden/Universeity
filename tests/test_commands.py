"""P3-S3: semantic command handlers produce schema-valid events (unit).

Uses an in-memory ledger double so the command builders can be exercised without
a database. The double *prepares* every appended event, so any payload that fails
conformance against its retained JSON schema raises — proving each command emits
authority-correct, schema-valid events.
"""

from __future__ import annotations

import uuid

import pytest

from umd.application.commands import SemanticCommandService
from umd.domain.events import EventSchemaError, SemanticEvent
from umd.storage.postgres.ledger import CommitResult


class InMemoryLedger:
    """Ledger double: validates every event via ``prepare`` and records it."""

    def __init__(self) -> None:
        self.appended: list[list[object]] = []
        self.last_kwargs: dict[str, object] = {}
        self._seq = 0

    def append(self, events: list[SemanticEvent], **_kwargs: object) -> CommitResult:
        prepared: list[object] = []
        for ev in events:
            self._seq += 1
            prepared.append(ev.prepare())  # forces schema validation (raises on bad)
        self.appended.append(prepared)
        self.last_kwargs = dict(_kwargs)
        return CommitResult(seq=self._seq, read_your_writes_token=self._seq)


def _svc() -> tuple[SemanticCommandService, InMemoryLedger]:
    ledger = InMemoryLedger()
    return SemanticCommandService(ledger), ledger


def test_source_ingested_command() -> None:
    svc, ledger = _svc()
    res = svc.record_source_ingested(
        source_id="s1",
        sha512="a" * 128,
        ocfl_ref="urn:ocfl:o1",
        size_bytes=12,
        media_kind="text",
        work_id="w1",
        original_name="a.txt",
        created_by="ingest-api",
    )
    assert res.read_your_writes_token == res.seq
    assert ledger.appended[0][0].event_type == "SourceIngested"


def test_semantic_assertion_requires_scope_at_latest_version() -> None:
    svc, ledger = _svc()
    svc.assert_semantic(
        predicate_code="SPEAKS",
        subject_ref="e:1",
        object_ref="utter:1",
        confidence=0.7,
        state="CONFIRMED",
        scope="CONTINUITY",
        actor="worker-asr",
    )
    prep = ledger.appended[0][0]
    assert prep.event_type == "SemanticAsserted"
    assert prep.event_version == 2  # latest retained version
    assert prep.payload["scope"] == "CONTINUITY"


def test_override_is_user_authority() -> None:
    svc, ledger = _svc()
    svc.record_override(
        subject_ref="e:1",
        predicate="SPEAKS",
        object_ref="user:truth",
        actor="user@example",
        evidence=["locator://a"],
    )
    prep = ledger.appended[0][0]
    assert prep.event_type == "OverrideApplied"
    assert prep.payload["authority"] == "USER_OVERRIDE"
    assert prep.payload["object_ref"] == "user:truth"


def test_entity_resolved_kinds() -> None:
    svc, ledger = _svc()
    for kind in ("MERGE", "SPLIT", "ALIAS"):
        svc.entity_resolve(
            kind=kind,
            entity_id="e:1",
            target_entity_id="e:2",
            refs=["m:1", "m:2"],
            assignments={"CANONICAL_ENTITY": "e:2"},
            reason="test",
        )
    kinds = {ledger.appended[i][0].payload["kind"] for i in range(3)}
    assert kinds == {"MERGE", "SPLIT", "ALIAS"}


def test_job_run_audit_command_event_type() -> None:
    """JobRunAudit is an auditable event distinct from semantic edits."""
    svc, ledger = _svc()
    svc.append(
        [
            SemanticEvent(
                event_type="JobRunAudit",
                payload={"job_id": "j1", "stage_name": "INGEST", "action": "complete"},
            )
        ]
    )
    assert ledger.appended[0][0].event_type == "JobRunAudit"


def test_command_idempotency_key_passthrough() -> None:
    key = uuid.uuid4()
    svc, ledger = _svc()
    svc.record_source_ingested(
        source_id="s1",
        sha512="a" * 128,
        ocfl_ref="urn:ocfl:o1",
        size_bytes=1,
        media_kind="text",
        idempotency_key=key,
    )
    assert ledger.appended[0][0].event_type == "SourceIngested"
    assert ledger.last_kwargs["idempotency_key"] == key


def test_invalid_payload_raises_through_command() -> None:
    """A malformed command payload is rejected by schema conformance; the command
    must not silently emit a bad event."""
    svc, _ledger = _svc()
    with pytest.raises(EventSchemaError):
        # missing required source fields (sha512/ocfl_ref/media_kind)
        svc.record_source_ingested(
            source_id="s1", sha512="x", ocfl_ref="", size_bytes=1, media_kind=""
        )
