"""EPUB extraction — AGPL-avoidance path (Phase B, P2-S1).

EPUB is a ZIP container of XHTML + OPF + (optional) NCX. This module extracts it
using **stdlib ``zipfile`` + ``xml.etree``** and emits EPUB CFI locators
(:class:`umd.domain.locators.CfiSelector`), deliberately *not* the AGPL-licensed
``ebooklib``.

**AGPL gate (recorded).** The DD names ebooklib for EPUB but lists AGPL deps as a
build/release gate. Preference order from the plan: (a) implement EPUB extraction
with stdlib + XML and record the AGPL-avoidance decision — which is what this
module does; ebooklib is NOT added as a dependency and NOT shipped as a default.

Determinism: same EPUB bytes + same parser version yield the same spine order and
the same per-paragraph CFI locators. The container is validated (required
``mimetype``/``container.xml``/``OPF``) and an invalid/unsupported container is
reported as a deterministic parse failure so the caller quarantines it while
retaining the raw bytes.
"""

from __future__ import annotations

import zipfile
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

#: XHTML namespace used by EPUB content documents.
_XHTML_NS = "http://www.w3.org/1999/xhtml"
_XHTML = "{" + _XHTML_NS + "}"

#: Block-level elements whose text becomes a paragraph in the normalized spine.
_BLOCK_TAGS = {"p", "h1", "h2", "h3", "h4", "h5", "h6", "li", "blockquote", "td"}


def build_cfi(spine_index: int, idref: str, paragraph_index: int = 0) -> str:
    """Construct a deterministic EPUB CFI anchored at a spine document.

    The CFI is structurally valid (``epubcfi(...)``) and stable across identical
    bytes: spine position + ``idref`` identify the document; ``paragraph_index``
    selects a block inside it. Character offsets are omitted (byte offsets on
    text are not required for the baseline and would be over-brittle).
    """
    part = spine_index + 2  # EPUB CFI book-start '/6/' then part per spine item
    base = f"/6/{part}[{idref}]"
    if paragraph_index == 0:
        return f"epubcfi({base}!/4/)"
    return f"epubcfi({base}!/4/2/{paragraph_index})"


@dataclass
class EpubParagraph:
    """A normalized text block within one EPUB spine document."""

    text: str
    index: int
    tag: str = "p"
    cfi: str | None = None


@dataclass
class EpubSpineItem:
    """One spine document (chapter/section) in reading order."""

    idref: str
    href: str
    index: int
    paragraphs: list[EpubParagraph] = field(default_factory=list)
    title: str | None = None


@dataclass
class EpubDocument:
    """Extracted, normalized EPUB content."""

    title: str | None = None
    language: str | None = None
    spine: list[EpubSpineItem] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "language": self.language,
            "warnings": self.warnings,
            "spine": [
                {
                    "idref": s.idref,
                    "href": s.href,
                    "index": s.index,
                    "title": s.title,
                    "paragraphs": [
                        {"text": p.text, "index": p.index, "tag": p.tag, "cfi": p.cfi}
                        for p in s.paragraphs
                    ],
                }
                for s in self.spine
            ],
        }


def _parse_xml(raw: bytes) -> ET.Element:
    """Parse XML from ``raw`` with entity-bomb protection (EPUB/OPF are untrusted).

    The dominant XML-bomb vector (billion-laughs via internal ``<!ENTITY``)
    relies on a DOCTYPE; we reject any ``<!DOCTYPE``/``<!ENTITY`` declaration
    outright, and the outer sandbox bounds input size/time. stdlib ElementTree is
    preferred here (AGPL-avoidance path); its known 3rd-party-attack surface is
    mitigated as above. (S314 is intentional: defusedxml would be a new dep for a
    path that is already entity-declaration-rejected and sandbox bounded.)
    """
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise EpubParseError("XML declares entities/DOCTYPE (rejected for safety)")
    return ET.fromstring(raw)  # noqa: S314 - guarded against entity/DOCTYPE bombs above


class EpubParseError(ValueError):
    """Deterministic EPUB parse failure (invalid/unsupported container)."""


def extract_epub(epub_path: Path) -> EpubDocument:
    """Extract a deterministic normalized view of an EPUB container."""
    try:
        with zipfile.ZipFile(epub_path) as zf:
            names = set(zf.namelist())
            _validate_container(names)
            opf_path = _find_opf(zf, names)
            opf_xml = zf.read(opf_path)
            doc = _parse_opf(opf_xml)
            _extract_spine(zf, opf_path.rpartition("/")[0], doc)
    except zipfile.BadZipFile as exc:
        raise EpubParseError(f"not a valid ZIP/EPUB container: {exc}") from exc
    return doc


