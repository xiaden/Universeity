# Universal Media Decomposer implementation plans

## Authority and handoff status

These plans implement the approved design at:

- `/workspace/Universeity/artifacts/designs/pending/DD-universal-media-decomposer-ci-repair.md` for the CI-repair release-gate work (the historical A–F design remains at the earlier path).

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

## Remediation order after historical Plans A–F

Plans A–F above are historical completed work and remain preserved. The authoritative Task.md gaps are remediated in this dependency order:

| Order | Plan | Outcome | Prerequisite |
|---|---|---|---|
| G | `TASK-universal-media-decomposer-G-production-runner-api.md` | Real stage registry, durable production runner, and truthful API ingestion | A–F historical baseline |
| H | `TASK-universal-media-decomposer-H-local-providers-modalities.md` | Validated self-hostable ASR plus real provider/modality composition | G |
| I | `TASK-universal-media-decomposer-I-hatchet-worker-integration.md` | Pinned operational Hatchet scheduler and bound worker callbacks | G (H may proceed alongside) |
| J | `TASK-universal-media-decomposer-J-api-boundary-ci-release.md` | Public-boundary E2E, hosted Docker CI, measured docs, final adversarial release gate | H and I |

## CI-repair supersession order

The approved CI-repair DD and PatternEnforcer approval identify the remaining G–J release seams as one new, sequential repair family. Execute K after the preserved G/H/I foundations and the completed J Phases 1–2 baseline; K owns the open production, deployment, hosted-evidence, documentation, QA, and DoD closure work. It supersedes only unresolved/open portions of G/H/I and unfinished J Phases 3–4, so no historical plan is re-executed and no duplicate scheduler, worker, E2E, or DoD authority is created.

| Order | Plan | Outcome | Prerequisite |
|---|---|---|---|
| K | `TASK-universal-media-decomposer-K-ci-repair-release-gate.md` | Production runtime/API wiring, split Hatchet/live callbacks, hosted toolchain and fail-closed gate, HTTP-only heterogeneous proof, post-green docs, final QA and 35-row DoD matrix | Preserved G/H/I foundations; J Phases 1–2 baseline |

The remediation does not weaken prior contracts or add a competing scheduler. Hatchet remains the sole v1 scheduler; reference providers and unvalidated platform features are disclosed with explicit capability statuses and release evidence.

## Semantic-capability repair order

The concrete semantic repair family follows the preserved A–K foundation/remediation plans and is executed sequentially:

| Order | Plan | Outcome | Prerequisite |
|---|---|---|---|
| L | `TASK-universal-media-decomposer-L-semantic-format-dispatch.md` | Format-aware production TXT/Markdown/EPUB/PDF dispatch, provenance, deterministic IDs, bounded EPUB extraction, and full-DAG StageWork acceptance | Preserved A–K foundations |
| M | `TASK-universal-media-decomposer-M-semantic-provider-contract.md` | Typed deterministic/provider-backed semantic text analysis with honest degradation | L |
| N | `TASK-universal-media-decomposer-N-multi-entity-resolution.md` | Multiple canonical entities, alias/mention mappings, ambiguity, locks, overrides, and idempotent resolution | L, M |
| O | `TASK-universal-media-decomposer-O-rich-reconciliation-multiedge-query.md` | Rich ledger reconciliation, replay-built active relationship edges, bounded query/search reads | L, M, N |
| P | `TASK-universal-media-decomposer-P-semantic-book-fixture-parity-e2e.md` | Realistic small-book fixture, generic Alexandria 2a–2f parity matrix, production/public E2E | L–O |
| Q | `TASK-universal-media-decomposer-Q-semantic-capability-verification.md` | Full static, unit, PostgreSQL, StageWork, public E2E, Docker/hosted and immutable-ledger verification | L–P |
| R | `TASK-universal-media-decomposer-R-provider-observation-reconciliation-promotion.md` | Evidence-backed provider observations reach existing reconciliation, replay/current/edge/search/query surfaces with exact provenance and honest degradation | Q |
| S | `TASK-universal-media-decomposer-S-semantic-identity-and-relationship-repair.md` | Ledger-first canonical identity, human-readable labels/aliases, cross-source membership/ambiguity, validated relationship predicates, and public semantic E2E | R and the completed L–P foundations; Q remains historical verification evidence |
| T | `TASK-universal-media-decomposer-T-semantic-identity-boundary-hardening.md` | Single-authority resolution, stable evidence-backed identity anchors, strict same-name/fallback semantics, replay-derived scoped entity/search reads, unified manual establishment, typed generic relationships, public A/B/C full-DAG acceptance, and hosted live-Hatchet release proof | S |

Plans L–T repair existing semantic seams only. They do not amend or re-execute Plan K, add a semantic graph database, copy Alexandria/audiobook state, introduce a second scheduler, or change OCFL/ledger authority. Plan S specifically keeps the SQL `entity` table from becoming a second semantic authority, preserves Plan N Option B string refs and Plan R provider hydration. Plan T supersedes Plan S's weaker identity/search/manual-creation/relationship behavior only where required by its immutable follow-up ledger and does not treat the historically gated Docker/live-Hatchet result as completion evidence.

No v1 plan introduces a semantic graph database, RDF authority/projection, dedicated vector database, XTDB witness, or Dagster scheduler. Their interfaces and measured promotion triggers remain documented extension paths.

## Shared contracts

`CONTRACTS.md` is the binding cross-plan interface ledger. A worker may refine internal names only if the externally visible behavior and signatures remain compatible, and must annotate any deviation in the relevant plan.
