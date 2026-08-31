"""Plan L P3-S2 / P3-S3: production format dispatch acceptance.

P3-S2: execute the REAL ``FORMAT_ANALYSIS`` and ``BASIC_SEGMENTATION`` production
StageWork for TXT, Markdown, EPUB, a text PDF and binary (image) media, asserting
the expected parser/segmenter pair and the ABSENCE of normalized raw binary bytes.

P3-S3: a multi-chapter EPUB acceptance case proving chapters + paragraphs are
segmented, evidence rows link to exact segment IDs with source provenance,
segment IDs are deterministic, and a SECOND StageWork run produces IDENTICAL
outputs (evidence deduped via ``uq_evidence_identity``; segments reused via
``uq_segment_deterministic``).

These tests are ADDITIVE to ``test_production_stage_registry.py`` /
``test_production_runner.py`` and never weaken their assertions.
"""

from __future__ import annotations

import importlib
import io
import json
import struct
import uuid
import zlib
from typing import Any

import pytest
import sqlalchemy as sa

from fixtures import (
    malformed_epub_bytes,
    markdown_bytes,
    multi_chapter_epub_bytes,
    pdf_image_only_bytes,
    pdf_text_bytes,
    raster_comic_bytes,
    txt_bytes,
)
from umd.domain.locators import StructuralSelector
from umd.extractors.dispatch import dispatch_text
from umd.extractors.epub import EpubParseError, extract_epub
from umd.security.sandbox import SandboxLimits
from umd.segmentation.registry import SegmentInput, SegmentRegistry
from umd.segmentation.segmenters import TEXT_PIPELINE_VERSION
from umd.storage.ocfl import SourceDescriptor, SourceStore
from umd.storage.postgres.repositories import PostgresSegmentStore

pytestmark = pytest.mark.postgres

#: Format cases -> expected (parser, segmenter) pair for the PRODUCTION path.
TEXT_CASES: list[dict[str, Any]] = [
    {
        "id": "a0000000-0000-4000-8000-000000000001",
        "raw": txt_bytes(),
        "format": "txt",
        "media_kind": "text",
        "name": "book.txt",
        "parser": "txt",
        "types": {"document", "chapter", "section", "paragraph", "sentence", "token"},
    },
    {
        "id": "a0000000-0000-4000-8000-000000000002",
        "raw": markdown_bytes(),
        "format": "markdown",
        "media_kind": "text",
        "name": "book.md",
        "parser": "markdown",
        "types": {"document", "chapter", "section", "paragraph"},
    },
    {
        "id": "a0000000-0000-4000-8000-000000000003",
        "raw": multi_chapter_epub_bytes(),
        "format": "epub",
        "media_kind": "text",
        "name": "book.epub",
        "parser": "epub",
        "types": {"document", "chapter", "paragraph"},
    },
    {
        "id": "a0000000-0000-4000-8000-000000000004",
        "raw": pdf_text_bytes(),
        "format": "pdf",
        "media_kind": "text",
        "name": "book.pdf",
        "parser": "pdf",
        "types": {"document", "chapter", "paragraph"},
    },
]


def _production() -> Any:
    return importlib.import_module("umd.jobs.production")


def _runtime(umd_db: sa.Engine, tmp_path: Any) -> tuple[dict[str, Any], SourceStore]:
    store = SourceStore.create(
        tmp_path / "ocfl",
        max_upload_bytes=16 * 1024 * 1024,
        max_range_bytes=16 * 1024 * 1024,
    )
    return {"engine": umd_db, "source_store": store}, store


def _seed_source(
    umd_db: sa.Engine,
    store: SourceStore,
    raw: bytes,
    *,
    source_id: str,
    media_kind: str,
    name: str,
    format: str | None,
) -> Any:
    from umd.storage.postgres.tables import metadata as _meta

    man = store.put_immutable(io.BytesIO(raw), SourceDescriptor(logical_name=name))
    src_t = _meta.tables["source"]
    with umd_db.begin() as conn:
        conn.execute(
            src_t.insert().values(
                id=uuid.UUID(source_id),
                ocfl_ref=man.object_id,
                sha512=man.sha512,
                size_bytes=man.size_bytes,
                media_kind=media_kind,
                format=format,
                original_name=name,
                work_id=None,
                descriptor={},
            )
        )
    return man


def _manifest(mod: Any, stage: str, source_id: str, job_id: str) -> Any:
    return mod.StageManifest(
        job_id=job_id,
        stage_name=stage,
        source_id=source_id,
        dag_universe=None,
        evidence_refs=[],
        input_manifest={"source_id": source_id},
    )


