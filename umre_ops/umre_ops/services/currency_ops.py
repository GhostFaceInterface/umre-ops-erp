# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
"""
Operational USD baseline — ERPNext master data helpers (Phase 2 / Step 1).

Umre Ops reports and the Operasyon dashboard intentionally use **USD** as the
canonical operational currency (`dashboard_service.CURRENCY`). Mis-formatting can
come from **wrong `tabAccount.account_currency`** (e.g. TRY vs USD) when
**account_currency** does not match operational reality — fix data in
:func:`bulk_fix_account_currency`. Desk display-only hacks are not sufficient.
"""
from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import cint

OPERATIONAL_CURRENCY = "USD"


def _pick_default_company() -> str | None:
	"""Prefer Global Defaults default company; else first Company row."""
	name = frappe.defaults.get_global_default("default_company") or frappe.db.get_single_value(
		"Global Defaults", "default_company"
	)
	if name and frappe.db.exists("Company", name):
		return name
	row = frappe.db.sql("SELECT name FROM `tabCompany` ORDER BY creation ASC LIMIT 1")
	return row[0][0] if row else None


def normalize_currency_usd_master() -> dict[str, Any]:
	"""Ensure `Currency` doc **USD** has symbol `$` (fixes odd symbols e.g. L)."""
	out: dict[str, Any] = {"currency": OPERATIONAL_CURRENCY, "symbol_corrected": False}
	if not frappe.db.exists("Currency", OPERATIONAL_CURRENCY):
		out["error"] = "missing_currency_master"
		return out
	curr = frappe.db.get_value(
		"Currency", OPERATIONAL_CURRENCY, ["symbol", "symbol_on_right"], as_dict=True
	)
	assert curr is not None
	sym = (curr.get("symbol") or "").strip()
	updates = {}
	if sym != "$":
		updates["symbol"] = "$"
	if cint(curr.get("symbol_on_right")):
		updates["symbol_on_right"] = 0
	if updates:
		frappe.db.set_value("Currency", OPERATIONAL_CURRENCY, updates, update_modified=False)
		out["symbol_corrected"] = True
	return out


def set_company_default_currency_usd(
	*,
	company_name: str | None = None,
	all_companies: bool = False,
) -> dict[str, Any]:
	"""Set `default_currency` on Company row(s) to USD."""
	updated: list[str] = []
	skipped: list[str] = []
	if all_companies:
		names = frappe.get_all("Company", pluck="name") or []
	else:
		c = company_name or _pick_default_company()
		names = [c] if c else []
	for name in names:
		if not name:
			continue
		cur = frappe.db.get_value("Company", name, "default_currency") or ""
		if (cur or "").upper() != OPERATIONAL_CURRENCY:
			frappe.db.set_value(
				"Company", name, "default_currency", OPERATIONAL_CURRENCY, update_modified=False
			)
			updated.append(name)
		else:
			skipped.append(name)
	return {"updated": updated, "unchanged": skipped}


@frappe.whitelist()
def bootstrap_operational_usd_baseline(all_companies: int | bool = False) -> dict[str, Any]:
	"""Desk/RPC: normalize USD Currency master + Company default_currency (USD).

	Run once after deploying Phase 2 Step 1. **System Manager** only.

	set_all_companies=1 updates every Company; default is **default Company only**.
	"""
	frappe.only_for("System Manager")
	all_c = bool(cint(all_companies))
	norm = normalize_currency_usd_master()
	co = set_company_default_currency_usd(all_companies=all_c)
	frappe.db.commit()
	frappe.clear_cache()
	return {
		"ok": 1,
		"operational_currency": OPERATIONAL_CURRENCY,
		"currency_master": norm,
		"companies": co,
		"hint": _(
			"Verify: Company default currency USD; Currency USD symbol $. "
			"Clear cache / hard-reload Desk if widgets still cache old symbols."
		),
	}


# ---------------------------------------------------------------------------
# Account ledger currency (tabAccount.account_currency) — operational USD
# ---------------------------------------------------------------------------

_PROTECTED_ACCOUNT_TYPES_FOR_CURRENCY = frozenset({"Bank", "Cash", "Tax"})

# TRY → USD only for these P&L / expense roles (operational costing).
_TRY_CONVERT_EXPENSE_TYPES = frozenset({
	"Direct Expense",
	"Indirect Expense",
	"Expense Account",
	"Cost of Goods Sold",
})

