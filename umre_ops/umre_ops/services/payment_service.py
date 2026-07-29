# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import flt

from umre_ops.umre_ops.doctype.umre_booking_payment.umre_booking_payment import (
	validate_payment_date_provenance,
)
from umre_ops.umre_ops.services.accounting_service import (
	post_booking_receipt_journal_entry,
	post_booking_receipt_payment_entry,
)
from umre_ops.umre_ops.services.mapping_service import get_account_mapping, map_odeme_turu_to_mode_of_payment
from umre_ops.umre_ops.services.permission_service import require_document_permission


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


def _validate_payment_accounting_state(row, *, expected_doctype: str) -> str:
	"""Fail closed unless the row is a clean draft or a consistent posted retry."""
	validate_payment_date_provenance(row)
	if getattr(row, "date_verification_status", None) != "Verified":
		frappe.throw(_("Payment date must be verified before accounting posting."))
	status = getattr(row, "posting_status", None) or "Draft"
	payment_entry = getattr(row, "payment_entry", None)
	journal_entry = getattr(row, "journal_entry", None)
	if payment_entry and journal_entry:
		frappe.throw(_("A payment row cannot link both a Payment Entry and a Journal Entry."))
	if status == "Draft":
		if payment_entry or journal_entry:
			frappe.throw(_("A draft payment row cannot already have an accounting voucher."))
		return status
	if status != "Posted":
		frappe.throw(_("Only Draft or consistently Posted payment rows can be processed."))
	linked = payment_entry if expected_doctype == "Payment Entry" else journal_entry
	other = journal_entry if expected_doctype == "Payment Entry" else payment_entry
	if not linked or other or not getattr(row, "idempotency_key", None):
		frappe.throw(_("Posted payment row accounting links are inconsistent."))
	return status


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
	require_document_permission(b, "write")
	if not posting_date:
		frappe.throw(_("Payment posting date is required."))
	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("Payment amount must be greater than 0."))

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
			"date_source": "Manual",
			"date_verification_status": "Needs Review",
			"posting_status": "Draft",
		},
	)
	b.save()
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
	require_document_permission(b, "read" if dry_run else "write")
	row = None
	for r in b.get("payments") or []:
		if r.name == payment_row_name:
			row = r
			break
	if not row:
		frappe.throw(_("Payment row not found on this booking."))
	if not row.posting_date:
		frappe.throw(_("Payment posting date is required."))
	if flt(row.amount) <= 0:
		frappe.throw(_("Payment amount must be greater than 0."))
	expected_doctype = "Payment Entry" if getattr(b, "customer", None) else "Journal Entry"
	previous_status = _validate_payment_accounting_state(row, expected_doctype=expected_doctype)

	# deterministic idempotency based on the child row stable name
	idempotency_key = row.idempotency_key or _build_idempotency_key(
		booking_name=booking_name, payment_row_name=payment_row_name, kind="RECEIPT"
	)

	# store the key on the row for visibility and for external API callers
	if not row.idempotency_key and not dry_run:
		row.idempotency_key = idempotency_key

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
		if res.doctype != expected_doctype:
			frappe.throw(_("Accounting service returned an unexpected voucher type."))
		existing_link = row.payment_entry if expected_doctype == "Payment Entry" else row.journal_entry
		if previous_status == "Posted" and existing_link != res.name:
			frappe.throw(_("Idempotent posting returned a different accounting voucher."))
		if res.doctype == "Journal Entry":
			row.journal_entry = res.name
			row.posting_status = "Posted"
		elif res.doctype == "Payment Entry":
			row.payment_entry = res.name
			row.posting_status = "Posted"

	if not dry_run:
		b.flags.ignore_booking_recalc = True
		# The Booking controller permits only the narrow Draft -> Posted field
		# transition while continuing to lock economic and evidence fields.
		b.flags.accounting_posting_transition = {
			"payment_row_name": payment_row_name,
			"expected_doctype": res.doctype,
			"voucher_name": res.name,
			"idempotency_key": idempotency_key,
		}
		b.save()

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
