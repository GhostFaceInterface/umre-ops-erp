# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch

from umre_ops.umre_ops.services.accounting_service import (
	PostResult,
	_get_valid_existing_result,
	_require_posting_date,
	post_booking_receipt_journal_entry,
)
from umre_ops.umre_ops.services.excel_import_service import _booking_payload, _upsert_payment_row
from umre_ops.umre_ops.services.idempotency_service import IdempotencyResult, sha256_hex, stable_json_dumps
from umre_ops.umre_ops.services.payment_service import add_payment_row, post_payment_row_receipt


class TestReleaseOnePaymentSafety(TestCase):
	@patch("umre_ops.umre_ops.services.payment_service.frappe.throw", side_effect=ValueError)
	@patch("umre_ops.umre_ops.services.payment_service.frappe.get_doc")
	def test_add_payment_requires_explicit_date(self, get_doc: Mock, _throw: Mock) -> None:
		booking = Mock()
		get_doc.return_value = booking

		with (
			patch("umre_ops.umre_ops.services.payment_service._", side_effect=lambda message: message),
			self.assertRaises(ValueError),
		):
			add_payment_row(booking_name="BOOKING-1", amount=100, posting_date=None)

		booking.save.assert_not_called()

	@patch("umre_ops.umre_ops.services.payment_service.frappe.throw", side_effect=ValueError)
	@patch("umre_ops.umre_ops.services.payment_service.frappe.get_doc")
	def test_add_payment_rejects_negative_amount(self, get_doc: Mock, _throw: Mock) -> None:
		booking = Mock()
		get_doc.return_value = booking

		with (
			patch("umre_ops.umre_ops.services.payment_service._", side_effect=lambda message: message),
			self.assertRaises(ValueError),
		):
			add_payment_row(booking_name="BOOKING-1", amount=-1, posting_date="2026-07-29")

		booking.save.assert_not_called()

	@patch("umre_ops.umre_ops.services.payment_service.post_booking_receipt_journal_entry")
	@patch("umre_ops.umre_ops.services.payment_service.frappe.get_doc")
	def test_payment_dry_run_does_not_save_booking(self, get_doc: Mock, post_receipt: Mock) -> None:
		row = SimpleNamespace(
			name="PAY-1",
			idempotency_key=None,
			posting_date="2026-07-29",
			amount=100,
			date_verification_status="Verified",
			date_source="Receipt",
			date_evidence_reference="RECEIPT-1",
			verified_by="Administrator",
			verified_on="2026-07-29 12:00:00",
			posting_status="Draft",
			payment_entry=None,
			journal_entry=None,
			is_new=lambda: False,
			currency="USD",
			mode_of_payment="Cash",
			reference_no=None,
			external_reference=None,
			reference_date=None,
			remarks=None,
			as_dict=lambda: {"name": "PAY-1"},
		)
		booking = Mock()
		booking.customer = None
		booking.get.return_value = [row]
		get_doc.return_value = booking
		post_receipt.return_value = PostResult("Journal Entry", "DRY-RUN", "KEY::JE")

		result = post_payment_row_receipt(
			booking_name="BOOKING-1",
			payment_row_name="PAY-1",
			paid_account="Cash - C",
			dry_run=True,
		)

		self.assertEqual(result["result_name"], "DRY-RUN")
		self.assertIsNone(row.idempotency_key)
		booking.save.assert_not_called()


