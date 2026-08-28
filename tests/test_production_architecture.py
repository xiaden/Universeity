"""Static architecture guards (Plan G Phase 3, P3-S5).

These run WITHOUT Postgres and prove, by reading the source, that the production
execution path honours the remediation contracts:

1. no production module (:mod:`umd.api`, :mod:`umd.application`,
   :mod:`umd.jobs.production`) imports or references the test-only
   :class:`SynchronousRunner` (or :class:`InMemoryJobStore`);
2. no submission / rerun / retry / invalidate path passes ``work_registry={}`` —
   every dispatch carries the composed production stage registry;
3. no module outside :mod:`umd.projections` writes the Tier-1 projection stores
   (``current_tier1`` / ``search_document`` / ``embedding``) directly;
4. no production module invokes a parser/decoder/model in-process — modality
   decoding is only reachable through the sandbox dispatch seam.

These are *guard* checks: a text/AST failure here is a regression signal, not a
substitute for the integration tests.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[1]
SRC = _ROOT / "src" / "umd"

#: Production execution roots — the modules that must honour the contracts.
PRODUCTION_ROOTS = [
    SRC / "api",
    SRC / "application",
    SRC / "jobs" / "production.py",
]

#: Test-only doubles that must never appear in a production module.
BANNED_DOUBLES = ("SynchronousRunner", "InMemoryJobStore")

#: Tier-1 projection stores — written ONLY by src/umd/projections/**.
PROJECTION_TABLES = ("current_tier1", "search_document", "embedding")

#: Decoder/model execution entrypoints that must never run in-process in the API
#: process. ``umd.models`` (provider *routing*) and ``umd.security.sandbox`` (the
#: dispatch *seam*) are intentionally excluded — routing a provider or scheduling
#: a sandboxed run is not an in-process invocation.
BANNED_DECODER_ROOTS = (
    "umd.audio",
    "umd.video",
    "umd.extractors",
    "umd.stt",
    "umd.ocr",
    "whisper",
    "torch",
    "transformers",
    "ffmpeg",
    "sentence_transformers",
)

_DML = re.compile(
    r"(?:INSERT\s+(?:INTO\s+)?|UPDATE\s+|DELETE\s+FROM\s+)"
    r"[`\"']?(?:current_tier1|search_document|embedding)\b",
    re.IGNORECASE,
)
_EMPTY_REGISTRY = re.compile(r"work_registry\s*=\s*\{\s*\}")


def _production_files() -> list[Path]:
    files: list[Path] = []
    for root in PRODUCTION_ROOTS:
        if root.is_file():
            files.append(root)
        else:
            files.extend(p for p in root.rglob("*.py") if p.is_file())
    return sorted(files)


def _module_level_imports(module: ast.Module) -> list[str]:
    """Return the FULL dotted path of every MODULE-LEVEL (top-level) import in
    ``module`` (e.g. ``umd.video.runner`` for ``from umd.video.runner import X``).

    Only *top-level* imports are returned, and with their full dotted path (not the
    first segment). An import nested inside a function/method body is a *deferred*
    import executed at call-time, not an import-time intent, so it is excluded.
    This is what lets the decoder guard treat production.py's in-method
    ``import umd.video.runner`` (which routes through the SandboxRunner dispatch
    seam and is legitimate) as benign, while still flagging any module-level
    ``import umd.audio`` or ``import torch``.
    """
    full: list[str] = []

    def visit_block(body: list[ast.stmt]) -> None:
        for node in body:
            if isinstance(node, ast.Import):
                for alias in node.names:
                    full.append(alias.name)
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    full.append(node.module)
            elif isinstance(node, ast.If):
                # Conditional imports at *module* scope (e.g. ``if TYPE_CHECKING:``)
                # are still import-time intents — recurse into their bodies only.
                # We never descend into FunctionDef/ClassDef, so method-body
                # (deferred) imports are excluded.
                visit_block(node.body)

    visit_block(module.body)
    return full


def _banned_decoder_hit(full_path: str, decoder_root: str) -> bool:
    """True when a module-level import of ``full_path`` fires ``decoder_root``.

    Prefix semantics: ``root == path`` or ``path.startswith(root + \".\")``, so both
    ``import umd.audio`` and ``from umd.audio.codec import X`` are caught. The
    pure-Python text normalizer ``umd.extractors.txt`` is explicitly exempt: it is
    the one legitimate in-process module-level import of a decoder-root *submodule*
    (production.py's ``from umd.extractors.txt import normalize_txt`` runs in-process
    and is NOT a decoder). A module-level import of any *other* decoder root — e.g.
    ``import umd.audio``, ``import whisper`` — still fires the guard.
    """
    if full_path == "umd.extractors.txt":
        return False  # pure-Python text normalizer, intended to run in-process
    return full_path == decoder_root or full_path.startswith(decoder_root + ".")


# ---------------------------------------------------------------------------
# 1. No production module references the test-only doubles.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("double", BANNED_DOUBLES)
def test_production_modules_never_reference_test_doubles(double: str) -> None:
    """AST-level: the double may be named in prose/docstrings, but must never be
    *used* (imported or called) in a production module."""
    offenders: list[str] = []
    for f in _production_files():
        tree = ast.parse(f.read_text(), filename=str(f))
        if any(isinstance(n, ast.Name) and n.id == double for n in ast.walk(tree)):
            offenders.append(str(f))
    assert not offenders, (
        f"production module(s) reference test-only double {double!r}: "
        + ", ".join(str(f) for f in offenders)
    )


# ---------------------------------------------------------------------------
# 2. No submission / rerun / retry / invalidate path passes an empty registry.
# ---------------------------------------------------------------------------


def test_no_dispatch_path_passes_empty_work_registry() -> None:
    paths = [
        SRC / "api" / "routers" / "sources.py",
        SRC / "api" / "routers" / "jobs.py",
        SRC / "api" / "routers" / "segments.py",
        SRC / "application" / "jobs.py",
    ]
    for path in paths:
        assert path.is_file(), f"expected {path} to exist"
        m = _EMPTY_REGISTRY.search(path.read_text())
        assert m is None, f"{path} still passes an empty work_registry: {m.group(0)!r}"


def test_job_service_routes_use_production_registry() -> None:
    """Every dispatch site must read the registry from the context/service, not hard-code {}."""
    src = (SRC / "api" / "routers" / "sources.py").read_text()
    # _dispatch is the single submission choke point and it must pass the context registry.
    assert "work_registry=ctx.work_registry" in src
    for rel in ("routers/jobs.py", "routers/segments.py"):
        text = (SRC / "api" / rel).read_text()
        assert "work_registry=ctx.work_registry" in text, rel


# ---------------------------------------------------------------------------
# 3. No module outside projections writes a Tier-1 projection store directly.
# ---------------------------------------------------------------------------


def test_no_direct_projection_writes_outside_projections() -> None:
    for f in sorted(SRC.rglob("*.py")):
        rel = f.relative_to(SRC)
        if rel.parts[0] == "projections":
            continue
        src = f.read_text()
        dml = _DML.search(src)
        assert dml is None, (
            f"{f} writes projection table directly: {dml.group(0)!r} "
            "(projection writes belong in src/umd/projections/**)"
        )


# ---------------------------------------------------------------------------
# 4. No production module invokes a decoder/model in-process.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("decoder_root", BANNED_DECODER_ROOTS)
def test_production_modules_do_not_import_decoders_in_process(decoder_root: str) -> None:
    offenders: list[str] = []
    for f in _production_files():
        tree = ast.parse(f.read_text(), filename=str(f))
        for full in _module_level_imports(tree):
            if _banned_decoder_hit(full, decoder_root):
                offenders.append(f"{f}#{full}")
    assert not offenders, (
        f"production module(s) import in-process decoder/model root {decoder_root!r}: "
        + ", ".join(offenders)
    )


def test_stage_work_never_runs_decoder_subprocess_itself() -> None:
    """The composed stage work performs no subprocess dispatch itself; the sandbox
    seam owns all parser dispatch (CONTRACTS §Modality and security)."""
    src = (SRC / "jobs" / "production.py").read_text()
    tree = ast.parse(src, filename=str(SRC / "jobs" / "production.py"))
    roots = _module_level_imports(tree)
    assert not any(r.split(".")[0] in ("subprocess", "os") for r in roots), (
        "src/umd/jobs/production.py must not run subprocesses directly — "
        "it routes modality work through the sandbox dispatch seam"
    )
