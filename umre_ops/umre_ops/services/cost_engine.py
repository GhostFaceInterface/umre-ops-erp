# Copyright (c) 2026, Sermed Turizm and contributors
# For license information, please see license.txt
"""
Component-based cost engine.

Public surface
==============
* ``CANONICAL_TYPES``                                        — system-managed type codes
* ``compute_cost(booking)``                                  — sum of component amounts
* ``get_cost_components(booking)``                           — raw component list
* ``cost_breakdown(booking)``                                — dict(cost_type_code -> total)
* ``generate_components(booking, *, replace_system_generated=False)``
                                                              — idempotent insert
* ``recompute_components(booking)``                          — alias with replace=True
* ``assert_components_valid(booking)``                       — integrity guard
* ``ensure_canonical_cost_types()``                          — seed master rows
* ``sync_tour_diyanet_rule_currencies_from_tour()``         — fix rule `para_birimi` vs tour
* ``recompute_tour_bookings(tour)``                        — full replace + per-booking commit

Design rules
------------
* Components are persisted ``Cost Component`` rows. They are the single
  source of truth for booking cost; the legacy ``otel/ucak/vize/diyanet``
  columns on ``Umre Booking`` are deprecated and not read by any service.
* Generation is **one-shot** per booking. After insert we never silently
  refresh; ``replace_system_generated=True`` is the only sanctioned path
  (called by the migration patch and an explicit ops action).
* Every component carries its own ``currency``; cross-currency sums are
  forbidden and will raise.
* All system-managed components are emitted even when their amount is 0
  (e.g. DIYANET when there is no tour rule or `tutar` is 0, OTHER when not configured) so
  the per-tour breakdown always carries the same column set.
"""
from __future__ import annotations

import re
from typing import Iterable

import frappe
from frappe import _
from frappe.utils import cint, flt

PAYING_STATUS = "UMRECI"

# Canonical, system-managed cost types (immutable order in the report).
CANONICAL_TYPES: list[dict] = [
	{"code": "HOTEL",   "name": "Otel Maliyeti",    "sort": 10, "is_system_managed": 1},
	{"code": "FLIGHT",  "name": "U\u00e7ak Maliyeti", "sort": 20, "is_system_managed": 1},
	{"code": "VISA",    "name": "Vize Maliyeti",    "sort": 30, "is_system_managed": 1},
	{"code": "DIYANET", "name": "Diyanet Maliyeti", "sort": 40, "is_system_managed": 1},
	{"code": "MEAL",    "name": "Yemek Maliyeti",   "sort": 50, "is_system_managed": 1},
	{"code": "OTHER",   "name": "Di\u011fer Maliyet", "sort": 60, "is_system_managed": 1},
	{"code": "MANUAL",  "name": "Manuel Maliyet",   "sort": 90, "is_system_managed": 1},
]
# Baseline per-UMRECI types; MEAL/OTHER are appended when domain rules exist.
_BASE_SYSTEM_TYPES_UMRECI: tuple[str, ...] = ("HOTEL", "FLIGHT", "VISA", "DIYANET")
# Backwards compat for code that still expects a constant tuple of all six:
SYSTEM_TYPES_FOR_UMRECI: tuple[str, ...] = _BASE_SYSTEM_TYPES_UMRECI + ("MEAL", "OTHER")
SYSTEM_TYPES_FOR_NON_UMRECI: tuple[str, ...] = ("MANUAL",)


# ---------------------------------------------------------------------------
# Master seeding
# ---------------------------------------------------------------------------

def ensure_canonical_cost_types() -> None:
	"""Idempotently materialize the canonical Cost Type master rows."""
	for spec in CANONICAL_TYPES:
		code = spec["code"]
		if frappe.db.exists("Cost Type", code):
			# Keep system flags and sort_order in sync if drifted.
			frappe.db.set_value(
				"Cost Type",
				code,
				{
					"cost_type_name": spec["name"],
					"is_system_managed": spec["is_system_managed"],
					"sort_order": spec["sort"],
					"default_currency": "USD",
					"is_revenue_negating": 1,
				},
				update_modified=False,
			)
			continue
		doc = frappe.get_doc({
			"doctype": "Cost Type",
			"cost_type_code": code,
			"cost_type_name": spec["name"],
			"is_system_managed": spec["is_system_managed"],
			"is_revenue_negating": 1,
			"default_currency": "USD",
			"sort_order": spec["sort"],
			"description": "Canonical system-managed cost type.",
		})
		doc.insert(ignore_permissions=True)


