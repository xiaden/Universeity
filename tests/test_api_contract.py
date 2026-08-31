"""P3-S5: public-contract API contract tests for the versioned REST boundary.

Exercises the FastAPI app built by :func:`umd.api.app.create_app` over the live
Postgres ledger + OCFL store (``postgres``-marked). The smoke flow covers the full
public contract: ingest, job polling, structured + semantic query (typed ops, never
unstructured-only RAG), source-native locator retrieval, correction (segment edit),
token-bearing reads, both consistency failures (``transient-lag`` and
``rebuild-in-progress``), cursor pagination, and RFC 7807 structured errors. Auth
(API key / bearer) and real per-key/IP rate limiting are asserted directly.

Projections are rebuilt explicitly with the Tier-1 builders after semantic writes —
the API boundary never writes projection stores (that is a Phase-2 invariant).
"""

from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from resolution_helpers import insert_entity, insert_source, mention
from umd.api.app import create_app
from umd.config import AuthSettings, ConsistencySettings, RateLimitSettings, Settings
from umd.domain.evidence import EvidenceBatch
from umd.domain.models import Evidence
from umd.projections.base import ReplayDriver
from umd.projections.checkpoint import ProjectionCheckpoint, ProjectionCheckpointStore
from umd.projections.current import CurrentTierOneBuilder
from umd.projections.edges import ActiveSemanticEdgeProjectionBuilder
from umd.projections.query import QueryService
from umd.projections.search import SearchProjectionBuilder
from umd.resolution.mentions import MentionService, PostgresMentionRepository
from umd.storage.postgres.ledger import SemanticLedger
from umd.storage.postgres.repositories import PostgresEvidenceRepository
from umd.storage.postgres.tables import metadata as db_meta

pytestmark = pytest.mark.postgres

W = {"Authorization": "Bearer write-key"}  # read + write
R = {"Authorization": "Bearer read-key"}  # read-only


def _tail(engine: sa.Engine) -> int:
    with engine.connect() as conn:
        t = conn.execute(sa.text("SELECT max(seq) FROM semantic_event")).scalar()
    return int(t or 0)


def _build(engine: sa.Engine, *, force_search_resume: bool = True) -> None:
    """Replay-build every Tier-1 projection (current_tier1 + edges + search) to the tail.

    P5-S1: the search projection now reconciles BOTH the ``edge:%`` and ``assert:%``
    document families from the ACTIVE edge store on finalize (the immutable assertion
    stream is no longer a search-doc source for utterances), so the semantic_edges
    projection must be built BEFORE search for utterance/edge terms to be searchable.
    """
    store = ProjectionCheckpointStore(engine)
    ReplayDriver(engine, store).run(CurrentTierOneBuilder(), wipe=True)
    ReplayDriver(engine, store).run(ActiveSemanticEdgeProjectionBuilder(), wipe=True)
    ReplayDriver(engine, store).run(
        SearchProjectionBuilder(), wipe=True, force_resume=force_search_resume
    )


def _build_all(engine: sa.Engine, *, force_search_resume: bool = True) -> None:
    """Replay-build every Tier-1 projection including the semantic_edges store.

    The edge store is built BEFORE the search projection: the search builder's
    ``finalize`` reads the active edge store (P2-S4) so relationship-edge search hits
    are indexed from the freshly-replayed active edges.
    """
    store = ProjectionCheckpointStore(engine)
    ReplayDriver(engine, store).run(CurrentTierOneBuilder(), wipe=True)
    ReplayDriver(engine, store).run(ActiveSemanticEdgeProjectionBuilder(), wipe=True)
    ReplayDriver(engine, store).run(
        SearchProjectionBuilder(), wipe=True, force_resume=force_search_resume
    )


def _client_settings(*, rate_enabled: bool = True) -> Settings:
    return Settings(
        auth=AuthSettings(api_keys=["write-key", "read-key"], write_keys=["write-key"]),
        rate_limit=RateLimitSettings(
            enabled=rate_enabled, requests_per_window=10000, window_seconds=60.0, burst=100
        ),
        consistency=ConsistencySettings(lag_wait_multiplier=1, max_waiters=16),
        lag_budget_seconds=0.05,
    )


@pytest.fixture()
def api_ctx(umd_db: sa.Engine, source_store):
    # Hermetic runner: these contract tests exercise the full API surface with an
    # in-process durable runner (no live Hatchet cluster). The RELEASE factory
    # (runner=None) selects ProductionDAGRunner and is tested separately.
    app = create_app(
        engine=umd_db, source_store=source_store, settings=_client_settings(), runner="hermetic"
    )
    with TestClient(app) as client:
        yield SimpleNamespace(client=client, engine=umd_db, settings=app.state.ctx.settings)


# ---------------------------------------------------------------------------
# Public-contract smoke flow
# ---------------------------------------------------------------------------


def test_public_contract_smoke_flow(api_ctx) -> None:
    client, engine = api_ctx.client, api_ctx.engine
    content = "The quick brown fox jumps over the lazy dog. Sherlock Holmes investigates."

    # -- ingest -------------------------------------------------------------
    r = client.post("/v1/sources", json={"media_kind": "txt", "content": content}, headers=W)
    assert r.status_code == 201, r.text
    ingest = r.json()
    sid, sha512 = ingest["source_id"], ingest["sha512"]
    assert r.json()["ocfl_ref"] and ingest["size_bytes"] == len(content.encode())
    assert isinstance(ingest["work_id"], str) and ingest["work_id"]
    assert ingest["consistency_token"] >= 1
    with engine.connect() as conn:
        assert (
            conn.execute(
                sa.text("SELECT 1 FROM work WHERE id = :work_id"),
                {"work_id": ingest["work_id"]},
            ).scalar()
            == 1
        )

    # -- polling: ingest submitted a decomposable job ------------------------
    rj = client.get(f"/v1/jobs/job-{sid[:12]}", headers=R)
    assert rj.status_code == 200, rj.text
    assert rj.json()["status"] == "complete"

    # -- semantic content: entities + utterances ------------------------------
    assert (
        client.post(
            "/v1/entities", json={"ref": "e:hero", "label": "Sherlock"}, headers=W
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/v1/entities", json={"ref": "e:villain", "label": "Moriarty"}, headers=W
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/v1/claims",
            json={
                "predicate_code": "SPEAKS",
                "subject_ref": "e:hero",
                "object_ref": "The game is afoot, Watson",
                "confidence": 0.8,
            },
            headers=W,
        ).status_code
        == 201
    )
    token_latest = _tail(engine)
    _build(engine)

    # -- token-bearing structured query --------------------------------------
    rq = client.post(
        "/v1/query/structured",
        json={"kind": "UTTERANCE", "consistency_token": token_latest},
        headers=R,
    )
    assert rq.status_code == 200, rq.text
    qb = rq.json()
    assert any(res["value"] == "The game is afoot, Watson" for res in qb["results"])
    for result in qb["results"]:
        for key in ("provenance", "confidence", "generated_by", "capabilities"):
            assert key in result
    assert qb["bound_report"]["bounded"] is True
    assert qb["freshness"]["status"] == "fresh"
    assert qb["freshness"]["applied_seq"] >= token_latest

    # -- semantic query: typed ops, NEVER unstructured-only RAG --------------
    rs = client.post("/v1/query/semantic", json={"question": "what does e:hero say"}, headers=R)
    assert rs.status_code == 200, rs.text
    sab = rs.json()
    assert "UTTERANCE" in sab["compiled_ops"]
    # compiled from typed operations, never an unstructured-only answer path.
    assert "typed relational" in sab["provenance"]["authority"]
    answer_item = next(
        item for item in sab["answer"] if item["value"] == "The game is afoot, Watson"
    )
    for key in ("provenance", "confidence", "generated_by", "capabilities"):
        assert key in answer_item

    # -- exact search with result-kind labels --------------------------------
    rsearch = client.post("/v1/search", json={"query": "afoot", "mode": "exact"}, headers=R)
    assert rsearch.status_code == 200, rsearch.text
    s = rsearch.json()
    assert s["total"] >= 1
    assert all(h["kind"] and h["label"] for h in s["hits"])
    assert s["freshness"] is not None

    # -- source-native locator retrieval --------------------------------------
    obj_id = f"urn:umd:ocfl:source:sha512:{sha512}"
    rl = client.get(f"/v1/locators/{obj_id}?start=0&length=1000", headers=R)
    assert rl.status_code == 200, rl.text
    decoded = base64.b64decode(rl.json()["data_b64"]).decode("utf-8")
    assert decoded == content

    ru = client.post(
        "/v1/query/structured",
        json={"kind": "ENTITY", "filters": {"ref": "e:hero"}},
        headers=R,
    )
    assert ru.status_code == 200, ru.text
    assert ru.json()["freshness"] is not None

    # -- correction (segment edit) returns a read-your-writes token ----------
    rc = client.post("/v1/segments/seg-1/edit", headers=W)
    assert rc.status_code == 200, rc.text
    assert rc.json()["action"] == "edit"
    assert rc.json()["consistency_token"] >= 1
    _build(engine)
    assert (
        client.post(
            "/v1/query/structured",
            json={"kind": "UTTERANCE", "filters": {"speaker": "e:hero"}},
            headers=R,
        ).status_code
        == 200
    )

    # -- cursor pagination over a collection ----------------------------------
    rp = client.get("/v1/entities?limit=1", headers=R)
    assert rp.status_code == 200, rp.text
    p1 = rp.json()
    assert p1["total"] >= 2
    assert p1["next_cursor"] is not None
    next_cursor = p1["next_cursor"]
    rp2 = client.get(f"/v1/entities?limit=1&cursor={next_cursor}", headers=R)
    assert rp2.status_code == 200, rp2.text
    assert rp2.json()["prev_cursor"] is not None
    assert rp2.json()["items"][0]["ref"] != p1["items"][0]["ref"]


def test_public_ingest_reuses_content_addressed_source(api_ctx) -> None:
    """Duplicate bytes reuse the canonical source instead of violating uniqueness."""
    client, engine = api_ctx.client, api_ctx.engine
    content = "content-addressed duplicate"

    first = client.post(
        "/v1/sources",
        json={"media_kind": "txt", "original_name": "first.txt", "content": content},
        headers=W,
    )
    assert first.status_code == 201, first.text
    first_body = first.json()

    duplicate = client.post(
        "/v1/sources",
        json={"media_kind": "txt", "original_name": "duplicate.txt", "content": content},
        headers=W,
    )
    assert duplicate.status_code == 201, duplicate.text
    duplicate_body = duplicate.json()

    assert duplicate_body["source_id"] == first_body["source_id"]
    assert duplicate_body["work_id"] == first_body["work_id"]
    assert duplicate_body["ocfl_ref"] == first_body["ocfl_ref"]
    with engine.connect() as conn:
        assert conn.execute(sa.text("SELECT count(*) FROM source")).scalar() == 1


# ---------------------------------------------------------------------------
# Consistency: both failure modes (transient-lag, rebuild-in-progress)
# ---------------------------------------------------------------------------


