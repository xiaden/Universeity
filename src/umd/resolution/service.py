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
  * **Evidence-anchored canonical refs** — new canonical refs are derived from
    an opaque, deterministic anchor over the canonicalized display label, the
    work/continuity scope, and the content-derived evidence tokens (structural
    locator/segment plus a normalized paragraph/context-content digest) of every
    member — NOT from sorted member mention ids. The anchor is independent of
    source/transient ids, filename, job, ingest order, and first establisher, so
    a rerun over the same accepted evidence converges to the same ref. Same-name
    text alone never merges: coincident structural positions with identical
    content are same-character co-references; coincident positions with
    differing (or absent) content are kept distinct and, when no content is
    available, classified AMBIGUOUS/reviewable and never ESTABLISHed.

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

import hashlib
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field

from umd.domain.ids import canonical_entity_ref
from umd.domain.models import ConfidenceState, IdentityClassification
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
    #: Honest resolution classification (accepted/probable) — Plan T P1-S3/R8.
    classification: str = IdentityClassification.PROBABLE.value


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
    #: Honest resolution classification (unresolved/ambiguous) — Plan T P1-S3/R8.
    classification: str = IdentityClassification.UNRESOLVED.value


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
    #: Honest aggregate classification (accepted/probable/unresolved/ambiguous).
    #: Plan T P1-S3/R8 — never infers an identity without evidence.
    classification: str = IdentityClassification.UNRESOLVED.value

    @classmethod
    def from_committed(
        cls,
        committed: Iterable[tuple[str, dict[str, Any]]],
        *,
        source_id: str,
        generated_by: dict[str, Any] | None = None,
    ) -> ResolutionBatch:
        """Build a READ-ONLY ``ResolutionBatch`` from committed canonical identities.

        Plan T P1-S1/R1: SEMANTIC_RECONCILIATION consumes the committed result of
        ENTITY_RESOLUTION (the ESTABLISHed canonicals folded into ``current_state``),
        never a second resolution batch. This projection carries ``canonical_entities``
        + ``alias_mappings`` ONLY — no commands, no assignments, no topology change —
        so the reconciler maps surfaces to refs without re-resolving or inventing
        canonical identity. ``committed`` is an iterable of ``(ref, meta)`` where
        ``meta`` carries display_label / aliases / memberships / support_refs /
        state / confidence / canonical_type / classification.
        """
        canonical_entities: list[CanonicalEntity] = []
        alias_mappings: list[AliasMapping] = []
        state_set: set[str] = set()
        for ref, meta in committed:
            label = str(meta.get("display_label") or "")
            if not label:
                continue
            conf = float(meta["confidence"]) if meta.get("confidence") is not None else 0.0
            classification = str(
                meta.get("classification") or IdentityClassification.PROBABLE.value
            )
            entity_state = str(meta.get("state") or ConfidenceState.PROBABLE.value)
            state_set.add(entity_state)
            canonical_entities.append(
                CanonicalEntity(
                    ref=str(ref),
                    label=label,
                    source_id=source_id,
                    entity_type=str(meta["canonical_type"]) if meta.get("canonical_type") else None,
                    member_mention_ids=list(meta.get("support_refs") or []),
                    confidence=conf,
                    state=entity_state,
                    support_refs=list(meta.get("support_refs") or []),
                    aliases=list(meta.get("aliases") or []),
                    generated_by=dict(generated_by or {}),
                    memberships=dict(meta.get("memberships") or {}),
                    classification=classification,
                )
            )
            for i, alias in enumerate(meta.get("aliases") or []):
                alias_mappings.append(
                    AliasMapping(
                        alias_ref=f"canonical:{ref}:alias:{i}",
                        canonical_ref=str(ref),
                        alias_text=str(alias),
                        canonical_text=label,
                        confidence=conf,
                    )
                )
        return cls(
            source_id=source_id,
            canonical_entities=canonical_entities,
            alias_mappings=alias_mappings,
            assignments={},
            unresolved=[],
            contradictions=[],
            commands=[],
            confidence=(
                round(sum(e.confidence for e in canonical_entities) / len(canonical_entities), 4)
                if canonical_entities
                else 0.0
            ),
            state=(
                ConfidenceState.AMBIGUOUS.value
                if "AMBIGUOUS" in state_set
                else (
                    ConfidenceState.CONFIRMED.value
                    if canonical_entities
                    else ConfidenceState.UNKNOWN.value
                )
            ),
            classification=(
                IdentityClassification.ACCEPTED.value
                if canonical_entities
                and all(
                    e.classification == IdentityClassification.ACCEPTED.value
                    for e in canonical_entities
                )
                else (
                    IdentityClassification.PROBABLE.value
                    if canonical_entities
                    else IdentityClassification.UNRESOLVED.value
                )
            ),
            generated_by=dict(generated_by or {}),
        )


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


