"""P3-S1: versioned event payload schemas, validation, pure upcasters, CI replay.

Event payload schemas live under ``schemas/events/<type>/v<n>.json`` and are the
published, retained versioned contracts. Tests:

  * every event type has a retained v1 schema (and SemanticAsserted has a v2),
    and the files parse as draft-2020-12 JSON Schema;
  * validation rejects non-conforming payloads and accepts conforming ones;
  * the pure upcaster chain replays a retained v1 ``SemanticAsserted`` row to the
    latest version (v2 gains ``scope``) WITHOUT mutating the original payload;
  * ``retained_event_references`` and ``upcast_payload`` form the CI replay
    fixture that exercises every retained version.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from umd.domain.events import (
    EVENT_TYPES,
    EventSchemaError,
    EventType,
    EventVersionError,
    SemanticEvent,
    _schemas_root,
    latest_version,
    load_schema,
    retained_event_references,
    schema_url,
    schemas_root,
    upcast_payload,
    validate_payload,
)

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def _probe_all_types() -> None:
    for t in EVENT_TYPES:
        assert EventType(t) == t, t


# ---------------------------------------------------------------------------
# schema presence / draft conformance
# ---------------------------------------------------------------------------


def test_retained_schemas_exist_for_every_event_type() -> None:
    _probe_all_types()
    for t in EVENT_TYPES:
        sch = load_schema(t, 1)
        assert sch["type"] == "object"
        assert sch["$schema"].startswith("https://json-schema.org/draft/2020-12/schema")
        assert sch.get("title") == t
    # SemanticAsserted is the demonstrative versioned event: v2 exists as latest.
    assert latest_version("SemanticAsserted") == 2


def test_schema_url_matches_retained_layout() -> None:
    assert schema_url("SemanticAsserted", 2) == "schemas/events/SemanticAsserted/v2.json"
    url = Path(schemas_root()) / "SourceIngested" / "v1.json"
    assert url.is_file()


def test_every_retained_version_is_referenceable() -> None:
    refs = retained_event_references()
    assert refs, "no retained event references"
    by_type: dict[str, set[int]] = {}
    for ref in refs:
        by_type.setdefault(ref.event_type, set()).add(ref.version)
        load_schema(ref.event_type, ref.version)  # must parse
    # CI fixture: every event type has a v1; only the upcast demo adds a v2.
    assert set(by_type) == set(EVENT_TYPES)
    assert by_type["SemanticAsserted"] == {1, 2}


# ---------------------------------------------------------------------------
# validation
# ---------------------------------------------------------------------------


def test_validate_rejects_nonconforming_payload() -> None:
    with pytest.raises(EventSchemaError):
        validate_payload(
            "SourceIngested",
            1,
            {"source_id": "x"},  # missing sha512/ocfl_ref/media_kind/...
        )


def test_validate_accepts_conforming_payload() -> None:
    validate_payload(
        "SourceIngested",
        1,
        {
            "source_id": "s1",
            "sha512": "a" * 128,
            "ocfl_ref": "urn:ocfl:o1",
            "size_bytes": 12,
            "media_kind": "text",
            "work_id": "w1",
            "original_name": "a.txt",
        },
    )


# ---------------------------------------------------------------------------
# pure upcasters + CI replay without mutation
# ---------------------------------------------------------------------------


def test_upcaster_replays_v1_semantic_asserted_to_v2_without_mutation() -> None:
    v1_payload = {
        "predicate_code": "SPEAKS",
        "subject_ref": "e:1",
        "object_ref": "utter:9",
        "authority": "asr",
        "confidence": 0.6,
        "state": "PROBABLE",
    }
    original = dict(v1_payload)
    version, upcast = upcast_payload("SemanticAsserted", 1, v1_payload)
    assert version == 2
    assert upcast["scope"] == "GLOBAL"  # COnservative default filled by the upcaster
    assert v1_payload == original  # the retained row is never mutated
    # The upcast result itself conforms to the latest (v2) schema.
    validate_payload("SemanticAsserted", 2, upcast)


def test_semantic_event_prepare_replays_retained_v1() -> None:
    ev = SemanticEvent(
        event_type="SemanticAsserted",
        payload_version=1,
        payload={
            "predicate_code": "SPEAKS",
            "subject_ref": "e:1",
            "object_ref": "utter:9",
            "authority": "asr",
            "confidence": 0.6,
            "state": "PROBABLE",
        },
        seq=7,
    )
    prep = ev.prepare()
    assert prep.event_version == 2
    assert prep.payload["scope"] == "GLOBAL"
    assert prep.schema_url == "schemas/events/SemanticAsserted/v2.json"


def test_semantic_event_prepare_requires_current_scope() -> None:
    # A freshly constructed event defaults to the latest version (v2), which
    # requires `scope`; providing it passes.
    ev = SemanticEvent(
        event_type="SemanticAsserted",
        payload={
            "predicate_code": "SPEAKS",
            "subject_ref": "e:1",
            "object_ref": "utter:9",
            "authority": "asr",
            "confidence": 0.6,
            "state": "PROBABLE",
            "scope": "CONTINUITY",
        },
    )
    assert ev.prepare().event_version == 2


def test_json_schemas_load_as_valid_due_to_load_schema() -> None:
    # Spot-check that every Schema file parses to a JSON object (draft conformance).
    for t in EVENT_TYPES:
        data = load_schema(t, 1)
        json.dumps(data)  # must be JSON-serializable
        assert isinstance(data, dict)


def test_unknown_version_raises() -> None:
    with pytest.raises(EventVersionError):
        load_schema("SemanticAsserted", 999)


# ---------------------------------------------------------------------------
# _schemas_root resolution (P3-S6): env override first (fail-closed when set
# but not a directory), then ancestor walk / cwd fallback for non-image runs.
# ---------------------------------------------------------------------------


def test_schemas_root_uses_env_override_when_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    override = tmp_path / "schemas" / "events"
    override.mkdir(parents=True)
    monkeypatch.setenv("UMD_EVENT_SCHEMAS_ROOT", str(override))
    assert _schemas_root() == override.resolve()


def test_schemas_root_fails_closed_when_env_set_but_not_dir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("UMD_EVENT_SCHEMAS_ROOT", "/definitely/not/a/schemas/events")
    with pytest.raises(FileNotFoundError):
        _schemas_root()


def test_schemas_root_ancestor_walk_without_env(monkeypatch: pytest.MonkeyPatch) -> None:
    # Without the env override, the ancestor walk from the installed module must
    # locate the repo's schemas/events (StageCompleted retained schema present).
    monkeypatch.delenv("UMD_EVENT_SCHEMAS_ROOT", raising=False)
    root = _schemas_root()
    assert (root / "StageCompleted").is_dir()
    assert root.is_dir()
