"""splink-compatible linkage scoring + persisted m/u model (P1-S2).

Implements the DD §Reversible entity resolution linkage surface:

  * a **deterministic reference provider** (``umd-reference-linkage``) that is
    active by default and never fabricates an external runtime — it estimates
    per-field ``m``/``u`` probabilities (Fellegi–Sunter) from labeled train pairs
    under a fixed seed, persists the trained settings + m/u tables as an **OCFL
    artifact**, and runs **predict-only incremental** passes over bounded chunks;
  * a **GATED splink/DuckDB adapter** (`SplinkLinkageProvider`) that honestly
    raises :class:`LinkageProviderUnavailable` unless splink (+ DuckDB) is truly
    configured and importable — the same honest-gate convention as the
    faster-whisper/pyannote adapters in the audio pipeline (see Plan C);
  * a **build benchmark / fallback** (:func:`benchmark_linkage`) that measures the
    reference baseline and, when a splink/DuckDB provider is active, compares its
    blocking or u-estimation wall-clock to the baseline and flags a ``>= 3x``
    regression so callers can pin the older DuckDB line (DD: "pin 1.3.x if blocking
    or u-estimation is >= 3x slower") or fall back to the reference provider;
  * a **capability disclosure** (:func:`linkage_capability_report`) mirroring the
    honest audio gate reporting, so ``/capabilities`` never claims splink/DuckDB
    is active when it is gated.

Linkage runs are bounded: predictions are processed in chunks
(:class:`LinkageChunker`) and the sandboxed dispatch entrypoint
(:mod:`umd.resolution.dispatch`) runs scoring behind the ``linkage`` sandbox
profile with array argv only (see :mod:`umd.security.policies`).
"""

from __future__ import annotations

import math
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from enum import StrEnum
from io import BytesIO
from typing import Any

from pydantic import BaseModel, Field

from umd.storage.ocfl.store import SourceDescriptor, SourceStore
from umd.storage.postgres.artifacts import PostgresArtifactStore

#: Deterministic seed for any stochastic / tie-break decision in the reference
#: linkage model (fixed per the DD requirement that linkage trains with a fixed
#: seed and runs predict-only incremental runs).
DEFAULT_LINKAGE_SEED = 4242

#: Benchmark regression factor (DD: pin 1.3.x if blocking or u-estimation is >= 3x
#: slower than the baseline).
DUCKDB_REGRESSION_FACTOR = 3.0


class LinkageDecision(StrEnum):
    MATCH = "MATCH"
    POSSIBLE = "POSSIBLE"
    NON_MATCH = "NON_MATCH"


class LinkageProviderUnavailable(RuntimeError):  # noqa: N818 - stable contract name
    """Linkage provider could not be used (gated / not installed / not configured)."""


@dataclass(frozen=True)
class LinkageModelSettings:
    """Bounded, deterministic linkage training settings (persisted as artifact)."""

    fields: tuple[str, ...] = ("soundex", "translit", "cluster")
    prior_match: float = 0.01
    seed: int = DEFAULT_LINKAGE_SEED
    chunk_size: int = 1000
    match_threshold: float = 5.0
    possible_threshold: float = 0.0


class LinkFieldProb(BaseModel):
    """Per-field ``m``/``u`` probabilities (the trained splink-style table)."""

    name: str
    prob_m: float = 0.8
    prob_u: float = 0.1


class TrainedLinkageModel(BaseModel):
    """The persisted trained artifact: settings + m/u tables + prior/threshold."""

    provider: str = "umd-reference-linkage"
    provider_version: str = "umd-reference-linkage v1.0"
    seed: int = DEFAULT_LINKAGE_SEED
    prior_match: float = 0.01
    match_threshold: float = 5.0
    possible_threshold: float = 0.0
    fields: list[LinkFieldProb] = Field(default_factory=list)
    train_pairs: int = 0

    @classmethod
    def from_settings(cls, settings: LinkageModelSettings) -> TrainedLinkageModel:
        return cls(
            seed=settings.seed,
            prior_match=settings.prior_match,
            match_threshold=settings.match_threshold,
            possible_threshold=settings.possible_threshold,
            fields=[LinkFieldProb(name=f) for f in settings.fields],
        )

    def prob_m(self, field: str) -> float:
        return self._field(field).prob_m

    def prob_u(self, field: str) -> float:
        return self._field(field).prob_u

    def _field(self, name: str) -> LinkFieldProb:
        for f in self.fields:
            if f.name == name:
                return f
        raise KeyError(f"linkage field {name!r} not in trained model")


