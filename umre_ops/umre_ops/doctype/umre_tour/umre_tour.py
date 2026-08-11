# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from umre_ops.umre_ops.services.permission_service import require_doctype_permission
from umre_ops.umre_ops.services.season_service import apply_active_season


class UmreTour(Document):
	def before_validate(self) -> None:
		apply_active_season(self)

	def validate(self) -> None:
		if self.para_birimi != "USD":
			frappe.throw(_("Umre turları ve rezervasyon finansalları USD olmalıdır."))
		if not self.is_new() and self.has_value_changed("season"):
			frappe.throw(_("Kaydedilmiş bir turun sezonu değiştirilemez."))



def _get_tour(tour: str, permission_type: str = "read"):
	tour = (tour or "").strip()
	if not tour:
		frappe.throw(_("Tur zorunludur."))
	doc = frappe.get_doc("Umre Tour", tour)
	doc.check_permission(permission_type)
	return doc


def _mask_identity(value: str | None) -> str:
	value = str(value or "").strip()
	if len(value) <= 4:
		return "*" * len(value)
	return f"{value[:2]}{'*' * (len(value) - 4)}{value[-2:]}"


def _participant_rows(tour: str) -> list[dict]:
	rows = frappe.db.sql(
		"""
		SELECT
			b.name AS booking, b.umreci, b.statu, b.oda_tipi,
			b.ic_hat_baglanti, b.arrival_city, b.return_city, b.kimden_geldi,
			b.ucret, b.odenen,
			u.ad, u.soyad, u.telefon_numarasi, u.tc_kimlik
		FROM `tabUmre Booking` b
		JOIN `tabUmreci` u ON u.name = b.umreci
		WHERE b.tur = %s
		ORDER BY u.soyad, u.ad, b.creation
		""",
		(tour,),
		as_dict=True,
	)
	for row in rows:
		row["masked_identity"] = _mask_identity(row.pop("tc_kimlik", None))
		row["ucret"] = flt(row.get("ucret"))
		row["odenen"] = flt(row.get("odenen"))
		row["bakiye"] = flt(row["ucret"] - row["odenen"])
	return rows


@frappe.whitelist()
def get_tour_participants(tour: str) -> dict:
	"""Return the operational/financial tour roster without exposing full identity numbers."""
	doc = _get_tour(tour)
	require_doctype_permission("Umre Booking", "read")
	rows = _participant_rows(doc.name)
	return {
		"tour": doc.name,
		"currency": doc.para_birimi,
		"count": len(rows),
		"total_ucret": flt(sum(row["ucret"] for row in rows)),
		"total_odenen": flt(sum(row["odenen"] for row in rows)),
		"participants": rows,
	}
