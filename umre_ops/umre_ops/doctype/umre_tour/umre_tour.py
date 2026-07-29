# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document

from umre_ops.umre_ops.services.season_service import apply_active_season


class UmreTour(Document):
	def before_validate(self) -> None:
		apply_active_season(self)

	def validate(self) -> None:
		if not self.is_new() and self.has_value_changed("season"):
			frappe.throw(_("Kaydedilmiş bir turun sezonu değiştirilemez."))

	def on_update(self) -> None:
		# `Umre Tour` artık yemek alanları taşımıyor; fiyat/para birimi yine bileşenleri etkiler.  # noqa: RUF003
		try:
			from umre_ops.umre_ops.services.cost_engine import schedule_recompute_for_tour

			schedule_recompute_for_tour(self.name)
		except Exception:
			frappe.log_error(title="Umre Tour: schedule recompute failed")
