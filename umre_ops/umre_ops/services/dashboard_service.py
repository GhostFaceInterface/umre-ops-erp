# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
"""
Financial dashboard aggregation service.

Public, whitelisted entry point:

    get_tour_cost_breakdown(tour: str | None = None) -> dict

Returns the strict data contract for the Umre Operasyon Paneli dashboard:

    {
        "kpis": {
            "total_revenue": float,
            "total_cost": float,
            "net_profit": float,
        },
        "cost_breakdown": [{"label": str, "value": float}],
        "performance": {
            "cost_per_person": float,
            "profit_per_person": float,
            "food_ratio": float,  # percentage, 0..100
        },
        "meta": {
            "kisi_sayisi": int,
        },
    }

Performance contract
--------------------
* TWO SQL queries total (booking-level metrics + component aggregation
  joined to ``Cost Type`` for sort order and display names).
* No per-booking Python loops; no response caching.
* Safe for use as a desk-page payload (returns inside one HTTP round-trip).
"""
from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import flt
from umre_ops.umre_ops.services.expense_service import get_operational_dashboard_summary

CURRENCY = "USD"

# Doughnut legend colours (align with `Cost Type` codes).
CHART_HEX_BY_CODE: dict[str, str] = {
	"HOTEL":   "#ff4d4f",
	"FLIGHT":  "#ff7a45",
	"VISA":    "#ffa940",
	"DIYANET": "#36cfc9",
	"MEAL":    "#597ef7",
	"OTHER":   "#9254de",
	"MANUAL":  "#13c2c2",
}


def _list_tour_options() -> list[dict[str, str]]:
	rows = frappe.get_all(
		"Umre Tour",
		fields=["name", "tur_adi", "tur_kodu"],
		order_by="modified desc",
	)
	return [
		{"name": r["name"], "label": r.get("tur_adi") or r["name"]}
		for r in rows
	]


def _booking_metrics(tour: str | None) -> dict[str, float]:
	"""Single SQL: per-tour or all-tours booking-side aggregates."""
	where = "WHERE 1=1"
	params: dict[str, Any] = {}
	if tour:
		where += " AND tur = %(tour)s"
		params["tour"] = tour

	row = frappe.db.sql(
		f"""
		SELECT
		  COUNT(*)                                           AS kisi_sayisi,
		  SUM(CASE WHEN statu = 'UMRECI' THEN 1 ELSE 0 END)  AS umreci_count,
		  SUM(CASE WHEN statu <> 'UMRECI' THEN 1 ELSE 0 END) AS non_umreci_count,
		  SUM(CASE WHEN statu = 'UMRECI' THEN ucret  ELSE 0 END) AS gelir,
		  SUM(CASE WHEN statu = 'UMRECI' THEN odenen ELSE 0 END) AS tahsil_edilen
		FROM `tabUmre Booking`
		{where}
		""",
		params,
		as_dict=True,
	)
	r = row[0] if row else {}
	return {
		"kisi_sayisi":      int(r.get("kisi_sayisi") or 0),
		"umreci_count":     int(r.get("umreci_count") or 0),
		"non_umreci_count": int(r.get("non_umreci_count") or 0),
		"gelir":            flt(r.get("gelir") or 0),
		"tahsil_edilen":    flt(r.get("tahsil_edilen") or 0),
	}


def _component_rollup(
	tour: str | None,
) -> tuple[dict[str, float], list[dict[str, Any]]]:
	"""One SQL: amounts per ``cost_type`` with ``Cost Type`` sort + label."""
	where = "WHERE 1=1"
	params: dict[str, Any] = {}
	if tour:
		where += " AND b.tur = %(tour)s"
		params["tour"] = tour

	rows = frappe.db.sql(
		f"""
		SELECT
			c.cost_type AS code,
			SUM(c.amount) AS total,
			MIN(IFNULL(ct.sort_order, 9999)) AS sort_order,
			MIN(IFNULL(ct.cost_type_name, c.cost_type)) AS type_label
		FROM `tabCost Component` c
		JOIN `tabUmre Booking` b ON b.name = c.booking
		LEFT JOIN `tabCost Type` ct ON ct.name = c.cost_type
		{where}
		GROUP BY c.cost_type
		ORDER BY sort_order, c.cost_type
		""",
		params,
		as_dict=True,
	)
	totals: dict[str, float] = {}
	ordered: list[dict[str, Any]] = []
	for r in rows:
		code = r["code"]
		amt = flt(r.get("total") or 0)
		totals[code] = amt
		ordered.append(
			{
				"code": code,
				"label": r.get("type_label") or code,
				"sort_order": cintish(r.get("sort_order")),
				"amount": amt,
			}
		)
	return totals, ordered


