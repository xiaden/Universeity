# Fixture Generation

Test fixtures are generated **deterministically at runtime**; nothing commits a
binary blob into the repository. The generator contract (`FuzzSeedFunction`, a
pure `seed -> bytes`) reproduces identical bytes for the same seed across
runs, so tests and golden assertions are stable without checked-in artifacts.

## Deterministic factories in `tests/fixtures.py`

- **Hand-assembled PDFs** — direct PDF objects with a correct, header-relative
  `xref` table and correct `startxref`, distinguishing **text-layer** PDFs from
  image-only PDFs (which route to raster/OCR).
- **EPUBs** — valid container structures and deliberately malformed variants
  (missing `mimetype`/`container`) for negative tests.
- **Raster fixtures** — synthesized images to PIL, bounded by explicit
  pixel/dimension budgets, for decompression-bomb and crop/panel tests.
- **Subtitle/WebVTT** — pysubs2-parseable streams with mandatory
  `X-TIMESTAMP-MAP` normalization cases.
- **Seed-driven fuzz bodies** for text parse, archive, and locator edge cases.

The generators are used across unit, storage, API-contract, and
pipeline/planner tests so the same bytes exercise parsing, storage, evidence,
and semantic steps consistently.

## Why generated, not committed

- No binary blobs in git (audit hygiene, no licensing ambiguity, smaller repo).
- Deterministic across environments — a failing fixture reproduces identically.
- Replay/payload tests rerun the same event payloads through projections and
  assert checksum-equivalence.

## Golden / replay fixtures

Retained historical event payloads (under the event-schema directories) are
replayed via upcasters in CI so a schema migration never silently breaks a
projection of historical state.