def _segment_rows(umd_db: sa.Engine, source_id: str) -> list[dict[str, Any]]:
    from umd.storage.postgres.tables import metadata as _meta

    seg_t = _meta.tables["segment"]
    with umd_db.connect() as conn:
        rows = conn.execute(sa.select(seg_t).where(seg_t.c.source_id == source_id)).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        key = str(r.deterministic_key)
        parts = key.split("#", 2)
        out.append(
            {
                "id": str(r.id),
                "deterministic_key": key,
                "structural_path": parts[2] if len(parts) == 3 else "",
                "segment_type": str(r.segment_type),
                "locator": str(r.locator) if r.locator is not None else "",
            }
        )
    return out


def _evidence_rows(umd_db: sa.Engine, source_id: str) -> list[dict[str, Any]]:
    from umd.storage.postgres.tables import metadata as _meta

    ev_t = _meta.tables["evidence"]
    with umd_db.connect() as conn:
        rows = conn.execute(sa.select(ev_t).where(ev_t.c.source_id == source_id)).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        out.append(
            {
                "locator": str(r.locator) if r.locator is not None else "",
                "segment_id": str(r.segment_id) if r.segment_id is not None else None,
                "evidence_kind": str(r.evidence_kind),
                "config_digest": r.config_digest,
                "raw_ref": r.raw_ref,
                "quality": json.loads(json.dumps(r.quality or {}, sort_keys=True)),
                "tool_versions": json.loads(json.dumps(r.tool_versions or {}, sort_keys=True)),
            }
        )
    return out


def _evidence_signature(rows: list[dict[str, Any]]) -> list[tuple[str, Any, Any, str, str]]:
    return sorted(
        (r["locator"], r["segment_id"], r["config_digest"], r["raw_ref"], r["quality"])
        for r in rows
    )


# ---------------------------------------------------------------------------
# P3-S2: production FORMAT_ANALYSIS + BASIC_SEGMENTATION select the right pair
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", TEXT_CASES, ids=[c["parser"] for c in TEXT_CASES])
def test_production_format_analysis_selects_expected_parser(
    umd_db: sa.Engine, tmp_path: Any, case: dict[str, Any]
) -> None:
    mod = _production()
    runtime, store = _runtime(umd_db, tmp_path)
    man = _seed_source(
        umd_db,
        store,
        case["raw"],
        source_id=case["id"],
        media_kind=case["media_kind"],
        name=case["name"],
        format=case["format"],
    )
    registry = mod.StageWorkRegistryFactory.build(runtime)
    outcome = registry["FORMAT_ANALYSIS"](_manifest(mod, "FORMAT_ANALYSIS", case["id"], "fa-job"))

    # The dispatcher selected the expected format-aware parser.
    assert outcome.metrics["parser"] == case["parser"], outcome.metrics
    # The durable format_analysis evidence records the exact parser/route + fixity.
    ev = [e for e in _evidence_rows(umd_db, case["id"]) if e["evidence_kind"] == "metadata"]
    assert ev, "FORMAT_ANALYSIS must record a format_analysis evidence row"
    row = ev[0]
    assert row["quality"]["parser"] == case["parser"]
    assert row["quality"]["route"] == "text"
    assert row["quality"]["source_sha512"] == man.sha512, "source fixity not recorded"
    assert row["raw_ref"] == man.object_id, "raw OCFL reference not preserved"
    assert row["config_digest"], "non-null config digest required for evidence dedup"


@pytest.mark.parametrize("case", TEXT_CASES, ids=[c["parser"] for c in TEXT_CASES])
def test_production_basic_segmentation_uses_expected_segmenter(
    umd_db: sa.Engine, tmp_path: Any, case: dict[str, Any]
) -> None:
    mod = _production()
    runtime, store = _runtime(umd_db, tmp_path)
    _seed_source(
        umd_db,
        store,
        case["raw"],
        source_id=case["id"],
        media_kind=case["media_kind"],
        name=case["name"],
        format=case["format"],
    )
    registry = mod.StageWorkRegistryFactory.build(runtime)
    registry["FORMAT_ANALYSIS"](_manifest(mod, "FORMAT_ANALYSIS", case["id"], "fa-job"))
    seg_out = registry["BASIC_SEGMENTATION"](
        _manifest(mod, "BASIC_SEGMENTATION", case["id"], "bs-job")
    )

    assert seg_out.metrics["segment_count"] > 0, seg_out.metrics
    segs = _segment_rows(umd_db, case["id"])
    types = {s["segment_type"] for s in segs}
    # The format-appropriate segmenter produced its characteristic hierarchy.
    assert case["types"] <= types, f"expected segment types {case['types']}, got {types}"
    # All registered segments carry a canonical locator (never a bare structural path).
    assert all(s["locator"].startswith("source://") for s in segs)


