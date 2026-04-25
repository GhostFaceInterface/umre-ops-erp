# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe.utils import cint, flt


def apply_tour_hotel_rule_derived_fields(doc) -> None:
	"""
	Recompute stored derived amounts on `Tour Hotel Cost Rule` from inputs.

	* `toplam_oda_maliyeti_usd` = gece_sayisi * birim_fiyat_sar * kur
	* Per-occupancy columns carry per-person cost assuming one room in this rule
	  is filled at that capacity (common operational shortcut).
	"""
	g = cint(getattr(doc, "gece_sayisi", None) or 0)
	unit = flt(getattr(doc, "birim_fiyat_sar", None) or 0)
	rate = flt(getattr(doc, "kur", None) or 0)
	if not g or not rate:
		doc.toplam_oda_maliyeti_usd = 0.0
	else:
		doc.toplam_oda_maliyeti_usd = flt(g * unit * rate)

	total = flt(doc.toplam_oda_maliyeti_usd)
	# Distribute to per-person cost columns.
	doc.bir_kisilik_oda_maaliyeti = total
	doc.iki_kisilik_oda_maliyeti = flt(total / 2) if total else 0.0
	doc.uc_kisilik_oda_maliyeti = flt(total / 3) if total else 0.0
	doc.dort_kisilik_oda_maliyeti = flt(total / 4) if total else 0.0
