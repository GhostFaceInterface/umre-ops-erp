"""Make the linked tour the authoritative season for every cost rule."""

from __future__ import annotations

import frappe

RULES = (
	("Tour Hotel Cost Rule", "tur"),
	("Tour Airfare Cost Rule", "tur"),
	("Tour Visa Cost Rule", "tur"),
	("Tour Diyanet Card Rule", "tur"),
	("Meal Cost Rule", "tour"),
	("Other Cost Rule", "tour"),
	("Tour Cost Configuration", "tour"),
)


def execute() -> None:
	updates: list[tuple[str, str, str]] = []
	errors: list[str] = []
	for doctype, tour_field in RULES:
		if not frappe.db.exists("DocType", doctype):
			continue
		for row in frappe.get_all(
			doctype,
			fields=["name", tour_field, "season"],
			limit_page_length=0,
		):
			tour = row.get(tour_field)
			tour_season = frappe.db.get_value("Umre Tour", tour, "season") if tour else None
			if not tour_season:
				errors.append(f"{doctype} {row['name']}: linked tour/season is missing")
			elif row.get("season") != tour_season:
				updates.append((doctype, row["name"], tour_season))
	if errors:
		frappe.throw(
			"Cost-rule season backfill stopped before changing data: " + "; ".join(errors[:20])
		)
	for doctype, name, season in updates:
		frappe.db.set_value(doctype, name, "season", season, update_modified=False)
