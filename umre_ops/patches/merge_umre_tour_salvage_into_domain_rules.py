# Copyright (c) 2026, Sermed Turizm and contributors
"""
After new cost-rule DocTypes are synced: import meal snapshot from:

1) ``sites/<site>/private/umre_meal_salvage.json`` (written by
   ``salvage_umre_tour_meal_columns_pre``), or
2) legacy ``__umre_tour_meal_salvage`` table (READ-ONLY) from a *failed* older
   migrate that used DDL (no DROP here — DBA can drop the table outside migrate).

No DROP/CREATE/ALTER; no :func:`frappe.db.commit` (framework owns the transaction).
Idempotent: skips rows when rule docs already exist.
"""
from __future__ import annotations

import json
import os
from typing import Any

import frappe
from frappe.utils import cint, flt

from umre_ops.patches.salvage_umre_tour_meal_columns_pre import _salvage_path
from umre_ops.patches.patch_guard import forbid_ddl


def _read_rows() -> list[dict[str, Any]]:
	path = _salvage_path()
	if os.path.isfile(path):
		with open(path, encoding="utf-8") as fh:
			data = json.load(fh)
		rows = data.get("rows") or []
		if rows:
			return list(rows)
	# Legacy: failed migration may have left a temp table. SELECT only.
	if "__umre_tour_meal_salvage" in frappe.db.get_tables():
		sql = "SELECT * FROM `__umre_tour_meal_salvage`"
		forbid_ddl(sql)
		return frappe.db.sql(sql, as_dict=True) or []
	return []


def execute() -> None:
	if not frappe.db.exists("DocType", "Tour Cost Configuration"):
		return

	rows = _read_rows()
	if not rows:
		return

	for r in rows:
		tour = r.get("tour")
		if not tour or not frappe.db.exists("Umre Tour", tour):
			continue

		if not frappe.db.exists("Tour Cost Configuration", {"tour": tour}):
			frappe.get_doc(
				{
					"doctype": "Tour Cost Configuration",
					"tour": tour,
					"mekke_days": cint(r.get("mekke_days") or 0),
					"medine_days": cint(r.get("medine_days") or 0),
				}
			).insert(ignore_permissions=True)

		if not frappe.db.exists("Meal Cost Rule", {"tour": tour}):
			frappe.get_doc(
				{
					"doctype": "Meal Cost Rule",
					"tour": tour,
					"mekke_price_sar": flt(r.get("mekke_meal_price_sar") or 0),
					"medine_price_sar": flt(r.get("medine_meal_price_sar") or 0),
					"sar_to_usd_rate": flt(r.get("sar_to_usd_rate") or 0) or 3.75,
				}
			).insert(ignore_permissions=True)

		if not frappe.db.exists("Other Cost Rule", {"tour": tour}):
			pb = frappe.db.get_value("Umre Tour", tour, "para_birimi") or "USD"
			frappe.get_doc(
				{
					"doctype": "Other Cost Rule",
					"tour": tour,
					"currency": pb,
					"per_person_cost": flt(r.get("other_cost_per_person") or 0),
				}
			).insert(ignore_permissions=True)

	# Remove snapshot file so re-migrate does not re-insert duplicates; rules are idempotent
	# via exists checks, but this keeps logs clean.
	path = _salvage_path()
	if os.path.isfile(path):
		try:
			os.remove(path)
		except OSError as exc:
			frappe.log_error(
				message=str(exc), title="merge_umre_tour_salvage: could not remove JSON"
			)

	# Recompute in-process (no enqueue inside migrate — worker may be unavailable)
	try:
		from umre_ops.umre_ops.services.cost_engine import recompute_tour_bookings

		for r in rows:
			t = r.get("tour")
			if t and frappe.db.exists("Umre Tour", t):
				recompute_tour_bookings(t)
	except Exception:
		frappe.log_error("merge_umre_tour_salvage: batch recompute failed")
