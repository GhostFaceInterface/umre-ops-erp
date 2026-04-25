# Copyright (c) 2026, Sermed Turizm
#
# Adds minimal traceability/idempotency fields to standard accounting doctypes.
# Idempotent: safe to re-run.

from __future__ import annotations

import frappe


def _ensure_custom_field(df: dict) -> None:
	"""
	Create a `Custom Field` if missing.
	We intentionally keep these fields additive and minimal.
	"""
	if frappe.db.exists(
		"Custom Field",
		{"dt": df["dt"], "fieldname": df["fieldname"]},
	):
		return
	doc = frappe.get_doc({"doctype": "Custom Field", **df})
	doc.insert(ignore_permissions=True)


def execute():
	fields: list[dict] = []

	# Payment Entry linkage + idempotency key
	fields += [
		{
			"dt": "Payment Entry",
			"label": "Umre Booking",
			"fieldname": "umre_booking",
			"fieldtype": "Link",
			"options": "Umre Booking",
			"insert_after": "remarks",
		},
		{
			"dt": "Payment Entry",
			"label": "Umre Posting Key",
			"fieldname": "umre_posting_key",
			"fieldtype": "Data",
			"unique": 1,
			"insert_after": "umre_booking",
		},
	]

	# Journal Entry linkage + idempotency key
	fields += [
		{
			"dt": "Journal Entry",
			"label": "Umre Booking",
			"fieldname": "umre_booking",
			"fieldtype": "Link",
			"options": "Umre Booking",
			"insert_after": "user_remark",
		},
		{
			"dt": "Journal Entry",
			"label": "Umre Posting Key",
			"fieldname": "umre_posting_key",
			"fieldtype": "Data",
			"unique": 1,
			"insert_after": "umre_booking",
		},
	]

	for df in fields:
		_ensure_custom_field(df)

	frappe.db.commit()

