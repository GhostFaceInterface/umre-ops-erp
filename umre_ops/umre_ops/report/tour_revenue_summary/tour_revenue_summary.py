# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
"""
Tour Revenue Summary — tour and season P&L in USD.

Every number comes from ``pnl_service.get_season_pnl`` (the same calculation as
the Umre Operasyon Paneli):

    net satış  = Σ ucret − Σ kms                     (UMRECI)
    maliyet    = Σ Cost Component + tur ekstra gider (Operational Expense.related_tour)
    tur kârı   = net satış − maliyet
    sezon sonucu = Σ tur kârı − ofis genel gideri    (summary, no tour filter)

Only tour rows carry the main amount columns. Status and cost-type rows use the
separate "Detay" columns, so exporting and summing a column never double counts.
"""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import escape_html, flt

from umre_ops.umre_ops.services.pnl_service import get_season_pnl
from umre_ops.umre_ops.services.season_service import get_active_season

DEFAULT_CURRENCY = "USD"
INDENT_TOUR = 0
INDENT_SECTION = 1
INDENT_DETAIL = 2


def execute(filters=None):
	filters = frappe._dict(filters or {})
	season = filters.get("season") or get_active_season(required=True)
	pnl = get_season_pnl(season, filters.get("tour") or None)
	data = get_data(pnl)
	return get_columns(), data, _warnings_message(pnl), get_chart(pnl), get_report_summary(pnl)


def get_columns() -> list[dict]:
	money = {"fieldtype": "Currency", "options": "currency", "width": 125}
	return [
		{"label": _("Tur"), "fieldname": "tour", "fieldtype": "Data", "width": 260},
		{"label": _("Kişi"), "fieldname": "kisi_sayisi", "fieldtype": "Int", "width": 70},
		{"label": _("Brüt Satış"), "fieldname": "brut_satis", **money},
		{"label": _("Komisyon"), "fieldname": "komisyon", **money},
		{"label": _("Net Satış"), "fieldname": "net_satis", **money},
		{"label": _("Yolcu Maliyeti"), "fieldname": "yolcu_maliyeti", **money},
		{"label": _("Tur Ekstra Gider"), "fieldname": "tur_ekstra_gider", **money},
		{"label": _("Toplam Maliyet"), "fieldname": "toplam_maliyet", **money},
		{"label": _("Tur Kârı"), "fieldname": "tur_kari", **money},
		{"label": _("Tahsil Edilen"), "fieldname": "tahsil_edilen", **money},
		{"label": _("Açık Alacak"), "fieldname": "acik_alacak", **money},
		{"label": _("Excel'e Göre Ödenen"), "fieldname": "excel_bildirilen", **money},
		{"label": _("Detay Kişi"), "fieldname": "detay_kisi", "fieldtype": "Int", "width": 90},
		{"label": _("Detay Tutar"), "fieldname": "detay_tutar", **money},
		{"label": _("Currency"), "fieldname": "currency", "fieldtype": "Link", "options": "Currency", "hidden": 1},
		{"label": _("Tour Key"), "fieldname": "tour_key", "fieldtype": "Data", "hidden": 1},
		{"label": _("Parent"), "fieldname": "parent_tour_key", "fieldtype": "Data", "hidden": 1},
		{"label": _("Row Kind"), "fieldname": "row_kind", "fieldtype": "Data", "hidden": 1},
	]


TOUR_COLUMNS = (
	"kisi_sayisi", "brut_satis", "komisyon", "net_satis", "yolcu_maliyeti", "tur_ekstra_gider",
	"toplam_maliyet", "tur_kari", "tahsil_edilen", "acik_alacak", "excel_bildirilen",
)


def _cost_type_labels() -> dict[str, str]:
	return {
		row["name"]: row.get("cost_type_name") or row["name"]
		for row in frappe.get_all("Cost Type", fields=["name", "cost_type_name"], limit_page_length=0)
	}


