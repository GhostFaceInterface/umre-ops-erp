# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import flt


def execute(filters=None):
	filters = frappe._dict(filters or {})
	columns = get_columns()
	data = get_data(filters)
	chart = get_chart(data)
	report_summary = get_report_summary(data)
	return columns, data, None, chart, report_summary


def get_columns() -> list[dict]:
	return [
		{"label": _("Tour"), "fieldname": "tour", "fieldtype": "Link", "options": "Umre Tour", "width": 220},
		{"label": _("Total Booked Revenue"), "fieldname": "total_booked_revenue", "fieldtype": "Currency", "width": 160},
		{"label": _("Total Paid"), "fieldname": "total_paid", "fieldtype": "Currency", "width": 130},
		{"label": _("Total Cost"), "fieldname": "total_cost", "fieldtype": "Currency", "width": 130},
		{"label": _("Total KMS"), "fieldname": "total_kms", "fieldtype": "Currency", "width": 130},
		{"label": _("Profit"), "fieldname": "profit", "fieldtype": "Currency", "width": 130},
		{"label": _("Remaining Balance"), "fieldname": "remaining_balance", "fieldtype": "Currency", "width": 150},
	]


def get_data(filters) -> list[dict]:
	booking_filters = {}
	if filters.get("tour"):
		booking_filters["tur"] = filters.tour

	bookings = frappe.db.get_all(
		"Umre Booking",
		fields=["tur", "ucret", "odenen", "toplam_maliyet", "kms", "kar"],
		filters=booking_filters,
		order_by="tur asc",
	)
	grouped: dict[str, dict] = {}
	for booking in bookings:
		tour = booking.tur or _("No Tour")
		row = grouped.setdefault(
			tour,
			{
				"tour": tour,
				"total_booked_revenue": 0.0,
				"total_paid": 0.0,
				"total_cost": 0.0,
				"total_kms": 0.0,
				"profit": 0.0,
				"remaining_balance": 0.0,
			},
		)
		revenue = flt(booking.ucret)
		paid = flt(booking.odenen)
		row["total_booked_revenue"] += revenue
		row["total_paid"] += paid
		row["total_cost"] += flt(booking.toplam_maliyet)
		row["total_kms"] += flt(booking.kms)
		row["profit"] += flt(booking.kar)
		row["remaining_balance"] += revenue - paid

	return list(grouped.values())


def get_chart(data: list[dict]) -> dict:
	limited = data[:20]
	return {
		"data": {
			"labels": [row["tour"] for row in limited],
			"datasets": [
				{"name": _("Revenue"), "values": [row["total_booked_revenue"] for row in limited]},
				{"name": _("Profit"), "values": [row["profit"] for row in limited]},
				{"name": _("Paid"), "values": [row["total_paid"] for row in limited]},
				{"name": _("Remaining"), "values": [row["remaining_balance"] for row in limited]},
			],
		},
		"type": "bar",
	}


def get_report_summary(data: list[dict]) -> list[dict]:
	total_revenue = sum(flt(row["total_booked_revenue"]) for row in data)
	total_paid = sum(flt(row["total_paid"]) for row in data)
	total_profit = sum(flt(row["profit"]) for row in data)
	total_remaining = sum(flt(row["remaining_balance"]) for row in data)
	return [
		{"value": total_revenue, "label": _("Booked Revenue"), "datatype": "Currency", "indicator": "Blue"},
		{"value": total_paid, "label": _("Paid"), "datatype": "Currency", "indicator": "Green"},
		{"value": total_profit, "label": _("Profit"), "datatype": "Currency", "indicator": "Green" if total_profit >= 0 else "Red"},
		{"value": total_remaining, "label": _("Remaining"), "datatype": "Currency", "indicator": "Orange"},
	]
