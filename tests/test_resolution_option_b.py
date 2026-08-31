"""Plan N Phase 4 (P4-S7): Option B ledger-first integration coverage.

The amendment pins **Option B**: production text resolution keeps
``entity_mention.entity_id`` NULL (nullable UUID FK); canonical refs remain
deterministic STRINGS in immutable ``EntityMentioned``/``EntityResolved``
payloads + reducer-backed ``current_state``; ``current_entity_map`` is written
only when both refs are UUID-compatible (legacy paths).

These tests prove the Option B invariants through the real command/ledger path
over live PostgreSQL:

  * deterministic reruns do not duplicate semantic events/rows and keep the
    same canonical refs;
  * a string canonical ALIAS writes NO ``current_entity_map`` row yet exposes
    the decision through ``current_state`` (ledger-first authority);
  * a split of a string-resolved entity discovers mentions from immutable ledger
    events and quarantines ambiguity without a typed-row UPDATE;
  * a human ``USER_OVERRIDE`` outranks a later machine resolution (shared
    reducer, ref-agnostic);
  * a genuinely ambiguous alias stays unresolved/reviewable until a human
    confirmation, which machine reruns never undo.

The existing UUID-backed resolver tests (``test_resolution_merge_split.py``,
``test_resolution_service.py``) keep proving the conditional map/rebind path.
"""

from __future__ import annotations

import importlib
from typing import Any

import pytest
import sqlalchemy as sa

from job_helpers import SOURCE_ID, ensure_source, make_manifest
from umd.application.commands import SemanticCommandService
from umd.domain.evidence import EvidenceBatch
from umd.domain.models import Evidence, EvidenceKind
from umd.resolution.mentions import MentionService, PostgresMentionRepository
from umd.resolution.resolution import PostgresSplitEnumerator, Resolver
from umd.storage.postgres.ledger import SemanticLedger
from umd.storage.postgres.reducer import USER_OVERRIDE
from umd.storage.postgres.tables import metadata as db_meta

pytestmark = pytest.mark.postgres

_se = db_meta.tables["semantic_event"]
_cs = db_meta.tables["current_state"]
_em = db_meta.tables["entity_mention"]
_map = db_meta.tables["current_entity_map"]
_q = db_meta.tables["quarantine"]


# ---------------------------------------------------------------------------
# production-path helpers
# ---------------------------------------------------------------------------


def _build_composer(umd_db: sa.Engine) -> tuple[Any, str]:
    production = importlib.import_module("umd.jobs.production")
    ensure_source(umd_db)
    ledger = SemanticLedger(umd_db)
    runtime = production.ProductionRuntime(
        engine=umd_db,
        commands=SemanticCommandService(ledger),
        ledger=ledger,
    )
    composer = production._Composer(umd_db, runtime)  # noqa: SLF001
    src = composer._require_source(make_manifest("ENTITY_RESOLUTION"))  # noqa: SLF001
    return composer, src["id"]


def _seed_cast(composer: Any, sid: str) -> None:
    """Seed 3 characters + aliases + one ambiguous alias as candidate evidence."""
    _c = {"entity_type": "character", "confidence": 0.6}
    mentions = [
        ("Alice", "chapter/1/paragraph/2", {**_c, "co_occurring": ["Robert"]}),
        ("Alice", "chapter/2/paragraph/1", {**_c, "co_occurring": ["Robert"]}),
        (
            "Al",
            "chapter/1/paragraph/1",
            {**_c, "co_occurring": ["Robert"], "normalized_forms": ["alice"]},
        ),
        ("Robert", "chapter/1/paragraph/3", {**_c, "co_occurring": ["Alice"]}),
        ("Robert", "chapter/2/paragraph/2", {**_c, "co_occurring": ["Alice"]}),
        (
            "Bob",
            "chapter/1/paragraph/5",
            {**_c, "co_occurring": ["Alice"], "normalized_forms": ["robert"]},
        ),
        ("Carol", "chapter/1/paragraph/4", {**_c, "co_occurring": ["Dan"]}),
        ("Carol", "chapter/2/paragraph/3", {**_c, "co_occurring": ["Dan"]}),
        (
            "Caro",
            "chapter/1/paragraph/6",
            {**_c, "co_occurring": ["Dan"], "normalized_forms": ["carol"]},
        ),
        ("Astra", "chapter/1/paragraph/7", {**_c, "confidence_state": "AMBIGUOUS"}),
    ]
    records = [
        Evidence(
            source_id=sid,
            evidence_kind=EvidenceKind.TEXT_SPAN,
            locator=locator,
            extraction_stage="STRUCTURAL_ANALYSIS",
            tool_versions={"analyzer": "umd-text-structural@2"},
            config_digest="umd-entity-resolution@1",
            confidence=0.6,
            quality={"candidate_kind": "entity", "mention_text": text, **quality},
        )
        for text, locator, quality in mentions
    ]
    composer._evidence.record(EvidenceBatch(records=records))  # noqa: SLF001


