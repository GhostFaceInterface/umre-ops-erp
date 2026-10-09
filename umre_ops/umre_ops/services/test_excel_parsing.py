from types import SimpleNamespace
from unittest import TestCase

import frappe

from umre_ops.umre_ops.services import excel_import_service as svc


class FakeUmreci(dict):
	def set(self, key, value) -> None:
		self[key] = value


def valid_row(**overrides) -> dict:
	row = {
		"TC KİMLİK": "12345678901",
		"AD": "Ali",
		"SOYAD": "Veli",
		"CİNSİYET": "MR",
		"UYRUK": "TC",
		"DOĞUM TARİHİ": "1980-04-03",
		"GELDİĞİ İL": "Ankara",
		"ODA SAYISI": "2",
		"TELEFON NUMARASI": "0500 000 00 00",
		"KİMDEN": "Kaynak",
		"FİYAT": "1300",
		"ÖDEDİĞİ MİKTAR": "1000",
		"YOLCU STATÜSÜ": "UMRECI",
	}
	row.update(overrides)
	return row


class TestSafeFloat(TestCase):
	def test_thousands_separators(self) -> None:
		for text, expected in (
			("1.500", 1500.0),
			("1,500", 1500.0),
			("12.000", 12000.0),
			("1.234,56", 1234.56),
			("1,234.56", 1234.56),
			("1 500", 1500.0),
		):
			self.assertEqual(svc.safe_float(text), expected, text)

	def test_decimal_marks(self) -> None:
		for text, expected in (("1,5", 1.5), ("12,50", 12.5), ("12.50", 12.5), ("0.500", 0.5), ("1500", 1500.0)):
			self.assertEqual(svc.safe_float(text), expected, text)

	def test_numeric_cells_and_blank(self) -> None:
		self.assertEqual(svc.safe_float(1500.0), 1500.0)
		self.assertEqual(svc.safe_float(""), 0)

	def test_numeric_cells_are_never_reparsed_as_text(self) -> None:
		self.assertEqual(svc.safe_float(333.333), 333.333)
		self.assertEqual(svc.safe_float(12.375), 12.375)
		self.assertEqual(svc.safe_float(1300), 1300.0)

	def test_invalid_values(self) -> None:
		for invalid in ("ücretsiz", "1.2.3", True):
			with self.assertRaises(frappe.ValidationError):
				svc.safe_float(invalid)


class TestParseDate(TestCase):
	def test_text_dates_are_day_first(self) -> None:
		self.assertEqual(svc.parse_date("03.04.1980"), "1980-04-03")
		self.assertEqual(svc.parse_date("03/04/1980"), "1980-04-03")

	def test_iso_dates_are_not_swapped(self) -> None:
		self.assertEqual(svc.parse_date("1990-01-02"), "1990-01-02")
		self.assertEqual(svc.parse_date("1990-01-02 00:00:00"), "1990-01-02")

	def test_birth_date_must_be_plausible(self) -> None:
		with self.assertRaises(frappe.ValidationError):
			svc._normalize_row(valid_row(**{"DOĞUM TARİHİ": "1890-01-01"}), "TUR-1")


class TestCommission(TestCase):
	def test_kms_is_optional(self) -> None:
		self.assertEqual(svc._normalize_row(valid_row(), "TUR-1")["kms"], 0)

	def test_kms_is_read(self) -> None:
		self.assertEqual(svc._normalize_row(valid_row(KMS="50"), "TUR-1")["kms"], 50.0)

	def test_kms_rules(self) -> None:
		for overrides in (
			{"KMS": "-1"},
			{"KMS": "1400"},
			{"KMS": "50", "FİYAT": "0", "ÖDEDİĞİ MİKTAR": "0", "YOLCU STATÜSÜ": "HOCA"},
		):
			with self.assertRaises(frappe.ValidationError):
				svc._normalize_row(valid_row(**overrides), "TUR-1")

	def test_row_key_unchanged_without_kms(self) -> None:
		normalized = svc._normalize_row(valid_row(), "TUR-1")
		legacy = dict(normalized)
		legacy.pop("kms")
		self.assertEqual(svc._row_key("TUR-1", normalized), svc._row_key("TUR-1", legacy))

	def test_kms_column_mapping_is_optional(self) -> None:
		headers = list(svc.IMPORT_FIELDS)
		doc = SimpleNamespace(
			get=lambda key, default=None: [
				SimpleNamespace(target_field=f, source_column=f) for f in svc.IMPORT_FIELDS
			]
		)
		self.assertNotIn("KMS", svc._validated_mapping(doc, headers))
		doc_with_kms = SimpleNamespace(
			get=lambda key, default=None: [
				SimpleNamespace(target_field=f, source_column=f) for f in svc.ALL_IMPORT_FIELDS
			]
		)
		self.assertEqual(svc._validated_mapping(doc_with_kms, [*headers, "KMS"])["KMS"], "KMS")


class TestIdentity(TestCase):
	def test_same_person_has_no_conflict(self) -> None:
		normalized = svc._normalize_row(valid_row(), "TUR-1")
		umreci = {"ad": "ALİ", "soyad": "veli", "dogum_tarihi": "1980-04-03"}
		self.assertIsNone(svc._identity_conflict(umreci, normalized))

	def test_different_person_with_same_tc_is_a_conflict(self) -> None:
		normalized = svc._normalize_row(valid_row(), "TUR-1")
		umreci = {"ad": "Ayşe", "soyad": "Veli", "dogum_tarihi": "1975-01-01"}
		self.assertIn("AD", svc._identity_conflict(umreci, normalized))

	def test_month_first_legacy_birth_date_is_not_a_conflict(self) -> None:
		normalized = svc._normalize_row(valid_row(**{"DOĞUM TARİHİ": "03.04.1980"}), "TUR-1")
		legacy = {"ad": "Ali", "soyad": "Veli", "dogum_tarihi": "1980-03-04"}
		self.assertIsNone(svc._identity_conflict(legacy, normalized))
		other = {"ad": "Ali", "soyad": "Veli", "dogum_tarihi": "1980-05-04"}
		self.assertIn("DOĞUM TARİHİ", svc._identity_conflict(other, normalized))

	def test_empty_phone_does_not_clear_stored_phone(self) -> None:
		normalized = svc._normalize_row(valid_row(**{"TELEFON NUMARASI": ""}), "TUR-1")
		umreci = FakeUmreci(
			tc_kimlik="12345678901", ad="Ali", soyad="Veli", cinsiyet="MR", uyruk="TC",
			dogum_tarihi="1980-04-03", telefon_numarasi="0500 111 11 11",
		)
		self.assertTrue(svc._umreci_matches(umreci, normalized))
		svc._apply_umreci_fields(umreci, normalized)
		self.assertEqual(umreci.get("telefon_numarasi"), "0500 111 11 11")


class TestPreflightWarnings(TestCase):
	def test_missing_rule_and_price_warnings(self) -> None:
		normalized = {"statu": "UMRECI", "ucret": 13}
		text = svc._preflight_warnings(
			normalized, [{"code": "MISSING_RULE", "cost_type": "FLIGHT", "detail": "Çocuk"}]
		)
		self.assertIn("FLIGHT (Çocuk): kural yok", text)
		self.assertIn("FİYAT", text)

	def test_no_warning_for_clean_row(self) -> None:
		self.assertIsNone(svc._preflight_warnings({"statu": "UMRECI", "ucret": 1300}, []))
