"""Provider-adapted OCR with reading order and evidence (Phase B, P3-S2).

Implements an :class:`OcrProvider` contract and three adapters:

  * **ReferenceOcrProvider** — deterministic, in-process, rule-based provider that
    template-matches the shared monochrome glyph renderer against the image's own
    pixels (see :mod:`umd.raster.textimg`). It makes the fixture-contract tests
    hermetic and deterministic and never fabricates text for an image it did not
    actually process.
  * **TesseractOcrProvider** — the CPU/clean-text alternative via ``pytesseract``
    (requires the system ``tesseract-ocr`` binary). Imported lazily; raises
    :class:`OcrProviderUnavailable` when the binding/binary is absent.
  * **PaddleOcrProvider** — the preferred scene/CJK/vertical path. **GATED**: the
    heavy ``paddlepaddle``/``paddleocr`` stack is deliberately not installed; the
    adapter is written to the same contract and raises
    :class:`OcrProviderUnavailable` with the gate reason until the build gates
    are satisfied (recorded in the P3-S2 annotation).

OCR output is **evidence** only — regions/text/confidence/reading order with
source locators; it is never promoted to canonical identity. The provider that
ran is reported in ``generated-by`` metadata.
"""

from __future__ import annotations

from abc import abstractmethod
from dataclasses import dataclass
from typing import Any, Protocol, cast

from pydantic import BaseModel, Field

from umd.raster.bounds import RasterLimits, decode_bounded

#: Gate reason for the PaddleOCR adapter (heavy dependency; not force-installed).
PADDLE_GATE = (
    "paddlepaddle/paddleocr are heavy CPython/CUDA-capable deps; adapter is "
    "written to the OcrProvider contract but GATED (not installed) until build/"
    "license/CVE gates pass (P3-S2)."
)


class OcrError(RuntimeError):
    """An OCR provider failed or is unavailable."""


class OcrProviderUnavailable(OcrError):  # noqa: N818 - stable public name used widely
    """The provider is gated/unavailable in this environment (a documented gate)."""


@dataclass(frozen=True)
class OcrConfig:
    """Per-run OCR configuration (bounded)."""

    language: str = "eng"
    max_regions: int = 64
    min_confidence: float = 0.0


class OcrRegion(BaseModel):
    """One recognized text region with a source locator and reading order."""

    x: int = Field(ge=0)
    y: int = Field(ge=0)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    text: str = ""
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    reading_order: int = Field(ge=1)
    language: str = "eng"

    @property
    def xywh(self) -> str:
        return f"{self.x},{self.y},{self.width},{self.height}"


class OcrResult(BaseModel):
    """Structured OCR output; each region is evidence with exact provenance."""

    provider: str
    provider_version: str
    language: str
    regions: list[OcrRegion] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @property
    def generated_by(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "provider_version": self.provider_version,
            "language": self.language,
        }


class OcrProvider(Protocol):
    """The binding provider-adapted OCR contract.

    Substitution tests use the SAME fixture and contract: every provider accepts
    the same raw image bytes and returns the same :class:`OcrResult` shape
    (bounded regions with xywh boxes, confidence, reading order, generated-by
    provider). No provider writes semantic state directly.
    """

    name: str
    version: str

    @abstractmethod
    def ocr(self, raw: bytes, config: OcrConfig | None = None) -> OcrResult: ...


# ---------------------------------------------------------------------------
# Reference provider (deterministic, in-process, rule-based)
# ---------------------------------------------------------------------------


class ReferenceOcrProvider:
    """Deterministic in-process OCR: template-matches rendered glyph patterns.

    Reads the image's pixels (via :func:`umd.raster.regions.find_ink_regions`),
    crops each ink region, and matches it against the shared monochrome word
    patterns. Confidence = the best overlap ratio. Purely deterministic.
    """

    name = "umd-reference-ocr"
    version = "1.0"

    def __init__(self) -> None:
        from umd.raster import textimg  # local: keep import graph light

        self._patterns = [textimg.render_word(word) for word in textimg.REFERENCE_WORDS]

    def ocr(self, raw: bytes, config: OcrConfig | None = None) -> OcrResult:
        config = config or OcrConfig()
        from umd.raster.regions import find_ink_regions
        from umd.raster.textimg import binarize_pattern

        results: list[OcrRegion] = []
        with decode_bounded(raw) as image:
            regions = find_ink_regions(image)
            # Crop each detected ink region from the page and match against patterns.
            for region in regions[: config.max_regions]:
                box = region.box
                crop = image.img.crop((box.x, box.y, box.x + box.w, box.y + box.h))
                mask = binarize_pattern(crop)
                text, conf = self._match(mask)
                if text is None or conf < config.min_confidence:
                    continue
                results.append(
                    OcrRegion(
                        x=box.x,
                        y=box.y,
                        width=box.w,
                        height=box.h,
                        text=text,
                        confidence=round(conf, 4),
                        reading_order=region.reading_order,
                        language=config.language,
                    )
                )
        return OcrResult(
            provider=self.name,
            provider_version=self.version,
            language=config.language,
            regions=results,
        )

    def _match(self, mask: list[list[bool]]) -> tuple[str | None, float]:
        """Best dictionary-word match for a binarized ink region (deterministic)."""
        if not mask:
            return None, 0.0
        dark = sum(1 for row in mask for cell in row if cell)
        if dark == 0:
            return None, 0.0
        best_text: str | None = None
        best_conf = 0.0
        for pattern in self._patterns:
            pmask = pattern.image.convert("L").load()
            assert pmask is not None  # noqa: S101 - mypy narrowing on open PIL image
            pw, ph = pattern.image.size
            mh = len(mask)
            mw = len(mask[0]) if mh else 0
            # overlap computed on the intersection box (deterministic)
            iw = min(mw, pw)
            ih = min(mh, ph)
            if iw <= 0 or ih <= 0:
                continue
            match = 0
            total = 0
            for y in range(ih):
                for x in range(iw):
                    total += 1
                    if mask[y][x] == (cast(int, pmask[x, y]) < 128):
                        match += 1
            conf = match / total
            if conf > best_conf:
                best_conf = conf
                best_text = pattern.text
        if best_conf >= 0.9:
            return best_text, best_conf
        return None, best_conf


