# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document


class UmreTour(Document):
	def on_update(self) -> None:
		# `Umre Tour` artık yemek alanları taşımıyor; fiyat/para birimi yine bileşenleri etkiler.
		try:
			from umre_ops.umre_ops.services.cost_engine import schedule_recompute_for_tour

			schedule_recompute_for_tour(self.name)
		except Exception:
			frappe.log_error(title="Umre Tour: schedule recompute failed")
