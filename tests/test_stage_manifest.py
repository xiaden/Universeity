"""P1-S2: deterministic stage manifests/idempotency keys + DAG-universe namespacing."""

from __future__ import annotations

import uuid

import pytest

from umd.jobs.manifest import (
    StageManifest,
    build_dag_universe,
    deterministic_stage_idempotency_key,
)


def test_dag_universe_encodes_version_and_manifest() -> None:
    u1 = build_dag_universe(dag_version="base")
    u2 = build_dag_universe(dag_version="base", manifest_version=2)
    u3 = build_dag_universe(dag_version="ocr-v3")
    assert u1 == "v1-dag:base" or u1.startswith("v")
    assert u1 != u2
    assert u1 != u3
    assert "ocr-v3" in u3


def test_idempotency_key_is_deterministic_and_a_valid_uuid() -> None:
    m1 = StageManifest(
        job_id="j-1",
        stage_name="ENTITY_RESOLUTION",
        source_id="s-abc",
        evidence_refs=["ev:1"],
    )
    m2 = StageManifest(
        job_id="j-1",
        stage_name="ENTITY_RESOLUTION",
        source_id="s-abc",
        evidence_refs=["ev:1"],
    )
    assert m1.idempotency_key() == m2.idempotency_key()
    # Must be a parseable UUID (matches the SAUuid storage column / ledger key).
    uuid.UUID(m1.idempotency_key())
    # A different stage/evidence/universe must change the key.
    other = StageManifest(
        job_id="j-1",
        stage_name="CROSS_SOURCE_ALIGNMENT",
        source_id="s-abc",
        evidence_refs=["ev:1"],
    )
    assert other.idempotency_key() != m1.idempotency_key()


def test_idempotency_key_changes_with_dag_universe() -> None:
    a = StageManifest(
        job_id="j-1",
        stage_name="BASIC_SEGMENTATION",
        source_id="s-abc",
        dag_universe="v1-dag:base",
    )
    b = StageManifest(
        job_id="j-1",
        stage_name="BASIC_SEGMENTATION",
        source_id="s-abc",
        dag_universe="v1-dag:ocr-v3",
    )
    # Same source+stage but a different DAG universe must NOT alias.
    assert a.idempotency_key() != b.idempotency_key()


def test_standalone_key_function_matches_manifest() -> None:
    key = deterministic_stage_idempotency_key(
        source_id="s-abc",
        segment_id=None,
        stage="FORMAT_ANALYSIS",
        evidence_refs=[],
        stage_schema_version=1,
        tool_versions={},
        config_digest=None,
        dag_universe="v1-dag:base",
    )
    m = StageManifest(
        job_id="irrelevant",
        stage_name="FORMAT_ANALYSIS",
        source_id="s-abc",
        dag_universe="v1-dag:base",
        evidence_refs=[],
    )
    uuid.UUID(key)
    assert key == m.idempotency_key()


def test_manifest_roundtrip_via_dict() -> None:
    m = StageManifest(
        job_id="j-9",
        stage_name="LOW_LEVEL_EXTRACTION",
        source_id="s-xyz",
        segment_id="seg:1",
        evidence_refs=["ev:1", "ev:2"],
        input_manifest={"mode": "ocr"},
        tool_versions={"ocr": "tesseract-5.3"},
        config_digest="cfg-1",
    )
    restored = StageManifest.from_dict(m.to_dict())
    assert restored == m
    assert restored.idempotency_key() == m.idempotency_key()


def test_invalid_stage_is_rejected() -> None:
    with pytest.raises(ValueError):
        StageManifest(job_id="j-1", stage_name="NOT_A_STAGE", source_id="s-abc")
