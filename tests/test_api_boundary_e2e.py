"""P1-S1..S5: spec-first PUBLIC-BOUNDARY E2E for heterogeneous real-format sources.

This module is the acceptance spec for the production API/worker/Hatchet path
(Plan G Phase 3 wiring + Plan I Hatchet worker + Plan H providers). The scenario
communicates ONLY through the versioned HTTP endpoints -- no direct modality,
repository, ledger, projection-builder, or internal-runner call appears anywhere
in the scenario path (enforced statically by ``tests/test_api_boundary_guardrails.py``).
Plumbing helpers (fixture generators, HTTP upload/poll helpers, metadata and
checksum assertions) are fine; the scenario assertions themselves are HTTP-only.

HONEST GATING (critical): the full heterogeneous scenario requires the production
API+worker+scheduler path that concurrent sessions are still implementing. Until
the live API reports that path active (``GET /v1/capabilities`` scheduler/worker
status is active), every scenario test SKIPS with a named spec-first gate reason --
it never fails and never silently passes. The gate keys off the live API's reported
capability state, NOT an env flag a CI run could forget. In a real production stack
(hosted CI, Phase 2) the scenario runs fully with no skip. This is the permitted
gate pattern: named gate reason + CI proves the baseline.

Coverage map:
  * P1-S1 -- several related real-format sources under one work: translated TXT,
    adapted Markdown, raster PNG, ordinary-speech WAV, dialogue video (FFmpeg),
    and multiple independent subtitle tracks (SRT with HI/SDH + ASS).
  * P1-S2 -- API returns source/work/job ids + consistency token; poll durable
    jobs to terminal state; retrieve persisted segments, evidence, semantic
    results, provenance locators, alignment, reversible entity resolution,
    structured query answers, semantic answers with support, and source-native refs.
  * P1-S3 -- user correction through the public override/edit endpoint; audit
    current/prior/actor/change-cause; descendant-only invalidation + selective
    rerun through public endpoints; unaffected segment/OCR/ASR ids/checksums and
    source bytes unchanged while corrected answers/confidence change.
  * P1-S4 -- mid-scenario API restart (new app over same Postgres + OCFL),
    duplicate/late-failure/retry, token-bearing reads never stale, and the two
    consistency-failure classes (transient-lag vs rebuild-in-progress).
  * P1-S5 -- every evidence/semantic answer carries provenance, confidence/
    uncertainty, generated-by, and capability metadata (also enforced here).
"""

from __future__ import annotations

import base64
import hashlib
import shutil
import time
import uuid
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa
from fastapi.testclient import TestClient

from fixtures import (
    adapted_markdown_bytes,
    dialogue_video_bytes,
    ordinary_speech_wav_bytes,
    raster_comic_bytes,
    subtitle_bytes,
    translated_txt_bytes,
)
from umd.api.app import create_app
from umd.config import AuthSettings, ConsistencySettings, RateLimitSettings, Settings

pytestmark = pytest.mark.postgres

W = {"Authorization": "Bearer write-key"}  # read + write
R = {"Authorization": "Bearer read-key"}  # read-only

_FFMPEG = shutil.which("ffmpeg") is not None

# P1-S5 metadata contract: every evidence/semantic answer must expose provenance,
# confidence/uncertainty, generated-by, and capability metadata.
_METADATA_KEYS = ("provenance", "confidence", "generated_by", "capabilities")

_TEXT_KINDS = ("txt", "markdown", "subtitle")
_CONTENT_TYPES = {"image": "image/png", "audio": "audio/wav", "video": "video/x-matroska"}


def _client_settings() -> Settings:
    return Settings(
        auth=AuthSettings(api_keys=["write-key", "read-key"], write_keys=["write-key"]),
        rate_limit=RateLimitSettings(
            enabled=True, requests_per_window=100000, window_seconds=60.0, burst=1000
        ),
        consistency=ConsistencySettings(lag_wait_multiplier=1, max_waiters=64),
        lag_budget_seconds=0.05,
    )


@pytest.fixture()
def api_ctx(umd_db: sa.Engine, source_store):
    """App + TestClient over the live Postgres ledger + OCFL store."""
    app = create_app(engine=umd_db, source_store=source_store, settings=_client_settings())
    with TestClient(app) as client:
        yield SimpleNamespace(
            client=client,
            engine=umd_db,
            source_store=source_store,
            settings=app.state.ctx.settings,
        )


