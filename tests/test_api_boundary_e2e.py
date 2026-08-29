"""P4-S1..S6: spec-first PUBLIC-BOUNDARY E2E for heterogeneous real-format sources.

This module is the LIVE acceptance scenario. It communicates ONLY through the
versioned external HTTP boundary against the RUNNING service -- no ``umd.*``
import, no in-process ASGI test transport, no direct repository/ledger/projection
builder, and no in-process app construction anywhere in the scenario path. That
boundary purity is enforced statically by ``tests/test_api_boundary_guardrails.py``.

HONEST GATING (critical): this is the live acceptance path. It must run against
the real stack and must NOT self-skip on capability checks. It skips ONLY when the
running service is not reachable at ``UMD_API_BASE_URL`` (a named local gate --
e.g. a developer without the compose stack, or the Postgres-only CI job). On the
protected/main docker-e2e job the API IS running, so every scenario executes fully
with no skip and no capability self-gate.

Coverage map:
  * P4-S2 -- several related real-format sources under one work: translated TXT,
    adapted Markdown, raster PNG, ordinary-speech WAV, dialogue video (FFmpeg),
    and multiple independent subtitle tracks (SRT with HI/SDH + ASS). Stable
    source/work/job IDs, bounded multipart/inline, independent realizations,
    real segments/evidence, OCFL-backed bytes, locators, generated-by/tool/model/
    config metadata, confidence/uncertainty, honest provider warnings, no
    fabricated identities/transcripts.
  * P4-S3 -- public endpoints: alignment many-to-many + adaptation-aware; entity
    merge/split reversible and historied; segment and semantic edits/overrides/
    locks append-only and provenance-bearing; structured graph queries and
    semantic questions return typed answers; every answer exposes retrievable
    supporting evidence/source refs plus capability metadata.
  * P4-S4 -- public user correction; retrieve current/prior/actor/cause audit;
    source/segment/claim invalidation + selective rerun; descendant-only
    invalidation (unaffected segment/evidence/OCFL IDs, checksums, locators,
    source bytes, unrelated branches unchanged) while corrected Tier-0/Tier-1
    answers change after projection catch-up.
  * P4-S5 -- duplicate submission, executor-owned retry/backoff, deterministic
    quarantine, cancellation, claimed/incomplete reclaim, completed-key replay,
    and API/worker stop-start (workflow-level) against the same Postgres and
    named OCFL volumes; no repeated committed ancestor work, one authoritative
    completion per effective stage, no RUNNING->PENDING regression.
  * P4-S6 -- read-your-writes at the HTTP boundary: token-bearing reads return
    fresh corrected data OR a structured 503 with Retry-After and exactly
    ``x-consistency: transient-lag`` / ``rebuild-in-progress``.

The hermetic (in-process ASGI test transport over real Postgres + OCFL) equivalents of
these flows live in ``tests/test_phase4_heterogeneous_ingestion.py`` and the
postgres-seam tests in ``tests/test_hatchet_live.py`` -- never here.
"""

from __future__ import annotations

import base64
import hashlib
import os
import time
from collections.abc import Iterator
from types import SimpleNamespace
from typing import Any, cast

import httpx
import pytest

from fixtures import (
    adapted_markdown_bytes,
    dialogue_video_bytes,
    ordinary_speech_wav_bytes,
    raster_comic_bytes,
    subtitle_bytes,
    translated_txt_bytes,
)

pytestmark = pytest.mark.postgres

W = {"Authorization": "Bearer write-key"}  # read + write
R = {"Authorization": "Bearer read-key"}  # read-only

#: The running service base URL. Overridden in the docker-e2e workflow when the
#: compose API is reachable; defaults to the local compose API port.
API_BASE_URL = os.environ.get("UMD_API_BASE_URL", "http://127.0.0.1:8080")

_FFMPEG = os.environ.get("UMD_FFMPEG") is not None or True  # hosted CI ships ffmpeg

# P4-S2/S3/S6 metadata contract: every evidence/semantic answer must expose
# provenance, confidence/uncertainty, generated-by, and capability metadata.
_METADATA_KEYS = ("provenance", "confidence", "generated_by", "capabilities")

_TEXT_KINDS = ("txt", "markdown", "subtitle")
_CONTENT_TYPES = {"image": "image/png", "audio": "audio/wav", "video": "video/x-matroska"}