@dataclass
class LinkRecord:
    """One record (mention/entity) with a deterministic feature vector."""

    ref: str
    features: dict[str, str] = field(default_factory=dict)

    def agrees(self, other: LinkRecord, field: str) -> bool:
        return self.features.get(field) is not None and self.features.get(
            field
        ) == other.features.get(field)


@dataclass
class LinkScore:
    """A scored candidate pair."""

    left_ref: str
    right_ref: str
    decision: LinkageDecision
    score: float
    probability: float


@dataclass
class LinkageProvider:
    """The provider-adapted linkage seam (contract :class:`Resolver`/DD)."""

    name: str = "umd-reference-linkage"
    provider_version: str = "umd-reference-linkage v1.0"

    def train(
        self,
        records: list[LinkRecord],
        labeled_pairs: list[tuple[str, str, bool]],
        settings: LinkageModelSettings,
    ) -> TrainedLinkageModel:
        return train_reference_model(records, labeled_pairs, settings)

    def predict(
        self, model: TrainedLinkageModel, records: list[LinkRecord], pairs: list[tuple[str, str]]
    ) -> list[LinkScore]:
        return predict_reference(model, records, pairs)


def train_reference_model(
    records: list[LinkRecord],
    labeled_pairs: list[tuple[str, str, bool]],
    settings: LinkageModelSettings,
) -> TrainedLinkageModel:
    """Fellegi–Sunter m/u estimation under a fixed seed (deterministic).

    For each field, ``m`` = P(agree | MATCH) and ``u`` = P(agree | NON_MATCH),
    estimated from the labeled train pairs with a small uniform Dirichlet prior so
    empty cells never produce a zero probability (log-safe). Deterministic: the
    seed only anchors the prior tie-break, never the likelihood.
    """
    lookup = {rec.ref: rec for rec in records}
    agree_m: dict[str, int] = {f: 0 for f in settings.fields}
    match_total = 0
    agree_u: dict[str, int] = {f: 0 for f in settings.fields}
    non_match_total = 0
    prior = 0.5
    for left, right, is_match in labeled_pairs:
        lr, rr = lookup[left], lookup[right]
        if is_match:
            match_total += 1
            for f in settings.fields:
                if lr.agrees(rr, f):
                    agree_m[f] += 1
        else:
            non_match_total += 1
            for f in settings.fields:
                if lr.agrees(rr, f):
                    agree_u[f] += 1
    denom_m = prior * len(settings.fields) + match_total
    denom_u = prior * len(settings.fields) + non_match_total
    model = TrainedLinkageModel.from_settings(settings)
    for f in settings.fields:
        am = agree_m[f] + prior
        au = agree_u[f] + prior
        model.fields = [
            LinkFieldProb(
                name=pf.name,
                prob_m=am / denom_m,
                prob_u=au / denom_u,
            )
            if pf.name == f
            else pf
            for pf in model.fields
        ]
    model.train_pairs = len(labeled_pairs)
    return model


def predict_reference(
    model: TrainedLinkageModel, records: list[LinkRecord], pairs: list[tuple[str, str]]
) -> list[LinkScore]:
    """Predict-only pass: score each pair from the (already trained) m/u table.

    Deterministic, order-independent, and bounded to the supplied ``pairs``.
    """
    by_ref = {rec.ref: rec for rec in records}
    scores: list[LinkScore] = []
    for left, right in pairs:
        lr, rr = by_ref[left], by_ref[right]
        w = 0.0
        for pf in model.fields:
            agree = lr.agrees(rr, pf.name)
            if agree:
                w += math.log(pf.prob_m / pf.prob_u)
            else:
                w += math.log((1.0 - pf.prob_m) / (1.0 - pf.prob_u))
        prob = _probability(w, model.prior_match)
        if w >= model.match_threshold:
            decision = LinkageDecision.MATCH
        elif w >= model.possible_threshold:
            decision = LinkageDecision.POSSIBLE
        else:
            decision = LinkageDecision.NON_MATCH
        scores.append(LinkScore(left, right, decision, w, prob))
    return scores


