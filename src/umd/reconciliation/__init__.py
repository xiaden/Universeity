"""Deterministic semantic reconciliation (Plan O Phase 1).

The :mod:`~umd.reconciliation.reconciler` module implements the binding
contract ``SemanticReconciler.reconcile(input) -> list[SemanticEvent]``
(CONTRACTS.md:78): a pure, deterministic, testable function that maps validated
typed observations plus resolved entity/mention mappings into rich typed
semantic assertions routed through the ledger command path.
"""

from umd.reconciliation.reconciler import ReconciliationInput, SemanticReconciler

__all__ = ["ReconciliationInput", "SemanticReconciler"]
