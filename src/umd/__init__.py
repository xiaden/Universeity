"""Universal Media Decomposer — core package.

Greenfield provenance-preserving media decomposition service. Phase 1 establishes
the repository scaffold, persistence foundation (PostgreSQL typed core + OCFL
object store), and ownership separation that later phases build on.

Layer authority (non-negotiable):
    OCFL source bytes -> Postgres evidence/segments -> append-only semantic ledger
    -> disposable, replay-only projections.
"""

__version__ = "0.1.0"
