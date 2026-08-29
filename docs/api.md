# Versioned API Reference (`/v1`)

FastAPI generates a versioned OpenAPI document at `/openapi.json`. Every ID is
stable, collection responses are **cursor/page paginated**, and failures use
**RFC 7807** structured errors with machine-readable `type`, `code`, `detail`,
`correlation_id`, and `retryable`.

## Authentication and rate limiting

- Present a key as `Authorization: Bearer <key>` **or** `X-API-Key: <key>`.
  When no keys are configured (empty `UMD_AUTH__API_KEYS`) auth is disabled.
- Different keys may be split into **read keys** and **write keys**
  (`UMD_AUTH__WRITE_KEYS`). Mutating endpoints require a write-capable key
  (else `403 forbidden`).
- Every request is rate limited per (authenticated key / client IP) with a
  real token bucket. Exceeding the bucket returns `429` with `Retry-After`
  (`code: rate_limited`, `retryable: true`).
- Responses include `x-correlation-id` (echoed from `x-request-id` or
  generated).

## Sources / locators / evidence / report

| Method + path | Auth | Body / params | Response |
|---|---|---|---|
| `POST /v1/sources` | write | `SourceIngestRequest` | `201` `SourceDescriptorResponse` |
| `POST /v1/sources/{media_kind}` | write | `media_kind` path variant | `201` `SourceDescriptorResponse` |
| `GET /v1/sources/{source_id}` | read | — | `SourceDetailResponse` |
| `GET /v1/sources/{source_id}/segments` | read | `limit` (20, 1–200), `cursor` | `SegmentListResponse` |
| `GET /v1/segments/{segment_id}/evidence` | read | `limit`, `cursor` | `EvidenceListResponse` |
| `GET /v1/locators/{source_ref}` | read | `start` (>=0), `length` (>=1) | `LocatorRangeResponse` |
| `POST /v1/sources/{source_id}/rerun` | write | — | `202` `{job_id, action, targets}` |
| `GET /v1/sources/{source_id}/report` | read | — | per-source decomposition report |
| `GET /v1/sources/{source_id}/analysis` | read | — | `{source_id, job_id, status, events}` |

**Ingest** (`SourceIngestRequest`): `media_kind` (default `txt`), `work_id`,
`original_name`, `source_id`, `content_type`, and `content` (inline text). When
`work_id` is omitted, ingestion creates a new work and returns its canonical ID;
when supplied, it must identify an existing work. The bytes are stored
immutably to OCFL (sha512 content-addressed), a source membership row is
created, a `SourceIngested` ledger event is appended, and a decomposable job is
submitted. Returns `source_id`, `work_id`, `ocfl_ref`, `sha512`, `size_bytes`,
`media_kind`, `seq`, and `consistency_token`.

**Source-native retrieval** (`LocatorRangeResponse`): `object_id`,
`logical_name`, `sha512`, `size_bytes`, `start`, `end`, `truncated`, and
`data_b64` (base64-encoded bounded bytes).

## Entities

| Method + path | Auth | Body / params | Response |
|---|---|---|---|
| `GET /v1/entities` | read | `limit`, `cursor` | `EntityListResponse` |
| `GET /v1/entities/{ref}` | read | — | `EntityResponse` |
| `POST /v1/entities` | write | `EntityCreateRequest` | `201` `EntityActionResponse` |
| `POST /v1/entities/{ref}/lock` | write | — | `EntityActionResponse` |
| `POST /v1/entities/{ref}/unlock` | write | — | `EntityActionResponse` |
| `POST /v1/entities/{ref}/merge` | write | `target_entity_ref` | `EntityActionResponse` |
| `POST /v1/entities/{ref}/split` | write | `targets` (list) | `EntityActionResponse` |

`EntityActionResponse` carries `entity_ref`, `action`, `seq`, and
`consistency_token` (and `detail` on merge/split). MERGE/SPLIT reach the full
reversible resolver (ledger + mention rebind + quarantine), returning
`422 invalid_merge` / `422 invalid_split` on rejection.

## Claims

| Method + path | Auth | Body / params | Response |
|---|---|---|---|
| `POST /v1/claims` | write | `ClaimCreateRequest` | `201` `ClaimResponse` |
| `POST /v1/claims/{ref}/override` | write | `ClaimMutationRequest` | `ClaimResponse` |
| `POST /v1/claims/{ref}/invalidate` | write | `ClaimMutationRequest` | `ClaimResponse` |
| `GET /v1/claims/{ref}/provenance` | read | — | `ProvenanceResponse` |

