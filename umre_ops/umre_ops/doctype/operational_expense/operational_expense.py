# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class OperationalExpense(Document):
	def on_update(self):
		frappe.publish_realtime(event="umre_operational_expense_dirty", message={"name": self.name}, after_commit=True)

	def validate(self):
		self._sync_money_currency()
		self._enforce_amount_rules()
		self._calc_usd()

	def _sync_money_currency(self) -> None:
		if self.money_account:
			cur = frappe.db.get_value("Umre Money Account", self.money_account, "currency")
			if cur:
				self.currency = cur

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
			self.usd_amount = amt
			return

		rate = flt(self.usd_exchange_rate)
		if rate <= 0:
			frappe.throw(
				_(
					"USD kur alanı zorunludur ({0}). Kullanıcılar tutar ile USD arasındaki "
					"çarpanı işler: USD = Tutar ÷ Kur (örneğin 1 USD karşılığı kaç TRY)."
				).format(cur)
			)

		self.usd_amount = flt(amt / rate)

