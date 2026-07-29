# Copyright (c) 2026, Sermed Turizm and contributors

from __future__ import annotations

import frappe
from frappe import _

from umre_ops.umre_ops.services.permission_service import require_doctype_permission


def execute(filters=None):
	frappe.only_for("System Manager")
	require_doctype_permission("Umre Booking", "read")
	filters = frappe._dict(filters or {})
	return get_columns(), get_data(filters)


def get_columns() -> list[dict]:
	return [
		{"label": _("Payment Row"), "fieldname": "payment_row_name", "fieldtype": "Data", "width": 150},
		{"label": _("Booking"), "fieldname": "booking_name", "fieldtype": "Link", "options": "Umre Booking", "width": 160},
		{"label": _("Pilgrim"), "fieldname": "pilgrim", "fieldtype": "Link", "options": "Umreci", "width": 160},
		{"label": _("Tour"), "fieldname": "tour", "fieldtype": "Link", "options": "Umre Tour", "width": 180},
		{"label": _("Current Date"), "fieldname": "posting_date", "fieldtype": "Date", "width": 110},
		{"label": _("Legacy Date"), "fieldname": "legacy_posting_date", "fieldtype": "Date", "width": 110},
		{"label": _("Amount"), "fieldname": "amount", "fieldtype": "Currency", "options": "currency", "width": 120},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Link", "options": "Currency", "width": 90},
		{"label": _("Source"), "fieldname": "date_source", "fieldtype": "Data", "width": 100},
		{"label": _("Verification"), "fieldname": "date_verification_status", "fieldtype": "Data", "width": 120},
		{"label": _("Evidence"), "fieldname": "date_evidence_reference", "fieldtype": "Data", "width": 180},
		{"label": _("Accounting"), "fieldname": "posting_status", "fieldtype": "Data", "width": 100},
		{"label": _("Payment Entry"), "fieldname": "payment_entry", "fieldtype": "Link", "options": "Payment Entry", "width": 150},
		{"label": _("Journal Entry"), "fieldname": "journal_entry", "fieldtype": "Link", "options": "Journal Entry", "width": 150},
		{"label": _("Booking Paid"), "fieldname": "booking_paid_amount", "fieldtype": "Currency", "options": "currency", "width": 120},
		{"label": _("Child Total"), "fieldname": "child_payment_total", "fieldtype": "Currency", "options": "currency", "width": 120},
		{"label": _("Difference"), "fieldname": "payment_difference", "fieldtype": "Currency", "options": "currency", "width": 110},
		{"label": _("Anomaly"), "fieldname": "anomaly", "fieldtype": "Data", "width": 170},
	]


def get_data(filters) -> list[dict]:
	conditions = []
	values = {}
	if filters.get("tour"):
		conditions.append("b.tur = %(tour)s")
		values["tour"] = filters.tour
	if filters.get("verification_status"):
		conditions.append("p.date_verification_status = %(verification_status)s")
		values["verification_status"] = filters.verification_status
	if filters.get("date_source"):
		conditions.append("p.date_source = %(date_source)s")
		values["date_source"] = filters.date_source
	if filters.get("posting_status"):
		conditions.append("p.posting_status = %(posting_status)s")
		values["posting_status"] = filters.posting_status
	if filters.get("anomalies_only"):
		conditions.append(
			"(p.name IS NULL OR COALESCE(p.date_verification_status, '') != 'Verified' "
			"OR p.posting_date IS NULL OR p.posting_date = u.dogum_tarihi "
			"OR ABS(COALESCE(b.odenen, 0) - COALESCE(pt.child_total, 0)) > 0.01)"
		)
	where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
	return frappe.db.sql(
		f"""
		SELECT
			p.name AS payment_row_name,
			b.name AS booking_name,
			b.umreci AS pilgrim,
			b.tur AS tour,
			p.posting_date,
			p.legacy_posting_date,
			p.amount,
			p.currency,
			p.date_source,
			p.date_verification_status,
			p.date_evidence_reference,
			p.posting_status,
			p.payment_entry,
			p.journal_entry,
			COALESCE(b.odenen, 0) AS booking_paid_amount,
			COALESCE(pt.child_total, 0) AS child_payment_total,
			COALESCE(b.odenen, 0) - COALESCE(pt.child_total, 0) AS payment_difference,
			CASE
				WHEN p.name IS NULL THEN 'No Payment Row'
				WHEN ABS(COALESCE(b.odenen, 0) - COALESCE(pt.child_total, 0)) > 0.01 THEN 'Payment Total Mismatch'
				WHEN p.posting_date IS NULL THEN 'Missing Date'
				WHEN p.posting_date = u.dogum_tarihi THEN 'Matches Birth Date'
				WHEN COALESCE(p.date_verification_status, '') != 'Verified' THEN 'Not Verified'
				ELSE ''
			END AS anomaly
		FROM `tabUmre Booking` b
		LEFT JOIN `tabUmre Booking Payment` p
			ON p.parent = b.name AND p.parenttype = 'Umre Booking' AND p.parentfield = 'payments'
		LEFT JOIN (
			SELECT parent, SUM(amount) AS child_total
			FROM `tabUmre Booking Payment`
			WHERE parenttype = 'Umre Booking' AND parentfield = 'payments'
			GROUP BY parent
		) pt ON pt.parent = b.name
		LEFT JOIN `tabUmreci` u ON u.name = b.umreci
		{where}
		ORDER BY b.tur, b.name, p.idx
		""",
		values,
		as_dict=True,
	)
