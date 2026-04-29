# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
"""Shared active-season helpers for umre_ops financial records."""
from __future__ import annotations

import frappe
from frappe import _


def get_active_season(required: bool = False) -> str | None:
	"""Return ``Umre Ops Settings.active_season``.

	When ``required`` is true, raise a business-facing validation error instead
	of allowing financial records to be saved without a global season context.
	"""
	season = (frappe.db.get_single_value("Umre Ops Settings", "active_season") or "").strip()
	if required and not season:
		frappe.throw(
			_(
				"Umre Ops Ayarları içinde Aktif Sezon seçilmeden finansal kayıt kaydedilemez."
			)
		)
	return season or None


def apply_active_season(doc, fieldname: str = "season") -> str | None:
	"""Require a global active season and default ``doc[fieldname]`` when empty."""
	season = get_active_season(required=True)
	if not doc.get(fieldname):
		doc.set(fieldname, season)
	return doc.get(fieldname)
