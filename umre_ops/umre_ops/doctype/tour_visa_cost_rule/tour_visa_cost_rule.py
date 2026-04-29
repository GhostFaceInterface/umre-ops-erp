# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from frappe.model.document import Document

from umre_ops.umre_ops.services.season_service import apply_active_season


class TourVisaCostRule(Document):
	def validate(self) -> None:
		apply_active_season(self)