def test_binary_media_never_decoded_as_plain_text(umd_db: sa.Engine, tmp_path: Any) -> None:
    """A binary (image) source is never plain-text segmented: FORMAT_ANALYSIS
    takes the media route, BASIC_SEGMENTATION registers ZERO text segments, and
    no text_span evidence is fabricated from the raw binary bytes."""
    mod = _production()
    runtime, store = _runtime(umd_db, tmp_path)
    sid = "a0000000-0000-4000-8000-0000000000aa"
    _seed_source(
        umd_db,
        store,
        raster_comic_bytes(),
        source_id=sid,
        media_kind="image",
        name="page.png",
        format="image/png",
    )
    registry = mod.StageWorkRegistryFactory.build(runtime)

    fa = registry["FORMAT_ANALYSIS"](_manifest(mod, "FORMAT_ANALYSIS", sid, "bin-fa"))
    # The media branch reports the modality, never a text parser.
    assert fa.metrics["parser"] == "image", fa.metrics

    bs = registry["BASIC_SEGMENTATION"](_manifest(mod, "BASIC_SEGMENTATION", sid, "bin-bs"))
    assert bs.metrics["segment_count"] == 0, bs.metrics

    segs = _segment_rows(umd_db, sid)
    assert segs == [], "binary source must not register text segments"
    kinds = {e["evidence_kind"] for e in _evidence_rows(umd_db, sid)}
    assert "text_span" not in kinds, "no text_span evidence may be fabricated from binary bytes"
    # The only recorded evidence is the media-route format_analysis metadata row.
    assert kinds == {"metadata"}, kinds


# ---------------------------------------------------------------------------
# P3-S3: multi-chapter EPUB acceptance + deterministic rerun
# ---------------------------------------------------------------------------


