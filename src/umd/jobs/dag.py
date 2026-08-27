"""Single in-repository stage lineage / DAG (Phase B, P1-S1).

This module is the **single lineage source** for the whole decomposition graph.
It is deliberately scheduler-agnostic: it defines *what* the stages are, their
dependency edges, the evidence class that flows along each edge, and the
per-modality branch metadata — it performs no execution. Both the durable runner
(``stage_execution.py`` / ``runner.py``) and the selective invalidator
(``invalidation.py``) consume this definition. There is no Dagster and no second
scheduler anywhere in v1; Hatchet (behind the runner seam) is the only runner.

The v1 DAG (from the DD, "Durable stage execution"):

    INGEST -> FORMAT_ANALYSIS -> BASIC_SEGMENTATION -> LOW_LEVEL_EXTRACTION
            -> STRUCTURAL_ANALYSIS -> ENTITY_RESOLUTION -> CROSS_SOURCE_ALIGNMENT
            -> SEMANTIC_RECONCILIATION -> CURRENT/SEARCH PROJECTION

Individual stages are independently rerunnable; changing one stage invalidates
only dependent descendants (via :class:`InvalidationPlanner`), never the whole
ingestion graph.
"""

from __future__ import annotations

from dataclasses import dataclass, field

#: Canonical stage order, topologically sorted (a stage never depends on one that
#: appears later in this tuple). ``CURRENT_SEARCH_PROJECTION`` is the terminal
#: dependency of every pipeline (projection builders are the only writers to
#: their projection stores; this stage schedules them, never writes directly).
STAGE_ORDER: tuple[str, ...] = (
    "INGEST",
    "FORMAT_ANALYSIS",
    "BASIC_SEGMENTATION",
    "LOW_LEVEL_EXTRACTION",
    "STRUCTURAL_ANALYSIS",
    "ENTITY_RESOLUTION",
    "CROSS_SOURCE_ALIGNMENT",
    "SEMANTIC_RECONCILIATION",
    "CURRENT_SEARCH_PROJECTION",
)

#: Evidence classes allowed on a dependency edge. These are the typed categories
#: of downstream input that a dependent stage consumes; a rerun keyed on an
#: upstream evidence class re-schedules only the edges that carry it.
EVIDENCE_CLASSES: tuple[str, ...] = (
    "source_bytes",  # immutable raw input (OCFL ref + fixity)
    "format_analysis",  # mime/format/capability/dispatch decisions
    "segments",  # deterministic segment refs + versioned locators
    "evidence_records",  # direct extraction evidence (OCR/ASR/metadata/...)
    "structural_assertions",  # structural findings: dialogue/narration/temporal/...
    "resolved_entities",  # entity resolution / candidate / canonical maps
    "alignments",  # many-to-many cross-source correspondence
    "reconciled_state",  # reconciled semantic state consumed by projections
)

#: ``stage -> [(dependency, evidence_class), ...]``. A dependency is expressed as
#: the *upstream* stage whose evidence feeds this stage. The terminal projection
#: stage consumes ``reconciled_state`` from ``SEMANTIC_RECONCILIATION``.
STAGE_DEPENDENCIES: dict[str, tuple[tuple[str, str], ...]] = {
    "INGEST": (),
    "FORMAT_ANALYSIS": (("INGEST", "source_bytes"),),
    "BASIC_SEGMENTATION": (("FORMAT_ANALYSIS", "format_analysis"),),
    "LOW_LEVEL_EXTRACTION": (("BASIC_SEGMENTATION", "segments"),),
    "STRUCTURAL_ANALYSIS": (("LOW_LEVEL_EXTRACTION", "evidence_records"),),
    "ENTITY_RESOLUTION": (
        ("STRUCTURAL_ANALYSIS", "structural_assertions"),
        ("LOW_LEVEL_EXTRACTION", "evidence_records"),
    ),
    "CROSS_SOURCE_ALIGNMENT": (
        ("ENTITY_RESOLUTION", "resolved_entities"),
        ("STRUCTURAL_ANALYSIS", "structural_assertions"),
    ),
    "SEMANTIC_RECONCILIATION": (
        ("ENTITY_RESOLUTION", "resolved_entities"),
        ("CROSS_SOURCE_ALIGNMENT", "alignments"),
    ),
    "CURRENT_SEARCH_PROJECTION": (("SEMANTIC_RECONCILIATION", "reconciled_state"),),
}


def stage_dependency() -> list[dict[str, str]]:
    """Return the ``stage_dependency(stage, depends_on_stage, evidence_class)`` rows.

    Matches the CONTRACTS.md lineage vocabulary: each edge names the dependent
    ``stage``, its ``depends_on_stage``, and the ``evidence_class`` that flows
    across the edge. Consumed by the runner and bounded invalidation planners.
    """
    rows: list[dict[str, str]] = []
    for stage, deps in STAGE_DEPENDENCIES.items():
        for depends_on, evidence_class in deps:
            rows.append(
                {
                    "stage": stage,
                    "depends_on_stage": depends_on,
                    "evidence_class": evidence_class,
                }
            )
    return rows


def build_dependents() -> dict[str, list[str]]:
    """``stage -> [direct dependents]`` — the lineage shape for the planner.

    This is the authoritative ``lineage`` argument to
    :meth:`InvalidationPlanner.plan`, replacing any ad-hoc test constants so the
    planner and the runner always reason about the SAME single lineage source.
    """
    dependents: dict[str, list[str]] = {stage: [] for stage in STAGE_ORDER}
    for stage, deps in STAGE_DEPENDENCIES.items():
        for depends_on, _class in deps:
            if stage not in dependents[depends_on]:
                dependents[depends_on].append(stage)
    return dependents


