# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
"""
Tour Revenue Summary — derives every cost number from `Cost Component` rows.

Source of truth
---------------
* Revenue:
    UMRECI:     `revenue = ucret`
    Non-UMRECI: `revenue = 0`
* Cost: SUM over `Cost Component.amount` for every row attached to the booking.
* Profit: `revenue - cost` (accrual basis).

Legacy `Umre Booking.otel_maliyeti / ucak_maliyeti / vize_maliyeti / diyanet_maliyeti / toplam_maliyet`
columns are NEVER read here. They are deprecated and held only for historical
backfill diff inspection.
"""
from __future__ import annotations

from collections import defaultdict

import frappe
from frappe import _
from frappe.utils import flt

DEFAULT_CURRENCY = "USD"
PAYING_STATUS = "UMRECI"
INDENT_TOUR = 0
INDENT_SECTION = 1
INDENT_DETAIL = 2


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = get_columns()
	data = _remove_artificial_total_rows(get_data(filters))
	chart = get_chart(data)
	report_summary = get_report_summary(data)
	return columns, data, None, chart, report_summary


def _remove_artificial_total_rows(data: list[dict]) -> list[dict]:
	return [
		row
		for row in data
		if not (
			str(row.get("tur") or row.get("tour") or "").lower() == "toplam"
			or str(row.get("satir_turu") or row.get("row_type") or "").lower() == "toplam"
		)
	]


def get_columns() -> list[dict]:
	currency_options = {"options": "currency"}
	return [
		{"label": _("Tur"), "fieldname": "tour", "fieldtype": "Data", "width": 280},
		{"label": _("Kişi Sayısı"), "fieldname": "kisi_sayisi", "fieldtype": "Int", "width": 100},
		{"label": _("Gelir"), "fieldname": "gelir", "fieldtype": "Currency", "width": 130, **currency_options},
		{"label": _("Tahsil Edilen"), "fieldname": "tahsil_edilen", "fieldtype": "Currency", "width": 135, **currency_options},
		{"label": _("Kalan Alacak"), "fieldname": "kalan_alacak", "fieldtype": "Currency", "width": 135, **currency_options},
		{"label": _("Toplam Maliyet"), "fieldname": "toplam_maliyet", "fieldtype": "Currency", "width": 140, **currency_options},
		{"label": _("Net Kar"), "fieldname": "net_kar", "fieldtype": "Currency", "width": 130, **currency_options},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Link", "options": "Currency", "hidden": 1},
		{"label": _("Tour Key"), "fieldname": "tour_key", "fieldtype": "Data", "hidden": 1},
		{"label": _("Parent"), "fieldname": "parent_tour_key", "fieldtype": "Data", "hidden": 1},
		{"label": _("Row Kind"), "fieldname": "row_kind", "fieldtype": "Data", "hidden": 1},
	]


# ---------------------------------------------------------------------------
# Data assembly
# ---------------------------------------------------------------------------

def _empty_bucket() -> dict:
	return {
		"kisi_sayisi": 0,
		"gelir": 0.0,
		"tahsil_edilen": 0.0,
		"booking_cost": 0.0,
		"statuses": {},               # by statu code
		"components": defaultdict(float),  # by Cost Type code
	}


def _get_bookings(filters) -> list[dict]:
	booking_filters = {}
	if filters.get("tour"):
		booking_filters["tur"] = filters.tour
	return frappe.db.get_all(
		"Umre Booking",
		fields=["name", "tur", "statu", "ucret", "odenen", "manual_cost"],
		filters=booking_filters,
		order_by="tur asc, statu asc",
	)


def _get_components_for(booking_names: list[str]) -> dict[str, list[dict]]:
	"""Return components keyed by booking name for a batch of bookings."""
	if not booking_names:
		return {}
	rows = frappe.db.sql(
		"""
		SELECT booking, cost_type, amount, currency
		FROM `tabCost Component`
		WHERE booking IN %(names)s
		""",
		{"names": tuple(booking_names)},
		as_dict=True,
	)
	out: dict[str, list[dict]] = defaultdict(list)
	for r in rows:
		out[r["booking"]].append(r)
	return out


def _get_cost_type_order() -> list[tuple[str, str]]:
	"""Return (code, display_name) for all Cost Type rows ordered by sort_order."""
	rows = frappe.get_all(
		"Cost Type",
		fields=["name as code", "cost_type_name", "sort_order"],
		order_by="sort_order asc, name asc",
	)
	return [(r["code"], r["cost_type_name"] or r["code"]) for r in rows]


