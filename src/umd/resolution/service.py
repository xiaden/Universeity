"""Deterministic multi-entity resolution service (Plan N Phase 2).

Implements the binding contract ``EntityResolutionService.resolve_mentions(input)
-> ResolutionBatch`` (CONTRACTS.md:76):

    bounded deterministic candidate/linkage decisions and optional model evidence
    over ``SourceMention`` records, producing multiple canonical assignments,
    alias/mention mappings, unresolved/conflicting decisions, and reversible
    ledger commands while honoring locks, overrides, human confirmation,
    quarantine, and idempotency.

The service is a *pure projection* over a collection of :class:`SourceMention`
records. It writes nothing and touches no database: given the same mention
input it always produces the identical :class:`ResolutionBatch` (idempotent
rerun convergence). The reversible ledger commands it carries are *applied* by
the caller through the existing command path (``MentionService.record`` for
``EntityMentioned``, ``Resolver.alias``/``commands.entity_resolve`` for
``ALIAS``/``MERGE``), never invented as a parallel decision path.

Semantics
---------
  * **Distinct clusters** — mentions are grouped into deterministic canonical
    clusters via the bounded multi-signal ``MentionBlockIndex.link`` scoring
    (name/alias/context/type/canonical/model). Each distinct cluster yields ONE
    canonical entity ref.
  * **Reuse existing canonicals** — a mention that already resolves to an
    entity (``entity_id`` set) seeds a cluster; the cluster's canonical ref IS
    that existing ref, so a rerun reuses the same canonical instead of
    fabricating a new one (existing canonical assignments are preserved unless
    an authorized correction/override changes them).
  * **No destructive collapse** — two *different* existing canonicals are never
    merged by a machine rerun; an attempted merge across distinct seeds is
    surfaced as a contradiction, never silently collapsed.
  * **Ambiguous / conflicting stay unresolved** — a mention whose confidence
    state is ``AMBIGUOUS`` or whose candidates name several distinct canonicals
    with no clear winner keeps ``entity_id=None`` and is emitted as
    ``unresolved`` — the resolver never guesses a target.
  * **Deterministic canonical refs** — new canonical refs are derived from the
    sorted member mention ids, so a rerun over the same mentions converges to
    the same refs.

Plan N canonical-reference representation (v1 — Option B, CONTRACTS.md:77):
  the canonical refs produced here are deterministic STRINGS
  (``entity:canonical:<sha256-16hex>`` or a reused seeded ref). Per Plan S
  P1-S2 the source-bound ``entity:canonical:<src>:<digest>`` form was replaced
  by this source-agnostic deterministic format — the ref carries NO source
  prefix, is stable for the accepted identity anchor/scope, and same-name text
  alone never merges. The refs are carried in the immutable
  ``EntityMentioned``/``EntityResolved`` ledger payloads and reducer-backed
  ``current_state``. ``entity_mention.entity_id`` (a nullable
  UUID FK) stays NULL for these non-UUID refs; ``current_entity_map`` is written
  only when both refs are UUID-compatible (legacy UUID-backed paths). No
  entity-table writer, migration, relation entity, or topology/stage change is
  introduced — resolution is represented ledger-first and replayed into the
  read/projection seams, never materialized. Nothing is collapsed or deleted;
  reruns are idempotent.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from umd.domain.ids import canonical_entity_ref
from umd.domain.models import ConfidenceState
from umd.resolution.candidates import CandidatePolicy, MentionBlockIndex, normalize_name
from umd.resolution.mentions import SourceMention

#: A candidate score above which a mention link is treated as a co-reference
#: edge for clustering. Below this the candidate is retained as evidence but
#: never used to fabricate a canonical decision. A pure same-name match scores
#: ~0.55 (name 0.55) plus alias/context/type/canonical/model contributions.
_DEFAULT_RESOLVE_FLOOR = 0.5


# ---------------------------------------------------------------------------
# Resolution output models (deterministic, serializable)
# ---------------------------------------------------------------------------


def _empty_memberships() -> dict[str, list[str]]:
    return {"source_ids": [], "work_ids": [], "continuity_ids": []}


class CanonicalEntity(BaseModel):
    """One resolved canonical entity (a distinct character/entity cluster).

    Plan S (P1-S1): each accepted canonical carries an opaque deterministic
    ref, canonical type, active display label, active aliases, member mention
    refs, exact support/evidence refs, confidence/state, generated-by
    provenance, and work/source/continuity membership context.
    """

    ref: str
    label: str
    source_id: str
    entity_type: str | None = None
    member_mention_ids: list[str] = Field(default_factory=list)
    confidence: float = 0.0
    state: str = ConfidenceState.PROBABLE.value
    support_refs: list[str] = Field(default_factory=list)
    #: Active alias surface forms (the distinct non-label member surfaces).
    aliases: list[str] = Field(default_factory=list)
    #: Generated-by provenance of the accepted decision (analyzer/config/stage).
    generated_by: dict[str, Any] = Field(default_factory=dict)
    #: Work/source/continuity membership context of the canonical identity.
    memberships: dict[str, list[str]] = Field(default_factory=_empty_memberships)


class AliasMapping(BaseModel):
    """An explicit alias -> canonical mapping decided for a cluster."""

    alias_ref: str
    canonical_ref: str
    alias_text: str = ""
    canonical_text: str = ""
    confidence: float = 0.0


class UnresolvedMention(BaseModel):
    """A mention kept reviewable with no guessed target."""

    mention_id: str
    text: str = ""
    reason: str = "ambiguous"  # ambiguous | conflicting
    candidates: list[str] = Field(default_factory=list)


class Contradiction(BaseModel):
    """A surfaced identity contradiction (never silently collapsed)."""

    subject_ref: str
    contradicting_ref: str
    reason: str = ""


class ResolutionCommand(BaseModel):
    """A reversible ledger command the caller applies through the command path.

    ``kind`` is one of ``MENTION`` (record an ``EntityMentioned`` via
    ``MentionService``), ``ALIAS`` (assert the alias mapping via
    ``Resolver.alias``/``entity_resolve``) or ``MERGE`` (merge distinct refs
    into one canonical via ``Resolver.merge``). ``mention`` carries the
    resolved ``SourceMention`` for ``MENTION`` commands.
    """

    kind: str  # MENTION | ALIAS | MERGE | ESTABLISH
    entity_id: str
    target_entity_id: str | None = None
    refs: list[str] = Field(default_factory=list)
    assignments: dict[str, str] = Field(default_factory=dict)
    reason: str = ""
    mention: SourceMention | None = None
    #: Canonical identity metadata for ``ESTABLISH`` commands (type, label,
    #: aliases, support refs, memberships, state, confidence).
    metadata: dict[str, Any] = Field(default_factory=dict)


class ResolutionBatch(BaseModel):
    """The deterministic result of resolving a set of mentions."""

    source_id: str
    canonical_entities: list[CanonicalEntity] = Field(default_factory=list)
    alias_mappings: list[AliasMapping] = Field(default_factory=list)
    assignments: dict[str, str] = Field(default_factory=dict)
    unresolved: list[UnresolvedMention] = Field(default_factory=list)
    contradictions: list[Contradiction] = Field(default_factory=list)
    commands: list[ResolutionCommand] = Field(default_factory=list)
    confidence: float = 0.0
    state: str = ConfidenceState.UNKNOWN.value
    generated_by: dict[str, Any] = Field(default_factory=dict)


class ResolutionInput(BaseModel):
    """The ``input`` to :meth:`EntityResolutionService.resolve_mentions`.

    Plan S (P3-S1): carries the work/continuity scope the source belongs to so
    the resolver can scope identity decisions to an explicit work/continuity
    rather than merging same-name strings across unrelated sources. The memberships
    mirror the ``SourceMembershipService`` context (work/source/continuity ids).
    """

    source_id: str
    mentions: list[SourceMention] = Field(default_factory=list)
    generated_by: dict[str, Any] = Field(default_factory=dict)
    #: Work scope of the source being resolved (explicit supported correspondence).
    work_id: str | None = None
    #: Continuity scope (a declared narrative continuity across works/sources).
    continuity_id: str | None = None
    #: Membership context carried from the source registry (source/work/continuity).
    memberships: dict[str, list[str]] = Field(default_factory=_empty_memberships)


# ---------------------------------------------------------------------------
# Deterministic clustering helpers
# ---------------------------------------------------------------------------


@dataclass
class _ClusterRoot:
    """Union-Find root carrying its seeded canonical (existing entity) if any."""

    members: list[str] = field(default_factory=list)
    seed: str | None = None


class _UnionFind:
    """Minimal deterministic union-find over mention ids.

    Tracks whether a component has been seeded by an *existing* canonical
    (``entity_id``). Two components with DIFFERENT seeds are never unioned — an
    attempted cross-seed merge is recorded as a contradiction and dropped, so a
    machine rerun can never destructively collapse two established entities.
    """

    def __init__(self, ids: Iterable[str]) -> None:
        self._parent = {i: i for i in ids}
        self._rank = {i: 0 for i in ids}
        self._seed: dict[str, str | None] = {i: None for i in ids}
        self.contradictions: list[Contradiction] = []
        self._contradiction_seen: set[tuple[str, str]] = set()

    def find(self, x: str) -> str:
        parent = self._parent[x]
        if parent != x:
            self._parent[x] = self.find(parent)
        return self._parent[x]

    def seed_of(self, x: str) -> str | None:
        return self._seed[self.find(x)]

    def _set_seed(self, root: str, seed: str) -> None:
        self._seed[root] = seed

    def union(self, a: str, b: str, *, candidate_ref: str | None = None) -> bool:
        """Union ``a`` and ``b``; returns True on a real merge.

        A merge across two *different* existing seeds is rejected and surfaced
        as a contradiction (no destructive collapse). ``candidate_ref`` names
        the mention that triggered the attempted cross-seed merge for the
        contradiction record.
        """
        ra, rb = self.find(a), self.find(b)
        if ra == rb:
            return False
        seed_a, seed_b = self._seed[ra], self._seed[rb]
        if seed_a is not None and seed_b is not None and seed_a != seed_b:
            self._record_contradiction(seed_a, seed_b, candidate_ref)
            return False
        if self._rank[ra] < self._rank[rb]:
            ra, rb = rb, ra
        self._parent[rb] = ra
        if self._rank[ra] == self._rank[rb]:
            self._rank[ra] += 1
        # Merge seed state (at most one of the two is non-None here).
        merged_seed = seed_a if seed_a is not None else seed_b
        self._seed[ra] = merged_seed
        return True

    def _record_contradiction(self, seed_a: str, seed_b: str, ref: str | None) -> None:
        key = (seed_a, seed_b) if seed_a <= seed_b else (seed_b, seed_a)
        if key in self._contradiction_seen:
            return
        self._contradiction_seen.add(key)
        self.contradictions.append(
            Contradiction(
                subject_ref=seed_a,
                contradicting_ref=seed_b,
                reason=(
                    f"conflicting canonical assignments surfaced by {ref}"
                    if ref
                    else "conflicting canonical assignments"
                ),
            )
        )


def _source_id_of(mentions: Iterable[SourceMention]) -> str:
    for m in mentions:
        if m.source_id:
            return m.source_id
    return "source:unknown"


def _canonical_label(members: list[SourceMention]) -> str:
    """Pick the canonical surface label deterministically.

    Prefer a real (non-alias) entity mention surface over provider-declared
    alias surfaces so the canonical keeps its primary name (Plan S P5-S1): an
    alias mention carries ``metadata_.canonical_name`` and must never become
    the display label of the cluster it resolves to. Within the preferred
    pool, use the longest distinct surface form, tie-broken by the earliest
    mention id so the choice is stable across reruns.
    """
    pool = [m for m in members if not (m.metadata_ or {}).get("canonical_name")] or list(members)
    by_id = {m.mention_id: m for m in pool}
    ordered = sorted(by_id, key=lambda mid: (len(by_id[mid].mention_text), mid), reverse=True)
    return by_id[ordered[0]].mention_text


def _cluster_confidence(members: list[SourceMention]) -> float:
    confs = [m.confidence for m in members if m.confidence is not None]
    if not confs:
        return 0.0
    return round(sum(confs) / len(confs), 4)


def _entity_type_of(members: list[SourceMention]) -> str | None:
    types = {str(m.metadata_.get("entity_type")) for m in members if m.metadata_.get("entity_type")}
    return sorted(types)[0] if len(types) == 1 else (next(iter(types)) if types else None)


# ---------------------------------------------------------------------------
# The service
# ---------------------------------------------------------------------------


class EntityResolutionService:
    """Bounded, deterministic multi-entity resolution over source mentions.

    Pure: ``resolve_mentions`` never writes to the ledger, database, or any
    projection store. The returned :class:`ResolutionBatch` carries the decided
    canonical entities, alias mappings, unresolved/conflicting decisions, and
    the reversible ledger commands the caller routes through the existing
    ``Resolver``/command path (never a parallel authority).
    """

    def __init__(
        self,
        *,
        resolve_floor: float = _DEFAULT_RESOLVE_FLOOR,
        policy: CandidatePolicy | None = None,
    ) -> None:
        self._resolve_floor = resolve_floor
        self._policy = policy

    def resolve_mentions(
        self,
        input: list[SourceMention] | ResolutionInput,
        *,
        generated_by: dict[str, Any] | None = None,
    ) -> ResolutionBatch:
        """Resolve a set of mentions into a deterministic :class:`ResolutionBatch`.

        ``input`` is either a list of :class:`SourceMention` or a
        :class:`ResolutionInput`. ``generated_by`` supplies the provenance
        metadata carried on every output (the provider/analyzer/config digest
        that produced the decision).
        """
        if isinstance(input, ResolutionInput):
            mentions = list(input.mentions)
            source_id = input.source_id or _source_id_of(mentions)
            gb = dict(input.generated_by) or dict(generated_by or {})
            input_work_id = input.work_id
            input_continuity_id = input.continuity_id
            input_scope = dict(input.memberships)
        else:
            mentions = list(input)
            source_id = _source_id_of(mentions)
            gb = dict(generated_by or {})
            input_work_id = None
            input_continuity_id = None
            input_scope = {}

        gb.setdefault("generator", "EntityResolutionService")
        if not gb.get("config_digest"):
            gb.setdefault("config_digest", "umd-entity-resolution@1")

        policy = self._policy or CandidatePolicy()
        index = MentionBlockIndex(mentions, policy)
        hits = {m.mention_id: index.link(m) for m in mentions}
        mention_by_id = {m.mention_id: m for m in mentions}

        uf = _UnionFind(mention_by_id.keys())

        # Pass 1 — hard seed clusters from existing canonical assignments.
        for m in mentions:
            if m.entity_id:
                root = uf.find(m.mention_id)
                current = uf._seed[root]
                if current is None:
                    uf._set_seed(root, m.entity_id)
                # A single seed per component; conflicting seeds handled by union.

        # Pass 2 — union strong co-reference edges (deterministic order).
        for m in sorted(mentions, key=lambda x: x.mention_id):
            for cand in hits[m.mention_id].candidates:
                if cand.confidence < self._resolve_floor:
                    continue
                target = _candidate_target(cand.entity_ref, mention_by_id)
                if target is None:
                    continue
                uf.union(m.mention_id, target, candidate_ref=m.mention_id)

        # Pass 2b — link provider-declared aliases to their canonical cluster by
        # canonical_name (Plan S P5-S1). An alias observation names its canonical
        # by display surface (no canonical ref exists yet at observation time), so
        # union it with the source-local REAL (non-alias) mention whose surface
        # matches that name. Alias mentions carry the canonical name inside their
        # own normalized_forms (e.g. 'the apprentice' -> ['mara','the apprentice']),
        # so they must NEVER be union targets for other aliases — otherwise two
        # alias mentions pair with each other and fabricate a synthetic alias
        # canonical. Prefer a real mention whose mention_text equals the canonical
        # name (exact real-mention match). Deterministic order; source-local;
        # never crosses scopes.
        for m in sorted(mentions, key=lambda x: x.mention_id):
            cn = (m.metadata_ or {}).get("canonical_name")
            if not cn:
                continue
            cn_norm = normalize_name(cn) or cn.casefold()
            real_targets = [
                t
                for t in mention_by_id.values()
                if t.source_id == m.source_id
                and t.mention_id != m.mention_id
                and not (t.metadata_ or {}).get("canonical_name")
            ]
            ordered = sorted(real_targets, key=lambda x: x.mention_id)
            # Exact real-mention match: the real mention whose surface literally
            # equals the canonical name wins before any normalized-form match.
            union_target = next(
                (t for t in ordered if normalize_name(t.mention_text) == cn_norm),
                None,
            )
            if union_target is None:
                union_target = next(
                    (
                        t
                        for t in ordered
                        if cn_norm in {*t.normalized_forms, normalize_name(t.mention_text)}
                    ),
                    None,
                )
            if union_target is not None:
                uf.union(m.mention_id, union_target.mention_id, candidate_ref=m.mention_id)

        # Pass 3 — group members by root.
        roots: dict[str, list[SourceMention]] = {}
        for m in mentions:
            roots.setdefault(uf.find(m.mention_id), []).append(m)

        canonical_entities: list[CanonicalEntity] = []
        alias_mappings: list[AliasMapping] = []
        assignments: dict[str, str] = {}
        unresolved: list[UnresolvedMention] = []
        commands: list[ResolutionCommand] = []

        for root in sorted(roots, key=lambda r: (uf.seed_of(r) or "", r)):
            members = sorted(roots[root], key=lambda m: m.mention_id)
            seed = uf.seed_of(root)
            if seed is not None:
                canonical_ref = seed
                entity_state = ConfidenceState.CONFIRMED.value
            else:
                canonical_ref = canonical_entity_ref(m.mention_id for m in members)
                entity_state = ConfidenceState.PROBABLE.value

            # Decide whether this component resolves to a canonical or stays
            # reviewable. A singleton with no seed and an ambiguous state, or
            # whose candidates name several distinct existing canonicals, is
            # unresolved (never guessed).
            if len(members) == 1 and seed is None:
                single = members[0]
                if _should_stay_unresolved(single, hits[single.mention_id], mention_by_id):
                    unresolved.append(_to_unresolved(single, hits[single.mention_id]))
                    continue

            label = _canonical_label(members)
            conf = _cluster_confidence(members)
            entity_type = _entity_type_of(members)
            member_ids = [m.mention_id for m in members]
            aliases = sorted({m.mention_text for m in members} - {label})
            memberships = {
                "source_ids": sorted({m.source_id for m in members if m.source_id}),
                "work_ids": sorted({m.work_id for m in members if m.work_id}),
                "continuity_ids": sorted({m.continuity_id for m in members if m.continuity_id}),
            }
            # Carry the explicit source-level work/continuity scope (P3-S1) when a
            # member did not annotate it directly, so the canonical stays scoped.
            if input_work_id and not memberships["work_ids"]:
                memberships["work_ids"] = [input_work_id]
            if input_continuity_id and not memberships["continuity_ids"]:
                memberships["continuity_ids"] = [input_continuity_id]
            if not memberships["source_ids"] and input_scope.get("source_ids"):
                memberships["source_ids"] = list(input_scope["source_ids"])
            canonical_entities.append(
                CanonicalEntity(
                    ref=canonical_ref,
                    label=label,
                    source_id=source_id,
                    entity_type=entity_type,
                    member_mention_ids=member_ids,
                    confidence=conf,
                    state=entity_state,
                    support_refs=sorted(m.mention_id for m in members),
                    aliases=aliases,
                    generated_by=dict(gb),
                    memberships=memberships,
                )
            )
            # Canonical establishment: a first-class append-only ledger event that
            # records the accepted canonical's identity metadata (type, display
            # label, aliases, support refs, memberships, state, confidence).
            commands.append(
                ResolutionCommand(
                    kind="ESTABLISH",
                    entity_id=canonical_ref,
                    target_entity_id=canonical_ref,
                    refs=sorted(m.mention_id for m in members),
                    assignments={m.mention_id: canonical_ref for m in members},
                    reason="canonical establishment",
                    metadata={
                        "canonical_type": entity_type,
                        "display_label": label,
                        "aliases": aliases,
                        "support_refs": sorted(m.mention_id for m in members),
                        "memberships": memberships,
                        "state": entity_state,
                        "confidence": conf,
                        "generated_by": dict(gb),
                    },
                )
            )

            # Alias mappings: every non-canonical member surface that differs
            # from the canonical label is an explicit alias of the cluster.
            for m in members:
                assignments[m.mention_id] = canonical_ref
                commands.append(
                    ResolutionCommand(
                        kind="MENTION",
                        entity_id=canonical_ref,
                        refs=[m.mention_id],
                        reason="entity resolution",
                        mention=m.model_copy(update={"entity_id": canonical_ref}),
                    )
                )
                if m.mention_id != members[0].mention_id and m.mention_text != label:
                    alias_mappings.append(
                        AliasMapping(
                            alias_ref=m.mention_id,
                            canonical_ref=canonical_ref,
                            alias_text=m.mention_text,
                            canonical_text=label,
                            confidence=m.confidence or conf,
                        )
                    )
                    commands.append(
                        ResolutionCommand(
                            kind="ALIAS",
                            entity_id=m.mention_id,
                            target_entity_id=canonical_ref,
                            refs=[m.mention_id],
                            assignments={m.mention_id: canonical_ref},
                            reason="alias resolution",
                        )
                    )

        batch_state = (
            ConfidenceState.AMBIGUOUS.value
            if unresolved
            else (
                ConfidenceState.CONFIRMED.value
                if canonical_entities
                else ConfidenceState.UNKNOWN.value
            )
        )
        batch_conf = (
            round(sum(e.confidence for e in canonical_entities) / len(canonical_entities), 4)
            if canonical_entities
            else 0.0
        )

        return ResolutionBatch(
            source_id=source_id,
            canonical_entities=canonical_entities,
            alias_mappings=alias_mappings,
            assignments=assignments,
            unresolved=unresolved,
            contradictions=uf.contradictions,
            commands=commands,
            confidence=batch_conf,
            state=batch_state,
            generated_by=gb,
        )


def _candidate_target(candidate_ref: str, mention_by_id: dict[str, SourceMention]) -> str | None:
    """Resolve a candidate entity ref to a mention id for unioning.

    A candidate ref may be another mention's id (new clusters) or an existing
    canonical entity id (seeded clusters). For an existing canonical we union
    against every mention that carries that entity id (its seed members).
    """
    if candidate_ref in mention_by_id:
        return candidate_ref
    for mid, m in mention_by_id.items():
        if m.entity_id and m.entity_id == candidate_ref:
            return mid
    return None


def _seeded_refs(candidates: Iterable[Any], mention_by_id: dict[str, SourceMention]) -> set[str]:
    """Distinct existing canonical (seeded) refs a candidate set names."""
    out: set[str] = set()
    for cand in candidates:
        ref = cand.entity_ref
        if ref in mention_by_id:
            continue
        if any(m.entity_id == ref for m in mention_by_id.values()):
            out.add(ref)
    return out


def _should_stay_unresolved(
    m: SourceMention, hits: Any, mention_by_id: dict[str, SourceMention]
) -> bool:
    """Whether a singleton no-seed mention must stay reviewable (never guessed).

    True when the mention is explicitly ambiguous, or its candidate set names
    two or more distinct existing canonicals with no decisive winner, or it is
    a conflict placeholder.
    """
    seeded = _seeded_refs(hits.candidates, mention_by_id)
    # A single strong candidate naming one existing canonical would have been
    # unioned in pass 2, so reaching here with a decisive seeded candidate is a
    # genuine ambiguity (tie) — keep reviewable.
    return m.confidence_state == ConfidenceState.AMBIGUOUS.value or len(seeded) >= 2


def _to_unresolved(m: SourceMention, hits: Any) -> UnresolvedMention:
    seeded = [c.entity_ref for c in hits.candidates]
    reason = "conflicting" if len(set(seeded)) >= 2 else "ambiguous"
    return UnresolvedMention(
        mention_id=m.mention_id,
        text=m.mention_text,
        reason=reason,
        candidates=seeded,
    )
