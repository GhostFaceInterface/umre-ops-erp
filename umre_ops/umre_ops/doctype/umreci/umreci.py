# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

import re

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.naming import make_autoname

from umre_ops.umre_ops.services.permission_service import require_doctype_permission


class Umreci(Document):
	"""
	Replaces ad-hoc Server Script naming. Primary key: "Ad Soyad - TC" (with collision suffix).
	"""

	def autoname(self) -> None:
		lab = f"{(self.ad or '').strip()} {(self.soyad or '').strip()}".strip()
		tck = re.sub(r"\s+", "", str((self.tc_kimlik or "")).strip())
		if not tck and not lab:
			frappe.throw(_("Ad, Soyad and TC Kimlik are required to generate the ID."))
		base = f"{lab} - {tck}" if tck else lab
		if not base.strip(" -"):
			frappe.throw(_("Could not build Umreci name from the given fields."))
		if not frappe.db.exists("Umreci", base):
			self.name = base
		else:
			self.name = make_autoname(f"{base}-.##")

	def validate(self) -> None:
		self.tc_kimlik = re.sub(r"\s+", "", str(self.tc_kimlik or "").strip()).upper()
		if not self.tc_kimlik:
			frappe.throw(_("TC / Yabancı Kimlik zorunludur."))
		duplicate = frappe.db.sql(
			"""
			select name
			from `tabUmreci`
			where replace(replace(replace(tc_kimlik, ' ', ''), char(9), ''), char(10), '') = %s
				and name != %s
			limit 1
			""",
			(self.tc_kimlik, self.name or ""),
		)
		if duplicate:
			frappe.throw(_("Bu TC / Yabancı Kimlik ile başka bir Umreci kaydı zaten var."))


@frappe.whitelist()
def get_tour_history(umreci: str) -> list[dict]:
	"""Return current participation history; deleted tour memberships intentionally disappear."""
	umreci = (umreci or "").strip()
	if not umreci:
		frappe.throw(_("Umreci zorunludur."))
	frappe.get_doc("Umreci", umreci).check_permission("read")
	require_doctype_permission("Umre Booking", "read")
	return frappe.db.sql(
		"""
		SELECT
			b.name AS booking, b.tur, t.tur_adi, t.baslangic_tarihi, t.bitis_tarihi,
			b.statu, b.oda_tipi, b.ucret, b.odenen, t.para_birimi,
			(b.ucret - b.odenen) AS bakiye
		FROM `tabUmre Booking` b
		JOIN `tabUmre Tour` t ON t.name = b.tur
		WHERE b.umreci = %s
		ORDER BY t.baslangic_tarihi DESC, b.creation DESC
		""",
		(umreci,),
		as_dict=True,
	)
