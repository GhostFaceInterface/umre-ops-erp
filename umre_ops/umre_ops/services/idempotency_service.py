# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import frappe


@dataclass(frozen=True)
class IdempotencyResult:
	event_name: str
	status: str
	result_doctype: str | None
	result_name: str | None


def stable_json_dumps(payload: Any) -> str:
	return json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True, default=str)


def sha256_hex(text: str) -> str:
	return hashlib.sha256(text.encode("utf-8")).hexdigest()


def ensure_event_started(
	*,
	idempotency_key: str,
	operation: str,
	company: str,
	source_doctype: str,
	source_name: str,
	source_child_doctype: str | None = None,
	source_child_name: str | None = None,
	request_payload: dict | None = None,
) -> tuple[str, str]:
	"""
	Create (or reuse) `Umre Posting Event` as the dedupe gate.

	Returns (event_name, request_hash).
	Raises if the same key is reused with different payload hash.
	"""
	if not idempotency_key:
		frappe.throw("idempotency_key is required")

	request_payload = request_payload or {}
	request_hash = sha256_hex(stable_json_dumps(request_payload))

	existing = frappe.db.get_value(
		"Umre Posting Event",
		{"idempotency_key": idempotency_key},
		["name", "status", "request_hash"],
		as_dict=True,
	)
	if existing:
		if existing.get("request_hash") and existing.get("request_hash") != request_hash:
			frappe.throw(
				f"Idempotency key reuse detected for {idempotency_key}. Payload hash mismatch."
			)
		# If already exists, let caller decide whether to short-circuit on status/result.
		return existing["name"], request_hash

	now = datetime.now(timezone.utc).replace(tzinfo=None)
	doc = frappe.get_doc(
		{
			"doctype": "Umre Posting Event",
			"idempotency_key": idempotency_key,
			"operation": operation,
			"status": "Started",
			"company": company,
			"source_doctype": source_doctype,
			"source_name": source_name,
			"source_child_doctype": source_child_doctype,
			"source_child_name": source_child_name,
			"request_hash": request_hash,
			"attempt_count": 1,
			"started_on": now,
			"request_payload_json": stable_json_dumps(request_payload),
		}
	)
	# Link target only exists with ERPNext; on Frappe-only sites (e.g. CI) validate the key otherwise.
	validate_company = bool(frappe.db.exists("DocType", "Company"))
	doc.insert(ignore_permissions=True, ignore_links=not validate_company)
	return doc.name, request_hash


def get_existing_result(idempotency_key: str) -> IdempotencyResult | None:
	row = frappe.db.get_value(
		"Umre Posting Event",
		{"idempotency_key": idempotency_key},
		["name", "status", "result_doctype", "result_name"],
		as_dict=True,
	)
	if not row:
		return None
	return IdempotencyResult(
		event_name=row["name"],
		status=row.get("status"),
		result_doctype=row.get("result_doctype"),
		result_name=row.get("result_name"),
	)


def mark_event_succeeded(*, event_name: str, result_doctype: str, result_name: str, result_payload: dict | None = None) -> None:
	now = datetime.now(timezone.utc).replace(tzinfo=None)
	frappe.db.set_value(
		"Umre Posting Event",
		event_name,
		{
			"status": "Succeeded",
			"result_doctype": result_doctype,
			"result_name": result_name,
			"finished_on": now,
			"result_payload_json": stable_json_dumps(result_payload or {}),
			"error": None,
		},
		update_modified=False,
	)


def mark_event_failed(*, event_name: str, error: str) -> None:
	now = datetime.now(timezone.utc).replace(tzinfo=None)
	frappe.db.set_value(
		"Umre Posting Event",
		event_name,
		{
			"status": "Failed",
			"finished_on": now,
			"error": error,
		},
		update_modified=False,
	)

