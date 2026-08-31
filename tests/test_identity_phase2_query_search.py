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
import uuid
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from job_helpers import ensure_source, make_manifest
from umd.analysis.semantic import (
    GeneratedBy,
    RelationshipCandidate,
    SegmentEvidenceRef,
    SemanticAnalysisResult,
)
from umd.api.app import create_app
from umd.application.commands import SemanticCommandService
from umd.config import (
    AuthSettings,
    ConsistencySettings,
    RateLimitSettings,
    Settings,
)
from umd.domain.evidence import EvidenceBatch
from umd.domain.models import Evidence, EvidenceKind, is_known_predicate
from umd.projections.base import ReplayDriver
from umd.projections.checkpoint import ProjectionCheckpointStore
from umd.projections.current import CurrentTierOneBuilder
from umd.projections.edges import ActiveSemanticEdgeProjectionBuilder
from umd.projections.query import (
    QueryService,
    ScopeUnmappableError,
    StructuredQuery,
)
from umd.projections.search import (
    SearchFilters,
    SearchProjectionBuilder,
    SearchService,
)
from umd.projections.tables import RESULT_KIND_CANONICAL_ENTITY, search_document
from umd.reconciliation.reconciler import ReconciliationInput, SemanticReconciler
from umd.resolution.resolution import resolved_event
from umd.resolution.service import CanonicalEntity, ResolutionBatch
from umd.storage.postgres.ledger import SemanticLedger
from umd.storage.postgres.reducer import CANONICAL_IDENTITY_PREDICATE
from umd.storage.postgres.tables import metadata as db_meta

pytestmark = pytest.mark.postgres

_cs = db_meta.tables["current_state"]

R = {"Authorization": "Bearer read-key"}
W = {"Authorization": "Bearer write-key"}


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


# ---------------------------------------------------------------------------
# Plan T Phase 2 (P2-S5): bounded membership filters, scoped search,
# operator establishment, typed relationships + replay equality
# ---------------------------------------------------------------------------


def test_entity_bounded_source_membership_filter(umd_db: sa.Engine) -> None:
    """P2-S1: bounded source_id membership filter restricts ENTITY reads to the
    active canonicals whose replay-derived source membership intersects the scope."""
    _composer, sid, _refs = _build_cast(umd_db)
    q = QueryService(umd_db)
    # All three cast canonicals belong to the source they were resolved from.
    inside = q.entities(StructuredQuery(kind="ENTITY", filters={"source_id": sid}))
    assert inside.total == 3
    # A disjoint source scope honestly returns zero (membership-scoped, not stale).
    outside = q.entities(StructuredQuery(kind="ENTITY", filters={"source_id": "src:elsewhere"}))
    assert outside.total == 0
    # Combining the source filter with a name filter still resolves the in-scope canonical.
    by_name = q.entities(
        StructuredQuery(kind="ENTITY", filters={"name": "Alice", "source_id": sid})
    )
    assert by_name.total == 1
    assert by_name.results[0].label == "Alice"


def test_entity_membership_filter_rejects_malformed_scope(umd_db: sa.Engine) -> None:
    """P2-S1: a malformed work_id/continuity_id is an RFC 7807-style scope error, never
    a silent unfiltered read."""
    _composer, _sid, _refs = _build_cast(umd_db)
    q = QueryService(umd_db)
    with pytest.raises(ScopeUnmappableError):
        q.entities(StructuredQuery(kind="ENTITY", filters={"work_id": "not-a-uuid"}))
    with pytest.raises(ScopeUnmappableError):
        q.entities(StructuredQuery(kind="ENTITY", filters={"continuity_id": "nope"}))


