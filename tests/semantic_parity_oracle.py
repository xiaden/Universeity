"""Generic Alexandria 2a-2f semantic parity oracle (Semantic Capability P, Phase 2).

Implements CONTRACTS.md:83 ``SemanticParityOracle.compare(fixture, modes) ->
ParityMatrix`` — a generic, repository-owned public-surface comparison for the
six Alexandria walks:

* ``2a`` scene segmentation    -> typed segment/scene surface (SCENE query kind
  reads ``segment_type``; segment registry/locators);
* ``2b`` character discovery   -> ENTITY surface (characters in the work);
* ``2c`` alias resolution      -> ALIAS surface (aliases + unresolved aliases);
* ``2d`` scene presence        -> PRESENT_IN / scene-membership edges;
* ``2e`` span attribution      -> EVIDENCE surface (evidence-linked spans,
  locators, provenance);
* ``2f`` character description -> trait/description assertions + evidence.

The oracle walks ONLY public typed surfaces — the deterministic
``SemanticAnalysisResult`` observation contract (:mod:`umd.analysis.semantic`),
the registered ``SegmentRegistry`` segment/locator surface, and the durable
``Evidence`` rows — never copied Alexandria/SQLite/audiobook state. It compares
the ``deterministic``, ``provider``, and ``hybrid`` routes over the SAME
fixture by normalizing each walk's typed reads into comparable
:class:`TypedClaim` sets (subject, predicate, object, confidence, authority,
semantic state, scope, support refs, provenance) and asserts that provider
output is either an evidence-supported extension of the deterministic baseline
or an honest gated/degraded result — never a fabricated claim.

The result is a :class:`ParityMatrix` with one row per ``(walk, route)`` and a
status of PASS / DIFF / GATED / UNSUPPORTED, including support refs,
confidence, authority, semantic state, scope, and provider/config/prompt
provenance, serializable to Markdown (Phase 3 persists it to
``artifacts/reports/``).

This module lives in the test suite (per plan scope) and contains no
consumer-specific state. It deliberately does NOT write to Postgres: the typed
public-surface inputs are produced by driving the real production seams (Plan L
``TextDispatch`` -> segmenter -> Plan M ``SemanticTextAnalyzer`` deterministic +
optional-provider observations), the same seams Phase 3 drives through the full
StageWork registry. Phase 3 can feed the same walk extractors from Postgres-
backed query/ledger pages because the claim extractors operate on the typed
contracts, not internal pipeline state.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from fixtures import BOOK_FORMATS, BOOK_SOURCE_SHA512, BOOK_TITLE, semantic_book_bytes
from umd.analysis.semantic import GeneratedBy, SemanticAnalysisResult, SemanticPath
from umd.analysis.semantic_analyzer import SemanticAnalysisInput, SemanticTextAnalyzer
from umd.analysis.text_structural import ParagraphSegment
from umd.domain.models import ConfidenceState
from umd.extractors.dispatch import dispatch_text
from umd.models.provider import (
    ModelMode,
    ModelProvider,
    ModelRequest,
    StructuredModelResult,
)
from umd.models.registry import ProviderRegistry
from umd.segmentation.registry import InMemorySegmentStore, SegmentRegistry

#: Alexandria walk identifiers (semantic capability repair ledger 2a-2f).
WALK_2A = "2a"  # scene segmentation
WALK_2B = "2b"  # character discovery
WALK_2C = "2c"  # alias resolution
WALK_2D = "2d"  # scene presence
WALK_2E = "2e"  # span attribution
WALK_2F = "2f"  # character description

WALKS: tuple[str, ...] = (WALK_2A, WALK_2B, WALK_2C, WALK_2D, WALK_2E, WALK_2F)

ROUTE_DETERMINISTIC = "deterministic"
ROUTE_PROVIDER = "provider"
ROUTE_HYBRID = "hybrid"

#: Route ordering for the matrix.
_ROUTE_ORDER = (ROUTE_DETERMINISTIC, ROUTE_PROVIDER, ROUTE_HYBRID)

#: Deterministic source id (a fixed valid UUID so ``SemanticTextAnalyzer`` can
#: assemble evidence; stable across runs so claims are reproducible).
_SID = "00000000-0000-4000-8000-0000000000ab"
#: Deterministic source sha512 placeholder for the in-memory segment registry
#: (matches the Phase-1 fixture determinism test convention).
_SHA = "a" * 128

#: Segment types the public SCENE query kind treats as scenes/segments
#: (mirrors ``QueryService.SCENE_SEGMENT_TYPES``).
_SCENE_TYPES = frozenset({"scene", "chapter", "shot", "frame", "section", "act"})


class Fixture(Protocol):
    """Generic repository-owned fixture the oracle compares routes over."""

    title: str
    formats: tuple[str, ...]

    def source_bytes(self, fmt: str) -> bytes: ...
    def sha512(self, fmt: str) -> str: ...


class _BookFixture:
    """Adapter over the Phase-1 ``The Lantern Keeper`` book fixture."""

    title = BOOK_TITLE
    formats = BOOK_FORMATS

    @staticmethod
    def source_bytes(fmt: str) -> bytes:
        return semantic_book_bytes(fmt)

    @staticmethod
    def sha512(fmt: str) -> str:
        return BOOK_SOURCE_SHA512[fmt]


def book_fixture() -> Fixture:
    """Return the repository's generic book fixture (``The Lantern Keeper``)."""
    return _BookFixture()


