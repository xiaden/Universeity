"""P1-S5 spec-first tests: tolerance-based linkage, fixed seed, chunked predict-only
runs, OCFL-persisted m/u model artifact, honest splink/DuckDB gate + benchmark
fallback, and the sandboxed dispatch entrypoint (array argv only)."""

from __future__ import annotations

import json
import sys

import pytest
import sqlalchemy as sa

from umd.resolution.linkage import (
    DUCKDB_REGRESSION_FACTOR,
    LinkageChunker,
    LinkageDecision,
    LinkageModelSettings,
    LinkageProvider,
    LinkageProviderUnavailable,
    LinkRecord,
    OcflLinkageStore,
    SplinkLinkageProvider,
    benchmark_linkage,
    predict_reference,
    resolve_provider,
    run_linkage,
    train_reference_model,
)
from umd.security.policies import policy_for
from umd.security.sandbox import SubprocessSandboxRunner, stage_spool
from umd.storage.postgres.artifacts import PostgresArtifactStore
from umd.storage.postgres.tables import metadata as db_meta


def _records() -> list[LinkRecord]:
    return [
        LinkRecord(ref="r1", features={"soundex": "A4", "translit": "alex", "cluster": "c1"}),
        LinkRecord(ref="r2", features={"soundex": "A4", "translit": "alex", "cluster": "c1"}),
        LinkRecord(ref="r3", features={"soundex": "Z9", "translit": "zed", "cluster": "c9"}),
    ]


def _trained(records: list[LinkRecord]):
    settings = LinkageModelSettings(fields=("soundex", "translit", "cluster"), match_threshold=3.0)
    return train_reference_model(
        records,
        [("r1", "r2", True), ("r1", "r3", False)],
        settings,
    )


def test_reference_linkage_train_predict_tolerance():
    records = _records()
    model = _trained(records)
    assert model.seed == LinkageModelSettings().seed  # fixed seed
    assert model.train_pairs == 2

    scores = predict_reference(model, records, [("r1", "r2"), ("r1", "r3")])
    by_pair = {(s.left_ref, s.right_ref): s for s in scores}
    assert by_pair[("r1", "r2")].decision == LinkageDecision.MATCH
    assert by_pair[("r1", "r3")].decision == LinkageDecision.NON_MATCH


def test_linkage_threshold_shifts_decision():
    records = _records()
    model = _trained(records)
    base = predict_reference(model, records, [("r1", "r2")])[0]
    model.match_threshold = base.score + 0.1  # now above the observed score
    lowered = predict_reference(model, records, [("r1", "r2")])[0]
    assert base.decision == LinkageDecision.MATCH
    assert lowered.decision == LinkageDecision.POSSIBLE


def test_run_linkage_chunked_bounded():
    records = _records()
    model = _trained(records)
    pairs = [("r1", "r2"), ("r1", "r3")] * 3
    run = run_linkage(LinkageProvider(), records=records, model=model, pairs=pairs, chunk_size=2)
    assert len(run.scores) == len(pairs)
    assert list(LinkageChunker(pairs, chunk_size=2)) == [pairs[0:2], pairs[2:4], pairs[4:6]]


def test_splink_is_honestly_gated():
    assert SplinkLinkageProvider.active() is False
    prov = resolve_provider("splink")
    with pytest.raises(LinkageProviderUnavailable):
        prov.train([], [], LinkageModelSettings())
    with pytest.raises(LinkageProviderUnavailable):
        prov.predict(_trained(_records()), [], [("r1", "r2")])


def test_benchmark_gate_reports_duckdb_gated_fallback():
    records = _records()
    model = _trained(records)
    result = benchmark_linkage(records, model, [("r1", "r2")])
    assert result.reference_seconds >= 0
    assert result.duckdb_gated is True
    assert result.regression_3x is False
    assert "GATED" in result.note
    assert DUCKDB_REGRESSION_FACTOR == 3.0
    assert result.as_dict()["duckdb_gated"] is True


def test_linkage_model_ocfl_persist_roundtrip(umd_db, source_store):
    model = _trained(_records())
    store = OcflLinkageStore(source_store, PostgresArtifactStore(umd_db))
    ocfl_ref = store.save(model)
    # content-addressed, immutable reference persisted to the artifact table
    assert ocfl_ref
    art_t = db_meta.tables["artifact"]
    with umd_db.connect() as conn:
        row = conn.execute(sa.select(art_t.c.kind).where(art_t.c.ocfl_ref == ocfl_ref)).first()
    assert row is not None and row.kind == "linkage_model"

    loaded = store.load(ocfl_ref)
    assert loaded.provider == model.provider
    assert [f.name for f in loaded.fields] == [f.name for f in model.fields]
    assert loaded.prob_m("soundex") == model.prob_m("soundex")


