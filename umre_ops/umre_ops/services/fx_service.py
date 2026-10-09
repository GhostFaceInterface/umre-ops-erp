# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
"""
Single source of exchange rates for Umre Ops.

Every rate in this app is expressed as **units of foreign currency per 1 USD**
(e.g. SAR 3.75, TRY 41.2) and converts with ``usd = amount / rate``.

Sources, in order (all built into ERPNext):

1. ``Pegged Currencies`` (Accounts) — SAR is pegged to USD at 3.75 by ERPNext's
   installer. The table is read directly because ERPNext's pegged shortcut in
   ``get_exchange_rate`` returns the ratio for both directions.
2. ``Currency Exchange`` records (USD → currency) dated on or shortly before the day.
3. ``erpnext.setup.utils.get_exchange_rate`` — the free frankfurter.dev (ECB)
   service configured in ``Currency Exchange Settings``. A fetched rate is
   stored as a ``Currency Exchange`` record so it stays auditable offline.
"""
from __future__ import annotations

import frappe
from frappe import _
from frappe.utils import add_days, flt, getdate, nowdate

BASE_CURRENCY = "USD"
# SAR has been officially pegged at 3.75 per USD since 1986.
SAR_OFFICIAL_PEG = 3.75
SAR_RANGE = (3.70, 3.80)
STORED_RATE_MAX_AGE_DAYS = 7
MANUAL_RATE_TOLERANCE = 0.10

SOURCE_BASE = "USD"
SOURCE_PEGGED = "Sabit kur (Pegged Currencies)"
SOURCE_STORED = "Currency Exchange"
SOURCE_FETCHED = "Otomatik (ERPNext kur servisi)"
SOURCE_MANUAL = "Manuel"


def _pegged_rate(currency: str) -> float | None:
	if not frappe.db.exists("DocType", "Pegged Currency Details"):
		return None
	value = frappe.db.get_value(
		"Pegged Currency Details",
		{"parent": "Pegged Currencies", "source_currency": currency, "pegged_against": BASE_CURRENCY},
		"pegged_exchange_rate",
	)
	return flt(value) or None


def _stored_rate(currency: str, on_date) -> float | None:
	rows = frappe.get_all(
		"Currency Exchange",
		filters=[
			["from_currency", "=", BASE_CURRENCY],
			["to_currency", "=", currency],
			["date", "<=", on_date],
			["date", ">=", add_days(on_date, -STORED_RATE_MAX_AGE_DAYS)],
		],
		fields=["exchange_rate"],
		order_by="date desc",
		limit=1,
	)
	return flt(rows[0]["exchange_rate"]) if rows else None


def _store_rate(currency: str, on_date, rate: float) -> None:
	if frappe.db.exists(
		"Currency Exchange",
		{"from_currency": BASE_CURRENCY, "to_currency": currency, "date": on_date},
	):
		return
	frappe.get_doc({
		"doctype": "Currency Exchange",
		"date": on_date,
		"from_currency": BASE_CURRENCY,
		"to_currency": currency,
		"exchange_rate": rate,
		"for_buying": 1,
		"for_selling": 1,
	}).insert(ignore_permissions=True)


def _fetch_rate(currency: str, on_date) -> float | None:
	from erpnext.setup.utils import get_exchange_rate

	return flt(get_exchange_rate(BASE_CURRENCY, currency, str(on_date))) or None


def _check_sar(rate: float) -> float:
	if not SAR_RANGE[0] <= rate <= SAR_RANGE[1]:
		frappe.throw(
			_("SAR kuru {0} beklenen aralıkta değil ({1}–{2} SAR / USD).").format(rate, *SAR_RANGE)
		)
	return rate


def usd_rate(currency: str | None, on_date=None) -> tuple[float, str]:
	"""Return ``(units of currency per 1 USD, source)`` for ``on_date``."""
	currency = (currency or "").strip().upper()
	if not currency or currency == BASE_CURRENCY:
		return 1.0, SOURCE_BASE
	on_date = getdate(on_date or nowdate())

	pegged = _pegged_rate(currency)
	if pegged:
		return (_check_sar(pegged) if currency == "SAR" else pegged), SOURCE_PEGGED

	stored = _stored_rate(currency, on_date)
	if stored:
		return stored, SOURCE_STORED

	fetched = None
	try:
		fetched = _fetch_rate(currency, on_date)
	except Exception:
		frappe.log_error(title=f"Umre Ops kur alınamadı: USD→{currency} {on_date}")
	if fetched:
		_store_rate(currency, on_date, fetched)
		return fetched, SOURCE_FETCHED

	if currency == "SAR":
		return SAR_OFFICIAL_PEG, SOURCE_PEGGED
	frappe.throw(
		_(
			"USD→{0} kuru {1} tarihi için bulunamadı. İnternet bağlantısını kontrol edin veya "
			"Currency Exchange kaydı girin."
		).format(currency, on_date)
	)


def validate_rate(currency: str | None, rate: float, on_date=None) -> str:
	"""Validate a rate typed by a user and return its source label.

	Rejects non-positive rates, SAR outside its peg band and rates that deviate
	more than 10% from the reference rate (typically an inverted rate such as
	0.024 instead of 41.2 TRY per USD).
	"""
	currency = (currency or "").strip().upper()
	rate = flt(rate)
	if not currency or currency == BASE_CURRENCY:
		return SOURCE_BASE
	if rate <= 0:
		frappe.throw(_("{0} kuru pozitif olmalıdır (1 USD karşılığı {0}).").format(currency))
	if currency == "SAR":
		_check_sar(rate)
	try:
		reference, _source = usd_rate(currency, on_date)
	except frappe.ValidationError:
		return SOURCE_MANUAL
	if abs(rate - reference) <= 1e-9:
		return _source
	if abs(rate - reference) / reference > MANUAL_RATE_TOLERANCE:
		frappe.throw(
			_(
				"{0} kuru {1}, referans kurdan ({2}) %10'dan fazla sapıyor. Kur 1 USD karşılığı "
				"{0} olarak girilmelidir; ters kur girmiş olabilirsiniz."
			).format(currency, rate, flt(reference, 4))
		)
	return SOURCE_MANUAL


def fill_rate(doc, *, currency: str | None, rate_field: str, on_date, source_field: str = "kur_kaynagi") -> None:
	"""Fill ``doc[rate_field]`` automatically when empty, else validate the typed rate."""
	if flt(doc.get(rate_field)) > 0:
		source = validate_rate(currency, doc.get(rate_field), on_date)
	else:
		rate, source = usd_rate(currency, on_date)
		doc.set(rate_field, rate)
	if doc.meta.has_field(source_field):
		doc.set(source_field, source)


@frappe.whitelist()
def get_usd_rate(currency: str, on_date: str | None = None) -> dict:
	"""Desk helper: the automatic rate a form would use (units of currency per 1 USD)."""
	if not frappe.has_permission("Currency Exchange", "read", throw=False) and not frappe.has_permission(
		"Operational Expense", "read", throw=False
	):
		frappe.throw(_("Kur bilgisini görme yetkiniz yok."), frappe.PermissionError)
	rate, source = usd_rate(currency, on_date)
	return {"currency": (currency or "").upper(), "rate": rate, "source": source}
