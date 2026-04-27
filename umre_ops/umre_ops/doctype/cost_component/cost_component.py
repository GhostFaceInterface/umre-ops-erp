# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
"""
`Cost Component` document — one row per cost item attached to an Umre Booking.

Invariants enforced here (cheap and safe; the cost engine has the wider
financial integrity checks):

* `amount = round(quantity * unit_price, 2)` whenever both are set.
* `amount >= 0` (no negative cost without explicit operator override).
* `currency` is always present (defaulted from Cost Type if missing).
* System-generated rows cannot be hand-edited via desk UI to a different
  amount unless `flags.ignore_system_generated_lock` is set.
"""
from __future__ import annotations

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt


class CostComponent(Document):
	def autoname(self):
		# naming_series handles it; just normalize.
		return None

	def validate(self):
		self._set_currency_default()
		self._recompute_amount()
		self._enforce_non_negative()
		self._enforce_system_generated_lock()

	def _set_currency_default(self) -> None:
		if self.currency:
			return
		if self.cost_type:
			default_curr = frappe.db.get_value("Cost Type", self.cost_type, "default_currency")
			if default_curr:
				self.currency = default_curr
				return
		self.currency = "USD"

	def _recompute_amount(self) -> None:
		# Only recompute when both qty + unit_price are provided. Otherwise
		# trust the caller (some patches push `amount` directly without
		# decomposing). Round to 2 dp for stable comparisons.
		qty = flt(self.quantity or 0)
		up = flt(self.unit_price or 0)
		if qty and up:
			self.amount = flt(round(qty * up, 2))
		elif self.amount in (None, ""):
			self.amount = 0.0

	def _enforce_non_negative(self) -> None:
		if flt(self.amount) < 0:
			frappe.throw(
				_("Cost Component {0} cannot have a negative amount ({1}). "
				  "Negative cost requires explicit operator override.").format(
					self.cost_type or "?", self.amount
				)
			)

	def _enforce_system_generated_lock(self) -> None:
		"""System-generated rows are immutable for amount/qty/unit_price unless flag set."""
		if not self.is_system_generated or self.is_new():
			return
		flags = getattr(self, "flags", None)
		if flags is not None and flags.get("ignore_system_generated_lock"):
			return
		old = frappe.db.get_value(
			"Cost Component",
			self.name,
			["amount", "quantity", "unit_price", "cost_type", "currency"],
			as_dict=True,
		)
		if not old:
			return
		for field in ("amount", "quantity", "unit_price"):
			new_val = flt(self.get(field) or 0)
			old_val = flt(old.get(field) or 0)
			if abs(new_val - old_val) > 0.01:
				frappe.throw(
					_("Cost Component {0} ({1}) is system-generated; field {2} cannot be edited "
					  "(was {3}, attempted {4}). Use the cost-engine recompute action instead.").format(
						self.name, self.cost_type, field, old_val, new_val
					)
				)
		for field in ("cost_type", "currency"):
			if (self.get(field) or "") != (old.get(field) or ""):
				frappe.throw(
					_("Cost Component {0} is system-generated; field {1} cannot be edited.").format(
						self.name, field
					)
				)

	def on_update(self):
		self._notify_dashboard()

	def on_trash(self):
		self._notify_dashboard()

	def _notify_dashboard(self) -> None:
		# Realtime nudge so any open Umre Operasyon Paneli refetches.
		try:
			from umre_ops.umre_ops.services.dashboard_service import publish_dashboard_dirty
			tour = self.get("tour") or frappe.db.get_value("Umre Booking", self.booking, "tur")
			publish_dashboard_dirty(tour)
		except Exception:
			# Dashboard refresh is best-effort; never block the write.
			frappe.log_error(title="dashboard publish failed")
