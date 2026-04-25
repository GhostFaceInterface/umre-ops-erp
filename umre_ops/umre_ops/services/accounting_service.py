# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, nowdate

from umre_ops.umre_ops.services.cost_center_service import resolve_booking_cost_center
from umre_ops.umre_ops.services.idempotency_service import (
	get_existing_result,
	mark_event_failed,
	mark_event_succeeded,
	ensure_event_started,
)
from umre_ops.umre_ops.services.mapping_service import get_account_mapping


@dataclass(frozen=True)
class PostResult:
	doctype: str
	name: str
	idempotency_key: str


def _require_company(booking) -> str:
	company = getattr(booking, "company", None) or get_account_mapping(None).company
	if not company:
		frappe.throw(_("Company is required to post accounting entries."))
	return company


def post_booking_receipt_journal_entry(
	*,
	booking_name: str,
	amount: float,
	paid_account: str,
	idempotency_key: str,
	posting_date: str | None = None,
	remarks: str | None = None,
	dry_run: bool = False,
) -> PostResult:
	"""
	Post a customer receipt as Journal Entry (cash/bank Dr, income Cr).
	This path does not require Customer/AR setup and is useful for minimal integration.
	"""
	existing = get_existing_result(idempotency_key)
	if existing and existing.status == "Succeeded" and existing.result_doctype and existing.result_name:
		return PostResult(existing.result_doctype, existing.result_name, idempotency_key)

	booking = frappe.get_doc("Umre Booking", booking_name)
	mapping = get_account_mapping(getattr(booking, "company", None))
	company = _require_company(booking)
	cc = resolve_booking_cost_center(booking)
	if not cc:
		frappe.throw(
			_(
				"Could not resolve a leaf Cost Center for this booking. "
				"Ensure the tour code matches an existing leaf Cost Center (e.g. TUR-2026-01) "
				"or set a non-group fallback Cost Center in Umre Ops Settings."
			)
		)
	income_account = mapping.income_account
	if not income_account:
		frappe.throw(_("Umre Ops Settings.income_account is required to post receipts."))

	posting_date = posting_date or nowdate()
	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("Receipt amount must be > 0"))

	request_payload = {
		"booking": booking_name,
		"company": company,
		"posting_date": posting_date,
		"amount": amount,
		"paid_account": paid_account,
		"income_account": income_account,
		"cost_center": cc,
	}
	event_name, _ = ensure_event_started(
		idempotency_key=idempotency_key,
		operation="BOOKING_RECEIPT_JE",
		company=company,
		source_doctype="Umre Booking",
		source_name=booking_name,
		request_payload=request_payload,
	)

	if dry_run:
		return PostResult("Journal Entry", f"DRY-RUN({event_name})", idempotency_key)

	# If a previous attempt created the JE but failed before marking the event,
	# adopt it instead of trying to create a duplicate (unique key safety).
	existing_je = frappe.db.get_value(
		"Journal Entry",
		{"umre_posting_key": idempotency_key},
		"name",
	)
	if existing_je:
		mark_event_succeeded(event_name=event_name, result_doctype="Journal Entry", result_name=existing_je)
		return PostResult("Journal Entry", existing_je, idempotency_key)

	try:
		je = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"voucher_type": "Journal Entry",
				"multi_currency": 1,
				"company": company,
				"posting_date": posting_date,
				"user_remark": remarks or f"Umre Booking {booking_name} receipt",
				"umre_booking": booking_name,
				"umre_posting_key": idempotency_key,
				"accounts": [
					{
						"account": paid_account,
						"debit_in_account_currency": amount,
						"cost_center": cc,
					},
					{
						"account": income_account,
						"credit_in_account_currency": amount,
						"cost_center": cc,
					},
				],
			}
		)
		je.insert(ignore_permissions=True)
		je.submit()
		mark_event_succeeded(event_name=event_name, result_doctype="Journal Entry", result_name=je.name)
		return PostResult("Journal Entry", je.name, idempotency_key)
	except Exception as e:
		mark_event_failed(event_name=event_name, error=str(e))
		raise