def cintish(v: Any) -> int:
	try:
		return int(v)
	except (TypeError, ValueError):
		return 9999


@frappe.whitelist()
def get_tour_cost_breakdown(tour: str | None = None) -> dict[str, Any]:
	"""Return the strict payload feeding the custom financial dashboard.

	`tour` is optional. When omitted (or empty), the breakdown aggregates
	across every tour in the database — i.e. the company-wide view a manager
	wants when they open the Operasyon Paneli.
	"""
	# Empty-string fallback (Frappe URL params come through as "").
	tour = (tour or "").strip() or None

	booking = _booking_metrics(tour)
	components, ordered_rows = _component_rollup(tour)
	total_cost = flt(sum(components.values()), 2)
	total_revenue = flt(booking["gelir"], 2)
	net_profit = flt(total_revenue - total_cost, 2)
	kisi = booking["kisi_sayisi"] or 0
	cost_per_person = flt(total_cost / kisi, 2) if kisi else 0.0
	profit_per_person = flt(net_profit / kisi, 2) if kisi else 0.0
	food_ratio = flt((components.get("MEAL", 0) / total_cost) * 100, 2) if total_cost > 0 else 0.0
	cost_breakdown = [
		{
			"label": str(row.get("label") or row.get("code")),
			"value": flt(row.get("amount") or 0, 2),
		}
		for row in ordered_rows
	]

	return {
		"kpis": {
			"total_revenue": total_revenue,
			"total_cost": total_cost,
			"net_profit": net_profit,
		},
		"cost_breakdown": cost_breakdown,
		"performance": {
			"cost_per_person": cost_per_person,
			"profit_per_person": profit_per_person,
			"food_ratio": food_ratio,
		},
		"meta": {
			"kisi_sayisi": booking["kisi_sayisi"],
		},
	}


def _bucket_for_operational_category(category_name: str | None) -> str:
	"""Map `Operational Expense Category.category_name` to dashboard card bucket."""
	if not category_name:
		return "other"
	n = category_name.lower()
	if any(k in n for k in ("pazarlama", "reklam")):
		return "marketing"
	if "ofis" in n:
		return "office"
	if "vergi" in n:
		return "taxes"
	if "personel" in n:
		return "personnel"
	return "other"


