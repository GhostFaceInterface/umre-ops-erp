# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from umre_ops.umre_ops.services.fx_service import SOURCE_MANUAL, fill_rate
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
		self._validate_related_tour()
		self._enforce_amount_rules()
		self._calc_usd()
		self._validate_receipt_attachment()

	def _sync_money_currency(self) -> None:
		"""Take currency from the money account when the account is chosen or changed.

		An existing expense keeps the currency it was entered in, even if the
		account's currency is edited later.
		"""
		if not self.money_account:
			return
		if not self.is_new() and not self.has_value_changed("money_account") and self.currency:
			return
		cur, institution = frappe.db.get_value(
			"Umre Money Account", self.money_account, ["currency", "institution"]
		) or (None, None)
		if cur and cur != self.currency:
			previous_currency = self.currency
			self.currency = cur
			if previous_currency and (self.is_new() or not self.has_value_changed("usd_exchange_rate")):
				# A rate typed for the previous currency is meaningless now.
				self.usd_exchange_rate = 0
		if institution:
			self.financial_institution = institution

	def _validate_related_tour(self) -> None:
		"""`related_tour` set = in-umrah tour expense; empty = office overhead."""
		if not self.get("related_tour"):
			return
		tour_season = frappe.db.get_value("Umre Tour", self.related_tour, "season")
		if tour_season and self.season and tour_season != self.season:
			frappe.throw(
				_("Tura ait gider, turun sezonuna ({0}) kaydedilmelidir.").format(tour_season)
			)

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
			self.kur_kaynagi = "USD"
			self.usd_amount = flt(amt, 2)
			return

		# Empty rate -> ERPNext rate of the expense date; a typed rate is checked
		# against it (inverted rates such as 0.024 TRY are rejected). An untouched
		# saved expense is not re-validated, so it can still be cancelled.
		unchanged = not self.is_new() and not any(
			self.has_value_changed(f) for f in ("amount", "currency", "usd_exchange_rate", "expense_date")
		)
		if (
			not self.is_new()
			and self.has_value_changed("expense_date")
			and not self.has_value_changed("usd_exchange_rate")
			and self.get("kur_kaynagi") != SOURCE_MANUAL
		):
			# An automatic rate follows the expense date.
			self.usd_exchange_rate = 0
		if not (unchanged and flt(self.usd_exchange_rate) > 0):
			fill_rate(self, currency=cur, rate_field="usd_exchange_rate", on_date=self.expense_date)
		self.usd_amount = flt(amt / flt(self.usd_exchange_rate), 2)

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
