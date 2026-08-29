# PatternEnforcer Approval — Plan K Netns Workflow Amendment

**Status:** DONE / PASS  
**Pattern:** Universal Media Decomposer Plan K workflow-only netns/startup amendment  
**Reviewed:** 2026-08-29  
**Decision:** Approved for downstream Plan K implementation handoff. The amended DD closes the three prior MAJOR gaps and preserves the complete workflow, release-gate, requirement-ledger, and forbidden-change contracts. This is a design approval only; no DD, plan, workflow, code, or test implementation was performed.

## Reviewed artifacts

- `artifacts/designs/pending/DD-universal-media-decomposer-plan-k-netns-workflow-amendment.md` (249 lines)
- `artifacts/designs/process/ADVERSARIAL-universal-media-decomposer-plan-k-netns-workflow-validated.md` (T1–T8, canonical patterns, Validation Manifest)
- `artifacts/designs/process/universal-media-decomposer-plan-k-netns-architecture-options.md` (Option D)
- `artifacts/designs/process/universal-media-decomposer-plan-k-netns-complexity-review.md` (S1–S9)
- `artifacts/designs/process/universal-media-decomposer-plan-k-netns-final-estimate.md`
- `artifacts/designs/pending/DD-universal-media-decomposer-ci-repair.md` (approved architecture anchor)
- `artifacts/plans/pending/TASK-universal-media-decomposer-K-ci-repair-release-gate.md` (Plan K)
- `Task.md` §32 and §40, items 1–35
- `artifacts/designs/parts/universal-media-decomposer/CONTRACTS.md` §§58–67
- `artifacts/logs/support-researcher.log.jsonl` L8–L9
- `artifacts/logs/support-debugger.log.jsonl` L8–L12
- `artifacts/logs/support-librarian.log.jsonl` L19–L21
- `src/umd/jobs/hatchet.py` lines 209–230 and 417–428 (current change sites)

## Verification result

The amended DD is internally consistent and materially complete for the requested workflow-design decision. It explicitly distinguishes design contracts from implementation/release proof: the current source still contains the old callback and non-durable registration sites, and Plan K must implement and prove their replacements before Phase 6. That is an intentional handoff condition, not a defect in this design artifact.

## MAJOR gap closure

### MAJOR-1 — v1 callback arity, direct input, and real durable proof

**PASS.** DD lines 49–67 require the pinned `hatchet-sdk==1.38.1` v1 callback signature `handler(input, ctx)`, direct input (no v0 `{"input": ...}` wrapper), direct v1 manifest handling, invocation of `DurableStageExecutor`, and callback-owned durable persistence of `stage_run`, `StageCompleted`, and operational audit records. Registration/readiness/submission alone cannot pass. AT-16 at lines 174–178 requires:

- hermetic invocation with `(input, ctx)` and direct v1 input;
- real-SDK-shaped rejection of one-argument and v0-wrapped handlers;
- executor/store-backed completion and durable rows; and
- hosted observation of the callback and resulting rows.

The evidence is accurately anchored to `support-researcher.log.jsonl:L9`, hosted run `33229130339` / job `99038602321`, and the current implementation site `src/umd/jobs/hatchet.py:209-230`. The cited current one-argument `handler(payload)` is correctly treated as an Exec-Manager implementation target, not as satisfied behavior.

### MAJOR-2 — schedulable tenant partition eligibility and consistency

**PASS.** DD lines 69–78 require deterministic discovery of exactly one setup-created or scheduler-eligible tenant with non-null `schedulerPartitionId` and `workerPartitionId`; zero matches, multiple matches, or null partitions fail closed. The selected tenant and both partition IDs are recorded. Before execution, JWT tenant, worker tenant, workflow tenant, and submitted-task tenant must be identical. Readiness or registration without those assertions is insufficient. AT-17 at lines 180–183 carries the same requirements.

The evidence is accurately anchored to `support-debugger.log.jsonl:L8-L12` and hosted run `33229130339` / job `99038602321`, including the queued/unassigned internal-tenant failure. This correctly treats tenant eligibility as an independent hosted execution contract, not netns evidence.

### MAJOR-3 — durable task registration and hosted `is_durable=true`

**PASS.** DD lines 80–88 require every release `umd-<stage>` task to use the pinned SDK durable registration surface:

```text
client.durable_task(name=wf_name)(handler)
```

The DD explicitly forbids substituting `client.task(...)` and requires hosted DB/engine evidence that every registered and submitted task has `v1_task.is_durable=true`. Callback-owned Postgres rows are expressly additional evidence, not proof of Hatchet durable scheduling. AT-18 at lines 185–188 carries this independently.

The evidence is accurately anchored to `support-debugger.log.jsonl:L9` and `src/umd/jobs/hatchet.py:417-428`, where the current non-durable registration is the Exec-Manager change site.

### AT-19 and phase mapping

