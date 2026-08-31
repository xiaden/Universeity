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


# =============================================================================
# Plan L P1-S1: shared production text-dispatch result
#
# One format-aware route for the production FORMAT_ANALYSIS / BASIC_SEGMENTATION
# / LOW_LEVEL_EXTRACTION stages (CONTRACTS.md:74 ``TextDispatch``). It records
# the format, parser, route, normalized document structure, structural
# locators/segment IDs and warnings WITHOUT exposing raw binary as normalized
# text — non-text/degraded routes carry an explicit status and no fabricated
# text. Later phases depend on this shape.
# =============================================================================

#: Stable configuration digest for the production text dispatch (evidence
#: ``uq_evidence_identity`` dedup and rerun determinism need a non-null digest).
_TEXT_DISPATCH_CONFIG_DIGEST = "umd-dispatch@1"

#: Deterministic parser/decoder version tags per dispatched format (provenance).
_PARSER_VERSIONS: dict[str, str] = {
    "txt": "umd-txt@1",
    "markdown": "umd-markdown@1",
    "epub": "umd-epub-stdlib@1",
    "pdf": "umd-pdf-pypdf@1",
}
_DECODER_VERSIONS: dict[str, str] = {
    "txt": "umd-stdlib-decode@1",
    "markdown": "umd-stdlib-decode@1",
    "epub": "umd-zip-xml@1",
    "pdf": "umd-pypdf@1",
}

#: Formats that have a dedicated text parser. Anything else (empty/unknown) keeps
#: the deterministic plain-text baseline with an explicit warning.
_KNOWN_TEXT_FORMATS = {"txt", "markdown", "epub", "pdf"}


@dataclass
class TextDispatchResult:
    """Shared production text-dispatch result (Plan L P1-S1).

    One format-aware route that records the parser, route, normalized document
    structure, warnings, provenance and source fixity for a text/book source
    without ever surfacing raw binary as normalized text. Non-text/degraded
    routes carry an explicit status (``route``/``non_text``/``degraded``) and an
    empty ``text`` so the caller never fabricates prose from binary bytes.

    :meth:`segment` runs the format-appropriate segmenter (the pairing the plan
    requires: TXT→``segment_txt``, Markdown→``segment_markdown``, EPUB→
    ``segment_epub``, text PDF→the extracted text via ``segment_txt``) and
    records the registered structural locators/segment IDs for downstream
    evidence linking. It returns None on non-text/degraded routes (never
    segments binary as plain text).
    """

    format: str
    parser: str
    route: str  # "text" | "image_raster" | "unsupported" | "degraded"
    document: Any  # NormalizedText | MarkdownDocument | EpubDocument | PdfTextResult | None
    text: str = ""
    warnings: list[str] = field(default_factory=list)
    degraded: bool = False
    non_text: bool = False
    parser_version: str = _PARSER_VERSIONS["txt"]
    decoder_version: str = _DECODER_VERSIONS["txt"]
    config_digest: str = _TEXT_DISPATCH_CONFIG_DIGEST
    source_sha512: str | None = None
    #: structural path -> canonical locator / segment id (populated by segment()).
    locators: dict[str, str] = field(default_factory=dict)
    segment_ids: dict[str, str] = field(default_factory=dict)

    def segment(
        self,
        registry: Any,
        *,
        source_id: str,
        source_sha512: str,
        work_id: str | None = None,
    ) -> Any:
        """Run the format-appropriate segmenter and record structural locators.

        Returns a :class:`~umd.segmentation.segmenters.SegmentationResult`, or
        None when this is a non-text/degraded route (never segments binary bytes
        as plain text).
        """
        if self.route != "text" or self.document is None:
            return None
        from umd.segmentation.segmenters import segment_epub, segment_markdown, segment_txt

        if self.parser == "markdown":
            out = segment_markdown(
                registry,
                source_id=source_id,
                source_sha512=source_sha512,
                work_id=work_id,
                doc=self.document,
            )
        elif self.parser == "epub":
            out = segment_epub(
                registry,
                source_id=source_id,
                source_sha512=source_sha512,
                work_id=work_id,
                doc=self.document,
            )
        else:  # txt (and text PDFs — the extracted text, never raw bytes)
            out = segment_txt(
                registry,
                source_id=source_id,
                source_sha512=source_sha512,
                work_id=work_id,
                text=self.text,
            )
        for seg in out.batch.created:
            self.locators[seg.structural_path] = seg.locator
            self.segment_ids[seg.structural_path] = seg.segment_id
        return out


def _epub_text(doc: Any) -> str:
    """Flatten an extracted EPUB's spine paragraphs into normalized text."""
    return "\n\n".join("\n\n".join(p.text for p in item.paragraphs) for item in doc.spine)


def _pdf_text(result: Any) -> str:
    """Flatten a text PDF's per-page text layer into normalized text."""
    return "\n\n".join(p.text for p in result.pages if p.text)


