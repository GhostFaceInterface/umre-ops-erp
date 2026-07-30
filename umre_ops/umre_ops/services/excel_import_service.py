# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date, datetime
from io import BytesIO
from typing import Any
from uuid import uuid4

import frappe
from frappe import _
from frappe.utils import flt, getdate, now
from frappe.utils.background_jobs import is_job_enqueued
from openpyxl import load_workbook

DOCTYPE_IMPORT = "Umre Excel Import"
DOCTYPE_UMRECI = "Umreci"
DOCTYPE_BOOKING = "Umre Booking"
RETRYABLE_IMPORT_ERRORS = (frappe.db.InternalError, frappe.RetryBackgroundJobError)
DOCTYPE_REFERRAL = "Referral Source"

REQUIRED_COLUMNS = (
	"ADI",
	"SOYADI",
	"TC KİMLİK NO",
	"DOĞUM TARİHİ",
	"KAYIT TARİHİ",
	"İÇ HAT BAĞLANTI",
	"TELEFON NO",
	"ODA SAYISI",
	"KİMDEN",
	"UYRUK",
	"ÜCRET",
	"ÖDENEN",
	"KMS",
)

OPTIONAL_COLUMNS = (
	"ÖDEME TARİHİ",
	"CİNSİYET",
	"PASAPORT NO",
	"MALİYET",
	"AÇIKLAMA",
)

COLUMN_ALIASES = {
	"ADI": ("AD", "ADI"),
	"SOYADI": ("SOYAD", "SOYADI"),
	"TC KİMLİK NO": ("TC", "TC KİMLİK NO", "TC KIMLIK NO"),
	"DOĞUM TARİHİ": ("DOĞUM TARİHİ", "DOGUM TARIHI", "DOĞUM TARIHI"),
	"KAYIT TARİHİ": ("KAYIT TARİHİ", "KAYIT TARIHI", "REGISTRATION DATE"),
	"ÖDEME TARİHİ": (
		"ÖDEME TARİHİ",
		"ÖDEME TARIHI",
		"ODEME TARIHI",
		"TAHSİLAT TARİHİ",
		"TAHSILAT TARIHI",
		"PAYMENT DATE",
	),
	"İÇ HAT BAĞLANTI": ("GELDİĞİ İL", "GELDIGI IL", "İÇ HAT BAĞLANTI", "IC HAT BAGLANTI"),
	"TELEFON NO": ("TELEFON", "TELEFON NO", "TELEFON NUMARASI"),
	"ODA SAYISI": ("ODA", "ODA SAYISI", "ODA TİPİ", "ODA TIPI"),
	"KİMDEN": ("KİMDEN", "KIMDEN", "REFERANS", "KAYNAK"),
	"UYRUK": ("UYRUK", "UYRUĞU", "UYRUGU"),
	"ÜCRET": ("ÜCRET", "UCRET", "FİYAT", "FIYAT"),
	"ÖDENEN": ("ÖDENEN", "ODENEN", "ÖDEDİĞİ MİKTAR", "ODEDIGI MIKTAR"),
	"KMS": ("KMS",),
	"CİNSİYET": ("CİNSİYET", "CINSIYET", "CİNS", "CINS"),
	"PASAPORT NO": ("PASAPORT NO", "PASAPORT", "PASSPORT NO", "PASSPORT"),
	"MALİYET": ("MALİYET", "MALIYET"),
	"AÇIKLAMA": ("AÇIKLAMA", "ACIKLAMA", "NOT", "NOTLAR"),
}

