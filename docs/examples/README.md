# Maintained Client Examples (public `/v1` contract only)

These examples demonstrate the versioned public REST surface — `POST /v1/sources`
(ingest), job polling, `POST /v1/query/structured` and `POST /v1/query/semantic`
(typed/semantic query), `POST /v1/search`, `GET /v1/locators/{ref}` (source-native
retrieval), segment correction, selective rerun, cursor pagination, RFC 7807
errors, read-your-writes tokens, and **both** Tier-1 consistency response
classes. They use **only** public `/v1` endpoints — no internal storage,
provider, or ledger API.

## Files

| File | Runs against | Demonstrates |
|---|---|---|
| `python_client.py` | live server **or** app-under-test | full flow incl. both 503 classes + RFC 7807 (self-asserting `run_demo`) |
| `curl.sh` | live server | the same public flow in curl + jq, with a bounded-backoff token query |

## Python client

```bash
# against a live deployment
python docs/examples/python_client.py --base-url http://localhost:8080 --api-key <write-key>
```

The same code is executed against the real app in CI by
`tests/test_docs_examples.py` (via the synchronous FastAPI `TestClient`),
proving the example is maintained and not stale. `PublicContractClient` keeps
all semantic/storage/provider authority on the server; the client only
constructs requests and decodes RFC 7807 bodies.

### The two 503 consistency classes

A token-bearing read may return `503` while the projection catches up:

- `x-consistency: transient-lag` — projection is behind the token; back off by
  `Retry-After` and retry.
- `x-consistency: rebuild-in-progress` — projection is paused for an authority
  rebuild; honor the long `Retry-After` and poll rebuild/job status rather than
  hammer reads.

The public API never fabricates these; they require operator-controlled
projection state. `run_demo` therefore accepts a `stage(name)` callback, which
in the test drives the real rebuild/pause path (see `tests/test_docs_examples.py`
and `docs/consistency.md`).

Machine behavior to be precise about: `run_demo` **asserts both 503 classes
unconditionally** — it never skips them based on whether ``stage`` is supplied.
`rebuild-in-progress` can never arise naturally on a caught-up server (the
projection is paused only by an operator/authority rebuild), so without a
`stage()` hook that pins the projection as paused, that assertion fails. Without
staging, an un-staged run therefore exercises the full public flow (ingest,
query, search, retrieval, correction, rerun, pagination, RFC 7807,
read-your-writes, transient-lag) but will crash at the rebuild-in-progress
assertion. The two 503 assertions require the `stage()` operator hook — pass it
in tests or via `tests/test_docs_examples.py`; do not claim an un-staged live run
exercises the 503 classes.

## curl

```bash
BASE_URL=http://localhost:8080 WRITE_KEY=<write-key> ./docs/examples/curl.sh
```

The script uses the real paths, methods, JSON bodies, and auth headers from
`docs/api.md`, and its `query_with_token` helper implements bounded backoff that
honors `Retry-After` and distinguishes the two `x-consistency` values. The
consistency **classes** are documented at the end with their operator-controlled
triggers and are deterministically tested in CI by the Python example test.

## Why these are trustworthy

- Paths/methods/bodies/headers are taken directly from the implemented routers
  (`docs/api.md`), not invented.
- `tests/test_docs_examples.py` passes only if the Python example runs green
  against the real app — so any contract drift fails CI.
- No provider/storage coupling: the client never names a vector backend, model,
  ledger, or storage implementation; it uses only the public contract's
  "content-addressed object id" shape returned by ingest.