def _count(umd_db: sa.Engine, event_type: str) -> int:
    with umd_db.connect() as conn:
        return int(
            conn.execute(
                sa.select(sa.func.count()).select_from(_se).where(_se.c.event_type == event_type)
            ).scalar()
        )


def _canonical_refs_of(outcome: Any) -> list[str]:
    return sorted(r for r in outcome.artifact_refs if r.startswith("entity:canonical:"))


def test_production_resolution_rerun_is_idempotent(umd_db: sa.Engine) -> None:
    """P4-S7: a deterministic rerun adds no duplicate events/rows and keeps refs."""
    composer, sid = _build_composer(umd_db)
    _seed_cast(composer, sid)

    first = composer._entity_resolution(make_manifest("ENTITY_RESOLUTION"))  # noqa: SLF001
    refs_first = _canonical_refs_of(first)
    assert len(refs_first) == 3

    em_before = _count(umd_db, "EntityMentioned")
    er_before = _count(umd_db, "EntityResolved")
    with umd_db.connect() as conn:
        rows_before = int(conn.execute(sa.select(sa.func.count()).select_from(_em)).scalar())
        ev_before = int(conn.execute(sa.select(sa.func.count()).select_from(_se)).scalar())

    second = composer._entity_resolution(make_manifest("ENTITY_RESOLUTION"))  # noqa: SLF001
    assert _canonical_refs_of(second) == refs_first, "rerun must converge to the same canonicals"

    assert _count(umd_db, "EntityMentioned") == em_before
    assert _count(umd_db, "EntityResolved") == er_before
    with umd_db.connect() as conn:
        rows_after = int(conn.execute(sa.select(sa.func.count()).select_from(_em)).scalar())
        ev_after = int(conn.execute(sa.select(sa.func.count()).select_from(_se)).scalar())
    assert rows_after == rows_before, "rerun must not duplicate mention rows"
    assert ev_after == ev_before, "rerun must not duplicate semantic events"


def test_alias_string_ref_skips_entity_map_exposes_current_state(umd_db: sa.Engine) -> None:
    """P4-S7/P4-S2: a string-canonical ALIAS writes no map row, exposes current_state."""
    ledger = SemanticLedger(umd_db)
    repo = PostgresMentionRepository(umd_db)
    resolver = Resolver(
        ledger=ledger,
        enumerator=PostgresSplitEnumerator(umd_db, repo),
        mentions=repo,
        engine=umd_db,
    )

    mid = "11111111-0000-0000-0000-000000000001"
    alias_entity = mid
    canonical = "entity:canonical:src:aaaa"  # deterministic STRING canonical
    resolver.alias(alias_entity=alias_entity, canonical=canonical, reason="option-b")

    # No UUID-only current_entity_map row may be written for a string canonical.
    with umd_db.connect() as conn:
        map_count = int(conn.execute(sa.select(sa.func.count()).select_from(_map)).scalar())
        assert map_count == 0, "string canonical must not materialize an entity-map row"
        row = conn.execute(
            sa.select(_cs.c.entity_ref, _cs.c.object_ref, _cs.c.predicate).where(
                _cs.c.entity_ref == mid
            )
        ).first()
    assert row is not None, "ALIAS decision must be exposed via current_state"
    assert row.predicate == "CANONICAL_ENTITY"
    assert row.object_ref == canonical


