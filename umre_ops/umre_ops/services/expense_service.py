# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
"""Operational expense reporting service.

This module is intentionally separate from the tour cost dashboard. Tour
revenue/cost logic stays in ``dashboard_service.get_tour_cost_breakdown``;
season/company expenses are aggregated here from ``Operational Expense`` rows.
Only rows with ``status = 'Confirmed'`` are reportable.
"""
from __future__ import annotations

import json
from typing import Any

import frappe
from frappe import _
from frappe.utils import flt

from umre_ops.umre_ops.services.season_service import get_active_season as _get_active_season

CURRENCY = "USD"


def normalize_filters(filters: dict[str, Any] | str | None = None) -> dict[str, Any]:
	"""Return a compact dict of supported Operational Expense filters."""
	if isinstance(filters, str):
		filters = json.loads(filters) if filters.strip() else {}
	if not isinstance(filters, dict):
		filters = {}

	allowed = {
		"tour",
		"season",
		"category",
		"expense_category",
		"currency",
		"money_account",
		"from_date",
		"to_date",
	}
	return {
		key: value.strip() if isinstance(value, str) else value
		for key, value in filters.items()
		if key in allowed and value not in (None, "")
	}


@frappe.whitelist()
def get_active_season(required: bool = False) -> str | None:
	"""Expose the global active Umre season for forms and dashboard clients."""
	return _get_active_season(required=bool(required))


def _filters_with_active_season(filters: dict[str, Any] | str | None = None) -> dict[str, Any]:
	filters = normalize_filters(filters)
	if not filters.get("season"):
		active = get_active_season()
		if active:
			filters["season"] = active
	return filters


def _where_clause(filters: dict[str, Any] | str | None = None) -> tuple[str, dict[str, Any]]:
	filters = _filters_with_active_season(filters)
	conditions = ["oe.status = %(status)s"]
	params: dict[str, Any] = {"status": "Confirmed"}

	if filters.get("season"):
		conditions.append("oe.season = %(season)s")
		params["season"] = filters["season"]
	else:
		conditions.append("1 = 0")
	expense_category = filters.get("expense_category") or filters.get("category")
	if expense_category:
		conditions.append("oe.expense_category = %(expense_category)s")
		params["expense_category"] = expense_category
	if filters.get("currency"):
		conditions.append("oe.currency = %(currency)s")
		params["currency"] = filters["currency"]
	if filters.get("money_account"):
		conditions.append("oe.money_account = %(money_account)s")
		params["money_account"] = filters["money_account"]
	if filters.get("from_date"):
		conditions.append("oe.expense_date >= %(from_date)s")
		params["from_date"] = filters["from_date"]
	if filters.get("to_date"):
		conditions.append("oe.expense_date <= %(to_date)s")
		params["to_date"] = filters["to_date"]

	return " AND ".join(conditions), params


def _empty_summary() -> dict[str, Any]:
	return {
		"active_season": get_active_season(),
		"total_expense_usd": 0.0,
		"by_main_category": [],
		"by_expense_item": [],
		"monthly_trend": [],
	}


def _has_operational_expense_doctype() -> bool:
	return bool(frappe.db.exists("DocType", "Operational Expense"))


def _main_category_label_columns() -> str:
	return """
		COALESCE(grand.category_name, parent.category_name, cat.category_name, %(uncategorized)s) AS main_label,
		COALESCE(grand.sort_order, parent.sort_order, cat.sort_order, 9999) AS main_sort_order
	"""


def _item_category_label_columns() -> str:
	return """
		COALESCE(grand.category_name, parent.category_name, cat.category_name, %(uncategorized)s) AS main_label,
		COALESCE(grand.sort_order, parent.sort_order, cat.sort_order, 9999) AS main_sort_order,
		COALESCE(cat.category_name, %(uncategorized)s) AS item_label,
		COALESCE(cat.sort_order, 9999) AS item_sort_order
	"""


def _category_joins() -> str:
	return """
		LEFT JOIN `tabOperational Expense Category` cat ON cat.name = oe.expense_category
		LEFT JOIN `tabOperational Expense Category` parent ON parent.name = cat.parent_category
		LEFT JOIN `tabOperational Expense Category` grand ON grand.name = parent.parent_category
	"""


@frappe.whitelist()
def get_operational_expense_taxonomy() -> list[dict[str, Any]]:
	"""Return active operational expense taxonomy as main groups with leaf items."""
	if not frappe.db.exists("DocType", "Operational Expense Category"):
		return []

	rows = frappe.get_all(
		"Operational Expense Category",
		filters={"is_active": 1},
		fields=["name", "category_name", "parent_category", "is_group", "sort_order"],
		order_by="sort_order asc, category_name asc",
		limit_page_length=0,
	)
	by_parent: dict[str | None, list[dict[str, Any]]] = {}
	by_name: dict[str, dict[str, Any]] = {}
	for row in rows:
		row["label"] = row.get("category_name")
		row["children"] = []
		by_name[row["name"]] = row
		by_parent.setdefault(row.get("parent_category"), []).append(row)

	def build(node: dict[str, Any]) -> dict[str, Any]:
		children = [build(child) for child in by_parent.get(node["name"], [])]
		return {
			"name": node["name"],
			"label": node.get("category_name") or node["name"],
			"is_group": bool(node.get("is_group")),
			"sort_order": node.get("sort_order") or 0,
			"children": children,
		}

	return [build(row) for row in by_parent.get(None, []) if row["name"] in by_name]


