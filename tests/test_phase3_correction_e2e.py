"""Phase F / P3-S1..S3: mandatory correction -> invalidation -> selective-rerun E2E.

This is the plan's mandatory end-to-end scenario, driven through the REAL service
layers (no fakes, live Postgres + OCFL):

  * P3-S1 — ingest SEVERAL related heterogeneous sources under one work
    (translated book, adapted book, multi-speaker audio, independent subtitle,
    raster/comic page, and a dialogue video with an independent embedded subtitle
    track when FFmpeg is present); decompose each independently (distinct
    deterministic segments never conflationally merged); align cross-source
    (translation/adaptation correspondence); resolve shared multilingual /
    adaptation entities (alias + merge of "Lapin Blanc" onto the canonical
    "White Rabbit"); reconcile SPEAKS utterances into the semantic ledger; produce
    a semantic graph-like answer (``QuestionService`` compiler -> typed
    relational ops) that returns supporting source references, and retain every
    distinct realization.
  * P3-S2 — apply a user entity correction/override (the corrected spoken
    utterance + corrected canonical identity) carrying audit + invalidation
    causation; prove unaffected OCR/ASR/segment IDs AND their checksums remain
    byte-stable; assert the pure offset InvalidationPlanner schedules ONLY the
    affected resolution/presence/alignment/reconciliation/projection descendants.
  * P3-S3 — selective rerun (descendant-only) + wipe-and-replay Tier-1 rebuild;
    assert the corrected answer and confidence are reflected in BOTH atomic
    Tier-0 and replay-built Tier-1 reads with cross-tier checksum equivalence;
    assert a token-bearing read never serves the stale pre-correction answer, and
    that the two consistency failure classes (transient-lag vs rebuild-in-progress)
    are handled distinctly.

The semantic authority invariant holds throughout: every mutation goes through
the append-only SemanticLedger (Tier-0 updated atomically with the event append);
projections are disposable (only builders write the Tier-1 stores); the corrected
Tier-0 answer is never stale.
"""

from __future__ import annotations

import array
import hashlib
import io
import shutil
import uuid
import wave
from types import SimpleNamespace
from typing import Any

import pytest
import sqlalchemy as sa

from fixtures import (
    adapted_markdown_bytes,
    dialogue_video_bytes,
    multi_speaker_audio_wav_bytes,
    raster_comic_bytes,
    subtitle_bytes,
    translated_txt_bytes,
)
from resolution_helpers import insert_alignment
from umd.api.consistency import ConsistencyGuard, ProjectionFreshness
from umd.api.errors import ConsistencyLagError
from umd.application.commands import SemanticCommandService
from umd.audio.config import config_digest_of
from umd.audio.evidence import build_audio_evidence_plan
from umd.audio.pipeline import run_audio_baseline
from umd.audio.types import AudioConfig, AudioMeta, DecodedAudio
from umd.audit.service import AuditService
from umd.config import AuthSettings, ConsistencySettings, RateLimitSettings, Settings
from umd.domain.evidence import EvidenceBatch
from umd.jobs.dag import STAGE_DEPENDENTS
from umd.jobs.invalidation import InvalidationPlanner
from umd.projections.base import ReplayDriver
from umd.projections.checkpoint import ProjectionCheckpoint, ProjectionCheckpointStore
from umd.projections.current import CurrentTierOneBuilder, tier0_checksum
from umd.projections.query import QueryService
from umd.projections.question import QuestionService
from umd.projections.search import SearchService
from umd.raster.pipeline import process_raster
from umd.segmentation.registry import SegmentRegistry
from umd.storage.ocfl import SourceDescriptor
from umd.storage.postgres.artifacts import PostgresArtifactStore
from umd.storage.postgres.ledger import SemanticLedger
from umd.storage.postgres.reducer import USER_OVERRIDE
from umd.storage.postgres.repositories import (
    PostgresEvidenceRepository,
    PostgresSegmentStore,
    SourceMembershipService,
)

pytestmark = pytest.mark.postgres

SR = 16000
_FFMPEG = shutil.which("ffmpeg") is not None

_ASR_KINDS = ("audio_interval", "text_span", "metadata")
_OCR_KINDS = ("ocr_region",)
_LOW_LEVEL = tuple(sorted(set(_ASR_KINDS) | set(_OCR_KINDS)))


def _wid() -> str:
    return uuid.uuid4().hex


