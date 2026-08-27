"""Plan E (P2-S2): worker honesty gate + migrate role dispatch (issue #5).

Exercises ``umd.deploy.cli``:

* the ``worker`` honesty gate exits non-zero (2) when ``hatchet_sdk`` is absent
  **or** ``UMD_HATCHET_SERVER_URL`` / ``UMD_HATCHET_TOKEN`` are unset — it never
  registers a fake ready worker;
* the ``migrate`` role dispatch runs the migration helper and returns 0;
* an unknown role dispatch returns 2.

No real Hatchet server or Postgres migration is required — the SDK import and
migration helper are stubbed so the honesty-gate and dispatch logic is tested in
isolation.
"""

from __future__ import annotations

import types

import umd.deploy.cli as cli


class _FakeImportLib:
    """Stand-in for ``importlib`` that can simulate a missing ``hatchet_sdk``."""

    def __init__(self, *, sdk_importable: bool) -> None:
        self._sdk_importable = sdk_importable

    def import_module(self, name: str):  # noqa: ANN201 - mirrors importlib.import_module
        if name == "hatchet_sdk":
            if not self._sdk_importable:
                raise ImportError("No module named 'hatchet_sdk'")
            return types.SimpleNamespace(Hatchet=_hatchet_stub)  # opaque SDK stub
        return __import__(name)


def _hatchet_stub(*, api_url: str, token: str):  # noqa: ANN201, ARG001 - test stub mirroring real SDK
    """Opaque stand-in for ``hatchet_sdk.Hatchet`` (unused by the honesty gate)."""
    return None


def test_worker_exits_2_when_hatchet_sdk_missing(monkeypatch, capsys) -> None:
    monkeypatch.setattr(cli, "importlib", _FakeImportLib(sdk_importable=False))
    monkeypatch.delenv("UMD_HATCHET_SERVER_URL", raising=False)
    monkeypatch.delenv("UMD_HATCHET_TOKEN", raising=False)

    assert cli.worker() == 2
    err = capsys.readouterr().err
    assert "hatchet_sdk not installed" in err
    # Never registers a fake ready worker.
    assert "worker ready" not in err


def test_worker_exits_2_when_env_unset_even_if_sdk_present(monkeypatch, capsys) -> None:
    # SDK is importable, but the server URL / token are not configured: the gate
    # must still refuse to register a worker against an unknown server.
    monkeypatch.setattr(cli, "importlib", _FakeImportLib(sdk_importable=True))
    monkeypatch.delenv("UMD_HATCHET_SERVER_URL", raising=False)
    monkeypatch.delenv("UMD_HATCHET_TOKEN", raising=False)

    assert cli.worker() == 2
    err = capsys.readouterr().err
    assert "UMD_HATCHET_SERVER_URL / UMD_HATCHET_TOKEN" in err
    assert "worker ready" not in err


def test_worker_exits_2_when_only_server_url_set(monkeypatch) -> None:
    monkeypatch.setattr(cli, "importlib", _FakeImportLib(sdk_importable=True))
    monkeypatch.setenv("UMD_HATCHET_SERVER_URL", "http://hatchet:8080")
    monkeypatch.delenv("UMD_HATCHET_TOKEN", raising=False)

    assert cli.worker() == 2


def test_main_migrate_role_dispatches_run_migrations(monkeypatch, capsys) -> None:
    # The migrate role applies the migration chain (stubbed) and returns 0.
    called: dict[str, object] = {}

    def fake_run_migrations(dsn: str) -> str:
        called["dsn"] = dsn
        return "head"

    monkeypatch.setattr(cli, "run_migrations", fake_run_migrations)
    settings = types.SimpleNamespace(postgres=types.SimpleNamespace(dsn="postgresql+psycopg://x"))
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    assert cli.main(["migrate"]) == 0
    assert called["dsn"] == "postgresql+psycopg://x"
    assert "migrations applied" in capsys.readouterr().out


def test_main_unknown_role_exits_2(capsys) -> None:
    assert cli.main(["nope"]) == 2
    assert "unknown role" in capsys.readouterr().err


def test_migrate_return_code_and_message(monkeypatch, capsys) -> None:
    def fake_run_migrations(dsn: str) -> str:  # noqa: ARG001
        return "head"

    monkeypatch.setattr(cli, "run_migrations", fake_run_migrations)
    settings = types.SimpleNamespace(postgres=types.SimpleNamespace(dsn="postgresql+psycopg://x"))
    monkeypatch.setattr(cli, "get_settings", lambda: settings)

    assert cli.migrate() == 0
    assert "migrations applied" in capsys.readouterr().out
