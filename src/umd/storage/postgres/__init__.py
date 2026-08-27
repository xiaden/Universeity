"""Typed relational core for PostgreSQL (transactional authority).

Phase 1 ships the structural schema. Phases 2-3 add the deterministic segment and
source repositories, the append-only semantic ledger (``SemanticLedger``), the
pure Tier-0 reducer (``CurrentStateReducer``), and the stage-run/job-audit repos.
This module defines the canonical ``metadata`` that both the Alembic structural
migration and repository code agree on.
"""

from sqlalchemy import MetaData

from . import tables  # noqa: F401  (defines all core tables + typed metadata)
from .ledger import CommitResult, LedgerConflictError, LedgerError, SemanticLedger
from .reducer import (
    CurrentReducedState,
    CurrentStateReducer,
    CurrentStateRow,
    reduce_current_state,
)
from .stage_repository import JobRunAudit, StageRunRepository

metadata: MetaData = tables.metadata

__all__ = [
    "metadata",
    "SemanticLedger",
    "CommitResult",
    "LedgerConflictError",
    "LedgerError",
    "CurrentStateReducer",
    "CurrentStateRow",
    "CurrentReducedState",
    "reduce_current_state",
    "StageRunRepository",
    "JobRunAudit",
]
