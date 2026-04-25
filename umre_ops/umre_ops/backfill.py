# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe

from umre_ops.umre_ops.services.booking_calculation_service import apply_to_booking
from umre_ops.umre_ops.services.payment_service import post_payment_row_receipt


@frappe.whitelist()
def recalculate_all_bookings(limit: int = 0) -> dict:
	"""
	Recompute derived amounts on existing `Umre Booking` documents.
	Safe to re-run. Does not post accounting entries.
	"""
	limit = int(limit or 0)
	names = frappe.get_all("Umre Booking", pluck="name", limit=limit or None, order_by="modified asc")
	updated = 0
	for name in names:
		doc = frappe.get_doc("Umre Booking", name)
		doc.flags.ignore_booking_recalc = True
		apply_to_booking(doc)
		doc.save(ignore_permissions=True)
		updated += 1
	return {"updated": updated, "total": len(names)}


@frappe.whitelist()
def post_all_unposted_payments(paid_account: str, dry_run: int = 1, limit: int = 0) -> dict:
	"""
	Backfill accounting receipts for existing booking payment rows.

	- Only posts child rows where `posting_status` is Draft/empty and amount != 0.
	- Idempotent (Posting Event + downstream unique keys).
	"""
	dry_run = bool(int(dry_run))
	limit = int(limit or 0)

	bookings = frappe.get_all("Umre Booking", pluck="name", limit=limit or None, order_by="modified asc")
	posted = 0
	skipped = 0
	results = []
	for bname in bookings:
		b = frappe.get_doc("Umre Booking", bname)
		for row in b.get("payments") or []:
			if (row.posting_status or "Draft") != "Draft":
				skipped += 1
				continue
			if not row.amount:
				skipped += 1
				continue
			out = post_payment_row_receipt(
				booking_name=bname,
				payment_row_name=row.name,
				paid_account=paid_account,
				dry_run=dry_run,
			)
			results.append(out)
			posted += 1
	return {"dry_run": dry_run, "posted": posted, "skipped": skipped, "results": results}

