# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

from dataclasses import dataclass

import frappe


@dataclass(frozen=True)
class UmreAccountMapping:
	company: str
	income_account: str | None
	receivable_account: str | None
	hotel_expense_account: str | None
	flight_expense_account: str | None
	visa_expense_account: str | None
	diyanet_expense_account: str | None
	commission_expense_account: str | None
	havale_mode_of_payment: str | None
	elden_mode_of_payment: str | None
	taksit_mode_of_payment: str | None


def get_settings() -> dict:
	"""Returns singleton `Umre Ops Settings` dict (empty if not created yet)."""
	try:
		return frappe.get_single("Umre Ops Settings").as_dict()
	except Exception:
		return {}


def get_account_mapping(company: str | None = None) -> UmreAccountMapping:
	s = get_settings()
	company = company or s.get("company")
	if not company:
		frappe.throw("Umre Ops Settings.company is required for accounting posting.")
	return UmreAccountMapping(
		company=company,
		income_account=s.get("income_account"),
		receivable_account=s.get("receivable_account"),
		hotel_expense_account=s.get("hotel_expense_account"),
		flight_expense_account=s.get("flight_expense_account"),
		visa_expense_account=s.get("visa_expense_account"),
		diyanet_expense_account=s.get("diyanet_expense_account"),
		commission_expense_account=s.get("commission_expense_account"),
		havale_mode_of_payment=s.get("havale_mode_of_payment"),
		elden_mode_of_payment=s.get("elden_mode_of_payment"),
		taksit_mode_of_payment=s.get("taksit_mode_of_payment"),
	)


def map_odeme_turu_to_mode_of_payment(odeme_turu: str | None, mapping: UmreAccountMapping) -> str | None:
	"""
	Translate legacy `Umre Booking.odeme_turu` values to an ERPNext Mode of Payment.
	"""
	if not odeme_turu:
		return None
	key = str(odeme_turu).strip().lower()
	if key == "havale":
		return mapping.havale_mode_of_payment
	if key == "elden":
		return mapping.elden_mode_of_payment
	if key == "taksit":
		return mapping.taksit_mode_of_payment
	return None