# ---------------------------------------------------------------------------
# Pure tour lookups (used by the meal / other-cost generators)
# ---------------------------------------------------------------------------

def _parse_oda_index(oda_tipi: str | None) -> int:
	if not oda_tipi:
		return 1
	m = re.match(r"^(\d+)", str(oda_tipi).strip())
	if m:
		return min(max(int(m.group(1)), 1), 4)
	return 1


def _hotel_field_for_oda(idx: int) -> str:
	return {
		1: "bir_kisilik_oda_maaliyeti",
		2: "iki_kisilik_oda_maliyeti",
		3: "uc_kisilik_oda_maliyeti",
		4: "dort_kisilik_oda_maliyeti",
	}[idx]


def _hotel_total(tur: str | None, oda_tipi: str | None) -> float:
	if not tur:
		return 0.0
	idx = _parse_oda_index(oda_tipi)
	field = _hotel_field_for_oda(idx)
	rules = frappe.get_all("Tour Hotel Cost Rule", filters={"tur": tur}, pluck="name")
	total = 0.0
	for rname in rules:
		row = frappe.db.get_value("Tour Hotel Cost Rule", rname, [field], as_dict=True)
		if row and row.get(field) is not None:
			total += flt(row[field])
	return flt(total)


def _flight_total(tur: str | None, yolcu_tipi: str | None) -> float:
	if not (tur and yolcu_tipi):
		return 0.0
	name = frappe.db.get_value(
		"Tour Airfare Cost Rule",
		{"tur": tur, "yolcu_tipi": yolcu_tipi},
		"name",
	)
	if not name:
		return 0.0
	return flt(frappe.db.get_value("Tour Airfare Cost Rule", name, "tutar") or 0)


def _visa_total(tur: str | None, vize_tipi: str | None) -> float:
	if not (tur and vize_tipi):
		return 0.0
	name = frappe.db.get_value(
		"Tour Visa Cost Rule",
		{"tur": tur, "vize_tipi": vize_tipi},
		"name",
	)
	if not name:
		return 0.0
	return flt(frappe.db.get_value("Tour Visa Cost Rule", name, "tutar") or 0)


def _diyanet_rule_row(tur: str | None) -> dict | None:
	"""Single `Tour Diyanet Card Rule` row for this tour (Umre Tour name = `tur` link)."""
	if not tur:
		return None
	name = frappe.db.get_value("Tour Diyanet Card Rule", {"tur": tur}, "name")
	if not name:
		return None
	return frappe.db.get_value(
		"Tour Diyanet Card Rule",
		name,
		["tutar", "para_birimi"],
		as_dict=True,
	)


def diyanet_rule_tutar_for_tour(tur: str | None) -> float:
	"""Published expected per-UMRECI Diyanet amount from the tour rule (0 if none)."""
	row = _diyanet_rule_row(tur)
	if not row:
		return 0.0
	return flt(row.get("tutar") or 0)


def _diyanet_for_umreci(
	tour_name: str | None,
	tour_currency: str,
) -> tuple[float, str, str | None]:
	"""Per-UMRECI Diyanet: `Tour Diyanet Card Rule` only. Never use ``diyanet_kart_var`` here.

	Component currency is always ``tour_currency`` (one currency per booking). If the
	rule’s ``para_birimi`` differs, we do **not** throw — we log it in **notes** so a
	line is still created (avoids zero DIYANET on currency mismatch in production).
	"""
	row = _diyanet_rule_row(tour_name)
	if not row:
		return 0.0, str(_("Diyanet kuralı yok")), None
	amt = flt(row.get("tutar") or 0)
	rule_curr = (row.get("para_birimi") or "").strip() or None
	notes: list[str] = [f"tour_diyanet_card_rule tutar={amt}"]
	if rule_curr and tour_currency and rule_curr != tour_currency:
		notes.append(
			_("Kural `para_birimi` = {0}, tur = {1} — bilet tutarı aynı sayı, para birimi tur ile.").format(
				rule_curr, tour_currency
			)
		)
	if amt <= 0:
		return 0.0, str(_("Diyanet kuralı: tutar 0")), " ".join(notes) if notes else None
	return flt(round(amt, 2)), str(_("Diyanet (Tour Diyanet Card Rule)")), " ".join(notes)