def test_token_read_transient_lag_503(api_ctx) -> None:
    client, engine = api_ctx.client, api_ctx.engine
    # Advance the ledger WITHOUT building the current_tier1 projection.
    assert (
        client.post(
            "/v1/sources", json={"media_kind": "txt", "content": "lag content"}, headers=W
        ).status_code
        == 201
    )
    tail = _tail(engine)
    assert tail >= 1
    resp = client.post(
        "/v1/query/structured", json={"kind": "ENTITY", "consistency_token": tail}, headers=R
    )
    assert resp.status_code == 503, resp.text
    doc = resp.json()
    assert doc["code"] == "consistency_transient_lag"
    assert doc["retryable"] is True
    assert doc["x-consistency"] == "transient-lag"
    assert resp.headers["x-consistency"] == "transient-lag"
    assert resp.headers["retry-after"]


def test_token_read_rebuild_in_progress_503(api_ctx) -> None:
    client, engine = api_ctx.client, api_ctx.engine
    # Pin the current_tier1 projection as paused (authority rebuild in progress).
    store = ProjectionCheckpointStore(engine)
    store.save(
        ProjectionCheckpoint("current_tier1", applied_seq=0).paused(
            "authority change on e:x; projections paused until reconciled state settles", 0
        )
    )
    assert (
        client.post(
            "/v1/sources", json={"media_kind": "txt", "content": "rebuild"}, headers=W
        ).status_code
        == 201
    )
    tail = _tail(engine)
    resp = client.post(
        "/v1/query/structured", json={"kind": "ENTITY", "consistency_token": tail}, headers=R
    )
    assert resp.status_code == 503, resp.text
    doc = resp.json()
    assert doc["x-consistency"] == "rebuild-in-progress"
    assert float(resp.headers["retry-after"]) >= 30
    assert resp.headers["x-consistency"] == "rebuild-in-progress"
    assert resp.headers["x-rebuild-estimate"]


# ---------------------------------------------------------------------------
# Auth, RFC 7807 structured errors, rate limiting
# ---------------------------------------------------------------------------


def test_auth_and_rfc7807_structured_errors(api_ctx) -> None:
    client = api_ctx.client
    # Unauthenticated -> 401 problem+json.
    r = client.get("/v1/sources/x")
    assert r.status_code == 401
    assert r.headers["content-type"].startswith("application/problem+json")
    doc = r.json()
    assert doc["type"].startswith("urn:umd:problem:")
    assert doc["code"] == "unauthorized"

    # Invalid key -> 401.
    assert client.get("/v1/sources/x", headers={"Authorization": "Bearer nope"}).status_code == 401

    # Read-only key cannot write -> 403.
    r = client.post(
        "/v1/claims",
        json={"predicate_code": "SPEAKS", "subject_ref": "e:1", "object_ref": "hi"},
        headers=R,
    )
    assert r.status_code == 403
    assert r.json()["code"] == "forbidden"

    # Unknown resource -> 404 problem+json.
    r = client.get("/v1/sources/nope", headers=R)
    assert r.status_code == 404
    assert r.json()["code"] == "not_found"


def test_rate_limit_429(umd_db: sa.Engine, source_store) -> None:
    settings = Settings(
        auth=AuthSettings(api_keys=["k"], write_keys=[]),
        rate_limit=RateLimitSettings(
            enabled=True, requests_per_window=2, window_seconds=60.0, burst=0
        ),
        consistency=ConsistencySettings(lag_wait_multiplier=1, max_waiters=16),
        lag_budget_seconds=0.05,
    )
    app = create_app(engine=umd_db, source_store=source_store, settings=settings)
    h = {"Authorization": "Bearer k"}
    with TestClient(app) as client:
        for _ in range(2):
            assert client.get("/v1/version", headers=h).status_code == 200
        resp = client.get("/v1/version", headers=h)
        assert resp.status_code == 429, resp.text
        assert resp.headers["retry-after"]
        assert resp.json()["code"] == "rate_limited"
        assert resp.json()["retryable"] is True


# ---------------------------------------------------------------------------
# System: health / readiness / capabilities / version / OpenAPI (P3-S4)
# ---------------------------------------------------------------------------


def test_system_health_capabilities_version_and_openapi(api_ctx) -> None:
    client, engine = api_ctx.client, api_ctx.engine
    r = client.get("/v1/health", headers=R)
    assert r.status_code == 200
    assert r.json()["status"] in ("ok", "degraded")

    r = client.get("/v1/capabilities", headers=R)
    assert r.status_code == 200
    cap = r.json()["capabilities"]
    assert cap["query_max_depth"] == 4
    assert cap["relationships_bounded"] is True
    assert cap["semantic_authority"] == "tier0-ledger; projections never authoritative"

    # Honest capability disclosure (P3-S4): gated linkage/alignment/vector providers
    # are surfaced as gated/inactive where not installed; the reference/builtin
    # providers are reported active. Nothing is fabricated as active.
    linkage = cap["linkage"]
    assert linkage["active_provider"] == "umd-reference-linkage"
    assert linkage["splink"]["gated"] is True
    assert linkage["splink"]["active"] is False
    alignment = cap["alignment"]
    assert alignment["active_provider"] == "umd-reference-aligner"
    assert alignment["vecalign"]["gated"] is True
    vector = cap["vector"]
    assert vector["active_provider"] == "exact-fallback-in-process"
    assert vector["providers"]["exact_fallback"]["active"] is True
    assert vector["providers"]["pgvector_hnsw"]["active"] is False

    r = client.get("/v1/version", headers=R)
    assert r.status_code == 200
    assert r.json()["contract_version"] == "1.0.0"
    assert r.json()["api_version"] == "v1"

    # Complementary ready path: with both Tier-1 projections built to the tail,
    # /v1/ready is deterministically 200. The paused rebuild-in-progress 503 is a
    # separate deterministic test (test_ready_rebuild_in_progress_503_is_deterministic).
    _build(engine)
    r = client.get("/v1/ready", headers=R)
    assert r.status_code == 200
    assert r.json()["status"] == "ready"

    r = client.get("/openapi.json", headers=R)
    assert r.status_code == 200
    paths = r.json()["paths"]
    for p in (
        "/v1/sources",
        "/v1/query/structured",
        "/v1/query/semantic",
        "/v1/search",
        "/v1/entities",
        "/v1/claims",
        "/v1/audit/{subject}",
        "/v1/health",
    ):
        assert p in paths


def test_ready_rebuild_in_progress_503_is_deterministic(api_ctx) -> None:
    """A real paused current_tier1 checkpoint makes /v1/ready deterministically 503.

    The previous assertion was nondeterministic (`assert status in (200, 503)`).
    Here the projection controller's pause mechanism (a real paused checkpoint)
    drives the 503 deterministically: HTTP 503, RFC 7807 `code=not_ready`,
    `retryable=true`, `x-consistency: rebuild-in-progress`, and `Retry-After` at or
    above the configured rebuild bound.
    """
    client, engine = api_ctx.client, api_ctx.engine
    store = ProjectionCheckpointStore(engine)
    store.save(
        ProjectionCheckpoint("current_tier1", applied_seq=0).paused(
            "qa: authority rebuild in progress; /v1/ready must be a deterministic 503", 0
        )
    )
    try:
        r = client.get("/v1/ready", headers=R)
        assert r.status_code == 503, r.text
        doc = r.json()
        assert doc["code"] == "not_ready"
        assert doc["retryable"] is True
        assert doc["x-consistency"] == "rebuild-in-progress"
        assert "rebuild" in doc["detail"].lower()
        configured = api_ctx.settings.consistency.rebuild_retry_after
        assert configured >= 30.0  # DD rebuild bound
        assert float(doc["retry_after"]) >= configured
        assert float(r.headers["retry-after"]) >= configured
        assert r.headers["x-consistency"] == "rebuild-in-progress"
    finally:
        # Cleanup: restore a resumed checkpoint so the paused posture is removed.
        store.save(ProjectionCheckpoint("current_tier1", applied_seq=0).resumed())


# ---------------------------------------------------------------------------
# Phase 4: structured-query scope filters (P4-S4)
# ---------------------------------------------------------------------------


def _scenes(api_ctx, payload: dict) -> list[str]:
    r = api_ctx.client.post("/v1/query/structured", json={"kind": "SCENE", **payload}, headers=R)
    assert r.status_code == 200, r.text
    return [res["ref"] for res in r.json()["results"]]


def test_structured_query_scope_filters(api_ctx) -> None:
    """Continuity/temporal/spatial scope narrow results; all-scope-absent is unfiltered;
    unmappable scope is an explicit 422 (never silently ignored)."""
    client, engine = api_ctx.client, api_ctx.engine

    cont1 = str(uuid.uuid4())
    cont2 = str(uuid.uuid4())
    wid = str(uuid.uuid4())
    seg_a, seg_b, seg_c = (str(uuid.uuid4()) for _ in range(3))
    sid1 = insert_source(engine)
    sid2 = insert_source(engine)
    _cont, _work, _src, _seg = (
        db_meta.tables["continuity"],
        db_meta.tables["work"],
        db_meta.tables["source"],
        db_meta.tables["segment"],
    )
    with engine.begin() as conn:
        conn.execute(_work.insert().values(id=wid, title="T", work_type="book"))
        conn.execute(_cont.insert().values(id=cont1, work_id=wid, name="MCU"))
        conn.execute(_cont.insert().values(id=cont2, work_id=wid, name="Elsewhere"))
        conn.execute(_src.update().where(_src.c.id == sid1).values(continuity_id=cont1))
        conn.execute(_src.update().where(_src.c.id == sid2).values(continuity_id=cont2))
        conn.execute(
            _seg.insert().values(
                id=seg_a,
                source_id=sid1,
                segment_type="scene",
                deterministic_key="a",
                locator="loc:a",
                ordinal=1,
                start_time=datetime(2026, 1, 1, 10, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 1, 10, 5, tzinfo=UTC),
                metadata_={"spatial": {"region": "panel-1"}},
            )
        )
        conn.execute(
            _seg.insert().values(
                id=seg_b,
                source_id=sid1,
                segment_type="scene",
                deterministic_key="b",
                locator="loc:b",
                ordinal=2,
                start_time=datetime(2026, 1, 1, 11, 0, tzinfo=UTC),
                end_time=datetime(2026, 1, 1, 11, 5, tzinfo=UTC),
                metadata_={"spatial": {"region": "panel-3"}},
            )
        )
        conn.execute(
            _seg.insert().values(
                id=seg_c,
                source_id=sid2,
                segment_type="scene",
                deterministic_key="c",
                locator="loc:c",
                ordinal=1,
            )
        )

    # All-scope-absent stays unfiltered.
    assert set(_scenes(api_ctx, {})) == {seg_a, seg_b, seg_c}

    # Continuity filter returns ONLY rows of the matching continuity's source(s).
    assert set(_scenes(api_ctx, {"continuity_id": cont1})) == {seg_a, seg_b}

    # Temporal upper bound narrows to the segment whose range is <= the bound.
    assert set(_scenes(api_ctx, {"temporal_to": "2026-01-01T10:05:30Z"})) == {seg_a}

    # Mappable spatial scope narrows via indexed JSONB containment.
    assert set(_scenes(api_ctx, {"spatial": {"region": "panel-3"}})) == {seg_b}

    # An unmappable scope (current_state op has no temporal column) is an explicit 422.
    r = client.post(
        "/v1/query/structured",
        json={"kind": "ENTITY", "temporal_from": "2026-01-01T00:00:00Z"},
        headers=R,
    )
    assert r.status_code == 422, r.text
    doc = r.json()
    assert doc["code"] == "unmappable_scope"
    assert doc["type"].startswith("urn:umd:problem:")


