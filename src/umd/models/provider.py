"""ModelProvider contract + structured model-call records (Phase C, P1-S3).

Implements the binding contract ``ModelProvider.invoke(request{mode, model,
prompt, input_refs}) -> StructuredModelResult`` (CONTRACTS.md §Plugin and stage
envelopes), with ``mode`` = ``completion | embedding`` and interchangeable local
and remote adapters.

Every model-driven operation emits a *structured* result (Task §13) that is
recorded — as **evidence** — with model, version, prompt/instruction version,
input evidence refs, output, confidence, timestamp, dependency stage and
cost/timing. Recording a model call writes evidence only; it never writes
semantic state and never writes a projection (the Plan A/B separation is
preserved). Providers are swappable behind this interface; an unusable provider
raises a typed :class:`ModelProviderUnavailable` and is reported through
capability reporting rather than guessed.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, Field

from umd.domain.models import Evidence, EvidenceKind


class ModelMode(StrEnum):
    """The two supported model call modes (CONTRACTS)."""

    COMPLETION = "completion"
    EMBEDDING = "embedding"


class ModelRequest(BaseModel):
    """The structured request to a :class:`ModelProvider`."""

    mode: ModelMode = ModelMode.COMPLETION
    model: str = Field(min_length=1)
    #: Prompt/instruction text for completion mode; None for pure embedding calls.
    prompt: str | None = None
    #: Text input(s) for embedding mode.
    input: str | list[str] | None = None
    #: Prompt/instruction version for auditability (Task §13).
    prompt_version: str | None = None
    #: Input evidence references that substantiate this call (never a claim of truth).
    input_refs: list[str] = Field(default_factory=list)
    #: Dependency stage (DAG-aligned) that generated the call.
    stage: str | None = None
    #: Configuration digest of the invoking pipeline.
    config_digest: str | None = None


@dataclass(frozen=True)
class ModelCost:
    """Token/cost accounting recorded on every model call."""

    input_tokens: int = 0
    output_tokens: int = 0
    currency: str | None = None


class StructuredModelResult(BaseModel):
    """The structured, confidence-scoped result of one model invocation.

    ``output`` is structured JSON-serializable data (never an opaque blob that
    downstream promotes unexamined); confidence is transcription/inference-scoped,
    not semantic truth.
    """

    mode: ModelMode
    model: str
    model_version: str | None = None
    provider: str
    prompt_version: str | None = None
    output: Any = None
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    input_refs: list[str] = Field(default_factory=list)
    stage: str | None = None
    timestamp: int = Field(default_factory=lambda: int(time.time()))
    cost: ModelCost | None = None
    warnings: list[str] = Field(default_factory=list)


class ModelCallRecord(BaseModel):
    """The durable structured model-call record (Task §13, DD §Provider/plugin).

    This is the record assembled as **evidence** on every model invocation:
    model, version, prompt version, input refs, output, timestamp, stage, cost.
    It is evidence of the call, never a semantic assertion.
    """

    record_id: str = Field(default_factory=lambda: uuid.uuid4().hex)
    mode: ModelMode
    model: str
    model_version: str | None = None
    provider: str
    prompt_version: str | None = None
    input_refs: list[str] = Field(default_factory=list)
    output: Any = None
    confidence: float | None = None
    timestamp: int = Field(default_factory=lambda: int(time.time()))
    stage: str | None = None
    cost: ModelCost | None = None
    config_digest: str | None = None
    warnings: list[str] = Field(default_factory=list)

    @classmethod
    def from_result(
        cls, result: StructuredModelResult, *, config_digest: str | None = None
    ) -> ModelCallRecord:
        return cls(
            mode=result.mode,
            model=result.model,
            model_version=result.model_version,
            provider=result.provider,
            prompt_version=result.prompt_version,
            input_refs=result.input_refs,
            output=result.output,
            confidence=result.confidence,
            timestamp=result.timestamp,
            stage=result.stage,
            cost=result.cost,
            config_digest=config_digest,
            warnings=result.warnings,
        )

    def to_evidence(
        self,
        source_id: uuid.UUID,
        *,
        locator: str | None = None,
        segment_id: uuid.UUID | None = None,
    ) -> Evidence:
        """Assemble this model call into an evidence row (never semantic state).

        The model-call record is *metadata about a model invocation* (see
        :class:`ModelCallRecord`), so it is recorded under the existing
        ``METADATA`` evidence kind with the full record in ``quality``. It is not
        a new extraction-surface kind, and it is never semantic state and never a
        projection write.
        """
        tool_versions: dict[str, str] = {
            "provider": self.provider,
            "model": self.model,
        }
        if self.model_version:
            tool_versions["model_version"] = self.model_version
        if self.prompt_version:
            tool_versions["prompt_version"] = self.prompt_version
        return Evidence(
            source_id=source_id,
            segment_id=segment_id,
            evidence_kind=EvidenceKind.METADATA,
            locator=locator,
            extraction_stage=self.stage,
            tool_versions=tool_versions,
            config_digest=self.config_digest,
            confidence=self.confidence,
            quality={
                "record_id": self.record_id,
                "provider": self.provider,
                "model": self.model,
                "model_version": self.model_version,
                "prompt_version": self.prompt_version,
                "mode": self.mode.value,
                "input_refs": self.input_refs,
                "output": self.output,
                "timestamp": self.timestamp,
                "stage": self.stage,
                "cost": None
                if self.cost is None
                else {
                    "input_tokens": self.cost.input_tokens,
                    "output_tokens": self.cost.output_tokens,
                    "currency": self.cost.currency,
                },
                "warnings": self.warnings,
            },
        )


class ModelProviderUnavailable(RuntimeError):  # noqa: N818 - stable public contract name
    """A provider could not be used (not installed / not reachable / gated).

    This is the typed, reported failure for unavailable or gated model
    enhancements — never a fabricated silent fallback. Callers route it into
    capability reporting and a documented gate.
    """


class ModelProvider(Protocol):
    """The binding provider seam (CONTRACTS §Plugin and stage envelopes).

    ``mode`` is ``completion | embedding``; local and remote adapters are
    interchangeable behind this interface. Implementations return a structured,
    confidence-scoped result and raise :class:`ModelProviderUnavailable` when
    unusable. No provider writes semantic state or a projection directly.
    """

    name: str

    def invoke(self, request: ModelRequest) -> StructuredModelResult: ...