# ---------------------------------------------------------------------------
# HONEST GATE: keyed off the live API's reported capability state (never an env flag)
# ---------------------------------------------------------------------------


def _require_production_path(client: TestClient) -> None:
    """Skip unless the live API reports the production scheduler/worker path active.

    Keys off ``GET /v1/capabilities`` (Plan I P3-S4 exposes scheduler/provider
    capability status there). Until the production wiring lands, the API reports no
    active scheduler/worker, so the scenario skips with a named spec-first reason
    rather than failing or silently passing.
    """
    r = client.get("/v1/capabilities", headers=R)
    if r.status_code != 200:
        pytest.skip(
            f"SPEC-FIRST gate: /v1/capabilities returned {r.status_code}; cannot confirm "
            "the production scheduler/worker path"
        )
    cap = r.json().get("capabilities", {}) or {}
    active = False
    for key in ("scheduler", "worker"):
        entry = cap.get(key)
        if isinstance(entry, dict):
            status = entry.get("status") or entry.get("state") or entry.get("active")
            if status in ("active", "ready", True):
                active = True
    if cap.get("scheduler_active") is True and cap.get("worker_active") is True:
        active = True
    if not active:
        pytest.skip(
            "SPEC-FIRST gate: /v1/capabilities reports no active scheduler/worker. The "
            "production API/worker/scheduler path (Plan G Phase 3 wiring + Plan I Hatchet "
            "worker + Plan H providers) is not live yet; skipping the public-boundary "
            "scenario by design (not failing, not silently passing)."
        )


# ---------------------------------------------------------------------------
# HTTP-only plumbing helpers
# ---------------------------------------------------------------------------


def _ingest(
    client: TestClient, *, kind: str, name: str, data: bytes, work_id: str
) -> dict[str, Any]:
    """Ingest one source through the versioned public boundary.

    Text sources (txt/markdown/subtitle) use the inline JSON ``content`` form the
    API retains for compatibility. Binary sources (image/audio/video) use a bounded
    multipart streamed upload -- the CONTRACTS/DD "ingest a stream plus descriptor"
    contract that Plan G Phase 3 is adding. Returns the SourceDescriptorResponse.
    """
    if kind in _TEXT_KINDS:
        payload = {
            "media_kind": kind,
            "work_id": work_id,
            "original_name": name,
            "content_type": "text/plain",
            "content": data.decode("utf-8"),
        }
        r = client.post("/v1/sources", json=payload, headers=W)
    else:
        r = client.post(
            "/v1/sources",
            files={"file": (name, data, _CONTENT_TYPES.get(kind, "application/octet-stream"))},
            data={"media_kind": kind, "work_id": work_id, "original_name": name},
            headers=W,
        )
    assert r.status_code == 201, r.text
    return r.json()


def _poll_to_terminal(client: TestClient, job_id: str, *, attempts: int = 60) -> dict[str, Any]:
    """Poll a durable job endpoint until a terminal state (complete/failed/cancelled)."""
    for _ in range(attempts):
        r = client.get(f"/v1/jobs/{job_id}", headers=R)
        assert r.status_code == 200, r.text
        rec = r.json()
        if rec["status"] in ("complete", "failed", "cancelled"):
            return rec
        time.sleep(0.1)
    raise AssertionError(f"job {job_id} did not reach a terminal state")


def _ingest_heterogeneous_sources(client: TestClient) -> SimpleNamespace:
    """Several related real-format sources under ONE work (P1-S1)."""
    work_id = uuid.uuid4().hex
    txt = _ingest(
        client, kind="txt", name="translated.txt", data=translated_txt_bytes(), work_id=work_id
    )
    md = _ingest(
        client, kind="markdown", name="adapted.md", data=adapted_markdown_bytes(), work_id=work_id
    )
    img = _ingest(
        client, kind="image", name="comic.png", data=raster_comic_bytes(), work_id=work_id
    )
    audio = _ingest(
        client, kind="audio", name="speech.wav", data=ordinary_speech_wav_bytes(), work_id=work_id
    )
    sub_srt = _ingest(
        client,
        kind="subtitle",
        name="dialog.srt",
        data=subtitle_bytes("srt", hi_sdh=True),
        work_id=work_id,
    )
    sub_ass = _ingest(
        client, kind="subtitle", name="dialog.ass", data=subtitle_bytes("ass"), work_id=work_id
    )
    bodies = [txt, md, img, audio, sub_srt, sub_ass]
    video = None
    if _FFMPEG:  # dialogue video requires the tested FFmpeg build
        video = _ingest(
            client, kind="video", name="dialog.mkv", data=dialogue_video_bytes(), work_id=work_id
        )
        bodies.append(video)
    return SimpleNamespace(
        work_id=work_id,
        txt=txt,
        md=md,
        img=img,
        audio=audio,
        video=video,
        sub_srt=sub_srt,
        sub_ass=sub_ass,
        bodies=bodies,
    )


