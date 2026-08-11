# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
"""
Financial dashboard aggregation service.

Public, whitelisted entry point:

    get_tour_cost_breakdown(season: str | None = None, tour: str | None = None) -> dict

Returns the strict data contract for the Umre Operasyon Paneli dashboard:

    {
        "kpis": {
            "total_revenue": float,
            "total_cost": float,
            "net_profit": float,
        },
        "configured_cost_items": [
            {"key": str, "label": str, "value": float, "currency": "USD",
             "source_doctype": str, "source_name": str}
        ],
        "performance": {
            "cost_per_person": float,
            "profit_per_person": float,
            "food_ratio": float,  # percentage, 0..100
        },
        "meta": {
            "kisi_sayisi": int,
        },
    }

The chart reads saved cost-rule rows directly. Persisted booking components are
kept separate and are used only for the historical KPI totals.
"""
from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import flt

from umre_ops.umre_ops.services.expense_service import get_operational_dashboard_summary
from umre_ops.umre_ops.services.permission_service import require_doctype_permission
from umre_ops.umre_ops.services.season_service import get_active_season

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
	return [
		{"name": r["name"], "label": r.get("tur_adi") or r["name"]}
		for r in rows
	]


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


def _booking_metrics(season: str, tour: str | None) -> dict[str, float]:
	"""Single SQL: per-tour or all-tours booking-side aggregates."""
	where = "WHERE t.season = %(season)s"
	params: dict[str, Any] = {"season": season}
	if tour:
		where += " AND b.tur = %(tour)s"
		params["tour"] = tour

	row = frappe.db.sql(
		f"""
		SELECT
		  COUNT(*)                                               AS kisi_sayisi,
		  SUM(CASE WHEN b.statu = 'UMRECI' THEN 1 ELSE 0 END)     AS umreci_count,
		  SUM(CASE WHEN b.statu <> 'UMRECI' THEN 1 ELSE 0 END)    AS non_umreci_count,
		  SUM(CASE WHEN b.statu = 'UMRECI' THEN b.ucret ELSE 0 END) AS gelir,
		  SUM(CASE WHEN b.statu = 'UMRECI' THEN b.odenen ELSE 0 END) AS tahsil_edilen
		FROM `tabUmre Booking` b
		JOIN `tabUmre Tour` t ON t.name = b.tur
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


def _actual_component_totals(season: str, tour: str | None) -> dict[str, float]:
	"""Return historical booking-component totals without feeding the rule chart."""
	where = "WHERE t.season = %(season)s"
	params: dict[str, Any] = {"season": season}
	if tour:
		where += " AND b.tur = %(tour)s"
		params["tour"] = tour
	rows = frappe.db.sql(
		f"""
		SELECT c.cost_type, SUM(c.amount) AS total
		FROM `tabCost Component` c
		JOIN `tabUmre Booking` b ON b.name = c.booking
		JOIN `tabUmre Tour` t ON t.name = b.tur
		{where}
		GROUP BY c.cost_type
		""",
		params,
		as_dict=True,
	)
	return {row["cost_type"]: flt(row.get("total") or 0) for row in rows}


def _configured_cost_items(season: str, tour: str | None) -> list[dict[str, Any]]:
	"""Return one dashboard row per persisted cost-rule record.

	This is intentionally independent from booking ``Cost Component`` rows. Submitted
	booking costs remain historical snapshots; unposted snapshots may be refreshed
	without changing what the chart displays.
	"""
	tours = [tour] if tour else frappe.get_all(
		"Umre Tour", filters={"season": season}, pluck="name", limit_page_length=0
	)
	if not tours:
		return []
	items: list[dict[str, Any]] = []

	def append(doctype: str, row: dict, label: str, value: float) -> None:
		items.append({
			"key": f"{doctype}:{row['name']}",
			"label": label,
			"value": flt(value, 2),
			"currency": CURRENCY,
			"source_doctype": doctype,
			"source_name": row["name"],
		})

	for row in frappe.get_all(
		"Tour Hotel Cost Rule",
		filters={"tur": ["in", tours]},
		fields=["name", "tur", "lokasyon", "gece_sayisi", "birim_fiyat_sar", "kur"],
		order_by="tur, lokasyon, creation",
		limit_page_length=0,
	):
		nights, unit_sar, sar_per_usd = (
			flt(row.get("gece_sayisi")), flt(row.get("birim_fiyat_sar")), flt(row.get("kur"))
		)
		if nights * unit_sar > 0 and sar_per_usd <= 0:
			frappe.throw(_("Otel kuralında SAR/USD kuru eksik: {0}").format(row["name"]))
		value = nights * unit_sar / sar_per_usd if sar_per_usd > 0 else 0
		append("Tour Hotel Cost Rule", row, f"{row['tur']} · Otel · {row.get('lokasyon')}", value)

	for row in frappe.get_all(
		"Tour Airfare Cost Rule",
		filters={"tur": ["in", tours]},
		fields=["name", "tur", "yolcu_tipi", "tutar"],
		order_by="tur, yolcu_tipi, creation",
		limit_page_length=0,
	):
		append(
			"Tour Airfare Cost Rule",
			row,
			f"{row['tur']} · Uçak · {row.get('yolcu_tipi')}",
			row.get("tutar"),
		)

	for row in frappe.get_all(
		"Tour Visa Cost Rule",
		filters={"tur": ["in", tours]},
		fields=["name", "tur", "vize_tipi", "tutar"],
		order_by="tur, vize_tipi, creation",
		limit_page_length=0,
	):
		append("Tour Visa Cost Rule", row, f"{row['tur']} · Vize · {row.get('vize_tipi')}", row.get("tutar"))

	for row in frappe.get_all(
		"Tour Diyanet Card Rule",
		filters={"tur": ["in", tours]}, fields=["name", "tur", "tutar"],
		order_by="tur, creation", limit_page_length=0,
	):
		append("Tour Diyanet Card Rule", row, f"{row['tur']} · Diyanet", row.get("tutar"))

	hotel_nights: dict[str, dict[str, float]] = {name: {"Mekke": 0, "Medine": 0} for name in tours}
	for row in frappe.get_all(
		"Tour Hotel Cost Rule", filters={"tur": ["in", tours]},
		fields=["tur", "lokasyon", "gece_sayisi"], limit_page_length=0,
	):
		if row.get("lokasyon") in {"Mekke", "Medine"}:
			hotel_nights[row["tur"]][row["lokasyon"]] += flt(row.get("gece_sayisi"))
	for row in frappe.get_all(
		"Meal Cost Rule", filters={"tour": ["in", tours]},
		fields=["name", "tour", "mekke_price_sar", "medine_price_sar", "sar_to_usd_rate"],
		order_by="tour, creation", limit_page_length=0,
	):
		nights = hotel_nights[row["tour"]]
		sar_total = (
			nights["Mekke"] * flt(row.get("mekke_price_sar"))
			+ nights["Medine"] * flt(row.get("medine_price_sar"))
		)
		rate = flt(row.get("sar_to_usd_rate"))
		if sar_total > 0 and rate <= 0:
			frappe.throw(_("Yemek kuralında SAR/USD kuru eksik: {0}").format(row["name"]))
		value = sar_total / rate if rate > 0 else 0
		append("Meal Cost Rule", row, f"{row['tour']} · Yemek", value)

	for row in frappe.get_all(
		"Other Cost Rule", filters={"tour": ["in", tours]},
		fields=["name", "tour", "per_person_cost"], order_by="tour, creation", limit_page_length=0,
	):
		append("Other Cost Rule", row, f"{row['tour']} · Diğer", row.get("per_person_cost"))
	return items


@frappe.whitelist()
def get_tour_cost_breakdown(
	season: str | None = None,
	tour: str | None = None,
) -> dict[str, Any]:
	"""Return the strict payload feeding the custom financial dashboard.

	An empty ``season`` selects the active season. An empty ``tour`` aggregates
	only the tours belonging to that selected season.
	"""
	require_doctype_permission("Umre Booking", "read")
	require_doctype_permission("Umre Tour", "read")
	require_doctype_permission("Umre Season", "read")
	season = (season or "").strip() or get_active_season(required=True)
	tour = (tour or "").strip() or None
	if not frappe.db.exists("Umre Season", season):
		frappe.throw(_("Sezon bulunamadı: {0}").format(season))  # noqa: RUF001
	if tour:
		tour_row = frappe.db.get_value("Umre Tour", tour, ["name", "season"], as_dict=True)
		if not tour_row:
			frappe.throw(_("Tur bulunamadı: {0}").format(tour))  # noqa: RUF001
		if tour_row.get("season") != season:
			frappe.throw(_("Seçilen tur {0} sezonuna ait değil.").format(season))
	_assert_usd_tours(season, tour)

	booking = _booking_metrics(season, tour)
	configured_cost_items = _configured_cost_items(season, tour)
	actual_components = _actual_component_totals(season, tour)
	total_cost = flt(sum(actual_components.values()), 2)
	total_revenue = flt(booking["gelir"], 2)
	net_profit = flt(total_revenue - total_cost, 2)
	kisi = booking["kisi_sayisi"] or 0
	cost_per_person = flt(total_cost / kisi, 2) if kisi else 0.0
	profit_per_person = flt(net_profit / kisi, 2) if kisi else 0.0
	meal_total = actual_components.get("MEAL", 0)
	food_ratio = flt((meal_total / total_cost) * 100, 2) if total_cost > 0 else 0.0
	cost_breakdown = [
		{
			"label": row["label"],
			"value": row["value"],
		}
		for row in configured_cost_items
	]

	return {
		"currency": CURRENCY,
		"selected_season": season,
		"active_season": get_active_season(),
		"seasons": _list_season_options(),
		"tours": _list_tour_options(season),
		"kpis": {
			"total_revenue": total_revenue,
			"total_cost": total_cost,
			"net_profit": net_profit,
		},
		"cost_breakdown": cost_breakdown,
		"configured_cost_items": configured_cost_items,
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
	if any(
		k in n
		for k in (
			"ofis",
			"kira",
			"elektrik",
			"doğalgaz",
			"dogalgaz",
			"internet",
			"bilişim",
			"bilisim",
			"yemek - gıda",  # noqa: RUF001
			"yemek - gida",
		)
	) or n.strip() == "su":
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
	require_doctype_permission("Operational Expense", "read")
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

	require_doctype_permission("Umre Booking", "read")
	require_doctype_permission("Operational Expense", "read")
	filters = normalize_filters(filters)
	return {
		"tour_dashboard": get_tour_cost_breakdown(
			season=filters.get("season"),
			tour=filters.get("tour"),
		),
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