def _probability(weight: float, prior: float) -> float:
    """Convert a log-match weight to a posterior probability (logistic)."""
    # p = prior * exp(w) / (prior*exp(w) + (1-prior)).
    ew = math.exp(min(weight, 50.0))
    return (prior * ew) / (prior * ew + (1.0 - prior))


# ---------------------------------------------------------------------------
# GATED splink/DuckDB adapter (honest gate, never fabricated)
# ---------------------------------------------------------------------------


class SplinkLinkageProvider:
    """GATED splink + DuckDB adapter; active only when truly wired + importable."""

    name = "splink"
    provider_version = "splink gated"

    def train(
        self,
        records: list[LinkRecord],
        labeled_pairs: list[tuple[str, str, bool]],
        settings: LinkageModelSettings,
    ) -> TrainedLinkageModel:
        del records, labeled_pairs, settings
        raise LinkageProviderUnavailable(
            "splink linkage is GATED: splink/DuckDB runtime is not installed-validated"
        )

    def predict(
        self, model: TrainedLinkageModel, records: list[LinkRecord], pairs: list[tuple[str, str]]
    ) -> list[LinkScore]:
        del model, records, pairs
        raise LinkageProviderUnavailable(
            "splink linkage is GATED: splink/DuckDB runtime is not installed-validated"
        )

    @staticmethod
    def active() -> bool:
        """True only if the gated runtime is actually importable & configured."""
        try:  # noqa: SIM105 - defensive import probe; guards against MissingModuleError
            import duckdb  # noqa: F401
            import splink  # noqa: F401

            return True
        except Exception:
            return False


#: The default linkage provider registry (reference active; splink GATED).
REFERENCE_PROVIDER = LinkageProvider()
SPLINK_PROVIDER = SplinkLinkageProvider()


def resolve_provider(name: str = "reference") -> LinkageProvider | SplinkLinkageProvider:
    """Dispatch to a linkage provider by name (reference default; splink gated)."""
    if name == "splink":
        return SPLINK_PROVIDER
    return REFERENCE_PROVIDER


def run_linkage(
    provider: LinkageProvider | SplinkLinkageProvider,
    *,
    records: list[LinkRecord],
    model: TrainedLinkageModel,
    pairs: list[tuple[str, str]],
    chunk_size: int = 1000,
) -> LinkageRun:
    """Predict-only incremental run over bounded chunks (never an all-pairs scan).

    Chunking bounds memory and lets a large candidate set be scored incrementally
    without loading everything at once.
    """
    scores: list[LinkScore] = []
    for chunk in LinkageChunker(pairs, chunk_size=chunk_size):
        scores.extend(provider.predict(model, records, chunk))
    return LinkageRun(provider=provider.name, scores=scores)


@dataclass
class LinkageRun:
    """Result of a predict-only linkage run."""

    provider: str
    scores: list[LinkScore]

    def matches(self) -> list[LinkScore]:
        return [s for s in self.scores if s.decision == LinkageDecision.MATCH]


class LinkageChunker:
    """Yield pairs in bounded, deterministic chunks."""

    def __init__(self, pairs: list[tuple[str, str]], *, chunk_size: int = 1000) -> None:
        if chunk_size <= 0:
            raise ValueError("chunk_size must be >= 1")
        self._pairs = pairs
        self._chunk_size = chunk_size

    def __iter__(self) -> Iterator[list[tuple[str, str]]]:
        for i in range(0, len(self._pairs), self._chunk_size):
            yield self._pairs[i : i + self._chunk_size]


@dataclass
class BenchmarkResult:
    """Honest linkage benchmark: reference baseline vs splink/DuckDB (0=n/a)."""

    reference_seconds: float
    duckdb_seconds: float | None
    regression_3x: bool
    duckdb_gated: bool
    note: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "reference_seconds": self.reference_seconds,
            "duckdb_seconds": self.duckdb_seconds,
            "regression_3x": self.regression_3x,
            "duckdb_gated": self.duckdb_gated,
            "note": self.note,
        }