def _ensure_source(
    memberships: Any, store: Any, name: str, data: bytes, kind: str, work_id: str
) -> tuple[str, Any]:
    man = store.put_immutable(io.BytesIO(data), SourceDescriptor(logical_name=name))
    sid = _wid()
    memberships.ensure_source(
        source_id=sid,
        ocfl_ref=man.object_id,
        sha512=man.sha512,
        size_bytes=man.size_bytes,
        media_kind=kind,
        original_name=name,
        work_id=work_id,
    )
    return sid, man


def _wav_decoded(wav_bytes: bytes) -> DecodedAudio:
    with wave.open(io.BytesIO(wav_bytes), "rb") as w:
        frames = w.readframes(w.getnframes())
    samples = [x / 32768.0 for x in array.array("h", frames)]
    dur = len(samples) / SR
    return DecodedAudio(
        sample_rate=SR,
        pcm=samples,
        duration_s=dur,
        meta=AudioMeta(
            format_name="pcm_s16le",
            codec_name="pcm_s16le",
            sample_rate=SR,
            channels=1,
            duration_s=dur,
        ),
    )


def _segment_checksum(engine: sa.Engine) -> tuple[str, int]:
    with engine.connect() as c:
        rows = c.execute(
            sa.text(
                "SELECT id, source_id, segment_type, deterministic_key, ordinal "
                "FROM segment ORDER BY id"
            )
        ).fetchall()
    h = hashlib.sha256()
    for r in rows:
        h.update("|".join(str(x) for x in r).encode())
        h.update(b"\n")
    return h.hexdigest(), len(rows)


def _evidence_checksum(engine: sa.Engine, kinds: tuple[str, ...]) -> tuple[str, int]:
    """Checksum evidence rows for the given kinds (OCR/ASR/low-level extraction)."""
    placeholders = ", ".join(f":k{i}" for i in range(len(kinds)))
    params = {f"k{i}": k for i, k in enumerate(kinds)}
    with engine.connect() as c:
        rows = c.execute(
            sa.text(
                "SELECT id, source_id, evidence_kind, locator, config_digest, "
                "COALESCE(confidence, -1), COALESCE(quality::text, '') "
                f"FROM evidence WHERE evidence_kind IN ({placeholders}) ORDER BY id"
            ),
            params,
        ).fetchall()
    h = hashlib.sha256()
    for r in rows:
        h.update("|".join(str(x) for x in r).encode())
        h.update(b"\n")
    return h.hexdigest(), len(rows)


def _evidence_ids(engine: sa.Engine, kind: str) -> set[str]:
    with engine.connect() as c:
        rows = c.execute(
            sa.text("SELECT id FROM evidence WHERE evidence_kind = :k"), {"k": kind}
        ).fetchall()
    return {str(r[0]) for r in rows}


def _tail(engine: sa.Engine) -> int:
    with engine.connect() as c:
        return int(c.execute(sa.text("SELECT coalesce(max(seq),0) FROM semantic_event")).scalar())


# ---------------------------------------------------------------------------
# Shared scenario: ingest + decompose + align + resolve + reconcile
# ---------------------------------------------------------------------------


