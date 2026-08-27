"""Deployment packaging, migration startup, and readiness helpers (Plan E, P2).

* :mod:`umd.deploy.startup` — Alembic migration execution and the componentwise
  startup-ordering readiness probe (Postgres -> migrations -> OCFL).

Docker/Compose and the operational security artifacts (dependency pins, CVE
watches, license/AGPL review, sandbox host profile) live under ``deploy/`` at the
repository root as the deployment deliverable surface.
"""
