# Extension Paths (Deferred, Trigger-Based)

These are **documented, not implemented** pathways. Each carries a **measured
trigger** (a concrete, observable threshold) and an **ownership invariant**
that must hold so no extension weakens the authority/security/provider posture.
Nothing here is active in v1; capability reporting stays truthful.

## Bounded-query promotion to a replay-only Neo4j/GQL projection

- **Problem it solves:** unbounded/first-class graph traversal and graph
  algorithms that the bounded typed-PostgreSQL v1 surface cannot serve.
- **Measured trigger:** recorded demand for `kind=TRAVERSAL` queries that
  exceed `max_depth` for a sustained period AND a concrete graph algorithm
  (e.g. community/burden detection, arbitrary-depth path) that the typed
  PostgreSQL planner cannot answer within the query-cost budget — evidenced by
  query-cost exceeded counters and operator demand, not speculation.
- **Ownership invariants:**
  - The projection is a **replay-only** Neo4j **Community Edition** (or
    GQL-compatible disposable) projection fed exclusively by the append-only
    ledger. It is never a second authority; it is rebuilt like any Tier-1
    projection and never accepts direct writes.
  - Replay remains the authority repair path; dual-write/mutation paths are
    barred at the boundary.
  - CE-specific limits (no authority-grade HA/backup/RBAC) are recognized: an
    authority-graded RDF/Neo4j authority was rejected for v1, so the projection
    must stay disposable.

## Funded RDF-star projection / interoperability

- **Problem it solves:** official RDF/RDF-star interoperability and
  cross-system interchange.
- **Measured trigger:** an external consumer/interoperability commitment that
  **funds** the projection (scarce-effort; not speculative). RDF-star vs RDF 1.2
  semantic uncertainty and second-authority/outbox lag must be resolved first.
- **Ownership invariants:**
  - RDF star/triple output is a **read projection** from the ledger, never a
    second write authority; no graph-db authority is introduced for v1.
  - Outbox lag between ledger and RDF projection is bounded and surfaced, never
    hidden.
  - Licensing for a production RDF/GraphDB authority remains a build/release
    gate.

## Gated XTDB witness

- **Problem it solves:** a tamper-evident, independently-readable witness of the
  semantic record.
- **Measured trigger:** XTDB reaches GA (no RC-only external-source path),
  compaction/read-path reliability is demonstrated, and recursive-query support
  is confirmed — the surviving-risk register lists all three as current blockers.
- **Ownership invariants:**
  - XTDB is a **witness**, not the authority or a service path; the PostgreSQL
    ledger remains the sole authority.
  - Its read path/compaction behavior is validated (the current evidence records
    a compaction/readability issue), and it never becomes a write dependency of
    the API.

## Dedicated vector promotion

- **Problem it solves:** scale/recall beyond the in-process exact-fallback and
  the local pgvector HNSW path.
- **Measured trigger:** vector count, recall, HNSW build memory, and write
  churn are monitored; the dedication triggers at the evaluated thresholds
  (review at 5M / 10M / 50M vectors, migrating through `VectorIndex` without
  narrowing recall expectations).
- **Ownership invariants:**
  - Authority never changes: vectors remain a projection, promoted through the
    `VectorIndex` boundary, gated by the `vector_hnsw_min_version` build floor.
  - The subtree stays a rebuildable read model with immutable embedding
    (NO-COW append-once) storage; CVE-2026-3172 requires >=0.8.2.

## Forced audio alignment

- **Problem it solves:** high-precision start/end alignment for longer,
  lower-confidence speech where word-level forced alignment improves
  transcription confidence and locator quality.
- **Measured trigger:** implemented as a deterministic post-processing step
  (forced aligner over the recognized text) when transcription spans/quality
  meet a defined confidence-and-length threshold; it is **deferred** out of the
  Phase B/C base.
- **Ownership invariants:**
  - Alignment output is evidence-scoped and never auto-promoted to semantics;
    locator drift is versioned/quarantined, not silently repaired.
  - The aligner runs in the sandbox; its version/config digest feeds the stage
    idempotency key.

## Higher-fidelity VLM / diarization

- **Problem it solves:** richer visual-language evidence and speaker-turn
  separation.
- **Measured trigger:** a **legally-unambiguous** (U1) model/weights provision
  and a pinned offline weights dir; VLM gated via `UMD_VLLM_ENABLED`,
  diarization gated via `UMD_DIARIZATION_ENABLED` + `UMD_DIARIZATION_LEGAL_GATE`.
- **Ownership invariants:**
  - Both remain GATED until legal sign-off; hallucination/best-effort signals
    stay filtered, retrained, and **never** automatically promoted to semantics.
  - Filter thresholds carry their own version/input dependency and invalidate
    ASR descendants when changed.

## Additional containers

- **Problem it solves:** separating heavy model/gpu or remote-bridge workloads
  (e.g. Ollama, MinIO S3 bridge, extra runners) from the API/worker image.
- **Measured trigger:** a concrete resource-isolation or GPU-compute demand that
  the single-image api/worker pair cannot meet; introduced as profile-gated
  compose services.
- **Ownership invariants:**
  - New containers reuse the pinned, non-privileged image posture; sandbox
    semantics (read-only root, no-new-privileges, cap_drop, seccomp) are
    preserved; `privileged` remains never used.
  - Credentials never embed in images; runtime injection only.

## Temporal migration

- **Problem it solves:** replacing Hatchet when durable workflows require
  deterministic multi-entity sagas or signal-heavy human waits that Hatchet's
  exact-pin (v0.50.0) release cannot yet guarantee.
- **Measured trigger:** a concrete workflow requirement (multi-entity saga or
  signal-heavy human approval) that the pinned Hatchet release fails in
  testing; the mechanical Temporal fallback is exercised, not assumed.
- **Ownership invariants:**
  - The in-repository lineage definition stays the **single lineage source**;
    swapping the runner never forks lineage truth.
  - No stage idempotency/effective-once/audit guarantees change in the move;
    `stage_run`/`job_run_audit` remain the operational record.
  - Exact release pins remain build gates on either runner.