# ---------------------------------------------------------------------------
# Phase 4: v1 MERGE/SPLIT reach the full Resolver (P4-S7)
# ---------------------------------------------------------------------------


def _mention_entity(engine: sa.Engine, mention_id: str) -> str | None:
    _mt = db_meta.tables["entity_mention"]
    with engine.connect() as conn:
        row = conn.execute(sa.select(_mt.c.entity_id).where(_mt.c.id == mention_id)).first()
    if row is None or row.entity_id is None:
        return None
    return str(row.entity_id)


def _rebound_events(engine: sa.Engine) -> list[dict]:
    _evt = db_meta.tables["semantic_event"]
    with engine.connect() as conn:
        rows = conn.execute(
            sa.select(_evt.c.payload).where(_evt.c.event_type == "ReferenceRebound")
        ).fetchall()
    return [r.payload for r in rows]


def _entity_resolved_kinds(engine: sa.Engine) -> list[str]:
    _evt = db_meta.tables["semantic_event"]
    with engine.connect() as conn:
        rows = conn.execute(
            sa.select(_evt.c.payload).where(_evt.c.event_type == "EntityResolved")
        ).fetchall()
    return [r.payload["kind"] for r in rows]


def _quarantined(engine: sa.Engine) -> list[str]:
    _q = db_meta.tables["quarantine"]
    with engine.connect() as conn:
        return [str(x) for x in conn.execute(sa.select(_q.c.locator)).scalars().all()]


def test_v1_merge_split_resolution_contract(api_ctx) -> None:
    """v1 MERGE/SPLIT reach the full Resolver: rebinding, ReferenceRebound, quarantine,
    and append-only auditable ledger history — not just an event append."""
    client, engine = api_ctx.client, api_ctx.engine

    ent_a = insert_entity(engine, label="A")  # composite entity
    ent_b = insert_entity(engine, label="B")
    ent_c = insert_entity(engine, label="C")
    ent_x = insert_entity(engine, label="X")
    sid = insert_source(engine)

    svc = MentionService(
        ledger=SemanticLedger(engine), repository=PostgresMentionRepository(engine)
    )
    _, m1 = svc.record(
        mention(
            source_id=sid, entity_id=ent_a, text="Alex", candidates=[(ent_b, 0.9), (ent_c, 0.1)]
        )
    )
    _, m2 = svc.record(
        mention(source_id=sid, entity_id=ent_a, text="lex", candidates=[(ent_c, 0.8)])
    )
    _, m3 = svc.record(
        mention(source_id=sid, entity_id=ent_a, text="???", candidates=[(ent_x, 0.5)])
    )

    # -- SPLIT via the REST boundary ----------------------------------------
    r = client.post(f"/v1/entities/{ent_a}/split?targets={ent_b}&targets={ent_c}", headers=W)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["action"] == "split"
    assert body["consistency_token"] >= 1
    # The REST path reached mention rebinding (not just an event append).
    assert _mention_entity(engine, m1) == ent_b
    assert _mention_entity(engine, m2) == ent_c
    # Ambiguity is quarantined, never silently dropped.
    assert m3 in _quarantined(engine)
    # Every reassignment emitted a ReferenceRebound event.
    rebounds = _rebound_events(engine)
    assert {x["reference"] for x in rebounds} == {m1, m2}
    assert {x["to_entity"] for x in rebounds} == {ent_b, ent_c}
    # Append-only EntityResolved(SPLIT) audit event.
    assert "SPLIT" in _entity_resolved_kinds(engine)

    # -- MERGE via the REST boundary ----------------------------------------
    r2 = client.post(f"/v1/entities/{ent_b}/merge?target_entity_ref={ent_a}", headers=W)
    assert r2.status_code == 200, r2.text
    mbody = r2.json()
    assert mbody["action"] == "merge"
    assert mbody["consistency_token"] >= 1
    assert "MERGE" in _entity_resolved_kinds(engine)
    # MERGE is append-only / reversible: the source mention survives with candidates.
    got = PostgresMentionRepository(engine).get(m1)
    assert got is not None
    assert {c.entity_ref for c in got.candidates} == {ent_b, ent_c}
    # No entity row was deleted by merge/split (reversible history).
    with engine.connect() as conn:
        n = conn.execute(sa.select(sa.func.count()).select_from(db_meta.tables["entity"])).scalar()
    assert n == 4


# ---------------------------------------------------------------------------
# Phase 4: segment-scoped evidence retrieval (P4-S9)
# ---------------------------------------------------------------------------


def test_v1_segment_evidence_is_scoped(api_ctx) -> None:
    """GET /v1/segments/{id}/evidence returns that segment's evidence, not another
    segment's, and not empty solely because the segment ID differs from the source ID."""
    client, engine = api_ctx.client, api_ctx.engine

    sid1 = insert_source(engine)
    sid2 = insert_source(engine)
    _seg = db_meta.tables["segment"]
    seg1, seg2 = str(uuid.uuid4()), str(uuid.uuid4())
    with engine.begin() as conn:
        conn.execute(
            _seg.insert().values(
                id=seg1,
                source_id=sid1,
                segment_type="scene",
                deterministic_key="k1#1",
                locator=f"source://s1/{seg1}",
                ordinal=1,
            )
        )
        conn.execute(
            _seg.insert().values(
                id=seg2,
                source_id=sid2,
                segment_type="scene",
                deterministic_key="k2#1",
                locator=f"source://s2/{seg2}",
                ordinal=1,
            )
        )

    repo = PostgresEvidenceRepository(engine)
    repo.record(
        EvidenceBatch(
            records=[
                Evidence(
                    source_id=uuid.UUID(sid1),
                    segment_id=uuid.UUID(seg1),
                    evidence_kind="subtitle_event",
                    locator="l1",
                    confidence=0.9,
                    config_digest="d1",
                ),
                Evidence(
                    source_id=uuid.UUID(sid2),
                    segment_id=uuid.UUID(seg2),
                    evidence_kind="subtitle_event",
                    locator="l2",
                    confidence=0.5,
                    config_digest="d2",
                ),
            ]
        )
    )

    r = client.get(f"/v1/segments/{seg1}/evidence", headers=R)
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert len(items) == 1
    assert items[0]["segment_id"] == seg1
    assert items[0]["source_id"] == sid1
    assert items[0]["locator"] == "l1"
    # Never another segment's evidence, never empty due to an id mismatch.
    assert items[0]["segment_id"] != seg2
    assert items[0]["source_id"] != sid2

    # Unknown segment -> RFC 7807 404.
    r2 = client.get("/v1/segments/nope/evidence", headers=R)
    assert r2.status_code == 404
    assert r2.json()["code"] == "not_found"


# ---------------------------------------------------------------------------
# /v1/metrics endpoint + records wiring (QA R1 issue #7)
# ---------------------------------------------------------------------------


def test_metrics_endpoint_reports_registry_and_honest_otel_gate(api_ctx) -> None:
    """GET /v1/metrics exposes the registry snapshot and reports the honest OTel
    gate (false unless UMD_OTEL_ENABLED is set and opentelemetry is importable)."""
    import umd.observability.records as records
    from umd.observability.metrics import MetricRegistry

    client = api_ctx.client

    reg = MetricRegistry()
    old = records.METRICS
    records.METRICS = reg
    try:
        records.record_503(origin="transient-lag")
        r = client.get("/v1/metrics", headers=R)
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["service"] == "universeity-umd"
        assert "metrics" in body
        # A genuine 503 record is visible in the served snapshot.
        assert body["metrics"]["http.503"][0]["value"] == 1
        # Honest gate: OTel export is NOT fabricated active when the env is off.
        assert body["otel_export_active"] is False
        assert "UMD_OTEL_ENABLED + opentelemetry-sdk" in body["otel_gate"]
    finally:
        records.METRICS = old


def test_genuine_503_increments_http_503_counter(api_ctx) -> None:
    """A real transient-lag 503 increments the `http.503` counter (boundary assert)."""
    import umd.observability.records as records
    from umd.observability.metrics import MetricRegistry

    client, engine = api_ctx.client, api_ctx.engine
    reg = MetricRegistry()
    old = records.METRICS
    records.METRICS = reg
    try:
        # Advance the ledger without building the current_tier1 projection.
        assert (
            client.post(
                "/v1/sources", json={"media_kind": "txt", "content": "lag for metric"}, headers=W
            ).status_code
            == 201
        )
        tail = _tail(engine)
        resp = client.post(
            "/v1/query/structured", json={"kind": "ENTITY", "consistency_token": tail}, headers=R
        )
        assert resp.status_code == 503, resp.text
        assert resp.json()["x-consistency"] == "transient-lag"
        # The genuine 503 recorded exactly one http.503 counter increment.
        assert reg.snapshot()["http.503"][0]["value"] == 1
    finally:
        records.METRICS = old


def test_app_factory_builds_wired_app_over_real_postgres(
    umd_db: sa.Engine, monkeypatch, tmp_path
) -> None:
    """app_factory() (zero-arg ASGI entrypoint) wires a working app over the live
    configured Postgres + OCFL store from environment.

    Proves the CONFIGURED DSN and OCFL root reach the running app — not only
    static health/version responses: a real ingest also writes source bytes to the
    configured OCFL root and a source row to the configured Postgres DSN.
    """
    from umd.api.entrypoints import app_factory
    from umd.storage.ocfl import SourceStore

    ocfl_root = tmp_path / "ocfl"
    SourceStore.create(root=ocfl_root)  # bootstrap the OCFL root the app will use
    monkeypatch.setenv("UMD_POSTGRES__DSN", umd_db.url.render_as_string(hide_password=False))
    monkeypatch.setenv("UMD_OCFL__ROOT", str(ocfl_root))
    # Auth keys default to empty (bearer auth disabled -> anonymous read+write).

    app = app_factory()
    with TestClient(app) as client:
        r = client.get("/v1/health", headers=R)
        assert r.status_code == 200
        assert r.json()["status"] in ("ok", "degraded")
        r = client.get("/v1/version", headers=R)
        assert r.status_code == 200
        assert r.json()["api_version"] == "v1"

        # Configured Postgres DSN wiring: the app engine targets the migrated test
        # database (not the 127.0.0.1 default) and answers a live query.
        engine = app.state.ctx.engine
        assert engine.url.database == umd_db.url.database
        assert engine.url.database != "umd"
        with engine.connect() as conn:
            assert conn.exec_driver_sql("SELECT 1").scalar() == 1

        # Configured OCFL root wiring: a real ingest writes source bytes under the
        # configured root and commits the source row to the configured DSN.
        # Release factory wires ProductionDAGRunner (never a test-only double).
        from umd.jobs.runner import ProductionDAGRunner

        assert isinstance(app.state.ctx.jobs._runner, ProductionDAGRunner)  # noqa: SLF001

        # A real ingest writes source bytes to the configured OCFL root and commits a
        # source row to the configured DSN. Without a live Hatchet scheduler the
        # release factory honestly refuses dispatch (500 dispatch_failed) rather than
        # fabricating completion, while the pre-dispatch OCFL/source-row side effects
        # are committed.
        resp = client.post("/v1/sources", json={"media_kind": "txt", "content": "wired app"})
        assert resp.status_code == 500, resp.text
        assert resp.json()["code"] == "dispatch_failed"
        assert list(ocfl_root.rglob("inventory.json")), "no OCFL object under configured root"
        with engine.connect() as conn:
            row = conn.execute(sa.text("SELECT sha512, ocfl_ref FROM source")).first()
        assert row is not None and row[0] and row[1]


