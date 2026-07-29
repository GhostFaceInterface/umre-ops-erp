# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.exceptions import PermissionError
from frappe.model.document import Document
from frappe.utils import flt

from umre_ops.umre_ops.doctype.umre_booking_payment.umre_booking_payment import (
	validate_payment_date_provenance,
)
from umre_ops.umre_ops.services import cost_engine
from umre_ops.umre_ops.services.booking_calculation_service import (
	apply_to_booking,
	compute_booking_view,
)


class UmreBooking(Document):
	"""Recomputes list price, cost components, totals, and margin on every save."""

	def validate(self) -> None:
		for payment in self.get("payments") or []:
			validate_payment_date_provenance(payment)
		# 1) Hard immutability gate. If `locked_financials` is set we forbid ANY
		#    change to `statu`, `ucret`, or `manual_cost` from this point on.
		#    Bypass is intentional and explicit via `flags.ignore_financial_lock`
		#    (used only by the corrective patch).
		self._enforce_financial_lock()
		self._enforce_posted_payment_lock()

		# 2) Pure read-only "soft defaults" (`vize_tipi`, `yolcu_tipi`). These
		#    NEVER touch financial fields. The previous mutation chain that
		#    silently rewrote ucret / cost columns has been removed; financial
		#    truth now flows from Excel → import → DB → report (immutable).
		if not getattr(self, "flags", None) or not self.flags.get("ignore_booking_recalc"):
			apply_to_booking(self)

		self._sync_paid_amount_from_payments()

	def after_insert(self) -> None:
		"""One-shot Cost Component generation. Idempotent: subsequent imports
		will be locked anyway by the financial-lock guard, and `generate_components`
		will no-op if rows already exist."""
		try:
			cost_engine.generate_components(self)
		except Exception:
			# Re-raise — the booking is already inserted; ops needs to know
			# that the cost engine could not produce its components, because
			# downstream reports / accounting depend on them.
			raise
		try:
			from umre_ops.umre_ops.services.dashboard_service import publish_dashboard_dirty
			publish_dashboard_dirty(self.tur)
		except Exception:
			frappe.log_error(title="dashboard publish failed (booking after_insert)")

	def _enforce_financial_lock(self) -> None:
		"""Reject silent mutation of locked financial fields.

		Three immutable fields after the booking is `locked_financials = 1`:
		`statu`, `ucret`, `manual_cost`. The previous data-corruption pattern
		(re-import or `validate()` re-save silently rewriting these) is
		structurally impossible while this guard is in place.
		"""
		if self.is_new() or not self.get("locked_financials"):
			return
		flags = getattr(self, "flags", None)
		if flags is not None and flags.get("ignore_financial_lock"):
			return
		db_doc = frappe.db.get_value(
			"Umre Booking",
			self.name,
			["statu", "ucret", "manual_cost"],
			as_dict=True,
		)
		if not db_doc:
			return

		new_statu = (self.get("statu") or "").strip()
		old_statu = (db_doc.get("statu") or "").strip()
		if new_statu != old_statu:
			frappe.throw(
				_("Locked field 'statu' cannot be modified after import (was {0}, attempted {1}).").format(
					old_statu or "?", new_statu or "?"
				)
			)
		new_ucret = flt(self.get("ucret") or 0)
		old_ucret = flt(db_doc.get("ucret") or 0)
		if abs(new_ucret - old_ucret) > 0.01:
			frappe.throw(
				_("Locked field 'ucret' cannot be modified after import (was {0}, attempted {1}).").format(
					old_ucret, new_ucret
				)
			)
		new_mc = flt(self.get("manual_cost") or 0)
		old_mc = flt(db_doc.get("manual_cost") or 0)
		if abs(new_mc - old_mc) > 0.01:
			frappe.throw(
				_("Locked field 'manual_cost' cannot be modified after import (was {0}, attempted {1}).").format(
					old_mc, new_mc
				)
			)

	def _sync_paid_amount_from_payments(self) -> None:
		"""
		Backward-compatible normalization:
		- If `payments` child table is used, keep `odenen` equal to the sum of payment rows.
		- Do not create any accounting entries here; posting is explicit via services/APIs.
		"""
		if not self.get("payments"):
			return
		total = 0.0
		for row in self.get("payments") or []:
			amt = flt(getattr(row, "amount", 0) or 0)
			total += amt
		self.odenen = flt(total)

	def _enforce_posted_payment_lock(self) -> None:
		"""Do not allow a submitted accounting voucher's source row to drift."""
		if self.is_new():
			if any(
				row.get("date_verification_status") == "Verified" for row in self.get("payments") or []
			):
				frappe.throw(_("Payment dates can be verified only through the reconciliation workflow."))
			return
		flags = getattr(self, "flags", None)
		posting_transition_scope = (
			flags.get("accounting_posting_transition") if flags is not None else None
		) or {}
		persisted = frappe.get_all(
			"Umre Booking Payment",
			filters={"parent": self.name, "parenttype": "Umre Booking", "parentfield": "payments"},
			fields=[
				"name",
				"posting_date",
				"amount",
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
			],
			limit_page_length=0,
		)
		protected = {
			row.name: row
			for row in persisted
			if row.posting_status == "Posted"
			or row.journal_entry
			or row.payment_entry
			or row.date_verification_status == "Verified"
			or row.date_repair_key
		}
		if not protected:
			return
		current = {row.name: row for row in self.get("payments") or [] if row.name}
		persisted_by_name = {row.name: row for row in persisted}
		for row in self.get("payments") or []:
			old = persisted_by_name.get(row.name)
			if row.get("date_verification_status") == "Verified" and (
				not old or old.date_verification_status != "Verified"
			):
				frappe.throw(_("Payment dates can be verified only through the reconciliation workflow."))
		for row_name, old in protected.items():
			new = current.get(row_name)
			if not new:
				frappe.throw(_("Protected payment row {0} cannot be deleted.").format(row_name))
			if abs(flt(new.amount) - flt(old.amount)) > 0.000001:
				frappe.throw(_("Protected payment row {0} amount cannot be changed.").format(row_name))
			posting_transition = (
				posting_transition_scope.get("payment_row_name") == row_name
				and old.date_verification_status == "Verified"
				and (old.posting_status or "Draft") == "Draft"
				and not old.journal_entry
				and not old.payment_entry
				and new.get("date_verification_status") == "Verified"
				and new.get("posting_status") == "Posted"
				and new.get("idempotency_key") == posting_transition_scope.get("idempotency_key")
				and (
					(
						posting_transition_scope.get("expected_doctype") == "Journal Entry"
						and new.get("journal_entry") == posting_transition_scope.get("voucher_name")
						and not new.get("payment_entry")
					)
					or (
						posting_transition_scope.get("expected_doctype") == "Payment Entry"
						and new.get("payment_entry") == posting_transition_scope.get("voucher_name")
						and not new.get("journal_entry")
					)
				)
			)
			for field in (
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
			):
				if str(new.get(field) or "") != str(old.get(field) or ""):
					if posting_transition and field in {
						"posting_status",
						"journal_entry",
						"payment_entry",
						"idempotency_key",
					}:
						continue
					frappe.throw(
						_("Protected payment row {0} field {1} cannot be changed.").format(row_name, field)
					)


