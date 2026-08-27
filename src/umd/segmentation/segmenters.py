"""Deterministic text/book segmentation drivers (Phase B, P2-S2).

Builds the v1 text baseline — deterministic
``document / work / edition / chapter / section / paragraph / sentence / token``
segment spans — registering each via :class:`SegmentRegistry` with a
:class:`StructuralSelector` locator. Same normalized input + same parser/tool
versions ⇒ identical segment IDs and locators (deterministic keys).

Stage alignment (from :mod:`umd.jobs.dag`): these drivers implement the
``BASIC_SEGMENTATION`` work (segments + versioned locators); the evidence rows the
callers attach carry ``extraction_stage``/``structural_analysis`` names matching
``LOW_LEVEL_EXTRACTION`` / ``STRUCTURAL_ANALYSIS``.

Raw input is always retained by the caller (OCFL); this module never rewrites it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from umd.domain.locators import PipelineVersion, StructuralSelector
from umd.extractors.epub import EpubDocument
from umd.extractors.markdown import MarkdownDocument
from umd.segmentation.registry import (
    SegmentBatch,
    SegmentInput,
    SegmentRegistry,
)

#: Deterministic tool-version tag for the text segmentation pipeline.
TEXT_PIPELINE_VERSION = PipelineVersion(
    segmenter="umd-text", decoder="umd-stdlib", renderer="plain", version=1
)

_CHAPTER_RE = re.compile(r"^\s*chapter\s+([0-9ivxlcdm]+)\b", re.IGNORECASE)
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+|\n")


@dataclass
class SegmentationResult:
    """Registered text segments plus a readable document structure summary."""

    batch: SegmentBatch
    structure: dict[str, int] = field(default_factory=dict)
    paragraphs: list[str] = field(default_factory=list)


def _paragraphs(text: str) -> list[str]:
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text)]
    return [b for b in blocks if b]


def split_sentences(paragraph: str) -> list[str]:
    """Deterministic sentence split on terminal punctuation followed by space."""
    parts = _SENTENCE_RE.split(paragraph)
    out = [p.strip() for p in parts if p.strip()]
    return out or [paragraph]


def tokenize(sentence: str) -> list[str]:
    """Deterministic whitespace/punctuation tokenization."""
    return [t for t in re.findall(r"[A-Za-z0-9']+", sentence)]


def _chapter_boundaries(text: str) -> list[tuple[str, str]]:
    """Split normalized text into (title, body) chapters on ``Chapter N`` headers.

    Deterministic for identical input. Chapters with no explicit header collapse
    to a single implicit chapter.
    """
    lines = text.split("\n")
    chapters: list[tuple[str, str]] = []
    current_title = "Chapter 1"
    current_lines: list[str] = []
    for line in lines:
        m = _CHAPTER_RE.match(line)
        if m and current_lines and any(c.strip() for c in current_lines):
            chapters.append((current_title, "\n".join(current_lines).strip()))
            current_title = line.strip()
            current_lines = []
        else:
            current_lines.append(line)
    if current_lines and any(c.strip() for c in current_lines):
        chapters.append((current_title, "\n".join(current_lines).strip()))
    return chapters or [("Chapter 1", text.strip())]


def _register(
    _registry: SegmentRegistry,
    *,
    source_id: str,
    source_sha512: str,
    work_id: str | None,
    modality: str,
    path: str,
    segment_type: str,
    version: PipelineVersion,
    ordinal: int | None,
    parent_path: str | None = None,
    frag: StructuralSelector | None = None,
) -> SegmentInput:
    return SegmentInput(
        source_id=source_id,
        source_sha512=source_sha512,
        work_id=work_id,
        modality=modality,
        structural_path=path,
        segment_type=segment_type,
        version=version,
        frag=frag,
        ordinal=ordinal,
        parent_path=parent_path,
    )


def segment_txt(
    registry: SegmentRegistry,
    *,
    source_id: str,
    source_sha512: str,
    work_id: str | None,
    text: str,
    version: PipelineVersion = TEXT_PIPELINE_VERSION,
) -> SegmentationResult:
    """Segment a normalized plain-text document into the full text hierarchy."""
    inputs: list[SegmentInput] = []
    structure: dict[str, int] = {}
    paragraphs: list[str] = []

    doc_path = "document/1"
    inputs.append(
        _register(
            registry,
            source_id=source_id,
            source_sha512=source_sha512,
            work_id=work_id,
            modality="text",
            path=doc_path,
            segment_type="document",
            version=version,
            ordinal=1,
        )
    )
    structure["document"] = 1

    for ci, (_ctitle, cbody) in enumerate(_chapter_boundaries(text), start=1):
        chap_path = f"chapter/{ci}"
        inputs.append(
            _register(
                registry,
                source_id=source_id,
                source_sha512=source_sha512,
                work_id=work_id,
                modality="text",
                path=chap_path,
                segment_type="chapter",
                version=version,
                ordinal=ci,
                parent_path=doc_path,
            )
        )
        # A plain-text document has no explicit section markers; emit one
        # deterministic implicit section per chapter so the full
        # document/chapter/section/paragraph/sentence/token hierarchy is present.
        sec_path = f"{chap_path}/section/1"
        inputs.append(
            _register(
                registry,
                source_id=source_id,
                source_sha512=source_sha512,
                work_id=work_id,
                modality="text",
                path=sec_path,
                segment_type="section",
                version=version,
                ordinal=1,
                parent_path=chap_path,
            )
        )
        paras = _paragraphs(cbody)
        for pi, para in enumerate(paras, start=1):
            para_path = f"{sec_path}/paragraph/{pi}"
            paragraphs.append(para)
            inputs.append(
                _register(
                    registry,
                    source_id=source_id,
                    source_sha512=source_sha512,
                    work_id=work_id,
                    modality="text",
                    path=para_path,
                    segment_type="paragraph",
                    version=version,
                    ordinal=pi,
                    parent_path=sec_path,
                    frag=StructuralSelector(path=para_path),
                )
            )
            for si, sent in enumerate(split_sentences(para), start=1):
                sent_path = f"{para_path}/sentence/{si}"
                inputs.append(
                    _register(
                        registry,
                        source_id=source_id,
                        source_sha512=source_sha512,
                        work_id=work_id,
                        modality="text",
                        path=sent_path,
                        segment_type="sentence",
                        version=version,
                        ordinal=si,
                        parent_path=para_path,
                        frag=StructuralSelector(path=sent_path),
                    )
                )
                for ti, _tok in enumerate(tokenize(sent), start=1):
                    tok_path = f"{sent_path}/token/{ti}"
                    inputs.append(
                        _register(
                            registry,
                            source_id=source_id,
                            source_sha512=source_sha512,
                            work_id=work_id,
                            modality="text",
                            path=tok_path,
                            segment_type="token",
                            version=version,
                            ordinal=ti,
                            parent_path=sent_path,
                        )
                    )
        structure["chapter"] = structure.get("chapter", 0) + 1

    batch = registry.register(inputs)
    return SegmentationResult(batch=batch, structure=structure, paragraphs=paragraphs)


def segment_markdown(
    registry: SegmentRegistry,
    *,
    source_id: str,
    source_sha512: str,
    work_id: str | None,
    doc: MarkdownDocument,
    version: PipelineVersion = TEXT_PIPELINE_VERSION,
) -> SegmentationResult:
    """Segment a parsed Markdown document (H1=chapter, H2=section)."""
    inputs: list[SegmentInput] = []
    structure: dict[str, int] = {}
    paragraphs: list[str] = []

    doc_path = "document/1"
    inputs.append(
        _register(
            registry,
            source_id=source_id,
            source_sha512=source_sha512,
            work_id=work_id,
            modality="text",
            path=doc_path,
            segment_type="document",
            version=version,
            ordinal=1,
        )
    )
    structure["document"] = 1

    chapter_idx = 0
    section_idx = 0
    para_idx = 0
    current_chap_parent = doc_path

    def push_paragraph(path: str, _text: str) -> None:
        nonlocal para_idx
        para_idx += 1
        inputs.append(
            _register(
                registry,
                source_id=source_id,
                source_sha512=source_sha512,
                work_id=work_id,
                modality="text",
                path=path,
                segment_type="paragraph",
                version=version,
                ordinal=para_idx,
                parent_path=current_chap_parent,
                frag=StructuralSelector(path=path),
            )
        )

    for block in doc.blocks:
        if block.kind == "heading" and block.level == 1:
            chapter_idx += 1
            section_idx = 0
            chap_path = f"chapter/{chapter_idx}"
            inputs.append(
                _register(
                    registry,
                    source_id=source_id,
                    source_sha512=source_sha512,
                    work_id=work_id,
                    modality="text",
                    path=chap_path,
                    segment_type="chapter",
                    version=version,
                    ordinal=chapter_idx,
                    parent_path=doc_path,
                )
            )
            current_chap_parent = chap_path
            structure["chapter"] = structure.get("chapter", 0) + 1
            continue
        if block.kind == "heading" and block.level == 2:
            section_idx += 1
            sec_path = f"chapter/{max(chapter_idx, 1)}/section/{section_idx}"
            inputs.append(
                _register(
                    registry,
                    source_id=source_id,
                    source_sha512=source_sha512,
                    work_id=work_id,
                    modality="text",
                    path=sec_path,
                    segment_type="section",
                    version=version,
                    ordinal=section_idx,
                    parent_path=current_chap_parent,
                )
            )
            structure["section"] = structure.get("section", 0) + 1
            continue
        if block.kind == "paragraph" or block.kind == "blockquote" or block.kind == "list":
            if not block.text:
                continue
            p = f"chapter/{max(chapter_idx, 1)}/paragraph/{para_idx + 1}"
            paragraphs.append(block.text)
            push_paragraph(p, block.text)
            continue
        # heading level 3+ treated as section-alike (no separate segment type)
    structure["paragraph"] = para_idx
    batch = registry.register(inputs)
    return SegmentationResult(batch=batch, structure=structure, paragraphs=paragraphs)


def segment_epub(
    registry: SegmentRegistry,
    *,
    source_id: str,
    source_sha512: str,
    work_id: str | None,
    doc: EpubDocument,
    version: PipelineVersion = TEXT_PIPELINE_VERSION,
) -> SegmentationResult:
    """Segment an extracted EPUB (spine item => chapter; paragraphs inside)."""
    inputs: list[SegmentInput] = []
    paragraphs: list[str] = []
    doc_path = "document/1"
    inputs.append(
        _register(
            registry,
            source_id=source_id,
            source_sha512=source_sha512,
            work_id=work_id,
            modality="text",
            path=doc_path,
            segment_type="document",
            version=version,
            ordinal=1,
        )
    )
    for item in doc.spine:
        chapter_idx = item.index + 1
        chap_path = f"chapter/{chapter_idx}"
        inputs.append(
            _register(
                registry,
                source_id=source_id,
                source_sha512=source_sha512,
                work_id=work_id,
                modality="text",
                path=chap_path,
                segment_type="chapter",
                version=version,
                ordinal=chapter_idx,
                parent_path=doc_path,
            )
        )
        for p in item.paragraphs:
            para_path = f"{chap_path}/paragraph/{p.index}"
            paragraphs.append(p.text)
            inputs.append(
                _register(
                    registry,
                    source_id=source_id,
                    source_sha512=source_sha512,
                    work_id=work_id,
                    modality="text",
                    path=para_path,
                    segment_type="paragraph",
                    version=version,
                    ordinal=p.index,
                    parent_path=chap_path,
                    frag=StructuralSelector(path=para_path),
                )
            )
    batch = registry.register(inputs)
    return SegmentationResult(batch=batch, paragraphs=paragraphs)
