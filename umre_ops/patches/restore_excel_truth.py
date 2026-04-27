# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
"""
Idempotent repair: restore (statu, ucret, manual_cost) from canonical Excel
truth and lock the bookings against future drift.

Scope:
- Reads `patches/data/excel_truth_*.json` files (one per tour pattern).
- For each booking that joins by TC to a truth row, applies
  (statu, ucret, manual_cost) directly via `frappe.db.set_value`
  (bypasses validate, so the new immutability guard does not block the repair).
- Then sets `is_imported = 1` and `locked_financials = 1` so any future drift
  is impossible without explicit `flags.ignore_financial_lock`.

Re-running this patch is a no-op when ERP already matches Excel.
The patch logs every change. It NEVER recomputes from tour pricing.
"""
from __future__ import annotations

import json
from pathlib import Path

import frappe
from frappe.utils import flt

DATA_DIR = Path(__file__).resolve().parent / "data"
PAYING_STATUS = "UMRECI"


def execute() -> None:
	truth_files = sorted(DATA_DIR.glob("excel_truth_*.json"))
	if not truth_files:
		print("[restore_excel_truth] no truth files found; nothing to do")
		return

	totals = {"updated_rows": 0, "locked_rows": 0, "skipped_no_match": 0, "already_correct": 0}

	for path in truth_files:
		doc = json.loads(path.read_text(encoding="utf-8"))
		pattern = doc.get("tour_pattern") or ""
		truth_rows = doc.get("rows") or []
		print(f"[restore_excel_truth] processing {path.name}  pattern={pattern!r}  rows={len(truth_rows)}")

		# Resolve tours matching the pattern.
		tours = [
			r["name"]
			for r in frappe.db.sql(
				"SELECT name FROM `tabUmre Tour` WHERE name LIKE %s",
				(pattern,),
				as_dict=True,
			)
		]
		if not tours:
			print(f"  no tour matches {pattern!r}, skip")
			continue

		# Index truth by TC.
		truth_by_tc = {r["tc"]: r for r in truth_rows if r.get("tc")}

		for tour in tours:
			bookings = frappe.db.sql(
				"""
				SELECT b.name, b.statu, b.ucret, b.manual_cost,
				       b.is_imported, b.locked_financials, u.tc_kimlik AS tc
				FROM `tabUmre Booking` b
				LEFT JOIN `tabUmreci` u ON u.name = b.umreci
				WHERE b.tur = %s
				""",
				(tour,),
				as_dict=True,
			)
			print(f"  tour={tour!r}  bookings={len(bookings)}")

			for b in bookings:
				tc = (b["tc"] or "").strip()
				ex = truth_by_tc.get(tc)
				if not ex:
					totals["skipped_no_match"] += 1
					continue

				new_statu = ex["statu"]
				new_ucret = flt(ex["ucret"])
				new_mc = flt(ex["manual_cost"])

				# Enforce business invariants on the truth itself.
				if new_statu == PAYING_STATUS:
					new_mc = 0.0
				else:
					new_ucret = 0.0

				cur_statu = (b["statu"] or "").strip()
				cur_ucret = flt(b["ucret"] or 0)
				cur_mc = flt(b["manual_cost"] or 0)
				cur_locked = int(b["locked_financials"] or 0)
				cur_imported = int(b["is_imported"] or 0)

				diff = (
					cur_statu != new_statu
					or abs(cur_ucret - new_ucret) > 0.01
					or abs(cur_mc - new_mc) > 0.01
				)

				to_write: dict = {}
				if diff:
					to_write["statu"] = new_statu
					to_write["ucret"] = new_ucret
					to_write["manual_cost"] = new_mc
					# Reset stored cost cache columns; the report no longer
					# reads them, but we don't want stale lies on the doc.
					if new_statu == PAYING_STATUS:
						# Leave existing component columns; they're stale-cache
						# and unused by the new report. Operator can recompute
						# explicitly if they want fresh stored values.
						pass
					else:
						to_write["otel_maliyeti"] = 0
						to_write["ucak_maliyeti"] = 0
						to_write["vize_maliyeti"] = 0
						to_write["diyanet_maliyeti"] = 0
						to_write["toplam_maliyet"] = new_mc
						to_write["kar"] = -new_mc
				if not cur_imported:
					to_write["is_imported"] = 1
				if not cur_locked:
					to_write["locked_financials"] = 1

				if not to_write:
					totals["already_correct"] += 1
					continue

				# Bypass validate: the lock guard would otherwise block this.
				frappe.db.set_value(
					"Umre Booking",
					b["name"],
					to_write,
					update_modified=False,
				)
				if diff:
					totals["updated_rows"] += 1
					print(
						f"    {b['name']} tc={tc}  statu {cur_statu}->{new_statu}  "
						f"ucret {cur_ucret:.2f}->{new_ucret:.2f}  manual_cost {cur_mc:.2f}->{new_mc:.2f}"
					)
				if "locked_financials" in to_write:
					totals["locked_rows"] += 1

	# Final pass: ensure Cost Components reflect the (possibly corrected)
	# statu / manual_cost. recompute_components is idempotent — it only
	# rebuilds system-generated rows, leaving any operator-added components
	# alone. Cheap when nothing changed (engine just no-ops).
	from umre_ops.umre_ops.services.cost_engine import recompute_components, ensure_canonical_cost_types
	ensure_canonical_cost_types()
	recomputed = 0
	failed_recompute = []
	touched_bookings = frappe.get_all(
		"Umre Booking",
		fields=["name", "statu", "manual_cost"],
		order_by="creation asc",
	)
	for row in touched_bookings:
		try:
			recompute_components(row["name"])
			recomputed += 1
		except Exception as exc:
			failed_recompute.append({"booking": row["name"], "statu": row["statu"], "error": str(exc)})
			frappe.db.rollback()
	print(f"[restore_excel_truth] cost components recomputed for {recomputed} bookings; failures={len(failed_recompute)}")
	if failed_recompute:
		for f in failed_recompute[:10]:
			print(f"  - {f['booking']} statu={f['statu']!r} :: {f['error']}")

	frappe.db.commit()
	print(f"[restore_excel_truth] done  totals={totals}")
