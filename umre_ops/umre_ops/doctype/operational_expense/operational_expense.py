# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from umre_ops.umre_ops.services.season_service import apply_active_season


class OperationalExpense(Document):
	def on_update(self):
		self._link_receipt_attachment()
		frappe.publish_realtime(event="umre_operational_expense_dirty", message={"name": self.name}, after_commit=True)

	def validate(self):
		apply_active_season(self)
		self._sync_money_currency()
		self._sync_legacy_category()
		self._validate_expense_category()
		self._enforce_amount_rules()
		self._calc_usd()
		self._validate_receipt_attachment()

	def _sync_money_currency(self) -> None:
		if self.money_account:
			cur, institution = frappe.db.get_value(
				"Umre Money Account", self.money_account, ["currency", "institution"]
			) or (None, None)
			if cur:
				self.currency = cur
			if institution:
				self.financial_institution = institution

	def _sync_legacy_category(self) -> None:
		if self.get("category") and not self.get("expense_category"):
			self.expense_category = self.category

	def _validate_expense_category(self) -> None:
		category = self.get("expense_category")
		if not category:
			frappe.throw(_("Gider kalemi zorunludur."))

		row = frappe.db.get_value(
			"Operational Expense Category",
			category,
			["category_name", "is_group", "is_active"],
			as_dict=True,
		)
		if not row:
			frappe.throw(_("Seçilen gider kalemi bulunamadı: {0}").format(category))
		if row.is_group:
			frappe.throw(_("Gider girişi yalnızca alt gider kalemlerine yapılabilir: {0}").format(row.category_name))
		if not row.is_active:
			frappe.throw(_("Pasif gider kalemine kayıt girilemez: {0}").format(row.category_name))

	def _enforce_amount_rules(self) -> None:
		amt = flt(self.amount)
		if amt < 0:
			frappe.throw(_("Amount cannot be negative."))
		if self.status == "Confirmed" and amt <= 0:
			frappe.throw(_("Confirmed operational expenses must have amount greater than zero."))

	def _calc_usd(self) -> None:
		cur = (self.currency or "").strip().upper()
		amt = flt(self.amount)
		if not cur:
			return
		if cur == "USD":
			self.usd_exchange_rate = 1.0
			self.usd_amount = flt(amt, 2)
			return

		rate = flt(self.usd_exchange_rate)
		if rate <= 0:
			frappe.throw(
				_(
					"USD kur alanı zorunludur ({0}). Kullanıcılar tutar ile USD arasındaki "
					"çarpanı işler: USD = Tutar ÷ Kur (örneğin 1 USD karşılığı kaç TRY)."
				).format(cur)
			)

		self.usd_amount = flt(amt / rate, 2)

	def _validate_receipt_attachment(self) -> None:
		if not self.receipt_attachment:
			return
		allowed = {".pdf", ".jpg", ".jpeg", ".png", ".webp"}
		path = self.receipt_attachment.split("?", 1)[0].lower()
		if not any(path.endswith(ext) for ext in allowed):
			frappe.throw(_("Dekont eki yalnızca PDF veya resim olabilir: pdf, jpg, jpeg, png, webp."))

	def _link_receipt_attachment(self) -> None:
		if not self.receipt_attachment:
			return

		file_row = frappe.db.get_value(
			"File",
			{"file_url": self.receipt_attachment},
			["name", "attached_to_doctype", "attached_to_name"],
			as_dict=True,
		)
		if not file_row:
			return

		if file_row.attached_to_doctype and file_row.attached_to_name != self.name:
			return

		frappe.db.set_value(
			"File",
			file_row.name,
			{
				"attached_to_doctype": self.doctype,
				"attached_to_name": self.name,
				"attached_to_field": "receipt_attachment",
			},
			update_modified=False,
		)
