"""ModelProvider contract tests (Phase C, P1-S3/S4).

Verifies the binding ``ModelProvider.invoke(request{mode,model,prompt,
input_refs}) -> StructuredModelResult`` contract, the provider registry, the
structured model-call record assembled as *evidence* (never semantic state),
the :class:`Embedder` typed wrapper (mode=embedding only), local-provider
substitution (any contract-compliant provider is interchangeable), and honest
reporting for unavailable/gated providers (Ollama server absent; vLLM gated).
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

from umd.domain.models import EvidenceKind
from umd.models import (
    Embedder,
    ModelCallRecord,
    ModelMode,
    ModelProviderUnavailable,
    ModelRequest,
    ProviderRegistry,
    StructuredModelResult,
)
from umd.models.adapters.ollama import OllamaProvider
from umd.models.adapters.vllm import VLLMProvider
from umd.models.provider import ModelCost


class FakeLocalProvider:
    """A contract-compliant local provider used to prove substitution.

    Implements :class:`ModelProvider` directly (no network) so the substitution
    test is hermetic: the pipeline must not care *which* provider backs it.
    """

    name = "fake_local"

    def __init__(self) -> None:
        self.calls: list[ModelRequest] = []

    def invoke(self, request: ModelRequest) -> StructuredModelResult:
        self.calls.append(request)
        if request.mode == ModelMode.EMBEDDING:
            return StructuredModelResult(
                mode=ModelMode.EMBEDDING,
                model=request.model,
                provider=self.name,
                output={"embeddings": [[0.1, 0.2, 0.3]]},
                input_refs=request.input_refs,
                stage=request.stage,
                cost=ModelCost(input_tokens=4),
            )
        return StructuredModelResult(
            mode=ModelMode.COMPLETION,
            model=request.model,
            provider=self.name,
            prompt_version=request.prompt_version,
            output={"text": f"completion for {request.prompt}"},
            input_refs=request.input_refs,
            stage=request.stage,
            cost=ModelCost(input_tokens=2, output_tokens=5),
        )


class TestContract:
    def test_completion_roundtrip(self) -> None:
        provider = FakeLocalProvider()
        result = provider.invoke(
            ModelRequest(
                mode=ModelMode.COMPLETION,
                model="local-qwen",
                prompt="summarize the evidence",
                prompt_version="v0.3",
                input_refs=["ev/1"],
                stage="structural_analysis",
            )
        )
        assert result.mode == ModelMode.COMPLETION
        assert result.provider == "fake_local"
        assert result.output["text"] == "completion for summarize the evidence"
        assert result.cost is not None and result.cost.output_tokens == 5

    def test_mode_is_explicit_completion_or_embedding(self) -> None:
        assert ModelMode.COMPLETION.value == "completion"
        assert ModelMode.EMBEDDING.value == "embedding"


class TestRegistry:
    def test_register_and_resolve_by_name(self) -> None:
        registry = ProviderRegistry([FakeLocalProvider()])
        assert "fake_local" in registry.names()
        resolved = registry.get("fake_local")
        assert isinstance(resolved, FakeLocalProvider)

    def test_resolve_missing_raises_typed_unavailable(self) -> None:
        with pytest.raises(ModelProviderUnavailable):
            ProviderRegistry([FakeLocalProvider()]).get("missing")

    def test_single_registered_is_default(self) -> None:
        registry = ProviderRegistry([FakeLocalProvider()])
        assert registry.get() is not None


class TestEmbedderWrapper:
    def test_embedder_forces_embedding_mode(self) -> None:
        fake = FakeLocalProvider()
        embedder = Embedder(fake)
        result = embedder.embed("deposit a transcript", model="local-embed", stage="semantic")
        assert result.mode == ModelMode.EMBEDDING
        assert result.output["embeddings"]

    def test_embedder_rejects_completion(self) -> None:
        with pytest.raises(ModelProviderUnavailable):
            Embedder(FakeLocalProvider()).invoke(
                ModelRequest(mode=ModelMode.COMPLETION, model="m", prompt="hi")
            )


class TestEvidenceAssembly:
    def test_model_call_record_becomes_evidence(self) -> None:
        result = FakeLocalProvider().invoke(
            ModelRequest(
                mode=ModelMode.COMPLETION,
                model="local-qwen",
                prompt="extract entities",
                config_digest="cfg-1",
            )
        )
        record = ModelCallRecord.from_result(result, config_digest="cfg-1")
        source_id = uuid.uuid4()
        evidence = record.to_evidence(source_id)
        assert evidence.evidence_kind == EvidenceKind.METADATA
        assert evidence.source_id == source_id
        assert evidence.config_digest == "cfg-1"
        assert evidence.tool_versions["model"] == "local-qwen"
        assert evidence.tool_versions["provider"] == "fake_local"
        assert evidence.quality["mode"] == "completion"
        assert evidence.quality["output"]["text"].startswith("completion for")


class TestUnavailableGating:
    def test_ollama_missing_server_raises_typed_unavailable(self) -> None:
        # Port 1 on loopback refuses instantly; no real server is expected.
        provider = OllamaProvider(base_url="http://127.0.0.1:1", timeout=2.0)
        with pytest.raises(ModelProviderUnavailable):
            provider.invoke(ModelRequest(mode=ModelMode.COMPLETION, model="m", prompt="hi"))

    def test_vllm_gated_off_raises(self) -> None:
        provider = VLLMProvider(enabled=False)
        with pytest.raises(ModelProviderUnavailable) as ei:
            provider.invoke(ModelRequest(mode=ModelMode.COMPLETION, model="m", prompt="hi"))
        assert "GATED" in str(ei.value)

    def test_remote_requires_base_url(self) -> None:
        from umd.models.adapters.remote import OpenAICompatProvider

        with pytest.raises(ModelProviderUnavailable):
            OpenAICompatProvider(base_url=None)


class _SemanticProvider:
    """A minimal contract-compliant provider returning configurable semantic JSON."""

    name = "sem_provider"

    def __init__(self, output: object) -> None:
        self._output = output
        self.calls: list[ModelRequest] = []

    def invoke(self, request: ModelRequest) -> StructuredModelResult:
        self.calls.append(request)
        return StructuredModelResult(
            mode=ModelMode.COMPLETION,
            model=request.model,
            model_version="1.0.0",
            provider=self.name,
            prompt_version=request.prompt_version,
            output=self._output,
            confidence=0.9,
            input_refs=request.input_refs,
            stage=request.stage,
        )


class TestSemanticProvenanceAndAuthority:
    """Plan M P3-S2: model-call provenance is durable metadata and semantic
    authority stays on the ledger/command path (providers never write it)."""

    @staticmethod
    def _segments() -> list[Any]:
        from umd.analysis.text_structural import ParagraphSegment

        return [
            ParagraphSegment(
                text="Alice spoke.",
                paragraph_index=1,
                chapter=1,
                locator="chapter/1/paragraph/1",
                structural_path="chapter/1/paragraph/1",
            )
        ]

    def test_semantic_call_provenance_is_durable_metadata(self) -> None:
        from umd.analysis.semantic_analyzer import SemanticAnalysisInput, SemanticTextAnalyzer

        registry = ProviderRegistry([FakeLocalProvider()])
        analyzer = SemanticTextAnalyzer(registry, provider="fake_local", model="local-qwen")
        result = analyzer.analyze(
            SemanticAnalysisInput(
                source_id=str(uuid.uuid4()),
                segments=self._segments(),
            )
        )
        meta = [e for e in result.evidence if e.evidence_kind == EvidenceKind.METADATA]
        assert meta, "provider call must be recorded as METADATA evidence"
        row = meta[0]
        # durable provenance metadata (never a semantic assertion)
        assert row.quality["provider"] == "fake_local"
        assert row.quality["model"] == "local-qwen"
        assert row.quality["mode"] == "completion"
        assert row.quality["input_refs"]
        assert row.config_digest, "provider digest must be set so evidence identity dedups"

    def test_semantic_authority_remains_ledger_command_path(self) -> None:
        from umd.analysis.semantic_analyzer import SemanticAnalysisInput, SemanticTextAnalyzer

        provider = _SemanticProvider(
            {
                "entities": [
                    {
                        "mention": "Alice",
                        "entity_type": "character",
                        "confidence": 0.9,
                        "segment": {"locator": "chapter/1/paragraph/1"},
                    }
                ]
            }
        )
        analyzer = SemanticTextAnalyzer(
            ProviderRegistry([provider]), provider="sem_provider", model="m"
        )
        result = analyzer.analyze(
            SemanticAnalysisInput(
                source_id=str(uuid.uuid4()),
                segments=self._segments(),
            )
        )
        # validated observations route ONLY as candidate evidence, explicitly
        # marked non-promotable (promotion_ban) so they can never silently become
        # semantic authority — authority is the downstream command/reconciliation path.
        obs = [e for e in result.evidence if e.quality.get("kind") == "semantic_observations"]
        assert obs, "validated observations must be recorded as evidence"
        assert obs[0].quality["can_auto_promote"] is False
        assert obs[0].quality["promotion_ban"]
        # every evidence row is METADATA (the call) or TEXT_SPAN (observations) —
        # never a semantic_assertion/current_state authority write.
        kinds = {e.evidence_kind for e in result.evidence}
        assert kinds <= {EvidenceKind.METADATA, EvidenceKind.TEXT_SPAN}

    def test_provider_config_change_alters_evidence_digest(self) -> None:
        from umd.analysis.semantic_prompt import semantic_config_digest

        base = semantic_config_digest()
        # Use a version distinct from the current default (semantic-analysis@2)
        # so the assertion genuinely proves a changed prompt yields a new digest.
        changed = semantic_config_digest(prompt_version="semantic-analysis@3")
        assert base != changed, "a changed prompt/parser/analyzer must yield a distinct digest"
        # Two model-call records with distinct config digests are distinguishable
        # evidence identities (uq_evidence_identity keys on config_digest).
        result = StructuredModelResult(mode=ModelMode.COMPLETION, model="m", provider="p")
        e1 = ModelCallRecord.from_result(result, config_digest=base).to_evidence(uuid.uuid4())
        e2 = ModelCallRecord.from_result(result, config_digest=changed).to_evidence(uuid.uuid4())
        assert e1.config_digest != e2.config_digest
