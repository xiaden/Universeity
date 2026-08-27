"""Deterministic TXT decoding and normalization (Phase B, P2-S1).

Raw input bytes are ALWAYS authoritative (OCFL). This module produces a
deterministic *normalized* text representation:

  * UTF-8 with BOM handling — a leading UTF-8 (or UTF-16/32) BOM is stripped and
    recorded as a normalization step; undecodable bytes are replaced (surrogate
    preserving is not required for the plain-text baseline);
  * line endings are normalized to ``\\n`` so the same logical text yields the
    same segment structure on every platform/decoder;
  * the raw bytes and byte length are retained alongside the normalized text so
    evidence always links back to the immutable source.

Pure stdlib, deterministic, no subprocess dependency.
"""

from __future__ import annotations

import codecs
from dataclasses import dataclass, field
from typing import Any

from umd.domain.ids import sha512_b32url


@dataclass
class NormalizedText:
    """Output of text decode/normalization."""

    text: str
    encoding: str
    bom_stripped: bool = False
    newline_normalized: bool = False
    raw_size_bytes: int = 0
    raw_sha512: str | None = None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "encoding": self.encoding,
            "bom_stripped": self.bom_stripped,
            "newline_normalized": self.newline_normalized,
            "raw_size_bytes": self.raw_size_bytes,
            "raw_sha512": self.raw_sha512,
            "warnings": self.warnings,
        }


#: Canonical BOM prefixes -> (codec, encoding name) for detection.
_BOMS: list[tuple[bytes, str]] = [
    (codecs.BOM_UTF32_LE, "utf-32-le"),
    (codecs.BOM_UTF32_BE, "utf-32-be"),
    (codecs.BOM_UTF8, "utf-8"),
    (codecs.BOM_UTF16_LE, "utf-16-le"),
    (codecs.BOM_UTF16_BE, "utf-16-be"),
]


def normalize_txt(raw: bytes, *, encoding: str | None = None) -> NormalizedText:
    """Decode ``raw`` deterministically and normalize line endings.

    :param raw: the immutable source bytes (authoritative).
    :param encoding: optional forced codec; otherwise BOM-sniffed, defaulting to
        UTF-8 with error replacement (never a decode crash on arbitrary bytes).
    """
    bom_stripped = False
    detected = encoding
    body = raw

    if encoding is None:
        for bom, codec_name in _BOMS:
            if raw.startswith(bom):
                detected = codec_name
                body = raw[len(bom) :]
                bom_stripped = True
                break

    codec = detected or "utf-8"
    text = body.decode(codec, errors="replace")
    had_crlf = "\r\n" in text or ("\r" in text and "\n" in text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return NormalizedText(
        text=text,
        encoding=codec,
        bom_stripped=bom_stripped,
        newline_normalized=had_crlf,
        raw_size_bytes=len(raw),
        raw_sha512=sha512_b32url(raw),
    )