def post_booking_receipt_payment_entry(
	*,
	booking_name: str,
	amount: float,
	paid_to_account: str,
	idempotency_key: str,
	posting_date: str | None = None,
	mode_of_payment: str | None = None,
	reference_no: str | None = None,
	reference_date: str | None = None,
	remarks: str | None = None,
	dry_run: bool = False,
) -> PostResult:
	"""
	Post a customer receipt using ERPNext `Payment Entry` (preferred when Customer exists).
	Idempotent using `Umre Posting Event` + unique `Payment Entry.umre_posting_key`.
	"""
	existing = get_existing_result(idempotency_key)
	if existing and existing.status == "Succeeded" and existing.result_doctype and existing.result_name:
		return PostResult(existing.result_doctype, existing.result_name, idempotency_key)

	booking = frappe.get_doc("Umre Booking", booking_name)
	company = _require_company(booking)
	mapping = get_account_mapping(getattr(booking, "company", None))
	if not getattr(booking, "customer", None):
		frappe.throw(_("Booking.customer is required to post Payment Entry receipts."))
	if not mapping.receivable_account:
		frappe.throw(_("Umre Ops Settings.receivable_account is required to post Payment Entry receipts."))

	posting_date = posting_date or nowdate()
	amount = flt(amount)
	if amount <= 0:
		frappe.throw(_("Receipt amount must be > 0"))

	request_payload = {
		"booking": booking_name,
		"company": company,
		"posting_date": posting_date,
		"amount": amount,
		"paid_to_account": paid_to_account,
		"receivable_account": mapping.receivable_account,
		"customer": booking.customer,
		"mode_of_payment": mode_of_payment,
		"reference_no": reference_no,
		"reference_date": reference_date,
	}
	event_name, _ = ensure_event_started(
		idempotency_key=idempotency_key,
		operation="BOOKING_RECEIPT_PE",
		company=company,
		source_doctype="Umre Booking",
		source_name=booking_name,
		request_payload=request_payload,
	)

	if dry_run:
		return PostResult("Payment Entry", f"DRY-RUN({event_name})", idempotency_key)

	# Adopt previously created PE by unique posting key.
	existing_pe = frappe.db.get_value(
		"Payment Entry",
		{"umre_posting_key": idempotency_key},
		"name",
	)
	if existing_pe:
		mark_event_succeeded(event_name=event_name, result_doctype="Payment Entry", result_name=existing_pe)
		return PostResult("Payment Entry", existing_pe, idempotency_key)

	try:
		pe = frappe.get_doc(
			{
				"doctype": "Payment Entry",
				"payment_type": "Receive",
				"company": company,
				"posting_date": posting_date,
				"party_type": "Customer",
				"party": booking.customer,
				"paid_from": mapping.receivable_account,
				"paid_to": paid_to_account,
				"paid_amount": amount,
				"received_amount": amount,
				"mode_of_payment": mode_of_payment,
				"reference_no": reference_no,
				"reference_date": reference_date,
				"remarks": remarks or f"Umre Booking {booking_name} receipt",
				"umre_booking": booking_name,
				"umre_posting_key": idempotency_key,
			}
		)
		pe.insert(ignore_permissions=True)
		pe.submit()
		mark_event_succeeded(event_name=event_name, result_doctype="Payment Entry", result_name=pe.name)
		return PostResult("Payment Entry", pe.name, idempotency_key)
	except Exception as e:
		mark_event_failed(event_name=event_name, error=str(e))
		raise


