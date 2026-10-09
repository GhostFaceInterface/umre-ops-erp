# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
"""
Read-only financial view for `Umre Booking`.

DESIGN INTENT
-------------
The booking is the *imported truth*. Its financial inputs (`statu`, `ucret`,
`kms`, `manual_cost`) are locked after import (`Umre Booking.locked_financials`).

This service NEVER writes financial fields. It only:
  - sets `vize_tipi` to its UI default if missing;
  - infers `yolcu_tipi` from `Umreci.dogum_tarihi` and the tour start date when
    it is empty or when the booking's passenger / tour changes.

Revenue / cost / profit for a single booking are derived on demand by
`BookingCalculationService.compute_view(doc)`, using the same pure function as
the persisted cost components (`cost_engine.compute_cost_lines`), so the desk
preview, the persisted components and the reports agree.
"""
from __future__ import annotations

from datetime import date
from typing import Any

import frappe
from frappe.utils import cint, flt, getdate

from umre_ops.umre_ops.services import cost_engine

PAYING_STATUS = cost_engine.PAYING_STATUS


def _age_on_date(birth: date, on: date) -> int:
	years = on.year - birth.year
	if (on.month, on.day) < (birth.month, birth.day):
		years -= 1
	return years


def passenger_type_for_age(age: int) -> str:
	if age < 2:
		return "Bebek"
	if age < 12:
		return "Çocuk"
	return "Normal"


def infer_yolcu_tipi_from_umreci(umreci_name: str | None, tour_start: date | None) -> str | None:
	if not (umreci_name and tour_start):
		return None
	birth = frappe.db.get_value("Umreci", umreci_name, "dogum_tarihi")
	if not birth:
		return None
	return passenger_type_for_age(_age_on_date(getdate(birth), tour_start))


def _tour_start(tur: str | None) -> date | None:
	if not tur:
		return None
	start = frappe.db.get_value("Umre Tour", tur, "baslangic_tarihi")
	return getdate(start) if start else None


class BookingCalculationService:
	"""Soft passenger-default applier (read-only for finance)."""

	__slots__ = ("doc",)

	def __init__(self, doc: Any):
		self.doc = doc

	def apply(self) -> None:
		"""Set safe, non-financial defaults. NEVER touches statu/ucret/kms/cost."""
		if not self.doc.get("vize_tipi"):
			self.doc.vize_tipi = "Umre"
		if not self.doc.get("umreci"):
			return
		if self.doc.get("yolcu_tipi") and not self._passenger_or_tour_changed():
			return
		inferred = infer_yolcu_tipi_from_umreci(self.doc.umreci, _tour_start(self.doc.get("tur")))
		if inferred:
			self.doc.yolcu_tipi = inferred

	def _passenger_or_tour_changed(self) -> bool:
		has_changed = getattr(self.doc, "has_value_changed", None)
		is_new = getattr(self.doc, "is_new", None)
		if not callable(has_changed) or (callable(is_new) and is_new()):
			return False
		return bool(has_changed("umreci") or has_changed("tur"))

	@staticmethod
	def compute_view(doc, ctx: cost_engine.TourCostContext | None = None) -> dict:
		"""Return the financial view of one booking. NO mutation.

		UMRECI:     net revenue = ucret − kms
		NON-UMRECI: revenue = 0
		cost   = cost_engine lines (same function as persisted components)
		profit = net revenue − cost
		"""
		inputs = cost_engine.booking_cost_inputs(doc)
		if ctx is None or ctx.tour != inputs["tur"]:
			ctx = cost_engine.load_tour_cost_context(inputs["tur"])
		lines, issues = cost_engine.compute_cost_lines(inputs, ctx)
		by_type = cost_engine.summarize_lines(lines)
		is_umreci = inputs["statu"] == PAYING_STATUS
		cancelled = bool(inputs["iptal_edildi"])
		revenue = flt(doc.get("ucret") or 0) if is_umreci and not cancelled else 0.0
		kms = flt(doc.get("kms") or 0) if is_umreci and not cancelled else 0.0
		net_revenue = flt(revenue - kms)
		cost = flt(sum(by_type.values()))
		paid = flt(doc.get("odenen") or 0)
		return {
			"statu": inputs["statu"],
			"is_umreci": is_umreci,
			"iptal_edildi": cint(cancelled),
			"revenue": revenue,
			"kms": kms,
			"net_revenue": net_revenue,
			"otel_maliyeti": by_type.get("HOTEL", 0.0),
			"ucak_maliyeti": by_type.get("FLIGHT", 0.0),
			"vize_maliyeti": by_type.get("VISA", 0.0),
			"diyanet_maliyeti": by_type.get("DIYANET", 0.0),
			"yemek_maliyeti": by_type.get("MEAL", 0.0),
			"diger_maliyet": by_type.get("OTHER", 0.0),
			"manual_cost": by_type.get("MANUAL", 0.0),
			"toplam_maliyet": cost,
			"net_kar": flt(net_revenue - cost),
			"odenen": paid,
			"kalan_alacak": flt(max(revenue - paid, 0.0)),
			"issues": issues,
		}


def refresh_passenger_types(*, umreci: str | None = None, tur: str | None = None) -> int:
	"""Re-infer `yolcu_tipi` after a birth date / tour start change.

	Saving a booking whose type changed triggers its cost recompute
	(`Umre Booking.on_update`). Bookings with a submitted cost posting are skipped.
	"""
	filters = {"umreci": umreci} if umreci else {"tur": tur}
	if not (umreci or tur):
		return 0
	changed = 0
	for row in frappe.get_all(
		"Umre Booking", filters=filters, fields=["name", "umreci", "tur", "yolcu_tipi"], limit_page_length=0
	):
		inferred = infer_yolcu_tipi_from_umreci(row["umreci"], _tour_start(row["tur"]))
		if not inferred or inferred == row.get("yolcu_tipi"):
			continue
		if cost_engine._has_submitted_cost_posting(row["name"]):
			continue
		booking = frappe.get_doc("Umre Booking", row["name"])
		booking.yolcu_tipi = inferred
		booking.save(ignore_permissions=True)
		changed += 1
	return changed


def apply_to_booking(doc) -> None:
	"""Document-level entry point. Soft defaults only — no financial mutation."""
	BookingCalculationService(doc).apply()


def compute_booking_view(doc) -> dict:
	"""Convenience wrapper for the read-only view."""
	return BookingCalculationService.compute_view(doc)
