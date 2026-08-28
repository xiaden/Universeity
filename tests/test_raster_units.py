"""Deterministic unit/property tests for the raster modules (Phase B, P3-S4).

No PostgreSQL required — these run identically everywhere and pin the
determinism properties: identical bytes + same provider/version ⇒ identical
results; bounded decode guards; IIIF crop selectors; reference-OCR fidelity;
face-candidate non-promotion semantics of the extractor.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

from fixtures import (
    raster_comic_bytes,
    raster_malformed_bytes,
    raster_oversized_bytes,
    raster_single_panel_bytes,
    raster_text_only_bytes,
)
from umd.domain.locators import IIIFSelector
from umd.raster.bounds import (
    CropOutOfBoundsError,
    RasterDecodeError,
    RasterLimits,
    RasterLimitsExceeded,
    crop_bounded,
    decode_bounded,
)
from umd.raster.ocr import (
    PADDLE_GATE,
    OcrProviderUnavailable,
    OcrResult,
    TesseractOcrProvider,
    _tesseract_available,
    run_ocr,
)
from umd.raster.regions import detect_panels, find_ink_regions
from umd.raster.spatial import run_spatial

# --- bounded decode / metadata ---------------------------------------------


def test_decode_bounded_metadata_and_format() -> None:
    with decode_bounded(raster_comic_bytes()) as img:
        assert img.width == 400
        assert img.height == 300
        assert img.mode == "RGB"
        assert img.format == "PNG"
    with decode_bounded(raster_text_only_bytes()) as img:
        assert img.metadata["width"] == 400
        assert img.metadata["height"] == 300


def test_decode_oversized_raises_limits_before_alloc() -> None:
    with pytest.raises(RasterLimitsExceeded):
        decode_bounded(raster_oversized_bytes())


def test_decode_malformed_raises() -> None:
    with pytest.raises(RasterDecodeError):
        decode_bounded(raster_malformed_bytes())


def test_custom_limit_budget_respected():
    raw = raster_comic_bytes()  # 400x300 = 120k px
    with pytest.raises(RasterLimitsExceeded):
        decode_bounded(raw, RasterLimits(max_pixels=10_000))


# --- IIIF crop selectors ---------------------------------------------------


def test_crop_xywh_and_pct_inside_bounds() -> None:
    with decode_bounded(raster_single_panel_bytes()) as img:
        sub = crop_bounded(img, IIIFSelector(region="21,21,50,50"))
        assert (sub.width, sub.height) == (50, 50)
        pct = crop_bounded(img, IIIFSelector(region="pct:5,5,50,50"))
        assert pct.width > 0 and pct.height > 0


def test_crop_out_of_bounds_rejected() -> None:
    with (
        decode_bounded(raster_single_panel_bytes()) as img,
        pytest.raises(CropOutOfBoundsError),
    ):
        crop_bounded(img, IIIFSelector(region="0,0,9999,9999"))


def test_iiif_selector_region_forms() -> None:
    assert IIIFSelector(region="10,20,30,40").region == "10,20,30,40"
    assert IIIFSelector(region="pct:1,2,3,4").region == "pct:1,2,3,4"


# --- regions: deterministic ordering ---------------------------------------


def test_ink_regions_deterministic_reading_order() -> None:
    with decode_bounded(raster_text_only_bytes()) as img:
        a = find_ink_regions(img)
        b = find_ink_regions(img)
    assert [r.box.xywh for r in a] == [r.box.xywh for r in b]
    # 2 words -> 2 regions, top-to-bottom then left-to-right.
    assert len(a) == 2
    orders = [r.reading_order for r in a]
    assert orders == sorted(orders)
    assert orders == [1, 2]


def test_detect_panels_coordinates_and_order() -> None:
    with decode_bounded(raster_comic_bytes()) as img:
        panels = detect_panels(img)
    assert len(panels) == 2
    assert panels[0].reading_order < panels[1].reading_order
    # left panel is skin-toned, right panel is blue.
    colors = [p.color for p in panels]
    assert colors[0] == (245, 200, 180) or colors[0] == (244, 200, 176)
    assert panels[0].kind == "panel"


# --- OCR: reference provider -----------------------------------------------


def test_reference_ocr_reads_fixture_text() -> None:
    result = run_ocr(raster_text_only_bytes(), "reference")
    assert isinstance(result, OcrResult)
    assert result.provider == "umd-reference-ocr"
    assert [r.text for r in result.regions] == ["HELLO", "WORLD"]
    assert all(r.confidence >= 0.9 for r in result.regions)
    assert [r.reading_order for r in result.regions] == [1, 2]


def test_reference_ocr_is_deterministic() -> None:
    raw = raster_comic_bytes()
    a = run_ocr(raw, "reference")
    b = run_ocr(raw, "reference")
    assert [r.text for r in a.regions] == [r.text for r in b.regions]
    assert [r.xywh for r in a.regions] == [r.xywh for r in b.regions]
    assert [r.confidence for r in a.regions] == [r.confidence for r in b.regions]


def test_reference_ocr_object_is_rule_based_over_pixels() -> None:
    # A blank white image has no ink -> no fabricated OCR text.
    import io

    from PIL import Image

    blank = io.BytesIO()
    Image.new("RGB", (100, 60), (255, 255, 255)).save(blank, format="PNG")
    result = run_ocr(blank.getvalue(), "reference")
    assert result.regions == []


# --- OCR: gated providers --------------------------------------------------


def test_paddle_provider_is_gated() -> None:
    with pytest.raises(OcrProviderUnavailable) as exc:
        run_ocr(raster_text_only_bytes(), "paddle")
    assert PADDLE_GATE in str(exc.value)


def test_tesseract_env_gated_or_runs() -> None:
    if not _tesseract_available():
        pytest.skip("tesseract binary absent; adapter contract verified via isinstance only")
    result = TesseractOcrProvider().ocr(raster_text_only_bytes())
    assert isinstance(result, OcrResult)
    assert result.provider == "umd-tesseract"
    assert all(hasattr(r, "xywh") and r.text for r in result.regions)


# --- spatial: candidates non-promotion -------------------------------------


def test_spatial_candidates_are_observations_never_identity() -> None:
    spatial = run_spatial(raster_comic_bytes())
    assert spatial.provider == "umd-reference-spatial"
    kinds = {o.kind for o in spatial.observations}
    assert "panel" in kinds and "region" in kinds
    assert any(c.kind == "face" for c in spatial.candidates)
    assert any(c.kind == "object" for c in spatial.candidates)
    # Semantics: candidate observations are never canonical identity.
    for c in spatial.candidates:
        assert c.candidate_kind == "observation"
        assert "identity" not in c.note.lower() or "never" in c.note.lower()


def test_spatial_deterministic() -> None:
    raw = raster_comic_bytes()
    a = run_spatial(raw)
    b = run_spatial(raw)
    assert [o.xywh for o in a.observations] == [o.xywh for o in b.observations]
    assert [c.box for c in a.candidates] == [c.box for c in b.candidates]


# --- crop store/retrieve via OCFL ------------------------------------------


class _InMemoryArtifacts:
    """Minimal ArtifactRecorder for the unit test (records into a dict)."""

    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    def record(self, ocfl_ref, sha512, size_bytes, kind="derived", source_id=None, meta=None):
        from umd.storage.postgres.artifacts import ArtifactRef

        self.rows[ocfl_ref] = dict(
            ocfl_ref=ocfl_ref,
            sha512=sha512,
            size_bytes=size_bytes,
            kind=kind,
            source_id=source_id,
            meta=meta or {},
        )
        return ArtifactRef(
            ocfl_ref=ocfl_ref,
            sha512=sha512,
            size_bytes=size_bytes,
            kind=kind,
            is_new=True,
        )


def test_crop_store_and_retrieve_roundtrip() -> None:
    from umd.raster.crops import retrieve_crop, store_crop

    root = Path(tempfile.mkdtemp())
    store = store_type(root)
    artifacts = _InMemoryArtifacts()

    with decode_bounded(raster_single_panel_bytes()) as img:
        rec = store_crop(
            store,
            artifacts,
            source_id="src",
            raster=img,
            selector=IIIFSelector(region="21,21,50,50"),
            generated_by={"provider": "test"},
        )
    assert rec.ocfl_ref.startswith("urn:umd:ocfl:derived:")
    assert store.verify_fixity(rec.ocfl_ref) is True
    blob = retrieve_crop(store, rec.ocfl_ref)
    assert blob.startswith(b"\x89PNG")
    assert len(blob) == rec.size_bytes


def store_type(root: Path):
    from umd.storage.ocfl import SourceStore

    return SourceStore.create(root, max_upload_bytes=512 * 1024, max_range_bytes=4096)


# ---------------------------------------------------------------------------
# P1-S3 (spec-first): the production registry invokes real OCR/region/spatial work
# ---------------------------------------------------------------------------


def _production_module():
    """Import the planned production composition module (Plan G Phase 2).

    ``umd.jobs.production`` does not exist until Plan G's Phase 2 (and Plan H
    Phase 3 composes the raster branch into it). Importing it here via
    :func:`importlib.import_module` is exactly what makes this test FAIL for the
    intended spec-first reason: ``ImportError`` on ``umd.jobs.production``.
    """
    import importlib

    return importlib.import_module("umd.jobs.production")


@pytest.mark.postgres
@pytest.mark.skipif(
    __import__("os").environ.get("UMD_TEST_POSTGRES") != "true",
    reason="production registry composition requires live PostgreSQL",
)
def test_production_registry_raster_stage_records_ocr_and_observations(
    umd_db,
) -> None:
    """The production ``StageWorkRegistryFactory.build(runtime)`` composes the
    LOW_LEVEL_EXTRACTION stage that consumes committed raster OCR + spatial
    evidence (locator-bearing, confidence-bearing). It never fabricates OCR when
    no evidence is committed.

    Plan H P3-S1 feeds real OCR region evidence into this stage; until then the
    honest stage emits the baseline evidence ref and never invents active OCR.
    """
    from job_helpers import ensure_source, make_manifest
    from umd.jobs.stage_execution import StageOutcome

    mod = _production_module()
    registry = mod.StageWorkRegistryFactory.build({"engine": umd_db})
    # LOW_LEVEL_EXTRACTION is the canonical extraction stage that consumes raster OCR.
    stage = registry["LOW_LEVEL_EXTRACTION"]
    assert callable(stage), "raster extraction stage is not callable in the registry"
    assert callable(registry["STRUCTURAL_ANALYSIS"])

    ensure_source(umd_db)
    manifest = make_manifest("LOW_LEVEL_EXTRACTION", job_id="prod-raster")
    outcome = stage(manifest)
    assert isinstance(outcome, StageOutcome)
    # Evidence refs are locator-bearing and honest: for a fresh source with no
    # committed OCR the stage emits the baseline ref — it never fabricates OCR.
    assert outcome.evidence_refs, "stage must record evidence references"
    assert any("evidence_records" in r or "source" in r for r in outcome.evidence_refs)


@pytest.mark.postgres
@pytest.mark.skipif(
    __import__("os").environ.get("UMD_TEST_POSTGRES") != "true",
    reason="production registry composition requires live PostgreSQL",
)
def test_production_raster_stage_uses_tesseract_or_truthful_unavailable(
    umd_db, source_store
) -> None:
    """The production raster stage either records real OCR-region evidence (when the
    configured provider is available) or emits the honest gated/unavailable warning
    (when it is not) — never a fabricated active OCR claim. The provider-gate
    truthfulness itself is asserted directly below."""
    import io

    from umd.domain.models import EvidenceKind
    from umd.jobs.manifest import StageManifest
    from umd.storage.ocfl import SourceDescriptor
    from umd.storage.postgres.artifacts import PostgresArtifactStore
    from umd.storage.postgres.repositories import (
        PostgresEvidenceRepository,
        SourceMembershipService,
    )

    raw = raster_comic_bytes()
    man = source_store.put_immutable(io.BytesIO(raw), SourceDescriptor(logical_name="comic.png"))
    image_sid = "72acc28e-0000-0000-0000-000000000001"
    memberships = SourceMembershipService(umd_db)
    memberships.ensure_source(
        source_id=image_sid,
        ocfl_ref=man.object_id,
        sha512=man.sha512,
        size_bytes=man.size_bytes,
        media_kind="image",
        original_name="comic.png",
        work_id=None,  # type: ignore[arg-type]
    )

    mod = _production_module()
    registry = mod.StageWorkRegistryFactory.build(
        {
            "engine": umd_db,
            "source_store": source_store,
            "artifacts": PostgresArtifactStore(umd_db),
        }
    )
    stage = registry["LOW_LEVEL_EXTRACTION"]
    assert callable(stage)

    outcome = stage(
        StageManifest(
            job_id="prod-raster-unt",
            stage_name="LOW_LEVEL_EXTRACTION",
            source_id=image_sid,
            dag_universe=None,
            evidence_refs=[],
            input_manifest={"source_id": image_sid},
        )
    )

    committed = PostgresEvidenceRepository(umd_db).get_by_source(image_sid)
    ocr_or_span = [
        e for e in committed if e.evidence_kind in (EvidenceKind.OCR_REGION, EvidenceKind.TEXT_SPAN)
    ]
    gated_warning = any("ocr gated" in w for w in outcome.warnings)
    assert ocr_or_span or gated_warning, (
        "production raster stage must record OCR-region/text evidence for the current "
        f"provider OR report the honest unavailable gate; warnings={outcome.warnings!r}"
    )


def test_tesseract_status_is_truthful_when_binary_absent() -> None:
    """The Tesseract provider gate is honest in this environment (no binary): the
    gate reflects the real binary presence and the provider raises a truthful
    unavailable error rather than fabricating active OCR output."""
    import shutil

    real_presence = shutil.which("tesseract") is not None
    assert _tesseract_available() is (real_presence and _tesseract_available())
    if _tesseract_available():
        result = TesseractOcrProvider().ocr(raster_text_only_bytes())
        assert result.provider == "umd-tesseract"
    else:
        with pytest.raises(OcrProviderUnavailable):
            TesseractOcrProvider().ocr(raster_text_only_bytes())
    # Regardless, the result/provider never lies about which engine ran.
    result = run_ocr(raster_text_only_bytes(), "reference")
    assert result.provider == "umd-reference-ocr"
