"""Per-parser sandbox policy / limit registry (Phase C, P1-S1).

Central registry mapping a *workload name* (parser / extraction stage) to the
:class:`SandboxPolicy` + :class:`SandboxLimits` pair it runs under. This keeps
the security posture declarative and consistent: every parser is invoked with an
explicit, reviewable allowlist and resource budget rather than ad-hoc per-call
arguments.

The media-heavy workloads (audio/video/subtitle) are registered here with their
entrypoint allowlists and resource ceilings. No ``model`` profile is registered:
in Phase 1 the model provider is HTTP-only (no sandboxed model dispatch), so it
has no sandbox policy entry. ``policy_for`` returns a frozen default so callers
get a fresh, safe copy.
"""

from __future__ import annotations

from dataclasses import dataclass

from umd.security.sandbox import SandboxLimits, SandboxPolicy

#: The single parser entrypoint module currently allowlisted behind the sandbox.
_PARSER_MODULE = "umd.extractors.dispatch"


@dataclass(frozen=True)
class ParserProfile:
    """The combined policy+limits for one workload name."""

    name: str
    policy: SandboxPolicy
    limits: SandboxLimits


#: Archive-capable workloads get decompression ceilings and entry-count bounds.
_ARCHIVE_LIMITS = SandboxLimits(
    max_files=2000,
    max_decompressed_bytes=512 * 1024 * 1024,
    timeout_s=60.0,
    max_output_bytes=32 * 1024 * 1024,
)

#: Registry of per-workload profiles. Keyed by workload name; the policy and
#: limits are authoritative for that parser.
PARSER_POLICIES: dict[str, ParserProfile] = {
    "txt": ParserProfile(
        name="txt",
        policy=SandboxPolicy(allowed_modules=(_PARSER_MODULE,), allowed_extensions=("txt",)),
        limits=SandboxLimits(timeout_s=30.0),
    ),
    "markdown": ParserProfile(
        name="markdown",
        policy=SandboxPolicy(allowed_modules=(_PARSER_MODULE,), allowed_extensions=("md",)),
        limits=SandboxLimits(timeout_s=30.0),
    ),
    "epub": ParserProfile(
        name="epub",
        policy=SandboxPolicy(
            allowed_modules=(_PARSER_MODULE,),
            allowed_extensions=("epub",),
            archive_allow_extensions=(
                "xml",
                "opf",
                "ncx",
                "html",
                "xhtml",
                "css",
                "png",
                "jpg",
                "jpeg",
                "gif",
                "svg",
                "webp",
            ),
        ),
        limits=_ARCHIVE_LIMITS,
    ),
    "pdf": ParserProfile(
        name="pdf",
        policy=SandboxPolicy(allowed_modules=(_PARSER_MODULE,), allowed_extensions=("pdf",)),
        limits=SandboxLimits(timeout_s=60.0, memory_bytes=768 * 1024 * 1024),
    ),
    # Media/extraction workloads (audio/video/subtitle) register their own
    # entrypoints and ceilings (Phases 2/3); the text parsers above share the
    # dispatch entrypoint. The registry stays complete and total.
    "audio": ParserProfile(
        name="audio",
        policy=SandboxPolicy(
            allowed_modules=("umd.audio.dispatch",),
            allowed_extensions=("wav", "mp3", "flac", "m4a", "ogg"),
        ),
        # The audio baseline alone spawns ffprobe+ffmpeg as decoder subprocesses.
        # RLIMIT_NPROC is per real-UID across ALL processes/threads (not just the
        # sandboxed child); the host harness's own threads push that count well past
        # 1024, which would starve the decoder fork (EAGAIN). Use a generous bounded
        # 8192 so the streaming decode can fork on a thread-heavy host while still
        # capping runaway process growth. Address-space (RLIMIT_AS), CPU, time and
        # fd caps still apply to ffmpeg.
        #
        # ``memory_bytes`` must sit well above the 512MiB SandboxLimits default:
        # the ASR stack (numpy/OpenBLAS + ctranslate2) allocates its buffers at
        # import/load time and hard-aborts ('Memory allocation still failed' /
        # 'mkl_malloc') under the address-space cliff. A 2GiB RLIMIT_AS reliably
        # clears it for the validated faster-whisper model (numpy + ctranslate2/
        # MKL reserve large virtual regions); far above the 512MiB default and
        # mirroring the video policy's own decoder ceiling bump.
        limits=SandboxLimits(
            timeout_s=120.0,
            max_duration_s=600.0,
            nproc_limit=8192,
            memory_bytes=2 * 1024 * 1024 * 1024,
        ),
    ),
    "video": ParserProfile(
        name="video",
        policy=SandboxPolicy(
            allowed_modules=("umd.video.dispatch", "umd.video.dispatch_extract"),
            allowed_extensions=("mp4", "mkv", "webm", "mov", "avi"),
        ),
        # Baseline + embedded-subtitle extraction spawn ffprobe/ffmpeg (scene
        # filter, PTS frame anchors, stream inventory). Same RLIMIT_NPROC note
        # applies as audio: nproc is per-UID and thread-heavy hosts would starve
        # the decoder fork; generous-but-bounded with AS/CPU/time/fd still capped.
        #
        # ``memory_bytes`` must stay well above the 512MiB SandboxLimits default:
        # the ffmpeg frame-anchoring pass (`select=...,showinfo` + `-frames:v`)
        # allocates its decode/filter buffer pool right at the 512MiB AS cliff.
        # Under the default it intermittently exhausts address space and exits
        # rc=69 with "Output file is empty, nothing was encoded" -> zero frame
        # anchors (silent, non-deterministic). A 1GiB RLIMIT_AS reliably clears
        # that cliff (mirrors the ``pdf`` profile's own decoder ceiling bump).
        limits=SandboxLimits(
            timeout_s=180.0,
            max_duration_s=1200.0,
            nproc_limit=8192,
            memory_bytes=1024 * 1024 * 1024,
        ),
    ),
    "subtitle": ParserProfile(
        name="subtitle",
        policy=SandboxPolicy(
            allowed_modules=("umd.subtitle.dispatch",),
            allowed_extensions=("srt", "ass", "vtt", "ttml", "sami", "mpl2", "sub", "tmp"),
        ),
        limits=SandboxLimits(timeout_s=60.0),
    ),
    "linkage": ParserProfile(
        name="linkage",
        # Bounded predict-only linkage: the resolution dispatch entrypoint only;
        # input/output are staged JSON under the spool (no shell, no untrusted
        # executable). Resource-bounded so heavy candidate scoring cannot run away.
        policy=SandboxPolicy(
            allowed_modules=("umd.resolution.dispatch",),
            allowed_extensions=("json",),
        ),
        limits=SandboxLimits(
            timeout_s=120.0,
            memory_bytes=1024 * 1024 * 1024,
            max_output_bytes=16 * 1024 * 1024,
        ),
    ),
}


def policy_for(name: str) -> ParserProfile:
    """Return the authoritative profile for ``name`` (raises on unknown)."""
    if name not in PARSER_POLICIES:
        raise KeyError(f"no sandbox policy registered for workload {name!r}")
    return PARSER_POLICIES[name]


def registered_workloads() -> tuple[str, ...]:
    """All registered workload names (for capability / completeness reporting)."""
    return tuple(sorted(PARSER_POLICIES))
