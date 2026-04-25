# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass
from datetime import date, datetime
from typing import Any

import frappe
from frappe import _
from frappe.utils import flt, getdate, now, nowdate
from frappe.utils.xlsxutils import read_xlsx_file_from_attached_file


DOCTYPE_IMPORT = "Umre Excel Import"
DOCTYPE_UMRECI = "Umreci"
DOCTYPE_BOOKING = "Umre Booking"
DOCTYPE_REFERRAL = "Referral Source"

REQUIRED_COLUMNS = (
	"ADI",
	"SOYADI",
	"TC KİMLİK NO",
	"DOĞUM TARİHİ",
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
		value = value.replace(".", "").replace(",", ".") if re.match(r"^-?\d{1,3}(\.\d{3})*,\d+$", value.strip()) else value.replace(",", ".")
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


def _read_rows(import_doc) -> tuple[list[str], list[dict[str, Any]]]:
	raw_rows = read_xlsx_file_from_attached_file(file_url=import_doc.import_file)
	if not raw_rows:
		frappe.throw(_("Excel file is empty."))

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


def _update_import_doc(docname: str, summary: ImportSummary, row_log: list[dict], status: str, error_log: str | None = None) -> None:
	doc = frappe.get_doc(DOCTYPE_IMPORT, docname)
	doc.status = status
	for field, value in asdict(summary).items():
		doc.set(field, value)
	doc.row_log = json.dumps(row_log, ensure_ascii=False, indent=2)
	doc.dry_run_result = json.dumps({"summary": asdict(summary), "rows": row_log}, ensure_ascii=False, indent=2)
	doc.error_log = error_log
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
	return {
		"umreci": umreci_name,
		"tur": tur_name,
		"oda_tipi": map_oda_tipi(row["ODA SAYISI"]),
		"ic_hat_baglanti": normalize_city(row["İÇ HAT BAĞLANTI"]),
		"kimden_geldi": _get_or_create_referral(row["KİMDEN"], dry_run=dry_run),
		"odenen": safe_float(row["ÖDENEN"]),
		"kms": safe_float(row["KMS"]),
		"ucret": safe_float(row["ÜCRET"]),
		"kayit_tarihi": parse_date(row["DOĞUM TARİHİ"]) or nowdate(),
		"not": preserve_excel_text(row.get("AÇIKLAMA")) or None,
	}


def _upsert_payment_row(booking, row: dict[str, Any], import_name: str, row_number: int) -> str | None:
	amount = safe_float(row["ÖDENEN"])
	if not amount:
		return None
	key = f"UMRE-EXCEL::{booking.tur}::{booking.umreci}"
	for payment in booking.get("payments") or []:
		if payment.idempotency_key == key:
			payment.amount = amount
			payment.posting_date = parse_date(row["DOĞUM TARİHİ"]) or nowdate()
			payment.external_reference = import_name
			payment.remarks = f"Excel import {import_name} row {row_number}"
			return "updated"
	booking.append(
		"payments",
		{
			"posting_date": parse_date(row["DOĞUM TARİHİ"]) or nowdate(),
			"amount": amount,
			"currency": frappe.db.get_value("Umre Tour", booking.tur, "para_birimi"),
			"external_reference": import_name,
			"idempotency_key": key,
			"posting_status": "Draft",
			"remarks": f"Excel import {import_name} row {row_number}",
		},
	)
	return "created"


def _process_row(row: dict[str, Any], tur_name: str, summary: ImportSummary, row_number: int, dry_run: bool, import_name: str) -> dict[str, Any]:
	tc = normalize_tc(row.get("TC KİMLİK NO"))
	if not tc:
		frappe.throw(_("Missing TC KİMLİK NO"))

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
	if not frappe.db.exists("Umre Tour", import_doc.target_tour):
		frappe.throw(_("Target Umre Tour does not exist."))

	_, rows = _read_rows(import_doc)
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

	status = "Validated" if dry_run else "Completed"
	_update_import_doc(docname, summary, row_log, status)
	return {"summary": asdict(summary), "rows": row_log}


def run_dry_run(docname: str) -> dict:
	return run_import(docname, dry_run=True)


def run_import_job(docname: str, user: str | None = None) -> None:
	if user:
		frappe.set_user(user)
	doc = frappe.get_doc(DOCTYPE_IMPORT, docname)
	doc.status = "Processing"
	doc.started_at = now()
	doc.completed_at = None
	doc.error_log = None
	doc.save(ignore_permissions=True)
	frappe.db.commit()
	try:
		run_import(docname, dry_run=False)
	except Exception:
		summary = ImportSummary(
			total_rows=doc.total_rows or 0,
			created_umreci=doc.created_umreci or 0,
			updated_umreci=doc.updated_umreci or 0,
			created_bookings=doc.created_bookings or 0,
			updated_bookings=doc.updated_bookings or 0,
			row_errors=(doc.row_errors or 0) + 1,
		)
		_update_import_doc(docname, summary, [], "Failed", error_log=frappe.get_traceback())
		raise


def enqueue_import(docname: str, user: str | None = None) -> dict:
	doc = frappe.get_doc(DOCTYPE_IMPORT, docname)
	doc.check_permission("write")
	job = frappe.enqueue(
		"umre_ops.umre_ops.services.excel_import_service.run_import_job",
		queue="long",
		docname=docname,
		user=user or frappe.session.user,
		job_name=f"Umre Excel Import {docname}",
	)
	doc.status = "Queued"
	doc.job_id = getattr(job, "id", None)
	doc.started_at = None
	doc.completed_at = None
	doc.save(ignore_permissions=True)
	return {"job_id": doc.job_id, "status": doc.status}
