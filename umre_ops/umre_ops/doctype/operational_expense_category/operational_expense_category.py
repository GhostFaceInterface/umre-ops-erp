# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document


class OperationalExpenseCategory(Document):
	def validate(self):
		if self.parent_category and self.parent_category == self.name:
			frappe.throw(_("Kategori kendi üst kategorisi olamaz."))
		if not self.is_group:
			return

		if self.name and frappe.db.exists(
			"Operational Expense",
			{"expense_category": self.name},
		):
			frappe.throw(_("Gider kaydı bulunan kategori grup olarak işaretlenemez."))
