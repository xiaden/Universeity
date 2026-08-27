# UMD CVE / vulnerability watch register (Plan E, P2-S2)

This register tracks the vulnerability streams the DD's risk register and
release gates require. It is a **living document**: each entry records the
watch status, the remediation floor, and the gate that fails a release if the
floor is not met. Nothing here is "resolved-and-forgotten"; every pin bump must
re-check the corresponding entry.

## Postgres / pgvector
| ID | Component | Watch | Remediation floor | Gate |
|----|-----------|-------|-------------------|------|
| CVE-2026-3172 | pgvector | ACTIVE | pgvector **>= 0.8.2**; container target **0.8.6** (Postgres **18.6**) | HNSW vector index is GATED and **not promoted to active** on any environment whose pgvector < 0.8.2. Local CI runs Postgres 17 + pgvector **0.8.0**, so HNSW stays gated there; only the 18.6/0.8.6 Compose target enables it. | 

## Media / multimedia libraries
| ID | Component | Watch | Remediation floor | Gate |
|----|-----------|-------|-------------------|------|
| ongoing | FFmpeg | ACTIVE (medium–high stream) | Track upstream releases; pin the FFmpeg build used by the video decode layer | A release that carries an **unpatched known-critical FFmpeg** CVE blocks (release gate). |
| ongoing | PyAV / av | ACTIVE | Pin media decode against current PyAV; re-review on bump | Same as FFmpeg; PyAV is gated behind `UMD_VIDEO_DECODE_PYAV`. |
| ongoing | pypdf / Pillow | WATCH (recurrent parser CVEs) | Stay on the pinned versions above; bump immediately on disclosed fix | Parser CVEs are reconciled in the dependency upgrade checklist. |

## Runtime / general
| ID | Component | Watch | Remediation floor | Gate |
|----|-----------|-------|-------------------|------|
| — | python:3.13 base image | ACTIVE | Track python:3.13-slim security updates; rebuild on release | Container rebuild on Python security release. |
| — | postgres 18.6 | WATCH | Stay within a PostgreSQL-supported minor | Compose targets 18.6 (supported). |
| — | tarfile / stdlib | RECONCILED | 3.13.x applies the "data filter" defaults | Covered by base image refresh. |

## Application / provider subsystems
| ID | Component | Watch | Remediation floor | Gate |
|----|-----------|-------|-------------------|------|
| U1-legal | pyannote.audio diarization | ACTIVE (legal + model-license) | GATED behind `UMD_DIARIZATION_ENABLED` + checked-in legal acknowledgment | Never promoted active; see LICENSE_REVIEW.md U1. |
| — | Hatchet durable runner | ACTIVE | Pin an **exact release** at deploy time (no floating tag) | Hatchet release pin is a build gate; the Compose `HATCHET_VERSION` default is exact (v0.50.0). |
| — | vLLM served weights | ACTIVE | License interrogator for any hosted model weights | GATED; never fetched at build. |

## SBOM / provenance
- The container image records an SBOM (installed packages + version) at build time;
  the `deploy/pins/runtime.txt` manifest is regenerated from that SBOM for the
  shipped tag. A release without a matching SBOM & pin manifest is **blocked**.

## Process
1. On any dependency bump or scheduled review, check every ACTIVE/WATCH row.
2. A row whose remediation floor is violated **blocks** the release (release gate).
3. Update this file in the same change that bumps the dependency — no drive-by pins.