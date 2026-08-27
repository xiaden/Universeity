"""Plan E (P2-S2/P2-S4): deployment configuration, migration startup ordering,
readiness probe, packaging artifacts, and conditional Docker/Kubernetes coverage.

Covers:
* **Migration startup ordering** (real, Postgres): a fresh database reports a
  *degraded* migrations probe until ``run_migrations`` applies the Alembic chain,
  after which the readiness probe is fully ready.
* **Packaging artifacts** (static): Compose targets Postgres 18.6 + pgvector
  >=0.8.2, the sandbox-runner service is never ``privileged``, the Dockerfile and
  entrypoint carry no API secret literals, and the pin/CVE/license/sandbox
  artifacts exist.
* **Container/Kubernetes requirements** (conditional): Docker-dependent tests are
  skipped with an honest reason when no daemon exists; if Docker IS present they
  validate the compose file (``docker compose config`` — no image pull/build) and
  check the baked base image string. Kubernetes is documented (bare-metal/VM is
  the first-class option); a k8s manifest validator runs only when kubectl + a
  configured context are present.
"""

from __future__ import annotations

import contextlib
import os
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
import sqlalchemy as sa

import conftest

REPO_ROOT = Path(__file__).resolve().parents[1]
DEPLOY = REPO_ROOT / "deploy"

_DOCKER_MISSING = shutil.which("docker") is None


def _docker_usable() -> bool:
    if _DOCKER_MISSING:
        return False
    try:
        proc = subprocess.run(["docker", "info"], capture_output=True, timeout=20, check=False)
        return proc.returncode == 0
    except (subprocess.SubprocessError, OSError):
        return False


_DOCKER_OK = _docker_usable()


# ---------------------------------------------------------------------------
# Packaging artifacts (static — always run)
# ---------------------------------------------------------------------------


def _compose() -> str:
    return (DEPLOY / "compose.yaml").read_text(encoding="utf-8")


def test_compose_targets_postgres18_and_pgvector() -> None:
    """Compose targets Postgres 18.6 + pgvector >=0.8.2 (target 0.8.6)."""
    compose = _compose()
    assert "pgvector/pgvector:pg18" in compose
    assert "18.6" in compose
    assert "0.8.2" in compose  # CVE-2026-3172 floor
    assert "0.8.6" in compose  # HNSW target
    # Honesty statement that local CI on PG17/pgvector0.8.0 keeps HNSW gated.
    assert "0.8.0" in compose and "HNSW" in compose


def test_compose_sandbox_not_privileged() -> None:
    """The sandbox-runner service never uses `privileged: true`; it is confined."""
    compose = _compose()
    # Assert the sandbox-runner SERVICE is never `privileged`. The word may
    # appear in a comment; only an uncommented `privileged:` YAML key counts.
    for line in compose.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        assert "privileged:" not in stripped, f"sandbox service may not be privileged: {line}"
    assert "no-new-privileges" in compose
    assert "read_only: true" in compose
    assert "cap_drop" in compose


def test_compose_never_exposes_api_secrets_literals() -> None:
    """No API secret value is hard-coded into compose (only substitution refs)."""
    compose = _compose()
    for line in compose.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        upper = stripped.upper()
        # A secret *volume mount* reference (e.g. `- umd-api-secrets:/run/secrets:ro`)
        # is a mount path, not a baked credential value — allow it.
        if " /run/secrets" in stripped or (stripped.startswith("-") and ":ro" in stripped):
            continue
        if not any(k in upper for k in ("PASSWORD", "SECRET", "TOKEN", "KEY")):
            continue
        # Skip key-only declarations (a volume/mapping name, no scalar value).
        if ":" in stripped and not stripped.partition(":")[2].strip():
            continue
        # A secret-bearing line with a value must substitute from the environment
        # (${...}) — never a literal credential baked into the file.
        assert "${" in stripped, f"possible baked secret: {line.strip()}"


def test_dockerfile_and_entrypoint_have_no_secrets() -> None:
    """The image Dockerfile + entrypoint carry zero credential literals."""
    for f in ("Dockerfile", "docker-entrypoint.sh"):
        text = (DEPLOY / f).read_text(encoding="utf-8")
        for bad in ("PASSWORD=", "SECRET=", "TOKEN=", "postgresql://umd:umd@"):
            assert bad not in text, f"{f} contains {bad}"
    # DSN is injected at runtime via environment, never baked in.
    assert "UMD_POSTGRES__DSN" in (DEPLOY / "docker-entrypoint.sh").read_text(encoding="utf-8")


