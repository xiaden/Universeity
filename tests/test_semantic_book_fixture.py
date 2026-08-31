"""Determinism + semantic-input tests for the Phase-P small-book fixture.

The book fixture (``fixtures.py``: ``semantic_book_*``) is the generic,
repository-owned oracle used across Plans L-Q. These tests prove that repeated
construction yields identical bytes, manifests, segment IDs / deterministic
keys / locators, evidence-identity material ((source_id, locator, evidence_kind,
config_digest)), and that every declared semantic-input threshold (chapters,
scenes, characters, aliases, narration+dialogue, multiple utterances, explicit +
implicit speaker candidates, repeated presence, trait, relationship, ambiguity)
is satisfied by the content.

Pure determinism tests: no live Postgres, no provider, no production writes —
they exercise only the deterministic fixture generators and the existing text
dispatch/segmenters (Plan-L ``TextDispatch`` seam) read-only.
"""

from __future__ import annotations

import hashlib
import re
import zipfile

from fixtures import (
    BOOK_ALIASES,
    BOOK_AMBIGUOUS_FACT,
    BOOK_CHAPTER_COUNT,
    BOOK_CHARACTERS,
    BOOK_EVIDENCE_CONFIG_DIGEST,
    BOOK_EXPECTED_PARAGRAPHS,
    BOOK_EXPECTED_SECTION_PATHS,
    BOOK_FORMATS,
    BOOK_RELATIONSHIPS,
    BOOK_SCENE_COUNT,
    BOOK_SOURCE_SHA512,
    BOOK_TITLE,
    BOOK_TRAITS,
    semantic_book_bytes,
    semantic_book_scenes,
    semantic_book_structural_paths,
    semantic_book_txt,
)
from umd.extractors.dispatch import dispatch_text
from umd.segmentation.registry import InMemorySegmentStore, SegmentRegistry

#: Segment types that carry the deterministic structural locator hierarchy
#: (document/chapter/section/paragraph). The real segmenters also emit
#: sentence/token children for TXT; those are deliberately excluded from the
#: structural-path oracle (which is document/chapter/section/paragraph level).
STRUCTURAL_TYPES = ("document", "chapter", "section", "paragraph")

SID = "00000000-0000-4000-8000-0000000000ab"
SHA = "a" * 128

#: Explicit speaker-attribution: a quoted utterance adjacent to a speech verb +
#: a capitalized name ("...said Alice." / "Alice said, ...").
# 1) "..." , said Alice.   2) "..." , Alice said.   3) Alice said, "..."
_EXPLICIT_QUOTE = re.compile(
    r'"[^"]*"[.,;!?]?\s*(?:said|asked|cried|called|murmured|whispered)\s+[A-Z][a-z]+'
    r'|"[^"]*"[.,;!?]?\s+[A-Z][a-z]+\s+(?:said|asked|cried|called|murmured|whispered)\b'
    r"|[A-Z][a-z]+\s+(?:said|asked|cried|called|murmured|whispered)\s*[,:]?\s*\""
)
_QUOTED_SPAN = re.compile(r'"[^"]*"')


def _segment(fmt: str):
    """Dispatch the raw fixture bytes through the real Plan-L text dispatch +
    segmenter (read-only, in-memory store). Returns (result, segmentation)."""
    reg = SegmentRegistry(InMemorySegmentStore())
    res = dispatch_text(semantic_book_bytes(fmt), format=fmt, source_sha512=SHA)
    seg = res.segment(reg, source_id=SID, source_sha512=SHA)
    assert seg is not None, f"{fmt} routed off the text path (shortcut guard)"
    return res, seg


def _structural_paths(seg) -> set[str]:
    return {s.structural_path for s in seg.batch.created if s.segment_type in STRUCTURAL_TYPES}


def _paragraphs(text: str) -> list[str]:
    return [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]


# ---------------------------------------------------------------------------
# Byte + hash determinism
# ---------------------------------------------------------------------------


