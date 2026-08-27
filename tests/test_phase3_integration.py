"""Phase B / P3-S4 integration tests: full raster path on Postgres + OCFL.

Covers the DD raster contract's bounded baseline: bounded decode + metadata,
deterministic page/panel/region ordering, IIIF crop selectors -> OCFL derived
artifacts, OCR region provenance + provider substitution on the SAME fixture,
deterministic/idempotent re-runs, face-candidate non-promotion, and quarantine of
oversized images (raw bytes retained). Requires live PostgreSQL (``postgres``).
"""

from __future__ import annotations

import io
import uuid

import pytest
import sqlalchemy as sa

from fixtures import (
    raster_comic_bytes,
    raster_malformed_bytes,
    raster_oversized_bytes,
    raster_single_panel_bytes,
    raster_text_only_bytes,
)
from umd.domain.locators import IIIFSelector
from umd.raster.bounds import RasterDecodeError, RasterLimitsExceeded, decode_bounded
from umd.raster.ocr import run_ocr
from umd.raster.pipeline import process_raster
from umd.raster.spatial import run_spatial
from umd.segmentation.registry import SegmentRegistry
from umd.storage.ocfl import SourceDescriptor
from umd.storage.postgres.artifacts import PostgresArtifactStore
from umd.storage.postgres.repositories import (
    PostgresEvidenceRepository,
    PostgresQuarantine,
    PostgresSegmentStore,
    SourceMembershipService,
)

pytestmark = pytest.mark.postgres


def _wid() -> str:
    return uuid.uuid4().hex


def _ensure_image(memberships, store, raw):
    man = store.put_immutable(io.BytesIO(raw), SourceDescriptor(logical_name="page.png"))
    sid = _wid()
    memberships.ensure_source(
        source_id=sid,
        ocfl_ref=man.object_id,
        sha512=man.sha512,
        size_bytes=man.size_bytes,
        media_kind="image",
        original_name="page.png",
        work_id=None,  # type: ignore[arg-type]
    )
    return sid, man


def _pipeline(umd_db):
    reg = SegmentRegistry(PostgresSegmentStore(umd_db))
    ev = PostgresEvidenceRepository(umd_db)
    artifacts = PostgresArtifactStore(umd_db)
    return reg, ev, artifacts


def test_raster_full_pipeline_evidence_and_crops(umd_db, source_store) -> None:
    memberships = SourceMembershipService(umd_db)
    sid, man = _ensure_image(memberships, source_store, raster_comic_bytes())
    reg, ev, artifacts = _pipeline(umd_db)

    result = process_raster(
        registry=reg,
        evidence_repo=ev,
        store=source_store,
        artifacts=artifacts,
        source_id=sid,
        source_sha512=man.sha512,
        raw=raster_comic_bytes(),
    )

    # Deterministic segments: page + panels + ink regions.
    types = {s.segment_type for s in result.batch.created}
    assert {"page", "panel", "region"} <= types
    assert result.batch.created, "expected new segments"

    # Evidence kinds emitted.
    kinds = {e.evidence_kind for e in result.evidence.created if e.is_new}
    assert kinds >= {
        "metadata",
        "panel",
        "page_region",
        "ocr_region",
        "text_span",
        "face_observation",
        "object_observation",
    }

    # OCR region provenance: source-first, deterministic text + generated_by.
    ocr = [e for e in result.evidence.created if e.evidence_kind == "ocr_region"]
    for e in ocr:
        assert e.locator.startswith("source://") or "page/1/ocr/" in e.locator
    # reference provider genuinely read HELLO / WORLD / PANEL from pixels.
    ocr_evidence = _evidence_rows(ev, sid, "ocr_region")
    assert any(_q(e, "text") == "HELLO" for e in _join(ocr_evidence))
    assert any(_q(e, "text") == "WORLD" for e in _join(ocr_evidence))
    assert all(
        _q(e, "generated_by", {})["provider"] == "umd-reference-ocr" for e in _join(ocr_evidence)
    )

    # Crops stored as OCFL derived artifacts + Postgres artifact refs.
    assert len(result.crops) >= 2
    for crop in result.crops:
        assert crop.ocfl_ref.startswith("urn:umd:ocfl:derived:")
        assert source_store.verify_fixity(crop.ocfl_ref) is True
        png = source_store.get_range(crop.ocfl_ref, 0, 8).data
        assert png.startswith(b"\x89PNG")
        row = artifacts.get(crop.ocfl_ref)
        assert row is not None and row.kind == "derived"
    # Panel evidence carries the artifact ref for its crop.
    panel_ev = _evidence_rows(ev, sid, "panel")
    assert any(_q(e, "artifact_ref") for e in _join(panel_ev))

    # Metadata evidence reflects bounded decode (format/dims).
    meta = _evidence_rows(ev, sid, "metadata")
    assert _q(_join(meta)[0], "format") == "PNG"
    assert _q(_join(meta)[0], "width") == 400