def _scenario(
    umd_db: sa.Engine, source_store: Any, *, with_video: bool = _FFMPEG
) -> SimpleNamespace:
    memberships = SourceMembershipService(umd_db)
    work_id = _wid()
    memberships.ensure_work(work_id=work_id, title="The Garden", work_type="book")
    reg = SegmentRegistry(PostgresSegmentStore(umd_db))
    ev = PostgresEvidenceRepository(umd_db)
    artifacts = PostgresArtifactStore(umd_db)
    ledger = SemanticLedger(umd_db)
    commands = SemanticCommandService(ledger)

    # --- 1. ingest several related heterogeneous sources under ONE work -----
    s_txt, man_txt = _ensure_source(
        memberships, source_store, "translated.txt", translated_txt_bytes(), "text", work_id
    )
    s_md, man_md = _ensure_source(
        memberships, source_store, "adapted.md", adapted_markdown_bytes(), "text", work_id
    )
    s_audio, man_audio = _ensure_source(
        memberships, source_store, "dialog.wav", multi_speaker_audio_wav_bytes(), "audio", work_id
    )
    s_sub, _man_sub = _ensure_source(
        memberships,
        source_store,
        "dialog.srt",
        subtitle_bytes("srt", hi_sdh=True),
        "subtitle",
        work_id,
    )
    s_raster, man_raster = _ensure_source(
        memberships, source_store, "comic.png", raster_comic_bytes(), "image", work_id
    )
    s_video = None
    if with_video:
        s_video, _man_video = _ensure_source(
            memberships, source_store, "dialog.mkv", dialogue_video_bytes(), "video", work_id
        )

    # --- 2. decompose independently (deterministic, per-modality) -----------
    from umd.extractors.markdown import parse_markdown
    from umd.extractors.txt import normalize_txt
    from umd.segmentation.segmenters import TEXT_PIPELINE_VERSION, segment_markdown, segment_txt

    r1 = segment_txt(
        reg,
        source_id=s_txt,
        source_sha512=man_txt.sha512,
        work_id=work_id,
        text=normalize_txt(translated_txt_bytes()).text,
        version=TEXT_PIPELINE_VERSION,
    )
    r2 = segment_markdown(
        reg,
        source_id=s_md,
        source_sha512=man_md.sha512,
        work_id=work_id,
        doc=parse_markdown(normalize_txt(adapted_markdown_bytes()).text),
        version=TEXT_PIPELINE_VERSION,
    )
    k_txt = {s.deterministic_key for s in r1.batch.created}
    k_md = {s.deterministic_key for s in r2.batch.created}

    # audio -> ASR with distinct utterance-level speaker candidates (no promotion)
    cfg = AudioConfig(declared_language="en")
    config_digest_of(cfg)
    aout = run_audio_baseline(_wav_decoded(multi_speaker_audio_wav_bytes()), cfg)
    assert aout.asr is not None and aout.asr.utterances
    uttr = " ".join(wd.word for u in aout.asr.utterances for wd in u.words)
    aplan = build_audio_evidence_plan(
        aout,
        source_id=s_audio,
        source_sha512=man_audio.sha512,
        work_id=work_id,
        config_digest=cfg.config_digest,
    )
    reg.register(aplan.segment_inputs)
    ev.record(EvidenceBatch(records=aplan.evidence))

    # raster -> OCR/regions/panels evidence (OCR checksum is asserted in P3-S2)
    process_raster(
        registry=reg,
        evidence_repo=ev,
        store=source_store,
        artifacts=artifacts,
        source_id=s_raster,
        source_sha512=man_raster.sha512,
        raw=raster_comic_bytes(),
    )

    # independent subtitle track parsed (HI/SDH preserved verbatim)
    from umd.subtitle.formats import parse_subtitle_text

    sub_raw = subtitle_bytes("srt", hi_sdh=True)
    parsed = parse_subtitle_text(
        sub_raw.decode("utf-8", "replace"),
        raw_bytes=sub_raw,
        charset="utf-8",
        charset_confidence=1.0,
        hint="srt",
    )
    assert parsed.events
    assert "[music playing]" in parsed.events[0].text  # HI/SDH never flattened

    if s_video is not None and with_video:
        # video: sandboxed inventory + independent embedded subtitle as its OWN source
        from umd.security.sandbox import SubprocessSandboxRunner
        from umd.video import evidence as video_evidence
        from umd.video.runner import extract_embedded_subtitles, invoke_video_baseline

        sandbox = SubprocessSandboxRunner()
        vout = invoke_video_baseline(sandbox, dialogue_video_bytes(), name="dialog.mkv")
        vplan = video_evidence.build_video_evidence_plan(
            vout, source_id=s_video, source_sha512="a" * 128, work_id=work_id
        )
        ev.record(EvidenceBatch(records=vplan.evidence)) if vplan.evidence else None
        extracted = extract_embedded_subtitles(sandbox, dialogue_video_bytes(), name="dialog.mkv")
        assert extracted and extracted[0]["payload"]
        track_payload = extracted[0]["payload"]
        s_video_sub, _mv = _ensure_source(
            memberships,
            source_store,
            "embedded.srt",
            track_payload,
            "subtitle",
            work_id,
        )

    # --- 3. cross-source alignment (translation / adaptation) ---------------
    seg_a = next(iter(k_txt)) if k_txt else f"source://{s_txt}/text/1"
    seg_b = next(iter(k_md)) if k_md else f"source://{s_md}/text/1"
    insert_alignment(
        umd_db,
        left_ref=seg_a,
        right_ref=seg_b,
        alignment_type="TRANSLATION",
        method="scene-order-dtw",
        confidence=0.7,
    )
    commands.record_alignment(
        left_ref=f"source://{s_txt}/text/1",
        right_ref=f"source://{s_md}/text/1",
        alignment_type="ADAPTATION",
        method="scene-order-dtw",
        confidence=0.6,
    )

    # --- 4. resolve shared multilingual / adaptation entities ----------------
    commands.entity_resolve(
        kind="ALIAS",
        entity_id="e:lapin",
        target_entity_id="e:white-rabbit",
        refs=["e:lapin"],
        reason="multilingual alias: 'Lapin Blanc' == 'White Rabbit'",
    )
    commands.entity_resolve(
        kind="MERGE",
        entity_id="e:white-rabbit",
        target_entity_id="e:white-rabbit",
        refs=["e:white-rabbit", "e:lapin"],
        reason="shared adaptation entity across realizations",
    )

    # --- 5. reconcile SPEAKS utterances into the semantic ledger ------------
    commands.assert_semantic(
        predicate_code="SPEAKS",
        subject_ref="e:alice",
        object_ref=uttr,
        confidence=0.6,
        state="PROBABLE",
        scope="CONTINUITY",
        support_refs=[f"source://{s_audio}/audio/0"],
        generated_by={"provider": "reference-asr", "kind": "speech"},
        actor="worker-asr",
    )
    commands.assert_semantic(
        predicate_code="SPEAKS",
        subject_ref="e:white-rabbit",
        object_ref="a fut la chasse",
        confidence=0.55,
        state="PROBABLE",
        scope="CONTINUITY",
        support_refs=[f"source://{s_txt}/text/1"],
        generated_by={"kind": "text-dialogue"},
        actor="worker-text",
    )

    token = _tail(umd_db)

    return SimpleNamespace(
        umd_db=umd_db,
        source_store=source_store,
        reg=reg,
        ev=ev,
        ledger=ledger,
        commands=commands,
        work_id=work_id,
        s_txt=s_txt,
        s_md=s_md,
        s_audio=s_audio,
        s_sub=s_sub,
        s_raster=s_raster,
        s_video=s_video,
        uttr=uttr,
        token=token,
        k_txt=k_txt,
        k_md=k_md,
    )