def test_repeated_construction_identical_bytes_and_pinned_hash() -> None:
    for fmt in BOOK_FORMATS:
        a = semantic_book_bytes(fmt)
        b = semantic_book_bytes(fmt)
        assert a == b, f"{fmt} bytes differ across repeated construction"
        # pinned, non-circular fixity: recomputed hash must equal the literal.
        assert hashlib.sha512(a).hexdigest() == BOOK_SOURCE_SHA512[fmt], fmt


def test_epub_manifest_deterministic() -> None:
    import io

    def names() -> list[str]:
        with zipfile.ZipFile(io.BytesIO(semantic_book_bytes("epub"))) as z:
            return z.namelist()

    assert names() == names()
    assert "mimetype" in names()
    assert any(n.endswith(".opf") for n in names())


# ---------------------------------------------------------------------------
# No hidden normalized raw-byte shortcut: the bytes route through the real
# per-format parser/segmenter (Plan-L TextDispatch) and actually segment.
# ---------------------------------------------------------------------------


def test_every_format_routes_as_text_and_segments_raw_bytes() -> None:
    for fmt in BOOK_FORMATS:
        res, seg = _segment(fmt)
        assert res.route == "text", fmt
        assert res.parser == fmt, fmt
        assert res.text, fmt
        assert len(seg.batch.created) > 0, fmt


# ---------------------------------------------------------------------------
# Segment / locator determinism vs the explicit oracle
# ---------------------------------------------------------------------------


def test_segment_ids_and_keys_deterministic_across_runs() -> None:
    for fmt in BOOK_FORMATS:
        _res1, seg1 = _segment(fmt)
        _res2, seg2 = _segment(fmt)
        assert [s.segment_id for s in seg1.batch.created] == [
            s.segment_id for s in seg2.batch.created
        ], fmt
        assert [s.deterministic_key for s in seg1.batch.created] == [
            s.deterministic_key for s in seg2.batch.created
        ], fmt
        assert [s.locator for s in seg1.batch.created] == [s.locator for s in seg2.batch.created], (
            fmt
        )
        assert len(seg1.batch.created) == len(seg2.batch.created) == seg1.batch.total, fmt


def test_structural_paths_match_explicit_per_format_oracle() -> None:
    for fmt in BOOK_FORMATS:
        _res, seg = _segment(fmt)
        real = _structural_paths(seg)
        expected = set(semantic_book_structural_paths(fmt))
        assert real == expected, (
            f"{fmt}: real structural paths differ from the explicit oracle\n"
            f"  missing: {sorted(expected - real)}\n"
            f"  extra:   {sorted(real - expected)}"
        )
        # chapter + section + paragraph counts per the declared expectations.
        assert all(p in real for p in BOOK_EXPECTED_SECTION_PATHS[fmt]), fmt
        paragraphs = [p for p in real if "/paragraph/" in p]
        assert len(paragraphs) == BOOK_EXPECTED_PARAGRAPHS[fmt], fmt


# ---------------------------------------------------------------------------
# Evidence-identity material determinism ((source_id, locator, evidence_kind,
# config_digest)) — the dedup identity later phases build evidence from.
# ---------------------------------------------------------------------------


def _evidence_identity(fmt: str, kinds: tuple[str, ...]):
    res, seg = _segment(fmt)
    return (
        sorted(
            (SID, s.locator, kind, res.config_digest)
            for s in seg.batch.created
            if s.segment_type in STRUCTURAL_TYPES
            for kind in kinds
        ),
        res.config_digest,
    )


def test_evidence_identity_material_deterministic_and_unique() -> None:
    kinds = ("text_span", "entity_candidate")
    for fmt in BOOK_FORMATS:
        a, digest_a = _evidence_identity(fmt, kinds)
        b, digest_b = _evidence_identity(fmt, kinds)
        assert a == b and a, fmt
        assert len(a) == len(set(a)), f"{fmt}: evidence-identity tuples must be unique"
        # config digest must be the pinned, non-null value production expects.
        assert digest_a == digest_b == BOOK_EVIDENCE_CONFIG_DIGEST, fmt