class ResolutionInputBuilder:
    """Single pure bounded input/batch builder (Plan T P1-S1 / requirement R1).

    ENTITY_RESOLUTION is the ONLY stage that builds, resolves, and applies a
    resolution batch. SEMANTIC_RECONCILIATION consumes the COMMITTED result via
    :meth:`ResolutionBatch.from_committed` and never rebuilds topology — there is
    exactly one resolution-input/batch builder and one domain decision per
    execution generation.

    ``build`` deterministically assembles a :class:`ResolutionInput` from:

      * ``source`` — the source scope (source_id / work_id / continuity_id);
      * ``evidence`` — the deterministic + provider :class:`SourceMention` records;
      * ``memberships`` — the source-registry work/source/continuity context;
      * ``committed_observations`` — existing canonical ASSIGNMENTS (mention ->
        existing canonical ref) so an accepted identity is reused, never re-derived;
      * ``correspondence`` — explicit correspondence decisions (mention -> ref);
      * ``human_support`` — human-confirmed refs that lock/override machine output.

    The existing-canonical seeding (committed_observations / correspondence /
    human_support) is the ONLY cross-source join a resolution performs here, and it
    is gated on a genuine existing canonical assignment or human confirmation —
    same-name/same-work string equality is NEVER proof (candidate narrowing only).

    Pure: writes nothing; the same inputs always yield the identical
    :class:`ResolutionInput` (idempotent rerun convergence).
    """

    def build(
        self,
        *,
        source: dict[str, Any],
        evidence: Iterable[SourceMention],
        memberships: dict[str, list[str]] | None = None,
        committed_observations: dict[str, str] | None = None,
        correspondence: dict[str, str] | None = None,
        human_support: dict[str, str] | None = None,
        generated_by: dict[str, Any] | None = None,
    ) -> ResolutionInput:
        by_id = {m.mention_id: m for m in evidence}
        # Candidate narrowing (Plan T P1-S2/R2/R3): reuse an EXISTING canonical
        # assignment / explicit correspondence / human-confirmed ref. We never
        # seed by same-name/same-work string equality.
        narrowing: list[dict[str, str]] = [
            committed_observations or {},
            correspondence or {},
            human_support or {},
        ]
        for mid, existing in {k: v for m in narrowing for k, v in m.items()}.items():
            if mid in by_id and existing:
                by_id[mid] = by_id[mid].model_copy(update={"entity_id": str(existing)})
        gb = dict(generated_by or {})
        gb.setdefault("stage", "ENTITY_RESOLUTION")
        gb.setdefault("analyzer", "umd-entity-resolution@1")
        return ResolutionInput(
            source_id=str(source.get("source_id") or ""),
            mentions=sorted(by_id.values(), key=lambda m: m.mention_id),
            generated_by=gb,
            work_id=source.get("work_id"),
            continuity_id=source.get("continuity_id"),
            memberships=memberships or _empty_memberships(),
        )


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


def _content_digest(m: SourceMention) -> str | None:
    """A deterministic content digest of a mention's paragraph/context text.

    Plan T P1-S2/R3: normalized surrounding content participates in the evidence
    anchor, so two same-work same-name mentions at a coincident structural
    locator resolve to DISTINCT opaque refs when their surrounding text differs
    (and to one same-character ref when it is identical). Returns ``None`` when
    no content is available (the risky coincident-locator case).
    """
    ct = m.context_text
    if not ct:
        return None
    norm = normalize_name(ct) or ct.casefold()
    return hashlib.sha256(norm.encode()).hexdigest()


