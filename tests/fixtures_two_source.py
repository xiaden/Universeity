"""Deterministic two-source fixture for Plan S Phase 3.

Proves source-independent identity (requirement ledger item 3) with a small,
deterministic cast across two works:

  * Work ``NOVEL`` has two *editions* (byte-different re-uploads, same
    ``work_id``, roles ``primary`` / ``alias``) — source A and source B. Both
    contain the SAME characters (Mara, Ellis) plus one ambiguous candidate
    (Astra). The shared work membership is the *supported correspondence* that
    authorizes Mara/Ellis to collapse to ONE opaque canonical ref across A and B.
  * Work ``OTHER`` (source C) contains Mara and Ellis again — UNRELATED
     same-name characters that must remain distinct from the Novel cast and stay
     reviewable (never merged by string equality).
  * Source A and source B place ``John`` at the SAME structural position
     (``chapter/1/paragraph/6``) but with DIFFERENT surrounding paragraph content.
     Same name + same work + coincident structure is ONLY candidate narrowing:
     because the surrounding content differs, John A and John B must resolve to TWO
     DISTINCT opaque canonical refs (Plan T P1-S2/R3 + P3-S1 content-derived proof).
  * ``ASTRA`` is deliberately ambiguous (``confidence_state=AMBIGUOUS`` with two
     plausible co-occurring candidates) so identity stays unresolved / reviewable.

All source bytes are deterministic and small. Immutable bytes and the Lantern
Keeper fixture values (``tests/fixtures.py``) are NOT touched.
"""

from __future__ import annotations

# Deterministic, well-formed UUIDs reused across tests (umd_db truncates tables
# between tests, so fixed ids are safe).
NOVEL_WORK = "11111111-1111-1111-1111-111111111111"
OTHER_WORK = "22222222-2222-2222-2222-222222222222"

SOURCE_A = "aaaaaaaa-0000-0000-0000-000000000001"  # Novel edition (primary)
SOURCE_B = "bbbbbbbb-0000-0000-0000-000000000002"  # Novel edition (alias)
SOURCE_C = "cccccccc-0000-0000-0000-000000000003"  # Other (unrelated)

WORK_BY_SOURCE: dict[str, str] = {
    SOURCE_A: NOVEL_WORK,
    SOURCE_B: NOVEL_WORK,
    SOURCE_C: OTHER_WORK,
}

ROLE_BY_SOURCE: dict[str, str] = {
    SOURCE_A: "primary",
    SOURCE_B: "alias",
    SOURCE_C: "primary",
}


def _q(
    text: str,
    *,
    locator: str,
    confidence: float = 0.85,
    confidence_state: str = "CONFIRMED",
    co_occurring: list[str] | None = None,
    normalized_forms: list[str] | None = None,
    context_text: str | None = None,
) -> dict:
    """Build one evidence-quality spec (mirrors ``_seed_cast`` in tests).

    ``context_text`` is the surrounding paragraph text. Its content digest feeds the
    resolution evidence anchor (``ctx:``), so coincident-structural same-name mentions
    separate ONLY when their surrounding content differs (Plan T P3-S1).
    """
    quality: dict = {
        "candidate_kind": "entity",
        "mention_text": text,
        "entity_type": "CHARACTER",
        "confidence": confidence,
        "confidence_state": confidence_state,
        "co_occurring": co_occurring or [],
        "normalized_forms": normalized_forms or [text],
    }
    if context_text is not None:
        quality["context_text"] = context_text
    return {
        "text": text,
        "locator": locator,
        "quality": quality,
    }


