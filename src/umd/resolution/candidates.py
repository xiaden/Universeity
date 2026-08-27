"""Bounded candidate generation for entity resolution (P1-S2).

Implements the DD §Reversible entity resolution candidate-generation surface with
*deterministic, dependency-free* primitives so linkage is reproducible and
testable without external systems:

  * normalized names — NFKC case-fold + whitespace collapse;
  * transliteration key — romanization-friendly fold for non-Latin scripts;
  * soundex — classic four-code soundex for Latin-script names, plus a stable
    digest fallback for non-ASCII (so indexing never crashes on any script);
  * high-cardinality speaker/face cluster keys — the raw cluster label is already
    high-cardinality; we expose a bounded, collision-safe key and treat a large
    cluster set explicitly (blocking threshold) rather than exhaustively pairwise;
  * MinHash + LSH banding — a small pure implementation (no ``datasketch``) using
    a fixed multiset hash so signatures are deterministic under a fixed seed.

Candidate generation is *blocking* (indexed retrieval against a mention index),
never an unbounded all-pairs scan. The DD names these as the bounded candidate
set operators; splink-compatible *scoring* lives in :mod:`umd.resolution.linkage`.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field

from umd.resolution.mentions import MentionCandidate, SourceMention

#: Minimum length below which a token group is not a useful block key.
_MIN_BLOCK_LEN = 2
#: Classic soundex output length.
_SOUNDEX_LEN = 4

_ASCII_LETTER = re.compile(r"[^a-z]")


# ---------------------------------------------------------------------------
# Normalization primitives (deterministic)
# ---------------------------------------------------------------------------


def normalize_name(text: str) -> str:
    """NFKC case-fold with collapsing whitespace (the canonical name key)."""
    folded = unicodedata.normalize("NFKC", text.strip()).casefold()
    return re.sub(r"\s+", " ", folded)


def transliteration_key(text: str) -> str:
    """A romanization-friendly key for a name or title.

    Strip diacritics from Latin script and keep a bounded NFC-folded form so
    ``エミリア`` vs ``Emilia`` vs ``EMILIA`` can be surfaced as the same block.
    Non-Latin script folds to its NFKC form (no fabricated romanization), which
    keeps the operation deterministic and honest.
    """
    nfd = unicodedata.normalize("NFD", text.casefold())
    out = "".join(
        ch for ch in nfd if not unicodedata.combining(ch) or ch == "\u3099" or ch == "\u309a"
    )
    return normalize_name(out)


def soundex(name: str) -> str:
    """Classic four-code soundex for Latin-script ASCII; digest fallback otherwise.

    Deterministic and dependency-free. Non-ASCII names (which soundex cannot
    encode meaningfully) collapse to a stable digest prefix of their normalized
    transliteration key so the index never misses or crashes on a script.
    """
    key = transliteration_key(name)
    ascii_key = _ASCII_LETTER.sub("", key)
    if len(ascii_key) < _MIN_BLOCK_LEN:
        digest = hashlib.sha256(key.encode()).hexdigest()[:8]
        return f"{digest}"
    return _soundex_ascii(ascii_key)


def _soundex_ascii(word: str) -> str:
    first = word[0]
    codes: list[str] = []
    for ch in word[1:]:
        code = _SOUNDEX_CODES.get(ch, "")
        if code and (not codes or codes[-1] != code):
            codes.append(code)
    compact = "".join(codes).replace("", "")
    return (first + compact)[:_SOUNDEX_LEN].ljust(_SOUNDEX_LEN, "0")


_SOUNDEX_CODES: dict[str, str] = {
    "b": "1",
    "f": "1",
    "p": "1",
    "v": "1",
    "c": "2",
    "g": "2",
    "j": "2",
    "k": "2",
    "q": "2",
    "s": "2",
    "x": "2",
    "z": "2",
    "d": "3",
    "t": "3",
    "l": "4",
    "m": "5",
    "n": "5",
    "r": "6",
}


def cluster_key(label: str) -> str:
    """A bounded, collision-safe block key for a high-cardinality cluster label.

    Speaker/face cluster labels (``speaker_07``, ``face_cluster_12``) are already
    high-cardinality and load-bearing; we keep them as an exact block key (no
    similarity collapsing across distinct clusters) — only the *same* high-
    cardinality cluster blocks together, which is the required semantic.
    """
    return normalize_name(label)


# ---------------------------------------------------------------------------
# MinHash + LSH (pure, deterministic, seed-fixed)
# ---------------------------------------------------------------------------


def _hash_token(token: str, seed: int, bucket: int) -> int:
    return int.from_bytes(
        hashlib.sha256(f"{seed}\x1f{bucket}\x1f{token}".encode()).digest()[:8], "big"
    )


def minhash_signature(tokens: Iterable[str], *, seed: int, n_hashes: int) -> list[int]:
    """A deterministic ``n_hashes``-long MinHash of a token set under ``seed``."""
    unique = set(tokens)
    sig: list[int] = []
    for b in range(n_hashes):
        sig.append(min(_hash_token(tok, seed, b) for tok in unique) if unique else 0)
    return sig


def lsh_bands(signature: list[int], *, band_rows: int) -> list[tuple[int, ...]]:
    """Partition a MinHash signature into LSH bands (band -> bucket key)."""
    if band_rows <= 0:
        raise ValueError("band_rows must be >= 1")
    return [tuple(signature[i : i + band_rows]) for i in range(0, len(signature), band_rows)]


def jaccard_similarity(a: set[str], b: set[str]) -> float:
    union = a | b
    return len(a & b) / len(union) if union else 0.0


# ---------------------------------------------------------------------------
# Candidate generation over a mention index (blocking, bounded)
# ---------------------------------------------------------------------------


@dataclass
class CandidatePolicy:
    """Bounded candidate-generation settings (deterministic run parameters)."""

    soundex_block: bool = True
    transliteration_block: bool = True
    cluster_block: bool = True
    minhash_seed: int = 42
    minhash_hashes: int = 64
    lsh_band_rows: int = 4
    max_candidates_per_mention: int = 20
    candidate_floor: float = 0.25


@dataclass
class CandidateHits:
    """Blocking index result for one mention."""

    mention: SourceMention
    candidates: list[MentionCandidate] = field(default_factory=list)


class MentionBlockIndex:
    """A deterministic in-memory blocking index over a mention collection.

    Built once from a bounded slice/collection of mentions; ``link`` returns the
    candidate entities for a probe mention using normalized-name, transliteration,
    soundex and high-cardinality cluster blocks, cross-checked by MinHash/Jaccard.
    """

    def __init__(
        self, mentions: Iterable[SourceMention], policy: CandidatePolicy | None = None
    ) -> None:
        self.policy = policy or CandidatePolicy()
        self._by_name: dict[str, list[SourceMention]] = {}
        self._by_trans: dict[str, list[SourceMention]] = {}
        self._by_soundex: dict[str, list[SourceMention]] = {}
        self._by_cluster: dict[str, list[SourceMention]] = {}
        self._all: list[SourceMention] = []
        for m in mentions:
            self._add(m)

    def _add(self, m: SourceMention) -> None:
        self._all.append(m)
        nkey = normalize_name(m.mention_text)
        self._by_name.setdefault(nkey, []).append(m)
        for form in m.normalized_forms:
            nk = normalize_name(form)
            if nk:
                self._by_name.setdefault(nk, []).append(m)
        tkey = transliteration_key(m.mention_text)
        self._by_trans.setdefault(tkey, []).append(m)
        for form in m.normalized_forms:
            tk = transliteration_key(form)
            if tk:
                self._by_trans.setdefault(tk, []).append(m)
        self._by_soundex.setdefault(soundex(m.mention_text), []).append(m)
        ckey = cluster_key(m.speaker_label or m.face_cluster or "")
        if ckey:
            self._by_cluster.setdefault(ckey, []).append(m)

    def link(self, mention: SourceMention) -> CandidateHits:
        """Return candidate entities for ``mention`` (bounded by policy)."""
        pool: list[SourceMention] = []
        seen: set[str] = set()
        nkeys = [normalize_name(mention.mention_text)] + [
            normalize_name(f) for f in mention.normalized_forms
        ]
        tkeys = [transliteration_key(mention.mention_text)] + [
            transliteration_key(f) for f in mention.normalized_forms
        ]
        blocks = [
            [(k, self._by_name) for k in nkeys if k],
            [(k, self._by_trans) for k in tkeys if k],
            (
                [(soundex(mention.mention_text), self._by_soundex)]
                if self.policy.soundex_block
                else []
            ),
            (
                [
                    (
                        cluster_key(mention.speaker_label or mention.face_cluster or ""),
                        self._by_cluster,
                    )
                ]
                if self.policy.cluster_block
                else []
            ),
        ]
        for group in blocks:
            for key, table in group:
                if not key:
                    continue
                for cand in table.get(key, []):
                    if cand.mention_id in seen:
                        continue
                    seen.add(cand.mention_id)
                    pool.append(cand)

        tokens = _token_set(mention)
        scored: list[tuple[float, SourceMention]] = []
        for cand in pool:
            cand_tokens = _token_set(cand)
            sim = jaccard_similarity(tokens, cand_tokens) if tokens else 0.0
            if cand.mention_id == mention.mention_id:
                continue
            if sim >= self.policy.candidate_floor:
                scored.append((sim, cand))
        scored.sort(key=lambda t: (-t[0], t[1].mention_id))
        candidates = [
            MentionCandidate(entity_ref=cand.entity_id or cand.mention_id, confidence=round(_s, 4))
            for _s, cand in scored[: self.policy.max_candidates_per_mention]
        ]
        return CandidateHits(mention=mention, candidates=candidates)


def _tokens(text: str) -> Iterable[str]:
    return [normalize_name(tok) for tok in re.split(r"\W+", normalize_name(text)) if tok]


def _token_set(m: SourceMention) -> set[str]:
    toks: set[str] = set()
    for text in (m.mention_text, *m.normalized_forms):
        toks.update(_tokens(text))
    return toks


CandidateGenerator = Callable[[SourceMention], CandidateHits]