def test_multi_chapter_epub_acceptance_and_deterministic_rerun(
    umd_db: sa.Engine, tmp_path: Any
) -> None:
    """Two-chapter EPUB acceptance through the production registry:
    * both chapters and their paragraph segments are registered;
    * paragraph evidence rows link to the EXACT registered segment id (FK) and
      carry source provenance (raw OCFL ref + content sha512 + config digest);
    * a SECOND StageWork run produces IDENTICAL outputs (evidence deduped by
      uq_evidence_identity; segments reused by uq_segment_deterministic)."""
    mod = _production()
    runtime, store = _runtime(umd_db, tmp_path)
    sid = "a0000000-0000-4000-8000-0000000000bb"
    man = _seed_source(
        umd_db,
        store,
        multi_chapter_epub_bytes(),
        source_id=sid,
        media_kind="text",
        name="two_gardens.epub",
        format="epub",
    )
    registry = mod.StageWorkRegistryFactory.build(runtime)
    stages = (
        "FORMAT_ANALYSIS",
        "BASIC_SEGMENTATION",
        "LOW_LEVEL_EXTRACTION",
        "STRUCTURAL_ANALYSIS",
    )
    for i in (1, 2):  # run the full text chain TWICE (incl. structural analysis)
        for stage in stages:
            registry[stage](_manifest(mod, stage, sid, f"epub-run{i}-{stage}"))

    segs = _segment_rows(umd_db, sid)
    paths = {s["structural_path"]: s for s in segs}
    # Two chapters present, each with paragraph segments.
    assert "chapter/1" in paths and "chapter/2" in paths
    assert paths["chapter/1"]["segment_type"] == "chapter"
    assert paths["chapter/2"]["segment_type"] == "chapter"
    para_paths = {p for p in paths if "/paragraph/" in p}
    # At least two chapters, each with body paragraphs (the EPUB extractor also
    # emits each chapter <h1> as a paragraph, so >=2 per chapter is guaranteed).
    assert {"chapter/1", "chapter/2"} <= {p.split("/paragraph/")[0] for p in para_paths}
    assert len(para_paths) >= 4, f"expected >=4 paragraph segments, got {sorted(para_paths)}"
    assert all(paths[p]["segment_type"] == "paragraph" for p in para_paths)

    # Evidence-to-segment IDs: every paragraph text_span evidence is pinned to the
    # exact registered paragraph segment (FK) and carries the segment's locator.
    ev = _evidence_rows(umd_db, sid)
    para_evidence = [e for e in ev if e["evidence_kind"] == "text_span" and e["segment_id"]]
    # document/1 + every paragraph segment produce linked text_span evidence.
    assert len(para_evidence) == 1 + len(para_paths), (
        f"expected 1 document + {len(para_paths)} paragraph evidence rows, got {len(para_evidence)}"
    )
    para_by_seg: dict[str, list[dict[str, Any]]] = {}
    for e in para_evidence:
        para_by_seg.setdefault(e["segment_id"], []).append(e)
    linked_paragraph_paths: set[str] = set()
    for seg in segs:
        if seg["segment_type"] != "paragraph":
            continue
        linked = para_by_seg.get(seg["id"])
        assert linked, f"paragraph segment {seg['structural_path']} has no linked evidence"
        linked_paragraph_paths.add(seg["structural_path"])
        for e in linked:
            assert e["locator"] == seg["locator"], (
                f"evidence locator {e['locator']} != segment locator {seg['locator']}"
            )
            # Source provenance on every linked evidence row.
            assert e["raw_ref"] == man.object_id, "raw OCFL ref not preserved on evidence"
            assert e["quality"]["source_sha512"] == man.sha512, "content fixity not on evidence"
            assert e["config_digest"], "evidence config digest must be non-null"
    assert linked_paragraph_paths == para_paths, "some paragraph segments produced no evidence"

    # (P3-S3 corrected path-keyed evidence) each paragraph text_span is pinned to
    # the segment whose structural_path MATCHES the paragraph, carrying the canonical
    # source:// locator and the correct paragraph text — never by positional order.
    # Derive the expected path->text map from the dispatched EPUB document itself.
    res = dispatch_text(multi_chapter_epub_bytes(), format="epub")
    expected_text: dict[str, str] = {}
    for item in res.document.spine:
        chap = item.index + 1
        for p in item.paragraphs:
            expected_text[f"chapter/{chap}/paragraph/{p.index}"] = p.text
    seg_path_by_id = {s["id"]: s["structural_path"] for s in segs}
    for e in para_evidence:
        path = seg_path_by_id[e["segment_id"]]
        if path == "document/1":
            continue  # whole-document span, not a paragraph
        assert path in expected_text, f"evidence segment {e['segment_id']} has unknown path {path}"
        assert e["quality"]["text"] == expected_text[path], (
            f"paragraph evidence at {path} got {e['quality']['text']!r}; expected "
            f"{expected_text[path]!r} (positional misattribution on retry)"
        )

    # Determinism: two runs produced IDENTICAL durable outputs.
    assert _evidence_signature(ev) == _evidence_signature(_evidence_rows(umd_db, sid))
    # Identical evidence count (deduped by uq_evidence_identity on the second run).
    assert len(_evidence_rows(umd_db, sid)) == len(ev)
    # Identical segment set and stable per-path DB ids (uq_segment_deterministic reuse).
    segs_again = _segment_rows(umd_db, sid)
    assert {s["id"] for s in segs_again} == {s["id"] for s in segs}
    assert {s["deterministic_key"] for s in segs_again} == {s["deterministic_key"] for s in segs}
    # The exact paragraph evidence segment_ids are stable across the rerun.
    ids1 = {e["segment_id"] for e in para_evidence}
    ids2 = {
        e["segment_id"]
        for e in _evidence_rows(umd_db, sid)
        if e["evidence_kind"] == "text_span" and e["segment_id"]
    }
    assert ids1 == ids2, "paragraph evidence segment ids must be stable across reruns"


