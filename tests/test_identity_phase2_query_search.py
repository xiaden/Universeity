"""Plan S Phase 2 (P2-S5): canonical identity is queryable, searchable, API-visible.

Builds on the Phase-1 cast fixture (Alice/Al, Robert/Bob, Carol/Caro accepted as
opaque string canonicals with display labels, active aliases, memberships and real
PROBABLE state) and proves the P2 query/search/API seams:

  * structured ENTITY name / alias filters resolve the SAME opaque canonical ref as
    the ref filter, exposing the active display label, aliases, type, state,
    confidence, support refs and memberships (from the reducer CANONICAL_IDENTITY
    row — never the SQL entity table);
  * an unknown name or the unresolved "Astra" alias never fabricates an ID;
  * ENTITY reads are paginated/bounded;
  * exact, fuzzy (pg_trgm) and alias search all resolve to the same canonical
    opaque ref;
  * a label/alias correction replays deterministically and removes the inactive
    historical label/alias from active search;
  * canonical labels are searchable ONLY once the search projection has been built
    (the replay/freshness path), never before;
  * the entities HTTP route exposes canonical identity metadata.
"""

from __future__ import annotations

import importlib
import json
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from job_helpers import ensure_source, make_manifest
from umd.api.app import create_app
from umd.application.commands import SemanticCommandService
from umd.config import (
    AuthSettings,
    ConsistencySettings,
    RateLimitSettings,
    Settings,
)
from umd.domain.evidence import EvidenceBatch
from umd.domain.models import Evidence, EvidenceKind
from umd.projections.base import ReplayDriver
from umd.projections.checkpoint import ProjectionCheckpointStore
from umd.projections.current import CurrentTierOneBuilder
from umd.projections.query import QueryService, StructuredQuery
from umd.projections.search import (
    SearchFilters,
    SearchProjectionBuilder,
    SearchService,
)
from umd.projections.tables import RESULT_KIND_CANONICAL_ENTITY
from umd.resolution.resolution import resolved_event
from umd.storage.postgres.ledger import SemanticLedger
from umd.storage.postgres.reducer import CANONICAL_IDENTITY_PREDICATE
from umd.storage.postgres.tables import metadata as db_meta

pytestmark = pytest.mark.postgres

_cs = db_meta.tables["current_state"]

R = {"Authorization": "Bearer read-key"}


# ---------------------------------------------------------------------------
# cast fixture (Alice/Al, Robert/Bob, Carol/Caro + unresolved Astra)
# ---------------------------------------------------------------------------


def _build_cast(umd_db: sa.Engine) -> tuple[Any, str, list[str]]:
    production = importlib.import_module("umd.jobs.production")
    ensure_source(umd_db)
    ledger = SemanticLedger(umd_db)
    runtime = production.ProductionRuntime(
        engine=umd_db,
        commands=SemanticCommandService(ledger),
        ledger=ledger,
    )
    composer = production._Composer(umd_db, runtime)  # noqa: SLF001
    src = composer._require_source(make_manifest("ENTITY_RESOLUTION"))  # noqa: SLF001
    sid = src["id"]

    _c = {"entity_type": "character", "confidence": 0.6}
    mentions = [
        ("Alice", "chapter/1/paragraph/2", {**_c, "co_occurring": ["Robert"]}),
        ("Alice", "chapter/2/paragraph/1", {**_c, "co_occurring": ["Robert"]}),
        (
            "Al",
            "chapter/1/paragraph/1",
            {**_c, "co_occurring": ["Robert"], "normalized_forms": ["alice"]},
        ),
        ("Robert", "chapter/1/paragraph/3", {**_c, "co_occurring": ["Alice"]}),
        ("Robert", "chapter/2/paragraph/2", {**_c, "co_occurring": ["Alice"]}),
        (
            "Bob",
            "chapter/1/paragraph/5",
            {**_c, "co_occurring": ["Alice"], "normalized_forms": ["robert"]},
        ),
        ("Carol", "chapter/1/paragraph/4", {**_c, "co_occurring": ["Dan"]}),
        ("Carol", "chapter/2/paragraph/3", {**_c, "co_occurring": ["Dan"]}),
        (
            "Caro",
            "chapter/1/paragraph/6",
            {**_c, "co_occurring": ["Dan"], "normalized_forms": ["carol"]},
        ),
        ("Astra", "chapter/1/paragraph/7", {**_c, "confidence_state": "AMBIGUOUS"}),
    ]
    records = [
        Evidence(
            source_id=sid,
            evidence_kind=EvidenceKind.TEXT_SPAN,
            locator=locator,
            extraction_stage="STRUCTURAL_ANALYSIS",
            tool_versions={"analyzer": "umd-text-structural@2"},
            config_digest="umd-entity-resolution@1",
            confidence=0.6,
            quality={"candidate_kind": "entity", "mention_text": text, **quality},
        )
        for text, locator, quality in mentions
    ]
    composer._evidence.record(EvidenceBatch(records=records))  # noqa: SLF001
    outcome = composer._entity_resolution(make_manifest("ENTITY_RESOLUTION"))  # noqa: SLF001
    refs = sorted(r for r in outcome.artifact_refs if r.startswith("entity:canonical:"))
    return composer, sid, refs


