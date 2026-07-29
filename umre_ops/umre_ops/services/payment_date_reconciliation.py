# Copyright (c) 2026, Sermed Turizm and contributors

"""Auditable, fail-closed payment date reconciliation."""

from __future__ import annotations

import csv
import hashlib
import io
import json
from datetime import date
from pathlib import Path

import frappe
from frappe import _
from frappe.utils import getdate, now_datetime

REQUIRED_COLUMNS = {
	"booking_name",
	"payment_row_name",
	"expected_current_date",
	"verified_posting_date",
	"date_source",
	"evidence_reference",
}
VERIFIABLE_SOURCES = {"Bank", "Receipt", "Excel", "Manual"}
MAX_CSV_BYTES = 5 * 1024 * 1024


def _read_csv(csv_path: str) -> tuple[str, list[dict[str, str]]]:
	path = Path(csv_path).expanduser()
	if path.suffix.lower() != ".csv":
		frappe.throw(_("Payment date repair input must be a CSV file."))
	raw = path.read_bytes()
	if not raw or len(raw) > MAX_CSV_BYTES:
		frappe.throw(_("Payment date repair CSV must be non-empty and at most 5 MB."))
	try:
		text = raw.decode("utf-8-sig")
	except UnicodeDecodeError:
		frappe.throw(_("Payment date repair CSV must be UTF-8 encoded."))
	reader = csv.DictReader(io.StringIO(text))
	columns = set(reader.fieldnames or [])
	missing = sorted(REQUIRED_COLUMNS - columns)
	if missing:
		frappe.throw(_("Payment date repair CSV is missing columns: {0}").format(", ".join(missing)))
	rows = [{key: (value or "").strip() for key, value in row.items()} for row in reader]
	if not rows:
		frappe.throw(_("Payment date repair CSV has no data rows."))
	return hashlib.sha256(raw).hexdigest(), rows


def _repair_key(batch_hash: str, row: dict[str, str]) -> str:
	payload = {key: row[key] for key in sorted(REQUIRED_COLUMNS)}
	return hashlib.sha256(
		f"{batch_hash}:{json.dumps(payload, ensure_ascii=False, sort_keys=True)}".encode()
	).hexdigest()


def _parse_iso_date(value: str, label: str) -> str:
	if not value:
		raise ValueError(f"{label} is required")
	parsed = date.fromisoformat(value)
	if parsed.isoformat() != value:
		raise ValueError(f"{label} must use YYYY-MM-DD")
	return parsed.isoformat()


def _has_posting_event(
	booking_name: str, payment_row_name: str, idempotency_key: str | None = None
) -> bool:
	base_filters = {"source_doctype": "Umre Booking", "source_name": booking_name}
	if idempotency_key and frappe.db.exists(
		"Umre Posting Event",
		{**base_filters, "idempotency_key": ["in", [f"{idempotency_key}::JE", f"{idempotency_key}::PE"]]},
	):
		return True
	return bool(
		frappe.db.exists(
			"Umre Posting Event",
			{**base_filters, "idempotency_key": ["like", f"%::{payment_row_name}::%"]},
		)
	)


def _build_plan(batch_hash: str, rows: list[dict[str, str]]) -> list[dict]:
	plan = []
	errors = []
	seen = set()
	for number, row in enumerate(rows, start=2):
		identity = (row["booking_name"], row["payment_row_name"])
		if identity in seen:
			errors.append(f"row {number}: duplicate booking/payment identity")
			continue
		seen.add(identity)
		try:
			expected_date = _parse_iso_date(row["expected_current_date"], "expected_current_date")
			new_date = _parse_iso_date(row["verified_posting_date"], "verified_posting_date")
		except Exception:
			errors.append(f"row {number}: expected and verified dates must be valid ISO dates")
			continue
		if row["date_source"] not in VERIFIABLE_SOURCES:
			errors.append(f"row {number}: date_source must be Bank, Receipt, Excel, or Manual")
			continue
		if not row["evidence_reference"]:
			errors.append(f"row {number}: evidence_reference is required")
			continue
		current = frappe.db.get_value(
			"Umre Booking Payment",
			{
				"name": row["payment_row_name"],
				"parent": row["booking_name"],
				"parenttype": "Umre Booking",
				"parentfield": "payments",
			},
			[
				"name",
				"posting_date",
				"legacy_posting_date",
				"posting_status",
				"payment_entry",
				"journal_entry",
				"date_verification_status",
				"date_repair_key",
				"idempotency_key",
			],
			as_dict=True,
		)
		if not current:
			errors.append(f"row {number}: payment row does not belong to the booking")
			continue
		key = _repair_key(batch_hash, row)
		current_date = getdate(current.posting_date).isoformat() if current.posting_date else ""
		already_applied = (
			current.date_repair_key == key
			and current_date == new_date
			and current.date_verification_status == "Verified"
		)
		if already_applied:
			plan.append({"row": number, "status": "already_applied", "repair_key": key, **row})
			continue
		if current.date_verification_status == "Verified" or current.date_repair_key:
			errors.append(f"row {number}: verified payment audit cannot be overwritten")
			continue
		if current_date != expected_date:
			errors.append(f"row {number}: current date changed; expected {expected_date}, found {current_date}")
			continue
		if (current.posting_status or "Draft") != "Draft" or current.payment_entry or current.journal_entry:
			errors.append(f"row {number}: posted or voucher-linked payment cannot be repaired")
			continue
		if _has_posting_event(
			row["booking_name"], row["payment_row_name"], current.idempotency_key
		):
			errors.append(f"row {number}: payment has an accounting posting event")
			continue
		plan.append(
			{
				"row": number,
				"status": "ready",
				"repair_key": key,
				"legacy_posting_date": current.legacy_posting_date or current_date,
				"expected_legacy_posting_date": current.legacy_posting_date or "",
				"expected_date_verification_status": current.date_verification_status or "",
				"expected_idempotency_key": current.idempotency_key or "",
				**row,
			}
		)
	if errors:
		frappe.throw(_("Payment date repair validation failed:\n{0}").format("\n".join(errors)))
	return plan


