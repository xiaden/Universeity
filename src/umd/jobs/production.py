"""Production stage composition (Phase 2, Plan G — real stage work).

Composes every canonical ``STAGE_ORDER`` stage into a
:class:`StageWorkRegistry` of **real, executable work** through a single factory
(CONTRACTS.md "Production execution remediation contracts":60):

    StageWorkRegistryFactory.build(runtime) -> StageWorkRegistry
    build_runtime(**deps)                     -> ProductionRuntime

``runtime`` is a :class:`ProductionRuntime` (or a dependency dict). The only
required key is ``engine`` (the Postgres engine). Optional fields let downstream
plans bind heavier processors without changing the factory contract:

  * ``commands``    — :class:`SemanticCommandService`; semantic-bearing stages
    route structured results through the ledger command path when provided.
  * ``source_store`` — :class:`umd.storage.ocfl.SourceStore`; format/segmentation/
    extraction stages read the committed immutable source bytes when provided.
  * ``replay``      — :class:`ReplayDriver`; the projection stage schedules the
    sanctioned Tier-1 builder (the only writer to its projection store).
  * ``builders``    — dict of Tier-1 projection builders keyed by ``projection_name``.

When the real deps are absent (e.g. the registry tests build with just an
engine), each stage still emits a deterministic, provenance-bearing output
derived from *committed upstream state* — so the registry is fully composed and
callable without a live sandbox/ML runtime, while still degrading honestly
(a warning is recorded on every degradation).

The real bindings (activated when the runtime supplies the processors):

  * ``FORMAT_ANALYSIS`` — reads the committed OCFL bytes (bounded range), routes
    them through ONE format-aware dispatch (:class:`umd.extractors.dispatch`
    ``dispatch_text``: TXT → ``normalize_txt``, Markdown → ``parse_markdown``,
    EPUB → the safe stdlib ``extract_epub``, PDF → the existing PDF text-layer
    path), and records a durable format_analysis evidence row carrying the
    dispatched parser/route + source fixity.
  * ``BASIC_SEGMENTATION`` — reuses the SAME dispatched result and runs the
    format-appropriate segmenter (``segment_txt`` / ``segment_markdown`` /
    ``segment_epub``; text PDFs segment via ``segment_txt`` over the extracted
    text), registering the native segment hierarchy through
    :class:`SegmentRegistry`/``PostgresSegmentStore``.
  * ``LOW_LEVEL_EXTRACTION`` — emits per-segment ``text_span`` evidence rows from
    the dispatched document's structural paths, with ``segment_id`` pinned to the
    committed ``segment`` rows and the segment's canonical ``source://`` locator.
  * ``STRUCTURAL_ANALYSIS`` — consumes the SAME dispatched document (one result
    per source shared across the text stages), runs :func:`analyze_text` over its
    paragraphs, and records dialogue/narration + candidate evidence. For
    image-only (route=``image_raster``), degraded, or unsupported inputs it emits
    an explicit warning and NO fabricated text evidence.
  * ``ENTITY_RESOLUTION`` — derives candidate mentions from committed structural
    evidence and routes reversible MENTION/ALIAS/MERGE resolution through the
    command path.
  * ``CROSS_SOURCE_ALIGNMENT`` — single-source runs are a deterministic no-op
    that still records a source-continuity ``Aligned`` event when commands exist.
  * ``SEMANTIC_RECONCILIATION`` — drives the deterministic
    :class:`umd.reconciliation.reconciler.SemanticReconciler` over the committed
    typed observations + resolved entities and routes every assertion through the
    ledger command path (each ``SemanticAsserted`` is also materialized into the
    read-side ``semantic_assertion`` table in the same transaction).
  * ``CURRENT_SEARCH_PROJECTION`` — replay-only: schedules the sanctioned
    Tier-1 builder through the :class:`ReplayDriver` (never writes projection
    tables directly).

Invariants enforced here (the binding contract the spec-first registry tests pin):

  * every stage in ``STAGE_ORDER`` resolves to callable work — an *absent* stage
    is a configuration failure and ``build`` raises, never a silent success;
  * stage work performs no subprocess dispatch itself (sandbox entrypoints only)
    and never writes Tier-1 projections or appends semantic events directly —
    the :class:`DurableStageExecutor` owns ``StageCompleted`` atomic completion
    and semantic events flow through the command path;
  * each stage reads its upstream committed outputs by source id / evidence refs
    and returns a :class:`StageOutcome` whose refs are provenance-bearing.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import sqlalchemy as sa
from pydantic import ValidationError

from umd.analysis.semantic import (
    ContextObservation,
    DescriptiveTrait,
    EmotionObservation,
    EntityMention,
    NormalizedAlias,
    Presence,
    RelationshipCandidate,
    SceneBoundary,
    SemanticCandidate,
    SpeakerCandidate,
    StateObservation,
    Utterance,
)
from umd.analysis.semantic_analyzer import SemanticAnalysisInput, SemanticTextAnalyzer
from umd.analysis.text_structural import ParagraphSegment
from umd.domain.evidence import EvidenceBatch
from umd.domain.models import (
    ConfidenceState,
    Evidence,
    EvidenceKind,
)
from umd.jobs.dag import STAGE_ORDER
from umd.jobs.manifest import StageManifest
from umd.jobs.runner import StageWorkRegistry
from umd.jobs.stage_execution import (
    MalformedInputError,
    StageOutcome,
    StageWork,
)
from umd.models.registry import ProviderRegistry
from umd.projections.current import CurrentTierOneBuilder
from umd.resolution.mentions import SourceMention
from umd.segmentation.registry import SegmentRegistry
from umd.storage.postgres.repositories import (
    PostgresEvidenceRepository,
    PostgresSegmentStore,
)
from umd.storage.postgres.tables import metadata as db_meta

_source_t = db_meta.tables["source"]
_segment_t = db_meta.tables["segment"]

#: Stable per-binding configuration digests for production evidence recorders.
#: Each recorder tags every Evidence it produces with these so `uq_evidence_identity`
#: (source_id, locator, evidence_kind, config_digest) dedups identical re-records on a
#: re-run -- a NULL digest would treat re-recorded rows as distinct and duplicate them
#: (CONTRACTS.md:12 evidence batches carry a configuration digest). Bump the suffix
#: only when the producing binding's configuration/behaviour changes in a way that
#: materially affects the evidence it emits.
_TEXT_EVIDENCE_CONFIG_DIGEST = "umd-txt@1"  # plain-text normalization/evidence bindings
_MEDIA_FORMAT_EVIDENCE_CONFIG_DIGEST = "umd-format@1"  # non-text media format analysis
#: Stable per-binding config digest for the entity-resolution stage decisions
#: (carried as ``generated_by`` on every ResolutionBatch output; never NULL).
_ENTITY_RESOLUTION_CONFIG_DIGEST = "umd-entity-resolution@1"
#: Base prefix for the video-stage audio-ASR branch evidence config digest. Unlike
#: the other static per-binding digests, the video audio-ASR digest MUST encode the
#: ASR engine + model id (see ``_video_audio_config_digest``): `uq_evidence_identity`
#: (source_id, locator, evidence_kind, config_digest) dedups identical re-records on a
#: re-run, and a static digest would silently retain the prior engine's transcript
#: rows when a rerun switches engine/model. Append the provider + model_id so the
#: quadruple differs across engines/models.
_VIDEO_AUDIO_EVIDENCE_CONFIG_DIGEST_PREFIX = "umd-video-audio"

#: Base prefix for the per-dispatch evidence config digest when the dispatch result
#: does not itself carry a config digest (the dispatch seam always sets one, so this
#: only guards direct recorder calls in tests).
_DISPATCH_BASE_DIGEST = "umd-dispatch"


def _dispatch_evidence_config_digest(result: Any) -> str:
    """Deterministic evidence config digest derived from a dispatch result (P2-S2).

    Encodes the base dispatch config digest PLUS the dispatched parser and decoder
    versions so ``uq_evidence_identity`` ``(source_id, locator, evidence_kind,
    config_digest)`` satisfies the Plan-L P2-S2 identity contract:

      * identical source/parser/config reruns derive the SAME digest -> the re-record
        dedups against the unique index (no duplicate rows);
      * a changed parser/config/decoder version derives a DIFFERENT digest -> a
        distinct evidence row is produced WITHOUT mutating historical rows (the old
        rows keep their original digest and are never UPDATE'd).
    """
    base = getattr(result, "config_digest", None) or _DISPATCH_BASE_DIGEST
    parser = getattr(result, "parser_version", None) or "umd-txt@1"
    decoder = getattr(result, "decoder_version", None) or "umd-stdlib-decode@1"
    return f"{base}:{parser}:{decoder}"


def _dispatch_versions(result: Any) -> tuple[str, str]:
    """(parser_version, decoder_version) from a dispatch result, defaulting to the
    plain-text baseline when none is carried (direct recorder calls in tests)."""
    parser = getattr(result, "parser_version", None) or "umd-txt@1"
    decoder = getattr(result, "decoder_version", None) or "umd-stdlib-decode@1"
    return parser, decoder


def _video_audio_config_digest(asr: Any | None) -> str:
    """Config digest for the video-stage audio-ASR branch evidence recorder.

    Encodes the actual ASR engine + model id observed at run time so that
    ``uq_evidence_identity`` (source_id, locator, evidence_kind, config_digest) does
    NOT silently retain a prior engine's/model's transcript rows when a rerun of the
    video branch switches engine (reference → faster-whisper) or model. Mirrors how
    the base audio path distinguishes engines via ``config_digest_of``; the video
    branch has no in-hand ``AudioConfig`` so it derives the digest from the worker's
    dispatched ``AsrResult`` (the same provider/model id ``_stamp_asr_provenance``
    reads). Falls back to a bare prefix when model_id is absent (e.g. a provider
    model is never set) so the digest is always non-null for evidence dedup.
    """
    if asr is not None and getattr(asr, "provider", None):
        model_id = getattr(asr, "model_id", None) or "default"
        return f"{_VIDEO_AUDIO_EVIDENCE_CONFIG_DIGEST_PREFIX}@{asr.provider}:{model_id}"
    return f"{_VIDEO_AUDIO_EVIDENCE_CONFIG_DIGEST_PREFIX}@unknown"


class ConfigurationError(ValueError):
    """The production registry is misconfigured (a canonical stage is absent)."""


def _source_row(engine: sa.Engine, source_id: str | None) -> dict[str, Any] | None:
    """Read the committed source row (content-addressed OCFL ref + metadata)."""
    if not source_id:
        return None
    try:
        sid: uuid.UUID | str = uuid.UUID(source_id)
    except ValueError:
        sid = source_id  # non-UUID id (defensive; production ids are UUIDs)
    with engine.connect() as conn:
        row = conn.execute(sa.select(_source_t).where(_source_t.c.id == sid)).first()
    if row is None:
        return None
    return {
        "id": str(row.id),
        "ocfl_ref": row.ocfl_ref,
        "sha512": str(row.sha512),
        "size_bytes": int(row.size_bytes),
        "media_kind": row.media_kind,
        "format": row.format,
    }


def _paragraphs(text: str) -> list[str]:
    """Deterministic blank-line paragraph split (matches the txt segmenter)."""
    blocks = [b.strip() for b in re.split(r"\n\s*\n", text)]
    return [b for b in blocks if b]


def _structural_path_key(path: str) -> tuple[tuple[int, str | int], ...]:
    """Deterministic document-order sort key for a structural path (Plan L P2-S1).

    Splits a path like ``chapter/1/section/1/paragraph/2`` into positional
    components — numeric segments as ``(1, int)`` and named segments as
    ``(0, str)`` — so sorting by this key reproduces reading order for the
    txt/markdown/epub hierarchies. The type-tagged tuples always compare safely
    (same-tag components share a value type). Used to pair low-level paragraph
    evidence with its registered segment by ``structural_path`` instead of
    positionally, so a partial-batch crash/retry that interleaves created and
    existing rows can never pin paragraph text to the wrong segment id.
    """
    return tuple((1, int(part)) if part.isdigit() else (0, part) for part in path.split("/"))


def _chapter_number(path: str) -> int:
    """Chapter index from a structural path like ``chapter/2/paragraph/3`` (default 1)."""
    m = re.search(r"(?:^|/)chapter/(\d+)(?:/|$)", path)
    return int(m.group(1)) if m else 1


def _paragraph_number(path: str) -> int:
    """Paragraph index from a structural path like ``chapter/2/paragraph/3`` (default 0)."""
    m = re.search(r"(?:^|/)paragraph/(\d+)(?:/|$)", path)
    return int(m.group(1)) if m else 0


@dataclass
class ProductionRuntime:
    """Runtime dependencies for production stage work (Phase 2 real bindings).

    Only ``engine`` is required. Optional fields activate the *real* stage
    bindings; when absent the stage degrades to a deterministic, provenance-
    bearing output derived from committed state (and records a warning).
    """

    engine: sa.Engine
    settings: Any = None
    source_store: Any = None
    commands: Any = None
    ledger: Any = None
    segmenters: dict[str, Any] | None = None
    sandbox: Any = None
    dispatch: Any = None
    providers: Any = None
    builders: Any = None
    replay: Any = None
    observability: Any = None
    capabilities: Any = None
    evidence: Any = None
    segments: Any = None
    artifacts: Any = None

    @classmethod
    def from_mapping(cls, runtime: Any) -> ProductionRuntime:
        """Coerce a dependency dict (or an existing runtime) into a runtime."""
        if isinstance(runtime, cls):
            return runtime
        if not isinstance(runtime, dict):
            raise ConfigurationError("production runtime must be a mapping or a ProductionRuntime")
        engine = runtime.get("engine")
        if engine is None:
            raise ConfigurationError(
                "production registry requires a Postgres engine in runtime['engine']"
            )
        return cls(
            engine=engine,
            settings=runtime.get("settings"),
            source_store=runtime.get("source_store"),
            commands=runtime.get("commands"),
            ledger=runtime.get("ledger"),
            segmenters=runtime.get("segmenters"),
            sandbox=runtime.get("sandbox"),
            dispatch=runtime.get("dispatch"),
            providers=runtime.get("providers"),
            builders=runtime.get("builders"),
            replay=runtime.get("replay"),
            observability=runtime.get("observability"),
            capabilities=runtime.get("capabilities"),
            evidence=runtime.get("evidence"),
            segments=runtime.get("segments"),
            artifacts=runtime.get("artifacts"),
        )


def build_runtime(
    *,
    engine: sa.Engine,
    settings: Any = None,
    source_store: Any = None,
    commands: Any = None,
    ledger: Any = None,
    segmenters: dict[str, Any] | None = None,
    sandbox: Any = None,
    dispatch: Any = None,
    providers: Any = None,
    builders: Any = None,
    replay: Any = None,
    observability: Any = None,
    capabilities: Any = None,
    **extra: Any,
) -> ProductionRuntime:
    """Factory building a fully-wired :class:`ProductionRuntime`.

    Phase 3's ``build_context`` calls this with the pieces it already assembles
    (engine, source_store, commands, ledger, segmenters, sandbox, dispatch,
    providers, builders, ...) and passes the result to
    :meth:`StageWorkRegistryFactory.build` — the production registry reads only
    committed state and never writes projections/events directly.
    """
    return ProductionRuntime(
        engine=engine,
        settings=settings,
        source_store=source_store,
        commands=commands,
        ledger=ledger,
        segmenters=segmenters,
        sandbox=sandbox,
        dispatch=dispatch,
        providers=providers,
        builders=builders,
        replay=replay,
        observability=observability,
        capabilities=capabilities,
        **extra,
    )


#: Plan R P1-S2 category dispatch for rehydrating committed
#: ``semantic_observations`` evidence. Each entry is ``(SemanticAnalysisResult
#: bucket attr, candidate class, category-discriminating key)``. The
#: discriminator key is the category-specific required field, unique across the
#: typed contract, so a serialized observation payload classifies unambiguously.
_PROVIDER_OBSERVATION_DISPATCH: tuple[tuple[str, type[SemanticCandidate], str], ...] = (
    ("scene_boundaries", SceneBoundary, "scene_ref"),
    ("entity_mentions", EntityMention, "mention"),
    ("aliases", NormalizedAlias, "canonical_name"),
    ("presence", Presence, "present_in"),
    ("utterances", Utterance, "utterance_text"),
    ("speaker_candidates", SpeakerCandidate, "speaker_label"),
    ("traits", DescriptiveTrait, "trait"),
    ("relationships", RelationshipCandidate, "predicate"),
    ("emotions", EmotionObservation, "emotion"),
    ("states", StateObservation, "observed_state"),
    ("context", ContextObservation, "context_type"),
)


def _classify_provider_observation(
    payload: dict[str, Any],
) -> tuple[str | None, type[SemanticCandidate] | None]:
    """Explicit category/type discrimination for one serialized observation.

    Returns ``(result-bucket attr, candidate class)`` when exactly one category
    key is present, else ``(None, None)`` — an unknown category or an ambiguous
    payload (more than one category key) is rejected rather than guessed.
    """
    matches = [(attr, cls) for attr, cls, key in _PROVIDER_OBSERVATION_DISPATCH if key in payload]
    if len(matches) == 1:
        return matches[0]
    return None, None


def _hydrate_provider_observations(
    evidence_rows: Sequence[Evidence], locators: set[str]
) -> tuple[dict[str, list[SemanticCandidate]], list[str]]:
    """Rehydrate committed, validated ``semantic_observations`` evidence (Plan R).

    Purely a projection over committed evidence — it never invokes a provider,
    constructs a second analyzer, or reads raw/unvalidated model output. Only
    known-category, well-formed payloads whose exact segment locator is a member
    of ``locators`` are rehydrated into typed candidate buckets. Unknown or
    ambiguous categories, malformed payloads, and invented segment support are
    rejected with a truthful warning (never repaired, never promoted). No refs
    are fabricated: each candidate is re-validated through its existing typed
    Pydantic model, preserving its serialized ``SegmentEvidenceRef``, evidence
    reference, confidence, semantic state, and ``GeneratedBy`` provenance.
    """
    buckets: dict[str, list[SemanticCandidate]] = {
        attr: [] for attr, _, _ in _PROVIDER_OBSERVATION_DISPATCH
    }
    warnings: list[str] = []
    for ev in evidence_rows:
        quality = ev.quality or {}
        if quality.get("kind") != "semantic_observations":
            continue
        raw = quality.get("observations")
        if not isinstance(raw, list):
            warnings.append(
                f"semantic_observations evidence {ev.id}: 'observations' is not a list; "
                "provider observations not rehydrated"
            )
            continue
        for i, payload in enumerate(raw):
            if not isinstance(payload, dict):
                warnings.append(
                    f"semantic_observations evidence {ev.id}: observation[{i}] is not an "
                    "object; rejected (not promoted)"
                )
                continue
            attr, cls = _classify_provider_observation(payload)
            if cls is None or attr is None:
                warnings.append(
                    f"semantic_observations evidence {ev.id}: observation[{i}] has an "
                    "unknown or ambiguous category; rejected (not promoted)"
                )
                continue
            try:
                obs = cls.model_validate(payload)
            except ValidationError as exc:
                warnings.append(
                    f"semantic_observations evidence {ev.id}: malformed "
                    f"{cls.__name__} observation[{i}]: {exc}; rejected (not promoted)"
                )
                continue
            if obs.segment.locator not in locators:
                warnings.append(
                    f"semantic_observations evidence {ev.id}: {cls.__name__} observation[{i}] "
                    f"lacks exact input-segment support ({obs.segment.locator!r}); not promoted"
                )
                continue
            buckets[attr].append(obs)
    return buckets, warnings


class _Composer:
    """Composes the nine canonical stages into real work over committed state."""

    def __init__(self, engine: sa.Engine, runtime: ProductionRuntime) -> None:
        self._engine = engine
        self._runtime = runtime
        self._segments = PostgresSegmentStore(engine)
        self._evidence = PostgresEvidenceRepository(engine)
        #: Per-source memo of the ONE format-aware dispatch result (Plan L P1-S3).
        #: All four text stages (FORMAT_ANALYSIS / BASIC_SEGMENTATION /
        #: LOW_LEVEL_EXTRACTION / STRUCTURAL_ANALYSIS) share this so a full DAG run
        #: dispatches each source exactly once and every stage observes the SAME
        #: parser/document/hierarchy. Keyed by (source id, content sha512, format) —
        #: a changed source/format derives a fresh dispatch.
        self._dispatch_cache: dict[str, Any] = {}

    def _opt(self, key: str) -> Any:
        return getattr(self._runtime, key)

    # -- shared dependency-gating helpers ----------------------------------

    def _require_source(self, manifest: StageManifest) -> dict[str, Any]:
        src = _source_row(self._engine, manifest.source_id)
        if src is None:
            raise MalformedInputError(
                f"source {manifest.source_id} is not committed before {manifest.stage_name}",
                f"source:{manifest.source_id}",
            )
        return src

    def _max_read(self) -> int:
        settings = self._runtime.settings
        if settings is not None:
            limits = getattr(settings, "limits", None)
            if limits is not None:
                return int(getattr(limits, "max_read_buffer_bytes", 1024 * 1024))
        return 1024 * 1024

    def _raw_bytes(self, src: dict[str, Any]) -> bytes | None:
        store = self._runtime.source_store
        if store is None:
            return None
        try:
            rep = store.get_range(src["ocfl_ref"], 0, self._max_read())
            data: bytes = rep.data
            return data
        except Exception:  # noqa: BLE001 - degrade to committed-state refs
            return None

    def _dispatch_text(self, src: dict[str, Any]) -> Any | None:
        """ONE format-aware text dispatch for a committed source (Plan L P1-S2).

        Reads the committed OCFL bytes and routes them through the shared
        ``umd.extractors.dispatch`` seam by format (TXT → ``normalize_txt``/
        ``segment_txt``, Markdown → ``parse_markdown``/``segment_markdown``,
        EPUB → the safe stdlib ``extract_epub``/``segment_epub``, PDF → the
        existing PDF text-layer path). Returns a ``TextDispatchResult``, or None
        when the source bytes are unavailable (no ``source_store`` / unreadable)
        so the caller degrades to a committed-state ref. Non-text routes
        (image-only PDF) and degraded routes carry explicit status on the result
        — raw binary is never surfaced as normalized text.

        The result is **memoized per source** (Plan L P1-S3): all four text
        stages — FORMAT_ANALYSIS, BASIC_SEGMENTATION, LOW_LEVEL_EXTRACTION and
        STRUCTURAL_ANALYSIS — consume the SAME dispatched document for one
        source, so a full-DAG run dispatches once and every stage observes the
        same parser/document/hierarchy (never an independent re-dispatch that
        re-normalizes raw EPUB/PDF bytes through TXT). A changed source content
        (sha512) or format derives a fresh dispatch.

        ``umd.extractors.*`` is the sandbox-owned decoder root, so the dispatch
        module is imported lazily (in-method), mirroring how the raster/video/
        audio/subtitle branches lazily import their decoder roots
        (``test_production_modules_do_not_import_decoders_in_process``).
        ``runtime.dispatch`` (if supplied) overrides the default dispatcher so
        later phases can bind an equivalent ``TextDispatch`` implementation.
        """
        cache_key = f"{src['id']}:{src.get('sha512')}:{src.get('format') or 'txt'}"
        cached = self._dispatch_cache.get(cache_key)
        if cached is not None:
            return cached
        store = self._runtime.source_store
        if store is None:
            self._dispatch_cache[cache_key] = None
            return None
        raw = self._raw_bytes(src)
        if raw is None:
            self._dispatch_cache[cache_key] = None
            return None
        fmt = src.get("format") or "txt"
        dispatcher = self._runtime.dispatch
        result: Any | None = None
        if dispatcher is not None:
            if hasattr(dispatcher, "dispatch"):
                result = dispatcher.dispatch(src, raw)
            elif callable(dispatcher):
                result = dispatcher(raw, format=fmt, source_sha512=src.get("sha512"))
        else:
            from umd.extractors.dispatch import dispatch_text

            result = dispatch_text(raw, format=fmt, source_sha512=src.get("sha512"))
        self._dispatch_cache[cache_key] = result
        return result

    # -- durable evidence helpers -----------------------------------------

    @staticmethod
    def _corr(job_id: str) -> str:
        """Deterministic UUID correlation id derived from a job id.

        The ledger persists ``correlation_id`` in a UUID column, so a string job
        id must be mapped to a stable UUID rather than passed through verbatim.
        """
        return str(uuid.uuid5(uuid.NAMESPACE_URL, f"umd-job:{job_id}"))

    def _segment_row_ids(self, src: dict[str, Any]) -> dict[str, str]:
        """Map ``structural_path -> DB segment row id`` for a committed source."""
        with self._engine.connect() as conn:
            rows = conn.execute(
                sa.select(_segment_t.c.id, _segment_t.c.deterministic_key).where(
                    _segment_t.c.source_id == src["id"]
                )
            ).fetchall()
        out: dict[str, str] = {}
        for row in rows:
            key = str(row.deterministic_key)
            parts = key.split("#", 2)
            path = parts[2] if len(parts) == 3 else ""
            out[path] = str(row.id)
        return out

    def _record_format_evidence(
        self,
        src: dict[str, Any],
        text: str,
        *,
        format: str | None = None,
        parser: str | None = None,
        result: Any = None,
    ) -> str | None:
        """Record a durable format_analysis evidence row for a TEXT source.

        ``format``/``parser`` default to the plain-text baseline so callers (and
        the recorder-level test) that pass only text keep the txt tagging;
        FORMAT_ANALYSIS passes the dispatched format/parser so the evidence
        records the real route (Markdown/EPUB/PDF), never a TXT mislabel.

        When the dispatched ``result`` is supplied (Plan L P2-S1/S2) the row also
        carries the dispatched parser/decoder versions in ``tool_versions``, a
        config digest that encodes those versions (so changed parser/config remains
        distinguishable without mutating historical rows), the raw OCFL reference
        (``raw_ref``), and the source content sha512 in ``quality``.
        """
        locator = f"format_analysis:{src['id']}"
        fmt = format or "text/plain"
        route_parser = parser or (result.parser if result is not None else "txt") or "txt"
        if result is not None:
            parser_v, decoder_v = _dispatch_versions(result)
            tool_versions = {"format_analyzer": parser_v, "decoder": decoder_v}
            config_digest = _dispatch_evidence_config_digest(result)
        else:
            tool_versions = {"format_analyzer": f"umd-{route_parser}@1"}
            config_digest = _TEXT_EVIDENCE_CONFIG_DIGEST
        quality: dict[str, Any] = {
            "format": fmt,
            "route": "text",
            "parser": route_parser,
            "chars": len(text),
        }
        if src.get("sha512"):
            quality["source_sha512"] = src["sha512"]
        batch = EvidenceBatch(
            records=[
                Evidence(
                    source_id=uuid.UUID(src["id"]),
                    evidence_kind=EvidenceKind.METADATA,
                    locator=locator,
                    extraction_stage="FORMAT_ANALYSIS",
                    tool_versions=tool_versions,
                    config_digest=config_digest,
                    confidence=0.99,
                    quality=quality,
                    raw_ref=src.get("ocfl_ref"),
                )
            ]
        )
        self._evidence.record(batch)
        return locator

    def _span_evidence(
        self,
        src: dict[str, Any],
        segment_id: str,
        locator: str,
        confidence: float,
        text: str,
        *,
        stage: str,
        result: Any = None,
    ) -> Evidence:
        """Build a ``text_span`` evidence row linked to a registered segment.

        ``segment_id`` is the DB ``segment`` row id (FK) and ``locator`` is the
        segment's canonical ``source://`` locator (Plan L P2-S1) — never a bare
        structural path. When ``result`` is supplied the row carries the dispatched
        parser/decoder versions, a version-encoding config digest, the raw OCFL
        reference, and the source content sha512 in ``quality`` (P2-S1/S2).
        """
        if result is not None:
            parser_v, decoder_v = _dispatch_versions(result)
            tool_versions = {"extractor": parser_v, "decoder": decoder_v}
            config_digest = _dispatch_evidence_config_digest(result)
        else:
            tool_versions = {"extractor": "umd-txt@1"}
            config_digest = _TEXT_EVIDENCE_CONFIG_DIGEST
        quality: dict[str, Any] = {"text": text}
        if src.get("sha512"):
            quality["source_sha512"] = src["sha512"]
        return Evidence(
            source_id=uuid.UUID(src["id"]),
            segment_id=uuid.UUID(segment_id),
            evidence_kind=EvidenceKind.TEXT_SPAN,
            locator=locator,
            extraction_stage=stage,
            tool_versions=tool_versions,
            config_digest=config_digest,
            confidence=confidence,
            quality=quality,
            raw_ref=src.get("ocfl_ref"),
        )

    def _emit_low_level_text_evidence(self, src: dict[str, Any], result: Any) -> list[str]:
        """Emit per-segment ``text_span`` evidence pinned to the ACTUAL registered
        paragraph segment paths (Plan L P1-S3) — never hard-coded chapter/1.

        ``result.segment`` (idempotent re-registration) supplies the format-aware
        segment hierarchy so the evidence rows pin the same paths the
        BASIC_SEGMENTATION stage registered.
        """
        seg_result = result.segment(
            SegmentRegistry(self._segments),
            source_id=src["id"],
            source_sha512=src["sha512"],
            work_id=None,
        )
        if seg_result is None:
            return []
        ids = self._segment_row_ids(src)
        if not ids:
            return []
        records: list[Evidence] = []
        # Both newly-registered and idempotently-existing segments carry the exact
        # structural hierarchy, so a rerun emits the SAME set of evidence (deduped by
        # uq_evidence_identity) rather than only the doc row (Plan L P2-S2 determinism).
        all_segs = list(seg_result.batch.created) + list(seg_result.batch.existing)
        doc_seg = next((s for s in all_segs if s.structural_path == "document/1"), None)
        if doc_seg is not None:
            doc_id = ids.get("document/1")
            if doc_id is not None:
                records.append(
                    self._span_evidence(
                        src,
                        doc_id,
                        doc_seg.locator,
                        1.0,
                        result.text,
                        stage="LOW_LEVEL_EXTRACTION",
                        result=result,
                    )
                )
        # Pair paragraph evidence by structural_path (document order), NEVER
        # positionally against the created+existing concatenation: on a
        # partial-batch crash + retry those interleave non-contiguously, so a
        # positional zip would pin paragraph text to the WRONG segment id
        # (Plan L P2-S1/FINDING 2 provenance misattribution). Both sides are in
        # reading order, so sorting the segments by their path key aligns them
        # with ``seg_result.paragraphs`` regardless of the created/existing split.
        para_segs = sorted(
            (s for s in all_segs if s.segment_type == "paragraph"),
            key=lambda s: _structural_path_key(s.structural_path),
        )
        for seg, para in zip(para_segs, seg_result.paragraphs, strict=False):
            seg_id = ids.get(seg.structural_path)
            if seg_id is None:
                continue
            # Canonical source:// locator (seg.locator), never the bare structural
            # path (Plan L P2-S1): evidence links the exact registered segment.
            records.append(
                self._span_evidence(
                    src,
                    seg_id,
                    seg.locator,
                    0.9,
                    para,
                    stage="LOW_LEVEL_EXTRACTION",
                    result=result,
                )
            )
        if not records:
            return []
        self._evidence.record(EvidenceBatch(records=records))
        return [r.locator for r in records if r.locator]

    def _resolution_mentions(self, src: dict[str, Any]) -> list[SourceMention]:
        """Build deterministic :class:`SourceMention` records from committed evidence.

        Reads the committed structural candidate-evidence stream (the same
        ``candidate_kind == "entity"`` rows the legacy stage consumed), but
        constructs typed mentions keyed by source/segment/span identity (the
        deterministic sha256 mention id), so
        the resolution stage has the candidate/linkage inputs it needs and a
        rerun converges to the same mention rows. Purely a projection over
        committed evidence — it writes nothing.
        """
        from umd.resolution.candidates import normalize_name
        from umd.resolution.mentions import SourceMention, _deterministic_mention_id

        committed = self._evidence.get_by_source(src["id"])
        out: list[SourceMention] = []
        seen: set[str] = set()
        for ev in committed:
            quality = ev.quality or {}
            if quality.get("candidate_kind") != "entity":
                continue
            mention_text = quality.get("mention_text")
            if not mention_text:
                continue
            mid = _deterministic_mention_id(
                src["id"],
                str(ev.locator),
                str(ev.segment_id) if ev.segment_id else None,
                mention_text,
            )
            if mid in seen:
                continue
            seen.add(mid)
            meta: dict[str, Any] = {}
            if quality.get("entity_type"):
                meta["entity_type"] = str(quality["entity_type"])
            if quality.get("co_occurring"):
                meta["co_occurring"] = list(quality["co_occurring"])
            forms = quality.get("normalized_forms")
            if isinstance(forms, list) and forms:
                normalized_forms = [f for f in (normalize_name(f) for f in forms) if f]
            else:
                single = normalize_name(mention_text)
                normalized_forms = [single] if single else []
            out.append(
                SourceMention(
                    id=uuid.UUID(mid),
                    source_id=src["id"],
                    segment_id=ev.segment_id,
                    mention_text=mention_text,
                    mention_kind="name",
                    normalized_forms=normalized_forms,
                    confidence=quality.get("confidence"),
                    # AMBIGUOUS confidence_state from evidence keeps an uncertain
                    # alias unresolved/reviewable (no guessed target).
                    confidence_state=str(quality["confidence_state"])
                    if quality.get("confidence_state")
                    else ConfidenceState.UNKNOWN.value,
                    provenance={
                        "locator": str(ev.locator),
                        "evidence_ref": str(ev.id),
                        "generated_by": {
                            "stage": "ENTITY_RESOLUTION",
                            "analyzer": "umd-entity-resolution@1",
                            "config_digest": _ENTITY_RESOLUTION_CONFIG_DIGEST,
                        },
                    },
                    metadata_=meta,
                )
            )
        return out

    def _apply_resolution(self, batch: Any, mentions: list[Any] | None = None) -> None:
        """Apply a resolution batch through the existing command path (P2-S2).

        Every decision routes through the ledger command path — never a parallel
        authority. ``MENTION`` commands are recorded via :class:`MentionService`
        (idempotent ``EntityMentioned`` + mention row); ``ALIAS``/``MERGE`` are
        applied through the reversible :class:`Resolver`. Locks and
        ``USER_OVERRIDE`` precedence are enforced by the shared reducer, and a
        human confirmation always outranks any machine rerun.

        Option B (P4-S6): genuinely-ambiguous/unresolved mentions (no assignment)
        are persisted as reviewable mention rows with ``entity_id`` NULL and NO
        canonical event, so they stay discoverable through the
        ``UNRESOLVED_ALIASES`` query seam until a human confirms/overrides them.
        """
        from umd.resolution.mentions import MentionService, PostgresMentionRepository

        ledger = self._opt("ledger")
        commands = self._opt("commands")
        if ledger is None or commands is None:
            return
        resolver = self._resolver()
        repo = PostgresMentionRepository(self._engine)
        mention_svc = MentionService(ledger=ledger, repository=repo)
        resolved_ids = set(batch.assignments)
        # Persist unresolved mentions as reviewable rows first (idempotent via
        # on-conflict-do-nothing), then apply the resolved commands.
        for m in mentions or []:
            if m.mention_id not in resolved_ids:
                repo.record(m)
        for cmd in batch.commands:
            if cmd.kind == "MENTION" and cmd.mention is not None:
                mention_svc.record(cmd.mention)
            elif cmd.kind == "ALIAS" and resolver is not None:
                resolver.alias(
                    alias_entity=cmd.entity_id,
                    canonical=cmd.target_entity_id or cmd.entity_id,
                    reason=cmd.reason or "entity resolution",
                )
            elif cmd.kind == "MERGE" and resolver is not None:
                resolver.merge(
                    target_entity=cmd.entity_id,
                    merged_refs=cmd.refs or [cmd.entity_id],
                    assignments=cmd.assignments or {},
                    reason=cmd.reason or "entity resolution",
                )

    def _resolver(self) -> Any:
        """Build the Phase-1 reversible :class:`Resolver` over the shared ledger."""
        from umd.resolution.mentions import PostgresMentionRepository
        from umd.resolution.resolution import PostgresSplitEnumerator, Resolver

        ledger = self._opt("ledger")
        if ledger is None:
            return None
        mentions = PostgresMentionRepository(self._engine)
        return Resolver(
            ledger=ledger,
            enumerator=PostgresSplitEnumerator(self._engine, mentions),
            mentions=mentions,
            engine=self._engine,
        )

    def _paragraph_segments(self, result: Any, src: dict[str, Any]) -> list[ParagraphSegment]:
        """Plan-L chapter-aware paragraph segment records for the dispatched result.

        Reuses the dispatch result's ``segment()`` seam (idempotent re-registration)
        to pair each registered paragraph segment with its text in reading order, so
        STRUCTURAL_ANALYSIS consumes the SAME registered hierarchy the earlier text
        stages did. Returns [] when no segment seam exists (e.g. a test double), so
        the caller falls back to the deterministic chapter-1 baseline.

        The structural-path locator (NOT the registered ``source://...?frag=``
        locator) is used for the evidence rows, and ``segment_id`` is deliberately
        left unset: LOW_LEVEL_EXTRACTION already emits the exact segment-id-linked
        text_span evidence, and the deterministic structural findings are a SEPARATE
        evidence stream (structural-path locators, no segment FK) so the two never
        collide (uq_evidence_identity) nor double-count a source's evidence.
        """
        if not callable(getattr(result, "segment", None)):
            return []
        try:
            seg_result = result.segment(
                SegmentRegistry(self._segments),
                source_id=src["id"],
                source_sha512=src["sha512"],
                work_id=None,
            )
        except Exception:  # noqa: BLE001 - degrade to the deterministic baseline
            return []
        if seg_result is None:
            return []
        all_segs = list(seg_result.batch.created) + list(seg_result.batch.existing)
        para_segs = sorted(
            (s for s in all_segs if s.segment_type == "paragraph"),
            key=lambda s: _structural_path_key(s.structural_path),
        )
        # strict=True: a registered-paragraph / dispatch-paragraphs count OR order
        # mismatch must NOT silently truncate the analysis input (Plan M P3-S2 QA
        # Round 1 fix). On mismatch we raise so the caller falls back to the
        # chapter-1 baseline with a truthful warning instead of analyzing a
        # silently-shortened segment set.
        try:
            pairs = zip(para_segs, seg_result.paragraphs, strict=True)
            return [
                ParagraphSegment(
                    text=para,
                    paragraph_index=_paragraph_number(seg.structural_path),
                    chapter=_chapter_number(seg.structural_path),
                    locator=seg.structural_path,
                    structural_path=seg.structural_path,
                    segment_id=None,
                )
                for seg, para in pairs
            ]
        except ValueError as exc:
            raise ValueError(
                "registered paragraph segments do not align with dispatch paragraphs "
                f"({para_segs!r} vs {seg_result.paragraphs!r}); refusing to truncate "
                "analysis input"
            ) from exc

    def _semantic_provider(self) -> str | None:
        """The configured semantic-analysis provider (``reference`` is the default)."""
        settings = self._runtime.settings
        if settings is not None:
            semantic = getattr(settings, "semantic", None)
            provider = getattr(semantic, "provider", None) if semantic is not None else None
            if provider:
                return str(provider)
        return None

    def _semantic_model(self) -> str | None:
        """The configured semantic-analysis model, if any."""
        settings = self._runtime.settings
        if settings is not None:
            semantic = getattr(settings, "semantic", None)
            model = getattr(semantic, "model", None) if semantic is not None else None
            if model:
                return str(model)
        return None

    def _semantic_analyzer(self, config_digest: str) -> SemanticTextAnalyzer:
        """Build the semantic analyzer over the runtime's provider registry + config.

        When the runtime carries no ``providers`` (or the configured provider is
        ``reference``/None) the analyzer degrades to the deterministic/reference
        baseline with a truthful warning — never a fabricated provider result.
        """
        registry = self._runtime.providers
        if not isinstance(registry, ProviderRegistry):
            registry = None
        return SemanticTextAnalyzer(
            registry,
            provider=self._semantic_provider(),
            model=self._semantic_model(),
            stage="STRUCTURAL_ANALYSIS",
            config_digest=config_digest,
        )

    # -- modality helpers (P3-S1/S2 real raster + video branches) -----------

    def _is_text_media(self, src: dict[str, Any]) -> bool:
        """Whether the committed source takes the plain-text analysis route.

        Image/video/audio/subtitle sources use their modality branches instead
        (raster OCR + spatial; video demux + audio baseline + independent
        subtitles). Anything else (text/unknown + text-like formats) keeps the
        Phase-2 text bindings unchanged.
        """
        mk = (src["media_kind"] or "").lower()
        if mk in ("image", "raster", "video", "audio", "subtitle"):
            return False
        if mk in ("text", "txt", "markdown", "md"):
            return True
        fmt = (src["format"] or "").lower()
        if fmt in ("txt", "markdown", "epub", "pdf"):
            return True
        # Unknown/empty media kind (and text-like formats already handled above)
        # keeps the Phase-2 plain-text bindings unchanged.
        return True

    def _ocr_provider(self) -> str:
        """The configured raster OCR provider (reference is the deterministic default)."""
        settings = self._runtime.settings
        if settings is not None:
            raster = getattr(settings, "raster", None)
            provider = getattr(raster, "ocr_provider", None) if raster is not None else None
            if provider:
                return str(provider)
        return "reference"

    def _record_media_format_evidence(self, src: dict[str, Any]) -> str:
        """Record a format_analysis metadata row for a non-text source (no text
        normalization — the media bytes are never coerced to plain text)."""
        locator = f"format_analysis:{src['id']}"
        batch = EvidenceBatch(
            records=[
                Evidence(
                    source_id=uuid.UUID(src["id"]),
                    evidence_kind=EvidenceKind.METADATA,
                    locator=locator,
                    extraction_stage="FORMAT_ANALYSIS",
                    tool_versions={"format_analyzer": f"umd-{src['media_kind']}@1"},
                    config_digest=_MEDIA_FORMAT_EVIDENCE_CONFIG_DIGEST,
                    confidence=0.99,
                    quality={
                        "format": src["format"] or "unknown",
                        "route": src["media_kind"],
                        "media_kind": src["media_kind"],
                    },
                )
            ]
        )
        self._evidence.record(batch)
        return locator

    def _raster_branch(self, src: dict[str, Any], warnings: list[str]) -> list[str]:
        """Real raster work: bounded OCR + spatial + IIIF crops via the configured
        OCR provider (reference baseline when the configured provider is gated).
        Returns locator-bearing evidence refs, or [] when deps are absent so the
        stage degrades to the deterministic baseline."""
        if self._runtime.source_store is None or self._runtime.artifacts is None:
            return []
        raw = self._raw_bytes(src)
        if raw is None:
            return []
        from umd.raster.ocr import OcrProviderUnavailable
        from umd.raster.pipeline import RasterPipelineConfig, process_raster
        from umd.segmentation.registry import SegmentRegistry

        provider = self._ocr_provider()
        config = RasterPipelineConfig(ocr_provider=provider)
        # Append-only segment linkage: resolve each evidence locator to its owning
        # segment's DB row id at record time (segments are already registered by
        # ``process_raster``), so the evidence path needs no post-hoc UPDATE.
        resolver = self._raster_segment_id_resolver(src)
        result = None
        try:
            result = process_raster(
                registry=SegmentRegistry(self._segments),
                evidence_repo=self._evidence,
                store=self._runtime.source_store,
                artifacts=self._runtime.artifacts,
                source_id=src["id"],
                source_sha512=src["sha512"],
                raw=raw,
                work_id=None,
                config=config,
                segment_id_for_locator=resolver,
            )
        except OcrProviderUnavailable as exc:
            # Configured provider unavailable -> honest gate warning + reference baseline.
            warnings.append(f"ocr gated: {exc}")
            try:
                result = process_raster(
                    registry=SegmentRegistry(self._segments),
                    evidence_repo=self._evidence,
                    store=self._runtime.source_store,
                    artifacts=self._runtime.artifacts,
                    source_id=src["id"],
                    source_sha512=src["sha512"],
                    raw=raw,
                    work_id=None,
                    config=RasterPipelineConfig(ocr_provider="reference"),
                    segment_id_for_locator=resolver,
                )
            except Exception as exc2:  # noqa: BLE001 - quarantine containment
                warnings.append(f"raster pipeline degraded: {exc2}")
                return []
        except Exception as exc:  # noqa: BLE001 - quarantine containment
            warnings.append(f"raster pipeline failed (quarantine): {exc}")
            return []
        return self._collect_refs(result)

    def _raster_segment_id_resolver(self, src: dict[str, Any]) -> Callable[[str], str | None]:
        """Return a lazily-evaluated locator -> owning segment DB row id resolver.

        ``process_raster`` registers the page/panel/region segments and then calls
        this for each evidence locator; because the resolver queries the committed
        ``segment`` table at call time it sees the freshly-inserted DB row ids.
        Evidence with no owning segment (e.g. OCR-region observations) resolves to
        None, keeping ``segment_id`` NULL (append-only, no post-hoc UPDATE)."""

        def resolve(locator: str) -> str | None:
            # Queried lazily per call so it sees the segments ``process_raster``
            # just registered (a snapshot taken at creation would be empty).
            return self._segment_row_ids(src).get(locator)

        return resolve

    def _video_branch(self, src: dict[str, Any], warnings: list[str]) -> list[str]:
        """Real video work: sandboxed demux -> scenes/shots/frames/observations +
        independent embedded-subtitle sources. Returns locator-bearing refs, or []
        when deps are absent so the stage degrades to the deterministic baseline."""
        sandbox = self._runtime.sandbox
        if sandbox is None or self._runtime.source_store is None:
            return []
        raw = self._raw_bytes(src)
        if raw is None:
            return []
        from umd.segmentation.registry import SegmentRegistry
        from umd.video.evidence import build_video_evidence_plan
        from umd.video.runner import invoke_video_baseline

        try:
            output = invoke_video_baseline(
                sandbox, raw, name=src.get("original_name") or "video.mkv"
            )
        except Exception as exc:  # noqa: BLE001 - quarantine containment
            warnings.append(f"video baseline failed (quarantine): {exc}")
            return []
        refs: list[str] = []
        try:
            plan = build_video_evidence_plan(
                output, source_id=src["id"], source_sha512=src["sha512"], work_id=None
            )
            batch = SegmentRegistry(self._segments).register(plan.segment_inputs)
            self._link_evidence(plan.evidence, src["id"], prefix="video/")
            self._evidence.record(EvidenceBatch(records=plan.evidence))
            refs.extend(self._plan_refs(batch, plan.evidence))
        except Exception as exc:  # noqa: BLE001 - quarantine containment
            warnings.append(f"video evidence assembly failed: {exc}")
            return []
        refs.extend(
            self._video_audio_asr_branch(
                sandbox, raw, src, warnings, has_audio_track=bool(output.audio_tracks)
            )
        )
        refs.extend(self._subtitle_tracks_branch(sandbox, raw, src, warnings))
        return refs

    def _audio_branch(self, src: dict[str, Any], warnings: list[str]) -> list[str]:
        """Run the sandboxed audio baseline for a standalone audio source."""
        sandbox = self._runtime.sandbox
        if sandbox is None or self._runtime.source_store is None:
            return []
        from umd.audio.config import audio_config_from_env, config_digest_of
        from umd.audio.evidence import build_audio_evidence_plan
        from umd.audio.runner import invoke_audio_baseline
        from umd.segmentation.registry import SegmentRegistry

        raw = self._raw_bytes(src)
        if raw is None:
            return []
        try:
            output = invoke_audio_baseline(
                sandbox, raw, name=src.get("original_name") or "audio.wav"
            )
        except Exception as exc:  # noqa: BLE001 - quarantine containment
            warnings.append(f"audio baseline failed (quarantine): {exc}")
            return []
        try:
            plan = build_audio_evidence_plan(
                output,
                source_id=src["id"],
                source_sha512=src["sha512"],
                work_id=None,
                config_digest=config_digest_of(audio_config_from_env()),
            )
            batch = SegmentRegistry(self._segments).register(plan.segment_inputs)
            self._link_evidence(plan.evidence, src["id"], prefix="audio/")
            self._evidence.record(EvidenceBatch(records=plan.evidence))
            return self._plan_refs(batch, plan.evidence)
        except Exception as exc:  # noqa: BLE001 - quarantine containment
            warnings.append(f"audio evidence assembly failed: {exc}")
            return []

    def _video_audio_asr_branch(
        self,
        sandbox: Any,
        raw: bytes,
        src: dict[str, Any],
        warnings: list[str],
        *,
        has_audio_track: bool,
    ) -> list[str]:
        """Run the audio baseline/ASR on the EXTRACTED audio track of the video source.

        The sandboxed audio worker (:mod:`umd.audio.dispatch`) decodes the container
        and extracts its audio track to PCM, then runs VAD -> ASR -> the four-signal
        hallucination filter (S_VAD/S_LOGPROB/S_ENERGY/S_PROMOTION) -> utterances.
        The ASR utterances are recorded as ``audio_interval`` evidence LINKED to the
        video source/segments (append-only, with word/utterance timestamps, language,
        transcription-scoped confidence, provider/model/config provenance,
        ``generated_by``, and the promotion ban ``can_auto_promote=false``). Raw
        pre-filter utterances are retained and never auto-promoted to semantic truth
        (the audio evidence plan + versioned HallucinationFiltered events preserve
        that separation). If the configured ASR engine or model cache is unavailable,
        an honest ``asr gated: <reason>`` warning is emitted and NO fabricated
        transcript is recorded; the branch still completes with visual, temporal, and
        subtitle evidence intact.
        """
        if not has_audio_track or self._runtime.source_store is None:
            return []
        from umd.audio.evidence import build_audio_evidence_plan
        from umd.audio.runner import invoke_audio_baseline
        from umd.segmentation.registry import SegmentRegistry

        name = src.get("original_name") or "video.mkv"
        # The audio worker extracts the container's audio track (decode_to_pcm runs
        # ffmpeg, which probes the container CONTENT, not the filename) and runs it
        # under the AUDIO policy, whose input-extension allowlist covers audio
        # suffixes only. Stage the container under an audio-suffixed spool name so
        # the bounded sandbox accepts it while the decoder still probes the real
        # Matroska/MP4 content and pulls the default audio stream to PCM.
        audio_name = f"{Path(name).stem}.wav"
        try:
            output = invoke_audio_baseline(sandbox, raw, name=audio_name)
        except Exception as exc:  # noqa: BLE001 - quarantine containment
            warnings.append(f"audio baseline failed (quarantine): {exc}")
            return []
        # Honest gate: the configured ASR engine/model cache is unavailable (the
        # worker returns gated=True with a reference fallback and a named reason).
        # Surface the reason and record NO fabricated transcript -- the branch still
        # completes with the visual, temporal, and subtitle evidence intact.
        if output.asr is not None and output.asr.gated:
            warnings.append(f"asr gated: {output.asr.gate_reason or output.asr.provider}")
            return []
        refs: list[str] = []
        try:
            plan = build_audio_evidence_plan(
                output,
                source_id=src["id"],
                source_sha512=src["sha512"],
                work_id=None,
                config_digest=_video_audio_config_digest(output.asr),
            )
            # Stamp model/config provenance + the promotion ban onto the composed
            # ASR evidence: the base audio plan already carries provider/version in
            # ``generated_by`` and a config digest; the video branch augments the raw
            # ASR rows with the exact model id/version + generation timestamp observed
            # at run time, and re-asserts the auditable can_auto_promote=false ban.
            self._stamp_asr_provenance(plan.evidence, output.asr)
            batch = SegmentRegistry(self._segments).register(plan.segment_inputs)
            self._link_evidence(plan.evidence, src["id"], prefix="audio/")
            self._evidence.record(EvidenceBatch(records=plan.evidence))
            refs.extend(self._plan_refs(batch, plan.evidence))
        except Exception as exc:  # noqa: BLE001 - quarantine containment
            warnings.append(f"audio-ASR evidence assembly failed: {exc}")
            return []
        return refs

    @staticmethod
    def _stamp_asr_provenance(records: list[Evidence], asr: Any) -> None:
        """Stamp model/config provenance + the promotion ban on composed ASR rows.

        ``audio_interval`` rows from the base audio plan already carry
        provider/version in ``generated_by`` and a config digest; the video branch
        augments them with the exact model id/version and generation timestamp
        observed at run time, and re-asserts the auditable ``can_auto_promote=false``
        promotion ban (raw ASR never auto-promotes to semantic truth). Idempotent for
        crash-retry reruns.
        """
        if asr is None:
            return
        for ev in records:
            if ev.evidence_kind != EvidenceKind.AUDIO_INTERVAL.value:
                continue
            q = dict(ev.quality or {})
            gb = dict(q.get("generated_by") or {})
            if asr.model_id:
                gb["model_id"] = asr.model_id
            if asr.model_version:
                gb["model_version"] = asr.model_version
            if asr.generated_at:
                gb["generated_at"] = asr.generated_at
            q["generated_by"] = gb
            q["promotion_ban"] = {"promotion_ban": True, "can_auto_promote": False}
            ev.quality = q

    def _subtitle_tracks_branch(
        self, sandbox: Any, raw: bytes, src: dict[str, Any], warnings: list[str]
    ) -> list[str]:
        """Extract EVERY embedded subtitle track as an INDEPENDENT source + evidence
        stream (never flattened), returning its evidence refs."""
        import io

        from umd.segmentation.registry import SegmentRegistry
        from umd.storage.ocfl import SourceDescriptor
        from umd.storage.postgres.repositories import SourceMembershipService
        from umd.subtitle.evidence import build_subtitle_evidence_plan
        from umd.subtitle.runner import invoke_subtitle_parse
        from umd.video.runner import extract_embedded_subtitles

        refs: list[str] = []
        try:
            tracks = extract_embedded_subtitles(
                sandbox, raw, name=src.get("original_name") or "video.mkv"
            )
        except Exception as exc:  # noqa: BLE001 - quarantine containment
            warnings.append(f"embedded subtitle extraction failed: {exc}")
            return refs
        store = self._runtime.source_store
        if store is None:
            return refs
        memberships = SourceMembershipService(self._engine)
        for idx, track in enumerate(tracks):
            payload = track.get("payload")
            if not payload:
                warnings.append(
                    f"subtitle track {track.get('index', idx)} not extractable: "
                    f"{track.get('quarantine_reason')}"
                )
                continue
            name = f"track_{idx}.srt"
            payload_bytes = cast(bytes, payload)
            man = store.put_immutable(
                io.BytesIO(payload_bytes), SourceDescriptor(logical_name=name)
            )
            # Content-addressed reuse (CONTRACTS stable-ID / rerunnable-DAG): the
            # extracted track bytes may already be a committed source — a byte-
            # identical standalone subtitle (re-ingest), or this branch re-running on
            # a stage retry. Reusing the existing source id keeps the ``ocfl_ref``
            # unique constraint intact and makes LOW_LEVEL_EXTRACTION idempotent
            # (no duplicated subtitle source or evidence rows). A fresh track still
            # derives the SAME deterministic uuid5 id across reruns.
            existing = memberships.find_source_by_sha512(man.sha512)
            if existing is not None:
                t_sid, _existing_work = existing
            else:
                t_sid = str(
                    uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"{src['id']}:subtitle-track:{track.get('index', idx)}:"
                        f"{track.get('language') or 'und'}",
                    )
                )
                memberships.ensure_source(
                    source_id=t_sid,
                    ocfl_ref=man.object_id,
                    sha512=man.sha512,
                    size_bytes=man.size_bytes,
                    media_kind="subtitle",
                    original_name=name,
                    work_id=None,
                )
            try:
                out = invoke_subtitle_parse(sandbox, payload_bytes, name=name)
            except Exception as exc:  # noqa: BLE001 - quarantine containment
                warnings.append(f"subtitle parse failed (track {track.get('index', idx)}): {exc}")
                continue
            for tr in out.tracks:
                plan = build_subtitle_evidence_plan(
                    tr, source_id=t_sid, source_sha512=man.sha512, work_id=None
                )
                try:
                    batch = SegmentRegistry(self._segments).register(plan.segment_inputs)
                    self._link_evidence(plan.evidence, t_sid, prefix="subtitle/")
                    self._evidence.record(EvidenceBatch(records=plan.evidence))
                    refs.extend(self._plan_refs(batch, plan.evidence))
                except Exception as exc:  # noqa: BLE001
                    tidx = track.get("index", idx)
                    warnings.append(f"subtitle evidence assembly failed (track {tidx}): {exc}")
        return refs

    def _link_evidence(self, records: list[Evidence], source_id: str, prefix: str) -> None:
        """Link modality evidence rows to their owning segment (by DB row id).

        Media branches register segments then record evidence with no segment
        linkage; this maps each ``prefix/<structural_path>`` locator to the
        registered segment's row id so the evidence is retrievable via the
        public per-segment evidence endpoint (never fabricated — the linkage is
        purely an index over already-persisted observations).
        """
        row_ids = self._segment_row_ids({"id": source_id})
        for ev in records:
            if ev.segment_id is not None or not ev.locator:
                continue
            if ev.locator.startswith(prefix):
                row = row_ids.get(ev.locator[len(prefix) :])
                if row is not None:
                    ev.segment_id = uuid.UUID(row)

    @staticmethod
    def _plan_refs(batch: Any, evidence: list[Evidence]) -> list[str]:
        """Collect locator-bearing refs from a registered segment batch + evidence."""
        refs: list[str] = []
        created = getattr(batch, "created", None) or []
        for seg in created:
            loc = getattr(seg, "locator", None)
            if loc:
                refs.append(loc)
        for ev in evidence:
            if ev.locator:
                refs.append(ev.locator)
        return refs

    def _collect_refs(self, result: Any) -> list[str]:
        """Collect locator-bearing refs from a RasterProcessResult (segments + evidence)."""
        refs: list[str] = []
        batch = getattr(result, "batch", None)
        created = getattr(batch, "created", None) or []
        for seg in created:
            loc = getattr(seg, "locator", None)
            if loc:
                refs.append(loc)
        evidence = getattr(result, "evidence", None)
        rec_created = getattr(evidence, "created", None) or []
        for ev in rec_created:
            loc = getattr(ev, "locator", None)
            if loc:
                refs.append(loc)
        return refs

    # -- stage work ---------------------------------------------------------

    def _ingest(self, manifest: StageManifest) -> StageOutcome:
        src = self._require_source(manifest)
        # INGEST references the already-committed immutable OCFL ref; it does NOT
        # re-upload or write projections (source bytes are OCFL authority).
        return StageOutcome(
            artifact_refs=[src["ocfl_ref"]],
            evidence_refs=[f"source_bytes:{src['ocfl_ref']}"],
            metrics={
                "size_bytes": src["size_bytes"],
                "media_kind": src["media_kind"],
            },
        )

    def _format_analysis(self, manifest: StageManifest) -> StageOutcome:
        src = self._require_source(manifest)
        media_kind = src["media_kind"]
        fmt = src["format"] or "unknown"
        warnings: list[str] = []
        if not self._is_text_media(src):
            # Media route (image/video/audio/subtitle): record a format_analysis
            # metadata row without ever coercing the media bytes to plain text.
            if self._runtime.source_store is not None and self._raw_bytes(src) is not None:
                media_locator = self._record_media_format_evidence(src)
            else:
                media_locator = f"format_analysis:{src['id']}:{media_kind}:{fmt}"
                warnings.append("no source_store wired; recorded deterministic format ref")
            return StageOutcome(
                artifact_refs=[media_locator],
                evidence_refs=[media_locator],
                warnings=warnings,
                metrics={"media_kind": media_kind, "format": fmt, "parser": media_kind},
            )
        # REAL binding: ONE format-aware text dispatch (Plan L P1-S1/P1-S2).
        result = self._dispatch_text(src)
        if result is not None and result.route == "text":
            parser = result.parser
            warnings.extend(result.warnings)
            locator = self._record_format_evidence(
                src, result.text, format=fmt, parser=parser, result=result
            )
            ref = locator or f"format_analysis:{src['id']}:{parser}"
            return StageOutcome(
                artifact_refs=[ref],
                evidence_refs=[ref],
                warnings=warnings,
                metrics={"media_kind": media_kind, "format": fmt, "parser": parser},
            )
        if result is not None and result.route == "image_raster":
            # Image-only PDF: a MEDIA (raster) route — record non-text format
            # evidence, never text normalization of binary page bytes.
            warnings.extend(result.warnings)
            locator = self._record_media_format_evidence(src)
            return StageOutcome(
                artifact_refs=[locator],
                evidence_refs=[locator],
                warnings=warnings,
                metrics={
                    "media_kind": media_kind,
                    "format": fmt,
                    "parser": "pdf",
                    "route": "image_raster",
                },
            )
        # Degraded / unsupported / unreadable (or no source_store): deterministic
        # committed ref + explicit warning — never fabricated text.
        if result is not None:
            warnings.extend(result.warnings)
            warnings.append(
                f"text dispatch {result.parser} degraded/unsupported for {fmt}; "
                "recorded deterministic format ref"
            )
        else:
            warnings.append("no source_store wired; recorded deterministic format ref")
        ref = f"format_analysis:{src['id']}:{media_kind}:{fmt}"
        return StageOutcome(
            artifact_refs=[ref],
            evidence_refs=[ref],
            warnings=warnings,
            metrics={"media_kind": media_kind, "format": fmt},
        )

    def _basic_segmentation(self, manifest: StageManifest) -> StageOutcome:
        src = self._require_source(manifest)
        if not self._is_text_media(src):
            # Media sources are NOT plain-text segmented here; their deterministic
            # page/panel/region (raster) or file/track/scene/shot (video) segments
            # are registered by the modality branch in LOW_LEVEL_EXTRACTION.
            return StageOutcome(
                artifact_refs=[f"segments:{src['id']}:root"],
                evidence_refs=[f"segments:{src['id']}"],
                metrics={"segment_count": 0},
            )
        segments = self._segments.segments_for_source(src["id"])
        if not segments:
            result = self._dispatch_text(src)
            if result is not None and result.route == "text":
                # ONE dispatch call routes to the format-appropriate segmenter
                # (Plan L P1-S2/P1-S3) — never re-normalizing bytes through TXT.
                result.segment(
                    SegmentRegistry(self._segments),
                    source_id=src["id"],
                    source_sha512=src["sha512"],
                    work_id=None,
                )
                segments = self._segments.segments_for_source(src["id"])
            elif result is not None and result.non_text:
                # Image-only PDF / degraded: never plain-text segment binary bytes.
                return StageOutcome(
                    artifact_refs=[f"segments:{src['id']}:root"],
                    evidence_refs=[f"segments:{src['id']}"],
                    warnings=list(result.warnings),
                    metrics={"segment_count": 0},
                )
        refs = [s.locator for s in segments] if segments else [f"segments:{src['id']}:root"]
        return StageOutcome(
            artifact_refs=refs,
            evidence_refs=[f"segments:{src['id']}"],
            metrics={"segment_count": len(segments)},
        )

    def _low_level_extraction(self, manifest: StageManifest) -> StageOutcome:
        src = self._require_source(manifest)
        refs: list[str] = []
        warnings: list[str] = []
        if src["media_kind"] == "image":
            # REAL raster branch: bounded OCR + spatial + IIIF crops (P3-S1).
            refs = self._raster_branch(src, warnings)
        elif src["media_kind"] == "video":
            # REAL video branch: demux + scenes/shots/frames/observations +
            # independent embedded subtitles + audio-baseline composition (P3-S2).
            refs = self._video_branch(src, warnings)
        elif src["media_kind"] == "audio":
            # Standalone audio follows the same sandboxed baseline/evidence path
            # as embedded video audio, while retaining its own source identity.
            refs = self._audio_branch(src, warnings)
        elif src["media_kind"] == "subtitle":
            # Standalone subtitle source: parse to subtitle_event evidence +
            # segments (independent evidence stream, never flattened).
            refs = self._subtitle_branch(src, warnings)
        elif self._is_text_media(src):
            # Text route: per-segment text_span evidence from the dispatched
            # document's structural paths (Plan L P1-S3), never hard-coded.
            result = self._dispatch_text(src)
            if result is not None and result.route == "text":
                produced = self._emit_low_level_text_evidence(src, result)
                if produced:
                    refs = produced
            elif result is not None and result.non_text:
                # Image-only PDF / degraded: explicit warning, NO fabricated text.
                warnings.extend(result.warnings)
        if not refs:
            committed = self._evidence.get_by_source(src["id"])
            refs = (
                [e.locator or str(e.id) for e in committed]
                if committed
                else [f"evidence_records:{src['id']}:baseline"]
            )
        return StageOutcome(
            artifact_refs=refs,
            evidence_refs=refs,
            warnings=warnings,
            metrics={"evidence_count": len(refs)},
        )

    def _subtitle_branch(self, src: dict[str, Any], warnings: list[str]) -> list[str]:
        """Real standalone-subtitle work: parse to subtitle_event evidence +
        segments. Mirrors the embedded-track path (``_subtitle_tracks_branch``)
        for a source ingested directly as ``media_kind=subtitle``."""
        sandbox = self._runtime.sandbox
        if sandbox is None:
            return []
        raw = self._raw_bytes(src)
        if raw is None:
            return []
        from umd.segmentation.registry import SegmentRegistry
        from umd.subtitle.evidence import build_subtitle_evidence_plan
        from umd.subtitle.runner import invoke_subtitle_parse

        try:
            out = invoke_subtitle_parse(
                sandbox, raw, name=src.get("original_name") or "subtitle.srt"
            )
        except Exception as exc:  # noqa: BLE001 - quarantine containment
            warnings.append(f"subtitle parse failed (quarantine): {exc}")
            return []
        refs: list[str] = []
        for tr in out.tracks:
            plan = build_subtitle_evidence_plan(
                tr, source_id=src["id"], source_sha512=src["sha512"], work_id=None
            )
            try:
                batch = SegmentRegistry(self._segments).register(plan.segment_inputs)
                self._link_evidence(plan.evidence, src["id"], prefix="subtitle/")
                self._evidence.record(EvidenceBatch(records=plan.evidence))
                refs.extend(self._plan_refs(batch, plan.evidence))
            except Exception as exc:  # noqa: BLE001 - quarantine containment
                tidx = getattr(tr, "index", None)
                warnings.append(f"subtitle evidence assembly failed (track {tidx}): {exc}")
        return refs

    def _structural_analysis(self, manifest: StageManifest) -> StageOutcome:
        src = self._require_source(manifest)
        if not self._is_text_media(src):
            # Media sources keep their modality-level structural evidence (panels,
            # scenes/shots, subtitle streams); text structural reconciliation does
            # not apply, so emit a deterministic reconciled ref.
            return StageOutcome(
                artifact_refs=[f"structural_assertions:{src['id']}:reconciled"],
                evidence_refs=[f"structural_assertions:{src['id']}"],
                metrics={"block_count": 0, "mode": "media"},
            )
        refs: list[str] = []
        warnings: list[str] = []
        # Reuse the SAME dispatched document the earlier text stages consumed (Plan
        # L P1-S3): STRUCTURAL_ANALYSIS observes the identical parser/document/
        # hierarchy a rerun does — never re-normalizing raw EPUB/PDF bytes through
        # TXT. ``_dispatch_text`` is memoized per source, so a full DAG run makes
        # ONE dispatch shared by FORMAT_ANALYSIS / BASIC_SEGMENTATION /
        # LOW_LEVEL_EXTRACTION / STRUCTURAL_ANALYSIS.
        result = self._dispatch_text(src)
        if result is not None and result.route == "text":
            # Deterministic/reference baseline PLUS an optional provider-backed
            # semantic path (Plan M P2). The analyzer consumes the Plan-L
            # chapter-aware segment records (exact segment refs) and composes the
            # optional provider invocation on top; it never changes the stage's
            # completion semantics — it returns the same typed SemanticAnalysisResult
            # the deterministic baseline produced, recorded as evidence below.
            config_digest = _dispatch_evidence_config_digest(result)
            analyzer = self._semantic_analyzer(config_digest)
            try:
                segments = self._paragraph_segments(result, src)
            except ValueError as exc:
                # Registered/dispatch paragraph misalignment -> fall back to the
                # chapter-1 deterministic baseline with a truthful warning rather
                # than analyzing a silently-truncated segment set (Plan M P3-S2 QA
                # Round 1 fix).
                segments = []
                warnings.append(f"structural analysis degraded to chapter-1 baseline: {exc}")
            if segments:
                analysis = analyzer.analyze(
                    SemanticAnalysisInput(
                        source_id=src["id"],
                        segments=segments,
                        language=None,
                    )
                )
            else:
                # No registered segment records (non-DAG caller / no segment seam):
                # fall back to the deterministic chapter-1 paragraph baseline so the
                # stage stays fully callable and provenance-bearing.
                analysis = analyzer.analyze(
                    SemanticAnalysisInput(
                        source_id=src["id"],
                        segments=[
                            ParagraphSegment(
                                text=para,
                                paragraph_index=idx,
                                chapter=1,
                                locator=f"chapter/1/paragraph/{idx}",
                                structural_path=f"chapter/1/paragraph/{idx}",
                            )
                            for idx, para in enumerate(_paragraphs(result.text), start=1)
                        ],
                        language=None,
                    )
                )
            warnings.extend(analysis.warnings)
            if analysis.evidence:
                self._evidence.record(EvidenceBatch(records=analysis.evidence))
                refs = [e.locator for e in analysis.evidence if e.locator]
        elif result is not None and result.non_text:
            # Image-only PDF (route=image_raster) / degraded / unsupported: emit NO
            # fabricated dialogue/narration or other text evidence from binary or
            # non-text bytes (Plan L P1-S4) — an explicit warning and a
            # deterministic reconciled ref only.
            warnings.extend(result.warnings)
            warnings.append(
                f"structural analysis skipped: {result.parser} non-text/degraded "
                f"(route={result.route}); no fabricated text evidence"
            )
        if not refs:
            refs = [f"structural_assertions:{src['id']}:reconciled"]
        return StageOutcome(
            artifact_refs=refs,
            evidence_refs=refs,
            warnings=warnings,
            metrics={"input_evidence_refs": len(manifest.evidence_refs)},
        )

    def _entity_resolution(self, manifest: StageManifest) -> StageOutcome:
        """Real multi-entity resolution over committed candidate mentions.

        Replaces the old source-level synthetic canonical placeholder: the stage
        builds deterministic :class:`SourceMention` records from committed
        structural evidence, runs them through :class:`EntityResolutionService`
        (bounded, deterministic multi-entity clustering), and routes every
        decision through the existing command path — ``MentionService.record``
        for ``EntityMentioned`` and ``Resolver.alias/merge`` for the reversible
        ``ALIAS``/``MERGE`` entity-resolved events. Ambiguous / conflicting
        mentions stay unresolved and reviewable; the service never guesses a
        target and a rerun over the same mentions converges to the same refs.
        """
        src = self._require_source(manifest)
        commands = self._opt("commands")
        mentions = self._resolution_mentions(src)
        if commands is not None and mentions:
            from umd.resolution.service import EntityResolutionService, ResolutionInput

            service = EntityResolutionService()
            batch = service.resolve_mentions(
                ResolutionInput(
                    source_id=src["id"],
                    mentions=mentions,
                    generated_by={
                        "stage": "ENTITY_RESOLUTION",
                        "analyzer": "umd-entity-resolution@1",
                        "config_digest": _ENTITY_RESOLUTION_CONFIG_DIGEST,
                    },
                )
            )
            self._apply_resolution(batch, mentions)
            refs = [f"resolved_entities:{src['id']}"] + [e.ref for e in batch.canonical_entities]
            return StageOutcome(artifact_refs=refs, evidence_refs=refs)
        # No commands or no candidate mentions: deterministic no-op with a
        # provenance-bearing ref. Never emits the old ``entity:canonical:<src>``
        # placeholder.
        refs = [f"resolved_entities:{src['id']}:none"]
        return StageOutcome(artifact_refs=refs, evidence_refs=refs)

    def _cross_source_alignment(self, manifest: StageManifest) -> StageOutcome:
        src = self._require_source(manifest)
        refs = [f"alignments:{src['id']}:continuity"]
        commands = self._opt("commands")
        if commands is not None:
            # Single-source run: deterministic source-continuity alignment plan.
            left = manifest.evidence_refs[0] if manifest.evidence_refs else refs[0]
            commands.record_alignment(
                left_ref=left,
                right_ref=refs[0],
                alignment_type="CONTINUITY",
                method="source-order",
                correlation_id=self._corr(manifest.job_id),
            )
        return StageOutcome(artifact_refs=refs, evidence_refs=refs)

    def _semantic_reconciliation(self, manifest: StageManifest) -> StageOutcome:
        """Drive the semantic reconciler (Plan O P1-S2 / Plan R P1).

        Replaces the single ``RECONCILED_SOURCE`` placeholder with rich typed
        assertions routed through the command path. The stage reconstructs the
        deterministic typed observations (re-running the deterministic analyzer
        over the SAME memoized dispatch the text stages consumed — never a
        provider re-invocation) and hydrates the already-validated, committed
        provider observations into the typed input (Plan R P1), feeds them to the
        pure :class:`SemanticReconciler`, and routes every returned assertion
        through ``SemanticCommandService.assert_semantic`` (the existing command
        path). Provider observations are never re-invoked here — only their
        committed, validated evidence is rehydrated — keeping the stage
        deterministic and idempotent.
        """
        src = self._require_source(manifest)
        refs = [f"reconciled_state:{src['id']}:current"]
        commands = self._opt("commands")
        if commands is None or not self._is_text_media(src):
            return StageOutcome(artifact_refs=refs, evidence_refs=refs)
        try:
            input_ = self._reconciliation_input(src)
        except Exception as exc:  # noqa: BLE001 - quarantine containment
            return StageOutcome(
                artifact_refs=refs,
                evidence_refs=refs,
                warnings=[f"semantic reconciliation degraded: {exc}"],
            )
        if input_ is None:
            return StageOutcome(artifact_refs=refs, evidence_refs=refs)
        from umd.reconciliation.reconciler import SemanticReconciler

        events = SemanticReconciler().reconcile(input_)
        for ev in events:
            p = ev.payload
            commands.assert_semantic(
                predicate_code=p["predicate_code"],
                subject_ref=p["subject_ref"],
                object_ref=p.get("object_ref"),
                confidence=p.get("confidence"),
                state=p.get("state", "PROBABLE"),
                authority=p.get("authority", "machine"),
                scope=p.get("scope", "SOURCE"),
                support_refs=p.get("support_refs") or [],
                contradiction_refs=p.get("contradiction_refs") or [],
                derived_from=p.get("derived_from") or [],
                generated_by=p.get("generated_by") or {},
                correlation_id=self._corr(manifest.job_id),
            )
        refs = [f"reconciled_state:{src['id']}:current", f"reconciled:{src['id']}:{len(events)}"]
        return StageOutcome(
            artifact_refs=refs,
            evidence_refs=refs,
            metrics={"assertion_count": len(events)},
        )

    def _reconciliation_input(self, src: dict[str, Any]) -> Any | None:
        """Deterministic + validated provider observations and resolution (Plan R).

        Re-runs the deterministic text analyzer over the same memoized dispatch
        the text stages consumed, then hydrates ONLY the already-validated,
        committed ``semantic_observations`` evidence the provider-aware
        STRUCTURAL_ANALYSIS recorded (:func:`_hydrate_provider_observations`) into
        the typed buckets — a deterministic union of the baseline and the
        committed provider candidates. It never re-invokes a provider, constructs
        a second provider analyzer, or reads raw/unvalidated model output.

        The resolution bridge unions the deterministic committed-evidence
        mentions with the provider entity/alias mentions via
        :func:`~umd.resolution.mentions.mentions_from_semantic`, deduplicating by
        mention id so the deterministic baseline resolution is preserved exactly
        while provider aliases/entities become resolvable. Idempotent rerun
        convergence is retained: the same committed evidence yields the same
        typed input.
        """
        from umd.reconciliation.reconciler import ReconciliationInput
        from umd.resolution.mentions import mentions_from_semantic
        from umd.resolution.service import EntityResolutionService, ResolutionInput

        result = self._dispatch_text(src)
        if result is None or result.route != "text":
            return None
        config_digest = _dispatch_evidence_config_digest(result)
        analyzer = SemanticTextAnalyzer(
            None,
            provider=None,
            model=None,
            stage="STRUCTURAL_ANALYSIS",
            config_digest=config_digest,
        )
        try:
            segments = self._paragraph_segments(result, src)
        except ValueError:
            segments = []
        if not segments:
            return None
        analysis = analyzer.analyze(
            SemanticAnalysisInput(
                source_id=src["id"],
                segments=segments,
                language=None,
            )
        )
        # P1-S1..S3: hydrate committed semantic_observations evidence (the exact
        # source is the durable evidence returned by get_by_source; the structural
        # analyzer is the only provider invocation site). Require exact input-segment
        # locator membership and reject malformed/unknown/ambiguous payloads rather
        # than repairing or fabricating them. Deterministic baseline always retained.
        locators = {s.locator for s in segments}
        buckets, hydrate_warnings = _hydrate_provider_observations(
            self._evidence.get_by_source(src["id"]), locators
        )
        for attr, candidates in buckets.items():
            if candidates:
                getattr(analysis, attr).extend(candidates)
        analysis.warnings.extend(hydrate_warnings)
        # Truthful degradation: a configured semantic provider that left no
        # rehydratable committed observations is reported rather than silently
        # presenting a provider-less result as provider-backed. Deterministic-only
        # runs (no provider configured) emit no such warning.
        if self._semantic_provider() and not any(buckets.values()):
            analysis.warnings.append(
                "semantic provider configured but no committed semantic-observation "
                "evidence rehydrated; reconciliation uses the deterministic baseline"
            )
        # P1-S4: resolution bridge = deterministic committed-evidence mentions
        # (preserved exactly) unioned with provider entity/alias mentions from the
        # hydrated analysis, deduplicated by deterministic mention id. Provider
        # mentions whose id already exists (same surface at the same segment) stay
        # on the deterministic baseline row; genuinely new provider aliases/entities
        # become resolvable without fabricating mention rows or canonical refs.
        mentions = self._resolution_mentions(src)
        seen_ids = {m.mention_id for m in mentions}
        for m in mentions_from_semantic(analysis):
            if m.mention_id not in seen_ids:
                seen_ids.add(m.mention_id)
                mentions.append(m)
        batch = None
        if mentions:
            batch = EntityResolutionService().resolve_mentions(
                ResolutionInput(
                    source_id=src["id"],
                    mentions=mentions,
                    generated_by={
                        "stage": "ENTITY_RESOLUTION",
                        "analyzer": "umd-entity-resolution@1",
                        "config_digest": _ENTITY_RESOLUTION_CONFIG_DIGEST,
                    },
                )
            )
        return ReconciliationInput(
            source_id=src["id"],
            analysis=analysis,
            resolution=batch,
            generated_by={
                "stage": "SEMANTIC_RECONCILIATION",
                "reconciler": "umd-semantic-reconciler@1",
                "config_digest": "umd-semantic-reconciliation@1",
                "path": "deterministic",
            },
        )

    def _current_search_projection(self, manifest: StageManifest) -> StageOutcome:
        src = self._require_source(manifest)
        # Replay-only projection stage: schedules the sanctioned builder / replay
        # driver (the ONLY writer to its projection store). It never writes
        # projection tables directly.
        replay = self._opt("replay")
        refs = [f"projection_checkpoint:current_tier1:{src['id']}"]
        if replay is not None:
            builder = self._tier1_builder()
            report = replay.run(builder, wipe=True)
            refs = [f"projection_checkpoint:current_tier1:seq{report.applied_seq}"]
        return StageOutcome(artifact_refs=refs, evidence_refs=refs)

    def _tier1_builder(self) -> CurrentTierOneBuilder:
        builders = self._runtime.builders
        if isinstance(builders, dict) and "current_tier1" in builders:
            candidate = builders["current_tier1"]
            if isinstance(candidate, CurrentTierOneBuilder):
                return candidate
        return CurrentTierOneBuilder()

    # -- composition ---------------------------------------------------------

    def compose(self) -> StageWorkRegistry:
        """Bind every canonical stage to callable work (absent -> config failure)."""
        work: dict[str, StageWork] = {
            "INGEST": self._ingest,
            "FORMAT_ANALYSIS": self._format_analysis,
            "BASIC_SEGMENTATION": self._basic_segmentation,
            "LOW_LEVEL_EXTRACTION": self._low_level_extraction,
            "STRUCTURAL_ANALYSIS": self._structural_analysis,
            "ENTITY_RESOLUTION": self._entity_resolution,
            "CROSS_SOURCE_ALIGNMENT": self._cross_source_alignment,
            "SEMANTIC_RECONCILIATION": self._semantic_reconciliation,
            "CURRENT_SEARCH_PROJECTION": self._current_search_projection,
        }
        missing = [s for s in STAGE_ORDER if s not in work]
        if missing:
            raise ConfigurationError(
                "production registry configuration failure: missing stage(s): " + ", ".join(missing)
            )
        return work


class StageWorkRegistryFactory:
    """Factory building the production :class:`StageWorkRegistry`.

    ``build(runtime)`` composes every canonical stage. ``runtime`` must carry an
    ``engine``; a ``stages`` key is accepted to *assert* configuration coverage
    (an absent canonical stage raises :class:`ConfigurationError` — never a
    silent successful completion).
    """

    @staticmethod
    def build(runtime: Any) -> StageWorkRegistry:
        rt = ProductionRuntime.from_mapping(runtime)
        registry = _Composer(rt.engine, rt).compose()
        selected = runtime.get("stages") if isinstance(runtime, dict) else None
        if selected is not None:
            provided = {s for s in selected}
            missing = [s for s in STAGE_ORDER if s not in provided]
            if missing:
                raise ConfigurationError(
                    "production registry configuration failure: missing canonical "
                    "stage(s): " + ", ".join(missing)
                )
        return registry


__all__ = [
    "ProductionRuntime",
    "build_runtime",
    "StageWorkRegistryFactory",
    "ConfigurationError",
]
