# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
from __future__ import annotations

import frappe
from frappe.model.document import Document


class MealCostRule(Document):
	def on_update(self) -> None:
		_schedule(self.tour)

	def after_insert(self) -> None:
		_schedule(self.tour)

	def on_trash(self) -> None:
		_schedule(self.tour)


def _schedule(tour: str | None) -> None:
	if not tour:
		return
	from umre_ops.umre_ops.services.cost_engine import schedule_recompute_for_tour

	schedule_recompute_for_tour(tour)
