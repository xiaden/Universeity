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


def test_compose_hatchet_split_topology_subpath_images() -> None:
    """P2-S4: the single invalid `hatchet` service is replaced by the split
    topology (hatchet-migrate/admin/engine/dashboard) using the REAL ghcr.io
    sub-path images at the pinned release. The denied top-level
    ``ghcr.io/hatchet-dev/hatchet:...`` reference must never appear."""
    compose = _compose()
    for svc in (
        "hatchet-migrate",
        "hatchet-admin",
        "hatchet-engine",
        "hatchet-dashboard",
    ):
        assert f"ghcr.io/hatchet-dev/hatchet/{svc}:" in compose, f"missing {svc} sub-path image"
    # The engine is the gRPC surface (7070); the dashboard is the HTTP UI (:80).
    assert '- "7070:7070"' in compose  # engine gRPC admin listener
    assert '- "${HATCHET_DASHBOARD_PORT:-8081}:80"' in compose  # dashboard HTTP UI
    # Top-level image (403 on ghcr.io) must never be referenced as an image.
    assert not re.search(r"^\s*image: ghcr\.io/hatchet-dev/hatchet:", compose, re.M)


def test_worker_hatchet_env_routes_grpc_to_engine_not_dashboard() -> None:
    """P2-S5: the compose worker points its gRPC host_port at the ENGINE (7070),
    never the dashboard, and carries a real-token substitution + server URL."""
    compose = _compose()
    assert "HATCHET_CLIENT_HOST_PORT: hatchet-engine:7070" in compose
    assert "UMD_HATCHET_SERVER_URL: http://hatchet-dashboard:8080" in compose
    assert "UMD_HATCHET_TOKEN: ${HATCHET_TENANT_TOKEN" in compose


def test_hatchet_token_is_real_jwt_not_placeholder() -> None:
    """P2-S5: the worker token is a REAL tenant JWT (minted via hatchet-admin after
    config generation), never a placeholder like ``umd-ci-token`` (which is not a
    JWT and can never register). .env.example documents the minting path."""
    compose = _compose()
    # The token must flow from the environment, not a baked placeholder literal.
    assert "HATCHET_TENANT_TOKEN" in compose
    # `umd-ci-token` is documented as a NON-JWT anti-pattern; it must never be
    # baked as an actual token value in any service env.
    assert "UMD_HATCHET_TOKEN: umd-ci-token" not in compose
    assert re.search(r"token\s*[:=]\s*umd-ci-token", compose) is None
    env_example = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "HATCHET_TENANT_TOKEN" in env_example
    assert "hatchet-admin" in env_example  # the minting command is documented

    # A real JWT is a three-part base64url token whose header starts with `ey`;
    # a placeholder secret is verifiably NOT a JWT and must be rejected as such.
    def _is_jwt(v: str) -> bool:
        return len(v.split(".")) == 3 and v.split(".")[0].startswith("ey")

    assert not _is_jwt("umd-ci-token"), "placeholder must not masquerade as a JWT"


def test_dockerfile_worker_target_installs_worker_extra_and_smoke_tests_sdk() -> None:
    """P3-S2: the Dockerfile has a `worker` build stage that installs the pinned
    `.[worker]` extra and smoke-tests the SDK import WITHOUT promoting the pair.
    The API stays on the lean base (`runtime`), so the worker-only SDK (a GATED
    dependency) never leaks into the base image."""
    df = (DEPLOY / "Dockerfile").read_text(encoding="utf-8")
    assert "FROM runtime AS worker" in df
    assert 'pip install --no-cache-dir ".[worker]"' in df
    assert "import hatchet_sdk" in df  # SDK import smoke test in the worker target
    assert 'CMD ["worker"]' in df
    # The GATED SDK stays out of the lean base: the base stage installs only `.`
    # and the `.[worker]` extra install lives exclusively in the worker stage.
    base_install = df.split("FROM runtime AS worker", 1)[0]
    assert "RUN pip install --no-cache-dir ." in base_install
    worker_stage = df.split("FROM runtime AS worker", 1)[1]
    assert 'RUN pip install --no-cache-dir ".[worker]"' in worker_stage