# ---------------------------------------------------------------------------
# P3-S2 (full-DAG extension): the real text chain never leaks raw binary bytes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("case", TEXT_CASES, ids=[c["parser"] for c in TEXT_CASES])
def test_full_text_dag_uses_expected_parser_and_never_leaks_raw_bytes(
    umd_db: sa.Engine, tmp_path: Any, case: dict[str, Any]
) -> None:
    """(P3-S2 full-DAG extension) Running the REAL text chain end-to-end
    (FORMAT_ANALYSIS -> BASIC_SEGMENTATION -> LOW_LEVEL_EXTRACTION ->
    STRUCTURAL_ANALYSIS) keeps the expected parser/segmenter pair and NEVER
    surfaces normalized raw binary bytes as any text evidence."""
    mod = _production()
    runtime, store = _runtime(umd_db, tmp_path)
    _seed_source(
        umd_db,
        store,
        case["raw"],
        source_id=case["id"],
        media_kind=case["media_kind"],
        name=case["name"],
        format=case["format"],
    )
    registry = mod.StageWorkRegistryFactory.build(runtime)
    outcomes: dict[str, Any] = {}
    for stage in (
        "FORMAT_ANALYSIS",
        "BASIC_SEGMENTATION",
        "LOW_LEVEL_EXTRACTION",
        "STRUCTURAL_ANALYSIS",
    ):
        outcomes[stage] = registry[stage](
            _manifest(mod, stage, case["id"], f"fulldag-{case['parser']}")
        )

    # FORMAT_ANALYSIS recorded the real dispatched parser (never a TXT mislabel).
    assert outcomes["FORMAT_ANALYSIS"].metrics["parser"] == case["parser"], outcomes[
        "FORMAT_ANALYSIS"
    ].metrics
    # The format-appropriate segmenter produced its characteristic hierarchy.
    seg_types = {s["segment_type"] for s in _segment_rows(umd_db, case["id"])}
    assert case["types"] <= seg_types, f"expected {case['types']}, got {seg_types}"
    # STRUCTURAL_ANALYSIS consumed the dispatched text (produced findings).
    structural = [
        e
        for e in _evidence_rows(umd_db, case["id"])
        if e["evidence_kind"] == "text_span"
        and e["quality"].get("finding") in ("dialogue", "narration")
    ]
    assert structural, "STRUCTURAL_ANALYSIS produced no dialogue/narration findings from text"

    # Absence of normalized raw binary bytes: no text_span evidence text carries a
    # NUL byte or any binary container signature (%PDF, PK.., PNG magic).
    text_evidence = "".join(
        (e["quality"].get("text") or "")
        for e in _evidence_rows(umd_db, case["id"])
        if e["evidence_kind"] == "text_span" and e["quality"].get("text")
    )
    assert "\x00" not in text_evidence, "raw NUL byte leaked into text evidence"
    raw = case["raw"]
    for sig in (b"%PDF", b"PK\x03\x04", b"\x89PNG"):
        if sig in raw:
            assert sig.decode("latin-1") not in text_evidence, (
                f"raw binary signature {sig!r} surfaced as normalized text evidence"
            )


# ---------------------------------------------------------------------------
# P3-S4: full-DAG dispatch reuse (ONE result through STRUCTURAL_ANALYSIS)
# ---------------------------------------------------------------------------


class _CountingDispatch:
    """Instrument the production dispatch seam: counts how many times a source's
    bytes are actually dispatched (the Plan L P1-S3 memo should make it exactly
    once for a full DAG run). Delegates to the real ``dispatch_text``."""

    def __init__(self) -> None:
        self.calls = 0
        self.formats: list[str | None] = []

    def dispatch(self, source: Any, raw_or_native: Any) -> Any:
        self.calls += 1
        fmt = source.get("format") if isinstance(source, dict) else getattr(source, "format", None)
        sha = source.get("sha512") if isinstance(source, dict) else getattr(source, "sha512", None)
        raw = (
            raw_or_native
            if isinstance(raw_or_native, (bytes, bytearray))
            else bytes(getattr(raw_or_native, "data", b"") or b"")
        )
        self.formats.append(fmt)
        return dispatch_text(bytes(raw), format=fmt, source_sha512=sha)


@pytest.mark.parametrize("case", [TEXT_CASES[2], TEXT_CASES[3]], ids=["epub", "pdf"])
def test_full_dag_dispatch_reused_once_through_structural_analysis(
    umd_db: sa.Engine, tmp_path: Any, case: dict[str, Any]
) -> None:
    """(P3-S4) A full DAG run dispatches an EPUB/PDF source EXACTLY ONCE and
    STRUCTURAL_ANALYSIS reuses the SAME dispatched result — never re-normalizing
    raw EPUB/PDF bytes through TXT. Instrumented at the dispatch seam (not by
    asserting an implementation-specific cache)."""
    mod = _production()
    runtime, store = _runtime(umd_db, tmp_path)
    counting = _CountingDispatch()
    runtime["dispatch"] = counting
    _seed_source(
        umd_db,
        store,
        case["raw"],
        source_id=case["id"],
        media_kind=case["media_kind"],
        name=case["name"],
        format=case["format"],
    )
    registry = mod.StageWorkRegistryFactory.build(runtime)
    for stage in (
        "FORMAT_ANALYSIS",
        "BASIC_SEGMENTATION",
        "LOW_LEVEL_EXTRACTION",
        "STRUCTURAL_ANALYSIS",
    ):
        registry[stage](_manifest(mod, stage, case["id"], f"reuse-{case['parser']}"))

    assert counting.calls == 1, (
        f"dispatch_text called {counting.calls} times for one {case['parser']} source; "
        "expected exactly ONE reused result through the full DAG"
    )
    assert counting.formats == [case["format"]], counting.formats
    # The dispatched parser is what FORMAT_ANALYSIS recorded and what STRUCTURAL
    # consumed — the source was never re-normalized through the TXT baseline.
    structural = [
        e
        for e in _evidence_rows(umd_db, case["id"])
        if e["evidence_kind"] == "text_span" and e["quality"].get("finding")
    ]
    assert structural, f"{case['parser']} full DAG produced no structural findings"


