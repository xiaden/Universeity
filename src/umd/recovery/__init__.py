"""Independent backup / restore / replay recovery capability (Plan E, P2-S3).

The two authorities are backed up and restorable *independently* of each other
(per the DD "Packaging and persistence"): the append-only PostgreSQL semantic
ledger + Tier-0 ``current_state`` on one hand, and the OCFL immutable source/
derived byte store (inventories + content) on the other. Restore verification
replays the ledger from ``seq=0`` and validates OCFL fixity.

* :mod:`umd.recovery.postgres_backup` — snapshot the ``semantic_event`` ledger
  (all retained envelope columns) and the Tier-0 ``current_state`` to portable
  JSONL; restore reloads the ledger preserving ``seq``/``causation_id`` and then
  replays ``current_state`` from ``seq=0`` through the ONE shared
  :class:`~umd.storage.postgres.reducer.CurrentStateReducer`, asserting the
  replayed Tier-0 is checksum-equivalent to the backed-up Tier-0.
* :mod:`umd.recovery.ocfl_backup` — snapshot the OCFL storage root (the
  ``0=ocfl_1.1`` declaration, layout, per-object ``inventory.json`` and
  ``content/`` bytes); restore recreates a root and validates fixity on every
  object via ``SourceStore.verify_fixity``.

The recovery surface never weakens the append-only/consistency invariants: it
uses the existing single-writer reducer and the existing content-addressed OCFL
adapter, and it is exercised by real tests over live Postgres + the filesystem
OCFL substrate (no Docker required).
"""