@frappe.whitelist()
def get_operational_expense_dashboard(
	season: str | None = None,
	category: str | None = None,
	currency: str | None = None,
	money_account: str | None = None,
) -> dict[str, Any]:
	"""Confirmed `Operational Expense` totals in **USD** — Sezonluk Genel Giderler panel.

	Draft / Cancelled rows are excluded.
	"""
	if not frappe.db.exists("DocType", "Operational Expense"):
		return {
			"currency": CURRENCY,
			"total_operational_usd": 0.0,
			"buckets_usd": {
				"marketing": 0.0,
				"office": 0.0,
				"taxes": 0.0,
				"personnel": 0.0,
				"other": 0.0,
			},
			"chart_by_category": {"labels": [], "datasets": []},
			"chart_monthly": {"labels": [], "datasets": []},
			"filters": {
				"seasons": [],
				"categories": [],
				"money_accounts": [],
				"currencies": [],
			},
		}

	season = (season or "").strip() or None
	category = (category or "").strip() or None
	currency = (currency or "").strip() or None
	money_account = (money_account or "").strip() or None

	w = ["oe.status = %(st)s"]
	params: dict[str, Any] = {"st": "Confirmed"}
	if season:
		w.append("oe.season = %(season)s")
		params["season"] = season
	if category:
		w.append("oe.expense_category = %(category)s")
		params["category"] = category
	if currency:
		w.append("oe.currency = %(currency)s")
		params["currency"] = currency
	if money_account:
		w.append("oe.money_account = %(money_account)s")
		params["money_account"] = money_account

	where = " AND ".join(w)

	row = frappe.db.sql(
		f"""
		SELECT COALESCE(SUM(oe.usd_amount), 0) AS total_usd
		FROM `tabOperational Expense` oe
		WHERE {where}
		""",
		params,
		as_dict=True,
	)
	total_all = flt((row[0] or {}).get("total_usd")) if row else 0.0

	by_cat = frappe.db.sql(
		f"""
		SELECT
		  c.category_name AS category_name,
		  COALESCE(SUM(oe.usd_amount), 0) AS total_usd
		FROM `tabOperational Expense` oe
		LEFT JOIN `tabOperational Expense Category` c ON c.name = oe.expense_category
		WHERE {where}
		GROUP BY c.category_name
		ORDER BY total_usd DESC
		""",
		params,
		as_dict=True,
	)
	chart_labels = [r["category_name"] or _("(No category)") for r in by_cat]
	chart_values = [flt(r.get("total_usd")) for r in by_cat]

	buckets = {"marketing": 0.0, "office": 0.0, "taxes": 0.0, "personnel": 0.0, "other": 0.0}
	for r in by_cat:
		bk = _bucket_for_operational_category(r.get("category_name"))
		buckets[bk] = buckets.get(bk, 0.0) + flt(r.get("total_usd"))

	monthly_rows = frappe.db.sql(
		f"""
		SELECT DATE_FORMAT(oe.expense_date, '%%Y-%%m') AS ym,
		       COALESCE(SUM(oe.usd_amount), 0) AS total_usd
		FROM `tabOperational Expense` oe
		WHERE {where}
		GROUP BY ym
		ORDER BY ym ASC
		""",
		params,
		as_dict=True,
	)
	mt_labels = [r["ym"] or "" for r in monthly_rows]
	mt_values = [flt(r.get("total_usd")) for r in monthly_rows]

	return {
		"currency": CURRENCY,
		"total_operational_usd": total_all,
		"buckets_usd": {
			"marketing": buckets["marketing"],
			"office": buckets["office"],
			"taxes": buckets["taxes"],
			"personnel": buckets["personnel"],
			"other": buckets["other"],
		},
		"chart_by_category": {
			"labels": chart_labels,
			"datasets": [{"name": _("Gider"), "values": chart_values}],
		},
		"chart_monthly": {
			"labels": mt_labels,
			"datasets": [{"name": _("USD"), "values": mt_values}],
		},
		"filters": {
			"seasons": frappe.get_all("Umre Season", fields=["name", "season_name"], order_by="modified desc"),
			"categories": frappe.get_all(
				"Operational Expense Category", fields=["name", "category_name"], order_by="sort_order asc"
			),
			"money_accounts": frappe.get_all(
				"Umre Money Account",
				filters={"is_active": 1},
				fields=["name", "account_name"],
				order_by="account_name asc",
			),
			"currencies": frappe.get_all("Currency", pluck="name", order_by="name asc"),
		},
	}


@frappe.whitelist()
def get_operational_dashboard_data(filters: dict[str, Any] | str | None = None) -> dict[str, Any]:
	"""Combined endpoint for the full Umre dashboard.

	Existing tour revenue/cost logic remains delegated to
	``get_tour_cost_breakdown``. Operational expenses are aggregated through the
	separate expense service.
	"""
	from umre_ops.umre_ops.services.expense_service import normalize_filters

	filters = normalize_filters(filters)
	return {
		"tour_dashboard": get_tour_cost_breakdown(tour=filters.get("tour")),
		"operational_dashboard": get_operational_dashboard_summary(filters),
	}


def publish_dashboard_dirty(tour: str | None = None) -> None:
	"""Emit a realtime nudge so any open dashboard panel re-fetches.

	Cheap fan-out: every desk session subscribed to the event will refetch.
	"""
	frappe.publish_realtime(
		event="umre_cost_dashboard_dirty",
		message={"tour": tour or ""},
		after_commit=True,
	)