# ---------------------------------------------------------------------------
# Normalized typed claims
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TypedClaim:
    """One normalized typed claim (subject, predicate, object, + metadata).

    ``support_refs`` are the exact segment/evidence locators substantiating the
    claim. ``provenance`` is a stable, sortable (key, value) tuple so claims are
    hashable and directly comparable across routes.
    """

    walk: str
    subject: str
    predicate: str
    object: str
    confidence: float
    authority: str  # deterministic | provider
    state: str  # ConfidenceState value
    scope: str  # canonical segment locator scope
    support_refs: tuple[str, ...]
    provenance: tuple[tuple[str, str], ...]


def _provenance(gb: GeneratedBy) -> tuple[tuple[str, str], ...]:
    """Normalize ``generated-by`` provenance into a sortable tuple."""
    items = {
        "path": gb.path.value,
        "analyzer": gb.analyzer,
        "provider": gb.provider or "",
        "model": gb.model or "",
        "model_version": gb.model_version or "",
        "prompt_version": gb.prompt_version or "",
        "config_digest": gb.config_digest or "",
    }
    return tuple(sorted(items.items()))


# ---------------------------------------------------------------------------
# Walk claim extractors (read ONLY the public typed surfaces)
# ---------------------------------------------------------------------------


def _claims_2a(result: SemanticAnalysisResult, locators: set[str]) -> list[TypedClaim]:
    """Scene segmentation: scene-boundary observations + scene segment types."""
    claims: list[TypedClaim] = []
    for sb in result.scene_boundaries:
        claims.append(
            TypedClaim(
                walk=WALK_2A,
                subject=sb.scene_ref,
                predicate="SCENE_BOUNDARY",
                object=f"{sb.boundary}:{sb.label or ''}",
                confidence=sb.confidence,
                authority=_authority(sb.generated_by.path),
                state=sb.state.value,
                scope=sb.segment.locator,
                support_refs=(sb.segment.locator,),
                provenance=_provenance(sb.generated_by),
            )
        )
    # The SCENE query kind reads ``segment_type`` over registered segments;
    # expose every scene-capable segment as a typed scene claim.
    for structural in sorted(locators):
        seg_type = _segment_type_from_path(structural)
        if seg_type in _SCENE_TYPES:
            claims.append(
                TypedClaim(
                    walk=WALK_2A,
                    subject=structural,
                    predicate="SEGMENT_TYPE",
                    object=seg_type,
                    confidence=1.0,
                    authority="deterministic",
                    state=ConfidenceState.PROBABLE.value,
                    scope=structural,
                    support_refs=(structural,),
                    provenance=(("path", "deterministic"), ("source", "segment_registry")),
                )
            )
    return claims


def _claims_2b(result: SemanticAnalysisResult) -> list[TypedClaim]:
    """Character discovery: entity/character mentions (ENTITY surface)."""
    return [
        TypedClaim(
            walk=WALK_2B,
            subject=em.mention,
            predicate="IS_CHARACTER",
            object=em.entity_type,
            confidence=em.confidence,
            authority=_authority(em.generated_by.path),
            state=em.state.value,
            scope=em.segment.locator,
            support_refs=(em.segment.locator,),
            provenance=_provenance(em.generated_by),
        )
        for em in result.entity_mentions
    ]


