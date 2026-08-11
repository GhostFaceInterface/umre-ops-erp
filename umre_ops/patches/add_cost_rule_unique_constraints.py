"""Fail-safe uniqueness migration for one authoritative rule per business key."""

import frappe

UNIQUE_RULES = (
	("Tour Diyanet Card Rule", ("tur",), "uniq_diyanet_tour"),
	("Tour Visa Cost Rule", ("tur", "vize_tipi"), "uniq_visa_tour_type"),
	("Tour Airfare Cost Rule", ("tur", "yolcu_tipi"), "uniq_airfare_tour_type"),
	("Tour Hotel Cost Rule", ("tur", "lokasyon"), "uniq_hotel_tour_location"),
)


def _duplicates(doctype: str, fields: tuple[str, ...]) -> list[dict]:
	columns = ", ".join(f"`{field}`" for field in fields)
	return frappe.db.sql(
		f"SELECT {columns}, COUNT(*) AS row_count FROM `tab{doctype}` "
		f"GROUP BY {columns} HAVING COUNT(*) > 1 LIMIT 20",
		as_dict=True,
	)


def execute() -> None:
	for doctype, fields, _constraint in UNIQUE_RULES:
		if not frappe.db.exists("DocType", doctype):
			continue
		duplicates = _duplicates(doctype, fields)
		if duplicates:
			frappe.throw(
				f"{doctype} contains duplicate business keys; no data was changed. "
				f"Resolve these rows before retrying migrate: {duplicates}"
			)
	for doctype, fields, constraint in UNIQUE_RULES:
		if frappe.db.exists("DocType", doctype):
			frappe.db.add_unique(doctype, list(fields), constraint_name=constraint)
