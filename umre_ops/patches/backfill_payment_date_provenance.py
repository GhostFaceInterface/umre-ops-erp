# Copyright (c) 2026, Sermed Turizm and contributors

"""Classify legacy payment dates without changing the recorded date."""

import frappe


def execute() -> None:
	frappe.db.sql(
		"""
		UPDATE `tabUmre Booking Payment`
		SET
			legacy_posting_date = CASE
				WHEN posting_date IS NOT NULL AND legacy_posting_date IS NULL THEN posting_date
				ELSE legacy_posting_date
			END,
			date_source = CASE
				WHEN COALESCE(date_source, '') = '' THEN 'Legacy'
				ELSE date_source
			END,
			date_verification_status = CASE
				WHEN COALESCE(date_verification_status, '') = '' THEN 'Needs Review'
				ELSE date_verification_status
			END
		WHERE (posting_date IS NOT NULL AND legacy_posting_date IS NULL)
		   OR COALESCE(date_source, '') = ''
		   OR COALESCE(date_verification_status, '') = ''
		"""
	)
