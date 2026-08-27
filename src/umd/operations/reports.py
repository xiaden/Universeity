"""Per-source decomposition reports (P1-S2).

The DD Security-and-observability contract and the DD operational sections require
a per-source decomposition report that explains a source's decomposition outcome:

* stage state (per ``stage_run`` status)
* timing / duration (from ``job_run_audit`` start/fail/complete + ``stage_run``
  timestamps)
* retry history (``job_run_audit`` ``retry`` actions per stage, attempt counts)
* versions / configuration digests (``stage_run.config_digest`` + evidence
  ``tool_versions``)
* incomplete branches (stages that are ``cancelled``/missing, jobs not terminal)
* quarantine records (``quarantine`` rows located under this source)
* rerun / invalidation causation (audit ``details`` + job ``cancelled_stages``)

Sources for report data are consistently the operational tables the DD names:
``job``, ``stage_run``, ``job_run_audit``, ``evidence``, ``quarantine`` — never
Tier-0. The builder is read-only; it never writes.
"""

from __future__ import annotations

import uuid
from dataclasses import asdict, dataclass, field
from typing import Any

import sqlalchemy as sa

from umd.observability.records import (
    observe_stage_duration,
    record_stage_failure,
    record_stage_retry,
)
from umd.storage.postgres.tables import metadata as db_meta

_job_t = db_meta.tables["job"]
_stage_run_t = db_meta.tables["stage_run"]
_audit_t = db_meta.tables["job_run_audit"]
_evidence_t = db_meta.tables["evidence"]
_segment_t = db_meta.tables["segment"]
_quarantine_t = db_meta.tables["quarantine"]
_source_t = db_meta.tables["source"]


@dataclass
class StageReport:
    """One stage's decomposition outcome within a job."""

    stage_name: str
    status: str
    attempts: int = 0
    starts: int = 0
    retries: int = 0
    completes: int = 0
    failures: int = 0
    config_digest: str | None = None
    artifact_count: int = 0
    created_at: str | None = None
    updated_at: str | None = None
    audit_details: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class JobReport:
    """One job run against the source."""

    job_id: str
    status: str
    dag_universe: str
    error: str | None = None
    cancelled_stages: list[str] = field(default_factory=list)
    created_at: str | None = None
    updated_at: str | None = None
    stages: list[StageReport] = field(default_factory=list)

    @property
    def incomplete_branches(self) -> list[str]:
        """Stages that did not reach a terminal-complete state for this job."""
        missing: list[str] = []
        if self.status != "COMPLETE":
            missing.append(f"job:{self.status}")
        for s in self.stages:
            if s.status not in ("complete", "COMPLETED", "COMPLETE"):
                missing.append(f"{s.stage_name}:{s.status}")
        for c in self.cancelled_stages:
            if c not in {s.stage_name for s in self.stages}:
                missing.append(f"{c}:cancelled")
        return missing


