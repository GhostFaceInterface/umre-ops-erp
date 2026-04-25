# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
"""
Server-side source of truth for `Umre Booking` pricing and cost fields.

Replaces ad-hoc client-only logic so API, import, and form saves stay aligned.
Assumptions are documented inline; adjust if your operational rules differ.
"""
from __future__ import annotations

import re
from datetime import date
from typing import Any

import frappe
from frappe.utils import cint, flt, getdate

# Must match `Tour Passenger Cost Rule.expense_component` options (first line = flight).
UCAK_COMPONENT = "U\u00e7ak"
PAYING_STATUS = "UMRECI"


def _parse_oda_index(oda_tipi: str | None) -> int:
	"""Map `oda_tipi` (e.g. '1 Kişilik' / '1') to 1|2|3|4."""
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
	"""`Tour Hotel Cost Rule` per-occupancy cost column names (ASCII, post-normalization)."""
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
	"""Heuristic: set Çocuk/Bebek/Normal from date of birth vs tour start when possible."""
	if not (umreci_name and tour_start):
		return None
	ur = frappe.db.get_value(
		"Umreci",
		umreci_name,
		["dogum_tarihi"],
		as_dict=True,
	)
	if not ur or not ur.get("dogum_tarihi"):
		return None
	bd = getdate(ur["dogum_tarihi"])
	age = _age_on_date(bd, tour_start)
	if age < 2:
		return "Bebek"
	if age < 12:
		return "Çocuk"
	return "Normal"


class BookingCalculationService:
	"""Applies all automatic fields on a booking document (mutates in place)."""

	__slots__ = ("doc",)

	def __init__(self, doc: Any):
		self.doc = doc

	def apply(self) -> None:
		self._apply_passenger_defaults()
		if not self._is_paying_customer():
			self._apply_non_paying_rules()
			return
		self.doc.manual_cost = None
		self._set_ucret_from_tour()
		self._set_otel_maliyeti()
		self._set_ucak_maliyeti()
		self._set_vize_maliyeti()
		self._set_diyanet()
		self._set_totals()

	def _status(self) -> str:
		status = (self.doc.get("statu") or PAYING_STATUS).strip()
		return status or PAYING_STATUS

	def _is_paying_customer(self) -> bool:
		return self._status() == PAYING_STATUS

	def _apply_non_paying_rules(self) -> None:
		manual_cost = flt(self.doc.get("manual_cost") or 0)
		self.doc.ucret = 0.0
		self.doc.otel_maliyeti = 0.0
		self.doc.ucak_maliyeti = 0.0
		self.doc.vize_maliyeti = 0.0
		self.doc.diyanet_maliyeti = 0.0
		self.doc.toplam_maliyet = manual_cost
		self.doc.kar = flt(0 - manual_cost - flt(self.doc.kms or 0))

	def _tour(self):
		if not self.doc.tur or not frappe.db.exists("Umre Tour", self.doc.tur):
			return None
		return frappe.get_doc("Umre Tour", self.doc.tur)

	def _tour_start(self) -> date | None:
		t = self._tour()
		if t and t.get("baslangic_tarihi"):
			return getdate(t.baslangic_tarihi)
		return None

	def _apply_passenger_defaults(self) -> None:
		"""
		When `umreci` and `tur` are set, optionally infer `yolcu_tipi` (only if empty).
		Default `vize_tipi` to 'Umre' if unset (matches DocType default).
		"""
		if not self.doc.get("vize_tipi"):
			self.doc.vize_tipi = "Umre"
		if self.doc.get("yolcu_tipi") or not self.doc.get("umreci"):
			return
		start = self._tour_start()
		inferred = infer_yolcu_tipi_from_umreci(self.doc.umreci, start)
		if inferred:
			self.doc.yolcu_tipi = inferred

	def _set_ucret_from_tour(self) -> None:
		"""List price on the selected tour for the room capacity (`oda_tipi`)."""
		t = self._tour()
		if not t:
			return
		idx = _parse_oda_index(self.doc.get("oda_tipi"))
		field = _tour_field_for_oda(idx)
		self.doc.ucret = flt(getattr(t, field, None) or 0)

	def _set_otel_maliyeti(self) -> None:
		"""
		Sum per-person hotel cost from all `Tour Hotel Cost Rule` rows for this tour
		that match the booking's room size (column selected by `oda_tipi`).
		"""
		if not self.doc.tur:
			return
		idx = _parse_oda_index(self.doc.get("oda_tipi"))
		field = _rule_field_for_oda_maaliyet(idx)
		rules = frappe.get_all(
			"Tour Hotel Cost Rule",
			filters={"tur": self.doc.tur},
			pluck="name",
		)
		total = 0.0
		for rname in rules:
			row = frappe.db.get_value("Tour Hotel Cost Rule", rname, [field], as_dict=True)
			if row and row.get(field) is not None:
				total += flt(row[field])
		self.doc.otel_maliyeti = flt(total)

	def _set_ucak_maliyeti(self) -> None:
		"""`Tour Passenger Cost Rule` row: flight segment for this tour + passenger type."""
		if not (self.doc.tur and self.doc.get("yolcu_tipi")):
			return
		name = frappe.db.get_value(
			"Tour Passenger Cost Rule",
			{
				"tur": self.doc.tur,
				"yolcu_tipi": self.doc.yolcu_tipi,
				"expense_component": UCAK_COMPONENT,
			},
			"name",
		)
		if not name:
			self.doc.ucak_maliyeti = 0.0
			return
		self.doc.ucak_maliyeti = flt(
			frappe.db.get_value("Tour Passenger Cost Rule", name, "tutar") or 0
		)

	def _set_vize_maliyeti(self) -> None:
		if not (self.doc.tur and self.doc.get("vize_tipi")):
			return
		name = frappe.db.get_value(
			"Tour Visa Cost Rule",
			{"tur": self.doc.tur, "vize_tipi": self.doc.vize_tipi},
			"name",
		)
		if not name:
			self.doc.vize_maliyeti = 0.0
			return
		self.doc.vize_maliyeti = flt(frappe.db.get_value("Tour Visa Cost Rule", name, "tutar") or 0)

	def _set_diyanet(self) -> None:
		if not self._is_paying_customer():
			self.doc.diyanet_maliyeti = 0.0
			return
		if not cint(self.doc.get("diyanet_kart_var")) or not self.doc.tur:
			self.doc.diyanet_maliyeti = 0.0
			return
		name = frappe.db.get_value(
			"Tour Diyanet Card Rule",
			{"tur": self.doc.tur},
			"name",
		)
		if not name:
			self.doc.diyanet_maliyeti = 0.0
			return
		self.doc.diyanet_maliyeti = flt(
			frappe.db.get_value("Tour Diyanet Card Rule", name, "tutar") or 0
		)

	def _set_totals(self) -> None:
		otel = flt(self.doc.otel_maliyeti)
		ucak = flt(self.doc.ucak_maliyeti)
		vize = flt(self.doc.vize_maliyeti)
		diy = flt(self.doc.diyanet_maliyeti)
		self.doc.toplam_maliyet = flt(otel + ucak + vize + diy)
		# Kâr: listed sales price minus all computed operating costs; KMS treated as an extra
		# deduction (matches typical desk behaviour where it reduced margin).
		ucret = flt(self.doc.ucret)
		kms = flt(self.doc.kms or 0)
		self.doc.kar = flt(ucret - self.doc.toplam_maliyet - kms)


def apply_to_booking(doc) -> None:
	BookingCalculationService(doc).apply()
