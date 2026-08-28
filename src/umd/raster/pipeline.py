"""Raster image pipeline: bounded decode -> segment -> evidence -> crops (P3-S1..S3).

Consumes the ``image_raster`` routing signal (Phase 2 extractors.dispatch) and
implements the DD raster contract's bounded baseline:

  1. **P3-S1** — bounded Pillow decode/metadata (format, mode, dimensions,
     EXIF-bounded metadata) with pixel/dimension budget + decompression-bomb
     guard; deterministic page / panel / region ordering with IIIF-compatible
     crop selectors; each panel's crop bytes are stored as an OCFL **derived**
     object and referenced by a Postgres ``artifact`` row.
  2. **P3-S2** — provider-adapted OCR (reference / tesseract / gated paddle)
     emitting ``ocr_region`` + ``text_span`` evidence with source locators,
     confidence, reading order, and generated-by provider. **Evidence, never
     canonical identity.**
  3. **P3-S3** — deterministic spatial extraction emitting ``page_region`` /
     ``panel`` evidence and confidence-bearing ``face_observation`` /
     ``object_observation`` **candidates** (``candidate_kind=observation``), which
     are never promoted to canonical identity.

Identical input bytes + same provider/version + same config ⇒ identical segment
and evidence IDs/rows (determinism). Raw source bytes are retained by the caller
(OCFL); this module never rewrites them.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from pydantic import BaseModel, Field

from umd.domain.evidence import EvidenceBatch, RecordedEvidenceBatch
from umd.domain.locators import IIIFSelector, PipelineVersion
from umd.domain.models import Evidence, EvidenceKind
from umd.raster.bounds import RasterImage, RasterLimits, decode_bounded
from umd.raster.crops import ArtifactRecorder, CropRecord, store_crop
from umd.raster.ocr import OcrConfig, OcrResult, run_ocr
from umd.raster.spatial import SpatialResult, run_spatial
from umd.segmentation.registry import SegmentBatch, SegmentInput, SegmentRegistry

#: Deterministic pipeline version for the raster branch (segmenter/decoder/renderer).
RASTER_PIPELINE_VERSION = PipelineVersion(
    segmenter="umd-raster", decoder="Pillow", renderer="raster", version=1
)

EXTRACTION_STAGE = "RASTER_OCR"


class EvidenceRepository(Protocol):
    def record(self, batch: EvidenceBatch) -> RecordedEvidenceBatch: ...


class RasterPipelineConfig(BaseModel):
    """Runtime configuration for one raster processing run (bounded)."""

    extraction_stage: str = EXTRACTION_STAGE
    ocr_provider: str = "reference"
    ocr_language: str = "eng"
    ocr_max_regions: int = 64
    ocr_min_confidence: float = 0.0
    panel_min_area: int = 1200
    limits: RasterLimits = Field(default_factory=RasterLimits)


@dataclass
class RasterProcessResult:
    """Summary of one raster processing run."""

    batch: SegmentBatch | None = None
    evidence: RecordedEvidenceBatch | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    ocr: OcrResult | None = None
    spatial: SpatialResult | None = None
    crops: list[CropRecord] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _tools(ocr: OcrResult | None, spatial: SpatialResult | None) -> dict[str, str]:
    t = {
        "segmenter": "umd-raster",
        "decoder": "Pillow",
        "renderer": "raster",
        "extractor": "umd-raster-custom@1",
    }
    if ocr is not None:
        t["ocr_provider"] = ocr.provider
        t["ocr_version"] = ocr.provider_version
    if spatial is not None:
        t["spatial_provider"] = spatial.provider
        t["spatial_version"] = spatial.provider_version
    return t


def _config_digest(config: RasterPipelineConfig) -> str:
    """Deterministic sha512 digest of the effective config.

    Evidence idempotency keys on (source, locator, kind, config_digest); the
    digest must be a stable, non-null value so identical runs deduplicate. Dedup
    is DB-authoritative: the ``evidence`` table's UNIQUE index
    ``uq_evidence_identity`` (source_id, locator, evidence_kind, config_digest)
    treats identical runs as a no-op across pipeline invocations — the config
    digest guarantees the same config yields the same key.
    """
    payload = json.dumps(config.model_dump(), sort_keys=True, default=str)
    return hashlib.sha512(payload.encode("utf-8")).hexdigest()


def process_raster(
    *,
    registry: SegmentRegistry,
    evidence_repo: EvidenceRepository,
    store: Any,
    artifacts: ArtifactRecorder,
    source_id: str,
    source_sha512: str,
    raw: bytes,
    work_id: str | None = None,
    version: PipelineVersion = RASTER_PIPELINE_VERSION,
    tool_versions: dict[str, str] | None = None,
    config_digest: str | None = None,
    config: RasterPipelineConfig | None = None,
    segment_id_for_locator: Callable[[str], str | None] | None = None,
) -> RasterProcessResult:
    """Run the full bounded raster pipeline on raw image bytes.

    Raises :class:`umd.raster.bounds.RasterError` subclasses on decode/limit
    failure; the caller quarantines rather than retries.
    """
    config = config or RasterPipelineConfig()
    if config_digest is None:
        config_digest = _config_digest(config)
    with decode_bounded(raw, config.limits) as image:
        raster: RasterImage = image

        # OCR + spatial first so generated-by flows into tool versions.
        ocr = run_ocr(
            raw,
            config.ocr_provider,
            OcrConfig(
                language=config.ocr_language,
                max_regions=config.ocr_max_regions,
                min_confidence=config.ocr_min_confidence,
            ),
        )
        spatial = run_spatial(raw, panel_min_area=config.panel_min_area)
        tools = _tools(ocr, spatial)
        if tool_versions:
            tools.update(tool_versions)

        inputs: list[SegmentInput] = []
        evidence: list[Evidence] = []
        crops: list[CropRecord] = []

        page_path = "page/1"
        inputs.append(
            SegmentInput(
                source_id=source_id,
                source_sha512=source_sha512,
                work_id=work_id,
                modality="image",
                structural_path=page_path,
                segment_type="page",
                version=version,
                ordinal=1,
                frag=IIIFSelector(region=f"0,0,{raster.width},{raster.height}"),
                metadata_={
                    "format": raster.format,
                    "width": raster.width,
                    "height": raster.height,
                    "mode": raster.mode,
                },
            )
        )

        # Metadata evidence (bounded decode metadata).
        evidence.append(
            Evidence(
                source_id=source_id,
                evidence_kind=EvidenceKind.METADATA,
                locator=page_path,
                extraction_stage=config.extraction_stage,
                tool_versions=dict(tools),
                config_digest=config_digest,
                confidence=1.0,
                quality=raster.metadata,
            )
        )

        # Panel + region segments and evidence with IIIF crop selectors + crops.
        panels = [o for o in spatial.observations if o.kind == "panel"]
        regions = [o for o in spatial.observations if o.kind == "region"]
        candidate_by_box: dict[tuple[int, int, int, int], Any] = {}
        for c in spatial.candidates:
            candidate_by_box[c.box] = c

        for p in panels:
            path = f"{page_path}/panel/{p.reading_order}"
            inputs.append(
                SegmentInput(
                    source_id=source_id,
                    source_sha512=source_sha512,
                    work_id=work_id,
                    modality="image",
                    structural_path=path,
                    segment_type="panel",
                    version=version,
                    ordinal=p.reading_order,
                    parent_path=page_path,
                    frag=IIIFSelector(region=p.xywh),
                    metadata_={"region_xywh": p.xywh, "reading_order": p.reading_order},
                )
            )
            crop = store_crop(
                store,
                artifacts,
                source_id=source_id,
                raster=raster,
                selector=IIIFSelector(region=p.xywh),
                generated_by={
                    "provider": spatial.provider,
                    "provider_version": spatial.provider_version,
                    "segmenter": "umd-raster",
                },
                logical_name=f"panel_{p.reading_order}.png",
            )
            crops.append(crop)
            evidence.append(
                Evidence(
                    source_id=source_id,
                    evidence_kind=EvidenceKind.PANEL,
                    locator=path,
                    extraction_stage=config.extraction_stage,
                    tool_versions=dict(tools),
                    config_digest=config_digest,
                    confidence=p.confidence,
                    artifact_ref=crop.ocfl_ref,
                    quality={
                        "region_xywh": p.xywh,
                        "reading_order": p.reading_order,
                        "artifact_ref": crop.ocfl_ref,
                        "crop_bytes": crop.size_bytes,
                    },
                )
            )
            cand = candidate_by_box.get((p.x, p.y, p.width, p.height))
            if cand is not None:
                kind = (
                    EvidenceKind.FACE_OBSERVATION
                    if cand.kind == "face"
                    else EvidenceKind.OBJECT_OBSERVATION
                )
                evidence.append(
                    Evidence(
                        source_id=source_id,
                        evidence_kind=kind,
                        locator=path,
                        extraction_stage=config.extraction_stage,
                        tool_versions=dict(tools),
                        config_digest=config_digest,
                        confidence=cand.confidence,
                        artifact_ref=crop.ocfl_ref,
                        quality={
                            "region_xywh": cand.xywh,
                            "candidate_kind": "observation",  # NEVER canonical identity
                            "candidate_label": cand.kind,
                            "note": cand.note,
                            "generated_by": cand.generated_by,
                        },
                    )
                )

        for r in regions:
            path = f"{page_path}/region/{r.reading_order}"
            inputs.append(
                SegmentInput(
                    source_id=source_id,
                    source_sha512=source_sha512,
                    work_id=work_id,
                    modality="image",
                    structural_path=path,
                    segment_type="region",
                    version=version,
                    ordinal=r.reading_order,
                    parent_path=page_path,
                    frag=IIIFSelector(region=r.xywh),
                    metadata_={"region_xywh": r.xywh, "reading_order": r.reading_order},
                )
            )
            evidence.append(
                Evidence(
                    source_id=source_id,
                    evidence_kind=EvidenceKind.PAGE_REGION,
                    locator=path,
                    extraction_stage=config.extraction_stage,
                    tool_versions=dict(tools),
                    config_digest=config_digest,
                    confidence=r.confidence,
                    quality={
                        "region_xywh": r.xywh,
                        "reading_order": r.reading_order,
                    },
                )
            )

        # OCR region + text_span evidence (with source locators + reading order).
        ocr_texts: list[str] = []
        for o in ocr.regions:
            loc = f"{page_path}/ocr/{o.reading_order}"
            ocr_texts.append(o.text)
            evidence.append(
                Evidence(
                    source_id=source_id,
                    evidence_kind=EvidenceKind.OCR_REGION,
                    locator=loc,
                    language=o.language,
                    extraction_stage=config.extraction_stage,
                    tool_versions=dict(tools),
                    config_digest=config_digest,
                    confidence=o.confidence,
                    quality={
                        "region_xywh": o.xywh,
                        "text": o.text,
                        "reading_order": o.reading_order,
                        "generated_by": ocr.generated_by,
                    },
                )
            )
        if ocr_texts:
            evidence.append(
                Evidence(
                    source_id=source_id,
                    evidence_kind=EvidenceKind.TEXT_SPAN,
                    locator=page_path,
                    language=config.ocr_language,
                    extraction_stage=config.extraction_stage,
                    tool_versions=dict(tools),
                    config_digest=config_digest,
                    confidence=0.9,
                    quality={
                        "text": " ".join(ocr_texts),
                        "reading_order": [o.reading_order for o in ocr.regions],
                        "generated_by": ocr.generated_by,
                    },
                )
            )

        batch = registry.register(inputs)
        # Append-only segment linkage: when a resolver is supplied, stamp each
        # evidence record's ``segment_id`` (the owning segment's DB row id) at
        # record time instead of a post-hoc UPDATE back-fill. The resolver is
        # called lazily here (after segments are registered) so it can resolve
        # freshly-persisted DB row ids. Evidence with no owning segment (e.g.
        # OCR-region observations) keeps ``segment_id`` NULL, unchanged.
        if segment_id_for_locator is not None:
            for ev in evidence:
                seg_id = segment_id_for_locator(ev.locator) if ev.locator else None
                if seg_id:
                    ev.segment_id = uuid.UUID(seg_id)
        recorded = evidence_repo.record(EvidenceBatch(records=evidence))

        return RasterProcessResult(
            batch=batch,
            evidence=recorded,
            metadata=raster.metadata,
            ocr=ocr,
            spatial=spatial,
            crops=crops,
            warnings=spatial.warnings,
        )
