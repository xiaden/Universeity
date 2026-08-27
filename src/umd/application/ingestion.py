"""Versioned ingestion command path (P3-S4).

Implements the application-layer command that POST ``/v1/sources`` boils down to:

  1. stream immutable input to OCFL via ``SourceStore.put_immutable``;
  2. create source/work membership via the PostgreSQL source repository;
  3. emit ``SourceIngested`` event(s) via the append-only semantic ledger
     (``read_your_writes_token = seq``);
  4. return stable ``source_id`` / ``work_id``, a job placeholder, and the
     consistency token.

This handler writes NO projection directly — it only appends to the ledger (whose
Tier-0 delta is produced by the shared reducer in the same transaction) and owns
source/work membership rows. Tier-1 search/vector/graph projections are replayed
later (Phase D), never written here.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, BinaryIO

from umd.storage.ocfl import SourceDescriptor, SourceStore
from umd.storage.postgres.ledger import CommitResult
from umd.storage.postgres.repositories import SourceMembershipService

#: Version of this command path (the REST route taxonomy is an adapter over it).
COMMAND_PATH_VERSION = "v1"


@dataclass
class IngestionRequest:
    """Descriptor for an ``POST /v1/sources``-style ingestion command."""

    media_kind: str
    original_name: str
    work_id: str | None = None
    work_title: str | None = None
    work_type: str = "media"
    format: str | None = None
    language: str | None = None
    idempotency_key: str | None = None
    created_by: str | None = None
    descriptor_extra: dict[str, Any] = field(default_factory=dict)


@dataclass
class IngestionResult:
    """Result of an ingestion command."""

    source_id: str
    work_id: str
    job_id: str
    read_your_writes_token: int
    sha512: str
    ocfl_ref: str
    size_bytes: int
    command_path_version: str = COMMAND_PATH_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "source_id": self.source_id,
            "work_id": self.work_id,
            "job_id": self.job_id,
            "read_your_writes_token": self.read_your_writes_token,
            "sha512": self.sha512,
            "ocfl_ref": self.ocfl_ref,
            "size_bytes": self.size_bytes,
            "command_path_version": self.command_path_version,
        }


class IngestionCommandHandler:
    """Application-layer command handler for source ingestion."""

    def __init__(
        self,
        source_store: SourceStore,
        memberships: SourceMembershipService,
        command_service: Any,  # SemanticCommandService (avoid import cycle at class level)
        job_id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._store = source_store
        self._memberships = memberships
        self._commands = command_service
        self._job_id = job_id_factory or (lambda: str(uuid.uuid4()))

    def ingest(self, stream: BinaryIO, request: IngestionRequest) -> IngestionResult:
        """Run the ingestion command: OCFL -> source/work -> SourceIngested event."""
        # 1) Immutable OCFL bytes (content-addressed; filename is metadata only).
        descriptor = SourceDescriptor(
            logical_name=request.original_name,
            media_kind=request.media_kind,
            format=request.format or "unknown",
            kind="source",
        )
        manifest = self._store.put_immutable(stream, descriptor)

        # 2) Source/work membership. Content-addressed: identical bytes reuse the
        #    existing immutable source (source.sha512 is unique) rather than
        #    inserting a duplicate; a fresh upload creates work/source/membership.
        source_id: str
        work_id: str
        existing = self._memberships.find_source_by_sha512(manifest.sha512)
        if existing is not None:
            source_id, existing_work = existing
            work_id = request.work_id or (existing_work or str(uuid.uuid4()))
        else:
            source_id = str(uuid.uuid4())
            work_id = request.work_id or str(uuid.uuid4())
            if request.work_id is None:
                self._memberships.ensure_work(
                    work_id=work_id,
                    title=request.work_title or request.original_name,
                    work_type=request.work_type,
                )
            self._memberships.ensure_source(
                source_id=source_id,
                ocfl_ref=manifest.object_id,
                sha512=manifest.sha512,
                size_bytes=manifest.size_bytes,
                media_kind=request.media_kind,
                original_name=request.original_name,
                work_id=work_id,
            )
            self._memberships.add_membership(source_id=source_id, work_id=work_id, role="primary")

        # 3) Emit SourceIngested via the semantic ledger (the only semantic
        #    write authority). No projection is written here.
        commit: CommitResult = self._commands.record_source_ingested(
            source_id=source_id,
            sha512=manifest.sha512,
            ocfl_ref=manifest.object_id,
            size_bytes=manifest.size_bytes,
            media_kind=request.media_kind,
            work_id=work_id,
            original_name=request.original_name,
            idempotency_key=request.idempotency_key,
            created_by=request.created_by,
        )

        # 4) Job placeholder (the durable DAG/job wiring arrives in Phase B).
        job_id = self._job_id()

        return IngestionResult(
            source_id=source_id,
            work_id=work_id,
            job_id=job_id,
            read_your_writes_token=commit.read_your_writes_token,
            sha512=manifest.sha512,
            ocfl_ref=manifest.object_id,
            size_bytes=manifest.size_bytes,
        )