def test_operational_security_artifacts_present() -> None:
    """Pins, CVE watch, license review, and sandbox profile are committed."""
    expect = [
        "pins/runtime.txt",
        "security/CVE_WATCH.md",
        "security/LICENSE_REVIEW.md",
        "security/SANDBOX_HOST_PROFILE.md",
        "security/sandbox-seccomp.json",
        "Dockerfile",
        "docker-entrypoint.sh",
        "compose.yaml",
    ]
    for rel in expect:
        assert (DEPLOY / rel).is_file(), f"missing {rel}"
    pins = (DEPLOY / "pins/runtime.txt").read_text(encoding="utf-8")
    assert "18.6" in pins or "0.8.2" in pins  # pinned pg target referenced
    cve = (DEPLOY / "security/CVE_WATCH.md").read_text(encoding="utf-8")
    assert "CVE-2026-3172" in cve and "0.8.2" in cve
    lic = (DEPLOY / "security/LICENSE_REVIEW.md").read_text(encoding="utf-8")
    assert "AGPL" in lic or "GPL" in lic


# ---------------------------------------------------------------------------
# Migration startup ordering + readiness probe (real, Postgres)
# ---------------------------------------------------------------------------


def _fresh_dbname() -> str:
    return f"umd_p2_{uuid.uuid4().hex[:8]}"


def test_migration_startup_ordering_and_readiness(tmp_path: Path) -> None:
    """Fresh DB is 'degraded' until migrations run; then the probe is ready.

    Exercises run_migrations + readiness_probe against a real throwaway Postgres
    database (no Docker): this is exactly the container entrypoint ordering.
    """
    from umd.deploy.startup import all_ready, readiness_probe, run_migrations
    from umd.storage.ocfl import SourceStore

    if not conftest._POSTGRES:  # pragma: no cover - env-gated
        pytest.skip("live PostgreSQL unavailable; set UMD_TEST_POSTGRES=true")

    ocfl = tmp_path / "ocfl"
    SourceStore.create(root=ocfl)

    dbname = _fresh_dbname()
    admin = sa.create_engine(
        conftest.ADMIN_DSN, isolation_level="AUTOCOMMIT", poolclass=sa.pool.NullPool
    )
    with admin.connect() as conn:
        conn.exec_driver_sql(f'CREATE DATABASE "{dbname}"')
    dsn = f"postgresql+psycopg://umd:umd@{conftest.PG_HOST}:{conftest.PG_PORT}/{dbname}"
    try:
        # (1) Before migrations: Postgres reachable but migrations DEGRADED =>
        #     the probe is not ready (startup ordering proves migrations gate ready).
        probe = readiness_probe(dsn=dsn, ocfl_root=ocfl, alembic_ini=REPO_ROOT / "alembic.ini")
        by_name = {c.name: c.status for c in probe}
        assert by_name["postgres"] == "ok"
        assert by_name["migrations"] == "degraded"
        assert all_ready(probe) is False

        # (2) Apply the Alembic chain through the production entrypoint helper.
        head = run_migrations(dsn, REPO_ROOT / "alembic.ini")
        assert head and head != "(no alembic_version table)"

        # (3) Now the full probe is ready: postgres + migrations + ocfl all ok.
        probe2 = readiness_probe(dsn=dsn, ocfl_root=ocfl, alembic_ini=REPO_ROOT / "alembic.ini")
        assert all_ready(probe2) is True
    finally:
        engine = sa.create_engine(dsn, poolclass=sa.pool.NullPool)
        engine.dispose()  # release any lingering connections before drop
        with admin.connect() as conn:
            conn.exec_driver_sql(
                f"SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                f"WHERE datname = '{dbname}' AND pid <> pg_backend_pid()"
            )
            conn.exec_driver_sql(f'DROP DATABASE IF EXISTS "{dbname}"')


def test_pg_backup_restore_runnable_without_docker(umd_db: sa.Engine, tmp_path: Path) -> None:
    """Backup/restore is a REAL local capability (no Docker): runs against live PG."""
    from umd.domain.events import SemanticEvent
    from umd.recovery.postgres_backup import backup_postgres, restore_postgres
    from umd.storage.postgres.ledger import SemanticLedger

    ledger = SemanticLedger(umd_db)
    ledger.append(
        [
            SemanticEvent(
                event_type="SemanticAsserted",
                authority="machine",
                payload={
                    "predicate_code": "SPEAKS",
                    "subject_ref": "e:1",
                    "object_ref": "utter:1",
                    "authority": "machine",
                    "confidence": 0.6,
                    "state": "PROBABLE",
                    "scope": "CONTINUITY",
                },
            )
        ]
    )
    snapshot = tmp_path / "bk"
    manifest = backup_postgres(umd_db, snapshot)
    report = restore_postgres(umd_db, snapshot)
    assert report.restored_events == manifest.ledger_count == 1
    assert report.checksum_verified is True


# ---------------------------------------------------------------------------
# Conditional Docker / Kubernetes coverage (honest skips when unavailable)
# ---------------------------------------------------------------------------


