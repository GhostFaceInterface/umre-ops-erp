# Copyright (c) 2026, Sermed Turizm and contributors

from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from umre_ops.umre_ops.services.payment_date_reconciliation import (
	_build_plan,
	_parse_iso_date,
	repair_payment_dates,
)
from umre_ops.umre_ops.services.payment_service import post_payment_row_receipt


def _csv_row(**overrides) -> dict[str, str]:
	row = {
		"booking_name": "BOOKING-1",
		"payment_row_name": "PAY-1",
		"expected_current_date": "1980-01-01",
		"verified_posting_date": "2026-07-20",
		"date_source": "Receipt",
		"evidence_reference": "RECEIPT-42",
	}
	row.update(overrides)
	return row


def _current(**overrides):
	values = {
		"name": "PAY-1",
		"posting_date": "1980-01-01",
		"legacy_posting_date": None,
		"posting_status": "Draft",
		"payment_entry": None,
		"journal_entry": None,
		"date_verification_status": "Needs Review",
		"date_repair_key": None,
	}
	values.update(overrides)
	return SimpleNamespace(**values)


class TestReleaseTwoPostingGate(TestCase):
	@patch("umre_ops.umre_ops.services.payment_service.frappe.throw", side_effect=ValueError)
	@patch("umre_ops.umre_ops.services.payment_service.frappe.get_doc")
	def test_unverified_date_is_rejected_even_in_dry_run(self, get_doc: Mock, _throw: Mock) -> None:
		row = SimpleNamespace(
			name="PAY-1",
			posting_date="2026-07-20",
			amount=100,
			date_verification_status="Needs Review",
		)
		booking = Mock()
		booking.get.return_value = [row]
		get_doc.return_value = booking
		with (
			patch("umre_ops.umre_ops.services.payment_service._", side_effect=lambda message: message),
			self.assertRaises(ValueError),
		):
			post_payment_row_receipt(
				booking_name="BOOKING-1",
				payment_row_name="PAY-1",
				paid_account="Cash - C",
				dry_run=True,
			)


class TestReleaseTwoRepairPlan(TestCase):
	def test_blank_date_is_not_coerced_to_today(self) -> None:
		with self.assertRaises(ValueError):
			_parse_iso_date("", "verified_posting_date")

	@patch("umre_ops.umre_ops.services.payment_date_reconciliation._has_posting_event", return_value=False)
	def test_plan_preserves_legacy_date_and_never_mutates(self, _event: Mock) -> None:
		get_value = Mock(return_value=_current())
		with patch(
			"umre_ops.umre_ops.services.payment_date_reconciliation.frappe.db",
			SimpleNamespace(get_value=get_value),
		):
			plan = _build_plan("batch", [_csv_row()])
		self.assertEqual(plan[0]["status"], "ready")
		self.assertEqual(plan[0]["legacy_posting_date"], "1980-01-01")
		get_value.assert_called_once()

	@patch("umre_ops.umre_ops.services.payment_date_reconciliation.frappe.throw", side_effect=ValueError)
	@patch("umre_ops.umre_ops.services.payment_date_reconciliation._has_posting_event", return_value=False)
	def test_stale_expected_date_rejects_entire_batch(
		self, _event: Mock, _throw: Mock
	) -> None:
		with (
			patch("umre_ops.umre_ops.services.payment_date_reconciliation._", side_effect=lambda message: message),
			patch(
				"umre_ops.umre_ops.services.payment_date_reconciliation.frappe.db",
				SimpleNamespace(get_value=Mock(return_value=_current(posting_date="2020-01-01"))),
			),
			self.assertRaises(ValueError),
		):
			_build_plan("batch", [_csv_row()])

	@patch("umre_ops.umre_ops.services.payment_date_reconciliation.frappe.throw", side_effect=ValueError)
	@patch("umre_ops.umre_ops.services.payment_date_reconciliation._has_posting_event", return_value=False)
	def test_posted_payment_cannot_be_repaired(self, _event: Mock, _throw: Mock) -> None:
		with (
			patch("umre_ops.umre_ops.services.payment_date_reconciliation._", side_effect=lambda message: message),
			patch(
				"umre_ops.umre_ops.services.payment_date_reconciliation.frappe.db",
				SimpleNamespace(
					get_value=Mock(return_value=_current(posting_status="Posted", payment_entry="PE-1"))
				),
			),
			self.assertRaises(ValueError),
		):
			_build_plan("batch", [_csv_row()])

	@patch("umre_ops.umre_ops.services.payment_date_reconciliation.frappe.throw", side_effect=ValueError)
	@patch("umre_ops.umre_ops.services.payment_date_reconciliation._has_posting_event", return_value=False)
	def test_verified_audit_cannot_be_overwritten(self, _event: Mock, _throw: Mock) -> None:
		with (
			patch("umre_ops.umre_ops.services.payment_date_reconciliation._", side_effect=lambda message: message),
			patch(
				"umre_ops.umre_ops.services.payment_date_reconciliation.frappe.db",
				SimpleNamespace(
					get_value=Mock(
						return_value=_current(
							date_verification_status="Verified", date_repair_key="different-key"
						)
					)
				),
			),
			self.assertRaises(ValueError),
		):
			_build_plan("batch", [_csv_row()])

	@patch("umre_ops.umre_ops.services.payment_date_reconciliation._build_plan")
	@patch("umre_ops.umre_ops.services.payment_date_reconciliation._read_csv")
	@patch("umre_ops.umre_ops.services.payment_date_reconciliation.frappe.only_for")
	def test_default_mode_is_dry_run_with_zero_writes(
		self, _only_for: Mock, read_csv: Mock, build_plan: Mock
	) -> None:
		read_csv.return_value = ("batch", [_csv_row()])
		build_plan.return_value = [{"status": "ready"}]
		set_value = Mock()
		with patch(
			"umre_ops.umre_ops.services.payment_date_reconciliation.frappe.db",
			SimpleNamespace(set_value=set_value),
		):
			result = repair_payment_dates("repair.csv")
		self.assertEqual(result["mode"], "dry-run")
		set_value.assert_not_called()