# ---------------------------------------------------------------------------
# Domain rules: Hotel / Meal / Other Cost Rule
# ---------------------------------------------------------------------------

def meal_cost_rule_exists(tour: str | None) -> bool:
	if not tour:
		return False
	if not frappe.db.exists("DocType", "Meal Cost Rule"):
		return False
	return bool(frappe.db.exists("Meal Cost Rule", {"tour": tour}))


def other_cost_rule_exists(tour: str | None) -> bool:
	if not tour:
		return False
	if not frappe.db.exists("DocType", "Other Cost Rule"):
		return False
	return bool(frappe.db.exists("Other Cost Rule", {"tour": tour}))


def _hotel_nights(tour: str | None) -> tuple[int, int]:
	"""Mekke / Medine nights from the persisted hotel rule rows."""
	if not tour:
		return 0, 0
	rows = frappe.get_all(
		"Tour Hotel Cost Rule",
		filters={"tur": tour, "lokasyon": ["in", ["Mekke", "Medine"]]},
		fields=["lokasyon", "gece_sayisi"],
		limit_page_length=0,
	)
	totals = {"Mekke": 0, "Medine": 0}
	for row in rows:
		totals[row["lokasyon"]] += cint(row.get("gece_sayisi"))
	return totals["Mekke"], totals["Medine"]


def _meal_per_person_usd(tour: str) -> tuple[float, str]:
	"""Per-UMRECI yemek (tour para birimi / booking currency).

	``(mekke_days * mekke_price_sar + medine_days * medine_price_sar) / rate``
	"""
	if not meal_cost_rule_exists(tour):
		return 0.0, "no meal cost rule"
	mekke_days, medine_days = _hotel_nights(tour)
	mr_name = frappe.db.get_value("Meal Cost Rule", {"tour": tour}, "name")
	if not mr_name:
		return 0.0, "no meal cost rule"
	mr = frappe.get_doc("Meal Cost Rule", mr_name)
	mp = flt(mr.mekke_price_sar)
	mdp = flt(mr.medine_price_sar)
	rate = flt(mr.sar_to_usd_rate)
	sar_portion = mekke_days * mp + medine_days * mdp
	if sar_portion > 0 and rate <= 0:
		frappe.throw(
			_("Meal Cost Rule (tour {0}): yemek SAR toplamı var ancak `sar_to_usd_rate` 0. "
			  "Kuru tanımlayın veya fiyat/gün değerlerini sıfırlayın.").format(tour)
		)
	if rate <= 0 and sar_portion == 0:
		return 0.0, "meal rule: zero days or prices"
	usd = flt(sar_portion / rate) if rate else 0.0
	desc = (
		f"({mekke_days}d M x {mp:.2f} SAR + {medine_days}d Med x {mdp:.2f} SAR) / {rate:.4f}"
		if (mekke_days or medine_days)
		else f"meal rule: SAR={sar_portion:.2f} / {rate:.4f}"
	)
	return flt(round(usd, 2)), desc


def _other_per_person(tour: str) -> float:
	if not other_cost_rule_exists(tour):
		return 0.0
	rname = frappe.db.get_value("Other Cost Rule", {"tour": tour}, "name")
	if not rname:
		return 0.0
	return flt(frappe.db.get_value("Other Cost Rule", rname, "per_person_cost") or 0)


def required_system_types_for_booking(
	tour: str | None, statu: str, cost_policy: str | None = None
) -> tuple[str, ...]:
	"""Dynamically required *system* component types (MEAL/OTHER if rules exist)."""
	if (statu or "").strip() != PAYING_STATUS and cost_policy != "System Rules":
		return SYSTEM_TYPES_FOR_NON_UMRECI
	req: list[str] = list(_BASE_SYSTEM_TYPES_UMRECI)
	if tour and meal_cost_rule_exists(tour):
		req.append("MEAL")
	if tour and other_cost_rule_exists(tour):
		req.append("OTHER")
	return tuple(req)


# ---------------------------------------------------------------------------
# Component access
# ---------------------------------------------------------------------------

def _booking_currency(booking) -> str:
	"""Operational costs are canonical USD; rules carrying SAR are converted first."""
	return "USD"


