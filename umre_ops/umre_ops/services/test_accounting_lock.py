# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from unittest import TestCase
from unittest.mock import Mock, patch

from umre_ops.umre_ops.services.accounting_service import _lock_booking_for_posting


class TestAccountingBookingLock(TestCase):
	@patch("umre_ops.umre_ops.services.accounting_service.frappe", new_callable=Mock)
	def test_real_posting_locks_booking_row(self, frappe_mock: Mock) -> None:
		frappe_mock.db.sql.return_value = [("BOOKING-1",)]

		_lock_booking_for_posting("BOOKING-1", dry_run=False)

		query = frappe_mock.db.sql.call_args.args[0]
		self.assertIn("FOR UPDATE", query)
		self.assertEqual(frappe_mock.db.sql.call_args.args[1], ("BOOKING-1",))

	@patch("umre_ops.umre_ops.services.accounting_service.frappe", new_callable=Mock)
	def test_dry_run_does_not_lock_booking_row(self, frappe_mock: Mock) -> None:
		_lock_booking_for_posting("BOOKING-1", dry_run=True)

		frappe_mock.db.sql.assert_not_called()