def test_linkage_dispatch_runs_inside_sandbox_array_argv(tmp_path):
    records = _records()
    model = _trained(records)
    payload = {
        "records": [{"ref": r.ref, "features": r.features} for r in records],
        "pairs": [["r1", "r2"], ["r1", "r3"]],
        "model": model.model_dump(),
        "chunk_size": 2,
    }
    input_path = stage_spool(json.dumps(payload).encode(), name="linkage.json", root=tmp_path)
    profile = policy_for("linkage")
    runner = SubprocessSandboxRunner(spool_root=tmp_path)
    result = runner.run(
        [sys.executable, "-m", "umd.resolution.dispatch", str(input_path)],
        limits=profile.limits,
        policy=profile.policy,
    )
    assert result.ok, result.stderr
    out = json.loads(result.stdout)
    by_pair = {(s["left_ref"], s["right_ref"]): s["decision"] for s in out["scores"]}
    assert len(by_pair) == 2
    assert by_pair[("r1", "r2")] == "MATCH"
    assert by_pair[("r1", "r3")] == "NON_MATCH"


# ---------------------------------------------------------------------------
# Plan N Phase 1 — multi-entity resolution machinery
# P1-S1: semantic observations -> deterministic SourceMention bridge.
# P1-S2: blocking/linkage multi-signal scoring with deterministic tie-break.
# ---------------------------------------------------------------------------


def test_mentions_from_semantic_bridges_deterministic_records():
    """P1-S1: typed semantic observations become deterministic SourceMention rows."""
    from umd.analysis.semantic import (
        EntityMention,
        GeneratedBy,
        NormalizedAlias,
        RelationshipCandidate,
        SegmentEvidenceRef,
        SemanticAnalysisResult,
        SemanticPath,
    )
    from umd.domain.models import ConfidenceState
    from umd.resolution.mentions import mentions_from_semantic

    gb = GeneratedBy(
        path=SemanticPath.DETERMINISTIC, analyzer="umd-text-structural@2", config_digest="cfg-d"
    )
    seg1 = SegmentEvidenceRef(
        locator="chapter/1/paragraph/2", evidence_ref="ev-1", chapter=1, paragraph=2
    )
    seg2 = SegmentEvidenceRef(
        locator="chapter/1/paragraph/5", evidence_ref="ev-2", chapter=1, paragraph=5
    )
    result = SemanticAnalysisResult(
        source_id="src-1",
        generated_by=gb,
        entity_mentions=[
            EntityMention(
                mention="Alice",
                entity_type="character",
                confidence=0.3,
                state=ConfidenceState.PROBABLE,
                segment=seg1,
                generated_by=gb,
            ),
        ],
        aliases=[
            NormalizedAlias(
                canonical_name="Alice",
                alias="Al",
                entity_ref=None,
                confidence=0.6,
                state=ConfidenceState.AMBIGUOUS,
                segment=seg2,
                generated_by=gb,
            ),
        ],
        relationships=[
            RelationshipCandidate(
                subject_ref="Alice",
                predicate="CO_OCCURS",
                object_ref="Bob",
                confidence=0.2,
                state=ConfidenceState.PROBABLE,
                segment=seg1,
                generated_by=gb,
            ),
        ],
    )

    first = mentions_from_semantic(result)
    second = mentions_from_semantic(result)

    # deterministic ids keyed by source/segment/span identity, stable across reruns
    assert [m.mention_id for m in first] == [m.mention_id for m in second]
    assert [m.mention_id for m in first] == [str(m.id) for m in first]
    assert len(first) == 2

    em = next(m for m in first if m.mention_text == "Alice")
    assert em.source_id == "src-1"
    assert em.mention_kind == "name"
    assert em.normalized_forms == ["alice"]  # via the existing normalize_name machinery
    assert em.confidence == 0.3
    assert em.confidence_state == "PROBABLE"
    assert em.segment_id is None
    assert em.provenance["locator"] == "chapter/1/paragraph/2"
    assert em.provenance["evidence_ref"] == "ev-1"
    assert em.provenance["generated_by"]["analyzer"] == "umd-text-structural@2"
    assert em.metadata_["entity_type"] == "character"
    assert em.metadata_["co_occurring"] == ["Alice", "Bob"]

    al = next(m for m in first if m.mention_text == "Al")
    assert al.mention_kind == "name"
    assert "alice" in al.normalized_forms
    assert al.entity_id is None  # ambiguous alias stays unresolved / reviewable
    assert al.metadata_["canonical_name"] == "Alice"
    assert al.confidence_state == "AMBIGUOUS"


