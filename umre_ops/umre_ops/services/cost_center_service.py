# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe


def _settings() -> dict:
	try:
		return frappe.get_single("Umre Ops Settings").as_dict()
	except Exception:
		return {}


def get_default_cost_centers() -> dict:
	s = _settings()
	return {
		"umre_operasyon_root": s.get("umre_operasyon_root_cost_center"),
		"genel_gider": s.get("genel_gider_cost_center"),
		"pazarlama": s.get("pazarlama_cost_center"),
	}


def resolve_tour_cost_center(tour_name: str | None) -> str | None:
	"""
	Resolve tour cost center by tour code convention:
	If `Umre Tour.tur_kodu` matches an existing Cost Center name prefix, use it.
	Else, attempt `TUR-YYYY-XX` style direct match against Cost Center names.
	"""
	if not tour_name:
		return None
	tour = frappe.db.get_value("Umre Tour", tour_name, ["tur_kodu"], as_dict=True)
	code = (tour or {}).get("tur_kodu")
	if code and frappe.db.exists("Cost Center", {"cost_center_name": code}):
		# cost center_name match (human name). Use the actual docname.
		return frappe.db.get_value("Cost Center", {"cost_center_name": code}, "name")
	if code and frappe.db.exists("Cost Center", f"{code} - ST"):
		return f"{code} - ST"
	# fallback: use code if it is itself a Cost Center docname
	if code and frappe.db.exists("Cost Center", code):
		return code
	return None


def resolve_booking_cost_center(booking) -> str | None:
	"""
	Default rule:
	- booking revenue/cost -> tour cost center (if resolvable)
	- if not, fallback to Umre Operasyon root (settings) ONLY if it is a leaf cost center
	"""
	tour_cc = resolve_tour_cost_center(getattr(booking, "tur", None))
	if tour_cc:
		return tour_cc
	root = get_default_cost_centers().get("umre_operasyon_root")
	if not root:
		return None
	is_group = frappe.db.get_value("Cost Center", root, "is_group")
	return None if is_group else root


def resolve_commission_cost_center() -> str | None:
	return get_default_cost_centers().get("pazarlama")


def resolve_overhead_cost_center() -> str | None:
	return get_default_cost_centers().get("genel_gider")

