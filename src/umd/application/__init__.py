"""Application: command handlers, transactions, idempotency, read-your-writes tokens.

The semantic command handler (``SemanticCommandService``) routes every semantic
mutation through the append-only ledger — no command writes a projection directly.
The ingestion command path streams source bytes to OCFL and emits ``SourceIngested``.
"""

from .commands import SemanticCommandService

__all__ = ["SemanticCommandService"]
