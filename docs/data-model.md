# Data Model, Events, and Provenance

## Typed relational core

The relational core uses stable UUIDv7/ULID-compatible IDs (concrete encoding is
an implementation detail) and foreign keys for `work`, `continuity`, `source`,
`source_membership`, `edition`, `segment`, `evidence`, `artifact`, `entity`,
`entity_mention`, `predicate`, `semantic_assertion`, `current_state`,
`current_entity_map`, `alignment`, `stage_run`, `job_run_audit`, `embedding`,
`projection_checkpoint`, `quarantine`, and `locator_rebase`. Core fields are
indexed and typed; extension fields use JSONB. A predicate dictionary permits
new predicates without a migration. High-value relationships (`SPEAKS`,
`PRESENT_IN`, `CORRESPONDS_TO`, `TRANSLATION_OF`, `ADAPTATION_OF`,
`DERIVED_FROM`, `CONTRADICTS`, `ALIAS_OF`, `EXPANDS`, `OMITS`, `REORDERS`,
`ALTERNATE_REALIZATION`) are validated vocabulary entries, not a closed
ontology.

The typed vocabulary covers work, continuity, source, edition, adaptation,
translation, character, person, organization, location, object, concept, scene,
event, action, utterance, relationship, state, emotion, goal, belief/knowledge,
timeline, presence, speaker identity, alias, visual appearance, environment,
music, sound, and cross-source correspondence.

Every evidence record identifies `source_id`, exact locator, evidence kind,
language, track/edition metadata, raw/normalized representation references,
extraction stage, tool/decoder/model versions, configuration digest, and
confidence/quality metadata. Assertions contain subject/object references,
predicate, authority, confidence, state
(`UNKNOWN|AMBIGUOUS|CONFLICTING|PROBABLE|CONFIRMED|USER_CONFIRMED`),
scope/continuity, valid-time/narrative-time fields, support and contradiction
references, derivation, and generated-by metadata.

## Append-only event envelope

```text
semantic_event(
  seq BIGSERIAL, event_type, event_version, schema_url,
  tx_time, valid_time, authority, confidence,
  generated_by, correlation_id, causation_id,
  payload JSONB, idempotency_key, created_by
)
```

- `seq` is the read-your-writes token returned to the client on a mutation.
- Payload schemas live under `schemas/events/<type>/v<n>.json`; historical rows
  are immutable.
- `idempotency_key` must be a valid UUID; ingest derives a stable one from the
  source id so a retried ingest of the same source is idempotent.

Event types include `SourceIngested`, `SourceAliased`, `FormatAnalyzed`,
`SegmentCreated`, `StageCompleted`, `JobRunAudit`, `EntityMentioned`,
`EntityResolved(MERGE|SPLIT|ALIAS)`, `ReferenceRebound`, `Aligned`,
`SemanticAsserted`, `ContradictionRecorded`, `OverrideApplied`,
`CorrectionApplied`, `Locked`, `Unlocked`, `Invalidated`, `LocatorRebased`, and
`HallucinationFiltered`. `JobRunAudit` is committed as an auditable
event/record but **excluded from semantic-state replay** to avoid sequence
inflation; the projector policy handles this type explicitly.

### Merge / split semantics (reversible, never destructive)

- **MERGE** records preserve mention-to-entity mappings and references known at
  merge time. A merge is a log record, never a delete.
- **SPLIT** performs a deterministic query at split-time sequence over **every**
  reference kind, including references created during the merged lifetime. Its
  payload carries explicit target assignments. `ReferenceRebound` records each
  reassignment. Ambiguous alignment/override/candidate/evidence references enter
  **quarantine** and are surfaced, never silently dropped.
- Merge/split is therefore a reversible projection operation. Tests prove all
  mentions and alignment/override/candidate/evidence references can be restored.

## Event / upcaster policy

- **Historical payloads are immutable and replayable.** Breaking changes to an
  event payload require a **new version** and a **pure upcaster chain**, never
  a rewrite of historical rows.
- `CI` replays every retained historical event fixture through every projection.
  The reducer is tested separately from payload construction so reducer
  determinism cannot hide malformed payloads.
- Payload-validation is against the retained JSON schemas using `jsonschema`.

## Reducer and consistency

`reduce_current_state(current_row, event)` is I/O-free, total, deterministic,
and bounded to indexed row operations. Winner selection is last-write-wins per
`(entity_ref, predicate)` after authority/lock rules, with numeric confidence
available for indexed threshold queries. Tier-0 is rebuilt by wiping and
replaying the log in tests. A mutation commits event and Tier-0 update
atomically and returns `read_your_writes_token = seq`.

## Semantic assertions, the mirror, and active relationship edges