# Each tag -> ordered list of evidence-quality specs. Source A and B mirror each
# other (same book, different editions); source C is an unrelated work that
# reuses the same two names plus its own ambiguous name. Shared characters carry
# IDENTICAL surrounding content across A/B (the supported shared identity); John A
# and John B sit at the SAME structural position but with DIFFERENT content, so the
# content digest (not a locator difference) is what keeps them apart.
_P1 = "The apprentice Mara met the warden Orin and Mara took the lantern."
_P2 = "Ellis the cartographer watched the flame and Ellis smiled."
_P3 = "Mara knelt and the wick caught and the light held steady."
_P4 = "Ellis unrolled the chart and Ellis marked the eastern road."
_P5 = "Zed and Wren argued while Astra watched them both."
_JOHN_A = "The merchant John arrived by dusk and John bought the map from Mara."
_JOHN_B = "The courier John rode through the night and John carried a sealed letter."

TWO_SOURCE_MENTION_SPECS: dict[str, list[dict]] = {
    SOURCE_A: [
        _q("Mara", locator="chapter/1/paragraph/1", co_occurring=["Ellis"], context_text=_P1),
        _q("Ellis", locator="chapter/1/paragraph/2", co_occurring=["Mara"], context_text=_P2),
        _q("Mara", locator="chapter/1/paragraph/3", co_occurring=["Ellis"], context_text=_P3),
        _q("Ellis", locator="chapter/1/paragraph/4", co_occurring=["Mara"], context_text=_P4),
        _q(
            "Astra",
            locator="chapter/1/paragraph/5",
            confidence=0.4,
            confidence_state="AMBIGUOUS",
            co_occurring=["Zed", "Wren"],  # two plausible candidates -> reviewable
            context_text=_P5,
        ),
        # John A: same work + coincident structure as B's John but DIFFERENT content.
        _q("John", locator="chapter/1/paragraph/6", co_occurring=["Mara"], context_text=_JOHN_A),
    ],
    SOURCE_B: [
        _q("Mara", locator="chapter/1/paragraph/1", co_occurring=["Ellis"], context_text=_P1),
        _q("Ellis", locator="chapter/1/paragraph/2", co_occurring=["Mara"], context_text=_P2),
        _q("Mara", locator="chapter/1/paragraph/3", co_occurring=["Ellis"], context_text=_P3),
        _q("Ellis", locator="chapter/1/paragraph/4", co_occurring=["Mara"], context_text=_P4),
        _q(
            "Astra",
            locator="chapter/1/paragraph/5",
            confidence=0.4,
            confidence_state="AMBIGUOUS",
            co_occurring=["Zed", "Wren"],
            context_text=_P5,
        ),
        # John B: same name + work + COINCIDENT structure but different content.
        _q("John", locator="chapter/1/paragraph/6", co_occurring=["Ellis"], context_text=_JOHN_B),
    ],
    SOURCE_C: [
        _q(
            "Mara",
            locator="chapter/1/paragraph/1",
            co_occurring=["Ellis"],
            context_text="Sailor Mara guided the ship by starlight and Mara sang low.",
        ),
        _q(
            "Ellis",
            locator="chapter/1/paragraph/2",
            co_occurring=["Mara"],
            context_text="Ellis the cook traded salt and Ellis bartered for rope.",
        ),
        _q(
            "Nyx",
            locator="chapter/1/paragraph/3",
            confidence=0.4,
            confidence_state="AMBIGUOUS",
            co_occurring=["Vex", "Rook"],
            context_text="Vex and Rook whispered while Nyx kept the lantern dark.",
        ),
    ],
}

SHARED_NOVEL_NAMES = ("Mara", "Ellis")  # supported shared identity across A and B
AMBIGUOUS_NAME = "Astra"  # unresolved / reviewable in Novel
AMBIGUOUS_OTHER_NAME = "Nyx"  # unresolved / reviewable in Other

#: Same name + same work in A and B at COINCIDENT structure but with DIFFERENT
#: surrounding content -> must stay separate (Plan T R3 + P3-S1 content-derived
#: proof). John A and John B both live at chapter/1/paragraph/6.
SAME_NAME_COLLISION = "John"


def two_source_mention_specs(source_id: str) -> list[dict]:
    """Return the ordered evidence-quality specs for a source tag."""
    return list(TWO_SOURCE_MENTION_SPECS[source_id])