def test_split_string_resolved_mention_quarantines_without_typed_update(umd_db: sa.Engine) -> None:
    """P4-S7/P4-S4: a split of a string-resolved entity quarantines ambiguity and
    never performs a typed-row UPDATE on the NULL-FK mention."""
    from resolution_helpers import quarantine_fn

    ensure_source(umd_db)
    ledger = SemanticLedger(umd_db)
    repo = PostgresMentionRepository(umd_db)
    mention_svc = MentionService(ledger=ledger, repository=repo)

    # A mention resolved to a string canonical: row keeps entity_id NULL while the
    # EntityMentioned event carries the string canonical ref.
    mid = "22222222-0000-0000-0000-000000000002"
    source_id = SOURCE_ID
    entity = "entity:canonical:src:bbbb"
    t1, t2 = "entity:canonical:src:b1", "entity:canonical:src:b2"
    from umd.resolution.mentions import MentionCandidate, SourceMention

    mention = SourceMention(
        id=mid,
        source_id=source_id,
        entity_id=entity,
        mention_text="Sapphire",
        candidates=[
            MentionCandidate(entity_ref=t1, confidence=0.6),
            MentionCandidate(entity_ref=t2, confidence=0.6),
        ],
    )
    mention_svc.record(mention)
    with umd_db.connect() as conn:
        fk = conn.execute(sa.select(_em.c.entity_id).where(_em.c.id == mid)).scalar()
    assert fk is None, "string-canonical mention row must store NULL FK"

    resolver = Resolver(
        ledger=ledger,
        enumerator=PostgresSplitEnumerator(umd_db, repo),
        mentions=repo,
        engine=umd_db,
        quarantine=quarantine_fn(umd_db),
    )
    outcome = resolver.split(entity=entity, targets=[t1, t2], reason="option-b-split")

    assert outcome.plan.quarantined_refs == [mid], "tied split must quarantine (never guess)"
    with umd_db.connect() as conn:
        # Quarantined ambiguity surfaced (quarantine rows carry the ref in
        # ``locator``/``refs``).
        qrow = conn.execute(sa.select(_q.c.id).where(_q.c.locator == mid)).first()
        assert qrow is not None, "ambiguous reference must be quarantined, not dropped"
        # No typed-row UPDATE happened: FK stays NULL.
        fk_after = conn.execute(sa.select(_em.c.entity_id).where(_em.c.id == mid)).scalar()
        assert fk_after is None, "string split must not write a typed-row entity_id"
        split_ev = int(
            conn.execute(
                sa.select(sa.func.count())
                .select_from(_se)
                .where(_se.c.event_type == "EntityResolved")
            ).scalar()
        )
    assert split_ev >= 1, "SPLIT must be emitted as an EntityResolved event"


def test_user_override_outranks_machine_rerun_string_path(umd_db: sa.Engine) -> None:
    """P4-S7: a human USER_OVERRIDE outranks a later machine ALIAS rerun."""
    from umd.domain.events import SemanticEvent

    ledger = SemanticLedger(umd_db)
    commands = SemanticCommandService(ledger)
    mid = "33333333-0000-0000-0000-000000000003"

    commands.entity_resolve(
        kind="ALIAS",
        entity_id=mid,
        target_entity_id="entity:canonical:src:machine",
        reason="machine rerun 1",
    )
    ledger.append(
        [
            SemanticEvent(
                event_type="OverrideApplied",
                authority=USER_OVERRIDE,
                payload={
                    "subject_ref": mid,
                    "predicate": "CANONICAL_ENTITY",
                    "object_ref": "entity:canonical:src:human",
                },
            )
        ]
    )
    # A later machine rerun proposes a different canonical.
    commands.entity_resolve(
        kind="ALIAS",
        entity_id=mid,
        target_entity_id="entity:canonical:src:machine2",
        reason="machine rerun 2",
    )

    with umd_db.connect() as conn:
        row = conn.execute(
            sa.select(_cs.c.object_ref, _cs.c.authority).where(
                (_cs.c.entity_ref == mid) & (_cs.c.predicate == "CANONICAL_ENTITY")
            )
        ).first()
    assert row is not None
    assert row.object_ref == "entity:canonical:src:human", (
        "the human override must outrank any later machine rerun"
    )
    assert row.authority == USER_OVERRIDE