**Assertion mirror materializes in the append transaction.** Every
`SemanticAsserted` appended through the command path is materialized into the
`semantic_assertion` table in the **same transaction** as the event append,
keyed by a deterministic content-addressable `fact_id` (derived from predicate,
subject/object refs, entity ids, and scope — never authority/evidence/seq, so a
rerun of the same fact maps to the same row and wipe-and-replay is stable). The
mirror is authoritative-agnostic in identity but preserves precedence: a locked
entity's machine assertion **never** writes a mirror row, and a later machine
reassertion of a fact whose mirror row carries `USER_OVERRIDE` authority leaves
that row at `USER_OVERRIDE` (it never downgrades the reduced winner). The mirror
stays a read-side projection of the event stream — events remain append-only,
and the reducer/edge authority semantics are unchanged.

**Active relationship-edge projection (`active_semantic_edge`).** The scalar
`current_state` is a single value per `(entity_ref, predicate)`; the active-edge
projection is a bounded **multi-edge** read side that retains every currently
`active` relationship fact, including multiple distinct facts sharing
`(subject_ref, predicate)` with different objects. It is a disposable,
single-writer, checkpointed wipe-and-replay projection: the projection builder
is the **only** writer, and no API/worker path writes it. It replays the
reconciliation predicates (`MENTIONED_IN`, `UTTERED_IN`, `HAS_TRAIT`,
`CO_OCCURS`, `HAS_EMOTION`, `IN_STATE`, `HAS_CONTEXT`, `STARTS_AT`) plus the
typed relation/emotion predicates from the semantic reconciliation vocabulary.

- Each active edge carries `fact_id`, `event_type`, `predicate`,
  `subject_ref`, `object_ref`, `authority` (`machine` | `USER_OVERRIDE`),
  `confidence`, `state` (`UNKNOWN|AMBIGUOUS|CONFLICTING|PROBABLE|CONFIRMED|
  USER_CONFIRMED`), `scope`, `support_refs`/`contradiction_refs` (JSONB), and
  `ledger_seq`.
- Overrides / corrections / invalidations **supersede** (flip `active=false` +
  record `superseded_by_seq`) the targeted active edge(s) and activate the
  `USER_OVERRIDE` edge; history is retained, never deleted. `USER_OVERRIDE`
  beats machine inference; while an entity is locked, machine assertions never
  activate or supersede edges.
- **Replay multi-edge reads** — `RELATIONSHIP_EDGES` structured queries and
  relationship semantic questions read this active edge store (bounded,
  paginated, `edge_guard`-gated). Superseded edges are never returned as active.
- **Search reconciliation** — `SearchProjectionBuilder` deterministically
  reconciles the `edge:%` (non-utterance) and `assert:%` (utterance predicates
  `SPEAKS|SAYS|UTTERANCE|PRONUNCIATION`) search-doc families against this active
  edge store on every `finalize`, so a corrected / overridden / invalidated
  utterance or edge is superseded on the search surface and the corrected value
  is indexed; the immutable assertion stream is no longer a search-doc source
  for utterances.

See [query-search.md](query-search.md) for the read surface and freshness
gating, and [consistency.md](consistency.md) for the per-projection guards.

## Provenance and audit

`AuditService.explain(subject, as_of, causation, correlation)` answers
why/current, prior state, actor, evidence, generated-by, and change cause. The
audit service is query-only; it serves provenance and never writes. per-source
decomposition reports are built read-only from the operational tables (`job`,
`stage_run`, `job_run_audit`, `evidence`, `segment`, `quarantine`, `source`) —
never Tier-0.

## Multilingual / adaptation / continuity handling

- Sources, editions, adaptations, translations, continuities, and subtitle
  tracks are **distinct typed realizations**, never flattened.
- `SourceAliased` groups byte-different reuploads/releases/transcodes into work
  membership without deduplicating them.
- Alignment is stored as typed confidence-bearing **many-to-many `Aligned`
  assertions**; evidence is never merged.
- Similar-looking realizations across continuities remain distinct and may
  `CONTRADICT` or be labeled `ALTERNATE_REALIZATION`.
- Every alignment exposes its method, input refs, confidence, assumptions,
  omissions/additions/reordering/contradiction metadata, and continuity scope.
  One-to-many, many-to-one, many-to-many, omitted, and adaptation-only events
  are first-class.
- Vecalign is **parallel-text-only** in v1 (see [limitations.md](limitations.md)
  and [providers.md](providers.md)); adaptations use temporal/embedding/LLM
  methods labeled `ADAPTATION`/`TEMPORAL` with explicit assumptions.

## Temporal / spatial semantics

- Source-local media time, timecodes, narrative sequence, story chronology,
  valid-time intervals, flashbacks, simultaneous events, unknown order, and
  cross-source temporal correspondence are represented **separately**.
- Locations, sublocations, participants, objects, visual/audio environment,
  weather, lighting, and relative positioning are provenance-bearing assertions,
  not only free text.
- Structured queries accept `continuity_id`, `temporal_from`/`temporal_to`, and
  `spatial` scope filters; an unmappable scope produces an explicit RFC 7807
  `422 unmappable_scope`, never silently unfiltered results
  (see [query-search.md](query-search.md)).