def _identity_meta(umd_db: sa.Engine, ref: str) -> dict[str, Any]:
    with umd_db.connect() as conn:
        row = conn.execute(
            sa.select(_cs.c.object_ref).where(
                (_cs.c.entity_ref == ref) & (_cs.c.predicate == CANONICAL_IDENTITY_PREDICATE)
            )
        ).scalar_one()
    return json.loads(str(row))


def _canonical_by_label(umd_db: sa.Engine, label: str) -> str:
    with umd_db.connect() as conn:
        rows = conn.execute(
            sa.select(_cs.c.entity_ref, _cs.c.object_ref).where(
                _cs.c.predicate == CANONICAL_IDENTITY_PREDICATE
            )
        ).fetchall()
    for r in rows:
        meta = json.loads(str(r.object_ref))
        if meta.get("display_label") == label:
            return str(r.entity_ref)
    raise AssertionError(f"no canonical with display_label {label!r}")


def _build_search(umd_db: sa.Engine) -> None:
    # The search builder pauses on authority events (EntityResolved). force_resume
    # is the documented replay path that acknowledges those authority events so the
    # canonical labels/aliases become searchable — the "search visibility only after
    # replay/freshness path" the plan requires.
    store = ProjectionCheckpointStore(umd_db)
    ReplayDriver(umd_db, store).run(CurrentTierOneBuilder(), wipe=True)
    ReplayDriver(umd_db, store).run(SearchProjectionBuilder(), wipe=True, force_resume=True)


# ---------------------------------------------------------------------------
# structured ENTITY query seam
# ---------------------------------------------------------------------------


def test_structured_entity_name_filter_exposes_canonical_metadata(umd_db: sa.Engine) -> None:
    _composer, sid, _refs = _build_cast(umd_db)
    page = QueryService(umd_db).entities(StructuredQuery(kind="ENTITY", filters={"name": "Alice"}))
    assert page.total == 1
    h = page.results[0]
    # Opaque deterministic ref, not a fabricated human-readable ID.
    assert h.ref.startswith("entity:canonical:")
    tail = h.ref[len("entity:canonical:") :]
    assert ":" not in tail
    # Active display label + type/state/confidence/support/memberships.
    meta = _identity_meta(umd_db, h.ref)
    assert h.label == "Alice"
    assert h.value == "Alice"
    assert meta["canonical_type"] == "character"
    assert meta["state"] == "PROBABLE"  # real state, not a fabricated CONFIRMED
    assert h.capabilities.get("display_label") == "Alice"
    assert set(meta["aliases"]) == {"Al"}
    assert meta["memberships"].get("source_ids") == [sid]
    assert isinstance(meta["support_refs"], list)


def test_structured_entity_alias_and_name_resolve_same_canonical(umd_db: sa.Engine) -> None:
    _composer, _sid, _refs = _build_cast(umd_db)
    by_name = QueryService(umd_db).entities(
        StructuredQuery(kind="ENTITY", filters={"name": "Alice"})
    )
    by_alias = QueryService(umd_db).entities(
        StructuredQuery(kind="ENTITY", filters={"alias": "Al"})
    )
    by_ref = QueryService(umd_db).entities(
        StructuredQuery(kind="ENTITY", filters={"ref": by_name.results[0].ref})
    )
    assert by_alias.total == 1
    assert by_ref.total == 1
    assert by_alias.results[0].ref == by_name.results[0].ref == by_ref.results[0].ref


def test_structured_entity_unknown_name_or_unresolved_alias_never_fabricates(
    umd_db: sa.Engine,
) -> None:
    _composer, _sid, _refs = _build_cast(umd_db)
    # Unknown human-readable name: honest zero, never an invented ref.
    unknown = QueryService(umd_db).entities(
        StructuredQuery(kind="ENTITY", filters={"name": "Nobody"})
    )
    assert unknown.total == 0
    assert unknown.results == []
    # The genuinely unresolved "Astra" alias is surfaced via UNRESOLVED_ALIASES,
    # never fabricated into a canonical by the ENTITY read.
    astra = QueryService(umd_db).entities(
        StructuredQuery(kind="ENTITY", filters={"alias": "Astra"})
    )
    assert astra.total == 0
    assert astra.results == []


def test_structured_entity_bounded_pagination(umd_db: sa.Engine) -> None:
    _composer, _sid, _refs = _build_cast(umd_db)
    q = QueryService(umd_db)
    first = q.entities(StructuredQuery(kind="ENTITY", limit=2, offset=0))
    assert first.total == 3
    assert len(first.results) == 2
    second = q.entities(StructuredQuery(kind="ENTITY", limit=2, offset=2))
    assert len(second.results) == 1
    # Pagination never duplicates a canonical across pages.
    assert {h.ref for h in first.results}.isdisjoint({h.ref for h in second.results})


