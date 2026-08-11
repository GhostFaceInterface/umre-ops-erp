"""Normalize rule metadata/derived values without touching posted components."""

import frappe
from frappe.utils import flt


def execute() -> None:
	non_usd_tours = [
		{"name": row["name"], "currency": row.get("para_birimi")}
		for row in frappe.get_all(
			"Umre Tour", fields=["name", "para_birimi"], limit_page_length=0
		)
		if row.get("para_birimi") not in (None, "", "USD")
	]
	if non_usd_tours:
		frappe.throw(
			"Tours with non-USD financials require explicit amount conversion; "
			f"no currency labels were changed: {non_usd_tours[:20]}"
		)
	for row in frappe.get_all(
		"Umre Tour", filters={"para_birimi": ["is", "not set"]}, pluck="name", limit_page_length=0
	):
		frappe.db.set_value("Umre Tour", row, "para_birimi", "USD", update_modified=False)
	currency_rules = (
		("Tour Airfare Cost Rule", "para_birimi"),
		("Tour Visa Cost Rule", "para_birimi"),
		("Tour Diyanet Card Rule", "para_birimi"),
		("Other Cost Rule", "currency"),
	)
	invalid_currency: list[dict] = []
	for doctype, currency_field in currency_rules:
		if not frappe.db.exists("DocType", doctype):
			continue
		invalid_currency.extend(
			{
				"doctype": doctype,
				"name": row["name"],
				"currency": row.get(currency_field),
			}
			for row in frappe.get_all(
				doctype,
				fields=["name", currency_field],
				limit_page_length=0,
			)
			if row.get(currency_field) not in (None, "", "USD")
		)
	if invalid_currency:
		frappe.throw(
			"Cost rule currencies require an explicit conversion before USD normalization; "
			f"no data was changed: {invalid_currency[:20]}"
		)
	for doctype, currency_field in (
		*currency_rules,
	):
		if not frappe.db.exists("DocType", doctype):
			continue
		for name in frappe.get_all(doctype, pluck="name", limit_page_length=0):
			frappe.db.set_value(doctype, name, currency_field, "USD", update_modified=False)

	if not frappe.db.exists("DocType", "Tour Hotel Cost Rule"):
		return
	for row in frappe.get_all(
		"Tour Hotel Cost Rule",
		fields=["name", "gece_sayisi", "birim_fiyat_sar", "kur"],
		limit_page_length=0,
	):
		rate = flt(row.get("kur"))
		sar_total = flt(row.get("gece_sayisi")) * flt(row.get("birim_fiyat_sar"))
		if sar_total > 0 and rate <= 0:
			frappe.throw(f"Tour Hotel Cost Rule {row['name']} has a missing SAR/USD rate.")
		if 0 < rate < 1:
			frappe.throw(
				f"Tour Hotel Cost Rule {row['name']} stores an ambiguous rate below 1. "
				"Convert it explicitly to SAR per USD before retrying migrate."
			)
		total = flt(sar_total / rate, 2) if rate > 0 else 0
		frappe.db.set_value(
			"Tour Hotel Cost Rule",
			row["name"],
			{
				"toplam_oda_maliyeti_usd": total,
				"bir_kisilik_oda_maaliyeti": total,
				"iki_kisilik_oda_maliyeti": flt(total / 2, 2),
				"uc_kisilik_oda_maliyeti": flt(total / 3, 2),
				"dort_kisilik_oda_maliyeti": flt(total / 4, 2),
			},
			update_modified=False,
		)
