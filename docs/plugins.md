# Plugin Authoring

Plugins extend the decomposition pipeline behind **versioned stage contracts**.
A plugin is never a projection writer, never a semantic authority, and never a
second source of truth — it produces evidence/artifacts that enter the ledger
through the command/event path.

## The stage contract

Every stage plugin must satisfy:

- **Deterministic idempotency key** derived from source/segment, stage,
  input-evidence refs, stage schema version, extractor/decoder/provider
  versions, and configuration digest. Duplicate submissions succeed once
  (effectively-once, from the database key / transaction boundary).
- **Evidence-scoped output** — a stage writes evidence rows tied to a concrete
  `source_id` + exact locator + the recorded `generated_by` metadata; it never
  invents relationships not supported by evidence.
- **Configuration digest** — the exact configuration that produced an output is
  hashed into the idempotency key and stored on `stage_run`.
- **Read-only inputs** — reads the immutable/derived registers it depends on,
  never mutating provenance or ledger state.
- **Sandboxed execution** — untrusted content is processed by the
  sandbox-runner with bounded resources (see [security.md](security.md)).

## The `ModelProvider` contract

Provider plugins implement `completion` and/or `embedding` through
`ModelProvider`. Every call is recorded (versions, config digest, tokens,
error, latency) and feeds `generated_by`. A provider is substitutable via
versioned configuration; the semantic schema and query language do not change
when a provider is swapped.

## Extractor / modality contracts

Modality pipelines (text/image/audio/video/subtitle) expose extractor gaps
(`PdfTextExtractor`, `OcrProvider`, subtitle-format parsers, etc.). Registering
a new parser/extractor updates the capability report so consumers can discover
what the current deployment can actually parse.

## Authoring workflow

1. Implement the stage/extractor/provider against its contract.
2. Provide a deterministic fixture per format (see [fixtures.md](fixtures.md)).
3. Add a payload/replay test: the stage's event payload must validate against
   the retained JSON schema and replay checksum-equivalently.
4. Wire the stage into the in-repository DAG (`stage_dependency` table) so
   invalidation plans descendants correctly.
5. Update `/v1/capabilities` reporting and, if a model is involved, mark it
   **GATED** until legal/CVE sign-off (see [providers.md](providers.md),
   [security.md](security.md)).

## Ownership invariants for plugin authors

- No direct projection writes — runs read projections, never write them.
- No in-place semantic mutation — append events via the command path.
- No flattening of track/edition/subtitle structure.
- No automatic semantic promotion of best-effort machine signals.