"""Plan U P3-S3/S4 — active canonical provenance + override winner (postgres).

Spec-first postgres tests for the Post-Plan-T canonical-provenance contract
(CONTRACTS.md:100):

* P3-S3 — active canonical identity reads (``QueryService.entities``) and
  wipe-and-replay retain the exact provenance: identity classification,
  ``generated_by`` (machine provider/config or human override), ``created_by``/
  actor, support refs, and correspondence/derivation refs. The additions are
  strictly additive to Plan T's public response shape.
* P3-S4 — an authenticated human override/correction REPLACES the current
  winning classification + provenance while prior event/audit metadata stays
  immutable and explainable; the machine provider/config provenance is retained
  (never wiped) unless the override explicitly supersedes it.

These drive the real reducer, replay and query seams (never a mock).
"""

from __future__ import annotations

import json
from typing import Any

import pytest
import sqlalchemy as sa

from umd.audit.service import AuditService
from umd.domain.events import SemanticEvent
from umd.projections.base import ReplayDriver
from umd.projections.checkpoint import ProjectionCheckpointStore
from umd.projections.current import CurrentTierOneBuilder
from umd.projections.query import QueryService, StructuredQuery
from umd.resolution.resolution import resolved_event
from umd.storage.postgres.ledger import SemanticLedger
from umd.storage.postgres.reducer import (
    CANONICAL_IDENTITY_PREDICATE,
    STATE_USER_CONFIRMED,
    USER_OVERRIDE,
)
from umd.storage.postgres.tables import metadata as db_meta

pytestmark = pytest.mark.postgres

_cs = db_meta.tables["current_state"]
_se = db_meta.tables["semantic_event"]

_CANONICAL = "entity:canonical:plan-u:aaa"
_MACHINE_GB = {
    "stage": "ENTITY_RESOLUTION",
    "analyzer": "umd-entity-resolution@1",
    "config_digest": "umd-entity-resolution@1",
}


def _establish(canonical: str, *, generated_by: dict[str, Any] | None = None) -> SemanticEvent:
    """An ESTABLISH event carrying full additive provenance (machine path)."""
    return resolved_event(
        kind="ESTABLISH",
        entity_id=canonical,
        target_entity_id=canonical,
        reason="entity resolution",
        canonical_type="character",
        display_label="Alice",
        aliases=["Al"],
        support_refs=["m:1", "m:2"],
        memberships={"source_ids": ["A"], "work_ids": [], "continuity_ids": []},
        state="CONFIRMED",
        classification="probable",
        intensity=0.6,
        authority="machine",
        created_by=None,
        generated_by=generated_by or _MACHINE_GB,
    )


def _identity_row(umd_db: sa.Engine, canonical: str) -> sa.Row[Any] | None:
    with umd_db.connect() as c:
        return c.execute(
            sa.select(_cs.c.object_ref, _cs.c.authority, _cs.c.state, _cs.c.confidence, _cs.c.seq)
            .where(_cs.c.entity_ref == canonical)
            .where(_cs.c.predicate == CANONICAL_IDENTITY_PREDICATE)
        ).first()


def _metadata_of(row: sa.Row[Any] | None) -> dict[str, Any]:
    assert row is not None
    return json.loads(row.object_ref)


def _entity_hit(umd_db: sa.Engine, canonical: str) -> Any:
    page = QueryService(umd_db).entities(StructuredQuery(kind="entities"))
    for hit in page.results:
        if hit.ref == canonical:
            return hit
    raise AssertionError(f"canonical {canonical} not in entities read")


# ---------------------------------------------------------------------------
# P3-S3: active canonical read + replay retain exact provenance
# ---------------------------------------------------------------------------


def test_active_canonical_read_exposes_classification_and_provenance(
    umd_db: sa.Engine,
) -> None:
    ledger = SemanticLedger(umd_db)
    ledger.append([_establish(_CANONICAL)])

    hit = _entity_hit(umd_db, _CANONICAL)
    # Provenance carries classification + machine provider/config + created_by.
    assert hit.provenance["predicate"] == CANONICAL_IDENTITY_PREDICATE
    assert hit.provenance["classification"] == "probable"
    assert hit.provenance["generated_by"] == _MACHINE_GB
    assert hit.provenance["support_refs"] == ["m:1", "m:2"]
    # Capabilities and data carry the classification additively too.
    assert hit.capabilities["classification"] == "probable"
    assert hit.data["classification"] == "probable"
    assert hit.data["generated_by"] == _MACHINE_GB


def test_wipe_replay_preserves_classification_and_provenance(umd_db: sa.Engine) -> None:
    ledger = SemanticLedger(umd_db)
    ledger.append([_establish(_CANONICAL)])
    before = _identity_row(umd_db, _CANONICAL)
    meta_before = _metadata_of(before)
    assert meta_before["generated_by"] == _MACHINE_GB
    assert meta_before["classification"] == "probable"

    # Wipe-and-replay through the shared reducer reconstructs the SAME winner.
    builder = CurrentTierOneBuilder()
    ReplayDriver(umd_db, ProjectionCheckpointStore(umd_db)).run(builder, wipe=True)
    after = _identity_row(umd_db, _CANONICAL)
    assert _metadata_of(after) == meta_before
    assert after.authority == before.authority
    assert after.state == before.state