# NULL → USD also for income / receivable leaf accounts (same company books in USD).
_NULL_USD_INCOME_AR_TYPES = frozenset({
	"Income Account",
	"Receivable",
})


@frappe.whitelist()
def bulk_fix_account_currency(company: str | None = None) -> dict[str, Any]:
	"""Align **leaf** `Account.account_currency` with operational USD rules (data model).

	**Does not** change ERPNext display formatters — updates **`tabAccount`** rows only.

	Rules (for ``company``):

	* **Never** change rows with ``account_type`` in **Bank / Cash / Tax** (multi-currency /
	  statutory tax as configured).
	* **NULL / empty** ``account_currency``: set **USD** if ``account_type`` is one of the
	  operational expense types, **or** (Income Account / Receivable) for leaf booking.
	  **Umre Ops Settings** ERPNext Account links were removed in Phase 2a — mapping set is empty.
	* **TRY**: set **USD** only ``account_type`` is in **Direct / Indirect / Expense Account / COGS**.
	* Other currencies (EUR, …) are left untouched (see ``skipped_sample`` with ``reason: leave_currency``).

	Idempotent: safe to re-run.

	Use from bench::

	    bench --site SITE execute \\
	      umre_ops.umre_ops.services.currency_ops.bulk_fix_account_currency \\
	      --kwargs "{'company': 'Sermed Turizm'}"

	Returns counts and sample row lists for audit logs.
	"""
	frappe.only_for("System Manager")
	if not company:
		frappe.throw(_("company is required (e.g. '{0}').").format("Sermed Turizm"))
	company = company.strip()
	if not frappe.db.exists("Company", company):
		frappe.throw(_("Company {0} does not exist.").format(company))

	mapped: set[str] = set()
	rows = frappe.db.sql(
		"""
		SELECT name, account_type, account_currency, IFNULL(is_group, 0) AS is_group,
		       IFNULL(disabled, 0) AS disabled
		FROM `tabAccount`
		WHERE company=%s
		""",
		(company,),
		as_dict=True,
	)

	null_to_usd: list[str] = []
	try_to_usd: list[str] = []
	skipped: list[dict[str, Any]] = []

	for row in rows:
		if row.disabled:
			continue
		if row.is_group:
			continue

		at = (row.account_type or "").strip()
		if at in _PROTECTED_ACCOUNT_TYPES_FOR_CURRENCY:
			skipped.append({"name": row.name, "reason": "protected_account_type", "detail": at})
			continue

		ac_raw = row.account_currency
		ac = (ac_raw if ac_raw is not None else "").strip()
		in_mapped = row.name in mapped
		is_exp_try = at in _TRY_CONVERT_EXPENSE_TYPES
		is_inv_null = at in _NULL_USD_INCOME_AR_TYPES

		upper = ac.upper() if ac else ""

		# TRY → USD only for operational mapping / expense roles.
		if upper == "TRY":
			if in_mapped or is_exp_try:
				frappe.db.set_value(
					"Account",
					row.name,
					{"account_currency": OPERATIONAL_CURRENCY},
					update_modified=False,
				)
				try_to_usd.append(row.name)
			else:
				skipped.append(
					{
						"name": row.name,
						"reason": "try_non_operational_leaf",
						"account_type": at or None,
					}
				)
			continue

		if not ac:
			if in_mapped or is_exp_try or is_inv_null:
				frappe.db.set_value(
					"Account",
					row.name,
					{"account_currency": OPERATIONAL_CURRENCY},
					update_modified=False,
				)
				null_to_usd.append(row.name)
			else:
				skipped.append({"name": row.name, "reason": "null_skipped", "account_type": at or None})
			continue

		if upper == OPERATIONAL_CURRENCY:
			continue

		skipped.append({"name": row.name, "reason": "leave_currency", "account_currency": ac})

	frappe.db.commit()
	frappe.clear_cache()

	return {
		"ok": 1,
		"company": company,
		"operational_currency": OPERATIONAL_CURRENCY,
		"mapped_umre_settings_accounts": sorted(mapped),
		"counts": {
			"null_set_to_usd": len(null_to_usd),
			"try_set_to_usd": len(try_to_usd),
			"skipped_entries": len(skipped),
		},
		"accounts_null_to_usd": null_to_usd[:200],
		"accounts_try_to_usd": try_to_usd[:200],
		"skipped_sample": skipped[:80],
	}

