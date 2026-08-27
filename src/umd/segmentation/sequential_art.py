"""Composed sequential-art structure from text-bearing sources (Phase B, P2-S3).

Where the source supports it (Markdown ``![alt](src)``, EPUB/HTML ``<img>``), we
emit page/region/caption **structure** while keeping the sequential-art hierarchy
*source-specific* and *composing* it with the text extraction rather than
flattening modalities:

  * each source image becomes an ``image``-modality ``page`` segment (deterministic
    id from content identity + ``image`` modality + structural path);
  * its alt/caption text becomes a ``caption`` segment plus evidence;
  * a **composition** evidence row links the image page to the adjacent text
    paragraph (they stay separate modalities — never merged into one segment).

Panel / speech-bubble / region geometry requires raster decoding and is explicitly
deferred to the Plan-C raster/OCR stage: this module emits the *composition
skeleton* only. ``page / region / panel / speech_bubble / caption`` align with the
``image`` :class:`~umd.jobs.dag.ModalityBranch` segment types.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from umd.domain.locators import PipelineVersion, StructuralSelector
from umd.domain.models import Evidence, EvidenceKind
from umd.extractors.markdown import MarkdownDocument
from umd.segmentation.registry import SegmentBatch, SegmentInput, SegmentRegistry
from umd.segmentation.segmenters import TEXT_PIPELINE_VERSION


@dataclass
class SequentialArtResult:
    """Composed page/caption structure for a text-bearing sequential-art source."""

    batch: SegmentBatch | None = None
    pages: list[str] = field(default_factory=list)  # structural paths of image pages
    captions: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)


def build_sequential_art(
    registry: SegmentRegistry,
    *,
    source_id: str,
    source_sha512: str,
    work_id: str | None,
    doc: MarkdownDocument,
    version: PipelineVersion = TEXT_PIPELINE_VERSION,
    tool_versions: dict[str, str] | None = None,
    config_digest: str | None = None,
) -> SequentialArtResult:
    """Emit image-page + caption segments from a Markdown document's image blocks.

    Non-destructive composition: image pages (``image`` modality) and the adjacent
    caption/text paragraphs (``text`` modality) both register under their own
    deterministc keys; a composition evidence row records the link. Panel/region/
    bubble geometry is out of scope here (raster, Plan C).
    """
    inputs: list[SegmentInput] = []
    result = SequentialArtResult()
    tools = {"segmenter": "umd-text", "decoder": "umd-stdlib", **(tool_versions or {})}

    pages = [b for b in doc.blocks if b.kind == "image"]
    # preceding text paragraph index (for composition) resets per image list
    for n, block in enumerate(pages, start=1):
        page_path = f"page/{n}"
        inputs.append(
            SegmentInput(
                source_id=source_id,
                source_sha512=source_sha512,
                work_id=work_id,
                modality="image",
                structural_path=page_path,
                segment_type="page",
                version=version,
                ordinal=n,
                frag=StructuralSelector(path=page_path),
                metadata_={
                    "image_src": block.image_src,
                    "image_alt": block.image_alt or "",
                    "panel/region/bubble geometry": "deferred to RASTER_OCR (Plan C)",
                },
            )
        )
        result.pages.append(page_path)

        if block.image_alt:
            cap_path = f"page/{n}/caption"
            inputs.append(
                SegmentInput(
                    source_id=source_id,
                    source_sha512=source_sha512,
                    work_id=work_id,
                    modality="text",
                    structural_path=cap_path,
                    segment_type="caption",
                    version=version,
                    ordinal=n,
                    parent_path=page_path,
                    frag=StructuralSelector(path=cap_path),
                )
            )
            result.captions.append(cap_path)
            result.evidence.append(
                Evidence(
                    source_id=source_id,
                    evidence_kind=EvidenceKind.TEXT_SPAN,
                    locator=cap_path,
                    extraction_stage="BASIC_SEGMENTATION",
                    tool_versions=tools,
                    config_digest=config_digest,
                    confidence=0.8,
                    quality={"caption_of": page_path, "text": block.image_alt},
                )
            )

        # Composition: image page <-> text flow, WITHOUT flattening modalities.
        result.evidence.append(
            Evidence(
                source_id=source_id,
                evidence_kind=EvidenceKind.LAYOUT,
                locator=page_path,
                extraction_stage="STRUCTURAL_ANALYSIS",
                tool_versions=tools,
                config_digest=config_digest,
                confidence=0.7,
                quality={
                    "composition": "sequential_art_page_in_text_flow",
                    "image_page": page_path,
                    "image_src": block.image_src,
                    "modalities_kept_separate": True,
                },
            )
        )

    result.batch = registry.register(inputs)
    return result
