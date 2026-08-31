"""Plan M P3-S1: typed semantic text-analysis validation tests.

Covers the ``SemanticTextAnalyzer.analyze(input) -> SemanticAnalysisResult``
contract (CONTRACTS.md:75) across BOTH the deterministic/reference baseline and
the optional provider-backed path:

* deterministic output (typed observations, unsupported categories ABSENT);
* valid provider output merged with full provenance (provider/model/version/
  prompt/config digest) and audited as model-call METADATA evidence;
* strict malformed-output rejection (garbage never fabricates observations);
* unsupported / gated / unconfigured provider fallback (honest warning, no
  silent "provider success");
* exact segment evidence (a candidate without an exact input segment locator is
  rejected);
* provenance fields; confidence bounds (out-of-range and below-bar rejected);
* no fabricated claims on any path.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa

from job_helpers import SOURCE_ID, make_manifest
from umd.analysis.semantic import (
    EntityMention,
    SemanticAnalysisResult,
    SemanticCandidate,
    SemanticPath,
)
from umd.analysis.semantic_analyzer import (
    SemanticAnalysisInput,
    SemanticTextAnalyzer,
    promotable_candidates,
)
from umd.analysis.text_structural import ParagraphSegment
from umd.domain.models import Evidence, EvidenceKind
from umd.models import (
    ModelMode,
    ModelProviderUnavailable,
    ModelRequest,
    ProviderRegistry,
    StructuredModelResult,
)

SID = "00000000-0000-4000-8000-000000000001"


class _FakeSemanticProvider:
    """A contract-compliant provider returning configurable semantic output.

    Implements :class:`ModelProvider` directly (no network) so the provider-path
    tests are hermetic. ``unavailable=True`` makes ``invoke`` raise the typed
    :class:`ModelProviderUnavailable` (a gated/disabled provider).
    """

    name = "fake_semantic"

    def __init__(
        self,
        output: object,
        *,
        unavailable: bool = False,
        confidence: float | None = 0.95,
        model: str = "sem-model@1",
        model_version: str = "1.0.0",
    ) -> None:
        self._output = output
        self._unavailable = unavailable
        self._confidence = confidence
        self._model = model
        self._model_version = model_version
        self.calls: list[ModelRequest] = []

    def invoke(self, request: ModelRequest) -> StructuredModelResult:
        self.calls.append(request)
        if self._unavailable:
            raise ModelProviderUnavailable("fake_semantic gated/unavailable")
        return StructuredModelResult(
            mode=ModelMode.COMPLETION,
            model=self._model,
            model_version=self._model_version,
            provider=self.name,
            prompt_version=request.prompt_version,
            output=self._output,
            confidence=self._confidence,
            input_refs=request.input_refs,
            stage=request.stage,
        )


def _segments() -> list[ParagraphSegment]:
    """Plan-L chapter-aware paragraph segment records (structural-path locators)."""
    return [
        ParagraphSegment(
            text="Chapter 1",
            paragraph_index=1,
            chapter=1,
            locator="chapter/1/paragraph/1",
            structural_path="chapter/1/paragraph/1",
        ),
        ParagraphSegment(
            text="Alice walked into the garden. She saw the White Rabbit.",
            paragraph_index=2,
            chapter=1,
            locator="chapter/1/paragraph/2",
            structural_path="chapter/1/paragraph/2",
        ),
        ParagraphSegment(
            text='"Hello," said Alice. "Where are you going?"',
            paragraph_index=3,
            chapter=1,
            locator="chapter/1/paragraph/3",
            structural_path="chapter/1/paragraph/3",
        ),
        ParagraphSegment(
            text="The White Rabbit hurried away.",
            paragraph_index=1,
            chapter=2,
            locator="chapter/2/paragraph/1",
            structural_path="chapter/2/paragraph/1",
        ),
    ]


def _input() -> SemanticAnalysisInput:
    return SemanticAnalysisInput(source_id=SID, segments=_segments(), language=None)


def _all(result: SemanticAnalysisResult) -> list[SemanticCandidate]:
    """Every candidate bucket in a stable order."""
    return [
        *result.scene_boundaries,
        *result.entity_mentions,
        *result.aliases,
        *result.presence,
        *result.utterances,
        *result.speaker_candidates,
        *result.traits,
        *result.relationships,
        *result.emotions,
        *result.states,
        *result.context,
    ]


# ---------------------------------------------------------------------------
# Deterministic / reference baseline
# ---------------------------------------------------------------------------


def test_deterministic_output_typed_and_unsupported_absent() -> None:
    analyzer = SemanticTextAnalyzer()
    result = analyzer.analyze(_input())
    assert result.generated_by.path == SemanticPath.DETERMINISTIC
    assert result.generated_by.analyzer == "umd-text-structural@2"
    # chapter transition -> a deterministic scene boundary
    assert any(sb.boundary == "start" for sb in result.scene_boundaries)
    # dialogue paragraph -> typed utterance
    assert result.utterances
    # durable evidence rows (dialogue/narration + candidate findings)
    assert result.evidence
    # unsupported categories are left ABSENT (no fabrication)
    assert result.aliases == []
    assert result.traits == []
    assert result.emotions == []
    assert result.states == []
    assert result.context == []
    # pure deterministic path carries no warnings
    assert result.warnings == []


def test_deterministic_evidence_and_observations_carry_exact_segment() -> None:
    result = SemanticTextAnalyzer().analyze(_input())
    # every candidate is pinned to an exact segment locator
    for cand in _all(result):
        assert cand.segment.locator in {s.locator for s in _segments()}
    # dialogue/narration evidence rows are TEXT_SPAN with exact locators
    kinds = {e.evidence_kind for e in result.evidence}
    assert kinds == {EvidenceKind.TEXT_SPAN}
    assert all(e.locator for e in result.evidence)


# ---------------------------------------------------------------------------
# Valid provider output (merge + provenance + audit)
# ---------------------------------------------------------------------------


def test_valid_provider_output_merged_with_provenance_and_audited() -> None:
    provider = _FakeSemanticProvider(
        {
            "entities": [
                {
                    "mention": "Alice",
                    "entity_type": "character",
                    "confidence": 0.9,
                    "segment": {"locator": "chapter/1/paragraph/2"},
                },
                {
                    "mention": "White Rabbit",
                    "entity_type": "character",
                    "confidence": 0.8,
                    "segment": {"locator": "chapter/1/paragraph/2"},
                },
            ],
            "traits": [
                {
                    "entity": "Alice",
                    "trait": "curious",
                    "confidence": 0.7,
                    "segment": {"locator": "chapter/1/paragraph/2"},
                },
            ],
        }
    )
    analyzer = SemanticTextAnalyzer(
        ProviderRegistry([provider]), provider="fake_semantic", model="sem-model@1"
    )
    result = analyzer.analyze(_input())

    # provider trait merged with full provenance
    provider_traits = [t for t in result.traits if t.generated_by.path == SemanticPath.PROVIDER]
    assert provider_traits
    trait = provider_traits[0]
    assert trait.trait == "curious"
    assert trait.generated_by.provider == "fake_semantic"
    assert trait.generated_by.model == "sem-model@1"
    assert trait.generated_by.model_version == "1.0.0"
    assert trait.generated_by.prompt_version
    assert trait.generated_by.config_digest

    # provider entities merged too
    provider_mentions = {
        m.mention for m in result.entity_mentions if m.generated_by.path == SemanticPath.PROVIDER
    }
    assert {"Alice", "White Rabbit"} <= provider_mentions

    # the model call is audited as METADATA evidence + observations as TEXT_SPAN
    kinds = {e.evidence_kind for e in result.evidence}
    assert EvidenceKind.METADATA in kinds
    assert EvidenceKind.TEXT_SPAN in kinds

    # the request carried prompt version + input refs + config digest
    assert provider.calls
    request = provider.calls[0]
    assert request.prompt_version
    assert request.input_refs
    assert request.config_digest


# ---------------------------------------------------------------------------
# Strict malformed-output rejection
# ---------------------------------------------------------------------------


def test_non_object_output_rejected_no_fabrication() -> None:
    provider = _FakeSemanticProvider("not a json object")
    analyzer = SemanticTextAnalyzer(
        ProviderRegistry([provider]), provider="fake_semantic", model="sem-model@1"
    )
    result = analyzer.analyze(_input())
    # honest warning recorded (parser raised SemanticParseError)
    assert any("malformed" in w for w in result.warnings)
    # no provider observation fabricated
    assert all(c.generated_by.path == SemanticPath.DETERMINISTIC for c in _all(result))
    # the model call is still audited as METADATA evidence
    assert EvidenceKind.METADATA in {e.evidence_kind for e in result.evidence}
    # deterministic baseline retained
    assert result.utterances


def test_out_of_range_confidence_rejected_per_item() -> None:
    provider = _FakeSemanticProvider(
        {
            "entities": [
                {
                    "mention": "Alice",
                    "entity_type": "character",
                    "confidence": 1.5,  # > 1.0 -> rejected by the strict parser
                    "segment": {"locator": "chapter/1/paragraph/2"},
                },
                {
                    "mention": "White Rabbit",
                    "entity_type": "character",
                    "confidence": -0.1,  # < 0.0 -> rejected too
                    "segment": {"locator": "chapter/1/paragraph/2"},
                },
            ],
        }
    )
    analyzer = SemanticTextAnalyzer(
        ProviderRegistry([provider]), provider="fake_semantic", model="sem-model@1"
    )
    result = analyzer.analyze(_input())
    provider_mentions = [
        m for m in result.entity_mentions if m.generated_by.path == SemanticPath.PROVIDER
    ]
    assert provider_mentions == []
    # each out-of-range confidence item is rejected with a strict-validation warning
    invalid = [w for w in result.warnings if "invalid entity_mentions observation" in w]
    assert len(invalid) == 2, result.warnings


def test_unknown_top_level_key_rejected() -> None:
    provider = _FakeSemanticProvider({"mystery_key": [1, 2]})
    analyzer = SemanticTextAnalyzer(
        ProviderRegistry([provider]), provider="fake_semantic", model="sem-model@1"
    )
    result = analyzer.analyze(_input())
    assert any("unknown top-level keys" in w for w in result.warnings)
    assert all(c.generated_by.path == SemanticPath.DETERMINISTIC for c in _all(result))


# ---------------------------------------------------------------------------
# Unsupported / gated provider fallback
# ---------------------------------------------------------------------------


def test_unregistered_provider_degrades_honestly() -> None:
    # Empty registry -> ProviderRegistry.get raises ModelProviderUnavailable.
    analyzer = SemanticTextAnalyzer(ProviderRegistry(), provider="ollama", model="qwen")
    result = analyzer.analyze(_input())
    assert result.generated_by.path == SemanticPath.DETERMINISTIC
    assert any(
        any(word in w for word in ("unavailable", "unsupported", "disabled"))
        for w in result.warnings
    )
    # provider never invoked -> no METADATA call evidence
    assert EvidenceKind.METADATA not in {e.evidence_kind for e in result.evidence}


def test_gated_provider_invoke_degrades_honestly() -> None:
    provider = _FakeSemanticProvider({}, unavailable=True)
    analyzer = SemanticTextAnalyzer(
        ProviderRegistry([provider]), provider="fake_semantic", model="sem-model@1"
    )
    result = analyzer.analyze(_input())
    assert result.generated_by.path == SemanticPath.DETERMINISTIC
    assert any("gated/unavailable" in w for w in result.warnings)
    assert EvidenceKind.METADATA not in {e.evidence_kind for e in result.evidence}


def test_provider_without_model_is_unsupported_not_invoked() -> None:
    provider = _FakeSemanticProvider({})
    analyzer = SemanticTextAnalyzer(ProviderRegistry([provider]), provider="fake_semantic")
    result = analyzer.analyze(_input())
    assert result.generated_by.path == SemanticPath.DETERMINISTIC
    assert any("no model" in w for w in result.warnings)
    assert provider.calls == []


# ---------------------------------------------------------------------------
# Exact segment evidence
# ---------------------------------------------------------------------------


def test_candidate_without_exact_segment_support_rejected() -> None:
    provider = _FakeSemanticProvider(
        {
            "entities": [
                {
                    "mention": "Invented",
                    "entity_type": "character",
                    "confidence": 0.9,
                    "segment": {"locator": "chapter/99/paragraph/999"},  # NOT in input
                },
                {
                    "mention": "Alice",
                    "entity_type": "character",
                    "confidence": 0.9,
                    "segment": {"locator": "chapter/1/paragraph/2"},  # exact
                },
            ],
        }
    )
    analyzer = SemanticTextAnalyzer(
        ProviderRegistry([provider]), provider="fake_semantic", model="sem-model@1"
    )
    result = analyzer.analyze(_input())
    provider_mentions = {
        m.mention for m in result.entity_mentions if m.generated_by.path == SemanticPath.PROVIDER
    }
    assert "Alice" in provider_mentions
    assert "Invented" not in provider_mentions
    assert any("rejected for missing exact segment support" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Confidence bounds / promotion bar
# ---------------------------------------------------------------------------


def test_promotable_candidates_requires_min_confidence() -> None:
    provider = _FakeSemanticProvider(
        {
            "entities": [
                {
                    "mention": "Alice",
                    "entity_type": "character",
                    "confidence": 0.9,
                    "segment": {"locator": "chapter/1/paragraph/2"},
                },
                {
                    "mention": "Bob",
                    "entity_type": "character",
                    "confidence": 0.4,  # below the promotion bar
                    "segment": {"locator": "chapter/1/paragraph/2"},
                },
            ],
        }
    )
    analyzer = SemanticTextAnalyzer(
        ProviderRegistry([provider]), provider="fake_semantic", model="sem-model@1"
    )
    result = analyzer.analyze(_input())
    promotable = promotable_candidates(result, min_confidence=0.5)
    names = {c.mention for c in promotable if isinstance(c, EntityMention)}
    assert "Alice" in names
    assert "Bob" not in names
    # only provider-backed candidates are promotable (deterministic never is)
    assert all(c.generated_by.path == SemanticPath.PROVIDER for c in promotable)


def test_promotable_candidates_rejects_invalid_threshold() -> None:
    result = SemanticTextAnalyzer().analyze(_input())
    try:
        promotable_candidates(result, min_confidence=1.5)
    except ValueError:
        pass
    else:
        raise AssertionError("min_confidence outside [0,1] must raise ValueError")


# ---------------------------------------------------------------------------
# No fabricated claims on any path
# ---------------------------------------------------------------------------


def test_no_fabricated_claims_on_malformed_category() -> None:
    provider = _FakeSemanticProvider({"entities": "not a list"})
    analyzer = SemanticTextAnalyzer(
        ProviderRegistry([provider]), provider="fake_semantic", model="sem-model@1"
    )
    result = analyzer.analyze(_input())
    assert all(c.generated_by.path == SemanticPath.DETERMINISTIC for c in _all(result))
    assert any("expected a list" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Plan M P3-S2 QA Round 2: content-discriminated observations evidence locator.
# The analyzer appends ONE observations evidence row whose locator embeds a
# content hash, so uq_evidence_identity (source_id, locator, evidence_kind,
# config_digest) persists DISTINCT rows on a content-CHANGING rerun and dedups
# the row on a content-IDENTICAL rerun — never leaving candidates referencing a
# non-persisted evidence row id.
# ---------------------------------------------------------------------------


def _observations_row(result: SemanticAnalysisResult) -> Evidence:
    """The single durable observations evidence row on a provider-backed result."""
    rows = [e for e in result.evidence if (e.quality or {}).get("kind") == "semantic_observations"]
    assert len(rows) == 1, f"expected exactly one observations row, got {len(rows)}"
    return rows[0]


def _entities_provider(mention: str) -> _FakeSemanticProvider:
    return _FakeSemanticProvider(
        {
            "entities": [
                {
                    "mention": mention,
                    "entity_type": "character",
                    "confidence": 0.9,
                    "segment": {"locator": "chapter/1/paragraph/2"},
                },
            ],
        }
    )


def test_observations_evidence_locator_is_content_discriminated() -> None:
    """Content-CHANGING reruns under the SAME source_id + config digest persist
    DISTINCT observations evidence rows: the locator embeds the source id AND a
    content-hash suffix so a new provider batch cannot be deduped onto a stale row."""
    result_a = SemanticTextAnalyzer(
        ProviderRegistry([_entities_provider("Alice")]),
        provider="fake_semantic",
        model="sem-model@1",
    ).analyze(_input())
    result_b = SemanticTextAnalyzer(
        ProviderRegistry([_entities_provider("White Rabbit")]),
        provider="fake_semantic",
        model="sem-model@1",
    ).analyze(_input())

    row_a = _observations_row(result_a)
    row_b = _observations_row(result_b)

    # locator embeds the source id AND a content-hash suffix
    assert row_a.locator.startswith(f"semantic_analysis:{SID}:")
    assert row_b.locator.startswith(f"semantic_analysis:{SID}:")
    # content-changing rerun -> distinct evidence identity (dedup can't collide)
    assert row_a.locator != row_b.locator
    # observations rows are TEXT_SPAN evidence and never auto-promote
    assert row_a.evidence_kind == EvidenceKind.TEXT_SPAN
    assert row_a.quality.get("can_auto_promote") is False


def test_observations_evidence_locator_stable_on_identical_rerun() -> None:
    """Content-IDENTICAL reruns under the SAME source_id + config digest produce
    the SAME observations locator, so uq_evidence_identity dedups the rerun row."""
    provider = _entities_provider("Alice")
    analyzer = SemanticTextAnalyzer(
        ProviderRegistry([provider]), provider="fake_semantic", model="sem-model@1"
    )
    first = _observations_row(analyzer.analyze(_input()))
    second = _observations_row(analyzer.analyze(_input()))
    assert first.locator == second.locator
    assert first.locator.startswith(f"semantic_analysis:{SID}:")


# ---------------------------------------------------------------------------
# Plan M P3-S2 QA Round 2: strict-zip baseline fallback in the production
# STRUCTURAL_ANALYSIS binding (hermetic — no Postgres). A registered/dispatch
# paragraph misalignment must never silently truncate the analysis input; the
# stage degrades to the deterministic chapter-1 baseline with a truthful warning.
# ---------------------------------------------------------------------------


def _composer() -> Any:
    """A production composer over a throwaway sqlite engine that is NEVER queried
    (the Postgres segment/evidence stores only wrap the engine at construction)."""
    import umd.jobs.production as production

    engine = sa.create_engine("sqlite://")
    return production._Composer(engine, production.ProductionRuntime(engine=engine))


def _misaligned_seg_result() -> SimpleNamespace:
    """A segment seam whose registered paragraph segments (NONE in an empty
    created/existing batch) do NOT align with the dispatch's reported paragraphs
    (three) — the strict-zip misalignment the fallback protects against."""
    return SimpleNamespace(
        batch=SimpleNamespace(created=[], existing=[]),
        paragraphs=["one", "two", "three"],
    )


def test_paragraph_segments_strict_zip_raises_on_misalignment() -> None:
    """A registered/dispatch paragraph count mismatch raises ``ValueError``
    ("refusing to truncate") instead of silently analyzing a shortened segment set."""

    def _seam(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return _misaligned_seg_result()

    composer = _composer()
    result = SimpleNamespace(segment=_seam)
    src = {"id": SOURCE_ID, "sha512": "d" * 128}
    with pytest.raises(ValueError, match="refusing to truncate"):
        composer._paragraph_segments(result, src)


def test_structural_analysis_falls_back_to_chapter1_baseline_on_misalignment() -> None:
    """On a strict-zip mismatch STRUCTURAL_ANALYSIS degrades to the deterministic
    chapter-1 paragraph baseline with a truthful warning, still emitting durable
    artifact/evidence refs and chapter-1 evidence rows."""
    from umd.domain.evidence import EvidenceBatch

    captured: list[Evidence] = []

    class _Capture:
        def record(self, batch: EvidenceBatch):  # type: ignore[no-untyped-def]
            captured.extend(batch.records)
            return object()

    def _src(_manifest: Any) -> dict[str, Any]:
        return {
            "id": SOURCE_ID,
            "media_kind": "text",
            "format": "txt",
            "ocfl_ref": "ocfl://x",
            "sha512": "d" * 128,
        }

    def _seam(*_args: object, **_kwargs: object) -> SimpleNamespace:
        return _misaligned_seg_result()

    def _dispatch(_src: Any) -> SimpleNamespace:
        return SimpleNamespace(
            route="text",
            text="Alice walked. She saw the rabbit.\n\n'Hello,' said Alice.",
            parser="txt",
            parser_version="umd-txt@1",
            decoder_version="umd-stdlib-decode@1",
            config_digest="umd-dispatch@1",
            non_text=False,
            warnings=[],
            segment=_seam,
        )

    composer = _composer()
    composer._evidence = _Capture()  # noqa: SLF001 - swap repo for a capture double
    composer._require_source = _src  # type: ignore[method-assign]
    composer._dispatch_text = _dispatch  # type: ignore[method-assign]

    outcome = composer._structural_analysis(make_manifest("STRUCTURAL_ANALYSIS"))  # noqa: SLF001

    assert any("degraded to chapter-1 baseline" in w for w in outcome.warnings), outcome.warnings
    assert outcome.artifact_refs, "fallback must still emit durable artifact refs"
    assert outcome.evidence_refs, "fallback must still emit durable evidence refs"
    assert any(ev.locator.startswith("chapter/1/paragraph/") for ev in captured), (
        "chapter-1 fallback baseline did not run"
    )


# ---------------------------------------------------------------------------
# Plan M P3-S2 QA Round 2 (low priority): @2 prompt-schema version pin.
# ---------------------------------------------------------------------------


def test_semantic_prompt_version_and_schema_pin() -> None:
    """The @2 prompt embeds the full per-category JSON schema: a version bump and
    the exact per-category field names + the mandatory exact 'segment' rule."""
    from umd.analysis.semantic_prompt import (
        SEMANTIC_PROMPT_VERSION,
        build_semantic_prompt,
    )

    assert SEMANTIC_PROMPT_VERSION == "semantic-analysis@2"
    prompt = build_semantic_prompt()
    assert "observed_state" in prompt
    assert "canonical_name" in prompt
    assert "context_type" in prompt
    assert "exact 'segment' reference" in prompt
    assert "Every observation object MUST include an exact 'segment'" in prompt
