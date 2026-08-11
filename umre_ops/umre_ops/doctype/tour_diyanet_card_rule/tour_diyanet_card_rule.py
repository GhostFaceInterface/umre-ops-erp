# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from umre_ops.umre_ops.services.season_service import apply_tour_season


class TourDiyanetCardRule(Document):
	def validate(self) -> None:
		apply_tour_season(self, tour_fieldname="tur")
		self.para_birimi = "USD"

	def on_update(self) -> None:
		_schedule(self.tur)

	def on_trash(self) -> None:
		_schedule(self.tur)


def _schedule(tour: str | None) -> None:
	from umre_ops.umre_ops.services.cost_engine import schedule_recompute_for_tour

	schedule_recompute_for_tour(tour)