class TestReleaseOneAccountingSafety(TestCase):
	@patch("umre_ops.umre_ops.services.accounting_service.frappe.throw", side_effect=ValueError)
	@patch("umre_ops.umre_ops.services.accounting_service._", side_effect=lambda message: message)
	def test_posting_date_is_required(self, _translate: Mock, _throw: Mock) -> None:
		with self.assertRaises(ValueError):
			_require_posting_date(None)

	@patch("umre_ops.umre_ops.services.accounting_service.frappe.throw", side_effect=ValueError)
	@patch("umre_ops.umre_ops.services.accounting_service._", side_effect=lambda message: message)
	@patch("umre_ops.umre_ops.services.accounting_service.get_existing_result")
	def test_idempotency_payload_mismatch_is_rejected(
		self,
		get_existing: Mock,
		_translate: Mock,
		_throw: Mock,
	) -> None:
		get_existing.return_value = IdempotencyResult("EVENT-1", "Succeeded", "Journal Entry", "JE-1", "wrong")
		with self.assertRaises(ValueError):
			_get_valid_existing_result("KEY-1", {"amount": 100})

	@patch("umre_ops.umre_ops.services.accounting_service.frappe.throw", side_effect=ValueError)
	@patch("umre_ops.umre_ops.services.accounting_service._", side_effect=lambda message: message)
	@patch("umre_ops.umre_ops.services.accounting_service.get_existing_result")
	def test_cancelled_idempotent_voucher_is_not_reused(
		self,
		get_existing: Mock,
		_translate: Mock,
		_throw: Mock,
	) -> None:
		payload = {"amount": 100}
		get_existing.return_value = IdempotencyResult(
			"EVENT-1",
			"Succeeded",
			"Journal Entry",
			"JE-1",
			sha256_hex(stable_json_dumps(payload)),
		)
		with (
			patch(
				"umre_ops.umre_ops.services.accounting_service.frappe.db",
				SimpleNamespace(get_value=lambda *_args, **_kwargs: 2),
			),
			self.assertRaises(ValueError),
		):
			_get_valid_existing_result("KEY-1", payload)

	@patch("umre_ops.umre_ops.services.accounting_service.ensure_event_started")
	@patch("umre_ops.umre_ops.services.accounting_service.get_existing_result", return_value=None)
	@patch("umre_ops.umre_ops.services.accounting_service.resolve_booking_cost_center", return_value="CC - C")
	@patch("umre_ops.umre_ops.services.accounting_service.get_account_mapping")
	@patch("umre_ops.umre_ops.services.accounting_service.frappe.get_doc")
	def test_dry_run_does_not_create_posting_event(
		self,
		get_doc: Mock,
		get_mapping: Mock,
		_resolve_cost_center: Mock,
		_get_existing: Mock,
		ensure_event: Mock,
	) -> None:
		get_doc.return_value = SimpleNamespace(company="Company", check_permission=lambda _ptype: None)
		get_mapping.return_value = SimpleNamespace(company="Company", income_account="Income - C")

		result = post_booking_receipt_journal_entry(
			booking_name="BOOKING-1",
			amount=100,
			paid_account="Cash - C",
			idempotency_key="KEY-1",
			posting_date="2026-07-29",
			dry_run=True,
		)

		self.assertEqual(result.name, "DRY-RUN")
		ensure_event.assert_not_called()

	@patch("umre_ops.umre_ops.services.accounting_service.ensure_event_started")
	@patch("umre_ops.umre_ops.services.accounting_service.get_existing_result", return_value=None)
	@patch("umre_ops.umre_ops.services.accounting_service.resolve_booking_cost_center", return_value="CC - C")
	@patch("umre_ops.umre_ops.services.accounting_service.get_account_mapping")
	@patch("umre_ops.umre_ops.services.accounting_service.frappe.throw", side_effect=ValueError)
	@patch("umre_ops.umre_ops.services.accounting_service.frappe.get_doc")
	def test_disabled_flag_rejects_real_posting(
		self,
		get_doc: Mock,
		_throw: Mock,
		get_mapping: Mock,
		_resolve_cost_center: Mock,
		_get_existing: Mock,
		ensure_event: Mock,
	) -> None:
		get_doc.return_value = SimpleNamespace(company="Company", check_permission=lambda _ptype: None)
		get_mapping.return_value = SimpleNamespace(company="Company", income_account="Income - C")
		with (
			patch(
				"umre_ops.umre_ops.services.accounting_service.frappe.db",
				SimpleNamespace(get_single_value=lambda *_args, **_kwargs: 0),
			),
			patch("umre_ops.umre_ops.services.accounting_service._", side_effect=lambda message: message),
		):
			with self.assertRaises(ValueError):
				post_booking_receipt_journal_entry(
					booking_name="BOOKING-1",
					amount=100,
					paid_account="Cash - C",
					idempotency_key="KEY-1",
					posting_date="2026-07-29",
					dry_run=False,
				)

		ensure_event.assert_not_called()


class TestReleaseOneExcelDateSafety(TestCase):
	@patch("umre_ops.umre_ops.services.excel_import_service._get_or_create_referral", return_value=None)
	def test_booking_dates_do_not_come_from_birth_date(self, _referral: Mock) -> None:
		row = {
			"DOĞUM TARİHİ": "1980-01-01",
			"KAYIT TARİHİ": "2026-07-20",
			"ODA SAYISI": "2",
			"İÇ HAT BAĞLANTI": "İstanbul",
			"KİMDEN": "",
			"ÖDENEN": 100,
			"KMS": 0,
			"ÜCRET": 100,
			"AÇIKLAMA": "",
		}

		payload = _booking_payload(row, "UMRECI-1", "TOUR-1", dry_run=True)

		self.assertEqual(payload["kayit_tarihi"], "2026-07-20")
		self.assertNotIn("odenen", payload)

	@patch("umre_ops.umre_ops.services.excel_import_service.frappe.throw", side_effect=ValueError)
	@patch("umre_ops.umre_ops.services.excel_import_service._", side_effect=lambda message: message)
	def test_missing_payment_date_rejects_before_existing_payment_changes(self, _translate: Mock, _throw: Mock) -> None:
		payment = SimpleNamespace(
			idempotency_key="UMRE-EXCEL::TOUR-1::UMRECI-1",
			amount=25,
			posting_date="2026-01-01",
			posting_status="Draft",
			payment_entry=None,
			journal_entry=None,
		)
		booking = SimpleNamespace(
			tur="TOUR-1",
			umreci="UMRECI-1",
			get=lambda _field: [payment],
		)

		with self.assertRaises(ValueError):
			_upsert_payment_row(
				booking,
				{"ÖDENEN": 100, "ÖDEME TARİHİ": None},
				"IMPORT-1",
				2,
			)

		self.assertEqual(payment.amount, 25)
		self.assertEqual(payment.posting_date, "2026-01-01")

	@patch("umre_ops.umre_ops.services.excel_import_service.frappe.throw", side_effect=ValueError)
	@patch("umre_ops.umre_ops.services.excel_import_service._", side_effect=lambda message: message)
	def test_posted_payment_cannot_be_changed_by_import(self, _translate: Mock, _throw: Mock) -> None:
		payment = SimpleNamespace(
			idempotency_key="UMRE-EXCEL::TOUR-1::UMRECI-1",
			amount=25,
			posting_date="2026-01-01",
			posting_status="Posted",
			payment_entry="ACC-PAY-1",
			journal_entry=None,
		)
		booking = SimpleNamespace(tur="TOUR-1", umreci="UMRECI-1", get=lambda _field: [payment])

		with self.assertRaises(ValueError):
			_upsert_payment_row(
				booking,
				{"ÖDENEN": 100, "ÖDEME TARİHİ": "2026-07-29"},
				"IMPORT-1",
				2,
			)

		self.assertEqual(payment.amount, 25)
		self.assertEqual(payment.posting_date, "2026-01-01")