TURKISH_PROVINCES = (
	"Adana",
	"Adıyaman",
	"Afyonkarahisar",
	"Ağrı",
	"Aksaray",
	"Amasya",
	"Ankara",
	"Antalya",
	"Ardahan",
	"Artvin",
	"Aydın",
	"Balıkesir",
	"Bartın",
	"Batman",
	"Bayburt",
	"Bilecik",
	"Bingöl",
	"Bitlis",
	"Bolu",
	"Burdur",
	"Bursa",
	"Çanakkale",
	"Çankırı",
	"Çorum",
	"Denizli",
	"Diyarbakır",
	"Düzce",
	"Edirne",
	"Elazığ",
	"Erzincan",
	"Erzurum",
	"Eskişehir",
	"Gaziantep",
	"Giresun",
	"Gümüşhane",
	"Hakkari",
	"Hatay",
	"Iğdır",
	"Isparta",
	"İstanbul",
	"İzmir",
	"Kahramanmaraş",
	"Karabük",
	"Karaman",
	"Kars",
	"Kastamonu",
	"Kayseri",
	"Kırıkkale",
	"Kırklareli",
	"Kırşehir",
	"Kilis",
	"Kocaeli",
	"Konya",
	"Kütahya",
	"Malatya",
	"Manisa",
	"Mardin",
	"Mersin",
	"Muğla",
	"Muş",
	"Nevşehir",
	"Niğde",
	"Ordu",
	"Osmaniye",
	"Rize",
	"Sakarya",
	"Samsun",
	"Siirt",
	"Sinop",
	"Sivas",
	"Şanlıurfa",
	"Şırnak",
	"Tekirdağ",
	"Tokat",
	"Trabzon",
	"Tunceli",
	"Uşak",
	"Van",
	"Yalova",
	"Yozgat",
	"Zonguldak",
)


@dataclass
class ImportSummary:
	total_rows: int = 0
	created_umreci: int = 0
	updated_umreci: int = 0
	created_bookings: int = 0
	updated_bookings: int = 0
	row_errors: int = 0


@dataclass(frozen=True)
class ImportSourceSnapshot:
	status: str
	import_file: str | None
	target_tour: str | None
	worksheet_name: str | None


def make_source_snapshot(import_doc) -> ImportSourceSnapshot:
	return ImportSourceSnapshot(
		status=import_doc.status,
		import_file=import_doc.import_file,
		target_tour=import_doc.target_tour,
		worksheet_name=import_doc.worksheet_name,
	)


def validate_dry_run_snapshot(snapshot: ImportSourceSnapshot, current_doc) -> None:
	if current_doc.status in {"Queued", "Processing", "Completed"}:
		frappe.throw(_("Bu aktarımın durumu değişti; kuru çalıştırma sonucu kaydedilmedi."))
	if make_source_snapshot(current_doc) != snapshot:
		frappe.throw(
			_(
				"Dosya, hedef tur, Excel sayfası veya durum kuru çalıştırma sırasında değişti; sonuç kaydedilmedi."
			)
		)


def attempt_can_run(current_doc, attempt_id: str) -> bool:
	return current_doc.job_id == attempt_id and current_doc.status in {"Queued", "Processing"}


def header_key(value: Any) -> str:
	text = "" if value is None else str(value)
	text = re.sub(r"\s+", " ", text).strip()
	text = text.replace("ı", "i").replace("İ", "I")
	text = unicodedata.normalize("NFKD", text)
	text = "".join(ch for ch in text if unicodedata.category(ch) != "Mn")
	return text.casefold()


def preserve_excel_text(value: Any) -> str:
	if is_blank(value):
		return ""
	return str(value)


def is_blank(value: Any) -> bool:
	if value is None:
		return True
	if isinstance(value, str):
		return not value.strip()
	return False


def normalize_tc(value: Any) -> str | None:
	if is_blank(value):
		return None
	if isinstance(value, float) and value == int(value):
		text = str(int(value))
	else:
		text = str(value).strip()
		if text.endswith(".0") and text[:-2].isdigit():
			text = text[:-2]
	if not text:
		return None
	if text.isdigit() and len(text) == 10:
		text = text.zfill(11)
	return text


def sanitize_phone(value: Any) -> str | None:
	if is_blank(value):
		return None
	cleaned = "".join(ch for ch in str(value) if ch.isdigit())
	if cleaned.startswith("5") and len(cleaned) == 10:
		cleaned = "0" + cleaned
	return cleaned or None


def parse_date(value: Any) -> str | None:
	if is_blank(value):
		return None
	if isinstance(value, datetime):
		return value.date().isoformat()
	if isinstance(value, date):
		return value.isoformat()
	try:
		return getdate(value).isoformat()
	except Exception:
		return None


