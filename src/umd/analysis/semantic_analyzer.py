"""Optional provider-backed semantic text analysis (Plan M P2).

Implements ``SemanticTextAnalyzer.analyze(input) -> SemanticAnalysisResult``
(CONTRACTS.md:75): the deterministic/reference baseline from
:func:`umd.analysis.text_structural.analyze_segments` is the **safe result**, and
an optional model provider — resolved through :class:`ProviderRegistry`, reusing
the existing local/remote adapters — may add validated, evidence-tied typed
observations on top.

Hard rules enforced here (Plan M P2; Task §13/14, DD §Provider/plugin):

* the **model is never authority** — provider output is strict-parsed
  (:func:`umd.analysis.semantic_parser.parse_semantic_output`) and only
  validated, exact-support candidates are merged into the result;
* every provider call is recorded as model-call ``METADATA`` evidence
  (:meth:`ModelCallRecord.to_evidence`) and the validated observations as a
  durable evidence row — provider output **never** directly writes semantic
  tables, projections, entity mappings, or authority state;
* **unavailable / unsupported / disabled / gated / malformed** providers degrade
  to the deterministic/reference baseline with a truthful warning — no fabricated
  facts, no silent "provider success";
* **evidence-supported promotion rules** at the analyzer boundary: a candidate
  must carry an exact segment locator that actually exists in the analyzed input
  AND a confidence; anything else is rejected or kept as candidate/evidence,
  never promoted. Because the analyzer only ever writes evidence (never semantic
  state), a model rerun can never overwrite human-confirmed ledger data.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeVar

from umd.analysis.semantic import (
    GeneratedBy,
    SemanticAnalysisResult,
    SemanticCandidate,
    SemanticPath,
)
from umd.analysis.semantic_parser import SemanticParseError, parse_semantic_output
from umd.analysis.semantic_prompt import (
    SEMANTIC_ANALYZER,
    SEMANTIC_PROMPT_VERSION,
    build_semantic_prompt,
    semantic_config_digest,
    semantic_input_refs,
)
from umd.analysis.text_structural import ParagraphSegment, analyze_segments
from umd.domain.models import Evidence, EvidenceKind
from umd.models.provider import (
    ModelCallRecord,
    ModelMode,
    ModelProvider,
    ModelProviderUnavailable,
    ModelRequest,
    StructuredModelResult,
)
from umd.models.registry import ProviderRegistry

_Candidate = TypeVar("_Candidate", bound=SemanticCandidate)


@dataclass
class SemanticAnalysisInput:
    """The validated input to :meth:`SemanticTextAnalyzer.analyze` (CONTRACTS.md:75).

    ``segments`` are the exact Plan-L chapter-aware paragraph segment records the
    analysis is scoped to; their locators are the exact segment-support set a
    provider candidate must reference to be promoted.
    """

    source_id: str
    segments: list[ParagraphSegment]
    language: str | None = None


class SemanticTextAnalyzer:
    """Deterministic baseline + optional provider-backed semantic analysis.

    Parameters mirror the production seam: ``provider``/``model`` select the
    optional provider path (``None``/``"reference"`` ⇒ deterministic-only);
    ``registry`` is the existing :class:`ProviderRegistry` whose registered
    adapters (ollama / remote / vllm) are reused as-is — no bespoke client.
    ``config_digest`` tags the deterministic evidence; the provider material
    always uses :func:`umd.analysis.semantic_prompt.semantic_config_digest` so a
    changed prompt/parser/analyzer yields a distinguishable digest.
    """

    def __init__(
        self,
        registry: ProviderRegistry | None = None,
        *,
        provider: str | None = None,
        model: str | None = None,
        stage: str = "STRUCTURAL_ANALYSIS",
        config_digest: str | None = None,
    ) -> None:
        self._registry = registry
        self._provider_name = provider if provider and provider != "reference" else None
        self._model = model
        self._stage = stage
        self._config_digest = config_digest or semantic_config_digest()
        #: Provider request/evidence digest encodes prompt|parser|analyzer versions.
        self._provider_digest = semantic_config_digest()

    # -- public contract ----------------------------------------------------

    def analyze(self, input_: SemanticAnalysisInput) -> SemanticAnalysisResult:
        """Return the typed semantic result for ``input_``.

        Deterministic/reference analysis is always the baseline; the optional
        provider path is attempted only when a provider + model are configured.
        """
        result = self._deterministic(input_)
        if self._provider_name is None:
            return result
        return self._provider_path(input_, result)

    # -- deterministic baseline ---------------------------------------------

    def _deterministic(self, input_: SemanticAnalysisInput) -> SemanticAnalysisResult:
        return analyze_segments(
            source_id=input_.source_id,
            segments=input_.segments,
            language=input_.language,
            extraction_stage=self._stage,
            config_digest=self._config_digest,
        )

    # -- optional provider path ---------------------------------------------

    def _resolve_provider(self) -> ModelProvider | None:
        if self._registry is None:
            return None
        try:
            return self._registry.get(self._provider_name)
        except ModelProviderUnavailable:
            return None

    def _provider_path(
        self, input_: SemanticAnalysisInput, result: SemanticAnalysisResult
    ) -> SemanticAnalysisResult:
        # Honest gate (P2-S3): a configured provider with no model is unsupported.
        if self._model is None:
            result.warnings.append(
                "semantic provider configured but no model; using deterministic/reference analysis"
            )
            return result
        provider = self._resolve_provider()
        if provider is None:
            result.warnings.append(
                f"semantic provider {self._provider_name!r} unavailable/unsupported/disabled; "
                "using deterministic/reference analysis"
            )
            return result

        input_refs = semantic_input_refs([s.locator for s in input_.segments])
        request = ModelRequest(
            mode=ModelMode.COMPLETION,
            model=self._model,
            prompt=build_semantic_prompt(input_refs=input_refs, language=input_.language),
            prompt_version=SEMANTIC_PROMPT_VERSION,
            input_refs=input_refs,
            stage=self._stage,
            config_digest=self._provider_digest,
        )
        try:
            model_result = provider.invoke(request)
        except ModelProviderUnavailable as exc:
            # Gated/unavailable provider -> honest gate warning + deterministic baseline.
            result.warnings.append(
                f"semantic provider {self._provider_name!r} gated/unavailable: {exc}"
            )
            return result

        # P2-S2: record EVERY provider call as durable model-call METADATA evidence.
        record = ModelCallRecord.from_result(model_result, config_digest=self._provider_digest)
        result.evidence.append(self._call_evidence(input_, record))

        generated_by = GeneratedBy(
            path=SemanticPath.PROVIDER,
            analyzer=SEMANTIC_ANALYZER,
            provider=model_result.provider,
            model=model_result.model,
            model_version=model_result.model_version,
            prompt_version=model_result.prompt_version or SEMANTIC_PROMPT_VERSION,
            config_digest=self._provider_digest,
        )
        try:
            parsed = parse_semantic_output(
                model_result.output,
                source_id=input_.source_id,
                generated_by=generated_by,
            )
        except SemanticParseError as exc:
            # Malformed/opaque output -> honest rejection, deterministic baseline,
            # NO fabricated observations (the model call is still audited above).
            result.warnings.append(
                f"semantic provider {model_result.provider} output malformed (rejected): {exc}"
            )
            return result

        result.warnings.extend(parsed.warnings)
        self._merge_validated(input_, result, parsed.result, model_result, parsed.rejected)
        return result

    def _call_evidence(self, input_: SemanticAnalysisInput, record: ModelCallRecord) -> Evidence:
        """Assemble the model-call METADATA evidence row for this provider invocation."""
        return record.to_evidence(
            uuid.UUID(input_.source_id),
            locator=f"model_call:{record.record_id}",
        )

    def _merge_validated(
        self,
        input_: SemanticAnalysisInput,
        result: SemanticAnalysisResult,
        provider_result: SemanticAnalysisResult,
        model_result: StructuredModelResult,
        rejected_parse: int,
    ) -> None:
        """Merge ONLY validated, exact-support candidates into ``result``.

        P2-S4 promotion rules: a candidate must carry an exact segment locator
        present in the analyzed input. Missing/invented segment support is
        rejected (kept as a warning, never promoted). Everything merged stays a
        candidate/evidence observation (``can_auto_promote=false``), never
        authority — so a model rerun can never overwrite human-confirmed data.
        """
        locators = {s.locator for s in input_.segments}
        rejected_support = 0
        kept: list[SemanticCandidate] = []

        def merge_into[C: SemanticCandidate](attr: str, candidates: Sequence[C]) -> list[C]:
            nonlocal rejected_support
            accepted, dropped = _exact_support(list(candidates), locators)
            rejected_support += dropped
            getattr(result, attr).extend(accepted)
            return accepted

        kept.extend(merge_into("scene_boundaries", provider_result.scene_boundaries))
        kept.extend(merge_into("entity_mentions", provider_result.entity_mentions))
        kept.extend(merge_into("aliases", provider_result.aliases))
        kept.extend(merge_into("presence", provider_result.presence))
        kept.extend(merge_into("utterances", provider_result.utterances))
        kept.extend(merge_into("speaker_candidates", provider_result.speaker_candidates))
        kept.extend(merge_into("traits", provider_result.traits))
        kept.extend(merge_into("relationships", provider_result.relationships))
        kept.extend(merge_into("emotions", provider_result.emotions))
        kept.extend(merge_into("states", provider_result.states))
        kept.extend(merge_into("context", provider_result.context))

        if rejected_support:
            result.warnings.append(
                f"semantic provider: {rejected_support} candidate(s) rejected for missing "
                "exact segment support (not promoted)"
            )
        if kept:
            result.evidence.append(
                self._observations_evidence(input_, model_result, kept, rejected_parse)
            )
        result.warnings.append(
            f"semantic provider {model_result.provider}: merged {len(kept)} validated "
            f"observation(s) (rejected: {rejected_parse + rejected_support})"
        )

    def _observations_evidence(
        self,
        input_: SemanticAnalysisInput,
        model_result: StructuredModelResult,
        observations: list[SemanticCandidate],
        rejected_parse: int,
    ) -> Evidence:
        """One durable evidence row carrying ONLY the validated candidate observations.

        This row is what routes to the later command/reconciliation path (its
        locator flows into the stage ``evidence_refs``); raw/malformed output is
        never routed. The promotion ban keeps these as candidate/evidence — the
        provider never auto-promotes to semantic truth.

        The locator embeds a per-batch content discriminator (a hash of the
        serialized observations) so DISTINCT observations batches persist as
        distinct evidence rows under ``uq_evidence_identity`` even when the same
        source + config digest recur on a content-CHANGING rerun. A locator keyed
        only on source_id (plus the content-independent provider config digest)
        would have its new observations row deduped (ON CONFLICT DO NOTHING) while
        the per-call METADATA rows (model_call:{record_id}) stayed distinct —
        leaving candidates referencing a non-persisted evidence row id.
        (Plan M P3-S2 QA Round 1 fix.)
        """
        payload_json = "\n".join(obs.model_dump_json() for obs in observations)
        payload_hash = hashlib.sha256(payload_json.encode()).hexdigest()[:16]
        tool_versions: dict[str, str] = {
            "provider": model_result.provider,
            "model": model_result.model,
        }
        if model_result.model_version:
            tool_versions["model_version"] = model_result.model_version
        tool_versions["prompt_version"] = model_result.prompt_version or SEMANTIC_PROMPT_VERSION
        quality: dict[str, object] = {
            "kind": "semantic_observations",
            "observations": [obs.model_dump(mode="json") for obs in observations],
            "rejected": rejected_parse,
            "prompt_version": SEMANTIC_PROMPT_VERSION,
            "can_auto_promote": False,
            "promotion_ban": {"can_auto_promote": False},
        }
        return Evidence(
            source_id=uuid.UUID(input_.source_id),
            evidence_kind=EvidenceKind.TEXT_SPAN,
            locator=f"semantic_analysis:{input_.source_id}:{payload_hash}",
            extraction_stage=self._stage,
            tool_versions=tool_versions,
            config_digest=self._provider_digest,
            confidence=model_result.confidence if model_result.confidence is not None else 1.0,
            quality=quality,
        )


def _exact_support[C: SemanticCandidate](
    candidates: list[C], locators: set[str]
) -> tuple[list[C], int]:
    """Keep candidates whose exact segment locator exists in the analyzed input.

    Returns ``(kept, dropped)`` — a candidate referencing an absent/invented
    segment locator is dropped (no exact segment support ⇒ not promoted).
    """
    kept = [c for c in candidates if c.segment.locator in locators]
    return kept, len(candidates) - len(kept)


def _all_buckets(result: SemanticAnalysisResult) -> list[list[SemanticCandidate]]:
    """The candidate buckets of a semantic result, in a stable order."""
    return [
        list(result.scene_boundaries),
        list(result.entity_mentions),
        list(result.aliases),
        list(result.presence),
        list(result.utterances),
        list(result.speaker_candidates),
        list(result.traits),
        list(result.relationships),
        list(result.emotions),
        list(result.states),
        list(result.context),
    ]


def promotable_candidates(
    result: SemanticAnalysisResult, *, min_confidence: float = 0.5
) -> list[SemanticCandidate]:
    """Provider-backed candidates that clear the analyzer promotion bar.

    P2-S4: a provider candidate is ``promotable`` (eligible to be offered to the
    command/reconciliation path) only when it is provider-backed AND has
    ``confidence >= min_confidence``. Everything else stays candidate/evidence —
    never promoted to authority. (Promotion is the downstream command path's
    decision; this only reports what cleared the analyzer boundary.)
    """
    if not 0.0 <= min_confidence <= 1.0:
        raise ValueError("min_confidence must be in [0, 1]")
    out: list[SemanticCandidate] = []
    for bucket in _all_buckets(result):
        out.extend(
            c
            for c in bucket
            if c.generated_by.path == SemanticPath.PROVIDER and c.confidence >= min_confidence
        )
    return out


__all__ = [
    "SemanticAnalysisInput",
    "SemanticTextAnalyzer",
    "promotable_candidates",
]
