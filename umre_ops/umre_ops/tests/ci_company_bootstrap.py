# Copyright (c) 2026, Sermed Turizm and Contributors
# See license.txt

"""
Create at least one ERPNext Company when the site has ERPNext but no Company (e.g. fresh CI).

Uses ERPNext's setup wizard company helper so chart of accounts is valid. Safe to call repeatedly.
"""

from __future__ import annotations

import frappe


def ensure_at_least_one_company() -> str | None:
	"""
	Ensure tabCompany has at least one row. Returns company name or None if ERPNext is not installed.

	Call from CI after: install-app erpnext, install-app umre_ops, migrate
	(`bench --site test_site execute umre_ops.umre_ops.tests.ci_company_bootstrap.ensure_at_least_one_company`)
	"""
	if not frappe.db.exists("DocType", "Company"):
		frappe.throw("Company DocType not found; install erpnext on the site before running this.")
	existing = frappe.get_all("Company", pluck="name", limit=1)
	if existing:
		return existing[0]

	try:
		from erpnext.accounts.doctype.account.chart_of_accounts.chart_of_accounts import (
			get_charts_for_country,
		)
		from erpnext.setup.setup_wizard.operations.company_setup import get_fy_details
	except ImportError:
		frappe.throw("ERPNext must be installed to create a Company document")

	# `Company.create_default_warehouses` always creates a "Goods In Transit" warehouse
	# with warehouse_type=Transit; fresh sites may not include that `Warehouse Type` yet.
	if not frappe.db.exists("Warehouse Type", "Transit"):
		frappe.get_doc(
			{
				"doctype": "Warehouse Type",
				"name": "Transit",
				"description": "In transit (CI / test site)",
			}
		).insert(ignore_permissions=True)

	country = "India"
	currency = "INR"
	templates = get_charts_for_country(country)
	chart = templates[0] if templates else "Standard"

	fy_start = "2025-04-01"
	fy_end = "2026-03-31"
	fy_name = get_fy_details(fy_start, fy_end)
	if not frappe.db.exists("Fiscal Year", fy_name):
		frappe.get_doc(
			{
				"doctype": "Fiscal Year",
				"year": fy_name,
				"year_start_date": fy_start,
				"year_end_date": fy_end,
			}
		).insert()

	frappe.get_doc(
		{
			"doctype": "Company",
			"company_name": "Umre Ops Test Company",
			"enable_perpetual_inventory": 0,
			"abbr": "UOTC",
			"default_currency": currency,
			"country": country,
			"create_chart_of_accounts_based_on": "Standard Template",
			"chart_of_accounts": chart,
		}
	).insert()

	frappe.db.commit()
	created = frappe.get_all("Company", pluck="name", limit=1)
	return created[0] if created else None


def get_or_create_test_company() -> str:
	"""Resolve a valid Company name for integration tests (creates one if the site is empty)."""
	names = frappe.get_all("Company", pluck="name", limit=1)
	if names:
		return names[0]
	created = ensure_at_least_one_company()
	if created:
		return created
	frappe.throw("No Company available: install ERPNext and run ensure_at_least_one_company()")
