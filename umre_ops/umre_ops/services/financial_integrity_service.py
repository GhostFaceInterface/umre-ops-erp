# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
"""
Hard-failing financial integrity checks.

This service is the *only* sanctioned way to assert that the booking layer
matches its imported truth. It deliberately raises on the first violation so
the system is either correct OR loud — never silently drifting.

Checks per tour:
    1. SUM(ucret WHERE statu="UMRECI") matches Excel canonical total to ±0.01
       (when an Excel truth file is registered for the tour).
    2. No non-UMRECI booking has `ucret > 0`.
    3. No UMRECI booking has `ucret == 0`.
    4. Every booking in the tour has `locked_financials = 1`.
    5. Per-TC join: ERP `statu`, `ucret`, `manual_cost` match Excel truth row
       for the same TC (when truth file is provided).

Public surface:
    validate_financial_integrity(tour, raise_on_fail=True, excel_truth_path=None)
        -> dict report

The function is whitelisted for desk/admin invocation.
"""
from __future__ import annotations

import json
from pathlib import Path

import frappe
from frappe import _
from frappe.utils import flt

PAYING_STATUS = "UMRECI"
TRUTH_DIR = Path(__file__).resolve().parent.parent / "patches" / "data"


def _load_truth(excel_truth_path: str | None, tour: str) -> dict | None:
	"""Return the canonical Excel truth for `tour`, or None if unavailable."""
	if excel_truth_path:
		p = Path(excel_truth_path)
	else:
		# Built-in: registered for known tours under patches/data/excel_truth_*.json
		# Choose the file whose `tour_pattern` matches `tour`.
		for candidate in TRUTH_DIR.glob("excel_truth_*.json"):
			doc = json.loads(candidate.read_text(encoding="utf-8"))
			pat = (doc.get("tour_pattern") or "").rstrip("%")
			if pat and tour.startswith(pat):
				return doc
		return None
	if not p.exists():
		return None
	return json.loads(p.read_text(encoding="utf-8"))


