# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt


DEFAULT_CURRENCY = "USD"
PAYING_STATUS = "UMRECI"
TOUR_TOTAL_ROW = _("Tour Total")
STATUS_DEBUG_ROW = _("Debug by Status")
# Diagnostic expectation from current reconciliation target. This does not feed
# calculations; it only exposes expected - calculated cost in the report.
EXPECTED_COST_BY_TOUR = {"Şevval 2026": 86922.0}


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = get_columns()
	data = get_data(filters)
	chart = get_chart(data)
	report_summary = get_report_summary(data)
	return columns, data, None, chart, report_summary


def get_columns() -> list[dict]:
	currency_options = {"options": "currency"}
	return [
		{"label": _("Tour"), "fieldname": "tour", "fieldtype": "Link", "options": "Umre Tour", "width": 190},
		{"label": _("Row Type"), "fieldname": "row_type", "fieldtype": "Data", "width": 130},
		{"label": _("Status"), "fieldname": "statu", "fieldtype": "Data", "width": 150},
		{"label": _("Count"), "fieldname": "record_count", "fieldtype": "Int", "width": 80},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Link", "options": "Currency", "hidden": 1},
		{"label": _("Revenue (UMRECI)"), "fieldname": "revenue", "fieldtype": "Currency", "width": 150, **currency_options},
		{"label": _("Paid Amount"), "fieldname": "paid_amount", "fieldtype": "Currency", "width": 130, **currency_options},
		{
			"label": _("Remaining Receivable"),
			"fieldname": "remaining_receivable",
			"fieldtype": "Currency",
			"width": 155,
			**currency_options,
		},
		{"label": _("Hotel Cost"), "fieldname": "hotel_cost", "fieldtype": "Currency", "width": 125, **currency_options},
		{"label": _("Flight Cost"), "fieldname": "flight_cost", "fieldtype": "Currency", "width": 125, **currency_options},
		{"label": _("Visa Cost"), "fieldname": "visa_cost", "fieldtype": "Currency", "width": 120, **currency_options},
		{"label": _("Diyanet Cost"), "fieldname": "diyanet_cost", "fieldtype": "Currency", "width": 130, **currency_options},
		{"label": _("Manual Cost"), "fieldname": "manual_cost", "fieldtype": "Currency", "width": 130, **currency_options},
		{"label": _("Total Cost"), "fieldname": "total_cost", "fieldtype": "Currency", "width": 130, **currency_options},
		{"label": _("Expected Cost"), "fieldname": "expected_cost", "fieldtype": "Currency", "width": 130, **currency_options},
		{"label": _("Discrepancy"), "fieldname": "discrepancy", "fieldtype": "Currency", "width": 130, **currency_options},
		{"label": _("Profit"), "fieldname": "profit", "fieldtype": "Currency", "width": 120, **currency_options},
		{
			"label": _("Raw Toplam Maliyet"),
			"fieldname": "raw_toplam_maliyet",
			"fieldtype": "Currency",
			"width": 150,
			**currency_options,
		},
	]


def get_data(filters) -> list[dict]:
	booking_filters = {}
	if filters.get("tour"):
		booking_filters["tur"] = filters.tour

	bookings = frappe.db.get_all(
		"Umre Booking",
		fields=[
			"tur",
			"statu",
			"ucret",
			"odenen",
			"otel_maliyeti",
			"ucak_maliyeti",
			"vize_maliyeti",
			"diyanet_maliyeti",
			"manual_cost",
			"toplam_maliyet",
		],
		filters=booking_filters,
		order_by="tur asc, statu asc",
	)
	if not bookings:
		return []

	tour_currencies = _get_tour_currencies([booking.tur for booking in bookings if booking.tur])
	by_tour: dict[str, dict] = {}
	by_tour_status: dict[tuple[str, str], dict] = {}
	for booking in bookings:
		tour = booking.tur or _("No Tour")
		currency = tour_currencies.get(booking.tur) or DEFAULT_CURRENCY
		status = booking.statu or PAYING_STATUS
		_apply_booking_to_row(_get_tour_row(by_tour, tour, currency), booking, status, is_debug=False)
		_apply_booking_to_row(_get_status_row(by_tour_status, tour, status, currency), booking, status, is_debug=True)

	data: list[dict] = []
	for tour in sorted(by_tour):
		row = _finalize_row(by_tour[tour], expected_cost=EXPECTED_COST_BY_TOUR.get(tour))
		data.append(row)
		for key in sorted(k for k in by_tour_status if k[0] == tour):
			data.append(_finalize_row(by_tour_status[key], expected_cost=None))

	return data


def _get_tour_row(grouped: dict[str, dict], tour: str, currency: str) -> dict:
	return grouped.setdefault(tour, _empty_row(tour=tour, row_type=TOUR_TOTAL_ROW, status="", currency=currency))


