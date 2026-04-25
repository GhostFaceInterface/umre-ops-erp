# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

import json

import frappe
from frappe.exceptions import PermissionError
from frappe.model.document import Document
from frappe.utils import flt

from umre_ops.umre_ops.services.booking_calculation_service import apply_to_booking


class UmreBooking(Document):
	"""Recomputes list price, cost components, totals, and margin on every save."""

	def validate(self) -> None:
		if not getattr(self, "flags", None) or not self.flags.get("ignore_booking_recalc"):
			apply_to_booking(self)


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
		frappe.throw("Not permitted to preview booking calculations", exc=PermissionError)
	if isinstance(doc, str):
		data = json.loads(doc)
	else:
		data = doc or {}
	temp = frappe.get_doc({"doctype": "Umre Booking", **data})
	apply_to_booking(temp)
	return {
		"yolcu_tipi": temp.get("yolcu_tipi"),
		"vize_tipi": temp.get("vize_tipi"),
		"ucret": flt(temp.get("ucret")),
		"otel_maliyeti": flt(temp.get("otel_maliyeti")),
		"ucak_maliyeti": flt(temp.get("ucak_maliyeti")),
		"vize_maliyeti": flt(temp.get("vize_maliyeti")),
		"diyanet_maliyeti": flt(temp.get("diyanet_maliyeti")),
		"toplam_maliyet": flt(temp.get("toplam_maliyet")),
		"kar": flt(temp.get("kar")),
	}
