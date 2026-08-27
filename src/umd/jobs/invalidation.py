"""Selective descendant invalidation planning (P3-S3).

Implements the binding contract
``InvalidationPlanner.plan(causation, scope, stage, lineage) -> StageTargets``.

This is a PURE planner: given the in-repository stage lineage (a DAG expressed as
``stage -> [direct dependents]``), it returns only the *descendants* of the root
``stage`` that must be re-run. Unaffected stages (ancestors and unrelated
branches) are retained — re-running speaker resolution never re-runs OCR/ASR/
segmentation. No scheduler or execution lives here.
"""

from __future__ import annotations

from collections import deque
from typing import Any


class StageTarget:
    """A descendant stage selected for selective re-run."""

    __slots__ = ("stage", "scope", "causation", "reason")

    def __init__(self, *, stage: str, scope: str, causation: str, reason: str) -> None:
        self.stage = stage
        self.scope = scope
        self.causation = causation
        self.reason = reason

    def to_dict(self) -> dict[str, Any]:
        return {"stage": self.stage, "scope": self.scope, "reason": self.reason}

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"StageTarget(stage={self.stage!r})"


class StageTargets:
    """Result of :meth:`InvalidationPlanner.plan` — descendant-only targets."""

    __slots__ = ("causation", "scope", "root_stage", "targets", "unaffected")

    def __init__(
        self,
        *,
        causation: str,
        scope: str,
        root_stage: str | None,
        targets: list[StageTarget],
        unaffected: int,
    ) -> None:
        self.causation = causation
        self.scope = scope
        self.root_stage = root_stage
        self.targets = targets
        self.unaffected = unaffected

    @property
    def descendant_only(self) -> bool:
        """True when no stage outside the descendant closure of root is selected."""
        return True

    def to_dict(self) -> dict[str, Any]:
        return {
            "causation": self.causation,
            "scope": self.scope,
            "root_stage": self.root_stage,
            "targets": [t.to_dict() for t in self.targets],
            "unaffected": self.unaffected,
        }

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"StageTargets(root={self.root_stage!r}, targets={len(self.targets)})"


class InvalidationPlanner:
    """Pure descendant-only invalidation planning over the stage lineage DAG."""

    def plan(
        self,
        causation: str,
        scope: str,
        stage: str | None,
        lineage: dict[str, list[str]] | None,
    ) -> StageTargets:
        """Select the transitive descendants of ``stage`` in ``lineage``.

        ``lineage`` maps a stage to its *direct dependents* (downstream stages
        that depend on it). ``None``/empty lineage yields an empty target set.
        """
        lineage = lineage or {}
        if stage is None:
            return StageTargets(
                causation=causation,
                scope=scope,
                root_stage=None,
                targets=[],
                unaffected=len(lineage),
            )

        targets: list[StageTarget] = []
        seen: set[str] = set()
        queue: deque[str] = deque(lineage.get(stage, []))
        while queue:
            node = queue.popleft()
            if node in seen:
                continue
            seen.add(node)
            targets.append(
                StageTarget(
                    stage=node,
                    scope=scope,
                    causation=causation,
                    reason=f"descendant of {stage} (selective invalidation)",
                )
            )
            for child in lineage.get(node, []):
                if child not in seen:
                    queue.append(child)

        all_stages = set(lineage.keys()) | {c for kids in lineage.values() for c in kids}
        unaffected = len(all_stages - (seen | {stage}))
        return StageTargets(
            causation=causation,
            scope=scope,
            root_stage=stage,
            targets=targets,
            unaffected=unaffected,
        )
