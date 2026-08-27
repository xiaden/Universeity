"""Parser dispatch through the :class:`SandboxRunner` seam (Phase B, P2-S1).

This is the *invocation boundary* the plan requires: untrusted parsers (PDF,
EPUB/archive) are executed as a **bounded subprocess** by the
:class:`~umd.security.sandbox.SubprocessSandboxRunner`, never in the API process.

Two layers:

* :func:`parse_document` — the pure parser "work" (reads the staged read-only
  input, runs one of the registered parsers, returns a JSON-serializable dict).
  This runs inside the sandboxed subprocess.
* :func:`invoke_parser` — the API-process caller: stages raw bytes into a
  read-only spool, builds an **array-only argv**
  (``[python, -m, umd.extractors.dispatch, <parser>, <spool_input>]``), runs it
  through the sandbox runner with bounded limits + policy, and reconstructs a
  typed :class:`ParsedSource`.

Routing: a PDF with no usable text layer yields ``route = "image_raster"`` (the
Plan-C ``RASTER_OCR`` signal); the text formats yield ``route = "text"``. OCR is
**not** implemented here.
"""

from __future__ import annotations

import json
import sys
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from umd.extractors.epub import EpubParseError, extract_epub
from umd.extractors.markdown import parse_markdown
from umd.extractors.pdf import PdfParseError, detect_pdf_text
from umd.extractors.txt import normalize_txt
from umd.security.sandbox import (
    SandboxLimits,
    SandboxPolicy,
    SandboxResult,
    SandboxRunner,
    stage_spool,
)

#: Routing signal emitted when a source has no usable text layer (Plan-C raster path).
RASTER_OCR_STAGE = "RASTER_OCR"

#: The single entrypoint module allowed as ``-m`` behind the sandbox policy.
_ENTRYPOINT_MODULE = "umd.extractors.dispatch"


@dataclass
class ParsedSource:
    """Typed result of a sandbox-invoked parse."""

    parser: str
    route: str  # "text" | "image_raster"
    document: dict[str, Any]
    input_path: str | None = None
    sandbox_result: SandboxResult | None = None
    warnings: list[str] = field(default_factory=list)


def parse_document(parser: str, input_path: Path) -> dict[str, Any]:
    """Run one registered parser over the staged input; return JSON-serializable dict.

    Pure/contained work — intended to run inside the sandboxed subprocess, but is
    a plain callable so it is independently unit-testable.
    """
    raw = input_path.read_bytes()
    if parser == "txt":
        return normalize_txt(raw).to_dict()
    if parser == "markdown":
        return parse_markdown(normalize_txt(raw).text).to_dict()
    if parser == "epub":
        return extract_epub(input_path).to_dict()
    if parser == "pdf":
        return detect_pdf_text(input_path).to_dict()
    raise ValueError(f"unknown parser {parser!r}")


def route_for(parser: str, document: dict[str, Any]) -> str:
    """Deterministic modality routing from a parsed document."""
    if parser == "pdf":
        has_text = bool(document.get("has_any_text"))
        return "text" if has_text else "image_raster"
    return "text"


def _parse_and_route(parser: str, input_path: Path) -> dict[str, Any]:
    doc = parse_document(parser, input_path)
    return {
        "parser": parser,
        "route": route_for(parser, doc),
        "document": doc,
    }


def invoke_parser(
    sandbox: SandboxRunner,
    parser: str,
    raw: bytes,
    *,
    name: str = "input",
    limits: SandboxLimits | None = None,
    policy: SandboxPolicy | None = None,
) -> ParsedSource:
    """Stage ``raw`` and invoke ``parser`` through the sandbox runner.

    :raises SandboxParseError: the parser process failed (crash/timeout/denied).
    """
    if parser not in {"txt", "markdown", "epub", "pdf"}:
        raise ValueError(f"unknown parser {parser!r}")

    limits = limits or SandboxLimits()
    with tempfile.TemporaryDirectory(prefix="umd_spool_") as tmp:
        spool_root = Path(tmp)
        input_path = stage_spool(raw, f"{name}.{_EXT[parser]}", spool_root)
        argv = [sys.executable, "-m", _ENTRYPOINT_MODULE, parser, str(input_path)]
        policy = policy or SandboxPolicy(
            allowed_modules=(_ENTRYPOINT_MODULE,),
            allowed_extensions=(_EXT[parser],),
        )
        result = sandbox.run(argv, limits=limits, policy=policy)
        if not result.ok:
            raise SandboxParseError(parser, result)
        try:
            payload = json.loads(result.stdout)
        except (json.JSONDecodeError, ValueError) as exc:
            raise SandboxParseError(
                parser, result, f"parser emitted non-JSON stdout: {exc}"
            ) from exc
        return ParsedSource(
            parser=payload.get("parser", parser),
            route=payload.get("route", "text"),
            document=payload.get("document", {}),
            input_path=str(input_path),
            sandbox_result=result,
        )


class SandboxParseError(RuntimeError):
    """A parser failed inside the sandbox (crash/timeout/denied/non-JSON)."""

    def __init__(self, parser: str, result: SandboxResult, detail: str | None = None) -> None:
        msg = (
            f"parser {parser!r} failed in sandbox (exit={result.exit_code}, "
            f"timeout={result.timed_out}, denied={result.policy_denied})"
        )
        if detail:
            msg += f": {detail}"
        super().__init__(msg)
        self.parser = parser
        self.result = result


#: File extension used when naming the spooled input per parser.
_EXT: dict[str, str] = {
    "txt": "txt",
    "markdown": "md",
    "epub": "epub",
    "pdf": "pdf",
}


def main(argv: list[str] | None = None) -> int:
    """Command-line entrypoint run *inside* the sandboxed subprocess.

    Usage: ``python -m umd.extractors.dispatch <parser> <input_path>`` — reads the
    staged read-only input and prints the parsed+route JSON blob to stdout.
    """
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        print("usage: dispatch <parser> <input_path>", file=sys.stderr)
        return 2
    parser, input_path = args[0], Path(args[1])
    try:
        payload = _parse_and_route(parser, input_path)
    except (EpubParseError, PdfParseError, OSError, ValueError) as exc:
        print(f"parser error: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(payload, sort_keys=True, ensure_ascii=True))
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised via subprocess
    raise SystemExit(main())
