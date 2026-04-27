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
* TWO SQL queries total (booking-level metrics + component aggregation).
* No per-booking Python loops.
* Safe for use as a desk-page payload (returns inside one HTTP round-trip).
"""
from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import flt

CURRENCY = "USD"

# Display labels and color hints (red shades for cost, in canonical sort order).
COMPONENT_DISPLAY: list[dict[str, Any]] = [
	{"code": "HOTEL",   "label": "Otel Maliyeti",     "color": "#b91c1c"},   # red 700
	{"code": "FLIGHT",  "label": "Uçak Maliyeti",     "color": "#dc2626"},   # red 600
	{"code": "VISA",    "label": "Vize Maliyeti",     "color": "#ef4444"},   # red 500
	{"code": "DIYANET", "label": "Diyanet Maliyeti",  "color": "#f87171"},   # red 400
	{"code": "MEAL",    "label": "Yemek Maliyeti",    "color": "#fb923c"},   # orange 400
	{"code": "OTHER",   "label": "Diğer Maliyetler", "color": "#fbbf24"},   # amber 400
	{"code": "MANUAL",  "label": "Manuel Maliyet",    "color": "#9a3412"},   # red 800
]
COMPONENT_ORDER: list[str] = [c["code"] for c in COMPONENT_DISPLAY]


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


def _component_totals(tour: str | None) -> dict[str, float]:
	"""Single SQL: SUM(amount) grouped by cost_type, optionally tour-scoped."""
	where = "WHERE 1=1"
	params: dict[str, Any] = {}
	if tour:
		where += " AND b.tur = %(tour)s"
		params["tour"] = tour

	rows = frappe.db.sql(
		f"""
		SELECT c.cost_type AS code, SUM(c.amount) AS total
		FROM `tabCost Component` c
		JOIN `tabUmre Booking` b ON b.name = c.booking
		{where}
		GROUP BY c.cost_type
		""",
		params,
		as_dict=True,
	)
	totals: dict[str, float] = {code: 0.0 for code in COMPONENT_ORDER}
	for r in rows:
		code = r["code"]
		# Even ad-hoc/operator-added types should be included so the chart
		# shows them; we'll surface them under their own code.
		totals[code] = flt(r.get("total") or 0)
	return totals


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
	components = _component_totals(tour)
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

	# Component dict + chart series (skip zero entries from the doughnut so
	# the picture stays legible; keep them in the cards for completeness).
	components_payload: dict[str, dict[str, Any]] = {}
	chart_labels: list[str] = []
	chart_values: list[float] = []
	chart_colors: list[str] = []
	for spec in COMPONENT_DISPLAY:
		amt = flt(components.get(spec["code"], 0))
		components_payload[spec["code"]] = {
			"label":  spec["label"],
			"amount": amt,
			"color":  spec["color"],
		}
		if amt > 0:
			chart_labels.append(spec["label"])
			chart_values.append(amt)
			chart_colors.append(spec["color"])

	return {
		"tour": tour,
		"currency": CURRENCY,
		"tours": _list_tour_options(),
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
