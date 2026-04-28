# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
"""
Financial dashboard aggregation service.

Public, whitelisted entry point:

    get_tour_cost_breakdown(tour: str | None = None) -> dict

Returns a single, complete payload for the Umre Operasyon Paneli dashboard:

    {
        "tour":                    str | None,           # echoed back
        "currency":                str,                  # canonical USD
        "tours":                   [{"name", "label"}],  # selector options
        "kisi_sayisi":             int,                  # all participants
        "umreci_count":            int,
        "non_umreci_count":        int,
        "gelir":                   float,                # UMRECI ucret total
        "tahsil_edilen":           float,                # UMRECI odenen total
        "kalan_alacak":            float,                # gelir - tahsil_edilen
        "components": {
            "HOTEL":   {"label", "amount", "color"},
            "FLIGHT":  ...,
            ...
            "MANUAL":  ...
        },
        "total_cost":              float,                # SUM(Cost Component.amount)
        "net_kar":                 float,                # gelir - total_cost
        "kpis": {
            "kisi_basi_maliyet":   float,
            "kisi_basi_kar":       float,
            "yemek_orani":         float                 # 0..1
        },
        "chart": {                                       # ready for Frappe Charts
            "labels":  [...],
            "datasets": [{"name": "Maliyet", "values": [...]}],
            "colors":  [...]
        }
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
	"""Single payload feeding the financial dashboard panel.

	`tour` is optional. When omitted (or empty), the breakdown aggregates
	across every tour in the database — i.e. the company-wide view a manager
	wants when they open the Operasyon Paneli.
	"""
	# Empty-string fallback (Frappe URL params come through as "").
	tour = (tour or "").strip() or None

	booking = _booking_metrics(tour)
	components, ordered_rows = _component_rollup(tour)
	total_cost = flt(sum(components.values()))
	gelir = booking["gelir"]
	net_kar = flt(gelir - total_cost)
	kalan = flt(gelir - booking["tahsil_edilen"])

	# KPIs (zero-safe). Per spec: per-person metrics divide by total kişi
	# sayısı (all participants on the tour, not just paying UMRECI).
	kisi = booking["kisi_sayisi"] or 0
	per_person_cost = flt(total_cost / kisi) if kisi else 0.0
	per_person_profit = flt(net_kar / kisi) if kisi else 0.0
	meal_ratio = flt(components.get("MEAL", 0) / total_cost) if total_cost > 0 else 0.0

	components_payload: dict[str, dict[str, Any]] = {}
	component_order: list[str] = []
	chart_labels: list[str] = []
	chart_values: list[float] = []
	chart_colors: list[str] = []
	for row in ordered_rows:
		code = row["code"]
		component_order.append(code)
		lab = str(row.get("label") or code)
		amt = flt(row.get("amount") or 0)
		hexc = CHART_HEX_BY_CODE.get(code, "#94a3b8")
		components_payload[code] = {
			"label": lab,
			"amount": amt,
			"color": hexc,
			"hide_if_zero": code in ("MEAL", "OTHER"),
		}
		# Doughnut: only positive segments; meal/other omitted when 0 (UX spec).
		if amt > 0:
			chart_labels.append(lab)
			chart_values.append(amt)
			chart_colors.append(hexc)

	return {
		"tour": tour,
		"currency": CURRENCY,
		"tours": _list_tour_options(),
		"component_order": component_order,
		"kisi_sayisi": booking["kisi_sayisi"],
		"umreci_count": booking["umreci_count"],
		"non_umreci_count": booking["non_umreci_count"],
		"gelir": gelir,
		"tahsil_edilen": booking["tahsil_edilen"],
		"kalan_alacak": kalan,
		"components": components_payload,
		"total_cost": total_cost,
		"net_kar": net_kar,
		"kpis": {
			"kisi_basi_maliyet": per_person_cost,
			"kisi_basi_kar": per_person_profit,
			"yemek_orani": meal_ratio,
		},
		"chart": {
			"labels": chart_labels,
			"datasets": [{"name": _("Maliyet"), "values": chart_values}],
			"colors": chart_colors,
			"total_for_share": total_cost,
		},
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
