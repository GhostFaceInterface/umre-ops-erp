# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import frappe
from frappe import _
from frappe.utils import cint, flt, getdate

from umre_ops.umre_ops.services.cost_center_service import resolve_booking_cost_center
from umre_ops.umre_ops.services.idempotency_service import (
	ensure_event_started,
	get_existing_result,
	mark_event_failed,
	mark_event_succeeded,
	sha256_hex,
	stable_json_dumps,
)
from umre_ops.umre_ops.services.mapping_service import get_account_mapping
from umre_ops.umre_ops.services.permission_service import (
	require_doctype_permission,
	require_document_permission,
)


@dataclass(frozen=True)
class PostResult:
	doctype: str
	name: str
	idempotency_key: str


def _require_accounting_posting_enabled(*, dry_run: bool) -> None:
	"""Keep accounting writes off until an administrator explicitly enables them."""
	if dry_run:
		return
	try:
		enabled = frappe.db.get_single_value("Umre Ops Settings", "accounting_posting_enabled")
	except Exception:
		# Safe default for deployments where the new Single field has not migrated yet.
		enabled = 0
	if not cint(enabled):
		frappe.throw(
			_("Accounting posting is disabled in Umre Ops Settings. Use dry-run for validation."),
		)


def _require_target_write_permissions(doctype: str, *, dry_run: bool) -> None:
	if dry_run:
		return
	require_doctype_permission(doctype, "create")
	require_doctype_permission(doctype, "submit")


def _lock_booking_for_posting(booking_name: str, *, dry_run: bool) -> None:
	"""Serialize real accounting posts with tour-participant deletion."""
	if dry_run:
		return
	locked = frappe.db.sql(
		"SELECT name FROM `tabUmre Booking` WHERE name = %s FOR UPDATE",
		(booking_name,),
	)
	if not locked:
		frappe.throw(_("Umre Booking {0} no longer exists.").format(booking_name))


def _require_posting_date(posting_date: str | None) -> str:
	if not posting_date:
		frappe.throw(_("Posting date is required."))
	try:
		return getdate(posting_date).isoformat()
	except Exception:
		frappe.throw(_("Posting date must contain a valid date."))


