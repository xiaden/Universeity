"""Subtitle capability disclosure (Phase C, P3-S3).

Discloses which subtitle paths are active vs gated: the formats pysubs2
(plus the WebVTT pre-normalizer) can parse as a real, unlocked capability; heavy
text/vision subtitle engines (OCR bitmap / VobSub decoding) are GATED/absent and
reported honestly — never fabricated as active.
"""

from __future__ import annotations

from umd.subtitle.formats import SUPPORTED_FORMATS


def subtitle_capability_report() -> dict[str, object]:
    """The subtitle capability snapshot for ``/capabilities`` (honest gates)."""
    return {
        "parser": "pysubs2",
        "pysubs2_version": _pysubs2_version(),
        "webvtt_pre_normalizer": {
            "active": True,
            "x_timestamp_map": "X-TIMESTAMP-MAP=LOCAL:...,MPEGTS:N -> shift = N/90000 - LOCAL",
            "header_stripped": True,
            "transformation_recorded": True,
        },
        "charset_probing": {
            "active": True,
            "surrogate_preserving": True,
            "raw_bytes_authoritative": True,
        },
        "formats": {name: info["kind"] for name, info in SUPPORTED_FORMATS.items()},
        "embedded_extraction": {"active": True, "track_independent_sources": True},
        "bitmap_vobsub_ocr": {"gated": True, "active": False},
        "promotion_ban": "enforced_auditable",
    }


def _pysubs2_version() -> str:
    try:
        import pysubs2

        return getattr(pysubs2, "VERSION", "unknown")
    except ImportError:  # pragma: no cover - requires deps
        return "unknown"


__all__ = ["subtitle_capability_report"]
