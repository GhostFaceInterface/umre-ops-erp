# Copyright (c) 2026, Sermed Turizm and contributors
#
# Seeds banks, suggested expense categories, and optional Umre Money Account rows.

from __future__ import annotations

import frappe


def execute():
	if not frappe.db.exists("DocType", "Umre Financial Institution"):
		return

	inst_specs = (
		("Ziraat Bankası", "Bank"),
		("Kuveyt Türk", "Bank"),
		("Al Baraka", "Bank"),
	)
	for name, itype in inst_specs:
		if frappe.db.exists("Umre Financial Institution", name):
			continue
		doc = frappe.get_doc(
			{"doctype": "Umre Financial Institution", "institution_name": name, "institution_type": itype, "is_active": 1}
		)
		doc.insert(ignore_permissions=True)

	# Short labels for Umre Money Account.display names — not hard-coded business rules.
	short = {"Ziraat Bankası": "Ziraat", "Kuveyt Türk": "Kuveyt Türk", "Al Baraka": "Al Baraka"}
	ccy = ("USD", "SAR", "TRY", "EUR")

	for bank_name in short.keys():
		if not frappe.db.exists("Umre Financial Institution", bank_name):
			continue
		for cur in ccy:
			alabel = f"{short[bank_name]} {cur}"
			exists = frappe.db.sql(
				"""
				SELECT name FROM `tabUmre Money Account`
				WHERE account_name=%s AND institution=%s AND currency=%s
				LIMIT 1
				""",
				(alabel, bank_name, cur),
			)
			if exists:
				continue
			frappe.get_doc(
				{
					"doctype": "Umre Money Account",
					"account_name": alabel,
					"institution": bank_name,
					"account_type": "Bank",
					"currency": cur,
					"is_active": 1,
				}
			).insert(ignore_permissions=True)

	if frappe.db.exists("DocType", "Operational Expense Category"):
		categories = (
			"Ofis Giderleri",
			"Kira",
			"Elektrik",
			"Su",
			"Doğalgaz",
			"İnternet",
			"Personel Giderleri",
			"Pazarlama",
			"Reklam",
			"Vergiler",
			"IT / Yazılım",
			"Diğer Giderler",
		)
		for i, nm in enumerate(categories):
			if frappe.db.exists("Operational Expense Category", nm):
				continue
			doc = frappe.get_doc(
				{
					"doctype": "Operational Expense Category",
					"category_name": nm,
					"is_group": 0,
					"is_active": 1,
					"sort_order": i * 10,
				}
			)
			doc.insert(ignore_permissions=True)

	if frappe.db.exists("DocType", "Umre Season"):
		sn = "2026-2027 Sezonu"
		if not frappe.db.exists("Umre Season", sn):
			frappe.get_doc(
				{"doctype": "Umre Season", "season_name": sn, "is_active": 1}
			).insert(ignore_permissions=True)

	frappe.db.commit()