def post_booking_costs_journal_entry(
	*,
	booking_name: str,
	bank_or_cash_account: str,
	idempotency_key: str,
	posting_date: str | None = None,
	dry_run: bool = False,
) -> PostResult:
	"""
	Post operational costs as Journal Entry (Expense Dr, cash/bank Cr).
	This is a minimal “direct paid expense” path; supplier/AP workflows can be added later.
	"""
	existing = get_existing_result(idempotency_key)
	if existing and existing.status == "Succeeded" and existing.result_doctype and existing.result_name:
		return PostResult(existing.result_doctype, existing.result_name, idempotency_key)

	booking = frappe.get_doc("Umre Booking", booking_name)
	mapping = get_account_mapping(getattr(booking, "company", None))
	company = _require_company(booking)
	cc = resolve_booking_cost_center(booking)
	if not cc:
		frappe.throw(
			_(
				"Could not resolve a leaf Cost Center for this booking. "
				"Ensure the tour code matches an existing leaf Cost Center (e.g. TUR-2026-01) "
				"or set a non-group fallback Cost Center in Umre Ops Settings."
			)
		)
	posting_date = posting_date or nowdate()

	components = [
		("hotel", flt(getattr(booking, "otel_maliyeti", 0) or 0), mapping.hotel_expense_account),
		("flight", flt(getattr(booking, "ucak_maliyeti", 0) or 0), mapping.flight_expense_account),
		("visa", flt(getattr(booking, "vize_maliyeti", 0) or 0), mapping.visa_expense_account),
		("diyanet", flt(getattr(booking, "diyanet_maliyeti", 0) or 0), mapping.diyanet_expense_account),
	]
	lines: list[dict[str, Any]] = []
	total = 0.0
	for key, amt, acc in components:
		if not amt:
			continue
		if not acc:
			frappe.throw(_("Missing expense account mapping for {0}. Configure Umre Ops Settings.").format(key))
		lines.append({"account": acc, "debit_in_account_currency": amt, "cost_center": cc})
		total += amt

	kms = flt(getattr(booking, "kms", 0) or 0)
	if kms:
		if not mapping.commission_expense_account:
			frappe.throw(_("Missing commission_expense_account mapping in Umre Ops Settings."))
		lines.append(
			{
				"account": mapping.commission_expense_account,
				"debit_in_account_currency": kms,
				"cost_center": cc,
			}
		)
		total += kms

	total = flt(total)
	if total <= 0:
		frappe.throw(_("No operational costs found to post for this booking."))

	request_payload = {
		"booking": booking_name,
		"company": company,
		"posting_date": posting_date,
		"total": total,
		"bank_or_cash_account": bank_or_cash_account,
		"lines": lines,
	}
	event_name, _ = ensure_event_started(
		idempotency_key=idempotency_key,
		operation="BOOKING_COSTS_JE",
		company=company,
		source_doctype="Umre Booking",
		source_name=booking_name,
		request_payload=request_payload,
	)

	if dry_run:
		return PostResult("Journal Entry", f"DRY-RUN({event_name})", idempotency_key)

	# Adopt previously created JE by unique posting key (partial failure safety).
	existing_je = frappe.db.get_value(
		"Journal Entry",
		{"umre_posting_key": idempotency_key},
		"name",
	)
	if existing_je:
		mark_event_succeeded(event_name=event_name, result_doctype="Journal Entry", result_name=existing_je)
		return PostResult("Journal Entry", existing_je, idempotency_key)

	try:
		je = frappe.get_doc(
			{
				"doctype": "Journal Entry",
				"voucher_type": "Journal Entry",
				"multi_currency": 1,
				"company": company,
				"posting_date": posting_date,
				"user_remark": f"Umre Booking {booking_name} operational costs",
				"umre_booking": booking_name,
				"umre_posting_key": idempotency_key,
				"accounts": [
					*lines,
					{
						"account": bank_or_cash_account,
						"credit_in_account_currency": total,
						"cost_center": cc,
					},
				],
			}
		)
		je.insert(ignore_permissions=True)
		je.submit()
		mark_event_succeeded(event_name=event_name, result_doctype="Journal Entry", result_name=je.name)
		return PostResult("Journal Entry", je.name, idempotency_key)
	except Exception as e:
		mark_event_failed(event_name=event_name, error=str(e))
		raise

