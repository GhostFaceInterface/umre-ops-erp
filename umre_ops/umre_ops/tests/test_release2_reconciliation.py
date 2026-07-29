# Copyright (c) 2026, Sermed Turizm and contributors

from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from umre_ops.install import after_install
from umre_ops.umre_ops.doctype.umre_booking.umre_booking import UmreBooking
from umre_ops.umre_ops.services.payment_date_reconciliation import (
	_build_plan,
	_has_posting_event,
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
		"idempotency_key": None,
	}
	values.update(overrides)
	return SimpleNamespace(**values)


class TestReleaseTwoPostingGate(TestCase):
	@patch("umre_ops.umre_ops.doctype.umre_booking.umre_booking.frappe.get_all")
	def test_parent_lock_allows_only_controlled_posting_transition(self, get_all: Mock) -> None:
		old = SimpleNamespace(
			name="PAY-1",
			posting_date="2026-07-20",
			amount=100,
			currency="USD",
			mode_of_payment="Cash",
			reference_no=None,
			reference_date=None,
			posting_status="Draft",
			journal_entry=None,
			payment_entry=None,
			idempotency_key=None,
			legacy_posting_date="1980-01-01",
			date_source="Receipt",
			date_verification_status="Verified",
			date_evidence_reference="RECEIPT-42",
			verified_by="Administrator",
			verified_on="2026-07-29 12:00:00",
			date_repair_key="REPAIR-1",
		)
		old.get = lambda field: getattr(old, field, None)
		values = {**vars(old), "posting_status": "Posted", "journal_entry": "JE-1", "idempotency_key": "KEY-1"}
		new = SimpleNamespace(**values)
		new.get = lambda field: getattr(new, field, None)
		booking = SimpleNamespace(
			name="BOOKING-1",
			flags={
				"accounting_posting_transition": {
					"payment_row_name": "PAY-1",
					"expected_doctype": "Journal Entry",
					"voucher_name": "JE-1",
					"idempotency_key": "KEY-1",
				}
			},
			is_new=lambda: False,
			get=lambda _field: [new],
		)
		get_all.return_value = [old]

		UmreBooking._enforce_posted_payment_lock(booking)

	@patch("umre_ops.umre_ops.doctype.umre_booking.umre_booking.frappe.throw", side_effect=ValueError)
	@patch("umre_ops.umre_ops.doctype.umre_booking.umre_booking.frappe.get_all")
	def test_posting_transition_rejects_stale_other_verified_row(
		self, get_all: Mock, _throw: Mock
	) -> None:
		def payment(name: str, posting_date: str):
			values = {
				"name": name,
				"posting_date": posting_date,
				"amount": 100,
				"currency": "USD",
				"mode_of_payment": "Cash",
				"reference_no": None,
				"reference_date": None,
				"posting_status": "Draft",
				"journal_entry": None,
				"payment_entry": None,
				"idempotency_key": None,
				"legacy_posting_date": "1980-01-01",
				"date_source": "Receipt",
				"date_verification_status": "Verified",
				"date_evidence_reference": "RECEIPT-42",
				"verified_by": "Administrator",
				"verified_on": "2026-07-29 12:00:00",
				"date_repair_key": "REPAIR-1",
			}
			row = SimpleNamespace(**values)
			row.get = lambda field: getattr(row, field, None)
			return row

		old_target = payment("PAY-1", "2026-07-20")
		old_other = payment("PAY-2", "2026-07-21")
		new_target = payment("PAY-1", "2026-07-20")
		new_target.posting_status = "Posted"
		new_target.journal_entry = "JE-1"
		new_target.idempotency_key = "KEY-1"
		stale_other = payment("PAY-2", "1980-01-01")
		booking = SimpleNamespace(
			name="BOOKING-1",
			flags={
				"accounting_posting_transition": {
					"payment_row_name": "PAY-1",
					"expected_doctype": "Journal Entry",
					"voucher_name": "JE-1",
					"idempotency_key": "KEY-1",
				}
			},
			is_new=lambda: False,
			get=lambda _field: [new_target, stale_other],
		)
		get_all.return_value = [old_target, old_other]

		with (
			patch(
				"umre_ops.umre_ops.doctype.umre_booking.umre_booking._",
				side_effect=lambda message: message,
			),
			self.assertRaises(ValueError),
		):
			UmreBooking._enforce_posted_payment_lock(booking)

	@patch("umre_ops.umre_ops.services.payment_service.frappe.throw", side_effect=ValueError)
	@patch("umre_ops.umre_ops.services.payment_service.frappe.get_doc")
	def test_unverified_date_is_rejected_even_in_dry_run(self, get_doc: Mock, _throw: Mock) -> None:
		row = SimpleNamespace(
			name="PAY-1",
			posting_date="2026-07-20",
			amount=100,
			date_verification_status="Needs Review",
			date_source="Manual",
			is_new=lambda: False,
		)
		booking = Mock()
		booking.get.return_value = [row]
		get_doc.return_value = booking
		with (
			patch("umre_ops.umre_ops.services.payment_service._", side_effect=lambda message: message),
			patch(
				"umre_ops.umre_ops.doctype.umre_booking_payment.umre_booking_payment._",
				side_effect=lambda message: message,
			),
			self.assertRaises(ValueError),
		):
			post_payment_row_receipt(
				booking_name="BOOKING-1",
				payment_row_name="PAY-1",
				paid_account="Cash - C",
				dry_run=True,
			)

	@patch("umre_ops.umre_ops.services.payment_service.post_booking_receipt_journal_entry")
	@patch("umre_ops.umre_ops.services.payment_service.frappe.get_doc")
	def test_verified_draft_can_transition_to_posted(self, get_doc: Mock, post_receipt: Mock) -> None:
		row = SimpleNamespace(
			name="PAY-1",
			idempotency_key=None,
			posting_date="2026-07-20",
			amount=100,
			currency="USD",
			mode_of_payment="Cash",
			reference_no=None,
			reference_date=None,
			remarks=None,
			posting_status="Draft",
			payment_entry=None,
			journal_entry=None,
			date_source="Receipt",
			date_verification_status="Verified",
			date_evidence_reference="RECEIPT-42",
			verified_by="Administrator",
			verified_on="2026-07-29 12:00:00",
			is_new=lambda: False,
			as_dict=lambda: {"name": "PAY-1"},
		)
		booking = Mock()
		booking.customer = None
		booking.get.return_value = [row]
		get_doc.return_value = booking
		post_receipt.return_value = SimpleNamespace(doctype="Journal Entry", name="JE-1")

		result = post_payment_row_receipt(
			booking_name="BOOKING-1",
			payment_row_name="PAY-1",
			paid_account="Cash - C",
		)

		self.assertEqual(result["result_name"], "JE-1")
		self.assertEqual(row.posting_status, "Posted")
		self.assertEqual(row.journal_entry, "JE-1")
		self.assertEqual(
			booking.flags.accounting_posting_transition,
			{
				"payment_row_name": "PAY-1",
				"expected_doctype": "Journal Entry",
				"voucher_name": "JE-1",
				"idempotency_key": "UMRE::BOOKING-1::RECEIPT::PAY-1",
			},
		)
		booking.save.assert_called_once_with()

	@patch("umre_ops.umre_ops.services.payment_service.frappe.throw", side_effect=ValueError)
	@patch("umre_ops.umre_ops.services.payment_service.frappe.get_doc")
	def test_verified_status_without_evidence_is_rejected(self, get_doc: Mock, _throw: Mock) -> None:
		row = SimpleNamespace(
			name="PAY-1",
			posting_date="2026-07-20",
			amount=100,
			date_source="Receipt",
			date_verification_status="Verified",
			date_evidence_reference=None,
			verified_by="Administrator",
			verified_on="2026-07-29 12:00:00",
			is_new=lambda: False,
		)
		booking = Mock(customer=None)
		booking.get.return_value = [row]
		get_doc.return_value = booking
		with (
			patch("umre_ops.umre_ops.services.payment_service._", side_effect=lambda message: message),
			patch(
				"umre_ops.umre_ops.doctype.umre_booking_payment.umre_booking_payment._",
				side_effect=lambda message: message,
			),
			self.assertRaises(ValueError),
		):
			post_payment_row_receipt(
				booking_name="BOOKING-1",
				payment_row_name="PAY-1",
				paid_account="Cash - C",
				dry_run=True,
			)


class TestReleaseTwoRepairPlan(TestCase):
	@patch("umre_ops.install.ensure_accounting_custom_fields")
	def test_fresh_install_ensures_accounting_custom_fields(self, ensure_fields: Mock) -> None:
		after_install()
		ensure_fields.assert_called_once_with()

	def test_custom_idempotency_key_finds_exact_posting_event(self) -> None:
		exists = Mock(side_effect=["EVENT-1"])
		with patch(
			"umre_ops.umre_ops.services.payment_date_reconciliation.frappe.db",
			SimpleNamespace(exists=exists),
		):
			self.assertTrue(
				_has_posting_event("BOOKING-1", "PAY-1", "UMRE-EXCEL::TOUR::PILGRIM")
			)
		self.assertEqual(
			exists.call_args.args[1]["idempotency_key"],
			["in", ["UMRE-EXCEL::TOUR::PILGRIM::JE", "UMRE-EXCEL::TOUR::PILGRIM::PE"]],
		)

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