def _guard(umd_db: sa.Engine) -> ConsistencyGuard:
    settings = Settings(
        auth=AuthSettings(api_keys=["write-key", "read-key"], write_keys=["write-key"]),
        rate_limit=RateLimitSettings(
            enabled=True, requests_per_window=10000, window_seconds=60.0, burst=100
        ),
        consistency=ConsistencySettings(lag_wait_multiplier=1, max_waiters=16),
        lag_budget_seconds=0.05,
    )
    return ConsistencyGuard(ProjectionFreshness(umd_db, "current_tier1"), settings)


# ---------------------------------------------------------------------------
# P3-S1
# ---------------------------------------------------------------------------


def test_e2e_ingest_align_resolve_graph_answer_retains_realizations(
    umd_db: sa.Engine, source_store: Any
) -> None:
    ctx = _scenario(umd_db, source_store)
    query = QueryService(umd_db)
    question = QuestionService(query, SearchService(umd_db))

    # Distinct realizations retained (never conflationally merged): the translated
    # book and the adaptation produce DISJOINT deterministic segment key spaces.
    assert ctx.k_txt and ctx.k_md
    assert ctx.k_txt.isdisjoint(ctx.k_md)
    # All ingested sources resolved as distinct rows under the shared work.
    with umd_db.connect() as c:
        srcs = c.execute(
            sa.text("SELECT media_kind, count(*) FROM source WHERE work_id=:w GROUP BY media_kind"),
            {"w": ctx.work_id},
        ).fetchall()
    kinds = {str(r[0]) for r in srcs}
    assert {"text", "audio", "subtitle", "image"} <= kinds

    # Cross-source alignment reachable via the typed CORRESPONDENCE query.
    corr = query.structured({"kind": "CORRESPONDENCE", "limit": 20})
    assert corr.total >= 1
    assert any(h.label == "correspondence" for h in corr.results)

    # Shared / adaptation entity resolved: the canonical entity graph node is
    # reachable through the typed ENTITY query (the alias+merge folded into
    # current_state as the canonical entity row).
    ent = query.structured({"kind": "ENTITY", "filters": {"ref": "e:white-rabbit"}, "limit": 10})
    assert ent.total >= 1
    assert any(h.ref == "e:white-rabbit" for h in ent.results)
    lapin = query.structured({"kind": "ENTITY", "filters": {"ref": "e:lapin"}, "limit": 10})
    assert lapin.total >= 1  # alias folded into a canonical node, never dropped

    # The semantic answer compiler serves an ENTITY describe question too (typed
    # op + hybrid-search alternatives), proving the graph-like answer path that
    # previously crashed by calling the search service as a plain function.
    desc = question.answer("describe e:white-rabbit", {"max_depth": 2, "limit": 10})
    assert "ENTITY" in desc.compiled_ops
    assert any(a.ref == "e:white-rabbit" for a in desc.answer or [])

    # Semantic graph-like answer: the speaker's utterance compiles to a typed
    # relational op (never unstructured RAG) and carries supporting source refs.
    ans = question.answer("what does e:alice say", {"max_depth": 2, "limit": 20})
    assert "UTTERANCE" in ans.compiled_ops
    assert ans.answer, "expected typed utterance answer rows"
    assert any(a.value == ctx.uttr for a in ans.answer)
    assert ans.support, "expected supporting utterance evidence"
    assert "typed relational" in ans.provenance["authority"]

    # Supporting SOURCE references are returned (source_id + locator) by the
    # typed evidence query for the audio source that produced the utterance.
    evpage = query.structured(
        {"kind": "EVIDENCE", "filters": {"source_id": ctx.s_audio}, "limit": 50}
    )
    assert evpage.results
    # every supporting-reference hit carries its source id; locators present
    assert all(h.source_id for h in evpage.results)
    assert any(h.value for h in evpage.results)