def test_docker_compose_config_when_daemon_present() -> None:
    """Validate compose syntax with the real engine when a Docker daemon exists."""
    if not _DOCKER_OK:
        pytest.skip("no Docker daemon available (conditional CI-only coverage)")
    proc = subprocess.run(
        ["docker", "compose", "-f", str(DEPLOY / "compose.yaml"), "config", "--quiet"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert proc.returncode == 0, f"docker compose config failed: {proc.stderr}"


def test_k8s_requirements_conditional() -> None:
    """Managed Kubernetes is a documentation-level, conditional requirement.

    Bare-metal/VM is the first-class deployment; k8s is a conditional add-on. When
    kubectl + a context exist, `kubectl apply --dry-run=client` validates any
    committed manifest; otherwise the requirement is documented, not fabricated.
    This test exists so the dependency is visible in the suite and the conditional
    engine coverage is honest — not a silent pass.
    """
    kube_dir = DEPLOY / "kubernetes"
    if not shutil.which("kubectl") or not os.environ.get("KUBECONFIG"):
        pytest.skip("kubectl/KUBECONFIG unavailable (managed Kubernetes is conditional)")
    manifests = sorted(kube_dir.glob("*.yaml")) if kube_dir.exists() else []
    assert manifests, "k8s manifests expected when managed-k8s is configured"
    for m in manifests:
        proc = subprocess.run(
            ["kubectl", "apply", "--dry-run=client", "-f", str(m)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
        assert proc.returncode == 0, f"kubectl validation failed for {m}: {proc.stderr}"


# ---------------------------------------------------------------------------
# QA R2 regression: canonical nested `__` env names (P4-S2)
# ---------------------------------------------------------------------------

# The stale single-underscore nested env names that must never remain in an active
# surface (\b word-boundary keeps `__` matches from being flagged).
_STALE_NESTED_NAMES = [
    r"UMD_POSTGRES_DSN\b",
    r"UMD_OCFL_ROOT\b",
    r"UMD_VECTOR_HNSW_MIN_VERSION\b",
    r"UMD_POSTGRES_POOL_SIZE\b",
    r"UMD_POSTGRES_MAX_OVERFLOW\b",
    r"UMD_OCFL_LAYOUT\b",
]


def _active_surface_texts() -> dict[str, str]:
    """Active deployment/config seams that must use canonical names.

    This is the governance surface enumerated in the P4 acceptance check
    (deploy/, .env.example, migrations/, src/umd/deploy/, conftest, Makefile,
    alembic.ini). Test files intentionally reference the stale single-underscore
    tokens as regression probes, so they are not scanned for staleness.
    """
    paths: list[Path] = [
        DEPLOY / "compose.yaml",
        DEPLOY / "docker-entrypoint.sh",
        DEPLOY / "Dockerfile",
        REPO_ROOT / ".env.example",
        REPO_ROOT / "Makefile",
        REPO_ROOT / "alembic.ini",
        REPO_ROOT / "migrations",
        REPO_ROOT / "src" / "umd" / "deploy",
        REPO_ROOT / "tests" / "conftest.py",
    ]
    out: dict[str, str] = {}
    for p in paths:
        if p.is_dir():
            for f in sorted(p.rglob("*")):
                if f.is_file():
                    _read_text_or_skip(f, out)
        else:
            _read_text_or_skip(p, out)
    return out


def _read_text_or_skip(p: Path, out: dict[str, str]) -> None:
    """Read a textual surface; silently skip non-UTF-8 (binary) files."""
    with contextlib.suppress(UnicodeDecodeError):
        out[str(p)] = p.read_text(encoding="utf-8")


def test_compose_connects_to_db_and_persists_ocfl_at_data() -> None:
    """Compose uses the canonical `__` names and wires db:5432 + /data/ocfl."""
    compose = _compose()
    assert "UMD_POSTGRES__DSN" in compose
    assert "postgresql+psycopg://umd:${UMD_POSTGRES_PASSWORD:-umd}@db:5432/umd" in compose
    assert "UMD_OCFL__ROOT: /data/ocfl" in compose
    # the named volume is mounted (read-write) at the API/worker OCFL path
    assert re.search(r"ocfl-data:/data/ocfl(\S*)", compose)


def test_migration_and_deploy_use_canonical_dsn_name() -> None:
    """Migrations, startup pinning, bootstrap, and entrypoint use UMD_POSTGRES__DSN."""
    text_by_label = {
        "migrations/env.py": (REPO_ROOT / "migrations" / "env.py").read_text(encoding="utf-8"),
        "startup.py": (REPO_ROOT / "src" / "umd" / "deploy" / "startup.py").read_text(
            encoding="utf-8"
        ),
        "conftest.py": (REPO_ROOT / "tests" / "conftest.py").read_text(encoding="utf-8"),
        "docker-entrypoint.sh": (DEPLOY / "docker-entrypoint.sh").read_text(encoding="utf-8"),
    }
    for label, text in text_by_label.items():
        assert "UMD_POSTGRES__DSN" in text, f"{label} must use the canonical DSN name"
        assert not re.search(r"UMD_POSTGRES_DSN\b", text), (
            f"{label} still uses a single-underscore nested DSN name"
        )


def test_no_stale_single_underscore_nested_names_in_active_surfaces() -> None:
    """No active deployment/config/test/documentation surface keeps a stale name."""
    for path, text in _active_surface_texts().items():
        for pat in _STALE_NESTED_NAMES:
            m = re.search(pat, text)
            assert m is None, f"{path}: stale nested env name {m.group(0)!r} present"
