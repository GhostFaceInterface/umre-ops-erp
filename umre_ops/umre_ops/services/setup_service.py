# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe


def verify_setup() -> dict:
	"""
	Validate required configuration and masters for Umre accounting integration.
	This is read-only and safe to run repeatedly.
	"""
	report: dict = {"ok": True, "errors": [], "warnings": [], "details": {}}

	if not frappe.db.exists("DocType", "Umre Ops Settings"):
		report["ok"] = False
		report["errors"].append("Missing DocType: Umre Ops Settings (run migrate).")
		return report

	try:
		s = frappe.get_single("Umre Ops Settings").as_dict()
	except Exception:
		report["ok"] = False
		report["errors"].append("Umre Ops Settings is not created yet. Create and set required fields.")
		return report

	def req(field: str, doctype: str | None = None):
		val = s.get(field)
		if not val:
			report["ok"] = False
			report["errors"].append(f"Missing setting: Umre Ops Settings.{field}")
			return
		if doctype and not frappe.db.exists(doctype, val):
			report["ok"] = False
			report["errors"].append(f"Invalid setting: {field} points to missing {doctype} {val}")

	req("company", "Company")
	for f in (
		"income_account",
		"receivable_account",
		"hotel_expense_account",
		"flight_expense_account",
		"visa_expense_account",
		"diyanet_expense_account",
		"commission_expense_account",
	):
		# not all are strictly required for all flows, but we validate them as warnings if missing
		val = s.get(f)
		if val and not frappe.db.exists("Account", val):
			report["ok"] = False
			report["errors"].append(f"Invalid Account mapping: {f} -> {val}")
		elif not val:
			report["warnings"].append(f"Missing Account mapping: Umre Ops Settings.{f}")

	for f in ("umre_operasyon_root_cost_center", "genel_gider_cost_center", "pazarlama_cost_center"):
		val = s.get(f)
		if val and not frappe.db.exists("Cost Center", val):
			report["ok"] = False
			report["errors"].append(f"Invalid Cost Center mapping: {f} -> {val}")
		elif not val:
			report["warnings"].append(f"Missing Cost Center mapping: Umre Ops Settings.{f}")

	for f in ("havale_mode_of_payment", "elden_mode_of_payment", "taksit_mode_of_payment"):
		val = s.get(f)
		if val and not frappe.db.exists("Mode of Payment", val):
			report["ok"] = False
			report["errors"].append(f"Invalid Mode of Payment mapping: {f} -> {val}")

	report["details"]["settings"] = {k: s.get(k) for k in s.keys()}
	return report

