# Project Cleanup Audit

Last updated: 2026-04-30

This document tracks cleanup candidates for the `umre_ops` app. It is intentionally conservative: do not delete tracked files from this list until the active Frappe import paths, DocType exports, hooks, patches, and runtime behavior have been verified.

## Current State

- Git branch: `version-16`
- Tracked files before first cleanup: 491
- Tracked files after first cleanup: 203
- AI code intelligence infrastructure is committed and pushed in `f285494`.
- Codex MCP config has been added to `/Users/boe747/.codex/config.toml`.
- Cursor MCP config is tracked at `.cursor/mcp.json`.
- Supabase code index is incremental by default.

## Confirmed Safe Generated Files

These are generated runtime/cache artifacts and are not tracked by Git:

- `.venv-code-intel/`
- `scripts/__pycache__/`
- `umre_ops/**/__pycache__/`

Cleanup rule: safe to remove locally when needed, but they do not need a Git commit.

## Completed Cleanup

Validated and removed the dead nested tree:

- `umre_ops/umre_ops/umre_ops/**`: removed 288 tracked duplicate files.

Validation evidence:

- Runtime import path inside the bench resolves to:
  - app package: `/workspace/development/frappe-bench/apps/umre_ops/umre_ops/__init__.py`
  - hooks: `/workspace/development/frappe-bench/apps/umre_ops/umre_ops/hooks.py`
  - service: `/workspace/development/frappe-bench/apps/umre_ops/umre_ops/umre_ops/services/expense_service.py`
- Canonical business service import works:
  - `umre_ops.umre_ops.services.expense_service`
- Dead duplicate service import fails as expected:
  - `umre_ops.umre_ops.umre_ops.services.expense_service`
- `bench --site development.localhost migrate` passed.
- `bench build --app umre_ops` passed.
- `expense_service.get_operational_expense_taxonomy` passed.
- `dashboard_service.get_tour_cost_breakdown` passed.
- Supabase index sync after cleanup:
  - files processed: 176
  - chunks: 638
  - stale rows deleted: 127
  - rows inserted: 96
  - active DB rows: 550
  - immediate no-change rerun inserted: 0

## Remaining Cleanup Candidates

Remaining repeated framework-looking files:

- `umre_ops/umre_ops/hooks.py`
- `umre_ops/umre_ops/modules.txt`

These are now inside the active business package path and should not be removed in the same cleanup pass. Investigate separately, because `umre_ops.umre_ops.*` is the active service/import namespace.

No deeper tracked `umre_ops/umre_ops/umre_ops/**` files remain.

## Cleanup Procedure

1. Create a dedicated cleanup branch.
2. Capture baseline checks:
   - `bench --site <site> migrate`
   - `bench --site <site> run-tests --app umre_ops`
   - targeted import checks for `umre_ops.umre_ops.services.*`
3. Identify the active package root used by Frappe.
4. Compare duplicate trees by file hash and by DocType/module role.
5. Move confirmed-dead files in small commits.
6. Re-run migration/tests after each cleanup commit.
7. Re-index Supabase with `python scripts/index_codebase.py` after cleanup.

## Current Decision

First tracked cleanup deletion has been validated. Continue only with small, separately validated cleanup commits.
