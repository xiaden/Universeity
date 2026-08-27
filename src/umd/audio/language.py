"""Reference language identification (Phase C, P2-S1).

The DD baseline emits *language* for the audio path. Real language identification
requires a model (GATED — see :mod:`umd.audio.asr`). The non-gated reference
provider (``umd-reference-lang``) NEVER fabricates a language it did not receive:
it reports the **source-native / descriptor-declared** language when one is given,
otherwise the **config-declared** language when configured, and honestly reports
``unknown`` with ``sources=["unknown"]`` otherwise. The reported language is
confidence-scoped (it is source/config provenance, not a model inference).
"""

from __future__ import annotations

from umd.audio.types import DecodedAudio, LanguageResult


def identify_language(
    _audio: DecodedAudio,
    *,
    declared_language: str | None = None,
    config_language: str | None = None,
) -> LanguageResult:
    """Return the language the baseline can honestly report for the source."""
    if declared_language:
        return LanguageResult(
            language=declared_language,
            confidence=0.5,
            provider="umd-reference-lang",
            sources=["declared"],
        )
    if config_language:
        return LanguageResult(
            language=config_language,
            confidence=0.4,
            provider="umd-reference-lang",
            sources=["config"],
        )
    return LanguageResult(
        language="unknown",
        confidence=0.0,
        provider="umd-reference-lang",
        sources=["unknown"],
    )
