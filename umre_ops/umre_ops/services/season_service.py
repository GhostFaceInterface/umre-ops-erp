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


def apply_tour_season(doc, tour_fieldname: str = "tour", season_fieldname: str = "season") -> str:
	"""Copy the linked tour's season to a rule document.

	The global active season is a Desk selection aid, not financial authority.
	Cost rules always inherit their immutable accounting context from ``Umre Tour``.
	"""
	tour = (doc.get(tour_fieldname) or "").strip()
	if not tour:
		frappe.throw(_("Tur seçilmeden maliyet kuralı kaydedilemez."))
	season = frappe.db.get_value("Umre Tour", tour, "season")
	if not season:
		frappe.throw(_("Seçilen turun sezonu bulunamadı: {0}").format(tour))
	doc.set(season_fieldname, season)
	return season