def _segment_checksum(client: TestClient, bodies: list[dict[str, Any]]) -> str:
    """Stable checksum over every persisted segment's HTTP-visible identity."""
    h = hashlib.sha256()
    for body in bodies:
        r = client.get(f"/v1/sources/{body['source_id']}/segments", headers=R)
        assert r.status_code == 200, r.text
        for it in sorted(r.json()["items"], key=lambda x: x["segment_id"]):
            h.update(
                "|".join(str(it.get(k)) for k in ("segment_id", "ref", "locator", "kind")).encode()
            )
            h.update(b"\n")
    return h.hexdigest()


def _evidence_checksum(client: TestClient, bodies: list[dict[str, Any]]) -> str:
    """Stable checksum over every persisted evidence record's HTTP-visible identity."""
    h = hashlib.sha256()
    for body in bodies:
        r = client.get(f"/v1/sources/{body['source_id']}/segments", headers=R)
        assert r.status_code == 200, r.text
        for it in r.json()["items"]:
            ev = client.get(f"/v1/segments/{it['segment_id']}/evidence", headers=R)
            assert ev.status_code == 200, ev.text
            for item in sorted(ev.json()["items"], key=lambda x: x["ref"]):
                h.update(
                    "|".join(
                        str(item.get(k)) for k in ("ref", "predicate", "locator", "confidence")
                    ).encode()
                )
                h.update(b"\n")
    return h.hexdigest()


def _assert_metadata_contract(item: dict[str, Any], *, context: str) -> None:
    """P1-S5: every evidence/semantic answer carries provenance, confidence/uncertainty,
    generated-by, and capability metadata."""
    for key in _METADATA_KEYS:
        assert key in item, f"{context} missing required metadata key {key!r}: {item}"


def _token_read_never_stale(
    client: TestClient, *, token: int, stale_value: str, filters: dict[str, Any]
) -> dict[str, Any]:
    """A token-bearing read never returns stale post-correction answers.

    If the projection has caught up it returns 200 with the corrected state (and
    never ``stale_value``); otherwise it 503s with ``x-consistency`` exactly one of
    ``transient-lag`` / ``rebuild-in-progress`` and the matching RFC 7807 body.
    """
    r = client.post(
        "/v1/query/structured",
        json={"kind": "UTTERANCE", "filters": filters, "consistency_token": token},
        headers=R,
    )
    if r.status_code == 200:
        body = r.json()
        assert not [h for h in body["results"] if h.get("value") == stale_value], (
            "token-bearing read served a stale pre-correction answer"
        )
        return body
    assert r.status_code == 503, r.text
    doc = r.json()
    assert doc["retryable"] is True
    assert doc["x-consistency"] in ("transient-lag", "rebuild-in-progress")
    assert r.headers.get("x-consistency") == doc["x-consistency"]
    assert float(r.headers.get("retry-after", 0)) > 0
    if doc["x-consistency"] == "transient-lag":
        assert float(r.headers.get("retry-after", 0)) < 30
    else:
        assert float(r.headers.get("retry-after", 0)) >= 30
    return doc


# ---------------------------------------------------------------------------
# P1-S1 + P1-S2: ingest heterogeneous sources, decompose, and retrieve
# ---------------------------------------------------------------------------


