# Copyright (c) 2026, Sermed Turizm and contributors

"""Classify legacy payment dates without changing the recorded date."""

import frappe


def execute() -> None:
	frappe.db.sql(
		"""
		UPDATE `tabUmre Booking Payment`
		SET legacy_posting_date = posting_date
		WHERE posting_date IS NOT NULL
		  AND legacy_posting_date IS NULL
		"""
	)
	frappe.db.sql(
		"""
		UPDATE `tabUmre Booking Payment`
		SET date_source = 'Legacy'
		WHERE COALESCE(date_source, '') = ''
		"""
	)
	frappe.db.sql(
		"""
		UPDATE `tabUmre Booking Payment`
		SET date_verification_status = 'Needs Review'
		WHERE COALESCE(date_verification_status, '') = ''
		"""
	)
