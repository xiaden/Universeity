#!/usr/bin/env bash
# =============================================================================
# Universal Media Decomposer — maintained curl example (public /v1 contract).
#
# Demonstrates the versioned public REST surface with GENUINELY runnable curl
# commands. It uses ONLY public /v1 endpoints — never internal storage, provider,
# or ledger APIs. Run against a live deployment:
#
#   BASE_URL=http://localhost:8080 WRITE_KEY=<write-key> ./curl.sh
#
# Read the printed notes: the two 503 consistency classes and RFC 7807 handling
# are demonstrated with real curl + jq, and their server-side triggers are
# documented in comments (projection state is controlled by operators/builders,
# not by the public API).
# =============================================================================
set -euo pipefail

BASE_URL="${BASE_URL:-http://localhost:8080}"
WRITE_KEY="${WRITE_KEY:?set WRITE_KEY to a write-capable API key}"
READ_KEY="${READ_KEY:-$WRITE_KEY}"
W="Authorization: Bearer $WRITE_KEY"
R="Authorization: Bearer $READ_KEY"
jq_present=0; command -v jq >/dev/null 2>&1 && jq_present=1

say()  { printf '\n\033[1;36m==> %s\033[0m\n' "$*"; }
jqr() { if [ "$jq_present" = 1 ]; then jq -r "$@"; else cat; fi; }

# Bounded-backoff token-bearing query that honors Retry-After and distinguishes
# the two 503 classes (transient-lag vs rebuild-in-progress).
query_with_token() {
  local payload="$1" attempt=1 code body
  while [ "$attempt" -le 8 ]; do
    body="$(curl -fsS -H "$R" -H 'content-type: application/json' \
      -d "$payload" "$BASE_URL/v1/query/structured" || true)"
    code="$(printf '%s' "$body" | jqr '.code // ""')"
    if [ -n "$code" ] && [ "$code" = "consistency_transient_lag" ]; then
      retry=$(printf '%s' "$body" | jqr '.retry_after // 1')
      printf '  [%s] transient-lag -> backing off %.0fs (retry-after honored)\n' "$attempt" "$retry"
      sleep "$retry"; attempt=$((attempt+1)); continue
    fi
    if [ -n "$code" ] && [ "$code" = "consistency_rebuild" ]; then
      retry=$(printf '%s' "$body" | jqr '.retry_after // 30')
      printf '  [%s] rebuild-in-progress -> x-consistency=rebuild-in-progress, wait %.0fs\n' "$attempt" "$retry"
      sleep "$retry"; attempt=$((attempt+1)); continue
    fi
    printf '%s' "$body"; return 0
  done
  echo "{}"
}

say "version"
curl -fsS -H "$R" "$BASE_URL/v1/version"

say "capabilities (honest gate disclosure)"
curl -fsS -H "$R" "$BASE_URL/v1/capabilities" | jqr '.capabilities | {semantic_authority, relationships_bounded, query_max_depth, vector}'

say "ingest a source (returns sha512 + read-your-writes consistency_token)"
ingest="$(curl -fsS -X POST -H "$W" -H 'content-type: application/json' \
  -d '{"media_kind":"txt","original_name":"affair.txt","content":"The quick brown fox jumps over the lazy dog. Sherlock Holmes investigates."}' \
  "$BASE_URL/v1/sources")"
source_id="$(printf '%s' "$ingest" | jqr .source_id)"
sha512="$(printf '%s' "$ingest" | jqr .sha512)"
token="$(printf '%s' "$ingest" | jqr .consistency_token)"
printf '  source_id=%s token=%s\n' "$source_id" "$token"

say "poll the decomposable job (API job facade; no provider coupling)"
curl -fsS -H "$R" "$BASE_URL/v1/jobs/job-${source_id:0:12}"

say "source metadata"
curl -fsS -H "$R" "$BASE_URL/v1/sources/$source_id"

say "entities + claim (write path)"
curl -fsS -X POST -H "$W" -H 'content-type: application/json' -d '{"ref":"e:hero","label":"Sherlock"}' "$BASE_URL/v1/entities" >/dev/null
curl -fsS -X POST -H "$W" -H 'content-type: application/json' -d '{"ref":"e:villain","label":"Moriarty"}' "$BASE_URL/v1/entities" >/dev/null
claim="$(curl -fsS -X POST -H "$W" -H 'content-type: application/json' \
  -d '{"predicate_code":"SPEAKS","subject_ref":"e:hero","object_ref":"The game is afoot, Watson","confidence":0.8}' \
  "$BASE_URL/v1/claims")"
write_token="$(printf '%s' "$claim" | jqr .consistency_token)"
printf '  claim consistency_token=%s\n' "$write_token"

say "token-bearing structured query (read-your-writes; 503s handled with backoff)"
query_with_token "{\"kind\":\"UTTERANCE\",\"consistency_token\":$write_token}" | jqr 'if .results then {results, fresh: .freshness.status, bounded: .bound_report.bounded} else . end'

say "semantic query (compiles to typed ops, never unstructured-only RAG)"
curl -fsS -X POST -H "$R" -H 'content-type: application/json' \
  -d "{\"question\":\"what does e:hero say\",\"consistency_token\":$write_token}" \
  "$BASE_URL/v1/query/semantic"

say "exact search"
curl -fsS -X POST -H "$R" -H 'content-type: application/json' -d '{"query":"afoot","mode":"exact"}' "$BASE_URL/v1/search"

say "source-native retrieval (content-addressed object)"
curl -fsS -H "$R" "$BASE_URL/v1/locators/urn:umd:ocfl:source:sha512:$sha512?start=0&length=1000"

say "untokened read exposes freshness metadata"
curl -fsS -X POST -H "$R" -H 'content-type: application/json' \
  -d '{"kind":"ENTITY","filters":{"ref":"e:hero"}}' "$BASE_URL/v1/query/structured" \
  | jqr '.freshness'

say "correction (segment edit) returns a read-your-writes token"
curl -fsS -X POST -H "$W" "$BASE_URL/v1/segments/seg-1/edit"

say "cursor pagination over a collection"
curl -fsS -H "$R" "$BASE_URL/v1/entities?limit=1" | jqr '{total, next_cursor}'

say "RFC 7807 structured error (unknown source => 404 not_found)"
curl -sS -H "$R" "$BASE_URL/v1/sources/definitely-not-a-source"
printf '\n'

say "selective source rerun (source-scoped)"
curl -fsS -X POST -H "$W" "$BASE_URL/v1/sources/$source_id/rerun"

printf '\n\033[1;36m==> Consistency response classes (how to observe)\033[0m\n'
cat <<'EOF'
Token-bearing reads (structured/semantic/search) may return a 503 with:
  * x-consistency: transient-lag        -> projection behind; Retry-After backoff
  * x-consistency: rebuild-in-progress  -> projection paused for authority rebuild;
                                           long Retry-After; poll rebuild/job status
Both require OPERATOR-controlled projection state (projection rebuild/pause via
builders/ops, see docs/consistency.md); the public API never fabricates them.
A deterministic, staged demonstration of BOTH classes is executed in CI by
tests/test_docs_examples.py running docs/examples/python_client.py.
EOF