# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt

from umre_ops.umre_ops.services.season_service import apply_tour_season


class MealCostRule(Document):
	def validate(self) -> None:
		apply_tour_season(self)
		rate = flt(self.sar_to_usd_rate)
		if rate < 0:
			frappe.throw(_("SAR/USD kuru negatif olamaz."))
		if 0 < rate < 1:
			frappe.throw(_("SAR/USD kuru 1 USD karşılığı SAR olarak girilmelidir (ör. 3.75)."))
		if (flt(self.mekke_price_sar) > 0 or flt(self.medine_price_sar) > 0) and rate <= 0:
			frappe.throw(_("Yemek maliyeti için SAR/USD kuru pozitif olmalıdır."))

	def on_update(self) -> None:
		_schedule(self.tour)

	def on_trash(self) -> None:
		_schedule(self.tour)


def _schedule(tour: str | None) -> None:
	from umre_ops.umre_ops.services.cost_engine import schedule_recompute_for_tour

	schedule_recompute_for_tour(tour)
