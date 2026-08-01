# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
"""Restore the audited 6 July 2026 Excel prices without changing any other field."""

# ruff: noqa: RUF001

from __future__ import annotations

import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

import frappe

MANIFEST_PATH = Path(__file__).resolve().parent / "data" / "july_2026_excel_prices.json"
TOUR_NAME = "6 Temmuz 40 vakit medine umresi"
EXPECTED_META = {
	"schema_version": 1,
	"patch_id": "restore_july_2026_excel_prices_v1",
	"tour": TOUR_NAME,
	"tour_code": "010",
	"start_date": "2026-07-06",
	"currency": "USD",
	"source_file_name": "ERPNext sistemine verilecek dosya.xlsx",
	"source_sha256": "cdbabf97796547869a2ef6ecde66c0aee97b966fa3d58b41efce2ed0aa8d1304",
	"source_sheet": "sermed_big_data",
	"rows_sha256": "bfa80e7f4ba28d788ee2238ee1cbda2330e204d24f0399d0961c9b4a8cf3cc95",
}
EXPECTED_TOTALS = {
	"row_count": 63,
	"unique_tc_count": 63,
	"positive_price_count": 58,
	"price_total": Decimal("85200"),
	"reported_paid_total": Decimal("84650"),
	"gross_shortfall": Decimal("850"),
	"gross_overpayment": Decimal("300"),
}
ROOM_FIELDS = {
	1: "bir_kisilik_oda",
	2: "iki_kisilik_oda",
	3: "uc_kisilik_oda",
	4: "dort_kisilik_oda",
}
HASH_RE = re.compile(r"[0-9a-f]{64}")
MONEY_QUANTUM = Decimal("0.01")


def _fail(message: str) -> None:
	raise frappe.ValidationError(f"[restore_july_2026_excel_prices] {message}")


def _decimal(value: Any, label: str) -> Decimal:
	if isinstance(value, bool) or value is None:
		_fail(f"{label} geçerli bir para değeri değil.")
	try:
		result = Decimal(str(value))
	except (InvalidOperation, ValueError):
		_fail(f"{label} geçerli bir para değeri değil.")
	if not result.is_finite():
		_fail(f"{label} sonlu olmalıdır.")
	quantized = result.quantize(MONEY_QUANTUM)
	if result != quantized:
		_fail(f"{label} en fazla iki ondalık hane içermelidir.")
	return quantized