def test_full_dag_image_only_pdf_produces_no_fabricated_text(
    umd_db: sa.Engine, tmp_path: Any
) -> None:
    """(P3-S4) An image-only PDF (route=image_raster) produces NO fabricated
    structural text evidence anywhere in the full DAG: FORMAT_ANALYSIS records a
    media (non-text) metadata row, BASIC_SEGMENTATION registers ZERO segments, and
    STRUCTURAL_ANALYSIS warns and emits nothing."""
    mod = _production()
    runtime, store = _runtime(umd_db, tmp_path)
    sid = "a0000000-0000-4000-8000-0000000000dd"
    _seed_source(
        umd_db,
        store,
        pdf_image_only_bytes(),
        source_id=sid,
        media_kind="text",
        name="scan.pdf",
        format="pdf",
    )
    registry = mod.StageWorkRegistryFactory.build(runtime)
    outcomes: dict[str, Any] = {}
    for stage in (
        "FORMAT_ANALYSIS",
        "BASIC_SEGMENTATION",
        "LOW_LEVEL_EXTRACTION",
        "STRUCTURAL_ANALYSIS",
    ):
        outcomes[stage] = registry[stage](_manifest(mod, stage, sid, f"iopdf-{stage}"))

    # FORMAT_ANALYSIS routed to the media (raster) route, never a text parser.
    assert outcomes["FORMAT_ANALYSIS"].metrics["route"] == "image_raster", outcomes[
        "FORMAT_ANALYSIS"
    ].metrics
    assert _segment_rows(umd_db, sid) == [], "image-only PDF must register no text segments"
    kinds = {e["evidence_kind"] for e in _evidence_rows(umd_db, sid)}
    assert "text_span" not in kinds, "no text_span evidence may be fabricated from binary pages"
    # The only durable evidence is the media-route format_analysis metadata row.
    assert kinds == {"metadata"}, kinds
    # STRUCTURAL_ANALYSIS emits an explicit non-text warning, never fabricated prose.
    structural_warnings = "\n".join(outcomes["STRUCTURAL_ANALYSIS"].warnings)
    assert "no fabricated text evidence" in structural_warnings, structural_warnings


def test_full_dag_degraded_epub_produces_no_fabricated_text(
    umd_db: sa.Engine, tmp_path: Any
) -> None:
    """(P3-S4) A malformed/degraded EPUB (route=degraded) produces NO fabricated
    structural text evidence anywhere in the full DAG, and no segments are
    registered from the non-text dispatch."""
    mod = _production()
    runtime, store = _runtime(umd_db, tmp_path)
    sid = "a0000000-0000-4000-8000-0000000000ee"
    _seed_source(
        umd_db,
        store,
        malformed_epub_bytes(),
        source_id=sid,
        media_kind="text",
        name="bad.epub",
        format="epub",
    )
    registry = mod.StageWorkRegistryFactory.build(runtime)
    outcomes: dict[str, Any] = {}
    for stage in (
        "FORMAT_ANALYSIS",
        "BASIC_SEGMENTATION",
        "LOW_LEVEL_EXTRACTION",
        "STRUCTURAL_ANALYSIS",
    ):
        outcomes[stage] = registry[stage](_manifest(mod, stage, sid, f"depub-{stage}"))

    assert _segment_rows(umd_db, sid) == [], "degraded EPUB must register no text segments"
    kinds = {e["evidence_kind"] for e in _evidence_rows(umd_db, sid)}
    assert "text_span" not in kinds, "no fabricated text_span evidence from a degraded EPUB"
    structural_warnings = "\n".join(outcomes["STRUCTURAL_ANALYSIS"].warnings)
    assert "no fabricated text evidence" in structural_warnings, structural_warnings
    # FORMAT_ANALYSIS surfaced the degraded dispatch warning too.
    assert any("epub parse failed" in w for w in outcomes["FORMAT_ANALYSIS"].warnings)


# ---------------------------------------------------------------------------
# P3-S5: partial-batch crash/retry pins paragraph evidence by structural_path
# ---------------------------------------------------------------------------