def test_build_source_store_uses_configured_ocfl_root(tmp_path) -> None:
    """Production wiring bootstraps a fresh configured OCFL root."""
    from umd.api.entrypoints import build_source_store
    from umd.config import OcflSettings, Settings

    root = tmp_path / "ocfl"
    settings = Settings(ocfl=OcflSettings(root=root))
    store = build_source_store(settings)
    assert store.root == root
    assert (root / "0=ocfl_1.1").exists()


def test_build_source_store_rejects_non_empty_non_ocfl_root(tmp_path) -> None:
    """Production bootstrap remains fail-closed for an invalid volume."""
    from umd.api.entrypoints import build_source_store
    from umd.config import OcflSettings, Settings
    from umd.storage.ocfl import StoreError

    root = tmp_path / "ocfl"
    root.mkdir()
    (root / "unexpected.txt").write_text("not OCFL", encoding="utf-8")
    with pytest.raises(StoreError):
        build_source_store(Settings(ocfl=OcflSettings(root=root)))


# ---------------------------------------------------------------------------
# P1-S2: spec-first production ingestion through the public route (Phase 3)
# ---------------------------------------------------------------------------


def test_spec_first_production_ingestion_persists_real_output(api_ctx) -> None:
    """SPEC-FIRST (FAILS until Phase 3 wires production dispatch).

    Ingest non-empty representative source bytes through the public POST
    /v1/sources route, poll a NON-fake (Postgres-backed) job, and verify persisted
    segments, evidence, semantic events, provenance refs, and queryable state —
    WITHOUT explicitly rebuilding projections and WITHOUT calling internal
    modality services. Today the fake path (InMemoryJobStore + SynchronousRunner
    + ``work_registry={}``) reports a fake complete job with no persisted output,
    so this test fails by design until Phase 3 replaces it.
    """
    client, engine = api_ctx.client, api_ctx.engine
    content = "Sherlock Holmes examined the room. The candle flickered.\n" * 3

    # -- public ingest ------------------------------------------------------
    r = client.post("/v1/sources", json={"media_kind": "txt", "content": content}, headers=W)
    assert r.status_code == 201, r.text
    sid = r.json()["source_id"]
    job_id = f"job-{sid[:12]}"

    # -- poll the durable (non-fake) job to a terminal state -----------------
    status = "running"
    for _ in range(20):
        rj = client.get(f"/v1/jobs/{job_id}", headers=R)
        status = rj.json()["status"]
        if status in ("complete", "failed", "cancelled"):
            break
    assert status == "complete", f"job did not reach complete (got {status})"

    # -- persisted segments through the public route ------------------------
    segs = client.get(f"/v1/sources/{sid}/segments", headers=R)
    assert segs.status_code == 200, segs.text
    assert segs.json()["total"] >= 1, "no segments persisted through the public route"

    # -- persisted evidence, queryable per-segment ---------------------------
    first_seg = segs.json()["items"][0]["segment_id"]
    ev = client.get(f"/v1/segments/{first_seg}/evidence", headers=R)
    assert ev.status_code == 200, ev.text
    assert ev.json()["total"] >= 1, "no evidence persisted through the public route"

    # -- semantic events + provenance refs committed to the ledger ----------
    with engine.connect() as conn:
        stage_events = conn.execute(
            sa.text(
                "SELECT count(*) FROM semantic_event "
                "WHERE event_type='StageCompleted' AND payload->>'source_id'=:s"
            ),
            {"s": sid},
        ).scalar()
    assert stage_events >= 1, "no StageCompleted semantic event persisted for the source"
    with engine.connect() as conn:
        n_seg = conn.execute(
            sa.text("SELECT count(*) FROM segment WHERE source_id=:s"), {"s": sid}
        ).scalar()
        n_ev = conn.execute(
            sa.text("SELECT count(*) FROM evidence WHERE source_id=:s"), {"s": sid}
        ).scalar()
    assert n_seg >= 1 and n_ev >= 1, "ledger/registry rows missing for decomposed source"

    # -- queryable structured state WITHOUT a projection rebuild -------------
    q = client.post(
        "/v1/query/structured", json={"kind": "SCENE", "filters": {"source_id": sid}}, headers=R
    )
    assert q.status_code == 200, q.text
    assert q.json()["total"] >= 1, "no queryable structured state from decomposed output"


# ---------------------------------------------------------------------------
# P1-S4(e): submission failure is reported, never swallowed (Phase 3)
# ---------------------------------------------------------------------------


def test_submission_failure_is_reported_not_swallowed(api_ctx) -> None:
    """SPEC-FIRST (FAILS until Phase 3): when decomposition dispatch fails, the API
    must surface it as a structured RFC 7807 error or a durable failed job — never
    return a successful fake completion or swallow the exception. Today the ingest
    route swallows submission exceptions and returns 201, so this fails by design.
    """
    client = api_ctx.client
    ctx = client.app.state.ctx

    def boom(**_kwargs):  # type: ignore[no-untyped-def]
        raise RuntimeError("dispatch backend unavailable")

    ctx.jobs.submit = boom  # type: ignore[method-assign]
    r = client.post(
        "/v1/sources", json={"media_kind": "txt", "content": "failing submission"}, headers=W
    )
    # Not a successful fake completion; the failure is surfaced to the client.
    assert r.status_code != 201, r.text
    doc = r.json()
    assert doc.get("type", "").startswith("urn:umd:problem:") or r.status_code in (
        409,
        500,
        502,
        503,
    )


# ---------------------------------------------------------------------------
# P3-S3: deterministic stage quarantine maps to a structured RFC 7807 422
# ---------------------------------------------------------------------------


def test_stage_quarantined_422_rfc7807_shape(api_ctx) -> None:
    """A deterministic stage quarantine surfaces as an RFC 7807 422 with
    code='stage_quarantined' (non-retryable), never a generic 500.

    ``_dispatch`` maps :class:`StageQuarantinedError` to an ``ApiError`` with
    status 422 / ``retryable=False``; the error handlers serialize it to a
    ``application/problem+json`` body whose ``type`` is a ``urn:umd:problem:``
    URI and whose ``retryable`` flag is ``False``.
    """
    from umd.jobs.stage_execution import StageQuarantinedError

    client = api_ctx.client
    ctx = client.app.state.ctx

    def quarantine(**_kwargs):  # type: ignore[no-untyped-def]
        raise StageQuarantinedError("INGEST", "malformed source", "source:x")

    ctx.jobs.submit = quarantine  # type: ignore[method-assign]
    r = client.post("/v1/sources", json={"media_kind": "txt", "content": "quarantined"}, headers=W)
    assert r.status_code == 422, r.text
    doc = r.json()
    assert doc["code"] == "stage_quarantined"
    assert doc["type"].startswith("urn:umd:problem:")
    assert doc["retryable"] is False


# ---------------------------------------------------------------------------
# P3-S2: bounded-upload enforcement (RFC 7807 413) + multipart forms
# ---------------------------------------------------------------------------


def test_upload_too_large_413_rejected_before_storage(api_ctx) -> None:
    """An oversize bounded upload is an RFC 7807 413 ``upload_too_large``
    (non-retryable) raised BEFORE any OCFL / source-row storage side effect.
    """
    client, engine = api_ctx.client, api_ctx.engine
    api_ctx.settings.limits.max_upload_bytes = 5  # tiny bound for the test
    r = client.post(
        "/v1/sources",
        json={"media_kind": "txt", "content": "this is longer than five bytes"},
        headers=W,
    )
    assert r.status_code == 413, r.text
    doc = r.json()
    assert doc["code"] == "upload_too_large"
    assert doc["type"].startswith("urn:umd:problem:")
    assert doc["retryable"] is False
    # Rejected up-front: no source row was committed for the oversize payload.
    with engine.connect() as conn:
        n = conn.execute(sa.text("SELECT count(*) FROM source")).scalar()
    assert n == 0, "oversize upload must be rejected before any storage side effect"


def test_multipart_upload_ingest_and_job_completes(api_ctx) -> None:
    """Multipart/form-data upload (P3-S2): a small txt ``file`` part ingests to
    201 with a source_id, and its job reaches a terminal complete state."""
    client = api_ctx.client
    r = client.post(
        "/v1/sources",
        files={"file": ("sample.txt", b"hello world", "text/plain")},
        data={"media_kind": "txt"},
        headers=W,
    )
    assert r.status_code == 201, r.text
    sid = r.json()["source_id"]
    assert sid
    job_id = f"job-{sid[:12]}"
    status = "running"
    for _ in range(20):
        rj = client.get(f"/v1/jobs/{job_id}", headers=R)
        status = rj.json()["status"]
        if status in ("complete", "failed", "cancelled"):
            break
    assert status == "complete", f"multipart job did not reach complete (got {status})"


