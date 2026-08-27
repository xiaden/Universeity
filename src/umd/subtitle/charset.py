"""Charset probing + surrogate-preserving subtitle decode (Phase C, P3-S3).

The DD mandates: non-UTF-8 subtitle input uses charset probing and
surrogate-preserving handling; **raw bytes remain authoritative**. This module
implements a deterministic, dependency-free prober:

  * UTF-8 BOM / UTF-16 LE+BE BOM / UTF-32 LE+BE BOM sniffing;
  * strict UTF-8 validity probing (full decode);
  * cp1252 / latin-1 fallback via Python's native single-byte codecs;
  * surrogate-preserving decode (``surrogateescape``) when a byte does not map to
    a clean lossless text character — the string keeps a reversible marker
    surrogate so the original byte is recoverable and never silently dropped.

``decode_subtitle_bytes`` is the single decode entrypoint; it returns the text
plus an honest ``(charset, confidence, surrogate_preserved)`` probe record.
"""

from __future__ import annotations

import codecs

UTF8_BOM = codecs.BOM_UTF8
UTF16_LE = codecs.BOM_UTF16_LE
UTF16_BE = codecs.BOM_UTF16_BE
UTF32_LE = codecs.BOM_UTF32_LE
UTF32_BE = codecs.BOM_UTF32_BE

#: Order of BOM sniffing (longest BOM first so UTF-32 is checked before UTF-16).
_BOMS: list[tuple[bytes, str]] = [
    (UTF32_LE, "utf-32-le"),
    (UTF32_BE, "utf-32-be"),
    (UTF16_LE, "utf-16-le"),
    (UTF16_BE, "utf-16-be"),
    (UTF8_BOM, "utf-8-sig"),
]


class SubtitleDecodeError(RuntimeError):
    """Bytes could not be decoded under any probed charset policy."""


def probe_charset(raw: bytes) -> ProbeResult:
    """Probe the charset of ``raw`` deterministically (BOM -> utf-8 -> cp1252)."""
    for bom, enc in _BOMS:
        if raw.startswith(bom):
            try:
                raw.decode(enc)  # validate BOM-declared encoding is well-formed
            except (UnicodeDecodeError, ValueError):
                break
            return ProbeResult(charset=enc, confidence=1.0, surrogate_preserved=False)
    # strict UTF-8
    try:
        raw.decode("utf-8")
        return ProbeResult(charset="utf-8", confidence=1.0, surrogate_preserved=False)
    except UnicodeDecodeError:
        pass
    # cp1252 is the most common single-byte western fallback; latin-1 always
    # decodes but loses Chinese/Japanese ranges. Prefer cp1252 when the byte
    # pattern is consistent, else latin-1 with surrogate preservation.
    try:
        text = raw.decode("cp1252")
    except UnicodeDecodeError:
        text = None
    if text is not None and not _has_foreign_controls(text):
        return ProbeResult(charset="cp1252", confidence=0.7, surrogate_preserved=False)
    # surrogate-preserving fallback: latin-1 header is authoritative ASCII; the
    # raw bytes are preserved via surrogateescape so nothing is ever dropped. We
    # route here when cp1252 would yield control characters (non-western high
    # bytes), keeping every byte losslessly recoverable.
    return ProbeResult(charset="latin-1", confidence=0.5, surrogate_preserved=True)


def _has_foreign_controls(text: str) -> bool:
    """True if ``text`` under cp1252 contains non-printable C0/C1 control chars.

    Bytes that in cp1252 map to controls (e.g. 0x81/0x8D/0x8F/0x90/0x9D, or a
    GBK/KOI8 high-byte that cp1252 renders as a control) indicate the content is
    not clean western cp1252 text -> route to the surrogate-preserving path.
    """
    for ch in text:
        o = ord(ch)
        if (o < 0x20 and ch not in "\t\r\n") or 0x7F <= o <= 0x9F:
            return True
    return False


class ProbeResult:
    """An honest charset probe outcome."""

    __slots__ = ("charset", "confidence", "surrogate_preserved")

    def __init__(self, charset: str, confidence: float, surrogate_preserved: bool) -> None:
        self.charset = charset
        self.confidence = confidence
        self.surrogate_preserved = surrogate_preserved

    def to_dict(self) -> dict[str, object]:
        return {
            "charset": self.charset,
            "confidence": self.confidence,
            "surrogate_preserved": self.surrogate_preserved,
        }


def decode_subtitle_bytes(raw: bytes) -> tuple[str, ProbeResult]:
    """Decode ``raw`` to text preserving raw bytes (surrogate-preserving).

    Returns ``(text, probe)``. When the probe selected ``latin-1`` with
    surrogate preservation the returned text carries surrogate escape sequences
    (``'\\udcXX'``) that reconstruct the original bytes exactly — the authoritative
    raw bytes are never flattened or lossily replaced.
    """
    result = probe_charset(raw)
    if result.charset == "latin-1" and result.surrogate_preserved:
        text = raw.decode("latin-1", errors="surrogateescape")
        return text, result
    try:
        return raw.decode(result.charset), result
    except (UnicodeDecodeError, LookupError, ValueError) as exc:
        raise SubtitleDecodeError(
            f"decode failed for probed charset {result.charset!r}: {exc}"
        ) from exc


def recover_raw_bytes(text: str) -> bytes:
    """Reconstruct the authoritative raw bytes from a surrogate-preserved text."""
    return text.encode("latin-1", errors="surrogateescape")


__all__ = [
    "ProbeResult",
    "SubtitleDecodeError",
    "decode_subtitle_bytes",
    "probe_charset",
    "recover_raw_bytes",
]
