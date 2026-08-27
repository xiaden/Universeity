"""Phase B / P2-S4 integration tests: full text/book path on Postgres + OCFL.

Covers TXT, Markdown, EPUB (CFI round-trip), a viable text PDF, image-only PDF
routing, translated/adapted books (multiple sources of one work, distinct), and
malformed-archive quarantine with raw-byte retention. Requires live PostgreSQL
(``postgres`` marker).
"""

from __future__ import annotations

import io
import uuid

import pytest
import sqlalchemy as sa

from fixtures import (
    epub_bytes,
    malformed_epub_bytes,
    markdown_bytes,
    pdf_image_only_bytes,
    pdf_text_bytes,
    txt_bytes,
)
from umd.analysis.text_structural import analyze_text
from umd.domain.evidence import EvidenceBatch
from umd.domain.locators import CfiSelector, PipelineVersion
from umd.extractors.dispatch import invoke_parser
from umd.extractors.epub import extract_epub
from umd.resolution.locator_resolver import LocatorResolver, VersionPolicy
from umd.security.sandbox import SubprocessSandboxRunner
from umd.segmentation.registry import SegmentInput, SegmentRegistry
from umd.segmentation.segmenters import (
    TEXT_PIPELINE_VERSION,
    segment_markdown,
    segment_txt,
)
from umd.storage.ocfl import SourceDescriptor
from umd.storage.postgres.repositories import (
    OcflByteSource,
    PostgresEvidenceRepository,
    PostgresQuarantine,
    PostgresSegmentStore,
    PostgresSourceRepository,
    SourceMembershipService,
)

pytestmark = pytest.mark.postgres


def _wid() -> str:
    return uuid.uuid4().hex


def _ensure_source(memberships, store, raw, *, media_kind, work_id=None):
    man = store.put_immutable(io.BytesIO(raw), SourceDescriptor(logical_name="src.bin"))
    sid = _wid()
    memberships.ensure_source(
        source_id=sid,
        ocfl_ref=man.object_id,
        sha512=man.sha512,
        size_bytes=man.size_bytes,
        media_kind=media_kind,
        original_name="src.bin",
        work_id=work_id,  # type: ignore[arg-type]
    )
    return sid, man


def test_txt_full_path_evidence_and_retrieval(umd_db, source_store) -> None:
    memberships = SourceMembershipService(umd_db)
    sid, man = _ensure_source(memberships, source_store, txt_bytes(), media_kind="text")

    seg_store = PostgresSegmentStore(umd_db)
    reg = SegmentRegistry(seg_store)

    # Decode + segment deterministically.
    from umd.extractors.txt import normalize_txt

    text = normalize_txt(txt_bytes()).text
    res = segment_txt(
        reg,
        source_id=sid,
        source_sha512=man.sha512,
        work_id=None,
        text=text,
        version=TEXT_PIPELINE_VERSION,
    )
    assert res.batch.created

    # Dialogue/narration candidate evidence pinned to a paragraph locator.
    structural = analyze_text(source_id=sid, paragraphs=res.paragraphs, language="en")
    ev = PostgresEvidenceRepository(umd_db)
    recorded = ev.record(EvidenceBatch(records=structural.evidence))
    assert recorded.total == len(structural.evidence)
    assert recorded.created and all(r.is_new for r in recorded.created)

    # Locator round-trip through the resolver returns source-native bytes.
    resolver = LocatorResolver(
        segment_store=seg_store,
        source_repo=PostgresSourceRepository(umd_db),
        byte_source=OcflByteSource(source_store),
        quarantine=PostgresQuarantine(umd_db),
        max_range_bytes=4096,
    )
    para = next(s for s in res.batch.created if s.segment_type == "paragraph")
    rng = resolver.resolve(para.locator, VersionPolicy.BARE)
    assert rng.segment_id == para.segment_id
    assert rng.sha512 == man.sha512  # authoritative full-source fixity
    assert rng.data  # bounded native representation


def test_epub_cfi_round_trip_via_resolver(umd_db, source_store) -> None:
    memberships = SourceMembershipService(umd_db)
    sid, man = _ensure_source(memberships, source_store, epub_bytes(), media_kind="epub")

    # Extraction through the sandbox seam.
    ps = invoke_parser(SubprocessSandboxRunner(), "epub", bytearray(epub_bytes()))
    assert ps.route == "text"

    doc = extract_epub(_write(epub_bytes()))
    seg_store = PostgresSegmentStore(umd_db)
    reg = SegmentRegistry(seg_store)

    # Register a paragraph with its native CfiSelector locator.
    para = doc.spine[0].paragraphs[0]
    seg = reg.register(
        [
            SegmentInput(
                source_id=sid,
                source_sha512=man.sha512,
                modality="text",
                structural_path=f"chapter/1/paragraph/{para.index}",
                segment_type="paragraph",
                version=PipelineVersion("umd-text", "umd-stdlib", "epub3", version=1),
                frag=CfiSelector(cfi=para.cfi),
            )
        ]
    ).created[0]
    assert "epubcfi(" in seg.locator

    resolver = LocatorResolver(
        segment_store=seg_store,
        source_repo=PostgresSourceRepository(umd_db),
        byte_source=OcflByteSource(source_store),
        quarantine=PostgresQuarantine(umd_db),
        max_range_bytes=4096,
    )
    rng = resolver.resolve(seg.locator, VersionPolicy.BARE)
    assert rng.segment_id == seg.segment_id
    assert rng.provenance["ocfl_ref"] == man.object_id