def safe_float(value: Any) -> float:
	if is_blank(value):
		return 0.0
	if isinstance(value, str):
		value = (
			value.replace(".", "").replace(",", ".")
			if re.match(r"^-?\d{1,3}(\.\d{3})*,\d+$", value.strip())
			else value.replace(",", ".")
		)
	return flt(value)


def map_oda_tipi(value: Any) -> str:
	m = re.search(r"[1-4]", str(value or ""))
	return f"{m.group(0)} Kişilik" if m else "2 Kişilik"


def normalize_cinsiyet(value: Any) -> str:
	key = header_key(value)
	if key in {"mrs", "ms", "female", "kadin", "bayan"}:
		return "MRS"
	if key in {"mr", "male", "erkek", "bay"}:
		return "MR"
	return "MR"


def _city_compare_key(value: Any) -> str:
	return header_key(str(value).replace("'", "").replace('"', ""))


CITY_LOOKUP = {_city_compare_key(city): city for city in TURKISH_PROVINCES}


def normalize_city(value: Any) -> str | None:
	if is_blank(value):
		return None
	key = _city_compare_key(value)
	if key in CITY_LOOKUP:
		return CITY_LOOKUP[key]
	frappe.throw(_("İl adı eşleşmedi: {0}").format(repr(value)))


def _alias_lookup() -> dict[str, str]:
	lookup = {}
	for logical, aliases in COLUMN_ALIASES.items():
		for alias in aliases:
			lookup[header_key(alias)] = logical
	return lookup


def _get_import_file(import_doc):
	file_name = frappe.db.get_value("File", {"file_url": import_doc.import_file}, "name")
	if not file_name:
		frappe.throw(_("Yüklenen Excel dosyası bulunamadı."))
	file_doc = frappe.get_doc("File", file_name)
	file_doc.check_permission("read")
	return file_doc


def _get_file_content(import_doc) -> bytes:
	content = _get_import_file(import_doc).get_content()
	if isinstance(content, str):
		content = content.encode()
	return bytes(content)


def _open_workbook(content: bytes):
	try:
		return load_workbook(BytesIO(content), read_only=True, data_only=True, keep_links=False)
	except Exception:
		frappe.throw(_("Excel dosyası okunamadı. Geçerli bir .xlsx dosyası yükleyin."))


def _worksheet_names_from_content(content: bytes) -> list[str]:
	workbook = _open_workbook(content)
	try:
		return list(workbook.sheetnames)
	finally:
		workbook.close()


def get_worksheet_names(import_doc) -> list[str]:
	return _worksheet_names_from_content(_get_file_content(import_doc))


def _read_selected_worksheet(content: bytes, worksheet_name: str | None) -> list[list[Any]]:
	workbook = _open_workbook(content)
	try:
		sheet_names = list(workbook.sheetnames)
		if not sheet_names:
			frappe.throw(_("Excel dosyasında çalışma sayfası bulunamadı."))
		if not worksheet_name:
			if len(sheet_names) > 1:
				frappe.throw(
					_("Excel dosyasında birden fazla sayfa var. Lütfen içe aktarılacak sayfayı seçin.")
				)
			worksheet_name = sheet_names[0]
		if worksheet_name not in sheet_names:
			frappe.throw(_("Seçilen Excel sayfası dosyada bulunamadı: {0}").format(worksheet_name))
		worksheet = workbook[worksheet_name]
		return [list(row) for row in worksheet.iter_rows(values_only=True)]
	finally:
		workbook.close()