def test_entity_work_and_continuity_membership_filter(umd_db: sa.Engine) -> None:
    """P2-S1: bounded work_id and continuity_id membership filters restrict the read;
    work+continuity valid combinations intersect; a disjoint scope returns zero."""
    _composer, _sid, _refs = _build_cast(umd_db)
    work = str(uuid.uuid4())
    cont = str(uuid.uuid4())
    # Establish a canonical that belongs to this work + continuity + a source.
    app = create_app(engine=umd_db, source_store=None, settings=_client_settings())
    with TestClient(app) as client:
        r = client.post(
            "/v1/entities",
            json={
                "ref": "entity:canonical:workbound:1",
                "display_label": "WorkWarden",
                "canonical_type": "character",
                "aliases": ["Warden"],
                "memberships": {
                    "work_ids": [work],
                    "continuity_ids": [cont],
                    "source_ids": ["src:w1"],
                },
                "state": "CONFIRMED",
                "authority": "operator",
                "actor": "plan-t",
            },
            headers=W,
        )
        assert r.status_code == 201, r.text
    q = QueryService(umd_db)
    assert q.entities(StructuredQuery(kind="ENTITY", filters={"work_id": work})).total >= 1
    assert (
        q.entities(
            StructuredQuery(kind="ENTITY", filters={"work_id": work, "continuity_id": cont})
        ).total
        >= 1
    )
    # A disjoint work scope excludes the established canonical (membership-scoped).
    assert (
        q.entities(StructuredQuery(kind="ENTITY", filters={"work_id": str(uuid.uuid4())})).total
        == 0
    )


def test_entity_api_membership_filter_rfc7807(umd_db: sa.Engine) -> None:
    """P2-S1: the REST boundary surfaces a malformed work_id as RFC 7807 422."""
    _composer, _sid, _refs = _build_cast(umd_db)
    app = create_app(engine=umd_db, source_store=None, settings=_client_settings())
    with TestClient(app) as client:
        r = client.get("/v1/entities", params={"work_id": "bogus"}, headers=R)
        assert r.status_code == 422
        assert r.json()["code"] == "unmappable_scope"


def test_operator_establish_create_and_read(umd_db: sa.Engine) -> None:
    """P2-S3: POST /v1/entities routes through Resolver.establish (operator authority),
    carrying display label / type / aliases / memberships / provenance, and legacy reads."""
    app = create_app(engine=umd_db, source_store=None, settings=_client_settings())
    ref = "entity:canonical:op:1"
    with TestClient(app) as client:
        r = client.post(
            "/v1/entities",
            json={
                "ref": ref,
                "display_label": "Opal",
                "canonical_type": "character",
                "aliases": ["Op"],
                "memberships": {"source_ids": ["src:op"], "work_ids": [], "continuity_ids": []},
                "state": "CONFIRMED",
                "authority": "operator",
                "actor": "plan-t",
            },
            headers=W,
        )
        assert r.status_code == 201, r.text
        assert r.json()["entity_ref"] == ref
        # Legacy read by name surfaces the established canonical with its metadata.
        r2 = client.get("/v1/entities", params={"name": "Opal"}, headers=R)
        assert r2.status_code == 200
        assert r2.json()["total"] == 1
        item = r2.json()["items"][0]
        assert item["ref"] == ref
        assert item["display_label"] == "Opal"
        assert item["canonical_type"] == "character"
        assert item["aliases"] == ["Op"]
        assert item["memberships"]["source_ids"] == ["src:op"]
        assert item["state"] == "CONFIRMED"


def test_operator_establish_is_idempotent(umd_db: sa.Engine) -> None:
    """P2-S3: re-running POST /v1/entities for the same ref converges (no duplicate)."""
    app = create_app(engine=umd_db, source_store=None, settings=_client_settings())
    ref = "entity:canonical:op:2"
    body = {
        "ref": ref,
        "display_label": "Idem",
        "canonical_type": "character",
        "aliases": [],
        "memberships": {"source_ids": ["src:id"], "work_ids": [], "continuity_ids": []},
        "state": "CONFIRMED",
        "authority": "operator",
    }
    with TestClient(app) as client:
        assert client.post("/v1/entities", json=body, headers=W).status_code == 201
        assert client.post("/v1/entities", json=body, headers=W).status_code == 201
        listed = client.get("/v1/entities", params={"name": "Idem"}, headers=R)
        assert listed.status_code == 200
        assert listed.json()["total"] == 1


def test_operator_establish_rejects_invalid_authority(umd_db: sa.Engine) -> None:
    """P2-S3: an unsupported authority is a 422, never silently coerced to operator."""
    app = create_app(engine=umd_db, source_store=None, settings=_client_settings())
    with TestClient(app) as client:
        r = client.post(
            "/v1/entities",
            json={
                "ref": "entity:canonical:op:3",
                "display_label": "NoAuth",
                "authority": "robot",
                "memberships": {"source_ids": [], "work_ids": [], "continuity_ids": []},
            },
            headers=W,
        )
        assert r.status_code == 422
        assert r.json()["code"] == "invalid_authority"