def _register_text_segment(
    umd_db: sa.Engine,
    sid: str,
    sha512: str,
    path: str,
    segment_type: str,
    ordinal: int,
    parent_path: str | None,
) -> None:
    """Register ONE deterministic text segment directly (crash-simulation helper).

    Mirrors what ``segment_txt`` would register for the same (sha512, path) so a
    later full re-registration reports it as ``existing`` (idempotent) and the
    rest as ``created`` — interleaving the two non-contiguously."""
    reg = SegmentRegistry(PostgresSegmentStore(umd_db))
    frag = StructuralSelector(path=path) if segment_type in ("paragraph", "sentence") else None
    reg.register(
        [
            SegmentInput(
                source_id=sid,
                source_sha512=sha512,
                work_id=None,
                modality="text",
                structural_path=path,
                segment_type=segment_type,
                version=TEXT_PIPELINE_VERSION,
                ordinal=ordinal,
                parent_path=parent_path,
                frag=frag,
            )
        ]
    )


def test_partial_batch_crash_retry_pins_paragraph_evidence_by_structural_path(
    umd_db: sa.Engine, tmp_path: Any
) -> None:
    """(P3-S5) A partial-batch crash + retry interleaves created and existing
    segment rows; each paragraph ``text_span`` must still pin to the segment whose
    structural_path matches, with the canonical source:// locator and the correct
    paragraph text — never by positional order."""
    mod = _production()
    runtime, store = _runtime(umd_db, tmp_path)
    sid = "a0000000-0000-4000-8000-0000000000cc"
    man = _seed_source(
        umd_db,
        store,
        txt_bytes(),
        source_id=sid,
        media_kind="text",
        name="book.txt",
        format="txt",
    )
    sha = man.sha512
    src = {
        "id": sid,
        "ocfl_ref": man.object_id,
        "sha512": sha,
        "size_bytes": man.size_bytes,
        "media_kind": "text",
        "format": "txt",
    }

    # Simulate a crash that committed ONLY the document/1, chapter/1, section/1
    # and FIRST paragraph (document-order interior). On retry the full batch is
    # re-registered, so `created` (paragraphs 2, 3, sentences, tokens) and
    # `existing` (the first paragraph) interleave non-contiguously.
    _register_text_segment(umd_db, sid, sha, "document/1", "document", 1, None)
    _register_text_segment(umd_db, sid, sha, "chapter/1", "chapter", 1, "document/1")
    _register_text_segment(umd_db, sid, sha, "chapter/1/section/1", "section", 1, "chapter/1")
    _register_text_segment(
        umd_db,
        sid,
        sha,
        "chapter/1/section/1/paragraph/1",
        "paragraph",
        1,
        "chapter/1/section/1",
    )

    # A fresh composer dispatches and emits LOW_LEVEL evidence over the
    # re-registered (interleaved created+existing) batch.
    composer = mod._Composer(  # noqa: SLF001 - registry-internal, test-only
        umd_db, mod.ProductionRuntime(engine=umd_db, source_store=store)
    )
    result = composer._dispatch_text(src)  # noqa: SLF001
    assert result is not None and result.route == "text"
    composer._emit_low_level_text_evidence(src, result)  # noqa: SLF001

    # Expected paragraph text per structural path for the txt fixture (doc order).
    expected: dict[str, str] = {
        "chapter/1/section/1/paragraph/1": "Chapter 1",
        "chapter/1/section/1/paragraph/2": (
            "Alice walked into the garden. She saw the White Rabbit."
        ),
        "chapter/1/section/1/paragraph/3": '"Hello," said Alice. "Where are you going?"',
        "chapter/1/section/1/paragraph/4": (
            "The White Rabbit looked at his pocket watch and hurried away."
        ),
    }
    segs = _segment_rows(umd_db, sid)
    path_by_segid = {s["id"]: s["structural_path"] for s in segs}
    para_ev = [
        e
        for e in _evidence_rows(umd_db, sid)
        if e["evidence_kind"] == "text_span"
        and e["segment_id"] is not None
        and path_by_segid[e["segment_id"]].startswith("chapter/1/section/1/paragraph/")
    ]
    assert len(para_ev) == 4, f"expected 4 paragraph text_span rows, got {len(para_ev)}"
    for e in para_ev:
        path = path_by_segid[e["segment_id"]]
        assert e["quality"]["text"] == expected[path], (
            f"paragraph evidence at {path} got {e['quality']['text']!r} instead of "
            f"{expected[path]!r} (positional misattribution on crash-retry)"
        )
        assert e["locator"].startswith("source://"), (
            "paragraph evidence at {path} must carry a canonical source:// locator, "
            f"got {e['locator']}"
        )
        assert e["raw_ref"] == man.object_id, "raw OCFL ref must be preserved on evidence"