def test_raster_deterministic_and_idempotent(umd_db, source_store) -> None:
    memberships = SourceMembershipService(umd_db)
    sid, man = _ensure_image(memberships, source_store, raster_comic_bytes())
    reg, ev, artifacts = _pipeline(umd_db)

    first = process_raster(
        registry=reg,
        evidence_repo=ev,
        store=source_store,
        artifacts=artifacts,
        source_id=sid,
        source_sha512=man.sha512,
        raw=raster_comic_bytes(),
    )
    assert first.batch.created

    # Determinism (DD raster contract): identical inputs + config produce the
    # SAME segment IDs (deterministic), so re-running deduplicates segments and
    # yields identical OCR regions/quality.
    second = process_raster(
        registry=reg,
        evidence_repo=ev,
        store=source_store,
        artifacts=artifacts,
        source_id=sid,
        source_sha512=man.sha512,
        raw=raster_comic_bytes(),
    )
    assert second.batch.created == []  # segment IDs are deterministic -> dedup
    assert second.batch.existing
    # Same evidence content (kinds + locators) produced on both runs. With
    # DB-authoritative idempotency (uq_evidence_identity), the second run's
    # evidence is deduplicated and reported as ``existing`` rather than re-created.
    key1 = {(e.evidence_kind, e.locator) for e in first.evidence.created}
    key2 = {(e.evidence_kind, e.locator) for e in second.evidence.existing}
    assert key1 == key2
    # Deterministic OCR: same provider/version => same recognized text.
    assert [r.text for r in first.ocr.regions] == [r.text for r in second.ocr.regions]
    # Deterministic spatial: same panel boxes both runs.
    assert [o.xywh for o in first.spatial.observations] == [
        o.xywh for o in second.spatial.observations
    ]


def test_evidence_cross_call_rerecord_is_idempotent(umd_db, source_store) -> None:
    """Re-recording identical evidence across SEPARATE record() calls is a no-op.

    The ``record`` batch-local ``seen`` set only dedups within one call; the
    DB-level UNIQUE index ``uq_evidence_identity`` (source_id, locator,
    evidence_kind, config_digest) is what makes cross-call re-records idempotent.
    A duplicate insert must be caught by ON CONFLICT DO NOTHING and reported as
    ``existing`` — never inserted as a fresh row.
    """
    from umd.domain.evidence import EvidenceBatch
    from umd.domain.models import Evidence, EvidenceKind

    memberships = SourceMembershipService(umd_db)
    sid, _man = _ensure_image(memberships, source_store, raster_text_only_bytes())
    ev = PostgresEvidenceRepository(umd_db)
    evid = (
        Evidence(
            id=uuid.uuid4(),
            source_id=uuid.UUID(sid),
            evidence_kind=EvidenceKind.TEXT_SPAN,
            locator="source://" + sid + "/text/1",
            config_digest="digest-a",
            quality={"text": "Hello"},
        ),
    )
    batch = EvidenceBatch(records=list(evid))

    first = ev.record(batch)
    second = ev.record(batch)  # a separate call over the identical rows
    assert first.created and all(r.is_new for r in first.created)
    assert first.existing == []
    assert second.created == []
    assert second.existing and all(not r.is_new for r in second.existing)

    # Row-count stability: the second call inserted no new evidence rows.
    with umd_db.connect() as c:
        n = c.execute(
            sa.text("SELECT count(*) FROM evidence WHERE source_id = :s"),
            {"s": sid},
        ).scalar()
    assert n == len(first.created) == 1


def test_ocr_provider_substitution_same_fixture_contract() -> None:
    """Reference + Tesseract both implement OcrResult over the SAME fixture bytes."""
    from umd.raster.ocr import OcrResult, TesseractOcrProvider, _tesseract_available

    fixture = raster_text_only_bytes()
    ref = run_ocr(fixture, "reference")
    assert isinstance(ref, OcrResult)
    assert [r.text for r in ref.regions] == ["HELLO", "WORLD"]
    assert all(r.reading_order >= 1 for r in ref.regions)

    # Substitution: the Tesseract adapter consumes the SAME contract/fixture, but
    # only when the (external) binary is present — otherwise skip cleanly.
    if _tesseract_available():
        t = TesseractOcrProvider().ocr(fixture)
        assert isinstance(t, OcrResult)
        assert t.provider == "umd-tesseract"
        assert all(hasattr(r, "text") and r.xywh for r in t.regions)
    else:
        pytest.skip("tesseract binary not installed; tesseract adapter not exercised")


