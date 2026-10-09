# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
"""
Single profit & loss calculation for Umre Ops (USD).

The dashboard, the Tour Revenue Summary report and any export read their numbers
from ``get_season_pnl`` so they can never disagree.

Per tour (cancelled bookings and tours with ``durum = İptal`` are excluded):

    brüt satış        = Σ ucret                        (UMRECI)
    komisyon          = Σ kms                          (UMRECI)
    net satış         = brüt satış − komisyon
    yolcu maliyeti    = Σ Cost Component (USD), every passenger status
    tur ekstra gider  = Σ Operational Expense.usd_amount (Confirmed, related_tour = tur)
    tur kârı          = net satış − yolcu maliyeti − tur ekstra gider

Season:

    genel gider       = Σ Operational Expense.usd_amount (Confirmed, no related_tour)
    sezon sonucu      = Σ tur kârı − genel gider

Collections are per booking: açık alacak = max(ucret − odenen, 0); an
overpayment is reported separately and never offsets another passenger's debt.
"""
from __future__ import annotations

from typing import Any

import frappe
from frappe import _
from frappe.utils import flt

from umre_ops.umre_ops.services import cost_engine

CURRENCY = "USD"
PAYING_STATUS = cost_engine.PAYING_STATUS
CANCELLED_TOUR_STATUS = "İptal"

MONEY_KEYS = (
	"brut_satis",
	"komisyon",
	"net_satis",
	"yolcu_maliyeti",
	"tur_ekstra_gider",
	"toplam_maliyet",
	"tur_kari",
	"tahsil_edilen",
	"excel_bildirilen",
	"acik_alacak",
	"fazla_odeme",
)
COUNT_KEYS = ("kisi_sayisi", "umreci_count", "non_umreci_count")

WARNING_MESSAGES = {
	"MISSING_RULE": "Maliyet kuralı tanımlı değil; bu yolcuların maliyeti eksik.",
	"ZERO_RULE": "Maliyet kuralı tutarı 0; bu yolcuların maliyeti eksik.",
	"INVALID_RATE": "Kuralda geçersiz kur var.",
	"MISSING_PASSENGER_TYPE": "Yolcu tipi boş; uçak ve otel maliyeti hesaplanamadı.",
	"STALE": "Kayıtlı maliyet güncel kurallarla uyuşmuyor; turu yeniden hesaplayın.",
	"NON_USD_COMPONENT": "USD dışı maliyet satırı toplamlara katılmadı.",
	"MISSING_COMPANY": "Şirketi boş rezervasyon, Ayarlar'daki şirket kapsamında gösteriliyor.",
}


def _empty_row(tour: str, label: str) -> dict[str, Any]:
	row: dict[str, Any] = {"tour": tour, "label": label}
	row.update({key: 0.0 for key in MONEY_KEYS})
	row.update({key: 0 for key in COUNT_KEYS})
	row["maliyet_by_type"] = {}
	row["by_status"] = {}
	return row


def _finish(row: dict[str, Any]) -> dict[str, Any]:
	row["net_satis"] = flt(row["brut_satis"] - row["komisyon"], 2)
	row["toplam_maliyet"] = flt(row["yolcu_maliyeti"] + row["tur_ekstra_gider"], 2)
	row["tur_kari"] = flt(row["net_satis"] - row["toplam_maliyet"], 2)
	for key in MONEY_KEYS:
		row[key] = flt(row[key], 2)
	row["maliyet_by_type"] = {k: flt(v, 2) for k, v in sorted(row["maliyet_by_type"].items())}
	row["kisi_basi_kar"] = flt(row["tur_kari"] / row["umreci_count"], 2) if row["umreci_count"] else 0.0
	row["kisi_basi_maliyet"] = flt(row["toplam_maliyet"] / row["kisi_sayisi"], 2) if row["kisi_sayisi"] else 0.0
	meal = row["maliyet_by_type"].get("MEAL", 0.0)
	row["yemek_orani"] = flt(meal / row["yolcu_maliyeti"] * 100, 2) if row["yolcu_maliyeti"] > 0 else 0.0
	return row


