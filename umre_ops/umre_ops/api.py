# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe

from umre_ops.umre_ops.services.setup_service import verify_setup
from umre_ops.umre_ops.services.accounting_service import post_booking_costs_journal_entry


@frappe.whitelist()
def verify_setup_state() -> dict:
	"""API endpoint: validate required configuration for posting."""
	return verify_setup()


@frappe.whitelist()
def post_booking_costs(docname: str, bank_or_cash_account: str, dry_run: int = 0) -> dict:
	"""
	Post operational costs for a booking as Journal Entry (Expense Dr / Bank-Cash Cr).
	Idempotent by deterministic key: one costs JE per booking.
	"""
	key = f"UMRE::{docname}::COSTS::JE"
	res = post_booking_costs_journal_entry(
		booking_name=docname,
		bank_or_cash_account=bank_or_cash_account,
		idempotency_key=key,
		dry_run=bool(int(dry_run)),
	)
	return {"idempotency_key": key, "result_doctype": res.doctype, "result_name": res.name}

