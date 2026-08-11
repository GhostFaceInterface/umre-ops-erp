# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
from __future__ import annotations

from frappe.model.document import Document

from umre_ops.umre_ops.services.season_service import apply_tour_season


class TourCostConfiguration(Document):
	def validate(self) -> None:
		apply_tour_season(self)
