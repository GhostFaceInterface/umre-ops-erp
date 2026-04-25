# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

import json
from typing import Any

import frappe
from frappe.utils import flt, nowdate

from umre_ops.umre_ops.services.accounting_service import (
	post_booking_receipt_journal_entry,
	post_booking_receipt_payment_entry,
)
from umre_ops.umre_ops.services.mapping_service import get_account_mapping, map_odeme_turu_to_mode_of_payment


def _booking_default_currency(booking) -> str | None:
	if getattr(booking, "tur", None):
		cur = frappe.db.get_value("Umre Tour", booking.tur, "para_birimi")
		if cur:
			return cur
	s = {}
	try:
		s = frappe.get_single("Umre Ops Settings").as_dict()
	except Exception:
		pass
	return s.get("default_currency")


def _build_idempotency_key(*, booking_name: str, payment_row_name: str, kind: str) -> str:
	return f"UMRE::{booking_name}::{kind}::{payment_row_name}"


def add_payment_row(
	*,
	booking_name: str,
	amount: float,
	posting_date: str | None = None,
	mode_of_payment: str | None = None,
	reference_no: str | None = None,
	reference_date: str | None = None,
	remarks: str | None = None,
	external_reference: str | None = None,
) -> dict[str, Any]:
	"""
	Add a payment row to `Umre Booking.payments`. Does not post accounting by itself.
	Returns the row as dict (including its stable row `name`).
	"""
	b = frappe.get_doc("Umre Booking", booking_name)
	posting_date = posting_date or nowdate()
	amount = flt(amount)
	if amount == 0:
		frappe.throw("Payment amount cannot be 0.")

	if not mode_of_payment:
		mapping = get_account_mapping(getattr(b, "company", None))
		mode_of_payment = map_odeme_turu_to_mode_of_payment(getattr(b, "odeme_turu", None), mapping)

	row = b.append(
		"payments",
		{
			"posting_date": posting_date,
			"amount": amount,
			"currency": _booking_default_currency(b),
			"mode_of_payment": mode_of_payment,
			"reference_no": reference_no,
			"reference_date": reference_date,
			"remarks": remarks,
			"external_reference": external_reference,
			"posting_status": "Draft",
		},
	)
	b.save(ignore_permissions=True)
	return row.as_dict()


def post_payment_row_receipt(
	*,
	booking_name: str,
	payment_row_name: str,
	paid_account: str,
	dry_run: bool = False,
) -> dict[str, Any]:
	"""
	Posts a single payment row as a Journal Entry receipt (minimal path).
	Idempotent per payment row using `Umre Posting Event`.
	"""
	b = frappe.get_doc("Umre Booking", booking_name)
	row = None
	for r in b.get("payments") or []:
		if r.name == payment_row_name:
			row = r
			break
	if not row:
		frappe.throw("Payment row not found on this booking.")

	# deterministic idempotency based on the child row stable name
	idempotency_key = row.idempotency_key or _build_idempotency_key(
		booking_name=booking_name, payment_row_name=payment_row_name, kind="RECEIPT"
	)

	# store the key on the row for visibility and for external API callers
	if not row.idempotency_key:
		row.idempotency_key = idempotency_key

	payload = {
		"booking": booking_name,
		"payment_row": payment_row_name,
		"posting_date": row.posting_date,
		"amount": flt(row.amount),
		"currency": row.currency,
		"mode_of_payment": row.mode_of_payment,
		"paid_account": paid_account,
		"reference_no": row.reference_no,
		"external_reference": row.external_reference,
	}

	# Preferred: Payment Entry when Customer exists (reconciliation-friendly).
	# Fallback: Journal Entry only when Customer is NOT used on the booking.
	if getattr(b, "customer", None):
		res = post_booking_receipt_payment_entry(
			booking_name=booking_name,
			amount=flt(row.amount),
			paid_to_account=paid_account,
			idempotency_key=f"{idempotency_key}::PE",
			posting_date=row.posting_date,
			mode_of_payment=row.mode_of_payment,
			reference_no=row.reference_no,
			reference_date=row.reference_date,
			remarks=row.remarks or f"Umre Booking {booking_name} payment {payment_row_name}",
			dry_run=dry_run,
		)
	else:
		res = post_booking_receipt_journal_entry(
			booking_name=booking_name,
			amount=flt(row.amount),
			paid_account=paid_account,
			idempotency_key=f"{idempotency_key}::JE",
			posting_date=row.posting_date,
			remarks=row.remarks or f"Umre Booking {booking_name} payment {payment_row_name}",
			dry_run=dry_run,
		)

	if not dry_run:
		if res.doctype == "Journal Entry":
			row.journal_entry = res.name
			row.posting_status = "Posted"
		elif res.doctype == "Payment Entry":
			row.payment_entry = res.name
			row.posting_status = "Posted"

	b.flags.ignore_booking_recalc = True
	b.save(ignore_permissions=True)

	return {
		"idempotency_key": idempotency_key,
		"result_doctype": res.doctype,
		"result_name": res.name,
		"payment_row": row.as_dict(),
	}


@frappe.whitelist()
def api_add_payment(docname: str, amount: float, posting_date: str | None = None, mode_of_payment: str | None = None, reference_no: str | None = None, reference_date: str | None = None, remarks: str | None = None, external_reference: str | None = None) -> dict:
	"""
	REST-friendly entrypoint to record a payment event (no accounting posting).
	"""
	return add_payment_row(
		booking_name=docname,
		amount=amount,
		posting_date=posting_date,
		mode_of_payment=mode_of_payment,
		reference_no=reference_no,
		reference_date=reference_date,
		remarks=remarks,
		external_reference=external_reference,
	)


@frappe.whitelist()
def api_post_payment_receipt(docname: str, payment_row_name: str, paid_account: str, dry_run: int = 0) -> dict:
	"""
	Post a specific booking payment row to accounting as Journal Entry receipt.
	"""
	return post_payment_row_receipt(
		booking_name=docname,
		payment_row_name=payment_row_name,
		paid_account=paid_account,
		dry_run=bool(int(dry_run)),
	)

