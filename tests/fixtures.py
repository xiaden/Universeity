"""Deterministic small media fixtures for Phase-2 integration tests.

Generated from source strings (no committed binaries) so identical inputs always
produce identical bytes, which is what deterministic segment/deterministic-key
tests need. TXT/Markdown are plain text; the EPUB is built with stdlib ``zipfile``;
the PDFs are assembled by hand with correct xref offsets.
"""

from __future__ import annotations

import io
import os
import shutil
import struct
import subprocess
import tarfile
import tempfile
import zipfile
import zlib

from PIL import Image, ImageDraw

from umd.audio import tone
from umd.raster.textimg import draw_text_line

# ---------------------------------------------------------------------------
# TXT
# ---------------------------------------------------------------------------

FIXTURE_TXT = (
    "Chapter 1\n"
    "\n"
    "Alice walked into the garden. She saw the White Rabbit.\n"
    "\n"
    '"Hello," said Alice. "Where are you going?"\n'
    "\n"
    "The White Rabbit looked at his pocket watch and hurried away.\n"
)

FIXTURE_TXT_BOM = "\ufeff" + FIXTURE_TXT  # leading UTF-8 BOM


def txt_bytes(bom: bool = False) -> bytes:
    return FIXTURE_TXT_BOM.encode("utf-8") if bom else FIXTURE_TXT.encode("utf-8")


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

FIXTURE_MARKDOWN = (
    "# The Garden\n"
    "\n"
    "## Meeting\n"
    "\n"
    "Alice met the White Rabbit in the garden.\n"
    "\n"
    '!["panel one"](img/panel1.png)\n'
    "\n"
    "## Farewell\n"
    "\n"
    '"Goodbye," said Alice, waving.\n'
)

FIXTURE_MARKDOWN_IMAGE_ONLY = "![panel one](img/panel1.png)\n"


def markdown_bytes(image_only: bool = False) -> bytes:
    src = FIXTURE_MARKDOWN_IMAGE_ONLY if image_only else FIXTURE_MARKDOWN
    return src.encode("utf-8")


# ---------------------------------------------------------------------------
# EPUB (stdlib zipfile; deterministic)
# ---------------------------------------------------------------------------


def _epub_xhtml(title: str, paras: list[str], imagelink: bool = False) -> bytes:
    body = "".join(f"<p>{p}</p>" for p in paras)
    img = '<p><img src="img/page1.png" alt="panel one"/></p>' if imagelink else ""
    return (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<html xmlns="http://www.w3.org/1999/xhtml"><head><title>{title}</title></head>'
        f"<body><h1>{title}</h1>{img}{body}</body></html>"
    ).encode()


def epub_bytes(dialogue: bool = True) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr(
            "META-INF/container.xml",
            '<?xml version="1.0"?><container version="1.0" '
            'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">'
            '<rootfiles><rootfile full-path="OEBPS/content.opf" '
            'media-type="application/oebps-package+xml"/></rootfiles></container>',
        )
        paras = (
            ['"Hello," said Alice. "Where are you going?"', "The White Rabbit hurried away."]
            if dialogue
            else ["Alice walked into the garden.", "She saw the White Rabbit."]
        )
        z.writestr(
            "OEBPS/content.opf",
            '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" '
            'version="2.0" unique-identifier="uid"><metadata '
            'xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>The Garden</dc:title>'
            "<dc:language>en</dc:language></metadata><manifest>"
            '<item id="c1" href="chap1.xhtml" media-type="application/xhtml+xml"/>'
            '<item id="img1" href="img/page1.png" media-type="image/png"/>'
            '</manifest><spine><itemref idref="c1"/></spine></package>',
        )
        z.writestr("OEBPS/chap1.xhtml", _epub_xhtml("Chapter One", paras, imagelink=True))
        z.writestr("OEBPS/img/page1.png", b"\x89PNG\r\n\x1a\nfixture")
    return buf.getvalue()


