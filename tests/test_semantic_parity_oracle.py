"""Tests for the generic Alexandria 2a-2f semantic parity oracle (Phase P2).

Proves CONTRACTS.md:83 ``SemanticParityOracle.compare(fixture, modes) ->
ParityMatrix``: the oracle walks ONLY public typed evidence/segment/ledger/
projection/query surfaces for the six walks, compares deterministic / provider /
hybrid routes over the same fixture using normalized typed claim sets + real
provider provenance, and produces a parity matrix with PASS / DIFF / GATED /
UNSUPPORTED statuses that serializes to Markdown.

Pure test-side hermetic tests: no live Postgres, no live provider. The
deterministic route runs the real Plan-L TextDispatch -> segmenter -> Plan-M
SemanticTextAnalyzer deterministic path; the provider/hybrid routes exercise the
real provider code path via a registered fake provider (Plan M substitution
pattern) whose real provider/config/prompt provenance is recorded in the matrix,
while the unexecuted live-provider gate is reported honestly.
"""

from __future__ import annotations

from fixtures import BOOK_TITLE
from semantic_parity_oracle import (
    ROUTE_DETERMINISTIC,
    ROUTE_HYBRID,
    ROUTE_PROVIDER,
    WALK_2A,
    WALK_2B,
    WALK_2C,
    WALK_2D,
    WALK_2E,
    WALK_2F,
    WALKS,
    FakeSemanticProvider,
    ParityMatrix,
    SemanticParityOracle,
    TypedClaim,
    book_fixture,
)

MODES = (ROUTE_DETERMINISTIC, ROUTE_PROVIDER, ROUTE_HYBRID)


def _matrix() -> ParityMatrix:
    oracle = SemanticParityOracle()
    return oracle.compare(book_fixture(), modes=MODES)


def _claims(matrix: ParityMatrix, walk: str, route: str) -> list[TypedClaim]:
    row = matrix.row(walk, route)
    assert row is not None, f"missing row for {walk}/{route}"
    return list(row.claims)


def _status(matrix: ParityMatrix, walk: str, route: str) -> str:
    row = matrix.row(walk, route)
    assert row is not None, f"missing row for {walk}/{route}"
    return row.status


def _gate(matrix: ParityMatrix, route: str) -> str | None:
    row = matrix.row(WALK_2A, route)
    assert row is not None
    return row.gate


# ---------------------------------------------------------------------------
# 2a scene segmentation
# ---------------------------------------------------------------------------


def test_matrix_has_one_row_per_walk_route() -> None:
    matrix = _matrix()
    assert matrix.title == BOOK_TITLE
    expected = len(WALKS) * len(MODES)
    assert len(matrix.rows) == expected, f"expected {expected} rows, got {len(matrix.rows)}"
    seen = {(r.walk, r.route) for r in matrix.rows}
    assert seen == {(w, r) for w in WALKS for r in MODES}
    # fixture hash is present (txt/markdown/epub) for Phase-3 report persistence.
    assert set(matrix.fixture_sha512) == {"txt", "markdown", "epub"}
    assert all(len(h) == 128 for h in matrix.fixture_sha512.values())


def test_2a_scene_segmentation_supported_across_routes() -> None:
    matrix = _matrix()
    # deterministic derives scene boundaries from chapter transitions + segment types.
    assert _status(matrix, WALK_2A, ROUTE_DETERMINISTIC) == "PASS"
    # The provider emits no scene observations (segmentation is a structural,
    # deterministic concern), so the provider-only route honestly reports
    # UNSUPPORTED rather than fabricating scene boundaries.
    assert _status(matrix, WALK_2A, ROUTE_PROVIDER) == "UNSUPPORTED"
    assert _status(matrix, WALK_2A, ROUTE_HYBRID) == "PASS"
    # both chapters yield scene-boundary observations on the deterministic path.
    subjects = {c.subject for c in _claims(matrix, WALK_2A, ROUTE_DETERMINISTIC)}
    assert any(s == "scene/1" or s == "scene/2" for s in subjects)
    # every 2a claim carries real segment support (no fabricated scene).
    for c in _claims(matrix, WALK_2A, ROUTE_HYBRID):
        assert c.support_refs, "2a claim must carry a segment support ref"
    assert not _claims(matrix, WALK_2A, ROUTE_PROVIDER)  # provider adds no scene obs


