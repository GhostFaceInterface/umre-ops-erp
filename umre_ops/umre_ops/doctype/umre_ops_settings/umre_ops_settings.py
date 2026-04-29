# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class UmreOpsSettings(Document):
	def validate(self):
		if not self.active_season:
			frappe.throw(_("Aktif Sezon zorunludur."))
