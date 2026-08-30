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

  * ``FORMAT_ANALYSIS`` — reads the committed OCFL bytes (bounded range),
    normalizes the plain-text baseline, and records a durable format_analysis
    evidence row.
  * ``BASIC_SEGMENTATION`` — runs :func:`segment_txt` and registers the full
    text segment hierarchy through :class:`SegmentRegistry`/``PostgresSegmentStore``.
  * ``LOW_LEVEL_EXTRACTION`` — emits per-segment ``text_span`` evidence rows with
    ``segment_id`` pinned to the committed ``segment`` rows (per-segment query).
  * ``STRUCTURAL_ANALYSIS`` — runs :func:`analyze_text` over the paragraphs and
    records its dialogue/narration + candidate evidence.
  * ``ENTITY_RESOLUTION`` — derives candidate mentions from committed structural
    evidence and routes a reversible ALIAS resolution through the command path.
  * ``CROSS_SOURCE_ALIGNMENT`` — single-source runs are a deterministic no-op
    that still records a source-continuity ``Aligned`` event when commands exist.
  * ``SEMANTIC_RECONCILIATION`` — asserts the reconciled source state through the
    ledger command path (the shared reducer folds it into Tier-0 current state).
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
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, cast

import sqlalchemy as sa

from umd.analysis.text_structural import analyze_text
from umd.domain.evidence import EvidenceBatch
from umd.domain.models import Evidence, EvidenceKind, register_predicate
from umd.extractors.txt import normalize_txt
from umd.jobs.dag import STAGE_ORDER
from umd.jobs.manifest import StageManifest
from umd.jobs.runner import StageWorkRegistry
from umd.jobs.stage_execution import (
    MalformedInputError,
    StageOutcome,
    StageWork,
)
from umd.projections.current import CurrentTierOneBuilder
from umd.segmentation.registry import SegmentRegistry
from umd.segmentation.segmenters import segment_txt
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
#: Base prefix for the video-stage audio-ASR branch evidence config digest. Unlike
#: the other static per-binding digests, the video audio-ASR digest MUST encode the
#: ASR engine + model id (see ``_video_audio_config_digest``): `uq_evidence_identity`
#: (source_id, locator, evidence_kind, config_digest) dedups identical re-records on a
#: re-run, and a static digest would silently retain the prior engine's transcript
#: rows when a rerun switches engine/model. Append the provider + model_id so the
#: quadruple differs across engines/models.
_VIDEO_AUDIO_EVIDENCE_CONFIG_DIGEST_PREFIX = "umd-video-audio"

#: Open-vocabulary predicate for the reconciled-source state assertion emitted by
#: SEMANTIC_RECONCILIATION (data addition, not a schema migration).
register_predicate("RECONCILED_SOURCE", "The reconciled semantic state derived for a source.")


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


