"""Deterministic-seed randomized property tests for locator round trips (P2-S4).

No optional test dependency is required: a seeded ``random.Random`` drives the
property coverage so results are reproducible across runs.
"""

from __future__ import annotations

import random

from umd.domain.locators import (
    CfiSelector,
    IIIFSelector,
    Locator,
    MediaFragmentSelector,
    PipelineVersion,
    StructuralSelector,
    parse_locator,
)

rng = random.Random(20260825)  # noqa: S311 - seeded for reproducible property tests, not crypto


def _frag(kind: int):
    if kind == 0:
        return StructuralSelector(
            path=f"chapter/{rng.randint(1, 40)}/paragraph/{rng.randint(1, 200)}"
        )
    if kind == 1:
        x, y, w, h = (
            rng.randint(0, 2000),
            rng.randint(0, 2000),
            rng.randint(1, 800),
            rng.randint(1, 800),
        )
        return IIIFSelector(region=f"{x},{y},{w},{h}")
    if kind == 2:
        start = rng.randint(0, 9_000_000)
        end = start + rng.randint(1, 5_000_000)
        frag = MediaFragmentSelector(t=f"{start},{end}")
        if rng.random() < 0.5:
            frag = MediaFragmentSelector(t=f"{start},{end}", track=str(rng.randint(1, 3)))
        return frag
    if kind == 3:
        return CfiSelector(cfi=f"epubcfi(/6/{rng.randint(1, 30)}!/4/{rng.randint(1, 30)}/2:0)")
    return None


def test_randomized_canonical_round_trip() -> None:
    for _ in range(200):
        version = (
            PipelineVersion("text", "pandoc22", "epub3", version=rng.randint(0, 3))
            if rng.random() < 0.7
            else None
        )
        frag = _frag(rng.randint(0, 4))
        loc = Locator(
            scheme="source",
            source_id=f"src-{rng.randint(1, 999)}",
            modality=rng.choice(["text", "image", "audio", "video", "subtitle"]),
            segment=f"seg-{rng.randint(0, 10**6)}",
            version=version,
            frag=frag,
        )
        canonical = loc.canonical()
        reparsed = parse_locator(canonical)
        assert reparsed.canonical() == canonical
        assert reparsed.source_id == loc.source_id
        assert reparsed.modality == loc.modality
        assert reparsed.segment == loc.segment
        assert (reparsed.version.tag if reparsed.version else None) == (
            version.tag if version else None
        )
        if frag is not None:
            assert reparsed.frag is not None
            assert reparsed.frag.to_frag() == frag.to_frag()


def test_randomized_bare_locator_has_no_version() -> None:
    for _ in range(50):
        loc = Locator(
            scheme="source",
            source_id="src-x",
            modality="text",
            segment="seg-y",
            version=None,
        )
        parsed = parse_locator(loc.canonical())
        assert parsed.version is None
        assert "#" not in parsed.canonical()


def test_structural_selector_is_never_lost_in_round_trip() -> None:
    for _ in range(50):
        path = f"chapter/{rng.randint(1, 50)}/sentence/{rng.randint(1, 500)}"
        loc = Locator(
            scheme="source",
            source_id="src",
            modality="text",
            segment="abc123",
            frag=StructuralSelector(path=path),
        )
        reparsed = parse_locator(loc.canonical())
    assert isinstance(reparsed.frag, StructuralSelector)
    assert reparsed.frag.path == path
