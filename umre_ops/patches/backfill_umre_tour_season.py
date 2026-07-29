# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
"""Assign the known legacy tour to its historical season."""

from __future__ import annotations

import frappe
from frappe import _

BLANK_SEASON_FILTER = {"season": ["is", "not set"]}
EXAMPLE_LIMIT = 5
LEGACY_TOUR = "Şevval 2026"
LEGACY_SEASON = "2025-2026 Sezonu"


def _examples(names: list[str]) -> str:
	return ", ".join(names[:EXAMPLE_LIMIT])


def _validate_blank_tours(tours: list[dict]) -> None:
	unexpected = [tour["name"] for tour in tours if tour["name"] != LEGACY_TOUR]
	if unexpected or len(tours) != 1:
		frappe.throw(
			_(
				"Umre Tour sezon aktarımı durduruldu. Beklenmedik boş sezonlu tur sayısı: {0} "  # noqa: RUF001
				"({1}). Hiçbir kayıt güncellenmedi."  # noqa: RUF001
			).format(len(unexpected), _examples(unexpected))
		)


def _get_or_create_legacy_season() -> str:
	season = frappe.db.exists("Umre Season", {"season_name": LEGACY_SEASON})
	if season:
		return season
	return (
		frappe.get_doc(
			{
				"doctype": "Umre Season",
				"season_name": LEGACY_SEASON,
				"is_active": 0,
			}
		)
		.insert(ignore_permissions=True)
		.name
	)


def execute() -> None:
	tours = frappe.get_all(
		"Umre Tour",
		filters=BLANK_SEASON_FILTER,
		fields=["name"],
		limit_page_length=0,
	)
	if not tours:
		return

	_validate_blank_tours(tours)
	season = _get_or_create_legacy_season()
	frappe.db.set_value(
		"Umre Tour",
		{"name": LEGACY_TOUR, "season": ["is", "not set"]},
		"season",
		season,
		update_modified=False,
	)