class _Warnings:
	def __init__(self) -> None:
		self._by_code: dict[str, dict[str, Any]] = {}

	def add(self, code: str, booking: str | None, detail: str | None = None) -> None:
		entry = self._by_code.setdefault(
			code, {"code": code, "message": _(WARNING_MESSAGES.get(code, code)), "bookings": set(), "details": {}}
		)
		if booking:
			entry["bookings"].add(booking)
		if detail:
			entry["details"][detail] = entry["details"].get(detail, 0) + 1

	def as_list(self) -> list[dict[str, Any]]:
		out = []
		for entry in self._by_code.values():
			bookings = sorted(entry["bookings"])
			out.append({
				"code": entry["code"],
				"message": entry["message"],
				"count": len(bookings),
				"examples": bookings[:5],
				"details": dict(sorted(entry["details"].items())),
			})
		return sorted(out, key=lambda w: w["code"])


def build_pnl(
	*,
	tours: list[dict],
	bookings: list[dict],
	components: list[dict],
	tour_expenses: dict[str, float] | None = None,
	overhead: float | None = None,
	contexts: dict[str, cost_engine.TourCostContext] | None = None,
) -> dict[str, Any]:
	"""Pure aggregation. ``contexts`` enables missing-rule / staleness checks."""
	tour_expenses = tour_expenses or {}
	warnings = _Warnings()
	rows: dict[str, dict[str, Any]] = {
		t["name"]: _empty_row(t["name"], t.get("label") or t["name"])
		for t in tours
		if (t.get("durum") or "") != CANCELLED_TOUR_STATUS
	}

	active = [b for b in bookings if b.get("tur") in rows and not b.get("iptal_edildi")]
	stored_by_booking: dict[str, dict[str, float]] = {}
	system_by_booking: dict[str, dict[str, float]] = {}
	for comp in components:
		booking = comp["booking"]
		if (comp.get("currency") or CURRENCY) != CURRENCY:
			warnings.add("NON_USD_COMPONENT", booking, comp.get("cost_type"))
			continue
		bucket = stored_by_booking.setdefault(booking, {})
		bucket[comp["cost_type"]] = flt(bucket.get(comp["cost_type"], 0) + flt(comp["amount"]))
		if comp.get("is_system_generated"):
			sys_bucket = system_by_booking.setdefault(booking, {})
			sys_bucket[comp["cost_type"]] = flt(sys_bucket.get(comp["cost_type"], 0) + flt(comp["amount"]), 2)

	for booking in active:
		row = rows[booking["tur"]]
		name = booking["name"]
		statu = (booking.get("statu") or PAYING_STATUS).strip() or PAYING_STATUS
		is_paying = statu == PAYING_STATUS
		cost_by_type = stored_by_booking.get(name, {})
		cost = sum(cost_by_type.values())
		ucret = flt(booking.get("ucret")) if is_paying else 0.0
		kms = flt(booking.get("kms")) if is_paying else 0.0
		paid = flt(booking.get("odenen")) if is_paying else 0.0

		row["kisi_sayisi"] += 1
		row["umreci_count" if is_paying else "non_umreci_count"] += 1
		row["brut_satis"] += ucret
		row["komisyon"] += kms
		row["yolcu_maliyeti"] += cost
		for code, amount in cost_by_type.items():
			row["maliyet_by_type"][code] = row["maliyet_by_type"].get(code, 0.0) + amount
		row["tahsil_edilen"] += paid
		row["excel_bildirilen"] += flt(booking.get("bildirilen_odenen")) if is_paying else 0.0
		row["acik_alacak"] += max(ucret - paid, 0.0)
		row["fazla_odeme"] += max(paid - ucret, 0.0)

		status_row = row["by_status"].setdefault(statu, {"kisi_sayisi": 0, "net_satis": 0.0, "maliyet": 0.0})
		status_row["kisi_sayisi"] += 1
		status_row["net_satis"] += ucret - kms
		status_row["maliyet"] += cost

		if not booking.get("company"):
			warnings.add("MISSING_COMPANY", name)
		ctx = (contexts or {}).get(booking["tur"])
		if ctx is not None:
			diff = cost_engine.diff_components(booking, ctx, system_by_booking.get(name, {}))
			for issue in diff["issues"]:
				detail = issue["cost_type"] + (f" ({issue['detail']})" if issue.get("detail") else "")
				warnings.add(issue["code"], name, detail)
			if diff["stale"]:
				warnings.add("STALE", name, booking["tur"])

	for tour_name, amount in tour_expenses.items():
		if tour_name in rows:
			rows[tour_name]["tur_ekstra_gider"] += flt(amount)

	tour_rows = []
	for row in rows.values():
		for status_row in row["by_status"].values():
			status_row["net_etki"] = flt(status_row["net_satis"] - status_row["maliyet"], 2)
			status_row["net_satis"] = flt(status_row["net_satis"], 2)
			status_row["maliyet"] = flt(status_row["maliyet"], 2)
		tour_rows.append(_finish(row))
	tour_rows.sort(key=lambda r: r["label"])

	totals = _empty_row("", _("Toplam"))
	for row in tour_rows:
		for key in (*MONEY_KEYS, *COUNT_KEYS):
			totals[key] += row[key]
		for code, amount in row["maliyet_by_type"].items():
			totals["maliyet_by_type"][code] = totals["maliyet_by_type"].get(code, 0.0) + amount
	totals = _finish(totals)
	totals.pop("by_status", None)

	season_result = None
	if overhead is not None:
		overhead = flt(overhead, 2)
		season_result = flt(totals["tur_kari"] - overhead, 2)
	return {
		"currency": CURRENCY,
		"tours": tour_rows,
		"totals": totals,
		"genel_gider": overhead,
		"sezon_sonucu": season_result,
		"warnings": warnings.as_list(),
	}


