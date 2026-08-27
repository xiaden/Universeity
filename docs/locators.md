# Locators, Source-Native Retrieval, and Reversible Resolution

## Locator grammar and lifecycle

Canonical form:

```text
source://<work-or-source-id>/<modality>/<deterministic-segment-id>@v<segmenter>.<decoder>.<renderer>?frag=<selector>
```

- Segment IDs are deterministic from canonical source/work content identity,
  modality, and structural path, using a collision-resistant hash and URL-safe
  encoding. Structural paths are stable where content and parser versions are
  stable.
- Text uses EPUB CFI or structural selectors plus text-location assertions;
  image/page regions use IIIF `xywh`/`pct`; audio/video/subtitles use
  Media Fragments-compatible `t=start,end`, `track`, and optional spatial
  selectors. **Byte offsets alone are forbidden** as locators.
- The OCFL object-id form used for source-native retrieval is
  `urn:umd:ocfl:source:sha512:<sha512>` — the content-addressed object identity.

### Segmentation and locator registration

`SegmentRegistry.register(batch)` produces deterministic stable segment IDs and
versioned locators. Byte offsets are never used as evidence locators.

### Version resolution

`LocatorResolver.resolve(locator, version_policy)` (CONTRACTS) resolves bare and
explicit `@vN` locators. V1 REST exposes:

- `GET /v1/locators/{source_ref}` resolves an object and returns a bounded
  native representation (`start`/`end`, `truncated`, `data_b64`) plus full-object
  fixity metadata (`sha512`, `size_bytes`).

A bare locator resolves the newest compatible locator version for the
work/source; a historical `@vN` remains addressable. `GET /v1/locators` resolves
explicit `@vN` versions exactly.

## Locator drift — the honest boundary

Content, EPUB structure, and decoder/renderer behavior changes may invalidate
locators. Drift is **versioned, detectable, rebasable, and quarantineable** —
it is **never silently repaired**:

- A decoder/renderer/segmenter change creates a new locator version and a
  selective invalidation.
- `SourceAliased` groups byte-different reuploads into work membership without
  deduplicating them.
- `LocatorRebased` records old/new locators and affected references.
- If a structural path cannot resolve, it is quarantined with
  `PATH_UNRESOLVED` and surfaced — never dropped or silently edited.

The design makes locator drift visible and rerunnable; **it cannot make changed
content address-equivalent.** This is a permanent operational tax, not a bug to
be silently removed.

## Source-native retrieval

`SourceStore.get_range(source_ref, start, length, *, version)` returns a
**bounded slice** (capped to `max_read_buffer_bytes` / `max_range_bytes`) plus
full-object fixity. Retrieval returns bounded source-native text, image
crop/panel, frame/clip metadata, audio clip, or subtitle event, with normalized
representation, neighboring context, evidence, claims, and provenance where the
call site provides them.

- `GET /v1/locators/{source_ref}?start=0&length=N` — bounded native bytes.
- `GET /v1/segments/{segment_id}/evidence` — segment-scoped evidence records
  (resolves the segment to its authoritative source/locator, 404 on unknown, and
  never returns another segment's/source's evidence).

## Storage ownership

- **Raw source bytes and fixity**: OCFL object storage is the sole authority.
  `put_immutable` writes content-addressed bytes, verifies sha512 fixity, and
  never uses a user filename as a key.
- **Derived evidence bytes**: OCFL derived objects plus Postgres references.
  The graph never holds the only copy.
- **OCFL local-spool/FUSE**: remote or FUSE access is not assumed to work in a
  user namespace; the sandbox stages a local read-only spool from OCFL at task
  start. A vanished content file FAILS loudly (a `StoreError`/`OSError`), never
  returning corrupted data. Backup/restore re-validates fixity per object.

## Reversible entity resolution

Every source mention, name/script/transliteration/title/nickname/OCR form,
speaker label, face cluster, and unknown placeholder is persisted. Candidate
generation uses normalized names, transliteration, soundex, high-cardinality
speaker/face clusters, and MinHash/LSH. splink provides interpretable linkage
scoring (GATED, see [providers.md](providers.md)); linkage runs in bounded
batches and in the sandbox.

- A merge is a log record, not a delete.
- Aliases remain assertions.
- Unknown entities retain candidate sets and may resolve later.
- Split enumerates all references at split-time, carries assignments, emits
  `ReferenceRebound`, and quarantines ambiguous targets.
- The REST boundary routes `POST /v1/entities/{ref}/merge` and
  `.../{ref}/split` through the **same** resolution authority as the service
  layer (ledger append + mention rebind + quarantine) — never a second semantic
  authority.