def test_link_scores_context_type_and_model_signals():
    """P1-S2: composite scoring surfaces type/context/model signals deterministically."""
    import uuid

    from umd.resolution.candidates import MentionBlockIndex
    from umd.resolution.mentions import MentionCandidate, SourceMention

    # Two same-name candidates; the character one co-occurs with the probe's context.
    cand_char = SourceMention(
        id=uuid.uuid4(),
        source_id="s",
        entity_id="ent-char",
        mention_text="Alice",
        metadata_={"entity_type": "character", "co_occurring": ["Bob"]},
    )
    cand_org = SourceMention(
        id=uuid.uuid4(),
        source_id="s",
        entity_id="ent-org",
        mention_text="Alice Corp",
        metadata_={"entity_type": "organization"},
    )
    idx = MentionBlockIndex([cand_char, cand_org])
    probe = SourceMention(
        id=uuid.uuid4(),
        source_id="s",
        mention_text="Alice",
        metadata_={"entity_type": "character", "co_occurring": ["Bob"]},
    )
    hits = idx.link(probe)
    assert hits.candidates[0].entity_ref == "ent-char"  # type + context outrank name-only
    sig = hits.signals["ent-char"]
    assert sig["name"] == 1.0
    assert sig["context"] == 1.0
    assert sig["type"] == 1.0

    # A model-named candidate flips an otherwise-tied ranking (deterministic).
    cand_a = SourceMention(
        id=uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
        source_id="s",
        entity_id="ent-a",
        mention_text="Alice",
    )
    cand_b = SourceMention(
        id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
        source_id="s",
        entity_id="ent-b",
        mention_text="Alice",
    )
    idx2 = MentionBlockIndex([cand_a, cand_b])
    probe2 = SourceMention(
        id=uuid.uuid4(),
        source_id="s",
        mention_text="Alice",
        candidates=[MentionCandidate(entity_ref="ent-a", confidence=0.9)],
    )
    hits2 = idx2.link(probe2)
    # without the model signal the tie would break to cand_b (lower mention id)
    assert hits2.candidates[0].entity_ref == "ent-a"
    assert hits2.signals["ent-a"]["model"] == 1.0
    assert hits2.signals["ent-b"]["model"] == 0.0


# ---------------------------------------------------------------------------
# Plan N Phase 3 (P3-S2) — candidate evidence, bounded counts, type signal.
# ---------------------------------------------------------------------------


def test_link_returns_bounded_candidates_with_signal_breakdown():
    """Candidate counts are bounded and every surfaced candidate keeps a full
    per-signal evidence breakdown (name/alias/context/type/canonical/model) so
    an ambiguous/conflicting candidate stays reviewable, never guessed."""
    import uuid

    from umd.resolution.candidates import CandidatePolicy, MentionBlockIndex
    from umd.resolution.mentions import SourceMention

    mentions = [
        SourceMention(
            id=uuid.uuid4(),
            source_id="s",
            mention_text="Alice",
            metadata_={"entity_type": "character"},
        )
        for _ in range(30)
    ]
    probe = SourceMention(
        id=uuid.uuid4(),
        source_id="s",
        mention_text="Alice",
        metadata_={"entity_type": "character"},
    )
    idx = MentionBlockIndex(mentions, CandidatePolicy(max_candidates_per_mention=5))
    hits = idx.link(probe)

    assert 0 < len(hits.candidates) <= 5  # bounded, non-empty
    assert len(hits.candidates) == 5
    for cand in hits.candidates:
        sig = hits.signals[cand.entity_ref]
        assert {"name", "alias", "context", "type", "canonical", "model"} <= set(sig)
        assert sig["name"] == 1.0  # identical normalized surface
        assert sig["type"] == 1.0


def test_type_signal_distinguishes_same_surface_different_kind():
    """Type mismatch DOWN-weights: a character probe prefers the character
    candidate over a same-surface organization when only the type differs."""
    import uuid

    from umd.resolution.candidates import MentionBlockIndex
    from umd.resolution.mentions import SourceMention

    char = SourceMention(
        id=uuid.UUID("ffffffff-ffff-ffff-ffff-ffffffffffff"),
        source_id="s",
        entity_id="ent-char",
        mention_text="Alex",
        metadata_={"entity_type": "character"},
    )
    org = SourceMention(
        id=uuid.UUID("00000000-0000-0000-0000-000000000000"),
        source_id="s",
        entity_id="ent-org",
        mention_text="Alex",
        metadata_={"entity_type": "organization"},
    )
    idx = MentionBlockIndex([char, org])
    probe = SourceMention(
        id=uuid.uuid4(),
        source_id="s",
        mention_text="Alex",
        metadata_={"entity_type": "character"},
    )
    hits = idx.link(probe)
    assert hits.candidates[0].entity_ref == "ent-char"
    assert hits.signals["ent-char"]["type"] == 1.0
    assert hits.signals["ent-org"]["type"] == 0.0
    assert hits.signals["ent-char"]["name"] == 1.0
    assert hits.signals["ent-org"]["name"] == 1.0  # same surface; only type differs
