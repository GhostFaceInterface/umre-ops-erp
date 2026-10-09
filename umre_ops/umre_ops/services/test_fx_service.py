from datetime import date
from unittest import TestCase
from unittest.mock import patch

import frappe

from umre_ops.umre_ops.services import fx_service

ON = date(2026, 3, 1)


class TestUsdRate(TestCase):
	def test_usd_is_one(self) -> None:
		self.assertEqual(fx_service.usd_rate("USD", ON), (1.0, fx_service.SOURCE_BASE))

	def test_sar_comes_from_erpnext_peg(self) -> None:
		with patch.object(fx_service, "_pegged_rate", return_value=3.75):
			self.assertEqual(fx_service.usd_rate("sar", ON), (3.75, fx_service.SOURCE_PEGGED))

	def test_sar_peg_outside_band_is_rejected(self) -> None:
		with patch.object(fx_service, "_pegged_rate", return_value=0.2667):
			with self.assertRaises(frappe.ValidationError):
				fx_service.usd_rate("SAR", ON)

	def test_sar_falls_back_to_official_peg_offline(self) -> None:
		with (
			patch.object(fx_service, "_pegged_rate", return_value=None),
			patch.object(fx_service, "_stored_rate", return_value=None),
			patch.object(fx_service, "_fetch_rate", side_effect=ConnectionError),
		):
			self.assertEqual(fx_service.usd_rate("SAR", ON)[0], 3.75)

	def test_try_prefers_stored_currency_exchange(self) -> None:
		with (
			patch.object(fx_service, "_pegged_rate", return_value=None),
			patch.object(fx_service, "_stored_rate", return_value=41.2),
			patch.object(fx_service, "_fetch_rate") as fetch,
		):
			self.assertEqual(fx_service.usd_rate("TRY", ON), (41.2, fx_service.SOURCE_STORED))
			fetch.assert_not_called()

	def test_try_fetched_rate_is_stored(self) -> None:
		with (
			patch.object(fx_service, "_pegged_rate", return_value=None),
			patch.object(fx_service, "_stored_rate", return_value=None),
			patch.object(fx_service, "_fetch_rate", return_value=41.2),
			patch.object(fx_service, "_store_rate") as store,
		):
			self.assertEqual(fx_service.usd_rate("TRY", ON), (41.2, fx_service.SOURCE_FETCHED))
			store.assert_called_once_with("TRY", ON, 41.2)

	def test_missing_try_rate_raises(self) -> None:
		with (
			patch.object(fx_service, "_pegged_rate", return_value=None),
			patch.object(fx_service, "_stored_rate", return_value=None),
			patch.object(fx_service, "_fetch_rate", return_value=None),
		):
			with self.assertRaises(frappe.ValidationError):
				fx_service.usd_rate("TRY", ON)


class TestValidateRate(TestCase):
	def _reference(self, rate: float):
		return patch.object(fx_service, "usd_rate", return_value=(rate, fx_service.SOURCE_STORED))

	def test_inverted_try_rate_is_rejected(self) -> None:
		with self._reference(41.2):
			with self.assertRaises(frappe.ValidationError):
				fx_service.validate_rate("TRY", 0.024, ON)

	def test_rate_of_one_for_try_is_rejected(self) -> None:
		with self._reference(41.2):
			with self.assertRaises(frappe.ValidationError):
				fx_service.validate_rate("TRY", 1, ON)

	def test_close_manual_rate_is_accepted(self) -> None:
		with self._reference(41.2):
			self.assertEqual(fx_service.validate_rate("TRY", 40.5, ON), fx_service.SOURCE_MANUAL)

	def test_sar_contract_rate_must_stay_in_band(self) -> None:
		with self._reference(3.75):
			self.assertEqual(fx_service.validate_rate("SAR", 3.76, ON), fx_service.SOURCE_MANUAL)
			with self.assertRaises(frappe.ValidationError):
				fx_service.validate_rate("SAR", 0.2667, ON)

	def test_manual_rate_without_reference_is_kept(self) -> None:
		with patch.object(fx_service, "usd_rate", side_effect=frappe.ValidationError):
			self.assertEqual(fx_service.validate_rate("TRY", 40.0, ON), fx_service.SOURCE_MANUAL)