def test_boundary_ingest_decompose_retrieve_heterogeneous(api_ctx) -> None:
    client = api_ctx.client
    _require_production_path(client)
    s = _ingest_heterogeneous_sources(client)

    # P1-S1/S2: the API returns stable source/work/job identifiers + a consistency token.
    for body in s.bodies:
        assert body["source_id"]
        assert body["work_id"] == s.work_id
        assert body["job_id"], "ingest response must carry a job identifier"
        assert body["consistency_token"] >= 1

    # Decompose each source independently by polling the durable job to terminal state.
    for body in s.bodies:
        rec = _poll_to_terminal(client, body["job_id"])
        assert rec["status"] == "complete", f"{body['media_kind']} job not complete: {rec}"

    # Every source exposes persisted, deterministic segments through the public route.
    for body in s.bodies:
        segs = client.get(f"/v1/sources/{body['source_id']}/segments", headers=R)
        assert segs.status_code == 200, segs.text
        assert segs.json()["total"] >= 1, f"no segments persisted for {body['media_kind']}"

    # Translated text vs adapted markdown produce DISJOINT deterministic segment keys
    # (distinct realizations retained, never conflationally merged).
    def segment_keys(source_id: str) -> set[str]:
        r = client.get(f"/v1/sources/{source_id}/segments", headers=R)
        assert r.status_code == 200, r.text
        return {it["ref"] for it in r.json()["items"] if it.get("ref")}

    k_txt = segment_keys(s.txt["source_id"])
    k_md = segment_keys(s.md["source_id"])
    assert k_txt and k_md and k_txt.isdisjoint(k_md)

    # Persisted evidence is retrievable per segment and satisfies the metadata contract.
    evidence_count = 0
    for body in s.bodies:
        segs = client.get(f"/v1/sources/{body['source_id']}/segments", headers=R)
        assert segs.status_code == 200, segs.text
        for it in segs.json()["items"]:
            ev = client.get(f"/v1/segments/{it['segment_id']}/evidence", headers=R)
            assert ev.status_code == 200, ev.text
            for item in ev.json()["items"]:
                evidence_count += 1
                _assert_metadata_contract(item, context="evidence")
    assert evidence_count >= 1

    # Semantic setup through the public boundary: canonical entities + reversible merge.
    assert (
        client.post(
            "/v1/entities", json={"ref": "e:white-rabbit", "label": "White Rabbit"}, headers=W
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/v1/entities", json={"ref": "e:lapin", "label": "Lapin Blanc"}, headers=W
        ).status_code
        == 201
    )
    merge = client.post("/v1/entities/e:lapin/merge?target_entity_ref=e:white-rabbit", headers=W)
    assert merge.status_code == 200 and merge.json()["consistency_token"] >= 1

    # Cross-source alignment (adaptation correspondence) via the public boundary.
    left, right = next(iter(k_txt)), next(iter(k_md))
    al = client.post(
        f"/v1/alignment?left_ref={left}&right_ref={right}&alignment_type=ADAPTATION", headers=W
    )
    assert al.status_code == 201, al.text
    corr = client.post(
        "/v1/query/structured", json={"kind": "CORRESPONDENCE", "limit": 20}, headers=R
    )
    assert corr.status_code == 200, corr.text
    assert corr.json()["total"] >= 1

    # Semantic claims (SPEAKS) with support refs -> typed semantic answer with support.
    claim = client.post(
        "/v1/claims",
        json={
            "predicate_code": "SPEAKS",
            "subject_ref": "e:alice",
            "object_ref": "hello there",
            "confidence": 0.6,
            "support_refs": [f"source://{s.audio['source_id']}/audio/0"],
        },
        headers=W,
    )
    assert claim.status_code == 201, claim.text

    sem = client.post("/v1/query/semantic", json={"question": "what does e:alice say"}, headers=R)
    assert sem.status_code == 200, sem.text
    sab = sem.json()
    assert "UTTERANCE" in sab["compiled_ops"]
    assert "typed relational" in sab["provenance"]["authority"]
    for item in sab.get("answer", []):
        _assert_metadata_contract(item, context="semantic answer")

    # Structured query hits satisfy the metadata contract too.
    sq = client.post(
        "/v1/query/structured",
        json={"kind": "UTTERANCE", "filters": {"speaker": "e:alice"}, "limit": 20},
        headers=R,
    )
    assert sq.status_code == 200, sq.text
    for hit in sq.json()["results"]:
        _assert_metadata_contract(hit, context="structured query hit")

    # Source-native retrieval: GET /v1/locators/{ocfl_ref} returns the bounded bytes.
    loc = client.get(f"/v1/locators/{s.txt['ocfl_ref']}?start=0&length=4096", headers=R)
    assert loc.status_code == 200, loc.text
    decoded = base64.b64decode(loc.json()["data_b64"]).decode("utf-8")
    assert decoded == translated_txt_bytes().decode("utf-8")

    # Reversible entity resolution is auditable through the public boundary.
    aud = client.get("/v1/audit/e:white-rabbit", headers=R)
    assert aud.status_code == 200, aud.text
    assert aud.json()["explanation"]