def test_scoped_entity_read_survives_server_side_cardinality(umd_db: sa.Engine) -> None:
    """Plan T fix cycle 2: scoped ENTITY reads are NOT bounded-prefetch-then-filter.

    On a populated database a canonical whose memberships sort beyond the old raw-fetch
    window (``(limit+offset)*2+4`` rows with the API default limit=20 -> 44 rows) used to
    be silently MISSING from a scoped read even though it is in scope, because membership
    filtering happened in Python AFTER a bounded prefetch. The fix moves the membership
    scope into candidate SELECTION (a SQL predicate over the persisted membership
    metadata) so the raw-fetch window is computed over in-scope rows.

    The test seeds 56 unrelated canonicals that sort BEFORE a 3-canonical target source, so
    every target canonical sorts beyond the old 44-row window in the unscoped ordering yet
    must still surface (with a correct ``total`` and cursor pagination) in a source-scoped
    read at the API-default limit=20.
    """
    app = create_app(engine=umd_db, source_store=None, settings=_client_settings())

    def _post(ref: str, label: str, src: str) -> None:
        with TestClient(app) as client:
            r = client.post(
                "/v1/entities",
                json={
                    "ref": ref,
                    "display_label": label,
                    "canonical_type": "character",
                    "aliases": [],
                    "memberships": {"source_ids": [src], "work_ids": [], "continuity_ids": []},
                    "state": "CONFIRMED",
                    "authority": "operator",
                    "actor": "plan-t-fix-2",
                },
                headers=W,
            )
            assert r.status_code == 201, r.text

    # 56 unrelated canonicals whose refs sort AFTER 'a' but BEFORE any 'z'-prefixed target.
    for i in range(56):
        _post(f"entity:canonical:aa:fill:{i:04d}", f"Filler{i}", "src:filler")
    # Target source: 3 canonicals with high-sorting refs so, in UNscoped ordering, all 56
    # fillers (plus the cast's 3 hex-tail refs, which sort below 'z') precede them -> every
    # target sits beyond the old 44-row window.
    target_refs = [f"entity:canonical:zz:target:{i}" for i in range(1, 4)]
    for ref in target_refs:
        _post(ref, f"Target{ref[-1]}", "src:target")

    with TestClient(app) as client:
        # (1) The in-scope target canonicals ARE returned at the API-default limit (no
        # explicit limit param), even though they sort beyond the old raw window.
        r = client.get("/v1/entities", params={"source_id": "src:target"}, headers=R)
        assert r.status_code == 200, r.text
        body = r.json()
        returned = {item["ref"] for item in body["items"]}
        assert target_refs[0] in returned
        assert target_refs[1] in returned
        assert target_refs[2] in returned
        # (2) total reflects the SCOPED set (the 3 target canonicals, nothing else).
        assert body["total"] == 3
        # (3) Cursor pagination across the scoped set: walk pages, no duplicates/gaps, all
        # in-scope targets eventually returned, out-of-scope fillers never returned.
        seen: set[str] = set()
        cursor: str | None = None
        for _ in range(10):
            params: dict[str, Any] = {"source_id": "src:target", "limit": 2}
            if cursor:
                params["cursor"] = cursor
            page = client.get("/v1/entities", params=params, headers=R)
            assert page.status_code == 200, page.text
            p = page.json()
            assert p["total"] == 3
            for item in p["items"]:
                assert item["ref"].startswith("entity:canonical:zz:target:"), item["ref"]
                assert item["ref"] not in seen, f"duplicate across pages: {item['ref']}"
                seen.add(item["ref"])
            if p["next_cursor"] is None:
                break
            cursor = p["next_cursor"]
        # Pagination covered every in-scope canonical exactly once, nothing extra.
        assert seen == set(target_refs)