#: ``stage -> [direct dependents]``, precomputed from the single source of truth.
STAGE_DEPENDENTS: dict[str, list[str]] = build_dependents()


@dataclass(frozen=True)
class ModalityBranch:
    """Per-modality branch metadata for the fan-out stages.

    ``BASIC_SEGMENTATION`` and ``LOW_LEVEL_EXTRACTION`` are the fan-out points in
    the DD ("independent branches fan out by segment and modality"): each
    supported v1 modality decomposes through its own deterministic segmenter and
    extraction sub-paths, yet all rejoin at ``STRUCTURAL_ANALYSIS``. This metadata
    is descriptive (a manifest/universal attribute) — it does not add scheduler
    branches or a second scheduler.
    """

    modality: str
    #: The source/media kind that selects this branch.
    source_kind: str
    #: Segment types this modality emits (deterministic id components).
    segment_types: tuple[str, ...]
    #: Extraction sub-paths under LOW_LEVEL_EXTRACTION (evidence kinds emitted).
    extractions: tuple[str, ...]
    #: Map of fan-out stage name -> its upstream dependency within the branch.
    branch_fanout: dict[str, str] = field(default_factory=dict)


MODALITY_BRANCHES: dict[str, ModalityBranch] = {
    "text": ModalityBranch(
        modality="text",
        source_kind="text",
        segment_types=("document", "chapter", "section", "paragraph", "sentence", "token"),
        extractions=("metadata", "text_span", "ocr_region"),
        branch_fanout={
            "BASIC_SEGMENTATION": "FORMAT_ANALYSIS",
            "LOW_LEVEL_EXTRACTION": "BASIC_SEGMENTATION",
        },
    ),
    "image": ModalityBranch(
        modality="image",
        source_kind="image",
        segment_types=("page", "region", "panel", "speech_bubble", "caption"),
        extractions=("metadata", "ocr_region", "object_observation", "face_observation"),
        branch_fanout={
            "BASIC_SEGMENTATION": "FORMAT_ANALYSIS",
            "LOW_LEVEL_EXTRACTION": "BASIC_SEGMENTATION",
        },
    ),
    "audio": ModalityBranch(
        modality="audio",
        source_kind="audio",
        segment_types=("region", "utterance", "music", "sound_event"),
        extractions=("metadata", "audio_interval", "music", "sound_event"),
        branch_fanout={"LOW_LEVEL_EXTRACTION": "BASIC_SEGMENTATION"},
    ),
    "video": ModalityBranch(
        modality="video",
        source_kind="video",
        segment_types=("scene", "shot", "frame", "region", "track"),
        extractions=("metadata", "frame", "audio_interval", "visual_relationship"),
        branch_fanout={"LOW_LEVEL_EXTRACTION": "BASIC_SEGMENTATION"},
    ),
    "subtitle": ModalityBranch(
        modality="subtitle",
        source_kind="subtitle",
        segment_types=("track", "subtitle_event"),
        extractions=("metadata", "text_span"),
        branch_fanout={"LOW_LEVEL_EXTRACTION": "BASIC_SEGMENTATION"},
    ),
}


@dataclass(frozen=True)
class StageDef:
    """A single stage in the canonical lineage."""

    name: str
    description: str
    #: Stages this stage directly depends on (upstream names).
    dependencies: tuple[str, ...]
    #: Evidence classes this stage consumes (from its dependency edges).
    consumes: tuple[str, ...]


def stages() -> list[StageDef]:
    """Typed description of every stage in topological order."""
    out: list[StageDef] = []
    for name in STAGE_ORDER:
        deps = STAGE_DEPENDENCIES[name]
        out.append(
            StageDef(
                name=name,
                description=_DESCRIPTION[name],
                dependencies=tuple(d for d, _c in deps),
                consumes=tuple(c for _d, c in deps),
            )
        )
    return out


_DESCRIPTION: dict[str, str] = {
    "INGEST": "Immutable source bytes to OCFL; source/work membership; SourceIngested event.",
    "FORMAT_ANALYSIS": "Format/mime/capability dispatch; routes to per-modality branches.",
    "BASIC_SEGMENTATION": "Deterministic segments + versioned locators per modality.",
    "LOW_LEVEL_EXTRACTION": "Direct extraction evidence (OCR/ASR/metadata/regions/objects).",
    "STRUCTURAL_ANALYSIS": "Structural findings: dialogue/narration, entities, temporal, env.",
    "ENTITY_RESOLUTION": "Reversible entity resolution; candidate/canonical maps.",
    "CROSS_SOURCE_ALIGNMENT": "Many-to-many cross-source/edition/continuity alignment.",
    "SEMANTIC_RECONCILIATION": "Reconcile semantic assertions; precedence/locks/contradictions.",
    "CURRENT_SEARCH_PROJECTION": (
        "Schedule disposable Tier-0/Tier-1 projection builders (replay-only)."
    ),
}

__all__ = [
    "STAGE_ORDER",
    "EVIDENCE_CLASSES",
    "STAGE_DEPENDENCIES",
    "STAGE_DEPENDENTS",
    "MODALITY_BRANCHES",
    "ModalityBranch",
    "StageDef",
    "stage_dependency",
    "build_dependents",
    "stages",
]