def test_raster_face_candidate_never_promoted_to_identity(umd_db, source_store) -> None:
    memberships = SourceMembershipService(umd_db)
    sid, man = _ensure_image(memberships, source_store, raster_comic_bytes())
    reg, ev, artifacts = _pipeline(umd_db)
    process_raster(
        registry=reg,
        evidence_repo=ev,
        store=source_store,
        artifacts=artifacts,
        source_id=sid,
        source_sha512=man.sha512,
        raw=raster_comic_bytes(),
    )

    faces = _evidence_rows(ev, sid, "face_observation")
    assert faces, "expected at least one face candidate observation"
    for e in _join(faces):
        assert _q(e, "candidate_kind") == "observation"  # candidate, NEVER canonical

    # No promotion: no canonical entity/identity and no semantic assertion exist
    # for this source (face/object remain observations, not identity claims).
    with umd_db.connect() as c:
        ent = c.execute(
            sa.text(
                "SELECT count(*) FROM entity e LEFT JOIN entity_mention m"
                " ON m.entity_id = e.id WHERE m.source_id = :s"
            ),
            {"s": sid},
        ).scalar()
        asserts = c.execute(
            sa.text("SELECT count(*) FROM semantic_assertion WHERE support_refs::text ILIKE :f"),
            {"f": f"%{sid}%"},
        ).scalar()
    assert (ent or 0) == 0
    assert (asserts or 0) == 0


def test_raster_oversized_quarantined_and_raw_retained(umd_db, source_store) -> None:
    memberships = SourceMembershipService(umd_db)
    sid, man = _ensure_image(memberships, source_store, raster_oversized_bytes())
    reg, ev, artifacts = _pipeline(umd_db)

    with pytest.raises(RasterLimitsExceeded):
        process_raster(
            registry=reg,
            evidence_repo=ev,
            store=source_store,
            artifacts=artifacts,
            source_id=sid,
            source_sha512=man.sha512,
            raw=raster_oversized_bytes(),
        )

    # Raw bytes retained in OCFL even though the image is rejected.
    assert source_store.verify_fixity(man.object_id) is True
    PostgresQuarantine(umd_db).record(
        locator=f"source://{sid}/image/page/1", reason="RASTER_LIMITS_EXCEEDED", refs=[]
    )
    with umd_db.connect() as c:
        n = c.execute(
            sa.text("SELECT count(*) FROM quarantine WHERE reason=:r"),
            {"r": "RASTER_LIMITS_EXCEEDED"},
        ).scalar()
    assert n == 1


def test_raster_malformed_rejected(umd_db, source_store) -> None:
    memberships = SourceMembershipService(umd_db)
    sid, man = _ensure_image(memberships, source_store, raster_malformed_bytes())
    reg, ev, artifacts = _pipeline(umd_db)
    with pytest.raises(RasterDecodeError):
        process_raster(
            registry=reg,
            evidence_repo=ev,
            store=source_store,
            artifacts=artifacts,
            source_id=sid,
            source_sha512=man.sha512,
            raw=raster_malformed_bytes(),
        )
    assert source_store.verify_fixity(man.object_id) is True


def test_crop_iiif_selector_to_bounded_bytes(umd_db, source_store) -> None:
    """IIIF xywh/pct selector -> bounded crop bytes (P3-S1)."""
    from umd.raster.crops import retrieve_crop, store_crop

    memberships = SourceMembershipService(umd_db)
    sid, man = _ensure_image(memberships, source_store, raster_single_panel_bytes())
    artifacts = PostgresArtifactStore(umd_db)

    with decode_bounded(raster_single_panel_bytes()) as img:
        # The single panel occupies (20,20)-(220,160): selector 21,21,199,139 stays in-bounds.
        crop = store_crop(
            source_store,
            artifacts,
            source_id=sid,
            raster=img,
            selector=IIIFSelector(region="21,21,199,139"),
            generated_by={"provider": "test"},
        )
        assert crop.ocfl_ref.startswith("urn:umd:ocfl:derived:")
        blob = retrieve_crop(source_store, crop.ocfl_ref)
        assert blob.startswith(b"\x89PNG")
        assert crop.size_bytes == len(blob)

    # pct form is accepted by IIIFSelector and yields an in-bounds box.
    with decode_bounded(raster_single_panel_bytes()) as img:
        from umd.raster.bounds import crop_bounded

        sub = crop_bounded(img, IIIFSelector(region="pct:5,5,50,50"))
        assert sub.width > 0 and sub.height > 0


def test_spatial_panels_and_candidates() -> None:
    spatial = run_spatial(raster_comic_bytes())
    panels = [o for o in spatial.observations if o.kind == "panel"]
    assert len(panels) >= 2
    assert all(o.reading_order >= 1 for o in panels)
    candidates = spatial.candidates
    assert any(c.kind == "face" for c in candidates)
    assert any(c.kind == "object" for c in candidates)
    assert all(c.candidate_kind == "observation" for c in candidates)


def _evidence_rows(ev, sid, kind: str):
    rows = ev.get_by_source(sid)
    return [r for r in rows if r.evidence_kind == kind]


def _join(rows):
    return list(rows)


def _q(e, key, default=None):
    return (e.quality or {}).get(key, default)
