# Structured Query, Semantic Query, and Search

## Typed structured query — `POST /v1/query/structured`

The request carries a typed `kind`, optional `ref`, typed `filters`, an optional
`consistency_token`, and optional scope — and is **bounded**.

`StructuredQueryRequest`:
- `kind` (required, one of): `ENTITY`, `UTTERANCE`, `SCENE`, `EVIDENCE`,
  `CORRESPONDENCE`, `CONTRADICTIONS`, `UNRESOLVED_ALIASES`, `TRAVERSAL`,
  `RELATIONSHIP_EDGES`.
- `ref`, `filters` (JSONB), `confidence_min`, `result_kind`, `max_depth`
  (0–8, clamped to the configured cap), `limit`, `offset`,
  `continuity_id`, `temporal_from`, `temporal_to`, `spatial`.

### Relationship edges — `RELATIONSHIP_EDGES`

`RELATIONSHIP_EDGES` reads the **active relationship-edge projection**
(`active_semantic_edge`, a bounded, replay-built multi-edge read side) rather
than the scalar `current_state`. It is the typed surface for the edges that
relate entities by any active predicate — both non-utterance (e.g. `HAS_EMOTION`,
`CO_OCCURS`) and utterance predicates (`SPEAKS`, `SAYS`, `UTTERANCE`,
`PRONUNCIATION`). The active edge set — including every currently-active fact per
`(subject_ref, predicate)` (multi-edge), with `USER_OVERRIDE` precedence over
machine inferences and states such as `CONFLICTING`; superseded / invalidated
edges are retained as inactive history and excluded from this active read side —
is the read side; the projection builder is the **sole writer** of
`active_semantic_edge`, and the API never writes it.

- `filters.subject` narrows to edges anchored on that subject (or, when the
  query has a `ref`, edges where `ref` is the subject or object).
- Each public edge hit carries `provenance` = {`fact_id` (the content-
  addressable edge identity), `state`, `scope`, `seq`} plus `data` =
  {`authority` (`machine` | `USER_OVERRIDE`), `state`, `scope`}, and exposes
  `predicate`, `value` (object ref), and `confidence`. The source-evidence refs
  (`support_refs`/`contradiction_refs`) live on the stored `active_semantic_edge`
  row only and are not part of the public hit provenance.
- Every active edge is enumerated — superseded edges are retained as inactive
  history, never returned as active.
- Relationship **semantic questions** ("what is the relationship between `e:hero`
  and `e:villain`") compile to the `RELATIONSHIP_EDGES` op and draw their answer
  from the active edge store (never unstructured RAG).


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

**Per-surface freshness gating.** The read surface is gated on the freshness of
the projection it reads, not a single scalar:

- Scalar / non-edge reads (`ENTITY`, `UTTERANCE`, …) are gated on the
  `current_tier1` `query_guard`.
- **Edge-derived reads** — `RELATIONSHIP_EDGES` structured queries and
  relationship semantic questions — read `active_semantic_edge`, so their
  token-bearing freshness wait and 503 behavior are gated on the `semantic_edges`
  **`edge_guard`** (bounded freshness over that projection). A token-bearing edge
  read 503s (`transient-lag`) while the edge store trails the token even when
  `current_tier1` is already fresh — it is never served from a lagging edge store.
- `POST /v1/search` is gated on the `search` `search_guard`.

**Search reconciles edge-derived documents.** `SearchProjectionBuilder` is the
sole writer of the search document store and indexes **active** relationship
edges as typed `INTERPRETATION` hits: non-utterance predicates (e.g.
`HAS_EMOTION`, `CO_OCCURS`) under the `edge:%` ref family and utterance
predicates (`SPEAKS`, `SAYS`, `UTTERANCE`, `PRONUNCIATION`) under the `assert:%`
ref family. Every incremental search `finalize` deterministically reconciles
BOTH families against the current active edge set (the immutable event stream is
no longer a search-doc source for utterances) — superseded / corrected /
overridden docs are deleted and only the currently-active edges are reindexed,
so a stale superseded object term is never searchable and the corrected
utterance text is always indexed. Because
search `finalize` reads `active_semantic_edge`, it is serialized against the
`semantic_edges` rebuild lock and requires the edge checkpoint to have reached
the search replay target; if the edge store lags, the search rebuild aborts
(rolling back, so the search checkpoint is never advanced and no edge doc is
written from a lagging edge store) until edges catch up.


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