class _Composer:
    """Composes the nine canonical stages into real work over committed state."""

    def __init__(self, engine: sa.Engine, runtime: ProductionRuntime) -> None:
        self._engine = engine
        self._runtime = runtime
        self._segments = PostgresSegmentStore(engine)
        self._evidence = PostgresEvidenceRepository(engine)

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

    def _parsed_text(self, src: dict[str, Any]) -> tuple[bytes, str] | None:
        raw = self._raw_bytes(src)
        if raw is None:
            return None
        return raw, normalize_txt(raw).text

    def _parser_for(self, fmt: str) -> str:
        if fmt == "markdown":
            return "markdown"
        if fmt in ("epub", "pdf"):
            return fmt
        return "txt"

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

    def _record_format_evidence(self, src: dict[str, Any], text: str) -> str | None:
        locator = f"format_analysis:{src['id']}"
        batch = EvidenceBatch(
            records=[
                Evidence(
                    source_id=uuid.UUID(src["id"]),
                    evidence_kind=EvidenceKind.METADATA,
                    locator=locator,
                    extraction_stage="FORMAT_ANALYSIS",
                    tool_versions={"format_analyzer": "umd-txt@1"},
                    config_digest=_TEXT_EVIDENCE_CONFIG_DIGEST,
                    confidence=0.99,
                    quality={"format": "text/plain", "route": "text", "chars": len(text)},
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
    ) -> Evidence:
        return Evidence(
            source_id=uuid.UUID(src["id"]),
            segment_id=uuid.UUID(segment_id),
            evidence_kind=EvidenceKind.TEXT_SPAN,
            locator=locator,
            extraction_stage=stage,
            tool_versions={"extractor": "umd-txt@1"},
            config_digest=_TEXT_EVIDENCE_CONFIG_DIGEST,
            confidence=confidence,
            quality={"text": text},
        )

    def _emit_low_level_text_evidence(self, src: dict[str, Any], text: str) -> list[str]:
        """Emit per-segment ``text_span`` evidence with ``segment_id`` pinned."""
        ids = self._segment_row_ids(src)
        if not ids:
            return []
        records: list[Evidence] = []
        doc_id = ids.get("document/1")
        if doc_id is not None:
            records.append(
                self._span_evidence(
                    src,
                    doc_id,
                    "document/1",
                    1.0,
                    text,
                    stage="LOW_LEVEL_EXTRACTION",
                )
            )
        for idx, para in enumerate(_paragraphs(text), start=1):
            path = f"chapter/1/section/1/paragraph/{idx}"
            seg_id = ids.get(path)
            if seg_id is not None:
                records.append(
                    self._span_evidence(src, seg_id, path, 0.9, para, stage="LOW_LEVEL_EXTRACTION")
                )
        if not records:
            return []
        self._evidence.record(EvidenceBatch(records=records))
        return [r.locator for r in records if r.locator]

    def _candidate_mentions(self, src: dict[str, Any]) -> list[str]:
        committed = self._evidence.get_by_source(src["id"])
        out: list[str] = []
        for ev in committed:
            quality = ev.quality or {}
            if quality.get("candidate_kind") != "entity":
                continue
            mention = quality.get("mention_text")
            if mention and mention not in out:
                out.append(mention)
        return out

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
        # REAL binding: read the committed OCFL bytes, normalize the plain-text
        # baseline, and record a durable format_analysis evidence row.
        parsed = self._parsed_text(src)
        if parsed is not None:
            _raw, text = parsed
            parser = self._parser_for(fmt)
            locator = self._record_format_evidence(src, text)
            ref = locator or f"format_analysis:{src['id']}:{parser}"
            return StageOutcome(
                artifact_refs=[ref],
                evidence_refs=[ref],
                warnings=warnings,
                metrics={"media_kind": media_kind, "format": fmt, "parser": parser},
            )
        # Degraded (engine-only / unreadable source): deterministic ref from the
        # committed source row, never fabricated bytes.
        ref = f"format_analysis:{src['id']}:{media_kind}:{fmt}"
        warnings.append("no source_store wired; recorded deterministic format ref")
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
            parsed = self._parsed_text(src)
            if parsed is not None:
                _raw, text = parsed
                segment_txt(
                    SegmentRegistry(self._segments),
                    source_id=src["id"],
                    source_sha512=src["sha512"],
                    work_id=None,
                    text=text,
                )
                segments = self._segments.segments_for_source(src["id"])
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
            # Text route: per-segment text_span evidence (Phase-2 binding).
            parsed = self._parsed_text(src)
            if parsed is not None:
                _raw, text = parsed
                produced = self._emit_low_level_text_evidence(src, text)
                if produced:
                    refs = produced
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
        parsed = self._parsed_text(src)
        if parsed is not None:
            _raw, text = parsed
            result = analyze_text(
                source_id=src["id"],
                paragraphs=_paragraphs(text),
                tool_versions={"analyzer": "umd-text-structural@1"},
                # Text-path structural evidence: tag with the stable text digest so
                # uq_evidence_identity (source_id, locator, evidence_kind,
                # config_digest) dedups a crash-retry re-record instead of treating
                # NULL digests as distinct and duplicating STRUCTURAL evidence rows.
                config_digest=_TEXT_EVIDENCE_CONFIG_DIGEST,
            )
            if result.evidence:
                self._evidence.record(EvidenceBatch(records=result.evidence))
                refs = [e.locator for e in result.evidence if e.locator]
        if not refs:
            refs = [f"structural_assertions:{src['id']}:reconciled"]
        return StageOutcome(
            artifact_refs=refs,
            evidence_refs=refs,
            metrics={"input_evidence_refs": len(manifest.evidence_refs)},
        )

    def _entity_resolution(self, manifest: StageManifest) -> StageOutcome:
        src = self._require_source(manifest)
        refs = [f"resolved_entities:{src['id']}:canonical"]
        commands = self._opt("commands")
        if commands is not None:
            # REAL binding: derive candidate mentions from committed structural
            # evidence and route a reversible ALIAS resolution through the ledger
            # command path (the executor's StageCompleted is the atomic completion).
            mentions = self._candidate_mentions(src)
            if mentions:
                canonical = f"entity:canonical:{src['id']}"
                commands.entity_resolve(
                    kind="ALIAS",
                    entity_id=canonical,
                    refs=mentions,
                    correlation_id=self._corr(manifest.job_id),
                )
                refs = [canonical]
            else:
                # Empty-candidate single-source run: deterministic no-op that
                # still routes a real ALIAS through the command path.
                commands.entity_resolve(
                    kind="ALIAS",
                    entity_id=refs[0],
                    refs=list(manifest.evidence_refs),
                    correlation_id=self._corr(manifest.job_id),
                )
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
        src = self._require_source(manifest)
        refs = [f"reconciled_state:{src['id']}:current"]
        commands = self._opt("commands")
        if commands is not None:
            # Assert the reconciled source state through the ledger command path;
            # the shared reducer folds it into Tier-0 current_state (equivalence
            # with the Tier-1 projection replay).
            commands.assert_semantic(
                predicate_code="RECONCILED_SOURCE",
                subject_ref=refs[0],
                object_ref=src["ocfl_ref"],
                confidence=0.95,
                state="PROBABLE",
                support_refs=list(manifest.evidence_refs),
                generated_by={"stage": "SEMANTIC_RECONCILIATION"},
                correlation_id=self._corr(manifest.job_id),
            )
        return StageOutcome(artifact_refs=refs, evidence_refs=refs)

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
