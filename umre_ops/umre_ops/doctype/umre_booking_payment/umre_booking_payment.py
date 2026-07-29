# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

PROTECTED_FIELDS = (
	"posting_date",
	"currency",
	"mode_of_payment",
	"reference_no",
	"reference_date",
	"posting_status",
	"journal_entry",
	"payment_entry",
	"idempotency_key",
	"legacy_posting_date",
	"date_source",
	"date_verification_status",
	"date_evidence_reference",
	"verified_by",
	"verified_on",
	"date_repair_key",
)


def validate_payment_date_provenance(row) -> None:
	if getattr(row, "is_new", lambda: False)():
		row.date_source = getattr(row, "date_source", None) or "Manual"
		row.date_verification_status = (
			getattr(row, "date_verification_status", None) or "Needs Review"
		)
	date_source = getattr(row, "date_source", None)
	verification_status = getattr(row, "date_verification_status", None)
	if not date_source or not verification_status:
		frappe.throw(_("Payment date provenance is missing; run the provenance backfill first."))
	if verification_status == "Verified":
		if date_source == "Legacy":
			frappe.throw(_("A verified payment date requires a non-legacy evidence source."))
		if not all(
			getattr(row, field, None)
			for field in ("verified_by", "verified_on", "date_evidence_reference")
		):
			frappe.throw(_("A verified payment date requires verifier, time, and evidence reference."))


class UmreBookingPayment(Document):
	def validate(self) -> None:
		validate_payment_date_provenance(self)
		if self.is_new() and self.date_verification_status == "Verified":
			frappe.throw(_("Payment dates can be verified only through the reconciliation workflow."))
		if self.is_new():
			return
		old = frappe.db.get_value(
			"Umre Booking Payment",
			self.name,
			["amount", *PROTECTED_FIELDS],
			as_dict=True,
		)
		if not old:
			return
		if self.date_verification_status == "Verified" and old.date_verification_status != "Verified":
			frappe.throw(_("Payment dates can be verified only through the reconciliation workflow."))
		if old.date_verification_status == "Verified" or old.date_repair_key:
			if abs(flt(self.amount) - flt(old.amount)) > 0.000001:
				frappe.throw(_("A verified payment amount cannot be changed."))
			for field in PROTECTED_FIELDS:
				if str(self.get(field) or "") != str(old.get(field) or ""):
					frappe.throw(_("A verified payment field cannot be changed: {0}").format(field))

	def on_trash(self) -> None:
		if self.is_new():
			return
		old = frappe.db.get_value(
			"Umre Booking Payment",
			self.name,
			["date_verification_status", "date_repair_key", "posting_status", "payment_entry", "journal_entry"],
			as_dict=True,
		)
		if old and (
			old.date_verification_status == "Verified"
			or old.date_repair_key
			or old.posting_status == "Posted"
			or old.payment_entry
			or old.journal_entry
		):
			frappe.throw(_("A verified or posted payment row cannot be deleted."))