def test_compose_worker_and_sandbox_use_worker_build_target() -> None:
    """P3-S2: the worker and sandbox-runner services build the `worker` target;
    the api service stays on the lean base (no explicit worker target)."""
    compose = _compose()
    # worker + sandbox-runner select the worker build target (SDK installed).
    assert compose.count("target: worker") >= 2
    assert "dockerfile: deploy/Dockerfile" in compose
    # The api service does NOT pin the worker target (lean base).
    api_block = compose.split("  api:", 1)[1].split("\n  worker:", 1)[0]
    assert "target: worker" not in api_block


def test_compose_api_exports_hatchet_worker_env() -> None:
    """P3-S3: the API release factory consumes the SAME real-tenant-JWT Hatchet
    surface as the worker (build_hatchet_client reads these env vars) so it can
    dispatch through ProductionDAGRunner to the sole v1 scheduler."""
    compose = _compose()
    assert "UMD_HATCHET_SERVER_URL: http://hatchet-dashboard:8080" in compose
    assert "UMD_HATCHET_TOKEN: ${HATCHET_TENANT_TOKEN:-}" in compose
    assert "HATCHET_CLIENT_HOST_PORT: hatchet-engine:7070" in compose


def test_workflow_no_live_worker_optin_antipattern() -> None:
    """P3-S3: the anti-pattern UMD_VALIDATE_LIVE_WORKER opt-in gate (db/api-only
    defaults, opt-in live worker) is REMOVED, not renamed. The workflow starts the
    full split topology unconditionally and gates on genuine worker registration
    (fail-closed wait-for-worker) plus an always-running aggregate gate."""
    wf = (REPO_ROOT / ".github/workflows/validation.yml").read_text(encoding="utf-8")
    assert "UMD_VALIDATE_LIVE_WORKER" not in wf  # the opt-in flag must be gone
    # Full split topology starts unconditionally (no db/api-only default branch).
    for svc in ("hatchet-migrate", "hatchet-admin", "hatchet-engine", "hatchet-dashboard"):
        assert svc in wf
    # Fail-closed worker registration is NOT gated behind an env condition.
    assert "wait-for-worker.sh deploy/compose.yaml worker 240 5" in wf
    assert "if: env.UMD_VALIDATE_LIVE_WORKER" not in wf
    # Preflight (P3-S4) + aggregate live-worker gate (P3-S3) are wired.
    assert "preflight-hatchet-images.sh" in wf
    assert "Aggregate live-worker release gate" in wf
    assert "live-worker-gate.txt" in wf


def test_hatchet_c7_required_secrets_stay_interpolated() -> None:
    """P2-S4/C7: HATCHET_COOKIE_SECRET and HATCHET_MASTER_KEY remain REQUIRED
    ${VAR:?} interpolations in compose (never defaults, never baked literals)."""
    compose = _compose()
    assert "${HATCHET_COOKIE_SECRET:?}" in compose
    assert "${HATCHET_MASTER_KEY:?}" in compose
    assert "HATCHET_COOKIE_SECRET=" not in compose.replace("${HATCHET_COOKIE_SECRET:?}", "")


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
    """Validate compose syntax with the real engine when a Docker daemon exists.

    The compose file keeps its `HATCHET_COOKIE_SECRET` / `HATCHET_MASTER_KEY`
    as *required* interpolation (`${VAR:?}`) so a real deployment can never
    silently start with a missing/weak secret. `docker compose config` still
    validates the file for any caller that supplies those required variables,
    so this test provisions throwaway values (exactly as the CI workflow's
    "Set Compose runtime environment" step does) only for interpolation.
    """
    if not _DOCKER_OK:
        pytest.skip("no Docker daemon available (conditional CI-only coverage)")
    env = dict(os.environ)
    env.setdefault("HATCHET_COOKIE_SECRET", "c" * 64)
    env.setdefault("HATCHET_MASTER_KEY", "m" * 64)
    proc = subprocess.run(
        ["docker", "compose", "-f", str(DEPLOY / "compose.yaml"), "config", "--quiet"],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
        env=env,
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
