"""Confidence-bearing spatial/object/face candidate observations (Phase B, P3-S3).

A deterministic, in-process spatial extractor over Pillow (no OpenCV/model):

  * **layout observations** — page regions and panels with deterministic ordering
    and confidence (bounded baseline the DD pre-approves).
  * **candidate object/person/face observations** — deterministic color/shape
    heuristics over the actual pixels produce *candidate observations* keyed by
    `candidate_kind`. These are **never promoted to canonical identity**: a face
    candidate is evidence (an observation someone *may* be pictured), not a claim
    that a canonical entity is present (Task §29, DD raster contract).
  * **interpretation descriptions** — a *model* concern. The deterministic
    provider emits none; an optional (gated) model interpreter writes
    descriptions as interpretation events with input locators and generated-by.

The provider that ran is reported in ``generated-by``/``generated_by`` metadata.
"""

from __future__ import annotations

from abc import abstractmethod
from typing import Any, Protocol

from pydantic import BaseModel, Field

from umd.raster.bounds import RasterLimits, decode_bounded
from umd.raster.regions import detect_panels, find_ink_regions

#: Gate note for the optional model/OpenCV interpretation path (Plan C contours).
MODEL_GATE = (
    "Descriptions of regions (model interpretations) require an LLM/VLM provider "
    "which is out of scope (Plan C). The deterministic extractor emits layout + "
    "candidate observations only; descriptions are interpretation events surfaced "
    "only when a provider is present (none here)."
)


class SpatialObservation(BaseModel):
    """A deterministic layout observation (panel/region) with reading order."""

    kind: str  # "panel" | "region"
    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    confidence: float = Field(ge=0.0, le=1.0)
    reading_order: int = Field(ge=1)
    color: tuple[int, int, int] | None = None
    generated_by: dict[str, Any] = Field(default_factory=dict)

    @property
    def xywh(self) -> str:
        return f"{self.x},{self.y},{self.width},{self.height}"


class CandidateObservation(BaseModel):
    """A candidate object/person/face observation (evidence, NEVER canonical)."""

    kind: str  # "object" | "person" | "face"
    candidate_kind: str = "observation"
    box: tuple[int, int, int, int]  # (x, y, w, h)
    confidence: float = Field(ge=0.0, le=1.0)
    note: str = ""
    generated_by: dict[str, Any] = Field(default_factory=dict)

    @property
    def xywh(self) -> str:
        x, y, w, h = self.box
        return f"{x},{y},{w},{h}"


class InterpretationEvent(BaseModel):
    """A model description of an input region (interpretation event, Plan C gated)."""

    region_xywh: str
    description: str
    confidence: float = Field(ge=0.0, le=1.0)
    input_locators: list[str] = Field(default_factory=list)
    generated_by: dict[str, Any] = Field(default_factory=dict)


class SpatialResult(BaseModel):
    """Deterministic spatial output: observations + candidate observations."""

    provider: str
    provider_version: str
    observations: list[SpatialObservation] = Field(default_factory=list)
    candidates: list[CandidateObservation] = Field(default_factory=list)
    descriptions: list[InterpretationEvent] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def generated_by(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "provider_version": self.provider_version,
        }


class SpatialProvider(Protocol):
    """Deterministic spatial extraction contract (provider substitution friendly)."""

    name: str
    version: str

    @abstractmethod
    def extract(self, raw: bytes, *, panel_min_area: int = 1200) -> SpatialResult: ...


def _skin_tone_like(color: tuple[int, int, int]) -> bool:
    r, g, b = color
    return r > 60 and r > g > b and (r - b) > 20


class ReferenceSpatialProvider:
    """Deterministic spatial extractor over Pillow.

    Detects panels (solid-color components distinct from the page background) and
    ink regions, emits layout observations with reading order, and derives
    *candidate* object/person/face observations from deterministic color/shape
    heuristics. Face/person/object observations are candidates only and are never
    promoted to canonical identity.
    """

    name = "umd-reference-spatial"
    version = "1.0"

    def extract(self, raw: bytes, *, panel_min_area: int = 1200) -> SpatialResult:
        with decode_bounded(raw, RasterLimits()) as image:
            panels = detect_panels(image, min_fill=panel_min_area)
            inks = find_ink_regions(image)

        observations: list[SpatialObservation] = []
        for p in panels:
            observations.append(
                SpatialObservation(
                    kind="panel",
                    x=p.box.x,
                    y=p.box.y,
                    width=p.box.w,
                    height=p.box.h,
                    confidence=0.7,  # deterministic baseline confidence
                    reading_order=p.reading_order,
                    color=p.color,
                    generated_by=self.generated_by,
                )
            )
        for ink in inks:
            observations.append(
                SpatialObservation(
                    kind="region",
                    x=ink.box.x,
                    y=ink.box.y,
                    width=ink.box.w,
                    height=ink.box.h,
                    confidence=0.6,
                    reading_order=ink.reading_order,
                    generated_by=self.generated_by,
                )
            )

        candidates: list[CandidateObservation] = []
        for p in panels:
            color = p.color or (0, 0, 0)
            aspect = p.box.w / max(1, p.box.h)
            if _skin_tone_like(color) and 0.6 <= aspect <= 1.6:
                candidates.append(
                    CandidateObservation(
                        kind="face",
                        box=(p.box.x, p.box.y, p.box.w, p.box.h),
                        confidence=0.4,  # heuristic, low — a candidate, not identity
                        note="deterministic skin-tone/shape heuristic; candidate, never identity",
                        generated_by=self.generated_by,
                    )
                )
            else:
                candidates.append(
                    CandidateObservation(
                        kind="object",
                        box=(p.box.x, p.box.y, p.box.w, p.box.h),
                        confidence=0.5,
                        note="deterministic panel/region heuristic; candidate observation",
                        generated_by=self.generated_by,
                    )
                )

        return SpatialResult(
            provider=self.name,
            provider_version=self.version,
            observations=observations,
            candidates=candidates,
            warnings=[MODEL_GATE],
        )

    @property
    def generated_by(self) -> dict[str, Any]:
        return {"provider": self.name, "provider_version": self.version}


SPATIAL_PROVIDERS: dict[str, type[SpatialProvider]] = {
    "reference": ReferenceSpatialProvider,
}


def run_spatial(
    raw: bytes, provider: str = "reference", *, panel_min_area: int = 1200
) -> SpatialResult:
    impl = SPATIAL_PROVIDERS[provider]()
    return impl.extract(raw, panel_min_area=panel_min_area)
