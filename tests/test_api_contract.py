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
    """Replay-build both Tier-1 projections (current_tier1 + search) to the tail."""
    store = ProjectionCheckpointStore(engine)
    ReplayDriver(engine, store).run(CurrentTierOneBuilder(), wipe=True)
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
    app = create_app(engine=umd_db, source_store=source_store, settings=_client_settings())
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
    assert ingest["consistency_token"] >= 1

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
    assert any(item["value"] == "The game is afoot, Watson" for item in sab["answer"])

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

    # -- untokened read exposes freshness metadata ----------------------------
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
        resp = client.post("/v1/sources", json={"media_kind": "txt", "content": "wired app"})
        assert resp.status_code == 201, resp.text
        sid = resp.json()["source_id"]
        assert list(ocfl_root.rglob("inventory.json")), "no OCFL object under configured root"
        with engine.connect() as conn:
            row = conn.execute(
                sa.text("SELECT sha512, ocfl_ref FROM source WHERE id=:id"), {"id": sid}
            ).first()
        assert row is not None and row[0] and row[1]


def test_build_source_store_uses_configured_ocfl_root(tmp_path) -> None:
    """build_source_store(settings) uses the configured OCFL root directly."""
    from umd.api.entrypoints import build_source_store
    from umd.config import OcflSettings, Settings

    root = tmp_path / "ocfl"
    settings = Settings(ocfl=OcflSettings(root=root))
    store = build_source_store(settings)
    assert store.root == root
