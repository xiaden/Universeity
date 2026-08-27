"""PostgreSQL artifact repository: OCFL derived-artifact references (P3-S1).

The ``artifact`` table records content-addressed OCFL references for *derived*
bytes (crops, OCR-normalized tiles, etc.). The bytes themselves live only in OCFL
(the graph never holds the only copy); the row binds an ``ocfl_ref``
(``urn:umd:ocfl:derived:sha512:...``) to a source, size, digest, kind and
metadata. Insertions are idempotent on the unique ``ocfl_ref``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa

from umd.storage.postgres.tables import metadata as db_meta

_artifact_t = db_meta.tables["artifact"]

pg_insert = sa.dialects.postgresql.insert


@dataclass
class ArtifactRef:
    """A recorded OCFL derived-artifact reference."""

    ocfl_ref: str
    sha512: str
    size_bytes: int
    kind: str
    is_new: bool = False


@dataclass
class ArtifactRecordResult:
    """Result of recording one or more artifacts."""

    created: list[ArtifactRef] = field(default_factory=list)
    existing: list[ArtifactRef] = field(default_factory=list)


def _uuid_hex() -> str:
    import uuid

    return uuid.uuid4().hex


class PostgresArtifactStore:
    """Record content-addressed OCFL derived-artifact references in ``artifact``."""

    def __init__(self, engine: sa.Engine) -> None:
        self._engine = engine

    def record(
        self,
        ocfl_ref: str,
        sha512: str,
        size_bytes: int,
        kind: str = "derived",
        source_id: str | None = None,
        meta: dict[str, Any] | None = None,
    ) -> ArtifactRef:
        """Insert an artifact row (idempotent on the unique ``ocfl_ref``).

        Returns whether the row was newly created vs. already present.
        """
        with self._engine.begin() as conn:
            stmt = (
                pg_insert(_artifact_t)
                .values(
                    id=_uuid_hex(),
                    ocfl_ref=ocfl_ref,
                    sha512=sha512,
                    size_bytes=size_bytes,
                    kind=kind,
                    source_id=source_id,
                    metadata_=meta or {},
                )
                .on_conflict_do_nothing(index_elements=["ocfl_ref"])
                .returning(_artifact_t.c.ocfl_ref)
            )
            inserted = conn.execute(stmt).fetchone()
        return ArtifactRef(
            ocfl_ref=ocfl_ref,
            sha512=sha512,
            size_bytes=size_bytes,
            kind=kind,
            is_new=inserted is not None,
        )

    def get(self, ocfl_ref: str) -> ArtifactRef | None:
        with self._engine.connect() as conn:
            row = conn.execute(
                sa.select(_artifact_t).where(_artifact_t.c.ocfl_ref == ocfl_ref)
            ).fetchone()
        if row is None:
            return None
        return ArtifactRef(
            ocfl_ref=row.ocfl_ref,
            sha512=row.sha512,
            size_bytes=row.size_bytes,
            kind=row.kind,
        )