# ---------------------------------------------------------------------------
# P3-S6: in-process EPUB decompression bound (declared sizes > 512 MiB)
# ---------------------------------------------------------------------------


def _raw_zip(entries: list[tuple[str, bytes, int | None]]) -> bytes:
    """Assemble a deterministic stored (uncompressed) ZIP by hand.

    Each entry is ``(name, data, declared_size)``; ``declared_size`` overrides the
    reported uncompressed size in the central directory (and local header) so we
    can fake an EPUB whose *declared* decompressed member size exceeds the bound
    while the actual on-disk bytes are tiny — proving rejection happens on the
    declared size before any unbounded member read."""
    local = bytearray()
    central = bytearray()
    for name, data, declared in entries:
        size = declared if declared is not None else len(data)
        crc = zlib.crc32(data) & 0xFFFFFFFF
        local_offset = len(local)
        local += struct.pack(
            "<IHHHHHIIIHH", 0x04034B50, 20, 0, 0, 0, 0, crc, size, size, len(name), 0
        )
        local += name.encode() + data
        central += struct.pack(
            "<IHHHHHHIIIHHHHHII",
            0x02014B50,
            20,
            20,
            0,
            0,
            0,
            0,
            crc,
            size,
            size,
            len(name),
            0,
            0,
            0,
            0,
            0,
            local_offset,
        )
        central += name.encode()
    cd_size = len(central)
    cd_offset = len(local)
    eocd = struct.pack(
        "<IHHHHIIH", 0x06054B50, 0, 0, len(entries), len(entries), cd_size, cd_offset, 0
    )
    return bytes(local) + bytes(central) + eocd


def _epub_with_declared_spine_size(declared_size: int) -> bytes:
    """A valid EPUB whose spine XHTML member *declares* ``declared_size``
    decompressed bytes but actually holds a tiny payload (decompression-bomb probe)."""
    container = (
        '<?xml version="1.0"?><container version="1.0" '
        'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
        '<rootfiles><rootfile full-path="OEBPS/content.opf" '
        'media-type="application/oebps-package+xml"/></rootfiles></container>'
    )
    opf = (
        '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="2.0" '
        'unique-identifier="uid"><metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
        "<dc:title>Bomb</dc:title><dc:language>en</dc:language></metadata><manifest>"
        '<item id="c1" href="chap1.xhtml" media-type="application/xhtml+xml"/>'
        '</manifest><spine><itemref idref="c1"/></spine></package>'
    )
    chap = '<html xmlns="http://www.w3.org/1999/xhtml"><body><p>tiny</p></body></html>'
    return _raw_zip(
        [
            ("mimetype", b"application/epub+zip", None),
            ("META-INF/container.xml", container.encode(), None),
            ("OEBPS/content.opf", opf.encode(), None),
            ("OEBPS/chap1.xhtml", chap.encode(), declared_size),
        ]
    )


def test_epub_decompression_bound_rejects_over_limit_before_member_reads(tmp_path: Any) -> None:
    """(P3-S6) An EPUB whose total *declared* decompressed member size exceeds
    ``SandboxLimits.max_decompressed_bytes`` (512 MiB) is rejected deterministically
    BEFORE any unbounded member read — even though its actual payload is tiny, so
    the only way it can fail is by honouring the declared-size bound."""
    limit = SandboxLimits().max_decompressed_bytes  # 512 MiB
    assert limit == 512 * 1024 * 1024, "contract bound is 512 MiB"

    tmp = tmp_path / "bomb.epub"
    tmp.write_bytes(_epub_with_declared_spine_size(limit + 1))

    # Direct extractor path: rejected before reads.
    with pytest.raises(EpubParseError, match="max_decompressed_bytes"):
        extract_epub(tmp)

    # Production dispatch seam: degraded non-text result, no fabricated text.
    res = dispatch_text(tmp.read_bytes(), format="epub")
    assert res.route == "degraded"
    assert res.degraded is True and res.non_text is True
    assert res.text == ""
    assert any("max_decompressed_bytes" in w for w in res.warnings), res.warnings


def test_epub_below_bound_still_dispatches() -> None:
    """(P3-S6) An ordinary small EPUB still dispatches successfully below the
    512 MiB bound (positive control for the decompression ceiling)."""
    res = dispatch_text(multi_chapter_epub_bytes(), format="epub")
    assert res.route == "text"
    assert res.text and not res.non_text and not res.degraded
    assert len(res.document.spine) == 2
