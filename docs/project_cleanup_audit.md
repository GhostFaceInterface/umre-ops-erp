# Project Cleanup Audit

Last updated: 2026-04-30

This document tracks cleanup candidates for the `umre_ops` app. It is intentionally conservative: do not delete tracked files from this list until the active Frappe import paths, DocType exports, hooks, patches, and runtime behavior have been verified.

## Current State

- Git branch: `version-16`
- Tracked files: 489
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

## High-Risk Cleanup Candidates

The repository contains repeated tracked package trees under nested `umre_ops` paths:

- `umre_ops/umre_ops/umre_ops/**`: 288 tracked files
- `umre_ops/umre_ops/umre_ops/umre_ops/**`: 223 tracked files

Repeated framework files also exist at multiple depths:

- `umre_ops/umre_ops/hooks.py`
- `umre_ops/umre_ops/umre_ops/hooks.py`
- `umre_ops/umre_ops/umre_ops/umre_ops/hooks.py`
- `umre_ops/umre_ops/umre_ops/umre_ops/umre_ops/hooks.py`
- `umre_ops/umre_ops/umre_ops/umre_ops/umre_ops/umre_ops/hooks.py`

And matching repeated `modules.txt` files at the same depths.

Do not delete these yet. Some may be accidental copies, but deleting nested Frappe files without proving the active import path can break hooks, DocTypes, patches, or service imports.

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

No tracked cleanup deletions are approved yet. The next cleanup step should be a read-only duplicate/import-path investigation, then a small quarantine branch commit only after validation.
