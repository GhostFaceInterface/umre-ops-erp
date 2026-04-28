# Copyright (c) 2026, Sermed Turizm and contributors
"""
Frappe migration patches run in a single DB transaction. Operations that
implicitly commit (most DDL) break the migration pipeline with ImplicitCommitError.

Policy for ``umre_ops.patches``:
* Allowed: SELECT, DML (INSERT/UPDATE/DELETE) via Frappe or parameterized SQL, ORM.
* Forbidden: DROP/CREATE/ALTER TABLE, TRUNCATE, and other schema DDL.

Use :func:`forbid_ddl` on any raw SQL string before execution.
"""
from __future__ import annotations

import re

# Case-insensitive; allow leading whitespace
_DDL = re.compile(
    r"^\s*(?:DROP|CREATE|ALTER|RENAME|TRUNCATE)\s+",
    re.IGNORECASE | re.DOTALL,
)


def forbid_ddl(sql: str) -> None:
	"""Raise if ``sql`` looks like schema / DDL. Safe for DML/SELECT only."""
	if not (sql or "").strip():
		return
	if _DDL.search(sql):
		raise RuntimeError(
			"Forbidden operation in Frappe patch (DDL / implicit commit risk). "
			f"Offending statement (first 200 chars): {sql.strip()[:200]!r}"
		)