# ---------------------------------------------------------------------------
# Database loader
# ---------------------------------------------------------------------------

def _booking_fields() -> list[str]:
	return sorted({
		"name", "tur", "statu", "ucret", "kms", "odenen", "bildirilen_odenen", "company",
		*cost_engine.COST_DRIVER_FIELDS,
	})


def get_season_pnl(
	season: str,
	tour: str | None = None,
	company: str | None = None,
	*,
	check_rules: bool = True,
) -> dict[str, Any]:
	"""Load one season (optionally one tour) and return ``build_pnl`` output.

	``company``: bookings of that company plus bookings with an empty company.
	"""
	if not season:
		frappe.throw(_("Sezon seçilmelidir."))
	tour_filters: dict[str, Any] = {"season": season}
	if tour:
		tour_filters["name"] = tour
	tours = [
		{"name": t["name"], "label": t.get("tur_adi") or t["name"], "durum": t.get("durum")}
		for t in frappe.get_all(
			"Umre Tour", filters=tour_filters, fields=["name", "tur_adi", "durum"], limit_page_length=0
		)
	]
	tour_names = [t["name"] for t in tours if (t.get("durum") or "") != CANCELLED_TOUR_STATUS]
	if not tour_names:
		empty = build_pnl(tours=[], bookings=[], components=[])
		empty["genel_gider"] = None if tour else _overhead(season)
		empty["sezon_sonucu"] = None if tour else flt(-(empty["genel_gider"] or 0), 2)
		return empty

	booking_filters: dict[str, Any] = {"tur": ["in", tour_names], "iptal_edildi": 0}
	bookings = frappe.get_all(
		"Umre Booking", filters=booking_filters, fields=_booking_fields(), limit_page_length=0
	)
	if company:
		bookings = [b for b in bookings if not b.get("company") or b.get("company") == company]
	booking_names = [b["name"] for b in bookings]
	components = frappe.get_all(
		"Cost Component",
		filters={"booking": ["in", booking_names]},
		fields=["booking", "cost_type", "currency", "amount", "is_system_generated"],
		limit_page_length=0,
	) if booking_names else []
	contexts = {name: cost_engine.load_tour_cost_context(name) for name in tour_names} if check_rules else None
	return build_pnl(
		tours=tours,
		bookings=bookings,
		components=components,
		tour_expenses=_tour_expenses(tour_names),
		overhead=None if tour else _overhead(season),
		contexts=contexts,
	)


def _tour_expenses(tour_names: list[str]) -> dict[str, float]:
	if not tour_names or not frappe.db.exists("DocType", "Operational Expense"):
		return {}
	rows = frappe.db.sql(
		"""
		SELECT related_tour, COALESCE(SUM(usd_amount), 0) AS total
		FROM `tabOperational Expense`
		WHERE status = 'Confirmed' AND related_tour IN %(tours)s
		GROUP BY related_tour
		""",
		{"tours": tuple(tour_names)},
		as_dict=True,
	)
	return {r["related_tour"]: flt(r["total"]) for r in rows}


def _overhead(season: str) -> float:
	if not frappe.db.exists("DocType", "Operational Expense"):
		return 0.0
	row = frappe.db.sql(
		"""
		SELECT COALESCE(SUM(usd_amount), 0)
		FROM `tabOperational Expense`
		WHERE status = 'Confirmed' AND season = %(season)s
		  AND COALESCE(related_tour, '') = ''
		""",
		{"season": season},
	)
	return flt(row[0][0] if row else 0, 2)
