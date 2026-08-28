# ASR runtime pin manifest (P2-S1)

The validated, self-hostable faster-whisper ASR path. **This is an opt-in
extension — never part of the base image.** Install with `pip install '.[asr]'`
and pull the pinned model into the env-driven cache dir.

## Resolved package pins (as validated in the source-of-truth venv, Py 3.13.5)

```
faster-whisper==1.2.1
ctranslate2==4.8.1
onnxruntime==1.29.0
tokenizers==0.23.1
huggingface_hub==1.29.0
numpy==2.5.2
av==18.1.0
protobuf==7.36.0
```

The `asr` optional extra in `pyproject.toml` pins `faster-whisper==1.2.1`; the
remaining pins above are the transitive closure resolved at validation time and
are recorded here for reproducible containers (build-time SBOM must match).

## Model pin

| Field | Value |
| --- | --- |
| Model id (repo) | `Systran/faster-whisper-tiny.en` |
| Config default (`asr_model_id`) | `Systran/faster-whisper-tiny.en` |
| Model cache env | `UMD_ASR_MODEL_CACHE` (also read as `asr_model_dir`) |
| Download target | `snapshot_download("Systran/faster-whisper-tiny.en", local_dir=$UMD_ASR_MODEL_CACHE)` |
| `model.bin` sha256 | `1a5afae06a4db91c975c9a9d78be5cc110ee4ea022ad57d55492e4550e936b2a` (of the converted CT2 `model.bin`; record at your own download) |
| License | MIT (model weights) — permissive, reviewed (deploy/security/LICENSE_REVIEW.md) |

The model cache dir is validated at runtime by `faster_whisper_runtime_ready()`
(importable runtime **and** cache dir present). The provider never fabricates a
transcript when either is absent — it raises `AsrProviderUnavailable` and
`run_asr` downgrades to the honest gated reference path.

## CPU resource limits

Config (env → `AudioConfig`) bounds the in-worker decoder:

| Setting | Env | Default |
| --- | --- | --- |
| CPU threads | `UMD_ASR_CPU_THREADS` | 4 |
| Decoder workers | `UMD_ASR_NUM_WORKERS` | 1 |
| Beam size (ordinary speech) | `UMD_ASR_BEAM_SIZE` | 5 |
| Beam size (music/SFX suspected) | (auto) | 1 |
| Compute type | `UMD_ASR_COMPUTE_TYPE` | `int8` |

ASR always runs **inside** the sandboxed audio worker (`umd.audio.dispatch`), never
in the API process, and spawns no subprocesses of its own.

## License / CVE watch

- Runtime package `faster-whisper` — MIT ✅ (LICENSE_REVIEW.md GATED table).
- Model weights — MIT ✅.
- CVE status tracked in `deploy/security/CVE_WATCH.md` provider-subsystems
  section. Any bump of the above pins requires the CVE + license review gates and
  a re-run of the full `UMD_TEST_POSTGRES=true` suite.

## Small-model validation command

```bash
pip install -e '.[asr]'
export UMD_ASR_MODEL_CACHE=/workspace/Universeity/.model-cache/faster-whisper-tiny.en
.venv/bin/python -m umd.audio.dispatch <input.wav>
```

`dispatch.py` derives `AudioConfig` from `UMD_ASR_*` env, runs the baseline
**inside** the sandbox, and prints the JSON `AudioOutput` (ASR provider, model id,
model version, per-utterance timestamps, transcription-scoped confidence, gate
status). When the runtime+model are validated, the ASR capability reports
`faster-whisper` as ACTIVE and the runnable spec tests
(`test_faster_whisper_dispatch_yields_timestamps_and_provenance`) execute instead
of skipping.
