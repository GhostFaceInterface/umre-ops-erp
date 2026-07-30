# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from io import BytesIO
from types import SimpleNamespace

import frappe
from frappe.tests import IntegrationTestCase
from openpyxl import Workbook

from umre_ops.umre_ops.services.excel_import_service import (
	_alias_lookup,
	_read_selected_worksheet,
	_worksheet_names_from_content,
	attempt_can_run,
	build_validation_signature,
	header_key,
	make_source_snapshot,
	map_oda_tipi,
	normalize_city,
	normalize_tc,
	sanitize_phone,
	validate_dry_run_snapshot,
	verify_validation_signature,
)


def make_workbook(*sheet_names: str) -> bytes:
	workbook = Workbook()
	workbook.active.title = sheet_names[0]
	for sheet_name in sheet_names[1:]:
		workbook.create_sheet(sheet_name)
	buffer = BytesIO()
	workbook.save(buffer)
	workbook.close()
	return buffer.getvalue()


class IntegrationTestUmreExcelImport(IntegrationTestCase):
	def test_column_aliases_are_order_independent(self) -> None:
		lookup = _alias_lookup()
		headers = ["Telefon Numarası", "TC Kimlik No", "Referans", "İç Hat Bağlantı", "Oda Tipi"]

		mapped = [lookup[header_key(header)] for header in headers]

		self.assertEqual(
			mapped,
			["TELEFON NO", "TC KİMLİK NO", "KİMDEN", "İÇ HAT BAĞLANTI", "ODA SAYISI"],
		)

	def test_script_normalizers_are_preserved(self) -> None:
		self.assertEqual(normalize_tc("1234567890.0"), "01234567890")
		self.assertEqual(sanitize_phone("532 111 22 33"), "05321112233")
		self.assertEqual(normalize_city("istanbul"), "İstanbul")
		self.assertEqual(map_oda_tipi("3"), "3 Kişilik")

	def test_worksheet_names_and_selected_sheet_are_explicit(self) -> None:
		content = make_workbook("Ocak", "Şubat")

		self.assertEqual(_worksheet_names_from_content(content), ["Ocak", "Şubat"])
		self.assertEqual(_read_selected_worksheet(content, "Şubat"), [])
		with self.assertRaises(frappe.ValidationError):
			_read_selected_worksheet(content, None)
		with self.assertRaises(frappe.ValidationError):
			_read_selected_worksheet(content, "Mart")

	def test_single_worksheet_can_be_read_without_a_selection(self) -> None:
		content = make_workbook("Tek Sayfa")

		self.assertEqual(_read_selected_worksheet(content, None), [])

	def test_validation_signature_binds_content_tour_and_worksheet(self) -> None:
		doc = SimpleNamespace(target_tour="TUR-1", worksheet_name="Ocak", validation_signature=None)
		content = make_workbook("Ocak", "Şubat")
		initial = build_validation_signature(doc, content)
		doc.validation_signature = initial
		verify_validation_signature(doc, content)

		doc.worksheet_name = "Şubat"
		self.assertNotEqual(initial, build_validation_signature(doc, content))
		with self.assertRaises(frappe.ValidationError):
			verify_validation_signature(doc, content)
		doc.worksheet_name = "Ocak"
		doc.target_tour = "TUR-2"
		self.assertNotEqual(initial, build_validation_signature(doc, content))
		self.assertNotEqual(
			initial,
			build_validation_signature(
				SimpleNamespace(target_tour="TUR-1", worksheet_name="Ocak"), content + b"changed"
			),
		)

	def test_dry_run_snapshot_rejects_source_or_status_changes(self) -> None:
		initial_doc = SimpleNamespace(
			status="Draft",
			import_file="/private/files/import.xlsx",
			target_tour="TUR-1",
			worksheet_name="Ocak",
		)
		snapshot = make_source_snapshot(initial_doc)
		validate_dry_run_snapshot(snapshot, initial_doc)

		changed_sheet = SimpleNamespace(**vars(initial_doc))
		changed_sheet.worksheet_name = "Şubat"
		with self.assertRaises(frappe.ValidationError):
			validate_dry_run_snapshot(snapshot, changed_sheet)

		completed = SimpleNamespace(**vars(initial_doc))
		completed.status = "Completed"
		with self.assertRaises(frappe.ValidationError):
			validate_dry_run_snapshot(snapshot, completed)

	def test_only_matching_attempt_can_run_or_recover(self) -> None:
		self.assertTrue(attempt_can_run(SimpleNamespace(status="Queued", job_id="attempt-1"), "attempt-1"))
		self.assertTrue(
			attempt_can_run(SimpleNamespace(status="Processing", job_id="attempt-1"), "attempt-1")
		)
		self.assertFalse(
			attempt_can_run(SimpleNamespace(status="Processing", job_id="attempt-2"), "attempt-1")
		)
		self.assertFalse(
			attempt_can_run(SimpleNamespace(status="Completed", job_id="attempt-1"), "attempt-1")
		)
