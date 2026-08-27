"""Audit: explanations and job-run audit stream, separate from semantic replay.

``AuditService.explain`` answers why/current/prior/change-cause from the ledger and
Tier-0 state. ``JobRunAudit`` records the operational job-run stream in its own
table — never a semantic-replay input.
"""

from .service import AuditService, ChangeExplanation

__all__ = ["AuditService", "ChangeExplanation"]
