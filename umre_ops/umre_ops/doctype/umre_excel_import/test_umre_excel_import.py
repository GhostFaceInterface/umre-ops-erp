# Copyright (c) 2026, Sermed Turizm and contributors

from io import BytesIO
from types import SimpleNamespace

import frappe
from frappe.tests import IntegrationTestCase
from openpyxl import Workbook

from umre_ops.umre_ops.services.excel_import_service import (
	IMPORT_FIELDS,
	ImportSummary,
	_final_status,
	_normalize_row,
	_read_single_worksheet,
	_validated_mapping,
	attempt_can_run,
	build_validation_signature,
	header_key,
	make_source_snapshot,
	map_oda_tipi,
	normalize_cinsiyet,
	normalize_nationality,
	normalize_status,
	normalize_tc,
	safe_float,
	sanitize_phone,
	split_cities,
	validate_dry_run_snapshot,
	verify_validation_signature,
)


class FakeImport(SimpleNamespace):
	def get(self, key, default=None):
		return getattr(self, key, default)


def make_workbook(*sheet_names: str) -> bytes:
	workbook = Workbook()
	workbook.active.title = sheet_names[0]
	for sheet_name in sheet_names[1:]:
		workbook.create_sheet(sheet_name)
	buffer = BytesIO()
	workbook.save(buffer)
	workbook.close()
	return buffer.getvalue()


def make_import(**overrides):
	values = dict(
		status="Draft",
		import_file="/private/files/import.xlsx",
		target_tour="TUR-1",
		header_row=1,
		validation_signature=None,
		column_mappings=[SimpleNamespace(target_field=field, source_column=field) for field in IMPORT_FIELDS],
	)
	values.update(overrides)
	return FakeImport(**values)


