"""Data-preserving technical rename for the airfare rule DocType."""

import frappe

OLD = "Tour Passenger Cost Rule"
NEW = "Tour Airfare Cost Rule"
PREFLIGHT_KEYS = (
	("Tour Diyanet Card Rule", ("tur",)),
	("Tour Visa Cost Rule", ("tur", "vize_tipi")),
	(OLD, ("tur", "yolcu_tipi")),
	("Tour Hotel Cost Rule", ("tur", "lokasyon")),
)


def _assert_no_duplicates() -> None:
	for doctype, fields in PREFLIGHT_KEYS:
		if not frappe.db.exists("DocType", doctype):
			continue
		columns = ", ".join(f"`{field}`" for field in fields)
		duplicates = frappe.db.sql(
			f"SELECT {columns}, COUNT(*) AS row_count FROM `tab{doctype}` "
			f"GROUP BY {columns} HAVING COUNT(*) > 1 LIMIT 20",
			as_dict=True,
		)
		if duplicates:
			frappe.throw(
				f"{doctype} contains duplicate business keys; no migration data was changed: "
				f"{duplicates}"
			)


def _assert_airfare_only() -> None:
	if not frappe.db.has_column(OLD, "expense_component"):
		if frappe.db.count(OLD):
			frappe.throw(
				f"{OLD} has rows but no expense_component discriminator; no migration data was changed."
			)
		return
	invalid = frappe.db.sql(
		f"SELECT name, tur, expense_component FROM `tab{OLD}` "
		"WHERE COALESCE(expense_component, '') != %s LIMIT 20",
		("Uçak",),
		as_dict=True,
	)
	if invalid:
		frappe.throw(
			f"{OLD} contains non-airfare rows; no migration data was changed: {invalid}"
		)


def execute() -> None:
	old_exists = bool(frappe.db.exists("DocType", OLD))
	new_exists = bool(frappe.db.exists("DocType", NEW))
	if not old_exists:
		return
	_assert_airfare_only()
	_assert_no_duplicates()
	if new_exists:
		frappe.throw(
			f"Both {OLD} and {NEW} exist; refusing an ambiguous automatic merge."
		)
	frappe.rename_doc("DocType", OLD, NEW, force=True)