# ---------------------------------------------------------------------------
# 2b character discovery
# ---------------------------------------------------------------------------


def test_2b_character_discovery_entity_surface() -> None:
    matrix = _matrix()
    # Deterministic entity detection requires a capitalized run to repeat within a
    # single paragraph. The fixture prose repeats the three canonical characters
    # ("Mara", "Ellis", "Orin") within single paragraphs, so the deterministic
    # path discovers them as entity mentions (never fabricates unsupported ones).
    assert _status(matrix, WALK_2B, ROUTE_DETERMINISTIC) == "PASS"
    det_subjects = {c.subject for c in _claims(matrix, WALK_2B, ROUTE_DETERMINISTIC)}
    assert {"Mara", "Ellis", "Orin"} <= det_subjects, det_subjects
    for c in _claims(matrix, WALK_2B, ROUTE_DETERMINISTIC):
        assert c.predicate == "IS_CHARACTER"
        assert c.object == "character"
        assert c.support_refs, "character mention must carry evidence support"
    # Provider adds the fixture's canonical characters as evidence-supported
    # mentions (an honest extension of the deterministic baseline).
    assert _status(matrix, WALK_2B, ROUTE_PROVIDER) == "PASS"
    subjects = {c.subject for c in _claims(matrix, WALK_2B, ROUTE_PROVIDER)}
    assert {"Mara", "Ellis", "Orin"} <= subjects
    for c in _claims(matrix, WALK_2B, ROUTE_PROVIDER):
        assert c.predicate == "IS_CHARACTER"
        assert c.object == "character"
        assert c.support_refs, "character mention must carry evidence support"
    assert _status(matrix, WALK_2B, ROUTE_HYBRID) == "PASS"


# ---------------------------------------------------------------------------
# 2c alias resolution
# ---------------------------------------------------------------------------


def test_2c_alias_resolution_honest_unsupported_deterministic_then_provider() -> None:
    matrix = _matrix()
    # Deterministic leaves aliases ABSENT (honest degradation), never fabricated.
    assert _status(matrix, WALK_2C, ROUTE_DETERMINISTIC) == "UNSUPPORTED"
    assert not _claims(matrix, WALK_2C, ROUTE_DETERMINISTIC)
    # Provider adds evidence-supported aliases (an extension).
    assert _status(matrix, WALK_2C, ROUTE_PROVIDER) == "PASS"
    aliases = {(c.subject, c.object) for c in _claims(matrix, WALK_2C, ROUTE_PROVIDER)}
    assert ("Moss", "Mara") in aliases
    assert ("the apprentice", "Mara") in aliases
    assert ("the cartographer", "Ellis") in aliases
    assert ("the warden", "Orin") in aliases
    for c in _claims(matrix, WALK_2C, ROUTE_PROVIDER):
        assert c.predicate == "ALIAS_OF"
        assert c.support_refs, "alias claim must carry evidence support"
    assert _status(matrix, WALK_2C, ROUTE_HYBRID) == "PASS"


# ---------------------------------------------------------------------------
# 2d scene presence
# ---------------------------------------------------------------------------


def test_2d_scene_presence_present_in_edges() -> None:
    matrix = _matrix()
    # Presence is derived from the same repeating-capitalized-run heuristic; the
    # amended fixture repeats the canonical characters within single paragraphs,
    # so the deterministic path now emits PRESENT_IN edges for them.
    assert _status(matrix, WALK_2D, ROUTE_DETERMINISTIC) == "PASS"
    det_subjects = {c.subject for c in _claims(matrix, WALK_2D, ROUTE_DETERMINISTIC)}
    assert {"Mara", "Ellis", "Orin"} <= det_subjects, det_subjects
    assert _status(matrix, WALK_2D, ROUTE_PROVIDER) == "PASS"
    presence = _claims(matrix, WALK_2D, ROUTE_PROVIDER)
    subjects = {c.subject for c in presence}
    assert {"Mara", "Ellis", "Orin"} <= subjects
    for c in presence:
        assert c.predicate == "PRESENT_IN"
        assert c.support_refs, "presence edge must carry evidence support"
    assert _status(matrix, WALK_2D, ROUTE_HYBRID) == "PASS"


