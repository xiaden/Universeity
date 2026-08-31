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
  * Source A adds ``John`` at ``paragraph/6`` and source B adds ``John`` at
     ``paragraph/7`` — the SAME name and the SAME work but NO shared evidence
     (distinct locators, no explicit correspondence). Same-name/same-work is
     only candidate narrowing, never proof: John A and John B must resolve to
     TWO DISTINCT opaque canonical refs (Plan T P1-S2 / R3 collision proof).
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
) -> dict:
    """Build one evidence-quality spec (mirrors ``_seed_cast`` in tests)."""
    return {
        "text": text,
        "locator": locator,
        "quality": {
            "candidate_kind": "entity",
            "mention_text": text,
            "entity_type": "CHARACTER",
            "confidence": confidence,
            "confidence_state": confidence_state,
            "co_occurring": co_occurring or [],
            "normalized_forms": normalized_forms or [text],
        },
    }


# Each tag -> ordered list of evidence-quality specs. Source A and B mirror each
# other (same book, different editions); source C is an unrelated work that
# reuses the same two names plus its own ambiguous name.
TWO_SOURCE_MENTION_SPECS: dict[str, list[dict]] = {
    SOURCE_A: [
        _q("Mara", locator="chapter/1/paragraph/1", co_occurring=["Ellis"]),
        _q("Ellis", locator="chapter/1/paragraph/2", co_occurring=["Mara"]),
        _q("Mara", locator="chapter/1/paragraph/3", co_occurring=["Ellis"]),
        _q("Ellis", locator="chapter/1/paragraph/4", co_occurring=["Mara"]),
        _q(
            "Astra",
            locator="chapter/1/paragraph/5",
            confidence=0.4,
            confidence_state="AMBIGUOUS",
            co_occurring=["Zed", "Wren"],  # two plausible candidates -> reviewable
        ),
        # John A: same work, no shared evidence with B's John -> distinct ref.
        _q("John", locator="chapter/1/paragraph/6", co_occurring=["Mara"]),
    ],
    SOURCE_B: [
        _q("Mara", locator="chapter/1/paragraph/1", co_occurring=["Ellis"]),
        _q("Ellis", locator="chapter/1/paragraph/2", co_occurring=["Mara"]),
        _q("Mara", locator="chapter/1/paragraph/3", co_occurring=["Ellis"]),
        _q("Ellis", locator="chapter/1/paragraph/4", co_occurring=["Mara"]),
        _q(
            "Astra",
            locator="chapter/1/paragraph/5",
            confidence=0.4,
            confidence_state="AMBIGUOUS",
            co_occurring=["Zed", "Wren"],
        ),
        # John B: same name + work but different evidence -> distinct from John A.
        _q("John", locator="chapter/1/paragraph/7", co_occurring=["Ellis"]),
    ],
    SOURCE_C: [
        _q("Mara", locator="chapter/1/paragraph/1", co_occurring=["Ellis"]),
        _q("Ellis", locator="chapter/1/paragraph/2", co_occurring=["Mara"]),
        _q(
            "Nyx",
            locator="chapter/1/paragraph/3",
            confidence=0.4,
            confidence_state="AMBIGUOUS",
            co_occurring=["Vex", "Rook"],
        ),
    ],
}

SHARED_NOVEL_NAMES = ("Mara", "Ellis")  # supported shared identity across A and B
AMBIGUOUS_NAME = "Astra"  # unresolved / reviewable in Novel
AMBIGUOUS_OTHER_NAME = "Nyx"  # unresolved / reviewable in Other

#: Same name + same work in A and B but NO shared evidence -> must stay separate
#: (Plan T R3 collision proof). John A lives at paragraph/6, John B at paragraph/7.
SAME_NAME_COLLISION = "John"


def two_source_mention_specs(source_id: str) -> list[dict]:
    """Return the ordered evidence-quality specs for a source tag."""
    return list(TWO_SOURCE_MENTION_SPECS[source_id])