def get_cost_components(booking) -> list[dict]:
	booking_name = booking if isinstance(booking, str) else (
		booking.get("name") if isinstance(booking, dict) else getattr(booking, "name", None)
	)
	if not booking_name:
		return []
	return frappe.get_all(
		"Cost Component",
		filters={"booking": booking_name},
		fields=["name", "cost_type", "description", "quantity", "unit_price",
		        "amount", "currency", "is_system_generated", "source"],
		order_by="cost_type asc, creation asc",
	)


def compute_cost(booking) -> float:
	"""Sum of all component amounts. Refuses to mix currencies silently."""
	comps = get_cost_components(booking)
	if not comps:
		return 0.0
	currencies = {c["currency"] for c in comps if c.get("currency")}
	if len(currencies) > 1:
		frappe.throw(
			_("Booking {0} has cost components in multiple currencies ({1}). "
			  "The cost engine refuses silent FX conversion at sum time.").format(
				booking if isinstance(booking, str) else getattr(booking, "name", "?"),
				", ".join(sorted(currencies)),
			)
		)
	return flt(sum(flt(c["amount"] or 0) for c in comps))


def cost_breakdown(booking) -> dict[str, float]:
	"""Component sums grouped by cost_type code. Includes all canonical types
	with 0 if the booking does not carry that component."""
	totals = {spec["code"]: 0.0 for spec in CANONICAL_TYPES}
	for c in get_cost_components(booking):
		ct = c["cost_type"]
		totals.setdefault(ct, 0.0)
		totals[ct] = flt(totals[ct] + flt(c["amount"] or 0))
	return totals


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def _make_component(
	*,
	booking_name: str,
	tour: str | None,
	cost_type: str,
	description: str,
	quantity: float,
	unit_price: float,
	currency: str,
	source: str,
	notes: str | None = None,
) -> str:
	"""Insert a system-generated Cost Component. Returns the new doc name."""
	amount = flt(round(flt(quantity) * flt(unit_price), 2))
	doc = frappe.get_doc({
		"doctype": "Cost Component",
		"booking": booking_name,
		"tour": tour,
		"cost_type": cost_type,
		"description": description,
		"quantity": flt(quantity),
		"unit_price": flt(unit_price),
		"amount": amount,
		"currency": currency,
		"is_system_generated": 1,
		"source": source,
		"notes": notes or None,
	})
	doc.flags.ignore_system_generated_lock = True
	doc.insert(ignore_permissions=True)
	return doc.name


def _delete_system_generated(booking_name: str) -> int:
	names = frappe.get_all(
		"Cost Component",
		filters={"booking": booking_name, "is_system_generated": 1},
		pluck="name",
	)
	for n in names:
		frappe.delete_doc("Cost Component", n, force=1, ignore_permissions=True)
	return len(names)


