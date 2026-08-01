import json
from copy import deepcopy
from decimal import Decimal
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import frappe

from umre_ops.patches.restore_july_2026_excel_prices import (
	EXPECTED_META,
	ROOM_FIELDS,
	TOUR_NAME,
	_tc_hash,
	build_update_plan,
	execute,
	load_and_validate_manifest,
)


class TestRestoreJuly2026ExcelPrices(TestCase):
	def setUp(self):
		_, self.truth = load_and_validate_manifest()
		self.tour = {
			"name": TOUR_NAME,
			"tur_adi": TOUR_NAME,
			"tur_kodu": EXPECTED_META["tour_code"],
			"baslangic_tarihi": EXPECTED_META["start_date"],
			"para_birimi": EXPECTED_META["currency"],
			"bir_kisilik_oda": 1700,
			"iki_kisilik_oda": 1700,
			"uc_kisilik_oda": 1600,
			"dort_kisilik_oda": 1500,
		}
		self.bookings = []
		for index, (tc_hash, row) in enumerate(list(self.truth.items())):
			status = "UMRECI" if row["price"] > 0 else "HOCA"
			self.bookings.append(
				{
					"name": f"BOOK-{index:03d}",
					"tc_kimlik": f"TC-{index:03d}",
					"statu": status,
					"oda_tipi": f"{row['room_size']} Kişilik",
					"ucret": row["price"],
					"bildirilen_odenen": row["reported_paid"],
					"is_imported": 1,
					"locked_financials": 1,
				}
			)
			# Tests use synthetic identifiers while preserving the audited truth rows.
			self.truth[_tc_hash(f"TC-{index:03d}")] = self.truth.pop(tc_hash)

	def test_manifest_hash_counts_and_financial_invariants(self):
		manifest, truth = load_and_validate_manifest()
		self.assertEqual(manifest["rows_sha256"], EXPECTED_META["rows_sha256"])
		self.assertEqual(len(truth), 63)
		self.assertEqual(sum(row["price"] > 0 for row in truth.values()), 58)

	def test_manifest_rejects_tampered_rows_and_subcent_values(self):
		manifest, _ = load_and_validate_manifest()
		for value in (1501, "1500.001"):
			tampered = deepcopy(manifest)
			tampered["rows"][0]["price"] = value
			with TemporaryDirectory() as directory:
				path = Path(directory) / "manifest.json"
				path.write_text(json.dumps(tampered), encoding="utf-8")
				with self.assertRaises(frappe.ValidationError):
					load_and_validate_manifest(path)

	def test_preflight_failure_produces_no_writes(self):
		bad = deepcopy(self.bookings)
		bad[-1]["ucret"] = 123456
		with self.assertRaises(frappe.ValidationError):
			build_update_plan(self.truth, self.tour, bad)

	def test_success_updates_only_tariff_mismatches_and_rerun_is_noop(self):
		bookings = deepcopy(self.bookings)
		changed = next(
			row
			for row in bookings
			if self.truth[_tc_hash(row["tc_kimlik"])]["price"] > 0
			and self.truth[_tc_hash(row["tc_kimlik"])]["price"]
			!= self.tour[ROOM_FIELDS[self.truth[_tc_hash(row["tc_kimlik"])]["room_size"]]]
		)
		truth = self.truth[_tc_hash(changed["tc_kimlik"])]
		changed["ucret"] = self.tour[ROOM_FIELDS[truth["room_size"]]]
		plan = build_update_plan(self.truth, self.tour, bookings)
		self.assertEqual(
			plan,
			[(changed["name"], Decimal(str(changed["ucret"])), truth["price"])],
		)
		changed["ucret"] = truth["price"]
		self.assertEqual(build_update_plan(self.truth, self.tour, bookings), [])

	def test_execute_finishes_preflight_before_first_write(self):
		bad = deepcopy(self.bookings)
		bad[-1]["locked_financials"] = 0
		with (
			patch(
				"umre_ops.patches.restore_july_2026_excel_prices.load_and_validate_manifest",
				return_value=({}, self.truth),
			),
			patch("umre_ops.patches.restore_july_2026_excel_prices.frappe") as frappe_mock,
		):
			frappe_mock.db.get_value.return_value = self.tour
			frappe_mock.db.sql.return_value = bad
			frappe_mock.ValidationError = frappe.ValidationError
			with self.assertRaises(frappe.ValidationError):
				execute()
		frappe_mock.db.set_value.assert_not_called()

	def test_execute_writes_only_the_audited_ucret_field(self):
		bookings = deepcopy(self.bookings)
		changed = next(
			row
			for row in bookings
			if self.truth[_tc_hash(row["tc_kimlik"])]["price"] > 0
			and self.truth[_tc_hash(row["tc_kimlik"])]["price"]
			!= self.tour[ROOM_FIELDS[self.truth[_tc_hash(row["tc_kimlik"])]["room_size"]]]
		)
		truth = self.truth[_tc_hash(changed["tc_kimlik"])]
		changed["ucret"] = self.tour[ROOM_FIELDS[truth["room_size"]]]
		with (
			patch(
				"umre_ops.patches.restore_july_2026_excel_prices.load_and_validate_manifest",
				return_value=({}, self.truth),
			),
			patch("umre_ops.patches.restore_july_2026_excel_prices.frappe") as frappe_mock,
		):
			frappe_mock.db.get_value.return_value = self.tour
			frappe_mock.db.sql.return_value = bookings
			execute()
		frappe_mock.db.set_value.assert_called_once_with(
			"Umre Booking",
			changed["name"],
			"ucret",
			truth["price"],
			update_modified=False,
		)

	def test_execute_skips_a_clean_site_without_the_historical_tour(self):
		with patch("umre_ops.patches.restore_july_2026_excel_prices.frappe") as frappe_mock:
			frappe_mock.db.get_value.return_value = None
			frappe_mock.db.count.return_value = 0
			execute()
		frappe_mock.db.sql.assert_not_called()
		frappe_mock.db.set_value.assert_not_called()
