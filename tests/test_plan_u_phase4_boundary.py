"""Plan U Phase 4 (P4-S1..S5) — boundary, correlated membership, and actor authority.

Spec-first postgres tests for the Phase-4 boundary-correctness contract:

* P4-S1 — one boundary-normalization contract for standard dashed-UUID wire values:
  POST/GET source+work ids are canonical DASHED form; the ``dashed_uuid`` helper is
  idempotent and passes opaque canonical refs through unchanged.
* P4-S4 — correlated ``memberships.tuples`` scope: a requested dimension
  combination matches only when a SINGLE tuple satisfies every requested dimension
  at once (A/X+B/Y matches while A/Y+B/X misses); rows without tuples fall back to
  the legacy independent-array overlap semantics.
* P4-S5 — ``POST /v1/entities`` records the authenticated principal as the
  authoritative ``created_by``/actor; a request-supplied ``actor`` is retained only
  as delegated, NON-authoritative ``attributed_actor`` and can never spoof event,
  current-state, or audit provenance; unsupported authority elevation is rejected.

These drive the real resolver, ledger, reducer, query and audit seams (never a mock).
"""

from __future__ import annotations

import json
import re
import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from test_api_contract import W, _client_settings
from umd.api.app import create_app
from umd.api.ids import dashed_uuid
from umd.audit.service import AuditService
from umd.domain.events import SemanticEvent
from umd.projections.query import QueryService, StructuredQuery
from umd.resolution.resolution import resolved_event
from umd.storage.postgres.ledger import SemanticLedger
from umd.storage.postgres.reducer import CANONICAL_IDENTITY_PREDICATE
from umd.storage.postgres.tables import metadata as db_meta

pytestmark = pytest.mark.postgres

_cs = db_meta.tables["current_state"]

_DASHED = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


def _establish(
    canonical: str, *, memberships: dict[str, Any], label: str = "Boundary"
) -> SemanticEvent:
    """An ESTABLISH event carrying arbitrary memberships (incl. correlated tuples)."""
    return resolved_event(
        kind="ESTABLISH",
        entity_id=canonical,
        target_entity_id=canonical,
        reason="entity resolution",
        canonical_type="character",
        display_label=label,
        aliases=[],
        support_refs=["m:1"],
        memberships=memberships,
        state="CONFIRMED",
        classification="probable",
        intensity=0.6,
        authority="machine",
        created_by="principal@example",
        generated_by={"stage": "ENTITY_RESOLUTION", "analyzer": "umd@1", "config_digest": "umd@1"},
    )


def _entity_refs(q: QueryService, **filters: str) -> set[str]:
    return {h.ref for h in q.entities(StructuredQuery(kind="ENTITY", filters=filters)).results}


# ---------------------------------------------------------------------------
# P4-S1: boundary-normalization contract
# ---------------------------------------------------------------------------


def test_dashed_uuid_normalization_contract() -> None:
    dashed = str(uuid.uuid4())
    dashless = dashed.replace("-", "")
    # Dashed stays dashed, dashless becomes dashed (idempotent).
    assert dashed_uuid(dashed) == dashed
    assert dashed_uuid(dashless) == dashed
    assert dashed_uuid(dashed_uuid(dashless)) == dashed
    # None stays None.
    assert dashed_uuid(None) is None
    # Opaque non-UUID ids (canonical refs, job ids, locators) pass through unchanged.
    for opaque in ("entity:canonical:abc123", "job-abc123", "ocfl://nested/ref", "src:opaque"):
        assert dashed_uuid(opaque) == opaque


def test_post_sources_and_detail_return_dashed_uuids(umd_db: sa.Engine, source_store: Any) -> None:
    app = create_app(
        engine=umd_db, source_store=source_store, settings=_client_settings(), runner="hermetic"
    )
    with TestClient(app) as client:
        r = client.post(
            "/v1/sources",
            json={
                "media_kind": "txt",
                "original_name": "boundary.txt",
                "content_type": "text/plain",
                "content": "Mara took the lantern and lit the flame.",
            },
            headers=W,
        )
        assert r.status_code == 201, r.text
        body = r.json()
        sid = body["source_id"]
        wid = body["work_id"]
        # POST /v1/sources returns canonical DASHED UUIDs (P4-S1).
        assert _DASHED.match(sid), sid
        assert _DASHED.match(wid), wid
        assert str(uuid.UUID(sid)) == sid
        assert str(uuid.UUID(wid)) == wid

        detail = client.get(f"/v1/sources/{sid}", headers=W)
        assert detail.status_code == 200, detail.text
        db = detail.json()
        # GET /v1/sources/{id} detail round-trips the same dashed ids.
        assert db["source_id"] == sid
        assert db["work_id"] == wid


# ---------------------------------------------------------------------------
# P4-S4: correlated tuple scope truth table
# ---------------------------------------------------------------------------


