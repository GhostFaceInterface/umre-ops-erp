# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
"""
Financial dashboard endpoints (Umre Operasyon Paneli).

Every number comes from ``pnl_service.get_season_pnl`` — the same calculation
used by the Tour Revenue Summary report — so the panel and the report agree.

``get_tour_cost_breakdown(season=None, tour=None)`` returns:

    kpis:        net_sales, gross_sales, commission, total_cost, passenger_cost,
                 tour_extra_expense, tour_profit, overhead, season_result
                 (+ legacy keys total_revenue / net_profit)
    cost_breakdown: [{key, label, value, currency, color}]
    performance: profit_per_paying_passenger, cost_per_person, food_ratio
    collections: collected, excel_reported, open_receivable, overpaid
    meta:        passenger counts
    warnings:    [{code, message, count, examples, details}]

Warnings never hide numbers: they say which bookings are incomplete.
"""
from __future__ import annotations

from typing import Any

import frappe
from frappe import _

from umre_ops.umre_ops.services.expense_service import get_operational_dashboard_summary
from umre_ops.umre_ops.services.permission_service import require_doctype_permission
from umre_ops.umre_ops.services.pnl_service import get_season_pnl
from umre_ops.umre_ops.services.season_service import get_active_season

CURRENCY = "USD"

# Doughnut colours keyed by `Cost Type` code so a type keeps its colour everywhere.
CHART_HEX_BY_CODE: dict[str, str] = {
	"HOTEL": "#ff4d4f",
	"FLIGHT": "#ff7a45",
	"VISA": "#ffa940",
	"DIYANET": "#36cfc9",
	"MEAL": "#597ef7",
	"OTHER": "#9254de",
	"MANUAL": "#13c2c2",
}
FALLBACK_COLOR = "#8c8c8c"
COST_LABEL_BY_CODE: dict[str, str] = {
	"HOTEL": "Otel", "FLIGHT": "Uçak", "VISA": "Vize", "DIYANET": "Diyanet",
	"MEAL": "Yemek", "OTHER": "Diğer", "MANUAL": "Manuel",
}


def _list_season_options() -> list[dict[str, str]]:
	rows = frappe.get_all(
		"Umre Season",
		fields=["name", "season_name"],
		order_by="start_date desc, modified desc",
		limit_page_length=0,
	)
	return [{"name": r["name"], "label": r.get("season_name") or r["name"]} for r in rows]


def _list_tour_options(season: str) -> list[dict[str, str]]:
	rows = frappe.get_all(
		"Umre Tour",
		filters={"season": season},
		fields=["name", "tur_adi", "tur_kodu"],
		order_by="modified desc",
		limit_page_length=0,
	)
	return [{"name": r["name"], "label": r.get("tur_adi") or r["name"]} for r in rows]


def _assert_usd_tours(season: str, tour: str | None) -> None:
	filters: dict[str, Any] = {"season": season}
	if tour:
		filters["name"] = tour
	non_usd = [
		row["name"]
		for row in frappe.get_all(
			"Umre Tour", filters=filters, fields=["name", "para_birimi"], limit_page_length=0
		)
		if (row.get("para_birimi") or CURRENCY) != CURRENCY
	]
	if non_usd:
		frappe.throw(
			_("Dashboard yalnız USD turları birleştirir. Para birimini düzeltin: {0}").format(
				", ".join(non_usd)
			)
		)


def _company_context() -> str | None:
	company = frappe.db.get_single_value("Umre Ops Settings", "company")
	if company:
		frappe.get_doc("Company", company).check_permission("read")
	return company or None


def _cost_type_labels() -> dict[str, str]:
	labels = dict(COST_LABEL_BY_CODE)
	for row in frappe.get_all("Cost Type", fields=["name", "cost_type_name"], limit_page_length=0):
		labels.setdefault(row["name"], row.get("cost_type_name") or row["name"])
	return labels


def _validate_selection(season: str, tour: str | None) -> None:
	if not frappe.db.exists("Umre Season", season):
		frappe.throw(_("Sezon bulunamadı: {0}").format(season))  # noqa: RUF001
	if tour:
		tour_row = frappe.db.get_value("Umre Tour", tour, ["name", "season"], as_dict=True)
		if not tour_row:
			frappe.throw(_("Tur bulunamadı: {0}").format(tour))  # noqa: RUF001
		if tour_row.get("season") != season:
			frappe.throw(_("Seçilen tur {0} sezonuna ait değil.").format(season))