def _get_status_row(grouped: dict[tuple[str, str], dict], tour: str, status: str, currency: str) -> dict:
	return grouped.setdefault(
		(tour, status),
		_empty_row(tour=tour, row_type=STATUS_DEBUG_ROW, status=status, currency=currency),
	)


def _empty_row(*, tour: str, row_type: str, status: str, currency: str) -> dict:
	return {
		"tour": tour,
		"row_type": row_type,
		"statu": status,
		"record_count": 0,
		"currency": currency,
		"revenue": 0.0,
		"paid_amount": 0.0,
		"remaining_receivable": 0.0,
		"hotel_cost": 0.0,
		"flight_cost": 0.0,
		"visa_cost": 0.0,
		"diyanet_cost": 0.0,
		"manual_cost": 0.0,
		"total_cost": 0.0,
		"expected_cost": 0.0,
		"discrepancy": 0.0,
		"profit": 0.0,
		"raw_toplam_maliyet": 0.0,
	}


def _apply_booking_to_row(row: dict, booking, status: str, *, is_debug: bool) -> None:
	is_paying = status == PAYING_STATUS
	revenue = flt(booking.ucret) if is_paying else 0.0
	paid = flt(booking.odenen) if is_paying else 0.0
	manual_cost = flt(booking.manual_cost)
	raw_toplam_maliyet = flt(booking.toplam_maliyet)
	calculated_cost = raw_toplam_maliyet if is_paying else manual_cost

	row["record_count"] += 1
	row["revenue"] += revenue
	row["paid_amount"] += paid
	row["remaining_receivable"] += revenue - paid
	row["hotel_cost"] += flt(booking.otel_maliyeti)
	row["flight_cost"] += flt(booking.ucak_maliyeti)
	row["visa_cost"] += flt(booking.vize_maliyeti)
	row["diyanet_cost"] += flt(booking.diyanet_maliyeti)
	row["manual_cost"] += manual_cost
	row["raw_toplam_maliyet"] += raw_toplam_maliyet
	row["total_cost"] += calculated_cost

	# Debug rows intentionally use the same aggregation as tour rows so status-level
	# cost can be reconciled directly against the total row.
	if is_debug:
		return


def _finalize_row(row: dict, *, expected_cost: float | None) -> dict:
	row["profit"] = flt(row["revenue"] - row["total_cost"])
	if expected_cost is not None:
		row["expected_cost"] = flt(expected_cost)
		row["discrepancy"] = flt(expected_cost - row["total_cost"])
	else:
		row["expected_cost"] = 0.0
		row["discrepancy"] = 0.0
	return row


def _get_tour_currencies(tours: list[str]) -> dict[str, str]:
	if not tours:
		return {}
	return dict(
		frappe.db.get_all(
			"Umre Tour",
			filters={"name": ["in", list(set(tours))]},
			fields=["name", "para_birimi"],
			as_list=True,
		)
	)


def _tour_total_rows(data: list[dict]) -> list[dict]:
	return [row for row in data if row.get("row_type") == TOUR_TOTAL_ROW]


def get_chart(data: list[dict]) -> dict:
	limited = _tour_total_rows(data)[:20]
	return {
		"data": {
			"labels": [row["tour"] for row in limited],
			"datasets": [
				{"name": _("Revenue"), "values": [row["revenue"] for row in limited]},
				{"name": _("Total Cost"), "values": [row["total_cost"] for row in limited]},
				{"name": _("Profit"), "values": [row["profit"] for row in limited]},
				{"name": _("Remaining"), "values": [row["remaining_receivable"] for row in limited]},
			],
		},
		"type": "bar",
	}


def get_report_summary(data: list[dict]) -> list[dict]:
	total_rows = _tour_total_rows(data)
	total_revenue = sum(flt(row["revenue"]) for row in total_rows)
	total_paid = sum(flt(row["paid_amount"]) for row in total_rows)
	total_cost = sum(flt(row["total_cost"]) for row in total_rows)
	total_profit = sum(flt(row["profit"]) for row in total_rows)
	total_remaining = sum(flt(row["remaining_receivable"]) for row in total_rows)
	currency = total_rows[0].get("currency") if total_rows else DEFAULT_CURRENCY
	return [
		{"value": total_revenue, "label": _("Revenue"), "datatype": "Currency", "currency": currency, "indicator": "Blue"},
		{"value": total_paid, "label": _("Paid"), "datatype": "Currency", "currency": currency, "indicator": "Green"},
		{"value": total_cost, "label": _("Total Cost"), "datatype": "Currency", "currency": currency, "indicator": "Orange"},
		{
			"value": total_profit,
			"label": _("Profit"),
			"datatype": "Currency",
			"currency": currency,
			"indicator": "Green" if total_profit >= 0 else "Red",
		},
		{"value": total_remaining, "label": _("Remaining"), "datatype": "Currency", "currency": currency, "indicator": "Orange"},
	]
