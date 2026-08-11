"""Stop migration if deprecated configuration days conflict with hotel nights."""

from __future__ import annotations

import frappe
from frappe.utils import cint


def execute() -> None:
	if not frappe.db.exists("DocType", "Tour Cost Configuration"):
		return
	mismatches: list[dict] = []
	for config in frappe.get_all(
		"Tour Cost Configuration",
		fields=["name", "tour", "mekke_days", "medine_days"],
		limit_page_length=0,
	):
		nights = {"Mekke": 0, "Medine": 0}
		for row in frappe.get_all(
			"Tour Hotel Cost Rule",
			filters={"tur": config["tour"], "lokasyon": ["in", ["Mekke", "Medine"]]},
			fields=["lokasyon", "gece_sayisi"],
			limit_page_length=0,
		):
			nights[row["lokasyon"]] += cint(row.get("gece_sayisi"))
		expected = (cint(config.get("mekke_days")), cint(config.get("medine_days")))
		actual = (nights["Mekke"], nights["Medine"])
		if expected != actual:
			mismatches.append(
				{"configuration": config["name"], "tour": config["tour"], "old_days": expected, "hotel_nights": actual}
			)
	if mismatches:
		frappe.throw(
			"Tour Cost Configuration cannot be deprecated until its days match the "
			f"authoritative hotel nights; no data was changed: {mismatches[:20]}"
		)
