# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
"""
Read-only financial view for `Umre Booking`.

DESIGN INTENT
-------------
This module USED to mutate `Umre Booking` rows on every save: rewriting `ucret`
from the tour's room price, recomputing `otel_maliyeti` / `ucak_maliyeti` /
`vize_maliyeti` / `diyanet_maliyeti` / `toplam_maliyet` / `kar`, and even
zeroing `ucret` for non-paying participants. That mutation pipeline was the
root cause of two distinct revenue-drift bugs (status flips and `ucret`
overwrites) confirmed in forensic reports. It has been REMOVED.

The new contract is:

* The booking is the *imported truth*. Its three financial inputs
  (`statu`, `ucret`, `manual_cost`) are immutable after import (gated by
  `Umre Booking.locked_financials` and the document-level guard).
* This service NEVER writes to financial fields. It only:
    - Sets `vize_tipi` to its UI default if missing.
    - Infers `yolcu_tipi` from `Umreci.dogum_tarihi` once when empty.
* All revenue / cost / profit numbers are derived on demand by
  `BookingCalculationService.compute_view(doc)`, which returns a snapshot
  dict and DOES NOT touch `doc`. The Tour Revenue Summary report and the
  desk preview API are the only consumers of this snapshot.

If you need to "save the totals" again, do it in an explicit, audited path
(a manual recompute action). Do NOT add it to validate().
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

import frappe
from frappe.utils import flt, getdate

PAYING_STATUS = "UMRECI"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _parse_oda_index(oda_tipi: str | None) -> int:
	if not oda_tipi:
		return 1
	m = re.match(r"^(\d+)", str(oda_tipi).strip())
	if m:
		n = int(m.group(1))
		return min(max(n, 1), 4)
	return 1


def _tour_field_for_oda(idx: int) -> str:
	return {
		1: "bir_kisilik_oda",
		2: "iki_kisilik_oda",
		3: "uc_kisilik_oda",
		4: "dort_kisilik_oda",
	}[idx]


def _rule_field_for_oda_maaliyet(idx: int) -> str:
	return {
		1: "bir_kisilik_oda_maaliyeti",
		2: "iki_kisilik_oda_maliyeti",
		3: "uc_kisilik_oda_maliyeti",
		4: "dort_kisilik_oda_maliyeti",
	}[idx]


def _age_on_date(birth: date, on: date) -> int:
	years = on.year - birth.year
	if (on.month, on.day) < (birth.month, birth.day):
		years -= 1
	return years


def infer_yolcu_tipi_from_umreci(umreci_name: str | None, tour_start: date | None) -> str | None:
	if not (umreci_name and tour_start):
		return None
	ur = frappe.db.get_value("Umreci", umreci_name, ["dogum_tarihi"], as_dict=True)
	if not ur or not ur.get("dogum_tarihi"):
		return None
	bd = getdate(ur["dogum_tarihi"])
	age = _age_on_date(bd, tour_start)
	if age < 2:
		return "Bebek"
	if age < 12:
		return "Çocuk"
	return "Normal"


# ---------------------------------------------------------------------------
# Pure cost lookups (read-only)
# ---------------------------------------------------------------------------

def _tour_doc(tur: str | None):
	if not tur or not frappe.db.exists("Umre Tour", tur):
		return None
	return frappe.get_doc("Umre Tour", tur)


def lookup_hotel_cost(tur: str | None, oda_tipi: str | None) -> float:
	if not tur:
		return 0.0
	idx = _parse_oda_index(oda_tipi)
	field = _rule_field_for_oda_maaliyet(idx)
	rules = frappe.get_all("Tour Hotel Cost Rule", filters={"tur": tur}, pluck="name")
	total = 0.0
	for rname in rules:
		row = frappe.db.get_value("Tour Hotel Cost Rule", rname, [field], as_dict=True)
		if row and row.get(field) is not None:
			total += flt(row[field])
	return flt(total)


def lookup_flight_cost(tur: str | None, yolcu_tipi: str | None) -> float:
	if not (tur and yolcu_tipi):
		return 0.0
	name = frappe.db.get_value(
		"Tour Airfare Cost Rule",
		{"tur": tur, "yolcu_tipi": yolcu_tipi},
		"name",
	)
	if not name:
		return 0.0
	return flt(frappe.db.get_value("Tour Airfare Cost Rule", name, "tutar") or 0)


def lookup_visa_cost(tur: str | None, vize_tipi: str | None) -> float:
	if not (tur and vize_tipi):
		return 0.0
	name = frappe.db.get_value(
		"Tour Visa Cost Rule",
		{"tur": tur, "vize_tipi": vize_tipi},
		"name",
	)
	if not name:
		return 0.0
	return flt(frappe.db.get_value("Tour Visa Cost Rule", name, "tutar") or 0)


def lookup_diyanet_cost(tur: str | None, _diyanet_kart_var: int | None = None) -> float:
	"""Tour `Tour Diyanet Card Rule` sets tutar. The booking checkbox is not a gate (legacy bug)."""
	if not tur:
		return 0.0
	name = frappe.db.get_value("Tour Diyanet Card Rule", {"tur": tur}, "name")
	if not name:
		return 0.0
	return flt(frappe.db.get_value("Tour Diyanet Card Rule", name, "tutar") or 0)


# ---------------------------------------------------------------------------
# Read-only service
# ---------------------------------------------------------------------------

class BookingCalculationService:
	"""Soft passenger-default applier (read-only for finance)."""

	__slots__ = ("doc",)

	def __init__(self, doc: Any):
		self.doc = doc

	# Mutation surface — strictly limited to non-financial UI defaults.
	def apply(self) -> None:
		"""Set safe, non-financial defaults. NEVER touches statu/ucret/cost.

		Mutated fields (UI defaults only):
			- vize_tipi (default "Umre" when empty)
			- yolcu_tipi (inferred once from Umreci birth date when empty)
		"""
		self._apply_passenger_defaults()

	def _apply_passenger_defaults(self) -> None:
		if not self.doc.get("vize_tipi"):
			self.doc.vize_tipi = "Umre"
		if self.doc.get("yolcu_tipi") or not self.doc.get("umreci"):
			return
		t = _tour_doc(self.doc.get("tur"))
		start = getdate(t.baslangic_tarihi) if t and t.get("baslangic_tarihi") else None
		inferred = infer_yolcu_tipi_from_umreci(self.doc.umreci, start)
		if inferred:
			self.doc.yolcu_tipi = inferred

	# Read surface — pure functions.
	@staticmethod
	def compute_view(doc) -> dict:
		"""Return the immutable financial view of a booking. NO mutation.

		Strict business model:
			UMRECI:     revenue = ucret
			            cost    = hotel + flight + visa + diyanet
			NON-UMRECI: revenue = 0
			            cost    = manual_cost
			profit = revenue - cost
		"""
		statu = (doc.get("statu") or PAYING_STATUS).strip() or PAYING_STATUS
		is_umreci = statu == PAYING_STATUS
		tur = doc.get("tur")
		oda_tipi = doc.get("oda_tipi")
		yolcu_tipi = doc.get("yolcu_tipi")
		vize_tipi = doc.get("vize_tipi")
		diyanet_kart_var = doc.get("diyanet_kart_var")

		uses_system_cost = is_umreci or doc.get("cost_policy") == "System Rules"
		if uses_system_cost:
			otel = lookup_hotel_cost(tur, oda_tipi)
			ucak = lookup_flight_cost(tur, yolcu_tipi)
			vize = lookup_visa_cost(tur, vize_tipi)
			diy = lookup_diyanet_cost(tur, diyanet_kart_var)
			revenue = flt(doc.get("ucret") or 0) if is_umreci else 0.0
			cost = flt(otel + ucak + vize + diy)
			manual = 0.0
		else:
			otel = 0.0
			ucak = 0.0
			vize = 0.0
			diy = 0.0
			revenue = 0.0
			manual = flt(doc.get("manual_cost") or 0)
			cost = manual

		return {
			"statu": statu,
			"is_umreci": is_umreci,
			"revenue": revenue,
			"otel_maliyeti": otel,
			"ucak_maliyeti": ucak,
			"vize_maliyeti": vize,
			"diyanet_maliyeti": diy,
			"manual_cost": manual,
			"toplam_maliyet": cost,
			"net_kar": flt(revenue - cost),
			"odenen": flt(doc.get("odenen") or 0),
			"kalan_alacak": flt(revenue - flt(doc.get("odenen") or 0)),
		}


def apply_to_booking(doc) -> None:
	"""Document-level entry point. Soft defaults only — no financial mutation."""
	BookingCalculationService(doc).apply()


def compute_booking_view(doc) -> dict:
	"""Convenience wrapper for the read-only view."""
	return BookingCalculationService.compute_view(doc)