def test_search_source_scoped_excludes_unrelated_source(umd_db: sa.Engine) -> None:
    """P2-S2: source-scoped canonical search includes only in-scope canonicals — a
    canonical belonging to source C never surfaces in source A's scoped search."""
    _composer, sid, _refs = _build_cast(umd_db)
    app = create_app(engine=umd_db, source_store=None, settings=_client_settings())
    with TestClient(app) as client:
        r = client.post(
            "/v1/entities",
            json={
                "ref": "entity:canonical:zephyr:1",
                "display_label": "Zephyr",
                "canonical_type": "character",
                "aliases": ["Zeph"],
                "memberships": {
                    "source_ids": ["src:c"],
                    "work_ids": [],
                    "continuity_ids": [],
                },
                "state": "CONFIRMED",
                "authority": "operator",
            },
            headers=W,
        )
        assert r.status_code == 201, r.text
    _build_search(umd_db)
    svc = SearchService(umd_db)
    # Global search finds Zephyr (its own source doc) AND the cast canonicals.
    assert svc.exact("Zephyr").total >= 1
    # Source C scoped search finds Zephyr (in C's membership).
    assert svc.exact("Zephyr", SearchFilters(source_id="src:c")).total >= 1
    # Source A (the cast's source) scoped search EXCLUDES Zephyr — unrelated scope.
    assert svc.exact("Zephyr", SearchFilters(source_id=sid)).total == 0


def test_search_work_scoped_includes_only_in_scope(umd_db: sa.Engine) -> None:
    """P2-S2: work-scoped canonical search returns only canonicals whose replay-derived
    work membership intersects the requested work scope."""
    work = str(uuid.uuid4())
    app = create_app(engine=umd_db, source_store=None, settings=_client_settings())
    with TestClient(app) as client:
        r = client.post(
            "/v1/entities",
            json={
                "ref": "entity:canonical:workbound:2",
                "display_label": "WorkCloak",
                "canonical_type": "character",
                "aliases": [],
                "memberships": {
                    "work_ids": [work],
                    "source_ids": ["src:w"],
                    "continuity_ids": [],
                },
                "state": "CONFIRMED",
                "authority": "operator",
            },
            headers=W,
        )
        assert r.status_code == 201, r.text
    _build_search(umd_db)
    svc = SearchService(umd_db)
    assert svc.exact("WorkCloak").total >= 1
    assert svc.exact("WorkCloak", SearchFilters(work_id=work)).total >= 1
    assert svc.exact("WorkCloak", SearchFilters(work_id=str(uuid.uuid4()))).total == 0


def test_reconciler_mentor_of_becomes_typed_related_to(umd_db: sa.Engine) -> None:
    """P2-S4: a valid MENTOR_OF relationship is emitted as a typed RELATED_TO carrying
    the normalized relationship_type, through the ledger and edge projection, and is
    queryable by relationship_type."""
    _composer, sid, _refs = _build_cast(umd_db)
    alice = _canonical_by_label(umd_db, "Alice")
    carol = _canonical_by_label(umd_db, "Carol")
    seg = SegmentEvidenceRef(locator="source://s1/rel/1", evidence_ref="ev:rel:1")
    gb = GeneratedBy(path="deterministic", config_digest="cfg@1")
    analysis = SemanticAnalysisResult(
        source_id=sid,
        generated_by=gb,
        relationships=[
            RelationshipCandidate(
                subject_ref=alice,
                predicate="MENTOR_OF",
                object_ref=carol,
                confidence=0.9,
                segment=seg,
                generated_by=gb,
            )
        ],
    )
    res = ResolutionBatch(
        source_id=sid,
        canonical_entities=[
            CanonicalEntity(ref=alice, label=alice, source_id=sid),
            CanonicalEntity(ref=carol, label=carol, source_id=sid),
        ],
    )
    events = SemanticReconciler().reconcile(
        ReconciliationInput(source_id=sid, analysis=analysis, resolution=res)
    )
    typed = [e for e in events if e.payload["predicate_code"] == "RELATED_TO"]
    assert len(typed) == 1
    assert typed[0].payload["relationship_type"] == "MENTOR_OF"
    assert typed[0].payload["subject_ref"] == alice
    assert typed[0].payload["object_ref"] == carol
    SemanticLedger(umd_db).append(typed)
    store = ProjectionCheckpointStore(umd_db)
    ReplayDriver(umd_db, store).run(ActiveSemanticEdgeProjectionBuilder(), wipe=True)
    q = QueryService(umd_db)
    by_type = q.relationship_edges(
        StructuredQuery(kind="RELATIONSHIP_EDGES", filters={"relationship_type": "MENTOR_OF"})
    )
    assert by_type.total >= 1
    h = by_type.results[0]
    assert h.predicate == "RELATED_TO"
    assert h.data.get("relationship_type") == "MENTOR_OF"
    assert h.value == carol  # object endpoint preserved
    # A different relationship_type filters it out.
    none = q.relationship_edges(
        StructuredQuery(kind="RELATIONSHIP_EDGES", filters={"relationship_type": "SIBLING_OF"})
    )
    assert all(
        r.predicate != "RELATED_TO" or r.data.get("relationship_type") != "MENTOR_OF"
        for r in none.results
    )


