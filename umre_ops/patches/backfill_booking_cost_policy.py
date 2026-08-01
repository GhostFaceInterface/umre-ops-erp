"""Mark historical bookings as legacy without changing financial values."""

import frappe


def execute() -> None:
	if not frappe.db.has_column("Umre Booking", "cost_policy"):
		return
	frappe.db.sql(
		"""
		update `tabUmre Booking`
		set cost_policy = 'Legacy Manual'
		where cost_policy is null or cost_policy = ''
		"""
	)
