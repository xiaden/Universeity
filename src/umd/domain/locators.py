"""Canonical ``source://`` locator parsing/serialization (Phase 2 / P2-S2).

Grammar:

    source://<work-or-source-id>/<modality>/<deterministic-segment-id>
            @v<segmenter>.<decoder>.<renderer>
            ?frag=<selector>

* The version tag is derived from ``segmenter.decoder.renderer`` — a newer
  toolchain produces a new version, and old ``@v...`` locators stay addressable.
* ``frag`` is a modality-native physical selector (IIIF xywh/pct, EPUB CFI,
  Media Fragments t=/track=, or a structural/text-location selector).
* A *byte-offset-only* locator is rejected: raw ``bytes=`` ranges may only ever
  augment structural/selector positions, never stand alone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum

from pydantic import BaseModel, Field, field_validator, model_validator

from umd.domain.ids import deterministic_segment_id, is_url_safe

SCHEME = "source"

_MAX_MODALITY = 32
_MAX_ID = 256


class LocatorError(ValueError):
    """Raised when a locator cannot be parsed or is invalid."""


class ByteOffsetLocatorError(LocatorError):
    """Raised for byte-offset-only locators (forbidden by contract)."""


# ---------------------------------------------------------------------------
# Versioning
# ---------------------------------------------------------------------------


@dataclass(frozen=True, order=True)
class PipelineVersion:
    """A locator version derived from segmenter.decoder.renderer.

    ``version`` is the registration ordinal used for *newest-compatible*
    precedence during bare resolution; the ``tag`` is the canonical serialization.
    """

    segmenter: str
    decoder: str
    renderer: str
    version: int = 0

    def __post_init__(self) -> None:
        for field in (self.segmenter, self.decoder, self.renderer):
            if not field or "/" in field or "?" in field or "#" in field or "@" in field:
                raise LocatorError(f"invalid pipeline version component {field!r}")

    @property
    def tag(self) -> str:
        return f"v{self.segmenter}.{self.decoder}.{self.renderer}"

    @classmethod
    def from_tag(cls, tag: str, version: int = 0) -> PipelineVersion:
        m = re.fullmatch(r"v([^.\s?@#]+)\.([^.\s?@#]+)\.([^.\s?@#]+)", tag)
        if not m:
            raise LocatorError(f"invalid version tag {tag!r}")
        return cls(segmenter=m.group(1), decoder=m.group(2), renderer=m.group(3), version=version)


# ---------------------------------------------------------------------------
# Modality-native selectors
# ---------------------------------------------------------------------------


class SelectorKind(StrEnum):
    IIIF = "iiif"
    EPUB_CFI = "epubcfi"
    MEDIA_FRAGMENTS = "media_fragments"
    STRUCTURAL = "structural"
    BYTE_OFFSET = "byte_offset"


_IIIF_XYWH = re.compile(r"^\d+,\d+,\d+,\d+$")
_IIIF_PCT = re.compile(r"^pct:\d+([.,]\d+)?,\d+([.,]\d+)?,\d+([.,]\d+)?,\d+([.,]\d+)?$")
_MF_T = re.compile(r"^\d+((\.\d+)?,)?\d*(\.\d+)?$")
_STRUCTURAL = re.compile(r"^[/a-z0-9_.-]+$")


class Selector(BaseModel):
    """Base type for a canonical ``frag`` selector. Subclasses add fields."""

    kind: SelectorKind

    def to_frag(self) -> str:
        raise NotImplementedError

    @classmethod
    def from_frag(cls, raw: str) -> Selector:
        return parse_selector(raw)


class IIIFSelector(Selector):
    """IIIF image region selector (``xywh=x,y,w,h`` or ``pct=...``)."""

    kind: SelectorKind = SelectorKind.IIIF
    region: str = Field(max_length=128)

    @field_validator("region")
    @classmethod
    def _valid_region(cls, v: str) -> str:
        if not (_IIIF_XYWH.match(v) or _IIIF_PCT.match(v)):
            raise LocatorError(f"invalid IIIF region {v!r}")
        return v

    def to_frag(self) -> str:
        return self.region


class CfiSelector(Selector):
    """EPUB CFI locator (``epubcfi(...)``)."""

    kind: SelectorKind = SelectorKind.EPUB_CFI
    cfi: str = Field(max_length=512)

    @field_validator("cfi")
    @classmethod
    def _valid_cfi(cls, v: str) -> str:
        if not (v.startswith("epubcfi(") and v.endswith(")")):
            raise LocatorError(f"invalid EPUB CFI {v!r}")
        return v

    def to_frag(self) -> str:
        return self.cfi


class MediaFragmentSelector(Selector):
    """Media Fragments-compatible selector: ``t=start,end`` + optional track/spatial.

    Time is *time*, never a byte offset. At least one of t/track/spatial must be
    present.
    """

    kind: SelectorKind = SelectorKind.MEDIA_FRAGMENTS
    t: str | None = Field(default=None, max_length=64)
    track: str | None = Field(default=None, max_length=128)
    spatial: str | None = Field(default=None, max_length=128)

    @field_validator("t")
    @classmethod
    def _valid_t(cls, v: str | None) -> str | None:
        if v is not None and not _MF_T.match(v):
            raise LocatorError(f"invalid Media Fragments t={v!r}")
        return v

    @model_validator(mode="after")
    def _at_least_one(self) -> MediaFragmentSelector:
        if not any((self.t, self.track, self.spatial)):
            raise LocatorError("Media Fragment must specify at least one of t=, track=, spatial=")
        return self

    def to_frag(self) -> str:
        parts = []
        if self.t:
            parts.append(f"t={self.t}")
        if self.track:
            parts.append(f"track={self.track}")
        if self.spatial:
            parts.append(f"spatial={self.spatial}")
        return "&".join(parts)


class StructuralSelector(Selector):
    """Structural/text-location selector (e.g. ``paragraph/18/sentence/3``)."""

    kind: SelectorKind = SelectorKind.STRUCTURAL
    path: str = Field(max_length=512)

    @field_validator("path")
    @classmethod
    def _valid_path(cls, v: str) -> str:
        p = v.strip("/")
        if not p or not _STRUCTURAL.match(p):
            raise LocatorError(f"invalid structural selector {v!r}")
        return p

    def to_frag(self) -> str:
        return self.path


class ByteOffsetSelector(Selector):
    """A raw byte range. NEVER sufficient on its own (rejected as sole locator)."""

    kind: SelectorKind = SelectorKind.BYTE_OFFSET
    start: int = Field(ge=0)
    end: int = Field(ge=0)

    @model_validator(mode="after")
    def _sane(self) -> ByteOffsetSelector:
        if self.end < self.start:
            raise LocatorError("byte offset end < start")
        return self

    def to_frag(self) -> str:
        return f"bytes={self.start}-{self.end}"


def parse_selector(raw: str) -> Selector:
    """Parse a ``frag`` value into a typed :class:`Selector`."""
    if not raw:
        raise LocatorError("empty selector")
    if raw.startswith("epubcfi("):
        return CfiSelector(cfi=raw)
    if raw.startswith("bytes="):
        m = re.fullmatch(r"bytes=(\d+)-(\d+)", raw)
        if not m:
            raise LocatorError(f"invalid byte-offset selector {raw!r}")
        return ByteOffsetSelector(start=int(m.group(1)), end=int(m.group(2)))
    if "&" in raw or raw.startswith("t=") or raw.startswith("track=") or raw.startswith("spatial="):
        # Media Fragments style
        t = track = spatial = None
        for part in raw.split("&"):
            if part.startswith("t="):
                t = part[2:]
            elif part.startswith("track="):
                track = part[6:]
            elif part.startswith("spatial="):
                spatial = part[8:]
            else:
                raise LocatorError(f"unknown selector parameter {part!r}")
        return MediaFragmentSelector(t=t, track=track, spatial=spatial)
    if _IIIF_XYWH.match(raw) or _IIIF_PCT.match(raw):
        return IIIFSelector(region=raw)
    if _STRUCTURAL.match(raw.strip("/")) and raw.strip("/"):
        return StructuralSelector(path=raw)
    raise LocatorError(f"unrecognized selector {raw!r}")


# ---------------------------------------------------------------------------
# Canonical locator
# ---------------------------------------------------------------------------


class Locator(BaseModel):
    """Canonical ``source://`` locator."""

    scheme: str = SCHEME
    source_id: str = Field(max_length=_MAX_ID)
    modality: str = Field(max_length=_MAX_MODALITY)
    segment: str = Field(max_length=512)
    version: PipelineVersion | None = None
    frag: Selector | None = None

    @field_validator("scheme")
    @classmethod
    def _scheme(cls, v: str) -> str:
        if v != SCHEME:
            raise LocatorError(f"unsupported scheme {v!r}")
        return v

    @field_validator("modality")
    @classmethod
    def _modality(cls, v: str) -> str:
        v = v.strip().lower()
        if not v or not re.fullmatch(r"[a-z0-9_-]+", v):
            raise LocatorError(f"invalid modality {v!r}")
        return v

    @field_validator("segment")
    @classmethod
    def _segment(cls, v: str) -> str:
        if not v or not is_url_safe(v):
            raise LocatorError(f"segment id must be URL-safe, got {v!r}")
        return v

    @model_validator(mode="after")
    def _reject_byte_offset_only(self) -> Locator:
        # Deterministic segment ids are structural hashes, never byte offsets; a
        # locator whose only selector is a byte range is rejected outright
        # (carry-forward invariant: byte-offset-only locators are forbidden).
        if isinstance(self.frag, ByteOffsetSelector):
            raise ByteOffsetLocatorError(f"byte-offset-only locator rejected: {self.canonical()!r}")
        return self

    def canonical(self) -> str:
        """Serialize to the canonical ``source://`` string form."""
        out = f"{SCHEME}://{self.source_id}/{self.modality}/{self.segment}"
        if self.version is not None:
            out += f"@{self.version.tag}"
        if self.frag is not None:
            out += f"?frag={self.frag.to_frag()}"
        return out

    def without_version(self) -> Locator:
        """Bare form (no version tag) — resolves newest compatible."""
        return self.model_copy(update={"version": None})

    @property
    def is_bare(self) -> bool:
        return self.version is None


