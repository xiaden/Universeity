"""Stage manifests, DAG-universe namespacing, deterministic idempotency keys (P1-S2).

Purely deterministic manifest construction for one stage run in the canonical
lineage (:mod:`umd.jobs.dag`). These helpers are the *shape* the runner and the
Hatchet adapter carry across a durable boundary: a :class:`StageManifest` is
fully serializable (``to_dict`` / ``from_dict``) so it can cross process/reboots
and still produce the identical idempotency key.

Idempotency-key discipline (from the DD, "Durable stage execution"):

* the key is a collision-resistant, URL-safe digest of the *inputs that change
  the output's meaning*: source/segment identity, stage, evidence refs, stage
  schema version, tool/decoder/extractor versions and the config digest;
* changing any one of those yields a different key and therefore a *new* run, so
  a rebuilt stage is rerun (and its descendants invalidated), never silently
  confused with the old output;
* the DAG *universe* is folded into the key, so when a new universe is activated
  the old in-flight stage runs are both drained and non-derivable — there is no
  cross-universe idempotency aliasing.

No scheduler header: these functions are scheduler-agnostic and used identically
by the in-memory double and the Hatchet adapter.
"""

from __future__ import annotations

import base64
import hashlib
import json
import uuid as _uuid
from typing import Any

from .dag import STAGE_ORDER

#: Current manifest shape version. Bump when the digest material changes meaning
#: (not for cosmetic reflows); it is folded into the DAG universe string.
_MANIFEST_VERSION = 1


def build_dag_universe(*, dag_version: str, manifest_version: int = _MANIFEST_VERSION) -> str:
    """The namespaced "universe" under which stage idempotency keys are computed.

    A universe is ``v{manifest_version}-dag:{dag_version}``. Each authoritative
    DAG release is a distinct universe; activating a new universe drains/cancels
    in-flight work from the old one (see :mod:`umd.jobs.drain`) so a stage run is
    never keyed across two different DAG definitions.
    """
    if not dag_version:
        raise ValueError("dag_version must be non-empty")
    return f"v{manifest_version}-dag:{dag_version}"


def _urlsafe_b64(digest: bytes, length: int | None = None) -> str:
    encoded = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return encoded[:length] if length is not None else encoded


def sha256_digest(material: str) -> str:
    """Deterministic sha256 digest of ``material`` (URL-safe, ~43 chars)."""
    return _urlsafe_b64(hashlib.sha256(material.encode("utf-8")).digest())


def deterministic_uuid(material: str) -> str:
    """Deterministic UUID (v4-masked) str from ``material``.

    Stage/semantic ``idempotency_key`` columns are `SAUuid`, so deterministic
    keys must be valid UUID strings. Sixteen bytes of the sha256 digest mask the
    version/variant bits to look like a v4 UUID; equal inputs always yield the
    same UUID string (collision-resistant and DB-friendly).
    """
    value = int.from_bytes(hashlib.sha256(material.encode("utf-8")).digest()[:16], "big")
    # Mask to version-4 + RFC-4122 variant (10xx) so the UUID looks like a v4 id.
    value = (value & 0xFFFFFFFFFFFF0FFF) | 0x4000
    value = (value & 0x3FFFFFFFFFFFFFFF) | 0x8000000000000000
    return str(_uuid.UUID(int=value))


def _stable_json(value: Any) -> str:
    """Deterministic JSON serialization (sorted keys, compact) for digests."""
    return json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"))


