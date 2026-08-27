"""P3-S3: AuditService.explain current/prior/change-cause (postgres)."""

from __future__ import annotations

import pytest
import sqlalchemy as sa

from umd.application.commands import SemanticCommandService
from umd.audit.service import AuditService
from umd.storage.postgres.ledger import SemanticLedger

pytestmark = pytest.mark.postgres


def test_explain_current_prior_and_change_cause(umd_db: sa.Engine) -> None:
    ledger = SemanticLedger(umd_db)
    svc = SemanticCommandService(ledger)

    # 1) machine assertion (the prior value)
    svc.assert_semantic(
        predicate_code="SPEAKS",
        subject_ref="e:1",
        object_ref="utter:machine",
        confidence=0.6,
        state="PROBABLE",
        scope="CONTINUITY",
        actor="worker-asr",
    )
    # 2) a user override (the current value + change cause)
    svc.record_override(
        subject_ref="e:1",
        predicate="SPEAKS",
        object_ref="utter:user",
        actor="user@example",
        evidence=["locator://e:1/audio/t=0,10"],
        reason="manual transcription correction",
    )

    audit = AuditService(umd_db)
    explanation = audit.explain("e:1#SPEAKS")

    assert explanation.subject == "e:1"
    assert explanation.predicate == "SPEAKS"
    # current reflects the user override
    assert explanation.current["object_ref"] == "utter:user"
    assert explanation.current["authority"] == "USER_OVERRIDE"
    # prior reflects the machine assertion
    assert explanation.prior["object_ref"] == "utter:machine"
    # actor + evidence + change cause
    assert explanation.actor == "user@example"
    assert "locator://e:1/audio/t=0,10" in explanation.evidence
    assert explanation.change_cause is not None
    assert explanation.change_cause.get("reason") == "manual transcription correction"
    assert len(explanation.history) >= 2


def test_explain_with_as_of_constrains_history(umd_db: sa.Engine) -> None:
    ledger = SemanticLedger(umd_db)
    svc = SemanticCommandService(ledger)
    svc.assert_semantic(
        predicate_code="SPEAKS",
        subject_ref="e:2",
        object_ref="utter:1",
        scope="CONTINUITY",
        actor="w1",
    )
    audit = AuditService(umd_db)
    ex = audit.explain("e:2#SPEAKS")
    assert ex.current["object_ref"] == "utter:1"
    assert ex.actor == "w1"
