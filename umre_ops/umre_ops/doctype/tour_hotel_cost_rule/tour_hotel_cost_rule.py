# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from umre_ops.umre_ops.services.season_service import apply_active_season
from umre_ops.umre_ops.services.tour_cost_rule_service import apply_tour_hotel_rule_derived_fields


class TourHotelCostRule(Document):
	def validate(self) -> None:
		apply_active_season(self)
		if not getattr(self, "flags", None) or not self.flags.get("ignore_hotel_recalc"):
			apply_tour_hotel_rule_derived_fields(self)