# ---------------------------------------------------------------------------
# P1-S3: correction -> descendant-only invalidation -> selective rerun
# ---------------------------------------------------------------------------


def test_boundary_correction_invalidation_selective_rerun(api_ctx) -> None:
    client = api_ctx.client
    _require_production_path(client)
    s = _ingest_heterogeneous_sources(client)
    for body in s.bodies:
        _poll_to_terminal(client, body["job_id"])

    # A machine claim the user will correct.
    assert (
        client.post(
            "/v1/entities", json={"ref": "e:alice", "label": "Alice"}, headers=W
        ).status_code
        == 201
    )
    c = client.post(
        "/v1/claims",
        json={
            "predicate_code": "SPEAKS",
            "subject_ref": "e:alice",
            "object_ref": "hello there",
            "confidence": 0.6,
        },
        headers=W,
    )
    assert c.status_code == 201, c.text

    # Baseline: unaffected segment + evidence checksums and source bytes.
    seg0 = _segment_checksum(client, s.bodies)
    low0 = _evidence_checksum(client, s.bodies)

    # Apply the user correction through the public override endpoint.
    corrected = "Hello, Alice"
    ov = client.post(
        "/v1/claims/e:alice/override",
        json={
            "reason": "manual transcription correction of the spoken utterance",
            "refs": [f"source://{s.audio['source_id']}/audio/0"],
        },
        headers=W,
    )
    assert ov.status_code == 200, ov.text
    corrected_token = ov.json()["consistency_token"]

    # Audit explains current/prior/actor/change-cause through the public boundary.
    ex = client.get("/v1/claims/e:alice/provenance", headers=R)
    assert ex.status_code == 200, ex.text
    pbody = ex.json()
    assert pbody["actor"] and pbody["current"] is not None
    assert pbody["change_cause"]

    # Descendant-only selective rerun through the public endpoint (202 Accepted).
    rj = client.post(f"/v1/sources/{s.audio['source_id']}/rerun", headers=W)
    assert rj.status_code in (200, 202), rj.text
    _poll_to_terminal(client, rj.json().get("job_id", f"job-{s.audio['source_id'][:12]}"))

    # Unaffected segment/evidence ids + checksums and source bytes remain unchanged.
    seg1 = _segment_checksum(client, s.bodies)
    low1 = _evidence_checksum(client, s.bodies)
    assert seg1 == seg0 and low1 == low0
    loc = client.get(f"/v1/locators/{s.audio['ocfl_ref']}?start=0&length=4096", headers=R)
    assert loc.status_code == 200, loc.text
    assert base64.b64decode(loc.json()["data_b64"]) == ordinary_speech_wav_bytes()

    # Corrected Tier-0 answer is reflected and the machine answer is gone.
    sem = client.post(
        "/v1/query/semantic",
        json={"question": "what does e:alice say", "consistency_token": corrected_token},
        headers=R,
    )
    assert sem.status_code == 200, sem.text
    values = [it.get("value") for it in sem.json().get("answer", [])]
    assert corrected in values
    assert "hello there" not in values
    # A token-bearing read never serves the stale pre-correction answer.
    _token_read_never_stale(
        client, token=corrected_token, stale_value="hello there", filters={"speaker": "e:alice"}
    )


# ---------------------------------------------------------------------------
# P1-S4: restart, duplicate / late-failure / retry, consistency classes
# ---------------------------------------------------------------------------