def load_and_validate_manifest(
	path: Path = MANIFEST_PATH,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
	manifest = json.loads(path.read_text(encoding="utf-8"), parse_float=Decimal)
	for key, expected in EXPECTED_META.items():
		if manifest.get(key) != expected:
			_fail(f"manifest {key} beklenen sabit değerle eşleşmiyor.")

	declared = manifest.get("expected") or {}
	for key, expected in EXPECTED_TOTALS.items():
		actual = (
			_decimal(declared.get(key), f"expected.{key}")
			if isinstance(expected, Decimal)
			else declared.get(key)
		)
		if actual != expected:
			_fail(f"manifest expected.{key} değeri geçersiz.")

	rows = manifest.get("rows")
	if not isinstance(rows, list) or len(rows) != EXPECTED_TOTALS["row_count"]:
		_fail("manifest satır sayısı 63 olmalıdır.")
	try:
		canonical_rows = json.dumps(rows, ensure_ascii=False, separators=(",", ":"))
	except (TypeError, ValueError):
		_fail("manifest satırları kanonik JSON biçimine dönüştürülemiyor.")
	computed_rows_hash = hashlib.sha256(canonical_rows.encode("utf-8")).hexdigest()
	if computed_rows_hash != manifest.get("rows_sha256"):
		_fail("manifest satır SHA-256 özeti geçersiz.")

	by_hash: dict[str, dict[str, Any]] = {}
	price_total = reported_total = shortfall = overpayment = Decimal("0")
	positive_count = 0
	for position, raw in enumerate(rows, start=1):
		if not isinstance(raw, dict) or set(raw) != {"tc_sha256", "price", "reported_paid", "room_size"}:
			_fail(f"manifest satır {position} alanları geçersiz.")
		tc_hash = raw["tc_sha256"]
		if not isinstance(tc_hash, str) or not HASH_RE.fullmatch(tc_hash) or tc_hash in by_hash:
			_fail(f"manifest satır {position} TC hash değeri geçersiz veya yinelenmiş.")
		price = _decimal(raw["price"], f"rows[{position}].price")
		reported = _decimal(raw["reported_paid"], f"rows[{position}].reported_paid")
		room_size = raw["room_size"]
		if price < 0 or reported < 0 or room_size not in ROOM_FIELDS:
			_fail(f"manifest satır {position} fiyat/ödeme/oda değeri geçersiz.")
		positive_count += int(price > 0)
		price_total += price
		reported_total += reported
		shortfall += max(price - reported, Decimal("0"))
		overpayment += max(reported - price, Decimal("0"))
		by_hash[tc_hash] = {**raw, "price": price, "reported_paid": reported}

	actuals = {
		"unique_tc_count": len(by_hash),
		"positive_price_count": positive_count,
		"price_total": price_total,
		"reported_paid_total": reported_total,
		"gross_shortfall": shortfall,
		"gross_overpayment": overpayment,
	}
	for key, expected in EXPECTED_TOTALS.items():
		if key != "row_count" and actuals[key] != expected:
			_fail(f"manifest hesaplanan {key} değişmezi geçersiz.")
	return manifest, by_hash


def _tc_hash(value: Any) -> str:
	canonical = "".join(str(value or "").split())
	if not canonical:
		_fail("rezervasyonda boş TC bulundu.")
	return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def build_update_plan(
	manifest_by_hash: dict[str, dict[str, Any]],
	tour: dict[str, Any],
	bookings: list[dict[str, Any]],
) -> list[tuple[str, Decimal, Decimal]]:
	if (
		tour.get("name") != TOUR_NAME
		or tour.get("tur_adi") != TOUR_NAME
		or tour.get("tur_kodu") != EXPECTED_META["tour_code"]
		or str(tour.get("baslangic_tarihi")) != EXPECTED_META["start_date"]
		or tour.get("para_birimi") != EXPECTED_META["currency"]
	):
		_fail("hedef turun ad/kod/tarih/para birimi değişmezleri eşleşmiyor.")

	if len(bookings) != EXPECTED_TOTALS["row_count"]:
		_fail("hedef turda tam 63 rezervasyon bulunmalıdır.")

	seen_names: set[str] = set()
	seen_hashes: set[str] = set()
	plan: list[tuple[str, Decimal, Decimal]] = []
	for booking in bookings:
		name = booking.get("name")
		tc_hash = _tc_hash(booking.get("tc_kimlik"))
		if not name or name in seen_names or tc_hash in seen_hashes:
			_fail("rezervasyon adı veya TC kimliği yinelenmiş.")
		seen_names.add(name)
		seen_hashes.add(tc_hash)
		truth = manifest_by_hash.get(tc_hash)
		if truth is None:
			_fail("rezervasyon TC hash değeri manifestte bulunamadı.")

		price = truth["price"]
		expected_status = "UMRECI" if price > 0 else None
		status = booking.get("statu")
		if (expected_status and status != expected_status) or (not expected_status and status == "UMRECI"):
			_fail(f"{name}: statü Excel fiyat sınıfıyla eşleşmiyor.")
		if _decimal(booking.get("bildirilen_odenen"), f"{name}.bildirilen_odenen") != truth["reported_paid"]:
			_fail(f"{name}: bildirilen ödeme manifestle eşleşmiyor.")
		if booking.get("oda_tipi") != f"{truth['room_size']} Kişilik":
			_fail(f"{name}: oda tipi manifestle eşleşmiyor.")
		if int(booking.get("is_imported") or 0) != 1 or int(booking.get("locked_financials") or 0) != 1:
			_fail(f"{name}: imported/locked değişmezleri sağlanmıyor.")

		current = _decimal(booking.get("ucret"), f"{name}.ucret")
		tariff = (
			Decimal("0")
			if price == 0
			else _decimal(
				tour.get(ROOM_FIELDS[truth["room_size"]]), f"tour.{ROOM_FIELDS[truth['room_size']]}"
			)
		)
		if current not in {price, tariff}:
			_fail(f"{name}: mevcut ücret ne Excel fiyatı ne oda tarifesi; işlem durduruldu.")
		if current != price:
			plan.append((name, current, price))

	if seen_hashes != set(manifest_by_hash):
		_fail("veritabanı ve manifest TC hash kümeleri birebir eşleşmiyor.")
	return plan


def execute() -> None:
	_, manifest_by_hash = load_and_validate_manifest()
	tour_fields = ["name", "tur_adi", "tur_kodu", "baslangic_tarihi", "para_birimi", *ROOM_FIELDS.values()]
	tour = frappe.db.get_value("Umre Tour", TOUR_NAME, tour_fields, as_dict=True)
	if not tour:
		if frappe.db.count("Umre Booking") == 0:
			print("[restore_july_2026_excel_prices] empty site; nothing to repair")
			return
		_fail("hedef tur bulunamadı.")
	bookings = frappe.db.sql(
		"""
		select b.name, b.statu, b.oda_tipi, b.ucret, b.bildirilen_odenen,
		       b.is_imported, b.locked_financials, u.tc_kimlik
		from `tabUmre Booking` b
		inner join `tabUmreci` u on u.name = b.umreci
		where b.tur = %s
		order by b.name
		for update
		""",
		(TOUR_NAME,),
		as_dict=True,
	)
	plan = build_update_plan(manifest_by_hash, dict(tour), [dict(row) for row in bookings])
	for booking_name, old_price, price in plan:
		frappe.db.set_value("Umre Booking", booking_name, "ucret", price, update_modified=False)
		print(f"[restore_july_2026_excel_prices] {booking_name}: ucret {old_price:.2f} -> {price:.2f}")
	print(
		f"[restore_july_2026_excel_prices] updated={len(plan)} source_sha256={EXPECTED_META['source_sha256']}"
	)