# ---------------------------------------------------------------------------
# P3-S4: override replaces the current winner while history stays immutable
# ---------------------------------------------------------------------------


def test_override_replaces_winner_keeps_machine_provenance_and_immutable_history(
    umd_db: sa.Engine,
) -> None:
    ledger = SemanticLedger(umd_db)
    from umd.application.commands import SemanticCommandService

    ledger.append([_establish(_CANONICAL)])
    SemanticCommandService(ledger).record_override(
        subject_ref=_CANONICAL,
        predicate=CANONICAL_IDENTITY_PREDICATE,
        object_ref=json.dumps(
            {"display_label": "Alice Prime", "classification": "accepted"},
            sort_keys=True,
        ),
        actor="operator@example",
        evidence=["locator://alice"],
        reason="manual identity confirmation",
        correlation_id="11111111-1111-4111-8111-111111111111",
    )

    row = _identity_row(umd_db, _CANONICAL)
    meta = _metadata_of(row)
    # The override becomes the current winner: classification + label replaced...
    assert meta["classification"] == "accepted"
    assert meta["display_label"] == "Alice Prime"
    assert row.authority == USER_OVERRIDE
    assert row.state == STATE_USER_CONFIRMED
    # ...while unsupported machine provenance is retained, never wiped.
    assert meta["generated_by"] == _MACHINE_GB
    assert meta["support_refs"] == ["m:1", "m:2"]
    assert meta["memberships"] == {"source_ids": ["A"], "work_ids": [], "continuity_ids": []}
    # Authenticated human actor recorded.
    assert meta["created_by"] == "operator@example"

    # Prior event/audit metadata is immutable: the ESTABLISH still carries the
    # original probable classification; the override is a new, separate event.
    with umd_db.connect() as c:
        est = (
            c.execute(sa.select(_se.c.payload).where(_se.c.event_type == "EntityResolved"))
            .scalars()
            .first()
        )
    assert est["classification"] == "probable"

    # Audit explains the change: current winner (human) vs prior (machine).
    audit = AuditService(umd_db).explain(f"{_CANONICAL}#{CANONICAL_IDENTITY_PREDICATE}")
    assert audit.actor == "operator@example"
    assert any(h["event_type"] == "OverrideApplied" for h in audit.history)
    assert audit.history[-1]["event_type"] == "OverrideApplied"
    assert audit.current["authority"] == USER_OVERRIDE


def test_correction_replaces_winner_and_is_explainable(umd_db: sa.Engine) -> None:
    from umd.application.commands import SemanticCommandService

    ledger = SemanticLedger(umd_db)
    svc = SemanticCommandService(ledger)
    ledger.append([_establish(_CANONICAL)])
    svc.record_correction(
        subject_ref=_CANONICAL,
        predicate=CANONICAL_IDENTITY_PREDICATE,
        object_ref=json.dumps({"display_label": "Alice (corrected)", "classification": "accepted"}),
        prior_ref=_CANONICAL,
        actor="reviewer@example",
        reason="label correction",
        evidence=["locator://alice"],
        correlation_id="22222222-2222-4222-8222-222222222222",
    )

    meta = _metadata_of(_identity_row(umd_db, _CANONICAL))
    assert meta["classification"] == "accepted"
    assert meta["display_label"] == "Alice (corrected)"
    # Machine provenance retained across the correction.
    assert meta["generated_by"] == _MACHINE_GB

    audit = AuditService(umd_db).explain(f"{_CANONICAL}#{CANONICAL_IDENTITY_PREDICATE}")
    assert audit.actor == "reviewer@example"
    assert any(h["event_type"] == "CorrectionApplied" for h in audit.history)


# ---------------------------------------------------------------------------
# P3-S3: public HTTP entity read exposes the active provenance additively
# ---------------------------------------------------------------------------


def test_public_entity_read_exposes_classification_and_provenance(
    umd_db: sa.Engine, source_store
) -> None:
    """P3-S3: the typed public ``/v1/entities`` read surfaces the active
    classification + provenance additively on the Plan T EntityResponse (no
    schema break: the extra keys ride the existing provenance/generated_by/
    capabilities dicts)."""
    from fastapi.testclient import TestClient

    from test_api_contract import _build_all, _client_settings
    from umd.api.app import create_app

    SemanticLedger(umd_db).append([_establish(_CANONICAL)])
    _build_all(umd_db)
    app = create_app(
        engine=umd_db,
        source_store=source_store,
        settings=_client_settings(),
        runner="hermetic",
    )
    read_headers = {"Authorization": "Bearer read-key"}
    with TestClient(app) as client:
        g = client.get(f"/v1/entities/{_CANONICAL}", headers=read_headers)
        assert g.status_code == 200, g.text
        body = g.json()
        # Active classification + machine provider/config provenance surfaced.
        assert body["capabilities"]["classification"] == "probable"
        assert body["provenance"]["classification"] == "probable"
        assert body["provenance"]["generated_by"] == _MACHINE_GB
        assert body["provenance"]["support_refs"] == ["m:1", "m:2"]

        le = client.get("/v1/entities?limit=100", headers=read_headers)
        assert le.status_code == 200, le.text
        item = next(it for it in le.json()["items"] if it["ref"] == _CANONICAL)
        assert item["capabilities"]["classification"] == "probable"
        assert item["provenance"]["generated_by"] == _MACHINE_GB