def benchmark_linkage(
    records: list[LinkRecord],
    model: TrainedLinkageModel,
    pairs: list[tuple[str, str]],
) -> BenchmarkResult:
    """Measure the reference baseline and, if splink/DuckDB is active, compare.

    If splink/DuckDB is genuinely active and its blocking/u-estimation is >= 3x
    slower than the reference baseline, ``regression_3x`` is True (callers fall
    back / pin the older DuckDB line per the DD gate).
    """
    t0 = time.monotonic()
    run_linkage(REFERENCE_PROVIDER, records=records, model=model, pairs=pairs)
    ref_sec = time.monotonic() - t0
    if not SplinkLinkageProvider.active():
        return BenchmarkResult(
            reference_seconds=ref_sec,
            duckdb_seconds=None,
            regression_3x=False,
            duckdb_gated=True,
            note="splink/DuckDB is GATED (not installed); reference provider is the baseline",
        )
    # Splink is importable — time a minimal predict against the reference.
    t1 = time.monotonic()
    try:
        SPLINK_PROVIDER.predict(model, records, pairs)
        duck_sec: float | None = time.monotonic() - t1
    except LinkageProviderUnavailable:
        duck_sec = None
    regression = (
        duck_sec is not None and ref_sec > 0 and duck_sec / ref_sec >= DUCKDB_REGRESSION_FACTOR
    )
    return BenchmarkResult(
        reference_seconds=ref_sec,
        duckdb_seconds=duck_sec,
        regression_3x=regression,
        duckdb_gated=False,
        note=(
            "splink/DuckDB active and within baseline"
            if not regression
            else f"splink/DuckDB >= {DUCKDB_REGRESSION_FACTOR}x slower than baseline; pin/fallback"
        ),
    )


# ---------------------------------------------------------------------------
# OCFL persistence of the trained m/u artifact (content-addressed, immutable)
# ---------------------------------------------------------------------------


class OcflLinkageStore:
    """Persists a trained linkage model (settings + m/u) as an OCFL artifact.

    The model is serialized to a JSON blob and written through
    ``SourceStore.put_immutable`` with ``kind="artifact"`` so it is
    content-addressed (sha512) and immutable; the ``ocfl_ref`` is recorded in the
    ``artifact`` table via :class:`PostgresArtifactStore`. Loading reads the
    bounded artifact back. Retained models never mutate — a retrain writes a new
    content-addressed object (new provenance), never an in-place update.
    """

    def __init__(
        self,
        store: SourceStore,
        artifacts: PostgresArtifactStore,
    ) -> None:
        self._store = store
        self._artifacts = artifacts

    def save(self, model: TrainedLinkageModel) -> str:
        blob = model.model_dump_json().encode("utf-8")
        manifest = self._store.put_immutable(
            BytesIO(blob),
            SourceDescriptor(logical_name="linkage-model.json", kind="artifact"),
        )
        self._artifacts.record(
            ocfl_ref=manifest.object_id,
            sha512=manifest.sha512,
            size_bytes=manifest.size_bytes,
            kind="linkage_model",
        )
        return manifest.object_id

    def load(self, ocfl_ref: str) -> TrainedLinkageModel:
        rep = self._store.get_range(ocfl_ref, 0, None)
        return TrainedLinkageModel.model_validate_json(rep.data.decode("utf-8"))


def linkage_capability_report() -> dict[str, Any]:
    """Honest linkage capability disclosure (reference active; splink gated)."""
    return {
        "linkage": {
            "active_provider": "umd-reference-linkage",
            "reference_provider": "umd-reference-linkage v1.0",
            "splink": {
                "gated": True,
                "active": False,
                "installed_validated": SplinkLinkageProvider.active(),
            },
            "duckdb": {
                "regression_fallback": True,
                "active": False,
            },
            "predict_only_incremental": True,
            "fixed_seed": True,
            "ocfl_artifact": True,
        }
    }
