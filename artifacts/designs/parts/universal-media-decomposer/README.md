# Universal Media Decomposer implementation plans

## Authority and handoff status

These plans implement the approved design at:

- `/workspace/Universeity/artifacts/designs/pending/DD-universal-media-decomposer.md`

The authoritative requirements are `/workspace/Universeity/Task.md` lines 1–1738. Supporting evidence is:

- `/workspace/Universeity/artifacts/designs/process/universal-media-decomposer-technology-research.md`
- `/workspace/Universeity/artifacts/designs/process/universal-media-decomposer-adversarial-log.md`
- `/workspace/Universeity/artifacts/designs/process/universal-media-decomposer-architecture-options.md`
- `/workspace/Universeity/artifacts/designs/process/universal-media-decomposer-complexity-review.md`
- `/workspace/Universeity/artifacts/designs/process/universal-media-decomposer-final-estimate.md`
- `/workspace/Universeity/artifacts/designs/process/universal-media-decomposer-pattern-enforcer-approval.md`

`DD_REQUIRED` is immutable, all T1–T8 adversarial turns are complete, and PatternEnforcer status is `AMEND_AND_PASS` with approval for downstream planning. The DD is implementation-ready and does not claim implementation completion.

## Execution order

The estimate classifies this as EPIC and requires sibling plans rather than one oversized execution context. Execute in letter order; each plan is independently readable and names its prerequisite.

| Order | Plan | Outcome | Prerequisite |
|---|---|---|---|
| A | `TASK-universal-media-decomposer-A-foundation-authority.md` | Repository, storage, domain, locators, semantic authority, and ingestion command foundation | None |
| B | `TASK-universal-media-decomposer-B-jobs-text-image.md` | Single-source DAG execution plus real text/image pipelines | A |
| C | `TASK-universal-media-decomposer-C-av-subtitles-providers.md` | Secure sandbox, model contracts, audio/video/subtitle pipelines | B |
| D | `TASK-universal-media-decomposer-D-resolution-query-api.md` | Resolution/alignment, projections, structured/semantic query, search, and REST | C |
| E | `TASK-universal-media-decomposer-E-operations-docs-deployment.md` | Operational hardening, observability, packaging, deployment, documentation, and extension gates | D |
| F | `TASK-universal-media-decomposer-F-validation-release.md` | Full fixture matrix, replay/E2E/security/operational validation, final adversarial review and repair gate | E |

No v1 plan introduces a semantic graph database, RDF authority/projection, dedicated vector database, XTDB witness, or Dagster scheduler. Their interfaces and measured promotion triggers remain documented extension paths.

## Shared contracts

`CONTRACTS.md` is the binding cross-plan interface ledger. A worker may refine internal names only if the externally visible behavior and signatures remain compatible, and must annotate any deviation in the relevant plan.