**PASS.** AT-19 at DD lines 190–193 composes AT-16, AT-17, and AT-18 with AT-1 through AT-15 as mandatory, non-skippable hosted checks. Failure, skip, missing evidence, readiness-only proof, or configured-unavailable outcome remains release-blocking and cannot be hidden by netns retry or a later gate.

The mapping at lines 219–235 is explicit and pre-Phase-6:

- callback/direct-input/executor/durable completion → Plan K P2-S4/P2-S5 and P3-S3 → AT-16;
- tenant eligibility, partition recording, and identity consistency → P2-S4/P2-S5 and P3-S3 → AT-4/AT-17;
- durable registration and hosted `v1_task.is_durable=true` → P2-S5 and P3-S3 → AT-18;
- all three contracts must pass before Phase 6.

## Invariant checks

### L1–L9

**PASS.** DD lines 200–215 reproduce the original request and immutable L1–L9 ledger verbatim. In particular, L9 remains full split Hatchet topology, real callbacks, mandatory hosted validation, no skips/stubs/fake readiness, and no second scheduler. The amendment is explicitly workflow-only and introduces no service, scheduler, network, API, data-store, semantic, or execution authority.

### S1–S9

**PASS.** DD lines 145–154 carry all canonical complexity findings: errexit-safe PIPESTATUS shielding, two-phase startup, scoped Bash, one shared bounded retry budget, capability snapshot rather than readiness, inspect-based one-shot classification, preserved JWT boundary plus tenant eligibility, sandbox parity/security treatment, and phase/attempt evidence naming.

### U1–U8 and Q1–Q8

**PASS AS CARRIED.** DD lines 156–167 retain every unresolved risk and human question without silently waiving or converting any into a skip. Q1 (sandbox role/security), Q2 (R18 tier-1 retrieval), and the remaining bounded parameter/security approvals remain visible. These are intentionally carried execution/finalization gates, not omissions from the DD. R18 is explicitly coordination-tier only at lines 195–196 and cannot close the release gate until tier-1 retrieval.

### AT-1–AT-15

**PASS AS PRESERVED.** DD lines 169–172 state that AT-1 through AT-15 remain unchanged, mandatory, and not conditionalized by AT-16 through AT-19. AT-11 remains conditional only if a job-wide shell default is changed. The new execution contracts extend rather than weaken the prior acceptance set.

### Forbidden changes

**PASS.** DD lines 39–42 and 137–139 reject Hatchet Lite, host networking, DinD, host Docker socket mounts, second scheduler, blanket privilege/security bypass, optional mandatory gates, fake readiness, blanket retry, and Compose `--wait` as the sole gate. The DD also preserves native hosted Docker, ordinary service-name networking, the exact eight-service split, callback-owned completion, mandatory sandbox/security handling, and fail-closed evidence gates. No forbidden architecture, topology, scheduler, authority, or implementation change is proposed.

### Task.md and upstream consistency

**PASS.** The DD preserves Task.md authority and maps the amendment to Plan K without weakening Task.md §40. The anchor DD remains the product/deployment architecture authority; this amendment only adds workflow sequencing, classification, evidence, and release-gate contracts. The architecture report's Option D, complexity S1–S9, final estimate, adversarial canonical patterns, and support findings are reflected without contradiction.

## Open execution gates (not material DD gaps)

The following remain deliberately visible and release-blocking where applicable:

- Q1–Q8 human decisions/sign-offs, including sandbox security and bounded workflow parameters;
- R18 (`33228898244`, job `99037936832`) tier-1 GitHub retrieval before final ledger closure;
- actual Exec-Manager implementation of the v1 callback and durable registration contracts;
- hosted proof of callback execution, durable Hatchet task rows, tenant/partition consistency, callback-owned UMD rows, and all existing topology/sandbox/HTTP/restart/evidence gates.

The DD does not claim these gates are already satisfied. It correctly defines them as prerequisites and hard-failure conditions.

## Final verdict

```yaml
status: DONE
approval: PASS
coverage: PASS
internal_consistency: PASS
requirement_conformance: PASS
immutable_L1_L9: PASS
S1_S9: PASS
U1_U8: PASS_AS_CARRIED
Q1_Q8: PASS_AS_CARRIED
AT_1_AT_15: PASS_PRESERVED
AT_16: PASS_DEFINED_AND_MAPPED
AT_17: PASS_DEFINED_AND_MAPPED
AT_18: PASS_DEFINED_AND_MAPPED
AT_19: PASS_DEFINED_AND_COMPOSED
phase_mapping: PASS
forbidden_changes: NONE_PROPOSED
material_gaps: []
release_gate: REMAINS_CLOSED_PENDING_HOSTED_PROOF
```

**Handoff:** Exec-Manager may implement only the amended Plan K workflow/release-gate steps, must complete AT-16/AT-17/AT-18 before Phase 6, and must not interpret this design approval as hosted release approval. No DD, plan, workflow, code, or test file was modified by this review; this approval artifact is the sole write.