`ClaimCreateRequest`: `predicate_code`, `subject_ref`, `object_ref`,
`confidence` (0–1), `scope` (default `GLOBAL`), `support_refs`.
`ClaimMutationRequest`: `cause`, `reason`, `scope`, `stage`, `refs`.

## Segments (edits / correction)

| Method + path | Auth | Body / params | Response |
|---|---|---|---|
| `POST /v1/segments/{segment_id}/edit` | write | `ref` (query) | `EntityActionResponse` |
| `POST /v1/segments/{segment_id}/split` | write | — | `EntityActionResponse` |
| `POST /v1/segments/{segment_id}/merge` | write | — | `EntityActionResponse` |
| `POST /v1/segments/{segment_id}/rerun` | write | — | `202` `{segment_id, action, job_id}` |

Segment edits record `CorrectionApplied` / `SEGMENT_SPLIT` / `SEGMENT_MERGE`
ledger events and return a read-your-writes `consistency_token`.

## Alignment

| Method + path | Auth | Body / params | Response |
|---|---|---|---|
| `POST /v1/alignment` | write | `left_ref`, `right_ref`, `alignment_type` (default `EQUIVALENT`) | `201` `EntityActionResponse` |

## Jobs

| Method + path | Auth | Response |
|---|---|---|
| `GET /v1/jobs/{job_id}` | read | `JobResponse` (`id`, `source_id`, `dag_universe`, `status`, `request`, `cancelled_stages`, `error`) |
| `GET /v1/jobs/{job_id}/events` | read | `list` of stage events |
| `POST /v1/jobs/{job_id}/cancel` | write | `JobActionResponse` |
| `POST /v1/jobs/{job_id}/retry` | write | `JobActionResponse` |

## Query

| Method + path | Auth | Response |
|---|---|---|
| `POST /v1/query/structured` | read | `StructuredQueryResponse` |
| `POST /v1/query/semantic` | read | `SemanticQueryResponse` |

Both accept an optional `consistency_token` and embed `freshness`. See
[query-search.md](query-search.md).

## Search

| Method + path | Auth | Response |
|---|---|---|
| `POST /v1/search` | read | `SearchResponse` |

## Audit

| Method + path | Auth | Response |
|---|---|---|
| `GET /v1/audit/{subject}` | read | `AuditResponse` (`subject`, `explanation`) |

Query params: `as_of` (datetime), `causation` (>=0), `correlation`.

## System

| Method + path | Auth | Response |
|---|---|---|
| `GET /v1/health` | read | `HealthResponse` — projection freshness/lag/pause state per component; degrades when a projection is not fresh |
| `GET /v1/ready` | read | `200 {status: ready}` or `503` when a projection is rebuilding |
| `GET /v1/capabilities` | read | `CapabilitiesResponse` — enabled modalities, providers (active vs GATED), sandbox posture, query limits, `semantic_authority` |
| `GET /v1/metrics` | read | in-process metric registry snapshot + OTel export gate |
| `GET /v1/version` | read | `VersionResponse` — service, `api_version` (`v1`), `contract_version` (`1.0.0`), `dag_universe`, `schema_version` |

## Errors — RFC 7807

Every failure returns `application/problem+json` with a `type` under
`urn:umd:problem:<code>`, plus `title`, `status`, `code`, `detail`,
`retryable`, and `correlation_id`. Notable codes:

| Code | HTTP | retryable |
|---|---|---|
| `unauthorized` | 401 | no |
| `forbidden` | 403 | no |
| `not_found` | 404 | no |
| `conflict` / `retry_failed` / `rerun_failed` | 409 | yes / no |
| `validation_error` | 422 | no |
| `invalid_query` / `unmappable_scope` / `invalid_merge` / `invalid_split` | 422 | no |
| `rate_limited` | 429 | yes |
| `consistency_transient_lag` / `consistency_rebuild` | 503 | yes |
| `not_ready` | 503 | yes |

503 consistency responses additionally set `Retry-After` and `x-consistency`
(`transient-lag` or `rebuild-in-progress`, the latter with `x-rebuild-estimate`).
See [consistency.md](consistency.md) and [query-search.md](query-search.md).