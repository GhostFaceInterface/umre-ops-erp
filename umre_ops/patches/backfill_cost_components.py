# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
"""
Backfill `Cost Component` rows for every existing `Umre Booking`.

Idempotent. Run once or many times — for each booking that does not yet have
any system-generated component rows, this patch invokes the cost engine to
generate them. Bookings that already have components are left alone.

Strategy
--------
1. Seed canonical Cost Type master rows (HOTEL/FLIGHT/...).
2. For every booking, call ``cost_engine.generate_components(booking)``.
   This runs the same code path as ``Umre Booking.after_insert`` so the
   live system and the historical backfill produce identical structures.
3. Print a one-line summary so the patch log carries proof.

Edge cases handled by the engine:
* UMRECI booking → 6 components (HOTEL, FLIGHT, VISA, DIYANET, MEAL, OTHER).
* Non-UMRECI booking with positive `manual_cost` → 1 MANUAL component.
* Non-UMRECI booking with `manual_cost=0` is reported as an error (cannot
  satisfy "every booking MUST have at least one component"). We log the
  offending bookings and continue; ops should fix `manual_cost` and re-run.
"""
from __future__ import annotations

import frappe

from umre_ops.umre_ops.services.cost_engine import (
	ensure_canonical_cost_types,
	generate_components,
)


def execute() -> None:
	ensure_canonical_cost_types()

	bookings = frappe.get_all(
		"Umre Booking",
		fields=["name", "statu", "manual_cost"],
		order_by="creation asc",
	)
	created = 0
	skipped = 0
	failed = []
	for row in bookings:
		try:
			existing = frappe.db.count(
				"Cost Component", {"booking": row["name"], "is_system_generated": 1}
			)
			if existing:
				skipped += 1
				continue
			generate_components(row["name"])
			created += 1
		except Exception as exc:
			failed.append({"booking": row["name"], "statu": row["statu"], "error": str(exc)})
			# Continue: a single bad row should not block the whole backfill.
			frappe.db.rollback()

	frappe.db.commit()

	print(
		f"[backfill_cost_components] bookings={len(bookings)} "
		f"created={created} skipped_existing={skipped} failed={len(failed)}"
	)
	if failed:
		print("[backfill_cost_components] failed rows (first 20):")
		for f in failed[:20]:
			print(f"  - {f['booking']} statu={f['statu']!r} :: {f['error']}")
