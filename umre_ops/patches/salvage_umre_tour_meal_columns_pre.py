# Copyright (c) 2026, Sermed Turizm and contributors
"""Before schema sync: snapshot legacy meal columns from ``tabUmre Tour`` to a *file*.

No DROP/CREATE/ALTER — avoids ImplicitCommitError inside the migration transaction.

Idempotent: overwrites the same JSON file while physical columns still exist.
After columns are removed by DocType sync, this patch no-ops (``has_column`` false).
"""
from __future__ import annotations

import json
import os

import frappe


SALVAGE_FILENAME = "umre_meal_salvage.json"


def _salvage_path() -> str:
	return os.path.join(frappe.get_site_path("private"), SALVAGE_FILENAME)


def execute() -> None:
	if not frappe.db.has_column("Umre Tour", "mekke_days"):
		return

	# Read-only snapshot; no DDL.
	rows = frappe.db.sql(
		"""
		SELECT
			`name` AS tour,
			IFNULL(`mekke_days`, 0) AS mekke_days,
			IFNULL(`medine_days`, 0) AS medine_days,
			IFNULL(`mekke_meal_price_sar`, 0) AS mekke_meal_price_sar,
			IFNULL(`medine_meal_price_sar`, 0) AS medine_meal_price_sar,
			IFNULL(`sar_to_usd_rate`, 0) AS sar_to_usd_rate,
			IFNULL(`other_cost_per_person`, 0) AS other_cost_per_person
		FROM `tabUmre Tour`
		""",
		as_dict=True,
	)
	path = _salvage_path()
	directory = os.path.dirname(path)
	if not os.path.exists(directory):
		os.makedirs(directory, exist_ok=True)
	payload = {
		"version": 1,
		"source": "tabUmre Tour legacy columns (pre domain-rule doctypes)",
		"rows": rows,
	}
	with open(path, "w", encoding="utf-8") as fh:
		json.dump(payload, fh, ensure_ascii=False, default=str, indent=2)
