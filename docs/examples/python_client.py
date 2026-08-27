"""Maintained public-contract client for the Universal Media Decomposer v1 API.

This module is the runnable companion example referenced by ``docs/examples/
README.md`` and executed against the live application by
``tests/test_docs_examples.py``. It uses **only the public, versioned ``/v1``
REST contract** — never internal storage, provider, or ledger APIs — and
demonstrates: ingest, job polling, typed structured + semantic query, exact
search, source-native retrieval, correction, selective rerun, cursor
pagination, RFC 7807 structured errors, read-your-writes tokens, and **both**
Tier-1 consistency response classes (``transient-lag`` and
``rebuild-in-progress`` 503).

The client is intentionally thin: it constructs requests and decodes RFC 7807
problem bodies. All semantic/storage/provider authority lives on the server; the
client never assumes a provider or storage backend.

``PublicContractClient`` accepts a ``base_url`` (live HTTP server) or a FastAPI
``app`` (via the synchronous ``TestClient``, as used by the integration test) so
the exact same code runs against a live deployment or the app-under-test.

The demonstration functions accept an optional ``stage(name)`` callback. That
callback is the *only* place server-side projection state is controlled; in a
running deployment these transitions are driven by operators/builders (see
``docs/consistency.md``), never by the public API. When ``stage`` is omitted the
consistency-failure demonstrations that require staging are skipped.
"""

from __future__ import annotations

import base64
from typing import Any, Callable

import httpx

_STAGE = Callable[[str], None]


class ApiError(Exception):
    """A structured RFC 7807 problem response (``application/problem+json``)."""

    def __init__(
        self, status: int, body: dict[str, Any] | None, headers: dict[str, str] | None = None
    ) -> None:
        super().__init__(f"HTTP {status}: {(body or {}).get('code', 'error')}")
        self.status = status
        self.body: dict[str, Any] = body or {}
        self.headers: dict[str, str] = headers or {}
        self.code: str = str(self.body.get("code") or "unknown")
        self.type: str = str(self.body.get("type") or "")
        self.retryable: bool | None = self.body.get("retryable")
        self.correlation_id: str | None = self.body.get("correlation_id")
        self.x_consistency: str | None = self.body.get("x-consistency") or self.headers.get(
            "x-consistency"
        )
        self.retry_after: Any = self.headers.get("retry-after") or self.body.get("retry_after")


