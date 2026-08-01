"""Canonicalize passenger identity keys before the schema adds uniqueness."""

import frappe
from frappe import _

CANONICAL_SQL = (
	"upper(replace(replace(replace(tc_kimlik, ' ', ''), char(9), ''), char(10), ''))"
)


def execute() -> None:
	if not frappe.db.table_exists("Umreci") or not frappe.db.has_column("Umreci", "tc_kimlik"):
		return
	duplicates = frappe.db.sql(
		f"""
		select {CANONICAL_SQL} as identity_key, count(*) as row_count
		from `tabUmreci`
		where coalesce(tc_kimlik, '') != ''
		group by {CANONICAL_SQL}
		having count(*) > 1
		limit 10
		""",
		as_dict=True,
	)
	if duplicates:
		frappe.throw(
			_(
				"TC / Yabancı Kimlik tekilleştirmesi durduruldu: normalize edildiğinde çakışan "
				"{0} kimlik anahtarı var. Kayıtları manuel olarak birleştirip migrate işlemini yenileyin."
			).format(len(duplicates))
		)
	frappe.db.sql(
		f"""
		update `tabUmreci`
		set tc_kimlik = {CANONICAL_SQL}
		where coalesce(tc_kimlik, '') != '' and tc_kimlik != {CANONICAL_SQL}
		"""
	)