def test_multipart_missing_file_422(api_ctx) -> None:
    """A multipart/form-data upload with no ``file`` part is an explicit RFC 7807
    422 (code='missing_file'), never a silent fallback to the inline-JSON path."""
    client = api_ctx.client
    boundary = "xumd-test-boundary"
    body = (
        f"--{boundary}\r\n"
        'Content-Disposition: form-data; name="media_kind"\r\n\r\n'
        "txt\r\n"
        f"--{boundary}--\r\n"
    ).encode()
    r = client.post(
        "/v1/sources",
        content=body,
        headers={**W, "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "missing_file"


# ---------------------------------------------------------------------------
# QA R2 M1: route-level smoke tests for cancel / retry / rerun (P3-S3)
# ---------------------------------------------------------------------------
# Service-level cancel/retry/rerun behavior is already covered in
# tests/test_production_runner.py; these exercise the HTTP contract surface
# (2xx bodies + RFC 7807 failure shape) that was previously untested.


def test_route_cancel_returns_200_and_job_reflects_cancelled(api_ctx) -> None:
    """POST /v1/jobs/{job_id}/cancel -> 200 with action=cancel, and the job's
    durable aggregate status reflects cancelled."""
    client = api_ctx.client
    r = client.post("/v1/sources", json={"media_kind": "txt", "content": "cancel me"}, headers=W)
    assert r.status_code == 201, r.text
    sid = r.json()["source_id"]
    job_id = f"job-{sid[:12]}"

    rc = client.post(f"/v1/jobs/{job_id}/cancel", headers=W)
    assert rc.status_code == 200, rc.text
    body = rc.json()
    assert body["action"] == "cancel"
    assert body["job_id"] == job_id

    rj = client.get(f"/v1/jobs/{job_id}", headers=R)
    assert rj.status_code == 200, rj.text
    assert rj.json()["status"] == "cancelled"


def test_route_retry_returns_200_and_job_reaches_terminal_state(api_ctx) -> None:
    """POST /v1/jobs/{job_id}/retry -> 200 with action=retry, and the retried job
    lands in a terminal state consistent with the real-registry behavior (all
    stages already committed -> complete)."""
    client = api_ctx.client
    r = client.post("/v1/sources", json={"media_kind": "txt", "content": "retry me"}, headers=W)
    assert r.status_code == 201, r.text
    sid = r.json()["source_id"]
    job_id = f"job-{sid[:12]}"

    rr = client.post(f"/v1/jobs/{job_id}/retry", headers=W)
    assert rr.status_code == 200, rr.text
    assert rr.json()["action"] == "retry"
    assert rr.json()["job_id"] == job_id

    status = "running"
    for _ in range(20):
        rj = client.get(f"/v1/jobs/{job_id}", headers=R)
        status = rj.json()["status"]
        if status in ("complete", "failed", "cancelled"):
            break
    assert status == "complete", f"retried job did not reach a terminal state (got {status})"


def test_route_segment_rerun_returns_202_and_ancestors_untouched(api_ctx) -> None:
    """POST /v1/segments/{segment_id}/rerun -> 202, and descendant-only
    invalidation is not contradicted: upstream/ancestor stage_run counts are
    untouched (the rerun schedules only the transitive descendants of
    LOW_LEVEL_EXTRACTION). The route's ``segment_id`` path param is interpreted
    by ``rerun_stage`` as a ``source_id`` (see src/umd/api/routers/segments.py),
    so we pass a real source id to exercise the descendant scheduler against the
    committed source rather than a segment row."""
    client, engine = api_ctx.client, api_ctx.engine
    r = client.post(
        "/v1/sources",
        json={"media_kind": "txt", "content": "Sherlock Holmes examined the room"},
        headers=W,
    )
    assert r.status_code == 201, r.text
    sid = r.json()["source_id"]
    job_id = f"job-{sid[:12]}"

    rr = client.post(f"/v1/segments/{sid}/rerun", headers=W)
    assert rr.status_code == 202, rr.text
    assert rr.json()["action"] == "rerun"
    assert rr.json()["job_id"] == job_id

    status = "running"
    for _ in range(20):
        rj = client.get(f"/v1/jobs/{job_id}", headers=R)
        status = rj.json()["status"]
        if status in ("complete", "failed", "cancelled"):
            break
    assert status == "complete", f"rerun job did not reach a terminal state (got {status})"

    with engine.connect() as conn:
        rows = conn.execute(
            sa.text(
                "SELECT stage_name, count(*) AS n FROM stage_run "
                "WHERE job_id=:j GROUP BY stage_name"
            ),
            {"j": job_id},
        ).fetchall()
    counts = {str(row.stage_name): int(row.n) for row in rows}
    # Ancestors (INGEST..LOW_LEVEL_EXTRACTION) were not re-scheduled by the rerun.
    for ancestor in ("INGEST", "FORMAT_ANALYSIS", "BASIC_SEGMENTATION", "LOW_LEVEL_EXTRACTION"):
        assert counts.get(ancestor, 0) == 1, (
            f"ancestor {ancestor} re-scheduled by descendant-only rerun: {counts}"
        )


def test_route_unknown_job_returns_rfc7807_404(api_ctx) -> None:
    """Unknown job id on cancel/retry surfaces as an RFC 7807 problem
    (urn:umd:problem:) 404, not a swallowed or generic error."""
    client = api_ctx.client
    for path in ("/v1/jobs/job-unknown/cancel", "/v1/jobs/job-unknown/retry"):
        r = client.post(path, headers=W)
        assert r.status_code == 404, (path, r.text)
        doc = r.json()
        assert doc.get("type", "").startswith("urn:umd:problem:"), (path, doc)
        assert doc.get("code") == "not_found", (path, doc)


def test_release_factory_never_constructs_test_doubles(umd_db, source_store) -> None:
    """Plan K P1-S2: the release API factory selects ProductionDAGRunner and never
    constructs SynchronousRunner / InMemoryJobStore / the hermetic DurableDAGRunner."""
    from umd.api.runner import SynchronousRunner
    from umd.jobs.job import InMemoryJobStore
    from umd.jobs.runner import DurableDAGRunner, ProductionDAGRunner
    from umd.storage.postgres.job_repository import PostgresJobRepository

    app = create_app(engine=umd_db, source_store=source_store, settings=_client_settings())
    ctx = app.state.ctx
    store = ctx.extra["job_store"]
    runner = ctx.jobs._runner  # noqa: SLF001
    assert isinstance(store, PostgresJobRepository)
    assert not isinstance(store, InMemoryJobStore)
    assert isinstance(runner, ProductionDAGRunner)
    assert not isinstance(runner, DurableDAGRunner)
    assert not isinstance(runner, SynchronousRunner)
    assert ctx.extra.get("production_wired") is True


# ---------------------------------------------------------------------------
# P3-S4: public relationship-edge surface (structured query, search, question)
# ---------------------------------------------------------------------------


def _seed_entities(client) -> None:
    for ref, label in (("e:hero", "Sherlock"), ("e:villain", "Moriarty")):
        r = client.post("/v1/entities", json={"ref": ref, "label": label}, headers=W)
        assert r.status_code == 201, r.text


def test_public_relationship_edges_query_returns_active_edges_with_provenance(api_ctx) -> None:
    """P3-S4: the PUBLIC structured query answers RELATIONSHIP_EDGES with every
    active edge plus provenance — via /v1/query/structured over real Postgres."""
    client, engine = api_ctx.client, api_ctx.engine
    content = "The quick brown fox jumps over the lazy dog."
    assert (
        client.post(
            "/v1/sources", json={"media_kind": "txt", "content": content}, headers=W
        ).status_code
        == 201
    )
    _seed_entities(client)
    for obj in ("The game is afoot, Watson", "The game is afoot, Watson again"):
        assert (
            client.post(
                "/v1/claims",
                json={
                    "predicate_code": "SPEAKS",
                    "subject_ref": "e:hero",
                    "object_ref": obj,
                    "confidence": 0.8,
                },
                headers=W,
            ).status_code
            == 201
        )
    token = _tail(engine)
    _build_all(engine)

    rq = client.post(
        "/v1/query/structured",
        json={
            "kind": "RELATIONSHIP_EDGES",
            "filters": {"subject": "e:hero", "predicate": "SPEAKS"},
            "consistency_token": token,
        },
        headers=R,
    )
    assert rq.status_code == 200, rq.text
    page = rq.json()
    assert page["total"] == 2  # multi-edge: both utterances active
    assert {h["value"] for h in page["results"]} == {
        "The game is afoot, Watson",
        "The game is afoot, Watson again",
    }
    for h in page["results"]:
        assert h["capabilities"]["edge"] is True
        assert h["provenance"]["fact_id"]
        assert h["provenance"]["state"]
        assert h["provenance"]["seq"] >= 1
        assert h["confidence"] is not None
    assert page["bound_report"]["bounded"] is True
    assert page["freshness"]["status"] == "fresh"
    assert page["freshness"]["applied_seq"] >= token


def test_public_relationship_edges_no_stale_after_override(api_ctx) -> None:
    """P3-S4: after an operator override the public relationship read never serves
    the stale superseded edge — only the new active edge is returned."""
    client, engine = api_ctx.client, api_ctx.engine
    content = "The quick brown fox jumps over the lazy dog."
    assert (
        client.post(
            "/v1/sources", json={"media_kind": "txt", "content": content}, headers=W
        ).status_code
        == 201
    )
    _seed_entities(client)
    assert (
        client.post(
            "/v1/claims",
            json={
                "predicate_code": "SPEAKS",
                "subject_ref": "e:hero",
                "object_ref": "original line",
                "confidence": 0.8,
            },
            headers=W,
        ).status_code
        == 201
    )
    _build_all(engine)
    r1 = client.post(
        "/v1/query/structured",
        json={
            "kind": "RELATIONSHIP_EDGES",
            "filters": {"subject": "e:hero", "predicate": "SPEAKS"},
        },
        headers=R,
    ).json()
    assert {h["value"] for h in r1["results"]} == {"original line"}

    # Operator override supersedes the machine edge.
    assert (
        client.post(
            "/v1/claims/e:hero/override",
            json={
                "predicate_code": "SPEAKS",
                "object_ref": "corrected line",
                "reason": "correction",
            },
            headers=W,
        ).status_code
        == 200
    )
    _build_all(engine)
    r2 = client.post(
        "/v1/query/structured",
        json={
            "kind": "RELATIONSHIP_EDGES",
            "filters": {"subject": "e:hero", "predicate": "SPEAKS"},
        },
        headers=R,
    ).json()
    assert {h["value"] for h in r2["results"]} == {"corrected line"}
    assert "original line" not in {h["value"] for h in r2["results"]}


def test_public_relationship_edges_bounded_pagination(api_ctx) -> None:
    """P3-S4: the public relationship read honors bounded depth/pagination and
    never leaks superseded edges into the active page."""
    client, engine = api_ctx.client, api_ctx.engine
    content = "The quick brown fox jumps over the lazy dog."
    assert (
        client.post(
            "/v1/sources", json={"media_kind": "txt", "content": content}, headers=W
        ).status_code
        == 201
    )
    _seed_entities(client)
    for i in range(4):
        assert (
            client.post(
                "/v1/claims",
                json={
                    "predicate_code": "SPEAKS",
                    "subject_ref": "e:hero",
                    "object_ref": f"line {i}",
                    "confidence": 0.8,
                },
                headers=W,
            ).status_code
            == 201
        )
    _build_all(engine)

    def page(offset: int) -> dict:
        return client.post(
            "/v1/query/structured",
            json={
                "kind": "RELATIONSHIP_EDGES",
                "filters": {"subject": "e:hero", "predicate": "SPEAKS"},
                "limit": 2,
                "offset": offset,
            },
            headers=R,
        ).json()

    p0, p1, p2 = page(0), page(2), page(4)
    assert p0["total"] == 4
    assert len(p0["results"]) == 2 and len(p1["results"]) == 2 and len(p2["results"]) == 0
    values = {h["value"] for h in p0["results"]} | {h["value"] for h in p1["results"]}
    assert values == {"line 0", "line 1", "line 2", "line 3"}


def test_search_surfaces_relationship_edge_results_gap(api_ctx) -> None:
    """P3-S4: search surfaces active relationship edges as result-kind-labelled hits.

    A relationship edge (HAS_EMOTION) whose object text appears nowhere in the source
    content is retrievable by search because SearchProjectionBuilder indexes the active
    edge store (non-utterance predicates) as INTERPRETATION hits carrying an ``edge``
    capability, so the relationship object term is searchable with provenance.
    """
    client, engine = api_ctx.client, api_ctx.engine
    content = "The quick brown fox jumps over the lazy dog."
    assert (
        client.post(
            "/v1/sources", json={"media_kind": "txt", "content": content}, headers=W
        ).status_code
        == 201
    )
    _seed_entities(client)
    # A non-utterance relationship edge with a distinctive object term.
    assert (
        client.post(
            "/v1/claims",
            json={
                "predicate_code": "HAS_EMOTION",
                "subject_ref": "e:hero",
                "object_ref": "hopeful-dawn",
                "confidence": 0.6,
            },
            headers=W,
        ).status_code
        == 201
    )
    _build_all(engine)

    rs = client.post("/v1/search", json={"query": "hopeful-dawn", "mode": "exact"}, headers=R)
    assert rs.status_code == 200, rs.text
    body = rs.json()
    assert body["total"] >= 1, (
        "search did not surface the active HAS_EMOTION relationship edge "
        "(SearchService must return relationship-edge results per plan P2-S4/P3-S4)"
    )
    assert any(
        "edge" in (h.get("capabilities") or {}) or h["kind"] == "INTERPRETATION"
        for h in body["hits"]
    )


def test_semantic_question_draws_on_active_edges_gap(api_ctx) -> None:
    """P3-S4: a semantic question about a relationship is answered from the ACTIVE
    relationship edges. QuestionService compiles the relationship question to the
    RELATIONSHIP_EDGES typed op (never unstructured-only RAG) and returns the CO_OCCURS
    active edge as a provenance-bearing answer item.
    """
    client, engine = api_ctx.client, api_ctx.engine
    content = "The quick brown fox jumps over the lazy dog."
    assert (
        client.post(
            "/v1/sources", json={"media_kind": "txt", "content": content}, headers=W
        ).status_code
        == 201
    )
    _seed_entities(client)
    assert (
        client.post(
            "/v1/claims",
            json={
                "predicate_code": "CO_OCCURS",
                "subject_ref": "e:hero",
                "object_ref": "e:villain",
                "confidence": 0.6,
            },
            headers=W,
        ).status_code
        == 201
    )
    _build_all(engine)

    rs = client.post(
        "/v1/query/semantic",
        json={"question": "what is the relationship between e:hero and e:villain"},
        headers=R,
    )
    assert rs.status_code == 200, rs.text
    sab = rs.json()
    assert "RELATIONSHIP_EDGES" in sab["compiled_ops"], (
        "semantic question did not compile to a RELATIONSHIP_EDGES read; "
        "QuestionService must answer relationship questions from active edges "
        "(per plan P2-S4/P3-S4)"
    )
    assert any(
        item.get("predicate") == "CO_OCCURS" and item.get("value") == "e:villain"
        for item in sab["answer"]
    ), "answer must draw on the active CO_OCCURS edge"


def test_edge_derived_reads_gate_on_edge_guard(api_ctx) -> None:
    """P4-S1: RELATIONSHIP_EDGES structured reads and relationship semantic questions are
    gated on the ``semantic_edges`` ``edge_guard`` (not only the scalar ``query_guard``).

    When ``current_tier1`` is fresh but the edge store trails the token, a token-bearing
    edge read 503s (``transient-lag``) while a non-edge read served by ``query_guard``
    passes — the edge-derived read must not be served from a lagging edge store.
    """
    client, engine = api_ctx.client, api_ctx.engine

    assert (
        client.post(
            "/v1/claims",
            json={
                "predicate_code": "HAS_EMOTION",
                "subject_ref": "e:hero",
                "object_ref": "term-one",
                "confidence": 0.6,
            },
            headers=W,
        ).status_code
        == 201
    )
    _build_all(engine)

    # A second assertion advances the ledger.
    assert (
        client.post(
            "/v1/claims",
            json={
                "predicate_code": "HAS_EMOTION",
                "subject_ref": "e:villain",
                "object_ref": "term-two",
                "confidence": 0.6,
            },
            headers=W,
        ).status_code
        == 201
    )
    # Catch current_tier1 up to the tail but leave semantic_edges + search lagging.
    store = ProjectionCheckpointStore(engine)
    ReplayDriver(engine, store).run(CurrentTierOneBuilder(), wipe=False)
    token = _tail(engine)  # ledger seq current_tier1 has reached; edges have not.

    # Non-edge read gated on query_guard (current_tier1 fresh) passes with the token.
    r = client.post(
        "/v1/query/structured",
        json={"kind": "ENTITY", "filters": {"ref": "e:hero"}, "consistency_token": token},
        headers=R,
    )
    assert r.status_code == 200, r.text

    # Edge-derived structured read gated on edge_guard (edges lagging) -> 503 transient-lag.
    r = client.post(
        "/v1/query/structured",
        json={
            "kind": "RELATIONSHIP_EDGES",
            "filters": {"subject": "e:hero"},
            "consistency_token": token,
        },
        headers=R,
    )
    assert r.status_code == 503, r.text
    assert r.json()["x-consistency"] == "transient-lag"

    # Relationship semantic question gated on edge_guard -> 503 transient-lag.
    r = client.post(
        "/v1/query/semantic",
        json={
            "question": "what is the relationship between e:hero and e:villain",
            "consistency_token": token,
        },
        headers=R,
    )
    assert r.status_code == 503, r.text
    assert r.json()["x-consistency"] == "transient-lag"


def test_public_search_no_stale_utterance_after_override(api_ctx) -> None:
    """P5-S2: the public ``/v1/search`` surface returns ZERO hits for a superseded
    SPEAKS utterance and >=1 for the corrected value (search_guard-gated), so a stale
    post-correction utterance is never served — while token-bearing RELATIONSHIP_EDGES
    reads for SPEAKS remain ``edge_guard``-gated (never the scalar query_guard).
    """
    client, engine = api_ctx.client, api_ctx.engine
    content = "The quick brown fox jumps over the lazy dog."
    assert (
        client.post(
            "/v1/sources", json={"media_kind": "txt", "content": content}, headers=W
        ).status_code
        == 201
    )
    _seed_entities(client)
    assert (
        client.post(
            "/v1/claims",
            json={
                "predicate_code": "SPEAKS",
                "subject_ref": "e:hero",
                "object_ref": "stale-line",
                "confidence": 0.8,
            },
            headers=W,
        ).status_code
        == 201
    )
    _build_all(engine)
    rs = client.post("/v1/search", json={"query": "stale-line", "mode": "exact"}, headers=R)
    assert rs.status_code == 200, rs.text
    assert rs.json()["total"] >= 1

    # Operator override supersedes the SPEAKS utterance on the active edge store.
    assert (
        client.post(
            "/v1/claims/e:hero/override",
            json={
                "predicate_code": "SPEAKS",
                "object_ref": "corrected-line",
                "reason": "correction",
            },
            headers=W,
        ).status_code
        == 200
    )
    _build_all(engine)

    # The public search surface returns ZERO for the superseded utterance text and
    # >=1 for the corrected value, carrying search_guard-gated freshness.
    rs_stale = client.post("/v1/search", json={"query": "stale-line", "mode": "exact"}, headers=R)
    assert rs_stale.status_code == 200, rs_stale.text
    assert rs_stale.json()["total"] == 0, (
        "stale superseded utterance remained searchable after override"
    )
    rs_new = client.post("/v1/search", json={"query": "corrected-line", "mode": "exact"}, headers=R)
    assert rs_new.status_code == 200, rs_new.text
    assert rs_new.json()["total"] >= 1
    assert rs_new.json()["freshness"] is not None
    # The corrected hit is the INTERPRETATION ``assert:{fact_id}`` doc (not stale source
    # evidence), indexed from the active edge store.
    assert any(h["kind"] == "INTERPRETATION" for h in rs_new.json()["hits"])


def test_speaks_edge_reads_gate_on_edge_guard(api_ctx) -> None:
    """P5-S2: SPEAKS is an utterance predicate that lives on the active edge store too,
    so token-bearing RELATIONSHIP_EDGES reads for SPEAKS gate on ``edge_guard`` (not only
    the scalar ``query_guard``). When current_tier1 is fresh but semantic_edges trails,
    a token-bearing SPEAKS RELATIONSHIP_EDGES read 503s transient-lag.
    """
    client, engine = api_ctx.client, api_ctx.engine
    assert (
        client.post(
            "/v1/claims",
            json={
                "predicate_code": "SPEAKS",
                "subject_ref": "e:hero",
                "object_ref": "utter-one",
                "confidence": 0.8,
            },
            headers=W,
        ).status_code
        == 201
    )
    _build_all(engine)

    # A second SPEAKS assertion advances the ledger.
    assert (
        client.post(
            "/v1/claims",
            json={
                "predicate_code": "SPEAKS",
                "subject_ref": "e:villain",
                "object_ref": "utter-two",
                "confidence": 0.8,
            },
            headers=W,
        ).status_code
        == 201
    )
    # Catch current_tier1 up to the tail but leave semantic_edges + search lagging.
    store = ProjectionCheckpointStore(engine)
    ReplayDriver(engine, store).run(CurrentTierOneBuilder(), wipe=False)
    token = _tail(engine)  # ledger seq current_tier1 has reached; edges have not.

    # Non-edge read gated on query_guard passes with the token.
    r = client.post(
        "/v1/query/structured",
        json={"kind": "ENTITY", "filters": {"ref": "e:hero"}, "consistency_token": token},
        headers=R,
    )
    assert r.status_code == 200, r.text

    # SPEAKS RELATIONSHIP_EDGES read gated on edge_guard (edges lagging) -> 503.
    r = client.post(
        "/v1/query/structured",
        json={
            "kind": "RELATIONSHIP_EDGES",
            "filters": {"subject": "e:hero", "predicate": "SPEAKS"},
            "consistency_token": token,
        },
        headers=R,
    )
    assert r.status_code == 503, r.text
    assert r.json()["x-consistency"] == "transient-lag"


# ---------------------------------------------------------------------------
# P3-S2: 'The Lantern Keeper' book fixture through the PUBLIC HTTP boundary —
# deterministic reads + provider-seam aliases/traits with honest gating.
# ---------------------------------------------------------------------------


def test_phase3_book_http_public_reads_deterministic(api_ctx) -> None:
    """Ingest the book fixture through public HTTP, poll durable job state, then
    read scenes/utterances/relationship-edges/evidence via public query routes.

    >=3 distinct characters are proven via the relationship-edge subjects (Mara,
    Ellis, Orin deterministically PRESENT_IN/MENTIONED_IN); the narrator's
    non-confirmed (ambiguous) statement is never promoted to an authoritative /
    conflicting claim; search for character/trait/relationship text honestly
    returns 0 (deterministic semantic refs are content-hash UUIDs — a documented
    production gap, never fabricated).
    """
    from fixtures import semantic_book_bytes

    client, engine = api_ctx.client, api_ctx.engine

    r = client.post(
        "/v1/sources",
        files={"file": ("lantern.txt", semantic_book_bytes("txt"), "text/plain")},
        data={"media_kind": "txt"},
        headers=W,
    )
    assert r.status_code == 201, r.text
    sid = r.json()["source_id"]
    job_id = f"job-{sid[:12]}"
    status = "running"
    for _ in range(40):
        rj = client.get(f"/v1/jobs/{job_id}", headers=R)
        status = rj.json()["status"]
        if status in ("complete", "failed", "cancelled"):
            break
    assert status == "complete", f"book job did not reach complete (got {status})"
    _build_all(engine)  # API never writes projection stores; rebuild like the suite does

    # -- scenes: >=2 chapters + >=2 sections -> >=3 structural SCENE hits (txt)
    sc = client.post(
        "/v1/query/structured", json={"kind": "SCENE", "filters": {"source_id": sid}}, headers=R
    )
    assert sc.status_code == 200, sc.text
    assert sc.json()["total"] >= 3, "expected >=3 structural scenes from the 2-chapter book"

    # -- utterances: SPEAKS attribution is deterministically asserted
    ut = client.post("/v1/query/structured", json={"kind": "UTTERANCE", "limit": 50}, headers=R)
    assert ut.status_code == 200, ut.text
    assert ut.json()["total"] >= 1, "no SPEAKS utterance surfaced via public route"
    assert any(h["predicate"] == "SPEAKS" for h in ut.json()["results"])

    # -- >=3 distinct characters via relationship-edge subjects (public reads)
    re_ = client.post(
        "/v1/query/structured", json={"kind": "RELATIONSHIP_EDGES", "limit": 100}, headers=R
    )
    assert re_.status_code == 200, re_.text
    assert re_.json()["total"] >= 1
    char_subjects = {
        h["ref"] for h in re_.json()["results"] if h["predicate"] in ("MENTIONED_IN", "PRESENT_IN")
    }
    assert len(char_subjects) >= 3, (
        "expected >=3 distinct characters deterministically present (Mara/Ellis/Orin)"
    )

    # -- evidence with locators + provenance via public route
    ev = client.post(
        "/v1/query/structured",
        json={"kind": "EVIDENCE", "filters": {"source_id": sid}, "limit": 100},
        headers=R,
    )
    assert ev.status_code == 200, ev.text
    ev_hits = ev.json()["results"]
    assert ev.json()["total"] >= 1
    # evidence is retrieved with locators + provenance (source_id anchor + locator).
    # Normalize UUID dashes: the ingest `sid` is non-dashed hex, the DB round-trip
    # provenance source_id is dashed — same id, different string form.
    assert any(
        (h.get("provenance", {}).get("source_id") or "").replace("-", "") == sid
        and h.get("provenance", {}).get("locator")
        for h in ev_hits
    )

    # -- ambiguous (narrator-never-confirmed) statement is NOT authoritative:
    #    no CONFLICTING / CONFIRMED claim is reachable. Deterministic reconciliation
    #    never asserts the watchtower-light claim (it stays narration text_span).
    co = client.post("/v1/query/structured", json={"kind": "CONTRADICTIONS"}, headers=R)
    assert co.status_code == 200, co.text
    assert co.json()["total"] == 0, "ambiguous fact must not surface as a contradiction"

    # -- POSITIVE assertion (QA R1): the ambiguous watchtower-light fact IS present
    #    as a narration text_span EVIDENCE row (locator + source provenance) but is
    #    NEVER promoted by a SemanticAsserted ledger event. Deterministic
    #    reconciliation never asserts the light as authoritative — the statement is
    #    evidence (narrator-never-confirmed narration), not a promoted fact.
    #    (a) a narration evidence row corresponds to the watchtower statement.
    wt = client.post(
        "/v1/query/structured",
        json={"kind": "EVIDENCE", "filters": {"source_id": sid}, "limit": 200},
        headers=R,
    )
    assert wt.status_code == 200, wt.text
    assert any(
        h.get("predicate") == "text_span"  # EVIDENCE hits expose kind in ``predicate``
        and h.get("provenance", {}).get("locator")
        and (h.get("provenance", {}).get("source_id") or "").replace("-", "") == sid
        for h in wt.json()["results"]
    ), "watchtower narration must surface as evidence with locator + provenance"
    # (b) no SemanticAsserted ledger event for this source promotes the claim.
    _evt_wt = db_meta.tables["semantic_event"]
    _evid_wt = db_meta.tables["evidence"]
    with engine.connect() as conn:
        wt_span = conn.execute(
            sa.select(_evid_wt.c.locator, _evid_wt.c.source_id).where(
                _evid_wt.c.source_id == str(uuid.UUID(sid)),
                _evid_wt.c.evidence_kind == "text_span",
                _evid_wt.c.quality["text"].astext.contains("whether it had been real"),
            )
        ).first()
        assert wt_span is not None and wt_span.locator, (
            "watchtower narration text_span evidence must be persisted (locator + source)"
        )
        promoted = (
            conn.execute(
                sa.select(_evt_wt.c.seq).where(
                    _evt_wt.c.event_type == "SemanticAsserted",
                    _evt_wt.c.correlation_id
                    == str(uuid.uuid5(uuid.NAMESPACE_URL, f"umd-job:{job_id}")),
                    sa.or_(
                        _evt_wt.c.payload["subject_ref"].astext.contains("light"),
                        _evt_wt.c.payload["object_ref"].astext.contains("light"),
                        _evt_wt.c.payload["predicate_code"].astext.contains("light"),
                    ),
                )
            )
            .scalars()
            .all()
        )
    assert not promoted, "no SemanticAsserted event may promote the watchtower-light claim"

    # -- search for character/trait/relationship text: honest deterministic result.
    #    Deterministic semantic refs are content-hash UUIDs (no display names) and
    #    trait/alias observations are not produced, so these searches return 0.
    for term in ("Mara", "siblings", "moss-green"):
        rs = client.post(
            "/v1/search", json={"query": term, "mode": "exact", "source_id": sid}, headers=R
        )
        assert rs.status_code == 200, rs.text
        assert rs.json()["total"] == 0, f"search '{term}' must be 0 deterministically"


def test_phase3_book_provider_aliases_and_traits_through_production_seam(
    umd_db: sa.Engine, source_store
) -> None:
    """Register a test SemanticProvider into the production runtime (the SAME seam
    ``build_context`` wires) and prove the provider-backed analyzer runs through the
    real production stage, committing alias + trait observations as durable evidence
    with provider provenance. Phase 3 lockstep: the provider observations now flow
    through the ``_reconciliation_input`` seam, so the provider aliases/traits are
    POSITIVELY retrievable through the public read surfaces (relationship edges +
    search) — while the canonical-entity surface (ENTITY) honestly stays empty
    because this fixture emits no ``EntityResolved`` events (provider aliases surface
    as KNOWN_AS/ALIAS_OF edges, never fabricated canonical rows).
    """
    from fixtures import semantic_book_bytes
    from semantic_parity_oracle import FakeSemanticProvider

    app = create_app(
        engine=umd_db, source_store=source_store, settings=_client_settings(), runner="hermetic"
    )
    ctx = app.state.ctx
    composer = ctx.extra["work_registry"]["STRUCTURAL_ANALYSIS"].__self__
    fake = FakeSemanticProvider()
    composer._runtime.providers.register(fake)
    ctx.settings.semantic.provider = "fake_semantic"
    ctx.settings.semantic.model = "qwen-test"

    with TestClient(app) as client:
        r = client.post(
            "/v1/sources",
            files={"file": ("lantern.txt", semantic_book_bytes("txt"), "text/plain")},
            data={"media_kind": "txt"},
            headers=W,
        )
        assert r.status_code == 201, r.text
        sid = r.json()["source_id"]
        job_id = f"job-{sid[:12]}"
        status = "running"
        for _ in range(40):
            rj = client.get(f"/v1/jobs/{job_id}", headers=R)
            status = rj.json()["status"]
            if status in ("complete", "failed", "cancelled"):
                break
        assert status == "complete", f"provider book job did not reach complete (got {status})"

    # provider genuinely invoked through the production seam (real model request)
    assert fake.calls, "fake semantic provider was never invoked"
    assert fake.calls[0].input_refs, "provider call must be anchored to input locators"

    # provider observations committed as durable evidence with provider provenance
    with umd_db.connect() as c:
        rows = c.execute(
            sa.text(
                "SELECT locator, tool_versions, quality FROM evidence "
                "WHERE source_id=:s AND quality->>'kind'='semantic_observations'"
            ),
            {"s": sid},
        ).fetchall()
    assert rows, "no provider semantic-observation evidence committed"
    tv = rows[0][1]
    assert tv.get("provider") == "fake_semantic"  # provider provenance on evidence
    obs = rows[0][2]["observations"]
    assert obs, "provider observations must carry at least one observation"
    gb = obs[0]["generated_by"]
    assert gb.get("path") == "provider" and gb.get("provider") == "fake_semantic"

    # the model-call record carries the provider's alias + trait output: >=2
    # aliases (Moss->Mara, the apprentice->Mara, the cartographer->Ellis, the
    # warden->Orin) and >=2 traits (moss-green eyes, grey beard).
    aliases: set[tuple[str, str]] = set()
    traits: set[tuple[str, str]] = set()
    with umd_db.connect() as c:
        mrows = c.execute(
            sa.text(
                "SELECT quality FROM evidence WHERE source_id=:s "
                "AND evidence_kind='metadata' AND tool_versions ? 'provider'"
            ),
            {"s": sid},
        ).fetchall()
    for (qq,) in mrows:
        out = qq.get("output") or {}
        for a in out.get("aliases", []):
            aliases.add((a["alias"], a["canonical_name"]))
        for t in out.get("traits", []):
            traits.add((t["entity"], t["trait"]))
    assert len(aliases) >= 2, f"provider aliases missing (got {sorted(aliases)})"
    assert len(traits) >= 2, f"provider traits missing (got {sorted(traits)})"

    # Phase 3 lockstep: provider observations now flow through the seam. Rebuild the
    # Tier-1 projections via the sanctioned replay path so the provider-backed
    # assertions are positively visible through the public read surfaces.
    _build_all(umd_db)

    with TestClient(app) as client:
        # POSITIVE: provider aliases/traits are retrievable as relationship edges.
        re_ = client.post(
            "/v1/query/structured",
            json={"kind": "RELATIONSHIP_EDGES", "limit": 200},
            headers=R,
        )
        assert re_.status_code == 200, re_.text
        by_pred: dict[str, set[str]] = {}
        for h in re_.json()["results"]:
            by_pred.setdefault(h["predicate"], set()).add(h["value"])
        assert "the apprentice" in by_pred.get("KNOWN_AS", set()), (
            "provider alias must now be visible as a KNOWN_AS edge"
        )
        assert "moss-green eyes" in by_pred.get("HAS_TRAIT", set()), (
            "provider trait must now be visible as a HAS_TRAIT edge"
        )
        assert "ALIAS_OF" in by_pred

        # ENTITY stays honestly empty: the book fixture emits no EntityResolved
        # events, so current_state has no CANONICAL_ENTITY rows. This is honest
        # non-promotion (never a fabricated pass) — the provider aliases surface as
        # KNOWN_AS/ALIAS_OF edges asserted above.
        ent = client.post("/v1/query/structured", json={"kind": "ENTITY", "limit": 50}, headers=R)
        assert ent.status_code == 200, ent.text
        assert ent.json()["total"] == 0, (
            "no EntityResolved events -> no CANONICAL_ENTITY rows (honest non-promotion)"
        )

        # POSITIVE search: the provider edge docs are indexed with the display text
        # (ref=edge:<fact_id> => derived from the active edge store, not a fabricated
        # source). They carry no source_id (content-addressable edge docs), so the
        # search must be asserted WITHOUT the source filter; a source-scoped search
        # honestly stays 0 because the edge docs are not source-scoped.
        sr = client.post("/v1/search", json={"query": "apprentice", "mode": "exact"}, headers=R)
        assert sr.status_code == 200, sr.text
        assert sr.json()["total"] >= 1, "provider alias must now be searchable"
        ahit = sr.json()["hits"][0]
        assert ahit["kind"] == "INTERPRETATION" and ahit["label"] == "interpretation"
        assert ahit["text"] == "the apprentice" and ahit["ref"].startswith("edge:"), ahit
        mg = client.post("/v1/search", json={"query": "moss-green", "mode": "exact"}, headers=R)
        assert mg.json()["total"] >= 1, "provider trait must now be searchable"
        assert mg.json()["hits"][0]["text"] == "moss-green eyes"

        # Honest non-promotion preserved: 'siblings' (unsupported predicate, stays
        # evidence-only) and 'Mara' (canonical ref is content-hash, not display text)
        # remain non-searchable.
        for term in ("siblings", "Mara"):
            r0 = client.post("/v1/search", json={"query": term, "mode": "exact"}, headers=R)
            assert r0.status_code == 200, r0.text
            assert r0.json()["total"] == 0, f"'{term}' must stay non-searchable (honest gap)"


def _provider_book(umd_db, source_store, provider) -> tuple[Any, str, Any, Any]:
    """Build the hermetic API app with ``provider`` registered into the production
    runtime, ingest 'The Lantern Keeper', and run the full job to completion.
    Returns ``(app, sid, provider, ctx)``."""
    from fixtures import semantic_book_bytes

    app = create_app(
        engine=umd_db, source_store=source_store, settings=_client_settings(), runner="hermetic"
    )
    ctx = app.state.ctx
    composer = ctx.extra["work_registry"]["STRUCTURAL_ANALYSIS"].__self__
    composer._runtime.providers.register(provider)
    ctx.settings.semantic.provider = provider.name
    ctx.settings.semantic.model = "lantern-qwen"
    with TestClient(app) as client:
        r = client.post(
            "/v1/sources",
            files={"file": ("lantern.txt", semantic_book_bytes("txt"), "text/plain")},
            data={"media_kind": "txt"},
            headers=W,
        )
        assert r.status_code == 201, r.text
        sid = r.json()["source_id"]
        job_id = f"job-{sid[:12]}"
        status = "running"
        for _ in range(40):
            rj = client.get(f"/v1/jobs/{job_id}", headers=R)
            status = rj.json()["status"]
            if status in ("complete", "failed", "cancelled"):
                break
        assert status == "complete", f"provider book job did not reach complete (got {status})"
    return app, sid, provider, ctx


# ---------------------------------------------------------------------------
# P3-S4 — provider-backed answers through the public semantic-question surface
# (QuestionService typed operations: relationship / entity / evidence).
# ---------------------------------------------------------------------------


def test_phase3_book_provider_semantic_questions_public_surface(
    umd_db: sa.Engine, source_store
) -> None:
    from test_reconciliation_provider_promotion import _LanternProvider

    provider = _LanternProvider()
    app, sid, provider, ctx = _provider_book(umd_db, source_store, provider)
    assert len(provider.calls) == 1, "provider must be invoked exactly once"
    _build_all(umd_db)

    with TestClient(app) as client:
        # -- relationship question draws on the ACTIVE edge store (edge_guard gated).
        re_ = client.post(
            "/v1/query/structured",
            json={"kind": "RELATIONSHIP_EDGES", "limit": 200},
            headers=R,
        )
        assert re_.status_code == 200, re_.text
        known = next(h for h in re_.json()["results"] if h["predicate"] == "KNOWN_AS")
        subj, obj = known["ref"], known["value"]
        rel_q = f"relationship between {subj} and {obj}"
        assert ctx.question.requires_edge_guard(rel_q), "relationship question must use edge_guard"
        q = client.post(
            "/v1/query/semantic",
            json={"question": rel_q, "constraints": {"limit": 20}},
            headers=R,
        )
        assert q.status_code == 200, q.text
        j = q.json()
        assert j["compiled_ops"] == ["RELATIONSHIP_EDGES"]
        assert len(j["answer"]) >= 1, "relationship question returned no provider-backed edge"
        a = j["answer"][0]
        assert a["predicate"] == "KNOWN_AS" and a["value"] == obj
        assert a["confidence"] == known["confidence"], "provider confidence lost in question"
        assert "SOURCE_EVIDENCE" in j["result_kind_labels"]

        # -- entity question surfaces the provider alias via hybrid alternatives.
        q2 = client.post(
            "/v1/query/semantic",
            json={"question": "who is the apprentice", "constraints": {"limit": 20}},
            headers=R,
        )
        j2 = q2.json()
        assert "SEARCH_HYBRID" in j2["compiled_ops"]
        assert any(
            alt["value"] == "the apprentice" and alt["kind"] == "INTERPRETATION"
            for alt in j2["alternatives"]
        ), "provider alias must surface as a hybrid alternative"

        # -- evidence question is bounded and result-kind labelled.
        q3 = client.post(
            "/v1/query/semantic",
            json={"question": "evidence", "constraints": {"limit": 3}},
            headers=R,
        )
        j3 = q3.json()
        assert j3["compiled_ops"] == ["EVIDENCE"]
        assert len(j3["answer"]) <= 3, "evidence question must be bounded by limit"
        assert j3["answer"], "evidence question returned nothing"
        assert all(a["kind"] == "SOURCE_EVIDENCE" for a in j3["answer"])


# ---------------------------------------------------------------------------
# P3-S5 — provider edge/search documents become visible ONLY after the existing
# active-edge replay + search freshness gates; SearchProjectionBuilder is the sole
# search writer; correction rebuilds remove stale provider documents.
# ---------------------------------------------------------------------------


def test_phase3_book_provider_search_after_replay_and_freshness_gates(
    umd_db: sa.Engine, source_store
) -> None:
    from test_reconciliation_provider_promotion import _LanternProvider

    provider = _LanternProvider()
    app, sid, provider, ctx = _provider_book(umd_db, source_store, provider)

    with TestClient(app) as client:
        # BEFORE the search projection replay: no provider edge docs are searchable.
        mg = client.post("/v1/search", json={"query": "moss-green", "mode": "exact"}, headers=R)
        assert mg.status_code == 200, mg.text
        assert mg.json()["total"] == 0, (
            "provider docs must not be visible before the active-edge + search replay"
        )
    # The DAG/reconciliation wrote NO search docs directly (sole-writer invariant).
    with umd_db.connect() as c:
        assert int(c.execute(sa.text("SELECT count(*) FROM search_document")).scalar()) == 0, (
            "reconciliation must not write search documents directly"
        )

    # Build the active-edge + search projections (the freshness gate).
    _build_all(umd_db)
    with TestClient(app) as client:
        mg = client.post("/v1/search", json={"query": "moss-green", "mode": "exact"}, headers=R)
        assert mg.json()["total"] >= 1
        assert mg.json()["hits"][0]["text"] == "moss-green eyes"  # HAS_TRAIT display text
        for term, text in (("apprentice", "the apprentice"), ("resolute", "resolute")):
            r = client.post("/v1/search", json={"query": term, "mode": "exact"}, headers=R)
            assert r.json()["total"] >= 1 and r.json()["hits"][0]["text"] == text, term
        # fuzzy + hybrid modes also surface the provider edge documents.
        for mode in ("fuzzy", "hybrid"):
            fm = client.post("/v1/search", json={"query": "moss-green", "mode": mode}, headers=R)
            assert fm.status_code == 200, fm.text
            assert fm.json()["total"] >= 1, f"{mode} search missed the provider trait doc"
            assert any(h["text"] == "moss-green eyes" for h in fm.json()["hits"]), (
                f"{mode} search did not surface the HAS_TRAIT provider doc"
            )

    # SearchProjectionBuilder is the SOLE search writer: every doc kind is a builder
    # output (edge:/assert: interpretations, source evidence, canonical entities).
    with umd_db.connect() as c:
        bad = c.execute(
            sa.text(
                "SELECT count(*) FROM search_document WHERE kind NOT IN "
                "('INTERPRETATION','SOURCE_EVIDENCE','CANONICAL_ENTITY')"
            )
        ).scalar()
    assert int(bad) == 0, "search_document holds a doc kind the builder never produces"

    # Correction rebuild removes the stale provider trait document.
    re_ = QueryService(umd_db).structured({"kind": "RELATIONSHIP_EDGES", "limit": 200})
    trait = next(
        h for h in re_.results if h.predicate == "HAS_TRAIT" and h.value == "moss-green eyes"
    )
    ctx.commands.record_correction(
        subject_ref=trait.ref,
        predicate="HAS_TRAIT",
        object_ref="emerald eyes",
        prior_ref="moss-green eyes",
        actor="human",
        reason="correction",
    )
    store = ProjectionCheckpointStore(umd_db)
    ReplayDriver(umd_db, store).run(ActiveSemanticEdgeProjectionBuilder(), wipe=False)
    ReplayDriver(umd_db, store).run(SearchProjectionBuilder(), wipe=False, force_resume=True)
    with TestClient(app) as client:
        stale = client.post("/v1/search", json={"query": "moss-green", "mode": "exact"}, headers=R)
        assert stale.json()["total"] == 0, "correction rebuild must remove the stale provider doc"
        fresh = client.post("/v1/search", json={"query": "emerald", "mode": "exact"}, headers=R)
        assert fresh.json()["total"] >= 1, "correction rebuild must index the corrected doc"


# ---------------------------------------------------------------------------
# P3-S6 — evidence reads expose the original provider model-call + semantic-
# observation evidence (exact locators, content-discriminated identity, warnings,
# provenance) even when an observation is omitted from reconciliation; no public
# surface invents a human-readable reference or presents model output as authority.
# ---------------------------------------------------------------------------


def test_phase3_book_provider_evidence_reads_expose_observations_and_provenance(
    umd_db: sa.Engine, source_store
) -> None:
    from test_reconciliation_provider_promotion import _LanternProvider

    provider = _LanternProvider()
    app, sid, provider, ctx = _provider_book(umd_db, source_store, provider)
    assert len(provider.calls) == 1

    # Original provider model-call + semantic-observation evidence with provenance.
    with umd_db.connect() as c:
        rows = c.execute(
            sa.text(
                "SELECT locator, tool_versions, quality FROM evidence "
                "WHERE source_id=:s AND quality->>'kind'='semantic_observations'"
            ),
            {"s": sid},
        ).fetchall()
    assert rows, "provider semantic-observation evidence missing"
    locator, tv, quality = rows[0][0], rows[0][1], rows[0][2]
    assert tv.get("provider") == provider.name
    obs = quality["observations"]
    # Every observation carries exact segment locators + provider generated_by.
    for o in obs:
        seg = (o.get("segment") or {}).get("locator")
        assert seg and str(seg).startswith("chapter/"), "observation lost exact segment locator"
        gb = o.get("generated_by") or {}
        assert gb.get("provider") == provider.name and gb.get("path") == "provider"
    # An observation OMITTED from reconciliation (unsupported SIBLING_OF) is still
    # exposed as evidence — never fabricated into an assertion, never erased.
    preds = {o.get("predicate") for o in obs if "predicate" in o}
    assert "SIBLING_OF" in preds, "omitted-from-reconciliation observation must stay evidence"

    # Public EVIDENCE read surfaces content-addressed refs + evidence_kind capability.
    with TestClient(app) as client:
        ev = client.post(
            "/v1/query/structured",
            json={"kind": "EVIDENCE", "filters": {"source_id": sid}, "limit": 200},
            headers=R,
        )
        assert ev.status_code == 200, ev.text
        j = ev.json()
        assert j["total"] >= 1
        # Content-discriminated identity: evidence refs are content-addressed UUIDs
        # (never a human-readable "Mara said ..." reference invented by a surface).
        refs = [h["ref"] for h in j["results"]]
        assert all(len(str(r)) == 36 and str(r).count("-") == 4 for r in refs), refs[:5]
        # The provider semantic-observation evidence is reachable by its EXACT
        # content-addressed locator (never re-labeled or invented).
        assert any(h.get("provenance", {}).get("locator") == locator for h in j["results"]), (
            f"provider evidence locator {locator!r} not exposed by EVIDENCE read"
        )
        # No surface presents model output as authority: evidence is exposed as
        # evidence (evidence_kind capability + SOURCE_EVIDENCE labelling), never as an
        # authoritative semantic assertion.
        assert any(h.get("capabilities", {}).get("evidence_kind") for h in j["results"]), (
            "evidence read must expose evidence_kind, not model output as authority"
        )