def generate_components(
	booking,
	*,
	replace_system_generated: bool = False,
) -> list[str]:
	"""Idempotent component generation for a single booking.

	If components already exist and ``replace_system_generated`` is False, this
	is a no-op (returns []). When True, all existing system-generated rows are
	deleted first; manually-added components are preserved.
	"""
	ensure_canonical_cost_types()

	# Resolve the booking doc so we always have the freshest field values.
	if isinstance(booking, str):
		booking_doc = frappe.get_doc("Umre Booking", booking)
	elif isinstance(booking, dict):
		booking_doc = frappe.get_doc("Umre Booking", booking["name"])
	else:
		booking_doc = booking
		if not booking_doc.name:
			frappe.throw(_("generate_components: booking must be a saved document."))

	booking_name = booking_doc.name
	tour_name = booking_doc.get("tur")

	existing = frappe.db.count(
		"Cost Component", {"booking": booking_name, "is_system_generated": 1}
	)
	if existing and not replace_system_generated:
		return []
	if replace_system_generated:
		_delete_system_generated(booking_name)

	currency = _booking_currency(booking_doc)

	statu = (booking_doc.get("statu") or PAYING_STATUS).strip() or PAYING_STATUS
	created: list[str] = []

	# New imports use the tour's system rules for every passenger status. The
	# default policy remains Legacy Manual so historical non-paying bookings keep
	# their existing MANUAL-only behavior.
	if statu == PAYING_STATUS or booking_doc.get("cost_policy") == "System Rules":
		# 1) HOTEL — sum all hotel rules for this tour at the booked oda_tipi.
		hotel = _hotel_total(tour_name, booking_doc.get("oda_tipi"))
		created.append(_make_component(
			booking_name=booking_name, tour=tour_name,
			cost_type="HOTEL",
			description=f"Otel ({booking_doc.get('oda_tipi') or '1 Kişilik'})",
			quantity=1, unit_price=hotel, currency=currency,
			source="tour_hotel_cost_rule",
		))
		# 2) FLIGHT — passenger rule for this tour + yolcu_tipi.
		flight = _flight_total(tour_name, booking_doc.get("yolcu_tipi"))
		created.append(_make_component(
			booking_name=booking_name, tour=tour_name,
			cost_type="FLIGHT",
			description=f"Uçak ({booking_doc.get('yolcu_tipi') or '?'})",
			quantity=1, unit_price=flight, currency=currency,
			source="tour_airfare_cost_rule",
		))
		# 3) VISA — visa rule for this tour + vize_tipi.
		visa = _visa_total(tour_name, booking_doc.get("vize_tipi"))
		created.append(_make_component(
			booking_name=booking_name, tour=tour_name,
			cost_type="VISA",
			description=f"Vize ({booking_doc.get('vize_tipi') or '?'})",
			quantity=1, unit_price=visa, currency=currency,
			source="tour_visa_cost_rule",
		))
		# 4) DIYANET — `Tour Diyanet Card Rule` (never `diyanet_kart_var`).
		diy, _diy_desc, diy_notes = _diyanet_for_umreci(tour_name, currency)
		created.append(_make_component(
			booking_name=booking_name, tour=tour_name,
			cost_type="DIYANET",
			description=str(_diy_desc),
			quantity=1, unit_price=diy, currency=currency,
			source="tour_diyanet_card_rule",
			notes=diy_notes or None,
		))
		# 5) MEAL — Hotel Mekke/Medine nights + `Meal Cost Rule`.
		if tour_name and meal_cost_rule_exists(tour_name):
			meal_amount, meal_desc = _meal_per_person_usd(tour_name)
			mk_d, md_d = _hotel_nights(tour_name)
			# Kişi başı: qty=1, unit_price=per-UMRECI toplam (tüm operasyonel günler).
			created.append(_make_component(
				booking_name=booking_name, tour=tour_name,
				cost_type="MEAL",
				description=f"Yemek {meal_desc}",
				quantity=1, unit_price=meal_amount, currency=currency,
				source="meal_cost_rule+tour_hotel_cost_rule",
				notes=f"domain: mekke_days={mk_d} medine_days={md_d}",
			))
		# 6) OTHER — `Other Cost Rule` (kişi başı, tek bileşen satırı).
		if tour_name and other_cost_rule_exists(tour_name):
			other = _other_per_person(tour_name)
			created.append(_make_component(
				booking_name=booking_name, tour=tour_name,
				cost_type="OTHER",
				description="Diğer (kişi başı, Other Cost Rule)",
				quantity=1, unit_price=other, currency=currency,
				source="other_cost_rule",
			))
	else:
		# Non-UMRECI: a single MANUAL component carrying `manual_cost`.
		manual = flt(booking_doc.get("manual_cost") or 0)
		if manual <= 0:
			frappe.throw(
				_("Booking {0} has statu {1} but `manual_cost` is 0. "
				  "Non-UMRECI bookings MUST carry a positive manual cost.").format(
					booking_name, statu
				)
			)
		created.append(_make_component(
			booking_name=booking_name, tour=tour_name,
			cost_type="MANUAL",
			description=f"Manuel maliyet ({statu})",
			quantity=1, unit_price=manual, currency=currency,
			source="umre_booking.manual_cost",
		))

	return created


def recompute_components(booking, *, skip_dashboard_publish: bool = False) -> list[str]:
	"""Explicit refresh: deletes existing system-generated rows and rebuilds."""
	created = generate_components(booking, replace_system_generated=True)
	if not skip_dashboard_publish:
		# Nudge any open Umre Operasyon Paneli even when components are unchanged.
		try:
			from umre_ops.umre_ops.services.dashboard_service import publish_dashboard_dirty
			name = booking if isinstance(booking, str) else getattr(booking, "name", None)
			tour = frappe.db.get_value("Umre Booking", name, "tur") if name else None
			publish_dashboard_dirty(tour)
		except Exception:
			frappe.log_error(title="dashboard publish failed (recompute)")
	return created