def build_validation_signature(import_doc, content: bytes | None = None) -> str:
	content = content if content is not None else _get_file_content(import_doc)
	payload = {
		"content_hash": hashlib.sha256(content).hexdigest(),
		"target_tour": import_doc.target_tour or "",
		"worksheet_name": import_doc.worksheet_name or "",
	}
	return hashlib.sha256(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def verify_validation_signature(import_doc, content: bytes | None = None) -> None:
	if not import_doc.validation_signature:
		frappe.throw(_("Kayıtlı doğrulama bilgisi bulunamadı. Lütfen kuru çalıştırmayı yeniden yapın."))
	if import_doc.validation_signature != build_validation_signature(import_doc, content):
		frappe.throw(
			_(
				"Dosya, hedef tur veya Excel sayfası doğrulamadan sonra değişti. Lütfen kuru çalıştırmayı yeniden yapın."
			)
		)


def _read_rows(import_doc, content: bytes | None = None) -> tuple[list[str], list[dict[str, Any]]]:
	content = content if content is not None else _get_file_content(import_doc)
	raw_rows = _read_selected_worksheet(content, import_doc.worksheet_name)
	if not raw_rows:
		frappe.throw(_("Seçilen Excel sayfası boş."))

	header = raw_rows[0]
	lookup = _alias_lookup()
	index_by_logical = {}
	seen = set()
	for idx, cell in enumerate(header):
		logical = lookup.get(header_key(cell))
		if logical and logical not in seen:
			index_by_logical[logical] = idx
			seen.add(logical)

	missing = [col for col in REQUIRED_COLUMNS if col not in index_by_logical]
	if missing:
		frappe.throw(_("Missing required Excel columns: {0}").format(", ".join(missing)))

	rows = []
	for raw in raw_rows[1:]:
		if not raw or all(is_blank(cell) for cell in raw):
			continue
		mapped = {}
		for logical in (*REQUIRED_COLUMNS, *OPTIONAL_COLUMNS):
			idx = index_by_logical.get(logical)
			mapped[logical] = raw[idx] if idx is not None and idx < len(raw) else None
		rows.append(mapped)
	return list(index_by_logical), rows


def _update_import_doc(
	docname: str,
	summary: ImportSummary,
	row_log: list[dict],
	status: str,
	error_log: str | None = None,
	validation_signature: str | None = None,
	worksheet_name: str | None = None,
	dry_run_snapshot: ImportSourceSnapshot | None = None,
) -> None:
	if dry_run_snapshot is not None:
		current = frappe.db.sql(
			"""
			select status, import_file, target_tour, worksheet_name
			from `tabUmre Excel Import`
			where name = %s
			for update
			""",
			docname,
			as_dict=True,
		)
		if not current:
			frappe.throw(_("İçe aktarım kaydı bulunamadı; kuru çalıştırma sonucu kaydedilmedi."))
		validate_dry_run_snapshot(dry_run_snapshot, current[0])
	doc = frappe.get_doc(DOCTYPE_IMPORT, docname)
	doc.flags.ignore_import_source_guard = True
	doc.status = status
	for field, value in asdict(summary).items():
		doc.set(field, value)
	doc.row_log = json.dumps(row_log, ensure_ascii=False, indent=2)
	doc.dry_run_result = json.dumps(
		{"summary": asdict(summary), "rows": row_log}, ensure_ascii=False, indent=2
	)
	doc.error_log = error_log
	if validation_signature is not None:
		doc.validation_signature = validation_signature
	if worksheet_name is not None:
		doc.worksheet_name = worksheet_name
	if status in {"Completed", "Failed", "Validated"}:
		doc.completed_at = now()
	doc.save(ignore_permissions=True)
	frappe.db.commit()


def _find_existing_umreci(tc: str) -> str | None:
	return frappe.db.get_value(DOCTYPE_UMRECI, {"tc_kimlik": tc}, "name")


def _find_existing_booking(umreci: str, tur: str) -> str | None:
	return frappe.db.get_value(DOCTYPE_BOOKING, {"umreci": umreci, "tur": tur}, "name")


def _get_or_create_referral(value: Any, dry_run: bool) -> str | None:
	name = preserve_excel_text(value).strip()
	if not name:
		return None
	if frappe.db.exists(DOCTYPE_REFERRAL, name):
		return name
	if dry_run:
		return name
	ref = frappe.get_doc({"doctype": DOCTYPE_REFERRAL, "kaynak_adi": name})
	ref.insert()
	return ref.name


def _umreci_payload(row: dict[str, Any], tc: str) -> dict[str, Any]:
	return {
		"ad": preserve_excel_text(row["ADI"]),
		"soyad": preserve_excel_text(row["SOYADI"]),
		"cinsiyet": normalize_cinsiyet(row.get("CİNSİYET")),
		"tc_kimlik": tc,
		"dogum_tarihi": parse_date(row["DOĞUM TARİHİ"]),
		"uyruk": preserve_excel_text(row["UYRUK"]) or "TC",
		"telefon_numarasi": sanitize_phone(row["TELEFON NO"]),
	}


def _booking_payload(row: dict[str, Any], umreci_name: str, tur_name: str, dry_run: bool) -> dict[str, Any]:
	registration_date = parse_date(row.get("KAYIT TARİHİ"))
	if not registration_date:
		frappe.throw(_("KAYIT TARİHİ is required and must contain a valid date."))
	return {
		"umreci": umreci_name,
		"tur": tur_name,
		"oda_tipi": map_oda_tipi(row["ODA SAYISI"]),
		"ic_hat_baglanti": normalize_city(row["İÇ HAT BAĞLANTI"]),
		"kimden_geldi": _get_or_create_referral(row["KİMDEN"], dry_run=dry_run),
		"kms": safe_float(row["KMS"]),
		"ucret": safe_float(row["ÜCRET"]),
		"kayit_tarihi": registration_date,
		"not": preserve_excel_text(row.get("AÇIKLAMA")) or None,
	}


def _upsert_payment_row(booking, row: dict[str, Any], import_name: str, row_number: int) -> str | None:
	amount = safe_float(row["ÖDENEN"])
	if not amount:
		return None
	if amount < 0:
		frappe.throw(_("ÖDENEN must be greater than 0 when a payment is supplied."))
	payment_date = parse_date(row.get("ÖDEME TARİHİ"))
	if not payment_date:
		frappe.throw(_("ÖDEME TARİHİ is required when ÖDENEN is greater than 0."))
	key = f"UMRE-EXCEL::{booking.tur}::{booking.umreci}"
	for payment in booking.get("payments") or []:
		if payment.idempotency_key == key:
			is_posted = payment.posting_status == "Posted" or payment.payment_entry or payment.journal_entry
			is_verified = getattr(payment, "date_verification_status", None) == "Verified"
			if is_posted:
				same_amount = abs(flt(payment.amount) - amount) <= 0.000001
				same_date = parse_date(payment.posting_date) == payment_date
				if not same_amount or not same_date:
					frappe.throw(_("A posted payment cannot be changed by Excel import."))
				return "unchanged_posted"
			if is_verified:
				same_amount = abs(flt(payment.amount) - amount) <= 0.000001
				same_date = parse_date(payment.posting_date) == payment_date
				if not same_amount or not same_date:
					frappe.throw(_("A verified payment cannot be changed by Excel import."))
				return "unchanged_verified"
			if not getattr(payment, "legacy_posting_date", None):
				payment.legacy_posting_date = payment.posting_date
			payment.amount = amount
			payment.posting_date = payment_date
			payment.external_reference = import_name
			payment.date_source = "Excel"
			payment.date_verification_status = "Needs Review"
			payment.date_evidence_reference = import_name
			payment.verified_by = None
			payment.verified_on = None
			payment.date_repair_key = None
			payment.remarks = f"Excel import {import_name} row {row_number}"
			return "updated"
	booking.append(
		"payments",
		{
			"posting_date": payment_date,
			"amount": amount,
			"currency": frappe.db.get_value("Umre Tour", booking.tur, "para_birimi"),
			"external_reference": import_name,
			"date_source": "Excel",
			"date_verification_status": "Needs Review",
			"date_evidence_reference": import_name,
			"idempotency_key": key,
			"posting_status": "Draft",
			"remarks": f"Excel import {import_name} row {row_number}",
		},
	)
	return "created"


def _process_row(
	row: dict[str, Any],
	tur_name: str,
	summary: ImportSummary,
	row_number: int,
	dry_run: bool,
	import_name: str,
) -> dict[str, Any]:
	tc = normalize_tc(row.get("TC KİMLİK NO"))
	if not tc:
		frappe.throw(_("Missing TC KİMLİK NO"))
	# Validate the explicit business date before any row-level document is changed.
	if not parse_date(row.get("KAYIT TARİHİ")):
		frappe.throw(_("KAYIT TARİHİ is required and must contain a valid date."))
	payment_amount = safe_float(row.get("ÖDENEN"))
	if payment_amount < 0:
		frappe.throw(_("ÖDENEN must be greater than 0 when a payment is supplied."))
	if payment_amount > 0 and not parse_date(row.get("ÖDEME TARİHİ")):
		frappe.throw(_("ÖDEME TARİHİ is required when ÖDENEN is greater than 0."))

	log = {
		"row_number": row_number,
		"tc_kimlik": tc,
		"ad": preserve_excel_text(row["ADI"]),
		"soyad": preserve_excel_text(row["SOYADI"]),
		"status": "Success",
		"action_umreci": None,
		"action_booking": None,
		"payment_action": None,
		"error_message": None,
		"created_or_updated_doc": None,
	}
	if payment_amount > 0:
		log["payment_action"] = "would_create_or_update" if dry_run else None

	existing_umreci = _find_existing_umreci(tc)
	umreci_payload = _umreci_payload(row, tc)
	if existing_umreci:
		log["action_umreci"] = "update"
		umreci_name = existing_umreci
		if not dry_run:
			doc = frappe.get_doc(DOCTYPE_UMRECI, existing_umreci)
			doc.update(umreci_payload)
			doc.save()
		summary.updated_umreci += 1
	else:
		log["action_umreci"] = "create"
		umreci_name = f"{umreci_payload['ad']} {umreci_payload['soyad']} - {tc}"
		if not dry_run:
			doc = frappe.get_doc({"doctype": DOCTYPE_UMRECI, **umreci_payload})
			doc.insert()
			umreci_name = doc.name
		summary.created_umreci += 1

	existing_booking = _find_existing_booking(umreci_name, tur_name)
	booking_payload = _booking_payload(row, umreci_name, tur_name, dry_run=dry_run)
	if existing_booking:
		log["action_booking"] = "update"
		log["created_or_updated_doc"] = existing_booking
		if not dry_run:
			booking = frappe.get_doc(DOCTYPE_BOOKING, existing_booking)
			booking.update(booking_payload)
			log["payment_action"] = _upsert_payment_row(booking, row, import_name, row_number)
			booking.save()
		summary.updated_bookings += 1
	else:
		log["action_booking"] = "create"
		if not dry_run:
			booking = frappe.get_doc({"doctype": DOCTYPE_BOOKING, **booking_payload})
			log["payment_action"] = _upsert_payment_row(booking, row, import_name, row_number)
			booking.insert()
			log["created_or_updated_doc"] = booking.name
		summary.created_bookings += 1

	return log


def run_import(docname: str, *, dry_run: bool) -> dict:
	import_doc = frappe.get_doc(DOCTYPE_IMPORT, docname)
	import_doc.check_permission("write")
	dry_run_snapshot = make_source_snapshot(import_doc) if dry_run else None
	if dry_run and import_doc.status in {"Queued", "Processing", "Completed"}:
		frappe.throw(_("Bu durumda kuru çalıştırma yapılamaz. Yeni bir içe aktarım kaydı oluşturun."))
	if not frappe.db.exists("Umre Tour", import_doc.target_tour):
		frappe.throw(_("Target Umre Tour does not exist."))

	content = _get_file_content(import_doc)
	if dry_run and not import_doc.worksheet_name:
		sheet_names = _worksheet_names_from_content(content)
		if len(sheet_names) == 1:
			import_doc.worksheet_name = sheet_names[0]
	if not dry_run:
		verify_validation_signature(import_doc, content)
	_discovered_columns, rows = _read_rows(import_doc, content)
	summary = ImportSummary(total_rows=len(rows))
	row_log = []

	for idx, row in enumerate(rows, start=2):
		try:
			row_log.append(_process_row(row, import_doc.target_tour, summary, idx, dry_run, import_doc.name))
		except Exception as exc:
			summary.row_errors += 1
			row_log.append(
				{
					"row_number": idx,
					"tc_kimlik": normalize_tc(row.get("TC KİMLİK NO")),
					"ad": preserve_excel_text(row.get("ADI")),
					"soyad": preserve_excel_text(row.get("SOYADI")),
					"status": "Error",
					"action_umreci": None,
					"action_booking": None,
					"payment_action": None,
					"error_message": frappe.get_traceback() if not dry_run else str(exc),
					"created_or_updated_doc": None,
				}
			)

	status = "Failed" if summary.row_errors else ("Validated" if dry_run else "Completed")
	validation_signature = build_validation_signature(import_doc, content) if dry_run else None
	_update_import_doc(
		docname,
		summary,
		row_log,
		status,
		validation_signature=validation_signature,
		worksheet_name=import_doc.worksheet_name if dry_run else None,
		dry_run_snapshot=dry_run_snapshot,
	)
	return {"summary": asdict(summary), "rows": row_log}


def run_dry_run(docname: str) -> dict:
	return run_import(docname, dry_run=True)


def _mark_failed_attempt(docname: str, attempt_id: str, error_log: str) -> None:
	frappe.db.sql("select name from `tabUmre Excel Import` where name = %s for update", docname)
	current = frappe.get_doc(DOCTYPE_IMPORT, docname)
	if not attempt_can_run(current, attempt_id):
		frappe.db.rollback()
		return
	summary = ImportSummary(
		total_rows=current.total_rows or 0,
		created_umreci=current.created_umreci or 0,
		updated_umreci=current.updated_umreci or 0,
		created_bookings=current.created_bookings or 0,
		updated_bookings=current.updated_bookings or 0,
		row_errors=(current.row_errors or 0) + 1,
	)
	_update_import_doc(docname, summary, [], "Failed", error_log=error_log)


def run_import_job(docname: str, attempt_id: str, user: str | None = None) -> None:
	if user:
		frappe.set_user(user)
	try:
		frappe.db.sql("select name from `tabUmre Excel Import` where name = %s for update", docname)
		doc = frappe.get_doc(DOCTYPE_IMPORT, docname)
		if not attempt_can_run(doc, attempt_id):
			frappe.db.rollback()
			return
		verify_validation_signature(doc)
		if doc.status == "Queued":
			doc.status = "Processing"
			doc.started_at = now()
			doc.completed_at = None
			doc.error_log = None
			doc.save(ignore_permissions=True)
		# RQ guarantees that one job_id is not executed concurrently. A Processing
		# retry with this same attempt_id therefore represents recovery after a hard kill.
		frappe.db.commit()
		run_import(docname, dry_run=False)
	except RETRYABLE_IMPORT_ERRORS:
		# Frappe retries transient database/job errors. Keep this attempt Processing
		# so the same attempt_id can safely resume after the financial rollback.
		frappe.db.rollback()
		raise
	except Exception:
		error_log = frappe.get_traceback()
		# Roll back every financial write made by this attempt before recording
		# the terminal failure in a fresh transaction.
		frappe.db.rollback()
		_mark_failed_attempt(docname, attempt_id, error_log)
		frappe.db.commit()
		raise


def _enqueue_attempt(docname: str, attempt_id: str, user: str, *, after_commit: bool) -> None:
	frappe.enqueue(
		"umre_ops.umre_ops.services.excel_import_service.run_import_job",
		queue="long",
		docname=docname,
		attempt_id=attempt_id,
		user=user,
		job_id=attempt_id,
		deduplicate=True,
		enqueue_after_commit=after_commit,
	)


def enqueue_import(docname: str, user: str | None = None) -> dict:
	frappe.db.sql("select name from `tabUmre Excel Import` where name = %s for update", docname)
	doc = frappe.get_doc(DOCTYPE_IMPORT, docname)
	doc.check_permission("write")
	queue_user = user or frappe.session.user
	if doc.status in {"Queued", "Processing"} and doc.job_id:
		if not is_job_enqueued(doc.job_id):
			_enqueue_attempt(docname, doc.job_id, queue_user, after_commit=False)
		return {"job_id": doc.job_id, "status": doc.status}
	if doc.status != "Validated" or doc.row_errors:
		frappe.throw(_("Aktarımı başlatmadan önce hatasız bir kuru çalıştırma yapın."))
	verify_validation_signature(doc)
	attempt_id = uuid4().hex
	doc.status = "Queued"
	doc.job_id = attempt_id
	doc.started_at = None
	doc.completed_at = None
	doc.save(ignore_permissions=True)
	_enqueue_attempt(docname, attempt_id, queue_user, after_commit=True)
	return {"job_id": attempt_id, "status": "Queued"}
