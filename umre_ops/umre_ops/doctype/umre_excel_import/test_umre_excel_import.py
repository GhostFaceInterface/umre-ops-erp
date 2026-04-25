# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from frappe.tests import IntegrationTestCase

from umre_ops.umre_ops.services.excel_import_service import (
	_alias_lookup,
	header_key,
	map_oda_tipi,
	normalize_city,
	normalize_tc,
	sanitize_phone,
)


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