def dispatch_text(
    raw: bytes,
    *,
    format: str | None,
    source_sha512: str | None = None,
) -> TextDispatchResult:
    """Format-aware production text dispatch (Plan L P1-S1).

    Routes one source's bytes to its parser/segmenter pair: TXT →
    ``normalize_txt``, Markdown → ``parse_markdown``, EPUB → the safe stdlib
    ``extract_epub``, PDF → the existing PDF text-layer path. Unknown/unsupported
    text formats keep the deterministic plain-text baseline with an explicit
    warning. Unreadable / image-only / unsupported routes carry an explicit
    non-text/degraded status and NO fabricated text.
    """
    fmt = (format or "").lower()
    warnings: list[str] = []

    if fmt not in _KNOWN_TEXT_FORMATS:
        if fmt:
            warnings.append(
                f"unsupported/unknown text format {format!r}; using plain-text baseline"
            )
        fmt = "txt"

    if fmt == "markdown":
        normalized = normalize_txt(raw)
        md_doc = parse_markdown(normalized.text)
        return TextDispatchResult(
            format="markdown",
            parser="markdown",
            route="text",
            document=md_doc,
            text=normalized.text,
            warnings=warnings + list(normalized.warnings),
            parser_version=_PARSER_VERSIONS["markdown"],
            decoder_version=_DECODER_VERSIONS["markdown"],
            source_sha512=source_sha512,
        )

    if fmt == "epub":
        try:
            with tempfile.NamedTemporaryFile(suffix=".epub", delete=False) as tf:
                tf.write(raw)
                tf_path = Path(tf.name)
            try:
                epub_doc = extract_epub(tf_path)
            finally:
                tf_path.unlink(missing_ok=True)
        except EpubParseError as exc:
            return TextDispatchResult(
                format="epub",
                parser="epub",
                route="degraded",
                document=None,
                text="",
                warnings=warnings + [f"epub parse failed: {exc}"],
                degraded=True,
                non_text=True,
                parser_version=_PARSER_VERSIONS["epub"],
                decoder_version=_DECODER_VERSIONS["epub"],
                source_sha512=source_sha512,
            )
        return TextDispatchResult(
            format="epub",
            parser="epub",
            route="text",
            document=epub_doc,
            text=_epub_text(epub_doc),
            warnings=warnings + list(epub_doc.warnings),
            parser_version=_PARSER_VERSIONS["epub"],
            decoder_version=_DECODER_VERSIONS["epub"],
            source_sha512=source_sha512,
        )

    if fmt == "pdf":
        try:
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as tf:
                tf.write(raw)
                tf_path = Path(tf.name)
            try:
                result = detect_pdf_text(tf_path)
            finally:
                tf_path.unlink(missing_ok=True)
        except PdfParseError as exc:
            return TextDispatchResult(
                format="pdf",
                parser="pdf",
                route="degraded",
                document=None,
                text="",
                warnings=warnings + [f"pdf parse failed: {exc}"],
                degraded=True,
                non_text=True,
                parser_version=_PARSER_VERSIONS["pdf"],
                decoder_version=_DECODER_VERSIONS["pdf"],
                source_sha512=source_sha512,
            )
        if not result.has_any_text:
            return TextDispatchResult(
                format="pdf",
                parser="pdf",
                route="image_raster",
                document=result,
                text="",
                warnings=warnings
                + list(result.warnings)
                + ["pdf has no usable text layer; routed to raster/OCR"],
                non_text=True,
                parser_version=_PARSER_VERSIONS["pdf"],
                decoder_version=_DECODER_VERSIONS["pdf"],
                source_sha512=source_sha512,
            )
        return TextDispatchResult(
            format="pdf",
            parser="pdf",
            route="text",
            document=result,
            text=_pdf_text(result),
            warnings=warnings + list(result.warnings),
            parser_version=_PARSER_VERSIONS["pdf"],
            decoder_version=_DECODER_VERSIONS["pdf"],
            source_sha512=source_sha512,
        )

    # TXT (and unknown text-like formats): deterministic plain-text baseline.
    normalized = normalize_txt(raw)
    return TextDispatchResult(
        format="txt",
        parser="txt",
        route="text",
        document=normalized,
        text=normalized.text,
        warnings=warnings + list(normalized.warnings),
        parser_version=_PARSER_VERSIONS["txt"],
        decoder_version=_DECODER_VERSIONS["txt"],
        source_sha512=source_sha512,
    )


class TextDispatch:
    """Contract boundary for the production text dispatch (CONTRACTS.md:74).

    ``TextDispatch.dispatch(source, raw_or_native) -> TextDispatchResult`` — a
    thin adapter over :func:`dispatch_text` so the contract name is importable
    by later phases and by the production stage registry.
    """

    @staticmethod
    def dispatch(source: Any, raw_or_native: Any) -> TextDispatchResult:
        fmt: str | None = None
        sha: str | None = None
        if isinstance(source, dict):
            fmt = source.get("format")
            sha = source.get("sha512")
        elif source is not None:
            fmt = getattr(source, "format", None)
            sha = getattr(source, "sha512", None)
        if isinstance(raw_or_native, (bytes, bytearray)):
            raw = bytes(raw_or_native)
        else:
            raw = bytes(getattr(raw_or_native, "data", b"") or b"")
        return dispatch_text(raw, format=fmt, source_sha512=sha)


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
