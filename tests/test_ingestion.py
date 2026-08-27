"""P3-S4: versioned ingestion command path (postgres + OCFL).

Proves the ingestion command handler:
  * streams immutable input to OCFL and returns stable ``source_id`` / ``work_id``;
  * creates source/work membership rows;
  * appends a ``SourceIngested`` semantic event and returns ``read_your_writes_token``;
  * never writes any projection directly (Tier-1 tables stay empty; the ledger's
    Tier-0 delta is the only extra write, and SourceIngested is non-rewriting);
  * a duplicate ingestion with the same idempotency key does not duplicate the
    authoritative completion.
"""

from __future__ import annotations

import io
import uuid

import pytest
import sqlalchemy as sa

from umd.application.commands import SemanticCommandService
from umd.application.ingestion import IngestionCommandHandler, IngestionRequest
from umd.storage.ocfl import SourceStore
from umd.storage.postgres.ledger import SemanticLedger
from umd.storage.postgres.repositories import SourceMembershipService
from umd.storage.postgres.tables import metadata as db_meta

pytestmark = pytest.mark.postgres

_se = db_meta.tables["semantic_event"]
_proj = db_meta.tables["projection_checkpoint"]
_emb = db_meta.tables["embedding"]


def _handler(umd_db: sa.Engine, source_store: SourceStore) -> IngestionCommandHandler:
    return IngestionCommandHandler(
        source_store=source_store,
        memberships=SourceMembershipService(umd_db),
        command_service=SemanticCommandService(SemanticLedger(umd_db)),
    )


def test_full_ingestion_path_no_projection_writes(umd_db: sa.Engine, source_store) -> None:
    handler = _handler(umd_db, source_store)
    result = handler.ingest(
        io.BytesIO(b"immutable body"),
        IngestionRequest(media_kind="text", original_name="novel.txt"),
    )
    assert result.source_id and result.work_id
    assert result.job_id  # job placeholder
    assert result.read_your_writes_token > 0
    assert result.sha512 and len(result.sha512) == 128

    with umd_db.connect() as conn:
        n_sources = conn.execute(sa.text("SELECT count(*) FROM source")).scalar()
        n_events = conn.execute(sa.text("SELECT count(*) FROM semantic_event")).scalar()
        ev_type = conn.execute(
            sa.select(_se.c.event_type).order_by(_se.c.seq.desc()).limit(1)
        ).scalar()
        # No projection writes at all (Tier-1 + Tier-0 projections remain empty):
        # the ingestion path must never touch projection tables directly.
        assert conn.execute(sa.select(sa.func.count()).select_from(_proj)).scalar() == 0
        assert conn.execute(sa.select(sa.func.count()).select_from(_emb)).scalar() == 0
        # SourceIngested is a NON-semantic event -> current_state (Tier-0) stays empty.
        tier0 = conn.execute(
            sa.select(sa.func.count()).select_from(db_meta.tables["current_state"])
        ).scalar()

    assert n_sources == 1
    assert n_events == 1
    assert ev_type == "SourceIngested"
    assert tier0 == 0


def test_follow_claim_to_stable_ids(umd_db: sa.Engine, source_store) -> None:
    """A claim (ingest result) carries the stable IDs back to OCFL bytes."""
    handler = _handler(umd_db, source_store)
    r = handler.ingest(
        io.BytesIO(b"the immutable source body"),
        IngestionRequest(media_kind="text", original_name="book.txt"),
    )
    # source row resolves to the OCFL object id, and the event carries sha512.
    with umd_db.connect() as conn:
        ocfl_ref = conn.execute(
            sa.text("SELECT ocfl_ref FROM source WHERE id=:sid"), {"sid": r.source_id}
        ).scalar()
    assert ocfl_ref == r.ocfl_ref
    assert source_store.has_object(r.ocfl_ref)  # immutable bytes present
    assert r.sha512 == source_store.get_range(r.ocfl_ref, 0, 10).sha512


def test_idempotent_ingestion_does_not_duplicate(umd_db: sa.Engine, source_store) -> None:
    handler = _handler(umd_db, source_store)
    key = str(uuid.uuid4())
    r1 = handler.ingest(
        io.BytesIO(b"body"),
        IngestionRequest(media_kind="text", original_name="a.txt", idempotency_key=key),
    )
    r2 = handler.ingest(
        io.BytesIO(b"body"),
        IngestionRequest(media_kind="text", original_name="a.txt", idempotency_key=key),
    )
    # Same idempotency key => same read-your-writes token, single authoritative event.
    assert r1.read_your_writes_token == r2.read_your_writes_token
    with umd_db.connect() as conn:
        n = conn.execute(sa.select(sa.func.count()).select_from(_se)).scalar()
    assert n == 1


def test_content_addressed_reuse_under_distinct_idempotency_keys(
    umd_db: sa.Engine, source_store
) -> None:
    """Same source bytes reuse the same immutable source/OCFL object even when
    submitted under DISTINCT idempotency keys (no source duplication), while the
    distinct keys still produce distinct authoritative SourceIngested events."""
    handler = _handler(umd_db, source_store)
    r1 = handler.ingest(
        io.BytesIO(b"same immutable bytes"),
        IngestionRequest(
            media_kind="text",
            original_name="a.txt",
            idempotency_key=str(uuid.uuid4()),
        ),
    )
    r2 = handler.ingest(
        io.BytesIO(b"same immutable bytes"),
        IngestionRequest(
            media_kind="text",
            original_name="b.txt",
            idempotency_key=str(uuid.uuid4()),
        ),
    )
    # Identical bytes -> the SAME content-addressed immutable source and OCFL object.
    # (The fresh-creation path returns a dashed uuid while the reuse path reads the
    # stored id as hex; normalize before comparing — both are the same UUID.)
    assert uuid.UUID(r1.source_id) == uuid.UUID(r2.source_id)
    assert r1.ocfl_ref == r2.ocfl_ref
    assert r1.sha512 == r2.sha512
    # Distinct idempotency keys -> distinct authoritative completions (two events).
    assert r1.read_your_writes_token != r2.read_your_writes_token
    with umd_db.connect() as conn:
        n_events = conn.execute(sa.select(sa.func.count()).select_from(_se)).scalar()
        n_sources = conn.execute(sa.text("SELECT count(*) FROM source")).scalar()
    assert n_events == 2  # one SourceIngested per distinct key
    assert n_sources == 1  # content-addressed reuse: the source was NOT duplicated
