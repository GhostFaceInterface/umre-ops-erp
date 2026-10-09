# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
from __future__ import annotations

import frappe
from frappe.model.document import Document

from umre_ops.umre_ops.services.fx_service import fill_rate
from umre_ops.umre_ops.services.season_service import apply_tour_season


class MealCostRule(Document):
	def validate(self) -> None:
		apply_tour_season(self)
		# Empty rate -> ERPNext SAR peg (3.75); a typed rate must stay inside the peg band.
		fill_rate(
			self,
			currency="SAR",
			rate_field="sar_to_usd_rate",
			on_date=frappe.db.get_value("Umre Tour", self.tour, "baslangic_tarihi"),
		)

	def on_update(self) -> None:
		from umre_ops.umre_ops.services.cost_engine import schedule_recompute_for_rule

		schedule_recompute_for_rule(self)

	def on_trash(self) -> None:
		_schedule(self.tour)


def _schedule(tour: str | None) -> None:
	from umre_ops.umre_ops.services.cost_engine import schedule_recompute_for_tour

	schedule_recompute_for_tour(tour)