def malformed_epub_bytes() -> bytes:
    """A ZIP that is not a valid EPUB (no mimetype/container) — deterministic."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("OEBPS/some.xhtml", "<html></html>")
    return buf.getvalue()


# ---------------------------------------------------------------------------
# PDF (hand-assembled; correct xref offsets)
# ---------------------------------------------------------------------------

_HEADER = b"%PDF-1.4\n"


def _write_pdf(objects: list[bytes]) -> bytes:
    """Assemble direct PDF objects with a correct, header-relative xref table.

    Object offsets and the ``startxref`` pointer are absolute byte positions from
    the start of the file, so every offset is shifted by ``len(_HEADER)``.
    """
    header_len = len(_HEADER)
    body = bytearray()
    offsets: list[int] = []
    for obj in objects:
        offsets.append(header_len + len(body))
        body += obj
    xref_offset = header_len + len(body)
    xref = bytearray(f"xref\n0 {len(objects) + 1}\n".encode("ascii"))
    xref += b"0000000000 65535 f \n"
    for off in offsets:
        xref += f"{off:010d} 00000 n \n".encode("ascii")
    trailer = (
        f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R >>\nstartxref\n{xref_offset}\n%%EOF\n"
    )
    return _HEADER + bytes(body) + bytes(xref) + trailer.encode("ascii")


def pdf_text_bytes() -> bytes:
    content = b"BT /F1 12 Tf 72 720 Td (Hello from the text layer) Tj ET"
    obj1 = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    obj2 = b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    obj3 = (
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>\nendobj\n"
    )
    obj4 = b"4 0 obj\n<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>\nendobj\n"
    obj5 = (
        f"5 0 obj\n<< /Length {len(content)} >>\nstream\n".encode("ascii")
        + content
        + b"\nendstream\nendobj\n"
    )
    return _write_pdf([obj1, obj2, obj3, obj4, obj5])


def pdf_image_only_bytes() -> bytes:
    """A single-page PDF with NO text layer -> routes to raster/OCR."""
    content = b"q 1 0 0 1 0 0 cm 0 0 100 100 re f Q"
    obj1 = b"1 0 obj\n<< /Type /Catalog /Pages 2 0 R >>\nendobj\n"
    obj2 = b"2 0 obj\n<< /Type /Pages /Kids [3 0 R] /Count 1 >>\nendobj\n"
    obj3 = (
        b"3 0 obj\n<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << >> /Contents 5 0 R >>\nendobj\n"
    )
    obj4 = b"4 0 obj\n<< /Length 0 >>\nstream\n\nendstream\nendobj\n"
    obj5 = (
        f"5 0 obj\n<< /Length {len(content)} >>\nstream\n".encode("ascii")
        + content
        + b"\nendstream\nendobj\n"
    )
    return _write_pdf([obj1, obj2, obj3, obj4, obj5])


# ---------------------------------------------------------------------------
# Raster (Phase B, P3) — deterministic comic-like pages
# ---------------------------------------------------------------------------

PAGE_W = 400
PAGE_H = 300

# Light panel colors (distinct from white bg, NOT <128 gray so they don't collide
# with dark-ink region detection). The skin-toned panel triggers the deterministic
# face-candidate heuristic; the blue panel is an object candidate.
SKIN_PANEL = (245, 200, 180)
BLUE_PANEL = (160, 190, 235)


def _panel(page: Image.Image, box: tuple[int, int, int, int], color: tuple[int, int, int]) -> None:
    x0, y0, x1, y1 = box
    ImageDraw.Draw(page).rectangle([x0, y0, x1, y1], fill=color)


def raster_comic_bytes() -> bytes:
    """A deterministic comic-like page: 2 light panels + 2 OCR text lines.

    * panel 1 = skin-toned square (face candidate),
    * panel 2 = light blue (object candidate),
    * bottom text lines ``HELLO WORLD`` / ``PANEL`` (reference-OCR readable).
    ``HELLO``, ``WORLD`` and ``PANEL`` are members of the reference OCR
    dictionary, so the hermetic in-process provider genuinely reads them.
    """
    page = Image.new("RGB", (PAGE_W, PAGE_H), (255, 255, 255))
    _panel(page, (10, 10, 190, 150), SKIN_PANEL)  # 180x140 square (face)
    _panel(page, (210, 10, 390, 150), BLUE_PANEL)  # 180x140 (object)
    draw_text_line(page, "HELLO WORLD", (20, 170))
    draw_text_line(page, "PANEL", (20, 195))
    buf = io.BytesIO()
    page.save(buf, format="PNG")
    return buf.getvalue()


def raster_single_panel_bytes() -> bytes:
    """A page with exactly one light-blue panel and no text (panel ordering test)."""
    page = Image.new("RGB", (PAGE_W, PAGE_H), (255, 255, 255))
    _panel(page, (20, 20, 220, 160), BLUE_PANEL)
    buf = io.BytesIO()
    page.save(buf, format="PNG")
    return buf.getvalue()


def raster_text_only_bytes() -> bytes:
    """A plain white page with OCR text only (no panels) — OCR region provenance."""
    page = Image.new("RGB", (PAGE_W, PAGE_H), (255, 255, 255))
    draw_text_line(page, "HELLO WORLD", (20, 40))
    buf = io.BytesIO()
    page.save(buf, format="PNG")
    return buf.getvalue()


def _png_chunk(typ: bytes, data: bytes) -> bytes:
    out = struct.pack(">I", len(data)) + typ + data
    out += struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
    return out


def png_with_dims(width: int, height: int) -> bytes:
    """A minimal valid PNG whose IHDR declares ``width``x``height``.

    Used to exercise the bounded-decode budget: PIL parses the IHDR dimensions at
    open time (before any pixel allocation), so ``RasterLimitsExceeded`` is raised
    without materializing an oversized buffer (decompression-bomb guard).
    """
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    row = b"\x00" + bytes([255, 255, 255]) * min(width, 1)
    idat = zlib.compress(row)
    return sig + _png_chunk(b"IHDR", ihdr) + _png_chunk(b"IDAT", idat) + _png_chunk(b"IEND", b"")


def raster_oversized_bytes() -> bytes:
    """PNG declaring 8000x8000 px = 64M px (over the 40M default budget)."""
    return png_with_dims(8000, 8000)


def raster_malformed_bytes() -> bytes:
    """Bytes that are not a decodable image (deterministic decode failure)."""
    return b"PNG-not-really-a-png\x00\x01\x02"


# ---------------------------------------------------------------------------
# Phase F / P1-S1: deterministic heterogeneous media fixtures
#
# Locked to the tested FFmpeg build (``/usr/bin/ffmpeg``) where audio/video is
# synthesized; all text/raster/subtitle/archive fixtures are pure stdlib so the
# exact same bytes are produced on every run (the determinism tests rely on this).
# ---------------------------------------------------------------------------


def _ffmpeg() -> str:
    """The FFmpeg binary the generators are locked to (test environment builds)."""
    return os.environ.get("UMD_FFMPEG") or shutil.which("ffmpeg") or "ffmpeg"


def _wav_from_samples(
    samples: list[float], sample_rate: int = tone.DEFAULT_SAMPLE_RATE, channels: int = 1
) -> bytes:
    """Deterministic RIFF/WAVE PCM wrapper around the reference tone codec output."""
    data = tone.to_pcm16(samples)
    byte_rate = sample_rate * channels * 2
    fmt = struct.pack("<HHIIHH", 1, channels, sample_rate, byte_rate, channels * 2, 16)
    riff = b"RIFF" + struct.pack("<I", 36 + len(data)) + b"WAVE"
    return (
        riff
        + b"fmt "
        + struct.pack("<I", len(fmt))
        + fmt
        + b"data"
        + struct.pack("<I", len(data))
        + data
    )


# --- translated / adapted books (byte-different realizations of ONE work) -----


def translated_txt_bytes() -> bytes:
    """A French translation of the canonical TXT work (distinct source bytes)."""
    return (
        "Chapitre 1\n"
        "\n"
        "Alice entra dans le jardin. Elle vit le Lapin Blanc.\n"
        "\n"
        "\u2013 Bonjour, dit Alice. O\u00f9 allez-vous ?\n"
        "\n"
        "Le Lapin Blanc regarda sa montre et s'enfuit.\n"
    ).encode("utf-8")


def adapted_markdown_bytes() -> bytes:
    """An ADAPTED (not translated) Markdown realization of the same work."""
    return (
        b"# The Musical Garden\n"
        b"\n"
        b"## Opening Scene\n"
        b"\n"
        b"Alice danced into the garden and the White Rabbit sang.\n"
        b"\n"
        b"## Finale\n"
        b"\n"
        b'"Farewell," sang Alice.\n'
    )


# --- raster / comic / CJK / vertical pages -----------------------------------


def raster_vertical_cjk_bytes() -> bytes:
    """A vertical-layout comic page: panels stacked top-to-bottom plus a vertical
    text column (CJK-style vertical typesetting) — deterministic regions.

    The three panels have distinct quantized colors so ``detect_panels`` returns
    them in a stable reading order; the dark vertical strokes form an ink column
    that ``find_ink_regions`` isolates deterministically. CJK/vertical OCR is the
    gated PaddleOCR path (never claimed); the deterministic region/panel stage is
    what this fixture exercises.
    """
    page = Image.new("RGB", (640, 420), (255, 255, 255))
    _panel(page, (10, 10, 300, 110), (240, 120, 120))  # top panel
    _panel(page, (10, 130, 300, 230), (120, 200, 120))  # middle panel
    _panel(page, (10, 250, 300, 350), (120, 140, 220))  # bottom panel
    draw = ImageDraw.Draw(page)
    for y in range(30, 370, 40):  # vertical text column (right)
        draw.rectangle([420, y, 438, y + 22], fill=(30, 30, 30))
    buf = io.BytesIO()
    page.save(buf, format="PNG")
    return buf.getvalue()


# --- multi-speaker audio ------------------------------------------------------


def multi_speaker_audio_wav_bytes(sample_rate: int = tone.DEFAULT_SAMPLE_RATE) -> bytes:
    """Deterministic two-speaker dialogue WAV rendered via the reference tone codec.

    Two speakers' phrases are rendered as distinct tone utterances separated by
    silence; the audio baseline therefore yields ≥2 distinct utterance-level
    speaker candidates (never merged into one speaker).
    """
    speaker_a = tone.render_phrase(["hello", "alice"], sample_rate)
    gap = tone.render_silence(0.5, sample_rate)
    speaker_b = tone.render_phrase(["goodbye", "bob"], sample_rate)
    return _wav_from_samples(speaker_a + gap + speaker_b, sample_rate)


# --- music-under-speech (adversarial audio) -----------------------------------


def music_under_speech_wav_bytes(sample_rate: int = tone.DEFAULT_SAMPLE_RATE) -> bytes:
    """Speech with a loud music tone overlaid mid-phrase (music-under-speech).

    The reference ASR reads the overlapped word as a non-codec tone (ambiguous =>
    low confidence); the hallucination filter is expected to flag the corrupted
    window rather than emit confident transcript text.
    """
    speech = tone.render_phrase(["hello", "world"], sample_rate)
    mid_s = (len(speech) * 0.5) / sample_rate
    under = tone.overlay_music(speech, start_s=mid_s, duration_s=0.45, sample_rate=sample_rate)
    return _wav_from_samples(under, sample_rate)


# --- dialogue video (FFmpeg-locked) -------------------------------------------


def dialogue_video_bytes() -> bytes:
    """Deterministic ~2s MKV: black video + ASR-able dialogue (tone) audio + an
    independent SRT dialogue/HI subtitle track. Locked to the tested FFmpeg build.
    """
    ffmpeg = _ffmpeg()
    with tempfile.TemporaryDirectory() as td:
        wav = td + "/dialog.wav"
        with open(wav, "wb") as f:
            f.write(multi_speaker_audio_wav_bytes())
        srt = td + "/dialog.srt"
        with open(srt, "w", encoding="utf-8") as f:
            f.write("1\n00:00:00.200 --> 00:00:00.900\n[bgm] Hello Alice\n")
        out = td + "/out.mkv"
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=96x96:r=25:d=2",
            "-i",
            wav,
            "-i",
            srt,
            "-map",
            "0:v",
            "-map",
            "1:a",
            "-map",
            "2:0",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-c:s",
            "srt",
            "-metadata:s:s:0",
            "language=eng",
            "-t",
            "2",
            out,
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        with open(out, "rb") as f:
            return f.read()


def vfr_editlist_video_bytes() -> bytes:
    """A non-CFR (VFR) MP4 assembled by concatenating two lavfi clips of different
    native frame rates, producing uneven PTS spacing. Locked to the FFmpeg build.
    """
    ffmpeg = _ffmpeg()
    with tempfile.TemporaryDirectory() as td:
        out = td + "/vfr.mp4"
        cmd = [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=48x48:d=0.5:r=25",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=s=48x48:d=0.5:r=12",
            "-filter_complex",
            "[0:v][1:v]concat=n=2:v=1:a=0[v]",
            "-map",
            "[v]",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            out,
        ]
        subprocess.run(cmd, check=True, capture_output=True)
        with open(out, "rb") as f:
            return f.read()


# --- independent subtitle tracks (HI/SDH, nonzero timestamp maps) --------------

_SRT = "1\n00:00:00.500 --> 00:00:01.500\nHello world\n"
_SRT_HI = "1\n00:00:00.500 --> 00:00:01.500\n[music playing] Hello world\n"

_ASS_BASE = (
    "[Script Info]\nScriptType: v4.00+\n\n"
    "[V4+ Styles]\nFormat: Name, Fontname, Fontsize, PrimaryColour, Bold, Italic\n"
    "Style: Default,Arial,20,16777215,0,0\n\n"
    "[Events]\n"
    "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text\n"
    "Dialogue: 0,0:00:00.50,0:00:01.50,Default,Julien,0,0,0,,{line}\n"
)
_ASS_HI = "{\\i1}[music] (laughs){\\i0}"

_VTT_WITH_MAP = (
    "WEBVTT\n"
    "X-TIMESTAMP-MAP=LOCAL:00:00:00.000,MPEGTS:900000\n\n"
    "00:00:00.500 --> 00:00:01.500\n{line}\n"
)
_VTT_LINE = "[bgm] Hello world"
_VTT_HI_LINE = "[bgm][music playing] Hello world"

_TTML = (
    '<tt xmlns="http://www.w3.org/ns/ttml" xmlns:tts="http://www.w3.org/ns/ttml#styling">'
    "<body><div>"
    '<p begin="00:00:00.500" end="00:00:01.500">{line}</p>'
    "</div></body></tt>"
)
_TTML_LINE = 'Hello <span tts:fontStyle="italic">world</span>'
_TTML_HI_LINE = '[music] Hello <span tts:fontStyle="italic">[SDH]</span> world'

_SAMI = "<SAMI><HEAD></HEAD><BODY><SYNC Start=500><P>{line}</P></SYNC></BODY></SAMI>"
_SAMI_LINE = "Hello world"
_SAMI_HI_LINE = "[SDH] Hello [music playing]"


def subtitle_bytes(fmt: str, *, hi_sdh: bool = False, timestamp_map: int = 900000) -> bytes:
    """Deterministic subtitle source bytes for every v1 format.

    ``hi_sdh`` injects HI/SDH markers (``[music playing]`` etc.) so the parser must
    preserve them verbatim; ``timestamp_map`` is the nonzero WebVTT MPEGTS epoch
    (in 90 kHz units) that the mandatory pre-normalization must shift cues by.
    """
    if fmt == "srt":
        return (_SRT_HI if hi_sdh else _SRT).encode("utf-8")
    if fmt == "ass":
        span = _ASS_HI if hi_sdh else "Hello world"
        return _ASS_BASE.replace("{line}", span).encode("utf-8")
    if fmt == "webvtt":
        line = _VTT_HI_LINE if hi_sdh else _VTT_LINE
        vtt = _VTT_WITH_MAP.replace("{line}", line)
        vtt = vtt.replace("MPEGTS:900000", f"MPEGTS:{timestamp_map}")
        return vtt.encode("utf-8")
    if fmt == "ttml":
        line = _TTML_HI_LINE if hi_sdh else _TTML_LINE
        return _TTML.replace("{line}", line).encode("utf-8")
    if fmt == "sami":
        line = _SAMI_HI_LINE if hi_sdh else _SAMI_LINE
        return _SAMI.replace("{line}", line).encode("utf-8")
    if fmt == "microdvd":
        words = "[SDH] Hello world" if hi_sdh else "Hello world"
        return f"{{2}}{{50}}{words}".encode()
    if fmt == "mpl2":
        words = "[SDH] Hello /world/" if hi_sdh else "Hello |world|"
        return f"[5][20]{words}".encode()
    if fmt == "tmp":
        words = "[SDH] Hello world" if hi_sdh else "Hello world"
        return f"0:00:00:0.5:{words}".encode()
    raise ValueError(f"unknown subtitle format: {fmt}")


SUBTITLE_FORMATS = ("srt", "ass", "webvtt", "ttml", "sami", "microdvd", "mpl2", "tmp")


# ---------------------------------------------------------------------------
# Phase F / P1-S2: adversarial fixture generators
# ---------------------------------------------------------------------------


def malformed_container_bytes() -> bytes:
    """Bytes that claim to be an EBML/Matroska container but are structurally invalid."""
    return b"\x1a\x45\xdf\xa3\x9f\x42\x86\x81\x01VOBSUBnodefaultGARBAGE"


def vobsub_idx_bytes() -> bytes:
    """A crafted VobSub-style ``.idx`` (CVE-2026-64830 demuxer class input)."""
    return (
        b"# VobSub index file, v7 (do not modify this line!)\n"
        b"id: en, index: 0\n"
        b"timestamp: 00:00:00:000, file: vobsub.00.sub\n"
    )


def vobsub_sub_bytes() -> bytes:
    """Crafted VobSub ``.sub`` packet bytes (raw bitmap subtitle stream)."""
    return b"\x00\x00\x01\xba\x00\x00\x00\x24" + b"\x00" * 64


def raster_max_ihdr_bytes() -> bytes:
    """PNG whose IHDR declares the maximum dimensions 65535x65535 → ~4.3G px,
    far beyond any pixel budget; the bounded-decode guard rejects it before alloc."""
    return png_with_dims(65535, 65535)


def non_utf8_subtitle_bytes() -> bytes:
    """cp1252 smart quotes + accented latin — NOT valid UTF-8 (charset probe)."""
    return b"1\n00:00:01.000 --> 00:00:02.000\ncaf\xe9 \x93perfect\x94"


def corrupt_encoding_bytes() -> bytes:
    """Byte sequence that is not a decodable text encoding (mixed/truncated)."""
    return b"\xff\xfe\x00GARBAGE\x80\x81\x82\xfe\xff\x00"


def zip_bomb_bytes() -> bytes:
    """A high-ratio deflate member (256 KiB → ~300 B) — a decompressed-size cap probe."""
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("bomb.bin", b"Z" * (256 * 1024))
    return buf.getvalue()


def tar_symlink_bytes() -> bytes:
    """A tar containing a symlink member pointing outside the archive root."""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tf:
        link = tarfile.TarInfo("lnk")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        tf.addfile(link)
    buf.seek(0)
    return buf.getvalue()


def tar_traversal_bytes() -> bytes:
    """A tar containing a ``..`` traversal member."""
    buf = io.BytesIO()
    data = b"x"
    with tarfile.open(fileobj=buf, mode="w") as tf:
        info = tarfile.TarInfo("../escape.txt")
        info.size = len(data)
        tf.addfile(info, io.BytesIO(data))
    buf.seek(0)
    return buf.getvalue()


def sandbox_violation_payload(kind: str) -> list[str]:
    """Deterministic subprocess argv that violates a sandbox limit.

    ``kind`` ∈ {``timeout``, ``oom``, ``fd``, ``pid``, ``crash``}. Returns a
    list of argv (the runner contract is array-args only — never a shell string).
    """
    if kind == "timeout":
        return ["-c", "import time; time.sleep(30)"]
    if kind == "oom":
        return ["-c", "x = list(range(200_000_000))"]
    if kind == "fd":
        return ["-c", "import os; [open('/dev/null') for _ in range(1000)]"]
    if kind == "pid":
        # Spawn far more descendant processes than the nproc budget; wrapped so a
        # gated platform that cannot enforce RLIMIT_NPROC still reports bounded.
        return [
            "-c",
            "import subprocess,sys; "
            "[subprocess.Popen([sys.executable,'-c','import time;time.sleep(5)']) "
            " for _ in range(200)]",
        ]
    if kind == "crash":
        return ["-c", "import os; os.abort()"]
    raise ValueError(f"unknown sandbox violation kind: {kind}")