@frappe.whitelist()
def validate_financial_integrity(
	tour: str,
	raise_on_fail: bool | int | str = True,
	excel_truth_path: str | None = None,
) -> dict:
	"""Run all five checks against `tour`. Either return a clean report or raise.

	Returns a structured dict report. Always returns the report — but if
	`raise_on_fail` is truthy and any check failed, raises `frappe.ValidationError`
	*after* assembling the full report so callers can inspect everything.
	"""
	if not tour:
		frappe.throw(_("Argument 'tour' is required."))

	if isinstance(raise_on_fail, str):
		raise_on_fail = raise_on_fail.lower() not in {"0", "false", "no", ""}
	raise_on_fail = bool(raise_on_fail)

	bookings = frappe.db.sql(
		"""
		SELECT b.name, b.statu, b.ucret, b.manual_cost,
		       b.locked_financials, b.is_imported, u.tc_kimlik AS tc
		FROM `tabUmre Booking` b
		LEFT JOIN `tabUmreci` u ON u.name = b.umreci
		WHERE b.tur = %s
		""",
		(tour,),
		as_dict=True,
	)

	report: dict = {
		"tour": tour,
		"total_bookings": len(bookings),
		"umreci_count": 0,
		"non_umreci_count": 0,
		"umreci_revenue_total": 0.0,
		"non_umreci_manual_cost_total": 0.0,
		"violations": [],
		"checks": {},
	}

	# Aggregate pass.
	for b in bookings:
		if b["statu"] == PAYING_STATUS:
			report["umreci_count"] += 1
			report["umreci_revenue_total"] += flt(b["ucret"] or 0)
		else:
			report["non_umreci_count"] += 1
			report["non_umreci_manual_cost_total"] += flt(b["manual_cost"] or 0)

	# 2 — non-UMRECI must NOT carry revenue.
	bad_revenue = [b for b in bookings if b["statu"] != PAYING_STATUS and flt(b["ucret"] or 0) > 0]
	report["checks"]["non_umreci_with_ucret_gt_0"] = {
		"violations": len(bad_revenue),
		"rows": [{"booking": b["name"], "tc": b["tc"], "statu": b["statu"], "ucret": flt(b["ucret"])} for b in bad_revenue],
	}
	if bad_revenue:
		report["violations"].append("non_umreci_with_ucret_gt_0")

	# 3 — UMRECI must carry positive revenue.
	bad_zero = [b for b in bookings if b["statu"] == PAYING_STATUS and flt(b["ucret"] or 0) == 0]
	report["checks"]["umreci_with_ucret_eq_0"] = {
		"violations": len(bad_zero),
		"rows": [{"booking": b["name"], "tc": b["tc"]} for b in bad_zero],
	}
	if bad_zero:
		report["violations"].append("umreci_with_ucret_eq_0")

	# 4 — All bookings must be locked.
	unlocked = [b for b in bookings if not b["locked_financials"]]
	report["checks"]["unlocked_bookings"] = {
		"violations": len(unlocked),
		"rows": [{"booking": b["name"], "tc": b["tc"], "statu": b["statu"]} for b in unlocked[:50]],
	}
	if unlocked:
		report["violations"].append("unlocked_bookings")

	# 4b — Cost-engine integrity: every booking must carry the canonical components for its statu.
	from umre_ops.umre_ops.services.cost_engine import (
		SYSTEM_TYPES_FOR_UMRECI,
		SYSTEM_TYPES_FOR_NON_UMRECI,
	)
	comp_rows = frappe.db.sql(
		"""
		SELECT booking, cost_type, SUM(amount) AS total
		FROM `tabCost Component`
		WHERE booking IN %(names)s
		GROUP BY booking, cost_type
		""",
		{"names": tuple(b["name"] for b in bookings) or ("__none__",)},
		as_dict=True,
	)
	comps_by_booking: dict[str, dict[str, float]] = {}
	for r in comp_rows:
		comps_by_booking.setdefault(r["booking"], {})[r["cost_type"]] = flt(r["total"] or 0)
	missing_components = []
	negative_components = []
	for b in bookings:
		current = comps_by_booking.get(b["name"], {})
		required = SYSTEM_TYPES_FOR_UMRECI if b["statu"] == PAYING_STATUS else SYSTEM_TYPES_FOR_NON_UMRECI
		lacks = [t for t in required if t not in current]
		if lacks:
			missing_components.append({"booking": b["name"], "tc": b["tc"], "statu": b["statu"], "missing": lacks})
		for t, total in current.items():
			if flt(total) < 0:
				negative_components.append({"booking": b["name"], "cost_type": t, "amount": flt(total)})
	report["checks"]["missing_components"] = {
		"violations": len(missing_components),
		"rows": missing_components[:50],
	}
	report["checks"]["negative_components"] = {
		"violations": len(negative_components),
		"rows": negative_components[:50],
	}
	if missing_components:
		report["violations"].append("missing_components")
	if negative_components:
		report["violations"].append("negative_components")

	# 4c — Component-derived cost totals must match per-booking cost in the report layer.
	cost_total_components = sum(
		flt(total)
		for d in comps_by_booking.values()
		for total in d.values()
	)
	report["component_cost_total"] = flt(cost_total_components)

	# 1 + 5 — Excel truth checks.
	truth = _load_truth(excel_truth_path, tour)
	if truth:
		exp_total = flt(truth["summary"]["umreci_revenue_total"])
		exp_count = int(truth["summary"]["umreci_count"])
		report["checks"]["excel_revenue_total"] = {
			"excel": exp_total,
			"erp": report["umreci_revenue_total"],
			"delta": flt(report["umreci_revenue_total"] - exp_total),
		}
		report["checks"]["excel_umreci_count"] = {
			"excel": exp_count,
			"erp": report["umreci_count"],
			"delta": report["umreci_count"] - exp_count,
		}
		if abs(report["umreci_revenue_total"] - exp_total) > 0.01:
			report["violations"].append("excel_revenue_total_mismatch")
		if report["umreci_count"] != exp_count:
			report["violations"].append("excel_umreci_count_mismatch")

		# Per-TC join.
		truth_by_tc = {r["tc"]: r for r in truth["rows"]}
		erp_by_tc = {b["tc"]: b for b in bookings if b["tc"]}
		mismatches = []
		for tc, ex in truth_by_tc.items():
			erp = erp_by_tc.get(tc)
			if not erp:
				mismatches.append({"tc": tc, "issue": "missing_in_erp"})
				continue
			if (erp["statu"] or "") != ex["statu"]:
				mismatches.append({
					"tc": tc, "issue": "statu_mismatch",
					"excel": ex["statu"], "erp": erp["statu"], "booking": erp["name"],
				})
			if abs(flt(erp["ucret"] or 0) - flt(ex["ucret"])) > 0.01:
				mismatches.append({
					"tc": tc, "issue": "ucret_mismatch",
					"excel": ex["ucret"], "erp": flt(erp["ucret"] or 0), "booking": erp["name"],
				})
			if abs(flt(erp["manual_cost"] or 0) - flt(ex["manual_cost"])) > 0.01:
				mismatches.append({
					"tc": tc, "issue": "manual_cost_mismatch",
					"excel": ex["manual_cost"], "erp": flt(erp["manual_cost"] or 0), "booking": erp["name"],
				})
		extra_in_erp = [tc for tc in erp_by_tc if tc not in truth_by_tc]
		report["checks"]["per_tc_join"] = {
			"violations": len(mismatches) + len(extra_in_erp),
			"mismatches": mismatches[:200],
			"extra_in_erp_tcs": extra_in_erp[:50],
		}
		if mismatches or extra_in_erp:
			report["violations"].append("per_tc_join_mismatch")
	else:
		report["checks"]["excel_revenue_total"] = {"status": "skipped (no truth file registered)"}

	report["passed"] = not report["violations"]

	if not report["passed"] and raise_on_fail:
		frappe.throw(
			_(
				"Financial integrity FAILED for tour {0}. Violations: {1}. "
				"Inspect the report dict for row-level detail."
			).format(tour, ", ".join(report["violations"]))
		)

	return report