def get_data(filters) -> list[dict]:
	bookings = _get_bookings(filters)
	if not bookings:
		return []

	components_by_booking = _get_components_for([b["name"] for b in bookings])
	cost_type_order = _get_cost_type_order()

	by_tour: dict[str, dict] = {}
	for booking in bookings:
		tour = booking.get("tur") or _("Tursuz")
		bucket = by_tour.setdefault(tour, _empty_bucket())
		statu = (booking.get("statu") or PAYING_STATUS).strip() or PAYING_STATUS
		is_umreci = statu == PAYING_STATUS
		ucret = flt(booking.get("ucret") or 0)
		odenen = flt(booking.get("odenen") or 0)

		comps = components_by_booking.get(booking["name"], [])
		comp_total = flt(sum(flt(c["amount"] or 0) for c in comps))

		bucket["kisi_sayisi"] += 1
		if is_umreci:
			bucket["gelir"] += ucret
			bucket["tahsil_edilen"] += odenen
		bucket["booking_cost"] += comp_total

		st = bucket["statuses"].setdefault(
			statu,
			{"kisi_sayisi": 0, "gelir": 0.0, "maliyet": 0.0, "net_etki": 0.0},
		)
		st["kisi_sayisi"] += 1
		if is_umreci:
			st["gelir"] += ucret
			st["maliyet"] += comp_total
			st["net_etki"] += ucret - comp_total
		else:
			st["maliyet"] += comp_total
			st["net_etki"] += -comp_total

		for c in comps:
			bucket["components"][c["cost_type"]] = flt(
				bucket["components"][c["cost_type"]] + flt(c["amount"] or 0)
			)

	data: list[dict] = []
	for tour in sorted(by_tour):
		bucket = by_tour[tour]
		total_cost = flt(bucket["booking_cost"])
		net_kar = flt(bucket["gelir"] - total_cost)
		kalan = flt(bucket["gelir"] - bucket["tahsil_edilen"])

		sum_net_effects = sum(s["net_etki"] for s in bucket["statuses"].values())
		if abs(net_kar - sum_net_effects) > 0.01:
			frappe.throw(
				_("Financial inconsistency: top profit {0} does not match sum of status net effects {1}").format(
					net_kar, sum_net_effects
				)
			)

		data.append({
			"tour": tour,
			"tour_key": tour,
			"parent_tour_key": "",
			"row_kind": "tour",
			"indent": INDENT_TOUR,
			"kisi_sayisi": bucket["kisi_sayisi"],
			"gelir": bucket["gelir"],
			"tahsil_edilen": bucket["tahsil_edilen"],
			"kalan_alacak": kalan,
			"toplam_maliyet": total_cost,
			"net_kar": net_kar,
			"currency": DEFAULT_CURRENCY,
		})

		# Statü Analizi
		data.append({
			"tour": _("Statü Analizi"),
			"tour_key": f"{tour}::section::status",
			"parent_tour_key": tour,
			"row_kind": "section",
			"indent": INDENT_SECTION,
			"currency": DEFAULT_CURRENCY,
		})
		for status_name in sorted(bucket["statuses"]):
			st = bucket["statuses"][status_name]
			data.append({
				"tour": status_name,
				"tour_key": f"{tour}::status::{status_name}",
				"parent_tour_key": f"{tour}::section::status",
				"row_kind": "status",
				"indent": INDENT_DETAIL,
				"kisi_sayisi": st["kisi_sayisi"],
				"gelir": flt(st["gelir"]),
				"toplam_maliyet": flt(st["maliyet"]),
				"net_kar": flt(st["net_etki"]),
				"currency": DEFAULT_CURRENCY,
			})

		# Maliyet Dağılımı (Cost Component breakdown)
		data.append({
			"tour": _("Maliyet Dağılımı"),
			"tour_key": f"{tour}::section::cost",
			"parent_tour_key": tour,
			"row_kind": "section",
			"indent": INDENT_SECTION,
			"currency": DEFAULT_CURRENCY,
		})
		for code, display in cost_type_order:
			amt = flt(bucket["components"].get(code, 0.0))
			# Skip if neither this tour has any of this type, nor it is a
			# canonical column (we keep canonical rows even at 0 for legibility).
			data.append({
				"tour": display,
				"tour_key": f"{tour}::cost::{code}",
				"parent_tour_key": f"{tour}::section::cost",
				"row_kind": "cost",
				"indent": INDENT_DETAIL,
				"toplam_maliyet": amt,
				"currency": DEFAULT_CURRENCY,
			})

	return data


def _tour_parent_rows(data: list[dict]) -> list[dict]:
	return [row for row in data if row.get("row_kind") == "tour"]


def get_chart(data: list[dict]) -> dict:
	rows = _tour_parent_rows(data)[:20]
	return {
		"data": {
			"labels": [row["tour"] for row in rows],
			"datasets": [
				{"name": _("Gelir"), "values": [row["gelir"] for row in rows]},
				{"name": _("Tahsil Edilen"), "values": [row["tahsil_edilen"] for row in rows]},
				{"name": _("Toplam Maliyet"), "values": [row["toplam_maliyet"] for row in rows]},
				{"name": _("Net Kar"), "values": [row["net_kar"] for row in rows]},
			],
		},
		"type": "bar",
	}


def get_report_summary(data: list[dict]) -> list[dict]:
	rows = _tour_parent_rows(data)
	revenue = sum(flt(r["gelir"]) for r in rows)
	paid = sum(flt(r["tahsil_edilen"]) for r in rows)
	cost = sum(flt(r["toplam_maliyet"]) for r in rows)
	profit = sum(flt(r["net_kar"]) for r in rows)
	remaining = sum(flt(r["kalan_alacak"]) for r in rows)
	return [
		{"value": revenue, "label": _("Gelir"), "datatype": "Currency", "currency": DEFAULT_CURRENCY, "indicator": "Blue"},
		{"value": paid, "label": _("Tahsil Edilen"), "datatype": "Currency", "currency": DEFAULT_CURRENCY, "indicator": "Green"},
		{"value": cost, "label": _("Toplam Maliyet"), "datatype": "Currency", "currency": DEFAULT_CURRENCY, "indicator": "Orange"},
		{"value": profit, "label": _("Net Kar"), "datatype": "Currency", "currency": DEFAULT_CURRENCY, "indicator": "Green" if profit >= 0 else "Red"},
		{"value": remaining, "label": _("Kalan"), "datatype": "Currency", "currency": DEFAULT_CURRENCY, "indicator": "Orange"},
	]