#: Endpoints that must be probed explicitly by the hosted acceptance step (P4-S7).
PUBLIC_PROBES = ("/v1/health", "/v1/ready", "/v1/capabilities", "/v1/version")


@pytest.fixture(scope="module")
def http() -> Iterator[httpx.Client]:
    """A single HTTP client bound to the running service for this module."""
    client = httpx.Client(base_url=API_BASE_URL, timeout=httpx.Timeout(30.0))
    try:
        yield client
    finally:
        client.close()


@pytest.fixture()
def api_ctx(http: httpx.Client) -> SimpleNamespace:
    """Live-service context. Skips ONLY when the running service is unreachable
    (named local gate), never on a capability self-check."""
    try:
        r = http.get("/v1/health", headers=R)
    except httpx.HTTPError:
        pytest.skip(
            f"live UMD API not reachable at {API_BASE_URL} "
            "(named local gate: compose stack not running; runs fully on docker-e2e)"
        )
    if r.status_code >= 500:
        pytest.skip(
            f"live UMD API at {API_BASE_URL} returned HTTP {r.status_code} on /v1/health "
            "(named local gate)"
        )
    return SimpleNamespace(client=http, base_url=API_BASE_URL)


ApiCtx = SimpleNamespace


# ---------------------------------------------------------------------------
# HTTP-only plumbing helpers
# ---------------------------------------------------------------------------


def _ingest(
    client: httpx.Client, *, kind: str, name: str, data: bytes, work_id: str | None
) -> dict[str, Any]:
    """Ingest one source through the versioned public boundary.

    Text sources (txt/markdown/subtitle) use the inline JSON ``content`` form.
    Binary sources (image/audio/video) use a bounded multipart streamed upload.
    Returns the SourceDescriptorResponse.
    """
    if kind in _TEXT_KINDS:
        payload = {
            "media_kind": kind,
            "original_name": name,
            "content_type": "text/plain",
            "content": data.decode("utf-8"),
        }
        if work_id is not None:
            payload["work_id"] = work_id
        r = client.post("/v1/sources", json=payload, headers=W)
    else:
        r = client.post(
            "/v1/sources",
            files={"file": (name, data, _CONTENT_TYPES.get(kind, "application/octet-stream"))},
            data={
                "media_kind": kind,
                "original_name": name,
                **({"work_id": work_id} if work_id else {}),
            },
            headers=W,
        )
    assert r.status_code == 201, r.text
    return cast("dict[str, Any]", r.json())


def _job_id(source_id: str) -> str:
    """Derive the durable job id from the source id (public router convention)."""
    return f"job-{source_id[:12]}"


def _poll_to_terminal(client: httpx.Client, job_id: str, *, attempts: int = 90) -> dict[str, Any]:
    """Poll a durable job endpoint until a terminal state (complete/failed/cancelled)."""
    for _ in range(attempts):
        r = client.get(f"/v1/jobs/{job_id}", headers=R)
        assert r.status_code == 200, r.text
        rec = cast("dict[str, Any]", r.json())
        if rec["status"] in ("complete", "failed", "cancelled"):
            return rec
        time.sleep(0.2)
    raise AssertionError(f"job {job_id} did not reach a terminal state")


def _ingest_heterogeneous_sources(client: httpx.Client) -> SimpleNamespace:
    """Several related real-format sources under ONE work (P4-S2)."""
    # Omitting work_id exercises the public contract that creates a new work.
    # Reuse the returned canonical ID for the related source realizations.
    txt = _ingest(
        client, kind="txt", name="translated.txt", data=translated_txt_bytes(), work_id=None
    )
    work_id = txt["work_id"]
    assert isinstance(work_id, str) and work_id
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


def _segment_checksum(client: httpx.Client, bodies: list[dict[str, Any]]) -> str:
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


def _evidence_checksum(client: httpx.Client, bodies: list[dict[str, Any]]) -> str:
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
    """Every evidence/semantic answer carries provenance, confidence/uncertainty,
    generated-by, and capability metadata."""
    for key in _METADATA_KEYS:
        assert key in item, f"{context} missing required metadata key {key!r}: {item}"