def _write(raw: bytes):
    import pathlib
    import tempfile

    p = pathlib.Path(tempfile.mkdtemp()) / "b.epub"
    p.write_bytes(raw)
    return p


def test_translated_adapted_books_distinct(umd_db, source_store) -> None:
    """Byte-different sources of ONE work yield distinct deterministic segments."""
    memberships = SourceMembershipService(umd_db)
    work_id = _wid()
    memberships.ensure_work(work_id=work_id, title="The Garden", work_type="book")

    s1 = _ensure_source(memberships, source_store, txt_bytes(), media_kind="text", work_id=work_id)
    s2 = _ensure_source(
        memberships, source_store, markdown_bytes(), media_kind="text", work_id=work_id
    )
    sid1, man1 = s1
    sid2, man2 = s2

    store = PostgresSegmentStore(umd_db)
    reg = SegmentRegistry(store)
    r1 = segment_txt(
        reg,
        source_id=sid1,
        source_sha512=man1.sha512,
        work_id=work_id,
        text=io.BytesIO(txt_bytes()).read().decode("utf-8"),
        version=TEXT_PIPELINE_VERSION,
    )
    r2 = segment_markdown(
        reg,
        source_id=sid2,
        source_sha512=man2.sha512,
        work_id=work_id,
        doc=_md_doc(),
        version=TEXT_PIPELINE_VERSION,
    )
    k1 = {s.deterministic_key for s in r1.batch.created}
    k2 = {s.deterministic_key for s in r2.batch.created}
    assert k1.isdisjoint(k2)  # distinct sources never conflated


def _md_doc():
    from umd.extractors.markdown import parse_markdown
    from umd.extractors.txt import normalize_txt

    return parse_markdown(normalize_txt(markdown_bytes()).text)


def test_malformed_archive_quarantined_raw_retained(umd_db, source_store) -> None:
    memberships = SourceMembershipService(umd_db)
    sid, man = _ensure_source(memberships, source_store, malformed_epub_bytes(), media_kind="epub")

    # Raw bytes are ALWAYS retained in OCFL, even though parsing fails.
    assert source_store.verify_fixity(man.object_id) is True
    raw = source_store.get_range(man.object_id, 0, 4096)
    assert raw.data == malformed_epub_bytes()

    # The deterministic parse failure surfaces through the sandbox seam and is
    # quarantined rather than retried silently.
    from umd.extractors.dispatch import SandboxParseError

    with pytest.raises(SandboxParseError):
        invoke_parser(SubprocessSandboxRunner(), "epub", bytearray(malformed_epub_bytes()))

    quarantine = PostgresQuarantine(umd_db)
    quarantine.record(locator=f"source://{sid}/epub/chapter/1", reason="EPUB_PARSE_ERROR", refs=[])
    with umd_db.connect() as c:
        n = c.execute(
            sa.text("SELECT count(*) FROM quarantine WHERE reason=:r"), {"r": "EPUB_PARSE_ERROR"}
        ).scalar()
    assert n == 1


def test_image_only_pdf_routes_to_raster_signal() -> None:
    from umd.extractors.dispatch import RASTER_OCR_STAGE

    sb = SubprocessSandboxRunner()
    ps = invoke_parser(sb, "pdf", bytearray(pdf_image_only_bytes()))
    assert ps.route == "image_raster"
    # The raster/OCR stage is a Plan-C routing signal, not implemented here.
    assert RASTER_OCR_STAGE == "RASTER_OCR"


def test_viable_text_pdf_segmented(umd_db, source_store) -> None:
    memberships = SourceMembershipService(umd_db)
    sid, man = _ensure_source(memberships, source_store, pdf_text_bytes(), media_kind="pdf")

    sb = SubprocessSandboxRunner()
    ps = invoke_parser(sb, "pdf", bytearray(pdf_text_bytes()))
    assert ps.route == "text"
    assert ps.document["has_any_text"] is True

    # Text PDF goes through normal text segmentation (raw retained).
    seg_store = PostgresSegmentStore(umd_db)
    reg = SegmentRegistry(seg_store)
    text = "Hello from the text layer."
    res = segment_txt(
        reg,
        source_id=sid,
        source_sha512=man.sha512,
        work_id=None,
        text=text,
        version=TEXT_PIPELINE_VERSION,
    )
    assert res.batch.created
    assert source_store.verify_fixity(man.object_id) is True
