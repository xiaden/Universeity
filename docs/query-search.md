# Structured Query, Semantic Query, and Search

## Typed structured query — `POST /v1/query/structured`

The request carries a typed `kind`, optional `ref`, typed `filters`, an optional
`consistency_token`, and optional scope — and is **bounded**.

`StructuredQueryRequest`:
- `kind` (required, one of): `ENTITY`, `UTTERANCE`, `SCENE`, `EVIDENCE`,
  `CORRESPONDENCE`, `CONTRADICTIONS`, `UNRESOLVED_ALIASES`, `TRAVERSAL`.
- `ref`, `filters` (JSONB), `confidence_min`, `result_kind`, `max_depth`
  (0–8, clamped to the configured cap), `limit`, `offset`,
  `continuity_id`, `temporal_from`, `temporal_to`, `spatial`.

**Scope filters:**

- `continuity_id` narrows to rows of the matching continuity's source(s).
- `temporal_from`/`temporal_to` narrow by segment start/end time ranges.
- `spatial` narrows via indexed JSONB containment.
- All scope absent → the query stays **unfiltered**.
- An **unmappable** scope (e.g. a `temporal_*` filter on a query whose backing
  op has no temporal column) is an explicit RFC 7807 **`422 unmappable_scope`**
  — it is never silently ignored (which would return misleading unfiltered
  results).

The response (`StructuredQueryResponse`) carries the compiled `query`, `results`
(ref, kind, label, predicate, value, score, confidence, source_id, segment_id,
data), `total`, `result_kinds`, `provenance`, a `bound_report` (with `bounded`),
and `freshness`. Bounded query-cost limits (`query_cost.max_depth`,
`max_limit`, `default_limit`) are applied server-side and cap the page/traversal.

## Semantic query — `POST /v1/query/semantic`

`SemanticQueryRequest` carries a natural-language `question`, optional
`consistency_token`, and optional `constraints`.

The `QuestionService` compiles **supported** questions into **typed operations**
(`compiled_ops`) against the same bounded relational surface. The service
**never answers from an unstructured-only RAG corpus** — there is no opaque
corpus as semantic authority. The response is a `StructuredAnswer`: `question`,
`compiled_ops`, `answer`, `interpretation`, `confidence`, `support` (claims with
locators), `alternatives`, `unresolved`, `contradictory`, `result_kind_labels`,
`provenance`, `bound_report`, and `freshness`. Each answer item is labeled with
its result kind and evidence support.

## Exact / fuzzy / hybrid search — `POST /v1/search`

`SearchRequest`: `query`, `mode` (`exact|fuzzy|hybrid`, default `hybrid`), and
optional `source_id`, `segment_id`, `entity_ref`, `kind`, `language`,
`locator_prefix`, `limit`, `offset`, `consistency_token`.

- **exact** — PostgreSQL `tsvector`/`pg_trgm` exact phrase/name matching.
- **fuzzy** — `pg_trgm` fuzzy matching.
- **hybrid** — fuses exact + vector (cosine) scores with a configured vector
  weight when a vector backend is available, and **degrades honestly** to exact
  when the pgvector-HNSW backend is gated/inactive.

Every hit carries `ref`, `kind`, `text`, `score`, `exact_score`,
`vector_score`, and a **result-kind `label`** (`SOURCE_EVIDENCE` |
`INTERPRETATION` | `CANONICAL_ENTITY`). The response also reports the active
`engine` and `vector_backend`, cursor pagination, and `freshness`. The vector
search is served through `VectorIndex`; pgvector-HNSW activates only above the
configured `vector_hnsw_min_version` gate (see [providers.md](providers.md)).

## Pagination

Collections are **cursor/page paginated**. The response carries an opaque
`next_cursor` and `prev_cursor` (a URL-safe encoding of a server-side position;
clients can never forge a position outside the bounded query surface).
`POST /v1/query/structured` and `POST /v1/search` also accept numeric `limit` /
`offset`. Malformed or out-of-range cursors raise `400 invalid_cursor`.

## Consistency tokens on reads

`POST /v1/query/structured`, `POST /v1/query/semantic`, and `POST /v1/search`
accept a `consistency_token`. Tokened reads wait within the bounded lag budget
then **503** with `Retry-After` and `x-consistency: transient-lag|rebuild-in-progress`
if the projection cannot catch up; untokened reads embed `freshness`. Full
semantics in [consistency.md](consistency.md).

## Worked request/response shapes

```json
POST /v1/query/structured
{
  "kind": "UTTERANCE",
  "ref": "e:hero",
  "consistency_token": 5,
  "continuity_id": null
}
```

```json
{
  "query": "...", "results": [{"ref": "...", "kind": "utterance", "value": "...", "score": 1.0,
    "confidence": 0.8, "source_id": "...", "segment_id": "...", "data": {}}],
  "total": 1, "result_kinds": ["SOURCE_EVIDENCE"],
  "bound_report": {"bounded": true},
  "freshness": {"projection": "current_tier1", "applied_seq": 5, "ledger_tail": 5,
    "lag": 0, "status": "fresh", "paused": false}
}
```

```json
POST /v1/query/semantic
{ "question": "what does e:hero say", "consistency_token": 5 }
```
```json
{ "compiled_ops": ["UTTERANCE"], "answer": [{"kind": "utterance", "value": "..."}],
  "support": [{"locator": "..."}], "provenance": {"authority": "typed relational"}, ... }
```

```json
POST /v1/search
{ "query": "afoot", "mode": "exact" }
```
```json
{ "engine": "exact", "vector_backend": "exact-fallback-in-process",
  "hits": [{"ref": "...", "kind": "utterance", "text": "...", "score": 0.9,
    "exact_score": 0.9, "label": "SOURCE_EVIDENCE"}], "total": 1, "freshness": {...} }
```