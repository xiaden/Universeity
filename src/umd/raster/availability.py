"""Raster capability disclosure: which OCR/spatial paths are active vs GATED (P3-S1).

Capability responses must disclose which raster paths (OCR engine, spatial
extraction) are active vs gated, and never report a gated enhancement as active.
The deterministic in-process reference OCR provider is always active; Tesseract
(CPU, ``pytesseract`` + system binary) is reported **configured-but-unavailable**
when the binary is absent — never active; PaddleOCR remains a named GATE. Spatial
extraction and IIIF crops are always available via the reference baseline.

This module is the single honest source the API ``/capabilities`` (and tests)
consult for the raster block (mirrors ``umd/audio/availability.py``).
"""

from __future__ import annotations

from umd.raster.ocr import PADDLE_GATE, _tesseract_available

#: The two named OCR providers with adapters (reference is the deterministic default).
REFERENCE_OCR = "umd-reference-ocr"
TESSERACT = "tesseract"


def _tesseract_gate_reason() -> str:
    """Honest, specific reason the Tesseract OCR path is unavailable."""
    try:
        import pytesseract  # noqa: F401
    except ImportError:
        return "configured-but-unavailable: pytesseract binding not installed (ocr extra)"
    import shutil

    if shutil.which("tesseract") is None:
        return "configured-but-unavailable: tesseract binary absent on PATH"
    return "configured-but-unavailable: tesseract did not validate (probe failed)"


def raster_capability_report(ocr_provider: str | None = None) -> dict[str, object]:
    """The raster capability snapshot for ``/capabilities`` (honest gates).

    ``ocr_provider`` is the *configured* engine name (``reference`` default,
    ``tesseract``, ``paddle``). The reference provider is always active; a
    configured-but-unavailable engine reports ``enabled=True, gated=True,
    active=False`` with a specific gate reason; an unselected engine reports
    ``gated`` (never active).
    """
    cfg = ocr_provider or REFERENCE_OCR
    tesseract_ready = _tesseract_available()
    tesseract = {
        "gated": not tesseract_ready,
        "enabled": cfg == TESSERACT,
        "active": tesseract_ready,
        "gate_reason": None if tesseract_ready else _tesseract_gate_reason(),
    }
    return {
        "ocr": {
            "active": REFERENCE_OCR
            if not tesseract_ready
            else (cfg if cfg != "paddle" else REFERENCE_OCR),
            "reference_provider": REFERENCE_OCR,
            "configured": cfg,
            TESSERACT: tesseract,
            "paddle": {
                "gated": True,
                "enabled": cfg == "paddle",
                "active": False,
                "gate_reason": PADDLE_GATE,
            },
        },
        "spatial": {"active": "umd-reference-spatial"},
        "crops": {"iiif": True, "bounded": True, "ocfl_derived": True},
        "observations": "candidate_kind only; face observations are never automatic identities",
        "promotion_ban": "enforced_auditable",
    }


def flatten_raster_capabilities(cap: dict[str, object]) -> dict[str, object]:
    """Merge the raster capability block into a JSON-serializable flat report."""
    out: dict[str, object] = {}
    for key, value in cap.items():
        out[key] = _jsonable(value) if isinstance(value, dict) else value
    return out


def _jsonable(value: object) -> object:
    if isinstance(value, dict):
        return {str(k): _jsonable(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_jsonable(v) for v in value]
    return value


__all__ = [
    "REFERENCE_OCR",
    "TESSERACT",
    "flatten_raster_capabilities",
    "raster_capability_report",
]
