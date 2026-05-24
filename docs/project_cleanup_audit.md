# Project Cleanup Audit

Last updated: 2026-04-30

This document tracks cleanup candidates for the `umre_ops` app. It is intentionally conservative: do not delete tracked files from this list until the active Frappe import paths, DocType exports, hooks, patches, and runtime behavior have been verified.

## Current State

- Git branch: `version-16`
- Tracked files before first cleanup: 491
- Tracked files after first cleanup: 203
- **Legacy AI Cleanup**: All local GPU/CPU embedding scripts, `.venv-code-intel/`, `.cursor/`, and local telemetry have been completely removed.
- **Supabase Removal**: The local `supabase/` CLI configurations, project database templates, `umre_ops/config/` agent definitions, and local `.env` credentials have been completely quarantined to `backups/quarantine_debris/`.
- **New Architecture**: Successfully upgraded to **@vudovn/ag-kit** based multi-agent, 3-tier persistent memory (`MEMORY.md`), and discoverable workflows.

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
- Python Compile and Git status validation after cleanup:
  - Active codebase compiled with **0 errors**.
  - All statutory accounting and Frappe DocType imports validated successfully.
  - Debris and legacy components isolated with zero regression.

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
7. Run host-level `py_compile` checks to verify codebase import integrity after cleanup.

## Current Decision

First tracked cleanup deletion has been validated. Continue only with small, separately validated cleanup commits. Supabase and legacy local AI elements successfully quarantined.