class StageManifest:
    """The full, serializable input for one stage run.

    Mirrors (and extends) :class:`StageRunManifest` with the extra digest
    material — evidence refs, stage schema version, tool versions, DAG universe —
    that determines the deterministic idempotency key.
    """

    __slots__ = (
        "job_id",
        "stage_name",
        "source_id",
        "segment_id",
        "dag_universe",
        "evidence_refs",
        "input_manifest",
        "stage_schema_version",
        "tool_versions",
        "config_digest",
    )

    def __init__(
        self,
        *,
        job_id: str,
        stage_name: str,
        source_id: str | None = None,
        segment_id: str | None = None,
        dag_universe: str | None = None,
        evidence_refs: list[str] | None = None,
        input_manifest: dict[str, Any] | None = None,
        stage_schema_version: int = 1,
        tool_versions: dict[str, str] | None = None,
        config_digest: str | None = None,
    ) -> None:
        if stage_name not in STAGE_ORDER:
            raise ValueError(f"unknown stage {stage_name!r} (must be in {list(STAGE_ORDER)})")
        self.job_id = job_id
        self.stage_name = stage_name
        self.source_id = source_id
        self.segment_id = segment_id
        self.dag_universe = dag_universe or build_dag_universe(dag_version="base")
        self.evidence_refs = evidence_refs or []
        self.input_manifest = input_manifest or {}
        self.stage_schema_version = stage_schema_version
        self.tool_versions = tool_versions or {}
        self.config_digest = config_digest

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, StageManifest):
            return NotImplemented
        return self.to_dict() == other.to_dict()

    # -- serialization -----------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        return {
            "job_id": self.job_id,
            "stage_name": self.stage_name,
            "source_id": self.source_id,
            "segment_id": self.segment_id,
            "dag_universe": self.dag_universe,
            "evidence_refs": sorted(self.evidence_refs),
            "input_manifest": self.input_manifest,
            "stage_schema_version": self.stage_schema_version,
            "tool_versions": dict(sorted(self.tool_versions.items())),
            "config_digest": self.config_digest,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> StageManifest:
        return cls(
            job_id=data["job_id"],
            stage_name=data["stage_name"],
            source_id=data.get("source_id"),
            segment_id=data.get("segment_id"),
            dag_universe=data.get("dag_universe"),
            evidence_refs=data.get("evidence_refs"),
            input_manifest=data.get("input_manifest"),
            stage_schema_version=data.get("stage_schema_version", 1),
            tool_versions=data.get("tool_versions"),
            config_digest=data.get("config_digest"),
        )

    def idempotency_material(self) -> str:
        """The canonical digest input for this stage (see ``deterministic_*``)."""
        parts = [
            "umd/stage-manifest",
            f"v={self.dag_universe}",
            # NOTE: job_id is deliberately excluded — idempotency is derived from
            # the stage's *evidence inputs* (DD §Jobs), so a rerun under a new job
            # dedups against the original without re-executing stage work.
            f"stage={self.stage_name}",
            f"source={self.source_id or ''}",
            f"segment={self.segment_id or ''}",
            "evidence=" + _stable_json(sorted(self.evidence_refs)),
            "input=" + _stable_json(self.input_manifest),
            f"schema={self.stage_schema_version}",
            "tools=" + _stable_json(dict(sorted(self.tool_versions.items()))),
            f"config={self.config_digest or ''}",
        ]
        return "\x1f".join(parts)

    def idempotency_key(self) -> str:
        """Deterministic stage idempotency key (UUID string).

        The same (universe, source, segment, stage, evidence, schema, tools,
        config) always yields the same UUID, so ``StageRunRepository.claim``
        (UNIQUE idempotency_key on a UUID column) deduplicates re-runs and the
        runner never repeats successful stage work.
        """
        return deterministic_uuid(self.idempotency_material())


def child_manifests(parent: StageManifest, branch: list[str]) -> list[StageManifest]:
    """Propagate a parent manifest to its direct dependents (``branch``).

    Builds the dependent manifests for the given ordered list of dependent stages
    (the DAG's direct ``STAGE_DEPENDENTS[parent.stage_name]``). Each dependent
    inherits the parent's source/segment identity, DAG universe and tool/config
    digest, and records the parent stage's artifact refs as its *evidence_refs*
    (the evidence-typed edge flows downstream unchanged in kind).
    """
    return [
        StageManifest(
            job_id=parent.job_id,
            stage_name=dep,
            source_id=parent.source_id,
            segment_id=parent.segment_id,
            dag_universe=parent.dag_universe,
            evidence_refs=list(parent.evidence_refs),
            input_manifest=parent.input_manifest,
            stage_schema_version=parent.stage_schema_version,
            tool_versions=dict(parent.tool_versions),
            config_digest=parent.config_digest,
        )
        for dep in branch
    ]


__all__ = [
    "StageManifest",
    "build_dag_universe",
    "sha256_digest",
    "child_manifests",
    "deterministic_stage_idempotency_key",
]


def deterministic_stage_idempotency_key(
    *,
    source_id: str,
    segment_id: str | None,
    stage: str,
    evidence_refs: list[str],
    stage_schema_version: int,
    tool_versions: dict[str, str],
    config_digest: str,
    dag_universe: str,
) -> str:
    """Standalone deterministic stage idempotency key (function form).

    Equivalent to constructing a :class:`StageManifest` and calling
    :meth:`StageManifest.idempotency_key`; kept for callers that only need a key
    without materializing a manifest. Deterministic across builds given equal
    inputs (the exact digest-matrix both the in-memory runner and the Hatchet
    adapter rely on).
    """
    manifest = StageManifest(
        job_id="",
        stage_name=stage,
        source_id=source_id,
        segment_id=segment_id,
        dag_universe=dag_universe,
        evidence_refs=evidence_refs,
        stage_schema_version=stage_schema_version,
        tool_versions=tool_versions,
        config_digest=config_digest,
    )
    return manifest.idempotency_key()