def test_ambiguous_alias_stays_unresolved_until_user_confirmation(umd_db: sa.Engine) -> None:
    """P4-S7: an ambiguous alias stays reviewable until confirmed; machine reruns
    never collapse or guess it."""
    from umd.projections.query import QueryService, StructuredQuery

    composer, sid = _build_composer(umd_db)
    _seed_cast(composer, sid)
    composer._entity_resolution(make_manifest("ENTITY_RESOLUTION"))  # noqa: SLF001

    # Genuinely ambiguous alias stays unresolved/reviewable.
    page = QueryService(umd_db).structured(
        StructuredQuery(kind="UNRESOLVED_ALIASES", filters={"source_id": sid})
    )
    assert [h.value for h in page.results] == ["Astra"]

    # A human confirms the ambiguous alias -> canonical decision.
    with umd_db.connect() as conn:
        astra = conn.execute(
            sa.select(_em.c.id).where((_em.c.source_id == sid) & (_em.c.mention_text == "Astra"))
        ).scalar()
    assert astra is not None
    ledger = SemanticLedger(umd_db)
    SemanticCommandService(ledger).entity_resolve(
        kind="ALIAS",
        entity_id=str(astra),
        target_entity_id="entity:canonical:src:astra-confirmed",
        reason="human confirmation",
    )
    # A later machine rerun must NOT undo the human confirmation.
    composer._entity_resolution(make_manifest("ENTITY_RESOLUTION"))  # noqa: SLF001

    with umd_db.connect() as conn:
        row = conn.execute(
            sa.select(_cs.c.object_ref, _cs.c.authority).where(
                (_cs.c.entity_ref == str(astra)) & (_cs.c.predicate == "CANONICAL_ENTITY")
            )
        ).first()
    assert row is not None
    assert row.object_ref == "entity:canonical:src:astra-confirmed"
    # Confirmed mention is no longer an unresolved alias.
    page2 = QueryService(umd_db).structured(
        StructuredQuery(kind="UNRESOLVED_ALIASES", filters={"source_id": sid})
    )
    assert [h.value for h in page2.results] == []


def test_query_entities_alias_string_canonical_resolves_deduped(umd_db: sa.Engine) -> None:
    """P4-S5: QueryService.entities(filters={'alias': ...}) resolves a STRING
    canonical via the current_state CANONICAL_ENTITY row + ALIAS event (Option B),
    returning exactly one deduped canonical hit through the public seam."""
    from umd.projections.query import QueryService, StructuredQuery
    from umd.resolution.mentions import SourceMention

    ensure_source(umd_db)
    ledger = SemanticLedger(umd_db)
    repo = PostgresMentionRepository(umd_db)
    mention_svc = MentionService(ledger=ledger, repository=repo)
    resolver = Resolver(
        ledger=ledger,
        enumerator=PostgresSplitEnumerator(umd_db, repo),
        mentions=repo,
        engine=umd_db,
    )

    mid = "44444444-0000-0000-0000-000000000004"
    canonical = "entity:canonical:src:query-string"
    # Option B: a mention resolved to a STRING canonical — the EntityMentioned
    # event carries the string ref (row keeps entity_id NULL).
    mention_svc.record(
        SourceMention(id=mid, source_id=SOURCE_ID, entity_id=canonical, mention_text="Al")
    )
    # Route the alias through Resolver.alias: mention id -> STRING canonical
    # (ledger-first path — no current_entity_map row since the canonical is
    # non-UUID), folding a current_state CANONICAL_ENTITY row for the alias.
    resolver.alias(alias_entity=mid, canonical=canonical, reason="option-b")
    # The canonical must itself be a resolvable canonical entity so the alias
    # query can return it as a result hit (its own CANONICAL_ENTITY row).
    resolver.alias(alias_entity=canonical, canonical=canonical, reason="canonical-self")

    # Public seam: QueryService.entities with an alias filter.
    page = QueryService(umd_db).entities(StructuredQuery(kind="ENTITY", filters={"alias": mid}))
    # The alias resolves to exactly the one canonical — deduped, no duplicates.
    assert [h.value for h in page.results] == [canonical]
    assert page.total == 1
    assert page.results[0].ref == canonical