def test_tuple_scope_truth_table(umd_db: sa.Engine) -> None:
    src_a, src_b = str(uuid.uuid4()), str(uuid.uuid4())
    work_x, work_y = str(uuid.uuid4()), str(uuid.uuid4())
    e_ax_by = "entity:canonical:truth:1"
    e_ay_bx = "entity:canonical:truth:2"
    ledger = SemanticLedger(umd_db)
    # E1 carries correlated tuples [A,X] and [B,Y]; E2 carries [A,Y] and [B,X].
    ledger.append(
        [
            _establish(
                e_ax_by,
                memberships={
                    "source_ids": [src_a, src_b],
                    "work_ids": [work_x, work_y],
                    "continuity_ids": [],
                    "tuples": [[src_a, work_x, None], [src_b, work_y, None]],
                },
            ),
            _establish(
                e_ay_bx,
                memberships={
                    "source_ids": [src_a, src_b],
                    "work_ids": [work_x, work_y],
                    "continuity_ids": [],
                    "tuples": [[src_a, work_y, None], [src_b, work_x, None]],
                },
            ),
        ]
    )
    q = QueryService(umd_db)

    # Exact tuple scope: A/X matches ONLY E1, A/Y matches ONLY E2.
    assert _entity_refs(q, source_id=src_a, work_id=work_x) == {e_ax_by}
    assert _entity_refs(q, source_id=src_a, work_id=work_y) == {e_ay_bx}
    assert _entity_refs(q, source_id=src_b, work_id=work_y) == {e_ax_by}
    assert _entity_refs(q, source_id=src_b, work_id=work_x) == {e_ay_bx}

    # A single-dimension scope matches both (each source/work appears in both).
    assert _entity_refs(q, source_id=src_a) == {e_ax_by, e_ay_bx}
    assert _entity_refs(q, work_id=work_x) == {e_ax_by, e_ay_bx}

    # A correlated scope with a dimension absent from every tuple is empty.
    assert _entity_refs(q, source_id=src_a, work_id=str(uuid.uuid4())) == set()


def test_legacy_array_membership_scope_fallback(umd_db: sa.Engine) -> None:
    legacy = "entity:canonical:legacy:1"
    ledger = SemanticLedger(umd_db)
    # Legacy row: independent-array memberships, NO correlated ``tuples`` block.
    ledger.append(
        [
            _establish(
                legacy,
                memberships={
                    "source_ids": ["src:l1", "src:l2"],
                    "work_ids": [],
                    "continuity_ids": [],
                },
            )
        ]
    )
    q = QueryService(umd_db)
    # Legacy overlap semantics still match (source_id is opaque, not dashed-normalized).
    assert _entity_refs(q, source_id="src:l1") == {legacy}
    assert _entity_refs(q, source_id="src:nope") == set()


# ---------------------------------------------------------------------------
# P4-S5: authenticated principal is the authoritative actor
# ---------------------------------------------------------------------------


def test_post_entities_principal_is_authoritative_actor(
    umd_db: sa.Engine,
) -> None:
    app = create_app(engine=umd_db, source_store=None, settings=_client_settings())
    ref = "entity:canonical:p45:principal"
    fake = "fake@attacker"
    with TestClient(app) as client:
        r = client.post(
            "/v1/entities",
            json={
                "ref": ref,
                "display_label": "PrincipalBoundary",
                "canonical_type": "character",
                "aliases": ["Pb"],
                "memberships": {"source_ids": ["src:p"], "work_ids": [], "continuity_ids": []},
                "state": "CONFIRMED",
                "authority": "operator",
                "actor": fake,
            },
            headers=W,
        )
        assert r.status_code == 201, r.text

    # Event provenance: created_by is the authenticated principal, never the fake.
    with umd_db.connect() as c:
        ev_row = c.execute(
            sa.text(
                "SELECT payload, created_by FROM semantic_event WHERE payload->>'entity_id' = :r"
            ),
            {"r": ref},
        ).first()
    assert ev_row is not None
    assert ev_row.created_by == "write-key"  # authenticated principal
    assert ev_row.created_by != fake

    # Current-state metadata: created_by is the principal; the fake survives only
    # as delegated, NON-authoritative attributed_actor.
    with umd_db.connect() as c:
        row = c.execute(
            sa.select(_cs.c.object_ref)
            .where(_cs.c.entity_ref == ref)
            .where(_cs.c.predicate == CANONICAL_IDENTITY_PREDICATE)
        ).first()
    assert row is not None
    meta = json.loads(row.object_ref)
    assert meta["created_by"] == "write-key"
    assert meta["attributed_actor"] == fake

    # Audit provenance exposes the authenticated principal as actor.
    expl = AuditService(umd_db).explain(ref)
    assert expl.actor == "write-key"
    assert all(h["created_by"] == "write-key" for h in expl.history)


def test_post_entities_rejects_unsupported_authority(umd_db: sa.Engine) -> None:
    app = create_app(engine=umd_db, source_store=None, settings=_client_settings())
    with TestClient(app) as client:
        r = client.post(
            "/v1/entities",
            json={
                "ref": "entity:canonical:p45:elevate",
                "display_label": "Elevate",
                "memberships": {"source_ids": [], "work_ids": [], "continuity_ids": []},
                "authority": "superuser",
                "actor": "fake@attacker",
            },
            headers=W,
        )
        assert r.status_code == 422, r.text
        assert r.json()["code"] == "invalid_authority"
