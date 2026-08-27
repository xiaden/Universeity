"""Sandboxed bounded FFprobe/FFmpeg video decode + scene analysis (P3-S1).

The DD mandates that PyAV/FFmpeg decode **never runs in the API process**
(CONTRACTS §Modality and security + Task §32). This module is the *worker-side*
codec boundary — it runs **inside** the sandboxed video worker subprocess and
shells out to ``ffprobe``/``ffmpeg`` with **array-only argv** (no shell
interpolation), exactly mirroring the Phase-2 audio decode boundary.

Bounded operations:

  * :func:`probe_inventory` — ffprobe stream/format metadata (real, deterministic).
  * :func:`detect_scene_boundaries` — ffmpeg ``scene`` filter showinfo parse
    (real, deterministic; the non-gated reference scene/shot provider).
  * :func:`frame_anchors` — bounded PTS-native frame timing anchors via
    ``ffmpeg`` ``showinfo`` on a sampled frame subset.
  * :func:`extract_embedded_subtitle_tracks` — P3-S2: extract EVERY embedded
    subtitle track into an independent source; unsupported (bitmap) subtitle
    codecs become classified quarantine records (never silently dropped).

Heavy/PyAV decode and PySceneDetect are GATED enhancers; the reference providers
above use the locked system ffmpeg/ffprobe build and are hermetic and bounded.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from umd.video.types import FrameAnchor, SceneBoundary, ShotBoundary, VideoConfig, VideoTrack

#: Cap on ffprobe/ffmpeg captured text output.
_MAX_CAPTURE = 1 << 20
#: Cap on extracted embedded-subtitle bytes we retain per track (bounded).
_MAX_SUBTITLE_BYTES = 4 * 1024 * 1024

#: Text subtitle codecs we can extract to a parseable native text stream, mapped
#: to ``(target_sub_codec, mux_format)``. Extraction uses a codec-appropriate
#: transcode so styles/signs/songs/typesetting/HI/SDH are preserved, not flattened.
#: Anything missing (bitmap/VobSub/PGS) is a classified quarantine record.
TEXT_SUBTITLE_CODECS: dict[str, tuple[str, str]] = {
    "subrip": ("srt", "srt"),
    "ssa": ("ass", "ass"),
    "ass": ("ass", "ass"),
    "webvtt": ("webvtt", "webvtt"),
    "mov_text": ("mov_text", "srt"),
    "text": ("srt", "srt"),
}
#: Subtitle codecs definitely NOT text-extractable -> classified quarantine records.
BITMAP_SUBTITLE_CODECS = {
    "dvd_subtitle",
    "dvdsub",
    "hdmv_pgs_subtitle",
    "pgssub",
    "dvb_subtitle",
    "dvb_teletext",
    "xsub",
}


class VideoDecodeError(RuntimeError):
    """Decode/inventory failed or exceeded bounds (typed, quarantine-able)."""


class SubtitleExtractionError(VideoDecodeError):
    """Embedded subtitle extraction failed (typed, quarantine-able)."""


def ffmpeg_binary() -> str:
    path = shutil.which("ffmpeg")
    if path is None:
        raise VideoDecodeError("ffmpeg not available; video decode is GATED/absent here")
    return path


def ffprobe_binary() -> str:
    path = shutil.which("ffprobe")
    if path is None:
        raise VideoDecodeError("ffprobe not available; video inventory is GATED/absent")
    return path


def _run(cmd: list[str], timeout: float) -> subprocess.CompletedProcess[bytes]:
    try:
        return subprocess.run(  # noqa: S603 - fixed resolved binaries, array argv
            cmd, capture_output=True, timeout=timeout, check=False
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise VideoDecodeError(f"ffmpeg/ffprobe failed to spawn: {exc}") from exc


def probe_inventory(input_path: Path, *, max_duration_s: float = 0.0) -> list[VideoTrack]:
    """Read container/stream metadata via ffprobe (bounded, array-only argv)."""
    cmd = [
        ffprobe_binary(),
        "-v",
        "error",
        "-show_format",
        "-show_streams",
        "-of",
        "json",
        str(input_path),
    ]
    proc = _run(cmd, timeout=20.0)
    if proc.returncode != 0:
        raise VideoDecodeError(
            f"ffprobe exited {proc.returncode}: {proc.stderr[:512].decode(errors='replace')}"
        )
    try:
        data = json.loads(proc.stdout.decode("utf-8", errors="replace"))
    except (ValueError, AttributeError) as exc:
        raise VideoDecodeError(f"ffprobe emitted non-JSON metadata: {exc}") from exc

    tracks: list[VideoTrack] = []
    for s in data.get("streams") or []:
        tracks.append(_track_from_stream(s))

    # Bounded duration: the primary video stream's (or format's) duration must
    # not exceed the ceiling when one is set.
    if max_duration_s > 0.0:
        for t in tracks:
            if t.codec_type == "video" and t.duration and t.duration > max_duration_s:
                raise VideoDecodeError(
                    f"video duration {t.duration:.3f}s exceeds ceiling {max_duration_s:.3f}s"
                )
    return tracks


def _as_tags(v: object) -> dict[str, Any]:
    """Narrow an ffprobe ``tags`` blob to a plain string dict."""
    if not isinstance(v, dict):
        return {}
    return {str(k): vv for k, vv in v.items()}


def _track_from_stream(s: dict[str, Any]) -> VideoTrack:
    def _int_(val: object) -> int | None:
        try:
            return int(float(str(val)))
        except (TypeError, ValueError):
            return None

    tags = _as_tags(s.get("tags"))
    duration = None
    d = s.get("duration")
    if d is not None:
        try:
            duration = float(str(d))
        except ValueError:
            duration = None
    return VideoTrack(
        index=_int_(s.get("index")) or 0,
        codec_type=str(s.get("codec_type") or "unknown"),
        codec_name=str(s.get("codec_name") or "unknown"),
        language=str(tags.get("language")) if tags.get("language") is not None else None,
        disposition=dict(s.get("disposition") or {}),
        title=str(tags.get("title")) if tags.get("title") is not None else None,
        width=_int_(s.get("width")),
        height=_int_(s.get("height")),
        time_base=str(s.get("time_base")),
        avg_frame_rate=str(s.get("avg_frame_rate")),
        r_frame_rate=str(s.get("r_frame_rate")),
        pix_fmt=str(s.get("pix_fmt")) if s.get("pix_fmt") else None,
        sample_rate=_int_(s.get("sample_rate")),
        channels=_int_(s.get("channels")),
        pts_start=_int_(s.get("start_pts")),
        duration=duration,
        nb_frames=_int_(s.get("nb_frames")),
        tags=tags,
    )


# ---------------------------------------------------------------------------
# Scene / shot boundary detection (real ffmpeg scene filter; PySceneDetect GATED)
# ---------------------------------------------------------------------------

#: ``showinfo`` line carries `pts_time:TIMESTAMP` and an optional `n:FRAME`.
_PTS_TIME_RE = re.compile(r"pts_time:([0-9]+(?:\.[0-9]+)?)")
_SCENE_SHOWINFO_RE = re.compile(r"pts_time:([0-9]+(?:\.[0-9]+)?)")


def _duration_cap(config: VideoConfig) -> list[str]:
    return ["-t", f"{config.max_duration_s:.3f}"] if config.max_duration_s > 0.0 else []


def detect_scene_boundaries(input_path: Path, config: VideoConfig) -> list[SceneBoundary]:
    """Detect scene boundaries with the ffmpeg ``scene`` filter (real, bounded).

    Uses ``select='gt(scene,THRESH)',showinfo`` and parses each *selected*
    frame's ``pts_time`` — the standard toolchain for deterministic scene cuts.
    Bounded by the duration cap. See :func:`reference_scene_shots` for the split
    into scene/shot.
    """
    cmd = [
        ffmpeg_binary(),
        "-v",
        "info",
        "-i",
        str(input_path),
        *_duration_cap(config),
        "-vf",
        f"select='gt(scene,{config.scene_threshold:.3f})',showinfo",
        "-f",
        "null",
        "-",
    ]
    proc = _run(cmd, timeout=max(30.0, config.max_duration_s + 30.0))
    return _parse_showinfo(proc.stderr.decode("utf-8", errors="replace"))


def _parse_showinfo(stderr: str) -> list[SceneBoundary]:
    boundaries: list[SceneBoundary] = []
    for line in stderr.splitlines():
        if "pts_time:" not in line:
            continue
        m = _PTS_TIME_RE.search(line)
        if not m:
            continue
        try:
            t = float(m.group(1))
        except ValueError:
            continue
        boundaries.append(SceneBoundary(index=0, start_pts=None, start_s=t, end_s=t, threshold=0.0))
    return boundaries


def reference_scene_shots(
    input_path: Path, config: VideoConfig, total_duration_s: float
) -> tuple[list[SceneBoundary], list[ShotBoundary]]:
    """Split detected scene-cut timestamps into scenes and shots (deterministic).

    A scene runs from one cut until the next (or the media end). Each scene is
    additionally partitioned into shots on the same cut timestamps so scene/shot
    segments are both PTS-native and bounded by ``max_scenes``. The reference
    provider is the ffmpeg scene filter (real) — PySceneDetect is the GATED
    enhancer (see :mod:`umd.video.scenes`).
    """
    cuts = detect_scene_boundaries(input_path, config)
    scenes: list[SceneBoundary] = []
    shots: list[ShotBoundary] = []
    times = [c.start_s for c in cuts]
    # Always emit a scene from 0.0 so a no-cut video still yields one scene + shot.
    boundaries = sorted(set([0.0, *times]))
    prev = 0.0
    for i, t in enumerate(boundaries):
        end = boundaries[i + 1] if i + 1 < len(boundaries) else total_duration_s
        scenes.append(
            SceneBoundary(
                index=len(scenes),
                start_pts=int(round(prev * 90000)),
                start_s=round(prev, 4),
                end_s=round(end, 4),
                threshold=config.scene_threshold,
            )
        )
        prev = t
        if len(scenes) >= config.max_scenes:
            break
    for sc in scenes:
        shots.append(
            ShotBoundary(
                index=len(shots),
                start_pts=sc.start_pts,
                start_s=sc.start_s,
                end_s=sc.end_s,
                threshold=sc.threshold,
            )
        )
    return scenes, shots


# ---------------------------------------------------------------------------
# Bounded PTS-native frame timing anchors
# ---------------------------------------------------------------------------


def frame_anchors(
    input_path: Path, config: VideoConfig, fps: float, duration_s: float
) -> list[FrameAnchor]:
    """Sample a bounded set of PTS-native frame timing anchors via ffmpeg showinfo.

    ``STEP = max(1, floor(total_frames / max_frames))`` so the sampled anchors
    never exceed ``max_frames`` regardless of source length. Real ``pts_time``
    values come back from ffmpeg (PTS-native), not synthesized.
    """
    if fps <= 0.0:
        return []
    total_frames = int(duration_s * fps)
    step = max(1, total_frames // max(1, config.max_frames))
    cmd = [
        ffmpeg_binary(),
        "-v",
        "info",
        "-i",
        str(input_path),
        *_duration_cap(config),
        "-vf",
        f"select='not(mod(n,{step}))',showinfo",
        "-frames:v",
        str(config.max_frames),
        "-f",
        "null",
        "-",
    ]
    proc = _run(cmd, timeout=max(30.0, config.max_duration_s + 30.0))
    anchors: list[FrameAnchor] = []
    for line in proc.stderr.decode("utf-8", errors="replace").splitlines():
        if "pts_time:" not in line:
            continue
        m = _PTS_TIME_RE.search(line)
        if not m:
            continue
        try:
            t = float(m.group(1))
        except ValueError:
            continue
        anchors.append(
            FrameAnchor(
                index=len(anchors),
                pts=int(round(t * 90000)),
                pts_time_s=round(t, 4),
            )
        )
    return anchors


# ---------------------------------------------------------------------------
# Embedded subtitle track extraction (P3-S2)
# ---------------------------------------------------------------------------


def _video_stream_index(tracks: list[VideoTrack]) -> int:
    """Index of the first video stream (or 0) for container-level analysis."""
    for t in tracks:
        if t.codec_type == "video":
            return t.index
    return 0


def extract_embedded_subtitle_tracks(
    input_path: Path,
    tracks: list[VideoTrack],
) -> list[dict[str, Any]]:
    """Extract EVERY embedded subtitle track into an independent source.

    For text-capable subtitle codecs the raw stream bytes are pulled with
    ``ffmpeg -map 0:<track_index> -c:s <sub_codec> -f <mux>`` — a global
    stream-index map and a codec-appropriate transcode (e.g. ``ass``->``ass``,
    ``webvtt``->``webvtt``), bounded to 4MB and base64-encoded. The transcode
    is styles/timing-preserving per stream, keeping each source native.
    Bitmap / unsupported codecs produce a classified ``quarantine`` record
    instead of a payload — a track is never silently dropped and never
    over-bundled.

    Returns one dict per subtitle track:
        {index, codec_name, language, disposition, title, extractable,
         quarantine_reason?, payload_b64?, offset_bytes, extraction_provider}
    """
    results: list[dict[str, Any]] = []
    for t in tracks:
        if t.codec_type != "subtitle":
            continue
        codec = t.codec_name
        target = TEXT_SUBTITLE_CODECS.get(codec)
        entry: dict[str, Any] = {
            "index": t.index,
            "codec_name": codec,
            "language": t.language,
            "disposition": t.disposition,
            "title": t.title,
            "tags": t.tags,
        }
        if target is None:
            entry.update(
                extractable=False,
                quarantine_reason=(
                    f"unsupported subtitle codec {codec!r}: bitmap/VobSub-class "
                    "payload is not text-extractable; classified QUARANTINE"
                ),
                payload_b64=None,
                offset_bytes=t.pts_start,
                extraction_provider="umd-reference-extract v1.0",
            )
            results.append(entry)
            continue
        try:
            payload = _extract_track_bytes(input_path, t.index, target[0], target[1])
        except SubtitleExtractionError as exc:
            entry.update(
                extractable=False,
                quarantine_reason=f"subtitle extraction failure: {exc}",
                payload_b64=None,
                offset_bytes=t.pts_start,
                extraction_provider="umd-reference-extract v1.0",
            )
            results.append(entry)
            continue
        entry.update(
            extractable=True,
            quarantine_reason=None,
            payload_b64=payload,
            offset_bytes=t.pts_start,
            extraction_provider="umd-reference-extract v1.0",
        )
        results.append(entry)
    return results


def _extract_track_bytes(input_path: Path, track_index: int, sub_codec: str, mux: str) -> str:
    """Return base64 of the extracted native text subtitle stream (bounded).

    Uses a codec-appropriate transcode (e.g. ``ass`` -> ass, ``webvtt`` -> webvtt)
    so the independent source preserves styles/timing/signs/songs instead of being
    flattened to a plain format. The resulting bytes are the authoritative raw
    content stored as an independent OCFL source.
    """
    import base64

    cmd = [
        ffmpeg_binary(),
        "-v",
        "error",
        "-i",
        str(input_path),
        "-map",
        f"0:{track_index}",
        "-c:s",
        sub_codec,
        "-f",
        mux,
        "-",
    ]
    proc = _run(cmd, timeout=60.0)
    if proc.returncode != 0:
        raise SubtitleExtractionError(
            "ffmpeg extraction exited "
            f"{proc.returncode}: {proc.stderr[:512].decode(errors='replace')}"
        )
    data = proc.stdout
    if len(data) > _MAX_SUBTITLE_BYTES:
        raise SubtitleExtractionError(
            f"extracted subtitle track exceeds budget ({len(data)} > {_MAX_SUBTITLE_BYTES} bytes)"
        )
    return base64.b64encode(data).decode("ascii")


__all__ = [
    "TEXT_SUBTITLE_CODECS",
    "SubtitleExtractionError",
    "VideoDecodeError",
    "_parse_showinfo",
    "detect_scene_boundaries",
    "extract_embedded_subtitle_tracks",
    "ffmpeg_binary",
    "ffprobe_binary",
    "frame_anchors",
    "probe_inventory",
    "reference_scene_shots",
]