# ---------------------------------------------------------------------------
# 2e span attribution
# ---------------------------------------------------------------------------


def test_2e_span_attribution_evidence_surface() -> None:
    matrix = _matrix()
    assert _status(matrix, WALK_2E, ROUTE_DETERMINISTIC) == "PASS"
    assert _status(matrix, WALK_2E, ROUTE_PROVIDER) == "PASS"
    assert _status(matrix, WALK_2E, ROUTE_HYBRID) == "PASS"
    # deterministic baseline emits dialogue/narration evidence (SPAN_KIND).
    kinds = {c.object for c in _claims(matrix, WALK_2E, ROUTE_DETERMINISTIC)}
    assert "dialogue" in kinds and "narration" in kinds
    # provider rows are evidence (the model call + observations) with provider
    # provenance, never semantic authority.
    provider_authorities = {c.authority for c in _claims(matrix, WALK_2E, ROUTE_PROVIDER)}
    assert "provider" in provider_authorities


# ---------------------------------------------------------------------------
# 2f character description
# ---------------------------------------------------------------------------


def test_2f_character_description_honest_unsupported_then_provider() -> None:
    matrix = _matrix()
    # Deterministic leaves traits ABSENT.
    assert _status(matrix, WALK_2F, ROUTE_DETERMINISTIC) == "UNSUPPORTED"
    assert not _claims(matrix, WALK_2F, ROUTE_DETERMINISTIC)
    assert _status(matrix, WALK_2F, ROUTE_PROVIDER) == "PASS"
    traits = {(c.subject, c.object) for c in _claims(matrix, WALK_2F, ROUTE_PROVIDER)}
    assert ("Mara", "moss-green eyes") in traits
    assert ("Orin", "grey beard") in traits
    for c in _claims(matrix, WALK_2F, ROUTE_PROVIDER):
        assert c.predicate == "HAS_TRAIT"
        assert c.support_refs, "trait claim must carry evidence support"
    assert _status(matrix, WALK_2F, ROUTE_HYBRID) == "PASS"


# ---------------------------------------------------------------------------
# Route-level invariants
# ---------------------------------------------------------------------------


def test_hybrid_is_exactly_deterministic_union_provider_no_fabrication() -> None:
    matrix = _matrix()
    for walk in WALKS:
        det = set(_claims(matrix, walk, ROUTE_DETERMINISTIC))
        pro = set(_claims(matrix, walk, ROUTE_PROVIDER))
        hybrid = set(_claims(matrix, walk, ROUTE_HYBRID))
        assert hybrid == det | pro, (
            f"walk {walk}: hybrid != deterministic U provider "
            f"(extra={hybrid - (det | pro)}, missing={(det | pro) - hybrid})"
        )
        assert _status(matrix, walk, ROUTE_HYBRID) == "PASS"


def test_no_route_contains_a_fabricated_claim() -> None:
    matrix = _matrix()
    for walk in WALKS:
        for route in MODES:
            for c in _claims(matrix, walk, route):
                # Every non-evidence walk must reference a real segment locator.
                # 2e is the evidence surface itself (self-supporting).
                assert c.support_refs, f"{walk}/{route}: claim {c} has no support"
                assert c.provenance, f"{walk}/{route}: claim {c} has no provenance"
            assert _status(matrix, walk, route) != "DIFF", f"{walk}/{route} unexpectedly DIFF"