@frappe.whitelist()
def preview_calculated_fields(doc) -> dict:
	"""
	Recompute derived amounts for desk preview; does not save.

	:param doc: JSON string (or dict) of field values for a Partial Umre Booking.
	"""
	if not (
		frappe.has_permission("Umre Booking", "read", throw=False)
		or frappe.has_permission("Umre Booking", "write", throw=False)
		or frappe.has_permission("Umre Booking", "create", throw=False)
	):
		frappe.throw(_("Not permitted to preview booking calculations"), exc=PermissionError)
	if isinstance(doc, str):
		data = json.loads(doc)
	else:
		data = doc or {}
	# Soft defaults (vize_tipi / yolcu_tipi) plus pure read-only financial
	# view. Nothing is written to disk — preview never causes drift.
	temp = frappe.get_doc({"doctype": "Umre Booking", **data})
	apply_to_booking(temp)
	view = compute_booking_view(temp)
	return {
		"statu": view["statu"],
		"manual_cost": flt(view["manual_cost"]),
		"yolcu_tipi": temp.get("yolcu_tipi"),
		"vize_tipi": temp.get("vize_tipi"),
		"ucret": flt(view["revenue"]),
		"otel_maliyeti": flt(view["otel_maliyeti"]),
		"ucak_maliyeti": flt(view["ucak_maliyeti"]),
		"vize_maliyeti": flt(view["vize_maliyeti"]),
		"diyanet_maliyeti": flt(view["diyanet_maliyeti"]),
		"toplam_maliyet": flt(view["toplam_maliyet"]),
		"kar": flt(view["net_kar"]),
	}