@dataclass
class SourceReport:
    """Full per-source decomposition report (P1-S2)."""

    source_id: str
    source_meta: dict[str, Any] = field(default_factory=dict)
    jobs: list[JobReport] = field(default_factory=list)
    quarantine: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class SourceReportBuilder:
    """Read-only builder producing a per-source :class:`SourceReport`."""

    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    def build(self, source_id: str) -> SourceReport:
        source_id_uuid = uuid.UUID(source_id)
        report = SourceReport(source_id=source_id)
        with self._engine.connect() as conn:
            src = (
                conn.execute(sa.select(_source_t).where(_source_t.c.id == source_id_uuid))
                .mappings()
                .first()
            )
            if src is not None:
                report.source_meta = {
                    "media_kind": src["media_kind"],
                    "format": src["format"],
                    "language": src["language"],
                    "sha512": src["sha512"],
                    "size_bytes": src["size_bytes"],
                    "original_name": src["original_name"],
                    "ocfl_ref": src["ocfl_ref"],
                }

            jobs = (
                conn.execute(
                    sa.select(_job_t)
                    .where(_job_t.c.source_id == source_id_uuid)
                    .order_by(_job_t.c.created_at)
                )
                .mappings()
                .fetchall()
            )

            stage_rows = (
                conn.execute(
                    sa.select(_stage_run_t)
                    .where(_stage_run_t.c.source_id == source_id_uuid)
                    .order_by(_stage_run_t.c.created_at)
                )
                .mappings()
                .fetchall()
            )

            audits = (
                conn.execute(
                    sa.select(_audit_t)
                    .where(_audit_t.c.job_id.in_([j["id"] for j in jobs] or ["__none__"]))
                    .order_by(_audit_t.c.created_at)
                )
                .mappings()
                .fetchall()
            )

            source_locators = self._source_locators(conn, source_id_uuid)
            quarantines = (
                conn.execute(sa.select(_quarantine_t).order_by(_quarantine_t.c.created_at))
                .mappings()
                .fetchall()
            )

        by_job: dict[str, list[Any]] = {}
        for sr in stage_rows:
            by_job.setdefault(str(sr["job_id"]), []).append(sr)
        audit_by_job: dict[str, list[Any]] = {}
        for a in audits:
            audit_by_job.setdefault(str(a["job_id"]), []).append(a)

        for j in jobs:
            jid = str(j["id"])
            job_report = JobReport(
                job_id=jid,
                status=str(j["status"]),
                dag_universe=str(j["dag_universe"]),
                error=j["error"],
                cancelled_stages=list(j["cancelled_stages"] or []),
                created_at=j["created_at"].isoformat() if j["created_at"] else None,
                updated_at=j["updated_at"].isoformat() if j["updated_at"] else None,
            )
            stage_map = {str(sr["stage_name"]): sr for sr in by_job.get(jid, [])}
            stage_names: list[str] = []
            for a in audit_by_job.get(jid, []):
                if a["stage_name"] not in stage_names:
                    stage_names.append(a["stage_name"])
            for name in list(stage_map.keys()):
                if name not in stage_names:
                    stage_names.append(name)
            for name in stage_names:
                st_row = stage_map.get(name)
                attempts = [a for a in audit_by_job.get(jid, []) if a["stage_name"] == name]
                job_report.stages.append(self._stage_report(name, st_row, attempts))
            report.jobs.append(job_report)

        for q in quarantines:
            loc = q["locator"]
            if loc in source_locators or loc.startswith(f"source://{source_id_uuid}"):
                report.quarantine.append(
                    {
                        "locator": loc,
                        "reason": q["reason"],
                        "stage": q["stage"],
                        "refs": q["refs"],
                        "created_at": q["created_at"].isoformat() if q["created_at"] else None,
                    }
                )
                report.warnings.append(f"quarantined segment {loc} ({q['reason']})")
        return report

    def _stage_report(self, name: str, sr: Any | None, audits: list[Any]) -> StageReport:
        retries = sum(1 for a in audits if a["action"] == "retry")
        starts = sum(1 for a in audits if a["action"] == "start")
        completes = sum(1 for a in audits if a["action"] == "complete")
        failures = sum(1 for a in audits if a["action"] == "fail")
        # Timing is best-effort from audit start/failure/complete timestamps.
        starts_wall = [a["started_at"] or a["created_at"] for a in audits if a["action"] == "start"]
        finishes_wall = [
            a["finished_at"] or a["created_at"]
            for a in audits
            if a["action"] in ("complete", "fail")
        ]
        report = StageReport(
            stage_name=name,
            status=str(sr["status"]) if sr is not None else "missing",
            attempts=len(audits) or (1 if sr is not None else 0),
            starts=starts,
            retries=retries,
            completes=completes,
            failures=failures,
            config_digest=sr["config_digest"] if sr is not None else None,
            artifact_count=len(sr["artifact_refs"] or []) if sr is not None else 0,
            created_at=sr["created_at"].isoformat()
            if sr is not None and sr["created_at"]
            else None,
            updated_at=sr["updated_at"].isoformat()
            if sr is not None and sr["updated_at"]
            else None,
            audit_details=[dict(a) for a in audits],
        )
        # Observability (P1-S1): expose retries/failures/stage duration as they occur.
        if retries:
            record_stage_retry(name, report.attempts)
        if failures:
            record_stage_failure(name, "operational")
        if starts and starts_wall and finishes_wall:
            seconds = (finishes_wall[-1] - starts_wall[0]).total_seconds()
            observe_stage_duration(name, seconds)
        return report

    def _source_locators(self, conn: sa.Connection, source_id_uuid: uuid.UUID) -> set[str]:
        locs: set[str] = set()
        rows = conn.execute(
            sa.select(_evidence_t.c.locator).where(_evidence_t.c.source_id == source_id_uuid)
        ).fetchall()
        for r in rows:
            if r.locator:
                locs.add(str(r.locator))
        segs = conn.execute(
            sa.select(_segment_t.c.locator).where(_segment_t.c.source_id == source_id_uuid)
        ).fetchall()
        for r in segs:
            if r.locator:
                locs.add(str(r.locator))
        return locs


__all__ = [
    "SourceReportBuilder",
    "SourceReport",
    "JobReport",
    "StageReport",
]