def test_reconciler_related_to_requires_valid_type(umd_db: sa.Engine) -> None:
    """P2-S4: RELATED_TO without a validated relationship_type is evidence-only."""
    _composer, sid, _refs = _build_cast(umd_db)
    alice = _canonical_by_label(umd_db, "Alice")
    carol = _canonical_by_label(umd_db, "Carol")
    seg = SegmentEvidenceRef(locator="source://s1/rel/2", evidence_ref="ev:rel:2")
    gb = GeneratedBy(path="deterministic", config_digest="cfg@1")
    analysis = SemanticAnalysisResult(
        source_id=sid,
        generated_by=gb,
        relationships=[
            RelationshipCandidate(
                subject_ref=alice,
                predicate="RELATED_TO",
                object_ref=carol,
                confidence=0.9,
                segment=seg,
                generated_by=gb,
            )
        ],
    )
    res = ResolutionBatch(
        source_id=sid,
        canonical_entities=[
            CanonicalEntity(ref=alice, label=alice, source_id=sid),
            CanonicalEntity(ref=carol, label=carol, source_id=sid),
        ],
    )
    events = SemanticReconciler().reconcile(
        ReconciliationInput(source_id=sid, analysis=analysis, resolution=res)
    )
    # No RELATED_TO assertion is fabricated for a type-less generic relationship.
    assert all(e.payload["predicate_code"] != "RELATED_TO" for e in events)


def test_registry_immutable_mentor_of_not_registered() -> None:
    """P2-S4: promoting MENTOR_OF to a typed RELATED_TO does NOT mutate the trusted
    vocabulary — MENTOR_OF is not a registered predicate, so payloads cannot forge one."""
    assert is_known_predicate("MENTOR_OF") is False
    assert is_known_predicate("RELATED_TO") is True
    assert is_known_predicate("SIBLING_OF") is True


def test_scoped_search_replay_equality(umd_db: sa.Engine) -> None:
    """P2-S2 / replay equality: wipe-and-replay of the search projection (force_resume)
    yields byte-identical membership-scoped search documents — the disposable,
    deterministically-rebuildable non-authoritative store."""
    _composer, _sid, _refs = _build_cast(umd_db)
    app = create_app(engine=umd_db, source_store=None, settings=_client_settings())
    with TestClient(app) as client:
        assert (
            client.post(
                "/v1/entities",
                json={
                    "ref": "entity:canonical:replay:1",
                    "display_label": "ReplayRune",
                    "canonical_type": "character",
                    "aliases": ["Rune"],
                    "memberships": {
                        "source_ids": ["src:r"],
                        "work_ids": [],
                        "continuity_ids": [],
                    },
                    "state": "CONFIRMED",
                    "authority": "operator",
                },
                headers=W,
            ).status_code
            == 201
        )
    _build_search(umd_db)
    docs = search_document

    def _snapshot() -> set[tuple[str, str, str, str, str | None, str | None, str | None]]:
        with umd_db.connect() as conn:
            rows = conn.execute(
                sa.select(
                    docs.c.ref,
                    docs.c.kind,
                    docs.c.text,
                    docs.c.entity_ref,
                    docs.c.source_id,
                    docs.c.work_id,
                    docs.c.continuity_id,
                )
            ).fetchall()
        return {(str(r[0]), str(r[1]), str(r[2]), str(r[3]), r[4], r[5], r[6]) for r in rows}

    first = _snapshot()
    # Deterministic wipe-and-replay rebuild (force_resume acknowledges authority events).
    _build_search(umd_db)
    second = _snapshot()
    assert first == second
    assert len(first) == len(second)  # no drift, no duplicates after rebuild
    # The source-scoped canonical doc is present and correctly scoped.
    assert any(r[2] == "ReplayRune" and r[4] == "src:r" for r in second)