def _structural_locator(m: SourceMention) -> str | None:
    """The deterministic structural position of a mention (locator or segment).

    Used to detect coincident structural positions. Prefers the evidence
    locator (the structural path the STRUCTURAL_ANALYSIS stream carries); falls
    back to the registered segment id. Returns ``None`` when neither is present.
    """
    loc = (m.provenance or {}).get("locator")
    if loc:
        return f"loc:{loc}"
    if m.segment_id:
        return f"seg:{m.segment_id}"
    return None


def _coincident_no_shared_content(a: SourceMention, b: SourceMention) -> bool:
    """True when two mentions share a structural position without identical content.

    Plan T P1-S2/R3: at a coincident structural locator, only identical content
    is treated as same-character co-reference (union). Different content means
    two DISTINCT characters (they stay separate); absent content on either side
    is a no-content coincidence collision that must not auto-unify (it is
    classified AMBIGUOUS downstream, never merged by name/work/locator alone).
    """
    la = _structural_locator(a)
    if la is None or la != _structural_locator(b):
        return False  # different (or no) structural positions -> normal linkage
    da = _content_digest(a)
    db = _content_digest(b)
    # Identical surrounding content is same-character co-reference (auto-union);
    # coincident-but-no-shared-content (different or absent) must not auto-union.
    return not (da is not None and db is not None and da == db)


def _evidence_tokens(m: SourceMention) -> list[str]:
    """Content-derived evidence tokens for a mention (Plan T P1-S2).

    The anchor is deliberately source-independent: it uses the deterministic
    structural evidence (segment id / locator) plus a digest of the normalized
    paragraph/context content, never the source id, transient mention id,
    filename, job, or any per-source UUID. A mention with no registered segment
    falls back to its canonicalized surface form only so the anchor stays
    non-empty (the work/continuity scope still disambiguates).
    """
    tokens: list[str] = []
    if m.segment_id:
        tokens.append(f"seg:{m.segment_id}")
    loc = (m.provenance or {}).get("locator")
    if loc:
        tokens.append(f"loc:{loc}")
    cd = _content_digest(m)
    if cd:
        tokens.append(f"ctx:{cd[:16]}")
    if not tokens:
        norm = normalize_name(m.mention_text) or m.mention_text.casefold()
        tokens.append(f"text:{norm}")
    return tokens


def _cluster_memberships(
    members: list[SourceMention],
    *,
    work_id: str | None,
    continuity_id: str | None,
    scope: dict[str, list[str]],
) -> dict[str, list[str]]:
    """Aggregate a cluster's work/source/continuity membership context.

    Carries the explicit source-level work/continuity scope (P3-S1) when a member
    did not annotate it directly, so the canonical stays scoped.
    """
    memberships = {
        "source_ids": sorted({m.source_id for m in members if m.source_id}),
        "work_ids": sorted({m.work_id for m in members if m.work_id}),
        "continuity_ids": sorted({m.continuity_id for m in members if m.continuity_id}),
    }
    if work_id and not memberships["work_ids"]:
        memberships["work_ids"] = [work_id]
    if continuity_id and not memberships["continuity_ids"]:
        memberships["continuity_ids"] = [continuity_id]
    if not memberships["source_ids"] and scope.get("source_ids"):
        memberships["source_ids"] = list(scope["source_ids"])
    return memberships


