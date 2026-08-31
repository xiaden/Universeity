"""Versioned prompt/config/input-reference material for semantic analysis (Plan M P1-S3).

The provider-backed path (Phase 2) invokes ``ModelProvider.invoke`` with a
**versioned** prompt, a **config digest** that encodes the prompt/analyzer/parser
versions, and the **input evidence references** that substantiate the call. This
module owns that material so prompt/config provenance is durable and a changed
prompt/parser/analyzer produces a distinguishable config digest (Task §13, DD
§Provider/plugin) — nothing here invokes a provider; it only builds the request
material the strict parser (:mod:`umd.analysis.semantic_parser`) will validate.
"""

from __future__ import annotations

import hashlib

#: Stable analyzer tag recorded in ``GeneratedBy.analyzer`` for the provider path.
SEMANTIC_ANALYZER = "umd-semantic-analysis@1"
#: Version of the semantic-analysis instruction (bump on any prompt change).
#: @2 embeds the full per-category JSON schema (exact field names per category,
#: required fields, enums, confidence bounds, and segment/evidence-ref
#: requirements) so a real Ollama/vLLM provider emitting natural names is not
#: rejected item-by-item by the strict parser (Plan M P3-S2 QA Round 1 fix).
SEMANTIC_PROMPT_VERSION = "semantic-analysis@2"
#: Version of the strict output parser (bump on any accepted-schema change).
SEMANTIC_PARSER_VERSION = "umd-semantic-parser@1"


def build_semantic_prompt(
    *,
    input_refs: list[str] | None = None,
    segment_context: str | None = None,
    language: str | None = None,
) -> str:
    """Return the versioned semantic-analysis instruction (provider completion).

    The instruction asks the provider to emit a JSON object of the typed
    categories (scenes, entities, aliases, presence, utterances, speakers,
    traits, relationships, emotions, states, context). Every observation MUST
    carry an exact ``segment`` reference and a ``confidence`` in [0,1]. The
    instruction is generic — no audiobook/TTS/Alexandria-specific schema — and
    explicitly forbids inventing observations without segment evidence.
    """
    refs = "\n".join(f"- {r}" for r in (input_refs or [])) or "(none provided)"
    ctx = segment_context or "(segment context not provided)"
    lang = f" The source language is {language}." if language else ""
    return (
        "You are a semantic text-analysis assistant. Analyze the supplied "
        "document segments and return a SINGLE JSON object with these keys: "
        '"scenes", "entities", "aliases", "presence", "utterances", "speakers", '
        '"traits", "relationships", "emotions", "states", "context".'
        f"{lang}\n"
        "Rules:\n"
        "- Every observation object MUST include an exact 'segment' reference and "
        "a 'confidence' number in [0,1]. The 'segment' is an object with a "
        "required 'locator' string and optional 'segment_id'/'evidence_ref' "
        "(when known) and 'chapter'/'paragraph' integers.\n"
        "- Use EXACTLY the field names below for each category. A missing or "
        "renamed required field causes that observation to be REJECTED.\n"
        "- Never invent an observation that is not supported by a segment; leave "
        "a category absent (empty list) when there is no evidence.\n"
        "- Keep output GENERIC and schema-stable; do not add consumer-specific "
        "fields.\n"
        "Per-category schema (each entry is an object with the shared segment + "
        "confidence fields plus these category fields):\n"
        '- "scenes": {"scene_ref": string (required), "boundary": "start"|"end" '
        '"(required), "label": string (optional)}\n'
        '- "entities": {"mention": string (required), "entity_type": string '
        '"(required; e.g. "character")}\n'
        '- "aliases": {"canonical_name": string (required), "alias": string '
        '"(required), "entity_ref": string (optional)}\n'
        '- "presence": {"entity": string (required), "present_in": string '
        '"(required)}\n'
        '- "utterances": {"utterance_text": string (required), "speaker": '
        '"string (optional)}\n'
        '- "speakers": {"speaker_label": string (required), "utterance_ref": '
        '"string (optional)}\n'
        '- "traits": {"entity": string (required), "trait": string (required)}\n'
        '- "relationships": {"subject_ref": string (required), "predicate": '
        '"string (required), "object_ref": string (required)}\n'
        '- "emotions": {"entity": string (required), "emotion": string '
        '"(required)}\n'
        '- "states": {"entity": string (required), "observed_state": string '
        '"(required; note: use "observed_state", NOT "state")}\n'
        '- "context": {"context_type": string (required), "value": string '
        '"(required)}\n'
        "Input evidence references:\n"
        f"{refs}\n"
        "Segment context:\n"
        f"{ctx}\n"
    )


def semantic_config_digest(
    *,
    parser_version: str = SEMANTIC_PARSER_VERSION,
    prompt_version: str = SEMANTIC_PROMPT_VERSION,
    analyzer: str = SEMANTIC_ANALYZER,
) -> str:
    """Deterministic configuration digest over the semantic-analysis material.

    Encoding prompt/parser/analyzer versions means a changed prompt or accepted
    schema yields a distinct digest, so evidence ``uq_evidence_identity``
    (source_id, locator, evidence_kind, config_digest) distinguishes a rerun
    after a material change without mutating historical rows.
    """
    payload = "|".join([analyzer, prompt_version, parser_version])
    return f"umd-semantic-analysis::{hashlib.sha256(payload.encode()).hexdigest()[:16]}"


def semantic_input_refs(segments: list[str]) -> list[str]:
    """Assemble the input evidence references substantiating a semantic call.

    ``segments`` are the canonical segment locators (Plan L) the analysis is
    scoped to; they become ``ModelRequest.input_refs`` (evidence of the call,
    never a claim of truth).
    """
    return [s for s in segments if s]


__all__ = [
    "SEMANTIC_ANALYZER",
    "SEMANTIC_PARSER_VERSION",
    "SEMANTIC_PROMPT_VERSION",
    "build_semantic_prompt",
    "semantic_config_digest",
    "semantic_input_refs",
]