# ---------------------------------------------------------------------------
# Tesseract
# ---------------------------------------------------------------------------


def _tesseract_available() -> bool:
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return False
    import shutil
    import subprocess

    exe = shutil.which("tesseract")
    if not exe:
        return False
    try:
        result = subprocess.run(  # noqa: S603 - fixed allowlisted binary resolved via which
            [exe, "--version"],
            capture_output=True,
            timeout=10,
            check=False,
        )
        return result.returncode == 0
    except Exception:  # noqa: BLE001
        return False


class TesseractOcrProvider:
    """CPU Tesseract adapter over ``pytesseract`` (boundary-gated import)."""

    name = "umd-tesseract"
    version = "tesseract-5"

    def ocr(self, raw: bytes, config: OcrConfig | None = None) -> OcrResult:
        config = config or OcrConfig()
        try:
            import pytesseract
        except ImportError as exc:  # pragma: no cover - env-dependent
            raise OcrProviderUnavailable("pytesseract not installed (ocr extra)") from exc
        if not _tesseract_available():
            raise OcrProviderUnavailable("tesseract binary not found on PATH")

        with decode_bounded(raw, RasterLimits()) as image:
            data = pytesseract.image_to_data(
                image.img,
                lang=config.language,
                output_type=pytesseract.Output.DICT,
            )
        words: list[tuple[int, int, int, int, str, float]] = []
        n = len(data.get("text", []))
        for i in range(n):
            text = (data.get("text") or [""] * n)[i].strip()
            conf = int((data.get("conf") or ["-1"] * n)[i])
            if not text or conf < 0:
                continue
            left = int((data.get("left") or [0] * n)[i])
            top = int((data.get("top") or [0] * n)[i])
            wdt = int((data.get("width") or [0] * n)[i])
            hgt = int((data.get("height") or [0] * n)[i])
            words.append((left, top, wdt, hgt, text, conf / 100.0))
        words.sort(key=lambda w: (w[1], w[0]))  # deterministic reading order
        regions = [
            OcrRegion(
                x=w[0],
                y=w[1],
                width=w[2],
                height=w[3],
                text=w[4],
                confidence=round(w[5], 4),
                reading_order=i,
                language=config.language,
            )
            for i, w in enumerate(words[: config.max_regions], start=1)
        ]
        return OcrResult(
            provider=self.name,
            provider_version=self.version,
            language=config.language,
            regions=regions,
        )


# ---------------------------------------------------------------------------
# PaddleOCR (preferred scene/CJK/vertical) — GATED
# ---------------------------------------------------------------------------


class PaddleOcrProvider:
    """PaddleOCR adapter written to the contract but GATED (not installed)."""

    name = "umd-paddleocr"
    version = "gated"

    def ocr(self, raw: bytes, config: OcrConfig | None = None) -> OcrResult:  # noqa: ARG002 - gated provider uses neither
        raise OcrProviderUnavailable(PADDLE_GATE)


#: Built-in providers by routing name (deterministic dispatch table).
PROVIDERS: dict[str, type[OcrProvider]] = {
    "reference": ReferenceOcrProvider,
    "tesseract": TesseractOcrProvider,
    "paddle": PaddleOcrProvider,
}


def run_ocr(raw: bytes, provider: str = "reference", config: OcrConfig | None = None) -> OcrResult:
    """Run OCR with a named provider; the reference provider is the deterministic default."""
    try:
        impl = PROVIDERS[provider]()
    except KeyError as exc:  # pragma: no cover - defensive
        raise OcrError(f"unknown OCR provider {provider!r}") from exc
    return impl.ocr(raw, config)