def get_operational_expense_summary(filters: dict[str, Any] | str | None = None) -> dict[str, Any]:
	"""Return total confirmed operational expense in USD."""
	if not _has_operational_expense_doctype():
		return {"total_expense_usd": 0.0}

	where, params = _where_clause(filters)
	rows = frappe.db.sql(
		f"""
		SELECT COALESCE(SUM(oe.usd_amount), 0) AS total_expense_usd
		FROM `tabOperational Expense` oe
		WHERE {where} AND oe.usd_amount IS NOT NULL
		""",
		params,
		as_dict=True,
	)
	return {"total_expense_usd": flt((rows[0] or {}).get("total_expense_usd"), 2) if rows else 0.0}


def get_expense_breakdown_by_category(filters: dict[str, Any] | str | None = None) -> list[dict[str, Any]]:
	"""Return confirmed operational expenses grouped by main category label."""
	if not _has_operational_expense_doctype():
		return []

	where, params = _where_clause(filters)
	rows = frappe.db.sql(
		f"""
		SELECT
			{_main_category_label_columns()},
			COALESCE(SUM(oe.usd_amount), 0) AS value
		FROM `tabOperational Expense` oe
		{_category_joins()}
		WHERE {where} AND oe.usd_amount IS NOT NULL
		GROUP BY main_label, main_sort_order
		ORDER BY main_sort_order ASC, main_label ASC
		""",
		{**params, "uncategorized": _("Kategorisiz")},
		as_dict=True,
	)
	return [{"label": row.get("main_label") or _("Kategorisiz"), "value": flt(row.get("value"), 2)} for row in rows]


def get_expense_breakdown_by_item(filters: dict[str, Any] | str | None = None) -> list[dict[str, Any]]:
	"""Return confirmed operational expenses grouped by leaf expense item."""
	if not _has_operational_expense_doctype():
		return []

	where, params = _where_clause(filters)
	rows = frappe.db.sql(
		f"""
		SELECT
			{_item_category_label_columns()},
			COALESCE(SUM(oe.usd_amount), 0) AS value
		FROM `tabOperational Expense` oe
		{_category_joins()}
		WHERE {where} AND oe.usd_amount IS NOT NULL
		GROUP BY main_label, main_sort_order, item_label, item_sort_order
		ORDER BY main_sort_order ASC, item_sort_order ASC, item_label ASC
		""",
		{**params, "uncategorized": _("Kategorisiz")},
		as_dict=True,
	)
	return [
		{
			"label": row.get("item_label") or _("Kategorisiz"),
			"parent_label": row.get("main_label") or _("Kategorisiz"),
			"value": flt(row.get("value"), 2),
		}
		for row in rows
	]


def get_monthly_expense_trend(filters: dict[str, Any] | str | None = None) -> list[dict[str, Any]]:
	"""Return confirmed operational expenses by accounting month."""
	if not _has_operational_expense_doctype():
		return []

	where, params = _where_clause(filters)
	rows = frappe.db.sql(
		f"""
		SELECT
			DATE_FORMAT(oe.expense_date, '%%Y-%%m') AS month,
			COALESCE(SUM(oe.usd_amount), 0) AS value
		FROM `tabOperational Expense` oe
		WHERE {where} AND oe.usd_amount IS NOT NULL
		GROUP BY month
		ORDER BY month ASC
		""",
		params,
		as_dict=True,
	)
	return [{"month": row.get("month") or "", "value": flt(row.get("value"), 2)} for row in rows if row.get("month")]


def get_operational_dashboard_summary(filters: dict[str, Any] | str | None = None) -> dict[str, Any]:
	"""Return the strict operational dashboard contract."""
	effective_filters = _filters_with_active_season(filters)
	if not _has_operational_expense_doctype():
		return _empty_summary()

	return {
		"active_season": effective_filters.get("season"),
		"total_expense_usd": get_operational_expense_summary(effective_filters)["total_expense_usd"],
		"by_main_category": get_expense_breakdown_by_category(effective_filters),
		"by_expense_item": get_expense_breakdown_by_item(effective_filters),
		"monthly_trend": get_monthly_expense_trend(effective_filters),
	}


@frappe.whitelist()
def get_operational_dashboard_data(filters: dict[str, Any] | str | None = None) -> dict[str, Any]:
	"""Combined endpoint for the full Umre dashboard.

	The tour dashboard is delegated to the existing service without changing its
	revenue or cost aggregation logic.
	"""
	from umre_ops.umre_ops.services.dashboard_service import get_tour_cost_breakdown

	filters = normalize_filters(filters)
	tour = filters.get("tour")
	return {
		"tour_dashboard": get_tour_cost_breakdown(tour=tour),
		"operational_dashboard": get_operational_dashboard_summary(filters),
	}