def schedule_recompute_for_tour(tour: str | None) -> None:
	"""Event-driven: enqueue full tour recompute after the current commit."""
	if not (tour or "").strip():
		return
	tour = tour.strip()
	frappe.enqueue(
		"umre_ops.umre_ops.services.cost_engine.recompute_tour_bookings",
		queue="default",
		tour=tour,
		enqueue_after_commit=True,
		job_name=f"recompute_tour:{tour}",
	)


def sync_tour_diyanet_rule_currencies_from_tour(*, commit: bool = True) -> dict:
	"""Align `Tour Diyanet Card Rule.para_birimi` with the linked `Umre Tour` currency.

	Rule rows may default to USD; aligning them avoids inconsistent ``para_birimi`` vs
	the tour. :func:`_diyanet_for_umreci` still emits a line if currencies differ, but
	keeping rules aligned is recommended.
	"""
	if not frappe.db.exists("DocType", "Tour Diyanet Card Rule"):
		return {"updated": 0, "rules_seen": 0}
	rules = frappe.get_all("Tour Diyanet Card Rule", fields=["name", "tur", "para_birimi"], limit_page_length=0)
	updated = 0
	for r in rules:
		if not r.get("tur"):
			continue
		tcurr = frappe.db.get_value("Umre Tour", r["tur"], "para_birimi")
		if not tcurr or (r.get("para_birimi") or "") == tcurr:
			continue
		frappe.db.set_value("Tour Diyanet Card Rule", r["name"], "para_birimi", tcurr)
		updated += 1
	if commit:
		frappe.db.commit()
	return {"updated": updated, "rules_seen": len(rules)}


def recompute_tour_bookings(tour: str) -> dict:
	"""Recompute system-generated `Cost Component` rows for every booking on this tour.

	Deletes *all* system-generated lines per booking, then rebuilds HOTEL, FLIGHT,
	VISA, DIYANET, and MEAL/OTHER when the domain rules exist.

	Invoked from RQ (after cost-rule saves), migration patches, and
	:func:`recompute_tour_from_desk` (whitelisted). Commits after each successful
	booking so one failure does not roll back the whole tour. Emits a single dashboard
	``dirty`` at the end to avoid N realtime storms.
	"""
	tour = (tour or "").strip()
	if not tour or not frappe.db.exists("Umre Tour", tour):
		return {"tour": tour, "bookings": 0, "ok": 0, "recomputed": 0, "errors": []}
	names = frappe.get_all(
		"Umre Booking", filters={"tur": tour}, pluck="name", order_by="creation asc"
	)
	errors: list[dict] = []
	skipped_posted: list[str] = []
	for name in names:
		try:
			if not _lock_booking_for_recompute(name):
				continue
			if _has_submitted_cost_posting(name):
				skipped_posted.append(name)
				frappe.db.commit()
				continue
			recompute_components(name, skip_dashboard_publish=True)
			frappe.db.commit()
		except Exception as exc:  # noqa: BLE001 — tour batch: collect and continue
			frappe.db.rollback()
			errors.append({"booking": name, "error": str(exc)})
			frappe.log_error(
				message=frappe.get_traceback(),
				title=f"recompute_tour_bookings: tour={tour!r} booking={name!r}",
			)
	try:
		from umre_ops.umre_ops.services.dashboard_service import publish_dashboard_dirty

		publish_dashboard_dirty(tour)
	except Exception:
		frappe.log_error(title="dashboard publish failed (recompute_for_tour)")
	ok = len(errors) == 0
	if errors:
		frappe.log_error(
			message=str(errors)[:20000],
			title=f"recompute_tour_bookings: {len(errors)} failed booking(s) on tour={tour!r}",
		)
	return {
		"tour": tour,
		"bookings": len(names),
		"recomputed": len(names) - len(errors) - len(skipped_posted),
		"skipped_posted": skipped_posted,
		"ok": 1 if ok else 0,
		"errors": errors,
	}


def _has_submitted_cost_posting(booking_name: str) -> bool:
	"""Protect the component snapshot used by a submitted cost journal entry."""
	je = frappe.db.get_value(
		"Umre Posting Event",
		{
			"operation": "BOOKING_COSTS_JE",
			"source_doctype": "Umre Booking",
			"source_name": booking_name,
			"status": "Succeeded",
		},
		"result_name",
	)
	return bool(je and frappe.db.get_value("Journal Entry", je, "docstatus") == 1)