def parse_locator(locator: str) -> Locator:
    """Parse a canonical ``source://`` locator string into a :class:`Locator`."""
    if not locator.startswith(f"{SCHEME}://"):
        raise LocatorError(f"not a {SCHEME}:// locator: {locator!r}")
    rest = locator[len(f"{SCHEME}://") :]

    frag: str | None = None
    if "?frag=" in rest:
        rest, frag = rest.split("?frag=", 1)

    version: PipelineVersion | None = None
    if "@v" in rest:
        rest, tag = rest.split("@", 1)
        version = PipelineVersion.from_tag(tag)

    parts = rest.split("/")
    if len(parts) < 3:
        raise LocatorError(f"locator {locator!r} is missing id/modality/segment")
    source_id, modality, segment = parts[0], parts[1], "/".join(parts[2:])
    if not source_id or not modality or not segment:
        raise LocatorError(f"empty component in {locator!r}")

    selector = parse_selector(frag) if frag is not None else None
    return Locator(
        source_id=source_id,
        modality=modality,
        segment=segment,
        version=version,
        frag=selector,
    )


def build_locator(
    source_id: str,
    modality: str,
    structural_path: str,
    canonical_identity: str,
    version: PipelineVersion | None = None,
    frag: Selector | None = None,
) -> Locator:
    """Build a canonical locator with a deterministic segment id."""
    seg_id = deterministic_segment_id(canonical_identity, modality, structural_path)
    # Preserve readability of the structural path inside the URL-safe segment id
    # boundary while keeping the DB deterministic_key hash-anchored.
    return Locator(
        source_id=source_id,
        modality=modality,
        segment=seg_id,
        version=version,
        frag=frag,
    )
