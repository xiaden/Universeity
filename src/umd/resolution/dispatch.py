"""Sandboxed predict-only linkage dispatch entrypoint (P1-S2).

The single entrypoint allowlisted behind the ``linkage`` sandbox profile
(see :mod:`umd.security.policies`). It runs a *predict-only* linkage pass over a
staged JSON input (records + candidate pairs + trained model) in bounded chunks
and writes a JSON result to **stdout** (the sandbox convention: the trailing
argv path is the single staged input, and results are captured on stdout so the
policy check always sees exactly one spool-contained input — mirroring the
subtitle/video runners). Invoked with **array argv only** — ``python -m
umd.resolution.dispatch <in_json>`` — never a shell string, so paths and content
can never be interpolated. Args are bounded by the runner's ``max_args`` limit.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, cast

from umd.resolution.linkage import (
    LinkageProvider,
    LinkRecord,
    TrainedLinkageModel,
    run_linkage,
)


def _load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as fh:
        return cast("dict[str, Any]", json.load(fh))


def run_from_args(argv: list[str]) -> dict[str, Any]:
    """Run a bounded predict-only linkage pass; returns the JSON result dict."""
    if len(argv) != 1:
        raise ValueError("usage: dispatch <in_json>")
    payload = _load(Path(argv[0]))
    records = [
        LinkRecord(ref=r["ref"], features=dict(r.get("features") or {}))
        for r in payload.get("records", [])
    ]
    pairs: list[tuple[str, str]] = [tuple(p) for p in payload.get("pairs", [])]
    model = TrainedLinkageModel.model_validate(payload.get("model", {}))
    run = run_linkage(
        LinkageProvider(),
        records=records,
        model=model,
        pairs=pairs,
        chunk_size=int(payload.get("chunk_size", 1000)),
    )
    return {
        "scores": [
            {
                "left_ref": s.left_ref,
                "right_ref": s.right_ref,
                "decision": s.decision.value,
                "score": s.score,
                "probability": s.probability,
            }
            for s in run.scores
        ]
    }


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:]) if argv is None else argv
    try:
        result = run_from_args(argv)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    sys.stdout.write(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