def _get_valid_existing_result(idempotency_key: str, request_payload: dict[str, Any]) -> PostResult | None:
	"""Validate payload identity and the submitted voucher before reusing a result."""
	existing = get_existing_result(idempotency_key)
	if not existing:
		return None
	request_hash = sha256_hex(stable_json_dumps(request_payload))
	if existing.request_hash and existing.request_hash != request_hash:
		frappe.throw(_("Idempotency key reuse detected. Payload hash mismatch."))
	if existing.status != "Succeeded":
		return None
	if not existing.result_doctype or not existing.result_name:
		frappe.throw(_("Succeeded posting event has no linked accounting voucher."))
	docstatus = frappe.db.get_value(existing.result_doctype, existing.result_name, "docstatus")
	if cint(docstatus) != 1:
		frappe.throw(_("Linked accounting voucher is missing or is not submitted."))
	return PostResult(existing.result_doctype, existing.result_name, idempotency_key)


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
	_require_accounting_posting_enabled(dry_run=dry_run)
	_lock_booking_for_posting(booking_name, dry_run=dry_run)
	booking = frappe.get_doc("Umre Booking", booking_name)
	require_document_permission(booking, "read" if dry_run else "write")
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

	posting_date = _require_posting_date(posting_date)
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
	existing = _get_valid_existing_result(idempotency_key, request_payload)
	if existing:
		return existing
	if dry_run:
		return PostResult("Journal Entry", "DRY-RUN", idempotency_key)
	_require_target_write_permissions("Journal Entry", dry_run=False)

	event_name, _request_hash = ensure_event_started(
		idempotency_key=idempotency_key,
		operation="BOOKING_RECEIPT_JE",
		company=company,
		source_doctype="Umre Booking",
		source_name=booking_name,
		request_payload=request_payload,
	)

	# If a previous attempt created the JE but failed before marking the event,
	# adopt it instead of trying to create a duplicate (unique key safety).
	existing_je = frappe.db.get_value(
		"Journal Entry",
		{"umre_posting_key": idempotency_key, "docstatus": 1},
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
		je.insert()
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
	_require_accounting_posting_enabled(dry_run=dry_run)
	_lock_booking_for_posting(booking_name, dry_run=dry_run)
	booking = frappe.get_doc("Umre Booking", booking_name)
	require_document_permission(booking, "read" if dry_run else "write")
	company = _require_company(booking)
	mapping = get_account_mapping(getattr(booking, "company", None))
	if not getattr(booking, "customer", None):
		frappe.throw(_("Booking.customer is required to post Payment Entry receipts."))
	if not mapping.receivable_account:
		frappe.throw(_("Umre Ops Settings.receivable_account is required to post Payment Entry receipts."))

	posting_date = _require_posting_date(posting_date)
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
	existing = _get_valid_existing_result(idempotency_key, request_payload)
	if existing:
		return existing
	if dry_run:
		return PostResult("Payment Entry", "DRY-RUN", idempotency_key)
	_require_target_write_permissions("Payment Entry", dry_run=False)

	event_name, _request_hash = ensure_event_started(
		idempotency_key=idempotency_key,
		operation="BOOKING_RECEIPT_PE",
		company=company,
		source_doctype="Umre Booking",
		source_name=booking_name,
		request_payload=request_payload,
	)

	# Adopt previously created PE by unique posting key.
	existing_pe = frappe.db.get_value(
		"Payment Entry",
		{"umre_posting_key": idempotency_key, "docstatus": 1},
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
		pe.insert()
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
	_require_accounting_posting_enabled(dry_run=dry_run)
	_lock_booking_for_posting(booking_name, dry_run=dry_run)
	booking = frappe.get_doc("Umre Booking", booking_name)
	require_document_permission(booking, "read" if dry_run else "write")
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
	posting_date = _require_posting_date(posting_date)

	# Costs are sourced from the component-based engine. Group component
	# rows by `cost_type` so each cost type maps to a single JE line and a
	# single expense account in `Umre Ops Settings`.
	comp_rows = frappe.db.sql(
		"""
		SELECT cost_type, SUM(amount) AS total
		FROM `tabCost Component`
		WHERE booking = %s
		GROUP BY cost_type
		""",
		(booking_name,),
		as_dict=True,
	)
	cost_type_to_account = {
		"HOTEL":   mapping.hotel_expense_account,
		"FLIGHT":  mapping.flight_expense_account,
		"VISA":    mapping.visa_expense_account,
		"DIYANET": mapping.diyanet_expense_account,
		# MEAL / OTHER / MANUAL / future ad-hoc types fall back to the
		# generic operational expense account if no dedicated mapping exists.
		"MEAL":    mapping.commission_expense_account,
		"OTHER":   mapping.commission_expense_account,
		"MANUAL":  mapping.commission_expense_account,
	}
	lines: list[dict[str, Any]] = []
	total = 0.0
	for row in comp_rows:
		amt = flt(row["total"] or 0)
		if not amt:
			continue
		cost_type = row["cost_type"]
		acc = cost_type_to_account.get(cost_type) or mapping.commission_expense_account
		if not acc:
			frappe.throw(_("Missing expense account mapping for cost type {0}. Configure Umre Ops Settings.").format(cost_type))
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
	existing = _get_valid_existing_result(idempotency_key, request_payload)
	if existing:
		return existing
	if dry_run:
		return PostResult("Journal Entry", "DRY-RUN", idempotency_key)
	_require_target_write_permissions("Journal Entry", dry_run=False)

	event_name, _request_hash = ensure_event_started(
		idempotency_key=idempotency_key,
		operation="BOOKING_COSTS_JE",
		company=company,
		source_doctype="Umre Booking",
		source_name=booking_name,
		request_payload=request_payload,
	)

	# Adopt previously created JE by unique posting key (partial failure safety).
	existing_je = frappe.db.get_value(
		"Journal Entry",
		{"umre_posting_key": idempotency_key, "docstatus": 1},
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
		je.insert()
		je.submit()
		mark_event_succeeded(event_name=event_name, result_doctype="Journal Entry", result_name=je.name)
		return PostResult("Journal Entry", je.name, idempotency_key)
	except Exception as e:
		mark_event_failed(event_name=event_name, error=str(e))
		raise
