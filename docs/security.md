# Security

The security model treats untrusted media as an attack surface. Every parser,
archive, and model runs with bounded, non-privileged execution and defense in
depth across independent boundaries.

## Sandbox posture

- A dedicated **sandbox-runner** role runs extraction with an explicitly
  non-privileged, documented-validated host profile
  (`deploy/security/SANDBOX_HOST_PROFILE.md`): `read_only` root
  filesystem, `no-new-privileges`, seccomp profile
  (`deploy/security/sandbox-seccomp.json`), `cap_drop: [ALL]`, tmpfs scratch,
  and **never** `privileged`. `UMD_SANDBOX_PROFILE=documented-validated-nonprivileged`.
- Host-level sandboxing (bubblewrap/AppArmor/user-namespace/capability matrix)
  is tracked in the surviving-risk register (U4) with a required spike,
  especially for the Ubuntu 24.04 manual AppArmor profile.
- OCFL remote/FUSE access is staged through a **local read-only spool** with
  validated crash cleanup (U7); a vanished content file fails loudly rather than
  returning corrupted data.
- Archive/path escape is a release-blocking failure mode:
  `ArchiveDenial` raises on any member that escapes, is a symlink, is
  ambiguous, or exceeds limits; no member is extracted until the whole archive
  validates (see `umd/security/archive.py`).

## Untrusted-input hardening

- **Bounded resource limits**: upload (`limits.max_upload_bytes`),
  range (`max_range_bytes`), read buffer (`max_read_buffer_bytes`) —
  enforced by the OCFL adapter at the storage boundary.
- **Bounded decode**: raster decoding arms the Pillow decompression-bomb guard
  and validates header dimensions against a budget **before** full decode.
- **Deterministic storage keys**: OCFL objects are content-addressed (sha512);
  user filenames are never storage keys.
- **Parser policy**: untrusted parsers run in the sandbox; a standing
  CVE/license watch (`deploy/security/CVE_WATCH.md`,
  `deploy/security/LICENSE_REVIEW.md`) tracks FFmpeg/PyAV, pgvector, and parser
  CVEs. pgvector CVE-2026-3172 requires >=0.8.2 (the HNSW gate), with an
  immutable embedding table and concurrent reindex.

## API security

- **Auth** — bearer or `X-API-Key`; read vs write key split
  (`UMD_AUTH__WRITE_KEYS`); mutating routes require a write-capable key.
- **Rate limiting** — real per-key / per-IP token bucket (`429` +
  `Retry-After`).
- **Errors** — RFC 7807 structured bodies; no stack or internal detail leakage.
- **CORS** — same-origin by default (`cors_allow_origins` empty).

## Model / provider gates

- **faster-whisper ASR** — GATED; needs a pinned offline weights dir; filter
  signals are best-effort, hallucination handling retains raw evidence and bans
  automatic semantic promotion.
- **pyannote diarization** — GATED and **legally** gated (weights/license U1);
  requires `UMD_DIARIZATION_LEGAL_GATE` and a pinned offline weights dir.
- **vLLM** — GATED via `UMD_VLLM_ENABLED`.
- **pgvector-HNSW** — GATED below the `0.8.2` build gate; the exact-fallback
  backend is the honest in-process fallback.
- **Hatchet** — exact release pin (v0.50.0) is a build gate; a mechanical
  Temporal fallback is retained for deterministic multi-entity sagas or
  signal-heavy human waits.
- License terms for gated/AGPL dependencies (ebooklib/PyMuPDF/other) are
  explicit **build/release gates**, never silently accepted.

## Auditability

Every accepted semantic mutation has an audit explanation: actor, causation,
prior/current state, generated-by metadata. `GET /v1/audit/{subject}` exposes
it read-only; the ledger is append-only (UPDATE/DELETE denied by trigger).
Sensitive configuration (secrets, model weights paths) is never embedded in
source or documentation.