class IntegrationTestUmreExcelImport(IntegrationTestCase):
	def test_header_and_business_normalizers(self) -> None:
		self.assertEqual(header_key(" tc KİMLİK "), "tc kimlik")
		self.assertEqual(normalize_tc("1234567890.0"), "01234567890")
		self.assertEqual(normalize_tc("AB 123"), "AB123")
		self.assertEqual(sanitize_phone("+90 532 111 22 33"), "+90 532 111 22 33")
		self.assertEqual(normalize_cinsiyet("mrs"), "MRS")
		self.assertEqual(normalize_nationality("TUR"), "TC")
		self.assertEqual(normalize_status("hoca eşi"), "HOCA_ESI")
		self.assertEqual(
			normalize_status("Şirket Müdürünün Çocuğu"), "SIRKET_MUDURU_COCUGU"
		)
		self.assertEqual(split_cities("istanbul-ankara"), ("İstanbul", "Ankara"))
		self.assertEqual(split_cities("İzmir"), ("İzmir", "İzmir"))

	def test_room_is_strictly_one_to_four(self) -> None:
		self.assertEqual(map_oda_tipi("3 kişi"), "3 Kişilik")
		for invalid in (None, "", "5", "oda 2", "12"):
			with self.assertRaises(frappe.ValidationError):
				map_oda_tipi(invalid)

	def test_money_parser_is_strict_and_supports_localized_values(self) -> None:
		self.assertEqual(safe_float("1.234,56"), 1234.56)
		self.assertEqual(safe_float("1,234.56"), 1234.56)
		self.assertEqual(safe_float(""), 0)
		for invalid in ("ücretsiz", "1.2.3", True):
			with self.assertRaises(frappe.ValidationError):
				safe_float(invalid)

	def test_workbook_must_have_exactly_one_physical_sheet(self) -> None:
		self.assertEqual(_read_single_worksheet(make_workbook("Tek")), [])
		with self.assertRaises(frappe.ValidationError):
			_read_single_worksheet(make_workbook("Ocak", "Şubat"))

	def test_pending_rows_keep_import_resumable(self) -> None:
		self.assertEqual(
			_final_status(
				ImportSummary(), dry_run=False, rows=[{"row_status": "Pending Referral"}]
			),
			"Partially Completed",
		)
		self.assertEqual(
			_final_status(ImportSummary(), dry_run=False, rows=[{"row_status": "Imported"}]),
			"Completed",
		)

	def test_non_paying_status_cannot_report_a_payment(self) -> None:
		row = {
			"TC KİMLİK": "12345678901",
			"AD": "Ali",
			"SOYAD": "Veli",
			"CİNSİYET": "MR",
			"UYRUK": "TC",
			"DOĞUM TARİHİ": "1990-01-01",
			"GELDİĞİ İL": "Ankara",
			"ODA SAYISI": "2",
			"TELEFON NUMARASI": "0500 000 00 00",
			"KİMDEN": "Kaynak",
			"FİYAT": "0",
			"ÖDEDİĞİ MİKTAR": "1",
			"YOLCU STATÜSÜ": "HOCA",
		}
		with self.assertRaises(frappe.ValidationError):
			_normalize_row(row, "TUR-1")

	def test_excel_price_is_preserved_without_reading_tour_tariff(self) -> None:
		row = self._valid_row()
		row["FİYAT"] = "1.234,56"
		normalized = _normalize_row(row, "TUR-WITH-DIFFERENT-TARIFF")
		self.assertEqual(normalized["ucret"], 1234.56)
		self.assertEqual(normalized["bildirilen_odenen"], 1000)
		self.assertEqual(normalized["odenen"], 0)

	def test_price_rules_follow_passenger_status(self) -> None:
		for price in ("0", "-1"):
			row = self._valid_row(**{"FİYAT": price})
			with self.assertRaises(frappe.ValidationError):
				_normalize_row(row, "TUR-1")

		for price in ("1", "-1"):
			row = self._valid_row(
				**{"FİYAT": price, "ÖDEDİĞİ MİKTAR": "0", "YOLCU STATÜSÜ": "HOCA"}
			)
			with self.assertRaises(frappe.ValidationError):
				_normalize_row(row, "TUR-1")

		row = self._valid_row(
			**{"FİYAT": "0", "ÖDEDİĞİ MİKTAR": "0", "YOLCU STATÜSÜ": "HOCA"}
		)
		self.assertEqual(_normalize_row(row, "TUR-1")["ucret"], 0)

	@staticmethod
	def _valid_row(**overrides):
		row = {
			"TC KİMLİK": "12345678901",
			"AD": "Ali",
			"SOYAD": "Veli",
			"CİNSİYET": "MR",
			"UYRUK": "TC",
			"DOĞUM TARİHİ": "1990-01-01",
			"GELDİĞİ İL": "Ankara",
			"ODA SAYISI": "2",
			"TELEFON NUMARASI": "0500 000 00 00",
			"KİMDEN": "Kaynak",
			"FİYAT": "1700",
			"ÖDEDİĞİ MİKTAR": "1000",
			"YOLCU STATÜSÜ": "UMRECI",
		}
		row.update(overrides)
		return row

	def test_mapping_is_case_insensitive_complete_and_one_to_one(self) -> None:
		doc = make_import()
		mapping = _validated_mapping(doc, [field.lower() for field in IMPORT_FIELDS])
		self.assertEqual(tuple(mapping), IMPORT_FIELDS)
		doc.column_mappings = [
			row for row in doc.column_mappings if row.target_field != "FİYAT"
		]
		with self.assertRaises(frappe.ValidationError):
			_validated_mapping(doc, list(IMPORT_FIELDS))

	def test_validation_signature_binds_content_tour_header_and_mapping(self) -> None:
		doc = make_import()
		content = make_workbook("Tek")
		initial = build_validation_signature(doc, content)
		doc.validation_signature = initial
		verify_validation_signature(doc, content)
		doc.header_row = 2
		self.assertNotEqual(initial, build_validation_signature(doc, content))
		with self.assertRaises(frappe.ValidationError):
			verify_validation_signature(doc, content)

	def test_dry_run_snapshot_rejects_source_or_status_changes(self) -> None:
		doc = make_import()
		snapshot = make_source_snapshot(doc)
		validate_dry_run_snapshot(snapshot, doc)
		changed = make_import(header_row=2)
		with self.assertRaises(frappe.ValidationError):
			validate_dry_run_snapshot(snapshot, changed)
		completed = make_import(status="Completed")
		with self.assertRaises(frappe.ValidationError):
			validate_dry_run_snapshot(snapshot, completed)

	def test_only_matching_attempt_can_run_or_recover(self) -> None:
		self.assertTrue(attempt_can_run(SimpleNamespace(status="Queued", job_id="a"), "a"))
		self.assertTrue(attempt_can_run(SimpleNamespace(status="Processing", job_id="a"), "a"))
		self.assertFalse(attempt_can_run(SimpleNamespace(status="Completed", job_id="a"), "a"))