def _claims_2c(result: SemanticAnalysisResult) -> list[TypedClaim]:
    """Alias resolution: normalized alias -> canonical mapping (ALIAS surface)."""
    return [
        TypedClaim(
            walk=WALK_2C,
            subject=a.alias,
            predicate="ALIAS_OF",
            object=a.canonical_name,
            confidence=a.confidence,
            authority=_authority(a.generated_by.path),
            state=a.state.value,
            scope=a.segment.locator,
            support_refs=(a.segment.locator,),
            provenance=_provenance(a.generated_by),
        )
        for a in result.aliases
    ]


def _claims_2d(result: SemanticAnalysisResult) -> list[TypedClaim]:
    """Scene presence: entity PRESENT_IN scene/segment edges."""
    return [
        TypedClaim(
            walk=WALK_2D,
            subject=p.entity,
            predicate="PRESENT_IN",
            object=p.present_in,
            confidence=p.confidence,
            authority=_authority(p.generated_by.path),
            state=p.state.value,
            scope=p.segment.locator,
            support_refs=(p.segment.locator,),
            provenance=_provenance(p.generated_by),
        )
        for p in result.presence
    ]


def _claims_2e(result: SemanticAnalysisResult) -> list[TypedClaim]:
    """Span attribution: evidence-linked spans, locators, provenance (EVIDENCE surface).

    Claims are keyed on the evidence identity material ``(evidence_kind,
    locator)`` rather than the random UUID evidence ``id`` so they are stable
    across analyzer runs (Phase-1 discovery: evidence row ids are random UUIDs,
    so they cannot anchor a deterministic comparison). Provider-backed evidence
    rows are detected by the ``provider`` entry in their ``tool_versions``.
    """
    claims: list[TypedClaim] = []
    for ev in result.evidence:
        locator = ev.locator or ""
        kind = ev.evidence_kind.value
        provider_backed = "provider" in ev.tool_versions
        provenance_items = [
            ("path", "provider" if provider_backed else "deterministic"),
            ("config_digest", ev.config_digest or ""),
            ("evidence_kind", kind),
            ("extraction_stage", ev.extraction_stage or ""),
        ]
        if provider_backed:
            provenance_items.extend(
                (k, ev.tool_versions.get(k, ""))
                for k in ("provider", "model", "model_version", "prompt_version")
            )
        claims.append(
            TypedClaim(
                walk=WALK_2E,
                subject=f"evidence:{locator}:{kind}",
                predicate="EVIDENCES_SPAN",
                object=locator,
                confidence=ev.confidence if ev.confidence is not None else 1.0,
                authority="provider" if provider_backed else "deterministic",
                state=ConfidenceState.PROBABLE.value,
                scope=locator,
                support_refs=(locator,) if locator else (),
                provenance=tuple(sorted(provenance_items)),
            )
        )
    for span in result.dialogue_spans:
        claims.append(
            TypedClaim(
                walk=WALK_2E,
                subject=span.locator,
                predicate="SPAN_KIND",
                object="dialogue" if span.is_dialogue else "narration",
                confidence=0.9,
                authority="deterministic",
                state=ConfidenceState.PROBABLE.value,
                scope=span.locator,
                support_refs=(span.locator,),
                provenance=(("path", "deterministic"), ("source", "dialogue_span")),
            )
        )
    return claims


def _claims_2f(result: SemanticAnalysisResult) -> list[TypedClaim]:
    """Character description: trait/description assertions + supporting evidence."""
    return [
        TypedClaim(
            walk=WALK_2F,
            subject=t.entity,
            predicate="HAS_TRAIT",
            object=t.trait,
            confidence=t.confidence,
            authority=_authority(t.generated_by.path),
            state=t.state.value,
            scope=t.segment.locator,
            support_refs=(t.segment.locator,),
            provenance=_provenance(t.generated_by),
        )
        for t in result.traits
    ]


def extract_walk_claims(
    walk: str, result: SemanticAnalysisResult, locators: set[str]
) -> list[TypedClaim]:
    """Extract one walk's normalized claims from the public typed surface."""
    if walk == WALK_2E:
        return _claims_2e(result)
    if walk == WALK_2A:
        return _claims_2a(result, locators)
    if walk == WALK_2B:
        return _claims_2b(result)
    if walk == WALK_2C:
        return _claims_2c(result)
    if walk == WALK_2D:
        return _claims_2d(result)
    return _claims_2f(result)