def _lock_booking_for_recompute(booking_name: str) -> bool:
	"""Serialize component replacement with accounting posting for this booking."""
	return bool(
		frappe.db.sql(
			"SELECT name FROM `tabUmre Booking` WHERE name = %s FOR UPDATE",
			(booking_name,),
		)
	)


@frappe.whitelist()
def sync_diyanet_rule_currencies_from_desk() -> dict:
	"""Set each `Tour Diyanet Card Rule` `para_birimi` to the linked `Umre Tour` currency (USD→try fix)."""
	_roles = set(frappe.get_roles())
	if frappe.session.user != "Administrator" and "System Manager" not in _roles:
		frappe.throw(_("Not permitted."))
	return sync_tour_diyanet_rule_currencies_from_tour(commit=True)


@frappe.whitelist()
def recompute_components_for_tour(tour: str) -> dict:
	"""Synchronous, explicit recompute of every booking for a tour (ops / desk)."""
	tour = (tour or "").strip()
	if not tour:
		frappe.throw(_("tour is required."))
	roles = set(frappe.get_roles())
	if frappe.session.user != "Administrator" and "System Manager" not in roles:
		frappe.throw(_("Not permitted to recompute tour costs."), frappe.PermissionError)
	if not frappe.has_permission("Umre Tour", "write", doc=tour):
		frappe.throw(_("Not permitted to recompute costs for tour {0}").format(tour))
	booking_names = frappe.get_all("Umre Booking", filters={"tur": tour}, pluck="name")
	unauthorized = [
		name for name in booking_names
		if not frappe.has_permission("Umre Booking", "write", doc=name)
	]
	if unauthorized:
		frappe.throw(
			_("Not permitted to recompute one or more bookings in this tour."),
			frappe.PermissionError,
		)
	return recompute_tour_bookings(tour)


@frappe.whitelist()
def recompute_components_for_booking(booking_name: str) -> dict:
	"""Whitelisted desk action: refresh components for a single booking."""
	if not frappe.has_permission("Umre Booking", "write", doc=booking_name):
		frappe.throw(_("Not permitted to recompute components for {0}").format(booking_name))
	if not _lock_booking_for_recompute(booking_name):
		frappe.throw(_("Umre Booking {0} no longer exists.").format(booking_name))
	if _has_submitted_cost_posting(booking_name):
		frappe.throw(_("Submitted booking costs cannot be recomputed for {0}.").format(booking_name))
	created = recompute_components(booking_name)
	return {"booking": booking_name, "components_created": created}


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

def assert_components_valid(booking) -> None:
	"""Hard-check: booking must have the required components for its statu."""
	booking_name = booking if isinstance(booking, str) else getattr(booking, "name", None)
	if not booking_name:
		return
	statu_value = (
		booking
		if not isinstance(booking, str)
		else None
	)
	statu = (
		(getattr(statu_value, "statu", None) if statu_value is not None else None)
		or frappe.db.get_value("Umre Booking", booking_name, "statu")
		or PAYING_STATUS
	)
	db_values = frappe.db.get_value("Umre Booking", booking_name, ["tur", "cost_policy"], as_dict=True) or {}
	required: Iterable[str] = required_system_types_for_booking(
		db_values.get("tur"), statu, db_values.get("cost_policy")
	)

	present = {
		c["cost_type"]
		for c in frappe.get_all(
			"Cost Component",
			filters={"booking": booking_name, "is_system_generated": 1},
			fields=["cost_type"],
		)
	}
	missing = [t for t in required if t not in present]
	if missing:
		frappe.throw(
			_("Booking {0} is missing required cost components: {1}").format(
				booking_name, ", ".join(missing)
			)
		)
	# No negative components.
	bad = frappe.db.sql(
		"SELECT name, cost_type, amount FROM `tabCost Component` WHERE booking=%s AND amount < 0",
		(booking_name,),
		as_dict=True,
	)
	if bad:
		frappe.throw(
			_("Booking {0} has negative cost components: {1}").format(
				booking_name, ", ".join(f"{b['name']}={b['amount']}" for b in bad)
			)
		)