def _lock_and_revalidate(plan: list[dict]) -> None:
	"""Close the validation/apply race with row locks and a second CAS check."""
	for item in plan:
		if item["status"] != "ready":
			continue
		rows = frappe.db.sql(
			"""
			SELECT posting_date, legacy_posting_date, posting_status, payment_entry, journal_entry,
			       date_verification_status, date_repair_key, idempotency_key
			FROM `tabUmre Booking Payment`
			WHERE name = %s AND parent = %s
			  AND parenttype = 'Umre Booking' AND parentfield = 'payments'
			FOR UPDATE
			""",
			(item["payment_row_name"], item["booking_name"]),
			as_dict=True,
		)
		if not rows:
			frappe.throw(_("Payment row disappeared before the repair could be applied."))
		current = rows[0]
		current_date = getdate(current.posting_date).isoformat() if current.posting_date else ""
		current_legacy_date = (
			getdate(current.legacy_posting_date).isoformat() if current.legacy_posting_date else ""
		)
		if (
			current_date != item["expected_current_date"]
			or current_legacy_date != item["expected_legacy_posting_date"]
			or (current.date_verification_status or "")
			!= item["expected_date_verification_status"]
			or (current.idempotency_key or "") != item["expected_idempotency_key"]
			or (current.posting_status or "Draft") != "Draft"
			or current.payment_entry
			or current.journal_entry
			or current.date_repair_key
			or _has_posting_event(
				item["booking_name"], item["payment_row_name"], current.idempotency_key
			)
		):
			frappe.throw(_("Payment row changed after validation; no repair was applied."))


def repair_payment_dates(csv_path: str, apply: bool = False, expected_sha256: str | None = None) -> dict:
	"""Validate a complete repair batch and optionally apply it atomically."""
	frappe.only_for("System Manager")
	batch_hash, rows = _read_csv(csv_path)
	if apply and (not expected_sha256 or expected_sha256.lower() != batch_hash):
		frappe.throw(_("Apply requires the exact SHA-256 returned by a prior dry-run."))
	if not apply:
		plan = _build_plan(batch_hash, rows)
		ready = [item for item in plan if item["status"] == "ready"]
		return {"mode": "dry-run", "batch_hash": batch_hash, "ready": len(ready), "rows": plan}

	frappe.db.savepoint("payment_date_repair")
	try:
		plan = _build_plan(batch_hash, rows)
		ready = [item for item in plan if item["status"] == "ready"]
		_lock_and_revalidate(plan)
		verified_on = now_datetime()
		verified_by = frappe.session.user
		for item in ready:
			frappe.db.set_value(
				"Umre Booking Payment",
				item["payment_row_name"],
				{
					"posting_date": item["verified_posting_date"],
					"legacy_posting_date": item["legacy_posting_date"],
					"date_source": item["date_source"],
					"date_verification_status": "Verified",
					"date_evidence_reference": item["evidence_reference"],
					"verified_by": verified_by,
					"verified_on": verified_on,
					"date_repair_key": item["repair_key"],
				},
				update_modified=False,
			)
	except Exception:
		frappe.db.rollback(save_point="payment_date_repair")
		raise
	return {
		"mode": "apply",
		"batch_hash": batch_hash,
		"updated": len(ready),
		"already_applied": len(plan) - len(ready),
	}