def test_query_entities_alias_uuid_legacy_map_resolves_deduped(umd_db: sa.Engine) -> None:
    """P4-S5: QueryService.entities(filters={'alias': ...}) resolves a canonical
    via the legacy UUID-backed current_entity_map row, returning exactly one
    deduped canonical hit through the public seam."""
    from resolution_helpers import insert_entity
    from umd.projections.query import QueryService, StructuredQuery

    ensure_source(umd_db)
    ledger = SemanticLedger(umd_db)
    repo = PostgresMentionRepository(umd_db)
    resolver = Resolver(
        ledger=ledger,
        enumerator=PostgresSplitEnumerator(umd_db, repo),
        mentions=repo,
        engine=umd_db,
    )

    mention_eid = insert_entity(umd_db, label="mention")
    canonical_eid = insert_entity(umd_db, label="canonical")
    # Both refs are UUIDs -> Resolver.alias writes a current_entity_map row
    # (legacy path) plus the ALIAS event / current_state fold.
    resolver.alias(alias_entity=mention_eid, canonical=canonical_eid, reason="legacy")

    # The legacy map row is materialized (UUID path).
    with umd_db.connect() as conn:
        map_rows = conn.execute(
            sa.select(_map.c.canonical_entity_id).where(_map.c.alias == mention_eid)
        ).fetchall()
    assert len(map_rows) == 1
    assert str(map_rows[0].canonical_entity_id) == canonical_eid

    # Public seam: QueryService.entities with an alias filter resolves the
    # canonical via the map row — deduped, no duplicates, same shape as string.
    page = QueryService(umd_db).entities(
        StructuredQuery(kind="ENTITY", filters={"alias": mention_eid})
    )
    assert [h.value for h in page.results] == [canonical_eid]
    assert page.total == 1


def test_production_resolution_establishes_durable_identity(umd_db: sa.Engine) -> None:
    """Plan S P1-S1/P1-S6: production resolution establishes a durable, replayable
    canonical identity (ESTABLISH event + CANONICAL_IDENTITY row) for each accepted
    canonical, while keeping ``entity_mention.entity_id`` NULL (Option B)."""
    from umd.storage.postgres.reducer import CANONICAL_IDENTITY_PREDICATE

    composer, sid = _build_composer(umd_db)
    _seed_cast(composer, sid)
    outcome = composer._entity_resolution(make_manifest("ENTITY_RESOLUTION"))  # noqa: SLF001
    refs = _canonical_refs_of(outcome)
    assert len(refs) == 3

    with umd_db.connect() as conn:
        est = conn.execute(
            sa.select(sa.func.count())
            .select_from(_se)
            .where(
                (_se.c.event_type == "EntityResolved")
                & (_se.c.payload["kind"].astext == "ESTABLISH")
            )
        ).scalar()
        identity_rows = conn.execute(
            sa.select(sa.func.count())
            .select_from(_cs)
            .where(_cs.c.predicate == CANONICAL_IDENTITY_PREDICATE)
        ).scalar()
        null_fks = conn.execute(
            sa.select(sa.func.count()).select_from(_em).where(_em.c.entity_id.is_(None))
        ).scalar()
        total_mentions = conn.execute(sa.select(sa.func.count()).select_from(_em)).scalar()

    assert int(est) == 3  # one ESTABLISH per accepted canonical
    assert int(identity_rows) == 3  # identity metadata folds to Tier-0
    assert int(null_fks) == int(total_mentions)  # no fabricated UUID FK

    # Inline vs wipe-and-replay equivalence for the identity metadata.
    from umd.projections.base import ReplayDriver
    from umd.projections.checkpoint import ProjectionCheckpointStore
    from umd.projections.current import CurrentTierOneBuilder, tier0_checksum

    t0 = tier0_checksum(umd_db)
    builder = CurrentTierOneBuilder()
    res = ReplayDriver(umd_db, ProjectionCheckpointStore(umd_db)).run(builder, wipe=True)
    assert res.fresh
    assert builder.checksum(umd_db) == t0