def build_dashboard_payload(pnl: dict[str, Any], labels: dict[str, str] | None = None) -> dict[str, Any]:
	"""Shape ``pnl_service`` output for the panel (pure)."""
	labels = labels or COST_LABEL_BY_CODE
	totals = pnl["totals"]
	cost_breakdown = [
		{
			"key": code,
			"label": labels.get(code, code),
			"value": value,
			"currency": CURRENCY,
			"color": CHART_HEX_BY_CODE.get(code, FALLBACK_COLOR),
		}
		for code, value in totals["maliyet_by_type"].items()
	]
	if totals["tur_ekstra_gider"]:
		cost_breakdown.append({
			"key": "TOUR_EXTRA",
			"label": _("Tur Ekstra Gider"),
			"value": totals["tur_ekstra_gider"],
			"currency": CURRENCY,
			"color": FALLBACK_COLOR,
		})
	return {
		"currency": CURRENCY,
		"kpis": {
			"gross_sales": totals["brut_satis"],
			"commission": totals["komisyon"],
			"net_sales": totals["net_satis"],
			"passenger_cost": totals["yolcu_maliyeti"],
			"tour_extra_expense": totals["tur_ekstra_gider"],
			"total_cost": totals["toplam_maliyet"],
			"tour_profit": totals["tur_kari"],
			"overhead": pnl["genel_gider"],
			"season_result": pnl["sezon_sonucu"],
			# Legacy keys kept for existing consumers.
			"total_revenue": totals["net_satis"],
			"net_profit": totals["tur_kari"],
		},
		"cost_breakdown": cost_breakdown,
		"performance": {
			"profit_per_paying_passenger": totals["kisi_basi_kar"],
			"cost_per_person": totals["kisi_basi_maliyet"],
			"food_ratio": totals["yemek_orani"],
			"profit_per_person": totals["kisi_basi_kar"],
		},
		"collections": {
			"collected": totals["tahsil_edilen"],
			"excel_reported": totals["excel_bildirilen"],
			"open_receivable": totals["acik_alacak"],
			"overpaid": totals["fazla_odeme"],
		},
		"meta": {
			"kisi_sayisi": totals["kisi_sayisi"],
			"total_count": totals["kisi_sayisi"],
			"umreci_count": totals["umreci_count"],
			"non_umreci_count": totals["non_umreci_count"],
		},
		"tour_rows": [
			{key: row[key] for key in ("tour", "label", "kisi_sayisi", "net_satis", "toplam_maliyet", "tur_kari")}
			for row in pnl["tours"]
		],
		"warnings": pnl["warnings"],
		# A warning never hides numbers anymore; kept for older clients.
		"financial_data_valid": True,
	}


@frappe.whitelist()
def get_tour_cost_breakdown(season: str | None = None, tour: str | None = None) -> dict[str, Any]:
	"""Payload for the tour financial panel. Empty ``season`` = active season."""
	require_doctype_permission("Umre Booking", "read")
	require_doctype_permission("Umre Tour", "read")
	require_doctype_permission("Umre Season", "read")
	season = (season or "").strip() or get_active_season(required=True)
	tour = (tour or "").strip() or None
	_validate_selection(season, tour)
	_assert_usd_tours(season, tour)
	company = _company_context()
	payload = build_dashboard_payload(get_season_pnl(season, tour, company), _cost_type_labels())
	payload.update({
		"selected_season": season,
		"selected_tour": tour or "",
		"active_season": get_active_season(),
		"seasons": _list_season_options(),
		"tours": _list_tour_options(season),
	})
	payload["meta"]["company"] = company
	return payload


@frappe.whitelist()
def get_operational_dashboard_data(filters: dict[str, Any] | str | None = None) -> dict[str, Any]:
	"""Season overhead panel. Independent from the tour calculation on purpose:
	a tour-side problem must never hide the office expense panel."""
	from umre_ops.umre_ops.services.expense_service import normalize_filters

	require_doctype_permission("Operational Expense", "read")
	return {"operational_dashboard": get_operational_dashboard_summary(normalize_filters(filters))}


def publish_dashboard_dirty(tour: str | None = None) -> None:
	"""Emit a realtime nudge so any open dashboard panel re-fetches."""
	frappe.publish_realtime(
		event="umre_cost_dashboard_dirty",
		message={"tour": tour or ""},
		after_commit=True,
	)