# ---------------------------------------------------------------------------
# Expected semantic inputs (chapters/scenes/characters/aliases/utterances/
# presence/trait/relationship/ambiguity thresholds).
# ---------------------------------------------------------------------------


def test_declared_chapter_and_scene_thresholds() -> None:
    scenes = semantic_book_scenes()
    assert BOOK_CHAPTER_COUNT >= 2
    assert len({ci for ci, _t, _p in scenes}) >= 2
    assert BOOK_SCENE_COUNT >= 3
    assert len(scenes) >= 3


def test_character_and_alias_thresholds() -> None:
    assert len(BOOK_CHARACTERS) >= 3
    assert len(BOOK_ALIASES) >= 2
    text = semantic_book_txt()
    # every alias (nickname and role/title) must actually appear verbatim so later
    # resolution phases have a surface to anchor alias-of evidence.
    for alias in BOOK_ALIASES:
        assert alias.lower() in text.lower(), f"alias {alias!r} absent from book text"


def test_narration_dialogue_and_multiple_utterances() -> None:
    text = semantic_book_txt()
    paragraphs = _paragraphs(text)
    # narration: at least one paragraph with no quoted dialogue.
    assert any(not _QUOTED_SPAN.search(p) for p in paragraphs)
    # dialogue: multiple quoted utterances present.
    utterances = _QUOTED_SPAN.findall(text)
    assert len(utterances) >= 4, f"expected multiple utterances, found {len(utterances)}"


def test_explicit_and_implicit_speaker_attribution_candidates() -> None:
    paragraphs = _paragraphs(semantic_book_txt())
    explicit = [p for p in paragraphs if _EXPLICIT_QUOTE.search(p)]
    implicit = [p for p in paragraphs if _QUOTED_SPAN.search(p) and not _EXPLICIT_QUOTE.search(p)]
    assert explicit, "no explicitly-attributed utterance found"
    assert implicit, "no implicitly-attributed (unnamed-speaker) utterance found"


def test_repeated_character_presence_across_scenes() -> None:
    presence: dict[str, int] = {}
    for _ci, _scene_title, paras in semantic_book_scenes():
        joined = "\n".join(paras)
        for char in BOOK_CHARACTERS:
            if char in joined:
                presence[char] = presence.get(char, 0) + 1
    # at least one character appears in more than one scene.
    assert any(count > 1 for count in presence.values()), presence
    # Mara and Ellis are explicitly designed to recur across scenes.
    assert presence.get("Mara", 0) > 1 and presence.get("Ellis", 0) > 1, presence


def test_trait_and_relationship_present() -> None:
    text = semantic_book_txt()
    for trait in BOOK_TRAITS.values():
        assert trait in text, f"trait {trait!r} absent"
    assert BOOK_RELATIONSHIPS, "fixture must declare at least one relationship"
    # the sibling relationship must be textually present (Mara/Ellis).
    assert "brother" in text


def test_ambiguous_non_confirmed_fact_declared_and_present() -> None:
    # The designated ambiguous fact: Mara claims she saw a light in the tower;
    # the narrator never confirms it. Must stay resolvable as ambiguous.
    assert BOOK_AMBIGUOUS_FACT
    assert "watchtower" in BOOK_AMBIGUOUS_FACT and "light" in BOOK_AMBIGUOUS_FACT
    text = semantic_book_txt()
    # the claim itself is uttered (explicit dialogue), and the narrator's
    # subsequent observation withholds confirmation ("no lamp and no candle").
    assert "I saw a light up here last night" in text
    assert "no lamp and no candle" in text
    # the narrator leaves the claim open ("whether it had been real") and never
    # flatly confirms it ("the light was real" is absent from the text).
    assert "whether it had been real" in text
    assert "the light was real" not in text


def test_book_title_and_genericness() -> None:
    assert BOOK_TITLE == "The Lantern Keeper"
    # generic + repository-owned, not a provider-specific golden database: the
    # fixture declares only content + determinism, no provider/schema coupling.
    assert set(BOOK_FORMATS) == {"txt", "markdown", "epub"}