def _validate_container(names: set[str]) -> None:
    if "mimetype" not in names:
        raise EpubParseError("EPUB missing the 'mimetype' entry")
    if "META-INF/container.xml" not in names:
        raise EpubParseError("EPUB missing META-INF/container.xml")
    if any(".." in n or n.startswith("/") or "\\" in n for n in names):
        raise EpubParseError("EPUB container contains a traversal/absolute path entry")


def _find_opf(zf: zipfile.ZipFile, names: set[str]) -> str:
    try:
        root = _parse_xml(zf.read("META-INF/container.xml"))
    except ET.ParseError as exc:
        raise EpubParseError(f"invalid container.xml: {exc}") from exc
    ns = "{urn:oasis:names:tc:opendocument:xmlns:container}"
    for rootfile in root.iter(f"{ns}rootfile"):
        full = rootfile.get("full-path")
        if full and full in names:
            return full
    raise EpubParseError("container.xml does not reference an OPF inside the archive")


def _parse_opf(opf_xml: bytes) -> EpubDocument:
    try:
        root = _parse_xml(opf_xml)
    except ET.ParseError as exc:
        raise EpubParseError(f"invalid OPF XML: {exc}") from exc

    doc = EpubDocument()
    doc.title = _first_metadata_text(root, "title")
    doc.language = _first_metadata_text(root, "language")

    manifest: dict[str, dict[str, str]] = {}
    for item in _iter_local(root, "item"):
        mid = item.get("id")
        if mid:
            manifest[mid] = {
                "href": item.get("href") or "",
                "media-type": item.get("media-type") or "",
            }

    spine: list[EpubSpineItem] = []
    for itemref in _iter_local(root, "itemref"):
        idx = len(spine)
        idref = itemref.get("idref")
        if not idref or idref not in manifest:
            continue
        spine.append(EpubSpineItem(idref=idref, href=manifest[idref]["href"], index=idx))
    doc.spine = spine
    return doc


def _extract_spine(zf: zipfile.ZipFile, base_dir: str, doc: EpubDocument) -> None:
    names = set(zf.namelist())
    for item in doc.spine:
        rel = _safe_href(item.href)
        path = f"{base_dir}/{rel}" if base_dir else rel
        if path not in names:
            base = rel.rsplit("/", 1)[-1]
            alt = [n for n in names if n.endswith("/" + base) or n == base]
            if not alt:
                doc.warnings.append(f"spine doc not found: {path}")
                continue
            path = alt[0]
        raw = zf.read(path)
        try:
            root = _parse_xml(raw)
        except ET.ParseError:
            doc.warnings.append(f"spine doc unparsable XML: {path}")
            continue
        item.title = _first_heading(root)
        _collect_paragraphs(root, item)


def _safe_href(href: str) -> str:
    href = href.replace("\\", "/")
    if any(part == ".." for part in href.split("/")):
        raise EpubParseError(f"spine href escapes container: {href!r}")
    return href.lstrip("/")


def _iter_local(root: ET.Element, tag: str) -> Iterator[ET.Element]:
    """Iterate elements whose *local name* equals ``tag`` (namespace-agnostic)."""
    for el in root.iter():
        name = el.tag
        if isinstance(name, str) and name.rsplit("}", 1)[-1] == tag:
            yield el


def _first_metadata_text(root: ET.Element, tag: str) -> str | None:
    for el in root.iter(f"{_XHTML}{tag}"):
        if el.text and el.text.strip():
            return el.text.strip()
    for el in _iter_local(root, tag):  # tolerate un-namespaced/OPF-namespaced metadata
        if el.text and el.text.strip():
            return el.text.strip()
    return None


def _first_heading(root: ET.Element) -> str | None:
    for tag in ("h1", "h2", "h3", "title"):
        for el in root.iter(f"{_XHTML}{tag}"):
            text = "".join(el.itertext()).strip()
            if text:
                return text
    return None


def _collect_paragraphs(root: ET.Element, item: EpubSpineItem) -> None:
    para_idx = 0
    for el in root.iter():
        tag = el.tag[len(_XHTML) :] if el.tag.startswith(_XHTML) else None
        if tag not in _BLOCK_TAGS:
            continue
        text = " ".join("".join(el.itertext()).split())
        if not text:
            continue
        para_idx += 1
        item.paragraphs.append(
            EpubParagraph(
                text=text,
                index=para_idx,
                tag=tag,
                cfi=build_cfi(item.index, item.idref, para_idx),
            )
        )