def test_boundary_restart_duplicate_retry_and_consistency(api_ctx) -> None:
    client = api_ctx.client
    _require_production_path(client)
    s = _ingest_heterogeneous_sources(client)
    for body in s.bodies:
        _poll_to_terminal(client, body["job_id"])

    seg0 = _segment_checksum(client, s.bodies)
    low0 = _evidence_checksum(client, s.bodies)

    # -- Mid-scenario API restart: a NEW app over the SAME Postgres + OCFL store
    #    (named-volume semantics). Postgres/OCFL-retained state stays visible.
    app2 = create_app(
        engine=api_ctx.engine, source_store=api_ctx.source_store, settings=api_ctx.settings
    )
    with TestClient(app2) as c2:
        for body in s.bodies:
            r = c2.get(f"/v1/sources/{body['source_id']}", headers=R)
            assert r.status_code == 200, r.text
            assert r.json()["sha512"] == body["sha512"]
            segs = c2.get(f"/v1/sources/{body['source_id']}/segments", headers=R)
            assert segs.status_code == 200 and segs.json()["total"] >= 1
        # Completed stages are not repeated after restart: report shows committed state.
        rep = c2.get(f"/v1/sources/{s.txt['source_id']}/report", headers=R)
        assert rep.status_code == 200, rep.text

    # -- Retry a completed job: completed expensive stages are not re-executed.
    retry = client.post(f"/v1/jobs/job-{s.txt['source_id'][:12]}/retry", headers=W)
    assert retry.status_code == 200, retry.text
    assert _segment_checksum(client, s.bodies) == seg0
    assert _evidence_checksum(client, s.bodies) == low0

    # -- Duplicate submission (identical content) is idempotent: the same
    #    deterministic segment keys result (no repeated decomposition).
    dup = _ingest(
        client, kind="txt", name="translated.txt", data=translated_txt_bytes(), work_id=s.work_id
    )
    _poll_to_terminal(client, dup["job_id"])

    def keys(source_id: str) -> set[str]:
        r = client.get(f"/v1/sources/{source_id}/segments", headers=R)
        assert r.status_code == 200, r.text
        return {it["ref"] for it in r.json()["items"] if it.get("ref")}

    assert keys(dup["source_id"]) == keys(s.txt["source_id"])

    # -- Consistency: token-bearing reads never return stale answers; the two
    #    503 classes (transient-lag vs rebuild-in-progress) are distinguished by
    #    the x-consistency header and Retry-After bounds.
    assert (
        client.post(
            "/v1/entities", json={"ref": "e:alice", "label": "Alice"}, headers=W
        ).status_code
        == 201
    )
    claim = client.post(
        "/v1/claims",
        json={
            "predicate_code": "SPEAKS",
            "subject_ref": "e:alice",
            "object_ref": "hello there",
            "confidence": 0.6,
        },
        headers=W,
    )
    assert claim.status_code == 201, claim.text
    token = claim.json()["consistency_token"]
    # If the projection has caught up this returns the corrected/fresh state; if it
    # is behind, it must 503 with exactly one of the two consistency classes -- never
    # a stale answer and never an unclassified failure.
    _token_read_never_stale(
        client, token=token, stale_value="never-a-value", filters={"speaker": "e:alice"}
    )


# ---------------------------------------------------------------------------
# P1-S5: metadata contract on every evidence/semantic answer
# ---------------------------------------------------------------------------


def test_boundary_every_answer_carries_metadata_contract(api_ctx) -> None:
    client = api_ctx.client
    _require_production_path(client)
    s = _ingest_heterogeneous_sources(client)
    for body in s.bodies:
        _poll_to_terminal(client, body["job_id"])

    # Evidence metadata contract.
    for body in s.bodies:
        segs = client.get(f"/v1/sources/{body['source_id']}/segments", headers=R)
        assert segs.status_code == 200, segs.text
        for it in segs.json()["items"]:
            ev = client.get(f"/v1/segments/{it['segment_id']}/evidence", headers=R)
            assert ev.status_code == 200, ev.text
            for item in ev.json()["items"]:
                _assert_metadata_contract(item, context="evidence")

    # Semantic answer metadata contract.
    assert (
        client.post(
            "/v1/entities", json={"ref": "e:alice", "label": "Alice"}, headers=W
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/v1/claims",
            json={
                "predicate_code": "SPEAKS",
                "subject_ref": "e:alice",
                "object_ref": "hello there",
                "confidence": 0.6,
            },
            headers=W,
        ).status_code
        == 201
    )
    sem = client.post("/v1/query/semantic", json={"question": "what does e:alice say"}, headers=R)
    assert sem.status_code == 200, sem.text
    for item in sem.json().get("answer", []):
        _assert_metadata_contract(item, context="semantic answer")
    # The semantic answer's provenance metadata is present at the envelope level too.
    assert sem.json()["provenance"]