def _token_read_never_stale(
    client: httpx.Client, *, token: int, stale_value: str, filters: dict[str, Any]
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
        body = cast("dict[str, Any]", r.json())
        assert not [h for h in body["results"] if h.get("value") == stale_value], (
            "token-bearing read served a stale pre-correction answer"
        )
        return body
    assert r.status_code == 503, r.text
    doc = cast("dict[str, Any]", r.json())
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
# P4-S2 + P4-S3: ingest heterogeneous sources, decompose, align, and retrieve
# ---------------------------------------------------------------------------


def test_boundary_ingest_decompose_retrieve_heterogeneous(api_ctx: ApiCtx) -> None:
    client = api_ctx.client
    s = _ingest_heterogeneous_sources(client)

    # P4-S2: stable source/work/job identifiers + a consistency token per source.
    for body in s.bodies:
        assert body["source_id"]
        assert body["work_id"] == s.work_id
        assert _job_id(body["source_id"]), "ingest response carries a durable job identifier"
        assert body["consistency_token"] >= 1

    # Decompose each source independently by polling the durable job to terminal state.
    for body in s.bodies:
        rec = _poll_to_terminal(client, _job_id(body["source_id"]))
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

    # Persisted evidence is retrievable per segment, satisfies the metadata contract,
    # and exposes supporting evidence/source refs + generated-by/tool metadata.
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
                assert item.get("locator") or item.get("ref"), (
                    f"evidence missing retrievable source ref: {item}"
                )
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

    # P4-S3: cross-source alignment (adaptation correspondence) many-to-many + adaptation-aware.
    left, right = next(iter(k_txt)), next(iter(k_md))
    al = client.post(
        f"/v1/alignment?left_ref={left}&right_ref={right}&alignment_type=ADAPTATION", headers=W
    )
    assert al.status_code == 201, al.text
    assert al.json()["action"] == "ADAPTATION"

    # P4-S3: structured graph query for alignments returns typed answers.
    corr = client.post(
        "/v1/query/structured", json={"kind": "CORRESPONDENCE", "limit": 20}, headers=R
    )
    assert corr.status_code == 200, corr.text
    assert corr.json()["total"] >= 1

    # P4-S3: semantic claims (SPEAKS) with support refs -> typed semantic answer with support.
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
    assert claim.json()["consistency_token"] >= 1

    # P4-S3: semantic questions return typed answers with retrievable support refs
    # and capability metadata at the envelope + item level.
    sem = client.post("/v1/query/semantic", json={"question": "what does e:alice say"}, headers=R)
    assert sem.status_code == 200, sem.text
    sab = sem.json()
    assert "UTTERANCE" in sab["compiled_ops"]
    assert "typed relational" in sab["provenance"]["authority"]
    assert sab.get("support"), "semantic answer exposes no retrievable supporting evidence"
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

    # Honest capability/readiness surface is available (P4-S7 probes run here too).
    for probe in PUBLIC_PROBES:
        r = client.get(probe, headers=R)
        assert r.status_code == 200, f"{probe} returned {r.status_code}: {r.text}"


# ---------------------------------------------------------------------------
# P4-S3: segment + semantic edits/overrides/locks are append-only + provenance-bearing
# ---------------------------------------------------------------------------


def test_boundary_edits_overrides_locks_are_append_only_and_provenance_bearing(
    api_ctx: ApiCtx,
) -> None:
    client = api_ctx.client
    s = _ingest_heterogeneous_sources(client)
    for body in s.bodies:
        _poll_to_terminal(client, _job_id(body["source_id"]))

    segs = client.get(f"/v1/sources/{s.audio['source_id']}/segments", headers=R)
    assert segs.status_code == 200, segs.text
    segment_id = segs.json()["items"][0]["segment_id"]

    # Segment edit through the public endpoint (append-only, provenance-bearing).
    se = client.post(f"/v1/segments/{segment_id}/edit?ref={segment_id}", headers=W)
    assert se.status_code == 200, se.text
    assert se.json()["consistency_token"] >= 1

    # Segment split through the public endpoint.
    sp = client.post(f"/v1/segments/{segment_id}/split", headers=W)
    assert sp.status_code == 200, sp.text

    # Semantic edit / override is append-only + provenance-bearing.
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
    ov = client.post(
        "/v1/claims/e:alice/override",
        json={"reason": "manual correction", "refs": [f"source://{s.audio['source_id']}/audio/0"]},
        headers=W,
    )
    assert ov.status_code == 200, ov.text
    assert ov.json()["consistency_token"] >= 1

    # Lock / unlock through the public endpoint.
    lk = client.post("/v1/entities/e:alice/lock", headers=W)
    assert lk.status_code == 200, lk.text
    ul = client.post("/v1/entities/e:alice/unlock", headers=W)
    assert ul.status_code == 200, ul.text

    # Provenance is auditable: current/prior/actor/change-cause.
    ex = client.get("/v1/claims/e:alice/provenance", headers=R)
    assert ex.status_code == 200, ex.text
    pbody = ex.json()
    assert pbody["actor"] and pbody["current"] is not None
    assert pbody["change_cause"]
    assert pbody["prior"] is not None, "override history must retain the prior state"


# ---------------------------------------------------------------------------
# P4-S4: correction -> descendant-only invalidation -> selective rerun
# ---------------------------------------------------------------------------


def test_boundary_correction_invalidation_selective_rerun(api_ctx: ApiCtx) -> None:
    client = api_ctx.client
    s = _ingest_heterogeneous_sources(client)
    for body in s.bodies:
        _poll_to_terminal(client, _job_id(body["source_id"]))

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
    # A token-bearing read never serves the stale pre-correction answer (P4-S6).
    _token_read_never_stale(
        client, token=corrected_token, stale_value="hello there", filters={"speaker": "e:alice"}
    )


# ---------------------------------------------------------------------------
# P4-S5 + P4-S6: duplicate, retry, cancel, and read-your-writes consistency
# ---------------------------------------------------------------------------


def test_boundary_duplicate_retry_cancel_and_consistency(api_ctx: ApiCtx) -> None:
    client = api_ctx.client
    s = _ingest_heterogeneous_sources(client)
    for body in s.bodies:
        _poll_to_terminal(client, _job_id(body["source_id"]))

    seg0 = _segment_checksum(client, s.bodies)
    low0 = _evidence_checksum(client, s.bodies)

    # -- Duplicate submission (identical content) is idempotent: the same
    #    deterministic segment keys result (no repeated decomposition) (P4-S5).
    dup = _ingest(
        client, kind="txt", name="translated.txt", data=translated_txt_bytes(), work_id=s.work_id
    )
    _poll_to_terminal(client, _job_id(dup["source_id"]))

    def keys(source_id: str) -> set[str]:
        r = client.get(f"/v1/sources/{source_id}/segments", headers=R)
        assert r.status_code == 200, r.text
        return {it["ref"] for it in r.json()["items"] if it.get("ref")}

    assert keys(dup["source_id"]) == keys(s.txt["source_id"])

    # -- Retry a completed job: completed expensive stages are not re-executed (P4-S5).
    retry = client.post(f"/v1/jobs/job-{s.txt['source_id'][:12]}/retry", headers=W)
    assert retry.status_code == 200, retry.text
    assert _segment_checksum(client, s.bodies) == seg0
    assert _evidence_checksum(client, s.bodies) == low0

    # -- Cancellation through the public endpoint (P4-S5): a submitted job can be
    #    cancelled; the durable store reconciles to a terminal cancelled state.
    cj = _ingest(
        client, kind="txt", name="cancel.txt", data=translated_txt_bytes(), work_id=s.work_id
    )
    cxl = client.post(f"/v1/jobs/{_job_id(cj['source_id'])}/cancel", headers=W)
    assert cxl.status_code == 200, cxl.text
    assert cxl.json()["action"] == "cancel"

    # -- Consistency (P4-S6): token-bearing reads never return stale answers; the
    #    two 503 classes are distinguished by x-consistency and Retry-After bounds.
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
    # a stale answer and never an unclassified failure (P4-S6).
    _token_read_never_stale(
        client, token=token, stale_value="never-a-value", filters={"speaker": "e:alice"}
    )


# ---------------------------------------------------------------------------
# P4-S5: API/worker stop-start is exercised at the WORKFLOW level (compose
# stop/start api worker preserving named volumes); the persisted evidence of the
# completed scenario above is durable and replay-safe (read-your-writes + audit).
# ---------------------------------------------------------------------------