def get_data(pnl: dict) -> list[dict]:
	labels = _cost_type_labels()
	data: list[dict] = []
	for tour in pnl["tours"]:
		key = tour["tour"]
		data.append({
			"tour": tour["label"],
			"tour_key": key,
			"parent_tour_key": "",
			"row_kind": "tour",
			"indent": INDENT_TOUR,
			"currency": DEFAULT_CURRENCY,
			**{column: tour[column] for column in TOUR_COLUMNS},
		})
		data.append(_section(key, "status", _("Statü Analizi (net etki)")))
		for status_name in sorted(tour["by_status"]):
			status = tour["by_status"][status_name]
			data.append(_detail(
				key, "status", status_name, status_name,
				people=status["kisi_sayisi"], amount=status["net_etki"],
			))
		data.append(_section(key, "cost", _("Maliyet Dağılımı")))
		for code, amount in tour["maliyet_by_type"].items():
			data.append(_detail(key, "cost", code, labels.get(code, code), amount=amount))
		if tour["tur_ekstra_gider"]:
			data.append(_detail(key, "cost", "TOUR_EXTRA", _("Tur Ekstra Gider"), amount=tour["tur_ekstra_gider"]))
	return data


def _section(tour_key: str, kind: str, label: str) -> dict:
	return {
		"tour": label,
		"tour_key": f"{tour_key}::section::{kind}",
		"parent_tour_key": tour_key,
		"row_kind": "section",
		"indent": INDENT_SECTION,
		"currency": DEFAULT_CURRENCY,
	}


def _detail(tour_key: str, kind: str, code: str, label: str, *, amount: float, people: int | None = None) -> dict:
	row = {
		"tour": label,
		"tour_key": f"{tour_key}::{kind}::{code}",
		"parent_tour_key": f"{tour_key}::section::{kind}",
		"row_kind": kind,
		"indent": INDENT_DETAIL,
		"detay_tutar": flt(amount, 2),
		"currency": DEFAULT_CURRENCY,
	}
	if people is not None:
		row["detay_kisi"] = people
	return row


def get_chart(pnl: dict) -> dict:
	rows = pnl["tours"][:20]
	return {
		"data": {
			"labels": [row["label"] for row in rows],
			"datasets": [
				{"name": _("Net Satış"), "values": [row["net_satis"] for row in rows]},
				{"name": _("Toplam Maliyet"), "values": [row["toplam_maliyet"] for row in rows]},
				{"name": _("Tur Kârı"), "values": [row["tur_kari"] for row in rows]},
			],
		},
		"type": "bar",
	}


def get_report_summary(pnl: dict) -> list[dict]:
	totals = pnl["totals"]

	def card(value, label, indicator):
		return {"value": value, "label": label, "datatype": "Currency", "currency": DEFAULT_CURRENCY, "indicator": indicator}

	cards = [
		card(totals["net_satis"], _("Net Satış"), "Blue"),
		card(totals["toplam_maliyet"], _("Toplam Maliyet"), "Orange"),
		card(totals["tur_kari"], _("Tur Kârı"), "Green" if totals["tur_kari"] >= 0 else "Red"),
		card(totals["tahsil_edilen"], _("Tahsil Edilen"), "Green"),
		card(totals["acik_alacak"], _("Açık Alacak"), "Orange"),
	]
	if pnl.get("genel_gider") is not None:
		cards.append(card(pnl["genel_gider"], _("Ofis Genel Gideri"), "Grey"))
		result = pnl["sezon_sonucu"]
		cards.append(card(result, _("Sezon Sonucu"), "Green" if result >= 0 else "Red"))
	return cards


def _warnings_message(pnl: dict) -> str | None:
	if not pnl["warnings"]:
		return None
	items = "".join(
		f"<li><b>{escape_html(str(w['count']))}</b> {escape_html(_('rezervasyon'))}: {escape_html(w['message'])}"
		+ (f" ({escape_html(', '.join(f'{k}: {v}' for k, v in w['details'].items()))})" if w["details"] else "")
		+ "</li>"
		for w in pnl["warnings"]
	)
	return f"<div class='alert alert-warning'><ul style='margin:0'>{items}</ul></div>"