def test_provider_provenance_recorded_and_live_gate_honest() -> None:
    matrix = _matrix()
    # Provider/hybrid rows carry real provider provenance (fake provider, live not run).
    row = matrix.row(WALK_2C, ROUTE_PROVIDER)
    assert row is not None and row.provider_provenance is not None
    pp = row.provider_provenance
    assert pp["provider"] == "fake_semantic"
    assert pp["model"]
    assert pp["prompt_version"]
    assert pp["config_digest"]
    assert pp["mode"] == "fake-exercised"
    # The unexecuted live provider gate is reported honestly on the provider/hybrid rows.
    assert _gate(matrix, ROUTE_PROVIDER) == "unexecuted_live_provider"
    assert _gate(matrix, ROUTE_HYBRID) == "unexecuted_live_provider"
    # The matrix-level provider gate says GATED (no live provider).
    assert matrix.provider_gate["status"] == "GATED"
    assert matrix.provider_gate["live_provider_configured"] is False
    # And the deterministic row carries no gate.
    assert _gate(matrix, ROUTE_DETERMINISTIC) is None


def test_claim_confidence_authority_state_scope_present() -> None:
    matrix = _matrix()
    for walk in (WALK_2B, WALK_2C, WALK_2F):
        for c in _claims(matrix, walk, ROUTE_PROVIDER):
            assert 0.0 <= c.confidence <= 1.0
            assert c.authority == "provider"
            assert c.state  # semantic state present
            assert c.scope  # scope present


def test_fake_provider_is_contract_compliant() -> None:
    # The fake provider is genuinely exercised on the provider/hybrid routes: the
    # hybrid claim set includes provider-path observations on walks the
    # deterministic path leaves ABSENT (alias/trait), and its candidates survive
    # the analyzer's exact-support gate (they are not dropped or gated).
    from semantic_parity_oracle import _run_format

    rc = _run_format("txt", book_fixture(), run_provider=True)
    assert rc.hybrid[WALK_2C], "provider alias observations must merge into hybrid"
    assert rc.hybrid[WALK_2F], "provider trait observations must merge into hybrid"
    # every provider-path claim survived exact-support (real segment locators)
    for c in rc.provider[WALK_2F]:
        assert c.support_refs and c.support_refs[0] in rc.locators
    provider = FakeSemanticProvider()
    assert provider.calls == []  # a fresh fake has not been invoked


def test_markdown_serialization() -> None:
    matrix = _matrix()
    md = matrix.to_markdown()
    assert md.startswith(f"# Semantic Capability Parity Matrix — {BOOK_TITLE}")
    assert "| Walk | Route | Status |" in md
    assert "2a | deterministic | PASS" in md
    assert "2b | deterministic | PASS" in md
    assert "2d | deterministic | PASS" in md
    assert "2c | deterministic | UNSUPPORTED" in md
    assert "2f | deterministic | UNSUPPORTED" in md
    assert "2c | provider | PASS" in md
    assert "Fixture sha512:" in md
    # every row serializes to exactly one table line
    row_lines = [
        line
        for line in md.splitlines()
        if line.startswith("| ")
        and not line.startswith("| Walk |")
        and not line.startswith("|------")
    ]
    assert len(row_lines) == len(matrix.rows)


def test_deterministic_only_modes_skip_provider_routes() -> None:
    matrix = SemanticParityOracle().compare(book_fixture(), modes=(ROUTE_DETERMINISTIC,))
    assert all(r.route == ROUTE_DETERMINISTIC for r in matrix.rows)
    assert len(matrix.rows) == len(WALKS)


def test_extract_walk_claims_covers_all_six_walks() -> None:
    # Direct unit check that every walk id maps to a typed extractor without error.
    from semantic_parity_oracle import _run_format

    rc = _run_format("txt", book_fixture(), run_provider=True)
    for walk in WALKS:
        for route in MODES:
            claims = getattr(rc, route).get(walk, [])
            assert isinstance(claims, list)
    # spot-check the typed extractor: deterministic scene segmentation fires on txt
    # while deterministic alias resolution honestly stays ABSENT.
    claims = rc.deterministic[WALK_2A]
    assert claims, "expected deterministic scene segmentation on txt"
    assert all(isinstance(c, TypedClaim) for c in claims)
    assert rc.deterministic[WALK_2C] == []