# ---------------------------------------------------------------------------
# search seam (SearchProjectionBuilder sole writer + freshness path)
# ---------------------------------------------------------------------------


def test_search_exact_fuzzy_alias_resolve_same_canonical(umd_db: sa.Engine) -> None:
    _composer, _sid, _refs = _build_cast(umd_db)
    _build_search(umd_db)
    svc = SearchService(umd_db)
    alice_ref = _canonical_by_label(umd_db, "Alice")
    exact = svc.exact("Alice")
    fuzzy = svc.fuzzy("Alyce")
    alias = svc.exact("Al")
    assert exact.total >= 1
    assert fuzzy.total >= 1
    assert alias.total >= 1
    # All three resolve the SAME canonical opaque ref (via entity_ref, or the ref
    # itself for the display-label doc).
    canon_of = lambda hits: {h.entity_ref or h.ref for h in hits}  # noqa: E731
    assert alice_ref in canon_of(exact.hits)
    assert alice_ref in canon_of(fuzzy.hits)
    assert alice_ref in canon_of(alias.hits)


def test_search_correction_replay_removes_inactive_label_and_alias(umd_db: sa.Engine) -> None:
    composer, _sid, _refs = _build_cast(umd_db)
    _build_search(umd_db)
    svc = SearchService(umd_db)
    alice_ref = _canonical_by_label(umd_db, "Alice")
    assert svc.exact("Alice").total >= 1
    assert svc.exact("Al").total >= 1

    # Correct Alice's display label + aliases (reducer folds the UPDATE; the old
    # label/alias moves to immutable history / row.alternatives as inactive).
    ledger = SemanticLedger(umd_db)
    ledger.append(
        [
            resolved_event(
                kind="UPDATE",
                entity_id=alice_ref,
                target_entity_id=alice_ref,
                display_label="Alicia",
                aliases=["Ali"],
                state="PROBABLE",
                intensity=0.7,
            )
        ]
    )
    _build_search(umd_db)
    # Historical/inactive label + alias removed from the CANONICAL_ENTITY search
    # surface by the deterministic rebuild; corrected label/alias searchable. (The
    # original source-evidence mention docs for "Alice"/"Al" legitimately remain —
    # immutable evidence — so scope to the canonical kind.)
    ce = SearchFilters(kind=RESULT_KIND_CANONICAL_ENTITY)
    assert svc.exact("Alice", ce).total == 0
    assert svc.exact("Al", ce).total == 0
    assert svc.exact("Alicia", ce).total >= 1
    assert svc.exact("Ali", ce).total >= 1
    hits = svc.exact("Alicia", ce).hits
    assert any((h.entity_ref or h.ref) == alice_ref for h in hits)


def test_search_canonical_visibility_requires_replay_freshness_path(umd_db: sa.Engine) -> None:
    _composer, _sid, _refs = _build_cast(umd_db)
    svc = SearchService(umd_db)
    # Before the search projection is built, canonical labels are NOT searchable.
    assert svc.exact("Alice").total == 0
    # The single-writer search projection indexes them via replay.
    _build_search(umd_db)
    assert svc.exact("Alice").total >= 1


# ---------------------------------------------------------------------------
# API seam
# ---------------------------------------------------------------------------


def _client_settings() -> Settings:
    return Settings(
        auth=AuthSettings(api_keys=["write-key", "read-key"], write_keys=["write-key"]),
        rate_limit=RateLimitSettings(
            enabled=False, requests_per_window=10000, window_seconds=60.0, burst=100
        ),
        consistency=ConsistencySettings(lag_wait_multiplier=1, max_waiters=16),
        lag_budget_seconds=0.05,
    )


def test_entities_api_exposes_canonical_metadata(umd_db: sa.Engine, source_store) -> None:
    _composer, _sid, _refs = _build_cast(umd_db)
    app = create_app(engine=umd_db, source_store=source_store, settings=_client_settings())
    with TestClient(app) as client:
        r = client.get("/v1/entities", params={"name": "Alice"}, headers=R)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["total"] == 1
        item = body["items"][0]
        assert item["ref"].startswith("entity:canonical:")
        assert item["label"] == "Alice"
        assert item["display_label"] == "Alice"
        assert item["state"] == "PROBABLE"
        assert item["canonical_type"] == "character"
        assert item["aliases"] == ["Al"]
        assert item["memberships"]["source_ids"] == [_sid]
        assert isinstance(item["support_refs"], list)
        # GET by the returned opaque ref returns the same canonical.
        r2 = client.get(f"/v1/entities/{item['ref']}", headers=R)
        assert r2.status_code == 200
        assert r2.json()["ref"] == item["ref"]
