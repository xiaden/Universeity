# UMD license review register (Plan E, P2-S2)

Documents the license posture of the DD's GATED provider/security extensions and
of the base distribution. Purpose: no dependency enters the base image or an
opt-in extra without a recorded license review, and Alpine/AGPL/copyleft surface
is disclosed rather than defaulted-on.

## Base distribution
- Project license: **Apache-2.0** (pyproject.toml). Base image is
  `python:3.13-slim` (Apache-2.0 adjacent Debian base; no AGPL surface added by
  the base image itself).

## Direct runtime dependencies (all permissive, reviewed for the base image)
| Package | License | Status |
|---------|---------|--------|
| fastapi / starlette | BSD-3 / BSD-3 | ✅ permissive |
| pydantic / pydantic-core | MIT | ✅ |
| pydantic-settings | MIT | ✅ |
| sqlalchemy | MIT | ✅ |
| ocfl-py | Apache-2.0 | ✅ |
| alembic | MIT | ✅ |
| psycopg[binary] | LGPL-3.0 + PostgreSQL | ⚠️ LGPL dynamic-link — **runtime import, not redistribution**; recorded, acceptable |
| jsonschema | MIT | ✅ |
| pypdf | BSD-3 | ✅ |
| pillow | HPND (permissive) | ✅ |
| pysubs2 | MIT | ✅ |
| uvicorn | BSD-3 | ✅ |
| Mako | MIT | ✅ |

### ⚠️ AGPL / strong-copyleft audit
No AGPL or GPL dependency is loaded by the **base image**. The only strong-ish
surface is `psycopg[binary]` (LGPL-3.0), which is consumed as a linked runtime
library against our Apache-2.0 service and is not cryptographic/derivative
work. Flagged here so a future bump cannot silently swap it for AGPL-licensed
alternative without this review being revisited.

## GATED provider/security extensions (opt-in only, release-gated)
These are **never** part of the base image and are only installed through a
documented opt-in extra. Each carries its own license + a build-time
interrogation where asked.

| Extension | License | Gate / review | Status |
|-----------|---------|---------------|--------|
| faster-whisper | MIT | permissive; model weights separate | ✅ |
| pyannote.audio | MIT | **U1 legal gate**: model-license + A/V biometric review documented before any promotion | ⚠️ GATED |
| PySceneDetect | BSD-3 + LGPL-3 (OpenCV) | dynamic; part of video gated extra | ⚠️ GATED |
| vLLM | Apache-2.0 | **license interrogator** for served model weights (never fetched at build) | ⚠️ GATED |
| splink / duckdb | MIT / MIT | permissive | ✅ |
| vecalign | MIT | permissive | ✅ |
| Hatchet SDK + server | Apache-2.0 | server release exact-pinned (build gate) | ⚠️ GATED |
| pgvector extension | PostgreSQL license | third-party Postgres extension; part of 18.6/0.8.6 deployment | ✅ |

### Gated-model license review
The decomposition pipeline can route to **hosted models** (ASR, VLM, diarization)
that each ship their own weights/terms. Policy: weights are loaded at runtime
under the operator's license responsibility; the service records a capability
that lists the active provider/engine. A never-verified model capability is not
advertised as active — the `/v1/capabilities` endpoint reports only what the
running configuration actually gates in.

## Sign-off requirement
Every dependency addition or pin change updates this register (at minimum the
affected rows) in the same change. A `GATED` row left silently promoted to a base
dependency is a **release blocker**.