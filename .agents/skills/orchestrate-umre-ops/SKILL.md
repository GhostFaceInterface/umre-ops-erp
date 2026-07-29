---
name: orchestrate-umre-ops
description: Orchestrate token-conscious Codex subagents for the Umre Ops ERPNext/Frappe repository. Use for repository health audits, accounting-integrity reviews, schema or data migrations, cross-layer bugs, major features, risky refactors, or changes spanning DocTypes, services, client code, patches, and tests. Do not use for a straightforward one-file edit or a narrow question that the main agent can answer directly.
---

# Orchestrate Umre Ops

Use the smallest agent team that materially improves confidence. Keep the main thread focused on requirements, decisions, and the final diff.

## 1. Classify the task

- **S0 — narrow:** one clear file or question. Use no subagent.
- **S1 — uncertain path:** spawn `repo_explorer`; continue after its concise map.
- **S2 — cross-layer change:** spawn two relevant read-only agents in parallel, then one `implementation_worker`.
- **S3 — financial/schema risk or health audit:** spawn up to three relevant read-only agents, synthesize their evidence, then use one writer if changes were requested.

Never spawn agents merely to fill concurrency. Cap active subagents at three.

## 2. Build bounded task packets

Give every subagent only:

1. one concrete objective;
2. explicit files/directories or a search boundary;
3. non-negotiable constraints;
4. an output contract of at most eight findings;
5. whether edits are forbidden.

Require file and symbol references. Ask for conclusions and verification evidence, not raw logs. Do not forward the full chat or unrelated agent output.

Do not read `docs/` or `umre_ops/umre_ops/docs/` unless the user has authorized it or a specific document is indispensable. Never bulk-load those folders.

## 3. Select roles

- Use `repo_explorer` for entry points, imports, hooks, duplicate paths, and change surface.
- Use `frappe_architect` for DocType lifecycle, permissions, hooks, migrations, Desk/API behavior, and Frappe conventions.
- Use `finance_guardian` for ledger semantics, payments, expenses, currencies, cost allocation, rounding, cancellation, and idempotency.
- Use `test_analyst` for test discovery, fixture/site needs, regression cases, and the cheapest reliable command sequence.
- Use `implementation_worker` only after the failure mode or desired design is clear.
- Use `change_reviewer` after implementation for an independent, read-only review.

Prefer `repo_explorer` and `test_analyst` for cheap supporting work. Reserve deeper agents for ambiguity, financial integrity, schema changes, and final review.

## 4. Execute in gates

### Evidence gate

Run independent read-only investigations in parallel. Wait for all required results. Reconcile disagreements against source code; do not decide by majority.

### Decision gate

Summarize the intended behavior, affected paths, invariants, smallest change, and validation plan. If the user requested diagnosis only, stop here without editing.

### Single-writer gate

Assign one bounded implementation task to `implementation_worker`, or implement in the main thread. Never allow parallel writers on overlapping files. Preserve all pre-existing worktree changes.

### Verification gate

Run the narrowest relevant checks. For financial, schema, permission, or migration changes, ask `change_reviewer` for an independent pass and use `test_analyst` only when test setup or failures need separate analysis.

## 5. Stop conditions

Stop spawning when the path and invariant are established, remaining work is sequential, agents would inspect the same evidence, or coordination would cost more than the task. Interrupt an agent that has drifted outside scope.

Return one consolidated result with: outcome, evidence, files changed, checks run, unresolved risks, and any production-safe next step.