def _authority(path: SemanticPath) -> str:
    return "deterministic" if path == SemanticPath.DETERMINISTIC else "provider"


# ---------------------------------------------------------------------------
# Segment-surface helpers
# ---------------------------------------------------------------------------


def _segment_type_from_path(path: str) -> str:
    for token in (
        "document",
        "chapter",
        "section",
        "paragraph",
        "sentence",
        "token",
        "scene",
        "act",
        "shot",
        "frame",
    ):
        if path == token or path.startswith(f"{token}/") or f"/{token}/" in path:
            return token
    return ""


def _chapter_from_path(path: str) -> int:
    marker = "/chapter/"
    if marker in path:
        num = ""
        for ch in path.split(marker, 1)[1]:
            if ch.isdigit():
                num += ch
            else:
                break
        if num:
            return int(num)
    return 1


def _paragraph_segments(seg: Any) -> list[ParagraphSegment]:
    """Build deterministic analyzer ``ParagraphSegment`` records from the registered
    paragraph segments (public segment surface), in reading order.

    Mirrors the production seam (``production.py._paragraph_segments``):
    ``segment_id=None`` (the registered deterministic segment id is a non-UUID
    string and cannot back ``Evidence.segment_id``) and ``locator`` is the
    structural path — the public segment identifier the analyzer uses for
    evidence/observation scope."""
    para_segs = [s for s in seg.batch.created if s.segment_type == "paragraph"]
    texts = list(seg.paragraphs)
    assert len(para_segs) == len(texts), "paragraph segments/paragraph texts mismatch"
    out: list[ParagraphSegment] = []
    per_chapter: dict[int, int] = {}
    for s, text in zip(para_segs, texts, strict=True):
        chapter = _chapter_from_path(s.structural_path)
        per_chapter[chapter] = per_chapter.get(chapter, 0) + 1
        out.append(
            ParagraphSegment(
                text=text,
                paragraph_index=per_chapter[chapter],
                chapter=chapter,
                locator=s.structural_path,
                structural_path=s.structural_path,
                segment_id=None,
            )
        )
    return out


def _locator_universe(seg: Any) -> set[str]:
    """The set of public segment identifiers (structural paths) for the format."""
    return {s.structural_path for s in seg.batch.created}


# ---------------------------------------------------------------------------
# Provider route (test-registered fake provider, Plan M substitution pattern)
# ---------------------------------------------------------------------------


