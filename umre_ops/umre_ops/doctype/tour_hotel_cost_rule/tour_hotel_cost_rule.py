# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import cint, date_diff

from umre_ops.umre_ops.services.fx_service import fill_rate
from umre_ops.umre_ops.services.season_service import apply_tour_season
from umre_ops.umre_ops.services.tour_cost_rule_service import apply_tour_hotel_rule_derived_fields


class TourHotelCostRule(Document):
	def validate(self) -> None:
		apply_tour_season(self, tour_fieldname="tur")
		fill_rate(
			self,
			currency="SAR",
			rate_field="kur",
			on_date=frappe.db.get_value("Umre Tour", self.tur, "baslangic_tarihi"),
		)
		if not getattr(self, "flags", None) or not self.flags.get("ignore_hotel_recalc"):
			apply_tour_hotel_rule_derived_fields(self)
		self._warn_if_nights_exceed_tour()

	def _warn_if_nights_exceed_tour(self) -> None:
		"""Hotel nights also drive meal days, so they should fit the tour duration."""
		start, end = frappe.db.get_value("Umre Tour", self.tur, ["baslangic_tarihi", "bitis_tarihi"]) or (None, None)
		if not (start and end):
			return
		duration = date_diff(end, start)
		other_nights = sum(
			cint(n)
			for n in frappe.get_all(
				"Tour Hotel Cost Rule",
				filters={"tur": self.tur, "name": ["!=", self.name or ""]},
				pluck="gece_sayisi",
			)
		)
		total = other_nights + cint(self.gece_sayisi)
		if total > duration:
			frappe.msgprint(
				_("Turun otel geceleri toplamı ({0}) tur süresini ({1} gece) aşıyor.").format(total, duration),
				indicator="orange",
				alert=True,
			)

	def on_update(self) -> None:
		from umre_ops.umre_ops.services.cost_engine import schedule_recompute_for_rule

		schedule_recompute_for_rule(self)

	def on_trash(self) -> None:
		_schedule(self.tur)


def _schedule(tour: str | None) -> None:
	from umre_ops.umre_ops.services.cost_engine import schedule_recompute_for_tour

	schedule_recompute_for_tour(tour)
