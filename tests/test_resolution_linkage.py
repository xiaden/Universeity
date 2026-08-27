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