class PublicContractClient:
    """Thin typed client over the public ``/v1`` contract."""

    def __init__(
        self,
        base_url: str = "http://localhost:8080",
        api_key: str | None = None,
        transport: httpx.BaseTransport | None = None,
        *,
        app: Any | None = None,
    ) -> None:
        """Construct against a live server (``base_url``/``transport``) or, when
        ``app`` is given, against a FastAPI/Starlette app through the synchronous
        ``TestClient`` — so the exact same example code runs in tests and live."""
        if app is not None:
            from fastapi.testclient import TestClient

            self._client: Any = TestClient(app)
            self._auth: dict[str, str] = {"Authorization": f"Bearer {api_key}"} if api_key else {}
        else:
            headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
            self._client = httpx.Client(base_url=base_url, headers=headers, transport=transport)
            self._auth = {}

    def close(self) -> None:
        # Best-effort cleanup; TestClient/transport variants may not implement a
        # synchronous close. Never fail a run on cleanup.
        close = getattr(self._client, "close", None)
        if callable(close):
            try:
                close()
            except (AttributeError, RuntimeError):
                pass

    # -- transport ----------------------------------------------------------
    def _send(self, method: str, path: str, **kw: Any) -> dict[str, Any]:
        resp = self._client.request(method, path, headers=self._auth, **kw)
        body: dict[str, Any] | None = None
        try:
            body = resp.json()
        except ValueError:
            body = None
        if resp.status_code >= 400:
            raise ApiError(resp.status_code, body, headers=dict(resp.headers))
        return body or {}

    # -- system -------------------------------------------------------------
    def version(self) -> dict[str, Any]:
        return self._send("GET", "/v1/version")

    def capabilities(self) -> dict[str, Any]:
        return self._send("GET", "/v1/capabilities")

    def health(self) -> dict[str, Any]:
        return self._send("GET", "/v1/health")

    # -- sources / jobs / locators -----------------------------------------
    def ingest_source(
        self,
        content: str,
        *,
        media_kind: str = "txt",
        original_name: str | None = None,
        source_id: str | None = None,
        work_id: str | None = None,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"media_kind": media_kind, "content": content}
        if original_name is not None:
            body["original_name"] = original_name
        if source_id is not None:
            body["source_id"] = source_id
        if work_id is not None:
            body["work_id"] = work_id
        return self._send("POST", "/v1/sources", json=body)

    def get_job(self, job_id: str) -> dict[str, Any]:
        return self._send("GET", f"/v1/jobs/{job_id}")

    def wait_job(self, job_id: str, *, timeout_s: float = 15.0) -> dict[str, Any]:
        import time

        deadline = time.monotonic() + timeout_s
        while True:
            job = self.get_job(job_id)
            if job.get("status") not in ("running", "pending", "queued", "started"):
                return job
            if time.monotonic() >= deadline:
                raise TimeoutError(f"job {job_id} did not reach a terminal state")
            time.sleep(0.05)

    def get_source(self, source_id: str) -> dict[str, Any]:
        return self._send("GET", f"/v1/sources/{source_id}")

    def list_segments(
        self, source_id: str, *, limit: int = 20, cursor: str | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        return self._send("GET", f"/v1/sources/{source_id}/segments", params=params)

    def get_locator(
        self, object_id: str, *, start: int = 0, length: int | None = None
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"start": start}
        if length is not None:
            params["length"] = length
        return self._send("GET", f"/v1/locators/{object_id}", params=params)

    def rerun_source(self, source_id: str) -> dict[str, Any]:
        return self._send("POST", f"/v1/sources/{source_id}/rerun")

    # -- entities / claims / corrections ------------------------------------
    def create_entity(self, ref: str, label: str) -> dict[str, Any]:
        return self._send("POST", "/v1/entities", json={"ref": ref, "label": label})

    def list_entities(self, *, limit: int = 20, cursor: str | None = None) -> dict[str, Any]:
        params: dict[str, Any] = {"limit": limit}
        if cursor is not None:
            params["cursor"] = cursor
        return self._send("GET", "/v1/entities", params=params)

    def create_claim(
        self,
        predicate_code: str,
        subject_ref: str,
        object_ref: str,
        confidence: float = 0.8,
    ) -> dict[str, Any]:
        return self._send(
            "POST",
            "/v1/claims",
            json={
                "predicate_code": predicate_code,
                "subject_ref": subject_ref,
                "object_ref": object_ref,
                "confidence": confidence,
            },
        )

    def edit_segment(self, segment_id: str) -> dict[str, Any]:
        return self._send("POST", f"/v1/segments/{segment_id}/edit")

    # -- query / search -----------------------------------------------------
    def structured_query(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._send("POST", "/v1/query/structured", json=payload)

    def semantic_query(
        self, question: str, *, consistency_token: int | None = None
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"question": question}
        if consistency_token is not None:
            body["consistency_token"] = consistency_token
        return self._send("POST", "/v1/query/semantic", json=body)

    def search(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self._send("POST", "/v1/search", json=payload)


def run_demo(api: PublicContractClient, *, stage: _STAGE | None = None) -> dict[str, Any]:
    """Run a full, self-asserting demonstration of the public v1 contract.

    ``stage`` gates only server-side projection-state transitions needed to
    exercise the two 503 consistency classes (see module docstring). Returns a
    summary dict (also used by the integration test).
    """
    noop: _STAGE = lambda _name: None
    on = stage or noop

    result: dict[str, Any] = {}

    # -- 1. system metadata -------------------------------------------------
    ver = api.version()
    assert ver["api_version"] == "v1"
    caps = api.capabilities()
    result["api_version"] = ver["api_version"]
    result["semantic_authority"] = caps["capabilities"]["semantic_authority"]

    # -- 2. ingest (returns a read-your-writes consistency token) -----------
    content = "The quick brown fox jumps over the lazy dog. Sherlock Holmes investigates."
    src = api.ingest_source(content=content, media_kind="txt", original_name="affair.txt")
    sid, sha512 = src["source_id"], src["sha512"]
    assert src["consistency_token"] >= 1
    result["source_id"] = sid

    # -- 3. job polling (API job facade; no provider coupling) ---------------
    job = api.wait_job(f"job-{sid[:12]}")
    assert job["status"] == "complete"
    result["job_status"] = job["status"]

    # -- 4. source metadata + segments ---------------------------------------
    meta = api.get_source(sid)
    assert meta["source_id"] == sid
    segs = api.list_segments(sid, limit=10)
    result["segments"] = segs.get("total", 0)

    # -- 5. typed semantic content (write path) ------------------------------
    assert api.create_entity("e:hero", "Sherlock")["action"] == "create"
    assert api.create_entity("e:villain", "Moriarty")["action"] == "create"
    claim = api.create_claim(
        predicate_code="SPEAKS",
        subject_ref="e:hero",
        object_ref="The game is afoot, Watson",
        confidence=0.8,
    )
    write_token = claim["consistency_token"]  # read-your-writes token
    assert write_token >= 1
    result["write_token"] = write_token

    # -- 6. transient-lag 503: ledger advanced, projection not yet built -----
    on("projections_behind")  # no-op unless the harness stages unbuilt projections
    try:
        api.structured_query({"kind": "UTTERANCE", "consistency_token": write_token})
        raise AssertionError("expected a transient-lag 503")
    except ApiError as exc:
        assert exc.status == 503
        assert exc.x_consistency == "transient-lag", exc.x_consistency
        assert exc.retryable is True
        result["transient_lag_503"] = exc.code

    # -- 7. catch up, then a fresh token-bearing read ------------------------
    on("projections_caught_up")
    q = api.structured_query({"kind": "UTTERANCE", "consistency_token": write_token})
    assert q["bound_report"]["bounded"] is True
    assert q["freshness"]["status"] == "fresh"
    assert q["freshness"]["applied_seq"] >= write_token
    assert any(res["value"] == "The game is afoot, Watson" for res in q["results"])

    # -- 8. semantic query compiles to typed ops (never unstructured RAG) ----
    sab = api.semantic_query("what does e:hero say", consistency_token=write_token)
    assert "UTTERANCE" in sab["compiled_ops"]
    assert "typed relational" in sab["provenance"]["authority"]
    result["semantic_ops"] = sab["compiled_ops"]

    # -- 9. exact search with result-kind labels -----------------------------
    s = api.search({"query": "afoot", "mode": "exact"})
    assert s["total"] >= 1
    assert all(hit["kind"] and hit["label"] for hit in s["hits"])
    result["search_total"] = s["total"]

    # -- 10. source-native retrieval via content-addressed object ------------
    loc = api.get_locator(f"urn:umd:ocfl:source:sha512:{sha512}", start=0, length=1000)
    decoded = base64.b64decode(loc["data_b64"]).decode("utf-8")
    assert decoded == content
    result["locator_object"] = loc["object_id"]

    # -- 11. untokened read exposes freshness metadata -----------------------
    u = api.structured_query({"kind": "ENTITY", "filters": {"ref": "e:hero"}})
    assert u["freshness"] is not None
    result["untokened_freshness"] = bool(u["freshness"])

    # -- 12. correction returns a read-your-writes token --------------------
    edit = api.edit_segment("seg-1")
    assert edit["action"] == "edit"
    assert edit["consistency_token"] >= 1
    result["correction_token"] = edit["consistency_token"]

    # -- 13. cursor pagination over a collection ----------------------------
    p1 = api.list_entities(limit=1)
    assert p1["total"] >= 2 and p1["next_cursor"] is not None
    p2 = api.list_entities(limit=1, cursor=p1["next_cursor"])
    assert p2["prev_cursor"] is not None
    assert p2["items"][0]["ref"] != p1["items"][0]["ref"]
    result["pagination"] = True

    # -- 14. RFC 7807 structured error (404 not_found) ----------------------
    try:
        api.get_source("definitely-not-a-source")
        raise AssertionError("expected a 404")
    except ApiError as exc:
        assert exc.status == 404 and exc.code == "not_found"
        assert exc.type.startswith("urn:umd:problem:")
        result["rfc7807"] = exc.code

    # -- 15. rebuild-in-progress 503 (projection paused by harness/ops) -----
    on("projection_paused")
    try:
        api.structured_query({"kind": "UTTERANCE", "consistency_token": write_token})
        raise AssertionError("expected a rebuild-in-progress 503")
    except ApiError as exc:
        assert exc.status == 503
        assert exc.x_consistency == "rebuild-in-progress", exc.x_consistency
        assert float(exc.retry_after) >= 30
        result["rebuild_in_progress_503"] = exc.code
    on("resume")

    # -- 16. selective rerun (source-scoped, no storage coupling) -----------
    rr = api.rerun_source(sid)
    assert rr["action"] == "rerun" and rr["job_id"]
    result["rerun_job"] = rr["job_id"]

    return result


def main(argv: list[str] | None = None) -> None:
    """Run the demo against a live server (base url + bearer key from argv/env)."""
    import argparse
    import os

    parser = argparse.ArgumentParser(description="UMD public-contract demo")
    parser.add_argument(
        "--base-url", default=os.environ.get("UMD_BASE_URL", "http://localhost:8080")
    )
    parser.add_argument("--api-key", default=os.environ.get("UMD_API_KEY"))
    args = parser.parse_args(argv)
    api = PublicContractClient(base_url=args.base_url, api_key=args.api_key)
    try:
        summary = run_demo(api)
    finally:
        api.close()
    print(summary)


if __name__ == "__main__":
    main()