class FakeSemanticProvider:
    """A contract-compliant provider returning realistic evidence-anchored
    semantic observations (Plan M substitution pattern).

    The output is anchored to the exact segment locators passed in
    ``ModelRequest.input_refs`` (what ``SemanticTextAnalyzer`` supplies from the
    segmented fixture), so every candidate carries a real segment locator that
    the analyzer's ``_exact_support`` gate accepts. This exercises the provider
    code path hermetically and records real provider/config/prompt provenance.
    """

    name = "fake_semantic"

    def __init__(self, entity_locators: dict[str, str] | None = None) -> None:
        #: Per-entity ``present_in`` segment to anchor presence edges at — passed
        #: from the deterministic route so provider presence agrees with where the
        #: deterministic detector found each character (a genuine evidence-
        #: supported extension, not a locator contradiction).
        self._entity_locators = entity_locators or {}
        self.calls: list[ModelRequest] = []

    def _presence_locator(self, entity: str, fallback: str) -> str:
        return self._entity_locators.get(entity) or fallback

    def invoke(self, request: ModelRequest) -> StructuredModelResult:
        self.calls.append(request)
        refs = list(request.input_refs or [])
        loc_a = refs[0] if refs else "chapter/1/paragraph/1"
        loc_b = refs[-1] if refs else loc_a
        loc_c = refs[len(refs) // 2] if len(refs) > 1 else loc_a

        def seg(locator: str) -> dict[str, str]:
            return {"locator": locator}

        output: dict[str, Any] = {
            "entities": [
                {
                    "mention": "Mara",
                    "entity_type": "character",
                    "confidence": 0.92,
                    "segment": seg(loc_a),
                },
                {
                    "mention": "Ellis",
                    "entity_type": "character",
                    "confidence": 0.91,
                    "segment": seg(loc_a),
                },
                {
                    "mention": "Orin",
                    "entity_type": "character",
                    "confidence": 0.9,
                    "segment": seg(loc_b),
                },
            ],
            "aliases": [
                {
                    "canonical_name": "Mara",
                    "alias": "Moss",
                    "confidence": 0.9,
                    "segment": seg(loc_a),
                },
                {
                    "canonical_name": "Mara",
                    "alias": "the apprentice",
                    "confidence": 0.85,
                    "segment": seg(loc_a),
                },
                {
                    "canonical_name": "Ellis",
                    "alias": "the cartographer",
                    "confidence": 0.9,
                    "segment": seg(loc_a),
                },
                {
                    "canonical_name": "Orin",
                    "alias": "the warden",
                    "confidence": 0.9,
                    "segment": seg(loc_b),
                },
            ],
            "traits": [
                {
                    "entity": "Mara",
                    "trait": "moss-green eyes",
                    "confidence": 0.9,
                    "segment": seg(loc_a),
                },
                {"entity": "Orin", "trait": "grey beard", "confidence": 0.9, "segment": seg(loc_b)},
            ],
            "presence": [
                {
                    "entity": "Mara",
                    "present_in": self._presence_locator("Mara", loc_a),
                    "confidence": 0.8,
                    "segment": seg(self._presence_locator("Mara", loc_a)),
                },
                {
                    "entity": "Ellis",
                    "present_in": self._presence_locator("Ellis", loc_a),
                    "confidence": 0.8,
                    "segment": seg(self._presence_locator("Ellis", loc_a)),
                },
                {
                    "entity": "Orin",
                    "present_in": self._presence_locator("Orin", loc_b),
                    "confidence": 0.8,
                    "segment": seg(self._presence_locator("Orin", loc_b)),
                },
                {
                    "entity": "Mara",
                    "present_in": self._presence_locator("Mara", loc_c),
                    "confidence": 0.7,
                    "segment": seg(self._presence_locator("Mara", loc_c)),
                },
            ],
            "relationships": [
                {
                    "subject_ref": "Mara",
                    "predicate": "SIBLING_OF",
                    "object_ref": "Ellis",
                    "confidence": 0.7,
                    "segment": seg(loc_a),
                },
            ],
        }
        return StructuredModelResult(
            mode=ModelMode.COMPLETION,
            model=request.model,
            model_version="1.0.0",
            provider=self.name,
            prompt_version=request.prompt_version,
            output=output,
            confidence=0.9,
            input_refs=request.input_refs,
            stage=request.stage,
        )


# ---------------------------------------------------------------------------
# Route drivers
# ---------------------------------------------------------------------------


@dataclass
class RouteClaims:
    """One format's claims per walk for each route + the segment locator universe."""

    deterministic: dict[str, list[TypedClaim]] = field(default_factory=dict)
    provider: dict[str, list[TypedClaim]] = field(default_factory=dict)
    hybrid: dict[str, list[TypedClaim]] = field(default_factory=dict)
    locators: set[str] = field(default_factory=set)


def _run_analyzer(
    fmt: str,
    fixture: Fixture,
    *,
    registry: ProviderRegistry | None = None,
    provider: str | None = None,
    model: str | None = None,
) -> tuple[SemanticAnalysisResult, set[str]]:
    """Drive the real seams (TextDispatch -> segmenter -> SemanticTextAnalyzer)
    for one format and return the typed result + the segment locator universe."""
    reg = SegmentRegistry(InMemorySegmentStore())
    res = dispatch_text(fixture.source_bytes(fmt), format=fmt, source_sha512=_SHA)
    seg = res.segment(reg, source_id=_SID, source_sha512=_SHA)
    assert seg is not None, f"{fmt} routed off the text path"
    paragraphs = _paragraph_segments(seg)
    locators = _locator_universe(seg)
    analyzer = SemanticTextAnalyzer(
        registry,
        provider=provider,
        model=model,
        config_digest="umd-dispatch@1",
    )
    result = analyzer.analyze(SemanticAnalysisInput(source_id=_SID, segments=paragraphs))
    return result, locators


def _run_format(
    fmt: str,
    fixture: Fixture,
    *,
    run_provider: bool,
) -> RouteClaims:
    """Run one format's routes and return per-route claims per walk.

    The deterministic route always runs. When ``run_provider``, the provider
    (provider-path claims) and hybrid (full merged set) routes run over the same
    segmentation via a registered fake provider.
    """
    det_result, det_locators = _run_analyzer(fmt, fixture)
    det_claims = {w: extract_walk_claims(w, det_result, det_locators) for w in WALKS}
    if not run_provider:
        return RouteClaims(deterministic=det_claims, locators=det_locators)

    # Anchor provider presence edges at the segment where the deterministic route
    # discovered each character (last locator per entity mirrors the parity
    # oracle's per-subject collapse), so provider presence is a genuine extension
    # rather than a locator contradiction.
    det_entity_locs: dict[str, str] = {}
    for c in det_claims[WALK_2B]:
        det_entity_locs[c.subject] = c.scope
    fake = FakeSemanticProvider(entity_locators=det_entity_locs)
    registry = ProviderRegistry([fake])
    prov_result, prov_locators = _run_analyzer(
        fmt, fixture, registry=registry, provider="fake_semantic", model="fake-model"
    )
    locators = det_locators | prov_locators
    full = {w: extract_walk_claims(w, prov_result, locators) for w in WALKS}
    provider_claims = {
        w: [c for c in full[w] if dict(c.provenance).get("path") == "provider"] for w in WALKS
    }
    return RouteClaims(
        deterministic=det_claims,
        provider=provider_claims,
        hybrid={w: list(full[w]) for w in WALKS},
        locators=locators,
    )


# ---------------------------------------------------------------------------
# Parity matrix
# ---------------------------------------------------------------------------


@dataclass
class ParityRow:
    """One ``(walk, route)`` comparison row of the parity matrix."""

    walk: str
    route: str
    status: str  # PASS | DIFF | GATED | UNSUPPORTED
    claims: tuple[TypedClaim, ...] = ()
    support_refs: tuple[str, ...] = ()
    confidence: float | None = None
    authority: str = ""
    state: str = ""
    scope: str = ""
    gate: str | None = None
    gate_reason: str | None = None
    provider_provenance: dict[str, Any] | None = None
    notes: tuple[str, ...] = ()

    def to_markdown(self) -> str:
        conf = f"{self.confidence:.3f}" if self.confidence is not None else "-"
        gate = self.gate or "-"
        notes = "; ".join(self.notes)
        return (
            f"| {self.walk} | {self.route} | {self.status} | {self.authority or '-'} | "
            f"{conf} | {self.state or '-'} | {self.scope or '-'} | {len(self.support_refs)} | "
            f"{gate} | {notes} |"
        )


@dataclass
class ParityMatrix:
    """The full 2a-2f x route parity matrix (CONTRACTS.md:83)."""

    title: str
    fixture_sha512: dict[str, str]
    provider_gate: dict[str, Any]
    rows: list[ParityRow]

    def row(self, walk: str, route: str) -> ParityRow | None:
        for r in self.rows:
            if r.walk == walk and r.route == route:
                return r
        return None

    def to_markdown(self) -> str:
        hashes = ", ".join(f"{fmt}={h}" for fmt, h in sorted(self.fixture_sha512.items()))
        lines = [
            f"# Semantic Capability Parity Matrix — {self.title}",
            "",
            f"- Fixture sha512: `{hashes}`",
            f"- Provider gate: `{self.provider_gate.get('status')}` — "
            f"{self.provider_gate.get('reason', '')}",
            "",
            "| Walk | Route | Status | Authority | Confidence | State | Scope | "
            "#support | Gate | Notes |",
            "|------|-------|--------|-----------|------------|-------|-------|----------|------|-------|",
        ]
        lines.extend(r.to_markdown() for r in self.rows)
        return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Fabrication / consistency checks
# ---------------------------------------------------------------------------


def _fabricated(claims: list[TypedClaim], locators: set[str]) -> list[TypedClaim]:
    """Claims whose segment support is absent from the segment surface (no exact
    evidence support). The 2e evidence surface is self-supporting (its rows ARE
    the evidence); all other walks must reference a real segment locator."""
    return [
        c
        for c in claims
        if c.walk != WALK_2E and c.support_refs and not all(s in locators for s in c.support_refs)
    ]


def _contradicts(provider: list[TypedClaim], det: list[TypedClaim]) -> list[TypedClaim]:
    """Provider claims that flatly contradict a deterministic finding (same
    subject+predicate, different object) — an extension must never overwrite a
    deterministic finding with a different value.

    Deterministic findings can be multi-valued per subject (e.g. PRESENT_IN
    spans many segments), so a provider claim only contradicts when its object
    agrees with NONE of the deterministic objects for that subject. A subject/
    predicate with a single deterministic value behaves exactly as a strict
    equality check, so the fabrication guarantee is unchanged.
    """
    det_map: dict[tuple[str, str], set[str]] = {}
    for c in det:
        det_map.setdefault((c.subject, c.predicate), set()).add(c.object)
    return [
        c
        for c in provider
        if (c.subject, c.predicate) in det_map and c.object not in det_map[(c.subject, c.predicate)]
    ]


def _row_confidence(claims: list[TypedClaim]) -> float | None:
    if not claims:
        return None
    return sum(c.confidence for c in claims) / len(claims)


def _summarize(values: set[str], *, cap: int = 3) -> str:
    if not values:
        return "-"
    ordered = sorted(values)
    if len(ordered) <= cap:
        return ", ".join(ordered)
    return f"{', '.join(ordered[:cap])}, +{len(ordered) - cap} more"


class SemanticParityOracle:
    """Generic repository-owned parity oracle (CONTRACTS.md:83)."""

    def __init__(
        self,
        *,
        live_provider: ModelProvider | None = None,
        live_provider_name: str | None = None,
    ) -> None:
        #: Optional LIVE provider (Phase 3 / provider-configured environments).
        #: When None, provider/hybrid modes are exercised via a registered fake
        #: provider and the unexecuted-live-provider gate is reported honestly.
        self._live_provider = live_provider
        self._live_provider_name = live_provider_name

    # -- public contract ----------------------------------------------------

    def compare(
        self,
        fixture: Fixture,
        modes: tuple[str, ...] = (ROUTE_DETERMINISTIC, ROUTE_PROVIDER, ROUTE_HYBRID),
    ) -> ParityMatrix:
        """Compare the fixture across the requested routes and return a matrix."""
        modes = tuple(m for m in _ROUTE_ORDER if m in modes)
        want_provider = ROUTE_PROVIDER in modes or ROUTE_HYBRID in modes

        det_claims: dict[str, list[TypedClaim]] = {w: [] for w in WALKS}
        provider_claims: dict[str, list[TypedClaim]] = {w: [] for w in WALKS}
        hybrid_claims: dict[str, list[TypedClaim]] = {w: [] for w in WALKS}
        locators: set[str] = set()

        for fmt in fixture.formats:
            rc = _run_format(fmt, fixture, run_provider=want_provider)
            locators |= rc.locators
            for w in WALKS:
                det_claims[w].extend(rc.deterministic[w])
                if want_provider:
                    provider_claims[w].extend(rc.provider[w])
                    hybrid_claims[w].extend(rc.hybrid[w])

        live_configured = self._live_provider is not None
        gate_reason = (
            None
            if live_configured
            else "no live provider configured; provider/hybrid modes exercised via a "
            "registered fake provider 'fake_semantic' (real provenance recorded per "
            "row); the unexecuted live-provider mode is reported honestly as GATED"
        )
        provider_gate = {
            "status": "ACTIVE" if live_configured else "GATED",
            "live_provider_configured": live_configured,
            "mode": "live" if live_configured else "fake-exercised",
            "reason": (
                f"live provider '{self._live_provider_name}' configured"
                if live_configured
                else gate_reason
            ),
        }

        rows: list[ParityRow] = []
        for walk in WALKS:
            for route in _ROUTE_ORDER:
                if route not in modes:
                    continue
                claims, fabricated, status, notes = self._decide_status(
                    walk, route, modes, det_claims, provider_claims, hybrid_claims, locators
                )
                support = (
                    tuple(sorted({r for cl in claims for r in cl.support_refs})) if claims else ()
                )
                provenance: dict[str, Any] | None = None
                if route in (ROUTE_PROVIDER, ROUTE_HYBRID) and claims:
                    prov = dict(claims[0].provenance)
                    provenance = {
                        "path": prov.get("path"),
                        "analyzer": prov.get("analyzer"),
                        "provider": prov.get("provider"),
                        "model": prov.get("model"),
                        "model_version": prov.get("model_version"),
                        "prompt_version": prov.get("prompt_version"),
                        "config_digest": prov.get("config_digest"),
                        "mode": "live" if live_configured else "fake-exercised",
                    }
                rows.append(
                    ParityRow(
                        walk=walk,
                        route=route,
                        status=status,
                        claims=tuple(claims),
                        support_refs=support,
                        confidence=_row_confidence(claims),
                        authority=",".join(sorted({c.authority for c in claims}))
                        if claims
                        else "-",
                        state=",".join(sorted({c.state for c in claims})) if claims else "-",
                        scope=_summarize({c.scope for c in claims if c.scope}),
                        gate="GATED"
                        if status == "GATED"
                        else (
                            "unexecuted_live_provider"
                            if not live_configured and route in (ROUTE_PROVIDER, ROUTE_HYBRID)
                            else None
                        ),
                        gate_reason=gate_reason
                        if not live_configured and route in (ROUTE_PROVIDER, ROUTE_HYBRID)
                        else None,
                        provider_provenance=provenance,
                        notes=notes,
                    )
                )
        return ParityMatrix(
            title=fixture.title,
            fixture_sha512=dict((f, fixture.sha512(f)) for f in fixture.formats),
            provider_gate=provider_gate,
            rows=rows,
        )

    # -- status decision ------------------------------------------------------

    def _decide_status(
        self,
        walk: str,
        route: str,
        modes: tuple[str, ...],
        det_claims: dict[str, list[TypedClaim]],
        provider_claims: dict[str, list[TypedClaim]],
        hybrid_claims: dict[str, list[TypedClaim]],
        locators: set[str],
    ) -> tuple[list[TypedClaim], list[TypedClaim], str, tuple[str, ...]]:
        """Return ``(claims, fabricated, status, notes)`` for one (walk, route)."""
        if route == ROUTE_DETERMINISTIC:
            claims = det_claims[walk]
            fabricated = _fabricated(claims, locators)
            if not claims:
                return (
                    claims,
                    [],
                    "UNSUPPORTED",
                    ("deterministic path leaves this category ABSENT (honest degradation)",),
                )
            if fabricated:
                return claims, fabricated, "DIFF", (f"{len(fabricated)} unsupported claim(s)",)
            return claims, [], "PASS", ()

        if route == ROUTE_PROVIDER:
            claims = provider_claims[walk]
            fabricated = _fabricated(claims, locators)
            if ROUTE_PROVIDER not in modes and ROUTE_HYBRID not in modes:
                return claims, [], "GATED", ()
            if not claims:
                return (
                    claims,
                    [],
                    "UNSUPPORTED",
                    ("provider produced no observations for this walk",),
                )
            if fabricated:
                return (
                    claims,
                    fabricated,
                    "DIFF",
                    (
                        f"{len(fabricated)} fabricated claim(s) — "
                        "provider invented unsupported spans",
                    ),
                )
            if _contradicts(claims, det_claims[walk]):
                return (
                    claims,
                    [],
                    "DIFF",
                    ("provider contradicts a deterministic finding (not a pure extension)",),
                )
            return (
                claims,
                [],
                "PASS",
                ("evidence-supported extension of the deterministic baseline",),
            )

        # hybrid
        claims = hybrid_claims[walk]
        fabricated = _fabricated(claims, locators)
        det_set = set(det_claims[walk])
        pro_set = set(provider_claims[walk])
        if set(claims) != det_set | pro_set:
            return claims, [], "DIFF", ("hybrid != deterministic U provider (claim set mismatch)",)
        if fabricated:
            return claims, fabricated, "DIFF", (f"{len(fabricated)} unsupported claim(s)",)
        return claims, [], "PASS", ("hybrid == deterministic U provider (no fabrication, no loss)",)


__all__ = [
    "FakeSemanticProvider",
    "Fixture",
    "ParityMatrix",
    "ParityRow",
    "RouteClaims",
    "SemanticParityOracle",
    "TypedClaim",
    "WALKS",
    "WALK_2A",
    "WALK_2B",
    "WALK_2C",
    "WALK_2D",
    "WALK_2E",
    "WALK_2F",
    "book_fixture",
    "extract_walk_claims",
]