# ---------------------------------------------------------------------------
# P3-S2
# ---------------------------------------------------------------------------


def test_e2e_correction_override_unaffected_ids_checksums_and_planner(
    umd_db: sa.Engine, source_store: Any
) -> None:
    ctx = _scenario(umd_db, source_store)
    audit = AuditService(umd_db)
    corrected_utterance = "Hello, Alice"  # user-corrected transcript

    # --- capture the pre-correction T0 answer + unaffected-checksum baselines ---
    pre = QueryService(umd_db).structured(
        {"kind": "UTTERANCE", "filters": {"speaker": "e:alice"}, "limit": 20}
    )
    assert any(h.value == ctx.uttr for h in pre.results)  # machine answer first

    seg0, n_seg0 = _segment_checksum(umd_db)
    low0, n_low0 = _evidence_checksum(umd_db, _LOW_LEVEL)
    asr_ids0 = _evidence_ids(umd_db, "audio_interval")
    ocr_ids0 = _evidence_ids(umd_db, "ocr_region")
    assert asr_ids0 and ocr_ids0  # OCR and ASR evidence really exist to protect

    # --- apply the user entity correction/override with audit causation ---
    ctx.commands.record_override(
        subject_ref="e:alice",
        predicate="SPEAKS",
        object_ref=corrected_utterance,
        actor="reviewer@example",
        evidence=[f"source://{ctx.s_audio}/audio/0"],
        reason="manual transcription correction of the spoken utterance",
    )
    ctx.commands.record_override(
        subject_ref="e:alice",
        predicate="CANONICAL_ENTITY",
        object_ref="Alice (user-corrected)",
        actor="reviewer@example",
        evidence=[f"source://{ctx.s_txt}/text/1"],
        reason="user override of speaker identity",
    )

    # audit causation: current reflects the user override, prior the machine value,
    # and the change cause (reason) is recorded.
    ex = audit.explain("e:alice#SPEAKS")
    assert ex.current["object_ref"] == corrected_utterance
    assert ex.current["authority"] == USER_OVERRIDE
    assert ex.prior["object_ref"] == ctx.uttr
    assert ex.actor == "reviewer@example"
    assert ex.change_cause and ex.change_cause.get("reason") == (
        "manual transcription correction of the spoken utterance"
    )

    # --- invalidation causation: the planner schedules ONLY affected descendants ---
    targets = InvalidationPlanner().plan(
        causation="correction",
        scope=f"work:{ctx.work_id}",
        stage="ENTITY_RESOLUTION",
        lineage=STAGE_DEPENDENTS,
    )
    planned = {t.stage for t in targets.targets}
    assert planned == {
        "CROSS_SOURCE_ALIGNMENT",
        "SEMANTIC_RECONCILIATION",
        "CURRENT_SEARCH_PROJECTION",
    }
    # unaffected branches / ancestors are retained, never re-run
    assert not (planned & {"OCR_ASR", "LOW_LEVEL_EXTRACTION", "BASIC_SEGMENTATION"})
    assert targets.unaffected >= 4

    # --- unaffected OCR/ASR/segment IDs AND checksums remain byte-stable ---
    seg1, n_seg1 = _segment_checksum(umd_db)
    low1, n_low1 = _evidence_checksum(umd_db, _LOW_LEVEL)
    assert (seg1, n_seg1) == (seg0, n_seg0)
    assert (low1, n_low1) == (low0, n_low0)
    assert _evidence_ids(umd_db, "audio_interval") == asr_ids0
    assert _evidence_ids(umd_db, "ocr_region") == ocr_ids0


