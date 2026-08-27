# =============================================================================
# Universal Media Decomposer — developer/CI commands
# Phase 1: reproducible repository + persistence foundation.
#
# Requires Python 3.13+ and a local venv (.venv). A live PostgreSQL server is
# needed only for the `postgres`-marked tests and `migrate` targets; all other
# targets run without a database.
# =============================================================================

PY        := .venv/bin/python
PIP       := .venv/bin/pip
PYTEST    := .venv/bin/pytest
RUFF      := .venv/bin/ruff
MYPY      := .venv/bin/mypy
ALEMBIC   := .venv/bin/alembic

.DEFAULT_GOAL := help

export UMD_OCFL__ROOT ?= .ocfl-root

# --------------------------------------------------------------------------
.PHONY: help
help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-22s\033[0m %s\n", $$1, $$2}'

.PHONY: install
install: ## Create .venv and install all dependencies (pinned policy)
	python3 -m venv .venv
	$(PIP) install --upgrade pip
	$(PIP) install -e ".[dev]"

.PHONY: lint
lint: ## Lint with ruff (zero errors required)
	$(RUFF) check src tests

.PHONY: lint-fix
lint-fix: ## Auto-fix lint issues
	$(RUFF) check --fix src tests

.PHONY: format
format: ## Format with ruff
	$(RUFF) format src tests

.PHONY: typecheck
typecheck: ## Static type check with mypy (strict)
	$(MYPY) src

.PHONY: test
test: ## Run the full test suite (unit + OCFL fixity + config)
	$(PYTEST) -q

.PHONY: test-postgres
test-postgres: ## Run Postgres-dependent migration/ownership tests (needs live server)
	UMD_TEST_POSTGRES=true $(PYTEST) -q -m postgres

.PHONY: check
check: lint typecheck test ## Full static + unit gate (no DB)

.PHONY: migrate
migrate: ## Apply structural migrations to the configured database
	$(ALEMBIC) upgrade head

.PHONY: migrations-check
migrations-check: ## Verify migrations are current vs. configured database
	$(ALEMBIC) check

.PHONY: db-up
db-up: ## Start a local ephemeral PostgreSQL for development (Ubuntu/Debian)
	sudo pg_ctlcluster 17 main start || true

.PHONY: db-createdb
db-createdb: ## Create umd / umd_test roles+databases (local dev)
	sudo -u postgres psql -c "CREATE ROLE umd LOGIN PASSWORD 'umd' CREATEDB SUPERUSER;" || true
	sudo -u postgres psql -c "CREATE DATABASE umd OWNER umd;" || true
	sudo -u postgres psql -c "CREATE DATABASE umd_test OWNER umd;" || true