def _evidence_canonical_ref(
    members: list[SourceMention],
    label: str,
    memberships: dict[str, list[str]],
) -> str:
    """Evidence-backed opaque canonical ref for a NEW (unseeded) cluster.

    The anchor material is the canonicalized display label plus the
    work/continuity scope plus the deterministic content-derived evidence refs
    of every member — sorted and deduplicated so a rerun over the same accepted
    cluster converges to the same ref, independent of ingest order, source,
    filename, job, transient id, or first establisher. Same-name text alone
    never merges: distinct work scope or distinct evidence yields a distinct
    ref, so same-name characters coexist and cross-source joins require accepted
    evidence / correspondence / existing assignment / human confirmation.
    """
    norm = normalize_name(label) or label.casefold()
    anchor: list[str] = [f"label:{norm}"]
    anchor.extend(f"work:{w}" for w in sorted(memberships.get("work_ids") or []))
    anchor.extend(f"cont:{c}" for c in sorted(memberships.get("continuity_ids") or []))
    for m in sorted(members, key=lambda x: x.mention_id):
        anchor.extend(_evidence_tokens(m))
    return canonical_entity_ref(anchor)


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
                # Plan T P1-S2/R3: at a coincident structural position only
                # identical content is same-character co-reference. Different (or
                # absent) content is NOT auto-unioned — those mentions stay
                # separate and (when content is absent) surface as AMBIGUOUS.
                if _coincident_no_shared_content(m, mention_by_id[target]):
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

        # Plan T P1-S2/R3 — coincidence-collision detection: compute the evidence
        # anchor ref for every NEW (unseeded) cluster up front so that two DISTINCT
        # clusters deriving the SAME opaque ref (same name + work + coincident
        # structural locator, no content to disambiguate) are never both established.
        # Such a collision is a no-content coincidence -> AMBIGUOUS/reviewable, with
        # NO ESTABLISH (the resolver never merges distinct mentions by name/work/
        # locator alone). Seeded clusters reuse their existing ref and never collide.
        new_ref_by_root: dict[str, str] = {}
        for root in roots:
            if uf.seed_of(root) is not None:
                continue
            rmembers = sorted(roots[root], key=lambda m: m.mention_id)
            rlabel = _canonical_label(rmembers)
            new_ref_by_root[root] = _evidence_canonical_ref(
                rmembers,
                rlabel,
                _cluster_memberships(
                    rmembers,
                    work_id=input_work_id,
                    continuity_id=input_continuity_id,
                    scope=input_scope,
                ),
            )
        _ref_counts: dict[str, int] = {}
        for ref in new_ref_by_root.values():
            _ref_counts[ref] = _ref_counts.get(ref, 0) + 1
        _collided_refs = {ref for ref, n in _ref_counts.items() if n > 1}

        canonical_entities: list[CanonicalEntity] = []
        alias_mappings: list[AliasMapping] = []
        assignments: dict[str, str] = {}
        unresolved: list[UnresolvedMention] = []
        commands: list[ResolutionCommand] = []

        for root in sorted(roots, key=lambda r: (uf.seed_of(r) or "", r)):
            members = sorted(roots[root], key=lambda m: m.mention_id)
            seed = uf.seed_of(root)

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
            memberships = _cluster_memberships(
                members,
                work_id=input_work_id,
                continuity_id=input_continuity_id,
                scope=input_scope,
            )

            if seed is not None:
                canonical_ref = seed
                entity_state = ConfidenceState.CONFIRMED.value
            else:
                canonical_ref = _evidence_canonical_ref(members, label, memberships)
                entity_state = ConfidenceState.PROBABLE.value
                if canonical_ref in _collided_refs:
                    # No-content coincidence collision (same name + work +
                    # coincident structural locator, no content to disambiguate):
                    # keep the mentions AMBIGUOUS/reviewable and do NOT ESTABLISH.
                    for m in members:
                        unresolved.append(
                            UnresolvedMention(
                                mention_id=m.mention_id,
                                text=m.mention_text,
                                reason="ambiguous",
                                classification=IdentityClassification.AMBIGUOUS.value,
                            )
                        )
                    continue
            classification = (
                IdentityClassification.ACCEPTED.value
                if seed is not None
                else IdentityClassification.PROBABLE.value
            )
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
                    classification=classification,
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
                        "classification": classification,
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
        # Honest aggregate classification (Plan T P1-S3/R8): ambiguity that must
        # stay reviewable outranks a probable machine inference, which outranks a
        # fully-accepted batch. Unknown surfaces are never fabricated as accepted.
        if unresolved:
            batch_class = (
                IdentityClassification.AMBIGUOUS.value
                if any(u.reason == "ambiguous" for u in unresolved)
                else IdentityClassification.UNRESOLVED.value
            )
        elif canonical_entities:
            batch_class = (
                IdentityClassification.ACCEPTED.value
                if all(
                    e.classification == IdentityClassification.ACCEPTED.value
                    for e in canonical_entities
                )
                else IdentityClassification.PROBABLE.value
            )
        else:
            batch_class = IdentityClassification.UNRESOLVED.value

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
            classification=batch_class,
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
        # Honest classification (Plan T P1-S3/R8): a genuinely ambiguous mention
        # must stay reviewable as AMBIGUOUS, never silently guessed.
        classification=(
            IdentityClassification.AMBIGUOUS.value
            if reason == "ambiguous"
            else IdentityClassification.UNRESOLVED.value
        ),
    )