# ---------------------------------------------------------------------------
# P3-S3
# ---------------------------------------------------------------------------


def test_e2e_selective_rerun_tier0_tier1_cross_equivalent_no_stale_distinct_lag(
    umd_db: sa.Engine, source_store: Any
) -> None:
    ctx = _scenario(umd_db, source_store)
    corrected_utterance = "Hello, Alice"
    ctx.commands.record_override(
        subject_ref="e:alice",
        predicate="SPEAKS",
        object_ref=corrected_utterance,
        actor="reviewer@example",
        evidence=[f"source://{ctx.s_audio}/audio/0"],
        reason="manual transcription correction of the spoken utterance",
        confidence=1.0,
    )
    corrected_token = _tail(umd_db)  # read-your-writes token for the corrected write

    # --- rerun ONLY the affected descendants (projection stage), never the
    #     extraction/segmentation evidence ---
    seg0, _n0 = _segment_checksum(umd_db)
    low0, _l0 = _evidence_checksum(umd_db, _LOW_LEVEL)
    guard = _guard(umd_db)
    store = ProjectionCheckpointStore(umd_db)
    builder = CurrentTierOneBuilder()
    driver = ReplayDriver(umd_db, store)

    # --- atomic Tier-0 read reflects the CORRECTED answer + confidence ---
    t0_inline = tier0_checksum(umd_db)
    t0 = QueryService(umd_db).structured(
        {"kind": "UTTERANCE", "filters": {"speaker": "e:alice"}, "limit": 20}
    )
    corrected = [h for h in t0.results if h.value == corrected_utterance]
    assert corrected and corrected[0].value == corrected_utterance
    assert corrected[0].confidence == 1.0  # corrected confidence reflected
    assert not [h for h in t0.results if h.value == ctx.uttr]  # no stale machine answer

    # --- distinct transient-lag vs rebuild-in-progress handling -------------
    # (a) projection behind the corrected token -> transient-lag 503
    store.save(ProjectionCheckpoint("current_tier1", applied_seq=0))
    try:
        guard.ensure_read(corrected_token)
        raise AssertionError("expected a transient-lag 503")
    except ConsistencyLagError as exc:
        assert exc.code == "consistency_transient_lag"
        assert exc.extra.get("x-consistency") == "transient-lag"
        assert exc.retryable is True

    # (b) projection paused (post-correction rebuild) -> rebuild-in-progress 503
    store.save(
        ProjectionCheckpoint("current_tier1", applied_seq=0).paused("rebuild after correction", 0)
    )
    try:
        guard.ensure_read(corrected_token)
        raise AssertionError("expected a rebuild-in-progress 503")
    except ConsistencyLagError as exc:
        assert exc.code == "consistency_rebuild"
        assert exc.extra.get("x-consistency") == "rebuild-in-progress"
        assert float(exc.extra.get("retry_after", 0)) >= 30
        assert exc.retryable is True

    # --- selective rerun + wipe-and-replay Tier-1 rebuild -------------------
    rep = driver.run(builder, wipe=True, force_resume=True)
    tail = _tail(umd_db)
    assert rep.fresh and rep.applied_seq == tail
    assert rep.events_seen == tail and rep.skipped == 0

    # token-bearing read is now servable (no more 503) and not stale
    snap = guard.ensure_read(corrected_token)
    assert snap.status == "fresh"

    # --- cross-tier equivalence: replay-built Tier-1 == atomic Tier-0 -------
    assert builder.checksum(umd_db) == t0_inline

    # --- Tier-1 read reflects the corrected answer too (no stale answer) -----
    t1 = QueryService(umd_db).structured(
        {"kind": "UTTERANCE", "filters": {"speaker": "e:alice"}, "limit": 20}
    )
    assert any(h.value == corrected_utterance for h in t1.results)
    assert not [h for h in t1.results if h.value == ctx.uttr]

    # --- the selective rerun did NOT re-extract/re-segment anything ---------
    seg1, _n1 = _segment_checksum(umd_db)
    low1, _l1 = _evidence_checksum(umd_db, _LOW_LEVEL)
    assert seg1 == seg0 and low1 == low0
